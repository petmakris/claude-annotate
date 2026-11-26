#!/usr/bin/env python3
"""The Claude Code session's side of talk: wait for a turn, send a reply.

Every command names its call with --call <call id>, the id in the call's link, since one talk server
holds the calls of every session on this machine. With exactly one call open, --call may be left out.

A turn the user takes back after the session collected it is a cancelled turn: the doorbell prints a
TALK_CANCELLED line (or a `cancelled` list in the TALK_TURN it brings), and a reply for it prints
`cancelled:` and shows nothing. A turn the user replaced with a correction is a superseded turn: the
correction's own line carries `replaces`, a status for the old one prints `superseded:` and a reply is kept
in the conversation, tagged as replaced and never read aloud (it prints `sent` and a `superseded:` line).

reply exit codes: 0 sent (or a status, or an answer, for a turn already answered, ignored; a reply --end
for an answered turn still ends the call), 2 refused (a reply of only boards or key points, with no
sentence, is refused and the turn stays open), unreachable or no such turn, 4 the call has ended.
Stdin is read as UTF-8 whatever the locale.

reply --board-for N sends boards alone for answer N, already given (no turn id, nothing is said): a board that
was refused inside that answer is mended without saying the answer again. Exit 2 with the board: lines when
no board is shown.

end closes the call when no turn is left to answer (the user asked in the terminal): a wrap-up on stdin is
said first. say adds an answer with no turn to answer, shown and read aloud like a reply (to put right an
answer that went wrong, or to show what the user asked for in the terminal). Both use reply's exit codes.

While the server is being replaced, both commands wait for the next one to carry the call on, for up to
TALK_RECONNECT_S seconds. When nothing has taken the port after a few seconds, the doorbell starts a
server itself (TALK_REVIVE=0 turns that off), which picks up every call the last one left open. With
the launchd service installed, it asks launchd to start it instead, so the server keeps the service's
settings and not this session's.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import talk_files  # noqa: E402
import talk_service  # noqa: E402

REPLY_TIMEOUT_S = 60.0
RECONNECT_S = float(os.environ.get("TALK_RECONNECT_S", "90"))
REVIVE_AFTER_S = 5.0
REVIVE_EVERY_S = 15.0
TALK_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "talk.py")


def call_id_or_only(call_id: str | None) -> str | None:
    if call_id:
        return call_id
    open_now = talk_files.open_calls()
    return open_now[0] if len(open_now) == 1 else None


def load_state(call_id: str | None) -> dict | None:
    call_id = call_id_or_only(call_id)
    return talk_files.read(talk_files.call_file(call_id)) if call_id else None


def no_call_text(call_id: str | None) -> str:
    if call_id:
        return f"call {call_id} is not open on this machine"
    open_now = talk_files.open_calls()
    if open_now:
        return f"several calls are open; name one with --call ({', '.join(open_now)})"
    return "no call is open"


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


def port_held(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def spawn_server(port: int) -> None:
    if talk_service.installed():
        try:
            talk_service.kickstart()
        except (talk_service.ServiceError, OSError, subprocess.TimeoutExpired):
            pass
        return
    uv = shutil.which("uv")
    if not uv:
        return
    log = talk_files.run_dir() / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as out:
        subprocess.Popen([uv, "run", "--script", TALK_PY, "--serve", "--port", str(int(port))],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True, cwd=os.path.dirname(TALK_PY))


class Reconnect:
    """The server holding a call went away: wait for the next one on its port to carry the call on, and
    start one when nobody else has after a few seconds. Calls written by older code are never carried
    over, so for those there is nothing to wait for."""

    def __init__(self):
        self.since: float | None = None
        self.revived = float("-inf")

    def wait(self, state: dict) -> bool:
        if not talk_files.adoptable(state):
            return False
        now = time.monotonic()
        self.since = self.since if self.since is not None else now
        if now - self.since > RECONNECT_S:
            return False
        if (os.environ.get("TALK_REVIVE", "1") != "0" and now - self.since >= REVIVE_AFTER_S
                and now - self.revived >= REVIVE_EVERY_S and not port_held(state["port"])):
            self.revived = now
            spawn_server(state["port"])
        time.sleep(1.0)
        return True

    def back(self) -> None:
        self.since = None


LOST_RETRY = ("this is not the end of the call: run the same doorbell command again. "
              "Stop only on TALK_END; if TALK_LOST comes 3 times in a row, tell the user the call is lost.")
LOST_SERVER_S = 90.0  # a doorbell waits this long through a server answering 5xx before it reports TALK_LOST


def emit_lost(reason: str) -> int:
    """The doorbell failed, but the call may well be open: its own line, never TALK_END, so the session
    re-arms rather than leaves a call the user is still in."""
    emit("TALK_LOST", {"reason": reason, "retry": LOST_RETRY})
    return 0


def emit_end(reason: str, transcript: str = "") -> int:
    emit("TALK_END", {"reason": reason, **({"transcript": transcript} if transcript else {})})
    return 0


def ended_transcript(state: dict) -> str:
    """The transcript of a call whose call file says it ended."""
    return str(Path(state["out"]) / "transcript.md") if state.get("out") else ""


def doorbell(call_id: str | None, wait: float) -> int:
    """Wait for the next turn. TALK_END is printed only when the call has really ended (the server said so,
    or its file says so and nothing answers); any other failure is TALK_LOST, which the session re-arms on."""
    call_id = call_id_or_only(call_id) or call_id
    lost = Reconnect()
    failing_since: float | None = None
    while True:
        state = load_state(call_id)
        if not state:
            if not call_id and len(talk_files.open_calls()) > 1:
                return emit_lost(no_call_text(call_id))
            return emit_end(no_call_text(call_id))
        try:
            status, raw = request(state, "GET", f"/api/turn?wait={wait:g}", timeout=wait + 10)
        except urllib.error.HTTPError as err:
            if err.code == 409:
                # A newer doorbell is listening; re-arming here would only supersede that one in turn.
                print("doorbell superseded: a newer doorbell is listening. Do not re-arm.", flush=True)
                return 0
            if err.code == 410:
                transcript = ""
                try:
                    transcript = json.loads(err.read() or b"{}").get("transcript") or ""
                except (ValueError, AttributeError, OSError):
                    pass
                return emit_end("the call has ended", transcript or ended_transcript(state))
            if err.code >= 500:
                if err.code == 503 and lost.wait(state):
                    continue
                now = time.monotonic()
                failing_since = failing_since if failing_since is not None else now
                if now - failing_since <= LOST_SERVER_S:
                    time.sleep(1.0)
                    continue
                return emit_lost(f"the talk server kept answering HTTP {err.code}")
            return emit_lost(f"server refused the doorbell: HTTP {err.code}")
        except http.client.HTTPException as err:
            # a truncated or malformed answer (IncompleteRead, BadStatusLine): the call may well be open
            return emit_lost(f"the talk server's answer was cut off or malformed ({type(err).__name__})")
        except (urllib.error.URLError, OSError):
            if state.get("ended"):
                return emit_end("the call has ended", ended_transcript(state))
            if lost.wait(state):
                continue
            return emit_lost("server unreachable")
        lost.back()
        failing_since = None
        if status == 204:
            continue
        try:
            event = json.loads(raw)
            kind = {"end": "TALK_END", "cancelled": "TALK_CANCELLED"}.get(event.pop("type"), "TALK_TURN")
        except (ValueError, KeyError, AttributeError, TypeError):
            return emit_lost("the talk server's answer was not a turn (not JSON)")
        emit(kind, event)
        return 0


def send_reply(call_id: str | None, body: dict):
    """POST the reply, waiting through a server being replaced: a turn already answered is ignored by
    the next server, so sending again never shows or says it twice."""
    lost = Reconnect()
    while True:
        state = load_state(call_id)
        if not state:
            raise LookupError(no_call_text(call_id))
        try:
            return request(state, "POST", "/api/reply", body, timeout=REPLY_TIMEOUT_S)
        except urllib.error.HTTPError as err:
            if err.code != 503 or not lost.wait(state):
                raise
        except (urllib.error.URLError, OSError) as err:
            if isinstance(err, (TimeoutError, socket.timeout)) or isinstance(getattr(err, "reason", None), (TimeoutError, socket.timeout)):
                raise
            if not lost.wait(state):
                raise


def read_stdin() -> str:
    """The answer on stdin, read as UTF-8 whatever the process locale: a POSIX locale would turn Greek
    into mojibake that is stored and then refused by the speech engine."""
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    return sys.stdin.read()


def reply(call_id: str | None, turn_id: str | None, status_text: str | None, end: bool, say: bool = False,
          board_for: int | None = None) -> int:
    call_id = call_id_or_only(call_id) or call_id
    state = load_state(call_id)
    if not state:
        print(f"talk is not reachable: {no_call_text(call_id)}", file=sys.stderr)
        return 2
    body: dict = {"id": turn_id or "", "end": end, **({"say": True} if say else {}),
                  **({"board_for": board_for} if board_for is not None else {})}
    if status_text:
        body["status"] = status_text
    else:
        body["text"] = "" if turn_id is None and sys.stdin.isatty() else read_stdin()
    try:
        _, raw = send_reply(call_id, body)
    except LookupError as err:
        print(f"talk is not reachable: {err}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as err:
        if err.code == 410:
            transcript = ""
            try:
                transcript = json.loads(err.read() or b"{}").get("transcript") or ""
            except (ValueError, AttributeError, OSError):
                pass
            print("call ended: the call is over and nothing was said. Do not re-arm."
                  + (f" Transcript {transcript}: write the recap from it." if transcript else ""))
            return 4
        if err.code == 404:
            print(f"no such turn: {turn_id} was never offered in this call ({error_text(err)})", file=sys.stderr)
            return 2
        print(f"talk refused the reply: {error_text(err)}", file=sys.stderr)
        return 2
    except http.client.HTTPException as err:
        print(f"sent, but talk's answer was cut off or malformed ({type(err).__name__}); do not resend it: "
              "it is probably being shown", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as err:
        if isinstance(err, (TimeoutError, socket.timeout)) or isinstance(getattr(err, "reason", None), (TimeoutError, socket.timeout)):
            print(f"sent, but talk did not confirm it within {REPLY_TIMEOUT_S:.0f} s; do not resend it: "
                  "it is probably being shown", file=sys.stderr)
            return 2
        print(f"talk is not reachable: {err}", file=sys.stderr)
        return 2
    try:
        result = json.loads(raw or b"{}")
        result.get("ignored")
    except (ValueError, AttributeError):
        print("sent, but talk's answer was not JSON; do not resend it: it is probably being shown", file=sys.stderr)
        return 2
    if result.get("cancelled"):
        print(result["ignored"])
        return 0
    if result.get("superseded") and result.get("ignored"):
        print(result["ignored"])
        return 0
    if result.get("ignored"):
        print(f"ignored: {result['ignored']}")
        return 0
    if board_for is not None:
        print(f"boards added to answer {board_for}: {result.get('boards', 0)}")
    else:
        print("ended: re-arm once to collect the TALK_END" if turn_id is None and not say else "sent")
    if result.get("superseded"):
        print(result.get("note") or "superseded: this question was replaced; the reply was not read aloud")
    for problem in result.get("board_problems", []):
        print(f"board: {problem}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bell = sub.add_parser("doorbell", help="wait for the next turn, print it, exit")
    bell.add_argument("--call", help="the call id, from the call's link; write --call=<id>")
    bell.add_argument("--wait", type=float, default=25.0, help="seconds per long-poll")
    rep = sub.add_parser("reply", help="send a reply (read from stdin) for a turn; it is shown and read aloud")
    rep.add_argument("id", nargs="?", help="the turn's id (left out with --board-for)")
    rep.add_argument("--call", help="the call id, from the call's link; write --call=<id>")
    rep.add_argument("--status", help="a few words shown while working, instead of a reply")
    rep.add_argument("--end", action="store_true", help="this reply wraps up the call")
    rep.add_argument("--board-for", type=int, metavar="N",
                     help="send only boards ([[show ...]] blocks) for answer N, already given: they are shown with it "
                          "and nothing is said, so a refused board is sent again without saying the answer twice")
    fin = sub.add_parser("end", help="end the call with no turn to answer; a wrap-up on stdin is said first")
    fin.add_argument("--call", help="the call id, from the call's link; write --call=<id>")
    say = sub.add_parser("say", help="say an answer (read from stdin) with no turn to answer; it is shown and "
                                     "read aloud like a reply")
    say.add_argument("--call", help="the call id, from the call's link; write --call=<id>")
    args = parser.parse_args()
    if args.command == "reply" and args.status and args.end:
        parser.error("--status cannot be combined with --end: send the wrap-up as a reply with --end")
    if args.command == "reply" and args.board_for is not None and (args.status or args.end):
        parser.error("--board-for sends boards alone: it cannot be combined with --status or --end")
    if args.command == "reply" and args.board_for is None and not args.id:
        parser.error("reply needs the turn's id (or --board-for N)")
    if args.command == "doorbell":
        return doorbell(args.call, args.wait)
    if args.command == "end":
        return reply(args.call, None, None, True)
    if args.command == "say":
        return reply(args.call, None, None, False, say=True)
    return reply(args.call, args.id, args.status, args.end, board_for=args.board_for)


if __name__ == "__main__":
    sys.exit(main())
