"""Stage defects the side-panel study's testers hit (run bd1125b, batch S). Page logic under node, drawers in Python:
nothing is laid out here, so a measure is given to the page by hand (a canvas that makes a character 14 px wide, a
board 300 px wide) and the page's own arithmetic is read back."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_r4_lanes import _scene

STATIC = Path(__file__).resolve().parents[1] / "static"


def node(src: str):
    got = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


def fit(call: str):
    return node('import { centreTarget, columnWidths } from %s; console.log(JSON.stringify(%s));' % (json.dumps((STATIC / "fit.js").as_uri()), call))


# -- QF-7: a table column is never narrower than its longest word ---------------------------------------------------

@needs_node
def test_a_column_under_its_floor_is_held_at_it_and_the_others_share_what_is_left():
    # shares 43 / 28.5 / 28.5 % of 300 px give the first 129 px, under its 156 px floor: it is held, the rest split 144
    assert fit("columnWidths([0.43, 0.285, 0.285], [156, 44, 44], 300)") == [156, 72, 72]


@needs_node
def test_holding_one_column_can_push_the_next_under_its_floor_too():
    # 150 / 90 / 60 of 300: the first is under 180 and held, 120 is left for 90:60, the second gets 72, under its 100
    assert fit("columnWidths([0.5, 0.3, 0.2], [180, 100, 20], 300)") == [180, 100, 20]


@needs_node
def test_floors_wider_than_the_table_are_the_widths_and_floors_that_fit_change_nothing():
    assert fit("columnWidths([0.5, 0.5], [200, 150], 300)") == [200, 150]
    assert fit("columnWidths([0.5, 0.25, 0.25], [10, 10, 10], 400)") == [200, 100, 100]
    assert fit("columnWidths([], [], 300)") == []


SHORT = {"type": "inline", "format": "table", "body": "| A | B | C |\n|---|---|---|\n| Concurrency | no | yes |\n| Migrations | one | ok |"}
# a canvas whose character is 14 px wide, and every element 300 px wide, as a browser would measure them
MEASURE = """
const canvas = document.createElement("canvas");
Object.getPrototypeOf(canvas).getContext = () => ({ font: "", measureText: (t) => ({ width: 14 * t.length }) });
const make = document.createElement.bind(document);
document.createElement = (name) => { const e = make(name); Object.defineProperty(e, "clientWidth", { get: () => 300, set() {}, configurable: true }); return e; };
"""


@needs_node
def test_the_page_sets_each_columns_width_in_px_with_its_floor_held(tmp_path):
    page = StagePage(tmp_path, before=MEASURE).show("t", SHORT, title="T").open()
    page.check("[...pane('t').querySelectorAll('col')].map((c) => c.style.width)")
    page.check("[...pane('t').querySelectorAll('col')].map((c) => c.style.getPropertyValue('--min'))")
    assert page.run() == [["156px", "72px", "72px"], ["156.0px", "44.0px", "44.0px"]]


# -- QF-12: no rect has a negative width on a board that is almost not there ----------------------------------------

SEQ = {"title": "T", "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
       "groups": [{"id": "g", "kind": "alt", "branches": ["fast", "slow"]}],
       "steps": [{"id": "s1", "from": "a", "to": "c", "arrow": "band", "label": "everything below"},
                 {"id": "s2", "from": "b", "to": "b", "arrow": "self", "group": "g", "branch": 0, "label": "works"},
                 {"id": "s3", "from": "b", "to": "b", "arrow": "self", "group": "g", "branch": 1, "label": "waits"}]}


@needs_node
def test_a_lanes_board_measured_a_few_pixels_wide_draws_no_rect_of_negative_width(tmp_path):
    built = _scene(SEQ, [["+ step s1"], ["+ step s2"], ["+ step s3"]])
    page = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    for w in (8, 16, 24):
        page.js("pane('seq').querySelector('.visual.lanes').clientWidth = %d;" % w)
        page.send({"type": "stage:frame", "view": "seq", "n": built["rest"]})
        page.check("[%d, [...pane('seq').querySelectorAll('rect')].map((r) => +r.getAttribute('width')).filter((x) => x < 0)]" % w)
    assert page.run() == [[8, []], [16, []], [24, []]]


# -- QF-14: a slide's title is never left half cut by the pane's edge -----------------------------------------------

@needs_node
def test_the_pane_never_stops_with_a_slides_title_half_hidden():
    pane = "{ top: 0, height: 500 }"
    # what is said is at 600-680, the title ends at 60: centring stops at 390, clear of the title
    assert fit("centreTarget({ top: 600, bottom: 680, box: %s, view: 500, scroll: 0, lead: 60 })" % pane) == 390
    # what is said is near the top: centring would go above the content, the pane stays at 0
    assert fit("centreTarget({ top: 40, bottom: 120, box: %s, view: 500, scroll: 0, lead: 60 })" % pane) == 0
    # centring would stop at 40, in the middle of the title (it ends at 60): what is said fits under it, so the title shows whole
    assert fit("centreTarget({ top: 260, bottom: 280, box: %s, view: 500, scroll: 20, lead: 60 })" % pane) == 0
    # the same, but what is said is taller than the pane: it moves past the title, never halfway through it
    assert fit("centreTarget({ top: 50, bottom: 700, box: %s, view: 500, scroll: 0, lead: 60 })" % pane) == 60
    # no title (a board that is not a slide): the move is the old one
    assert fit("centreTarget({ top: 260, bottom: 280, box: %s, view: 500, scroll: 20 })" % pane) == 40


# -- QF-9: a board of Greek words is marked lang="el", so a capital loses its tonos ----------------------------------

GREEK_TABLE = {"type": "inline", "format": "table", "body": "| Στάδιο | Απόσταση |\n|---|---|\n| Τύμπανο | 15 χλμ. |"}
# the stylesheet capitalises a table head (text-transform): a head is read as capitals here, and every word measured is kept
HEADS = """
const canvas = document.createElement("canvas");
window.__measured = [];
Object.getPrototypeOf(canvas).getContext = () => ({ font: "", measureText: (t) => { window.__measured.push(t); return { width: 10 * t.length }; } });
const make = document.createElement.bind(document);
document.createElement = (name) => { const e = make(name); Object.defineProperty(e, "clientWidth", { get: () => 500, set() {}, configurable: true }); return e; };
const computed = globalThis.getComputedStyle;
globalThis.getComputedStyle = (el) => { const cs = computed(el); return el.localName === "th" ? new Proxy(cs, { get: (t, p) => (p === "textTransform" ? "uppercase" : t[p]) }) : cs; };
"""


@needs_node
def test_a_pane_of_greek_words_is_lang_el_and_an_english_one_has_no_lang(tmp_path):
    page = StagePage(tmp_path).show("gr", GREEK_TABLE, title="Αποστάσεις").open()
    page.check("pane('gr').getAttribute('lang')")
    page.js("document.querySelector('button[role=tab]')")
    page.show("en", SHORT, title="T").check("pane('en').getAttribute('lang')")
    assert page.run() == ["el", None]


@needs_node
def test_a_greek_head_is_measured_as_the_browser_sets_it_without_its_tonos(tmp_path):
    # under lang="el" the browser capitalises Στάδιο as ΣΤΑΔΙΟ and Απόσταση as ΑΠΟΣΤΑΣΗ, not with an accent on a capital
    page = StagePage(tmp_path, before=HEADS).show("gr", GREEK_TABLE, title="T").open()
    page.check("[...new Set(window.__measured)].filter((t) => /^[Α-Ω]+$/.test(t)).sort()")
    page.check("[...new Set(window.__measured)].filter((t) => /[ΆΈΉΊΌΎΏ]/.test(t))")
    assert page.run() == [["ΑΠΟΣΤΑΣΗ", "ΣΤΑΔΙΟ"], []]


# -- QF-11: the step control names its buttons, and "All shown" is a button that starts the steps again -----------------

STEP = ("(() => { const p = pane('seq'), s = p.querySelector('.vstep'); return [s.tagName, s.textContent, s.title, "
        "p.querySelector('.stepback').getAttribute('aria-label'), p.querySelector('.stepback').title, "
        "p.querySelector('.stepnext').getAttribute('aria-label'), p.querySelector('.stepnext').title, p.querySelector('.stepnext').disabled]; })()")


@needs_node
def test_all_shown_is_a_button_that_starts_again_and_the_chevrons_have_names(tmp_path):
    built = _scene(SEQ, [["+ step s1"], ["+ step s2"], ["+ step s3"]])
    page = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    page.send({"type": "stage:frame", "view": "seq", "n": built["rest"]}).check(STEP)
    page.js("pane('seq').querySelector('.vstep').click();").check(STEP)
    page.js("pane('seq').querySelector('.vstep').click();").check("pane('seq').querySelector('.vstep').textContent")
    rest, again, next_ = page.run()
    assert rest == ["BUTTON", "All shown", "All shown. Start the steps again", "Previous step", "Previous step", "Next step", "Next step", True]
    assert again == ["BUTTON", "3 steps", "3 steps. Next step", "Previous step", "Previous step", "Next step", "Next step", False]
    assert next_ == "Step 1 of 3"


# -- QF-13: code is wrapped unless the reader turned it off ---------------------------------------------------------

CODE = {"type": "inline", "format": "code", "path": "a.py", "start": 1, "highlight": None, "lang": "python", "lines": ["x = 1 + 2 + 3" * 20]}


@needs_node
def test_a_code_board_on_a_wide_screen_wraps_its_long_lines_until_the_reader_says_not(tmp_path):
    page = StagePage(tmp_path, width=1300).show("c", CODE, title="C").open()
    page.check("[pane('c').querySelector('.code').classList.contains('wrap'), pane('c').querySelector('.wrapbtn') && pane('c').querySelector('.wrapbtn').getAttribute('aria-pressed')]")
    page.js("localStorage.setItem('stage.wrap', '0');").show("c2", CODE, title="C2")
    page.check("pane('c2').querySelector('.code').classList.contains('wrap')")
    assert page.run() == [[True, "true"], False]


# -- QF-6, T11: the board list is above the sticky lanes header; a TV's zoom is taken off the window's height ----------

def rule(css: str, selector: str) -> str:
    return re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", css).group(1)


def test_the_board_list_stacks_above_the_lanes_header_it_opens_over():
    css = (STATIC / "stage.css").read_text()
    z = lambda sel: int(re.search(r"z-index:(\d+)", rule(css, sel)).group(1))
    assert (z(".tabbar"), z(".ln-head")) == (10, 6)


@needs_node
def test_a_zoomed_stage_is_as_tall_as_the_window_and_not_zoom_times_taller(tmp_path):
    css = (STATIC / "stage.css").read_text()
    assert "height:calc(100dvh / var(--z,1))" in rule(css, ".stage")
    page = StagePage(tmp_path).show("t", SHORT, title="T").open()
    page.send({"type": "stage:zoom", "zoom": 1.35}).check("[document.documentElement.style.zoom, document.documentElement.style.getPropertyValue('--z')]")
    page.send({"type": "stage:zoom", "zoom": 1}).check("[document.documentElement.style.zoom, document.documentElement.style.getPropertyValue('--z')]")
    assert page.run() == [["1.35", "1.35"], ["", "1"]]


# -- QF-14: at rest a slide shows from its title, whatever the last part said had scrolled to ------------------------

SLIDE = ('<div class="slide"><h1 class="title">Four workers</h1><div class="stack">'
         '<div class="layer" data-part="a" data-name="the first">first</div><div class="layer" data-part="b" data-name="the second">second</div></div></div>')


@needs_node
def test_a_slide_at_rest_scrolls_back_to_its_top_and_while_a_part_is_said_it_does_not(tmp_path):
    from skills.stage import model as stage_model, scene
    src = stage_model.scene_source(SLIDE)
    built = scene.compile_scene(scene.parts_model(src["parts"]), [[scene.parse_verb("+ a")], [scene.parse_verb("+ b")]], "S")[0]
    page = StagePage(tmp_path).show("sl", src, title="S", extra={"scene": built, "kind": "scene"}).open()
    page.js("""const real = globalThis.getComputedStyle;
      globalThis.getComputedStyle = (el) => (el.classList && el.classList.contains('pbody') ? { overflowY: 'auto', getPropertyValue: () => '' } : real(el));
      const body = pane('sl').querySelector('.pbody'); window.__tops = []; body.scrollTop = 500; body.scrollTo = (o) => window.__tops.push(o.top);""")
    page.send({"type": "stage:frame", "view": "sl", "n": 1}).check("window.__tops.length")
    page.send({"type": "stage:frame", "view": "sl", "n": built["rest"]}).check("window.__tops")
    assert page.run() == [0, [0]]
