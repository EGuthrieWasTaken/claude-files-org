# Spec Delta

## Purpose

Keeps the inbox small by moving finished work into the org archive file the same way Emacs's `org-archive-subtree` does, so archived history stays readable to org and to reports.

## ADDED Requirements

### Requirement: Archive one closed subtree
`org_archive` SHALL move an item and its whole subtree from its file to the archive file. The archive file is the configured archive directory plus `<file name>_archive`. The item SHALL be closed. Archiving an item that has an open descendant SHALL be refused with `open_descendants`, listing them.

#### Scenario: Archive a closed project
- **WHEN** a DONE level-2 item with only closed children is archived
- **THEN** its subtree is removed from `inbox.org` and appended to `archive/inbox.org_archive`, and every other line of `inbox.org` is unchanged

#### Scenario: Open child
- **WHEN** a DONE project still has a TODO subtask
- **THEN** the call fails with `open_descendants`, naming the subtask, and neither file changes

#### Scenario: Open item
- **WHEN** an agent archives an item whose keyword is open
- **THEN** the call fails with `not_closed`

### Requirement: Archived entries carry org's archive properties
The archived subtree's top headline SHALL become level 1, with every descendant shifted by the same amount. It SHALL gain `ARCHIVE_TIME`, `ARCHIVE_FILE`, `ARCHIVE_OLPATH`, `ARCHIVE_CATEGORY`, `ARCHIVE_TODO`, and `ARCHIVE_ITAGS` when it had inherited tags, in org's order and format, in its property drawer.

#### Scenario: Archived subtask with inherited tags
- **WHEN** `*** DONE b1` under `** TODO beta :stephen:` is archived at 2026-11-19 09:30
- **THEN** the archive gains `* DONE b1` with `:ARCHIVE_TIME: 2026-11-19 Thu 09:30`, `:ARCHIVE_FILE: ~/.emacs.d/org-projects/inbox.org`, `:ARCHIVE_OLPATH: Tasks/beta`, `:ARCHIVE_CATEGORY: inbox`, `:ARCHIVE_TODO: DONE` and `:ARCHIVE_ITAGS: stephen`

#### Scenario: Existing property drawer
- **WHEN** the archived item already has `:Effort:` in its property drawer
- **THEN** the archive properties are added to that same drawer after the existing properties, and no second drawer is created

### Requirement: Archive file paths are written as Emacs sees them
`ARCHIVE_FILE` and the archive file's header SHALL name the source file as Emacs sees it. That is the configured Emacs path for the served folder (default `~/.emacs.d`) joined with the file's path in the folder, not the container's path.

#### Scenario: Container path not leaked
- **WHEN** the server's folder is mounted at `/data`
- **THEN** `ARCHIVE_FILE` reads `~/.emacs.d/org-projects/inbox.org`, not `/data/org-projects/inbox.org`

### Requirement: A new archive file gets org's header
When the archive file does not exist, the system SHALL create it, and its directory if missing, with org's header (`#    -*- mode: org -*-`, then `Archived entries from file <path>`, with org's blank lines) before the first entry.

#### Scenario: First archive
- **WHEN** `archive/inbox.org_archive` does not exist and an item is archived
- **THEN** the new file starts with org's mode line and the `Archived entries from file ~/.emacs.d/org-projects/inbox.org` line, followed by the entry

### Requirement: Parent cookies are updated after archiving a child
When an archived item was a child of a parent with a progress cookie, the parent's cookie SHALL be recomputed from the children that remain, as org does.

#### Scenario: Cookie after archive
- **WHEN** DONE `b1` is archived from under `** TODO beta [1/2]`, leaving TODO `b2`
- **THEN** the parent reads `** TODO beta [0/1]`

### Requirement: Bulk archive by closing date
`org_archive_closed` SHALL archive every closed top-level item under the inbox heading that has no open descendants and whose `CLOSED` date is more than `older_than_days` days ago (default 30). It runs as one write per file. It SHALL list what it archived, and what it skipped and why.

#### Scenario: Monthly cleanup
- **WHEN** it runs with `older_than_days: 30` on 2026-12-19
- **THEN** closed top-level items closed before 2026-11-19 are archived, items closed since stay, and a closed project with an open child is listed under `skipped` with `open_descendants`

#### Scenario: Item without CLOSED
- **WHEN** a closed item has no `CLOSED:` timestamp
- **THEN** it is skipped with reason `no_closed_date`, and never archived by age

#### Scenario: Dry run
- **WHEN** it is called with `dry_run: true`
- **THEN** it returns the list and the diffs for both files and writes nothing
