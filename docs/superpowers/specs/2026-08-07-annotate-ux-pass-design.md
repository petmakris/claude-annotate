# The annotate UX pass — seeing the round, the work, and the change

Date: 2026-08-07
Status: approved from mockups, ready for implementation planning

## Problem

The compact control and the coherence sweep shipped earlier today. Two
independent reviews of the whole tool — one interaction-design, one
workflow — plus a live session driving the real page converged on the same
three complaints, none of which is about a missing feature. They are about
the user being unable to see what is happening.

**You cannot see the round before you fire it.** `Submit round (12)` is the
entire record of twelve irreversible decisions made across six screens. No
manifest, no jump-back, no per-mark removal.

**You cannot see what Claude is doing.** After Submit the page freezes
completely — every marking control vanishes — behind a static
"Claude is updating…" banner with no label and no elapsed time, typically for
one to three minutes.

**You cannot see what changed.** The ack lands, blocks re-render, and the
only signal is a version pill ticking `v1` → `v2` in a card corner. The
coherence sweep makes this materially worse: its entire job is changing
blocks the user never marked, so the feature shipped this morning silently
edits things the user was not looking at and offers no way to check it.

Two outright bugs surfaced alongside these, documented at the end.

The design was settled visually, as a set of five interactive mockups built
against the real stylesheet and approved in full. This spec is the written
form of those mockups; where the two disagree, the mockups are the intent.

## Screen 1 — Reading

Three changes reclaim the top of the page and give a long document a shape.

**The general composer collapses to one line.** Today it is a large empty
textarea sitting above the document (`server.py` renders it in the page
shell). It is the least-used input holding the most valuable space and it
pushes the content below the fold. It becomes a single dashed button reading
"Comment on the whole response", which expands to the existing composer on
click. Keyboard hint `G` shown at its right edge.

**A first-run discovery hint.** Every control on this page is hover-only and
the legend is collapsed behind a "?" chip, so a first-time reader sees a
static document and never learns the page is the point. A dismissible strip
shows the four glyphs and one sentence: *"Hover any sentence to mark it.
Marks batch up — nothing reaches Claude until you submit."* Dismissed state
is per-workspace and persists in `localStorage`.

**A document map rail.** A sticky left column listing every section by number
and title, click to scroll. Six sections do not need it; twenty do. It is
also the surface every other signal reuses — pending marks and changed
sections both appear here as coloured dots.

## Screen 2 — Marking

**The round dock becomes a review drawer.** The collapsed state keeps today's
information (counts per kind, a Submit button) and gains a caret. Expanded, it
lists every pending mark as a row carrying: the kind as a coloured glyph, the
section number and title, the marked text truncated to one line, the comment
text if the mark has one, and a `×` that removes that single mark. Clicking a
row scrolls to and briefly highlights the marked content.

A footer states the thing that makes the drawer safe to explore: *"Nothing has
reached Claude yet — every mark is undoable until you submit."*

**Pending marks appear in the map rail** as one dot per kind, so a five-mark
round spread over six screens is visible at a glance.

## Screen 3 — While Claude works

**The banner learns to talk.** It shows what Claude is doing right now —
*"Rewriting §2 · The retry path"* — with a sub-label of progress through the
round (*"3 of 5 marks applied"*), step pips, and a live elapsed timer.

This requires almost no new machinery, and that is the point. The pipeline
already exists end to end: a `PostToolUse` hook publishes per-event progress
labels, `/poll` serves them in its `progress` map, and the client has an
`applyProgress` function that renders them. But `pendingEvents` is populated
in exactly two places — block comments (`script.js:447`) and general comments
(`script.js:1119`) — and `subunits.js` never touches it. A round therefore
never registers its event id, `applyProgress` returns early, and the label is
computed, transmitted, and discarded. Registering the round's event id at
submit is the whole fix.

**Marking stops being frozen.** Today the busy lock hides every strip control
(`style.css`, the `body.is-busy .unit-strip button` rule) and the header strip
with it, so the user reads sections Claude is not touching and cannot mark
them. Marks are local until Submit; the only thing that ever needed the lock
is **Submit itself**. Marks made during a round queue for the next one, and
the drawer says so.

The per-block updating overlay stays as it is — a block genuinely being
rewritten should not be markable — but it becomes label-bearing in the same
way as the banner.

## Screen 4 — What changed

The largest gap, and the one that makes the sweep trustworthy.

**A change summary bar** appears after the ack: *"5 sections changed — 3 you
marked, 2 by the coherence sweep"*, with prev/next navigation that scrolls
between changed sections, and a dismiss. It is sticky beneath the header while
it lives, and it goes away on dismiss or on the next round.

**Per-section attribution.** Each changed card carries a chip in its header
saying either **you asked** or **sweep**. This split is the entire reason the
bar earns its space: the sweep changes blocks the user never marked, and the
user must be able to tell those apart from the ones they requested.

**Attribution is computed client-side and needs neither the server nor
Claude.** The client knows which `block_id`s it just submitted; any block whose
version bumped that was not in that set was changed by the sweep. This is
mechanically derivable and therefore cannot drift.

One ordering constraint makes or breaks it: the submitted `block_id` set must
be captured **when the round is sent**, not read back afterwards. On ack the
client calls `clearRound()`, which wipes `marks` — so by the time the change
bar wants to know what the user asked for, the only record of it is gone. The
set is captured at submit alongside the pending event id and held until the
bar is dismissed or the next round starts.

The bar does not survive a page reload, and that is accepted: it describes the
transition the user just watched, not a durable property of the document. The
per-block diffs do survive, because they read from the snapshot on disk.

**A per-block diff.** A "what changed" toggle in the card header opens a pane
showing the previous text against the current, with deletions and insertions
marked. The pane's heading names the provenance — for a swept block it reads
*"changed from v1 — you did not mark this section"*.

**This requires a snapshot, because today it is impossible.** `versions.json`
stores `{block_id: [hash, …]}` — content hashes only, never text
(`versions.py`). The system knows a block changed and how often but cannot say
what it said before. The fix: when the server queues a mutating event it also
writes a copy of the current `blocks.json` alongside it. That copy is exactly
the document the user was looking at when they submitted, which is the correct
baseline for "what changed since I submitted".

Server-side at queue time is deliberate over asking Claude to snapshot in the
contract. It is one mechanical place, it covers every mutating path uniformly,
and it cannot be forgotten — the sweep already taught us that an unverifiable
contract step is a weak guarantee.

Only the most recent snapshot is retained, written beside `blocks.json` in the
response directory and overwritten on each new mutating event. One round back
is what the bar describes and what the user needs; a full history is storage
and complexity for a feature nobody asked for.

The client needs the previous text to render a diff, so the snapshot has to be
reachable over HTTP — an addition to the existing per-block data route rather
than a new endpoint, and a read, so it stays outside the owner write gate and
works on read-only links too.

**An optional change note from Claude.** A mechanical diff shows *what* the
text became but not *why*, and for a compact it cannot show what was lost —
that information exists only in Claude's head at apply time. Claude may write
an optional per-block `change_note` carrying a short **Why** and, when a
compact dropped detail, a **Lost** line naming it.

The **Lost** line is the honest half of compact. Compact is lossy and
irreversible after submit, and this is the only place a user would ever learn
what it actually discarded.

The note is optional by design: when absent the diff still renders. A feature
that breaks when Claude forgets a field is a feature that breaks.

## Screen 5 — Compact severity, and one rename

**Compact's visual severity is backwards.** Delete renders struck through and
dimmed to 0.45. Compact renders as a soft violet wash at 0.55 with no
strikethrough. Delete removes content the user consciously chose to discard;
compact silently drops detail they never intended to lose. The gentler-looking
of the two is the dangerous one.

The correction keeps compact visually distinct from delete — no strikethrough,
because compact is not delete — while raising its weight: a solid violet left
spine, a deeper wash, and a one-line consequence rendered directly beneath the
marked text, *"compacted — its point is folded into what stays; the rest is
lost"*. Stating the consequence at the moment of the decision is worth more
than any legend the user has already collapsed.

**`keep` is renamed to "Leave as written".** The ✓ reads as "I approve", so it
invites liberal clicking; but it costs a full round and does nothing outside
the two narrow cases the contract documents. The wire kind stays `keep` — this
is a label change only, at both scopes and in the legend.

## The two bugs

**A typed comment can be silently omitted from the round.** Drafts live in one
`localStorage` store (`script.js`, `annotations`) and round marks in another
(`subunits.js`, `marks`), and `submitRound` reads only the second. The dock's
disabled condition is `pendingRound || is-busy` (`subunits.js:474`) and does
not include `is-editing`, which the page already sets on `<body>` whenever a
draft exists (`script.js:978`). So: type a comment, do not click "Add to
round", press Submit — the round goes without it. The text survives in the
open draft, so nothing is destroyed, but the user believes they commented and
did not.

Fix: include `is-editing` in the disabled condition, and have the dock say why
it is disabled — *"finish or discard the open comment"*.

**The dead-session banner is false and invites a duplicate round.** It says the
last submission "was not processed" (`script.js:1326`). The event is still
queued on disk and a freshly armed watcher re-emits it. Meanwhile Submit
re-arms, so the natural response — resubmit — sends the same round twice.

Fix: correct the copy to say the submission is still queued and will be picked
up, name `/annotate resume <slug>` as the way back, and keep the dock locked
rather than re-arming it.

## Explicitly out of scope

These came out of the same reviews and are deliberately not in this pass:
search that navigates rather than filters; unifying the unit-scope and
block-scope comment editors; a "suggested wording" field on comments;
per-reaction failure reporting when one bad `block_id` 422s a whole round;
multi-tab mark reconciliation; and the dead code both reviewers catalogued.

## Accepted risks

- The map rail and the drawer both add persistent chrome to a reading surface.
  The mockups show them at a size that reads as calm, but this is the kind of
  thing that only proves itself in use.
- The diff pane's usefulness depends on Claude writing good `change_note`
  text. The mechanical diff carries the feature on its own if the notes are
  poor, but the **Lost** line has no mechanical fallback.
