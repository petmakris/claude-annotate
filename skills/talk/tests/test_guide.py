"""The answer guide (SKILL.md, references/boards.md): the wording that steers which board a session picks."""
import re

from helpers import make_args, talk

GUIDE = (talk.SKILL_DIR / "SKILL.md").read_text()
BOARDS = (talk.SKILL_DIR / "references" / "boards.md").read_text()


def test_the_choice_table_keeps_the_flowchart_for_real_rules_and_the_table_last():
    section = GUIDE.split("### Choose the board by the question")[1].split("### Writing the answer")[0]
    rows = [r for r in section.splitlines() if r.startswith("| ")]
    flow = next(r for r in rows if "| flowchart |" in r and "decision" in r)
    assert "never a decision tree you make up" in flow
    assert "a flowchart is not the fallback for a table" in GUIDE
    code = next(r for r in rows if r.startswith("| how a mechanism, loop or piece of code works"))
    assert "never board-less" in code
    assert rows[-1].startswith("| several things judged")  # the table is the last row
    assert "never a how or why question about code" in GUIDE


def test_the_answer_rules_cap_the_lead_in_the_steps_and_name_the_flowchart_roles():
    assert "**At most one plain claim sentence of 20 words or fewer before the board's tag.**" in GUIDE
    assert GUIDE.index("At most one plain claim sentence") < GUIDE.index("**The stage reads your words aloud with you.**")
    assert "up to 9 steps if the answer stays under 220 words" in GUIDE and "three to six steps" not in GUIDE
    assert "`entry`, `code`, `call`, `decision`, `success` or `error`" in GUIDE.split("### Teaching with the board")[1]
    assert "Order the actors by who talks to whom" in GUIDE and "Order the actors by who talks to whom" in BOARDS
    assert "one `[[point: lines A-B]]` for each range" in GUIDE and "show a whole short file" in GUIDE


def test_a_list_of_line_ranges_in_one_point_is_not_read_as_two_ranges(tmp_path):
    call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Guide", tmp_path / "out")
    call.split_reply("[[show code: skills/talk/live_turns.py:33-53 | Turns]] Here. [[point: lines 35-36, 40-41]] Both.")
    assert call.board.problems, "a multi-range point is refused, so the guide says one point per range"


def test_no_example_in_the_guide_or_demo_uses_internal_jargon_as_a_label():
    demo = (talk.SKILL_DIR / "demo.md").read_text()
    for text in (GUIDE, demo):
        assert '"label": "Doorbell"' not in text and "TALK_TURN" not in "".join(re.findall(r"\[\[show.*?\[\[/show\]\]", text, re.S))
        assert "draft=1" not in text.split("### Teaching with the board")[-1]
    assert '"label": "Claude waits for the turn", "sub": "talk_client.py"' in GUIDE


def _choice_rows():
    section = GUIDE.split("### Choose the board by the question")[1].split("### Writing the answer")[0]
    return [r for r in section.splitlines() if r.startswith("| ")]


def test_a_plan_with_a_value_per_item_has_its_own_row_and_days_no_longer_send_a_table_to_a_sequence():
    rows = _choice_rows()
    plan = next(r for r in rows if r.startswith("| a plan, itinerary or schedule where each item has a value"))
    assert "bars when the cost decides; a table of up to about 7 rows" in plan
    assert "nothing in a plan is between actors" in plan
    assert rows.index(plan) < rows.index(rows[-1])  # before the table's row, which stays last
    assert "steps, parts or states, or events between actors, use a sequence" in GUIDE and "days or events" not in GUIDE
    assert "steps, parts or states, or events between actors, belong on a sequence" in BOARDS and "days or events" not in BOARDS
    assert "It is never a sequence: nothing in it is between actors." in BOARDS
    assert "**A plan with a cost for each day**" in GUIDE


def test_key_points_is_first_in_the_list_never_in_front_and_a_saved_item_is_shown_with_a_front_cue():
    assert "which is first in the board list but never in front" in GUIDE
    assert "puts it up with a front cue for Key points" in GUIDE and "pinned first" not in GUIDE
    page = (talk.SKILL_DIR / "references" / "call-page.md").read_text()
    assert "a tap on it puts that board in front" in page


def test_a_picture_of_a_physical_thing_is_said_to_be_undrawable_and_boxes_with_arrows_do_not_stand_in():
    rows = _choice_rows()
    pic = next(r for r in rows if r.startswith("| a picture or drawing of a physical or spatial thing"))
    assert "no board draws it: say so in one plain first sentence" in pic
    assert "a flowchart or map is not a picture, and boxes with arrows must not stand in for a spatial layout" in pic
    assert "a page in `--code` when the user has an image" in pic and rows[-1].startswith("| several things judged")
    assert "scene" not in pic.lower() and "svg" not in pic.lower()
    assert "## A picture of a physical thing" in BOARDS
    assert "A flowchart or a map is not a picture: never let boxes with arrows stand in for a spatial layout." in BOARDS


def test_a_long_typed_message_is_answered_point_by_point_and_the_now_card_copy_is_named():
    loop = GUIDE.split("## 3. Answering a turn")[1].split("`reply` exit codes")[0]
    assert "answer every numbered point in order, and answer any question it asks about the page itself" in loop
    assert "the Now card has a Copy button for the answer's text" in loop
    assert "State no fact the user did not give" in loop
    page = (talk.SKILL_DIR / "references" / "call-page.md").read_text()
    assert "a **Copy** button for the answer's text" in page
