# Tasks

Implementation order for `add-org-tools`. Work on branch `claude/add-org-tools`, one commit per group, with that group's tests passing before moving on. The run's guardrails are in `openspec/config.yaml` (`operations.apply.guidance`). The specs say what to build, and `design.md` says how.

## 1. Scaffolding

- [x] 1.1 Create the `claude_files_org/` package with `__init__.py` (`__version__ = "0.1.0"`, `REQUIRES_API = 1`, a placeholder `INSTRUCTIONS`, and a `register(api)` that adds nothing yet), plus `requirements-dev.txt` (`pytest`), `pyproject.toml` pytest settings, a Python `.gitignore` and a `tests/` tree. Verify: `python -c "import claude_files_org"` succeeds and `pytest` exits 0 (no tests yet is fine).
- [x] 1.2 Add `tests/fixtures/`: synthetic org files covering every shape in design.md Decision 4. Verify: each file opens in `emacs --batch -Q` with org-mode and `org-element-parse-buffer` raises no error.

## 2. Configuration and timestamps

- [x] 2.1 Implement `ORG_*` settings with the defaults from design.md Decision 6. Keyword sequences parse `(@)` note flags and `|`, tag groups use `parent=child` syntax, and every value is validated (unknown timezone, file outside the folder, bad sequence). Verify: unit tests cover each default and each refusal message (org-tools-deployment: settings validated at startup).
- [x] 2.2 Implement org timestamp reading and writing: active and inactive forms, optional `H:MM` or `HH:MM` time, time ranges, English day abbreviations, repeater/warning cookies detected (for refusal) but never written, and "now" and "today" in `ORG_TIMEZONE`. Verify: unit tests, including the Indiana-evening scenario (org-write-safety) and single-digit hours (`9:30`) read and written back unchanged.
- [x] 2.3 Document every `ORG_*` setting in `README.md` (a table matching design.md Decision 6). Verify: the table lists exactly the variables the config module reads.

## 3. Parser, item model and identity

- [x] 3.1 Implement the line-preserving parser. It finds headlines (never inside `#+BEGIN_…`/`#+END_…` blocks), keyword (honoring `#+TODO:`), title, cookie and tags, the planning line, property and logbook drawers (with org's placement rules), the body and children. Verify: unit tests for each fixture shape, including the no-keyword heading and the preamble scenarios (org-item-query).
- [x] 3.2 Implement tag inheritance and group expansion, and the open/closed classification. Verify: unit tests for the inherited-tags and tag-group scenarios.
- [x] 3.3 Implement `id` and `rev` per design.md Decision 3. Verify: unit tests for every org-item-query identity scenario (unrelated insert, cookie change, duplicate titles, child edit leaves parent rev).
- [x] 3.4 Add the round-trip property test: parse and render every fixture with no edit, and assert byte identity. Add an opt-in test, skipped unless `ORG_ROUNDTRIP_FILES` names local files, that does the same for real files. Verify: the fixture round trip passes in `pytest`. If the real `inbox.org` and archive were downloaded locally (see guidance), the opt-in test passes on them too.

## 4. Oracle harness

- [x] 4.1 Write `tests/oracle/`: an Emacs batch driver (an elisp file with Ethan's org settings, frozen `current-time`, and `TZ` from the test) that applies one named org command to a copy of a fixture, plus a pytest helper. The helper runs the same operation through the tool engine and asserts byte equality, masking only the `:ARCHIVE_TIME:` value. Tests are skipped with a clear reason when `emacs` is missing. Verify: a sanity oracle test (reschedule on a fixture, implemented directly in elisp vs. a hand-written expected file) passes, and `emacs --version` reports 29.3 / org 9.6.15.

## 5. Query tools logic

- [x] 5.1 Implement list-items filtering (state, tags with inheritance and groups, scheduled and deadline ranges, overdue, text, limit plus a total count) and the result shape from org-item-query. Verify: unit tests for each scenario of "List items with filters".
- [x] 5.2 Implement get-item detail, with the logbook parsed into entries (state, rescheduled, not-scheduled, new-deadline, removed-deadline, note, unknown) and child summaries. Verify: unit tests for "Get one item in full", including `not_found`.
- [x] 5.3 Implement lint checks for every problem listed in org-item-query's lint requirement. Verify: unit tests with one fixture per problem, and an empty result on a clean fixture.

## 6. Edit engine and state changes

- [x] 6.1 Implement the edit engine: line-range replacements within one item's section, rendering, the runtime diff guard (design.md Decision 2), the `rev` check returning `stale` with current state, `unsafe_structure` detection for the target, and unified diff output. Verify: unit tests for `stale`, `unsafe_structure` and an `internal_error` case forced by a deliberately out-of-range replacement.
- [x] 6.2 Implement `set_state`: add CLOSED on closing, remove CLOSED on reopening, require notes for `@` keywords, place logbook entries (newest first, drawer creation position), reject unknown keywords, and update parent cookies. Verify: oracle tests for DONE (with and without a planning line), CANCELLED with a note, WAIT with a note, reopen, and child-closes-cookie, plus unit tests for `note_required` and `unknown_keyword`.

## 7. Schedule, deadline, notes, tags, effort and new items

- [x] 7.1 Implement `reschedule` and `set_deadline` (set, change, remove, same-date no-op, time and range, optional note continuation) and the repeater refusal. Verify: oracle tests for each scenario in org-item-editing's reschedule and deadline requirements, and a unit test for `repeater_unsupported`.
- [x] 7.2 Implement `add_note` (single and multi-line) and `set_tags` (validation, org's column-77 alignment, long headline, remove). Verify: oracle tests for the note, aligned tags, long-headline tags and tag removal, and a unit test for `unknown_tag`.
- [x] 7.3 Implement `set_effort` (set, replace, remove, drawer creation under the planning line, `bad_effort`, warning off the preferred list) and `add_item` (capture-equivalent placement under the inbox heading or a parent, CREATED, optional tags, planning, effort and body, and the parent cookie). Verify: oracle tests against `org-set-effort` and `org-capture` with the `t` template, and unit tests for `bad_effort` and the returned id/rev.

## 8. Batch and dry run

- [x] 8.1 Implement all-or-nothing batches (ordered ops on one file, one write, combined diff, failing op index and reason) and `dry_run` for every edit. Verify: unit tests for the weekly-rebalance and one-stale-edit scenarios, and that a dry run leaves the file's sha256 unchanged.

## 9. Archiving

- [x] 9.1 Implement single-item archive: the closed and no-open-descendant checks, level shift, archive properties (including `ARCHIVE_ITAGS`, appended to an existing drawer), `ARCHIVE_FILE` from `ORG_EMACS_ROOT`, archive file and directory creation with org's header, and the parent cookie update. Verify: oracle tests against `org-archive-subtree` for a closed project, a subtask with inherited tags, an item with an existing property drawer, and a first archive (header), with `ARCHIVE_TIME` masked; plus unit tests for `open_descendants` and `not_closed`.
- [x] 9.2 Implement `archive_closed` (older-than-N-days by CLOSED date in `ORG_TIMEZONE`, top-level under the inbox heading, skipped list with reasons, one write per file, dry run). Verify: unit tests for the monthly-cleanup, no-CLOSED-date and dry-run scenarios.

## 10. MCP tools

- [x] 10.1 Implement `register(api)`: register all tools from the proposal with `read_only` set correctly, route bodies through `api.guard`, use the fixed error vocabulary (design.md Decision 7), add per-file locks, enforce the configured file set (`file_not_allowed`), and write the final `INSTRUCTIONS` (org-tools-deployment: agents are told how to use the tools). Verify: unit tests for argument validation, and a test that every tool's input schema has no `ctx` and has the documented parameters.
- [x] 10.2 Add in-process integration tests that load the real claude-files 1.4.0 app with `EXTRA_TOOL_MODULES=claude_files_org` and a fixture folder, and drive it through `/mcp`. Cover: tools listed; instructions present; rw edit works; ro edit refused before anything changes; reads work with ro; stale refusal; two threads editing different items both land; an edit during a held worktree gate waits or fails busy; dry run; `get_folder_info` lists the module. App code comes from `CLAUDE_FILES_APP` (a path to claude-files' `app/` parent). Verify: the suite passes locally against a claude-files checkout at `v1.4.0`.
- [x] 10.3 Document every tool in `README.md` (purpose, parameters, result, errors, one example call). Verify: the documented tool list matches `tools/list` from the integration test.

## 11. Image

- [ ] 11.1 Write the `Dockerfile` per design.md Decision 8, plus `tests/container_smoke.sh`, which builds the image, runs it with production hardening flags and a fixture folder, and checks: `tools/list` includes `org_*`; `org_list_items`; a dry run; a real edit visible on disk; an ro-token refusal; health OK. Verify: the script passes locally (the base image can come from a local `docker build` of claude-files `v1.3.0` tagged as the GHCR name when GHCR is not reachable).
- [ ] 11.2 Document deployment in `README.md`: the prerequisites (GHCR access for CI and for the host), the image swap for the Emacs Files container, verification and rollback (design.md Migration Plan). Verify: every command in the section is the same one the smoke test or the release workflow runs.

## 12. CI and release

- [ ] 12.1 Add `.github/workflows/ci.yml` with these jobs:
  - unit + oracle on `ubuntu-24.04` with `emacs-nox`;
  - in-process integration, extracting `/srv/app` from `ghcr.io/eguthriewastaken/claude-files:1.4.0` (public, no login needed), failing with a message naming the image if the pull is denied;
  - container smoke;
  - version check.

  Verify: `actionlint` and `shellcheck` are clean, and every job's commands pass locally.
- [x] 12.2 Add `.github/scripts/check-version.sh` (reads `claude_files_org/__init__.py`, PR mode refuses an existing git tag, release mode checks tag equality and GHCR) and `.github/workflows/release.yml` (amd64+arm64, `:X.Y.Z` plus `:latest`, `GITHUB_TOKEN`, refuses an existing tag), adapted from claude-files. Verify: script cases tested locally (pass, existing tag, mismatched release tag), and actionlint is clean.

## 13. Integration and hand-off

- [ ] 13.1 Run every suite from a clean checkout (unit, oracle, in-process integration, container smoke, version check), and the opt-in real-file round trip if the files were downloaded. Verify: all pass, and the counts are recorded for the PR description.
- [ ] 13.2 Push `claude/add-org-tools` and open one PR against `main`. List what was built, the test counts, any oracle discrepancies from the specs (and how they were resolved), the CI status per job, and the remaining manual steps from design.md's Migration Plan. Verify: the PR exists, and its CI results are reported. A red job caused only by the missing GHCR access prerequisite is called out as that, not as a code failure.

## Workflow follow-up

- Ethan reviews the PR. After merge, publish release `v0.1.0` and follow design.md's Migration Plan steps 2–3.
- After deployment, archive this change with `openspec archive add-org-tools`, so its specs become `openspec/specs/`.
