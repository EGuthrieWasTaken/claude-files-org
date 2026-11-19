import pytest

from claude_files_org.config import ConfigError, load_config, parse_keyword_sequence


def test_defaults_match_ethans_config():
    c = load_config({})
    assert c.files == ("org-projects/inbox.org",)
    assert c.inbox_heading == "Tasks"
    assert c.keywords.open == ("TODO", "STARTED", "WAIT")
    assert c.keywords.closed == ("DONE", "CANCELLED")
    assert c.keywords.note == frozenset({"WAIT", "CANCELLED"})
    assert c.tags == ("stephen", "jwa", "research", "coursework", "admin", "personal", "blog")
    assert c.tag_groups == {"personal": ("blog",)}
    assert c.effort_values[0] == "0:15" and c.effort_values[-1] == "8:00" and len(c.effort_values) == 10
    assert c.archive_dir == "org-projects/archive"
    assert c.emacs_root == "~/.emacs.d"
    assert c.timezone_name == "America/Indiana/Indianapolis"
    assert c.as_dict()["log"]["into_drawer"] is True


def test_blank_values_fall_back_to_defaults():
    assert load_config({"ORG_TAGS": "  "}).tags[0] == "stephen"


def test_overrides_are_read():
    c = load_config({"ORG_FILES": "a.org, sub/b.org", "ORG_TAGS": "x,y", "ORG_TAG_GROUPS": "x=y",
                     "ORG_TIMEZONE": "UTC", "ORG_EMACS_ROOT": "~/org/"})
    assert c.files == ("a.org", "sub/b.org")
    assert c.tag_groups == {"x": ("y",)}
    assert c.emacs_root == "~/org"


def test_keyword_sequence_flags_and_fast_keys():
    seq = parse_keyword_sequence("TODO(t) STARTED(s) WAIT(w@) | DONE(d) CANCELLED(c@/!)")
    assert seq.note == frozenset({"WAIT", "CANCELLED"})
    assert seq.is_open("WAIT") and seq.is_closed("DONE")


def test_keyword_sequence_without_bar_closes_last():
    seq = parse_keyword_sequence("TODO DONE")
    assert seq.open == ("TODO",) and seq.closed == ("DONE",)


@pytest.mark.parametrize("env,name", [
    ({"ORG_TODO_KEYWORDS": "TODO | | DONE"}, "ORG_TODO_KEYWORDS"),
    ({"ORG_TODO_KEYWORDS": "TODO TODO | DONE"}, "ORG_TODO_KEYWORDS"),
    ({"ORG_TODO_KEYWORDS": "| DONE"}, "ORG_TODO_KEYWORDS"),
    ({"ORG_TODO_KEYWORDS": "TODO |"}, "ORG_TODO_KEYWORDS"),
    ({"ORG_TODO_KEYWORDS": "TODO(xyz!!!) | DONE"}, "ORG_TODO_KEYWORDS"),
    ({"ORG_TIMEZONE": "Mars/Olympus"}, "ORG_TIMEZONE"),
    ({"ORG_FILES": "/etc/passwd"}, "ORG_FILES"),
    ({"ORG_FILES": "../outside.org"}, "ORG_FILES"),
    ({"ORG_FILES": "a/../../b.org"}, "ORG_FILES"),
    ({"ORG_ARCHIVE_DIR": "../x"}, "ORG_ARCHIVE_DIR"),
    ({"ORG_TAG_GROUPS": "personal"}, "ORG_TAG_GROUPS"),
    ({"ORG_TAG_GROUPS": "nosuch=blog"}, "ORG_TAG_GROUPS"),
    ({"ORG_TAG_GROUPS": "personal=nosuch"}, "ORG_TAG_GROUPS"),
    ({"ORG_TAGS": "bad tag!,x"}, "ORG_TAGS"),
    ({"ORG_TAGS": "a,a", "ORG_TAG_GROUPS": "a=a"}, "ORG_TAGS"),
    ({"ORG_EFFORT_VALUES": "90"}, "ORG_EFFORT_VALUES"),
    ({"ORG_EFFORT_VALUES": "0:75"}, "ORG_EFFORT_VALUES"),
])
def test_bad_settings_are_refused_naming_the_variable(env, name):
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert name in str(exc.value)


def test_readme_documents_exactly_the_settings_the_module_reads():
    import pathlib
    import re
    from claude_files_org.config import DEFAULTS
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text()
    assert set(re.findall(r"^\| `(ORG_[A-Z_]+)`", readme, re.M)) == set(DEFAULTS)
