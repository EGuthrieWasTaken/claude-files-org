"""All-or-nothing batches: ordered edits on one file, applied to an in-memory copy."""
from . import edits
from .model import OrgError, parse

#: tool-level edit names that may appear in a batch (archiving touches a second file and is not batchable)
BATCHABLE = ("set_state", "reschedule", "set_deadline", "add_note", "set_tags", "set_effort", "add_item")

_RESERVED = {"op", "id", "rev"}


def _fail(n, op, err):
    if isinstance(err, OrgError):
        return OrgError(err.code, f"edit {n} ({op}): {err.message}", failed_edit=n, **err.extra)
    return ValueError(f"edit {n} ({op}): {err}")


def apply_batch(doc, edit_list):
    """Apply every edit in order, or none.

    Each edit is ``{"op": ..., "id": ..., "rev": ..., **args}``. Revs are checked against ``doc`` as the
    caller read it, before anything is applied; later edits may therefore touch an item an earlier one
    already changed. Returns ``(final_doc_text, results)`` where ``results`` has one entry per edit.
    """
    if not isinstance(edit_list, list) or not edit_list:
        raise ValueError("a batch needs a non-empty list of edits")
    # phase 1: shape and rev checks against the file as read
    for n, e in enumerate(edit_list, 1):
        op = e.get("op") if isinstance(e, dict) else None
        if op not in BATCHABLE:
            raise ValueError(f"edit {n}: unknown op {op!r}; use one of {list(BATCHABLE)}")
        try:
            if op == "add_item" and not e.get("id"):
                if e.get("rev"):
                    raise ValueError("`rev` without `id`: pass the parent's id, or neither")
                continue
            if not e.get("id") or not e.get("rev"):
                raise ValueError("every edit needs the target `id` and the `rev` you last read")
            edits.locate(doc, e["id"], e["rev"])
        except (OrgError, ValueError) as err:
            raise _fail(n, op, err) from None
    # phase 2: apply in order on evolving copies
    cur = doc
    results = []
    for n, e in enumerate(edit_list, 1):
        op = e["op"]
        args = {k: v for k, v in e.items() if k not in _RESERVED}
        try:
            if op == "add_item":
                parent = cur.get(e["id"]) if e.get("id") else edits.default_parent(cur)
                if parent is None:
                    raise OrgError("not_found", f"no item with id {e['id']!r}")
                res = edits.execute(cur, edits.OPS[op], parent, args, check_repeater=False, check_structure=False)
            else:
                item = cur.get(e["id"])
                if item is None:
                    raise OrgError("not_found", f"no item with id {e['id']!r}; an earlier edit may have moved it")
                res = edits.execute(cur, edits.OPS[op], item, args)
        except (OrgError, ValueError) as err:
            raise _fail(n, op, err) from None
        results.append({"index": n, "op": op, "id": res.target_id, "changed": res.changed, "warnings": list(res.warnings)})
        if res.changed:
            cur = parse(res.text, cur.config, cur.name)
    final = cur
    for r in results:
        it = final.get(r["id"])
        r["rev"] = it.rev if it else None
    return final.original if final is not doc else doc.original, results
