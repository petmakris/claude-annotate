# `kind: "flowchart"` block

Read this when you've decided (from the kind menu in SKILL.md) that a block
should be a flowchart, and you need the exact contract to emit or rewrite it.

## When a flowchart is the right block

A block should be a `kind: "flowchart"` (instead of prose, or another diagram
kind) when the content is a **branching / decision / process flow**: a
sequence of steps that forks on a condition, converges from multiple entry
points, or ends in distinct success/error outcomes.

Typical fits: validation pipelines, guard clauses that fan in from several
callers, "if X then Y else Z" logic across a few methods, request-handling
flows with an error branch.

**Use `kind: "sequence"` instead when** the dominant axis is *time* and
*who-talks-to-whom* — actor A calls actor B, which calls actor C, in order.
Sequence diagrams are for temporal actor↔actor exchanges; flowcharts are for
the shape of a decision, regardless of how many actors are involved.

**Use `kind: "diagram"` instead when** the content is static structure or
non-branching shape: system/service architecture, state machines, ER models,
class hierarchies. Those four families still go through Mermaid — see
`references/block-kinds/diagram.md`. (Mermaid `type:"flowchart"` is
deprecated in favor of this kind — see that file.)

**Do NOT use a flowchart block for:**

- A flow with no branching or convergence — a numbered list or short prose
  does the job.
- Temporal actor↔actor exchanges — use `kind: "sequence"`.
- Anything that fits in 1–2 sentences.

**One diagram per concept.** Like sequence and Mermaid blocks, flowcharts are
heavier than prose — visually and token-wise. Frame the diagram with a short
prose block; the diagram must add clarity, not decorate.

## Block shape

A `kind: "flowchart"` block looks like this in `blocks.json`:

    {"id": "section-N", "kind": "flowchart", "spec": {
      "title": "<short title>",
      "nodes": [
        {"id": "<short-id>", "role": "<role>", "label": "<text>", "ref": "<Class:line>",
         "method": "<signature>", "sub": "<italic sub-caption>", "href": "<link>"},
        ...
      ],
      "edges": [
        {"from": "<node-id>", "to": "<node-id>", "label": "<optional edge label>"},
        ...
      ]
    }}

Block id remains `section-N` (assigned by `next_block_id`). Node ids are
short author-chosen strings (`"a"`, `"b"`, `"f"`, ...) — there is no
`next_node_id` minting helper; pick stable, short, unique ids yourself and
keep them stable across rewrites. `edges` must form a DAG over `nodes` — the
server rejects a spec whose edges contain a cycle or reference an unknown
node id.

### `role` values and what they mean

Every node has a `role`; it drives both the node's shape and its color:

| `role` | Meaning | Color |
|--------|---------|-------|
| `entry` | Where the flow starts (a user action, an incoming call). | blue |
| `code` | A concrete method/class in the flow. | slate/grey |
| `call` | A downstream call made from the flow (no `ref`, just a `method`). | slate/grey |
| `decision` | A branch point. Rendered as a diamond, not a rounded box. | amber |
| `success` | A terminal "this succeeds" outcome. | green |
| `error` | A terminal "this throws/fails" outcome. | red |

An unrecognized or missing `role` falls back to the `code` styling.

### Node fields

- `id` (required) — short, unique, stable across rewrites.
- `role` (required) — one of the six values above.
- `label` — short display text (the node's headline).
- `ref` — a `Class:line` style code reference, rendered as its own line and,
  when `href` is set, wrapped in a link.
- `method` — a method name/signature, rendered as its own line.
- `sub` — an italic sub-caption line (secondary detail, e.g. "no check").
- `href` — optional link target for the node. Two forms:
  - `jetbrains://idea/navigate/reference?project=<name>&path=<abs-path>:<line>`
    — jump-to-source; opens the referenced file/line in IntelliJ. Use for
    `code`/`call` nodes that point at a real method.
  - `#<block-id>` — cross-block anchor; scrolls the page to another block
    (e.g. a node that says "see the retry flow" linking to `#section-7`).

A node needs none of `label`/`ref`/`method`/`sub` to be individually
required, but should have at least one so it isn't blank. Prefer a
**structured node** (separate `ref`/`method`/`sub` lines) over cramming
everything into one long `label` string — the renderer lays each field on
its own line, so splitting them keeps the box compact and scannable.

### Edge fields

- `from` / `to` (required) — node ids; must reference nodes that exist.
- `label` — optional short text on the edge (e.g. `"OFF"`, `"ON + doc
  missing"`) for a decision's branch outcomes.

### Size guidance

Keep a flowchart to **≤ ~15 nodes**. Past that it stops being legible as an
inline block — split into two flowcharts (e.g. one per entry point) or fold
the excess detail into the framing prose instead of adding more boxes.

Sizing is automatic and you do not have to defend against it: node boxes are
measured from their text using the real fonts, long `label`/`sub` prose wraps,
`ref`/`method` never break mid-token (the box widens instead), rows are packed
so nodes cannot overlap, and the canvas grows when a row needs the room. What
still costs you is **width**: a row of five wide nodes produces a wide diagram
that the card scales down, so text ends up small. Prefer **≤ 4 nodes per
layer**, and keep a `decision` node's text short — a diamond needs roughly
twice the width of the text it holds, so `{"role":"decision","label":"toggle
ON?"}` reads far better than a decision node carrying a long `ref` line.

## Canonical example

    {"id": "section-N", "kind": "flowchart", "spec": {
      "title": "Both actions funnel into one guard",
      "nodes": [
        {"id": "a", "role": "entry",    "label": "User SAVES / edits orders"},
        {"id": "c", "role": "entry",    "label": "User SHARES", "sub": "VALIDATE lifecycle action"},
        {"id": "b", "role": "code",     "ref": "OrderService:154", "method": "validateAttachmentsSelection(items)",
                    "href": "jetbrains://idea/navigate/reference?project=proj&path=/abs/OrderService.java:154"},
        {"id": "d", "role": "code",     "ref": "WorkflowActionsExecutor:129", "method": "validateOrder(order)"},
        {"id": "e", "role": "call",     "method": "validateRequiredDocuments(...)"},
        {"id": "f", "role": "decision", "label": "toggle ON?"},
        {"id": "g", "role": "success",  "label": "allow", "sub": "no check"},
        {"id": "h", "role": "error",    "label": "throw", "method": "MissingAttachmentsException"}
      ],
      "edges": [
        {"from": "a", "to": "b"}, {"from": "c", "to": "d"},
        {"from": "b", "to": "e"}, {"from": "d", "to": "e"}, {"from": "e", "to": "f"},
        {"from": "f", "to": "g", "label": "OFF"}, {"from": "f", "to": "h", "label": "ON + doc missing"}
      ]
    }}

Two entry points (`a`, `c`) converge on the shared guard (`e`), which
branches on a decision (`f`) into a success and an error outcome — a shape a
numbered list or a single sequence diagram couldn't express cleanly.

## Authoring the chart as Python (`source`)

Hand-written `nodes`/`edges` are fine for a shape nobody will revise. Write
`spec.source` instead whenever the flow is something the human will **argue
with**: a plan, a control flow you are proposing to change, an explanation they
will want to correct. A node list has nothing to edit, so a comment on one box
can only be answered in prose. A source has a line.

    {"id": "section-N", "kind": "flowchart", "spec": {
      "source": "\"\"\"How a request becomes evidence.\"\"\"\n\n\ndef atlas(request):  # ! request R\n    ..."
    }}

The server compiles `source` and fills in `title`, `nodes` and `edges` itself.
**Do not write `nodes` or `edges` alongside a `source`** — they are derived, any
you write are replaced, and hand-editing them is how the two fall out of sync.

### The subset

One module docstring (the chart title), one `def` (the entry node), and inside
it only:

| Python | Node |
|---|---|
| `def f(...)` | `entry` — labelled by the `# !` tag, else the function name |
| `if` / `elif` / `else` | `decision` — labelled by the `# ?` tag, else the test's source |
| `raise X(...)` | `error` |
| `return X(...)` | `success` |
| `x = f(...)` | `code` |
| `f(...)` | `call` |

The `yes` branch is the body; the `no` branch is the `else`, or the
fall-through when there is no `else`. A branch that does not return or raise
converges on the next statement — that is how fan-in is expressed.

### Tags

Trailing comments carry what the node cannot say in code. All optional:

| Tag | On | Becomes |
|---|---|---|
| `# ! text` | the `def` | the entry node's label |
| `# ? text` | an `if` | the diamond's label — keep it short, a diamond needs roughly twice the width of its text |
| `# id: slug` | any statement | pins the node id (see below) |
| `# cache: text` | any statement | `sub`, prefixed `cache:` |
| `# gate: text` | any statement | `sub`, prefixed `gate:` |
| `# note: text` | any statement | `sub`, plain |
| `# ref: Class:line` | any statement | the `ref` line |

### What it refuses, and why that is the point

The compiler fails with a line number rather than dropping what it does not
understand, and the block renders an error pill carrying that line. **Do not
work around a refusal by hand-writing nodes** — a chart that quietly omits a
branch reads as complete, which is worse than no chart.

- `for` / `while` — a loop needs a back edge and this spec must be a DAG; the
  validator rejects cycles. Collapse the repetition into one step, or split the
  flow.
- `try` / `except` — draw the failure as an explicit `raise` on the branch that
  produces it.
- `with`, nested `def`, `class` — the flow is the steps, not the scoping or the
  types.
- an assignment or bare statement that is not a call — a step is something that
  happens.
- a statement after a `return` or `raise` in the same block — unreachable.

Over ~15 nodes it still compiles but warns, for the reason in **Size guidance**
above. Split it exactly as you would a hand-written one.

### Node ids, and keeping a comment thread alive

Ids are derived from the node's text, so they are stable for free — until the
node is reworded, which renames its id and orphans any comment thread hanging
off it. **Before rewording a node that carries a live thread, pin its id** with
`# id: <slug>`. Ids must be unique; a duplicate pin is refused, naming both
lines.

## Per-node comments

Flowchart blocks have **per-node hit targets** — each node in the rendered
SVG carries `data-node-id`. Clicking a node scopes the comment to that node:
on the wire the click arrives in the same `step_id` field the sequence kind
uses (there is no separate `node_id` JSON field — `step_id` carries the
node's id for this kind too). See `references/handling-events.md` §
"Flowchart block-rewrite contract" for how to handle the resulting event.

Flowchart blocks authored as `source` render the Python under the chart, one
row per line, with the same hit target on the row that produced each node — so
a reader can click either the box or the line that draws it.

## Rewriting a flowchart block after a comment

See `references/handling-events.md` § "Flowchart block-rewrite contract" —
flowchart blocks support per-node targeting via `step_id`.

When the block has a `source`, answer the comment by editing the source, never
the compiled nodes:

1. Find the commented node in the block's spec. Its `line` is the source line
   that produced it.
2. Edit **that line** of `source`.
3. Re-emit the block with only `source` changed. The server recompiles; if your
   edit leaves the subset, the refusal names the line — fix it rather than
   falling back to hand-written nodes.
4. If the reword would change the node's derived id and it carries a thread,
   pin the id first with `# id: <slug>`.

This is the whole reason `source` exists: a comment on a box becomes an edit to
a line.
