# Spec Delta

## Purpose

Lets an agent read an org file as a list of items, find the ones it needs without loading the whole file, and get a stable handle (`id` + `rev`) to pass to the edit tools.

## ADDED Requirements

### Requirement: Org files are read as items
The system SHALL treat every headline as an item with its level, TODO keyword, title, own tags, planning timestamps (SCHEDULED, DEADLINE, CLOSED), properties, logbook entries, body and children. Text before the first headline is file preamble, not an item. A headline with no keyword is still an item.

#### Scenario: Headline without a keyword
- **WHEN** the file contains `** Midterm 1` followed by an active timestamp line
- **THEN** that item is returned with `keyword` null, `open` false, and the title `Midterm 1`

#### Scenario: Preamble is not an item
- **WHEN** a file starts with `#+TODO:` and `#+STARTUP:` lines before `* Tasks`
- **THEN** the item list starts at `* Tasks`, and the preamble lines are never part of any item

### Requirement: Open and closed follow the configured keywords
Keywords before `|` in the configured TODO sequence SHALL count as open and keywords after it as closed, using the same configuration as the edit tools. A `#+TODO:` line in the file overrides the configured sequence for that file.

#### Scenario: Default sequence
- **WHEN** no `#+TODO:` line is present and the default sequence `TODO STARTED WAIT | DONE CANCELLED` applies
- **THEN** items with TODO, STARTED or WAIT are open, and DONE or CANCELLED items are closed

#### Scenario: File overrides the sequence
- **WHEN** the file has `#+TODO: TODO NEXT | DONE`
- **THEN** NEXT counts as open in that file and WAIT is not recognized as a keyword there

### Requirement: Item id is stable across unrelated edits
Each item SHALL have an opaque `id` derived from its outline path of normalized titles (keyword, priority, tags and progress cookies removed) and its position among items with the same path. The id SHALL stay the same when other items are added, removed or edited, and when the item's own state, dates, tags, cookie or body change.

#### Scenario: Unrelated insert above
- **WHEN** a new item is added earlier in the file
- **THEN** every existing item keeps its `id`

#### Scenario: Cookie changes
- **WHEN** a project's cookie changes from `[19/21]` to `[20/21]`
- **THEN** the project's `id` is unchanged

#### Scenario: Duplicate titles
- **WHEN** two sibling items are both titled `Final Exam`
- **THEN** they have different ids, and each id resolves to the same item on every read until one of them is renamed, moved or removed

### Requirement: Item rev identifies the item's current text
Each item SHALL have a `rev`: a short hash of its own section's exact bytes, from its headline through the line before the next headline of any level. Changing any byte of that section SHALL change `rev`. Changes to children or to other items SHALL NOT.

#### Scenario: Child edit leaves parent rev alone
- **WHEN** a subtask's state changes and the parent has no progress cookie
- **THEN** the parent's `rev` is unchanged and the subtask's `rev` changes

### Requirement: List items with filters
`org_list_items` SHALL return items matching all given filters. The filters are: state (`open` by default, or `closed`, `all`, or explicit keywords), tags (including inherited tags and tag-group members), scheduled and deadline date ranges, `overdue`, title text, and a maximum count. Each result SHALL carry id, rev, outline path, level, keyword, title, own and inherited tags, the planning timestamps, Effort, CREATED, cookie, child count and line number, but no body.

#### Scenario: Default call
- **WHEN** an agent calls `org_list_items` with no arguments
- **THEN** it gets every open item in the default file, in file order, without bodies

#### Scenario: Inherited tags match
- **WHEN** a project is tagged `:research:stephen:` and its subtask has no tags of its own
- **THEN** filtering by tag `stephen` returns the subtask, with `inherited_tags` listing `research` and `stephen`

#### Scenario: Tag group
- **WHEN** an item is tagged `:blog:` and `blog` is configured as a member of the `personal` group
- **THEN** filtering by tag `personal` returns it

#### Scenario: Overdue
- **WHEN** an open item is SCHEDULED before today in the configured timezone, or has a DEADLINE before today
- **THEN** `overdue: true` includes it, and closed items are never overdue

#### Scenario: Result limit
- **WHEN** more items match than the `limit` argument allows
- **THEN** the result holds the first `limit` items in file order and says how many matched in total

### Requirement: Get one item in full
`org_get_item` SHALL return one item by `id`. The result has everything `org_list_items` returns, plus the body text, all properties, the parsed logbook entries (kind, timestamp, the old value where there is one, and the note), and a summary of each direct child.

#### Scenario: Logbook is parsed
- **WHEN** an item's logbook holds `- Rescheduled from "[2026-11-13 Fri]" on [2026-11-16 Mon 11:15]`
- **THEN** the entry comes back as kind `rescheduled`, old value `2026-11-13`, and time `2026-11-16 11:15`

#### Scenario: Unknown id
- **WHEN** the id matches no item, for example because the item was renamed or archived
- **THEN** the call fails with `not_found` and suggests calling `org_list_items` again

### Requirement: Lint reports structure org cannot read
`org_lint` SHALL report, with line numbers and without changing the file:
- property drawers not directly under the headline or planning line;
- drawers missing `:END:`;
- malformed timestamps;
- tags outside the configured set;
- duplicate outline paths;
- closed items that still have open children;
- invented logbook lines.

#### Scenario: Misplaced property drawer
- **WHEN** an item's `:PROPERTIES:` drawer sits after its `:LOGBOOK:` drawer
- **THEN** lint reports it as `misplaced_property_drawer` with the item and line, and notes that org ignores its properties

#### Scenario: Clean file
- **WHEN** the file has none of the listed problems
- **THEN** lint returns an empty problem list

### Requirement: Reads are limited to configured files
The query tools SHALL read only files listed in the configured org file set, resolved through the server's path-contained file access. With no `file` argument they SHALL use the first configured file. Read tools SHALL work with a read-only token.

#### Scenario: File outside the set
- **WHEN** an agent passes `file: "config.org"` and it is not in the configured set
- **THEN** the call fails, naming the files that are allowed

#### Scenario: Read-only token
- **WHEN** a read-only token calls `org_list_items`
- **THEN** the call succeeds
