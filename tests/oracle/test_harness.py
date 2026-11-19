"""Sanity checks for the oracle itself: it must agree with hand-written expectations."""
import subprocess

import pytest

from tests.oracle import harness as H
from tests.conftest import fixture_text

pytestmark = H.requires_emacs


def test_oracle_pin_is_emacs_29_3_org_9_6_15():
    out = subprocess.run([H.EMACS, "--batch", "-Q", "--eval", "(progn (require 'org) (princ (format \"%s org %s\" emacs-version (org-version))))"],
                         capture_output=True, text=True, timeout=60).stdout
    assert out.strip() == "29.3 org 9.6.15", f"oracle pin changed: {out!r} (bump the pin in CI too)"


def test_reschedule_in_elisp_matches_a_hand_written_file(tmp_path):
    home = H.make_folder(tmp_path)
    tree = H.emacs_apply(home, "reschedule", {"path": "Tasks/alpha", "date": "2026-11-20"})
    original = fixture_text("inbox.org")
    expected = original.replace("SCHEDULED: <2026-11-13 Fri> DEADLINE: <2026-11-20 Fri 9:30>",
                                "SCHEDULED: <2026-11-20 Fri> DEADLINE: <2026-11-20 Fri 9:30>", 1)
    expected = expected.replace(":LOGBOOK:\n- Rescheduled from \"[2026-11-06 Fri]\"",
                                ":LOGBOOK:\n- Rescheduled from \"[2026-11-13 Fri]\" on [2026-11-19 Thu 09:30]\n"
                                "- Rescheduled from \"[2026-11-06 Fri]\"", 1)
    assert tree["org-projects/inbox.org"].decode() == expected


def test_clock_is_frozen_and_in_indiana_time(tmp_path):
    home = H.make_folder(tmp_path)
    tree = H.emacs_apply(home, "set-state", {"path": "Tasks/gamma with no planning", "state": "DONE"},
                         now="2026-11-19 22:30")
    assert "CLOSED: [2026-11-19 Thu 22:30]" in tree["org-projects/inbox.org"].decode()


def test_archive_time_is_masked_but_format_checked(tmp_path):
    a = {"x": b":ARCHIVE_TIME: 2026-11-19 Thu 09:30\n"}
    b = {"x": b":ARCHIVE_TIME: 2030-01-01 Tue 00:00\n"}
    H.assert_same_tree(a, b)
    with pytest.raises(pytest.fail.Exception):
        H.assert_same_tree({"x": b"one\n"}, {"x": b"two\n"})
    with pytest.raises(AssertionError):
        H.check_archive_time_format({"x": b":ARCHIVE_TIME: yesterday\n"} | {"y": b":ARCHIVE_TIME: 2026-1-1\n"})
