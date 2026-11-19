# Proposal

## Why

Agents change `org-projects/inbox.org` by rewriting the whole file with `write_file`. That has already cost real work: whole-file rewrites conflict with Ethan's own edits from his clone (the 2026-11-09 rebalance was lost in a merge), and earlier agents left structure org can't read (33 misplaced property drawers, invented logbook lines). Now that claude-files 1.3.0 can load extension tools (`EXTRA_TOOL_MODULES`), a set of org-aware MCP tools can make each change small, exactly what Emacs itself would write, and safe to merge.

## What Changes

- New Python package `claude_files_org`, loaded into a claude-files server as an extension module. It registers MCP tools that read and edit org files:
  - Read: `org_list_items`, `org_get_item`, `org_lint`.
  - Edit: `org_set_state`, `org_reschedule`, `org_set_deadline`, `org_add_item`, `org_add_note`, `org_set_tags`, `org_set_effort`, `org_batch`.
  - Archive: `org_archive` (one item) and `org_archive_closed` (bulk, closed more than N days ago).
- Every edit writes what Emacs org-mode (with Ethan's config) would write for the same command, byte for byte. That covers `CLOSED:` lines, logbook wording, notes, drawer order, tag alignment, progress cookies and archive properties. Everything else in the file stays byte-identical.
- Items are addressed by an opaque `id` (from their outline path) plus a `rev` (a hash of the item's own text). An edit whose `rev` no longer matches is refused, so an agent never overwrites a change it didn't see.
- All file access goes through the base server's path-contained `Vault` and worktree gate. Edit tools are refused for a read-only token. Every edit supports `dry_run`, which returns the diff and writes nothing.
- A derived image, `ghcr.io/eguthriewastaken/claude-files-org`, built `FROM ghcr.io/eguthriewastaken/claude-files:1.4.0`. It is a drop-in replacement for the Emacs Files container: same env vars, port, tokens, `/mcp` path and volumes, plus optional `ORG_*` settings.
- CI with byte-for-byte comparison against real Emacs batch mode ("oracle" tests), in-process tool tests against the 1.4.0 server, and a container smoke test. It also adds the same "every PR has a never-released version" rule and tag-driven release workflow as claude-files.

## Capabilities

### New Capabilities

- `org-item-query`: Reading org files as items. This covers parsing, item `id`/`rev`, the open/closed keyword split, inherited tags, `org_list_items` filters, `org_get_item` detail, and `org_lint` structural checks.
- `org-item-editing`: Changing one item the way org does. This covers state changes (with `CLOSED:` and required notes), schedule/deadline changes with their logbook entries, notes, tags, effort, adding items, and parent progress cookies.
- `org-archiving`: Moving closed subtrees to the archive file with org's archive properties and header, one item or in bulk by closing date.
- `org-write-safety`: Guarantees common to every edit. These are the `rev` check, untouched bytes left as they were, atomic writes through the Vault, read-only token refusal, `dry_run`, all-or-nothing `org_batch`, refusing structures it can't edit safely, and Eastern-local timestamps.
- `org-tools-deployment`: How the tools ship and are configured. This covers the derived image, `ORG_*` environment settings and their defaults, the server instructions agents see, versioning, and releases.

### Modified Capabilities

None. This is a new repository with no existing specs.

## Impact

- **New code:** the `claude_files_org/` package, its tests, the `Dockerfile`, and `.github/workflows/` (CI and release) in this repo.
- **Depends on** claude-files ≥ 1.4.0: the extension API v1 and the public `ghcr.io/eguthriewastaken/claude-files:1.4.0` base image.
- **Deployment:** the Emacs Files container switches its image to `ghcr.io/eguthriewastaken/claude-files-org`. Agents' workflow on `inbox.org` becomes `git_pull` → `org_*` tools → `git_commit` → `git_push`. The Emacs repo's `CLAUDE.md` already tells agents to use these tools once they exist.
- **No change** to claude-files itself, Ethan's Emacs config, or the existing `inbox.org` content.
