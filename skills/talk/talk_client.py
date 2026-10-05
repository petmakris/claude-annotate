#!/usr/bin/env python3
"""The Claude Code session's side of talk: wait for a turn, send a reply.

reply exit codes: 0 sent (or a status for a turn already answered, ignored), 2 refused, unreachable or no
such turn, 4 the call has ended.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

STATE_FILE = Path(os.environ.get("TALK_STATE")
                  or Path(os.environ.get("TMPDIR") or "/tmp") / "talk" / "session.json")


def load_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def request(state: dict, method: str, path: str, body: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Talk-Token": state["token"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def error_text(err: urllib.error.HTTPError) -> str:
    try:
        return json.loads(err.read()).get("error") or f"HTTP {err.code}"
    except (OSError, ValueError, AttributeError):
        return f"HTTP {err.code}"


def emit(kind: str, payload: dict) -> None:
    print(f"{kind} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def doorbell(wait: float) -> int:
    while True:
        state = load_state()
        if not state:
            emit("TALK_END", {"reason": "server unreachable"})
            return 0
        try:
            status, raw = request(state, "GET", f"/api/turn?wait={wait:g}", timeout=wait + 10)
        except urllib.error.HTTPError as err:
            if err.code == 409:
                # A newer doorbell is listening; re-arming here would only supersede that one in turn.
                print("doorbell superseded: a newer doorbell is listening. Do not re-arm.", flush=True)
                return 0
            emit("TALK_END", {"reason": f"server refused the doorbell: HTTP {err.code}"})
            return 0
        except (urllib.error.URLError, OSError):
            emit("TALK_END", {"reason": "server unreachable"})
            return 0
        if status == 204:
            continue
        event = json.loads(raw)
        kind = "TALK_END" if event.pop("type") == "end" else "TALK_TURN"
        emit(kind, event)
        return 0


def reply(turn_id: str, status_text: str | None, end: bool) -> int:
    state = load_state()
    if not state:
        print("talk is not reachable: no state file", file=sys.stderr)
        return 2
    body: dict = {"id": turn_id, "end": end}
    if status_text:
        body["status"] = status_text
    else:
        body["text"] = sys.stdin.read()
    try:
        _, raw = request(state, "POST", "/api/reply", body)
    except urllib.error.HTTPError as err:
        if err.code == 410:
            print("call ended: the call is over and nothing was said. Do not re-arm.")
            return 4
        if err.code == 404:
            print(f"no such turn: {turn_id} was never offered in this call ({error_text(err)})", file=sys.stderr)
            return 2
        print(f"talk refused the reply: {error_text(err)}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as err:
        print(f"talk is not reachable: {err}", file=sys.stderr)
        return 2
    result = json.loads(raw or b"{}")
    if result.get("ignored"):
        print(f"ignored: {result['ignored']}")
        return 0
    print("sent")
    for problem in result.get("board_problems", []):
        print(f"board: {problem}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bell = sub.add_parser("doorbell", help="wait for the next turn, print it, exit")
    bell.add_argument("--wait", type=float, default=25.0, help="seconds per long-poll")
    rep = sub.add_parser("reply", help="send a reply (read from stdin) for a turn; it is shown and read aloud")
    rep.add_argument("id")
    rep.add_argument("--status", help="a few words shown while working, instead of a reply")
    rep.add_argument("--end", action="store_true", help="this reply wraps up the call")
    args = parser.parse_args()
    if args.command == "reply" and args.status and args.end:
        parser.error("--status cannot be combined with --end: send the wrap-up as a reply with --end")
    if args.command == "doorbell":
        return doorbell(args.wait)
    return reply(args.id, args.status, args.end)


if __name__ == "__main__":
    sys.exit(main())
