import pytest

from tests.oracle import harness as H

pytestmark = H.requires_emacs
P = "Tasks/"
A = "org-projects/archive/inbox.org_archive"


def test_archive_a_closed_project_with_closed_children(both):
    out = both("archive_cases.org", "archive", {"path": P + "closed project"})
    assert out[A].startswith(b"#    -*- mode: org -*-\n")
    assert b"* DONE closed project" in out[A] and b"** DONE c1" in out[A] and b"closed project" not in out["org-projects/inbox.org"]


def test_archive_a_subtask_with_inherited_tags_and_update_the_cookie(both):
    out = both("archive_cases.org", "archive", {"path": P + "beta/b1"})
    assert b":ARCHIVE_ITAGS: stephen" in out[A] and b":ARCHIVE_OLPATH: Tasks/beta" in out[A]
    assert b"** TODO beta [0/1]" in out["org-projects/inbox.org"]


def test_archive_into_an_existing_property_drawer(both):
    out = both("archive_cases.org", "archive", {"path": P + "with effort"})
    assert out[A].count(b":PROPERTIES:") == 1 and out[A].index(b":Effort:") < out[A].index(b":ARCHIVE_TIME:")


def test_archive_keeps_logbooks_and_bodies_and_adds_properties_after_the_planning_line(both):
    both("archive_drawers.org", "archive", {"path": P + "with logbook"})
    both("archive_drawers.org", "archive", {"path": P + "with props and logbook"})
    both("archive_drawers.org", "archive", {"path": P + "no planning"})


def test_inherited_tags_from_several_ancestors(both):
    both("archive_tags.org", "archive", {"path": P + "p/c"})
    both("archive_tags.org", "archive", {"path": P + "p/c/gc"})


def test_level_shift_of_descendants(both):
    out = both("archive_tags.org", "archive", {"path": P + "p/c"})
    assert b"* DONE c\n" in out[A] and b"** DONE gc" in out[A]


def test_second_archive_appends_after_the_first(both):
    existing = (b"#    -*- mode: org -*-\n\n\nArchived entries from file ~/.emacs.d/org-projects/inbox.org\n\n\n"
                b"* DONE earlier\n:PROPERTIES:\n:ARCHIVE_TIME: 2026-10-01 Thu 09:00\n:END:\n")
    both("archive_cases.org", "archive", {"path": P + "closed project"}, extra={A: existing})


def test_existing_archive_without_a_final_newline(both):
    both("archive_cases.org", "archive", {"path": P + "closed project"}, extra={A: b"* old entry\nno newline at end"})


def test_blank_lines_after_the_subtree_travel_with_it(both):
    both("archive_blank.org", "archive", {"path": P + "a"})
    both("archive_blank.org", "archive", {"path": P + "b"})


def test_archiving_the_last_item_of_a_file(both):
    both("archive_eof.org", "archive", {"path": P + "last with newline"})
    both("archive_eof_no_newline.org", "archive", {"path": P + "last no newline"})


def test_archive_time_comes_from_the_configured_timezone(both):
    both("archive_cases.org", "archive", {"path": P + "closed project"}, now="2026-11-19 22:30", mask_archive=False)


def test_bulk_archive_equals_archiving_one_by_one_in_emacs(tmp_path):
    """org_archive_closed == org-archive-subtree applied to each old closed item in file order."""
    import datetime as dt
    from claude_files_org import timestamps as T
    from claude_files_org.config import load_config
    from claude_files_org.service import OrgService
    from tests.conftest import DirStore

    now = "2026-12-19 09:30"
    emacs_home = H.make_folder(tmp_path, "bulk.org", name="emacs")
    tool_home = H.make_folder(tmp_path, "bulk.org", name="tool")
    for title in ["old a", "old b with kids", "just before", "cancelled old"]:
        expected = H.emacs_apply(emacs_home, "archive", {"path": P + title}, now=now)
    when = dt.datetime(2026, 12, 19, 9, 30)
    T.set_clock(lambda tz: when.replace(tzinfo=tz))
    try:
        OrgService(load_config({}), DirStore(tool_home / ".emacs.d")).archive_closed(older_than_days=30)
    finally:
        T.set_clock(None)
    expected = {k: v.replace(str(emacs_home).encode(), b"~") for k, v in expected.items()}
    H.assert_same_tree(expected, H.read_tree(tool_home))
