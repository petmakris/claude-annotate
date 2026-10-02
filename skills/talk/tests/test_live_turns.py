import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_turns import TurnQueue  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def said(*texts):
    return [{"who": "you", "text": t} for t in texts]


def test_delivers_an_offered_turn():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("hello"))
        return await q.next(timeout=1)

    assert asyncio.run(go()) == {"type": "turn", "id": "d1", "said": said("hello")}


def test_a_waiting_doorbell_wakes_when_a_turn_is_offered():
    async def go():
        q = TurnQueue()
        waiter = asyncio.create_task(q.next(timeout=5))
        await asyncio.sleep(0.01)
        q.offer("d1", said("hi"))
        return await waiter

    assert asyncio.run(go())["id"] == "d1"


def test_times_out_when_there_is_nothing_to_deliver():
    async def go():
        return await TurnQueue().next(timeout=0.05)

    assert asyncio.run(go()) is None


def test_turns_offered_before_collection_merge_into_the_latest():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("first"))
        q.offer("d2", said("second"))
        return await q.next(timeout=1)

    assert asyncio.run(go()) == {"type": "turn", "id": "d2", "said": said("first", "second")}


def test_a_delivered_turn_is_not_delivered_twice():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("hello"))
        await q.next(timeout=1)
        return await q.next(timeout=0.05)

    assert asyncio.run(go()) is None


def test_a_reply_to_a_superseded_turn_is_refused():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("one"))
        await q.next(timeout=1)
        q.offer("d2", said("two"))
        return q.accept_reply("d1"), q.accept_reply("d2")

    assert asyncio.run(go()) == (False, True)


def test_a_status_then_a_reply_to_the_live_turn_are_both_accepted():
    q = TurnQueue()
    q.offer("d1", said("one"))
    assert q.accept_reply("d1") and q.accept_reply("d1")


def test_the_end_is_delivered_and_marked_collected():
    async def go():
        q = TurnQueue()
        q.finish("learner finished", "/x/transcript.md")
        event = await q.next(timeout=1)
        return event, q.end_collected.is_set()

    event, collected = asyncio.run(go())
    assert event == {"type": "end", "reason": "learner finished", "transcript": "/x/transcript.md"}
    assert collected


def test_the_end_wins_over_a_pending_turn():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("late words"))
        q.finish("ended from the page", "/x/transcript.md")
        return await q.next(timeout=1)

    assert asyncio.run(go())["type"] == "end"


def test_put_back_restores_a_turn_before_newer_lines():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("first"))
        event = await q.next(timeout=1)
        q.offer("d2", said("second"))
        q.put_back(event)
        return await q.next(timeout=1)

    assert asyncio.run(go()) == {"type": "turn", "id": "d2", "said": said("first", "second")}


def test_busy_alert_fires_once_after_eight_seconds_without_a_reply():
    async def go():
        clock = Clock()
        q = TurnQueue(clock)
        q.offer("d1", said("hello"))
        await q.next(timeout=1)
        clock.t += 7.9
        first = q.check()
        clock.t += 0.2
        second = q.check()
        clock.t += 5
        third = q.check()
        return first, second, third

    assert asyncio.run(go()) == (None, "busy", None)


def test_no_busy_alert_once_the_turn_is_answered():
    async def go():
        clock = Clock()
        q = TurnQueue(clock)
        q.offer("d1", said("hello"))
        await q.next(timeout=1)
        q.accept_reply("d1")
        clock.t += 30
        return q.check()

    assert asyncio.run(go()) is None


def test_offline_alert_fires_once_when_no_doorbell_collects_a_turn():
    clock = Clock()
    q = TurnQueue(clock)
    q.offer("d1", said("hello"))
    clock.t += 19.9
    assert q.check() is None
    clock.t += 0.2
    assert q.check() == "offline"
    assert q.check() is None


def test_alerts_reset_for_the_next_turn():
    clock = Clock()
    q = TurnQueue(clock)
    q.offer("d1", said("hello"))
    clock.t += 21
    assert q.check() == "offline"
    q.offer("d2", said("again"))
    clock.t += 21
    assert q.check() == "offline"


def test_working_is_true_between_delivery_and_the_first_reply():
    async def go():
        q = TurnQueue()
        q.offer("d1", said("hello"))
        before = q.working
        await q.next(timeout=1)
        during = q.working
        q.accept_reply("d1")
        return before, during, q.working

    assert asyncio.run(go()) == (False, True, False)


def test_a_status_keeps_the_turn_working_but_stops_the_busy_alert():
    async def go():
        clock = Clock()
        q = TurnQueue(clock)
        q.offer("d1", said("check jira"))
        await q.next(timeout=1)
        q.accept_reply("d1", final=False)
        clock.t += 9
        return q.working, q.check()

    assert asyncio.run(go()) == (True, None)


def test_a_newer_waiter_supersedes_an_older_one_so_only_it_gets_the_turn():
    async def go():
        q = TurnQueue()
        older = asyncio.create_task(q.next(timeout=5))
        await asyncio.sleep(0.01)
        newer = asyncio.create_task(q.next(timeout=5))
        await asyncio.sleep(0.01)
        q.offer("d1", said("hi"))
        return await older, await newer

    older, newer = asyncio.run(go())
    assert older == {"type": "superseded"}
    assert newer["id"] == "d1"


def test_no_offline_alert_while_the_session_is_busy_with_tools():
    clock = Clock()
    q = TurnQueue(clock)
    q.offer("d1", said("hello"))
    clock.t += 15
    q.note_activity()
    clock.t += 10
    assert q.check() is None
    clock.t += 21
    assert q.check() == "offline"


def test_offered_turns_stay_known_after_they_are_superseded():
    q = TurnQueue()
    q.offer("d1", said("one"))
    q.offer("d2", said("two"))
    assert q.known("d1") and q.known("d2") and not q.known("d3")
