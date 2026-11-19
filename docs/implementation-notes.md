# Implementation notes: where the Emacs oracle and the specs differ

Found while implementing `add-org-tools` against Emacs 29.3 / org 9.6.15. The specs were not edited
(see `openspec/config.yaml`); each item says what the tools do.

## Spec scenario vs. oracle

- **Archive file header path.** Emacs writes the *absolute* path of the source file in the header of a new
  archive file (`Archived entries from file /home/me/.emacs.d/org-projects/inbox.org`), while
  `ARCHIVE_FILE` uses the `~` form. The spec asks for the `~/.emacs.d/...` form in both, and the container
  cannot know the host's home directory, so the tools follow the spec. The oracle tests fold `$HOME` to `~`
  before comparing.
- **Setting the date an item already has.** `org-schedule` and `org-deadline` still rewrite the planning
  line (moving the entry to the front and dropping `CLOSED`) even though no log entry is written. The spec
  says "change nothing", so the tools make no edit at all. The bytes agree with Emacs whenever the entry is
  already first and there is no `CLOSED`.

## Behavior the specs do not mention (the tools match org)

- A new or changed `SCHEDULED`/`DEADLINE` entry goes to the *front* of the planning line, and setting either
  one on a closed item removes its `CLOSED:` entry (`org-add-planning-info ... 'closed`).
- Creating a `:LOGBOOK:` drawer under an item whose section ends at the next headline also leaves a blank
  line after `:END:` (the quirk of `org-log-beginning`). Property drawers do not.
- `org-capture` puts the new entry after the last non-blank line of the target subtree and swallows the
  subtree's trailing blank lines. It also refreshes the parent's progress cookie.
- A state change realigns the headline's tags (`org-auto-align-tags`), and a changed cookie width realigns
  them on the parent.
- Only the direct parent's cookie is refreshed (`org-hierarchical-todo-statistics`).
- Setting an item to the state it already has is a no-op (org would log `WAIT` again).
- Removing the only property from a drawer removes the drawer.
- A `#+BEGIN_SRC` block that contains an unescaped `* ` line is read by Emacs's outline commands as a
  headline. The parser follows the design (lines inside `#+BEGIN_…`/`#+END_…` blocks are never headlines),
  which agrees with Emacs for valid org, where such lines are comma-escaped (`,* `). The oracle fixtures use
  comma-escaped lines; `src_block_unescaped.org` is parser-only.

## Error codes

The fixed vocabulary of design.md Decision 7 is used as is. A note line that is exactly `:END:` is refused as
`unsafe_structure`; other malformed arguments are plain `ValueError`s that `api.guard` reports as messages.
