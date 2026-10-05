"""The turn queue between GPT-Live's hand-offs and the Claude Code session that answers them."""

import asyncio
import time

BUSY_AFTER = 8.0
OFFLINE_AFTER = 20.0
ACTIVE_WITHIN = 20.0  # tool calls this recent mean the session is alive, just busy


class TurnQueue:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.live_id: str | None = None
        self.lines: list[dict] = []
        self.pending = False
        self.offered_at = 0.0
        self.delivered_at: float | None = None
        self.replied = False
        self.answered = False
        self.alerted: set[str] = set()
        self.offered_ids: set[str] = set()
        self.last_activity = float("-inf")
        self.replied_at = float("-inf")  # the brain's last reply or status to the live turn
        self.waiters = 0
        self._newest_waiter = 0
        self.ended: dict | None = None
        self.end_collected = asyncio.Event()
        self._changed = asyncio.Event()

    def offer(self, turn_id: str, lines: list[dict]) -> None:
        self.live_id = turn_id
        self.offered_ids.add(turn_id)
        self.lines.extend(lines)
        self.pending = True
        self.offered_at = self.clock()
        self.delivered_at = None
        self.replied = False
        self.answered = False
        self.alerted.clear()
        self._changed.set()

    def put_back(self, event: dict) -> None:
        if event.get("type") != "turn":
            return
        self.lines = list(event["said"]) + self.lines
        self.pending = True
        self.delivered_at = None
        self._changed.set()

    def finish(self, reason: str, transcript: str, unsaid: str | None = None) -> None:
        self.ended = {"reason": reason, "transcript": transcript}
        if unsaid:
            self.ended["unsaid"] = unsaid  # a reply the brain sent that no session ever said
        self._changed.set()

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
                if self.pending:
                    turn = {"type": "turn", "id": self.live_id, "said": self.lines}
                    self.lines, self.pending = [], False
                    self.delivered_at = self.clock()
                    return turn
                self._changed.clear()
                try:
                    await asyncio.wait_for(self._changed.wait(), timeout)
                except asyncio.TimeoutError:
                    return None
        finally:
            self.waiters -= 1

    def known(self, turn_id: str) -> bool:
        return turn_id in self.offered_ids

    def note_activity(self) -> None:
        self.last_activity = self.clock()

    def accept_reply(self, turn_id: str, final: bool = True) -> bool:
        if turn_id != self.live_id:
            return False
        self.replied = True
        self.replied_at = self.clock()
        self.answered = self.answered or final
        return True

    @property
    def working(self) -> bool:
        return self.delivered_at is not None and not self.pending and not self.answered

    def check(self) -> str | None:
        now = self.clock()
        if (self.pending and self.waiters == 0 and now - self.offered_at > OFFLINE_AFTER
                and now - self.last_activity > ACTIVE_WITHIN and "offline" not in self.alerted):
            self.alerted.add("offline")
            return "offline"
        if self.working and not self.replied and now - self.delivered_at > BUSY_AFTER and "busy" not in self.alerted:
            self.alerted.add("busy")
            return "busy"
        return None
