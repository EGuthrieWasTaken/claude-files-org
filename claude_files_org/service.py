"""The org service: file access, locking, dry runs, diffs. Independent of the MCP layer.

``store`` is anything with ``read(path) -> bytes | None`` and ``write(path, data: bytes)``, where ``path``
is relative to the served folder. In production it is the host's path-contained ``Vault``.
"""
import hashlib
import threading

from . import batch, edits, query
from . import timestamps as T
from .model import OrgError, parse


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _decode(data):
    return data.decode("utf-8", "surrogateescape")


def _encode(text):
    return text.encode("utf-8", "surrogateescape")


class OrgService:
    def __init__(self, cfg, store, log=None):
        self.cfg = cfg
        self.store = store
        self.log = log
        self._locks = {}
        self._locks_guard = threading.Lock()

    # -- files ------------------------------------------------------------
    def resolve_file(self, file=None):
        if file is None or not str(file).strip():
            return self.cfg.files[0]
        rel = str(file).strip().replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if rel not in self.cfg.files:
            raise OrgError("file_not_allowed", f"{file!r} is not an org file these tools edit. "
                           f"Allowed files: {list(self.cfg.files)}")
        return rel

    def _lock(self, rel):
        with self._locks_guard:
            return self._locks.setdefault(rel, threading.Lock())

    def _read(self, rel):
        data = self.store.read(rel)
        if data is None:
            raise OrgError("not_found", f"{rel} does not exist in the served folder")
        return data

    def load(self, rel):
        data = self._read(rel)
        return parse(_decode(data), self.cfg, rel.rsplit("/", 1)[-1]), data

    # -- reads --------------------------------------------------------------
    def list_items(self, file=None, limit=None, **filters):
        rel = self.resolve_file(file)
        doc, _ = self.load(rel)
        out = query.list_items(doc, T.today(self.cfg.tz), limit=limit, **filters)
        out["file"] = rel
        return out

    def get_item(self, item_id, file=None):
        rel = self.resolve_file(file)
        doc, _ = self.load(rel)
        out = query.get_item(doc, item_id)
        out["file"] = rel
        return out

    def lint(self, file=None):
        rel = self.resolve_file(file)
        doc, _ = self.load(rel)
        problems = query.lint(doc)
        return {"file": rel, "problems": problems, "count": len(problems)}

    # -- writing ------------------------------------------------------------
    def _commit(self, changes, dry_run, label):
        """Write ``changes`` = ``[(rel, old_bytes | None, new_text), ...]`` (archive file first) or only describe them."""
        files = {}
        for rel, old, new_text in changes:
            old_text = _decode(old) if old is not None else ""
            new_raw = _encode(new_text)
            if old is not None and new_raw == old:
                continue
            files[rel] = {"diff": edits.unified_diff(old_text, new_text, rel),
                          "sha256_before": sha256(old) if old is not None else None, "sha256": sha256(new_raw),
                          "created": old is None}
        written = False
        if files and not dry_run:
            for rel, old, new_text in changes:
                if rel in files:
                    self.store.write(rel, _encode(new_text))
            written = True
            if self.log:
                self.log(f"org {label}: {sorted(files)}")
        return files, written

    # -- edits --------------------------------------------------------------
    def edit(self, edit_list, file=None, dry_run=False):
        """Apply ``edit_list`` (see :func:`batch.apply_batch`) to one file as a single write."""
        rel = self.resolve_file(file)
        with self._lock(rel):
            doc, raw = self.load(rel)
            new_text, results = batch.apply_batch(doc, edit_list)
            files, written = self._commit([(rel, raw, new_text)], dry_run, "edit " + str([r["op"] for r in results]))
            warnings = [w for r in results for w in r["warnings"]]
            return {"file": rel, "dry_run": bool(dry_run), "changed": bool(files), "written": written,
                    "results": results, "files": files,
                    "diff": "\n".join(f["diff"] for f in files.values()), "warnings": warnings}

    def edit_one(self, op, item_id, rev, file=None, dry_run=False, **args):
        spec = {"op": op, "id": item_id, "rev": rev, **args}
        try:
            out = self.edit([spec], file=file, dry_run=dry_run)
        except OrgError as e:           # a single edit is not "edit 1" of anything
            prefix = f"edit 1 ({op}): "
            extra = {k: v for k, v in e.extra.items() if k != "failed_edit"}
            raise OrgError(e.code, e.message.replace(prefix, "", 1), **extra) from None
        except ValueError as e:
            raise ValueError(str(e).replace(f"edit 1 ({op}): ", "", 1).replace("edit 1: ", "", 1)) from None
        r = out["results"][0]
        out["id"], out["rev"] = r["id"], r["rev"]
        return out

    # -- archiving ------------------------------------------------------------
    def _archive_lock(self, rel, arch):
        return [self._lock(p) for p in sorted({rel, arch})]

    def archive(self, item_id, rev, file=None, dry_run=False):
        """``org_archive``: move one closed subtree to the archive file."""
        from . import archive as A
        rel = self.resolve_file(file)
        arch = A.archive_rel(self.cfg, rel)
        locks = self._archive_lock(rel, arch)
        for lk in locks:
            lk.acquire()
        try:
            doc, raw = self.load(rel)
            item = edits.locate(doc, item_id, rev)
            old_arch = self.store.read(arch)
            res = edits.execute(doc, edits.OPS["archive"], item,
                                {"file_rel": rel, "archive_text": _decode(old_arch) if old_arch is not None else None})
            files, written = self._commit([(arch, old_arch, res.side_files[arch]), (rel, raw, res.text)], dry_run,
                                          "archive " + item.title)
            return {"file": rel, "archive_file": arch, "dry_run": bool(dry_run), "changed": bool(files),
                    "written": written, "id": item.id, "title": item.title, "files": files,
                    "diff": "\n".join(f["diff"] for f in files.values())}
        finally:
            for lk in reversed(locks):
                lk.release()

    def archive_closed(self, older_than_days=30, file=None, dry_run=False):
        """``org_archive_closed``: archive old closed items under the inbox heading."""
        from . import archive as A
        rel = self.resolve_file(file)
        arch = A.archive_rel(self.cfg, rel)
        locks = self._archive_lock(rel, arch)
        for lk in locks:
            lk.acquire()
        try:
            doc, raw = self.load(rel)
            old_arch = self.store.read(arch)
            new_text, new_arch, archived, skipped = A.plan_archive_closed(
                doc, rel, T.today(self.cfg.tz), older_than_days, _decode(old_arch) if old_arch is not None else None)
            changes = []
            if archived:
                changes = [(arch, old_arch, new_arch), (rel, raw, new_text)]
            files, written = self._commit(changes, dry_run, f"archive_closed {len(archived)} items")
            return {"file": rel, "archive_file": arch, "dry_run": bool(dry_run), "changed": bool(files),
                    "written": written, "older_than_days": older_than_days, "archived": archived,
                    "skipped": skipped, "files": files, "diff": "\n".join(f["diff"] for f in files.values())}
        finally:
            for lk in reversed(locks):
                lk.release()
