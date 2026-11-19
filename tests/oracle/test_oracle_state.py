import pytest

from tests.oracle import harness as H

pytestmark = H.requires_emacs

P = "Tasks/"


def test_done_with_planning_line(both):
    out = both("inbox.org", "set-state", {"path": P + "alpha", "state": "DONE"})
    assert b"CLOSED: [2026-11-19 Thu 09:30] SCHEDULED: <2026-11-13 Fri> DEADLINE: <2026-11-20 Fri 9:30>" in out["org-projects/inbox.org"]


def test_done_without_planning_line(both):
    both("inbox.org", "set-state", {"path": P + "gamma with no planning", "state": "DONE"})


def test_cancelled_with_a_note(both):
    both("inbox.org", "set-state", {"path": P + "alpha", "state": "CANCELLED",
                                     "note": "Superseded by the entry with the real date and room."})


def test_wait_with_a_note_creates_the_logbook(both):
    both("inbox.org", "set-state", {"path": P + "gamma with no planning", "state": "WAIT", "note": "blocked on Stephen"})


def test_wait_with_a_note_into_an_existing_logbook(both):
    both("inbox.org", "set-state", {"path": P + "alpha", "state": "WAIT", "note": "waiting\nfor two things"})


def test_reopen_removes_closed_and_the_empty_planning_line(both):
    both("shapes.org", "set-state", {"path": P + "closed only", "state": "TODO"})


def test_reopen_keeps_other_planning_entries(both):
    both("shapes.org", "set-state", {"path": P + "closed and scheduled and deadline", "state": "STARTED"})


def test_between_closed_states_keeps_closed(both):
    both("shapes.org", "set-state", {"path": P + "closed only", "state": "CANCELLED", "note": "dropped"})


def test_keyword_added_to_a_headline_without_one(both):
    both("inbox.org", "set-state", {"path": P + "Midterm 1", "state": "TODO"})


def test_child_closes_cookie(both):
    out = both("inbox.org", "set-state", {"path": P + "beta/b1", "state": "DONE"})
    assert b"** TODO beta [1/2]" in out["org-projects/inbox.org"]


def test_percent_cookie(both):
    both("cookies.org", "set-state", {"path": P + "pct/p2", "state": "DONE"})


def test_cookie_growth_realigns_tags(both):
    both("cookies.org", "set-state", {"path": P + "big/x10", "state": "DONE"})


def test_only_the_direct_parent_cookie_is_updated(both):
    out = both("cookies.org", "set-state", {"path": P + "grand/mid/m1", "state": "DONE"})
    assert b"** TODO grand [0/1]" in out["org-projects/inbox.org"]


def test_keywordless_children_are_not_counted(both):
    both("cookies.org", "set-state", {"path": P + "no cookie parent/n1", "state": "DONE"})


def test_longer_keyword_realigns_tags(both):
    both("inbox.org", "set-state", {"path": P + "alpha", "state": "STARTED"})


def test_closing_in_the_evening_uses_indiana_time(both):
    both("inbox.org", "set-state", {"path": P + "alpha", "state": "DONE"}, now="2026-11-19 22:30")


@pytest.mark.parametrize("fixture", ["shapes_eof_no_newline.org", "shapes_eof_planning_no_newline.org"])
def test_logbook_at_end_of_file_without_newline(both, fixture):
    both(fixture, "set-state", {"path": P + "last item no newline", "state": "WAIT", "note": "n"})


def test_logbook_after_each_meta_shape(both):
    for title in ["bare heading, then next heading", "planning only", "planning and props only", "props only",
                  "body follows", "blank line follows", "blank then body", "has other drawer", "deadline only",
                  "last item, bare"]:
        both("shapes.org", "set-state", {"path": P + title, "state": "WAIT", "note": "why"})
