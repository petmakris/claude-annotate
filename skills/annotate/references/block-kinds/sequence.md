# `kind: "sequence"` block

Read this when you've decided (from the kind menu in SKILL.md) that a block
should be a sequence diagram, and you need the exact contract to emit or rewrite it.

## When a sequence diagram is the right block

A block should be a sequence diagram (instead of prose) when ALL of:

- The content involves ≥ 2 named entities interacting (browser ↔ server, user ↔ system, two services...).
- The content has a clear temporal order — step 1, then step 2, ...
- Who-talks-to-whom matters — a numbered list loses that information.

Typical fits: code flows, request/response protocols, event lifecycles, deployment pipelines, state transitions tied to events over time.

**Do NOT use a sequence-diagram block for:**

- Single-actor flows (a numbered list does the job).
- Branching/decision logic where time isn't the dominant axis — use a `kind: "flowchart"` block.
- Static structure: class hierarchies, data shapes, dependency graphs, system architecture — use a `kind: "diagram"` block.
- Anything that fits in 1–2 sentences.

**One diagram per flow.** Diagrams are heavier than prose blocks — visually and token-wise. A response that explains one flow gets one diagram block; longer explanations get prose blocks framing it. Don't emit two diagrams unless they're genuinely two separate flows.

## Block shape

A sequence-diagram block looks like this in `blocks.json`:

    {"id": "section-N", "kind": "sequence", "spec": {
      "title": "<short title>",
      "actors": [{"id": "<short-id>", "label": "<display name>", "tone": "<tone>"}, ...],  // ≥ 2
      "legend": [{"tone": "<tone>", "label": "<what this colour means here>"}, ...],       // optional
      "phases": [{"id": "<phase-id>", "label": "<UPPERCASE LABEL>", "start_at": "<step-id>"}, ...],  // optional; in step-order
      "steps": [
        {"id": "s1", "from": "<actor-id>", "to": "<actor-id>",
         "arrow": "request|event|self|band",
         "tone": "<tone>",                  // optional; default "plain"
         "label": "<terse English>",
         "sub": "<optional monospace sub-caption — a file:line, a call id>",
         "note": "<optional right-gutter text — a timing, a count, a verdict>"},
        ...
      ]
    }}

Block id remains `section-N` (assigned by `next_block_id`); step ids are `s1`, `s2`, ... per `next_step_id`. Both are stable across rewrites.

`tone` is optional everywhere it appears. Omit all of them and you get a clean
monochrome diagram — nothing below is required.

## Arrow types

- `request` — a call from one actor to another; direction follows `from`/`to`.
- `event` — a return or an automatic push; drawn dashed.
- `self` — a call an actor makes on itself; requires `from === to`.
- `band` — **not an arrow**: a labelled strip laid across the actors from `from`
  to `to`, carrying a sentence about that stretch of the flow rather than a
  call. Use it for a phase of work with no single call to point at
  (`pre-processing — auth, tenant resolution, task lookup`) or for a branch
  condition (`the task carries Action.REFRESH, so the refresh closure runs`).
  `from === to` is allowed.

## Tones — colour carries the finding, not the mechanism

A tone says **what the reader should conclude** from an edge. It does not
describe how the call was made — `request` vs `event` already does that.

| tone | reads as | typical use |
|---|---|---|
| `plain` | default ink | ordinary steps; the majority of a diagram |
| `edge` | blue | crosses the system boundary — browser, gateway, public API |
| `internal` | amber | inside the component being explained |
| `service` | teal | a downstream service or dependency |
| `cheap` | grey | negligible; deliberately de-emphasised |
| `hot` | crimson, heavier | **the problem** — duplicated work, the slow call |
| `good` | green, heavier | **the fix** — the proposed path |
| `dropped` | grey, struck through | a call the proposal removes |

Rules:

- **A tone with no `legend` entry is a colour with no meaning.** If you tone any
  step, add a `legend` entry for each tone you used, saying what it means *in
  this diagram* — `{"tone": "service", "label": "crosses Kong — expensive"}`.
- **Use at most four tones in one diagram**, `plain` aside. Beyond that the
  colours stop grouping and start decorating.
- **`hot` and `good` are the only heavy strokes.** Reserve them for the one or
  two rows the whole diagram exists to show. Toning half the rows `hot` means
  none of them stand out.
- A `band` and an actor take a tone too — tone the actor by the layer it belongs
  to, so the column heads read as a legend of their own.

## `note`, and row numbers

`note` puts monospace text in a fixed right-hand gutter — a timing, a count, a
verdict. Steps that carry a `note` are **numbered automatically** (`#1`, `#2`, …)
in the left margin, in order; steps without one are left unnumbered. That gives
a diagram two reading orders: the flow itself, and the numbered rows worth
measuring. Give a step a `note` only if the number earns its place.

## Density is the point — do not fight the grid

The renderer uses a fixed grid: 112px actor columns on a 122px pitch, 34px rows,
and a canvas that keeps its pixel size inside a card that scrolls horizontally.
Consequences for you as the author:

- **Long actor names are free.** `EnrichedProposalBatchService` wraps to
  `EnrichedProposal` / `BatchService` inside the standard column. Do not
  abbreviate an actor to make it fit, and do not shorten a class name to
  something the reader cannot grep for.
- Force a two-line split with a newline in the label — `"Kong\nUOB gateway"` —
  when the second line is a qualifier rather than part of the name.
- **Twelve actors is comfortable.** The old renderer scaled the whole diagram
  down to the card, so wide diagrams became unreadable and the guidance was to
  keep the actor count low. That is no longer true: type is the same size at two
  actors and at twelve. Include the actor if the flow genuinely touches it.
- Arrow labels float over neighbouring lifelines by design. Write the real call
  signature; do not truncate it to the width of its arrow.

## Rewriting a sequence block after a comment

A sequence diagram is commented as a whole, from the card header — the step
rows are not click targets, so comments arrive with `step_id: null` and the
words tell you which step the reader means. See
`references/handling-events.md` § "Diagram block-rewrite contract" (its
targeted branch still applies to older comments that carry a `step_id`).
