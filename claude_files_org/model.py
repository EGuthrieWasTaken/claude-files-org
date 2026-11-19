"""Line-preserving org parser and item model.

The file is kept as its original lines (``"\\n"``-split, with any ``"\\r"`` left on the
line), and items are an index over those lines. Rendering re-joins the lines
verbatim, so an unedited parse is byte-identical to the input. Edits replace line
ranges inside one item's section (see :mod:`edits`).
"""
import hashlib
import re
from typing import Dict, List, Optional

from .config import ConfigError, KeywordSequence, parse_keyword_sequence
from .timestamps import Timestamp, parse_timestamp

HEADLINE_RE = re.compile(r"^(\*+) (.*)$")
TAGS_RE = re.compile(r"(?:^|[ \t]+)(:(?:[\w@#%]+:)+)[ \t]*$")
COOKIE_RE = re.compile(r"\[[0-9]*%\]|\[[0-9]*/[0-9]*\]")
PRIORITY_RE = re.compile(r"^\[#[A-Za-z0-9]+\][ \t]*")
PLANNING_RE = re.compile(r"^[ \t]*(?:(?:SCHEDULED|DEADLINE|CLOSED):[ \t]*[<\[][^\]>\n]*[>\]][ \t]*)+$")
PLANNING_ENTRY_RE = re.compile(r"(SCHEDULED|DEADLINE|CLOSED):[ \t]*([<\[][^\]>\n]*[>\]])")
DRAWER_START_RE = re.compile(r"^[ \t]*:([A-Za-z0-9_-]+):[ \t]*$")
END_RE = re.compile(r"^[ \t]*:END:[ \t]*$", re.I)
BLOCK_BEGIN_RE = re.compile(r"^[ \t]*#\+BEGIN_(\S+)", re.I)
BLOCK_END_RE = re.compile(r"^[ \t]*#\+END_(\S+)[ \t]*$", re.I)
TODO_LINE_RE = re.compile(r"^#\+(?:SEQ_)?TODO:[ \t]*(.*?)[ \t]*$", re.I)
FILETAGS_RE = re.compile(r"^#\+FILETAGS:[ \t]*(.*?)[ \t]*$", re.I)
PROPERTY_RE = re.compile(r"^[ \t]*:([^\s:]+):(?:[ \t]+(.*?))?[ \t]*$")
LOOSE_TS_RE = re.compile(r"[<\[]\d{4}-\d{2}-\d{2}[^<>\[\]\n]*[>\]]")


class OrgError(ValueError):
    """An org tool error with a machine-readable ``code`` (see design.md Decision 7)."""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def __str__(self):
        return f"{self.code}: {self.message}"


class FileKeywords:
    """The TODO sequences in force for one file."""

    def __init__(self, sequences: List[KeywordSequence]):
        self.sequences = sequences
        self.open = tuple(k for s in sequences for k in s.open)
        self.closed = tuple(k for s in sequences for k in s.closed)
        self.all = self.open + self.closed
        self.note = frozenset(k for s in sequences for k in s.note)

    def is_open(self, kw):
        return kw in self.open

    def is_closed(self, kw):
        return kw in self.closed

    def needs_note(self, kw):
        return kw in self.note

    def describe(self):
        return " | ".join(s.describe() for s in self.sequences)


def normalize_title(rest):
    t = COOKIE_RE.sub("", rest)
    return re.sub(r"\s+", " ", t).strip()


class Item:
    """One headline and everything up to the next headline of any level."""

    def __init__(self, doc, idx, start, level):
        self.doc = doc
        self.idx = idx
        self.start = start
        self.level = level
        self.end = None          # exclusive: next headline of any level (or EOF)
        self.sub_end = None      # exclusive: next headline of level <= self.level (or EOF)
        self.parent: Optional["Item"] = None
        self.children: List["Item"] = []
        self.keyword = None
        self.priority = None
        self.title = ""
        self.raw_title = ""
        self.cookie = None
        self.tags: List[str] = []
        self.planning_idx = None
        self.planning: Dict[str, Optional[Timestamp]] = {}
        self.planning_raw: Dict[str, str] = {}
        self.props_span = None
        self.properties: Dict[str, str] = {}
        self.logbook_span = None
        self.problems = []       # (code, 0-based line index, message)
        self.path: List[str] = []
        self.id = None
        self.occurrence = 0

    # -- derived views ------------------------------------------------------
    @property
    def line(self):
        return self.start + 1

    @property
    def open(self):
        return self.keyword is not None and self.doc.keywords.is_open(self.keyword)

    @property
    def closed(self):
        return self.keyword is not None and self.doc.keywords.is_closed(self.keyword)

    @property
    def section_lines(self):
        return self.doc.lines[self.start:self.end]

    @property
    def rev(self):
        data = "\n".join(self.section_lines).encode("utf-8", "surrogateescape")
        return hashlib.sha256(data).hexdigest()[:12]

    @property
    def inherited_tags(self):
        out, seen = [], set()
        anc = []
        p = self.parent
        while p is not None:
            anc.append(p)
            p = p.parent
        for a in reversed(anc):
            for t in a.tags:
                if t not in seen:
                    seen.add(t)
                    out.append(t)
        for t in self.doc.filetags:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def all_tags(self):
        return list(dict.fromkeys(self.tags + self.inherited_tags))

    @property
    def effort(self):
        return self.properties.get("Effort")

    @property
    def created(self):
        return self.properties.get("CREATED")

    def has_tag(self, tag):
        """True when ``tag`` (or, for a tag group, any member) is an own or inherited tag."""
        wanted = {tag}
        wanted.update(self.doc.config.tag_groups.get(tag, ()))
        return any(t in wanted for t in self.all_tags())

    def descendants(self):
        for c in self.children:
            yield c
            yield from c.descendants()

    def open_descendants(self):
        return [d for d in self.descendants() if d.open]

    def structure_problems(self):
        """Problems that make editing this item's own section unsafe."""
        return [p for p in self.problems if p[0] in UNSAFE_CODES]


UNSAFE_CODES = {"unclosed_drawer", "misplaced_property_drawer", "two_planning_lines"}


class OrgDocument:
    def __init__(self, text, config, name="inbox.org"):
        self.name = name
        self.config = config
        self.original = text
        self.lines = text.split("\n")
        self.eol = "\r" if self.lines and self.lines[0].endswith("\r") else ""
        self.filetags: List[str] = []
        self.preamble_end = 0
        self.items: List[Item] = []
        self.keywords = self._read_keywords()
        self._parse()

    # -- construction -------------------------------------------------------
    def _read_keywords(self):
        sequences = []
        for line in self.lines:
            if line.startswith("*"):
                break
            m = TODO_LINE_RE.match(line.rstrip("\r"))
            if m:
                try:
                    sequences.append(parse_keyword_sequence(m.group(1), "#+TODO"))
                except ConfigError:
                    continue
            m = FILETAGS_RE.match(line.rstrip("\r"))
            if m:
                self.filetags += [t for t in m.group(1).strip(":").split(":") if t]
        if not sequences:
            sequences = [self.config.keywords]
        return FileKeywords(sequences)

    def _headline_indexes(self):
        """Line indexes of headlines, ignoring lines inside ``#+BEGIN_…``/``#+END_…`` blocks."""
        n = len(self.lines)
        out, i = [], 0
        while i < n:
            line = self.lines[i].rstrip("\r")
            mb = BLOCK_BEGIN_RE.match(line)
            if mb:
                name = mb.group(1).lower()
                for j in range(i + 1, n):
                    me = BLOCK_END_RE.match(self.lines[j].rstrip("\r"))
                    if me and me.group(1).lower() == name:
                        i = j + 1
                        break
                else:
                    i += 1
                continue
            if HEADLINE_RE.match(line):
                out.append(i)
            i += 1
        return out

    def _parse(self):
        heads = self._headline_indexes()
        self.preamble_end = heads[0] if heads else len(self.lines)
        # A final "" produced by a trailing newline belongs to no item.
        eof = len(self.lines)
        if self.lines and self.lines[-1] == "" and len(self.lines) > 1:
            eof = len(self.lines) - 1
        stack: List[Item] = []
        for n, h in enumerate(heads):
            m = HEADLINE_RE.match(self.lines[h].rstrip("\r"))
            item = Item(self, n, h, len(m.group(1)))
            item.end = heads[n + 1] if n + 1 < len(heads) else eof
            self.items.append(item)
            while stack and stack[-1].level >= item.level:
                stack.pop()
            item.parent = stack[-1] if stack else None
            if item.parent:
                item.parent.children.append(item)
            stack.append(item)
            self._parse_headline(item, m.group(2))
        # sub_end: end of subtree
        for item in self.items:
            nxt = item.end
            j = item.idx + 1
            while j < len(self.items) and self.items[j].level > item.level:
                nxt = self.items[j].end
                j += 1
            item.sub_end = nxt
        for item in self.items:
            self._parse_section(item)
        self._assign_ids()
        self._index = {it.id: it for it in self.items}

    def _parse_headline(self, item, rest):
        m = re.match(r"(\S+)(?:[ \t]+|$)", rest)
        if m and m.group(1) in self.keywords.all:
            item.keyword = m.group(1)
            rest = rest[m.end():]
        mp = PRIORITY_RE.match(rest)
        if mp:
            item.priority = mp.group(0).strip()
            rest = rest[mp.end():]
        mt = TAGS_RE.search(rest)
        if mt:
            item.tags = [t for t in mt.group(1).strip(":").split(":") if t]
            rest = rest[:mt.start()]
        item.raw_title = rest
        mc = COOKIE_RE.search(self.lines[item.start])
        item.cookie = mc.group(0) if mc else None
        item.title = normalize_title(rest)
        p = item.parent
        item.path = (p.path if p else []) + [item.title]

    def _parse_section(self, item):
        lines = self.lines
        end = item.end
        i = item.start + 1
        if i < end and PLANNING_RE.match(lines[i].rstrip("\r")):
            item.planning_idx = i
            for key, ts in PLANNING_ENTRY_RE.findall(lines[i]):
                item.planning_raw[key] = ts
                item.planning[key] = parse_timestamp(ts)
            i += 1
            if i < end and PLANNING_RE.match(lines[i].rstrip("\r")):
                item.problems.append(("two_planning_lines", i, "second planning line"))
        if i < end and lines[i].rstrip("\r").strip().upper() == ":PROPERTIES:":
            j = self._drawer_end(i, end)
            if j is None:
                item.problems.append(("unclosed_drawer", i, ":PROPERTIES: drawer has no :END:"))
                i = end
            else:
                item.props_span = (i, j)
                for k in range(i + 1, j):
                    pm = PROPERTY_RE.match(lines[k].rstrip("\r"))
                    if pm:
                        item.properties[pm.group(1)] = pm.group(2) or ""
                i = j + 1
        while i < end:
            dm = DRAWER_START_RE.match(lines[i].rstrip("\r"))
            if dm and dm.group(1).upper() != "END":
                name = dm.group(1).upper()
                j = self._drawer_end(i, end)
                if j is None:
                    item.problems.append(("unclosed_drawer", i, f":{dm.group(1)}: drawer has no :END:"))
                    break
                if name == "PROPERTIES":
                    item.problems.append(("misplaced_property_drawer", i,
                                          "property drawer is not directly under the headline or planning "
                                          "line; org ignores its properties"))
                elif name == "LOGBOOK" and item.logbook_span is None:
                    item.logbook_span = (i, j)
                i = j + 1
                continue
            i += 1

    def _drawer_end(self, start, end):
        for j in range(start + 1, end):
            if END_RE.match(self.lines[j].rstrip("\r")):
                return j
        return None

    def _assign_ids(self):
        seen: Dict[str, int] = {}
        for item in self.items:
            norm = "\x1f".join(item.path)
            h = hashlib.sha256(norm.encode("utf-8", "surrogateescape")).hexdigest()[:10]
            n = seen.get(h, 0)
            seen[h] = n + 1
            item.occurrence = n
            item.id = f"o_{h}" if n == 0 else f"o_{h}.{n}"

    # -- access -------------------------------------------------------------
    def get(self, item_id):
        return self._index.get(item_id)

    def find_by_title(self, title, parent=None):
        for it in self.items:
            if it.title == title and (parent is None or it.parent is parent):
                return it
        return None

    def render(self):
        return "\n".join(self.lines)


def parse(text, config, name="inbox.org"):
    return OrgDocument(text, config, name)
