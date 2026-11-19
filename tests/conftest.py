import pathlib

import pytest

from claude_files_org.config import load_config
from claude_files_org.model import parse

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_text(name):
    return (FIXTURES / name).read_bytes().decode("utf-8")


@pytest.fixture
def cfg():
    return load_config({})


@pytest.fixture
def load(cfg):
    def _load(name="inbox.org", config=None):
        return parse(fixture_text(name), config or cfg, name)
    return _load


@pytest.fixture
def by_title():
    def _find(doc, title, nth=0):
        hits = [i for i in doc.items if i.title == title]
        return hits[nth]
    return _find


class MemoryStore:
    """A tiny stand-in for the host's Vault: ``read``/``write`` of bytes by relative path."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.writes = []

    def read(self, path):
        return self.files.get(path)

    def write(self, path, data):
        self.writes.append(path)
        self.files[path] = data


@pytest.fixture
def make_service(cfg):
    from claude_files_org.service import OrgService

    def _make(fixture="inbox.org", config=None, extra=None):
        files = {"org-projects/inbox.org": (FIXTURES / fixture).read_bytes()}
        files.update(extra or {})
        store = MemoryStore(files)
        return OrgService(config or cfg, store), store
    return _make
