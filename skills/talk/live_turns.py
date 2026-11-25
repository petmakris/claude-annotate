"""The turn queue between the call page and the Claude Code session that answers it.

The page offers a turn each time the user sends something. Turns sent before the session
collects them are merged into one. The session collects a turn with a long poll (the
doorbell) and answers it once; a turn the user sent meanwhile waits for the next doorbell.
"""

from __future__ import annotations

import asyncio
import time

STALLED_AFTER = 20.0  # a turn nobody collected for this long, with no tool call either: the page says it was not picked up
ACTIVE_WITHIN = 20.0  # tool calls this recent mean the session is alive, just busy
STALLED_OPEN_AFTER = 180.0  # a turn is waiting while the session answers an older one (or a collected turn went unanswered): silent this long, the page says Claude has gone quiet


class TurnQueue:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.pending_id: str | None = None
        self.lines: list[dict] = []
        self.offered_at = 0.0
        self.offered_ids: set[str] = set()
        self.open_ids: set[str] = set()  # collected, not yet answered
        self.folded_ids: set[str] = set()  # collected earlier, left open when a newer turn was collected: still answerable, no longer "working"
        self.cancelled_ids: set[str] = set()  # collected, then taken back by the user: its reply is dropped, and the session is told
        self.stale_ids: set[str] = set()  # collected, then replaced by a correction: its reply is kept but never spoken
        self.alias: dict[str, str] = {}  # a turn id merged into a newer one before any doorbell collected it -> that one
        self.notices: list[dict] = []  # {"id", "kind"}: a cancel the session has not been told of yet
        self.collected_at = float("-inf")  # when a turn was last collected
        self.last_activity = float("-inf")
        self.waiters = 0
        self._newest_waiter = 0
        self.ended: dict | None = None
        self.suspended = False
        self.end_collected = asyncio.Event()
        self._changed = asyncio.Event()

    def offer(self, turn_id: str, lines: list[dict]) -> None:
        """A new turn. One still waiting to be collected is merged into it under the new id."""
        if self.pending_id:
            self.offered_ids.discard(self.pending_id)
            self.alias[self.pending_id] = turn_id
        self.pending_id = turn_id
        self.offered_ids.add(turn_id)
        self.lines.extend(lines)
        self.offered_at = self.clock()
        self._changed.set()

    def withdraw(self, line: dict) -> bool:
        """Take back a line no doorbell has collected yet; False once one has."""
        for i, held in enumerate(self.lines):
            if held is line or held == line:
                del self.lines[i]
                if not self.lines and self.pending_id:
                    self.offered_ids.discard(self.pending_id)
                    self.pending_id = None
                self._changed.set()
                return True
        return False

    def put_back(self, event: dict) -> None:
        """A collected turn whose doorbell went away before it was printed: offer it again."""
        if event.get("type") != "turn":
            return
        self.open_ids.discard(event["id"])
        self.folded_ids.discard(event["id"])
        if self.pending_id:
            self.offered_ids.discard(self.pending_id)
            self.alias[self.pending_id] = event["id"]
        self.pending_id = event["id"]
        self.lines = list(event["said"]) + self.lines
        self._changed.set()

    def finish(self, reason: str, transcript: str) -> None:
        self.ended = {"reason": reason, "transcript": transcript}
        self._changed.set()

    def suspend(self) -> None:
        """The server is handing the call over: every doorbell waiting now returns empty and re-arms."""
        self.suspended = True
        self._changed.set()

    def resolve(self, turn_id: str) -> str:
        """The turn a line was finally collected in: an uncollected turn is merged into the next one offered."""
        seen = set()
        while turn_id in self.alias and turn_id not in seen:
            seen.add(turn_id)
            turn_id = self.alias[turn_id]
        return turn_id

    def state_of(self, turn_id: str) -> str:
        """Where a turn stands: 'pending' (offered, no doorbell has collected it), 'open' (collected, not answered),
        'folded' (as open, but a newer turn was collected after it), 'cancelled' or 'superseded' (collected, then
        taken back or replaced, its reply still to come), 'answered' or 'unknown'."""
        turn_id = self.resolve(turn_id)
        if turn_id == self.pending_id:
            return "pending"
        if turn_id in self.cancelled_ids:
            return "cancelled"
        if turn_id in self.stale_ids:
            return "superseded"
        if turn_id in self.open_ids:
            return "open"
        if turn_id in self.folded_ids:
            return "folded"
        return "answered" if turn_id in self.offered_ids else "unknown"

    def cancel(self, turn_id: str) -> bool:
        """The user takes back a turn the session has collected. It stops counting as working; the session is told
        (its reply says so, and the next doorbell carries a notice if no reply comes first); a reply that still
        arrives is dropped. False when the turn is not collected and unanswered."""
        turn_id = self.resolve(turn_id)
        if turn_id not in self.open_ids and turn_id not in self.folded_ids:
            return False
        self.open_ids.discard(turn_id)
        self.folded_ids.discard(turn_id)
        self.cancelled_ids.add(turn_id)
        self.notices.append({"id": turn_id, "kind": "cancelled"})
        self._changed.set()
        return True

    def supersede(self, turn_id: str) -> bool:
        """A correction replaces a turn the session has collected. It stops counting as working, but the session is
        busy with it until it replies, so the stall clock still waits for that reply; the reply is kept, never spoken."""
        turn_id = self.resolve(turn_id)
        if turn_id not in self.open_ids and turn_id not in self.folded_ids:
            return False
        self.open_ids.discard(turn_id)
        self.folded_ids.discard(turn_id)
        self.stale_ids.add(turn_id)
        self._changed.set()
        return True

    def snapshot(self) -> dict:
        return {"pending": self.pending_id, "lines": list(self.lines), "offered": sorted(self.offered_ids),
                "open": sorted(self.open_ids), "folded": sorted(self.folded_ids), "ended": self.ended,
                "cancelled": sorted(self.cancelled_ids), "stale": sorted(self.stale_ids), "alias": dict(self.alias),
                "notices": list(self.notices)}

    def restore(self, data: dict) -> None:
        self.pending_id = data.get("pending")
        self.lines = list(data.get("lines") or [])
        self.offered_ids = set(data.get("offered") or [])
        self.open_ids = set(data.get("open") or [])
        self.folded_ids = set(data.get("folded") or [])
        self.cancelled_ids = set(data.get("cancelled") or [])
        self.stale_ids = set(data.get("stale") or [])
        self.alias = dict(data.get("alias") or {})
        self.notices = list(data.get("notices") or [])
        self.ended = data.get("ended") or None
        self.offered_at = self.clock()

    def state_key(self) -> tuple:
        return (self.pending_id, len(self.lines), tuple(sorted(self.offered_ids)), tuple(sorted(self.open_ids)),
                tuple(sorted(self.folded_ids)), tuple(sorted(self.cancelled_ids)), tuple(sorted(self.stale_ids)),
                len(self.notices), bool(self.ended))

    async def next(self, timeout: float) -> dict | None:
        """The next turn or the end; None on timeout. Only the newest waiter can receive a turn:
        an older one still waiting (a doorbell left over from a re-arm) gets {"type": "superseded"}."""
        self._newest_waiter += 1
        me = self._newest_waiter
        self.waiters += 1
        self._changed.set()  # wake an older waiter so it sees it has been superseded
        try:
            while True:
                if me != self._newest_waiter:
                    return {"type": "superseded"}
                if self.ended:
                    self.end_collected.set()
                    return {"type": "end", **self.ended}
                if self.suspended:
                    return None
                if self.notices and not self.pending_id:
                    told, self.notices = self.notices, []
                    return {"type": "cancelled", "turns": [n["id"] for n in told]}
                if self.pending_id:
                    turn = {"type": "turn", "id": self.pending_id, "said": self.lines}
                    if self.notices:  # a turn taken back since the session last heard: told with the next one
                        turn["cancelled"], self.notices = [n["id"] for n in self.notices], []
                    # A turn collected and never answered is folded into this one: it can still be answered
                    # (that answer is shown), but it no longer keeps the call "working".
                    self.folded_ids |= self.open_ids
                    self.open_ids = {self.pending_id}
                    self.collected_at = self.clock()
                    self.pending_id, self.lines = None, []
                    return turn
                self._changed.clear()
                try:
                    await asyncio.wait_for(self._changed.wait(), timeout)
                except asyncio.TimeoutError:
                    return None
        finally:
            self.waiters -= 1

    def note_activity(self) -> None:
        self.last_activity = self.clock()

    def reply_state(self, turn_id: str) -> str:
        """What accept_reply would say, with nothing changed: 'ok', 'answered', 'cancelled' (the user took the turn
        back after it was collected), 'superseded' (a correction replaced it) or 'unknown'."""
        if turn_id in self.cancelled_ids:
            return "cancelled"
        if turn_id in self.stale_ids:
            return "superseded"
        if turn_id not in self.offered_ids and turn_id not in self.folded_ids:
            return "unknown"
        if turn_id in self.folded_ids or turn_id in self.open_ids:
            return "ok"
        return "answered"

    def accept_reply(self, turn_id: str, final: bool = True) -> str:
        """'ok', 'answered' (a status after the answer, or a second answer), 'cancelled', 'superseded' or 'unknown'.
        Any reply to a cancelled turn tells the session what happened, so its notice is dropped; the final reply to a
        cancelled or superseded turn closes it."""
        state = self.reply_state(turn_id)
        if state == "cancelled":
            self.notices = [n for n in self.notices if n["id"] != turn_id]
            if final:
                self.cancelled_ids.discard(turn_id)
        elif state == "superseded":
            if final:
                self.stale_ids.discard(turn_id)
        elif state == "ok" and final:
            if turn_id in self.folded_ids:
                self.folded_ids.discard(turn_id)
            else:
                self.open_ids.discard(turn_id)
        return state

    @property
    def working(self) -> bool:
        return bool(self.open_ids)

    @property
    def listening(self) -> bool:
        """A doorbell is waiting right now: a session is there to collect the next turn."""
        return self.waiters > 0

    @property
    def stalled(self) -> bool:
        now = self.clock()
        if self.waiters:
            return False
        held = self.open_ids or self.stale_ids  # a replaced turn the session has not replied to still keeps it busy
        if self.pending_id is None:
            # A collected turn nobody answers, and no doorbell back: the session died or was interrupted.
            return bool(self.open_ids) and now - max(self.collected_at, self.last_activity) > STALLED_OPEN_AFTER
        if held:
            # The session is answering an older turn: it is busy, not stalled, until it has been silent for long.
            return now - max(self.collected_at, self.last_activity, self.offered_at) > STALLED_OPEN_AFTER
        return now - self.offered_at > STALLED_AFTER and now - self.last_activity > ACTIVE_WITHIN
