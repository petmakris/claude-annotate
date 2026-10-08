"""The stage demo: `talk.py --demo` plays demo.md's answers in a real call, one per thing said, so every
board can be seen moving with the voice without a Claude session."""
import asyncio
import re

from helpers import AUTH, make_args, run, running_app, stage_rule_breaks, talk


def test_every_demo_answer_goes_through_the_reply_parser_without_a_board_problem(tmp_path):
    answers = talk.load_demo()
    assert len(answers) >= 9
    call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Stage demo", tmp_path / "out")
    for text in answers:
        first, _, rest = text.partition("\n")
        body = rest if first.startswith("page:") else text
        call.board.problems.clear()
        call.split_reply(body)
        assert call.board.problems == [], (body[:60], call.board.problems)
    # every kind of board the stage draws comes past
    kinds = {item["kind"] for item in call.board.items}
    assert {"code", "change", "sequence", "flowchart", "table"} <= kinds, kinds  # a call draws no Mermaid
    assert any(a.startswith("page:") for a in answers)


def test_a_demo_starts_when_its_page_opens_and_next_again_back_move_through_it(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.demo = ["First board.", "Second board.", "Third board."]
            said = lambda: [e["text"] for e in call.entries if e["who"] == "claude"]  # noqa: E731
            await client.get("/api/state", headers=AUTH)
            for _ in range(50):
                if said():
                    break
                await asyncio.sleep(0.02)
            steps = [said()[-1]]
            for typed in ("next", "again", "next", "back", "start over"):
                n = len(said())
                await client.post("/api/say", json={"text": typed}, headers=AUTH)
                for _ in range(150):  # every move plays one new answer, "again" too
                    if len(said()) > n:
                        break
                    await asyncio.sleep(0.02)
                assert len(said()) == n + 1, (typed, said())
                steps.append(said()[-1])
            turn = (await client.get("/api/turn?wait=0.1", headers=AUTH)).status
            return steps, turn

    steps, turn = run(go())
    assert steps == ["First board.", "Second board.", "Second board.", "Third board.", "Second board.", "First board."]
    assert turn == 204  # nothing waits for a Claude session


def test_demo_moves_read_what_was_said():
    assert talk.demo_move("next please", 2, 9) == 3
    assert talk.demo_move("Again.", 2, 9) == 2
    assert talk.demo_move("go back", 2, 9) == 1
    assert talk.demo_move("start over", 5, 9) == 0
    assert talk.demo_move("next", 8, 9) == 8  # the last one stays


def test_the_gears_demo_opens_one_demo_call_and_keeps_it_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "open_call", lambda args, topic, out, cwd, base=None: (
        talk.Call(args, topic, out), []))
    monkeypatch.setattr(talk.speech, "ensure_running", lambda **kw: {})

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            first = await (await client.post("/api/demo", headers=AUTH)).json()
            again = await (await client.post("/api/demo", headers=AUTH)).json()
            return first, again

    first, again = run(go())
    assert first["path"].startswith("/c/") and again == first  # the open one is reused


def test_the_demo_shows_every_board_kind_and_every_way_to_steer_one():
    """What talk can draw and how a reply steers it, read from talk itself: a kind or a form added there and
    missing from demo.md fails here, so the demo cannot fall behind. (The audit-demo skill checks the rest.)"""
    text = talk.DEMO_FILE.read_text()
    kinds = set(talk.BOARD_KINDS) - {"diagram"}  # a call draws no Mermaid: a diagram becomes a flowchart
    shown = set(re.findall(r"\[\[show (\w+)", text))
    assert kinds <= shown, f"no demo answer shows: {sorted(kinds - shown)}"
    forms = {"lines": r"\[\[point[^\]]*: lines? \d", "row or cell": r"\[\[point[^\]]*: (?:row|cell) ",
             "node": r"\[\[point[^\]]*: node ", "step": r"\[\[point[^\]]*: step "}
    missing = [name for name, rx in forms.items() if not re.search(rx, text)]
    assert not missing, f"no demo answer points at a {missing}"
    for tag in ("[[next]]", "[[+ ", "[[key:", "\npage:"):
        assert tag in text, f"the demo never uses {tag.strip()}"


def test_every_demo_board_keeps_what_the_stage_keeps_true(tmp_path):
    call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Stage demo", tmp_path / "out")
    breaks = []
    for text in talk.load_demo():
        first, _, rest = text.partition("\n")
        shown = call.split_reply(rest if first.startswith("page:") else text)
        breaks += stage_rule_breaks(call, shown)
        for item in call.board.items:
            item.pop("scene", None)  # a scene belongs to the answer that compiled it
    assert breaks == []


def test_the_demos_change_board_points_at_the_lines_it_talks_about():
    """The change board's points are line numbers in today's scene.js, so an edit above them moves them."""
    text = talk.DEMO_FILE.read_text()
    lines = (talk.SKILL_DIR.parents[1] / "skills/stage/static/scene.js").read_text().split("\n")
    a, b = map(int, re.search(r"\[\[point: lines (\d+)-(\d+)\]\] And this new function reads which thing is being said", text).groups())
    assert (lines[a - 1].split("(")[0], lines[b - 1].strip()) == ("export function beingSaid", "if (Array.isArray(frame.cur)) return frame.cur;")
