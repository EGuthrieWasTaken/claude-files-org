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
from .section import Section, clean_note


@dataclass
class OpOutcome:
    changed: bool = True
    update_parent_cookie: bool = False
    #: (start, end, new_lines) in document line indexes, replacing the default section splice
    splice: tuple = None
    #: extra (start, end) ranges the operation is allowed to touch, beside the target section
    allowed: list = field(default_factory=list)
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
    merged = []
    for a, b in sorted(allowed):
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
    parent_id = item.parent.id if item.parent else None
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


OPS = {"set_state": op_set_state}


def run_oracle_op(doc, name, item, args, **_kw):
    """Run a registered operation directly on an item (used by the oracle tests and the tools)."""
    return execute(doc, OPS[name], item, args)
