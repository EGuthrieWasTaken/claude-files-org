# claude-files-org

Org-aware MCP tools for [claude-files](https://github.com/EGuthrieWasTaken/claude-files), loaded as an
extension module (`EXTRA_TOOL_MODULES=claude_files_org`, extension API v1). Every edit writes exactly
what Emacs org-mode would write for the same command, and leaves every other byte of the file alone.

Standard library only at runtime; Python 3.12.

## Configuration

All settings are optional environment variables, validated when the server starts. A bad value stops
the server with a message naming the variable. The defaults reproduce Ethan's Emacs setup.

| Variable | Default | Meaning |
|---|---|---|
| `ORG_FILES` | `org-projects/inbox.org` | Comma-separated org files (relative to the served folder) the tools may read and edit. The first one is the default. |
| `ORG_INBOX_HEADING` | `Tasks` | Top-level heading that new items are added under and that `org_archive_closed` sweeps. |
| `ORG_TODO_KEYWORDS` | `TODO STARTED WAIT(@) \| DONE CANCELLED(@)` | TODO sequence. Keywords before `\|` are open, after it closed; `(@)` means a note is required. `;` works in place of `\|` (for the unRAID template, which treats `\|` as a dropdown delimiter): `TODO STARTED NEXT WAIT(@) ; DONE CANCELLED(@)`. A `#+TODO:` line in a file overrides it for that file. |
| `ORG_TAGS` | `stephen,jwa,research,coursework,admin,personal,blog` | Allowed tags. |
| `ORG_TAG_GROUPS` | `personal=blog` | Tag groups as `parent=child[,child]`, separated by `;`. Filtering by the parent also matches the children. |
| `ORG_EFFORT_VALUES` | `0:15 0:30 0:45 1:00 1:30 2:00 3:00 4:00 6:00 8:00` | Preferred Effort values (`H:MM`). Other well-formed values are accepted with a warning. |
| `ORG_ARCHIVE_DIR` | `org-projects/archive` | Folder (relative to the served folder) holding `<file name>_archive` files. |
| `ORG_EMACS_ROOT` | `~/.emacs.d` | How Emacs names the served folder; used for `ARCHIVE_FILE` and the archive header. |
| `ORG_TIMEZONE` | `America/Indiana/Indianapolis` | Wall-clock timezone for every timestamp written and for "today". |

Logging is fixed to Ethan's values: log done, reschedule and redeadline are all `time`, into the
`:LOGBOOK:` drawer.

## Tools

Every edit tool takes the target item's `id` and the `rev` you last read (both come from `org_list_items`
or `org_get_item`), accepts `file` (default: the first `ORG_FILES` entry) and `dry_run` (return the diff,
write nothing), and returns `{file, dry_run, changed, written, diff, sha256: {path: sha}, id, rev,
warnings?}`. Edit and archive tools are refused for a read-only token before anything is read. A failed call
is a tool error whose message starts with its code (`stale`, `not_found`, `note_required`, `unknown_keyword`,
`unknown_tag`, `bad_effort`, `bad_date`, `repeater_unsupported`, `unsafe_structure`, `open_descendants`,
`not_closed`, `file_not_allowed`, `internal_error`) followed by what to do next. `stale` also carries the
item's current state as JSON.

Typical flow: `git_pull`, `org_list_items`, edit tools, `git_commit`, `git_push`.

### `org_list_items`
Items without bodies, in file order. Parameters: `state` (`open` default, `closed`, `all`, or keywords such as
`["WAIT"]`), `tags` (all must match, own or inherited; a group name matches its members), `scheduled_from`,
`scheduled_to`, `deadline_from`, `deadline_to` (inclusive `YYYY-MM-DD`), `overdue`, `text`, `limit`. Result:
`{file, today, total, returned, items: [{id, rev, path, level, keyword, open, title, tags, inherited_tags,
scheduled, deadline, closed, effort, created, cookie, child_count, line}], settings}`. Works with a read-only
token. Example: `org_list_items(tags=["stephen"], overdue=true)`.

### `org_get_item`
One item in full: the list fields plus `body`, `properties`, `logbook` (entries of kind `state`, `rescheduled`,
`not_scheduled`, `new_deadline`, `removed_deadline`, `note`, `unknown`) and `children`. Errors: `not_found`.
Example: `org_get_item(id="o_1f7c84a75a")`.

### `org_lint`
Reports, without changing anything, `misplaced_property_drawer`, `unclosed_drawer`, `malformed_timestamp`,
`unknown_tag`, `duplicate_path`, `closed_with_open_children`, `invented_logbook_line` and `two_planning_lines`,
each with item and line. Example: `org_lint()`.

### `org_set_state`
`state`, optional `note`. Adds `CLOSED:` for a closed keyword, removes it on reopening, writes org's `State`
logbook entry for `(@)` keywords (WAIT, CANCELLED), and refreshes the parent's `[n/m]`/`[n%]` cookie. Errors:
`note_required`, `unknown_keyword`, `repeater_unsupported`, `unsafe_structure`. Example:
`org_set_state(id, rev, state="WAIT", note="waiting for Stephen")`.

### `org_reschedule` and `org_set_deadline`
`date` (`YYYY-MM-DD`), optional `time` (`H:MM` or `HH:MM-HH:MM`), `remove` (drop the timestamp), optional
`note`. Logs the previous value as org does and drops `CLOSED:`. The date an item already has changes nothing.
Errors: `bad_date`, `repeater_unsupported`, `unsafe_structure`. Example:
`org_reschedule(id, rev, date="2026-11-20", time="13:00")`.

### `org_add_note`
`note` (multi-line allowed): a `Note taken on [now]` entry at the top of the logbook. Errors: `note_required`.
Example: `org_add_note(id, rev, note="reply from Stephen on the draft")`.

### `org_set_tags`
`tags`: replaces the item's own tags in the given order, aligned at column 77; `[]` removes them. Errors:
`unknown_tag`. Example: `org_set_tags(id, rev, tags=["stephen", "research"])`.

### `org_set_effort`
`value` (`H:MM`) or `remove`. A value outside `ORG_EFFORT_VALUES` is accepted with a warning. Errors:
`bad_effort`. Example: `org_set_effort(id, rev, value="0:45")`.

### `org_add_item`
`title`, optional `parent_id` + `parent_rev` (default: the inbox heading), `tags`, `scheduled`,
`scheduled_time`, `deadline`, `deadline_time`, `effort`, `body`. Adds `TODO title` as the last child, like the
capture template, and returns the new `id` and `rev`. Example:
`org_add_item(title="review poster draft", tags=["research"], deadline="2026-11-23")`.

### `org_batch`
`edits`: a list of `{op, id, rev, ...args}` with `op` one of `set_state`, `reschedule`, `set_deadline`,
`add_note`, `set_tags`, `set_effort`, `add_item`. All or nothing, one write, one combined diff, revs checked
against the file as you read it; a failure names the edit (`edit 9 (reschedule): stale: ...`). Example:
`org_batch(edits=[{"op": "reschedule", "id": a, "rev": ra, "date": "2026-11-27"}, ...])`.

### `org_archive`
Moves a closed item and its subtree to `<ORG_ARCHIVE_DIR>/<file>_archive` like `org-archive-subtree`
(`ARCHIVE_*` properties, level 1, new files get org's header). Errors: `not_closed`, `open_descendants`.
Example: `org_archive(id, rev)`.

### `org_archive_closed`
`older_than_days` (default 30): archives closed top-level items under the inbox heading closed more than that
many days ago with no open descendants. Returns `archived` and `skipped` (with `reason`: `open_descendants`,
`no_closed_date`, `too_recent`). Example: `org_archive_closed(older_than_days=30, dry_run=true)`.

## Deployment

The image `ghcr.io/eguthriewastaken/claude-files-org` is built `FROM ghcr.io/eguthriewastaken/claude-files:1.4.0`
and is a drop-in replacement for the Emacs Files container: same port, env vars, tokens, `/mcp` path and
volumes; the `org_*` tools are loaded through `EXTRA_TOOL_MODULES=claude_files_org`. Optional `ORG_*`
settings are described above.

**Prerequisites**

- The base image `ghcr.io/eguthriewastaken/claude-files` is public, so CI pulls it without logging in. If it
  is ever made private, CI fails with a message naming the image.
- `claude-files-org` is private. The host that runs it needs to pull it: make the package public (GitHub >
  Packages > claude-files-org > Package settings), or log the host in to GHCR with a token that can read it.

**Check a build before releasing.** `tests/container_smoke.sh` builds the image and runs it with
`--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges` and a bind-mounted folder, then
checks `/health`, `tools/list`, `org_list_items`, a dry run, a real edit on disk and a read-only token's
refusal:

```bash
tests/container_smoke.sh
```

**Release.** Every pull request needs a `__version__` that has never been released (CI runs the first command
below), and publishing a GitHub release `vX.Y.Z` runs the second, builds `linux/amd64` and `linux/arm64`, and
pushes `:X.Y.Z` plus `:latest` (not for pre-releases):

```bash
.github/scripts/check-version.sh pr
.github/scripts/check-version.sh release v0.1.0
```

**Swap the image.** In the Emacs Files container's settings change the Repository from
`ghcr.io/eguthriewastaken/claude-files:latest` to `ghcr.io/eguthriewastaken/claude-files-org:latest`, keeping
every other setting. Verify that `tools/list` shows the `org_*` tools and that `org_list_items` returns the
open items (`get_folder_info` lists the module under `extensions`).

**Roll back.** Set the Repository back to `ghcr.io/eguthriewastaken/claude-files:latest`. The tools store
nothing outside the org files, so nothing else needs undoing.
