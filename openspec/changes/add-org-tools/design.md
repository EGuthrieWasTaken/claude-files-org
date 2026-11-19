# Design

## Context

- **Host server.** claude-files 1.4.0 (extension API v1, unchanged since it arrived in 1.3.0) loads modules named in `EXTRA_TOOL_MODULES` and calls `register(api)`; the contract is in claude-files `docs/extensions.md`. `api` provides:
  - `api.vault`: path-contained reads, and atomic writes under the worktree gate;
  - `api.add_tool(fn, read_only=...)`: write tools are refused for read-only tokens before `fn` runs;
  - `api.guard` and `api.run_in_thread`;
  - `api.config` and `api.log`.

  The SDK is pinned to `mcp==1.12.4`, so tool modules must not use `from __future__ import annotations`. The base image is Python 3.12 on Debian and includes `/usr/share/zoneinfo`, so `zoneinfo` needs no extra package.
- **The data.** `org-projects/inbox.org` is now about 52 KB, LF line endings, ASCII:
  - one `* Tasks` heading; projects at level 2, subtasks at levels 3–4;
  - planning lines flush left; `:PROPERTIES:` holding `:Effort:` (and `:CREATED:` for new captures), then `:LOGBOOK:`;
  - tags on 35 headlines; no repeaters, IDs or priorities in use.

  Ethan edits it in Emacs from his own git clone, and agents edit the server's clone. Conflicts surface in git merges.
- **The reference behavior.** Ethan's org settings (`config.org`, `* Org Agenda` section):
  - keywords `TODO(t) STARTED(s) WAIT(w@) | DONE(d) CANCELLED(c@)`;
  - `org-log-done`, `org-log-reschedule` and `org-log-redeadline` all `time`; `org-log-into-drawer` `t`;
  - archive location `<org-projects>/archive/%s_archive::`;
  - the tag alist with `blog` grouped under `personal`;
  - capture template `t`.

  The exact output formats used in the specs (state lines, reschedule and deadline logs, notes, tag column 77, `:Effort:   0:45`, archive properties including `ARCHIVE_ITAGS`, cookie updates, capture placement) were confirmed in Emacs 29.3 / org 9.6.15 batch runs while writing this change.
- **Access constraints.** `claude-files` and its image `ghcr.io/eguthriewastaken/claude-files` are public, so CI here pulls the base image without credentials. `claude-files-org` itself is private. The agent sandbox cannot reach GHCR's blob host (`pkg-containers.githubusercontent.com`) or GNU ELPA; GitHub runners can reach both. Locally, the base image is built from a claude-files `v1.4.0` checkout instead of pulled.

## Goals / Non-Goals

**Goals:**
- One edit tool call produces exactly the bytes Emacs would, and nothing else changes. Verified mechanically, not by inspection.
- An agent can do a whole weekly rebalance in one `org_batch` call with one small diff.
- Zero changes to claude-files. Everything rides on extension API v1.

**Non-Goals:**
- Repeating tasks, clocking (`CLOCK:` lines), refiling between files, priority editing, renaming headlines, rewriting bodies (`org_add_note` and `org_add_item` cover the agent cases for now), and `:ID:` properties.
- General org-mode configuration emulation. Settings cover Ethan's options, and other org options keep org's defaults.
- Editing org files other than the configured set. The set defaults to `inbox.org` only; the archive file is written only by the archive tools.
- Deploying the image or changing the Emacs repo. Those are Ethan's steps after review.

## Decisions

### 1. A small line-preserving parser, not an org library
The parser keeps the file as its original lines and builds an index of items over them:
- headline line, planning line, drawer spans, body span, children;
- byte offsets for each.

Edits are expressed as replacements of specific line ranges inside one item's section (plus a cookie line or the archive file). Rendering re-joins the untouched lines verbatim.
- *Alternatives:* `orgparse` and similar libraries read but do not round-trip, and would re-serialize the whole file. Driving Emacs itself (`emacs --batch`) inside the container would be exact, but adds about 100 MB to the image and Ethan's whole config to the server's trust surface.
- *Rationale:* byte preservation is the core requirement, and a narrow parser is the cheapest way to guarantee it.

### 2. A runtime diff guard on every write
After computing the new text, the engine compares old and new line by line and checks that every changed line falls inside the ranges the operation declared. If anything else changed, the write is refused as `internal_error` and logged. This turns a parser bug into a refusal, not a corrupted file.

### 3. Identity: path-hash `id`, section-hash `rev`
- `id` = `o_` + 10 hex digits of the sha256 of the normalized outline path, plus the occurrence index among identical paths.
- `rev` = 12 hex digits of the sha256 of the section's bytes.

Both are recomputed on every read. Nothing is stored, and nothing is written into the file.
- *Alternatives:* adding `:ID:` properties (rejected by Ethan: adds lines); line numbers (shift with every edit).
- *Known edge:* when one of two identical paths is archived, the other's occurrence index can change. That only ever yields `stale` or `not_found`, never a wrong edit, because `rev` must still match.

### 4. Emacs batch mode as the test oracle
Oracle tests run each operation twice on the same fixture: once through the tool, and once through `emacs --batch -Q` with the configured org settings and a frozen clock (`cl-letf` on `current-time`, `TZ` set). The results are compared byte for byte.
- `ARCHIVE_TIME` comes from a clock org reads directly, which `cl-letf` cannot freeze, so the oracle masks that one line and checks its format separately.
- The org pin for v1 is the org bundled with Emacs 29.3 (9.6.15). That is what `apt install emacs-nox` gives on `ubuntu-24.04` runners and in the agent sandbox, so local and CI results agree.
- Fixtures are synthetic but mirror the real file's shapes: no-keyword headings, duplicate titles, cookies, drawers in both orders, unclosed drawer, malformed timestamp, long headlines. Real `inbox.org` content is never committed.

### 5. Three test layers, each runnable locally
- **Unit and oracle** (`pytest`, plus Emacs): pure Python, plus the Emacs comparisons.
- **In-process integration:** the real claude-files 1.4.0 app with `EXTRA_TOOL_MODULES=claude_files_org`, driven through `/mcp` with a `TestClient` and rw/ro tokens, following claude-files' `tests/extension_tests.py` pattern.
  - In CI, the app code and its `requirements*.txt` come out of the pinned base image (`docker create` + `docker cp /srv/app`).
  - Locally, they come from a claude-files checkout at `v1.4.0`.
- **Container smoke test:** build the derived image and run it as production does:
  - `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges`, bind-mounting a fixture folder;
  - `tools/list`;
  - one dry run and one real edit;
  - an ro-token refusal.

### 6. Configuration via `ORG_*` environment variables
| Variable | Default |
|---|---|
| `ORG_FILES` | `org-projects/inbox.org` (comma list) |
| `ORG_INBOX_HEADING` | `Tasks` |
| `ORG_TODO_KEYWORDS` | `TODO STARTED WAIT(@) \| DONE CANCELLED(@)` |
| `ORG_TAGS` | `stephen,jwa,research,coursework,admin,personal,blog` |
| `ORG_TAG_GROUPS` | `personal=blog` |
| `ORG_EFFORT_VALUES` | `0:15 0:30 0:45 1:00 1:30 2:00 3:00 4:00 6:00 8:00` |
| `ORG_ARCHIVE_DIR` | `org-projects/archive` |
| `ORG_EMACS_ROOT` | `~/.emacs.d` (how Emacs names the served folder) |
| `ORG_TIMEZONE` | `America/Indiana/Indianapolis` |

All variables are validated at import time, so a bad value stops the server from starting (claude-files turns it into an `ExtensionError`). Log settings are fixed to Ethan's values, not configurable, until there is a need.

### 7. Tool surface and execution
- Tools are sync functions. A whole-file parse of 50–120 KB takes milliseconds, so worker threads are not worth their complexity.
- Each tool body runs inside `api.guard`, so `ValueError`s reach the agent as messages and are logged as `denied MCP org_*`.
- A per-file `threading.Lock` serializes read-modify-write within the process. The vault's atomic write plus the `rev` check cover everything outside it.
- Error codes are a fixed vocabulary: `stale`, `not_found`, `note_required`, `unknown_keyword`, `unknown_tag`, `bad_effort`, `bad_date`, `repeater_unsupported`, `unsafe_structure`, `open_descendants`, `not_closed`, `file_not_allowed`, `internal_error`. Each comes with a message telling the agent what to do next.

### 8. Package and image layout
- `claude_files_org/` is a plain package:
  - `__init__.py` exposes `REQUIRES_API = 1`, `INSTRUCTIONS`, `register`, and `__version__`;
  - modules cover config, timestamps, the parser/model, ids, edits, archive, lint and tools.
- No runtime dependencies beyond the standard library.
- The `Dockerfile` does four things:
  - starts `FROM ghcr.io/eguthriewastaken/claude-files:1.4.0`;
  - `COPY`s the package to `/srv/claude_files_org/` (uvicorn runs from `/srv`, so it is importable);
  - byte-compiles it as root, then returns to `USER 1000:1000`;
  - sets `ENV EXTRA_TOOL_MODULES=claude_files_org`.
- Dev and test dependencies (`pytest`) live in `requirements-dev.txt`.

### 9. Versioning and release copied from claude-files
- `__version__` is the single source of truth.
- `.github/scripts/check-version.sh` (adapted: one image, git tags only) runs on PRs. `release.yml` builds and pushes `ghcr.io/eguthriewastaken/claude-files-org` for amd64 and arm64 on a published release.
- The first version is `0.1.0`.

## Risks / Trade-offs

- **Oracle org version ≠ Ethan's org version** (his elpaca build is likely 9.7.x), so formats could differ in edge cases. → The pin is one line in CI. The formats the specs rely on are long-stable in org, and the open question below tracks confirming his version.
- **Hand-written parser misreads an unusual construct** (inline tasks, `#+BEGIN_SRC` blocks containing `* `-prefixed lines, CRLF). → Lines inside `#+BEGIN_…`/`#+END_…` blocks are never treated as headlines. The round-trip property test runs on every fixture, plus a local-only round trip of the real `inbox.org` and its archive. The runtime diff guard (Decision 2) refuses anything unexpected.
- **The base image becomes unpullable** (made private again, or GHCR down). → The CI job that needs it fails with a message naming the image and the access fix. Unit and oracle jobs don't need the image and still run.
- **`id` instability for duplicate titles.** → Documented. It fails safe (Decision 3).
- **An agent bypasses the tools with `write_file`.** → Out of scope to forbid. The server instructions and the Emacs repo's `CLAUDE.md` both point agents at the tools.

## Migration Plan

0. *(Done 2026-11-19.)* `ghcr.io/eguthriewastaken/claude-files` is public, so CI pulls the base image without credentials.
1. Review and merge the implementation PR. Publish release `v0.1.0`, which builds and pushes the image.
2. Make the `claude-files-org` package public, or log the unRAID host in to GHCR.
3. Change the Emacs Files container's Repository to `ghcr.io/eguthriewastaken/claude-files-org:latest`, keeping every other setting. Verify that `tools/list` shows the `org_*` tools and that `org_list_items` returns the open items.
4. **Rollback:** set the Repository back to `ghcr.io/eguthriewastaken/claude-files:latest`. The tools store nothing outside the org files, so nothing else needs undoing.

## Open Questions

- Ethan's exact org version (`M-x org-version`). If it isn't 9.6.x, bump the oracle pin to that release from GNU ELPA in CI and re-run the oracle suite. This doesn't change the specs or the tasks.
