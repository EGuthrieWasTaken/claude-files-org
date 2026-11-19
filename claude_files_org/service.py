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

    # -- edits --------------------------------------------------------------
    def edit(self, edit_list, file=None, dry_run=False):
        """Apply ``edit_list`` (see :func:`batch.apply_batch`) to one file as a single write."""
        rel = self.resolve_file(file)
        with self._lock(rel):
            doc, raw = self.load(rel)
            new_text, results = batch.apply_batch(doc, edit_list)
            changed = new_text != doc.original
            new_raw = _encode(new_text)
            files = {}
            if changed:
                files[rel] = {"diff": edits.unified_diff(doc.original, new_text, rel),
                              "sha256_before": sha256(raw), "sha256": sha256(new_raw)}
                if not dry_run:
                    self.store.write(rel, new_raw)
                    if self.log:
                        self.log(f"org edit {rel}: {[r['op'] for r in results]}")
            warnings = [w for r in results for w in r["warnings"]]
            return {"file": rel, "dry_run": bool(dry_run), "changed": changed,
                    "written": bool(changed and not dry_run), "results": results, "files": files,
                    "diff": "\n".join(f["diff"] for f in files.values()), "warnings": warnings}

    def edit_one(self, op, item_id, rev, file=None, dry_run=False, **args):
        spec = {"op": op, "id": item_id, "rev": rev, **args}
        out = self.edit([spec], file=file, dry_run=dry_run)
        r = out["results"][0]
        out["id"], out["rev"] = r["id"], r["rev"]
        return out
