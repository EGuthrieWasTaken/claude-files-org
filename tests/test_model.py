import os
import pathlib

import pytest

from claude_files_org.config import load_config
from claude_files_org.model import parse
from tests.conftest import FIXTURES, fixture_text


def test_headline_without_keyword_is_an_item(load, by_title):
    it = by_title(load(), "Midterm 1")
    assert it.keyword is None and not it.open and not it.closed and it.level == 2
    assert it.planning_idx is None  # a bare timestamp line is body text, not planning


def test_preamble_is_not_an_item(load):
    doc = load()
    assert doc.items[0].title == "Tasks" and doc.items[0].start == 3
    assert doc.preamble_end == 3
    assert all(i.start >= 3 for i in doc.items)


def test_headline_parts(load, by_title):
    doc = load()
    alpha = by_title(doc, "alpha")
    assert (alpha.keyword, alpha.level, alpha.tags, alpha.cookie) == ("TODO", 2, ["stephen", "research"], None)
    assert alpha.planning["SCHEDULED"].raw == "<2026-11-13 Fri>"
    assert alpha.planning["DEADLINE"].raw == "<2026-11-20 Fri 9:30>"
    assert alpha.effort == "0:45"
    assert alpha.logbook_span is not None and alpha.props_span == (alpha.start + 2, alpha.start + 4)
    beta = by_title(doc, "beta")
    assert beta.cookie == "[0/2]" and beta.title == "beta"
    assert [c.title for c in beta.children] == ["b1", "b2"]
    assert by_title(doc, "epsilon").cookie == "[50%]"


def test_long_headline_with_tags(load, by_title):
    it = by_title(load(), "a headline that is deliberately very long so that the tags cannot be aligned at column 77 any more")
    assert it.tags == ["admin"]


def test_src_block_contents_are_not_headlines(load, by_title):
    unescaped = load("src_block_unescaped.org")
    assert [i.title for i in unescaped.items] == ["Tasks", "with block", "after"]
    doc = load()
    assert by_title(doc, "kappa").level == 2
    assert by_title(doc, "Reference").level == 1
    assert by_title(doc, "iota with src block").end == by_title(doc, "kappa").start


def test_section_and_subtree_bounds(load, by_title):
    doc = load()
    beta, b1 = by_title(doc, "beta"), by_title(doc, "b1")
    assert beta.end == b1.start                       # section stops at the next headline of any level
    assert beta.sub_end == by_title(doc, "gamma with no planning").start


def test_todo_line_in_file_wins(load, by_title):
    doc = load("todo_override.org")
    assert by_title(doc, "upcoming thing").open
    wait = [i for i in doc.items if "not a keyword here" in i.title][0]
    assert wait.keyword is None and wait.title == "WAIT not a keyword here"   # WAIT isn't recognized here
    assert by_title(doc, "finished").closed


def test_default_sequence_classification(load, by_title):
    doc = load()
    for title, expect in [("alpha", "open"), ("zeta", "open"), ("eta", "open"), ("delta", "closed"), ("theta", "closed")]:
        it = by_title(doc, title)
        assert (it.open, it.closed) == ((True, False) if expect == "open" else (False, True)), title


def test_drawers_on_the_fixture(load, by_title):
    doc = load()
    zeta = by_title(doc, "zeta")
    assert zeta.properties == {"CREATED": "[2026-11-02 Mon 09:15]"}
    assert by_title(doc, "eta").logbook_span is not None and by_title(doc, "eta").props_span is None
    assert all(not it.problems for it in doc.items)


def test_malformed_structures_are_recorded(load, by_title):
    doc = load("malformed.org")
    codes = {t: [p[0] for p in by_title(doc, t).problems] for t in
             ("misplaced drawer", "unclosed drawer", "two planning lines", "invisible property drawer", "fine")}
    assert codes["misplaced drawer"] == ["misplaced_property_drawer"]
    assert codes["unclosed drawer"] == ["unclosed_drawer"]
    assert codes["two planning lines"] == ["two_planning_lines"]
    assert codes["invisible property drawer"] == ["misplaced_property_drawer"]
    assert codes["fine"] == []


def test_tag_inheritance_and_groups(load, by_title):
    doc = load()
    b1 = by_title(doc, "b1")
    assert b1.tags == [] and b1.inherited_tags == ["stephen"] and b1.has_tag("stephen")
    assert not b1.has_tag("jwa")
    blog = by_title(doc, "blog about the thing")
    assert blog.has_tag("blog") and blog.has_tag("personal")      # blog is in group personal
    assert not by_title(doc, "alpha").has_tag("personal")


def test_inherited_tags_nest_outermost_first():
    cfg = load_config({})
    doc = parse("* Tasks :admin:\n** TODO p :research:stephen:\n*** TODO c\n", cfg)
    assert doc.items[2].inherited_tags == ["admin", "research", "stephen"]


def test_id_and_rev_basics(load):
    doc = load()
    ids = [i.id for i in doc.items]
    assert len(set(ids)) == len(ids)
    f1, f2 = [i for i in doc.items if i.title == "Final Exam"]
    assert f1.id != f2.id
    assert all(len(i.rev) == 12 for i in doc.items)


def test_unrelated_insert_keeps_ids(cfg):
    text = fixture_text("inbox.org")
    before = {(i.path[-1], i.occurrence): i.id for i in parse(text, cfg).items}
    inserted = text.replace("** TODO beta", "** TODO brand new\n** TODO beta", 1)
    after = {(i.path[-1], i.occurrence): i.id for i in parse(inserted, cfg).items}
    assert all(after[k] == v for k, v in before.items())


def test_cookie_change_keeps_id_but_not_rev(cfg):
    text = fixture_text("inbox.org")
    a = parse(text, cfg)
    b = parse(text.replace("beta [0/2]", "beta [1/2]"), cfg)
    ab = [i for i in a.items if i.title == "beta"][0]
    bb = [i for i in b.items if i.title == "beta"][0]
    assert ab.id == bb.id and ab.rev != bb.rev


def test_child_edit_leaves_parent_rev_alone(cfg):
    text = "* Tasks\n** TODO parent\n*** TODO child\nSCHEDULED: <2026-11-13 Fri>\n"
    a = parse(text, cfg)
    b = parse(text.replace("TODO child", "DONE child"), cfg)
    assert a.items[1].rev == b.items[1].rev and a.items[2].rev != b.items[2].rev
    assert a.items[1].id == b.items[1].id and a.items[2].id == b.items[2].id


def test_duplicate_ids_are_stable_across_reads(cfg):
    text = fixture_text("inbox.org")
    one = [i.id for i in parse(text, cfg).items if i.title == "Final Exam"]
    two = [i.id for i in parse(text, cfg).items if i.title == "Final Exam"]
    assert one == two and one[0] != one[1]


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.org")), ids=lambda p: p.name)
def test_round_trip_is_byte_identical(path, cfg):
    raw = path.read_bytes()
    doc = parse(raw.decode("utf-8"), cfg, path.name)
    assert doc.render().encode("utf-8") == raw


def test_crlf_and_missing_final_newline(load):
    assert load("crlf.org").eol == "\r"
    assert load("crlf.org").items[1].keyword == "TODO"
    assert load("no_final_newline.org").items[1].title == "last line has no newline"


def test_empty_and_headingless_files(cfg):
    assert parse("", cfg).items == []
    assert parse("just text\nmore\n", cfg).items == []
    assert parse("just text\nmore\n", cfg).render() == "just text\nmore\n"


@pytest.mark.skipif(not os.environ.get("ORG_ROUNDTRIP_FILES"),
                    reason="set ORG_ROUNDTRIP_FILES to a pathsep-separated list of local org files to opt in")
@pytest.mark.parametrize("path", [p for p in os.environ.get("ORG_ROUNDTRIP_FILES", "").split(os.pathsep) if p])
def test_real_files_round_trip(path, cfg):
    raw = pathlib.Path(path).read_bytes()
    doc = parse(raw.decode("utf-8", "surrogateescape"), cfg)
    assert doc.render().encode("utf-8", "surrogateescape") == raw
