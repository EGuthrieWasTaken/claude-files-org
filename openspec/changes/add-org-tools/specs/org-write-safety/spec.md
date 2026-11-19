# Spec Delta

## Purpose

Makes every org edit safe to run against a file that Ethan and other agents also change. An edit never overwrites unseen work, never touches unrelated text, and either happens completely or not at all.

## ADDED Requirements

### Requirement: Edits require the current rev
Every edit SHALL take the target item's `id` and the `rev` the caller last read. If the item's current `rev` differs, the edit SHALL be refused with `stale`, and the refusal SHALL include the item's current state and `rev`. Nothing is written.

#### Scenario: Changed since read
- **WHEN** Ethan's edit reschedules an item after an agent listed it, and the agent then sets it to DONE with the old rev
- **THEN** the call fails with `stale`, returning the item as it is now, and the file is unchanged

#### Scenario: Unrelated change elsewhere
- **WHEN** another item in the same file changed since the agent read the target
- **THEN** the edit to the target still succeeds

### Requirement: Untouched bytes stay identical
An edit SHALL change only the lines its operation calls for: the target item's own section, plus a parent's cookie line or the archive file where the operation requires it. Every other byte of the file SHALL be identical afterwards. That includes line endings, trailing whitespace, the final newline and malformed text elsewhere.

#### Scenario: Round trip
- **WHEN** a file is parsed and written back with no edit
- **THEN** the output is byte-identical to the input

#### Scenario: Malformed text elsewhere
- **WHEN** another item has a timestamp like `<2026-02-11 Wed: 12:30>`
- **THEN** an edit to a different item leaves that line exactly as it was

### Requirement: Writes are atomic and contained
Edits SHALL read and write only through the base server's path-contained file access. That access refuses symlinks, denied names and paths outside the folder, holds the worktree gate, and writes atomically, so a reader never sees a half-written file. Edits to the same file within the server SHALL be serialized.

#### Scenario: Concurrent edits
- **WHEN** two agents edit different items in the same file at the same moment
- **THEN** both edits land, one after the other, and neither is lost

#### Scenario: During a git pull
- **WHEN** an edit arrives while `git_pull` holds the worktree gate
- **THEN** the edit waits, or fails as busy, the same way `write_file` does, and never interleaves with the pull

### Requirement: Edit tools need a read-write token
All edit and archive tools SHALL be refused for a read-only token before anything is read for writing. Query and lint tools SHALL work with either token.

#### Scenario: Read-only token edits
- **WHEN** a read-only token calls `org_set_state`
- **THEN** the call fails with the server's read-only error and the file is unchanged

### Requirement: Every edit reports its diff
Every successful edit SHALL return a unified diff of each file it changed, the target's new `rev`, and each changed file's new sha256. With `dry_run: true`, it SHALL return the same diff and write nothing.

#### Scenario: Dry run
- **WHEN** `org_reschedule` is called with `dry_run: true`
- **THEN** the result holds the diff that would be applied, and the file's bytes and sha256 are unchanged

### Requirement: Batches are all-or-nothing
`org_batch` SHALL apply a list of edits to one file in order, as a single write. Each edit names its target `id` and `rev`. If any edit fails validation or its `rev` check, no edit SHALL be applied, and the result SHALL say which one failed and why.

#### Scenario: Weekly rebalance
- **WHEN** an agent submits twelve reschedules in one batch and all revs match
- **THEN** all twelve apply in one write, with one combined diff

#### Scenario: One stale edit
- **WHEN** the ninth edit in a batch has a stale rev
- **THEN** none of the twelve edits is applied, and the error names edit 9 as `stale`

### Requirement: Unsafe structure is refused, not guessed
An edit SHALL be refused with `unsafe_structure` when the target item's own section cannot be edited the way org would. Examples are an unclosed drawer, a property drawer org cannot see, or two planning lines. The refusal names the line and suggests `org_lint`. Problems elsewhere in the file SHALL NOT block edits to a healthy item.

#### Scenario: Unclosed drawer in target
- **WHEN** the target item has `:PROPERTIES:` with no matching `:END:`
- **THEN** the edit fails with `unsafe_structure`, naming the line, and nothing changes

### Requirement: Timestamps use the configured timezone
Timestamps the tools write (CLOSED, logbook times, CREATED, ARCHIVE_TIME) and the "today" used by date filters SHALL be wall-clock time in the configured timezone (default `America/Indiana/Indianapolis`), never UTC. Day abbreviations are in English.

#### Scenario: Evening in Indiana
- **WHEN** an item is closed at 2026-11-20 03:30 UTC
- **THEN** the CLOSED timestamp reads `[2026-11-19 Thu 22:30]`
