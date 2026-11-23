# Choice block v2 — selectable cards + note

**Date:** 2026-08-11
**Status:** Approved design, pending implementation plan

## Problem

The annotate choice block renders a plain radio/checkbox list with a Submit
button. Two gaps:

1. **No free text.** The user can only pick — there is no way to add the
   minimum caveat ("Koumbaras, but lowercase") or to say "none of these" with
   a direction. The submit payload already carries a `text` field, but the
   client hardcodes it to `""`.
2. **Inelegant presentation.** Tiny radio circles on large rows, and
   "(recommended)" smuggled into option description prose instead of being a
   first-class rendered badge.

## Decisions (from brainstorming)

- Free text is a **pick + optional note**, one note per answer (not
  per-option, no separate "Other" write-in mechanism).
- **Note-only submission is allowed**: no pick + non-empty note means "none
  of these — here's my direction", and Claude re-proposes instead of
  resolving the block.
- Interaction is **selectable cards + footer**: whole option row is the
  click target; one shared note field and Submit below the cards.

## Design

### 1. Interaction (client — `renderChoice` in `skills/annotate/static/script.js`)

- Each option renders as a full clickable card (label + description). No
  radio/checkbox input is shown. A selected card gets a highlighted state;
  clicking a selected card deselects it.
- `multiSelect: false` allows at most one highlighted card (clicking a second
  card moves the selection). `multiSelect: true` allows several.
- Keyboard, active while focus is inside the choice block: `1`–`4` toggle the
  corresponding option, arrow keys move focus between cards, Space/Enter on a
  focused card toggles it, Enter in the note field submits. Cards carry
  proper ARIA roles (`radiogroup`/`radio` or `checkbox`) so the state is
  announced.
- Footer below the cards: one auto-growing textarea, initially one line,
  placeholder *"Add a note (optional) — or answer in your own words"*, then
  the Submit button.
- After submit, the same "updating" overlay and pending-event flow as today
  (`startUpdatingOverlay`, `pendingEvents`). The note field joins the
  `body.is-busy` disabled set alongside the submit button.

### 2. Submit contract

- Submit is enabled when **at least one option is selected OR the note is
  non-empty** (whitespace-only counts as empty).
- Payload shape is unchanged: `type: "choice"`, `selected_options` (list,
  now possibly empty), `text` (the note, `""` when blank). No new fields.
- Old browser tabs that send a pick with `text: ""` remain valid — no
  compatibility break.

### 3. Validation (`skills/annotate/blocks.py`, `skills/annotate/server.py`)

- `validate_choice_selection(spec, selected)` gains a notion of the note:
  an **empty selection is valid only when the submission carries non-empty
  text**; empty pick + empty text is rejected (server answers 422). Unknown
  option ids and the single-select cardinality rule ("exactly one when a
  selection is present") are unchanged.
- Concretely the function grows a `has_text: bool` keyword parameter
  (default `False`, so existing callers keep today's behaviour); the server
  passes `has_text=bool(text.strip())`.
- The stored event keeps today's shape plus the already-passed-through
  `text`; `selected_options` may be `[]`.

### 4. Spec addition — `recommended` flag

- An option may carry `"recommended": true`. The client renders it as a
  small "recommended" badge on the card; it has no effect on validation.
- Authoring guidance changes: stop writing "(recommended)" inside
  `description` prose; set the flag instead. At most one recommended option
  per block.

Example spec:

    {"id": "section-N", "kind": "choice", "spec": {
      "question": "<the decision, one line>",
      "multiSelect": false,
      "options": [
        {"id": "o1", "label": "...", "description": "...", "recommended": true},
        {"id": "o2", "label": "...", "description": "..."}
      ]
    }}

### 5. Event handling semantics (Claude side)

- **Pick (with or without note):** resolve the block into a decision
  paragraph as today (`convert_block_to_markdown`); the decision prose folds
  the note in (e.g. *"Decision: Koumbaras, lowercased per your note…"*).
- **Note-only (empty `selected_options`, non-empty `text`):** do NOT
  resolve. Treat it as a rejection-with-direction: rewrite the choice block
  with re-proposed options (a spec update bumps the version), or resolve to
  prose if the note itself settles the question.

### 6. Docs

- `references/block-kinds/choice.md`: new spec field (`recommended`), the
  submit contract (note + note-only), updated authoring guidance.
- `references/handling-events.md` § choice: `text` may carry a note; the
  note-only case and its re-propose semantics.

### 7. Styling (`skills/annotate/static/style.css`)

- Card selected state, hover, focus ring, recommended badge, note-field
  styling — consistent with the existing card/round visual language. The
  existing `.choice-*` classes are reworked rather than added-to where that
  is cleaner.

### 8. Tests

- `test_blocks.py`: empty selection + text → valid; empty + no text →
  invalid; existing cases unchanged.
- `test_server.py`: POST choice with `selected_options: []` + text → 202 and
  event records both; empty both → 422; pick + text → 202.
- `test_smoke_e2e_choice.py`: updated for the card UI (click card, type
  note, submit) and a note-only submission path.

## Out of scope (YAGNI)

- Ranking / ordering of options.
- Per-option notes.
- A dedicated "Other…" write-in option (note-only submission covers it).
- Changes to walkthrough / interactive_review skills.
