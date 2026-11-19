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
| `ORG_TODO_KEYWORDS` | `TODO STARTED WAIT(@) \| DONE CANCELLED(@)` | TODO sequence. Keywords before `\|` are open, after it closed; `(@)` means a note is required. A `#+TODO:` line in a file overrides it for that file. |
| `ORG_TAGS` | `stephen,jwa,research,coursework,admin,personal,blog` | Allowed tags. |
| `ORG_TAG_GROUPS` | `personal=blog` | Tag groups as `parent=child[,child]`, separated by `;`. Filtering by the parent also matches the children. |
| `ORG_EFFORT_VALUES` | `0:15 0:30 0:45 1:00 1:30 2:00 3:00 4:00 6:00 8:00` | Preferred Effort values (`H:MM`). Other well-formed values are accepted with a warning. |
| `ORG_ARCHIVE_DIR` | `org-projects/archive` | Folder (relative to the served folder) holding `<file name>_archive` files. |
| `ORG_EMACS_ROOT` | `~/.emacs.d` | How Emacs names the served folder; used for `ARCHIVE_FILE` and the archive header. |
| `ORG_TIMEZONE` | `America/Indiana/Indianapolis` | Wall-clock timezone for every timestamp written and for "today". |

Logging is fixed to Ethan's values: log done, reschedule and redeadline are all `time`, into the
`:LOGBOOK:` drawer.
