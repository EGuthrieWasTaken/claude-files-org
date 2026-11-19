"""The edit engine and the single-item edit operations.

An operation edits a :class:`~section.Section` (a copy of one item's lines). The
engine splices the result into the document, refreshes the parent's progress
cookie when the operation calls for it, and then proves, line by line, that only
the declared ranges changed (design.md Decision 2).
"""
import difflib
import re
from dataclasses import dataclass, field

from . import timestamps as T
from .model import OrgError, parse
from .section import Section, align_headline, clean_note, tag_string


@dataclass
class OpOutcome:
    changed: bool = True
    update_parent_cookie: bool = False
    #: (start, end, new_lines) in document line indexes, replacing the default section splice
    splice: tuple = None
    #: extra (start, end) ranges the operation is allowed to touch, beside the target section
    allowed: list = field(default_factory=list)
    #: id of the item whose progress cookie to refresh (default: the target's parent)
    cookie_id: str = None
    #: line index in the *new* text of a headline the operation created (add_item)
    result_line: int = None
    #: files other than the target (path relative to the served folder -> new text)
    side_files: dict = field(default_factory=dict)
    result_id: str = None
    warnings: list = field(default_factory=list)
    info: dict = field(default_factory=dict)


@dataclass
class EditResult:
    changed: bool
    text: str
    old_text: str
    target_id: str
    rev: str
    side_files: dict
    warnings: list
    info: dict


# -- shared helpers -------------------------------------------------------------------------------------


def now_dt(cfg):
    return T.now(cfg.tz)


def now_stamp(cfg, active=False):
    return T.stamp(now_dt(cfg), active=active)


def log_state_line(new, old, stamp):
    q = lambda s: '"%s"' % (s or "")
    return f"- State {q(new):<12} from {q(old):<12} {stamp}"


def count_cookie(parent):
    """The cookie text org would write for ``parent``: direct children with a keyword, closed ones done."""
    m = re.search(r"\[[0-9]*%\]|\[[0-9]*/[0-9]*\]", parent.doc.lines[parent.start])
    if not m:
        return None
    kids = [c for c in parent.children if c.keyword is not None]
    done = sum(1 for c in kids if c.closed)
    if m.group(0).endswith("%]"):
        return "[%d%%]" % (100 * done // max(1, len(kids)))
    return "[%d/%d]" % (done, len(kids))


def _check_structure(item):
    problems = item.structure_problems()
    if problems:
        code, ln, msg = problems[0]
        raise OrgError("unsafe_structure",
                       f"line {ln + 1} of {item.doc.name}: {msg}. org would not edit this item the way the tool "
                       "does; run org_lint and fix it in Emacs.", line=ln + 1)


def _check_repeaters(item):
    for key in ("SCHEDULED", "DEADLINE"):
        ts = item.planning.get(key)
        if ts is not None and (ts.has_repeater):
            raise OrgError("repeater_unsupported",
                           f"{key} {ts.raw} repeats; repeating tasks must be changed in Emacs.")


def _guard(old_lines, new_lines, allowed, name):
    """Every changed line must fall inside a declared range (design.md Decision 2)."""
    # A diff may slide a change along a run of identical lines (blank lines, ":END:"), so each declared
    # range also covers the identical lines directly beside it.
    n = len(old_lines)
    widened = []
    for a, b in allowed:
        while 0 < a < n and old_lines[a - 1] == old_lines[a]:
            a -= 1
        while 0 < b < n and old_lines[b] == old_lines[b - 1]:
            b += 1
        widened.append((a, b))
    merged = []
    for a, b in sorted(widened):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    allowed = merged
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        ok = any(a <= i1 and i2 <= b for a, b in allowed)
        if not ok:
            raise OrgError("internal_error",
                           f"refusing to write {name}: the edit would change lines {i1 + 1}-{max(i2, i1 + 1)}, "
                           "outside what the operation declared. Nothing was written; this is a bug.")


def unified_diff(old_text, new_text, name):
    return "\n".join(difflib.unified_diff(old_text.split("\n"), new_text.split("\n"),
                                          f"a/{name}", f"b/{name}", lineterm="", n=2))


def locate(doc, item_id, rev):
    """Find the target and check the caller's ``rev`` (design: ``stale`` returns the current state)."""
    from . import query
    item = doc.get(item_id)
    if item is None:
        raise OrgError("not_found", f"no item with id {item_id!r} in {doc.name}; it may have been renamed, moved or "
                       "archived. Call org_list_items again to find its current id.")
    if rev is None or item.rev != rev:
        raise OrgError("stale", f"{item.title!r} changed since you read it (rev {rev!r}, now {item.rev!r}). "
                       "Re-read it with the current state below, decide again, and retry with the new rev.",
                       current=query.describe(item))
    return item


# -- the engine ------------------------------------------------------------------------------------------


def execute(doc, op, item, args, check_repeater=True, check_structure=True):
    """Apply operation ``op(doc, item, sec, args) -> OpOutcome`` and return an :class:`EditResult`."""
    if check_structure:
        _check_structure(item)
    if check_repeater:
        _check_repeaters(item)
    sec = Section(doc, item)
    out = op(doc, item, sec, args)
    old_lines = doc.lines
    parent_id = out.cookie_id or (item.parent.id if item.parent else None)
    if out.splice is not None:
        a, b, repl = out.splice
        new_lines = old_lines[:a] + repl + old_lines[b:]
        allowed = [(a, b)] + list(out.allowed)
    else:
        new_lines = old_lines[:item.start] + sec.lines + old_lines[item.end:]
        allowed = [(item.start, item.end)] + list(out.allowed)
    if out.update_parent_cookie and parent_id:
        new_lines, extra_allowed = _refresh_parent_cookie(doc, new_lines, parent_id)
        allowed += extra_allowed
    _guard(old_lines, new_lines, allowed, doc.name)
    new_text = "\n".join(new_lines)
    result_id = out.result_id or item.id
    rev = None
    if new_text != doc.original:
        doc2 = parse(new_text, doc.config, doc.name)
        if out.result_line is not None:
            it2 = next((i for i in doc2.items if i.start == out.result_line), None)
            result_id = it2.id if it2 else result_id
        else:
            it2 = doc2.get(result_id)
        rev = it2.rev if it2 else None
    else:
        rev = item.rev
    return EditResult(new_text != doc.original, new_text, doc.original, result_id, rev, out.side_files,
                      out.warnings, out.info)


def _refresh_parent_cookie(doc, new_lines, parent_id):
    """Recount the parent's progress cookie in the edited text (``org-update-parent-todo-statistics``)."""
    text = "\n".join(new_lines)
    doc2 = parse(text, doc.config, doc.name)
    parent = doc2.get(parent_id)
    if parent is None:
        return new_lines, []
    new = count_cookie(parent)
    if new is None:
        return new_lines, []
    sec = Section(doc2, parent)
    # only the headline line is touched
    if not sec.set_cookie(new):
        return new_lines, []
    lines = list(new_lines)
    lines[parent.start] = sec.lines[0]
    # the parent's headline index in the *old* document is the one the guard understands
    old_parent = doc.get(parent_id)
    return lines, [(old_parent.start, old_parent.start + 1)] if old_parent else []


# -- operations -------------------------------------------------------------------------------------------


def op_set_state(doc, item, sec, args):
    cfg = doc.config
    kws = doc.keywords
    state = (args.get("state") or "").strip()
    if state not in kws.all:
        raise OrgError("unknown_keyword", f"{state!r} is not a keyword in {doc.name}; valid keywords: {list(kws.all)}")
    note = clean_note(args.get("note"))
    if kws.needs_note(state) and not note:
        raise OrgError("note_required", f"{state} needs a note: pass a short reason in `note`.")
    old = item.keyword
    if state == old:
        return OpOutcome(changed=False)
    stamp = now_stamp(cfg)
    sec.set_keyword(state, kws.all)
    sec.realign()
    was_closed = old is not None and kws.is_closed(old)
    was_open = old is not None and kws.is_open(old)
    if kws.is_open(state) and not was_open:
        sec.add_planning(None, None, remove=("CLOSED",))       # reopening drops CLOSED
    if kws.is_closed(state) and not was_closed:
        sec.add_planning("CLOSED", stamp)
    if kws.needs_note(state) or note:
        sec.add_log_entry(log_state_line(state, old, stamp), note)
    return OpOutcome(update_parent_cookie=True)




def _need(args, key):
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ValueError(f"missing required argument {key!r}")
    return v


def _old_log_text(raw):
    ts = T.parse_timestamp(raw)
    return '"' + (ts.inactive_text() if ts else raw) + '"'


def _planning_op(key, changed_label, removed_label):
    def op(doc, item, sec, args):
        cfg = doc.config
        raw = item.planning_raw.get(key)
        old = item.planning.get(key)
        if raw is not None and old is None:
            raise OrgError("unsafe_structure", f"{key} {raw} on line {item.planning_idx + 1} is not a valid "
                           "timestamp; org would not edit it the way the tool does. Fix it in Emacs (see org_lint).")
        if old is not None and old.has_warning:
            raise OrgError("repeater_unsupported", f"{key} {old.raw} has a warning period, which the tools do not "
                           "write; change it in Emacs.")
        note = clean_note(args.get("note"))
        stamp = now_stamp(cfg)
        if args.get("remove"):
            if old is None:
                return OpOutcome(changed=False)
            sec.remove_entry(key)
            sec.add_log_entry(f"- {removed_label} {_old_log_text(raw)} on {stamp}", note)
            return OpOutcome()
        try:
            new = T.build_timestamp(_need(args, "date"), args.get("time"))
        except T.TimestampError as e:
            raise OrgError("bad_date", str(e)) from None
        if old is not None and old.same_moment(T.parse_timestamp(new)):
            return OpOutcome(changed=False)
        sec.add_planning(key, new, remove=("CLOSED",))        # org also drops CLOSED when (re)planning
        if old is not None:
            sec.add_log_entry(f'- {changed_label} {_old_log_text(raw)} on {stamp}', note)
        return OpOutcome()
    return op


op_reschedule = _planning_op("SCHEDULED", "Rescheduled from", "Not scheduled, was")
op_set_deadline = _planning_op("DEADLINE", "New deadline from", "Removed deadline, was")


def op_add_note(doc, item, sec, args):
    note = clean_note(args.get("note"))
    if not note:
        raise OrgError("note_required", "org_add_note needs a non-empty note.")
    sec.add_log_entry(f"- Note taken on {now_stamp(doc.config)}", note)
    return OpOutcome()


def validate_tags(cfg, tags):
    if isinstance(tags, str):
        tags = [tags]
    out = []
    for t in tags or []:
        t = str(t).strip().strip(":")
        if t not in cfg.tags:
            raise OrgError("unknown_tag", f"tag {t!r} is not configured; allowed tags: {list(cfg.tags)}")
        if t not in out:
            out.append(t)
    return out


def op_set_tags(doc, item, sec, args):
    tags = validate_tags(doc.config, args.get("tags"))
    sec.set_tags(tags)
    return OpOutcome()


_EFFORT_RE = re.compile(r"^(\d+):([0-5]\d)$")


def op_set_effort(doc, item, sec, args):
    value = args.get("value")
    warnings = []
    if args.get("remove") or value in (None, ""):
        if not args.get("remove"):
            raise ValueError("pass effort `value` (H:MM) or remove=true")
        sec.delete_property("Effort")
        return OpOutcome()
    value = str(value).strip()
    if not _EFFORT_RE.match(value):
        raise OrgError("bad_effort", f"effort {value!r} is not H:MM (for example 0:45 or 2:00)")
    h, m = value.split(":")
    value = f"{int(h)}:{m}"
    if value not in doc.config.effort_values:
        warnings.append(f"effort {value} is not one of the preferred values {list(doc.config.effort_values)}")
    sec.set_property("Effort", value)
    return OpOutcome(warnings=warnings)


def _planning_arg(args, key):
    date = args.get(key)
    if date in (None, ""):
        return None
    try:
        return T.build_timestamp(date, args.get(key + "_time"))
    except T.TimestampError as e:
        raise OrgError("bad_date", f"{key}: {e}") from None


def op_add_item(doc, parent, sec, args):
    """``org-capture`` with Ethan's ``t`` template: ``TODO title`` as the last child of ``parent``."""
    cfg = doc.config
    title = (args.get("title") or "").strip()
    if not title or "\n" in title or "\r" in title:
        raise ValueError("title must be a single non-empty line")
    from .model import TAGS_RE, HEADLINE_RE
    if TAGS_RE.search(title):
        raise ValueError("title may not end in :tag: text; pass tags separately")
    tags = validate_tags(cfg, args.get("tags"))
    keyword = "TODO" if "TODO" in doc.keywords.open else doc.keywords.open[0]
    head = "*" * (parent.level + 1) + f" {keyword} {title}"
    if tags:
        head = align_headline(head + " " + tag_string(tags))
    scheduled, deadline = _planning_arg(args, "scheduled"), _planning_arg(args, "deadline")
    effort = args.get("effort")
    warnings = []
    if effort not in (None, ""):
        effort = str(effort).strip()
        if not _EFFORT_RE.match(effort):
            raise OrgError("bad_effort", f"effort {effort!r} is not H:MM (for example 0:45 or 2:00)")
        h, m = effort.split(":")
        effort = f"{int(h)}:{m}"
        if effort not in cfg.effort_values:
            warnings.append(f"effort {effort} is not one of the preferred values {list(cfg.effort_values)}")
    body = args.get("body")
    new = [head]
    plan = [f"SCHEDULED: {scheduled}"] if scheduled else []
    plan += [f"DEADLINE: {deadline}"] if deadline else []
    if plan:
        new.append(" ".join(plan))
    new += [":PROPERTIES:", f"{':CREATED:':<10} {now_stamp(cfg)}"]
    if effort:
        new.append(f"{':Effort:':<10} {effort}")
    new.append(":END:")
    if body and body.strip():
        for ln in body.replace("\r\n", "\n").rstrip().split("\n"):
            if HEADLINE_RE.match(ln) or ln.strip().upper() == ":END:":
                raise ValueError("body lines may not start with '* ' or be ':END:'; they would change the structure")
            new.append(ln)
    eol = doc.eol
    new = [x + eol for x in new]
    end = parent.sub_end
    at = end
    while at > parent.start + 1 and doc.lines[at - 1].strip() == "":
        at -= 1                    # capture puts the entry after the last non-blank line ...
    if end >= len(doc.lines) and doc.lines and doc.lines[-1] != "":
        new = new + [""]          # the file had no final newline; org adds one
    # ... and swallows the subtree's trailing blank lines, as org-capture does
    return OpOutcome(update_parent_cookie=True, splice=(at, end, new), result_line=at, warnings=warnings,
                     cookie_id=parent.id)


OPS = {"set_state": op_set_state, "reschedule": op_reschedule, "set_deadline": op_set_deadline,
       "add_note": op_add_note, "set_tags": op_set_tags, "set_effort": op_set_effort, "add_item": op_add_item}


def run_oracle_op(doc, name, item, args, **_kw):
    """Run a registered operation directly on an item (used by the oracle tests and the tools)."""
    if name == "add_item":
        parent = item if item is not None else default_parent(doc)
        return execute(doc, OPS[name], parent, args, check_repeater=False, check_structure=False)
    return execute(doc, OPS[name], item, args)


def default_parent(doc):
    """The configured inbox heading (a top-level item titled ``ORG_INBOX_HEADING``)."""
    for it in doc.items:
        if it.level == 1 and it.title == doc.config.inbox_heading:
            return it
    raise OrgError("not_found", f"inbox heading {doc.config.inbox_heading!r} not found in {doc.name}; "
                   "pass an explicit parent")
