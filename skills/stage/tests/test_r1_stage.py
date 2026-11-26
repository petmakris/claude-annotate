"""Round 1 of the bulldozer on the talk side panel, the stage's share (run bd1125b, batch stage): rest frames, popups,
table rows, the table at rest on a wide screen, the arrows read to a screen reader, focus after a click. Page logic under
node (stage_page.py): nothing is laid out, so a measure is given to the page by hand where one matters."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from skills.stage import scene
from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_scene import TIMELINE
from skills.stage.tests.test_stage_page import (CLICK, FADE, RELEASE, SPOP, TERM_HTML, THREE_PATHS, TIMELINE_BODY, TURN, _release_scenes, _release_two_steps, _release_two_steps,
                                                _scene, _turn)

pytestmark = needs_node
STATIC = Path(__file__).resolve().parents[1] / "static"
CSS = (STATIC / "stage.css").read_text()


# -- S-listener-6: a board an answer with no board of its own leaves in front is shown whole ----------------------------

def test_an_answer_with_no_board_of_its_own_leaves_the_board_in_front_whole_not_half_stepped(tmp_path):
    one = _release_two_steps()
    page = StagePage(tmp_path, width=1400).show("rp", visual("sequence", RELEASE), title="Release path",
                                                extra={"scene": one, "scenes": {"1": one}, "answer": 1}).open()
    page.send({"type": "stage:answer", "n": 1})
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 1}, "keys": 0, "answer": 1}).check(FADE + "('rp')")
    # answer 2 has no board: the voice's picture names no board and no frame
    page.send({"type": "stage:answer", "n": 2})
    page.send({"type": "stage:state", "front": None, "frames": {}, "keys": 0, "answer": 2}).check(FADE + "('rp')")
    # a board the reader took in hand stays on the step it is on
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 1}, "keys": 0, "answer": 1})
    page.js("pane('rp').querySelector('.stepback').click();")
    page.send({"type": "stage:answer", "n": 3, "follow": False})
    page.send({"type": "stage:state", "front": None, "frames": {}, "keys": 0, "answer": 3}).check(FADE + "('rp')")
    assert page.run() == [{"frame": 1, "step": "Step 1 of 2", "dim": True},
                          {"frame": 3, "step": "All shown", "dim": False},
                          {"frame": 0, "step": "2 steps", "dim": False}]


# -- r1-phone-4: a popup is of the board and the step it opened on -----------------------------------------------------

def test_a_step_popup_closes_on_another_frame_a_new_answer_and_a_board_change(tmp_path):
    built = _scene(scene.sequence_model(TURN), [[f"+ step s{i}"] for i in range(1, 8)], "A spoken turn")
    page = _turn(tmp_path, extra={"scene": built, "scenes": {"2": built}, "answer": 2})
    page = page.show("other", {"type": "inline", "format": "table", "body": "| a | b |\n|---|---|\n| 1 | 2 |"}, title="Other").open()
    page.send({"type": "stage:state", "front": "turn", "frames": {"turn": 3}, "keys": 0, "answer": 2})
    title = "(() => pane('turn').querySelector('.ln-pop')?.querySelector('h3').textContent ?? null)()"
    page.js(CLICK % "'.ln-row[data-step=\"s1\"]'").check(title)
    page.send({"type": "stage:frame", "view": "turn", "n": 3, "answer": 2}).check(title)      # the same frame again: it stays
    page.send({"type": "stage:frame", "view": "turn", "n": 4, "animate": True, "answer": 2}).check(title)
    page.js(CLICK % "'.ln-row[data-step=\"s1\"]'").check(title)
    page.send({"type": "stage:answer", "n": 3}).check(title)
    page.js(CLICK % "'.ln-row[data-step=\"s1\"]'").check(title)
    page.send({"type": "stage:front", "view": "other", "manual": False, "answer": 3})
    page.send({"type": "stage:front", "view": "turn", "manual": False, "answer": 2}).check(title)
    assert page.run() == ["Sends the recording", "Sends the recording", None, "Sends the recording", None, "Sends the recording", None]


def test_the_popup_of_a_scene_part_has_a_close_button_and_goes_with_the_next_answer_and_the_next_frame(tmp_path):
    from skills.stage import model as stage_model
    src = stage_model.scene_source(TERM_HTML)
    built = _scene(scene.parts_model(src["parts"]), [["+ data"], ["+ pdf"]], "Ben")
    page = StagePage(tmp_path, embedded=True).show("ben", src, title="Ben", extra={
        "scene": built, "scenes": {"1": built}, "answer": 1, "kind": "scene"}).open()
    page.send({"type": "stage:state", "front": "ben", "frames": {"ben": 2}, "keys": 0, "answer": 1})
    pdf = "pane('ben').querySelector('[data-part=\"pdf\"]').click();"
    x = "[...document.querySelectorAll('.spop button.spop-x')].map((b) => [b.title, b.getAttribute('aria-label')])"
    page.js(pdf).check(SPOP).check(x)
    page.js("document.querySelector('.spop-x').click();").check(SPOP)
    page.js(pdf).send({"type": "stage:frame", "view": "ben", "n": 1, "answer": 1}).check(SPOP)
    page.js(pdf).send({"type": "stage:answer", "n": 2}).check(SPOP)
    out = page.run()
    assert [o[0] for o in out if isinstance(o[0], bool)] == [False, True, True, True]
    assert out[1] == [["Close", "Close"]]


def test_a_popup_closes_on_a_tap_of_the_close_button_of_a_lanes_step_and_it_is_44px_on_a_narrow_stage():
    narrow = CSS[CSS.rindex("@media (max-width:760px){\n"):]
    for rule in (".nb{width:44px;height:44px}", ".stepbar .btn{min-height:44px;width:44px}", ".vstep{height:44px;min-width:5.5em}",
                 ".pbtns .btn.sm{min-height:44px;min-width:44px;padding:3px 12px}", ".ln-x,.spop-x{width:44px;height:44px}",
                 ".pos{height:44px;min-width:44px}", ".follow{height:44px;border-radius:22px}"):
        assert rule in narrow, rule
    assert "@media (max-width:600px){.follow{width:44px;min-width:44px;margin-left:2px}}" in CSS


# -- r1-finder-4: a row of a table board can be asked about, and played from when an answer says it ---------------------

ROW = ("(() => { const p = document.querySelector('.spop'); return [p.hidden, p.querySelector('h3')?.textContent ?? '',"
       " p.querySelector('p')?.textContent ?? '', [...p.querySelectorAll('.sacts button')].map((b) => b.textContent)]; })()")


def test_a_tap_on_a_table_row_asks_about_it_and_plays_from_it_when_an_answer_says_it(tmp_path):
    built = _scene(TIMELINE, [["focus rows 1-2"], ["focus row 3"]], "Timeline, simply")
    page = StagePage(tmp_path, embedded=True).show("t", TIMELINE_BODY, title="Timeline", extra={
        "scene": built, "scenes": {"1": built}, "answer": 1}).open()
    page.send({"type": "stage:state", "front": "t", "frames": {"t": 2}, "keys": 0, "answer": 1})
    row = "pane('t').querySelectorAll('tbody tr')[%d].click();"
    press = "[...document.querySelectorAll('.spop button')].find((b) => b.textContent === '%s').click();"
    page.js(row % 2).check(ROW)                   # row 3, said by frame 2
    page.js(press % "Play from here").check(ROW)
    page.js(row % 4).check(ROW)                   # no frame says row 5
    page.js(press % "Ask about this").check(ROW)
    page.js(row % 1).js("pane('t').querySelector('table').click();").check(ROW)   # a tap beside the rows closes it
    assert page.run() == [[False, "21 Jan", "", ["Ask about this", "Play from here"]], [True, "21 Jan", "", ["Ask about this", "Play from here"]],
                          [False, "2 Feb", "Not said in the voice.", ["Ask about this"]], [True, "2 Feb", "Not said in the voice.", ["Ask about this"]],
                          [True, "13 Jan", "", ["Ask about this", "Play from here"]]]
    sent = [m for m in page.posted if m["type"] in ("stage:ask", "stage:play")]
    assert sent == [{"type": "stage:play", "view": "t", "answer": 1, "n": 2}, {"type": "stage:ask", "text": 'About "2 Feb": '}]


# -- r1-tv-2: a table at rest on a wide screen is drawn larger, within bounds ------------------------------------------

def fit(call: str):
    src = 'import { restScale } from %s; console.log(JSON.stringify(%s));' % (json.dumps((STATIC / "fit.js").as_uri()), call)
    got = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


def test_the_rest_scale_fills_seventy_percent_of_the_pane_up_to_1_6_and_never_below_1():
    assert fit("restScale({ natural: 600, pane: 1540 })") == 1.6                        # 1.79 wanted, capped
    assert fit("restScale({ natural: 600, pane: 1000 })") == 1.16                       # 700 / 600
    assert fit("restScale({ natural: 1200, pane: 1540 })") == 1                          # already wide: left alone
    assert fit("restScale({ natural: 600, pane: 700 })") == 1                            # a narrow pane never shrinks it
    assert fit("restScale({ natural: 600, pane: 1140, zoom: 1.35 })") == 1.18           # the TV zoom counts: 1.6 / 1.35
    assert fit("restScale({ natural: 600, height: 700, pane: 1540, paneHeight: 800 })") == 1.05   # never taller than the pane
    assert fit("restScale({ natural: 0, pane: 1540 })") == 1                             # nothing measured: nothing scaled


GRID = {"type": "inline", "format": "table", "body": "| A | B | C |\n|---|---|---|\n| Concurrency | no | yes |\n| Migrations | one | ok |"}
# a canvas whose character is 14 px wide, a table 600 px wide and 135 tall in a pane 1540 px wide and 1000 tall
WIDE = """
const canvas = document.createElement("canvas");
Object.getPrototypeOf(canvas).getContext = () => ({ font: "", measureText: (t) => ({ width: 14 * t.length }) });
const proto = Object.getPrototypeOf(canvas);
const size = (cls, w, h) => ({ get() { return this.classList.contains(cls) ? w : undefined; }, configurable: true });
for (const [prop, tests] of Object.entries({ offsetWidth: [["tablewrap", 600]], offsetHeight: [["tablewrap", 135]],
    clientWidth: [["tablewrap", 600], ["md", 1540]], clientHeight: [["pbody", 1000]] })) {
  Object.defineProperty(proto, prop, { get() { for (const [cls, v] of tests) if (this.classList.contains(cls)) return v; return 0; }, set() {}, configurable: true });
}
"""
UP = "pane('t').querySelector('.tablewrap').style.getPropertyValue('--up')"


def test_a_table_at_rest_is_drawn_larger_on_a_wide_screen_but_not_while_a_row_is_said_nor_on_a_phone(tmp_path):
    built = _scene(TIMELINE, [["focus rows 1-2"], ["focus row 3"]], "Timeline, simply")
    page = StagePage(tmp_path, width=1920, before=WIDE).show("t", GRID, title="T").open()
    page.check(UP)
    assert page.run() == ["1.6"]                       # no answer steps it: it is whole
    page = StagePage(tmp_path, width=1920, before=WIDE).show("t", TIMELINE_BODY, title="T", extra={
        "scene": built, "scenes": {"1": built}, "answer": 1}).open()
    page.send({"type": "stage:state", "front": "t", "frames": {"t": 1}, "keys": 0, "answer": 1}).check(UP).check("pane('t').querySelector('.md').classList.contains('g-rest')")
    page.send({"type": "stage:frame", "view": "t", "n": built["rest"], "answer": 1}).check(UP)
    page.send({"type": "stage:zoom", "zoom": 1.35}).check(UP)       # the zoom is counted, not stacked
    page.send({"type": "stage:frame", "view": "t", "n": 1, "answer": 1}).check(UP)
    assert page.run() == ["", False, "1.6", "1.18", ""]
    page = StagePage(tmp_path, width=390, before=WIDE).show("t", GRID, title="T").open()
    page.check(UP)
    assert page.run() == [""]


# -- r1-screenreader-2: the arrows of a flowchart are a list a screen reader reads -------------------------------------

READING = ("(n => { const l = pane(n).querySelector('ul.m-reading'); return l && { label: l.getAttribute('aria-label'),"
           " items: [...l.querySelectorAll('li')].map((e) => e.textContent), svg: pane(n).querySelector('svg.m-edges').getAttribute('aria-hidden') }; })")


def test_every_arrow_of_a_flowchart_is_read_with_its_ends_and_its_label_in_the_specs_order(tmp_path):
    ready = scene.mermaid_spec("graph TD; H[Hours after feeding] --> D{Did it double}; D -->|yes| R[Ready to bake]; D -->|no| W[Wait]")
    page = (StagePage(tmp_path).show("ready", visual("flowchart", ready), title="Is it ready")
            .show("paths", visual("flowchart", THREE_PATHS), title="Three paths").open())
    page.send({"type": "stage:front", "view": "ready", "manual": False}).check(READING + "('ready')")
    page.send({"type": "stage:front", "view": "paths", "manual": False}).check(READING + "('paths')")
    out = page.run()
    assert out[0] == {"label": "Arrows", "svg": "true", "items": [
        "Hours after feeding goes to Did it double", "Did it double, yes, goes to Ready to bake", "Did it double, no, goes to Wait"]}
    assert out[1]["items"] == ["Open a proposal goes to Catch every error", "Nightly batch goes to Broken guard first",
                               "Broken guard first goes to Put in error", "Share task, if broken, goes to Return latest state"]


# -- r1-tinkerer-2: a click with the pointer hands focus back so Space plays the answer --------------------------------

def test_after_a_pointer_click_on_a_step_board_or_follow_button_focus_goes_back_to_the_page_and_a_key_press_keeps_it(tmp_path):
    built = _scene(TIMELINE, [["focus rows 1-2"], ["focus row 3"]], "Timeline, simply")
    page = (StagePage(tmp_path, embedded=True).show("t", TIMELINE_BODY, title="T", extra={"scene": built, "scenes": {"1": built}, "answer": 1})
            .show("u", GRID, title="U").open())
    page.send({"type": "stage:state", "front": "t", "frames": {"t": 1}, "keys": 0, "answer": 1})
    at = "document.activeElement.className"
    pointer = "(sel) => { const b = document.querySelector(sel); b.focus(); b.dispatchEvent(new Event('click', { bubbles: true, detail: 1 })); }"
    key = "(sel) => { const b = document.querySelector(sel); b.focus(); b.dispatchEvent(new Event('click', { bubbles: true, detail: 0 })); }"
    page.js("(%s)('%s');" % (key, "section.pane:not([hidden]) .stepnext")).check(at)
    for sel in ("section.pane:not([hidden]) .stepnext", "section.pane:not([hidden]) .vstep", ".navbtn.next"):
        page.js("(%s)('%s');" % (pointer, sel)).check(at)
    page.js("document.querySelector('.follow').hidden = false; (%s)('.follow');" % pointer).check(at)
    out = page.run()
    assert out == ["btn sm stepnext", "", "", "", ""]


# -- S-tinkerer-6 (the stage's share): the button that puts the stage back on the voice says so ------------------------

def test_the_button_that_puts_the_stage_back_on_the_voice_says_back_to_the_voice_in_its_text_title_and_label(tmp_path):
    page = StagePage(tmp_path, embedded=True).show("u", GRID, title="U").open()
    page.check("(() => { const b = document.querySelector('.follow'); return [b.textContent, b.title, b.getAttribute('aria-label')]; })()")
    assert page.run() == [["Back to the voice", "Back to the voice", "Back to the voice"]]
