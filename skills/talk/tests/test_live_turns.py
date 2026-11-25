import asyncio

from helpers import run
from live_turns import STALLED_AFTER, TurnQueue


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_turn_is_collected_once():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "hi"}])
        first = await q.next(timeout=0.1)
        second = await q.next(timeout=0.1)
        return first, second

    first, second = run(go())
    assert first == {"type": "turn", "id": "t1", "said": [{"who": "you", "text": "hi"}]}
    assert second is None


def test_turns_sent_before_collection_merge_under_the_newer_id():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        q.offer("t2", [{"who": "you", "text": "two"}])
        return await q.next(timeout=0.1), q.accept_reply("t1")

    turn, old = run(go())
    assert turn["id"] == "t2" and [line["text"] for line in turn["said"]] == ["one", "two"]
    assert old == "unknown"


def test_a_collected_turn_can_be_answered_after_a_newer_one_arrives():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        await q.next(timeout=0.1)
        q.offer("t2", [{"who": "you", "text": "two"}])
        return q.accept_reply("t1"), (await q.next(timeout=0.1))["id"]

    assert run(go()) == ("ok", "t2")


def test_a_status_keeps_the_turn_open_and_the_answer_closes_it():
    async def go():
        q = TurnQueue()
        q.offer("t1", [])
        await q.next(timeout=0.1)
        status = q.accept_reply("t1", final=False)
        working = q.working
        answer = q.accept_reply("t1")
        return status, working, answer, q.working, q.accept_reply("t1", final=False)

    assert run(go()) == ("ok", True, "ok", False, "answered")


def test_an_older_doorbell_is_superseded_by_a_newer_one():
    async def go():
        q = TurnQueue()
        older = asyncio.create_task(q.next(timeout=2))
        await asyncio.sleep(0.05)
        newer = asyncio.create_task(q.next(timeout=2))
        await asyncio.sleep(0.05)
        q.offer("t1", [])
        return await older, (await newer)["id"]

    old, new = run(go())
    assert old == {"type": "superseded"} and new == "t1"


def test_the_end_reaches_the_doorbell():
    async def go():
        q = TurnQueue()
        q.finish("ended from the page", "/x/transcript.md")
        return await q.next(timeout=0.1), q.end_collected.is_set()

    event, collected = run(go())
    assert event == {"type": "end", "reason": "ended from the page", "transcript": "/x/transcript.md"}
    assert collected


def test_put_back_offers_the_turn_again():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        turn = await q.next(timeout=0.1)
        q.put_back(turn)
        return await q.next(timeout=0.1)

    assert run(go())["id"] == "t1"


def test_stalled_only_when_nobody_collects_and_nothing_runs():
    clock = Clock()
    q = TurnQueue(clock=clock)
    q.offer("t1", [])
    clock.now += STALLED_AFTER + 1
    assert q.stalled
    q.note_activity()
    assert not q.stalled


def test_a_doorbell_that_returned_empty_still_lets_a_turn_count_as_stalled():
    async def go():
        clock = Clock()
        q = TurnQueue(clock=clock)
        assert await q.next(timeout=0.01) is None  # a doorbell rang and went away
        q.offer("t1", [{"who": "you", "text": "hi"}])
        clock.now += STALLED_AFTER + 1
        return q.waiters, q.stalled

    assert run(go()) == (0, True)


def test_a_stall_needs_both_the_offer_and_the_last_tool_call_to_be_old():
    clock = Clock()
    q = TurnQueue(clock=clock)
    q.offer("t1", [{"who": "you", "text": "hi"}])
    q.note_activity()
    clock.now += 19.5
    assert not q.stalled  # a tool call in the last 20 s: alive, just busy
    clock.now += 1.0
    assert q.stalled


def test_a_turn_put_back_while_a_newer_one_waits_absorbs_it():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "first"}])
        turn = await q.next(timeout=0.1)
        q.offer("t2", [{"who": "you", "text": "second"}])
        q.put_back(turn)  # the doorbell that took t1 went away before printing it
        return q, await q.next(timeout=0.1)

    q, again = run(go())
    assert again["id"] == "t1" and [x["text"] for x in again["said"]] == ["first", "second"]
    assert q.accept_reply("t2") == "unknown"  # t2 was merged into t1
    assert q.accept_reply("t1") == "ok"


def test_a_turn_collected_and_never_answered_does_not_keep_the_call_working_once_a_later_one_is_answered():
    async def go():
        q = TurnQueue()
        q.offer("t1", [{"who": "you", "text": "one"}])
        await q.next(timeout=0.1)  # collected, never answered
        q.offer("t2", [{"who": "you", "text": "two"}])
        await q.next(timeout=0.1)
        working_on_t2 = q.working
        final = q.accept_reply("t2")
        return working_on_t2, final, q.working, sorted(q.open_ids), sorted(q.folded_ids)

    assert run(go()) == (True, "ok", False, [], ["t1"])


def test_the_folded_turn_can_still_be_answered_and_shows_once():
    async def go():
        q = TurnQueue()
        q.offer("t1", [])
        await q.next(timeout=0.1)
        q.offer("t2", [])
        await q.next(timeout=0.1)
        return q.accept_reply("t1"), q.accept_reply("t1"), q.working

    assert run(go()) == ("ok", "answered", True)


def test_a_turn_waiting_while_claude_answers_the_previous_one_is_not_stalled_until_long_silence():
    async def go():
        clock = Clock()
        q = TurnQueue(clock=clock)
        q.offer("t1", [])
        await q.next(timeout=0.1)  # Claude is answering t1
        q.offer("t2", [])
        clock.now += 60
        busy = q.stalled
        clock.now += 200
        return busy, q.stalled

    assert run(go()) == (False, True)


def test_a_turn_nobody_collects_is_still_stalled_after_the_wait():
    async def go():
        clock = Clock()
        q = TurnQueue(clock=clock)
        q.offer("t1", [])
        clock.now += STALLED_AFTER + 1
        return q.stalled

    assert run(go()) is True


def test_the_queue_snapshot_keeps_the_folded_turns_and_the_end():
    async def go():
        q = TurnQueue()
        q.offer("t1", [])
        await q.next(timeout=0.1)
        q.offer("t2", [])
        await q.next(timeout=0.1)
        q.finish("done", "/t/transcript.md")
        again = TurnQueue()
        again.restore(q.snapshot())
        return sorted(again.folded_ids), sorted(again.open_ids), again.ended

    assert run(go()) == (["t1"], ["t2"], {"reason": "done", "transcript": "/t/transcript.md"})
