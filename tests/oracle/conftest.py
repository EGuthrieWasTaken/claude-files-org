import pytest

from tests.oracle import harness as H
from tests.oracle.engine import engine_apply


@pytest.fixture
def both(tmp_path):
    """``both(fixture, op, args, now=..., config=None)``: run Emacs and the engine on fresh copies of a
    fixture and assert that every resulting file is byte-identical."""
    counter = {"n": 0}

    def run(fixture, op, args, now=H.DEFAULT_NOW, mask_archive=True, config=None, expect_change=True, extra=None):
        counter["n"] += 1
        homes = [H.make_folder(tmp_path, fixture, name=f"{n}{counter['n']}") for n in ("before", "emacs", "tool")]
        for rel, data in (extra or {}).items():
            for h in homes:
                p = h / ".emacs.d" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
        before_home, emacs_home, tool_home = homes
        before = H.read_tree(before_home)
        expected = H.emacs_apply(emacs_home, op, args, now=now)
        # Emacs writes the absolute path of the source in a new archive file's header; the tool writes the
        # configured ``~/.emacs.d`` form (documented discrepancy), so compare with $HOME folded to "~".
        expected = {k: v.replace(str(emacs_home).encode(), b"~") for k, v in expected.items()}
        actual = engine_apply(tool_home, op, args, now=now, config=config)
        H.assert_same_tree(expected, actual, mask_archive=mask_archive)
        if expect_change:
            assert expected != before, "the oracle changed nothing: the case proves nothing"
        return expected

    return run
