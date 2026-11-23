# Compact, and a coherence sweep before the page unlocks

Date: 2026-08-07
Status: approved, ready for implementation planning

## Problem

Two independent complaints about the annotate page, both about what the user
sees after Claude responds.

### The document drifts out of alignment

A round rewrites block 4. Block 6 still describes what block 4 used to say.
Nothing catches this, because nothing is looking: the block-rewrite contract in
`references/handling-events.md` says, in as many words, *"Touch only the blocks
you actually need to change."* That rule exists for a good reason — the server
derives `version` from a content-hash chain, so gratuitously re-emitting prose
inflates the version of a block the user never asked about — but it means an
untouched block that the round made false stays false.

The round contract already carries a narrow version of the fix. A block-scope
`delete` is followed by a "smart-drop" step that re-threads surviving blocks
which referenced the removed one. That is the right instinct applied to exactly
one of the four ways a round can break the document.

### Hiding content does not do what the user wants

The eye-off control today is a **fold**: a private, local, reversible "I have
read this". `subunits.js` is explicit that this is deliberate — the read store
is a separate key space from marks precisely so that folding a paragraph you
understood cannot be mistaken for rejecting it, and Claude is never told about
it.

That is not what the user wants the gesture to mean. The intent behind hiding a
sentence is *"I am fine with this, it is not important enough to occupy the
page, take it out of my sight."* The document should get slimmer. Folding
leaves a dimmed one-line stub behind and changes nothing about the document
itself, so a 50-sentence plan with 20 things hidden is still a 50-sentence
plan.

## What compact means

Compact is a **fourth round control**, alongside delete / keep / comment. It
shares their vocabulary and their timing model: local and undoable until
Submit, then applied with the rest of the round in one pass.

It is not an alias for delete, and the difference is the reason it earns its own
kind:

| kind | the words | the idea |
|------|-----------|----------|
| `delete` | removed | **out of scope.** Never acted on, never reintroduced |
| `compact` | removed | **still binds the plan.** Only its page real estate is withdrawn |

Delete the sentence about health checks and no health check gets built.
Compact it and one still does — the plan simply stops spending six lines
saying so.

### What happens to the hidden information

It is **absorbed into the surviving prose**. Each compacted unit's contribution
is folded into the nearest surviving unit that already covers that ground. The
page gets shorter and denser. Nothing new appears — no summary box, no "3
compacted" trailer, no dimmed stub.

Worked example. Six sentences, two compacted:

```
Phase 1 moves the read path onto the new ingest service while writes
keep going to the legacy queue.
The service is deployed behind the existing load balancer.        ← compact
Health checks hit /healthz every 10s with a 2s timeout.           ← compact
Phase 2 flips writes over once the read path has run clean.
```

becomes

```
Phase 1 moves the read path onto the new ingest service while writes keep
going to the legacy queue, behind the existing load balancer and
health-checked on /healthz.
Phase 2 flips writes over once the read path has run clean.
```

The first sentence was rewritten to carry the absorbed material, so its version
bumps. The last was not touched, so it does not.

Note what the absorb dropped: the 10-second interval and the 2-second timeout.
That is the accepted, deliberate cost — see the next section.

### There is no hidden store

Nothing is retained off-page. Not in `blocks.json`, not in a side file, not in
Claude's working context past the turn. **Whatever survives the absorb is the
document, and it is the whole of what Claude acts on.**

This was chosen over two alternatives — retaining the originals and still using
them, or retaining them inert as an undo trail — for one reason: if Claude
keeps working from material the user deliberately removed from sight, the page
stops being the full picture. The user approves a 30-sentence plan and Claude
executes a 50-sentence one, with no way to audit the gap.

The cost is real and is accepted: **compact is lossy and irreversible.** Detail
that no surviving sentence can carry is gone. Local undo until Submit is the
only safety net.

### Compact is an owner-only edit

A guest on a shared read-only link cannot compact. Compact is an edit, and
edits belong to the person who owns the workspace.

This falls out for free. The write gate lives on `_dispatch_post` in
`skills/_shared/web_companion/server.py` rather than on individual routes, so
every POST is guarded by default. Compact travels on the existing round route
and inherits the 403.

## What the sweep does

After a round is applied and **before the `.ack` is written**, every block is
re-read and checked.

The placement is the load-bearing decision. The page is locked behind "Claude
is updating…" until the `.ack` lands — `/poll` reports `busy: true` until then.
The ack *is* the moment the user sees the answer. Putting the sweep before it
means an unaligned document is never on screen.

It costs no extra tool calls. `blocks.json` has already been read to apply the
round; the sweep is a reasoning pass over material already in hand.

**The sweep fixes exactly two things:**

1. **References that no longer resolve** — a pointer to a deleted block, a step
   number that shifted, a count or total that stopped adding up, a glossary
   term whose referent is gone.
2. **Claims the round made false** — including claims that never name the
   changed block. This is the case today's smart-drop cannot catch.

**The sweep must not touch** wording, tone, ordering, transitions, or anything
that still reads true. A block is rewritten only if leaving it alone would make
the document lie. "Wordy but accurate" is left alone.

Rewrites go through `blocks.update_block`, which is content-hash-safe, so a
block that needed nothing costs no version bump. If a sweep edit itself
invalidates another block, that is resolved in the same pass — the sweep
settles before the ack, not across turns.

This subsumes the existing smart-drop step, which becomes one case of the
general rule rather than a separate instruction.

## Implementation

The two halves share a spec because they are the same complaint — what the
document looks like when Claude hands it back — and they touch the same round
pipeline in `references/handling-events.md`. They are independently shippable:
the sweep is a contract change with no code, and compact is a control change.
Neither depends on the other.

### Frontend

The eye-off button keeps its position, its SVG, and its round shape. Three
changes:

- Gains `data-kind="compact"`; its click handler calls `toggleMark(...)`
  instead of `toggleUnitRead(...)`, putting it on the wire with the other three
  controls.
- Class renames `.unit-read` → `.unit-compact` and `.hover-read` →
  `.hover-compact`. It loses the solid-border-versus-dashed distinction, which
  exists solely to signal "I am not one of the round controls". It now is one.
- Gains a pending-mark appearance distinct from the other three: dimmed with a
  violet wash, against delete's strikethrough and keep's green tint.

The button is appended separately from the three text-glyph controls, because
the strip's render loop assigns `b.textContent = glyph` and cannot carry SVG.
That separate append already exists for the fold and is kept as-is.

`foldable()` and its `<tr>` exclusion are removed. That exclusion exists only
because a folded row cannot be height-clamped, which made the control an
affordance that visibly did nothing. Compact clamps nothing, so **table rows
become compactable** — an existing gap closes as a side effect.

### Server

`_ROUND_KINDS` gains `"compact"`. That is the entire server change. Validation
already handles a kind with no `text` — only `comment` requires non-empty text.

### Claude's contract

`references/handling-events.md` gains compact to the round vocabulary table and
a rule for applying it, plus the sweep as a mandatory step before the ack.

Application order within the single pass, extending what is already there:

1. Block-scope reactions first. A block-scope `delete` makes that block's unit
   reactions moot; a block-scope `compact` absorbs them — a comment on a unit
   inside a compacted block is answered, and the answer is what gets carried
   into the neighbour.
2. Unit-scope reactions, all of a block's applied together in one rewrite.
3. `drop_unused_terms`.
4. **The sweep.**
5. One `save_atomic`, one `.ack`.

Compact rules:

- Cut the unit from the block's markdown; fold its contribution into the
  nearest surviving unit that already covers that ground.
- If no surviving unit can carry it, it is dropped. This is expected, not an
  error condition.
- If every unit in a block is compacted, the block is removed via
  `remove_block`, its gist absorbed into a neighbouring block, and the
  remainder re-threaded — same handling as a block-scope delete, different
  meaning for what survives.
- A compacted idea still binds the plan. Do not treat compacted content as out
  of scope the way deleted content is.
- **`keep` beats compact.** If the only surviving unit that could carry the
  absorbed material is marked `keep`, it is not rewritten — `keep` is an
  explicit "do not rewrite this" and is the whole reason it exists. Carry the
  material into a different surviving unit, or drop it. A user can therefore
  protect a sentence and compact its neighbour in the same round without the
  protection quietly failing.

### What is removed

The private-fold apparatus in full: the `READ_KEY` store, `loadRead` /
`saveRead`, `applyReadState`, `applyBlockRead`, `toggleUnitRead` /
`toggleBlockRead`, the version-keyed spring-back that unfolds a rewritten
block, the read sweep in the reconcile path, `foldable()`, and the associated
CSS (`.sub-unit[data-read="1"]`, `section.block[data-read="1"]`).

Two behavioural exemptions die with it:

- **Read-only mode.** Today the fold is the one thing a guest can still do,
  because it never reaches the server. With no fold, a shared link renders the
  document and nothing else. The `:not(.hover-read)` / `:not(.unit-read)`
  carve-outs collapse to hiding every control.
- **`body.is-busy`.** Today the fold stays live during a round because it
  changes nothing Claude will see. It collapses to hiding every strip button.

## Testing

- **Server:** `compact` is accepted by round validation at both scopes; a
  compact reaction with empty `text` is valid; the round route still 403s for a
  non-owner.
- **Frontend smoke:** the strip carries a compact button; `.unit-compact`
  exists and carries the round-control appearance; no reference to the read
  store survives.
- **Read-only:** `test_smoke_read_only.py` is rewritten to assert that *every*
  control is hidden, inverting its current `:not(.hover-read)` assertions.
- **Deleted:** `test_smoke_read_fold.py` in full.
- **Audit suite:** `/audit-http-surface` and `/audit-docs-truth` must stay green
  — the route contract and the prose both change here.

## Explicitly out of scope

- Any off-page store of compacted content, in any form.
- Undo for compact after submit.
- A guest-side compact queue or any new guest feedback channel.
- Any on-page residue of a compact — trailer, count, or stub.
- A user-visible report of what the sweep changed. Version bumps already show
  which blocks moved.

## Accepted risks

- **Compact is irreversible and lands in one click.** Delete at least looks
  destructive; the eye does not, and it now permanently drops detail. Local
  undo until Submit is the only protection.
- **Absorption is lossy in a way that is invisible at click time.** The user
  cannot tell, when compacting, whether a neighbour exists that can carry the
  detail. Both risks follow directly from "the page is the contract" and were
  accepted with that choice.
