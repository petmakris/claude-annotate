# Shared visuals with frames

Status: design agreed 2026-10-06, written for review. Projects 2 and 3 of `2026-10-06-talk-and-stage-join-annotate-design.md`, built as one.

## Goal

Annotate's sequence diagram and flowchart become tools that talk and stage use too. On the stage they reveal step by step, in time with the voice. Annotate keeps drawing exactly what it draws today.

Success, seen on a live call:

1. The agent writes `[[show sequence | Service check]] {json} [[/show]]`. The stage shows the actors, then each step arrives as the voice reaches its sentence. The step being spoken is lit both in the grid and in its key row.
2. `[[show flowchart | …]] {json} [[/show]]` reveals its nodes in order. Every arrow appears as soon as both of its ends are shown.
3. A small diagram fills the pane. The counter reads "Step 2 of 5", with Back and Next buttons.
4. Annotate's suite passes, and annotate's rendered output for a fixed set of specs is byte-identical to before the move.

## What exists today

- `skills/annotate/diagrams/`: `sequence.py` (an SVG grid plus an HTML key), `flowchart.py` (SVG, laid out by ELK through Node, with a pure-Python fallback), `flowchart_layout.py`, `elk_layout.py`, `elk_driver.mjs`, `flavours.py`, `views.py`, `text_metrics.py`, `font_metrics.py`, and `vendor/elk.bundled.js`. Their only import from the rest of annotate is `skills.annotate.atomic.write_text_atomic`.
- Their look is the sequence and flowchart rules of `skills/annotate/static/diagram.css`, written against annotate's colour tokens (`--text-dim`, `--text-strong`, `--diagram-ground`, `--border`, `--t-*`) and fonts (Bricolage Grotesque, Monaspace Radon).
- `skills/stage/scene.py` compiles talk's verbs into frames over keys (`node:`, `edge:`, `group:`, `line:`, `row#`). `_reveal` brings in an edge's two ends, but revealing two nodes never brings in the edge between them, so a stepped diagram's arrows only arrive with the rest frame.
- `skills/stage/static/scene.js` finds keys through three adapters: lines, rows and Mermaid flowcharts (`svg_keys.js`).
- Talk reads `flowchart` as another name for a Mermaid diagram (`KIND_ALIASES` in `talk.py`).
- The webcompanion daemon serves a session's assets only from inside its registered root, and refuses symlinks that point out of it.

## Design

### 1. The library: `skills/_shared/visuals/`

The `diagrams/` modules move to `skills/_shared/visuals/`, with `vendor/` and `elk_driver.mjs`. `write_text_atomic` moves with them as `visuals/atomic.py`. Annotate's other users of `atomic` import it from there. Every import of `skills.annotate.diagrams` changes to `skills._shared.visuals`, the tests that cover those modules move to `skills/_shared/visuals/tests/`, and nothing is left behind as a re-export.

**Keys, opt-in.** `sequence.render`, `sequence.render_key` and `flowchart.render` gain a keyword `keyed: bool = False`. With `keyed=True` they add `data-key` to every part the eye can land on:

| Part | `data-key` |
|---|---|
| a sequence step row (arrow, band or self call) and its key row | `step:<step id>` |
| a sequence actor box and its label | `actor:<actor id>` |
| a flowchart node | `node:<node id>` |
| a flowchart edge, its path, head and label | `edge:<from>-><to>#<n>`, the n-th edge from `from` to `to` |

Annotate never passes `keyed`, so its output does not change.

**Typefaces.** `text_metrics` takes a face profile. `annotate` (the default) keeps Bricolage Grotesque and Monaspace Radon. `stage` measures Geist and Geist Mono. `tools/gen_font_metrics.py` generates both tables into `font_metrics.py`. `render` and `render_key` take `face: str = "annotate"`, and the stage passes `face="stage"`. Geist and Geist Mono (OFL) ship as woff2 in `skills/_shared/visuals/fonts/`, and the stage loads them from there instead of from Google Fonts.

**CSS.** `skills/_shared/visuals/visuals.css` holds the sequence and flowchart rules, written against the token names annotate already uses. Annotate's `diagram.css` keeps those rules between `/* visuals:begin */` and `/* visuals:end */`, byte-identical to `visuals.css`. A test fails if they differ, because annotate's page can only load files from its own `static/` folder. The stage loads `visuals.css` directly, and maps annotate's token names onto its own colours in `stage.css`, for light and dark. Font families in `visuals.css` are variables, `--vis-sans` and `--vis-mono`, defaulting to annotate's fonts. The stage sets them to Geist.

### 2. The stage's asset root is `skills/`

`stage.py` registers `skills/` as the session's asset root, with the entry `stage/static/entry.js`. Every stage asset is already addressed relative to its own script, so nothing else moves. `entry.js` loads `../../_shared/visuals/visuals.css` and the fonts beside it.

### 3. One frame engine, on `data-key`

`scene.js` drops its three adapters. Every board marks its own keys as it paints:

- code and change lines: `data-key="line:<n>"`
- table rows: `data-key="row#<n>"`
- Mermaid: after drawing, `svg_keys.js` stamps `node:`, `edge:` and `group:` keys on the elements it finds today
- sequence and flowchart: the generator's own `data-key`

The engine looks keys up with `[data-key]` only. One key may name several elements, such as a step's arrow and its key row, and they hide, show and light together. The draw-on animation for edges stays, keyed on `edge:`.

**The arrow rule.** In `scene.py`, after every reveal, each `edge:` key whose ends (its `up` list) are all shown is shown too. This fixes stepped Mermaid diagrams as well.

**Models.** `scene.py` gains `sequence_model(spec)` and `flowchart_spec_model(spec)`:

- Sequence: keys are actors and steps. `order` is the steps in spec order. A step's `up` is its two actors. `names` maps each folded label and actor label to its key.
- Flowchart: keys are nodes and edges. `order` is the nodes in spec order, then any edge whose ends are not both earlier. An edge's `up` is its two nodes, and `edges` maps `(from, to)` to its keys.

`resolve` accepts `step s3`, `s3`, `node a`, `a`, `a->b`, and a label read fuzzily as today.

### 4. On the stage

A new inline format, `visual`: `{"type": "inline", "format": "visual", "tool": "sequence" | "flowchart", "html": "<svg>…", "key": "<ol>…"}`. `html` and `key` come from the generator, which escapes every label, so the page inserts them as they are.

- **Sequence layout.** The grid and the key sit side by side when the pane is at least 1000px wide. Below that, the key goes under the grid. A lit step lights its row in both.
- **Fit grows.** For every diagram (visual and Mermaid), Fit draws at the largest size that fits the pane, up to 2× its natural size. Actual size stays as drawn.
- **The step bar.** The bare `2/5` becomes `Step 2 of 5`, between Back and Next buttons. Back and Next move one frame, from 0 to the rest frame, and turn off "Stage follows the voice" until the next answer, as tapping a tab does today.

`stage.py show` accepts `sequence:-` and `flowchart:-`, with the JSON spec on stdin. A bad spec exits 2 with the validator's message.

### 5. In talk

- `[[show sequence | Title]] {json} [[/show]]` and `[[show flowchart | Title]] {json} [[/show]]`. A body starting with `{` is a spec for the tool. Any other body under `flowchart` stays a Mermaid diagram, so `KIND_ALIASES` keeps working.
- An invalid spec does not reach the stage. The board says what the validator said, as `diagram_problems` does for Mermaid.
- Frames work as they do for any board: with no verb tags, the steps are spread over the answer's sentences (`auto_steps`). `[[+ s3]]`, `[[next]]`, `[[focus a]]` and `[[point s3]]` work as they do now.
- Talk's SKILL.md gains a row for each tool with a short example, and annotate's "when to use which" rules: a sequence for who-talks-to-whom over time, a flowchart for branching, Mermaid for a quick sketch, a table for facts.

### 6. Annotate

Annotate imports from `skills._shared.visuals`, passes no new arguments and gets no frames. Before the move, a fixture captures annotate's rendered output (`svg`, `key` and the flowchart `svgs`) for every spec in annotate's tests and its gallery. After the move, a test checks it is byte-identical.

## Testing

- Python: keyed output carries the keys in the table above and nothing else changes; the two face profiles measure differently; `sequence_model` and `flowchart_spec_model` build the right keys, order and `up`; the arrow rule shows an edge once both ends are shown, for Mermaid and for flowchart specs; `visuals.css` matches the marked block in `diagram.css`; annotate's golden output is unchanged; talk turns a spec into a `visual` board and refuses a bad one with the validator's message.
- Browser (stage): a sequence scene reveals actors then steps, and lights a step's arrow and key row together; a flowchart scene's arrows appear with their second end; Fit grows a small diagram; Back and Next move frames and stop the following; code, table and Mermaid scenes still step through the one engine; the stage loads its fonts and `visuals.css` with no network.
- Live: a talk call shows a sequence and a flowchart, stepping with the voice.

## Out of scope

- A free-HTML view. The `data-key` engine makes it a small step later.
- Frames in annotate.
- A shorthand text format for specs.
