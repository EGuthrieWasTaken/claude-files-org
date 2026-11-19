import datetime as dt
import zoneinfo

import pytest

from claude_files_org import timestamps as T

IND = zoneinfo.ZoneInfo("America/Indiana/Indianapolis")


def test_parse_active_with_single_digit_hour_round_trips():
    ts = T.parse_timestamp("<2026-11-20 Fri 9:30>")
    assert ts.active and ts.date == dt.date(2026, 11, 20) and ts.start == "9:30"
    assert ts.raw == "<2026-11-20 Fri 9:30>"
    assert ts.inactive_text() == "[2026-11-20 Fri 9:30]"


def test_parse_inactive_range_and_date_only():
    ts = T.parse_timestamp("[2026-11-20 Fri 13:00-14:00]")
    assert not ts.active and (ts.start, ts.end) == ("13:00", "14:00")
    assert T.parse_timestamp("<2026-11-20 Fri>").start is None
    assert T.parse_timestamp("<2026-11-20>").date == dt.date(2026, 11, 20)


@pytest.mark.parametrize("text", [
    "<2026-02-11 Wed: 12:30>", "<2026-13-01 Mon>", "<2026-02-30 Mon>", "<2026-11-20 Fri 25:00>",
    "<2026-11-20 Fri>>", "(2026-11-20)", "<2026-11-20 Fri 9:3>", "[2026-11-20 Fri>",
])
def test_malformed_timestamps_are_none(text):
    assert T.parse_timestamp(text) is None


def test_cookies_are_detected_but_never_written():
    for text, rep, warn in [("<2026-11-20 Fri +1w>", True, False), ("<2026-11-21 Sat .+1d>", True, False),
                            ("<2026-11-22 Sun ++1m>", True, False), ("<2026-11-20 Fri -2d>", False, True),
                            ("<2026-11-20 Fri +1w -2d>", True, True)]:
        ts = T.parse_timestamp(text)
        assert (ts.has_repeater, ts.has_warning) == (rep, warn), text
    assert T.format_timestamp(dt.date(2026, 11, 20)) == "<2026-11-20 Fri>"


def test_format_with_time_and_range_and_inactive():
    d = dt.date(2026, 11, 20)
    assert T.format_timestamp(d, "13:00") == "<2026-11-20 Fri 13:00>"
    assert T.format_timestamp(d, "13:00", "14:00") == "<2026-11-20 Fri 13:00-14:00>"
    assert T.format_timestamp(d, "09:30", active=False) == "[2026-11-20 Fri 09:30]"


def test_english_day_abbreviations():
    assert [T.DAYS[(dt.date(2026, 11, 16) + dt.timedelta(days=i)).weekday()] for i in range(7)] == \
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def test_build_timestamp_arguments():
    assert T.build_timestamp("2026-11-20") == "<2026-11-20 Fri>"
    assert T.build_timestamp("2026-11-20", "13:00") == "<2026-11-20 Fri 13:00>"
    assert T.build_timestamp("2026-11-20", "9:30") == "<2026-11-20 Fri 09:30>"
    assert T.build_timestamp("2026-11-20", "13:00-14:00") == "<2026-11-20 Fri 13:00-14:00>"


@pytest.mark.parametrize("date,time", [("tomorrow", None), ("2026-02-30", None), ("2026-11-20", "25:00"),
                                      ("2026-11-20", "noon"), ("2026-11-20", "1:00-2:00-3:00")])
def test_bad_arguments(date, time):
    with pytest.raises(T.TimestampError):
        T.build_timestamp(date, time)


def test_same_moment_ignores_zero_padding():
    a, b = T.parse_timestamp("<2026-11-20 Fri 9:30>"), T.parse_timestamp("<2026-11-20 Fri 09:30>")
    assert a.same_moment(b)
    assert not a.same_moment(T.parse_timestamp("<2026-11-20 Fri>"))


def test_indiana_evening_is_not_utc():
    utc = dt.datetime(2026, 11, 20, 3, 30, tzinfo=dt.timezone.utc)
    T.set_clock(lambda tz: utc.astimezone(tz))
    try:
        assert T.stamp(T.now(IND)) == "[2026-11-19 Thu 22:30]"
        assert T.today(IND) == dt.date(2026, 11, 19)
    finally:
        T.set_clock(None)


def test_single_digit_hour_survives_find_timestamps():
    line = "DEADLINE: <2026-11-20 Fri 9:30> SCHEDULED: <2026-11-13 Fri>"
    found = [ts.raw for ts, _ in T.find_timestamps(line)]
    assert found == ["<2026-11-20 Fri 9:30>", "<2026-11-13 Fri>"]
