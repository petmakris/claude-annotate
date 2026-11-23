"""A screen board in a call: [[show screen: <spotlight.json> | T]], stepped by the sentences that say its parts'
titles and lit by [[point: part N]] or [[point: part "title"]]."""
from helpers import make_args, stage_rule_breaks, talk
from skills.stage.tests.test_screen import project


def _call(tmp_path, code):
    return talk.Call(make_args(code=code), "T", tmp_path / "out")


def test_a_screen_comes_in_part_by_part_with_the_sentences_that_say_its_titles(tmp_path):
    code = project(tmp_path / "code")
    call = _call(tmp_path, code)
    shown = call.split_reply("[[show screen: docs/spotlight.json | Filing]] Here is how a request is filed. "
                             "Every request starts from one form. Then press Send when it is done. "
                             "And your own requests come first in the list.")
    (item,) = call.board.items
    assert (item["kind"], item["view"], call.board.problems) == ("screen", "filing", [])
    name, source, title = talk.stage_view(item)
    assert (source["format"], title) == ("screen", "Filing") and source is item["visual"]
    frames = item["scene"]["frames"]
    assert [f["cur"] for f in frames[1:-1]] == [["part:p1"], ["part:p2"], ["part:p3"]]
    assert stage_rule_breaks(call, shown) == []


def test_a_point_lights_a_screen_part_by_its_number_or_its_title(tmp_path):
    code = project(tmp_path / "code")
    call = _call(tmp_path, code)
    shown = call.split_reply('[[show screen: docs/spotlight.json | Filing]] Every request starts from one form. [[point: part 2]] This button sends it. '
                             '[[point: part "Your own requests come first"]] And this list holds yours.')
    frames = call.board.items[0]["scene"]["frames"]
    assert call.board.problems == []
    assert [f["focus"] for f in frames[1:-1]][-2:] == [["part:p2"], ["part:p3"]]
    assert stage_rule_breaks(call, shown) == []


def test_a_screen_that_cannot_be_shown_or_pointed_at_is_a_problem(tmp_path):
    code = project(tmp_path / "code")
    call = _call(tmp_path, code)
    call.split_reply("[[show screen: docs/none.json | X]] Hi.")
    assert call.board.problems == ["screen not shown, no such spotlight spec in the project: docs/none.json"]
    call = _call(tmp_path, code)
    call.split_reply("[[show screen: docs/spotlight.json | Filing]] Hi. [[point: part 9]] There.")
    assert call.board.problems[0] == 'point not shown: no part 9 in "Filing"'
    call = _call(tmp_path, code)
    call.split_reply("[[show screen: docs/spotlight.json | Filing]] Hi. [[point: row 2]] There.")
    assert call.board.problems[0] == 'point not shown: "Filing" is a screen; use part ID'
    call = _call(tmp_path, None)
    call.split_reply("[[show screen: docs/spotlight.json | Filing]] Hi.")
    assert call.board.problems == ["screen not shown, talk was started without --code: docs/spotlight.json"]
