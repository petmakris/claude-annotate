"""Round 2 fixes of the sequence and compare boards (run bd1125, job r2-b3): the outcome box is drawn under the one
key the scene gives it, a spec of the wrong type is refused by name or shown as a failure, a step pointed at that
moved lights both its places, a phone keeps its step notes. Page logic under node; nothing measured here."""
from __future__ import annotations

import json

import pytest

from skills.stage import model, scene
from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_compare import step
from skills._shared.visuals import sequence_svg
from skills._shared.visuals.sequence import ValidationError

A, B, C = {"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}
OUT = {"title": "Same hops", "lines": ["only the order moved"], "tone": "green"}
SEQ = {"actors": [A, B], "steps": [step("s1", "a", "b", "asks", note="port 443, 1 round trip"),
                                   step("s2", "b", "a", "answers", "event", reply_to="s1")], "outcome": OUT}
MOVED = {"compare": {"before": {"actors": [A, B, C], "steps": [step("m1", "a", "b", "one"), step("m2", "b", "c", "two"), step("m3", "a", "c", "three")]},
                     "after": {"actors": [A, B, C], "steps": [step("m2", "b", "c", "two"), step("m3", "a", "c", "three"), step("m1", "a", "b", "one")]}},
         "outcome": OUT}


def _scene(spec, tags, title="T"):
    built, _ = scene.compile_scene(scene.sequence_model(spec), [[scene.parse_verb(t) for t in g] for g in tags], title)
    return built


# -- validation: a field of the wrong type is named ---------------------------------------------------------------

def test_an_outcome_whose_lines_is_one_text_is_refused_naming_the_field():
    with pytest.raises(ValidationError, match=r"outcome: lines is a list of text"):
        sequence_svg.validate({**SEQ, "outcome": {"title": "T", "lines": "one line"}})


@pytest.mark.parametrize("field", ["actors", "steps", "phases", "legend"])
def test_a_list_field_that_is_text_is_refused_naming_it(field):
    with pytest.raises(ValidationError, match=f"^{field} must be a list of objects"):
        sequence_svg.validate({**SEQ, field: "oops"})


# -- the outcome box: one key, ghosted until said, lit at rest ----------------------------------------------------

OUTCOME = ("(n => { const e = pane(n).querySelector('.ln-outcome');"
           " return e && {key: e.dataset.key, ghost: e.classList.contains('ln-ghost'), lit: e.classList.contains('ln-lit'),"
           " hidden: e.classList.contains('k-hidden'), said: e.classList.contains('ln-said'),"
           " lines: [...e.querySelectorAll('span')].map((x) => x.textContent)}; })")


@needs_node
def test_a_sequences_outcome_has_the_scene_key_and_is_lit_at_rest(tmp_path):
    built = _scene(SEQ, [["+ step s1"], ["+ step s2"]])
    page = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    for n in (0, built["rest"]):
        page.send({"type": "stage:frame", "view": "seq", "n": n}).check(OUTCOME + "('seq')")
    first, rest = page.run()
    assert first["key"] == rest["key"] == "outcome:end" and first["hidden"] is True and first["ghost"] is True
    assert rest == {"key": "outcome:end", "ghost": False, "lit": True, "hidden": False, "said": False, "lines": ["only the order moved"]}


@needs_node
def test_a_compared_boards_outcome_has_the_scene_key_and_is_lit_at_rest(tmp_path):
    flat = visual("sequence", MOVED)
    built = _scene(flat["spec"], [["+ step m2"]])
    page = StagePage(tmp_path, width=1400).show("cmp", flat, title="T", extra={"scene": built}).open()
    page.send({"type": "stage:frame", "view": "cmp", "n": built["rest"]}).check(OUTCOME + "('cmp')")
    got = page.run()[0]
    assert got["key"] == "outcome:end" and got["lit"] is True and got["ghost"] is False


@needs_node
def test_pointing_at_the_outcome_says_it(tmp_path):
    built = _scene(SEQ, [["+ step s1"], ["focus outcome"]])
    page = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    page.send({"type": "stage:frame", "view": "seq", "n": 2}).check(OUTCOME + "('seq')")
    assert page.run()[0]["said"] is True


# -- a spec the lanes cannot draw is said on the stage ----------------------------------------------------------

@needs_node
def test_a_spec_the_lanes_cannot_draw_shows_a_failure_message_not_a_blank_board(tmp_path):
    bad = {"type": "inline", "format": "visual", "tool": "sequence", "spec": {"actors": [A, B], "steps": [None]}}
    page = StagePage(tmp_path, width=1400).show("bad", bad, title="Bad").open()
    page.check("pane('bad').querySelector('.ln-fail b')?.textContent")
    assert page.run() == ["This diagram could not be drawn."]


# -- compare: a point on a moved step lights both places, rest is whole ---------------------------------------------

CMP = ("(() => { const side = (sd) => { const p = pane('cmp').querySelector('.ln-s-' + sd + ' .ln-pane');"
       " const on = (c) => [...p.querySelectorAll('.ln-row.' + c)].map((r) => r.dataset.step);"
       " return {focus: on('k-focus'), cur: on('ln-cur'), rows: [...p.querySelectorAll('.ln-row')].map((r) => r.dataset.step)}; };"
       " const b = pane('cmp').querySelector('.visual.lanes');"
       " return {before: side('before'), after: side('after'), mode: ['both', 'before', 'after'].filter((m) => b.classList.contains('ln-m-' + m)),"
       " conn: [...b.querySelectorAll('.ln-gconn')].map((c) => [c.dataset.row, c.classList.contains('ln-lit')])}; })()")


def _moved(tmp_path, tags, width=1400):
    flat = visual("sequence", MOVED)
    built = _scene(flat["spec"], tags)
    return StagePage(tmp_path, width=width).show("cmp", flat, title="T", extra={"scene": built}).open(), built


@needs_node
def test_a_point_on_a_moved_step_lights_its_old_place_and_its_new_one_and_never_a_gap(tmp_path):
    page, built = _moved(tmp_path, [["+ step m2"], ["focus step m1"]])
    page.send({"type": "stage:frame", "view": "cmp", "n": 2}).check(CMP)
    got = page.run()[0]
    assert got["after"]["cur"] == ["m1"] and got["before"]["cur"] == ["was~m1"]
    assert got["before"]["focus"] == ["was~m1"] and "m1" not in got["before"]["focus"]
    assert got["conn"] == [["m1", True]]


@needs_node
def test_at_rest_a_compare_board_shows_both_sides_undimmed(tmp_path):
    page, built = _moved(tmp_path, [["focus before"], ["focus after"]])
    page.send({"type": "stage:frame", "view": "cmp", "n": 2}).check(CMP)
    page.send({"type": "stage:frame", "view": "cmp", "n": built["rest"]}).check(CMP)
    assert [g["mode"] for g in page.run()] == [["after"], ["both"]]


NARROW_CMP = ("(() => { const b = pane('cmp').querySelector('.visual.lanes');"
              " return {hidden: [...b.querySelectorAll('.ln-side')].map((s) => [s.dataset.side, s.hidden]),"
              " gaps: b.querySelectorAll('.ln-gap').length}; })()")


@needs_node
def test_on_a_phone_a_compare_board_drops_its_hatched_gaps_and_shows_the_side_that_has_the_step_said(tmp_path):
    page, built = _moved(tmp_path, [["+ step m2"], ["focus step m1"]], width=390)
    page.check("(() => { const b = pane('cmp').querySelector('.visual.lanes'); b.clientWidth = 390; })()")
    page.send({"type": "stage:frame", "view": "cmp", "n": 2}).check(NARROW_CMP)
    got = page.run()[1]
    assert got == {"hidden": [["before", True], ["after", False]], "gaps": 0}


# -- step notes: a phone keeps them --------------------------------------------------------------------------

NOTES = ("(n => { const p = pane(n); return {notes: [...p.querySelectorAll('.ln-note')].map((e) => [e.textContent, e.classList.contains('ln-under'), e.style.maxWidth])}; })")


@needs_node
def test_a_phone_shows_the_note_of_the_step_said_under_its_arrow_and_a_wide_board_keeps_it_in_the_margin(tmp_path):
    built = _scene(SEQ, [["focus step s1"]])
    wide = StagePage(tmp_path, width=1400).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    wide.send({"type": "stage:frame", "view": "seq", "n": 1}).check(NOTES + "('seq')")
    assert wide.run()[0]["notes"] == [["port 443, 1 round trip", False, "169px"]]   # 22 characters at 7.4 px (13.5 px sans) and 28 of padding: 191 reserved, 22 less for its edges
    phone = StagePage(tmp_path, width=390).show("seq", visual("sequence", SEQ), title="T", extra={"scene": built}).open()
    phone.check("(() => { pane('seq').querySelector('.visual.lanes').clientWidth = 390; })()")
    phone.send({"type": "stage:frame", "view": "seq", "n": 1}).check(NOTES + "('seq')")
    assert phone.run()[1]["notes"] == [["port 443, 1 round trip", True, ""]]
