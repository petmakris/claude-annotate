"""Round 2 fixes of the talk server and guide (bulldozer bd1125b, batch server)."""
import asyncio
import json
import re
from pathlib import Path

import pytest

import talk_client
import call_page
from call_page import CallPage, needs_node, served
from helpers import AUTH, CALL, make_args, run, running_app, talk

GUIDE = talk.SKILL_DIR / "SKILL.md"
BOARDS = talk.SKILL_DIR / "references" / "boards.md"

EMPTY = "[[show table | Costs]]\n| a | b |\n|---|---|\n[[/show]]"  # a table with no body rows is refused
TABLE = "[[show table | Costs]]\n| a | b |\n|---|---|\n| x | 1 |\n| y | 2 |\n[[/show]]"


async def settle(call):
    for _ in range(100):
        if all(e.get("speech") in (None, "ready", "failed") for e in call.entries):
            return
        await asyncio.sleep(0.02)


async def reply(client, **body):
    resp = await client.post("/api/reply", json=body, headers=AUTH)
    return resp.status, await resp.json()


# -- r2-first-1: boards alone for an answer already given ---------------------------------------

def test_a_refused_board_is_mended_for_the_answer_without_saying_it_again(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("costs?", typed=True)
            await call.turns.next(timeout=1)
            first = await reply(client, id="t1", text="The costs are small. " + EMPTY)
            await settle(call)
            before = [dict(e) for e in call.entries]
            fixed = await reply(client, board_for=1, text=TABLE)
            await settle(call)
            return first, before, fixed, call

    first, before, fixed, call = run(go())
    assert first[0] == 200 and any("table" in p and "Costs" in p for p in first[1]["board_problems"])
    assert [e["who"] for e in before] == ["you", "claude"]  # the refused board left no chip
    assert fixed == (200, {"ok": True, "boards": 1, "board_problems": []})
    assert [(e["who"], e.get("answer"), e.get("repair"), e["text"]) for e in call.entries[2:]] == [("board", 1, True, "Costs")]
    answers = [e for e in call.entries if e["who"] == "claude"]
    assert len(answers) == 1 and answers[0]["text"] == "The costs are small."  # nothing said again, no new number
    assert answers[0]["cues"] == []  # the board is shown whole, with a chip and no front cue
    assert fake_spoken(call) == ["The costs are small."]
    assert call.turns.reply_state("t1") == "answered"


def fake_spoken(call):
    return [e["text"] for e in call.entries if e["who"] == "claude" and e.get("speech") != "skipped"]


def test_a_board_repair_that_is_refused_again_answers_400_with_the_board_lines(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("costs?", typed=True)
            await call.turns.next(timeout=1)
            await reply(client, id="t1", text="The costs are small. " + EMPTY)
            await settle(call)
            n = len(call.entries)
            again = await reply(client, board_for=1, text=EMPTY)
            return again, len(call.entries) == n, call.board.items

    (status, body), unchanged, items = run(go())
    assert status == 400 and unchanged and items == []
    assert body["error"] == body["board_problems"][0] and "Costs" in body["error"]


def test_a_board_repair_names_the_answer_and_holds_nothing_but_boards(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("costs?", typed=True)
            await call.turns.next(timeout=1)
            await reply(client, id="t1", text="The costs are small.")
            await settle(call)
            return [await reply(client, board_for=2, text=TABLE), await reply(client, board_for=1, status="x", text=TABLE),
                    await reply(client, board_for="1", text=TABLE), await reply(client, board_for=0, text=TABLE),
                    await reply(client, board_for=1, text=""), await reply(client, board_for=1, text="Say it again. " + TABLE),
                    await reply(client, text=TABLE, id="t1")]

    two, status, string, zero, empty, words, plain = run(go())
    assert two[0] == 400 and two[1]["error"] == "no answer 2 in this call: it holds 1"
    assert status == (400, {"error": "board_for takes only boards: no status, say or end"})
    assert string == (400, {"error": "board_for is an answer number"}) and zero[0] == 400
    assert empty[1]["error"] == "nothing to say: the reply is empty"
    # words with the boards are dropped with a board: line, the board still shown
    assert words[0] == 200 and words[1]["board_problems"] == ["a board repair says nothing: its words were dropped, the answer was said already"]
    assert plain[0] == 200 and plain[1] == {"ok": True, "ignored": "the turn was already answered; this reply was not shown or said again"}


def test_a_reply_that_names_no_answer_and_holds_only_boards_is_still_refused(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("costs?", typed=True)
            await call.turns.next(timeout=1)
            return await reply(client, id="t1", text=TABLE)

    status, body = run(go())
    assert status == 400 and "a board needs a sentence" in body["error"]


def test_a_repair_of_an_answer_set_aside_is_refused(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await call.answer("Kept but never said.", superseded="correction")
            return await reply(client, board_for=1, text=TABLE)

    status, body = run(go())
    assert status == 400 and body["error"].startswith("answer 1 was set aside")


def test_a_repair_drops_points_and_leaves_the_boards_whole_and_in_the_background_for_an_old_answer(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await call.answer("First answer.")
            await call.answer("Second answer.")
            shows = []
            call.put_on_stage = lambda item: shows.append((item["title"], call.reply_shows))
            done = await reply(client, board_for=1, text=TABLE + "[[point: row 1]]")
            await reply(client, board_for=2, text=TABLE.replace("Costs", "Prices"))
            return done, shows, call

    (status, body), shows, call = run(go())
    assert status == 200 and body["board_problems"] == [
        "points and verbs are dropped in a board repair: the answer was said already, so the board is shown whole"]
    assert shows == [("Costs", 1), ("Prices", 0)]  # answer 1 is not the one heard: it stays behind; the newest comes forward
    assert all("scene" not in i for i in call.board.items)


def test_the_client_sends_board_for_without_a_turn_id_and_prints_the_result(tmp_path, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(talk_client, "call_id_or_only", lambda c: c)
    monkeypatch.setattr(talk_client, "load_state", lambda c: {"port": 1})
    monkeypatch.setattr(talk_client, "read_stdin", lambda: TABLE)
    monkeypatch.setattr(talk_client, "send_reply", lambda call, body: (sent.append(body), (200, b'{"ok": true, "boards": 1, "board_problems": ["x"]}'))[1])
    assert talk_client.reply("c", None, None, False, board_for=2) == 0
    assert sent == [{"id": "", "end": False, "board_for": 2, "text": TABLE}]
    assert capsys.readouterr().out == "boards added to answer 2: 1\nboard: x\n"
    monkeypatch.setattr(talk_client.sys, "argv", ["talk_client.py", "reply", "--board-for", "2", "--status", "x"])
    with pytest.raises(SystemExit):
        talk_client.main()
    monkeypatch.setattr(talk_client.sys, "argv", ["talk_client.py", "reply"])
    with pytest.raises(SystemExit):
        talk_client.main()


# -- r2-tinkerer-2: the page keeps its id across a reload and gives the voice up when it closes -

def test_the_holder_releases_the_claim_and_nobody_else_can(tmp_path, monkeypatch):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            async def claim(page, **more):
                resp = await client.post("/api/player", json={"page": page, **more}, headers=AUTH)
                return resp.status, await resp.json()
            held = await claim("page-a")
            stranger = await claim("page-b", release=True)
            released = await claim("page-a", release=True)
            state = await (await client.get("/api/state?page=page-b", headers=AUTH)).json()
            after = await claim("page-b")  # not take: free, so the claim is granted at once
            return held, stranger, released, state["player"], after

    held, stranger, released, shown, after = run(go())
    assert held == (200, {"player": "page-a"}) and stranger == (200, {"player": "page-a"})
    assert released == (200, {"player": None}) and shown is None and after == (200, {"player": "page-b"})


@needs_node
def test_a_reloaded_page_keeps_its_id_and_a_new_tab_gets_its_own(tmp_path):
    html, states = served(tmp_path, ["Said to one tab."])
    first = CallPage(html, states).js("globalThis.playerReply = (b) => ({player: b.page}); await claimPlayer(false);")
    first.check("[PAGE_ID, [...new Set(claims.map((c) => c.page))], sessionStorage.dump()]")
    [[page_id, claimed, stored]] = first.run()
    assert set(claimed) == {page_id} and stored == {f"talk.page.{CALL}": page_id}
    # the same tab after a reload: the storage is kept, and the old id still holds the claim
    reload = CallPage(html, states, session=stored).js("globalThis.playerReply = (b) => ({player: page_id_held}); await claimPlayer(false);".replace("page_id_held", json.dumps(page_id)))
    reload.check("[PAGE_ID, playingElsewhere()]")
    assert reload.run() == [[page_id, False]]
    # a new tab: no storage, a new id, and the first tab still holds the voice
    tab = CallPage(html, [dict(st, player=page_id) for st in states]).js("globalThis.playerReply = () => ({player: %s}); await claimPlayer(false); await serve(1);" % json.dumps(page_id))
    tab.check("[PAGE_ID !== %s, playingElsewhere(), audio.paused, $('status').textContent]" % json.dumps(page_id))
    assert tab.run() == [[True, True, True, "Playing on another screen."]]


# A browser's Duplicate tab copies sessionStorage. The page node runs has no BroadcastChannel, so the tests give it one
# that delivers to the other channels of the same name, and (when asked) a "source tab" that holds an id and answers.
FAKE_CHANNEL = """
{
  const open = new Map();
  globalThis.BroadcastChannel = class {
    constructor(name) { this.name = name; this.onmessage = null; (open.get(name) || open.set(name, new Set()).get(name)).add(this); }
    postMessage(data) { for (const c of open.get(this.name)) if (c !== this) Promise.resolve().then(() => c.onmessage && c.onmessage({data})); }
  };
  globalThis.asked = [];
  const source = %s;
  if (source) { const ch = new BroadcastChannel("talk-page-" + JSON.parse(%s).call);
    ch.onmessage = ({data}) => { asked.push(data.t); if (data.t === "who" && data.id === source) ch.postMessage({t: "mine", id: source, to: data.nonce, nonce: "source-tab"}); }; }
}
"""


_PRELUDE = call_page.PRELUDE


def _tab(monkeypatch, html, states, *, source=None, session=None):
    cfg = re.search(r"window\.CFG = (.*?);</script>", html).group(1).replace("<\\/", "</")
    fake = FAKE_CHANNEL % (json.dumps(source), json.dumps(cfg))
    monkeypatch.setattr(call_page, "PRELUDE", _PRELUDE.replace("%(storage)s", "%(storage)s\n" + fake.replace("%", "%%")))
    return CallPage(html, states, session=session)


@needs_node
def test_a_duplicated_tab_gets_a_new_id_a_reload_keeps_its_id_and_a_new_tab_gets_its_own(tmp_path, monkeypatch):
    html, states = served(tmp_path, ["Said to one tab."])
    key = f"talk.page.{CALL}"
    # the page waits PAGE_ASK_MS for an answer before it claims, so the clock moves on
    reply = "globalThis.playerReply = (b) => ({player: b.page}); const sent = claimPlayer(false); await advance(200); await sent;"
    # Duplicate tab: the copied storage holds the source's id and the source tab, still open, says it is its own
    dup = _tab(monkeypatch, html, states, source="srcid", session={key: "srcid"}).js(reply)
    dup.check("[PAGE_ID, [...new Set(claims.map((c) => c.page))], sessionStorage.dump()[%s], asked]" % json.dumps(key))
    [[new_id, claimed, stored, asked]] = dup.run()
    assert new_id != "srcid" and len(new_id) == 8 and claimed == [new_id] and stored == new_id and asked == ["who"]
    # Reload: the old tab is gone, nobody answers, the id stays and the first claim is made under it
    reload = _tab(monkeypatch, html, states, session={key: "srcid"}).js(reply)
    reload.check("[PAGE_ID, [...new Set(claims.map((c) => c.page))], asked]")
    assert reload.run() == [["srcid", ["srcid"], []]]
    # New tab: no storage, an id of its own that differs from another tab's, and no one to change it
    tab = _tab(monkeypatch, html, states, source="srcid").js(reply)
    tab.check("[PAGE_ID, [...new Set(claims.map((c) => c.page))], sessionStorage.dump()[%s]]" % json.dumps(key))
    [[own, claimed, stored]] = tab.run()
    assert own != "srcid" and claimed == [own] and stored == own


@needs_node
def test_a_page_that_holds_the_voice_releases_it_on_pagehide_and_one_that_does_not_sends_nothing(tmp_path):
    html, states = served(tmp_path, ["Said to one tab."])
    holder = CallPage(html, states).js("globalThis.playerReply = (b) => ({player: b.page}); await claimPlayer(false); claims.length = 0; dispatchEvent(new ShimEvent('pagehide'));")
    holder.check("[claims, PAGE_ID]")
    other = CallPage(html, states).js("globalThis.playerReply = () => ({player: 'the-tv'}); await claimPlayer(false); claims.length = 0; dispatchEvent(new ShimEvent('pagehide'));")
    other.check("claims")
    [[claims, page_id]] = holder.run()
    assert claims == [{"page": page_id, "release": True}]
    assert other.run() == [[]]


# -- r2-typist-3 and r2-typist-1: the guide ------------------------------------------------------

def _draft_example():
    text = BOARDS.read_text()
    found = re.search(r"```\n(\[\[show page: draft\.txt .*?)```", text, re.S)
    assert found, "boards.md gives one example of a draft shown as a page"
    return found.group(1)


def test_the_guides_draft_example_parses_and_a_text_page_keeps_its_line_breaks(tmp_path):
    model = talk.stage_model
    (tmp_path / "draft.txt").write_text("Hi Sam,\n\nThe report is attached.\nI will call at ten.\n\nPetros\n")
    call = talk.Call(make_args(code=tmp_path), "Draft", tmp_path / "out")
    shown = call.split_reply(_draft_example())
    assert call.board.problems == [] and shown.strip()
    [item] = call.board.items
    assert (item["kind"], item["source"]["type"], item["source"]["path"]) == ("page", "file", "draft.txt")
    assert model.file_display("draft.txt") == "text" and model.file_display("draft.md") == "markdown"
    root = talk.SKILL_DIR.parent / "stage" / "static"
    assert 'pre.className = "filetext"; pre.textContent = text' in (root / "stage.js").read_text()
    assert re.search(r"pre\.filetext\{[^}]*white-space:pre", (root / "stage.css").read_text())


def test_the_guide_tells_a_session_to_put_a_copy_draft_in_a_txt_page_and_to_clear_the_stage():
    for doc in (GUIDE, BOARDS):
        text = " ".join(doc.read_text().split()).lower()
        assert "write it to a .txt file in --code and show it as a page" in text, doc.name
        assert "never leave an unrelated board in front" in text, doc.name
    assert len(GUIDE.read_text().splitlines()) < 360


def test_the_guide_names_the_copy_icon_by_where_it_is_and_never_the_internal_card_names():
    text = GUIDE.read_text()
    assert "the copy icon at the top right of the answer card" in text and "copies the whole answer" in text
    assert "Now card" not in text and "Following strip" not in text
    assert "Copy button" not in text and "Now card" in (GUIDE.parent / "references" / "call-page.md").read_text()
    assert "never say these names" in (GUIDE.parent / "references" / "call-page.md").read_text()


def test_the_guide_sends_a_refused_board_back_with_board_for_and_never_says_the_answer_again():
    for doc in (GUIDE, BOARDS):
        text = " ".join(doc.read_text().split())
        assert "--board-for" in text and "never say the answer again" in text, doc.name
