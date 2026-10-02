"""The per-session SSE loop, shared by every skill that streams thread changes.

Both skill servers had their own copy of this: same headers, same 30s waiter,
same self-correcting re-read, same deleted/changed/heartbeat/session-ended
events. Only one of the two copies had tests, and the SSE contract is shared
with the IntelliJ client — so a fix to the frames had to be made twice, in a
place where half the copies were unguarded.

Skill-specific frames stay skill-specific: `extra` is called once before the
first snapshot and again on every tick, and emits whatever that skill has that
the others do not (walkthrough's `steps-changed`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def serve(handler, dirs: dict, *, registry, threads_bulk: Callable[[dict], dict],
          is_terminal: Callable[[Path], bool],
          extra: Callable[[Callable[[str, dict], bool]], bool] | None = None) -> None:
    """Stream this session's thread changes until the client disconnects.

    :param registry: the session registry, for its per-sid wake waiter.
    :param threads_bulk: the skill's {anchor: info} snapshot function.
    :param is_terminal: True once the session has a finished/cancelled marker.
    :param extra: optional per-skill emitter; return False to end the stream
        (the client hung up). Called before the first snapshot and each tick.
    """
    sid = dirs.get("_sid")
    state_dir = Path(dirs["state_dir"])
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()

    def emit(name: str, obj: dict) -> bool:
        try:
            handler.wfile.write(f"event: {name}\ndata: {json.dumps(obj)}\n\n".encode())
            handler.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    if not emit("connected", {}):
        return
    if not registry or not sid:
        return  # registry not injected — should not happen in production

    if extra is not None and not extra(emit):
        return
    last_threads = threads_bulk(dirs)
    for anchor, info in last_threads.items():
        if not emit("thread-changed", {"anchor": anchor, **info}):
            return

    waiter = registry.waiter(sid)
    while True:
        woke = waiter.wait(timeout=30)
        if is_terminal(state_dir):
            # Tell the client the session is over and end the stream — otherwise
            # this loop re-reads every thread file every 30s per connected
            # client, forever.
            emit("session-ended", {})
            return
        if extra is not None and not extra(emit):
            return
        # Always re-read rather than trusting the wake signal, so a missed
        # notify cannot strand the client on stale content.
        new_threads = threads_bulk(dirs)
        for anchor in list(last_threads):
            if anchor not in new_threads and not emit("thread-deleted", {"anchor": anchor}):
                return
        for anchor, info in new_threads.items():
            old = last_threads.get(anchor)
            if (old is None or old.get("version") != info.get("version")) \
                    and not emit("thread-changed", {"anchor": anchor, **info}):
                return
        last_threads = new_threads
        # Heartbeat only when nothing woke us, to keep proxies from timing out.
        if not woke and not emit("heartbeat", {}):
            return
