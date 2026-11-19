"""Reading org files as items: list, get and lint."""
import datetime as _dt
import re

from . import timestamps as T
from .model import OrgError, PLANNING_RE, LOOSE_TS_RE

# -- timestamps as agents see them ---------------------------------------------


def ts_iso(ts):
    """``2026-11-20``, ``2026-11-20 09:30`` or ``2026-11-20 13:00-14:00`` (zero padded)."""
    if ts is None:
        return None
    out = ts.date.isoformat()
    if ts.start:
        out += " " + T._norm_time(ts.start)
        if ts.end:
            out += "-" + T._norm_time(ts.end)
    return out


def raw_iso(raw):
    """ISO form of a raw timestamp string, or None if it is malformed."""
    return ts_iso(T.parse_timestamp(raw)) if raw else None


# -- item summaries ----------------------------------------------------------------


def _planning_iso(item, key):
    ts = item.planning.get(key)
    if ts is not None:
        return ts_iso(ts)
    raw = item.planning_raw.get(key)
    return None if raw is None else f"malformed:{raw}"


def summarize(item):
    """The list shape: no body."""
    return {
        "id": item.id,
        "rev": item.rev,
        "path": list(item.path),
        "level": item.level,
        "keyword": item.keyword,
        "open": item.open,
        "title": item.title,
        "tags": list(item.tags),
        "inherited_tags": item.inherited_tags,
        "scheduled": _planning_iso(item, "SCHEDULED"),
        "deadline": _planning_iso(item, "DEADLINE"),
        "closed": _planning_iso(item, "CLOSED"),
        "effort": item.effort,
        "created": raw_iso(item.created) if item.created else None,
        "cookie": item.cookie,
        "child_count": len(item.children),
        "line": item.line,
    }


# -- list ----------------------------------------------------------------------------


def _norm_states(state, doc):
    if state is None:
        return "open"
    if isinstance(state, str):
        s = state.strip()
        if s.lower() in ("open", "closed", "all"):
            return s.lower()
        state = [s]
    kws = [k.strip() for k in state if k and k.strip()]
    if not kws:
        return "open"
    low = {k.lower() for k in kws}
    if low <= {"open", "closed", "all"} and len(low) == 1:
        return next(iter(low))
    unknown = [k for k in kws if k not in doc.keywords.all]
    if unknown:
        raise OrgError("unknown_keyword", f"unknown keyword(s) {unknown}; valid keywords: {list(doc.keywords.all)} "
                       "(or 'open', 'closed', 'all')")
    return set(kws)


def _date_arg(value, name):
    if value is None or value == "":
        return None
    try:
        return T.parse_date_arg(value)
    except T.TimestampError as e:
        raise OrgError("bad_date", f"{name}: {e}") from None


def _in_range(ts, lo, hi):
    if ts is None:
        return False
    d = ts.date
    return (lo is None or d >= lo) and (hi is None or d <= hi)


def is_overdue(item, today):
    if not item.open:
        return False
    for key in ("SCHEDULED", "DEADLINE"):
        ts = item.planning.get(key)
        if ts is not None and ts.date < today:
            return True
    return False


def select_items(doc, state=None, tags=None, scheduled_from=None, scheduled_to=None, deadline_from=None,
                 deadline_to=None, overdue=None, text=None, today=None):
    """Items matching all the filters, in file order."""
    st = _norm_states(state, doc)
    sf, stt = _date_arg(scheduled_from, "scheduled_from"), _date_arg(scheduled_to, "scheduled_to")
    df, dt_ = _date_arg(deadline_from, "deadline_from"), _date_arg(deadline_to, "deadline_to")
    if isinstance(tags, str):
        tags = [tags]
    tags = [t for t in (tags or []) if t]
    needle = text.lower().strip() if text else None
    out = []
    for it in doc.items:
        if st == "open":
            if not it.open:
                continue
        elif st == "closed":
            if not it.closed:
                continue
        elif st == "all":
            pass
        elif it.keyword not in st:
            continue
        if any(not it.has_tag(t) for t in tags):
            continue
        if (sf or stt) and not _in_range(it.planning.get("SCHEDULED"), sf, stt):
            continue
        if (df or dt_) and not _in_range(it.planning.get("DEADLINE"), df, dt_):
            continue
        if overdue and not is_overdue(it, today):
            continue
        if needle and needle not in it.title.lower():
            continue
        out.append(it)
    return out


def list_items(doc, today, limit=None, **filters):
    matched = select_items(doc, today=today, **filters)
    if limit is not None:
        if not isinstance(limit, int) or limit < 0:
            raise OrgError("bad_argument", "limit must be a non-negative integer")
        shown = matched[:limit]
    else:
        shown = matched
    return {
        "file": doc.name,
        "today": today.isoformat(),
        "total": len(matched),
        "returned": len(shown),
        "items": [summarize(i) for i in shown],
        "settings": doc.config.as_dict(),
    }


# -- get -----------------------------------------------------------------------------------

_TS = r"\[[^\]]*\]"
_STATE_RE = re.compile(r'^- State\s+"([^"]*)"(?:\s+from\s+"([^"]*)")?\s+(' + _TS + r")(?: \\\\)?\s*$")
_RESCHEDULED_RE = re.compile(r'^- Rescheduled from "(' + _TS + r')" on (' + _TS + r")(?: \\\\)?\s*$")
_NOT_SCHEDULED_RE = re.compile(r'^- Not scheduled, was "(' + _TS + r')" on (' + _TS + r")(?: \\\\)?\s*$")
_NEW_DEADLINE_RE = re.compile(r'^- New deadline from "(' + _TS + r')" on (' + _TS + r")(?: \\\\)?\s*$")
_REMOVED_DEADLINE_RE = re.compile(r'^- Removed deadline, was "(' + _TS + r')" on (' + _TS + r")(?: \\\\)?\s*$")
_NOTE_RE = re.compile(r"^- Note taken on (" + _TS + r")(?: \\\\)?\s*$")
# other lines org itself may write into a logbook; not "invented", but not parsed further
_ORG_OTHER_RE = re.compile(r"^(?:- (?:Refiled on|Priority|Tag(?:s)? changed|Clocked)\b.*|CLOCK:.*)$")


def parse_logbook(item):
    """Parsed logbook entries, newest first as in the file."""
    if item.logbook_span is None:
        return []
    lines = item.doc.lines
    a, b = item.logbook_span
    entries, cur = [], None
    for i in range(a + 1, b):
        line = lines[i].rstrip("\r")
        if line.startswith("- ") or _ORG_OTHER_RE.match(line):
            cur = {"line": i + 1, "text": line, "cont": []}
            entries.append(cur)
        elif cur is not None and line.startswith("  "):
            cur["cont"].append(line[2:])
        elif line.strip() == "":
            continue
        else:
            cur = {"line": i + 1, "text": line, "cont": [], "stray": True}
            entries.append(cur)
    return [_entry(e) for e in entries]


def _iso(ts_text):
    return raw_iso(ts_text) or ts_text


def _entry(e):
    text, note = e["text"], "\n".join(e["cont"]).strip("\n") or None
    base = {"line": e["line"], "note": note}
    if not e.get("stray"):
        for kind, rx in (("rescheduled", _RESCHEDULED_RE), ("not_scheduled", _NOT_SCHEDULED_RE),
                         ("new_deadline", _NEW_DEADLINE_RE), ("removed_deadline", _REMOVED_DEADLINE_RE)):
            m = rx.match(text)
            if m:
                return {"kind": kind, "old": _iso(m.group(1)), "time": _iso(m.group(2)), **base}
        m = _STATE_RE.match(text)
        if m:
            return {"kind": "state", "state": m.group(1), "from": m.group(2), "time": _iso(m.group(3)), **base}
        m = _NOTE_RE.match(text)
        if m:
            return {"kind": "note", "time": _iso(m.group(1)), **base}
    return {"kind": "unknown", "text": text, **base}


def body_text(item):
    """Body lines: the section without headline, planning, property drawer and logbook."""
    lines = item.doc.lines
    skip = set()
    if item.planning_idx is not None:
        skip.add(item.planning_idx)
    for span in (item.props_span, item.logbook_span):
        if span:
            skip.update(range(span[0], span[1] + 1))
    keep = [lines[i].rstrip("\r") for i in range(item.start + 1, item.end) if i not in skip]
    return "\n".join(keep).strip("\n")


def get_item(doc, item_id):
    item = doc.get(item_id)
    if item is None:
        raise OrgError("not_found", f"no item with id {item_id!r} in {doc.name}; it may have been renamed, moved "
                       "or archived. Call org_list_items again to find its current id.")
    return describe(item)


def describe(item):
    d = summarize(item)
    d.update({
        "body": body_text(item),
        "properties": dict(item.properties),
        "logbook": parse_logbook(item),
        "children": [{"id": c.id, "rev": c.rev, "title": c.title, "keyword": c.keyword, "open": c.open,
                      "line": c.line, "cookie": c.cookie} for c in item.children],
        "problems": [{"code": c, "line": ln + 1, "message": m} for c, ln, m in item.problems],
    })
    return d


# -- lint --------------------------------------------------------------------------------------


def lint(doc):
    """Structure org cannot read, with line numbers. Never changes the file."""
    problems = []

    def add(item, code, line, message):
        problems.append({"code": code, "id": item.id, "path": list(item.path), "line": line + 1, "message": message})

    for item in doc.items:
        for code, ln, msg in item.problems:
            add(item, code, ln, msg)
        # malformed timestamps anywhere in the section
        for i in range(item.start, item.end):
            line = doc.lines[i].rstrip("\r")
            for m in LOOSE_TS_RE.finditer(line):
                if T.parse_timestamp(m.group(0)) is None:
                    add(item, "malformed_timestamp", i, f"malformed timestamp {m.group(0)!r}")
        for t in item.tags:
            if t not in doc.config.tags:
                add(item, "unknown_tag", item.start, f"tag {t!r} is not in the configured set {list(doc.config.tags)}")
        if item.occurrence > 0:
            add(item, "duplicate_path", item.start,
                f"another item has the same outline path {' / '.join(item.path)!r}; ids stay stable but are easy to confuse")
        if item.closed:
            opens = item.open_descendants()
            if opens:
                add(item, "closed_with_open_children", item.start,
                    f"{item.keyword} item still has open descendants: {[o.title for o in opens]}")
        if item.logbook_span:
            a, b = item.logbook_span
            for e in parse_logbook(item):
                if e["kind"] == "unknown" and not _ORG_OTHER_RE.match(e["text"]):
                    add(item, "invented_logbook_line", e["line"] - 1,
                        f"line is not a logbook entry org writes: {e['text']!r}")
    return problems
