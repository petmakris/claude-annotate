"""The server's part of the wait card: a turn in flight is told apart (sent, picked up), can be taken back after the
session collected it (cancel), and can be replaced by a correction (supersede). A replaced or amended turn's answer is
kept with its tag and never spoken; the session's client is told of a cancelled or superseded turn."""
import asyncio
import json
import os
import sys

from helpers import AUTH, CALL, add_call, run, running_app, spoken
from live_turns import STALLED_OPEN_AFTER, TurnQueue
import talk

sys.path.insert(0, os.path.dirname(__file__))
from test_talk_client import client_proc, finish, write_state  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def say(client, text, **extra):
    resp = await client.post("/api/say", json={"text": text, **extra}, headers=AUTH)
    return resp.status, await resp.json()


async def state(client):
    return await (await client.get("/api/state", headers=AUTH)).json()


async def settle(call):
    for _ in range(100):
        if all(e.get("speech") in (None, "ready", "failed", "skipped") for e in call.entries):
            return
        await asyncio.sleep(0.02)


# ---- the queue ------------------------------------------------------------------------------------------------------

def test_a_cancelled_turn_stops_working_and_its_reply_says_cancelled_and_is_dropped():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        await q.next(timeout=0.1)
        assert q.working
        assert q.cancel("t1") is True
        return q.working, q.state_of("t1"), q.reply_state("t1"), q.accept_reply("t1", final=False), q.accept_reply("t1")

    assert run(go()) == (False, "cancelled", "cancelled", "cancelled", "cancelled")


def test_only_a_collected_turn_can_be_cancelled_or_superseded():
    q = TurnQueue()
    q.offer("t1", [{"who": "you", "text": "one"}])
    assert (q.cancel("t1"), q.supersede("t1"), q.state_of("t1")) == (False, False, "pending")
    assert q.state_of("nope") == "unknown"


def test_a_cancel_reaches_the_next_doorbell_once_when_nothing_else_waits():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        await q.next(timeout=0.1)
        q.cancel("t1")
        return await q.next(timeout=0.1), await q.next(timeout=0.05)

    told, again = run(go())
    assert told == {"type": "cancelled", "turns": ["t1"]} and again is None


def test_a_cancel_rides_on_the_next_turn_when_one_is_waiting_and_a_reply_clears_the_notice():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        await q.next(timeout=0.1)
        q.cancel("t1")
        q.offer("t2", [{"who": "you", "text": "two"}])
        turn = await q.next(timeout=0.1)
        q.offer("t3", [{"who": "you", "text": "three"}])
        q.accept_reply("t1", final=False)  # the session's own reply already told it
        q2 = TurnQueue()
        q2.offer("a", [{"who": "you", "text": "x"}])
        await q2.next(timeout=0.1)
        q2.cancel("a")
        q2.accept_reply("a", final=False)
        return turn, q.notices, await q2.next(timeout=0.05)

    turn, left, quiet = run(go())
    assert turn == {"type": "turn", "id": "t2", "said": [{"who": "you", "text": "two"}], "cancelled": ["t1"]}
    assert left == [] and quiet is None


def test_a_superseded_turn_leaves_working_but_keeps_the_session_busy_until_it_replies():
    clock = Clock()
    q = TurnQueue(clock=clock)

    async def go():
        q.offer("t1", [{"who": "you", "text": "one"}])
        await q.next(timeout=0.1)
        q.offer("t2", [{"who": "you", "text": "two"}])
        assert q.supersede("t1") is True
        return q.working, q.reply_state("t1"), q.state_of("t1")

    assert run(go()) == (False, "superseded", "superseded")
    clock.now += 60
    assert q.stalled is False  # 60 s: busy with the replaced turn, the long wait applies
    clock.now += STALLED_OPEN_AFTER
    assert q.stalled is True
    assert (q.accept_reply("t1"), q.reply_state("t1"), q.stale_ids) == ("superseded", "answered", set())


def test_a_turn_merged_into_a_newer_one_is_found_under_the_newer_id():
    q = TurnQueue()
    q.offer("t1", [{"who": "you", "text": "one"}])
    q.offer("t2", [{"who": "you", "text": "two"}])
    assert (q.resolve("t1"), q.state_of("t1"), q.state_of("t2")) == ("t2", "pending", "pending")
    snap = q.snapshot()
    again = TurnQueue()
    again.restore(snap)
    assert again.resolve("t1") == "t2"


def test_the_snapshot_keeps_cancelled_and_superseded_turns_and_the_notices():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "a"}])
        await q.next(timeout=0.1)
        q.offer("t2", [{"who": "you", "text": "b"}])
        await q.next(timeout=0.1)
        q.cancel("t2")
        q.supersede("t1")
        again = TurnQueue()
        again.restore(q.snapshot())
        return again.cancelled_ids, again.stale_ids, again.notices

    assert run(go()) == ({"t2"}, {"t1"}, [{"id": "t2", "kind": "cancelled"}])


# ---- a call: where a question stands --------------------------------------------------------------------------------

def test_the_view_says_sent_then_picked_and_nothing_once_answered(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            _, body = await say(client, "How do vaccines work?")
            sent = (await state(client))["turn"]
            await call.turns.next(timeout=1)
            call.collected()
            picked = (await state(client))["turn"]
            call.turns.accept_reply("t1")
            done = (await state(client))["turn"]
            return body["entry"]["id"], sent, picked, done

    first, sent, picked, done = run(go())
    assert first == 0
    assert sent == {"entries": [{"id": 0, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None}
    assert picked["entries"] == [{"id": 0, "state": "picked"}] and picked["earlier"] == 0
    assert abs(picked["collected_at"] - talk.time.time()) < 5 and abs(picked["alive_at"] - talk.time.time()) < 5
    assert done == {"entries": [], "earlier": 0, "collected_at": None, "alive_at": None}


def test_two_messages_sent_before_pickup_are_both_in_flight_and_both_picked_together(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "one")
            await say(client, "two")
            before = (await state(client))["turn"]["entries"]
            await call.turns.next(timeout=1)
            return before, (await state(client))["turn"]["entries"]

    before, after = run(go())
    assert before == [{"id": 0, "state": "sent"}, {"id": 1, "state": "sent"}]
    assert after == [{"id": 0, "state": "picked"}, {"id": 1, "state": "picked"}]


# ---- cancel ---------------------------------------------------------------------------------------------------------

def test_cancel_before_pickup_is_a_withdraw(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "oops")
            r = await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)
            body = await r.json()
            return body, call.entries[0].get("withdrawn"), call.entries[0].get("cancelled"), call.turns.pending_id

    body, withdrawn, cancelled, pending = run(go())
    assert body == {"cancelled": True, "how": "withdrawn", "entries": [0]}
    assert withdrawn is True and cancelled is None and pending is None


def test_cancel_after_pickup_takes_back_the_turn_and_what_was_added_to_it(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan two weeks in Japan")
            await call.turns.next(timeout=1)
            await say(client, "and include Kyoto")  # said while Claude works: an addition, not collected
            r = await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)
            body = await r.json()
            view = await state(client)
            return body, view["working"], view["turn"], [(e["id"], e.get("cancelled"), e.get("withdrawn")) for e in view["entries"]], call.turns.pending_id

    body, working, turn, entries, pending = run(go())
    assert body == {"cancelled": True, "how": "cancelled", "entries": [0, 1]}
    assert working is False and turn["entries"] == [] and pending is None
    assert entries == [(0, True, True), (1, True, True)]


def test_cancel_of_an_answered_or_unknown_question_changes_nothing(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            call.turns.accept_reply("t1")
            a = await (await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)).json()
            b = await (await client.post("/api/cancel", json={"entry": 99}, headers=AUTH)).json()
            c = await client.post("/api/cancel", json={"entry": "x"}, headers=AUTH)
            return a, b, c.status

    assert run(go()) == ({"cancelled": False}, {"cancelled": False}, 400)


def test_a_reply_to_a_cancelled_turn_is_dropped_and_tells_the_session_and_takes_no_answer_number(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)
            status = await (await client.post("/api/reply", json={"id": "t1", "status": "checking"}, headers=AUTH)).json()
            final = await (await client.post("/api/reply", json={"id": "t1", "text": "Late answer."}, headers=AUTH)).json()
            return status, final, spoken(call), fake.spoken

    status, final, said, voiced = run(go())
    assert status["cancelled"] is True and status["ignored"].startswith("cancelled: the user took this turn back")
    assert final["cancelled"] is True and said == [] and voiced == []


def test_the_wrap_up_of_a_cancelled_turn_still_ends_the_call(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)
            r = await client.post("/api/reply", json={"id": "t1", "text": "Bye.", "end": True}, headers=AUTH)
            return (await r.json()), call.ended, spoken(call)

    body, ended, said = run(go())
    assert body["ok"] is True and ended == "wrapped up by Claude" and said == ["Bye."]


# ---- replace --------------------------------------------------------------------------------------------------------

def test_a_correction_of_a_question_not_collected_yet_takes_the_old_one_back(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan fourteen days")
            _, body = await say(client, "no, ten days", replaces=0)
            turn = await call.turns.next(timeout=1)
            return body, turn, call.entries[0].get("superseded"), call.entries[0].get("withdrawn")

    body, turn, superseded, withdrawn = run(go())
    assert body["replaced"] is True and body["entry"]["replaces"] == 0
    assert [l["text"] for l in turn["said"]] == ["no, ten days"] and "replaces" not in turn["said"][0]
    assert superseded is True and withdrawn is True


def test_a_correction_of_a_collected_question_marks_it_and_tells_the_session_which_turn_to_drop(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan fourteen days")
            await call.turns.next(timeout=1)
            _, body = await say(client, "no, ten days", replaces=0)
            view = await state(client)
            turn = await call.turns.next(timeout=1)
            return body, view, turn, call.entries[0].get("superseded")

    body, view, turn, superseded = run(go())
    assert body["replaced"] is True
    assert view["working"] is False and view["turn"]["entries"] == [{"id": 1, "state": "sent"}] and view["turn"]["earlier"] == 1
    assert turn["said"] == [{"who": "you", "text": "no, ten days", "replaces": "t1"}]  # no while_working: a new question
    assert superseded is True


def test_a_correction_of_an_answered_question_is_an_ordinary_new_question(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            call.turns.accept_reply("t1")
            _, body = await say(client, "next", replaces=0)
            return body, (await call.turns.next(timeout=1))["said"]

    body, said = run(go())
    assert body["replaced"] is False and "replaces" not in body["entry"] and said == [{"who": "you", "text": "next"}]


def test_replaces_must_be_a_number(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            status, body = await say(client, "x", replaces="0")
            return status, body

    assert run(go()) == (400, {"error": "replaces names the entry of the question to replace"})


def test_the_reply_to_a_replaced_question_is_kept_tagged_and_never_spoken_and_stages_no_board(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan fourteen days")
            await call.turns.next(timeout=1)
            await say(client, "no, ten days", replaces=0)
            reply = await (await client.post("/api/reply", json={"id": "t1", "text":
                "[[show table | Days]] | A | B |\n|---|---|\n| 1 | 2 | [[/show]] Fourteen days: **start** in Tokyo. [[key: fourteen]] Rail pass."},
                headers=AUTH)).json()
            await settle(call)
            claude = [e for e in call.entries if e["who"] == "claude"]
            return reply, claude, fake.spoken, len(call.board.items), len(call.keys), call.turns.stale_ids

    reply, claude, voiced, boards, keys, stale = run(go())
    assert reply["superseded"] is True and reply["note"].startswith("superseded: the user replaced this question")
    assert len(claude) == 1 and claude[0]["text"] == "Fourteen days: start in Tokyo. Rail pass."
    assert (claude[0]["superseded"], claude[0]["superseded_kind"], claude[0]["speech"], claude[0]["cues"]) == (True, "correction", "skipped", [])
    assert voiced == [] and boards == 0 and keys == 0 and stale == set()


def test_a_replaced_questions_reply_with_no_sentence_is_refused_and_takes_no_number(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await say(client, "fix", replaces=0)
            r = await client.post("/api/reply", json={"id": "t1", "text": "[[show table | T]] | A |\n|---|\n| 1 | [[/show]]"}, headers=AUTH)
            return r.status, [e for e in call.entries if e["who"] == "claude"], call.turns.reply_state("t1")

    status, claude, state_now = run(go())
    assert status == 400 and claude == [] and state_now == "superseded"


def test_a_status_for_a_replaced_question_is_not_shown_and_tells_the_session(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await say(client, "fix", replaces=0)
            body = await (await client.post("/api/reply", json={"id": "t1", "status": "digging"}, headers=AUTH)).json()
            return body, [e for e in call.entries if e["who"] == "status"]

    body, statuses = run(go())
    assert body["superseded"] is True and "Stop working on it" in body["ignored"] and statuses == []


def test_the_answer_to_a_question_added_to_since_is_kept_tagged_and_not_spoken(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan two weeks in Japan")
            await call.turns.next(timeout=1)
            await say(client, "no wait, only 10 days")  # plain Send while Claude works: an addition, uncollected
            reply = await (await client.post("/api/reply", json={"id": "t1", "text": "Fourteen days in Japan."}, headers=AUTH)).json()
            claude = [e for e in call.entries if e["who"] == "claude"]
            return reply, claude, fake.spoken

    reply, claude, voiced = run(go())
    assert reply["superseded"] is True and reply["note"].startswith("superseded: the user added to this question")
    assert (claude[0]["superseded"], claude[0]["superseded_kind"], claude[0]["speech"]) == (True, "addition", "skipped")
    assert voiced == []


def test_the_answer_to_a_question_whose_addition_was_collected_as_its_own_turn_is_kept_tagged_and_not_spoken(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan me 14 days in Japan")
            await call.turns.next(timeout=1)                      # t1 collected
            await say(client, "no wait, only 10 days, Kyoto first")  # plain Send while Claude works
            await call.turns.next(timeout=1)                      # the session collects it as t2 before it answers t1
            carried = (dict(call.said_lines[1]), call.entries[1].get("replaces"), call.turn_of[1])
            late = await (await client.post("/api/reply", json={"id": "t1", "text": "Here is the 14 day plan."}, headers=AUTH)).json()
            await settle(call)
            current = await (await client.post("/api/reply", json={"id": "t2", "text": "Ten days, Kyoto first."}, headers=AUTH)).json()
            await settle(call)
            claude = [e for e in call.entries if e["who"] == "claude"]
            return carried, late, current, claude, fake.spoken

    carried, late, current, claude, voiced = run(go())
    # the correction carries `while_working` and no `replaces`: only the Replace button sets that
    assert carried == ({"who": "you", "text": "no wait, only 10 days, Kyoto first", "while_working": True}, None, "t2")
    assert late["superseded"] is True and late["note"].startswith("superseded: the user added to this question")
    assert (claude[0]["superseded"], claude[0]["superseded_kind"], claude[0]["speech"]) == (True, "addition", "skipped")
    assert "superseded" not in current and "superseded" not in claude[1] and claude[1]["speech"] == "ready"
    assert voiced == ["Ten days, Kyoto first."]


def test_the_answer_to_a_question_replaced_by_a_correction_collected_as_its_own_turn_is_tagged_a_correction(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan me 14 days in Japan")
            await call.turns.next(timeout=1)
            await say(client, "no wait, only 10 days", replaces=0)
            await call.turns.next(timeout=1)
            late = await (await client.post("/api/reply", json={"id": "t1", "text": "Here is the 14 day plan."}, headers=AUTH)).json()
            await settle(call)
            claude = [e for e in call.entries if e["who"] == "claude"]
            return late, claude, fake.spoken

    late, claude, voiced = run(go())
    assert late["superseded"] is True and late["note"].startswith("superseded: the user replaced this question")
    assert (claude[0]["superseded_kind"], claude[0]["speech"]) == ("correction", "skipped") and voiced == []


def test_an_addition_the_user_took_back_leaves_the_answer_to_the_question_spoken(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan me 14 days in Japan")
            await call.turns.next(timeout=1)
            await say(client, "no wait, only 10 days")
            await call.turns.next(timeout=1)
            cancelled = call.cancel(1)["cancelled"]
            reply = await (await client.post("/api/reply", json={"id": "t1", "text": "Here is the 14 day plan."}, headers=AUTH)).json()
            await settle(call)
            return cancelled, reply, fake.spoken

    cancelled, reply, voiced = run(go())
    assert cancelled is True and "superseded" not in reply and voiced == ["Here is the 14 day plan."]


def test_an_answer_with_nothing_added_since_is_spoken_as_ever(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await client.post("/api/reply", json={"id": "t1", "text": "Plain answer."}, headers=AUTH)
            await settle(call)
            return [e for e in call.entries if e["who"] == "claude"][0], fake.spoken

    entry, voiced = run(go())
    assert "superseded" not in entry and entry["speech"] == "ready" and voiced == ["Plain answer."]


def test_a_skipped_answer_is_read_when_the_reader_asks(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await say(client, "fix", replaces=0)
            await client.post("/api/reply", json={"id": "t1", "text": "The old answer."}, headers=AUTH)
            r = await client.post("/api/speak", json={"entry": 2}, headers=AUTH)
            await settle(call)
            again = await client.post("/api/speak", json={"entry": 2}, headers=AUTH)
            return r.status, again.status, call.entries[2]["speech"], call.entries[2]["superseded"], fake.spoken

    assert run(go()) == (200, 409, "ready", True, ["The old answer."])


def test_the_turns_of_a_call_survive_a_restart(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "q")
            await call.turns.next(timeout=1)
            await say(client, "fix", replaces=0)
            state_now = json.loads(json.dumps(call.snapshot()))
            again = talk.Call.restore(state_now)
            return again.turn_view(), again.turns.stale_ids

    view, stale = run(go())
    assert view["entries"] == [{"id": 1, "state": "sent"}] and view["earlier"] == 1 and stale == {"t1"}


# ---- the session's client -------------------------------------------------------------------------------------------

def test_the_doorbell_prints_a_cancelled_turn_for_the_session(tmp_path):
    state_file = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            write_state(state_file, client.server.port)
            await say(client, "q")
            await call.turns.next(timeout=1)
            await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)
            return await finish(await client_proc(state_file, "doorbell", "--wait", "5"))

    code, out, _ = run(go())
    assert code == 0 and out.startswith("TALK_CANCELLED ")
    assert json.loads(out.split(" ", 1)[1]) == {"turns": ["t1"]}


def test_the_client_prints_what_became_of_a_cancelled_turns_reply(tmp_path):
    state_file = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            write_state(state_file, client.server.port)
            await say(client, "q")
            await call.turns.next(timeout=1)
            await client.post("/api/cancel", json={"entry": 0}, headers=AUTH)
            return await finish(await client_proc(state_file, "reply", "t1"), "Late.")

    code, out, _ = run(go())
    assert code == 0 and out.startswith("cancelled: the user took this turn back after you collected it")


def test_the_client_prints_a_superseded_note_after_sent(tmp_path):
    state_file = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            write_state(state_file, client.server.port)
            await say(client, "q")
            await call.turns.next(timeout=1)
            await say(client, "fix", replaces=0)
            return await finish(await client_proc(state_file, "reply", "t1"), "Old answer.")

    code, out, _ = run(go())
    lines = out.strip().splitlines()
    assert code == 0 and lines[0] == "sent" and lines[1].startswith("superseded: the user replaced this question")


def test_a_correction_sets_aside_everything_in_flight_the_collected_turn_and_what_was_added(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await say(client, "Plan fourteen days")
            await call.turns.next(timeout=1)
            await say(client, "and include Osaka")  # an addition, not collected
            _, body = await say(client, "forget it: ten days only", replaces=0)
            view = await state(client)
            turn = await call.turns.next(timeout=1)
            return body, view["turn"], [(e["id"], e.get("superseded"), e.get("withdrawn")) for e in call.entries if e["who"] == "you"], turn["said"]

    body, turn_view, flags, said = run(go())
    assert body["replaced"] is True
    assert turn_view["entries"] == [{"id": 2, "state": "sent"}] and turn_view["earlier"] == 1
    assert flags == [(0, True, None), (1, True, True), (2, None, None)]
    assert said == [{"who": "you", "text": "forget it: ten days only", "replaces": "t1"}]
