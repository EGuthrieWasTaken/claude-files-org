#!/usr/bin/env bash
# Version gate for claude-files-org. The package version is the single source of truth for the image tag.
#
#   check-version.sh pr                 fail if v<version> is already a git tag (every PR ships a new version)
#   check-version.sh release <tag>      fail unless <tag> is exactly v<version>; with CHECK_GHCR=1 also fail
#                                       if ghcr.io/<IMAGE>:<version> already exists
#
# Env: VERSION_FILE (default claude_files_org/__init__.py), IMAGE (default
# ghcr.io/eguthriewastaken/claude-files-org), CHECK_GHCR.
set -euo pipefail

mode="${1:-}"
version_file="${VERSION_FILE:-claude_files_org/__init__.py}"
image="${IMAGE:-ghcr.io/eguthriewastaken/claude-files-org}"

version="$(sed -n 's/^__version__ = "\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)"$/\1/p' "$version_file" | head -n 1)"
if [ -z "$version" ]; then
  echo "error: no __version__ = \"X.Y.Z\" in $version_file" >&2
  exit 2
fi

case "$mode" in
  pr)
    if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
      echo "error: version $version is already released (git tag v$version exists). Bump __version__ in $version_file." >&2
      exit 1
    fi
    echo "ok: version $version has no git tag yet"
    ;;
  release)
    tag="${2:-}"
    if [ -z "$tag" ]; then
      echo "usage: $0 release <tag>" >&2
      exit 2
    fi
    if [ "$tag" != "v$version" ]; then
      echo "error: release tag $tag does not match the package version v$version ($version_file)." >&2
      exit 1
    fi
    if [ "${CHECK_GHCR:-}" = "1" ] && docker manifest inspect "$image:$version" >/dev/null 2>&1; then
      echo "error: $image:$version already exists on GHCR; refusing to overwrite it." >&2
      exit 1
    fi
    echo "ok: release $tag matches version $version"
    ;;
  *)
    echo "usage: $0 pr | release <tag>" >&2
    exit 2
    ;;
esac
