"""Editing one item's section the way org does.

A :class:`Section` is a working copy of one item's lines (headline through the
line before the next headline). Its methods emulate the org functions the specs
name: ``org-add-planning-info``, ``org-log-beginning`` + ``org-store-log-note``,
``org-align-tags`` and ``org-update-parent-todo-statistics``. Every method keeps
untouched lines exactly as they were (including a trailing ``\\r``).
"""
import re
import unicodedata

from .model import (COOKIE_RE, DRAWER_START_RE, END_RE, HEADLINE_RE, OrgError, PLANNING_RE, PROPERTY_RE,
                    TAGS_RE)

TAGS_COLUMN = 77
_KEYS = ("CLOSED", "DEADLINE", "SCHEDULED")
_KEY_ENTRY = {k: re.compile(r"\b" + k + r": +[<\[][^\]>\n]+[>\]]") for k in _KEYS}
_NEXT_KEY = re.compile(r"\b(?:SCHEDULED|DEADLINE|CLOSED): *")


def string_width(s):
    """Display width, as Emacs ``string-width`` sees it."""
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def split_cr(line):
    return (line[:-1], "\r") if line.endswith("\r") else (line, "")


def align_headline(core, tags_column=TAGS_COLUMN):
    """Align the tags on a headline (without ``\\r``) like ``org-align-tags`` with ``org-tags-column`` -77."""
    m = TAGS_RE.search(core)
    if not m:
        return core
    tags = m.group(1)
    before = core[:m.start(1)].rstrip(" \t")
    start = max(tags_column - string_width(tags), string_width(before) + 1)
    return before + " " * (start - string_width(before)) + tags


def tag_string(tags):
    return ":" + ":".join(tags) + ":" if tags else ""


class Section:
    def __init__(self, doc, item):
        self.doc = doc
        self.eol = doc.eol
        self.lines = list(doc.lines[item.start:item.end])
        # True when the item is the last thing in a file that ends without a newline
        self.ends_without_newline = item.end == len(doc.lines)
        # True when another headline follows this section
        self.has_next_heading = item.end < len(doc.lines) - (1 if doc.lines and doc.lines[-1] == "" else 0)

    # -- structure ---------------------------------------------------------
    def core(self, i):
        return split_cr(self.lines[i])[0]

    def new_line(self, text):
        return text + self.eol

    def planning_idx(self):
        return 1 if len(self.lines) > 1 and PLANNING_RE.match(self.core(1)) else None

    def props_span(self):
        i = 1 + (1 if self.planning_idx() else 0)
        if i < len(self.lines) and self.core(i).strip().upper() == ":PROPERTIES:":
            for j in range(i + 1, len(self.lines)):
                if END_RE.match(self.core(j)):
                    return (i, j)
        return None

    def meta_end(self):
        """Index of the first line after the planning line and property drawer (``org-end-of-meta-data``)."""
        i = 1 + (1 if self.planning_idx() else 0)
        span = self.props_span()
        return span[1] + 1 if span else i

    def logbook_span(self):
        i = self.meta_end()
        while i < len(self.lines):
            dm = DRAWER_START_RE.match(self.core(i))
            if dm and dm.group(1).upper() != "END":
                end = next((j for j in range(i + 1, len(self.lines)) if END_RE.match(self.core(j))), None)
                if end is None:
                    return None
                if dm.group(1).upper() == "LOGBOOK":
                    return (i, end)
                i = end + 1
                continue
            i += 1
        return None

    # -- headline ----------------------------------------------------------
    def headline_parts(self):
        core, cr = split_cr(self.lines[0])
        m = HEADLINE_RE.match(core)
        stars, rest = m.group(1), m.group(2)
        return stars, rest

    def set_headline(self, core):
        self.lines[0] = core + split_cr(self.lines[0])[1]

    def set_keyword(self, new_keyword, known_keywords):
        """Replace (or add, or remove) the TODO keyword. Returns the old keyword or None."""
        stars, rest = self.headline_parts()
        m = re.match(r"(\S+)(?: +|$)", rest)
        old = None
        if m and m.group(1) in known_keywords:
            old = m.group(1)
            rest = rest[m.end():]
        head = stars + " " + (new_keyword + " " if new_keyword else "") + rest
        if not rest and new_keyword:
            head = stars + " " + new_keyword
        self.set_headline(head)
        return old

    def tags(self):
        _, rest = self.headline_parts()
        m = TAGS_RE.search(rest)
        return [t for t in m.group(1).strip(":").split(":") if t] if m else []

    def set_tags(self, tags):
        stars, rest = self.headline_parts()
        m = TAGS_RE.search(rest)
        if m:
            rest = rest[:m.start()]
        rest = rest.rstrip(" \t")
        head = stars + " " + rest if rest else stars + " "
        if tags:
            head = head.rstrip(" ") + " " + tag_string(tags)
            head = align_headline(head)
        else:
            head = head.rstrip(" ") if rest else head
        self.set_headline(head)

    def realign(self):
        core = split_cr(self.lines[0])[0]
        self.set_headline(align_headline(core))

    def set_cookie(self, new):
        """Replace the first statistics cookie on the headline; realign tags (``org-fix-tags-on-the-fly``)."""
        core = split_cr(self.lines[0])[0]
        m = COOKIE_RE.search(core)
        if not m or m.group(0) == new:
            return False
        self.set_headline(align_headline(core[:m.start()] + new + core[m.end():]))
        return True

    # -- planning ----------------------------------------------------------
    def planning_text(self):
        i = self.planning_idx()
        return None if i is None else self.core(i)

    def add_planning(self, what, ts, remove=()):
        """``org-add-planning-info``: drop the ``what``/``remove`` entries, then put ``what: ts`` first."""
        if self.planning_idx() is not None:
            core, cr = split_cr(self.lines[1])
            indent = core[:len(core) - len(core.lstrip(" \t"))]
            text = core[len(indent):]
            for key in ([what] if what else []) + list(remove):
                text = _drop_entry(text, key)
            if not text.strip() and not what:
                del self.lines[1]
                return
            text = text.rstrip(" \t")
            if what:
                text = f"{what}: {ts}" + (" " + text if text else "")
            self.lines[1] = indent + text + cr
        elif what:
            self.lines.insert(1, self.new_line(f"{what}: {ts}"))

    def remove_entry(self, key):
        """``org-remove-timestamp-with-keyword``: drop one entry; delete the line if it empties."""
        i = self.planning_idx()
        if i is None:
            return
        core, cr = split_cr(self.lines[i])
        m = re.search(r"\b" + key + r": +<[^>\n]+>[ \t]*", core)
        if not m:
            return
        before, after = core[:m.start()], core[m.end():]
        if before.strip() and before.endswith(" "):
            before = before[:-1]
        new = before + after
        if not new.strip():
            del self.lines[i]
        else:
            self.lines[i] = new + cr

    # -- logbook -----------------------------------------------------------
    def add_log_entry(self, text, note=None):
        """``org-log-beginning`` + ``org-store-log-note``: new entry at the top of :LOGBOOK:."""
        entry = [text + (" \\\\" if note else "")]
        if note:
            entry += [("  " + ln) if ln else "" for ln in note.split("\n")]
        entry = [self.new_line(x) for x in entry]
        span = self.logbook_span()
        if span:
            self.lines[span[0] + 1:span[0] + 1] = entry
            return
        drawer = [self.new_line(":LOGBOOK:")] + entry + [self.new_line(":END:")]
        at = self.meta_end()
        if at < len(self.lines):
            self.lines[at:at] = drawer
        elif self.ends_without_newline:
            # org adds the missing final newline before the drawer
            self.lines.extend(drawer + [""])
        elif self.has_next_heading:
            # org opens the drawer at the end of the previous line, leaving a blank line after :END:
            self.lines.extend(drawer + [self.new_line("")])
        else:
            self.lines.extend(drawer)


    # -- properties --------------------------------------------------------
    def set_property(self, key, value, padded=True):
        """Add or replace a property in the drawer (created if needed).

        ``padded`` writes ``:Effort:   0:30`` (org-set-property, ``%-10s %s``); otherwise ``:KEY: value``
        as ``org-entry-put`` does for the archive properties.
        """
        formatted = f"{':' + key + ':':<10} {value}" if padded else f":{key}: {value}"
        span = self.props_span()
        if span:
            a, b = span
            for i in range(a + 1, b):
                pm = PROPERTY_RE.match(self.core(i))
                if pm and pm.group(1).lower() == key.lower():
                    self.lines[i] = formatted + split_cr(self.lines[i])[1]
                    return
            self.lines.insert(b, self.new_line(formatted))
            return
        at = 1 + (1 if self.planning_idx() else 0)
        block = [self.new_line(x) for x in (":PROPERTIES:", formatted, ":END:")]
        if at >= len(self.lines) and self.ends_without_newline:
            self.lines.extend(block + [""])      # org adds the missing final newline
        else:
            self.lines[at:at] = block

    def delete_property(self, key):
        """``org-delete-property``: drop the line, and the whole drawer once it is empty."""
        span = self.props_span()
        if not span:
            return
        a, b = span
        for i in range(a + 1, b):
            pm = PROPERTY_RE.match(self.core(i))
            if pm and pm.group(1).lower() == key.lower():
                del self.lines[i]
                b -= 1
                break
        else:
            return
        if b == a + 1:
            del self.lines[a:b + 1]


def _drop_entry(text, key):
    m = _KEY_ENTRY[key].search(text)
    if not m:
        return text
    nxt = _NEXT_KEY.search(text, m.end())
    return text[:m.start()] + text[nxt.start() if nxt else len(text):]


def clean_note(note):
    """Validate and normalize note text the way org's note buffer is stored."""
    if note is None:
        return None
    text = note.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    text = re.sub(r"\A\s*\n", "", text)
    if not text.strip():
        return None
    for line in text.split("\n"):
        if END_RE.match(line.strip()):
            raise OrgError("unsafe_structure", "a note line may not be ':END:': it would close the logbook drawer early")
    return text
