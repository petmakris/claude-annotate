# Before and after sequences, side by side

Date: 2026-11-10. Replaces the merged view of 6ad2c14 and 2463576.

## Why

A sequence board on the talk stage can compare a flow before and after a change (`compare: {before, after}`).
Today it draws both flows as one lane diagram. Removed rows are struck out and red, and changed rows are amber.
That reads as one long list of coloured rows. The reader cannot see the two flows as flows and compare their shape.

The reader wants what a split code diff gives: two whole diagrams side by side, the before on the left and the
after on the right. A step that is in both flows sits on the same row on both sides. Where one side has a step
the other lacks, the other side shows a gap at that height, so the two diagrams stay in line row by row.

The test case is an internal PR, the proposal report's backtesting request. Before, the report
service calls a Service client in PMP's module, which builds the requests with fixed lists and returns ready-made
report timeseries. After, a new shared backtesting module (owned by PMP and PSIM) sits in the middle. The report
service passes quarterly and its own measure lists down, gets raw values back, and builds the timeseries itself.
The Service requests are the same on both sides.

## Goals

- Two lane diagrams, each one a complete flow with its own actors, numbering, lifelines and activation bars.
- Rows aligned across the two sides, with a gap where a side has no step.
- The difference readable at a glance, and the words that changed easy to see.
- The voice can say a row, which lights it on both sides, and can point at one side.

## Non-goals

- No change to a single sequence (a spec without `compare`). Its drawing, its scene and its tests stay as they are.
- No change to the `compare` input an answer writes. Existing answers and the demo's input still work.
- `phases`, `groups`, `outcome` and `captions` stay unsupported with `compare`, as today.
- The annotate page, `sequence_svg` and `tools/vz.py` do not draw `compare`, as today.

## Anti-goals

- A merged single diagram with struck-out rows. The merged view, its Both toggle and its strike-through are removed.
- Rows that drift apart. A row must have the same height on both sides, so the eye can run straight across.

## What the reader sees (decided with mockups)

The mockups are `side-by-side-mockups.html`, shared at https://files.example.com/side-by-side-mockups.html.
The user picked these:

1. **A changed step is one shared row**, and the words that differ are bold inside each label: red on the
   before side, green on the after side. (Mockup question 1, option B.)
2. **A gap is a hatched band** across the side's width, behind its lifelines. (Question 2, option B.)
3. **An actor that is not on both sides is toned and tagged**: red with a "removed" tag on the left, green with
   a "new" tag on the right. This overrides the actor's own tone. (Question 4, option B.)

These are my calls:

4. **Diff marks in a narrow gutter between the two diagrams**, one per row: `=` same (faint), `~` changed
   (amber), `+` new (green), `−` removed (red), `↕` moved (amber). (Question 3, option B.) The user's question 3
   answer was not explicit.
5. **Each side numbers its own steps** 1, 2, 3. A gap takes no number. So a side reads as a whole flow.
6. **The row being said lights on both sides** with the usual accent band. Hovering a row lights its partner.
7. **Each side has its label over it** ("Before · master", "After · with the PR"), taken from the sides' `label`.

## How the sides are matched

Matching stays as `compare.py` does it today. Steps match by id first. A before step with no id match matches an
after step with the same `label` and `arrow` but other actors.

| Kind | Rule | Rows |
|---|---|---|
| same | both sides, the same words; ends equal or only replaced | one row, a step on each side |
| changed | same id, same `from` and `to`, other words | one row, a step on each side |
| added | after only | one row, a gap on the left |
| removed | before only | one row, a gap on the right |
| moved | in both, between other actors | two rows (see below) |

**A step whose actors differ only because an actor was replaced keeps one row.** This is my call, and it
is needed for the example. With the same words it is **same** (the Service requests, which the user called identical);
with other words it is **changed**. In that PR, "Report service asks for backtest data" goes to the Service client before and to
the shared module after. These are different actor ids, so by today's rule it is moved. It should be one shared
row. The rule: two steps with the same id share one row when each of their ends is the same actor id or the
end's actor exists on one side only. They are **moved** when an end is an actor that exists on both sides
but at another end.

**Steps matched by words** (other ids, same `label` and `arrow`) follow the same actor rule (my call): when
their ends differ only by replaced actors they are one changed row with no word marks, else moved.

**A step whose position changed is moved too** (my call). The rows of matched steps (same and changed) are the
longest run of matched pairs that keeps both sides' order (a longest common subsequence over the pairs). A pair
outside that run is moved: two rows, each facing a gap.

**A moved step is two rows**, each facing a gap. The before row stands where the before flow has it and the after
row stands where the after flow has it. Both carry the `↕` mark, and saying the step lights both rows (as
`replaces` does today).

**The row order** comes from the two flows, like a line diff. The rows of the common run are the anchors.
Between two anchors come the before-only rows (removed, and the before rows of moved steps), then the after-only
rows. A side's own order never changes.

**Word marks.** For a changed row, `compare.py` splits the two labels into words and marks the words that differ
(Python's `difflib` on word tokens). Words removed are marked on the before label and words added on the after
label. The same goes for `sub`. The page only draws the marks.

## What compare.py hands the page

The flat spec keeps one entry per row in `steps`, so the scene engine, `[[point: step X]]` and the step names keep
working on rows:

- A row's `id` is the after step's id, or the before step's id when the row has no after step. The before row of
  a moved step keeps `was~<id>`.
- A row carries `change` (same, changed, added, removed, moved), `before` (the before step, or absent for a gap)
  and `after` (the after step, or absent for a gap). Each side's step carries its own word marks, for example
  `label_marks: [["fetch(proposal", false], [", QUARTERLY, measures", true], [")", false]]`.
- The row's own `from`, `to`, `label` and `arrow` are the after step's when it has one, else the before step's.
  This keeps the scene engine and the names working without change.
- `compare` holds `before: {label, actors}` and `after: {label, actors}`, each side's actors in its own order
  and each tagged `same`, `added` or `removed`.
- The flat `actors` stays the union of both sides, so `actor:<id>` keys still exist. An actor on both sides is one
  key, lit on both.
- Each side's step keeps its own id and its own `reply_to` as written, and carries `row`, the key of its row. The
  page keys a side's step element `step:<row>`, so lighting a row lights both sides (my call).
- A moved step's after row keeps `replaces` (the before row's key), so the scene brings the two in together.
  The `was` text is gone: the popup shows each side's own step.
- The `bi` field is gone.

The scene model (`scene.sequence_model`) for compare is updated to match. A changed row is now one key. The old
words still name it (keep the alias). A moved step's before row still comes in with its after row.

## How the page draws it (lanes.js)

A compare board is two lane panes in one board, with the gutter between them. Each pane is drawn by the existing
lanes code from a per-side spec: that side's actors and that side's steps, with a gap step in place of a missing
one. One change is needed so the rows stay in line: **each row's height is the larger of its two sides'**.

- A gap row draws the hatched band and no number. It cannot be clicked.
- Each pane has its own sticky actor head. The two heads have the same height.
- A click on a step opens that side's popup, with that side's own `ref` lines. Play from here plays the row.
- Activation bars come from `reply_to` inside each side. A reply whose request is a gap on that side draws as a
  plain reply with no bar.
- The panes may be drawn and then measured once more so each row pair gets the same height (my call). Equal row
  tops can only be checked in the browser; the node tests check the row counts and the gap rows.

**Narrow boards.** Below the width where two panes fit (about 900 px of board, my call; the builder measures
it), the board shows one pane at a time with a Before / After toggle in its head. The gaps and the gutter marks
stay, so the reader still sees where steps are missing. On a wide board the toggle is not shown.

**The voice.** `[[point: before]]` and `[[point: after]]` light that side and dim the other one (on a narrow
board they switch the pane). `[[point: both]]` lifts the dimming. `[[point: merged]]` is still accepted and
means both, so saved answers keep working. The scene keys are `mode:both`, `mode:before` and `mode:after`, and the
page reads a saved frame's `mode:merged` as `mode:both`. The pointing lasts until a later frame points elsewhere, and the board
goes back to both when the answer ends, as today.

**Boards saved in the old shape.** A view saved before this change holds the merged flat spec (rows tagged with
`bi`, struck-out rows). The page tells the two apart by `compare.before`: an object is the new shape, text is the old one. It draws an old
one as a plain single sequence of its rows. The feature is one day old, so
nothing more is needed (my call).

## Docs and demo

- `skills/talk/SKILL.md` "Before and after": rewrite for the side-by-side board. Keep the input format, explain
  the matching rules above, the gap, the marks and `[[point: before|after|both]]`.
- `skills/annotate/references/block-kinds/sequence.md`: the short `compare` paragraph says side by side.
- `skills/talk/demo.md`: the example answer becomes the the example flow, written from the description above.
- The project `CLAUDE.md`: one paragraph on the compare board (where matching lives, rows of equal height,
  gaps), so later sessions do not rebuild a merged view.

## Tests

Each new behaviour gets a guard test, shown failing without the change and passing with it:

- `test_compare.py`: the row list for the the example spec (exact rows, their order, their `change`, gaps), the
  replaced-actor rule (changed, not moved), word marks on a changed label, a moved step as two rows, each side's
  order kept.
- `test_stage_page.py` (node, no layout): a compare board draws two panes with the same number of rows, a gap
  row where a side has no step, the gutter marks, the tags on removed and new actors, and `mode:before` dimming
  the after pane.
- `skills/talk/tests/test_call.py`: `[[point: both]]` and `[[point: merged]]` resolve; a row said lights one key.
- A single sequence's tests stay unchanged and pass.

The full suite runs once at the end. The result is checked in Playwright headless on a real talk board with the
the example spec: both panes, rows in line (equal `getBoundingClientRect().top` for each row pair), and a narrow
viewport.

## Left to the builder

- The exact DOM and CSS of the two panes and the gutter, in the lanes look.
- The exact narrow-board width.
