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
