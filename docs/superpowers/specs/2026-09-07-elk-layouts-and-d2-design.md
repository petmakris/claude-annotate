# ELK layout flavours for `flowchart`, D2 for `diagram`

**Date:** 2026-09-07
**Status:** Design approved on the two open questions, pending implementation plan

## Problem

A `kind: "diagram"` class diagram of seven Java classes came out unreadable —
crossing edges, a node stretched to the canvas width, labels landing on other
edges. Redrawing it by hand as a banded HTML layout was worse.

A bake-off rendered the same thirteen-node graph through seven engines
(published at `claude.ai/code/artifact/442fa180-d1f4-4b01-9cf4-31c1494aa740`)
and isolated the cause. Plates 02 and 03 are the same D2 source through the
same drawing code with one flag changed, `--layout=dagre` to `--layout=elk`,
and every crossing disappears. **The fault was never Mermaid's styling; it was
dagre.** `flowchart_layout.py` has the same weakness for the same reason: its
`assign_layers` / `order_layers` pair is a one-pass barycentre heuristic, which
is the cheap half of the same Sugiyama family.

A second finding is specific to this codebase: Mermaid puts node labels inside
`foreignObject`, so the SVG `mmdc` returns renders **blank text in anything
that is not a browser**. Two separate converters produced a picture with no
words in it.

## Decisions (from brainstorming)

- **The two kinds stay distinct** and get different treatments.
  `flowchart` = the graph you interrogate; `diagram` = the picture you look at.
- **`flowchart` gets ELK's geometry and keeps annotate's drawing.** elkjs
  returns coordinates and edge bend points; `flowchart.py` paints exactly as
  it does now.
- **`flowchart` ships several layouts and the reader picks.** Every variant is
  rendered at push time and stored in the block; a control on the block swaps
  them with no round-trip. The choice is remembered per viewer in
  `localStorage`.
- **The variant set is a fixed house set**, identical on every block so a
  reader learns the control once, minus any variant that comes out unusable
  for that particular graph.
- **`diagram` renders through D2 with no switcher** — one SVG,
  `--layout=elk`, a theme/dark-theme pair, whole-block commenting as today.
- **Mermaid is removed, not deprecated.** There is no `lang` field and no
  fallback path; `kind: "diagram"` means D2.
- **`elk.bundled.js` is vendored** in the plugin, so the plugin stays
  installable with no package step.

### What is deliberately not in scope

- Per-node comments. They do not exist on either kind today and this does not
  add them. The listener was withdrawn on purpose: a `ref` line is painted
  accent-coloured and underlined whether or not the spec gave it an `href`, so
  clicking a file reference opened the composer instead of the file.
- TALA. Best pure layout of the seven and closed-source, licensed per seat,
  watermarked until paid for.
- Structurizr. A modelling answer to a different question, and it delegates
  its drawing to Graphviz anyway.
- Client-side re-layout. Shipping `elk.bundled.js` to the browser would put
  1.4 MB on every page to save 45 KB on blocks that have a diagram.

## Design

### 1. Layout — `skills/annotate/diagrams/elk_layout.py` (new) + `elk_driver.mjs` (new)

`flowchart_layout.layout(nodes, edges)` currently returns
`(positions, canvas_w, canvas_h)` and no edge geometry; `flowchart.py`
computes every edge path itself from `cx/cy/w/h/layer`, including the side
gutter for layer-skipping edges.

The new entry point keeps that contract and extends it:

```python
layout(nodes, edges, variant="layered") -> (positions, canvas_w, canvas_h, routes)
```

- `positions` is unchanged in shape, so `flowchart.py`'s node painting needs
  no edit.
- `routes` maps edge index → `{"points": [(x, y), ...], "label": (x, y)}`, or
  is empty when ELK was not used.
- Text is measured in Python exactly as today (`text_metrics.py`,
  `node_size`), so the fonts stay the ones the page actually serves. Python
  measures, Node arranges, Python draws.
- `elk_driver.mjs` reads one JSON graph on stdin and writes the laid-out graph
  to stdout. It is a driver, not a renderer: no styling knowledge crosses the
  boundary.

**Fallback is mandatory.** If Node is absent, the driver fails, or ELK throws,
`layout` falls back to the existing pure-Python implementation and returns
empty `routes`. This is what makes the change unable to break an existing
push.

### 2. The house set — `skills/annotate/diagrams/flavours.py` (new)

Four presets, always attempted, in this order:

| name | options |
|---|---|
| `layered` | `algorithm: layered`, `direction: DOWN`, `edgeRouting: ORTHOGONAL`, entry nodes pinned to the first layer |
| `compact` | as `layered`, plus `spacing.nodeNodeBetweenLayers: 38`, `spacing.nodeNode: 22` |
| `wide` | as `layered`, `direction: RIGHT` |
| `tree` | `algorithm: mrtree` |

Entry pinning is `elk.layered.layering.layerConstraint: FIRST` set per node on
every node whose `role` is `entry`. On the bake-off graph it moves all five
entry points to the top rank *and* shortens the canvas. It is the single most
valuable option in the set and D2 cannot express it — `d2 layout elk` exposes
exactly five flags and this is not one of them.

**Edge labels stay annotate's.** ELK is sent nodes and edges only, never
labels. `flowchart.py` already has a label placer that walks candidate points
outwards from mid-edge and avoids nodes and previously placed chips
(`_place_label`), and it is better than anything ELK offers — only the
`layered` algorithm places labels at all. Keeping it also means a non-layered
variant is not disqualified for something we were never going to use.

**Viability gate**, applied to each variant before it is kept:

1. Any edge without a route of at least two points → drop. (`rectpacking`
   routes none at all.)
2. Any two node boxes overlapping → drop. (`stress` reaches its small canvas
   by letting boxes overlap.)
3. Canvas within 5% of an already-kept variant on both axes → drop as a
   duplicate.
4. `layered` is never dropped; if everything else fails, the control does not
   render and the block behaves exactly as it does today.

### 3. Block body — `skills/annotate/render.py`

The `flowchart` branch currently sets `base["svg"]`. It gains:

```python
base["svg"]      = svgs["layered"]        # unchanged; the default rendering
base["svgs"]     = {"layered": "...", "compact": "...", "wide": "..."}
base["flavours"] = ["layered", "compact", "wide"]   # order for the control
```

`base["svg"]` staying put is what keeps every stored block and any client that
has not been updated working unchanged.

Cost measured on the bake-off graph: 130 ms and 8–11 KB per variant, so three
variants is under half a second and about 28 KB per block.

### 4. The control — `paintFlowchart` in `skills/annotate/static/script.js`

`paintFlowchart(content, blk)` today is two statements: set
`content.innerHTML = blk.svg`, then append the pflow source pane. It gains a
segmented control prepended to the content when `blk.flavours` has more than
one entry.

- Buttons are the flavour names, title-cased. Clicking one swaps
  `content` innerHTML for `blk.svgs[name]` and re-appends the source pane.
- The choice is stored as `annotate.flavour.<block-id>` in `localStorage`,
  read on paint, wrapped in try/catch, and falls back to `blk.flavours[0]`.
  Per viewer, never shared, never sent to the daemon.
- `linkPflowHover` and the anchor-click listener are bound to `content`, not
  to the SVG, so both survive the swap untouched.
- The control renders after `updateBlockContent`'s innerHTML swap for the same
  reason, so an in-place rewrite cannot leave a block without it.
- `maximize.js` picks `host.querySelector("svg, iframe")`, so the maximised
  view follows the current selection with no change.

### 5. D2 — `skills/annotate/diagrams/d2.py` (new)

Takes over the contract `mermaid.py` had: spec in, SVG string out, raise on
failure so `render.py`'s existing error-pill branch catches it.

- Invocation: `d2 --layout=elk --theme=<light> --dark-theme=<dark> --pad=20`.
- `style.fill: transparent` is prepended to the source before rendering, which
  makes D2 emit `fill="transparent"` on its root rect instead of the theme's
  background. Verified: the theme's `fill-N7` background rect disappears
  entirely. Without this the diagram paints its own ground over the card.
- No `--svgId` equivalent is needed. D2 already scopes its whole stylesheet
  under a per-render hash class (`.d2-555910822`) and gives every marker a
  unique id, so two diagrams on one page cannot cross-apply — which is exactly
  the bug `--svgId` existed to prevent for Mermaid.
- `--dark-theme` emits **one** SVG carrying both palettes, switching on the
  viewer's browser dark mode. This is strictly better than what Mermaid does
  today, and it is the closest any external renderer gets to the page's
  three-state theme. It does not honour an explicit `data-theme` stamp; a
  reader who has forced light while their OS is dark will see the dark
  diagram. Accepted.
- `spec.type` (`flowchart|architecture|state|er|class`) is **dropped**. It
  existed to pick a Mermaid diagram family; D2 has none, and the shape of a
  diagram is expressed in the D2 source itself. A spec still carrying `type`
  is ignored rather than rejected, so an old `blocks.json` on disk does not
  become a hard error.
- If the `d2` binary is missing, raise with a message naming
  `brew install d2`, so the block shows the standard error pill. There is no
  fallback renderer to fall back to.

### 5b. Removing Mermaid

`render.py` stores the rendered SVG in the block body at push time and the
daemon keeps it opaquely, so **a page that is never pushed again keeps
rendering exactly as it does now**.

That does not mean removal is scoped to the block someone happens to edit.
`push.py`'s `items_for` calls `render_block` on **every** block in
`blocks.json`, and `push` always sends `{"items": items, "replace": True}` —
there is no partial push. So one comment on any single block of a live
session re-renders the whole document, and every `kind: "diagram"` block
still carrying Mermaid source (from before this branch, or from an
`/annotate resume` onto an older workspace) turns into an error pill,
including blocks nobody touched. The failure is honest — a pill, with the
Mermaid source intact in `blocks.json` — and the remedy is to rewrite that
block's `spec.source` from Mermaid to D2, the same as any other diagram
authoring change.

Twelve files mention Mermaid; the removal is:

| file | change |
|---|---|
| `diagrams/mermaid.py` | delete |
| `tests/test_diagrams_mermaid.py` | delete |
| `render.py` | `diagram` branch calls `d2.render` |
| `references/block-kinds/diagram.md` | rewritten for D2 |
| `references/block-kinds/flowchart.md` | drop the three "use Mermaid instead" pointers |
| `SKILL.md` | block-kind menu line |
| `static/script.js` | two comments naming Mermaid's inline `<style>` |
| `README.md`, `skills/annotate/README.md` | the "one renderer that shells out" line |
| `references/handling-events.md` | one mention in the rewrite contract |
| `diagrams/text_metrics.py`, `diagrams/flowchart.py` | one comment each |

`mmdc` stops being a dependency of this plugin. Nothing else in the repository
invokes it.

### 6. Docs

- `references/block-kinds/flowchart.md` — the house set, what each flavour is
  for, the viability gate, and the per-node entry pin.
- `references/block-kinds/diagram.md` — rewritten for D2 authoring; the
  Mermaid rules move under a "legacy" heading kept for `lang: "mermaid"`.
- `SKILL.md` block-kind menu — one line each.

### 7. Testing

- `elk_layout` golden tests: a fixed graph through each house-set variant,
  asserting node count, no overlaps, and that `routes` is populated.
- Fallback test: driver forced to fail, `layout` still returns a usable
  result with empty `routes`.
- Viability-gate unit tests: an unplaced label, an unrouted edge, and a
  near-duplicate canvas each drop their variant, and `layered` never drops.
- `render.py`: a flowchart block emits `svg`, `svgs` and `flavours`, and a
  block whose variants all fail still emits a working `svg`.
- `d2.py`: missing-binary message, and a spec still carrying the old `type`
  key renders rather than erroring.

## Dependencies added

| what | where | size |
|---|---|---|
| `elk.bundled.js` | vendored in the plugin | ~1.4 MB |
| `d2` | must be on PATH for `kind: "diagram"` | Go binary, `brew install d2` |

Removed: `mmdc` and the headless Chrome it spawns.

Node is still required, now for the ELK driver instead of for `mmdc`.
Vendoring rather than depending on npm keeps the plugin installable with no
package step, at the cost of 1.4 MB in the repository — chosen for minimum
friction over minimum repository size.

## Outcome

The ELK half of this design shipped: the vendored `elk.bundled.js`, the
`node` driver, the house set with its viability gate, and the reader-facing
layout control on `kind: "flowchart"` blocks.

The D2 half was reverted. `kind: "diagram"` stays on Mermaid via `mmdc`, and
`d2` is not a dependency of this plugin. Seven adversarial review rounds each
found a fresh way for author-controlled markup to reach the page: D2's `|md|`
markdown blocks embed raw HTML in the rendered SVG, and that SVG is injected
into a page with no CSP and exported into files users share. Every guard we
tried — a source-level refusal of markdown blocks, a Python SVG sanitizer, a
`foreignObject` allowlist, an in-page DOM sanitizer, then dropping the
`foreignObject` surface altogether — rested on predicting how some other
parser behaves (Chrome's URL parser, D2's XML checker, D2's own lexer), and
each prediction diverged somewhere. The last break was a quote inside an
unquoted D2 key (`a'b: |md '`), which defeated the source check and let the
payload fire a live `@import` beacon and restyle the host page. Mermaid runs
with `htmlLabels: false` and `securityLevel: "strict"`, so author HTML never
reaches the page at all — worse layout, sound security posture.

Anyone reconsidering D2 should start here: the blocker is not a specific
bypass to patch, it is that every defence available to us is a prediction of
a third-party parser rather than a property we control. A CSP on the annotate
page, or a D2 build with markdown blocks compiled out, would change that
calculus; nothing short of it does.
