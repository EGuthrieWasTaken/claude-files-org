# Spec Delta

## Purpose

Ships the org tools as a drop-in replacement image for the Emacs Files container, configured for Ethan's org setup by default, versioned and released the same way as claude-files.

## ADDED Requirements

### Requirement: Drop-in derived image
The image `ghcr.io/eguthriewastaken/claude-files-org` SHALL be built `FROM` a pinned `ghcr.io/eguthriewastaken/claude-files` tag, 1.4.0 or later, and SHALL load the tools via `EXTRA_TOOL_MODULES`. Every base setting (env vars, port, tokens, `/mcp` path, volumes, health check, non-root user, read-only rootfs support) SHALL work unchanged.

#### Scenario: Swap the image
- **WHEN** the Emacs Files container's image is changed from `claude-files` to `claude-files-org`, with no other change
- **THEN** it starts, every existing tool still works, and `org_*` tools appear in `tools/list`

#### Scenario: Read-only rootfs
- **WHEN** the container runs with `--read-only --tmpfs /tmp` and a bind-mounted folder
- **THEN** it starts, and the org tools can read and edit files in the folder

### Requirement: Ethan's org configuration is the default
With no `ORG_*` variables set, the tools SHALL behave as Ethan's `config.org` does:
- org files: `org-projects/inbox.org`;
- inbox heading: `Tasks`;
- keywords `TODO STARTED WAIT(@) | DONE CANCELLED(@)`;
- log done/reschedule/redeadline as `time`, into a drawer;
- tags `stephen jwa research coursework admin personal blog`, with `blog` in group `personal`;
- archive dir `org-projects/archive`; Emacs path `~/.emacs.d`;
- timezone `America/Indiana/Indianapolis`;
- the configured Effort values.

#### Scenario: Defaults
- **WHEN** the server starts with no `ORG_*` variables
- **THEN** `get_folder_info`'s extension block, and `org_list_items`'s result, report these settings

### Requirement: Settings are validated at startup
Every `ORG_*` setting SHALL be validated when the server starts. A bad keyword sequence, an unknown timezone, a file outside the served folder or a malformed tag group SHALL stop the server from starting, with a message naming the setting.

#### Scenario: Bad timezone
- **WHEN** `ORG_TIMEZONE=Mars/Olympus`
- **THEN** the server refuses to start, and the message names `ORG_TIMEZONE`

### Requirement: Agents are told how to use the tools
The extension's server instructions SHALL tell agents to:
- use the `org_*` tools rather than `write_file` for configured org files;
- follow `git_pull` → org tools → `git_commit` → `git_push`;
- treat `stale` as a signal to re-read;
- pass notes for WAIT and CANCELLED.

#### Scenario: Instructions present
- **WHEN** an MCP client initializes against the server
- **THEN** the instructions it receives include the org tools paragraph after the base server's text

### Requirement: Every PR ships a new version
The package version SHALL be the single source of truth for the image tag. CI SHALL fail a pull request whose version already has a git tag `vX.Y.Z`. A release whose tag differs from the version SHALL fail before building anything.

#### Scenario: Reused version
- **WHEN** a PR keeps version `0.1.0` after `v0.1.0` was released
- **THEN** the version check fails, naming the existing tag

### Requirement: Releases publish the image
Publishing a GitHub release `vX.Y.Z` SHALL build the image for `linux/amd64` and `linux/arm64` and push `:X.Y.Z`, plus `:latest` unless it is a pre-release, to GHCR using the repository's own token. It SHALL refuse a tag that already exists on GHCR.

#### Scenario: First release
- **WHEN** release `v0.1.0` is published
- **THEN** `ghcr.io/eguthriewastaken/claude-files-org:0.1.0` and `:latest` exist for both architectures
