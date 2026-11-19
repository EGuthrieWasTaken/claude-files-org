"""Emacs batch-mode oracle: run one org command and compare file bytes with the tool engine."""
import json
import os
import pathlib
import re
import shutil
import subprocess
from typing import Optional

import pytest

HERE = pathlib.Path(__file__).parent
DRIVER = HERE / "driver.el"
FIXTURES = HERE.parent / "fixtures"
EMACS = shutil.which("emacs")
TZ = "America/Indiana/Indianapolis"
DEFAULT_NOW = "2026-11-19 09:30"          # a Thursday morning in Indiana

requires_emacs = pytest.mark.skipif(EMACS is None, reason="emacs is not installed (apt install emacs-nox)")

_ARCHIVE_TIME = re.compile(rb"^(:ARCHIVE_TIME: +)\d{4}-\d{2}-\d{2} [A-Za-z]{3} \d{2}:\d{2}$", re.M)


def make_folder(tmp_path, fixture="inbox.org", target="org-projects/inbox.org", name="home"):
    """Create ``<tmp>/<name>/.emacs.d`` holding the fixture at ``target``; return the home dir."""
    home = tmp_path / name
    folder = home / ".emacs.d"
    dest = folder / target
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / fixture, dest)
    return home


def read_tree(home):
    """Every file under ``home/.emacs.d`` -> bytes, keyed by path relative to it."""
    root = home / ".emacs.d"
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
            and "eln-cache" not in p.parts}


def emacs_apply(home, op, args, now=DEFAULT_NOW, target="org-projects/inbox.org"):
    """Apply ``op`` with Emacs in ``home`` and return the resulting tree."""
    if EMACS is None:
        pytest.skip("emacs is not installed")
    eln = home.parent / (home.name + "-eln")
    eln.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), TZ=TZ, ORACLE_ELN=str(eln), ORACLE_OP=op, ORACLE_NOW=now,
               ORACLE_FILE=str(home / ".emacs.d" / target), ORACLE_ARGS=json.dumps(args),
               LC_ALL="C.UTF-8")
    r = subprocess.run([EMACS, "--batch", "-Q", "-l", str(DRIVER)], env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stdout, f"emacs failed:\n{r.stdout}\n{r.stderr}"
    return read_tree(home)


def archive_time_values(tree):
    return [line for data in tree.values() for line in data.split(b"\n") if line.startswith(b":ARCHIVE_TIME:")]


def mask_archive_time(tree):
    return {k: _ARCHIVE_TIME.sub(rb"\1<masked>", v) for k, v in tree.items()}


def check_archive_time_format(tree, now=DEFAULT_NOW):
    """ARCHIVE_TIME is read from a clock the oracle can't freeze: only check its shape."""
    for line in archive_time_values(tree):
        assert _ARCHIVE_TIME.match(line), line


def assert_same_tree(expected, actual, mask_archive=True):
    if mask_archive:
        check_archive_time_format(expected)
        check_archive_time_format(actual)
        expected, actual = mask_archive_time(expected), mask_archive_time(actual)
    assert sorted(expected) == sorted(actual), f"different files: {sorted(expected)} vs {sorted(actual)}"
    for name in expected:
        if expected[name] != actual[name]:
            import difflib
            diff = "\n".join(difflib.unified_diff(
                expected[name].decode("utf-8", "replace").split("\n"),
                actual[name].decode("utf-8", "replace").split("\n"),
                "emacs/" + name, "tool/" + name, lineterm=""))
            pytest.fail(f"{name} differs (emacs vs tool):\n{diff}")
