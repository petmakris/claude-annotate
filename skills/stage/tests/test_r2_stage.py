"""Round 2 of the bulldozer on the side panel, batch stage: the flowchart's reading list is out of sight, the drawn boards
(map, graph, bars) carry one for a screen reader, a sequence step names who sends to whom, the lanes read at a distance,
a board with one step has no step control and a long table counts its rows out of sight, Back to the voice fronts the board
the voice last showed, and the stage's own words follow the page's language. Page logic under node (nothing is measured
there), the stylesheet as text, and the server's reading lists on the real render."""
from __future__ import annotations

import json
import re
from pathlib import Path

from skills.stage import model, scene
from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_compare import SPEC as COMPARED, step
from skills.stage.tests.test_r1_stage import GRID
from skills.stage.tests.test_stage_page import THREE_PATHS, TURN, _scene

STATIC = Path(__file__).resolve().parents[1] / "static"
CSS = (STATIC / "stage.css").read_text()


def rule(selector: str) -> dict:
    """The declarations of the stylesheet's rule that starts with `selector`, as a dict."""
    body = re.search(r"(?:^|[}/])\s*" + re.escape(selector) + r"\{([^}]*)\}", CSS).group(1)
    return {k.strip(): v.strip() for k, v in (d.split(":", 1) for d in body.split(";") if d.strip())}


# -- r2-listener-1: the flowchart's arrow list is read by a screen reader and never seen ------------------------------

HIDDEN = {"position": "absolute", "width": "1px", "height": "1px", "margin": "-1px", "padding": "0", "overflow": "hidden",
          "clip-path": "inset(50%)", "white-space": "nowrap", "list-style": "none"}


def test_the_reading_lists_are_visually_hidden_by_a_rule_that_keeps_them_in_the_accessibility_tree():
    assert rule(".m-reading,.vz-reading") == HIDDEN
    assert "display:none" not in CSS.split(".m-reading,.vz-reading{")[1].split("}")[0]


@needs_node
def test_the_flowchart_keeps_its_arrow_list_in_the_page_with_every_arrow_for_a_screen_reader(tmp_path):
    page = StagePage(tmp_path).show("paths", visual("flowchart", THREE_PATHS), title="Three paths").open()
    page.check("(() => { const l = pane('paths').querySelector('ul.m-reading'); return [!!l, l.hidden, l.querySelectorAll('li').length, l.getAttribute('aria-label')]; })()")
    assert page.run() == [[True, False, 4, "Arrows"]]


# -- r2-screenreader-1: a drawn board has a list of its connections -----------------------------------------------------

MAP = {"title": "Why a middle bank", "columns": ["Payer", "Middle"],
       "boxes": [{"id": "x", "name": "Page\nA", "col": 0, "row": 0}, {"id": "y", "name": "`Store`", "col": 1, "row": 0}],
       "arrows": [{"from": "x", "to": "y", "label": "writes", "b": 1}, {"from": "y", "to": "x", "label": "never", "dash": True, "tone": "red", "b": 2}]}
BARS = {"title": "A miss costs more", "unit": "ns", "bars": [{"id": "l1", "label": "L1 cache", "value": 1, "note": "about 4 cycles"},
                                                              {"id": "ram", "label": "Main memory", "value": 100}], "threshold": {"value": 10, "label": "budget"}}
GRAPH = {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C copy", "state": "new"}, {"id": "d", "label": "D", "state": "struck"}],
         "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "rebased"}]}


def test_a_map_graph_or_bars_source_carries_a_reading_list_made_from_its_spec():
    assert model.visual_source("map", json.dumps(MAP))["reading"] == {"title": "arrows", "items": [
        {"kind": "edge", "from": "Page A", "to": "Store", "label": "writes"},
        {"kind": "edge", "from": "Store", "to": "Page A", "label": "never", "dashed": True}]}
    assert model.visual_source("bars", json.dumps(BARS))["reading"] == {"title": "values", "items": [
        {"kind": "bar", "label": "L1 cache", "value": "1 ns", "note": "about 4 cycles"}, {"kind": "bar", "label": "Main memory", "value": "100 ns"},
        {"kind": "threshold", "label": "budget", "value": "10 ns"}]}
    assert model.visual_source("graph", json.dumps(GRAPH))["reading"] == {"title": "arrows", "items": [
        {"kind": "link", "from": "A", "to": "B", "label": ""}, {"kind": "link", "from": "B", "to": "C copy", "label": "rebased"},
        {"kind": "state", "label": "C copy", "state": "new"}, {"kind": "state", "label": "D", "state": "struck"}]}
    assert "reading" not in model.visual_source("flowchart", json.dumps({"nodes": [{"id": "a", "label": "A"}], "edges": []}))


@needs_node
def test_the_page_puts_the_reading_list_after_the_drawing_in_words_with_both_ends_the_label_and_the_dashed_state(tmp_path):
    page = (StagePage(tmp_path).show("m", visual("map", MAP), title="Map").show("b", visual("bars", BARS), title="Bars")
            .show("g", visual("graph", GRAPH), title="Graph").open())
    read = ("(n => { const s = pane(n).querySelector('svg.vz'), l = s.nextElementSibling;"
            " return {role: s.getAttribute('role'), tag: l.tagName, cls: l.className, label: l.getAttribute('aria-label'), items: [...l.querySelectorAll('li')].map((e) => e.textContent)}; })")
    page.send({"type": "stage:front", "view": "m", "manual": True}).check(read + "('m')")
    page.send({"type": "stage:front", "view": "b", "manual": True}).check(read + "('b')")
    page.send({"type": "stage:front", "view": "g", "manual": True}).check(read + "('g')")
    got = page.run()
    assert got[0] == {"role": "img", "tag": "UL", "cls": "vz-reading", "label": "Arrows",
                      "items": ["Page A, writes, goes to Store", "Store, never, goes to Page A, dashed"]}
    assert got[1]["label"] == "Values" and got[1]["items"] == ["L1 cache: 1 ns, about 4 cycles", "Main memory: 100 ns", "budget, the line: 10 ns"]
    assert got[2]["items"] == ["A is joined to B", "B, rebased, is joined to C copy", "C copy is new", "D is removed"]


@needs_node
def test_a_flowchart_dashed_arrow_is_read_as_dashed(tmp_path):
    spec = {"nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}], "edges": [{"from": "a", "to": "b", "line": "dashed", "label": "maybe"}]}
    page = StagePage(tmp_path).show("f", visual("flowchart", spec), title="F").open()
    page.check("[...pane('f').querySelectorAll('ul.m-reading li')].map((e) => e.textContent)")
    assert page.run() == [["Start, maybe, goes to End, dashed"]]


# -- r2-screenreader-3: a step names who sends to whom -------------------------------------------------------------------

NAMED = {"actors": [{"id": "a", "label": "Sender's\nbank"}, {"id": "b", "label": "Correspondent bank"}],
         "steps": [{"id": "s1", "from": "a", "to": "b", "arrow": "request", "label": "sends a SWIFT message"},
                   {"id": "s2", "from": "b", "to": "a", "arrow": "event", "label": "confirms", "reply_to": "s1"},
                   {"id": "s3", "from": "b", "to": "b", "arrow": "self", "label": "books it"},
                   {"id": "s4", "from": "a", "to": "b", "arrow": "band", "label": "settlement window"}]}


@needs_node
def test_a_sequence_row_and_its_dialog_say_the_step_number_who_sends_to_whom_and_what_in_one_wording(tmp_path):
    page = StagePage(tmp_path).show("seq", visual("sequence", NAMED), title="T").open()
    page.check("[...pane('seq').querySelectorAll('.ln-row')].map((r) => r.getAttribute('aria-label'))")
    page.js("pane('seq').querySelector('.ln-row[data-step=\"s2\"]').click();").check("pane('seq').querySelector('.ln-pop').getAttribute('aria-label')")
    assert page.run() == [["Step 1: Sender's bank to Correspondent bank, sends a SWIFT message",
                           "Step 2: Correspondent bank replies to Sender's bank, confirms",
                           "Step 3: Correspondent bank to itself, books it", "Step 4: stretch, settlement window"],
                          "Step 2: Correspondent bank replies to Sender's bank, confirms"]


@needs_node
def test_a_row_and_its_dialog_use_the_boards_own_numbers_when_a_spec_numbers_its_walkthrough(tmp_path):
    spec = {**NAMED, "steps": [{**s, "n": 7 + (i > 0)} for i, s in enumerate(NAMED["steps"])]}
    page = StagePage(tmp_path).show("seq", visual("sequence", spec), title="T").open()
    page.check("pane('seq').querySelector('.ln-row[data-step=\"s2\"]').getAttribute('aria-label')")
    page.js("pane('seq').querySelector('.ln-row[data-step=\"s2\"]').click();").check("pane('seq').querySelector('.ln-pop').getAttribute('aria-label')")
    assert page.run() == ["Step 8: Correspondent bank replies to Sender's bank, confirms"] * 2


# -- r2-tv-1: the secondary lanes styles read from across a room --------------------------------------------------------

def test_a_replys_words_a_steps_note_the_side_titles_and_the_gutter_marks_are_as_plain_as_the_rest_at_a_distance():
    assert rule(".ln-event .ln-lbl b")["font-weight"] == "600" and rule(".ln-event .ln-lbl b")["color"] == "var(--ink)"
    note = rule(".ln-note")
    assert note["font"] == "500 13.5px/1.35 var(--sans)" and note["color"] == "var(--ink)"
    assert rule(".ln-note.ln-under")["font-size"] == "13.5px"
    assert rule(".ln-stitle")["font"] == "600 14.5px/1.2 var(--sans)"      # the actor names are 14.5 px
    assert rule(".ln-gm")["font"] == "700 20px/1 var(--mono)" and rule(".ln-gm")["color"] == "var(--muted)"
    num = rule(".ln-num")
    assert (num["width"], num["height"], num["margin-top"], num["font"]) == ("26px", "26px", "-13px", "700 13px var(--sans)")
    assert rule(".ln-lbl code,.ln-call code")["font"] == "400 12.5px/1.35 var(--mono)"
    assert "ln-hatch" not in CSS and rule(".ln-gaptext")["font"] == "600 13.5px var(--sans)"


@needs_node
def test_a_side_with_no_step_in_a_row_is_a_plain_box_with_the_words_no_step_here(tmp_path):
    flat = visual("sequence", COMPARED)
    built = _scene(scene.sequence_model(flat["spec"]), [["+ step b1"]], "T")
    page = StagePage(tmp_path, width=1400).show("cmp", flat, title="T", extra={"scene": built}).open()
    page.check("(() => { const p = pane('cmp').querySelector('.ln-s-before .ln-pane'); return {words: [...p.querySelectorAll('.ln-gaptext')].map((t) => t.textContent),"
               " boxes: p.querySelectorAll('rect.ln-gapband').length, pattern: p.querySelectorAll('pattern').length}; })()")
    page.send({"type": "stage:lang", "lang": "el"}).check("[...pane('cmp').querySelectorAll('.ln-s-before .ln-gaptext')].map((t) => t.textContent)")
    assert page.run() == [{"words": ["No step here"], "boxes": 1, "pattern": 0}, ["Δεν υπάρχει βήμα εδώ"]]


@needs_node
def test_the_step_number_stands_beside_the_start_of_its_arrow_on_a_wide_board_and_a_phone_draws_a_line_from_the_gutter(tmp_path):
    spec = {"actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
            "steps": [step("s1", "a", "b", "one"), step("s2", "b", "a", "two", "event", reply_to="s1")]}
    built = _scene(scene.sequence_model(spec), [["focus step s1"]], "T")
    nums = ("[...pane('seq').querySelectorAll('.ln-row')].map((r) => [r.querySelector('.ln-num').style.left, r.querySelectorAll('line.ln-lead').length])")
    wide = StagePage(tmp_path, width=1400).show("seq", visual("sequence", spec), title="T", extra={"scene": built}).open().check(nums)
    phone = StagePage(tmp_path, width=390).show("seq", visual("sequence", spec), title="T", extra={"scene": built}).open()
    phone.check("(() => { pane('seq').querySelector('.visual.lanes').clientWidth = 390; })()").send({"type": "stage:frame", "view": "seq", "n": 1}).check(nums)
    left_wide = wide.run()[0]
    assert [r[1] for r in left_wide] == [0, 0]
    assert [r[0] for r in left_wide] != ["20px", "20px"]            # beside the arrows' starts, not in the gutter
    got = phone.run()[1]
    assert [r[0] for r in got] == ["4px", "4px"] and [r[1] for r in got] == [1, 1]


# -- r2-phone-1: no step control for a board with no steps, and a table says how many rows are below -------------------

@needs_node
def test_a_board_with_one_step_or_none_has_no_step_control_and_one_with_two_has(tmp_path):
    one = _scene(scene.sequence_model(TURN), [["focus step s1"]], "T")
    two = _scene(scene.sequence_model(TURN), [["focus step s1"], ["focus step s2"]], "T")
    page = (StagePage(tmp_path).show("one", visual("sequence", TURN), title="One", extra={"scene": one})
            .show("two", visual("sequence", TURN), title="Two", extra={"scene": two}).show("none", GRID, title="None").open())
    for n in ("one", "two", "none"):
        page.send({"type": "stage:front", "view": n, "manual": True})
    page.check("['one', 'two', 'none'].map((n) => [!!pane(n).querySelector('.stepbar'), !!pane(n).querySelector('.vstep')])")
    assert page.run() == [[[False, False], [True, True], [False, False]]]


def test_on_a_phone_a_board_starts_at_the_top_of_its_pane_and_the_rows_cue_is_a_visible_pill():
    phone = CSS.split("@media (max-width:600px){\n  /* The title keeps the row")[1].split("\n}")[0]
    assert "  .pbody{padding:2px 12px 8px;justify-content:flex-start}" in phone
    pill = rule(".more-rows")
    assert pill["background"] == "var(--acc)" and pill["border-radius"] == "999px" and pill["position"] == "absolute"
    assert rule(".md.grid") == {"position": "relative"}


@needs_node
def test_a_table_taller_than_its_pane_shows_a_pill_with_the_rows_out_of_sight_and_the_pill_scrolls_them_in(tmp_path):
    rows = "\n".join(f"| Brand {i} | {i} g |" for i in range(7))
    page = StagePage(tmp_path, width=390).show("t", {"type": "inline", "format": "table", "body": "| Cereal | Fibre |\n|---|---|\n" + rows}, title="T").open()
    fake = ("(() => { const w = pane('t').querySelector('.tablewrap'); Object.defineProperty(w, 'scrollHeight', {value: 400, configurable: true});"
            " Object.defineProperty(w, 'clientHeight', {value: 200, configurable: true});"
            " w.getBoundingClientRect = () => ({top: 0, bottom: 200, left: 0, right: 390, width: 390, height: 200});"
            " [...w.querySelectorAll('tbody tr')].forEach((tr, i) => { tr.getBoundingClientRect = () => ({top: 40 * i, bottom: 40 * i + 40, left: 0, right: 390, width: 390, height: 40}); });"
            " w.scrollTo = (o) => { w.__scrolled = o; }; w.scrollBy = (o) => { w.__by = o; };"
            " w.dispatchEvent(new Event('scroll')); })();")
    page.js(fake).check("(() => { const p = pane('t').querySelector('.more-rows'); return p && [p.textContent, p.tagName, p.type]; })()")
    page.js("pane('t').querySelector('.more-rows').click();").check("pane('t').querySelector('.tablewrap').__by.top")
    page.send({"type": "stage:lang", "lang": "el"}).js("pane('t').querySelector('.tablewrap').dispatchEvent(new Event('scroll'));").check("pane('t').querySelector('.more-rows').textContent")
    page.js("Object.defineProperty(pane('t').querySelector('.tablewrap'), 'clientHeight', {value: 400, configurable: true}); pane('t').querySelector('.tablewrap').dispatchEvent(new Event('scroll'));").check("!!pane('t').querySelector('.more-rows')")
    assert page.run() == [["↓ 2 more rows", "BUTTON", "button"], 160, "↓ Ακόμη 2 γραμμές", False]


# -- r2-first-3: Back to the voice fronts the board the voice last showed -----------------------------------------------

POINTS = {"type": "inline", "format": "points", "items": [{"n": 1, "text": "Layers end where the wire starts", "answer": 1}]}
IN_FRONT = "[...document.querySelectorAll('button[role=tab]')].find((t) => t.getAttribute('aria-selected') === 'true')?.dataset.view"


def _boards(tmp_path):
    return (StagePage(tmp_path, width=1400).show("layers", GRID, title="Where each layer ends").show("other", GRID, title="Other", background=True)
            .show("key-points", POINTS, title="Key points", extra={"kind": "points", "pinned": True}, background=True).open())


@needs_node
def test_following_turning_on_fronts_the_board_the_voice_showed_last_not_key_points_the_reader_opened(tmp_path):
    page = _boards(tmp_path)
    page.send({"type": "stage:answer", "n": 1}).send({"type": "stage:front", "view": "layers", "manual": False, "answer": 1}).check(IN_FRONT)
    page.send({"type": "stage:front", "view": "key-points", "manual": True}).check(IN_FRONT)                     # opened by hand: following off
    page.send({"type": "stage:follow", "on": True, "front": True}).check(IN_FRONT)                               # Back to the voice (the page's button or the gear)
    page.send({"type": "stage:front", "view": "other", "manual": True}).send({"type": "stage:follow", "on": True}).check(IN_FRONT)   # no front asked (a play of the board in front)
    page.js("document.querySelector('.follow').click();").check(IN_FRONT)                                       # the stage's own Back to the voice
    page.check("[document.querySelector('.follow').hidden]")
    assert page.run() == ["layers", "key-points", "layers", "other", "layers", [True]]


@needs_node
def test_a_text_only_answer_while_following_returns_from_key_points_to_the_board_the_voice_showed(tmp_path):
    page = _boards(tmp_path)
    page.send({"type": "stage:answer", "n": 1}).send({"type": "stage:front", "view": "layers", "manual": False, "answer": 1})
    page.send({"type": "stage:front", "view": "key-points", "manual": True}).send({"type": "stage:follow", "on": True}).check(IN_FRONT)   # following, Key points still in front by hand
    page.send({"type": "stage:answer", "n": 2}).send({"type": "stage:state", "front": None, "frames": {}, "keys": 0, "answer": 2}).check(IN_FRONT)
    # Key points stays where the reader puts it while they are not following
    page.send({"type": "stage:front", "view": "key-points", "manual": True}).send({"type": "stage:state", "front": None, "frames": {}, "keys": 0, "answer": 3}).check(IN_FRONT)
    assert page.run() == ["key-points", "layers", "key-points"]


@needs_node
def test_a_board_the_voice_fronted_while_the_reader_was_elsewhere_is_the_one_following_returns_to(tmp_path):
    page = _boards(tmp_path)
    page.send({"type": "stage:front", "view": "layers", "manual": False}).send({"type": "stage:front", "view": "other", "manual": True})
    page.send({"type": "stage:front", "view": "key-points", "manual": False}).check(IN_FRONT)      # the voice never fronts Key points, and the reader is following nothing
    page.send({"type": "stage:front", "view": "layers", "manual": False}).send({"type": "stage:front", "view": "other", "manual": True}).send({"type": "stage:follow", "on": True, "front": True}).check(IN_FRONT)
    assert page.run() == ["other", "layers"]


# -- r2-greek-2: the stage's own words follow the page's language -------------------------------------------------------

TOOLBAR = ("(() => ({ back: document.querySelector('.follow').textContent, pos: document.querySelector('.tabpos').textContent,"
           " prev: document.querySelector('.navbtn.prev').getAttribute('aria-label'), lang: document.querySelector('.tabbar').getAttribute('lang'),"
           " root: document.documentElement.lang, boards: document.querySelector('.boards h4').textContent,"
           " empty: document.querySelector('.empty h2')?.textContent }))()")


@needs_node
def test_the_stage_says_its_toolbar_in_greek_when_the_page_does_and_back_in_english_when_it_goes_back(tmp_path):
    page = StagePage(tmp_path).show("a", GRID, title="A").show("b", GRID, title="B", background=True).open()
    page.check(TOOLBAR).send({"type": "stage:lang", "lang": "el"}).check(TOOLBAR).send({"type": "stage:lang", "lang": "en"}).check(TOOLBAR)
    en, el, back = page.run()
    assert en["back"] == "Back to the voice" and en["pos"] == "Board 1 of 2" and en["prev"] == "Previous board" and en["boards"] == "Boards"
    assert el == {"back": "Πίσω στη φωνή", "pos": "Πίνακας 1 από 2", "prev": "Προηγούμενος πίνακας", "lang": "el", "root": "el", "boards": "Πίνακες", "empty": el["empty"]}
    assert back == {**en, "lang": "en", "root": "en"}


@needs_node
def test_the_empty_stage_copy_the_step_control_and_the_key_points_board_say_themselves_in_greek(tmp_path):
    empty = StagePage(tmp_path).open().send({"type": "stage:lang", "lang": "el"}).check("[document.querySelector('.empty h2').textContent, document.querySelector('.empty .msg').textContent, [...document.querySelectorAll('.tile span')].map((s) => s.textContent)]")
    assert empty.run() == [["Η σκηνή είναι άδεια", "Όταν ο Claude δείξει κώδικα, διάγραμμα, πίνακα ή σελίδα, εμφανίζεται εδώ.", ["Κώδικας", "Διάγραμμα", "Πίνακας", "Σελίδα"]]]
    two = _scene(scene.sequence_model(TURN), [["focus step s1"], ["focus step s2"]], "T")
    page = (StagePage(tmp_path).show("seq", visual("sequence", TURN), title="Turn", extra={"scene": two})
            .show("key-points", POINTS, title="Key points", extra={"kind": "points", "pinned": True}, background=True).open())
    page.send({"type": "stage:frame", "view": "seq", "n": 1}).check("[pane('seq').querySelector('.vstep').textContent, [...pane('seq').querySelectorAll('.pbtns .btn')].map((b) => b.textContent)]")
    page.send({"type": "stage:lang", "lang": "el"}).check("[pane('seq').querySelector('.vstep').textContent, [...pane('seq').querySelectorAll('.pbtns .btn')].map((b) => b.textContent), pane('seq').querySelector('.stepnext').getAttribute('aria-label')]")
    page.send({"type": "stage:front", "view": "key-points", "manual": True}).check(
        "[pane('key-points').querySelector('.vtitle').textContent, pane('key-points').querySelector('.kcap').textContent, document.querySelector('button[data-view=\"key-points\"] .ttl').textContent]")
    out = page.run()
    assert out[0] == ["Step 1 of 2", ["Copy"]]
    assert out[1] == ["Βήμα 1 από 2", ["Αντιγραφή"], "Επόμενο βήμα"]
    assert out[2] == ["Βασικά σημεία", "Απάντηση 1", "Βασικά σημεία"]


def words_table():
    """words.js's two tables, as dicts, read from its text (no node needed): key -> text."""
    src = (STATIC / "words.js").read_text()
    out = {}
    for lang in ("en", "el"):
        body = re.search(r"\n  " + lang + r": \{\n(.*?)\n  \},", src, re.S).group(1)
        out[lang] = dict(re.findall(r'"([\w.]+)": "((?:[^"\\]|\\.)*)"', body))
    return out


def test_every_stage_word_has_a_greek_form_with_the_same_blanks_and_nothing_is_left_blank():
    t = words_table()
    assert sorted(set(t["en"]) ^ set(t["el"])) == []
    for key, text in t["en"].items():
        assert sorted(re.findall(r"\{(\w+)\}", text)) == sorted(re.findall(r"\{(\w+)\}", t["el"][key])), key
        assert t["el"][key].strip(), key
    same = [k for k in t["en"] if t["en"][k] == t["el"][k] and re.search(r"[A-Za-z]{4}", t["en"][k]) and "{" not in t["en"][k]]
    assert same == []   # a word left in English in the Greek table is not translated


def test_every_word_the_stage_asks_for_is_in_the_table_and_the_stage_writes_no_word_of_its_own_where_it_shows_one():
    t = words_table()["en"]
    srcs = {f: (STATIC / f).read_text() for f in ("stage.js", "lanes.js", "map.js", "scene.js")}
    asked, literals = set(), set()
    for src in srcs.values():
        asked |= set(re.findall(r'\bwd\("([\w.]+)"', src))
        asked |= {k + sfx for k in re.findall(r'\bwdn\("([\w.]+)"', src) for sfx in (".one", ".other")}
        literals |= set(re.findall(r'"([a-z]\w*(?:\.\w+)+|[a-z]+)"', src))
    families = ("kind.", "read.state.", "mark.", "read.edge", "read.link")   # keys built from a name or a suffix
    assert sorted(k for k in asked if not k.endswith(".") and k not in t) == []
    unused = [k for k in t if not k.endswith((".one", ".other")) and k not in literals and not k.startswith(families)]
    unused += [k for k in t if k.endswith((".one", ".other")) and k.rsplit(".", 1)[0] not in literals and not k.startswith(families)]
    assert sorted(set(unused)) == []                       # nothing in the table is unused
    stage = srcs["stage.js"]
    for english in ("Answer in the text field", '"Copied"', '"Copy failed"', "The stage is empty", "Previous step", "Wrap lines"):
        assert english not in stage.replace('wd("', ""), english   # said through the table, never written where it shows
