import datetime as dt

import pytest

from claude_files_org import edits
from claude_files_org import timestamps as T
from claude_files_org.model import OrgError, parse
from tests.conftest import fixture_text


@pytest.fixture(autouse=True)
def clock():
    when = dt.datetime(2026, 11, 19, 9, 30)
    T.set_clock(lambda tz: when.replace(tzinfo=tz))
    yield
    T.set_clock(None)


def run(doc, item, **args):
    return edits.execute(doc, edits.op_set_state, item, args)


def test_stale_rev_returns_the_current_state(load, by_title):
    doc = load()
    alpha = by_title(doc, "alpha")
    with pytest.raises(OrgError) as e:
        edits.locate(doc, alpha.id, "000000000000")
    assert e.value.code == "stale"
    cur = e.value.extra["current"]
    assert cur["id"] == alpha.id and cur["rev"] == alpha.rev and cur["keyword"] == "TODO"
    assert edits.locate(doc, alpha.id, alpha.rev) is alpha


def test_unknown_id_is_not_found(load):
    with pytest.raises(OrgError) as e:
        edits.locate(load(), "o_nope", "x")
    assert e.value.code == "not_found"


def test_unsafe_structure_in_the_target_names_the_line(load, by_title):
    doc = load("malformed.org")
    for title, line in [("unclosed drawer", 12), ("misplaced drawer", 8), ("two planning lines", 18)]:
        with pytest.raises(OrgError) as e:
            run(doc, by_title(doc, title), state="DONE")
        assert e.value.code == "unsafe_structure" and f"line {line}" in e.value.message and "org_lint" in e.value.message


def test_problems_elsewhere_do_not_block_a_healthy_item(load, by_title):
    doc = load("malformed.org")
    res = run(doc, by_title(doc, "fine"), state="DONE")
    assert res.changed and "** DONE fine" in res.text
    assert res.text.replace("** DONE fine\nCLOSED: [2026-11-19 Thu 09:30]\n", "** TODO fine\n") == doc.original


def test_only_the_declared_lines_change(load, by_title):
    doc = load()
    res = run(doc, by_title(doc, "alpha"), state="DONE")
    old, new = doc.original.split("\n"), res.text.split("\n")
    changed = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
    assert changed == [4, 5] and len(old) == len(new)


def test_malformed_text_elsewhere_is_left_alone(load, by_title):
    doc = load("malformed.org")
    res = run(doc, by_title(doc, "fine"), state="DONE")
    assert "SCHEDULED: <2026-02-11 Wed: 12:30>" in res.text


def test_guard_refuses_changes_outside_the_declared_ranges():
    old = ["a", "b", "c", "d", "e"]
    new = ["a", "b", "C", "d", "E"]
    with pytest.raises(OrgError) as e:
        edits._guard(old, new, [(2, 3)], "f.org")
    assert e.value.code == "internal_error" and "lines 5-5" in e.value.message
    edits._guard(old, new, [(2, 3), (4, 5)], "f.org")            # both declared: fine
    edits._guard(old, ["a", "b", "x", "c", "d", "e"], [(2, 2)], "f.org")   # insertion at a declared point


def test_internal_error_when_the_engine_would_touch_other_lines(load, by_title, monkeypatch):
    doc = load()
    monkeypatch.setattr(edits, "_refresh_parent_cookie",
                        lambda d, lines, pid: (["TAMPERED"] + lines[1:], []))
    with pytest.raises(OrgError) as e:
        run(doc, by_title(doc, "b1"), state="DONE")
    assert e.value.code == "internal_error"


def test_unchanged_edit_reports_no_change(load, by_title):
    doc = load()
    res = run(doc, by_title(doc, "alpha"), state="TODO")
    assert res.changed is False and res.text == doc.original


def test_result_carries_the_new_rev(load, by_title):
    doc = load()
    alpha = by_title(doc, "alpha")
    res = run(doc, alpha, state="DONE")
    assert res.target_id == alpha.id and res.rev != alpha.rev
    assert parse(res.text, doc.config).get(alpha.id).rev == res.rev


# -- set_state errors (the success paths are oracle tests) ---------------------------------------------

def test_note_required_for_note_keywords(load, by_title):
    doc = load()
    for kw in ("WAIT", "CANCELLED"):
        for note in (None, "", "   \n "):
            with pytest.raises(OrgError) as e:
                run(doc, by_title(doc, "gamma with no planning"), state=kw, note=note)
            assert e.value.code == "note_required"


def test_unknown_keyword_lists_the_valid_ones(load, by_title):
    doc = load()
    with pytest.raises(OrgError) as e:
        run(doc, by_title(doc, "alpha"), state="NEXT")
    assert e.value.code == "unknown_keyword" and "STARTED" in e.value.message


def test_unknown_keyword_respects_the_files_own_sequence(load, by_title):
    doc = load("todo_override.org")
    assert "NEXT" in run(doc, by_title(doc, "finished"), state="NEXT").text
    with pytest.raises(OrgError) as e:
        run(doc, by_title(doc, "finished"), state="WAIT")
    assert e.value.code == "unknown_keyword"


def test_note_line_that_would_close_the_drawer_is_refused(load, by_title):
    doc = load()
    with pytest.raises(OrgError) as e:
        run(doc, by_title(doc, "gamma with no planning"), state="WAIT", note="first\n:END:\nsecond")
    assert e.value.code == "bad_argument"


def test_repeating_items_are_refused(load, by_title):
    doc = load("repeater.org")
    for title in ("weekly review", "daily from done", "monthly catchup"):
        with pytest.raises(OrgError) as e:
            run(doc, by_title(doc, title), state="DONE")
        assert e.value.code == "repeater_unsupported" and "Emacs" in e.value.message


def test_crlf_files_keep_their_line_endings(load, by_title):
    doc = load("crlf.org")
    res = run(doc, by_title(doc, "windows item"), state="WAIT", note="why")
    assert "\n" not in res.text.replace("\r\n", "")        # every newline stays CRLF
    assert "- State \"WAIT\"       from \"TODO\"       [2026-11-19 Thu 09:30] \\\\\r\n  why\r\n" in res.text
