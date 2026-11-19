"""Run an edit through the tool engine in the same shape the Emacs driver uses."""
import datetime as dt

from claude_files_org import edits
from claude_files_org import timestamps as T
from claude_files_org.config import load_config
from claude_files_org.model import parse

from tests.oracle.harness import DEFAULT_NOW, read_tree

TARGET = "org-projects/inbox.org"


def find_item(doc, path, nth=0):
    hits = [i for i in doc.items if "/".join(i.path) == path]
    return hits[nth]


def frozen(now):
    when = dt.datetime.strptime(now, "%Y-%m-%d %H:%M")
    return lambda tz: when.replace(tzinfo=tz)


def engine_apply(home, op, args, now=DEFAULT_NOW, target=TARGET, config=None):
    """Apply ``op`` (an oracle op name, ``set-state`` style) with the engine and return the tree."""
    cfg = config or load_config({})
    path = home / ".emacs.d" / target
    raw = path.read_bytes()
    doc = parse(raw.decode("utf-8", "surrogateescape"), cfg, path.name)
    if op == "add-item":
        item = find_item(doc, args.get("parent", "Tasks"), args.get("parent_nth", 0))
    else:
        item = find_item(doc, args["path"], args.get("nth", 0)) if "path" in args else None
    if op == "add-item":
        args = _structured_add_args(args)
    T.set_clock(frozen(now))
    try:
        res = edits.run_oracle_op(doc, op.replace("-", "_"), item, args, home=home)
    finally:
        T.set_clock(None)
    path.write_bytes(res.text.encode("utf-8", "surrogateescape"))
    for rel, text in res.side_files.items():
        p = home / ".emacs.d" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8", "surrogateescape"))
    return read_tree(home)


def _structured_add_args(args):
    """Oracle args carry the planning line as literal text; the engine wants dates."""
    import re
    out = dict(args)
    plan = out.pop("planning", None)
    if plan:
        for key, ts in re.findall(r"(SCHEDULED|DEADLINE): <(\d{4}-\d{2}-\d{2})[^>]*>", plan):
            out[key.lower()] = ts
    return out
