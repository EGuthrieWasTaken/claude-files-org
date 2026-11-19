import datetime as dt

import pytest

from claude_files_org import timestamps as T
from claude_files_org.config import load_config
from claude_files_org.model import OrgError

F = "org-projects/inbox.org"
A = "org-projects/archive/inbox.org_archive"


@pytest.fixture(autouse=True)
def clock():
    when = dt.datetime(2026, 11, 19, 9, 30)
    T.set_clock(lambda tz: when.replace(tzinfo=tz))
    yield
    T.set_clock(None)


def freeze(y, m, d):
    when = dt.datetime(y, m, d, 9, 30)
    T.set_clock(lambda tz: when.replace(tzinfo=tz))


def find(svc, title, **kw):
    return next(i for i in svc.list_items(state="all", **kw)["items"] if i["title"] == title)


def test_archive_a_closed_project(make_service):
    svc, store = make_service("archive_cases.org")
    p = find(svc, "closed project")
    out = svc.archive(p["id"], p["rev"])
    assert out["written"] and out["archive_file"] == A and set(out["files"]) == {A, F}
    assert store.writes == [A, F]                      # the archive first, so a failure never loses the item
    src = store.files[F].decode()
    assert "closed project" not in src and "c1" not in src and "c2" not in src
    arch = store.files[A].decode()
    assert arch.startswith("#    -*- mode: org -*-\n\n\nArchived entries from file ~/.emacs.d/org-projects/inbox.org\n\n\n* DONE closed project\n")
    assert "** DONE c1" in arch and "** CANCELLED c2" in arch


def test_other_lines_of_the_source_are_untouched(make_service):
    svc, store = make_service("archive_cases.org")
    before = store.files[F].decode().split("\n")
    p = find(svc, "with effort")
    svc.archive(p["id"], p["rev"])
    after = store.files[F].decode().split("\n")
    start = before.index("** DONE with effort")
    assert after == before[:start] + before[start + 5:]


def test_open_descendants_are_listed_and_nothing_changes(make_service):
    svc, store = make_service("archive_cases.org")
    before = dict(store.files)
    p = find(svc, "old with open child")
    with pytest.raises(OrgError) as e:
        svc.archive(p["id"], p["rev"])
    assert e.value.code == "open_descendants" and "child still open" in e.value.message
    assert e.value.extra["open_descendants"][0]["title"] == "child still open"
    assert store.files == before and store.writes == []


def test_open_item_is_not_closed(make_service):
    svc, store = make_service("archive_cases.org")
    p = find(svc, "still open")
    with pytest.raises(OrgError) as e:
        svc.archive(p["id"], p["rev"])
    assert e.value.code == "not_closed" and store.writes == []


def test_stale_rev_is_refused(make_service):
    svc, store = make_service("archive_cases.org")
    p = find(svc, "closed project")
    with pytest.raises(OrgError) as e:
        svc.archive(p["id"], "000000000000")
    assert e.value.code == "stale"


def test_properties_in_orgs_order_and_the_container_path_is_not_leaked(make_service):
    svc, store = make_service("archive_cases.org")
    p = find(svc, "b1")
    svc.archive(p["id"], p["rev"])
    arch = store.files[A].decode()
    props = [l for l in arch.split("\n") if l.startswith(":ARCHIVE_")]
    assert props == [":ARCHIVE_TIME: 2026-11-19 Thu 09:30", ":ARCHIVE_FILE: ~/.emacs.d/org-projects/inbox.org",
                     ":ARCHIVE_OLPATH: Tasks/beta", ":ARCHIVE_CATEGORY: inbox", ":ARCHIVE_TODO: DONE",
                     ":ARCHIVE_ITAGS: stephen"]
    assert "/data" not in arch and "/tmp" not in arch


def test_emacs_root_is_configurable(make_service, cfg):
    svc, store = make_service("archive_cases.org", config=load_config({"ORG_EMACS_ROOT": "~/org"}))
    p = find(svc, "with effort")
    svc.archive(p["id"], p["rev"])
    assert ":ARCHIVE_FILE: ~/org/org-projects/inbox.org" in store.files[A].decode()


def test_no_itags_or_olpath_properties_when_there_are_none(make_service):
    svc, store = make_service("archive_cases.org")
    p = find(svc, "closed project")
    svc.archive(p["id"], p["rev"])
    arch = store.files[A].decode()
    assert "ARCHIVE_ITAGS" not in arch and ":ARCHIVE_OLPATH: Tasks\n" in arch


def test_parent_cookie_after_archiving_a_child(make_service):
    svc, store = make_service("archive_cases.org")
    p = find(svc, "b1")
    svc.archive(p["id"], p["rev"])
    assert "** TODO beta [0/1]" in store.files[F].decode()


def test_second_archive_is_appended(make_service):
    svc, store = make_service("archive_cases.org")
    a = find(svc, "closed project")
    svc.archive(a["id"], a["rev"])
    b = find(svc, "with effort")
    svc.archive(b["id"], b["rev"])
    arch = store.files[A].decode()
    assert arch.count("Archived entries from file") == 1
    assert arch.index("* DONE closed project") < arch.index("* DONE with effort")
    assert "\n\n* DONE with effort" in arch


def test_dry_run_archive_writes_nothing(make_service):
    svc, store = make_service("archive_cases.org")
    before = dict(store.files)
    p = find(svc, "closed project")
    out = svc.archive(p["id"], p["rev"], dry_run=True)
    assert out["dry_run"] and not out["written"] and store.files == before and store.writes == []
    assert out["files"][A]["created"] and "+* DONE closed project" in out["files"][A]["diff"]
    assert "-** DONE closed project" in out["files"][F]["diff"]


def test_archive_refuses_an_unsafe_target(make_service):
    svc, store = make_service("malformed.org")
    p = find(svc, "unclosed drawer")
    with pytest.raises(OrgError) as e:
        svc.archive(p["id"], p["rev"])
    assert e.value.code in ("unsafe_structure", "not_closed")


# -- bulk ------------------------------------------------------------------------------------------------

def test_monthly_cleanup(make_service):
    freeze(2026, 12, 19)
    svc, store = make_service("bulk.org")
    out = svc.archive_closed(older_than_days=30)
    titles = [a["title"] for a in out["archived"]]
    assert titles == ["old a", "old b with kids", "just before", "cancelled old"]
    skipped = {s["title"]: s["reason"] for s in out["skipped"]}
    assert skipped == {"old project open kid": "open_descendants", "boundary exactly": "too_recent",
                       "recent": "too_recent", "no closed date": "no_closed_date"}
    assert store.writes == [A, F]                              # one write per file
    src = store.files[F].decode()
    for stay in ("old project open kid", "boundary exactly", "recent", "no closed date", "open", "not under inbox"):
        assert stay in src
    for gone in ("old a", "old b with kids", "just before", "cancelled old"):
        assert f"DONE {gone}" not in src and f"CANCELLED {gone}" not in src
    assert "** DONE old b with kids" not in src and "*** DONE kid\n" not in src
    arch = store.files[A].decode()
    assert arch.count("Archived entries from file") == 1 and "* CANCELLED cancelled old" in arch
    assert arch.index("* DONE old a") < arch.index("* DONE old b") < arch.index("* DONE just before")


def test_item_without_closed_date_is_never_archived_by_age(make_service):
    freeze(2030, 1, 1)
    svc, store = make_service("bulk.org")
    out = svc.archive_closed(older_than_days=0)
    assert "no closed date" not in [a["title"] for a in out["archived"]]
    assert any(x["title"] == "no closed date" and x["reason"] == "no_closed_date" for x in out["skipped"])


def test_bulk_dry_run(make_service):
    freeze(2026, 12, 19)
    svc, store = make_service("bulk.org")
    before = dict(store.files)
    out = svc.archive_closed(dry_run=True)
    assert out["dry_run"] and not out["written"] and len(out["archived"]) == 4
    assert store.files == before and store.writes == []
    assert set(out["files"]) == {A, F} and out["files"][A]["created"]


def test_bulk_with_nothing_to_do_writes_nothing(make_service):
    freeze(2026, 12, 19)
    svc, store = make_service("bulk.org")
    out = svc.archive_closed(older_than_days=100000)
    assert out["archived"] == [] and not out["changed"] and store.writes == []


def test_bulk_equals_archiving_one_at_a_time(make_service):
    freeze(2026, 12, 19)
    bulk, bstore = make_service("bulk.org")
    bulk.archive_closed()
    seq, sstore = make_service("bulk.org")
    for title in ["old a", "old b with kids", "just before", "cancelled old"]:
        i = find(seq, title)
        seq.archive(i["id"], i["rev"])
    assert bstore.files == sstore.files


def test_bulk_validates_the_age(make_service):
    svc, _ = make_service("bulk.org")
    for bad in (-1, "30", None, True):
        with pytest.raises(ValueError):
            svc.archive_closed(older_than_days=bad)
