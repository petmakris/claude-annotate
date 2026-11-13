# Dataflow Field Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static field-view page with a full-page pan-and-zoom canvas whose layout engine spaces rows, routes bypasses round cards, gives each wire its own port and places labels without collisions, and give `render.py` a `--check` that screenshots and measures the result.

**Architecture:** `render.py` validates the spec and writes one self-contained HTML file: a page template (`canvas.html`) with the spec as inline JSON and the engine (`engine.js`) inlined. The engine computes all geometry in the browser from the spec alone, draws the SVG, runs the canvas, and publishes its geometry and measurements on `window.__layout` and `window.__layoutReport`. `check.py` opens the file in headless Chromium, writes a PNG and returns the report.

**Tech Stack:** Python 3 stdlib, vanilla JavaScript (no libraries), inline SVG, pytest + Playwright (Chromium) for browser tests.

**Spec:** `docs/superpowers/specs/2026-10-02-dataflow-field-canvas-design.md`

**Reference implementation:** the throwaway mockup's engine, `template.html` in this session's scratchpad (`…/scratchpad/proto/template.html`). Task 2 ports it; the mockup is not committed.

## Global Constraints

- The output HTML has no external references: no webfont, CDN, script src or remote image (`test_output_has_no_external_references`).
- Nothing measures the DOM for layout. Text widths use `MONO_11 = 6.65`, `MONO_13 = 7.90`, `SANS_95 = 5.30`, `SANS_9 = 5.10`.
- The same spec gives byte-identical HTML and an identical layout report.
- Rows keep declaration order unless their card sets `"rows": "follow"`.
- Grid: `HEADER_H = 46`, `ROW_H = 26`, `PAD_X = 13`, `MIN_GAP = 120`, `SLOT_VGAP = 40`, `PORT = 10`, `DGAP = 16`, `DPAD = 24`, `COMPACT = 0.8`, `STEEP = 1.0`, `STEEP_CAP = 480`, `PER_WIRE = 8`, 14 sweep pairs then one closing left-to-right pass.
- Test fixtures are made-up data only; the repository is public.
- Commit messages are a single line.

## Review Focus

- An edge that runs right-to-left or within one column: the engine assumes left-to-right. Expect a clear `ValueError` from `render()`, not a broken drawing. Pinned in Task 1.
- A card with one field, or a slot with no wires at all: the layout must not divide by zero or produce `NaN` coordinates. Pinned in Task 2 (`test_no_nan_in_layout` over a fixture with an isolated card).
- A label longer than any gap: the gap grows to hold it, as today. Pinned in Task 2 (`test_gap_holds_longest_label`).
- A spec with `muted` fields and no outgoing wire: the row still renders faded and is not counted as a port. Covered by `example-order.json` in Task 2.
- Opening the file with no `localStorage` (file:// in some browsers, private windows): nothing in the page may depend on storage. The engine uses none; Task 2's browser tests load via `set_content`, which has no storage origin.

---

### Task 1: Spec validation and the new knobs

**Files:**
- Modify: `skills/dataflow/fields/render.py` (add `validate(spec)` called first in `render`)
- Test: `skills/dataflow/tests/test_fields.py`

**Interfaces:**
- Produces: `render.validate(spec: dict) -> None`, raising `KeyError` for an edge naming an undeclared card or field, `ValueError` for an edge whose target slot is not greater than its source slot, an unknown `lane` (allowed: `"above"`, `"below"`), or an unknown card `rows` (allowed: `"real"`, `"follow"`).

- [ ] **Step 1: Write the failing tests**

```python
import pytest

def test_backward_edge_is_refused():
    spec = _example()
    spec["edges"].append({"from": "json.total", "to": "entity.id"})
    with pytest.raises(ValueError):
        render.render(spec)

def test_unknown_lane_is_refused():
    spec = _example()
    spec["edges"][0]["lane"] = "sideways"
    with pytest.raises(ValueError):
        render.render(spec)

def test_unknown_rows_mode_is_refused():
    spec = _example()
    spec["cards"][0]["rows"] = "alphabetical"
    with pytest.raises(ValueError):
        render.render(spec)
```

(Use card and field ids that exist in `example-order.json`; read the file for the last card's id.)

- [ ] **Step 2: Run, expect 3 failures**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/dataflow/tests/test_fields.py -n 0 -q`

- [ ] **Step 3: Implement `validate`**

```python
LANES = ("above", "below")
ROW_MODES = ("real", "follow")

def validate(spec: dict) -> None:
    cards = {c["id"]: c for c in spec["cards"]}
    slot = {c["id"]: c.get("slot", i) for i, c in enumerate(spec["cards"])}
    for c in spec["cards"]:
        if c.get("rows", "real") not in ROW_MODES:
            raise ValueError(f"card {c['id']!r}: rows must be one of {ROW_MODES}")
    for e in spec.get("edges", []):
        for end in (e["from"], e["to"]):
            cid, fid = end.split(".", 1)
            if cid not in cards:
                raise KeyError(f"no card {cid!r}")
            if not any(f["id"] == fid for f in cards[cid]["fields"]):
                raise KeyError(f"{cid} has no field {fid!r}")
        a, b = e["from"].split(".")[0], e["to"].split(".")[0]
        if slot[b] <= slot[a]:
            raise ValueError(f"edge {e['from']} → {e['to']} must run left to right")
        if "lane" in e and e["lane"] not in LANES:
            raise ValueError(f"edge {e['from']} → {e['to']}: lane must be one of {LANES}")
```

- [ ] **Step 4: Run the file, expect all pass** (same command).

- [ ] **Step 5: Commit** — `git commit -m "dataflow(fields): validate edges, lanes and row modes before rendering"`

---

### Task 2: The engine and the canvas page

**Files:**
- Create: `skills/dataflow/fields/engine.js`
- Create: `skills/dataflow/fields/canvas.html`
- Create: `skills/dataflow/fields/example-bypass.json`
- Modify: `skills/dataflow/fields/render.py` (replace `Card`, `layout`, `draw_*`, `TEMPLATE` with template inlining)
- Test: `skills/dataflow/tests/test_fields_browser.py`

**Interfaces:**
- Consumes: `render.validate`.
- Produces:
  - `render.render(spec) -> str`: `canvas.html` with `/*ENGINE*/` replaced by `engine.js` and `/*SPEC*/` by `json.dumps(spec, sort_keys=True)` with `</` escaped as `<\/`; `{{title}}` replaced by the escaped title.
  - In the page, after load: `window.__layout = { cards: {id: {x, y, w, h, rows: {fid: {y, h}}}}, wires: [{from, to, start: [x, y], end: [x, y], samples: [[x, y], …]}], labels: [{edge, x, y, w, h}] }` and `window.__layoutReport = { behind_card, label_overlaps, crossings, max_steepness, detour }` (integers for counts, floats rounded to 2 places).

`engine.js` is the mockup's engine with these parts kept and everything else removed:
- kept: constants, `layoutTidy` (renamed `layout`), `place`/`pav` sweeps, port `spread`, gap widths, curved routes with bypass `L` segments, label placement, `draw` (cards, rows with gap shading, wires, labels), camera (`apply`, `zoomAt`, `animateTo`, `fitRect`, `fit`, `fitSel`), input (wheel, drag, dblclick, keys, minimap), hover and click tracing, title chip, About panel, legend.
- removed: modes 2 and 3, threads, ask panel, toast, the fold (`t`, `foldTo`, badges, `nameK`), `layoutCurved`, the mode bar and its toggles, `localStorage`, `roundedPath`.
- changed: `rowOrder` is per card (`card.rows === "follow"`); a dummy's lane honours `edge.lane`; routes also record `samples` (24 points per curve, ends of each straight run) for the report.

The report, computed from `samples` after layout:
- `behind_card`: samples strictly inside (1px inset) any card that is not the wire's own source or target card.
- `label_overlaps`: label boxes intersecting a card box or another label box.
- `crossings`: pairs of wires sharing no endpoint field whose sample polylines intersect.
- `max_steepness`: max over wire hops of `|Δy| / gap width`.
- `detour`: max over bypassing wires of `polyline length − straight distance between ends`.

`example-bypass.json` (made-up): five slots — `form` (4 fields), `ctx` stacked under it (2 fields), `cmd` (3 fields, one fed by two form fields), `envelope` (`rows: "follow"`, 4 fields), `request` (5 fields), `lonely` in slot 4 with one field and no wires. At least three edges skip a column; one has `"lane": "below"`; one row receives three wires.

- [ ] **Step 1: Write the failing browser tests**

```python
# skills/dataflow/tests/test_fields_browser.py
import json
from pathlib import Path
import pytest
pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402
from skills.dataflow.fields import render

FIELDS = Path(__file__).resolve().parents[1] / "fields"
def _spec(name): return json.loads((FIELDS / name).read_text())

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(); yield b; b.close()

def _load(browser, spec):
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    pg.set_content(render.render(spec))
    pg.wait_for_function("() => window.__layoutReport")
    out = pg.evaluate("() => ({ L: window.__layout, R: window.__layoutReport })")
    pg.close(); return out["L"], out["R"]

@pytest.mark.parametrize("name", ["example-order.json", "example-bypass.json"])
def test_no_wire_behind_a_card(browser, name):
    _, rep = _load(browser, _spec(name))
    assert rep["behind_card"] == 0

@pytest.mark.parametrize("name", ["example-order.json", "example-bypass.json"])
def test_arrowheads_land_on_their_rows(browser, name):
    L, _ = _load(browser, _spec(name))
    for w in L["wires"]:
        cid, fid = w["to"].split(".", 1)
        row, card = L["cards"][cid]["rows"][fid], L["cards"][cid]
        assert abs(w["end"][0] - card["x"]) < 0.5
        assert row["y"] - row["h"] / 2 <= w["end"][1] <= row["y"] + row["h"] / 2

def test_wires_sharing_a_row_get_distinct_ordered_ports(browser):
    L, _ = _load(browser, _spec("example-bypass.json"))
    by_target = {}
    for w in L["wires"]: by_target.setdefault(w["to"], []).append(w)
    busy = [ws for ws in by_target.values() if len(ws) >= 3]
    assert busy
    for ws in busy:
        ends = [w["end"][1] for w in ws]
        assert len(set(round(y, 1) for y in ends)) == len(ends)
        starts = [w["start"][1] for w in sorted(ws, key=lambda w: w["end"][1])]
        assert starts == sorted(starts)

def test_real_order_holds_without_follow(browser):
    spec = _spec("example-bypass.json")
    L, _ = _load(browser, spec)
    for c in spec["cards"]:
        if c.get("rows") == "follow": continue
        ys = [L["cards"][c["id"]]["rows"][f["id"]]["y"] for f in c["fields"]]
        assert ys == sorted(ys)

def test_lane_override_goes_below(browser):
    spec = _spec("example-bypass.json")
    e = next(e for e in spec["edges"] if e.get("lane") == "below")
    L, _ = _load(browser, spec)
    w = next(w for w in L["wires"] if w["from"] == e["from"] and w["to"] == e["to"])
    skipped = [c for c in spec["cards"]
               if _slot(spec, e["from"]) < c.get("slot") < _slot(spec, e["to"])]
    lowest = max(L["cards"][c["id"]]["y"] + L["cards"][c["id"]]["h"] for c in skipped)
    xs = [L["cards"][c["id"]]["x"] + L["cards"][c["id"]]["w"] / 2 for c in skipped]
    for x in xs:
        y = min(w["samples"], key=lambda p: abs(p[0] - x))[1]
        assert y > lowest

def _slot(spec, end):
    return next(c["slot"] for c in spec["cards"] if c["id"] == end.split(".")[0])

def test_no_nan_in_layout(browser):
    L, rep = _load(browser, _spec("example-bypass.json"))
    assert "NaN" not in json.dumps(L) and "null" not in json.dumps(rep)

def test_gap_holds_longest_label(browser):
    spec = _spec("example-order.json")
    spec["edges"][0]["label"] = "x" * 90
    _, rep = _load(browser, spec)
    assert rep["label_overlaps"] == 0

def test_layout_is_deterministic(browser):
    spec = _spec("example-bypass.json")
    assert render.render(spec) == render.render(spec)
    assert _load(browser, spec) == _load(browser, spec)
```

- [ ] **Step 2: Run, expect failures** (`__layoutReport` never appears; `example-bypass.json` missing).

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/dataflow/tests/test_fields_browser.py -n 0 -q`

- [ ] **Step 3: Write `example-bypass.json`, `canvas.html`, `engine.js`, and rewrite `render.render` as specified above.** `canvas.html` carries the mockup's CSS minus the mode bar, ask panel, toast, pins and acts; its body is the stage SVG, title chip, About panel, legend strip, help line and navigator, with `<script type="application/json" id="spec">/*SPEC*/</script>` and `<script>/*ENGINE*/</script>`.

- [ ] **Step 4: Run the browser file and `test_fields.py`; all pass.**

- [ ] **Step 5: Watch one fail.** Temporarily make every bypass waypoint take the mean of its two ends' heights (no lane), re-run `test_no_wire_behind_a_card[example-bypass.json]`, confirm it fails, revert, confirm it passes.

- [ ] **Step 6: Commit** — `git commit -m "dataflow(fields): full-page canvas with spaced rows, bypass lanes, ports and placed labels"`

---

### Task 3: `render.py --check`

**Files:**
- Create: `skills/dataflow/fields/check.py`
- Modify: `skills/dataflow/fields/render.py` (`main`)
- Test: `skills/dataflow/tests/test_fields_browser.py`

**Interfaces:**
- Consumes: the page's `window.__layoutReport` and `window.__layout`.
- Produces: `check.run(html_path: Path) -> dict` that writes `html_path.with_suffix(".png")` and returns the report; CLI `render.py SPEC [--check OUT.html]`. With `--check`, writes OUT.html, runs the check, prints one `name: value` line per measure, exits 0 when `behind_card` and `label_overlaps` are both 0, 1 when either is not, 2 when Playwright is not importable (printing `check needs playwright: pip install playwright`).

The screenshot: a Chromium page at device scale factor 2, viewport width 1800 and height `ceil(1800 * drawing_h / drawing_w) + 160` (from `__layout` bounds), loaded via `file://`, the camera fitted (`F` key), the chrome hidden by adding `class="shot"` to `<body>` (CSS hides `.float`, `#help`), then `page.screenshot(path=…)`.

- [ ] **Step 1: Write the failing test**

```python
import subprocess, sys

def test_check_writes_png_and_reports(tmp_path):
    spec = tmp_path / "s.json"
    spec.write_text((FIELDS / "example-bypass.json").read_text())
    out = tmp_path / "s.html"
    r = subprocess.run([sys.executable, str(FIELDS / "render.py"), str(spec), "--check", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists() and out.with_suffix(".png").stat().st_size > 10_000
    for name in ("behind_card", "label_overlaps", "crossings", "max_steepness", "detour"):
        assert f"{name}:" in r.stdout
```

- [ ] **Step 2: Run, expect failure** (unknown argument).
- [ ] **Step 3: Implement `check.py` and the `main` change.**
- [ ] **Step 4: Run all dataflow tests; all pass.**
- [ ] **Step 5: Commit** — `git commit -m "dataflow(fields): render --check screenshots the canvas and reports its layout measures"`

---

### Task 4: The skill step

**Files:**
- Modify: `skills/dataflow/SKILL.md` (Field mode: steps, spec format, failure modes)
- Test: `skills/dataflow/tests/test_skill_doc.py`

- [ ] **Step 1: Write the failing test**

```python
def test_field_mode_requires_the_checked_render():
    text = SKILL.read_text()
    field = text[text.index("## Field mode"):]
    for must in ["--check", "behind_card", "label_overlaps", '"lane"', '"rows": "follow"', "three rounds"]:
        assert must in field, must
```

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Rewrite the Field mode section.** The steps become: read the real code; write the spec; render with `--check`; read the PNG and the report; fix any nonzero `behind_card` or `label_overlaps`, and any wire that visibly takes the long way round, through `lane`, `rows: "follow"` (only on a card whose order means nothing), card order or `gaps`; re-render, at most three rounds; hand over the file with what was adjusted. Document the page (canvas, About panel, hover tracing), the two new knobs, and the exit codes. Replace "Nothing is hand-placed…" with the new engine summary.
- [ ] **Step 4: Run the whole suite as CI does** — `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`.
- [ ] **Step 5: Commit** — `git commit -m "dataflow(fields): the skill checks every field diagram before handing it over"`
