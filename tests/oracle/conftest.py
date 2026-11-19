import pytest

from tests.oracle import harness as H
from tests.oracle.engine import engine_apply


@pytest.fixture
def both(tmp_path):
    """``both(fixture, op, args, now=..., config=None)``: run Emacs and the engine on fresh copies of a
    fixture and assert that every resulting file is byte-identical."""
    counter = {"n": 0}

    def run(fixture, op, args, now=H.DEFAULT_NOW, mask_archive=True, config=None, expect_change=True):
        counter["n"] += 1
        before_home = H.make_folder(tmp_path, fixture, name=f"before{counter['n']}")
        emacs_home = H.make_folder(tmp_path, fixture, name=f"emacs{counter['n']}")
        tool_home = H.make_folder(tmp_path, fixture, name=f"tool{counter['n']}")
        before = H.read_tree(before_home)
        expected = H.emacs_apply(emacs_home, op, args, now=now)
        actual = engine_apply(tool_home, op, args, now=now, config=config)
        H.assert_same_tree(expected, actual, mask_archive=mask_archive)
        if expect_change:
            assert expected != before, "the oracle changed nothing: the case proves nothing"
        return expected

    return run
