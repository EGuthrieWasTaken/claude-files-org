"""Archiving closed subtrees like ``org-archive-subtree`` (org 9.6)."""
import re

from . import timestamps as T
from .edits import OpOutcome, count_cookie, now_dt
from .model import HEADLINE_RE, OrgError
from .section import Section

MODE_LINE = "#    -*- mode: org -*-\n\n"
HEADER_FORMAT = "\nArchived entries from file %s\n\n"
_CATEGORY_RE = re.compile(r"^#\+CATEGORY:[ \t]*(.*?)[ \t]*$", re.I)


def emacs_path(cfg, rel):
    """The source file as Emacs sees it: the configured Emacs root joined with its path in the folder."""
    return f"{cfg.emacs_root}/{rel}"


def archive_rel(cfg, rel):
    """``org-projects/inbox.org`` -> ``<archive dir>/inbox.org_archive``."""
    return f"{cfg.archive_dir}/{rel.rsplit('/', 1)[-1]}_archive"


def category(doc, rel):
    for line in doc.lines[:doc.preamble_end]:
        m = _CATEGORY_RE.match(line.rstrip("\r"))
        if m and m.group(1):
            return m.group(1)
    base = rel.rsplit("/", 1)[-1]
    return base[:-4] if base.endswith(".org") else base


def _shift_levels(item, own_lines, tail):
    """Re-level the headlines of ``item``'s subtree so that ``item`` becomes level 1.

    ``own_lines`` is the item's own (already edited) section, ``tail`` the lines of its descendants.
    """
    delta = item.level - 1
    if delta == 0:
        return own_lines + tail
    own, rest = list(own_lines), list(tail)

    def relevel(line, level):
        core, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
        return "*" * (level - delta) + " " + HEADLINE_RE.match(core).group(2) + cr

    own[0] = relevel(own[0], item.level)
    for it in item.descendants():
        rest[it.start - item.end] = relevel(rest[it.start - item.end], it.level)
    return own + rest


def append_entry(existing, entry_lines, source_path):
    """The archive file's new text after pasting ``entry_lines`` at its end."""
    entry = "\n".join(entry_lines) + "\n"
    if existing is None:
        return MODE_LINE + HEADER_FORMAT % source_path + "\n" + entry
    return existing + "\n" + entry


def op_archive(doc, item, sec, args):
    cfg = doc.config
    rel = args["file_rel"]
    if not item.closed:
        raise OrgError("not_closed", f"{item.title!r} is {item.keyword or 'not a TODO item'}, which is not a closed "
                       f"keyword ({list(doc.keywords.closed)}). Close it first.")
    opens = item.open_descendants()
    if opens:
        listing = [{"id": o.id, "title": o.title, "keyword": o.keyword, "line": o.line} for o in opens]
        raise OrgError("open_descendants", f"{item.title!r} still has open descendants: "
                       f"{[o['title'] for o in listing]}. Close or cancel them first.", open_descendants=listing)
    now = now_dt(cfg)
    src = emacs_path(cfg, rel)
    ctx = [("TIME", T.format_timestamp(now.date(), now.strftime("%H:%M"))[1:-1]),
           ("FILE", src),
           ("OLPATH", "/".join(item.path[:-1])),
           ("CATEGORY", category(doc, rel)),
           ("TODO", item.keyword or ""),
           ("ITAGS", " ".join(item.inherited_tags))]
    sec.ends_without_newline = False     # the entry is pasted into another file, which gets its own newline
    for key, value in ctx:
        if value:
            sec.set_property("ARCHIVE_" + key, value, padded=False)
    tail = doc.lines[item.end:item.sub_end]
    entry = _shift_levels(item, sec.lines, tail)
    arch_rel = archive_rel(cfg, rel)
    new_archive = append_entry(args.get("archive_text"), entry, src)
    repl = []
    if item.sub_end >= len(doc.lines) and doc.lines and doc.lines[-1] != "" and item.start > 0:
        repl = [""]                  # cutting the last line must leave the previous line terminated
    parent = item.parent
    return OpOutcome(splice=(item.start, item.sub_end, repl), update_parent_cookie=parent is not None,
                     cookie_id=parent.id if parent else None, side_files={arch_rel: new_archive},
                     info={"archive_file": arch_rel, "title": item.title, "id": item.id})


def plan_archive_closed(doc, rel, today, older_than_days, archive_text):
    """Archive old closed items under the inbox heading, in file order, on in-memory copies.

    Returns ``(new_text, new_archive_text, archived, skipped)``; ``new_archive_text`` is ``archive_text``
    when nothing was archived.
    """
    import datetime as _dt

    from . import edits
    from .model import parse

    if not isinstance(older_than_days, int) or isinstance(older_than_days, bool) or older_than_days < 0:
        raise ValueError("older_than_days must be a non-negative integer")
    inbox = edits.default_parent(doc)
    cutoff = today - _dt.timedelta(days=older_than_days)
    arch_rel = archive_rel(doc.config, rel)
    skipped, candidates = [], []
    for c in inbox.children:
        if not c.closed:
            continue
        info = {"id": c.id, "title": c.title, "keyword": c.keyword}
        ts = c.planning.get("CLOSED")
        if ts is None:
            skipped.append({**info, "reason": "no_closed_date"})
        elif c.open_descendants():
            skipped.append({**info, "reason": "open_descendants",
                            "open": [o.title for o in c.open_descendants()]})
        elif ts.date >= cutoff:
            skipped.append({**info, "reason": "too_recent", "closed": ts.date.isoformat()})
        else:
            candidates.append((c, ts.date))
    cur, cur_arch = doc, archive_text
    archived = []
    for c, closed in candidates:
        item = next((i for i in cur.items if i.path == c.path and i.rev == c.rev), None)
        if item is None:                       # pragma: no cover - cannot happen with sibling-only changes
            skipped.append({"id": c.id, "title": c.title, "keyword": c.keyword, "reason": "changed_while_archiving"})
            continue
        res = edits.execute(cur, edits.OPS["archive"], item, {"file_rel": rel, "archive_text": cur_arch})
        cur_arch = res.side_files[arch_rel]
        cur = parse(res.text, cur.config, cur.name)
        archived.append({"id": c.id, "title": c.title, "closed": closed.isoformat()})
    return cur.original, cur_arch, archived, skipped
