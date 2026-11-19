# Spec Delta

## Purpose

Lets an agent change one org item the way Ethan would in Emacs, so the result is byte-for-byte what org-mode writes with his configuration and merges cleanly with his own edits.

## ADDED Requirements

### Requirement: Edits match org-mode byte for byte
For every edit tool, the changed lines SHALL be exactly what Emacs org-mode writes for the equivalent command on the same input, at the same time, with the configured settings: TODO keywords and their `@` note flags, log done, log into drawer, log reschedule, log redeadline. The reference is the org release pinned in this repository's oracle tests.

#### Scenario: Oracle agreement
- **WHEN** the oracle test suite applies an edit through the tool and the equivalent command through Emacs batch mode with the same fixed time
- **THEN** the two resulting files are byte-identical

### Requirement: State changes to a done keyword add CLOSED
`org_set_state` to a closed keyword SHALL add `CLOSED: [YYYY-MM-DD Ddd HH:MM]` as the first entry of the item's planning line, creating that line directly under the headline if there is none. Other planning entries SHALL keep their order and text.

#### Scenario: Close a scheduled item
- **WHEN** `** TODO alpha` with `SCHEDULED: <2026-11-13 Fri> DEADLINE: <2026-11-20 Fri 9:30>` is set to DONE at 2026-11-19 09:30
- **THEN** the planning line becomes `CLOSED: [2026-11-19 Thu 09:30] SCHEDULED: <2026-11-13 Fri> DEADLINE: <2026-11-20 Fri 9:30>`, and no `State` line is written for DONE

#### Scenario: Close an item with no planning line
- **WHEN** `*** TODO b1` with no planning line is set to DONE
- **THEN** a line `CLOSED: [2026-11-19 Thu 09:30]` is inserted directly under the headline

### Requirement: Reopening removes CLOSED
`org_set_state` from a closed keyword to an open one SHALL remove the `CLOSED:` entry from the planning line, and remove the line itself if nothing else is left on it.

#### Scenario: Reopen
- **WHEN** a DONE item whose planning line is only `CLOSED: [2026-11-19 Thu 09:30]` is set to TODO
- **THEN** the planning line is gone and the headline reads `TODO`

### Requirement: Keywords marked for a note require one
A target keyword configured with `@` (WAIT and CANCELLED by default) SHALL require a non-empty `note`. The tool SHALL write org's state entry at the top of the logbook, `- State "WAIT"       from "TODO"       [timestamp] \\`, followed by the note indented two spaces. A missing note SHALL refuse the edit and change nothing.

#### Scenario: Cancel with a reason
- **WHEN** an item is set to CANCELLED with note `Superseded by the entry with the real date and room.`
- **THEN** it gains `CLOSED:` plus `- State "CANCELLED"  from "TODO"       [2026-11-19 Thu 09:30] \\` and the indented note, as org writes it

#### Scenario: WAIT without a note
- **WHEN** an agent sets an item to WAIT and passes no note
- **THEN** the call fails with `note_required` and the file is unchanged

#### Scenario: Unknown keyword
- **WHEN** the target keyword is not in the item's file's TODO sequence
- **THEN** the call fails with `unknown_keyword`, listing the valid keywords

### Requirement: Logbook placement follows org
New logbook entries SHALL go at the top of the item's `:LOGBOOK:` drawer, newest first. If the item has no logbook, the drawer SHALL be created after the planning line and the property drawer. An optional `note` on any edit SHALL be appended to that edit's entry as org's ` \\` continuation, indented two spaces.

#### Scenario: First logbook entry
- **WHEN** an item with a planning line and a `:PROPERTIES:` drawer, but no logbook, is rescheduled
- **THEN** a `:LOGBOOK:` drawer holding the entry is inserted right after the property drawer's `:END:`, above the body

### Requirement: Rescheduling logs the previous date
`org_reschedule` SHALL set, replace or remove the item's SCHEDULED timestamp. When there was a previous one, it SHALL log `- Rescheduled from "[old]" on [now]`, or `- Not scheduled, was "[old]" on [now]` on removal. The old value is written as an inactive timestamp, keeping its time of day. Setting the date it already has SHALL change nothing.

#### Scenario: Move a date
- **WHEN** `SCHEDULED: <2026-11-13 Fri>` is moved to 2026-11-20
- **THEN** the planning line holds `SCHEDULED: <2026-11-20 Fri>`, and the logbook gains `- Rescheduled from "[2026-11-13 Fri]" on [2026-11-19 Thu 09:30]`

#### Scenario: First schedule
- **WHEN** an item with no SCHEDULED is scheduled for 2026-11-20
- **THEN** the timestamp is added and nothing is logged, as org does

#### Scenario: Time of day and ranges
- **WHEN** a date is given with time `13:00`, or with the range `13:00-14:00`
- **THEN** the timestamp is `<2026-11-20 Fri 13:00>` or `<2026-11-20 Fri 13:00-14:00>`

### Requirement: Deadlines log the previous deadline
`org_set_deadline` SHALL behave like `org_reschedule` for the DEADLINE timestamp. It logs `- New deadline from "[old]" on [now]` on a change, and `- Removed deadline, was "[old]" on [now]` on removal.

#### Scenario: Remove a deadline
- **WHEN** a deadline `<2026-11-20 Fri 9:30>` is removed
- **THEN** the logbook gains `- Removed deadline, was "[2026-11-20 Fri 9:30]" on [2026-11-19 Thu 09:30]`

### Requirement: Notes are org notes
`org_add_note` SHALL add `- Note taken on [now] \\` with the note text indented two spaces at the top of the logbook. Multi-line notes SHALL indent every line.

#### Scenario: Plain note
- **WHEN** the note `reply from Stephen on the draft` is added
- **THEN** the logbook's first entry is that note in org's format

### Requirement: Tags are validated and aligned like org
`org_set_tags` SHALL replace the item's own tags with the given list, in the given order. It SHALL refuse tags outside the configured set. Tags SHALL be aligned as org does: right-aligned to end at column 77, or one space after the title when it is too long. An empty list removes the tags.

#### Scenario: Aligned tags
- **WHEN** `** TODO alpha` gets tags `stephen`, `research`
- **THEN** the headline is `** TODO alpha` padded with spaces so that `:stephen:research:` ends at column 77

#### Scenario: Long headline
- **WHEN** the headline is too long for the tags to end at column 77
- **THEN** the tags follow the title after a single space

#### Scenario: Tag outside the set
- **WHEN** an agent passes tag `urgent` and it is not configured
- **THEN** the call fails with `unknown_tag`, listing the configured tags, and nothing changes

### Requirement: Effort is set as an org property
`org_set_effort` SHALL set or remove the `Effort` property in the item's property drawer, formatted as org does (`:Effort:   0:45`). It SHALL create the drawer in its required position if needed. Values SHALL be `H:MM`. A value outside the configured preferred list is accepted with a warning.

#### Scenario: New property drawer
- **WHEN** an item with a planning line and no property drawer gets effort `0:30`
- **THEN** `:PROPERTIES:`, `:Effort:   0:30` and `:END:` are inserted directly under the planning line

#### Scenario: Bad format
- **WHEN** an agent passes effort `90 minutes`
- **THEN** the call fails with `bad_effort` and nothing changes

### Requirement: Adding an item matches capture
`org_add_item` SHALL add `TODO title` as the last child of the given parent. The default parent is the configured inbox heading, `* Tasks`. It SHALL write optional tags (validated and aligned), an optional planning line, a property drawer with `:CREATED:  [now]` and an optional Effort, then optional body text, matching Ethan's `t` capture template. It returns the new id and rev.

#### Scenario: Add to the inbox
- **WHEN** an agent adds `review poster draft` with tags `research` and a deadline of 2026-11-23
- **THEN** a level-2 item `** TODO review poster draft` with aligned `:research:` is appended at the end of `* Tasks`, with `DEADLINE: <2026-11-23 Mon>` and a `:CREATED:` property, and no blank line is added

### Requirement: Parent progress cookies stay current
When a state change, an added item or an archived child changes the counts under a parent that has a `[n/m]` or `[n%]` cookie, the cookie SHALL be updated as org updates it: direct children with a TODO keyword, closed ones counted as done.

#### Scenario: Child closed
- **WHEN** `*** TODO b1` under `** TODO beta [0/2]` is set to DONE
- **THEN** the parent headline reads `** TODO beta [1/2]`, and nothing else on that line changes

### Requirement: Repeating timestamps are refused
An edit to an item whose SCHEDULED or DEADLINE carries a repeater (for example `+1w`, `.+1d` or `++1m`) SHALL be refused with `repeater_unsupported`, explaining that repeating tasks must be changed in Emacs.

#### Scenario: Weekly task
- **WHEN** an agent sets `SCHEDULED: <2026-11-20 Fri +1w>` to DONE
- **THEN** the call fails with `repeater_unsupported` and nothing changes
