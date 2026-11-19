import datetime as dt
import hashlib

import pytest

from claude_files_org import timestamps as T
from claude_files_org.model import OrgError

F = "org-projects/inbox.org"


@pytest.fixture(autouse=True)
def clock():
    when = dt.datetime(2026, 11, 19, 9, 30)
    T.set_clock(lambda tz: when.replace(tzinfo=tz))
    yield
    T.set_clock(None)


def items(svc, **kw):
    return {i["title"]: i for i in svc.list_items(**kw)["items"]}


def reschedules(svc, titles, date="2026-11-30"):
    by = items(svc, state="all")
    return [{"op": "reschedule", "id": by[t]["id"], "rev": by[t]["rev"], "date": date} for t in titles]


def test_weekly_rebalance_is_one_write_and_one_diff(make_service):
    svc, store = make_service("clean.org")
    by = items(svc, state="all")
    plan = [{"op": "reschedule", "id": by[t]["id"], "rev": by[t]["rev"], "date": f"2026-11-{20 + i}"}
            for i, t in enumerate(["alpha", "b1", "b2"])]
    plan += [{"op": "set_deadline", "id": by["alpha"]["id"], "rev": by["alpha"]["rev"], "date": "2026-12-01"},
             {"op": "set_tags", "id": by["b2"]["id"], "rev": by["b2"]["rev"], "tags": ["admin"]},
             {"op": "add_note", "id": by["b2"]["id"], "rev": by["b2"]["rev"], "note": "moved with the rest"}]
    out = svc.edit(plan)
    assert out["written"] and len(store.writes) == 1 and len(out["results"]) == 6
    assert list(out["files"]) == [F] and out["diff"].count("--- a/") == 1
    assert [r["index"] for r in out["results"]] == [1, 2, 3, 4, 5, 6]
    new = items(svc)
    assert new["alpha"]["scheduled"] == "2026-11-20" and new["alpha"]["deadline"] == "2026-12-01"


def test_twelve_reschedules_apply_in_one_write(make_service):
    svc, store = make_service("inbox.org")
    open_items = [i for i in svc.list_items()["items"] if i["scheduled"] or i["deadline"] or True][:12]
    plan = [{"op": "reschedule", "id": i["id"], "rev": i["rev"], "date": "2026-12-%02d" % (n + 1)}
            for n, i in enumerate(open_items)]
    out = svc.edit(plan)
    assert len(out["results"]) == 12 and len(store.writes) == 1 and out["diff"].count("--- a/") == 1


def test_revs_are_checked_against_the_file_as_read(make_service):
    svc, store = make_service("clean.org")
    a = items(svc)["alpha"]
    out = svc.edit([{"op": "reschedule", "id": a["id"], "rev": a["rev"], "date": "2026-11-21"},
                    {"op": "set_deadline", "id": a["id"], "rev": a["rev"], "date": "2026-11-30"}])
    assert len(out["results"]) == 2 and out["results"][0]["rev"] == out["results"][1]["rev"] != a["rev"]


def test_one_stale_edit_applies_nothing_and_names_the_edit(make_service):
    svc, store = make_service("clean.org")
    before = dict(store.files)
    by = items(svc, state="all")
    plan = reschedules(svc, ["alpha", "b1", "b2", "overdue deadline", "beta"])
    plan[2]["rev"] = "000000000000"                         # the third edit is stale
    with pytest.raises(OrgError) as e:
        svc.edit(plan)
    assert e.value.code == "stale" and e.value.extra["failed_edit"] == 3 and "edit 3" in e.value.message
    assert e.value.extra["current"]["title"] == "b2"
    assert store.files == before and store.writes == []


def test_a_failing_edit_late_in_the_batch_applies_nothing(make_service):
    svc, store = make_service("clean.org")
    before = dict(store.files)
    plan = reschedules(svc, ["alpha", "b1"])
    by = items(svc)
    plan.append({"op": "set_tags", "id": by["b2"]["id"], "rev": by["b2"]["rev"], "tags": ["urgent"]})
    with pytest.raises(OrgError) as e:
        svc.edit(plan)
    assert e.value.code == "unknown_tag" and e.value.extra["failed_edit"] == 3
    assert store.files == before


def test_argument_errors_name_the_edit_too(make_service):
    svc, store = make_service("clean.org")
    plan = reschedules(svc, ["alpha"]) + [{"op": "nonsense", "id": "x", "rev": "y"}]
    with pytest.raises(ValueError) as e:
        svc.edit(plan)
    assert "edit 2" in str(e.value)
    with pytest.raises(ValueError):
        svc.edit([])
    with pytest.raises(ValueError) as e:
        svc.edit([{"op": "reschedule", "id": "x"}])
    assert "edit 1" in str(e.value) and "rev" in str(e.value)


def test_unrelated_change_elsewhere_does_not_make_an_edit_stale(make_service):
    svc, store = make_service("clean.org")
    by = items(svc)
    # somebody else edits a different item after we read
    raw = store.files[F].decode().replace("** TODO overdue deadline\nDEADLINE: <2026-11-10 Tue>",
                                          "** TODO overdue deadline\nDEADLINE: <2026-11-12 Thu>")
    store.files[F] = raw.encode()
    out = svc.edit([{"op": "reschedule", "id": by["alpha"]["id"], "rev": by["alpha"]["rev"], "date": "2026-11-21"}])
    assert out["written"]


def test_dry_run_returns_the_diff_and_writes_nothing(make_service):
    svc, store = make_service("clean.org")
    a = items(svc)["alpha"]
    before = hashlib.sha256(store.files[F]).hexdigest()
    out = svc.edit_one("reschedule", a["id"], a["rev"], dry_run=True, date="2026-11-21")
    assert out["dry_run"] and out["changed"] and not out["written"]
    assert "-SCHEDULED: <2026-11-13 Fri>" in out["diff"] and "+SCHEDULED: <2026-11-21 Sat>" in out["diff"]
    assert hashlib.sha256(store.files[F]).hexdigest() == before and store.writes == []
    assert out["files"][F]["sha256_before"] == before and out["files"][F]["sha256"] != before
    real = svc.edit_one("reschedule", a["id"], a["rev"], date="2026-11-21")
    assert real["diff"] == out["diff"] and real["files"][F]["sha256"] == out["files"][F]["sha256"]
    assert hashlib.sha256(store.files[F]).hexdigest() == real["files"][F]["sha256"]
    assert out["rev"] == real["rev"]


def test_dry_run_of_a_failing_edit_still_fails(make_service):
    svc, store = make_service("clean.org")
    with pytest.raises(OrgError):
        svc.edit_one("set_state", items(svc)["alpha"]["id"], "stale", dry_run=True, state="DONE")


def test_no_op_edit_writes_nothing(make_service):
    svc, store = make_service("clean.org")
    a = items(svc)["alpha"]
    out = svc.edit_one("reschedule", a["id"], a["rev"], date="2026-11-13")
    assert not out["changed"] and not out["written"] and out["diff"] == "" and store.writes == []
    assert out["rev"] == a["rev"]


def test_add_item_in_a_batch(make_service):
    svc, store = make_service("clean.org")
    by = items(svc)
    out = svc.edit([{"op": "add_item", "title": "new one", "tags": ["admin"]},
                    {"op": "add_item", "title": "new child", "id": by["beta"]["id"], "rev": by["beta"]["rev"]}])
    assert len(out["results"]) == 2
    new = items(svc)
    assert new["new one"]["level"] == 2 and new["new child"]["level"] == 3 and new["beta"]["cookie"] == "[1/3]"
    assert out["results"][0]["id"] == new["new one"]["id"] and out["results"][0]["rev"] == new["new one"]["rev"]


def test_edits_to_files_outside_the_set_are_refused(make_service):
    svc, store = make_service("clean.org", extra={"config.org": b"* x\n"})
    with pytest.raises(OrgError) as e:
        svc.edit(reschedules(svc, ["alpha"]), file="config.org")
    assert e.value.code == "file_not_allowed" and "org-projects/inbox.org" in e.value.message
    with pytest.raises(OrgError):
        svc.list_items(file="../etc/passwd")
    assert svc.resolve_file("./org-projects/inbox.org") == F


def test_sequential_edits_hold_the_lock_so_neither_is_lost(make_service):
    import threading
    svc, store = make_service("clean.org")
    by = items(svc)
    errors = []

    def go(title, date):
        try:
            svc.edit_one("reschedule", by[title]["id"], by[title]["rev"], date=date)
        except Exception as e:                      # pragma: no cover
            errors.append(e)
    ts = [threading.Thread(target=go, args=(t, d)) for t, d in [("alpha", "2026-11-21"), ("b2", "2026-11-22"),
                                                                  ("beta", "2026-11-23")]]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    new = items(svc)
    assert (new["alpha"]["scheduled"], new["b2"]["scheduled"], new["beta"]["scheduled"]) == \
        ("2026-11-21", "2026-11-22", "2026-11-23")
