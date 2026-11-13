# Rich choice options and choice queues

Date: 2026-09-29. Status: design approved in conversation, spec awaiting review.

## Why

A choice block's options are a one-line `label` and a one-line `description`. When the
options are themselves content, such as two versions of a Java file, the content has to
live in a separate block above the question. The reader reads one card and answers in
another, and on a page with 60 such questions that becomes 120 cards.

The ABC-270 annotation review was exactly this case: 60 model files, each asking "original
PR or Confluence only?", each needing both versions of the file on screen to answer.

## Decisions

Chosen by the user from rendered mockups (`choice-mockups.html`, `choice-design.html`):

| Decision | Chosen | Rejected |
|---|---|---|
| Where rich content sits | **1A**: each option card carries its own content, stacked | side-by-side columns, tabs, a question bar on any block |
| How fine-grained an answer is | **2A**: one pick per question | line-level picks, per-row keep/drop |
| Many similar questions | **3B**: a queue, one question at a time | one card per question, a decision table |
| How a queue is authored | **choice blocks sharing a `group`** | a new `queue` block kind, a page-wide toggle |

The user's rule for granularity: when a smaller subject needs its own decision, it gets its
own block with its own question. Questions never nest.

## Non-goals

- Nested questions, and picks on individual lines or rows inside an option.
- Side-by-side or tabbed option layouts.
- Any change to the event payload or the round.
- A new block kind.

## Authoring contract

Two optional fields, both additive. A block without them renders exactly as it does today.

```json
{"id": "section-4", "kind": "choice", "spec": {
  "question": "What should Asset.java carry?",
  "group": "Annotation decisions",
  "options": [
    {"id": "o1", "label": "Original PR", "markdown": "```java\n...\n```"},
    {"id": "o2", "label": "Confluence only", "markdown": "```java\n...\n```"},
    {"id": "o3", "label": "Mix", "description": "Name the fields in the note"}
  ]}}
```

**`options[].markdown`** (string, optional). Rendered under the option's label by the same
pipeline as a `markdown` block: markdown-it with `html: true`, the same sanitizer, and Shiki
for fenced code. `label` stays required as the option's heading. `description` still
renders beside the label, so an option may carry both.

**`spec.group`** (string, optional, 1 to 80 characters). Consecutive choice blocks whose
`group` strings are equal form one queue. A run needs at least two blocks; a lone grouped choice renders as an ordinary choice. The string is also the queue card's title, so it
is written as a heading ("Annotation decisions"), not a slug.

"Consecutive" means adjacent in document order with no other block between them. Two runs
of the same `group` separated by another block are two queues. The kind reference tells
Claude to keep a group's blocks together.

Validation, in `blocks.py` at push time, rejects the push with a message naming the block:

- `group` present but not a string, empty, or over 80 characters.
- `markdown` present on an option but not a string.

Every other rule of the choice block is unchanged: 2 to 4 options, stable option ids, at
most one `recommended`.

## Rendering: rich options (1A)

`renderChoice` in `static/script.js` gains one step per option. When `opt.markdown` is set,
it renders the markdown with `blockMd` into a `.choice-option-body` under the option's head
row, then runs the highlighter over it, the same call a markdown block makes.

The option card stays one click target, with two exceptions so the content stays usable:

- A click that ends a text selection inside the body does not toggle the option. The reader
  must be able to select and copy code.
- A click on a link inside the body follows the link and does not toggle.

The existing radio or checkbox roles, arrow keys, digit shortcuts and note field are
unchanged. The card's `aria-describedby` points at the body, so a screen reader announces
the content with the option.

Styles go in `style.css` beside the existing `.choice-option` rules. The body spans the full
card width under the head row, and code inside it uses the page's normal code card.

## Rendering: queues (3B)

A new module, `static/choice-queue.js`, runs after every render of the page. It finds each
run of consecutive choice blocks sharing a `group` and turns the run into one queue:

- **The bar.** A queue bar is inserted just above the run's first section. It is minimal:
  a progress ring, the `group` as its title, "File 12 of 60 · 18 decided", then Prev,
  "Next undecided" and Next, and a "Show all" switch. Prev is disabled on the first
  question and Next on the last. There is no per-question map: a row of one dot per
  question was tried and rejected as unreadable at sixty questions. Jumping to a particular
  question goes through Show all or search.
- **One member at a time.** Only the current member's section is shown. The others get the
  class `cq-hidden` and stay in the DOM. Each member is an ordinary choice section rendered
  by the unchanged `renderChoice`, so its card header carries the question, and its comment,
  highlight and rewrite paths are the ones every block already has. A comment on question 37
  arrives anchored to question 37's block without any rerouting.
- **Picking.** Picking an option records the answer exactly as today, as a round mark keyed
  by that member's block id. The queue then moves to the next undecided member. Typing a
  note, or clearing a pick, does not move.
- **Decided.** A member is decided when it has a choice mark in the current round. A note
  with no pick counts, because that is the existing "none of these, here's my direction"
  answer. A choice Claude has resolved is rewritten into a markdown block, so it leaves the
  queue on its own.
- **Keys.** The page's existing <kbd>J</kbd>/<kbd>K</kbd> walker is queue-aware. When the
  focused block is the current member of a collapsed queue, <kbd>J</kbd> moves to the next
  question and <kbd>K</kbd> to the previous one. Past the last question, <kbd>J</kbd> carries
  on to the block after the queue, and before the first, <kbd>K</kbd> to the block before it.
  The digit shortcuts that pick an option are the existing ones in `renderChoice`.
- **Show all.** The switch expands the run back into ordinary choice cards, one per member,
  and switching it off collapses them again.
- **Remembered per viewer.** The current position and the switch state are stored in
  `localStorage` under the page's response id and the group. Every read and write is wrapped
  in try/catch, and the queue starts at the first undecided member when nothing is stored.
- **Rewrites.** When Claude rewrites a member, the queue is recomputed after the render. If
  a rewrite removes a member's `group` or changes it, the block leaves the queue.
- **Search.** While a search query is active, every queue shows all its members, so search
  filters them exactly like any other block. Clearing the search collapses them again.

## What does not change

- The event payload. Each pick still travels as a `kind: "choice"` reaction with the
  member's own `block_id` and `selected_options`. The watcher side, `handling-events.md`
  and `validate_choice_selection` need no change.
- The round. Picks accumulate, and one Submit sends them all.
- Choice blocks with no `group` and no option `markdown`.

## Other surfaces

- **Export** (`static/export.js`). The queue bar is stripped from the export and every
  member is un-hidden, so members export as ordinary choice cards, one per question, with
  each option's markdown rendered under its label. A queue is a way of viewing the page, not
  part of the document.
- **Confluence publish** (`confluence/body.py`). The open-question panel lists each option's
  label and then its markdown, converted with the existing `to_html`. `group` is ignored.
- **Docs.** `references/block-kinds/choice.md` gains two sections: "Options that carry
  content", covering when to put markdown in an option, and "Many similar questions: groups",
  covering the adjacency rule and writing `group` as a title. The block-kind menu row in
  `SKILL.md` mentions both in one clause. `docs/gallery.html` gets one rich choice and one
  three-question queue.

## Testing

Unit tests, in `tests/test_blocks.py`:

- A `group` that is not a string, is empty, or is over 80 characters is rejected, and the
  error names the block.
- An option `markdown` that is not a string is rejected.
- A spec with neither field validates exactly as before.

Unit test, in `tests/test_confluence_body.py`: an option's markdown appears in the published
panel under its label.

Browser tests, Playwright, beside `tests/test_browser_review.py`:

- A rich option renders its fenced Java as highlighted code inside the option card.
- Selecting text inside an option's code does not toggle the option. A plain click does.
- Three adjacent blocks sharing a `group` render as one queue card showing "1 / 3", and a
  fourth, ungrouped choice block renders as an ordinary card.
- Picking in the queue records a round mark on that member's block id and moves to the next
  undecided member. Typing a note does not move.
- <kbd>J</kbd> and <kbd>K</kbd> step through the queue's questions, and <kbd>J</kbd> on the
  last question moves on to the block after the queue.
- A search query that matches one member shows that member, and clearing the search
  collapses the queue again.
- An export of a page with a queue contains every member and no queue bar.
- Submitting the round sends one `choice` reaction per answered member, each with its own
  `block_id`.
- "Show all" expands the run into three cards and collapses it back. The state survives a
  reload.
- A comment made from the queue arrives anchored to the current member's block id.
- Two runs of the same `group` split by a markdown block render as two queues.

Acceptance, done once in a browser after merge: rebuild the ABC-270 decision page as one
60-question queue with rich options, and check it by eye and by the round payload.
