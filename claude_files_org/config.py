"""``ORG_*`` settings: defaults mirror Ethan's Emacs org configuration.

Every value is validated when :func:`load_config` runs, so a bad setting
stops the server from starting with a message that names the variable.
"""
import re
import zoneinfo
from dataclasses import dataclass, field

DEFAULTS = {
    "ORG_FILES": "org-projects/inbox.org",
    "ORG_INBOX_HEADING": "Tasks",
    "ORG_TODO_KEYWORDS": "TODO STARTED WAIT(@) | DONE CANCELLED(@)",
    "ORG_TAGS": "stephen,jwa,research,coursework,admin,personal,blog",
    "ORG_TAG_GROUPS": "personal=blog",
    "ORG_EFFORT_VALUES": "0:15 0:30 0:45 1:00 1:30 2:00 3:00 4:00 6:00 8:00",
    "ORG_ARCHIVE_DIR": "org-projects/archive",
    "ORG_EMACS_ROOT": "~/.emacs.d",
    "ORG_TIMEZONE": "America/Indiana/Indianapolis",
}

_TAG_RE = re.compile(r"^[A-Za-z0-9_@#%]+$")
_EFFORT_RE = re.compile(r"^\d+:[0-5]\d$")
_KEYWORD_RE = re.compile(r"^([^\s()|]+)(?:\(([^)]*)\))?$")


class ConfigError(ValueError):
    """A bad ``ORG_*`` setting. The message names the setting."""


@dataclass(frozen=True)
class KeywordSequence:
    """An org TODO sequence: open keywords, closed keywords and note flags."""

    open: tuple
    closed: tuple
    note: frozenset = field(default_factory=frozenset)

    @property
    def all(self):
        return self.open + self.closed

    def is_open(self, keyword):
        return keyword in self.open

    def is_closed(self, keyword):
        return keyword in self.closed

    def needs_note(self, keyword):
        return keyword in self.note

    def describe(self):
        def one(k):
            return k + "(@)" if k in self.note else k
        return " ".join(one(k) for k in self.open) + " | " + " ".join(one(k) for k in self.closed)


def parse_keyword_sequence(text, source="ORG_TODO_KEYWORDS"):
    """Parse ``TODO STARTED WAIT(@) | DONE CANCELLED(@)``.

    Fast-key letters (``(t)``) and ``!`` flags are accepted and ignored;
    ``@`` marks a keyword that requires a note. Without ``|`` the last
    keyword is the closed one, as in org.

    In ``ORG_TODO_KEYWORDS`` (only) ``;`` works as the separator too, for places that cannot carry a
    ``|`` (the unRAID template treats it as a dropdown delimiter): ``TODO NEXT ; DONE``. A file's own
    ``#+TODO:`` line is read as org reads it, where ``;`` has no meaning.
    """
    if source == "ORG_TODO_KEYWORDS":
        text = text.replace(";", " | ")
    tokens = text.split()
    if not tokens:
        raise ConfigError(f"{source}: no keywords given")
    open_, closed, note = [], [], set()
    target = open_
    seen_bar = False
    for tok in tokens:
        if tok == "|":
            if seen_bar:
                raise ConfigError(f"{source}: more than one '|' in {text!r}")
            seen_bar = True
            target = closed
            continue
        m = _KEYWORD_RE.match(tok)
        if not m:
            raise ConfigError(f"{source}: bad keyword {tok!r} in {text!r}")
        name, flags = m.group(1), m.group(2) or ""
        if not re.fullmatch(r"[A-Za-z]?[@!]{0,2}(?:/[@!]{1,2})?", flags):
            raise ConfigError(f"{source}: bad flags ({flags}) on {name} in {text!r}")
        if name in open_ or name in closed:
            raise ConfigError(f"{source}: duplicate keyword {name!r}")
        if "@" in flags:
            note.add(name)
        target.append(name)
    if not seen_bar:
        if len(open_) < 2:
            raise ConfigError(f"{source}: need at least one open and one closed keyword in {text!r}")
        closed.append(open_.pop())
    if not open_ or not closed:
        raise ConfigError(f"{source}: need at least one open and one closed keyword in {text!r}")
    return KeywordSequence(tuple(open_), tuple(closed), frozenset(note))


def _split(text, seps=r"[,\s]+"):
    return [p for p in re.split(seps, text.strip()) if p]


def _relative_path(value, source):
    value = value.strip().strip("/") if source == "ORG_ARCHIVE_DIR" else value.strip()
    if not value or value.startswith("/") or "\\" in value or "\0" in value:
        raise ConfigError(f"{source}: {value!r} must be a relative path inside the served folder")
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ConfigError(f"{source}: {value!r} must stay inside the served folder")
    return "/".join(parts)


@dataclass(frozen=True)
class Config:
    files: tuple
    inbox_heading: str
    keywords: KeywordSequence
    tags: tuple
    tag_groups: dict
    effort_values: tuple
    archive_dir: str
    emacs_root: str
    timezone_name: str

    @property
    def tz(self):
        return zoneinfo.ZoneInfo(self.timezone_name)

    def as_dict(self):
        return {
            "files": list(self.files),
            "inbox_heading": self.inbox_heading,
            "todo_keywords": self.keywords.describe(),
            "tags": list(self.tags),
            "tag_groups": {k: list(v) for k, v in self.tag_groups.items()},
            "effort_values": list(self.effort_values),
            "archive_dir": self.archive_dir,
            "emacs_root": self.emacs_root,
            "timezone": self.timezone_name,
            "log": {"done": "time", "reschedule": "time", "redeadline": "time", "into_drawer": True},
        }


def load_config(env=None):
    """Build a validated :class:`Config` from ``env`` (default: ``os.environ``)."""
    if env is None:
        import os
        env = os.environ

    def get(name):
        value = env.get(name)
        return DEFAULTS[name] if value is None or not str(value).strip() else str(value)

    files = tuple(_relative_path(p, "ORG_FILES") for p in _split(get("ORG_FILES"), r"\s*,\s*"))
    if not files:
        raise ConfigError("ORG_FILES: at least one file is required")
    heading = get("ORG_INBOX_HEADING").strip()
    if not heading or "\n" in heading:
        raise ConfigError("ORG_INBOX_HEADING: must be a single-line heading title")
    keywords = parse_keyword_sequence(get("ORG_TODO_KEYWORDS"))

    tags = tuple(_split(get("ORG_TAGS"), r"\s*,\s*|\s+"))
    for t in tags:
        if not _TAG_RE.match(t):
            raise ConfigError(f"ORG_TAGS: bad tag {t!r} (letters, digits, _ @ # % only)")
    if len(set(tags)) != len(tags):
        raise ConfigError("ORG_TAGS: duplicate tag")

    groups = {}
    for chunk in [c for c in re.split(r"\s*;\s*", get("ORG_TAG_GROUPS").strip()) if c]:
        if "=" not in chunk:
            raise ConfigError(f"ORG_TAG_GROUPS: expected parent=child[,child], got {chunk!r}")
        parent, children = chunk.split("=", 1)
        parent = parent.strip()
        members = tuple(_split(children, r"\s*,\s*"))
        if not parent or not members:
            raise ConfigError(f"ORG_TAG_GROUPS: expected parent=child[,child], got {chunk!r}")
        for t in (parent,) + members:
            if t not in tags:
                raise ConfigError(f"ORG_TAG_GROUPS: {t!r} is not in ORG_TAGS")
        if parent in groups:
            raise ConfigError(f"ORG_TAG_GROUPS: group {parent!r} given twice")
        groups[parent] = members

    efforts = tuple(_split(get("ORG_EFFORT_VALUES")))
    for e in efforts:
        if not _EFFORT_RE.match(e):
            raise ConfigError(f"ORG_EFFORT_VALUES: {e!r} is not H:MM")

    archive_dir = _relative_path(get("ORG_ARCHIVE_DIR"), "ORG_ARCHIVE_DIR")
    emacs_root = get("ORG_EMACS_ROOT").strip().rstrip("/")
    if not emacs_root:
        raise ConfigError("ORG_EMACS_ROOT: must not be empty")

    tzname = get("ORG_TIMEZONE").strip()
    try:
        zoneinfo.ZoneInfo(tzname)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        raise ConfigError(f"ORG_TIMEZONE: unknown timezone {tzname!r}") from None

    return Config(files, heading, keywords, tags, groups, efforts, archive_dir, emacs_root, tzname)
