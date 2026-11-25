"""talk_client survives a truncated or non-JSON answer: TALK_LOST, never a traceback."""
import json
import os
import socket
import subprocess
import sys
import threading

from helpers import CALL, SKILL_DIR, TOKEN

CLIENT = str(SKILL_DIR / "talk_client.py")
LOST_RETRY = ("this is not the end of the call: run the same doorbell command again. "
              "Stop only on TALK_END; if TALK_LOST comes 3 times in a row, tell the user the call is lost.")


def serve_once(raw: bytes):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def go():
        conn, _ = srv.accept()
        conn.recv(65536)
        conn.sendall(raw)
        conn.close()
        srv.close()

    threading.Thread(target=go, daemon=True).start()
    return srv.getsockname()[1]


def doorbell(tmp_path, raw):
    port = serve_once(raw)
    calls = tmp_path / "run" / "calls"
    calls.mkdir(parents=True)
    (calls / f"{CALL}.json").write_text(json.dumps({"port": port, "token": TOKEN, "call": CALL, "pid": 1}))
    p = subprocess.run([sys.executable, CLIENT, "doorbell", f"--call={CALL}", "--wait", "1"],
                       env={**os.environ, "TALK_RUN_DIR": str(tmp_path / "run")},
                       capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    return p


def lost(reason):
    return "TALK_LOST " + json.dumps({"reason": reason, "retry": LOST_RETRY}, ensure_ascii=False) + "\n"


def test_truncated_body_is_talk_lost(tmp_path):
    p = doorbell(tmp_path, b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{\"type\": \"tu")
    assert (p.returncode, p.stdout, p.stderr) == (
        0, lost("the talk server's answer was cut off or malformed (IncompleteRead)"), "")


def test_non_json_body_is_talk_lost(tmp_path):
    p = doorbell(tmp_path, b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\nConnection: close\r\n\r\n<html>oops")
    assert (p.returncode, p.stdout, p.stderr) == (
        0, lost("the talk server's answer was not a turn (not JSON)"), "")
