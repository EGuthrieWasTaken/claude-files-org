import inspect
import logging
import os
import types

import pytest

import claude_files_org as org
from claude_files_org import tools
from claude_files_org.model import OrgError

READS = {"org_list_items", "org_get_item", "org_lint"}
WRITES = {"org_set_state", "org_reschedule", "org_set_deadline", "org_add_item", "org_add_note", "org_set_tags",
          "org_set_effort", "org_batch", "org_archive", "org_archive_closed"}


class FakeVault:
    """The few Vault methods the store uses, over a plain directory."""

    def __init__(self, root):
        self.root = root

    def components(self, raw):
        if raw.startswith("/") or ".." in raw.split("/"):
            raise ValueError(f"bad path {raw}")
        return raw.split("/")

    def open_read(self, parts):
        p = self.root.joinpath(*parts)
        if not p.exists():
            err = Exception("missing")
            err.code = "not_found"
            raise err
        return os.open(p, os.O_RDONLY), p.stat()

    def atomic_write(self, parts, overwrite, create_parents=False):
        import contextlib

        @contextlib.contextmanager
        def cm():
            p = self.root.joinpath(*parts)
            p.parent.mkdir(parents=True, exist_ok=create_parents)
            fd = os.open(str(p) + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            committer = types.SimpleNamespace(commit=lambda fd_: os.replace(str(p) + ".tmp", p))
            try:
                yield fd, committer
            finally:
                os.close(fd)
        return cm()


class FakeApi:
    def __init__(self, vault):
        self.vault = vault
        self.tools = {}
        self.log = logging.getLogger("test")

    def add_tool(self, fn, *, read_only, **kw):
        self.tools[kw.get("name") or fn.__name__] = (fn, read_only, kw)

    def guard(self, op, fn, *a):
        return fn(*a)


@pytest.fixture
def api(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("ORG_"):
            monkeypatch.delenv(k)
    (tmp_path / "org-projects").mkdir()
    (tmp_path / "org-projects" / "inbox.org").write_bytes(open("tests/fixtures/clean.org", "rb").read())
    a = FakeApi(FakeVault(tmp_path))
    org.register(a)
    return a


def test_package_exposes_the_extension_contract():
    assert org.REQUIRES_API == 1 and org.__version__ == "0.1.0"
    assert callable(org.register) and "org_*" in org.INSTRUCTIONS


def test_instructions_cover_what_agents_must_know():
    text = org.INSTRUCTIONS
    for needle in ("write_file", "git_pull", "git_commit", "git_push", "stale", "WAIT", "CANCELLED", "note"):
        assert needle in text


def test_all_tools_registered_with_the_right_read_only_flag(api):
    assert {n for n, (_, ro, _) in api.tools.items() if ro} == READS
    assert {n for n, (_, ro, _) in api.tools.items() if not ro} == WRITES


def test_no_tool_takes_ctx_and_every_tool_has_a_docstring(api):
    for name, (fn, _, _) in api.tools.items():
        params = inspect.signature(fn).parameters
        assert "ctx" not in params, name
        assert fn.__doc__ and len(fn.__doc__) > 40, name
        assert all(p.annotation is not inspect.Parameter.empty for p in params.values()), name


def test_documented_parameters(api):
    p = lambda n: set(inspect.signature(api.tools[n][0]).parameters)
    assert {"file", "state", "tags", "scheduled_from", "scheduled_to", "deadline_from", "deadline_to", "overdue",
            "text", "limit"} == p("org_list_items")
    assert {"id", "rev", "state", "note", "file", "dry_run"} == p("org_set_state")
    assert {"edits", "file", "dry_run"} == p("org_batch")
    assert {"id", "rev", "file", "dry_run"} == p("org_archive")
    assert {"older_than_days", "file", "dry_run"} == p("org_archive_closed")
    for n in WRITES - {"org_archive_closed"}:
        assert "dry_run" in p(n), n


def test_the_tools_work_end_to_end_over_the_vault_store(api, tmp_path):
    t = lambda n: api.tools[n][0]
    listing = t("org_list_items")(state="all")
    alpha = next(i for i in listing["items"] if i["title"] == "alpha")
    out = t("org_reschedule")(alpha["id"], alpha["rev"], date="2026-11-21")
    assert out["written"] and "SCHEDULED: <2026-11-21 Sat>" in (tmp_path / "org-projects/inbox.org").read_text()
    assert out["id"] == alpha["id"] and out["rev"] != alpha["rev"]
    with pytest.raises(ValueError) as e:
        t("org_reschedule")(alpha["id"], alpha["rev"], date="2026-11-22")
    assert str(e.value).startswith("stale:") and out["rev"] in str(e.value)


def test_errors_carry_the_code_and_extra_detail(api):
    t = lambda n: api.tools[n][0]
    with pytest.raises(ValueError) as e:
        t("org_get_item")("o_nope")
    assert str(e.value).startswith("not_found:")
    with pytest.raises(ValueError) as e:
        t("org_list_items")(file="config.org")
    assert "file_not_allowed" in str(e.value)
    with pytest.raises(ValueError):
        t("org_batch")([])


def test_a_missing_file_is_reported(api, tmp_path):
    os.remove(tmp_path / "org-projects/inbox.org")
    with pytest.raises(ValueError) as e:
        api.tools["org_list_items"][0]()
    assert "not_found" in str(e.value)


def test_bad_settings_stop_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("ORG_TIMEZONE", "Mars/Olympus")
    with pytest.raises(ValueError) as e:
        org.register(FakeApi(FakeVault(tmp_path)))
    assert "ORG_TIMEZONE" in str(e.value)


def test_readme_documents_exactly_the_registered_tools(api):
    import pathlib
    import re
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text()
    documented = set(re.findall(r"^### `(org_[a-z_]+)`", readme, re.M))
    documented |= {n for line in re.findall(r"^### (`org_[a-z_]+` and `org_[a-z_]+`)", readme, re.M)
                   for n in re.findall(r"org_[a-z_]+", line)}
    assert documented == set(api.tools)


def test_deployment_commands_in_the_readme_are_the_ones_ci_runs():
    import pathlib
    import re
    root = pathlib.Path(__file__).parent.parent
    readme = (root / "README.md").read_text()
    section = readme[readme.index("## Deployment"):]
    commands = [ln.strip() for block in re.findall(r"```bash\n(.*?)```", section, re.S) for ln in block.splitlines()
                if ln.strip()]
    assert commands
    ran = "\n".join((root / p).read_text() for p in (".github/workflows/ci.yml", ".github/workflows/release.yml"))
    ran = ran.replace('"$TAG"', "v0.1.0")
    for cmd in commands:
        assert cmd in ran, f"README runs {cmd!r}, which no workflow runs"
