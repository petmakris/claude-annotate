"""Maps and lane sequences in annotate: `kind: "map"` and `kind: "sequence"`.

Both are drawn on the server by the shared library (visuals/map_svg.py,
sequence_svg.py) and stored as the player fragment (visuals/player.py). The
page loads vz.css and vz-reveal.js and boots the players; Share and the
Confluence PNG carry the whole drawing with no controls.
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from skills.annotate import blocks
from skills.annotate.confluence import body as cbody
from skills.annotate.confluence import images
from skills.annotate.render import render_block
from skills.annotate.tests.page_source import SCRIPT_JS

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SHARED_STATIC = REPO / "skills" / "_shared" / "static"
SHIM = REPO / "skills" / "_shared" / "tests" / "dom_shim.mjs"
GOLDEN = REPO / "skills" / "_shared" / "visuals" / "tests" / "golden.json.gz"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _seq(**extra) -> dict:
    return {
        "title": "The app asks the API, and the API checks the scope",
        "subtitle": "one request, start to end",
        "actors": [{"id": "app", "label": "App", "role": "the app's chat", "tone": "blue"},
                   {"id": "api", "label": "API", "tone": "green"}],
        "steps": [
            {"id": "s1", "from": "app", "to": "api", "arrow": "request",
             "label": "mark the bill paid", "sub": "POST /bills/7/pay",
             "checks": [{"label": "scopes", "ok": True}]},
            {"id": "s2", "from": "api", "to": "app", "arrow": "event", "label": "200 OK"},
        ],
        "captions": [{"title": "The app calls", "text": "with `bills.pay`"},
                     {"title": "The API answers", "text": "a <b>plain</b> 200"}],
        **extra,
    }


def _map(**extra) -> dict:
    return {
        "title": "Two callers, one set of rules",
        "columns": ["Who asks", "The services"],
        "boxes": [
            {"id": "chat", "col": 0, "row": 0, "tone": "blue", "name": "A person in the chat",
             "lines": ["asks in words"], "b": 1, "r": 1},
            {"id": "svc", "col": 1, "row": 0, "tone": "green", "name": "Billpod services",
             "lines": ["the rules live here", "`bills.pay`"], "b": 2, "r": 2},
        ],
        "arrows": [{"from": "chat", "to": "svc", "b": 2},
                   {"layer": "route", "from": "chat", "to": "svc", "n": 1, "r": 2,
                    "label": "calls"}],
        "captions": {"build": [{"title": "Who asks", "text": "a person"},
                               {"title": "Where the rules live", "text": "the services"}],
                     "route": [{"title": "Start", "text": ""}, {"title": "The call", "text": "`bills.pay`"}]},
        **extra,
    }


def _steps_json(stored: str) -> dict:
    m = re.search(r'<script type="application/json" class="vz-steps">(.*?)</script>', stored, re.S)
    assert m, stored[:200]
    return json.loads(m.group(1))


def _drawn_text(stored: str) -> str:
    svg = re.search(r"<svg class=\"vz\".*?</svg>", stored, re.S).group(0)
    return " ".join(re.findall(r">([^<]+)<", svg))


# ---- the stored body ------------------------------------------------------------------------------

def test_a_sequence_is_stored_as_the_lane_sequence_player():
    body = render_block({"id": "section-2", "kind": "sequence", "spec": _seq()})
    stored = body["svg"]
    assert stored.startswith('<div class="vz-player" data-vz-player>')
    assert 'data-vz="sequence"' in stored
    assert "key" not in body, "the old grid's key rides along with the new drawing"
    drawn = _drawn_text(stored)
    for words in ("App", "the app's chat", "mark the bill paid", "POST /bills/7/pay", "✓ scopes", "200 OK"):
        assert words.replace("'", "&#x27;") in drawn or words in drawn, words
    assert _steps_json(stored) == {"route": [
        {"title": "The app calls", "text": "with `bills.pay`"},
        {"title": "The API answers", "text": "a <b>plain</b> 200"}]}
    assert body["spec"] == _seq()


def test_the_heading_carries_the_title_and_the_drawing_does_not_repeat_it():
    stored = render_block({"id": "section-2", "kind": "sequence", "spec": _seq()})["svg"]
    drawn = _drawn_text(stored)
    assert "The app asks the API" not in drawn and "one request, start to end" not in drawn
    assert 'aria-label="The app asks the API, and the API checks the scope"' in stored


@pytest.mark.parametrize("kind", ["map", "sequence"])
def test_cutting_the_title_band_moves_nothing_in_the_drawing(kind):
    """A map's `points` are canvas coordinates laid out under the title band,
    so the page keeps the author's layout and starts the viewBox below the
    band instead of drawing the spec again without a title."""
    from skills._shared.visuals import map_svg, sequence_svg
    spec = _map(subtitle="where the rules live") if kind == "map" else _seq()
    lib = (map_svg if kind == "map" else sequence_svg).render(spec, "vz-section-5")
    stored = render_block({"id": "section-5", "kind": kind, "spec": spec})["svg"]
    drawn = re.search(r"<svg class=\"vz\".*?</svg>", stored, re.S).group(0)
    w, h = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', lib).groups())
    band = re.search(r'viewBox="0 ([\d.]+) ', drawn).group(1)
    assert 0 < float(band) < 120
    assert f'viewBox="0 {band} {w:g} {h - float(band):g}"' in drawn
    strip = lambda svg: re.sub(r'viewBox="[^"]*"|<text class="(ttl|sub)" [^>]*>.*?</text>', "", svg)
    assert strip(drawn) == strip(lib)


def test_a_drawing_with_no_title_is_stored_as_drawn():
    from skills._shared.visuals import sequence_svg
    spec = _seq()
    del spec["title"], spec["subtitle"]
    stored = render_block({"id": "section-5", "kind": "sequence", "spec": spec})["svg"]
    assert sequence_svg.render(spec, "vz-section-5") in stored


def test_a_map_block_is_known_and_stored_as_the_map_player(tmp_path):
    assert "map" in blocks.BLOCK_KINDS
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps({"blocks": [{"id": "section-1", "kind": "map", "spec": _map()}]}))
    doc = blocks.load(path)
    body = render_block(doc.blocks[0])
    assert body["kind"] == "map"
    assert 'data-vz="map"' in body["svg"]
    assert "Billpod services" in _drawn_text(body["svg"])
    steps = _steps_json(body["svg"])
    assert [c["title"] for c in steps["build"]] == ["Who asks", "Where the rules live"]
    assert [c["title"] for c in steps["route"]] == ["Start", "The call"]


def test_no_spec_text_reaches_the_page_as_markup():
    spec = _seq()
    spec["actors"][0]["label"] = "<img src=x onerror=alert(1)>"
    spec["steps"][0]["label"] = "</script><script>alert(2)</script>"
    spec["captions"] = [{"title": "</script><b>x</b>", "text": "<i>y</i>"}]
    stored = render_block({"id": "section-2", "kind": "sequence", "spec": spec})["svg"]
    assert "<img" not in stored and "<b>" not in stored and "<i>" not in stored
    # The one script element is the player's own JSON, closed once.
    assert stored.count("<script") == 1 and stored.count("</script>") == 1
    m = _map()
    m["boxes"][0]["name"] = "<svg onload=alert(3)>"
    stored = render_block({"id": "section-1", "kind": "map", "spec": m})["svg"]
    assert "<svg onload" not in stored


@pytest.mark.parametrize("kind,spec", [
    ("sequence", {"actors": [], "steps": []}),
    ("sequence", {"actors": [{"id": "a", "label": "A"}], "steps": [{"id": "s1", "from": "a", "to": "zz", "arrow": "request"}]}),
    ("map", {"columns": 5}),
    ("map", {"columns": ["a"], "boxes": [{"id": "x", "col": 9, "row": 0, "name": "X"}]}),
    ("map", "not a spec"),
])
def test_a_spec_that_fails_shows_the_error_pill_never_a_blank_part(kind, spec):
    body = render_block({"id": "section-4", "kind": kind, "spec": spec})
    assert "diagram render failed" in body["svg"]
    assert "vz-player" not in body["svg"]


def test_any_block_id_makes_a_valid_drawing_id():
    for bid in ("section-12", "9 lives", "b.1/2", "x" * 80):
        stored = render_block({"id": bid, "kind": "sequence", "spec": _seq()})["svg"]
        assert "diagram render failed" not in stored, bid
        assert re.search(r'marker id="vz-[A-Za-z0-9_-]+-', stored), bid


def test_two_parts_on_one_page_never_share_an_id():
    a = render_block({"id": "section-1", "kind": "map", "spec": _map()})["svg"]
    b = render_block({"id": "section-2", "kind": "map", "spec": _map()})["svg"]
    assert not set(re.findall(r' id="([^"]+)"', a)) & set(re.findall(r' id="([^"]+)"', b))


def _golden_sequence_specs() -> list[dict]:
    records = json.loads(gzip.decompress(GOLDEN.read_bytes()))
    return [r["args"][0] for r in records if r["fn"] == "sequence.render"]


@pytest.mark.parametrize("spec", _golden_sequence_specs())
def test_every_stored_sequence_spec_still_draws(spec):
    """golden.json.gz holds every sequence spec annotate's suite drew before the
    move to shared tools: the old menu's tones, bands, notes, phases. Each must
    draw in the new look, not fall back to the error pill."""
    stored = render_block({"id": "section-3", "kind": "sequence", "spec": spec})["svg"]
    assert "diagram render failed" not in stored
    assert 'data-vz="sequence"' in stored


# ---- the page ---------------------------------------------------------------------------------------

def _entry_list(name: str) -> list[str]:
    src = (STATIC / "entry.js").read_text()
    body = re.search(r"const %s = \[(.*?)\];" % name, src, re.S).group(1)
    body = "\n".join(line.split("//", 1)[0] for line in body.splitlines())
    return re.findall(r'"([^"]+)"', body)


def test_the_page_loads_the_look_and_the_player_in_order():
    css, js = _entry_list("CSS"), _entry_list("JS")
    assert "vz.css" in css and css.index("vz.css") < css.index("diagram.css"), \
        "diagram.css must come after vz.css to hold it to the page's theme"
    assert "vz-reveal.js" in js and js.index("vz-reveal.js") < js.index("script.js")
    for name in ("vz.css", "vz-reveal.js"):
        assert (STATIC / name).read_bytes() == (SHARED_STATIC / name).read_bytes()


def test_the_players_boot_after_every_render():
    src = SCRIPT_JS.read_text()
    assert 'document.addEventListener("annotate:rendered", bootPlayers);' in src
    assert "window.vzReveal.boot()" in src
    # Both paint sites go through paintVz, so a rewrite paints a new player.
    assert src.count("paintVz(content, blk);") == 2
    assert '"map"' in re.search(r"const FRAMED = \[(.*?)\];", src).group(1)


def _token_sets(css: str) -> list[dict]:
    """Every rule body that sets --vz-fg, as {token: value}."""
    out = []
    for body in re.findall(r"\{([^{}]*--vz-fg:[^{}]*)\}", css):
        out.append(dict(re.findall(r"(--vz-[\w-]+):\s*([^;}\s]+)", body)))
    return out


def test_the_page_theme_tokens_are_vz_css_s_own():
    vz = _token_sets((SHARED_STATIC / "vz.css").read_text())
    ours = _token_sets((STATIC / "diagram.css").read_text())
    light = {k: v for k, v in vz[0].items() if not k.endswith(("sans", "mono"))}
    assert len(ours) == 2
    assert ours[0] == light, "diagram.css's light tokens drifted from vz.css"
    assert ours[1] == vz[-1], "diagram.css's dark tokens drifted from vz.css"


def test_the_page_has_the_faces_the_drawings_were_measured_in():
    core = (STATIC / "core.css").read_text()
    for family, file in (("Inter", "Inter-Variable.woff2"), ("JetBrains Mono", "JetBrainsMono-Variable.woff2")):
        face = re.search(r"@font-face\s*\{[^}]*font-family:\s*'%s'[^}]*\}" % family, core)
        assert face and f"fonts/{file}" in face.group(0), family
        assert (STATIC / "fonts" / file).read_bytes() == (SHARED_STATIC / "fonts" / file).read_bytes()


EXPORT_RUN = """
import { readFileSync } from "node:fs";
import { install, document } from %(shim)s;
install();
document.body.innerHTML = %(body)s;
new Function(readFileSync(%(reveal)s, "utf8"))();
const root = document.querySelector("[data-vz-player]");
const before = { bar: !!root.querySelector(".vz-bar"), ready: root.dataset.vzReady };
root.vz.setMode("route");
root.vz.go(1);
const mid = { fut: root.querySelectorAll(".fut").length, now: root.querySelectorAll(".now").length };
new Function(readFileSync(%(export)s, "utf8"))();
const out = window.AnnotateExport.buildProse();
console.log(JSON.stringify({ before, mid, out }));
"""


@needs_node
def test_share_carries_the_whole_drawing_with_no_player(tmp_path):
    """A player stepped to step 1 hides later parts and lights the current
    ones. The exported file has no script to undo that, so it gets the
    drawing at rest, without the controls or the captions' JSON."""
    stored = render_block({"id": "section-2", "kind": "sequence", "spec": _seq()})["svg"]
    markup = ('<main class="prose"><section class="block" data-block-id="section-2" data-kind="sequence">'
              '<div class="block-content">%s</div></section></main>' % stored)
    script = tmp_path / "run.mjs"
    script.write_text(EXPORT_RUN % {
        "shim": json.dumps(SHIM.as_uri()), "body": json.dumps(markup),
        "reveal": json.dumps(str(STATIC / "vz-reveal.js")), "export": json.dumps(str(STATIC / "export.js"))})
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["before"] == {"bar": True, "ready": "1"}, "the player never set up"
    assert got["mid"]["fut"] > 0 and got["mid"]["now"] > 0, "stepping changed nothing to undo"
    out = got["out"]
    for gone in ("vz-bar", "vz-cap", "vz-steps", "data-vz-ready", "data-mk", " fut", " now", "mode-route"):
        assert gone not in out, gone
    assert 'class="vz"' in out and "mark the bill paid" in out
    assert 'marker-end="url(#vz-section-2-' in out and "-on)" not in out


def test_share_keeps_the_mono_face_a_drawing_was_measured_in():
    src = (STATIC / "export.js").read_text()
    assert 'const VZ_SELECTOR = "svg.vz";' in src
    assert 'document.querySelector(VZ_SELECTOR) ? "JetBrains Mono" : null' in src


def test_a_drawing_keeps_its_own_size_and_fit_is_css_alone():
    """Old pictures were drawn at their real size and scrolled; a drawing
    scaled to the column put 13px words at 7px. Fit width in maximize lets the
    drawing take the width given, with no measured height that would cut off
    the player's controls."""
    js = SCRIPT_JS.read_text()
    assert 'svg.style.setProperty("--vz-w", box.width + "px")' in js
    css = (STATIC / "diagram.css").read_text()
    assert "main.prose .vz-stage svg.vz { width: var(--vz-w, 100%); max-width: none; }" in css
    assert "main.prose section.block.is-fit .vz-stage svg.vz { width: 100%; min-width: 0; }" in css
    mx = (STATIC / "maximize.js").read_text()
    fit = mx[mx.index("function applyFit("):]
    assert fit.index('section.querySelector(".vz-player")') < fit.index("const scale =")


# ---- Confluence -------------------------------------------------------------------------------------

def test_the_png_page_draws_with_vz_css_and_the_stage_faces():
    stored = render_block({"id": "section-1", "kind": "map", "spec": _map()})["svg"]
    html = images.standalone_html(stored)
    assert "svg.vz .bx.blue" in html, "vz.css is missing, so the map draws unstyled"
    assert html.index("svg.vz .bx.blue") < html.index('body:not([data-page-theme="dark"])) .vz-player'), \
        "diagram.css's light tokens must come after vz.css"
    for family in ("Inter", "JetBrains Mono"):
        assert "font-family:'%s';src:url('data:font/woff2;base64," % family in html, family
    # No player script runs in the PNG page, so it has no controls.
    assert not re.findall(r"<script(?![^>]*application/json)", html), "a script would add controls"
    w, h = re.search(r'viewBox="0 [\d.]+ (\d+) (\d+)"', stored).groups()
    assert "<div style='width:%spx;height:%spx'>" % (w, h) in html


def test_confluence_publishes_a_map_as_a_picture_with_its_steps_written_out():
    blk = render_block({"id": "section-1", "kind": "map", "spec": _map(subtitle="where the rules live")})
    assert cbody.has_picture(blk)
    w, h = re.search(r'viewBox="0 [\d.]+ (\d+) (\d+)"', blk["svg"]).groups()
    assert cbody.svg_size(blk["svg"]) == (int(w), int(h))
    html = cbody.render_block(blk, [])
    assert html.startswith("<h2>Two callers, one set of rules</h2><p>where the rules live</p><figure")
    assert "<p>Built up step by step:</p><ol><li><p><strong>Who asks</strong> a person</p></li>" in html
    assert "<li><p><strong>The call</strong> <code>bills.pay</code></p></li>" in html


def test_confluence_drops_the_key_table_for_a_lane_sequence():
    blk = render_block({"id": "section-2", "kind": "sequence", "spec": _seq()})
    html = cbody.render_block(blk, [])
    assert "<table>" not in html, "the picture carries the labels; the key would repeat them"
    assert "<ol><li><p><strong>The app calls</strong> with <code>bills.pay</code></p></li>" in html
    assert "a &lt;b&gt;plain&lt;/b&gt; 200" in html


def test_confluence_keeps_the_key_table_for_a_grid_stored_before():
    old = {"id": "section-2", "kind": "sequence", "spec": _seq(),
           "svg": '<svg class="annotate-seq" width="400" height="200"></svg>'}
    assert "<table>" in cbody.render_block(old, [])
