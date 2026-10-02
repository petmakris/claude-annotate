# Editing text in annotate

Date: 2026-10-01. Status: design approved (the user chose every recommendation), written spec awaiting review.

Mockups the decisions were made on: https://claude.ai/artifact/8Jb1V8aukqCZMBQdgvUNGT

Depends on: the selection menu (`docs/superpowers/plans/2026-10-01-selection-menu.md`), specifically `AnnotateSelection.registerAction` and the text anchors in `anchors.js`.

## 1. What this changes, and why

Annotate helps the user find their voice with Claude, but the finished words are the user's. So the user can open any section and change its text directly. What they save is final:
- The section takes it byte for byte.
- Claude is told exactly what changed.
- Claude keeps those words as they are from then on.

Success looks like this:

- Pressing `e` on a section, or ✎ in the selection menu, turns that section's card into an editor in place. Nothing on the page moves.
- What is saved is exactly what was typed. Tables, code fences and hard-wrapped lines come back unchanged.
- The next round tells Claude the exact before and after, and Claude never rewords the user's edited words unless a later comment asks it to.
- Claude never writes into a section the user has open.
- A save onto a section that changed underneath is refused and offered as a choice. It is never a silent overwrite.

## 2. Decisions

| # | Question | Decision |
|---|----------|----------|
| A | What one edit covers | **A1**: one section, edited in place inside its own card. |
| B | Views | The dashboard's three: **Live** (default), **Source**, **Split**. `⌘/` flips Live and Source, `⌘S` saves, `Esc` is Done. |
| C | How Claude learns the words are fixed | **C1**: saved to the page at once. The next round carries an `edit` reaction with the exact before and after. The section records which words are the user's. |
| D | Claude changes a section the user is editing | **D2**: it can't. An open section is **held**, and Claude's writes to it are refused until Done. The dashboard's "Take Claude's / Keep mine" prompt remains as the safety net for a save that races a write. |

## 3. Behaviour

### 3.1 Opening and closing

- **Ways in:**
  - `e`, when a section is focused with `j`/`k` and nothing is selected, opens that section.
  - ✎ **Edit** in the selection menu, registered through `registerAction`, opens the section the selection is in. It places the cursor at the start of the selected words.
  - On a whole-section selection (the title), ✎ opens with the cursor at the start.
- **The edit bar:** it sits between the card's title and its body, as the dashboard draws it. It shows the state dot (accent, or orange when there are unsaved changes), the state text ("Editing", "Unsaved changes", "Saving…"), the Live / Source / Split switch, the key hint, and **Discard** and **Done**.
- **Done** (or `Esc`) saves when there are changes, then closes. A failed save keeps the editor open with the error in the bar.
- **Discard** asks first, inside the bar ("Discard your changes? Discard · Keep editing"), then closes without saving. No browser dialog is used.
- **One open at a time:** opening a second section saves and closes the first.
- **Leaving with unsaved changes:** the page warns through `beforeunload`.
- **When editing is unavailable:**
  - Read-only pages offer no editing.
  - While Claude is rewriting a section (it carries `is-updating`), ✎ and `e` are disabled for that section, with the reason "Claude is rewriting this section".

### 3.2 The editor

- **The editor:** CodeMirror 6, editing the section's markdown source.
  - **Live** draws markdown rendered, except the line the cursor is on.
  - **Source** shows every character, with line numbers.
  - **Split** puts Source beside annotate's own rendering of the text.
- **Behaviour carried over from the dashboard** (`app/frontend/src/lib/`):
  - `mdLivePreview.ts`: live decorations, including tables as tables.
  - `mdSource.ts`: line numbers, folding, the highlight style.
  - `mdCommands.ts`: `⌘B` bold, `⌘I` italic, `⌘E` code, `⌘K` link.
  - The keymap: `⌘S` save, `⌘/` toggle view, `Esc` done, history (undo/redo) and Tab indent.
- **Look:** Live inherits the card's font, size and width, so entering edit mode moves nothing. The card gets the same 2px accent outline the selection menu uses for a whole-section scope.
- **Saving:** byte-exact. The saved markdown is the editor's text and is never re-serialised.

### 3.3 What is saved, and what Claude learns

On save, the page:

1. Writes the section's new `markdown` to the daemon. It names the version it started from, so a changed section is refused (§4.3).
2. Records the user's words in the section as `mine`: a list of text anchors (`selected_text`, `prefix`, `suffix`) for every run of text the user inserted or changed. The runs are computed by a word-level diff between the text before and after the edit. Earlier `mine` anchors that still resolve are kept.
3. Adds one `edit` mark to the round: `{scope: "block", kind: "edit", block_id, before, after}`. The before and after are the section's full markdown. Two edits to the same section before a submit merge into one, keeping the earliest `before` and the latest `after`.

The page then paints `mine` with a quiet green rule (Highlight registry `annotate-mine`), and the card's title gets a "✎ your words" badge.

The round dock shows edits with ✎ and a count. A row reads "§N title" with the changed words shown struck out and added.

### 3.4 Held sections

- While a section is open, the page holds it. It writes the item `__holds__` as `{block_id: opened_at, …}` and removes the entry on close. It also clears the entry when the page unloads, through `navigator.sendBeacon` to a hold-release route, and a hold older than 30 minutes with no heartbeat is ignored.
- The `claude-annotate` commands Claude uses to write sections refuse to write a held section. The refusal names the hold and tells Claude to fold that part of its work into the next round. Claude's other sections are written normally.
- Claude learns about holds from that refusal, and from `__holds__` when it reads the session.

## 4. Architecture

### 4.1 Components

| Unit | Where | Does |
|------|-------|------|
| `editor/` source | `skills/annotate/editor/src/` | Copies of the dashboard's `mdLivePreview.ts`, `mdSource.ts` and `mdCommands.ts`, adapted. The ticket-key and task-body imports are replaced with annotate-neutral stubs. An `index.ts` exposes `window.AnnotateEditor.mount(host, {doc, mode, onSave, onDone, onChange})` returning `{getText, setMode, focusAt(offset), destroy}`. |
| `editor` build | `skills/annotate/editor/package.json` + `build.mjs` | esbuild bundles the source with pinned CodeMirror versions (the same ones the dashboard uses) into one IIFE file. |
| `static/vendor/editor.min.js` | committed build output | Loaded lazily by `edit.js` the first time an editor opens. It is not in `entry.js`'s eager list, so pages that never edit don't pay for it. |
| `edit.js` | `skills/annotate/static/` | Opening, closing and the edit bar. It registers ✎ with the selection menu and binds `e`. It also handles the save path, `mine` computation, holds, the conflict prompt and painting `mine`. |
| `subunits.js` | existing | Gains `edit` marks in the round (merge rule above), the ✎ dock rows, and the wire field mapping (`before`, `after`). |
| daemon | webcompanion | `PUT /s/{sid}/items/<anchor>` accepts `If-Match: <version>` and returns `412` with the current version when it differs. A new owner route releases one hold by beacon. |
| `claude-annotate` writers | `skills/annotate/*.py` (the push and update paths) | Refuse to write a block listed in `__holds__`, with a message Claude acts on. |
| `references/handling-events.md` | docs | The `edit` reaction and the `mine` rule (§4.2). |

### 4.2 What Claude reads

New round reaction:

```json
{ "scope": "block", "kind": "edit", "block_id": "section-1",
  "before": "<the section's markdown before the user's edit>",
  "after": "<the section's markdown now — already saved on the page>" }
```

New rules in `handling-events.md`:

- **An `edit` reaction is already applied.** Update the working `blocks.json` to `after` verbatim, and do not write the block back just because of the edit. The user's text is the section's text now.
- **The user's words are final.** A block's `mine` anchors name text the user wrote. When any later reaction makes you rewrite that block (a comment, a compact of a neighbour), keep every `mine` passage character for character, and keep its anchors valid. Never compact, merge or reword user-written text unless a reaction on those exact words asks you to.
- **Read the edit as information.** If the edit contradicts another section, say so in the next round's reply, or fix the other section. Never revert the user's text.
- **A held section is not yours to write.** If a write is refused because the section is held, finish everything else, and say in your reply what you will do to that section once it is released.

### 4.3 The save path

1. `edit.js` holds the version the editor opened at, which is the section's `data-version`.
2. On save it sends `PUT /s/{sid}/items/<block_id>` with `If-Match: <version>` and the block body with the new `markdown` and the updated `mine`.
3. On `200`, the version the page gets back becomes the new base, the section re-renders, and the `edit` mark goes into the round.
4. On `412`, the bar becomes the conflict prompt: "This section changed while you were editing. Nothing has been overwritten." The choices are **Show what changed** (a word diff of theirs against yours), **Take theirs** and **Keep mine**. Keep mine re-sends with the new version.

## 5. Errors and limits

| Situation | What the user sees |
|-----------|--------------------|
| The editor bundle fails to load | ✎ and `e` show "The editor could not load", with the HTTP status. The page keeps working without editing. |
| A save fails (network, 5xx) | The bar says "Not saved — <reason>" with Retry. The text stays in the editor. |
| `412` on save | The conflict prompt from §4.3. |
| The section was deleted while open | The bar says "This section was removed. Copy your text before closing", with a Copy button. |
| The section is over the daemon's 2 MB item limit | The bar shows the daemon's `400` message. The text stays. |
| A non-owner viewer | No editing at all, as with every other control. |

## 6. Testing

- **The editor bundle** is tested in a bare page (as `test_browser_anchors.py` is): mount, type, toggle Live and Source, check the text round-trips byte for byte (a table, a fence, hard-wrapped lines), check the key bindings, destroy.
- **The `mine` diff** is tested as a pure function: inserted, replaced and deleted words; repeated words; a whole-section rewrite; and edits at the very start and end.
- **Browser tests (daemon-backed):**
  - `e` and ✎ open the editor in place, with no layout shift (the card's top and width are measured before and after).
  - Done saves, and the section's markdown in the daemon is byte-identical to what was typed.
  - An `edit` reaction lands in the round with the right before and after.
  - Two edits merge into one.
  - `mine` paints after a reload.
  - A held section refuses a CLI write.
  - A `412` shows the conflict prompt. Take theirs and Keep mine each do what they say.
  - Discard asks first.
- **Daemon:** `If-Match` gives `412` on a mismatch and `200` on a match. A PUT without `If-Match` is unchanged, so existing clients keep working.
- **Contract:** `handling-events.md` carries the `edit` and `mine` rules (source-string tests, as for the round).

## 7. Out of scope

- Editing the whole page as one document (A2).
- Editing a code pane, a diagram's source, or a choice block's options.
- Collaborative editing by two people at once.
- Keeping the copied editor files in sync with the dashboard automatically. They are copied once; a later improvement in the dashboard is ported by hand.
