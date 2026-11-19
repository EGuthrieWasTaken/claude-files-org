"""In-process integration against the real claude-files app (extension API v1).

Needs a claude-files checkout (v1.4.0, or the app extracted from the pinned image) and its dependencies:

    CLAUDE_FILES_APP=/path/to/claude-files   # the directory that contains app/
    CLAUDE_FILES_PYTHON=/path/to/venv/python # optional: an interpreter with app/requirements*.txt installed
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
FIXTURES = HERE.parent / "fixtures"
APP = os.environ.get("CLAUDE_FILES_APP")
PYTHON = os.environ.get("CLAUDE_FILES_PYTHON", sys.executable)

pytestmark = pytest.mark.skipif(not APP or not (pathlib.Path(APP) / "app" / "extensions.py").exists(),
                                reason="set CLAUDE_FILES_APP to a claude-files checkout (v1.4.0)")


def run_child(tmp_path, scenario, fixture="clean.org"):
    data = tmp_path / "data"
    (data / "org-projects").mkdir(parents=True)
    shutil.copyfile(FIXTURES / fixture, data / "org-projects" / "inbox.org")
    (data / "config.org").write_text("* not an org tool file\n")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO), str(APP)]))
    for k in ("EXTRA_TOOL_MODULES", "ENABLE_MCP", "API_TOKEN", "API_TOKEN_READONLY"):
        env.pop(k, None)
    p = subprocess.run([PYTHON, str(HERE / "child.py"), scenario, str(data)], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=300)
    checks = [json.loads(line[6:]) for line in p.stdout.splitlines() if line.startswith("CHECK ")]
    return p, checks


@pytest.fixture(scope="module")
def app_checks(tmp_path_factory):
    p, checks = run_child(tmp_path_factory.mktemp("app"), "app")
    assert checks, f"the scenario produced no checks:\n{p.stdout[-2000:]}\n{p.stderr[-3000:]}"
    return checks


def test_every_check_ran(app_checks):
    assert len(app_checks) >= 25


def test_all_checks_pass(app_checks):
    failed = [f"{c['name']}: {c['detail']}" for c in app_checks if not c["ok"]]
    assert not failed, "\n".join(failed)


@pytest.mark.parametrize("scenario", ["bad_tz", "bad_files"])
def test_bad_settings_stop_the_server(tmp_path, scenario):
    p, checks = run_child(tmp_path, scenario)
    assert checks and all(c["ok"] for c in checks), f"{checks}\n{p.stdout[-1500:]}\n{p.stderr[-2500:]}"
