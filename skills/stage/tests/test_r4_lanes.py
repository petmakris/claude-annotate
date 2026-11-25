"""Round 4 fixes of the sequence and compare boards (run bd1125, job f-3): an actor is a letter, never a digit; a compare
board's two sides are in one card mode; a call to itself on a narrow board has its chip over the loop and its step number
in its own gutter; pointing at the outcome goes to the outcome, not the top. Page logic under node; nothing measured here."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skills.stage import scene
from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_compare import step

LANES = Path(__file__).resolve().parents[1] / "static" / "lanes.js"


def marks(labels):
    src = ("import { actorMarks } from %s; console.log(JSON.stringify(actorMarks(%s.map((l) => ({ label: l })))));"
           % (json.dumps(LANES.as_uri()), json.dumps(labels)))
    got = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


@needs_node
def test_an_actors_mark_is_its_first_letter_then_its_words_initials_then_more_letters():
    assert marks(["kubectl", "API server", "etcd", "Scheduler", "Kubelet", "Container runtime"]) == ["K", "A", "E", "S", "Ku", "C"]
    assert marks(["Service A", "Service B", "Service C"]) == ["S", "SB", "SC"]
    assert marks(["Éclair", "écran", "Ω"]) == ["É", "Éc", "Ω"]


@needs_node
def test_a_mark_that_no_prefix_can_tell_apart_falls_back_to_the_actors_place():
    assert marks(["aaa", "aaa", "aaa", "aaa", "aaa"]) == ["A", "Aa", "Aaa", "4", "5"]


def _scene(spec, tags):
    built, _ = scene.compile_scene(scene.sequence_model(spec), [[scene.parse_verb(t) for t in g] for g in tags], "T")
    return built


A, B, C = {"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}
OUT = {"title": "Same hops", "lines": ["only the order moved"], "tone": "green"}
SEQ = {"actors": [A, B], "steps": [step("s1", "a", "b", "asks"), step("s2", "b", "a", "answers", "event", reply_to="s1")], "outcome": OUT}


@needs_node
def test_pointing_at_the_outcome_aims_the_view_at_the_outcome_never_the_top(tmp_path):
    built = _scene(SEQ, [["+ step s1"], ["focus outcome"]])
    page = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    page.check("(() => { const b = pane('seq').querySelector('.visual.lanes'); b._lanes.managed = true; return 0; })()")
    for n in (1, 2, built["rest"]):
        page.send({"type": "stage:frame", "view": "seq", "n": n}).check("pane('seq').querySelector('.visual.lanes')._lanes.aim")
    got = page.run()
    assert (built["rest"], got[1:]) == (3, ["row", "outcome", "top"])   # the answer over, after a point at the outcome: back to the top


def _many(n, tail=""):
    return [{"id": f"x{i}", "label": f"Actor {chr(97 + i)}"} for i in range(n)]


CMP53 = {"compare": {"before": {"actors": _many(5), "steps": [step("p1", "x0", "x1", "one"), step("p2", "x1", "x4", "two")]},
                     "after": {"actors": _many(3), "steps": [step("p1", "x0", "x1", "one"), step("p2", "x1", "x2", "two")]}}}


@needs_node
def test_a_compare_board_with_five_actors_on_one_side_has_both_sides_in_the_dense_card_mode(tmp_path):
    flat = visual("sequence", CMP53)
    built = _scene(flat["spec"], [["+ step p1"]])
    page = StagePage(tmp_path, width=1400).show("cmp", flat, title="T", extra={"scene": built}).open()
    page.check("(() => { for (const p of pane('cmp').querySelectorAll('.ln-pane')) Object.defineProperty(p, 'clientWidth', { value: 430, configurable: true }); })()")
    page.send({"type": "stage:frame", "view": "cmp", "n": 1}).check(
        "[...pane('cmp').querySelectorAll('.ln-pane')].map((p) => [p.classList.contains('ln-dense'), p.querySelectorAll('.ln-key .ln-kitem').length])")
    got = page.run()[1]
    assert got == [[True, 5], [True, 3]]


SELF = {"actors": [A, B, C], "steps": [step("s1", "a", "b", "asks"), step("s2", "b", "b", "builds the answer from what it holds", note="43 to 128 characters"),
                                     step("s3", "b", "c", "writes")]}
ROWS = ("(() => { const r = pane('seq').querySelector('.ln-row.ln-cur'); const lbl = r.querySelector('.ln-lbl'), note = r.querySelector('.ln-note'), num = r.querySelector('.ln-num');"
        " return {lbl: [lbl.className, lbl.style.top, lbl.style.maxWidth], note: note && [note.className, note.style.top], num: num.style.left, h: r.style.height}; })()")


@needs_node
def test_a_call_to_itself_on_a_phone_has_its_chip_over_the_loop_its_note_under_it_and_its_number_in_the_gutter(tmp_path):
    built = _scene(SELF, [["focus step s2"]])
    phone = StagePage(tmp_path, width=390).show("seq", visual("sequence", SELF), title="T", extra={"scene": built}).open()
    phone.check("(() => { pane('seq').querySelector('.visual.lanes').clientWidth = 390; })()")
    phone.send({"type": "stage:frame", "view": "seq", "n": 1}).check(ROWS)
    assert phone.run()[1] == {"lbl": ["ln-lbl ln-over ln-chipped", "62px", "332.40000000000003px"], "note": ["ln-note ln-under", "82px"], "num": "4px", "h": "98px"}


@needs_node
def test_a_call_to_itself_on_a_wide_board_keeps_its_chip_beside_the_loop_and_its_number_where_it_was(tmp_path):
    built = _scene(SELF, [["focus step s2"]])
    wide = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SELF), title="T", extra={"scene": built}).open()
    wide.send({"type": "stage:frame", "view": "seq", "n": 1}).check(ROWS)
    got = wide.run()[0]
    assert got["lbl"][0] == "ln-lbl ln-beside ln-chipped" and got["num"] == "20px" and got["h"] == "76px"
