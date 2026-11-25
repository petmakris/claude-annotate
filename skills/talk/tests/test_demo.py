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
        call.board.problems.clear()
        call.split_reply(text)
        assert call.board.problems == [], (text[:60], call.board.problems)
    # every kind of board the stage draws comes past
    kinds = {item["kind"] for item in call.board.items}
    assert {"code", "change", "sequence", "flowchart", "map", "table", "page"} <= kinds, kinds  # a call draws no Mermaid


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
    kinds = set(talk.BOARD_KINDS) - {"diagram", "scene"}  # no Mermaid (a diagram becomes a flowchart); scenes are retired
    shown = set(re.findall(r"\[\[show (\w+)", text))
    assert kinds <= shown, f"no demo answer shows: {sorted(kinds - shown)}"
    forms = {"lines": r"\[\[point[^\]]*: lines? \d", "row or cell": r"\[\[point[^\]]*: (?:row|cell) ",
             "node": r"\[\[point[^\]]*: node ", "step": r"\[\[point[^\]]*: step ", "box": r"\[\[point[^\]]*: box "}
    missing = [name for name, rx in forms.items() if not re.search(rx, text)]
    assert not missing, f"no demo answer points at a {missing}"
    for tag in ("[[next]]", "[[+ ", "[[key:"):
        assert tag in text, f"the demo never uses {tag.strip()}"


def test_every_demo_board_keeps_what_the_stage_keeps_true(tmp_path):
    call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Stage demo", tmp_path / "out")
    breaks = []
    for text in talk.load_demo():
        shown = call.split_reply(text)
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


def test_the_demos_small_diagram_shows_whole_and_lights_the_part_each_sentence_names(tmp_path):
    call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Stage demo", tmp_path / "out")
    text = next(a for a in talk.load_demo() if "[[show flowchart | Where a turn waits]]" in a)
    shown = call.split_reply(text)
    scene = call.board.items[-1]["scene"]
    assert scene["start"] == "full" and [f["cur"] for f in scene["frames"]] == [
        [], ["node:page"], ["node:talk"], ["node:claude"], []]
    assert call.board.problems == [] and stage_rule_breaks(call, shown) == []


# ---- the guide a session reads (SKILL.md, references/, demo.md): what it must teach, and that what it shows runs ----
GUIDE = talk.SKILL_DIR / "SKILL.md"


def _tables(text):
    """Every markdown table of a document as a list of rows, each row its cells split at unescaped pipes."""
    out, run = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            run.append([c.strip() for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])])
        elif run:
            out.append(run)
            run = []
    return out


def test_the_guide_opens_with_a_decision_table_that_puts_the_table_board_last():
    text = GUIDE.read_text()
    decision, boards = text.index("### Choose the board by the question"), text.index("### Teaching with the board")
    assert decision < boards < text.index("| Board | Use it for | Tag |")
    table = next(t for t in _tables(text) if t[0][0].startswith("The question is about"))
    assert [row[1] for row in table[2:]] == ["sequence", "sequence with compare (`compare`)", "map", "flowchart",
                                             "bars", "graph", "code, change", "table, last"]
    assert "could the viewer say what each column means?" in text.lower()
    assert "5 to 8 rows" in text


def test_every_table_of_the_guide_has_the_same_cells_in_every_row():
    """An unescaped pipe in a cell (a `[[show sequence | T]]` tag) splits it, and the row grows a cell: the compare
    row of the board table once did, and its tag was lost."""
    for doc in (GUIDE, *sorted((GUIDE.parent / "references").glob("*.md"))):
        for table in _tables(doc.read_text()):
            widths = {len(row) for row in table}
            assert len(widths) == 1, (doc.name, table[0], widths)


def test_the_guides_boards_table_tags_all_survive_their_pipes():
    table = next(t for t in _tables(GUIDE.read_text()) if t[0][0] == "Board")
    tags = {row[0]: row[2] for row in table[2:]}
    assert set(tags) >= {"sequence", "sequence with compare", "map", "flowchart", "bars", "graph", "code", "change", "table", "page", "screen"}
    for name, cell in tags.items():
        assert re.search(r"\[\[show [a-z]+(?::[^\]]*)? \\\| [^\]]+\]\]|\[\[show [a-z]+: [^\]|]+ \\\| [^\]]+\]\]", cell), (name, cell)


def test_the_guides_references_exist_and_are_linked_from_it():
    text = GUIDE.read_text()
    for name in ("call-page", "server", "boards"):
        assert (GUIDE.parent / "references" / f"{name}.md").is_file()
        assert f"references/{name}.md" in text
    assert len(text.splitlines()) < 330 and max(len(ln) for ln in text.splitlines()) < 700  # no 3,000 character lines
    assert "scenes and stops" not in (talk.SKILL_DIR.parent / "stage" / "SKILL.md").read_text().lower()


def test_every_example_the_guide_gives_is_a_spec_the_real_validators_accept(tmp_path):
    text = GUIDE.read_text()
    examples = [b for b in re.findall(r"```\n(\[\[show .*?)```", text, re.S) if not b.startswith("[[show change")]
    assert len(examples) >= 6  # a map, a wait, a compare, bars, a graph and a flowchart
    for n, example in enumerate(examples):
        call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Guide", tmp_path / f"out{n}")
        shown = call.split_reply(example)
        assert call.board.problems == [], (example[:60], call.board.problems)
        assert stage_rule_breaks(call, shown) == []


def test_the_demo_teaches_a_zoned_map_a_never_arrow_a_wait_and_a_real_grid(tmp_path):
    call = talk.Call(make_args(code=talk.SKILL_DIR.parents[1]), "Stage demo", tmp_path / "out")
    for text in talk.load_demo():
        call.split_reply(text)
    boards = {item["title"]: item for item in call.board.items}
    spec = boards["Where talk's parts live"]["visual"]["spec"]
    assert any("port 8766" in z["label"] for z in spec["zones"])
    never = [a for a in spec["arrows"] if a.get("label") == "never"]
    assert len(never) == 1 and never[0]["tone"] == "red" and never[0]["dash"] is True
    wait = boards["The doorbell waits"]["visual"]["spec"]["steps"]
    assert [s.get("reply_to") for s in wait] == [None, None, "w1"]
    grid = _tables(boards["Four boards, picked by hand"]["body"])[0]
    assert len(grid) == 6 and {len(row) for row in grid} == {4}  # a header, a separator and four things on three measures
