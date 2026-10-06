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
