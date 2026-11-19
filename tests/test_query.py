import datetime as dt

import pytest

from claude_files_org import query
from claude_files_org.model import OrgError, parse
from tests.conftest import fixture_text

TODAY = dt.date(2026, 11, 19)


def titles(result):
    return [i["title"] for i in result["items"]]


# -- list ---------------------------------------------------------------------------

def test_default_call_returns_open_items_in_file_order_without_bodies(load):
    r = query.list_items(load(), TODAY)
    ts = titles(r)
    assert ts[:3] == ["alpha", "beta", "b1"]
    assert "delta" not in ts and "theta" not in ts and "Midterm 1" not in ts
    assert all("body" not in i for i in r["items"])
    assert r["total"] == r["returned"] == len(ts)
    assert r["settings"]["timezone"] == "America/Indiana/Indianapolis"   # settings are reported
    first = r["items"][0]
    assert set(first) >= {"id", "rev", "path", "level", "keyword", "title", "tags", "inherited_tags", "scheduled",
                          "deadline", "closed", "effort", "created", "cookie", "child_count", "line"}
    assert first["scheduled"] == "2026-11-13" and first["deadline"] == "2026-11-20 09:30"
    assert first["effort"] == "0:45" and first["path"] == ["Tasks", "alpha"]


def test_state_filters(load):
    doc = load()
    assert "delta" in titles(query.list_items(doc, TODAY, state="closed"))
    assert "alpha" not in titles(query.list_items(doc, TODAY, state="closed"))
    allt = titles(query.list_items(doc, TODAY, state="all"))
    assert "Midterm 1" in allt and "alpha" in allt and "delta" in allt
    assert titles(query.list_items(doc, TODAY, state=["WAIT"])) == ["eta"]
    assert set(titles(query.list_items(doc, TODAY, state=["STARTED", "WAIT"]))) == {"zeta", "eta"}
    with pytest.raises(OrgError) as e:
        query.list_items(doc, TODAY, state=["NEXT"])
    assert e.value.code == "unknown_keyword" and "TODO" in e.value.message


def test_inherited_tags_match(load):
    r = query.list_items(load(), TODAY, tags=["stephen"])
    assert "b1" in titles(r) and "alpha" in titles(r)
    b1 = next(i for i in r["items"] if i["title"] == "b1")
    assert b1["tags"] == [] and b1["inherited_tags"] == ["stephen"]


def test_nested_inherited_tags_are_listed():
    from claude_files_org.config import load_config
    doc = parse("* Tasks\n** TODO p :research:stephen:\n*** TODO c\n", load_config({}))
    c = next(i for i in query.list_items(doc, TODAY, tags=["stephen"])["items"] if i["title"] == "c")
    assert c["inherited_tags"] == ["research", "stephen"]


def test_tag_group(load):
    assert titles(query.list_items(load(), TODAY, tags=["personal"])) == ["blog about the thing"]
    assert titles(query.list_items(load(), TODAY, tags=["blog"])) == ["blog about the thing"]


def test_multiple_tags_must_all_match(load):
    assert titles(query.list_items(load(), TODAY, tags=["stephen", "research"])) == ["alpha"]


def test_overdue(load):
    doc = parse(fixture_text("clean.org"), load().config)
    r = query.list_items(doc, TODAY, overdue=True)
    assert titles(r) == ["alpha", "overdue deadline"]
    assert "overdue but closed" not in titles(query.list_items(doc, TODAY, state="all", overdue=True))


def test_date_ranges(load):
    doc = load()
    r = query.list_items(doc, TODAY, scheduled_from="2026-11-14", scheduled_to="2026-11-25")
    assert set(titles(r)) == {"b1", "eta"}
    r = query.list_items(doc, TODAY, deadline_from="2026-11-20", deadline_to="2026-12-14")
    assert titles(r) == ["alpha"]
    with pytest.raises(OrgError) as e:
        query.list_items(doc, TODAY, deadline_from="soon")
    assert e.value.code == "bad_date"


def test_text_filter_is_case_insensitive(load):
    assert titles(query.list_items(load(), TODAY, text="FINAL")) == ["Final Exam", "Final Exam"]


def test_limit_reports_the_total(load):
    r = query.list_items(load(), TODAY, limit=3)
    assert titles(r) == ["alpha", "beta", "b1"] and r["returned"] == 3 and r["total"] > 3


# -- get ----------------------------------------------------------------------------

def test_get_item_in_full(load, by_title):
    doc = load()
    alpha = by_title(doc, "alpha")
    d = query.get_item(doc, alpha.id)
    assert d["body"] == "Notes about alpha.\nSecond body line."
    assert d["properties"] == {"Effort": "0:45"}
    assert d["logbook"] == [{"kind": "rescheduled", "old": "2026-11-06", "time": "2026-11-09 10:00", "line": 11,
                             "note": None}]
    beta = query.get_item(doc, by_title(doc, "beta").id)
    assert [c["title"] for c in beta["children"]] == ["b1", "b2"] and beta["cookie"] == "[0/2]"


def test_logbook_entry_kinds():
    from claude_files_org.config import load_config
    text = "\n".join([
        "* Tasks", "** TODO x", ":LOGBOOK:",
        '- Rescheduled from "[2026-11-13 Fri]" on [2026-11-16 Mon 11:15]',
        '- Not scheduled, was "[2026-11-13 Fri 9:30]" on [2026-11-16 Mon 11:16]',
        '- New deadline from "[2026-11-20 Fri]" on [2026-11-16 Mon 11:17]',
        '- Removed deadline, was "[2026-11-20 Fri]" on [2026-11-16 Mon 11:18]',
        '- State "WAIT"       from "TODO"       [2026-11-16 Mon 11:19] \\\\', "  waiting", "  on two lines",
        '- State "DONE"       from "TODO"       [2026-11-16 Mon 11:20]',
        '- Note taken on [2026-11-16 Mon 11:21] \\\\', "  hello",
        "- something an agent made up", ":END:", ""])
    doc = parse(text, load_config({}))
    kinds = [e["kind"] for e in query.parse_logbook(doc.items[1])]
    assert kinds == ["rescheduled", "not_scheduled", "new_deadline", "removed_deadline", "state", "state", "note",
                     "unknown"]
    es = query.parse_logbook(doc.items[1])
    assert es[0]["old"] == "2026-11-13" and es[0]["time"] == "2026-11-16 11:15"
    assert es[1]["old"] == "2026-11-13 09:30"
    assert (es[4]["state"], es[4]["from"], es[4]["note"]) == ("WAIT", "TODO", "waiting\non two lines")
    assert es[6]["note"] == "hello"


def test_unknown_id_is_not_found(load):
    with pytest.raises(OrgError) as e:
        query.get_item(load(), "o_0000000000")
    assert e.value.code == "not_found" and "org_list_items" in e.value.message


# -- lint ---------------------------------------------------------------------------

def test_lint_reports_each_problem_with_line_numbers(load):
    found = {(p["code"], p["path"][-1], p["line"]) for p in query.lint(load("malformed.org"))}
    assert ("misplaced_property_drawer", "misplaced drawer", 8) in found
    assert ("unclosed_drawer", "unclosed drawer", 12) in found
    assert ("malformed_timestamp", "bad timestamp", 15) in found
    assert ("unknown_tag", "bad tag", 19) in found
    assert any(c == "duplicate_path" and t == "duplicate" for c, t, _ in found)
    assert ("closed_with_open_children", "closed with open child", 22) in found
    assert ("invented_logbook_line", "invented logbook", 27) in found
    assert ("misplaced_property_drawer", "invisible property drawer", 31) in found
    msg = next(p["message"] for p in query.lint(load("malformed.org")) if p["code"] == "misplaced_property_drawer")
    assert "ignores" in msg


def test_lint_does_not_change_the_document(load):
    doc = load("malformed.org")
    before = doc.render()
    query.lint(doc)
    assert doc.render() == before


def test_clean_file_has_no_problems(load):
    assert query.lint(load("clean.org")) == []
