"""Org timestamps: reading, writing, and the clock in ``ORG_TIMEZONE``."""
import datetime as _dt
import re
from dataclasses import dataclass
from typing import Optional

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_TS_RE = re.compile(
    r"(?P<open>[<\[])"
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?: +(?P<dow>[A-Za-z]+))?"
    r"(?: +(?P<t1>\d{1,2}:\d{2})(?:-(?P<t2>\d{1,2}:\d{2}))?)?"
    r"(?P<cookies>(?: +(?:[.+]?\+|--?)\d+[hdwmy](?:/\d+[hdwmy])?)*)"
    r"(?P<close>[>\]])"
)
_REPEATER_RE = re.compile(r"(?:^| )[.+]?\+\d+[hdwmy]")
_WARNING_RE = re.compile(r"(?:^| )--?\d+[hdwmy]")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class TimestampError(ValueError):
    """Bad date or time argument (reported to agents as ``bad_date``)."""


@dataclass(frozen=True)
class Timestamp:
    """An org timestamp, remembering its exact source text."""

    raw: str
    active: bool
    date: _dt.date
    start: Optional[str] = None   # "9:30" or "09:30": text as written
    end: Optional[str] = None
    cookies: str = ""

    @property
    def has_repeater(self):
        return bool(_REPEATER_RE.search(self.cookies))

    @property
    def has_warning(self):
        return bool(_WARNING_RE.search(self.cookies))

    def inner(self):
        return self.raw[1:-1]

    def inactive_text(self):
        """``[..]`` form with the same inner text (time of day kept as written)."""
        return "[" + self.inner() + "]"

    def same_moment(self, other):
        return (self.date, _norm_time(self.start), _norm_time(self.end)) == (
            other.date, _norm_time(other.start), _norm_time(other.end))


def _norm_time(t):
    if t is None:
        return None
    h, m = t.split(":")
    return f"{int(h):02d}:{m}"


def parse_timestamp(text):
    """Return a :class:`Timestamp` if ``text`` is exactly one valid org timestamp, else None."""
    m = _TS_RE.fullmatch(text.strip())
    return _from_match(m) if m else None


def _from_match(m):
    try:
        date = _dt.date.fromisoformat(m.group("date"))
    except ValueError:
        return None
    for key in ("t1", "t2"):
        t = m.group(key)
        if t and not _valid_hm(t):
            return None
    opener, closer = m.group("open"), m.group("close")
    if (opener, closer) not in (("<", ">"), ("[", "]")):
        return None
    return Timestamp(m.group(0), opener == "<", date, m.group("t1"), m.group("t2"),
                     m.group("cookies").strip())


def _valid_hm(t):
    h, mi = _TIME_RE.match(t).groups()
    return 0 <= int(h) <= 23 and 0 <= int(mi) <= 59


def find_timestamps(line):
    """Yield every well-formed timestamp found in ``line`` with its (start, end) span."""
    for m in _TS_RE.finditer(line):
        ts = _from_match(m)
        if ts:
            yield ts, m.span()


def format_timestamp(date, start=None, end=None, active=True):
    """Write a timestamp as org does: ``<2026-11-20 Fri 13:00-14:00>``."""
    parts = [date.isoformat(), DAYS[date.weekday()]]
    if start:
        parts.append(start if not end else f"{start}-{end}")
    inner = " ".join(parts)
    return f"<{inner}>" if active else f"[{inner}]"


def parse_time_arg(value):
    """``13:00``, ``9:30`` or ``13:00-14:00`` -> ("13:00", None) / ("13:00", "14:00") (zero padded)."""
    if value is None or value == "":
        return None, None
    parts = value.strip().split("-")
    if len(parts) > 2:
        raise TimestampError(f"bad time {value!r}: use H:MM, HH:MM or HH:MM-HH:MM")
    out = []
    for p in parts:
        m = _TIME_RE.match(p.strip())
        if not m or not _valid_hm(p.strip()):
            raise TimestampError(f"bad time {value!r}: use H:MM, HH:MM or HH:MM-HH:MM")
        out.append(f"{int(m.group(1)):02d}:{m.group(2)}")
    return out[0], (out[1] if len(out) == 2 else None)


def parse_date_arg(value):
    try:
        return _dt.date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        raise TimestampError(f"bad date {value!r}: use YYYY-MM-DD") from None


def build_timestamp(date, time=None, active=True):
    """Build a timestamp from tool arguments (``date`` is YYYY-MM-DD text)."""
    d = parse_date_arg(date)
    start, end = parse_time_arg(time)
    return format_timestamp(d, start, end, active)


# -- the clock ---------------------------------------------------------------

_clock = None


def set_clock(fn):
    """Replace the clock (tests). ``fn(tz)`` returns an aware datetime; ``None`` restores the real one."""
    global _clock
    _clock = fn


def now(tz):
    """Current wall-clock time in ``tz``, never UTC."""
    if _clock is not None:
        return _clock(tz)
    return _dt.datetime.now(tz)


def today(tz):
    return now(tz).date()


def stamp(dt, active=False, with_time=True):
    """``[2026-11-19 Thu 09:30]`` for a datetime (zero padded %H:%M, as org's %t/%T)."""
    d = dt.date() if hasattr(dt, "date") else dt
    return format_timestamp(d, dt.strftime("%H:%M") if with_time else None, None, active)
