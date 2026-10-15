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
- System architecture — the parts, where each caller comes in, where the rules live: use a `kind: "map"` block.
- Static structure: class hierarchies, data shapes, dependency graphs — a `flowchart` block when it has a shape, otherwise prose.
- Anything that fits in 1–2 sentences.

**One diagram per flow.** Diagrams are heavier than prose blocks — visually and token-wise. A response that explains one flow gets one diagram block; longer explanations get prose blocks framing it. Don't emit two diagrams unless they're genuinely two separate flows.

## Block shape

A sequence-diagram block looks like this in `blocks.json`:

    {"id": "section-N", "kind": "sequence", "spec": {
      "title": "<the claim, a sentence with a verb>",
      "subtitle": "<optional>",
      "actors": [{"id": "<short-id>", "label": "<display name>", "role": "<optional second line>",
                  "tone": "<tone>"}, ...],                                                   // ≥ 2
      "legend": [{"tone": "<tone>", "label": "<what this colour means here>"}, ...],       // optional
      "phases": [{"id": "<phase-id>", "label": "<label>", "start_at": "<step-id>"}, ...],  // optional; in step-order
      "steps": [
        {"id": "s1", "from": "<actor-id>", "to": "<actor-id>",
         "arrow": "request|event|self|band",
         "tone": "<tone>",                  // optional
         "label": "<terse English>",
         "sub": "<optional monospace line — a call, a file:line>",
         "note": "<optional text beside the lanes — a timing, a count, a verdict>",
         "checks": [{"label": "scopes", "ok": true}, {"label": "already paid", "ok": false}],  // optional
         "n": 1},                           // optional: its number in the walkthrough
        ...
      ],
      "outcome": {"tone": "<tone>", "title": "<what happened>", "lines": ["..."]},           // optional
      "captions": [{"title": "<step 1>", "text": "<one or two sentences>"}, ...]           // optional
    }}

Block id remains `section-N` (assigned by `next_block_id`); step ids are `s1`, `s2`, ... per `next_step_id`. Both are stable across rewrites.

How the page draws it (`skills/_shared/visuals/sequence_svg.py`; the guide is `vz.md` § Lane sequence spec, in the plugin's `docs` folder):

- Each actor heads a lane: its `label`, and its `role` as a second line.
- What a step carries sits in a chip on its arrow: `label`, then `sub` in mono. Backticks in any text make a mono span.
- `checks` are ✓ / ✗ badges where the rule is applied, under the arrow's end.
- `n` numbers the walkthrough. Several arrows may share a number. Without any `n`, every arrow is numbered.
- `phases` become bands behind their rows.
- `outcome` is a box that closes the diagram.
- `captions` holds one `{title, text}` per step number. The reader presses **Step through**, and the caption of the step shows under the drawing. In a Confluence page they are written out as a numbered list under the picture.
- The part's heading shows `title`, and the drawing leaves it out. The `subtitle` shows under the heading as plain text.

`tone` is optional everywhere it appears. Omit all of them and you get a clean
monochrome diagram.

## Arrow types

- `request` — a call from one actor to another; direction follows `from`/`to`.
- `event` — a return or an automatic push; drawn dashed, its words under it.
- `self` — a call an actor makes on itself; requires `from === to`. Its chip sits beside the lane.
- `band` — **not an arrow**: a labelled strip laid across the actors from `from`
  to `to`, carrying a sentence about that stretch of the flow rather than a
  call. Use it for a phase of work with no single call to point at
  (`pre-processing — auth, tenant resolution, task lookup`) or for a branch
  condition (`the task carries Action.REFRESH, so the refresh closure runs`).
  `from === to` is allowed.

## Replies, boxes and refs — for the stage

Three optional fields are checked here and drawn only by the talk stage's lanes;
this page ignores them, so a block that carries them still renders.

- `reply_to` on an `event` names the `request` it answers, going back the way the
  call came (`from` and `to` swapped). The stage holds a bar open on the receiver
  from the call to its reply.
- `groups` puts UML boxes round runs of steps: `{"id", "kind": "alt" | "par",
  "branches": ["<condition>", ...]}` or `{"id", "kind": "loop" | "opt", "label":
  "<condition>"}`. A step joins one with `"group"`, plus `"branch": 0, 1, ...` in
  an `alt` or `par`. A box's steps follow one another, its branches come in order
  from 0, each branch has a step, and a phase never starts inside a box.
- `ref` on a step, `path:line`, gives the step's popup on the stage the source
  lines round that line.

## Tones — four colours, each with one meaning

A tone says **what the reader should conclude** from a lane or an arrow. It
does not describe how the call was made — `request` vs `event` already does that.

| tone | reads as | use it for |
|---|---|---|
| (none) | default ink | ordinary steps; most of a diagram |
| `blue` | blue | the AI or model path |
| `red` | red | the central mechanism, or the risky part |
| `green` | green | where a rule holds, or what passes |
| `amber` | amber | a warning, a cost or a workaround |

Older specs use the older tone names, and they still draw: `edge` and
`service` are blue, `internal` amber, `hot` red, `good` green, and `cheap` and
`dropped` plain (`dropped` stays dashed). Write the four colours in a new spec.

Rules:

- **A tone with no `legend` entry is a colour with no meaning.** If you tone any
  step, add a `legend` entry for each tone you used, saying what it means *in
  this diagram* — `{"tone": "red", "label": "the rule that refuses a 2nd payment"}`.
- **No colour is ordinary.** Reserve `red` and `green` for the one or two rows
  the whole diagram exists to show.
- Tone an actor by the layer it belongs to, so the lane heads read as a legend
  of their own.

## Width

The lanes are as far apart as the widest chip between them needs, so write the
real call signature and the real class name; never shorten them to fit. On the
page the drawing keeps its own size and scrolls sideways when it is wider than
the column; maximize and **Fit width** show it whole.

## Rewriting a sequence block after a comment

A sequence diagram is commented as a whole, from the card header — the step
rows are not click targets, so comments arrive with `step_id: null` and the
words tell you which step the reader means. See
`references/handling-events.md` § "Diagram block-rewrite contract" (its
targeted branch still applies to older comments that carry a `step_id`).
