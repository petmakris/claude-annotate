# Maps and lane sequences

Two diagrams, drawn the same way everywhere Claude draws: this repo's skills, the ai-building-blocks site, decks, pages and files. Claude writes a JSON spec; the library measures, lays out and draws the SVG; a small script plays it one step at a time.

| Diagram | Use it for | Spec has | Module |
|---|---|---|---|
| **map** | architecture: the parts of a system, where each caller comes in, where the rules live | `columns`, `boxes` | `skills/_shared/visuals/map_svg.py` |
| **lane sequence** | a request over time: who calls whom, with what, and what each check decides | `actors`, `steps` | `skills/_shared/visuals/sequence_svg.py` |

Both read three ways from one SVG: whole, for a page, a PNG or a slide; built up one step at a time; and followed one request step by step. The reveal is something the reader starts; at rest the diagram is complete.

## Commands

    python3 tools/vz.py svg SPEC.json -o out.svg          # the drawing alone
    python3 tools/vz.py html A.json B.json -o page.html   # one self-contained page with the player
    python3 tools/vz.py fragment SPEC.json                # the player, for a page that loads vz.css and vz-reveal.js
    uv run tools/vz_check.py check out.svg                # Chromium: every fault, in every frame, light and dark PNGs
    uv run tools/vz_check.py frames out.svg --out DIR --mode build|route   # one PNG per step, for slides

A drawing is done when `vz_check.py check` reports 0 faults and its light and dark PNGs look right.

## Rules for every diagram

- **The title is the claim**, a sentence with a verb, inside the drawing (`title`). It works alone on a slide.
- **Every word carries a fact**: a real name, a number, a consequence. A line that only restates the box name goes.
- **Real values only.** A made-up example is labelled "example".
- **Four colours, each with one meaning.** `blue` the AI or model path, `red` the central mechanism or the risky part, `green` where a rule holds or what passes, `amber` a warning, a cost or a workaround. No colour is ordinary.
- **`code` spans** in backticks become mono: names of functions, fields, routes.
- **Arrows point the way the call goes.** A dependency arrow points from the module that provides the code to the module that uses it, and the legend says so.

## Map spec

    {
      "title": "Three kinds of caller, one set of rules: every path ends in the same services",
      "subtitle": "optional",
      "columns": ["Who asks", "Entry point", "The tool layer", "The services"],
      "boxes": [
        {"id": "chat", "col": 0, "row": 1, "tone": "blue", "name": "A person in the app's chat",
         "lines": ["\"I paid the electricity bill\""], "b": 1, "r": 1},
        {"id": "ask", "col": 1, "row": 1, "tone": "blue", "name": "Ask Billpod", "b": 2, "r": 1,
         "lines": ["ctx: person, household, all scopes", {"text": "a card first for 31 tools", "tone": "blue", "r": 2}],
         "children": [{"id": "gemini", "tone": "blue", "name": "Gemini", "lines": ["picks `mark_paid` of 46 tools"], "r": 2}]},
        {"id": "services", "col": 3, "row": 1, "rows": 2, "tone": "green", "name": "Billpod services", "b": 4, "r": 4,
         "lines": ["the rules live here", {"text": "`bills.pay`", "gap": true}]}
      ],
      "zones": [{"label": "defined once, shared by both AI entry points", "tone": "red", "boxes": ["runtool", "tools"]}],
      "arrows": [
        {"from": "chat", "to": "ask", "tone": "blue", "b": 2},
        {"from": "rest", "to": "services", "label": "calls the services directly", "path": "hv", "b": 4},
        {"layer": "route", "from": "ask", "to": "runtool", "tone": "blue", "n": 3, "r": 3, "mono": true,
         "label": "runTool(mark_paid, args, ctx)"}
      ],
      "legend": [{"label": "calls"}, {"tone": "blue", "label": "an AI call"}, {"tone": "amber", "dash": true, "label": "a rule copied by hand"}],
      "captions": {"build": [{"title": "Who asks", "text": "…"}], "route": [{"title": "…", "text": "…"}]}
    }

- **Boxes** sit on a grid: `col`, `row`, and `cols` / `rows` to span. Boxes in a column share its width; a box is as tall as its lines unless it spans rows or says `"fill": true`. `children` stack inside a box under its lines. A line is text, or `{text, tone, mono, gap, b, r}`; `gap` adds space above it.
- **Zones** draw a dashed frame round boxes, with a label that wraps.
- **Arrows** route themselves at right angles round other boxes. `path` forces a shape (`straight`, `hv`, `vh`, `hvh`); `offset` moves one sideways in px; `points` gives the corners outright. Two arrows leaving or reaching the same point are spread apart. A label finds a spot beside its arrow clear of every box, label and line; when there is none, the gap widens.
- **Build** (`b` on any box, line, zone or arrow): the step at which the part appears when the map is built up. A child or a line takes its box's step unless it has its own.
- **Route** (`r`, and `"layer": "route"` arrows with a badge number `n`): the step at which a part joins the request's path. Route arrows show only while following the request; structure arrows (`layer` base) show only otherwise; parts the route never touches are dimmed.
- **Captions** for each mode, one `{title, text}` per step, show under the diagram while it plays.

## Lane sequence spec

The sequence spec of `kind: "sequence"` (`skills/annotate/references/block-kinds/sequence.md`), read as it is, plus:

- `role` on an actor: a second line in its head (`"one runner"`, `"the app's chat"`).
- `tone` takes the four colours above; the older tones still work (`edge` and `service` are blue, `internal` amber, `hot` red, `good` green).
- `label` and `sub` sit in a chip on the arrow; `sub` is mono. An `event` is a dashed reply with its words under it. A `self` step is a chip beside its lane.
- `checks` on a step: `[{"label": "scopes", "ok": true}, {"label": "already paid", "ok": false}]`, drawn as ✓ / ✗ badges where the rule is applied.
- `n` on a step: its number in the walkthrough. Several arrows share a number; without any `n`, every arrow is numbered.
- `phases` become bands behind their rows.
- `outcome`: `{"tone", "title", "lines"}`, a box that closes the diagram.
- `captions`: one `{title, text}` per step number.

## In a page

Load `skills/_shared/static/vz.css` (the look, light and dark, every colour a `--vz-*` token) and `vz-reveal.js` (the player), and put each `vz.py fragment` where it goes. A page that sets its own colours overrides the `--vz-*` tokens on `.vz-player, svg.vz`.

## Safety

The SVG is built from a validated spec. A spec holds words, never markup: every text is escaped, ids are prefixed with a checked uid, and captions travel as JSON text. Read `docs/security/diagram-rendering.md` before giving a spec any way to carry markup.
