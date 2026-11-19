import pathlib
import shutil
import subprocess

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PARSE_CHECK = pathlib.Path(__file__).parent / "oracle" / "parse_check.el"

emacs = shutil.which("emacs")


@pytest.mark.skipif(emacs is None, reason="emacs is not installed")
@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.org")), ids=lambda p: p.name)
def test_fixture_parses_in_emacs(path):
    result = subprocess.run(
        [emacs, "--batch", "-Q", "-l", str(PARSE_CHECK), str(path)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK")
