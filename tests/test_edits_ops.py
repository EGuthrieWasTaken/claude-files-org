import datetime as dt

import pytest

from claude_files_org import edits
from claude_files_org import timestamps as T
from claude_files_org.model import OrgError, parse


@pytest.fixture(autouse=True)
def clock():
    when = dt.datetime(2026, 11, 19, 9, 30)
    T.set_clock(lambda tz: when.replace(tzinfo=tz))
    yield
    T.set_clock(None)


def do(doc, item, op, **args):
    return edits.execute(doc, edits.OPS[op], item, args)


def test_repeating_timestamps_are_refused_by_every_planning_edit(load, by_title):
    doc = load("repeater.org")
    for op in ("reschedule", "set_deadline"):
        for title in ("weekly review", "daily from done", "monthly catchup"):
            with pytest.raises(OrgError) as e:
                do(doc, by_title(doc, title), op, date="2026-12-01")
            assert e.value.code == "repeater_unsupported"


def test_same_date_changes_nothing(load, by_title):
    doc = load()
    alpha = by_title(doc, "alpha")
    res = do(doc, alpha, "reschedule", date="2026-11-13")
    assert not res.changed and res.text == doc.original
    res = do(doc, alpha, "set_deadline", date="2026-11-20", time="9:30")       # same moment, different padding
    assert not res.changed


def test_removing_what_is_not_there_changes_nothing(load, by_title):
    doc = load()
    gamma = by_title(doc, "gamma with no planning")
    assert not do(doc, gamma, "reschedule", remove=True).changed
    assert not do(doc, gamma, "set_deadline", remove=True).changed


@pytest.mark.parametrize("date,time", [("tomorrow", None), ("2026-02-30", None), ("2026-11-20", "25:00"),
                                      ("2026-11-20", "noon")])
def test_bad_dates_and_times(load, by_title, date, time):
    doc = load()
    with pytest.raises(OrgError) as e:
        do(doc, by_title(doc, "alpha"), "reschedule", date=date, time=time)
    assert e.value.code == "bad_date"


def test_date_is_required_unless_removing(load, by_title):
    doc = load()
    with pytest.raises(ValueError):
        do(doc, by_title(doc, "alpha"), "reschedule")


def test_warning_cookie_is_refused(load, by_title):
    from claude_files_org.config import load_config
    doc = parse("* Tasks\n** TODO x\nDEADLINE: <2026-11-20 Fri -2d>\n", load_config({}))
    with pytest.raises(OrgError) as e:
        do(doc, doc.items[1], "set_deadline", date="2026-11-25")
    assert e.value.code == "repeater_unsupported"


def test_malformed_planning_timestamp_is_unsafe(load, by_title):
    doc = load("malformed.org")
    with pytest.raises(OrgError) as e:
        do(doc, by_title(doc, "bad timestamp"), "reschedule", date="2026-11-20")
    assert e.value.code == "unsafe_structure" and "line 15" in e.value.message


def test_note_is_required(load, by_title):
    doc = load()
    for note in (None, "", "  \n"):
        with pytest.raises(OrgError) as e:
            do(doc, by_title(doc, "alpha"), "add_note", note=note)
        assert e.value.code == "note_required"


def test_unknown_tag_lists_the_configured_tags_and_changes_nothing(load, by_title):
    doc = load()
    with pytest.raises(OrgError) as e:
        do(doc, by_title(doc, "alpha"), "set_tags", tags=["stephen", "urgent"])
    assert e.value.code == "unknown_tag" and "urgent" in e.value.message and "coursework" in e.value.message


def test_tags_accept_colon_wrapped_and_duplicate_names(load, by_title):
    doc = load()
    res = do(doc, by_title(doc, "gamma with no planning"), "set_tags", tags=[":stephen:", "stephen", "jwa"])
    assert ":stephen:jwa:" in res.text


@pytest.mark.parametrize("value", ["90 minutes", "1:5", "abc", "1.5", ":30", "0:60", ""])
def test_bad_effort(load, by_title, value):
    doc = load()
    with pytest.raises((OrgError, ValueError)) as e:
        do(doc, by_title(doc, "alpha"), "set_effort", value=value)
    if isinstance(e.value, OrgError):
        assert e.value.code == "bad_effort"


def test_effort_outside_the_preferred_list_is_accepted_with_a_warning(load, by_title):
    doc = load()
    res = do(doc, by_title(doc, "gamma with no planning"), "set_effort", value="0:20")
    assert ":Effort:   0:20" in res.text and any("preferred" in w for w in res.warnings)
    ok = do(doc, by_title(doc, "gamma with no planning"), "set_effort", value="0:30")
    assert ok.warnings == []


def test_effort_hours_are_not_zero_padded(load, by_title):
    doc = load()
    assert ":Effort:   2:00" in do(doc, by_title(doc, "gamma with no planning"), "set_effort", value="02:00").text


def test_property_drawer_in_the_wrong_place_blocks_effort(load, by_title):
    doc = load("malformed.org")
    with pytest.raises(OrgError) as e:
        do(doc, by_title(doc, "invisible property drawer"), "set_effort", value="0:30")
    assert e.value.code == "unsafe_structure"


def test_add_item_returns_the_new_id_and_rev(load, by_title):
    doc = load()
    res = edits.run_oracle_op(doc, "add_item", None, {"title": "review poster draft", "tags": ["research"],
                                                      "deadline": "2026-11-23"})
    new = parse(res.text, doc.config).get(res.target_id)
    assert new.title == "review poster draft" and new.rev == res.rev and new.level == 2
    assert new.keyword == "TODO" and new.tags == ["research"] and new.created == "[2026-11-19 Thu 09:30]"
    assert new.parent.title == "Tasks"


def test_add_item_under_a_given_parent(load, by_title):
    doc = load()
    beta = by_title(doc, "beta")
    res = edits.execute(doc, edits.OPS["add_item"], beta, {"title": "b3"}, check_repeater=False)
    d2 = parse(res.text, doc.config)
    assert d2.get(res.target_id).level == 3 and d2.get(beta.id).cookie == "[0/3]"


@pytest.mark.parametrize("args", [{"title": ""}, {"title": "two\nlines"}, {"title": "ends in :tag:"},
                                  {"title": "x", "body": "* sneaky headline"}, {"title": "x", "body": "a\n:END:"}])
def test_add_item_refuses_structure_breaking_input(load, args):
    with pytest.raises(ValueError):
        edits.run_oracle_op(load(), "add_item", None, args)


def test_add_item_validates_tags_effort_and_dates(load):
    doc = load()
    for args, code in [({"title": "x", "tags": ["urgent"]}, "unknown_tag"), ({"title": "x", "effort": "soon"}, "bad_effort"),
                       ({"title": "x", "deadline": "someday"}, "bad_date")]:
        with pytest.raises(OrgError) as e:
            edits.run_oracle_op(doc, "add_item", None, args)
        assert e.value.code == code


def test_missing_inbox_heading_is_reported(load):
    from claude_files_org.config import load_config
    doc = parse("* Elsewhere\n", load_config({}))
    with pytest.raises(OrgError) as e:
        edits.run_oracle_op(doc, "add_item", None, {"title": "x"})
    assert e.value.code == "not_found" and "Tasks" in e.value.message
