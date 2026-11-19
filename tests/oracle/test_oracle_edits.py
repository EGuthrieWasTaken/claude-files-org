import pytest

from tests.oracle import harness as H

pytestmark = H.requires_emacs
P = "Tasks/"


# -- reschedule / deadline -----------------------------------------------------------------------------

def test_move_a_date(both):
    out = both("inbox.org", "reschedule", {"path": P + "alpha", "date": "2026-11-20"})
    assert b'- Rescheduled from "[2026-11-13 Fri]" on [2026-11-19 Thu 09:30]' in out["org-projects/inbox.org"]


def test_first_schedule_logs_nothing(both):
    both("inbox.org", "reschedule", {"path": P + "gamma with no planning", "date": "2026-11-20"})


def test_schedule_an_item_that_has_only_a_deadline(both):
    both("inbox.org", "reschedule", {"path": P + "Final Exam", "date": "2026-12-16"})


def test_time_of_day_and_range(both):
    both("inbox.org", "reschedule", {"path": P + "alpha", "date": "2026-11-20", "time": "13:00"})
    both("inbox.org", "reschedule", {"path": P + "alpha", "date": "2026-11-20", "time": "13:00-14:00"})
    both("inbox.org", "reschedule", {"path": P + "alpha", "date": "2026-11-20", "time": "9:30"})


def test_old_value_keeps_its_time_of_day(both):
    out = both("inbox.org", "set-deadline", {"path": P + "alpha", "date": "2026-11-25"})
    assert b'- New deadline from "[2026-11-20 Fri 9:30]" on [2026-11-19 Thu 09:30]' in out["org-projects/inbox.org"]


def test_new_deadline_goes_first_on_the_planning_line(both):
    both("inbox.org", "set-deadline", {"path": P + "beta/b1", "date": "2026-11-30"})


def test_rescheduling_a_closed_item_drops_closed(both):
    both("shapes.org", "reschedule", {"path": P + "closed and scheduled and deadline", "date": "2026-12-01"})
    both("shapes.org", "set-deadline", {"path": P + "closed and scheduled and deadline", "date": "2026-12-01"})


def test_remove_a_deadline(both):
    out = both("inbox.org", "set-deadline", {"path": P + "alpha", "remove": True})
    assert b'- Removed deadline, was "[2026-11-20 Fri 9:30]" on [2026-11-19 Thu 09:30]' in out["org-projects/inbox.org"]


def test_remove_a_schedule_and_the_planning_line_when_empty(both):
    both("inbox.org", "reschedule", {"path": P + "beta/b1", "remove": True})
    both("shapes.org", "reschedule", {"path": P + "planning only", "remove": True})


def test_remove_one_of_two_entries(both):
    both("inbox.org", "reschedule", {"path": P + "alpha", "remove": True})


def test_logbook_after_the_property_drawer(both):
    both("shapes.org", "reschedule", {"path": P + "planning and props only", "date": "2026-11-20"})


def test_reschedule_with_a_note(both):
    both("inbox.org", "reschedule", {"path": P + "alpha", "date": "2026-11-27", "note": "Stephen is away that week."})


def test_deadline_with_a_note_into_a_new_logbook(both):
    both("shapes.org", "set-deadline", {"path": P + "deadline only", "date": "2026-11-30", "note": "moved"})


# -- notes ---------------------------------------------------------------------------------------------------

def test_plain_note(both):
    both("inbox.org", "add-note", {"path": P + "zeta", "note": "reply from Stephen on the draft"})


def test_multi_line_note_with_a_blank_line(both):
    both("inbox.org", "add-note", {"path": P + "alpha", "note": "line one\nline two\n\nline four"})


def test_note_creates_logbook_in_every_shape(both):
    for title in ["bare heading, then next heading", "planning only", "planning and props only", "props only",
                  "body follows", "blank line follows", "blank then body", "has other drawer", "last item, bare"]:
        both("shapes.org", "add-note", {"path": P + title, "note": "n"})


# -- tags ---------------------------------------------------------------------------------------------------

def test_aligned_tags(both):
    both("inbox.org", "set-tags", {"path": P + "gamma with no planning", "tags": ["stephen", "research"]})


def test_tags_replace_and_reorder(both):
    both("inbox.org", "set-tags", {"path": P + "alpha", "tags": ["research", "stephen", "admin"]})


def test_long_headline_tags_follow_after_one_space(both):
    both("inbox.org", "set-tags", {"path": P + "a headline that is deliberately very long so that the tags cannot be aligned at column 77 any more",
                                    "tags": ["stephen", "research"]})


def test_remove_tags(both):
    both("inbox.org", "set-tags", {"path": P + "alpha", "tags": []})


def test_tag_group_members_together(both):
    both("inbox.org", "set-tags", {"path": P + "gamma with no planning", "tags": ["personal", "blog"]})


def test_tags_on_a_headline_with_a_cookie(both):
    both("cookies.org", "set-tags", {"path": P + "no cookie parent", "tags": ["jwa"]})


# -- effort -------------------------------------------------------------------------------------------------

def test_effort_in_every_shape(both):
    for title in ["planning only", "bare heading, then next heading", "props only", "body follows",
                  "planning and props only", "has other drawer", "last item, bare", "blank line follows"]:
        both("shapes.org", "set-effort", {"path": P + title, "value": "0:45"})


def test_effort_replace_and_odd_spacing(both):
    both("shapes_effort.org", "set-effort", {"path": P + "odd spacing", "value": "0:45"})
    both("shapes_effort.org", "set-effort", {"path": P + "lowercase key", "value": "0:45"})
    both("shapes_effort.org", "set-effort", {"path": P + "other props first", "value": "0:45"})
    both("shapes_effort.org", "set-effort", {"path": P + "two props", "value": "2:00"})


def test_effort_remove(both):
    both("shapes_effort.org", "set-effort", {"path": P + "odd spacing", "remove": True})
    both("shapes_effort.org", "set-effort", {"path": P + "two props", "remove": True})
    both("inbox.org", "set-effort", {"path": P + "alpha", "remove": True})


def test_effort_drawer_with_blank_lines_after(both):
    both("shapes_effort.org", "set-effort", {"path": P + "blank lines after", "value": "1:30"})


@pytest.mark.parametrize("fixture", ["shapes_eof_no_newline.org", "shapes_eof_planning_no_newline.org"])
def test_effort_at_end_of_file_without_newline(both, fixture):
    both(fixture, "set-effort", {"path": P + "last item no newline", "value": "0:30"})


# -- add item -----------------------------------------------------------------------------------------------

def test_add_to_the_inbox(both):
    out = both("inbox.org", "add-item", {"title": "review poster draft", "tags": ["research"],
                                         "planning": "DEADLINE: <2026-11-23 Mon>"})
    text = out["org-projects/inbox.org"].decode()
    assert "** TODO review poster draft" in text and text.index("review poster draft") < text.index("* Reference")


def test_add_plain_item_with_everything(both):
    both("inbox.org", "add-item", {"title": "write the summary", "tags": ["stephen", "jwa"], "effort": "0:30",
                                   "planning": "SCHEDULED: <2026-11-24 Tue> DEADLINE: <2026-11-27 Fri>",
                                   "body": "First line.\nSecond line."})


def test_add_to_a_file_where_the_inbox_is_last(both):
    both("inbox_at_eof.org", "add-item", {"title": "x"})
    both("inbox_at_eof_no_newline.org", "add-item", {"title": "x", "tags": ["admin"]})


def test_add_after_trailing_blank_lines(both):
    both("trailing_blank.org", "add-item", {"title": "x", "parent": "Other"})
    both("trailing_blank.org", "add-item", {"title": "x", "parent": "Tasks"})


def test_add_swallows_every_trailing_blank_line(both):
    both("trailing_blank2.org", "add-item", {"title": "x"})
    both("trailing_blank_eof.org", "add-item", {"title": "x"})


def test_add_a_subtask_updates_the_parent_cookie(both):
    both("trailing_blank.org", "add-item", {"title": "b2", "parent": "Other/b"})
    both("cookies.org", "add-item", {"title": "p4", "parent": "Tasks/pct"})
