"""The stage demo: `talk.py --demo` plays demo.md's answers in a real call, one per thing said, so every
board can be seen moving with the voice without a Claude session."""
import asyncio

from helpers import AUTH, make_args, run, running_app, talk


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
                await client.post("/api/say", json={"text": typed}, headers=AUTH)
                n = len(said())
                for _ in range(50):
                    if len(said()) > n - 1 and said()[-1] and len(said()) == n + 0 or len(said()) > n:
                        break
                    await asyncio.sleep(0.02)
                await asyncio.sleep(0.05)
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
