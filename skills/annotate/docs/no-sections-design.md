# The annotate page reads as one document and never shows sections

Design, settled with the maintainer on 2026-10-10 from rendered options on two
real pages ("Delivery listener", "Stress-test selection"). Each decision below
names the option picked; the reasoning sits under it.

## What stays the same

Claude still pushes blocks with ids (`section-1`, `section-2`, …). A block is
still the unit a comment points at, a rewrite replaces, the editor opens and
the version counts. Only the reader stops seeing it. The push format does not
change, and no Python reads `block_id` from events, so the daemon and
`pull.py` / `push.py` / `blocks.py` stay as they are. One addition to the
round contract is needed, for a comment that covers two blocks (decision 6).

## The decisions

| # | Question | Picked |
|---|---|---|
| 1 | How the page looks | One document: no card, no chevron, no section pill. An authored title is an `h2`. |
| 2 | Where a comment opens | Beside the text, level with the first selected line |
| 3 | How a rewrite is marked | The change bar stays. The "you asked" / "sweep" chip and "what changed" sit on the heading. |
| 4 | While Claude rewrites | Today's tint and "updating" pill, over the block being rewritten |
| 5 | Diagrams, mockups, questions, code | A light frame with the title and the maximise button on it |
| 6 | The comment box | A floating window: title bar to drag, corner to resize. Used for every comment. A selection may cross a heading. |
| 7 | Long answers | A visible fold button before each heading, and a Fold all button |
| 8 | Claude's side | Blocks keep their ids. The title is optional and becomes a heading. |

### 1. One document

- `createBlockSection` (`static/script-blocks.js` 273) builds
  `section.block` without the `card` class, `.card-head`, `.card-chevron` or
  `.section-pill`. The body wrapper is renamed `.block-body` (today
  `.card-body`), so no `card-*` name survives.
- A block with an authored `title` starts with
  `h2.block-heading#block-heading-<id>`. A block without one has no heading:
  it reads as the next paragraph of the block above.
- `block-title.js` no longer invents a visible title. Its derived title
  ("Section", "Diagram", "Decision", the first line) is still used where a
  label is needed and nothing is shown: `aria-label`, the round dock, the
  maximised view's bar.
- `renderVersionBadge` goes. The version stays in `data-version` for the
  change machinery.
- The page background under the text becomes `--surface`, as in the mockup.

### 2 and 6. The comment window

One module, `static/comment-window.js`, replaces both comment boxes:

- the small composer that opens on a selection (`selection.js`
  `openComposer`, `hostFor`, `closeComposer`, `rescueDraft`), and
- the comment card inserted after a section (`script-cards.js` `buildCard`,
  `renderComments`, `revealOpenDraft`, and `script.js` `openAnnotation`).

The window:

- has a title bar reading "Comment" with a grip and ×, the quote, the text box,
  the image paste strip and mic from today's card, and Cancel / Add to round;
- is moved by its title bar and resized from its corner (pointer events,
  minimum 300 × 200);
- opens right of the text, level with the first selected line, and never over
  the selected words; on a window too narrow for that it opens below the
  selection;
- remembers its last size per page (`localStorage`, wrapped in try/catch);
- is one at a time. Opening a second comment while one is open shows the open
  one, as `revealOpenDraft` does today.

Every way into a comment opens it: a selection, the menu on a heading, the
key `c`, and a click on a mockup's step. A saved comment keeps its chip
(`.sel-chip`) after the paragraph; clicking the chip reopens the window.

### 6. A selection that crosses a heading

Today the menu refuses it ("Select within one section", `selection.js` 182).
After this change:

- `anchorFor` returns one anchor per block the range touches, each with its
  own `block_id`, `selected_text`, `prefix` and `suffix`.
- The mark stores them as `spans: [anchor, …]`. A one-block comment keeps
  today's flat shape.
- The round reaction carries `block_id` (the first block) and, when the
  comment covers more than one block, `spans`. Readers of the old shape are
  unaffected.
- `references/handling-events.md` adds one rule: a reaction with `spans`
  belongs to every block it names. Group it under each, and rewrite each.
- `pruneMarks`, `paintSpans`, `overlapping` and `spanMarkAt` work per span.
- The reading highlighter's own cross-block refusal (`highlighter.js` 151)
  stays.

### 3. Changes after a round

- The bar keeps its place and buttons. Its text reads "1 part changed — 1 you
  asked for" (`script-changes.js` 88).
- `markChangedCard` puts the chip and "what changed" at the end of the
  block's heading. A block without a heading gets them on a small line at the
  top of the block.
- Tooltips and the diff pane drop the word "section".

### 4. While Claude rewrites

`startUpdatingOverlay` (`script-cards.js` 29) has no caller today, so nothing
shows while a round is being answered. Submitting a round starts it on every
block the round names, `spans` included. Clearing on ack must clear all of
them: `script-poll.js` 26 clears only `pend.blockId`, while a round registers
`blockIds`. Blocks the sweep rewrites are not known in advance and get no
overlay. The overlay CSS loses `border-radius: inherit`, which assumed a card.

### 5. Frames

- `sequence`, `flowchart`, `mockup`, `choice` and `explain` sit in
  `.block-frame`: a border, `--diagram-ground`, and a head with the title.
- `maximize.js` mounts its button in the frame head (today `.card-head`).
  `MAXIMIZABLE` stays `sequence`, `flowchart`, `mockup`.
- A choice's `aria-labelledby` points at the frame title.

### 7. Folding

- Each heading gets a visible fold button before it. Folding hides the
  block's content and every following untitled block, up to the next heading.
- The fold state keeps today's key, `annotate.collapsed:<responseId>:<blockId>`,
  for the heading's block.
- A Fold all / Unfold all button sits in the page header. The key `f` and the
  ⌘K ⌘0 / ⌘K ⌘J chords call the same function as the buttons.

### 8. Words

- The search box reads "Search…" (`shell.js` 20), and its count reads "N of M
  match" (`search.js` 158).
- `references/pushing.md` stops calling the title a card header. It says a
  title becomes a heading, so give one where a reader needs a heading and
  leave it out where the text simply continues.

## Order of work

Each step leaves the suite green and the page usable.

1. **Document rendering.** Change `createBlockSection`, the CSS and
   `block-title.js`, then every selector that reads the card. These are
   `anchors.js` `SKIP`, `selection.js` `inTitle` / `excluded` / `homeFocus`,
   `maximize.js`, `edit.js`, `export.js`, `script-changes.js`,
   `script-reconcile.js`, `subunits.js` `blockTitleFor`, `script.js`
   `renderChoice`, and the CSS rows in the card table below.
2. **Frames** (decision 5). This needs step 1.
3. **Folding** (decision 7). This needs step 1.
4. **Changes and overlay** (decisions 3 and 4). This needs step 1.
5. **Comment window** (decisions 2 and 6). This needs step 1. It also changes
   the users of the old boxes: `choice-queue.js`, `search.js`,
   `script-reconcile.js`, `edit.js`, `export.js` and `voice.js`, plus the
   dock lock in `subunits.js`.
6. **Cross-heading selection** (decision 6). This needs step 5. It changes
   anchors, marks and the round, then `handling-events.md` and
   `pushing.md`.
7. **Words and docs.** Update the search, `pushing.md`, `docs/gallery.html`
   and the skill's README.

Every step is checked in a live browser on a real workspace, with the
`getComputedStyle` / `getBoundingClientRect` numbers quoted.

## Tests that change

These pin today's card and are rewritten to pin the new page:

- `block_title.test.cjs` asserts the "Section" fallback (line 84). It moves
  to the label-only use.
- `test_smoke_code_panes.py` checks the `.card-body` rules and
  `TestCollapseGuard`.
- `test_smoke_fold_shortcuts.py` requires `.card-chevron` in `foldAll`.
- `test_smoke_comment_open.py`, `test_smoke_empty_draft.py`,
  `test_smoke_dismiss_lock.py` and
  `test_smoke_review_ergonomics.py::test_comment_goes_through_the_same_door_as_the_button`
  pin the old comment boxes.
- `test_smoke_export.py`, `test_smoke_compact.py` and `test_smoke_read_only.py`
  list `.sel-composer` and `.inline-comments`.
- `test_smoke_change_bar.py::test_a_change_bar_is_rendered` asserts the
  literal "sections changed".
- `test_smoke_maximize.py` cites `.card-head`, and its promotion test reads
  `section.block.card`.
- `test_smoke_card_structure.py` pins `.card-close`.
- `test_round_contract.py` gains a test for the `spans` rule.

New tests cover four things:

- **The comment window:** one at a time, its placement rule, and the size it
  remembers.
- **Folding:** a heading folds its untitled followers.
- **The overlay:** it starts on submit and clears on ack for every named block.
- **Spans:** a cross-heading anchor round-trips through `anchorFor`,
  `locate` and the round.

## Out of scope

- The keyboard review cursor (`j`/`k`, `data-kb-focus`) still steps block by
  block and marks the block it is on.
- The in-place editor still opens one block. While it is open, that block's
  edges show.
- Confluence publishing (`confluence/body.py` `_title_of`) already turns
  titles into headings. It is not changed.
- The reading highlighter keeps its one-block rule.
- The stage and talk skills, which have their own cards.

## Selectors that read the card today

From the code map, at `e6f3afe`. Step 1 removes every row.

| Selector | JS | CSS |
|---|---|---|
| `.card-head` | anchors.js 21; selection.js 62, 74, 280; maximize.js 266; script-changes.js 136; script-blocks.js 428; export.js 72 | style.css 495–517, 633–634, 654 |
| `.card-title` | selection.js 163; maximize.js 172; subunits.js 397; script.js 484, 512 | style.css 261–294, 346, 502, 516; style-selection.css 91 |
| `.card-chevron` | script-cards.js 295; selection.js 346; edit.js 1345; maximize.js 130; script-chrome.js 433, 482; export.js 33 | style.css 635–654 |
| `.section-pill` | script-blocks.js 419–433; script-changes.js 159; maximize.js 285; subunits.js 396; export.js 35 | style.css 660–690 |
| `.card-body` | edit.js 763, 956; script-changes.js 314; script-reconcile.js 321 | style.css 257–630; style-code.css 9–12; style-edit.css 63 |
| `section.block.card` | — | style.css 486–531; style-maximize.css 80–98; style-edit.css 57; style-selection.css 30–33 |
