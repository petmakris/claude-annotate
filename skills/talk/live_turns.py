"""The turn queue between the call page and the Claude Code session that answers it.

The page offers a turn each time the user sends something. Turns sent before the session
collects them are merged into one. The session collects a turn with a long poll (the
doorbell) and answers it once; a turn the user sent meanwhile waits for the next doorbell.
"""

from __future__ import annotations

import asyncio
import time

STALLED_AFTER = 20.0  # a turn nobody collected for this long, with no tool call either: check the terminal
ACTIVE_WITHIN = 20.0  # tool calls this recent mean the session is alive, just busy


class TurnQueue:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.pending_id: str | None = None
        self.lines: list[dict] = []
        self.offered_at = 0.0
        self.offered_ids: set[str] = set()
        self.open_ids: set[str] = set()  # collected, not yet answered
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
        if self.pending_id:
            self.offered_ids.discard(self.pending_id)
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

    def snapshot(self) -> dict:
        return {"pending": self.pending_id, "lines": list(self.lines), "offered": sorted(self.offered_ids),
                "open": sorted(self.open_ids)}

    def restore(self, data: dict) -> None:
        self.pending_id = data.get("pending")
        self.lines = list(data.get("lines") or [])
        self.offered_ids = set(data.get("offered") or [])
        self.open_ids = set(data.get("open") or [])
        self.offered_at = self.clock()

    def state_key(self) -> tuple:
        return self.pending_id, len(self.lines), tuple(sorted(self.offered_ids)), tuple(sorted(self.open_ids))

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
                if self.pending_id:
                    turn = {"type": "turn", "id": self.pending_id, "said": self.lines}
                    self.open_ids.add(self.pending_id)
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

    def accept_reply(self, turn_id: str, final: bool = True) -> str:
        """'ok', 'answered' (a status after the answer, or a second answer), or 'unknown'."""
        if turn_id not in self.offered_ids:
            return "unknown"
        if turn_id not in self.open_ids:
            return "answered"
        if final:
            self.open_ids.discard(turn_id)
        return "ok"

    @property
    def working(self) -> bool:
        return bool(self.open_ids)

    @property
    def stalled(self) -> bool:
        now = self.clock()
        return (self.pending_id is not None and self.waiters == 0 and now - self.offered_at > STALLED_AFTER
                and now - self.last_activity > ACTIVE_WITHIN)
