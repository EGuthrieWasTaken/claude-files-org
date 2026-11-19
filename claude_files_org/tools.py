"""MCP tool registration. No ``from __future__ import annotations`` here: the pinned MCP SDK (1.12.4)
inspects real annotations when it builds each tool's input schema."""
import json
import os
from typing import Any, Dict, List, Optional, Union

from .config import load_config
from .model import OrgError
from .service import OrgService

INSTRUCTIONS = """\
Org files (org-projects/inbox.org by default): use the org_* tools, never write_file, to change them. \
Each edit is exactly what Emacs org-mode would write, and nothing else in the file changes. \
Workflow: git_pull, then org_list_items (or org_get_item), then the edit tools, then git_commit and git_push. \
Every edit takes an item's id and the rev you last read; "stale" means the item changed since, so re-read it \
(the error carries its current state) and decide again. WAIT and CANCELLED need a note. Use dry_run to preview the \
diff, and org_batch to apply many edits to one file as a single write (all or nothing). Repeating tasks and \
structure org_lint reports must be fixed in Emacs."""

_MAX_ERROR_JSON = 6000


class VaultStore:
    """The service's file store over the host's path-contained Vault."""

    def __init__(self, vault):
        self.vault = vault

    def read(self, path):
        parts = self.vault.components(path)
        try:
            fd, _st = self.vault.open_read(parts)
        except Exception as exc:                       # PathError(404) -> missing file
            if getattr(exc, "code", None) == "not_found":
                return None
            raise
        try:
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def write(self, path, data):
        parts = self.vault.components(path)
        with self.vault.atomic_write(parts, overwrite=True, create_parents=True) as (fd, committer):
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            committer.commit(fd)


def _as_error(exc):
    """OrgError -> ValueError with the code first and, for ``stale``, the item's current state."""
    msg = f"{exc.code}: {exc.message}"
    extra = {k: v for k, v in exc.extra.items()}
    if extra:
        try:
            blob = json.dumps(extra, default=str)
            if len(blob) <= _MAX_ERROR_JSON:
                msg += "\n" + blob
        except (TypeError, ValueError):                # pragma: no cover
            pass
    return ValueError(msg)


def _brief(out):
    """Tool result for an edit: what changed, the new rev, the diff and the new sha256 of each changed file."""
    res = {"file": out["file"], "dry_run": out["dry_run"], "changed": out["changed"], "written": out["written"],
           "diff": out["diff"], "sha256": {p: f["sha256"] for p, f in out["files"].items()}}
    for key in ("id", "rev", "results", "warnings", "archive_file", "title", "archived", "skipped",
                "older_than_days"):
        if key in out and out[key] not in (None, []):
            res[key] = out[key]
    return res


def register(api):
    cfg = load_config(os.environ)
    svc = OrgService(cfg, VaultStore(api.vault), log=api.log.info)

    def run(op, fn):
        def _do():
            try:
                return fn()
            except OrgError as exc:
                raise _as_error(exc) from None
        return api.guard(op, _do)

    # -- reads -------------------------------------------------------------------------------------------

    def org_list_items(file: Optional[str] = None, state: Optional[Union[str, List[str]]] = None,
                       tags: Optional[Union[str, List[str]]] = None, scheduled_from: Optional[str] = None,
                       scheduled_to: Optional[str] = None, deadline_from: Optional[str] = None,
                       deadline_to: Optional[str] = None, overdue: bool = False, text: Optional[str] = None,
                       limit: Optional[int] = None) -> Dict[str, Any]:
        """List org items without their bodies, in file order.

        state: "open" (default), "closed", "all", or a list of keywords such as ["WAIT"]. tags: every listed
        tag must match, own or inherited; a tag group name matches its members. Dates are YYYY-MM-DD and the
        ranges are inclusive. overdue: open items scheduled or due before today (Indiana time). text:
        case-insensitive title substring. limit caps the returned items; total says how many matched.
        Each item has id and rev: pass both to the edit tools. The result also reports the active settings.
        """
        return run("org_list_items", lambda: svc.list_items(
            file=file, limit=limit, state=state, tags=tags, scheduled_from=scheduled_from,
            scheduled_to=scheduled_to, deadline_from=deadline_from, deadline_to=deadline_to,
            overdue=overdue, text=text))

    def org_get_item(id: str, file: Optional[str] = None) -> Dict[str, Any]:
        """One item in full: body, properties, parsed logbook entries and a summary of its children."""
        return run("org_get_item", lambda: svc.get_item(id, file=file))

    def org_lint(file: Optional[str] = None) -> Dict[str, Any]:
        """Report structure org cannot read (misplaced or unclosed drawers, malformed timestamps, unknown
        tags, duplicate paths, closed items with open children, invented logbook lines). Changes nothing."""
        return run("org_lint", lambda: svc.lint(file=file))

    # -- edits -------------------------------------------------------------------------------------------

    def org_set_state(id: str, rev: str, state: str, note: Optional[str] = None, file: Optional[str] = None,
                      dry_run: bool = False) -> Dict[str, Any]:
        """Change an item's TODO keyword as org does: CLOSED for done keywords, removed on reopening, a State
        logbook entry for WAIT/CANCELLED (which require a note), and the parent's [n/m] cookie refreshed."""
        return run("org_set_state", lambda: _brief(svc.edit_one(
            "set_state", id, rev, file=file, dry_run=dry_run, state=state, note=note)))

    def org_reschedule(id: str, rev: str, date: Optional[str] = None, time: Optional[str] = None,
                       remove: bool = False, note: Optional[str] = None, file: Optional[str] = None,
                       dry_run: bool = False) -> Dict[str, Any]:
        """Set, change or remove (remove=true) SCHEDULED. date is YYYY-MM-DD; time is H:MM or HH:MM-HH:MM.
        The previous date is logged as org does. Repeating timestamps are refused."""
        return run("org_reschedule", lambda: _brief(svc.edit_one(
            "reschedule", id, rev, file=file, dry_run=dry_run, date=date, time=time, remove=remove, note=note)))

    def org_set_deadline(id: str, rev: str, date: Optional[str] = None, time: Optional[str] = None,
                         remove: bool = False, note: Optional[str] = None, file: Optional[str] = None,
                         dry_run: bool = False) -> Dict[str, Any]:
        """Set, change or remove (remove=true) DEADLINE, with org's logbook entry for the previous one."""
        return run("org_set_deadline", lambda: _brief(svc.edit_one(
            "set_deadline", id, rev, file=file, dry_run=dry_run, date=date, time=time, remove=remove, note=note)))

    def org_add_note(id: str, rev: str, note: str, file: Optional[str] = None,
                     dry_run: bool = False) -> Dict[str, Any]:
        """Add a "Note taken on [now]" entry (multi-line allowed) at the top of the item's logbook."""
        return run("org_add_note", lambda: _brief(svc.edit_one(
            "add_note", id, rev, file=file, dry_run=dry_run, note=note)))

    def org_set_tags(id: str, rev: str, tags: Union[str, List[str]], file: Optional[str] = None,
                     dry_run: bool = False) -> Dict[str, Any]:
        """Replace the item's own tags (an empty list removes them), aligned at column 77 as org does.
        Only configured tags are accepted."""
        return run("org_set_tags", lambda: _brief(svc.edit_one(
            "set_tags", id, rev, file=file, dry_run=dry_run, tags=tags)))

    def org_set_effort(id: str, rev: str, value: Optional[str] = None, remove: bool = False,
                       file: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Set (value as H:MM, e.g. 0:45) or remove (remove=true) the Effort property. A value outside the
        preferred list is accepted with a warning."""
        return run("org_set_effort", lambda: _brief(svc.edit_one(
            "set_effort", id, rev, file=file, dry_run=dry_run, value=value, remove=remove)))

    def org_add_item(title: str, parent_id: Optional[str] = None, parent_rev: Optional[str] = None,
                     tags: Optional[Union[str, List[str]]] = None, scheduled: Optional[str] = None,
                     scheduled_time: Optional[str] = None, deadline: Optional[str] = None,
                     deadline_time: Optional[str] = None, effort: Optional[str] = None,
                     body: Optional[str] = None, file: Optional[str] = None,
                     dry_run: bool = False) -> Dict[str, Any]:
        """Add "TODO title" as the last child of parent_id (with its parent_rev), by default of the inbox
        heading, the way the org capture template does: CREATED property, optional tags, planning, effort
        and body. Returns the new item's id and rev."""
        args = dict(title=title, tags=tags, scheduled=scheduled, scheduled_time=scheduled_time,
                    deadline=deadline, deadline_time=deadline_time, effort=effort, body=body)
        return run("org_add_item", lambda: _brief(svc.edit_one(
            "add_item", parent_id, parent_rev, file=file, dry_run=dry_run, **args)))

    def org_batch(edits: List[Dict[str, Any]], file: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Apply several edits to one file as a single write, all or nothing. Each edit is an object with
        "op" (set_state, reschedule, set_deadline, add_note, set_tags, set_effort, add_item), the target "id"
        and "rev" as you read them, and that op's arguments, e.g. {"op": "reschedule", "id": "...", "rev":
        "...", "date": "2026-11-20"}. Revs are checked against the file as you read it, before anything is
        applied. If one edit fails, none is applied and the error names it (edit N)."""
        return run("org_batch", lambda: _brief(svc.edit(edits, file=file, dry_run=dry_run)))

    # -- archiving ---------------------------------------------------------------------------------------

    def org_archive(id: str, rev: str, file: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Move one closed item and its subtree to the archive file as org-archive-subtree does, adding the
        ARCHIVE_* properties. Refused with open_descendants or not_closed."""
        return run("org_archive", lambda: _brief(svc.archive(id, rev, file=file, dry_run=dry_run)))

    def org_archive_closed(older_than_days: int = 30, file: Optional[str] = None,
                           dry_run: bool = False) -> Dict[str, Any]:
        """Archive every closed top-level item under the inbox heading whose CLOSED date is more than
        older_than_days days ago and that has no open descendants. Lists what was archived and what was
        skipped (and why)."""
        return run("org_archive_closed", lambda: _brief(svc.archive_closed(
            older_than_days=older_than_days, file=file, dry_run=dry_run)))

    for fn in (org_list_items, org_get_item, org_lint):
        api.add_tool(fn, read_only=True)
    for fn in (org_set_state, org_reschedule, org_set_deadline, org_add_item, org_add_note, org_set_tags,
               org_set_effort, org_batch):
        api.add_tool(fn, read_only=False)
    api.add_tool(org_archive, read_only=False, destructive=True)
    api.add_tool(org_archive_closed, read_only=False, destructive=True)
    api.log.info("org tools registered for %s", ", ".join(cfg.files))
