# Dataflow field view: canvas, spaced layout, and a checked render

Date: 2026-10-02. Status: written spec awaiting review.

The decisions below were made on a throwaway mockup outside the repository. The layout engine in it is the reference for this spec.

## 1. What this changes, and why

`/dataflow fields` draws which field of one object becomes which field of another. Today `fields/render.py` emits a static page: a header, a fixed-width SVG, a caption and a sources table. The user's verdict:

- The left-to-right path is the best part and stays.
- The page spends too much room on the header and the sources table.
- The arrows tangle. Three causes were found:
  - Rows are packed tight, so wires from far-apart rows converge steeply.
  - Wires that skip a column cut behind the card in between.
  - Several wires meeting one row all land on the same pixel.

Success looks like this:

- The diagram fills the page and can be panned and zoomed like a design canvas.
- No wire passes behind a card.
- Each wire that meets a busy row has its own visible port.
- Hovering a field lights its whole route and dims everything else.
- Before handing a diagram over, Claude looks at the rendered result and fixes what it sees.

## 2. Decisions

> Decision B (spaced rows) is reversed by `2026-10-02-dataflow-field-layout-design.md`: cards are rigid records, and the sources move to meet them.

| # | Question | Decision |
|---|----------|----------|
| A | Arrow style | **Curves.** The right-angle "tidy" routing was tried and rejected as unhelpful. |
| B | Row spacing | **Spaced.** A row sits at the height of what feeds it. Cards may grow and show gaps. Chosen by the user. |
| C | Row order | **Real order by default.** Rows keep their declaration order. A card may opt in to `"rows": "follow"`, which reorders its rows to follow the wires. This fits argument lists and wire parameters, whose order means nothing. |
| D | Who decides the geometry | **The algorithm.** The engine is deterministic: the same spec always gives the same picture. Claude never places coordinates. It decides the content and a few structural knobs (§5), then checks the render (§6). Chosen by the user: "all parts". |
| E | Which canvas ships first | *Recommended:* **canvas only** (mockup option 1, plus hover). It covers pan, zoom, fit, the minimap, the About panel and hover-to-trace. "Open in editor" and "ask Claude" (option 2) need the webcompanion daemon and come later. Folding to classes (option 3) comes after that. |
| F | Where the layout code lives | *Recommended:* **JavaScript, inlined into the page.** `render.py` validates the spec and writes one self-contained HTML file with the engine inside. A later live version on the webcompanion board can reuse the same engine unchanged. The page stays fully offline. |

## 3. The page

The page is a full-viewport canvas.

- **The drawing** is an SVG under a pan-and-zoom camera:
  - Drag or two-finger scroll pans. Pinch or ⌘-scroll zooms toward the pointer, from 12% to 400%.
  - Double-click zooms in.
  - `F` fits the whole diagram, or the lit path when a field is selected. `1` sets 100%, and `+` / `−` step the zoom.
  - The background is a dot grid that moves with the camera.
- **A title chip** sits top-left: the eyebrow and title, plus an **About** button.
  - About opens a panel holding the lede, the caption and the sources table.
  - The panel is closed by default. This is where the old header and sources section go.
- **The legend** is a strip at bottom-left.
- **The navigator** sits at bottom-right:
  - A minimap of the whole drawing, with the visible area outlined. Click or drag it to move.
  - Zoom out, the zoom percentage (click for 100%), zoom in, and Fit.
- **Tracing:**
  - Hovering a field lights everything connected to it, upstream and downstream, and dims the rest.
  - A click pins the trace. A click on the background or `Esc` clears it.
- **First paint** fits the diagram to the window.

## 4. The layout engine

> Replaced by `2026-10-02-dataflow-field-layout-design.md`, which derives columns, order and heights from the wires.

All geometry is computed. Nothing measures the DOM, so a thumbnail, a print and a cold load draw the same picture. Text widths use the advance-width constants `render.py` uses today.

### 4.1 Columns and bypasses

- A card's `slot` is its column. Cards sharing a slot stack in spec order.
- A wire that skips columns gets a **waypoint** in each column it crosses.
- A waypoint sits above or below that column's cards, never between them or behind them.
  - It goes **above** when the mean height of the wire's two ends is above the centre of the column's cards. Otherwise it goes **below**.
  - The spec can force the side with `"lane"` (§5).

### 4.2 Heights

Every row and waypoint gets a height through alternating sweeps:

1. **Pull toward neighbours.** Left to right, each item moves toward the mean height of what feeds it. Right to left, it moves toward the mean height of what it feeds.
   - A waypoint only follows its source, so a bypass holds its height and bends once, at its target.
2. **Keep the order.** An order-preserving least-squares fit (pool-adjacent-violators) restores the minimum spacing. The spacing covers row heights, card headers, the gap between stacked cards, and the clearance around waypoints.
3. **Keep cards compact.** Each row is also pulled toward its card neighbours (weight 0.8). A card only opens a gap where a wire gains more than the gap costs.
4. **Settle.** The engine runs 14 sweep pairs, then one closing left-to-right pass, so the last column agrees with what feeds it.

### 4.3 Rows and ports

- A row that carries several wires on one side grows 10px taller for each extra wire.
- Each wire gets its own **port** inside the row, 10px apart. Ports are ordered by the height of the wire's other end, so wires leaving one row never cross each other at the start.

### 4.4 Gaps and wires

- **Gap width** is the largest of:
  - the minimum (120px)
  - the longest label leaving that column, plus 46px
  - the tallest climb across the gap, plus 8px per wire it carries, capped at 480px
  - an explicit `gaps` override
- **Wires** are cubic curves from port to port, flat at both ends.
- **Bypasses** run straight past the cards of a skipped column, then curve again.
- Wires are drawn before cards, so a wire never strikes through a field name.

### 4.5 Labels

- A label tries four spots in order:
  1. above its wire's start
  2. below its wire's start
  3. above its arrowhead, right-aligned
  4. below its arrowhead, right-aligned
- It takes the first spot that overlaps no card and no label already placed. If every spot overlaps something, it takes the one with the least overlap.
- Labels keep the halo they have today, so a wire behind one is interrupted rather than striking through it.

## 5. The spec's new knobs

> `slot` and `gaps` no longer place anything: `2026-10-02-dataflow-field-layout-design.md` §3 makes them legacy keys that are validated, noted and dropped.

These are the structural choices left to Claude. All are optional, and a spec without them renders as described above.

```jsonc
{ "cards": [ { "id": "args", "rows": "follow", … } ],     // C: reorder rows to follow wires
  "edges": [ { "from": "…", "to": "…", "lane": "below" } ] // force a bypass over or under
}
```

The existing knobs stay:

- `slot` and the spec order of cards choose column and stacking.
- `gaps` widens a gap.
- Splitting one diagram into two is done by writing two specs.

## 6. The checked render

> The measures and targets are replaced by `2026-10-02-dataflow-field-layout-design.md` §6: five targets, and every measure recomputed from the published layout.

`render.py` gains a check, and the skill makes it a required step before handover.

```bash
python3 render.py spec.json > out.html            # as today
python3 render.py spec.json --check out.html      # also writes out.png and prints a report
```

`--check` opens the file in headless Chromium through Playwright. The engine exposes its own measurements on `window.__layoutReport`. The check writes a full-diagram screenshot at 2× and prints:

| Measure | Meaning | Target |
|---|---|---|
| `behind_card` | wire samples inside a card it does not end at | 0 |
| `label_overlaps` | label boxes overlapping a card or another label | 0 |
| `crossings` | pairs of wires that intersect | report only |
| `max_steepness` | the steepest wire's climb divided by its gap | report only |
| `detour` | the longest bypass's extra length over a straight run | report only |

The new skill step (in `SKILL.md`'s field mode):

1. Render with `--check`.
2. Read the PNG and the report.
3. Any nonzero target, or a wire that visibly takes the long way round, is fixed through the spec. The tools are a `lane`, `rows: "follow"` on a card whose order is meaningless, card order, or `gaps`.
4. Re-render, at most three rounds. Hand over the final file and say what was adjusted.

When Playwright is missing, `--check` says so and exits nonzero, and the skill hands over the unchecked file with that stated. The plain render never needs a browser.

## 7. Testing

The tests use the existing pytest + Playwright setup. Fixtures are made-up data only, because the repo is public:

- `example-order.json` (exists)
- a new `example-bypass.json` with column skips, a fan-out, a fan-in and a card in `follow` order

The tests:

- **Offline:** `test_output_has_no_external_references` keeps passing, with the engine inlined.
- **Validation:** the unknown-field `KeyError` test keeps passing, plus an unknown `lane` value is refused.
- **Arrowheads land on their rows** (browser): every wire's end point lies inside its target row's band.
- **No wire behind a card** (browser): `behind_card == 0` for both fixtures.
- **Ports:** wires sharing a row end at distinct heights, ordered by their other end.
- **Real order holds:** without `follow`, every card's rows appear in spec order.
- **Lane override:** forcing `lane: "above"` puts that bypass above the cards of the columns it skips.
- **Determinism:** two renders of the same spec are byte-identical, and the report is identical.
- **Check:** `--check` writes a PNG and a report with the five measures.

Each browser test is confirmed to fail first against a deliberately broken engine. For example, with waypoints placed at the mean height, `behind_card` goes nonzero.

## 8. Out of scope

- Option 2: open-in-editor and ask-Claude on a field, through webcompanion.
- Option 3: folding to classes when zoomed out.
- The class view (`/dataflow <feature>`). It keeps its board.
- Right-angle routing. It was tried and rejected (decision A).
