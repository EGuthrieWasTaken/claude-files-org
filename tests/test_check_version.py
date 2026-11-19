import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).parent.parent / ".github" / "scripts" / "check-version.sh"
bash = shutil.which("bash")
git = shutil.which("git")

pytestmark = pytest.mark.skipif(not (bash and git), reason="needs bash and git")


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "claude_files_org").mkdir()
    (tmp_path / "claude_files_org" / "__init__.py").write_text('__version__ = "0.1.0"\nREQUIRES_API = 1\n')
    run = lambda *a: subprocess.run(a, cwd=tmp_path, check=True, capture_output=True,
                                    env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
    run("git", "init", "-q")
    run("git", "add", ".")
    run("git", "commit", "-qm", "init")
    return tmp_path, run


def check(path, *args, **env):
    return subprocess.run([bash, str(SCRIPT), *args], cwd=path, capture_output=True, text=True,
                          env=dict(os.environ, **env))


def test_pr_passes_for_an_unreleased_version(repo):
    path, _ = repo
    r = check(path, "pr")
    assert r.returncode == 0 and "0.1.0" in r.stdout


def test_pr_fails_when_the_version_has_a_tag_and_names_it(repo):
    path, run = repo
    run("git", "tag", "v0.1.0")
    r = check(path, "pr")
    assert r.returncode == 1 and "v0.1.0" in r.stderr


def test_release_with_the_matching_tag_passes(repo):
    path, _ = repo
    assert check(path, "release", "v0.1.0").returncode == 0


@pytest.mark.parametrize("tag", ["v0.1.1", "0.1.0", "v0.2.0", "release-0.1.0"])
def test_release_with_a_mismatched_tag_fails_before_anything_else(repo, tmp_path_factory, tag):
    path, _ = repo
    fake = tmp_path_factory.mktemp("bin")
    marker = fake / "docker-was-called"
    (fake / "docker").write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    (fake / "docker").chmod(0o755)
    r = check(path, "release", tag, CHECK_GHCR="1", PATH=f"{fake}:{os.environ['PATH']}")
    assert r.returncode == 1 and "does not match" in r.stderr and not marker.exists()


def test_release_refuses_an_existing_ghcr_tag(repo, tmp_path_factory):
    path, _ = repo
    fake = tmp_path_factory.mktemp("bin")
    (fake / "docker").write_text("#!/bin/sh\n[ \"$1 $2\" = 'manifest inspect' ] && exit 0\nexit 1\n")
    (fake / "docker").chmod(0o755)
    r = check(path, "release", "v0.1.0", CHECK_GHCR="1", PATH=f"{fake}:{os.environ['PATH']}")
    assert r.returncode == 1 and "already exists on GHCR" in r.stderr


def test_release_passes_when_ghcr_has_no_such_tag(repo, tmp_path_factory):
    path, _ = repo
    fake = tmp_path_factory.mktemp("bin")
    (fake / "docker").write_text("#!/bin/sh\nexit 1\n")
    (fake / "docker").chmod(0o755)
    assert check(path, "release", "v0.1.0", CHECK_GHCR="1", PATH=f"{fake}:{os.environ['PATH']}").returncode == 0


def test_a_missing_version_is_a_usage_error(repo):
    path, _ = repo
    (path / "claude_files_org" / "__init__.py").write_text("REQUIRES_API = 1\n")
    assert check(path, "pr").returncode == 2


def test_bad_usage(repo):
    path, _ = repo
    assert check(path).returncode == 2 and check(path, "release").returncode == 2
