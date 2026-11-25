#!/usr/bin/env python3
"""Render one /talk answer the way a user sees it, and take screenshots of it.

    uv run --with playwright python render.py --repo <checkout> --answer <file> --code <folder> --out <dir>
        [--question "what the user asked"] [--pace 1.0] [--no-phone] [--no-dark] [--topic T]

What it does (README.md has the details):
  1. starts <repo>'s own talk server on a free port, with a silent stand-in speech engine
     (fake_speech.py), never through launchd, never port 8766, never Azure;
  2. opens a call from <repo>'s own launcher; the stage's static files are the ones <repo>'s stage.py
     registers with the webcompanion daemon for that call's own stage session;
  3. opens the call page in Playwright's Chromium, sends the answer the way a session does
     (talk_client.py say, or doorbell + reply when --question is given), and plays it through,
     pausing at every moment a board comes to the front, at every [[point]] and at the end;
  4. replays it at 390x844 and once more in dark at rest;
  5. stops its server, its helper and its stage session by PID/sid, also on failure.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE_PORT = 8766
SETTLE_S = 0.9          # a paused moment waits this long for the stage's own animation to finish
REST_WAIT_S = 2.6       # the page holds the last frame 1.5 s, then shows every board whole
MAX_PLAY_S = float(__import__("os").environ.get("RENDER_MAX_PLAY_S", "420"))      # one pass is abandoned after this long
DESKTOP = (1440, 900)
PHONE = (390, 844)

_children: list[int] = []
_stage_sids: list[str] = []
_repo_for_cleanup: Path | None = None


def log(msg: str) -> None:
    print(f"render: {msg}", flush=True)


# --------------------------------------------------------------------------- processes


def clean_env(run_dir: Path, pace: float) -> dict:
    """The talk settings of this machine (service address, Azure key command...) never reach the harness's server."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TALK_", "AZURE_", "VOICESTUDIO", "OMNIVOICE"))}
    env.update(TALK_RUN_DIR=str(run_dir / "run"), XDG_DATA_HOME=str(run_dir / "xdg"),
               TALK_FAKE_PACE=str(pace), TALK_SPEECH="voicestudio", TALK_REVIVE="0", PYTHONUNBUFFERED="1")
    return env  # TALK_SPEECH only decides nothing here: serve.py has put the silent engine in already


def free_port() -> int:
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != LIVE_PORT:
            return port
    raise SystemExit("no free port")


def uv_python(args: list[str], env: dict, **kw) -> subprocess.Popen:
    return subprocess.Popen(["uv", "run", "-q", "--with", "aiohttp", "python", str(HERE / "serve.py"), *args],
                            env=env, stdin=subprocess.DEVNULL, **kw)


def kill_pid(pid: int, grace: float = 4.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    end = time.time() + grace
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def cleanup() -> None:
    for pid in _children:
        kill_pid(pid)
    _children.clear()
    if _stage_sids and _repo_for_cleanup:
        sys.path.insert(0, str(_repo_for_cleanup))
        try:
            from skills._shared import webcompanion_client as wc
            for sid in _stage_sids:
                try:
                    wc.finish_session(sid, "stage")
                    log(f"stage session {sid} ended")
                except Exception as err:  # noqa: BLE001
                    log(f"stage session {sid} not ended: {err}")
        except Exception as err:  # noqa: BLE001
            log(f"could not load the webcompanion client: {err}")
    _stage_sids.clear()


def on_signal(signum, _frame) -> None:
    raise SystemExit(128 + signum)


# --------------------------------------------------------------------------- talk server


def http_json(url: str, token: str = "", timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"X-Talk-Token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def start_server(repo: Path, run_dir: Path, port: int, env: dict) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    out = (run_dir / "server.log").open("w")
    proc = uv_python(["--repo", str(repo), "--", "--serve", "--port", str(port)], env,
                     stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    _children.append(proc.pid)
    sfile = run_dir / "run" / "servers" / f"{port}.json"
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"the talk server exited ({proc.returncode}): see {run_dir / 'server.log'}")
        try:
            info = json.loads(sfile.read_text())
            http_json(f"http://127.0.0.1:{port}/api/health", info["token"], timeout=3)
            if info.get("pid"):
                _children.append(int(info["pid"]))
            return info
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            time.sleep(0.3)
    raise SystemExit(f"the talk server did not answer in 90 s: see {run_dir / 'server.log'}")


def open_call(repo: Path, code: Path, run_dir: Path, port: int, env: dict, topic: str) -> dict:
    proc = uv_python(["--repo", str(repo), "--", "--topic", topic, "--port", str(port), "--no-open",
                      "--code", str(code), "--out", str(run_dir / "talk-out")], env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out, _ = proc.communicate(timeout=180)
    (run_dir / "launch.txt").write_text(out)
    if proc.returncode:
        raise SystemExit(f"the launch failed ({proc.returncode}):\n{out}")
    call = re.search(r"^Call (\S+)", out, re.M)
    stage = re.search(r"^Stage (\S+) \(folder (.*), slug (\S+), sid (\S+)\)", out, re.M)
    if not call or not stage:
        raise SystemExit(f"the launch printed no call or stage:\n{out}")
    sid = stage.group(4)
    _stage_sids.append(sid)
    token = json.loads((run_dir / "run" / "calls" / f"{call.group(1)}.json").read_text())["token"]
    return {"id": call.group(1), "url": f"http://127.0.0.1:{port}/c/{call.group(1)}", "stage_url": stage.group(1),
            "sid": sid, "token": token}


def send_answer(repo: Path, call: dict, answer: str, question: str | None, env: dict, port: int) -> str:
    """The way a session does it: say, or (with a question typed on the page) doorbell then reply."""
    client = str(repo / "skills" / "talk" / "talk_client.py")
    cid = f"--call={call['id']}"
    if question:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/say", method="POST",
                                     data=json.dumps({"text": question}).encode(),
                                     headers={"X-Talk-Token": call["token"], "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
        bell = subprocess.run([sys.executable, client, "doorbell", cid, "--wait", "10"], env=env,
                              capture_output=True, text=True, timeout=60)
        m = re.search(r"^TALK_TURN (\{.*\})", bell.stdout, re.M)
        if not m:
            raise SystemExit(f"no turn came to the doorbell: {bell.stdout!r} {bell.stderr!r}")
        turn = json.loads(m.group(1))["id"]
        cmd = [sys.executable, client, "reply", str(turn), cid]
    else:
        cmd = [sys.executable, client, "say", cid]
    done = subprocess.run(cmd, input=answer, env=env, capture_output=True, text=True, timeout=180)
    return f"$ {' '.join(cmd[2:])}\n(exit {done.returncode})\n{done.stdout}{done.stderr}"


# --------------------------------------------------------------------------- the answer's timeline


def state_of(port: int, call: dict) -> dict:
    return http_json(f"http://127.0.0.1:{port}/api/state", call["token"])


def wait_answer(port: int, call: dict, timeout: float = 180.0) -> tuple[dict, dict]:
    """The state once the (last) Claude answer has its voice: audio made, words timed."""
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        last = state_of(port, call)
        answers = [e for e in last.get("entries", []) if e.get("who") == "claude"]
        if answers and answers[-1].get("speech") in ("ready", "failed", None) and answers[-1].get("words") is not None \
                and answers[-1].get("audio"):
            return last, answers[-1]
        time.sleep(0.4)
    raise SystemExit(f"the answer never became ready; last answer entry: {json.dumps((answers or [None])[-1])[:800]}")


def sentence_at(text: str, char: int) -> str:
    """The sentence of `text` that holds position `char`."""
    marks = [0] + [m.end() for m in re.finditer(r"[.!?…][)\]\"'”’]*\s+", text)] + [len(text)]
    i = max(0, bisect.bisect_right(marks, max(0, min(char, len(text) - 1))) - 1)
    return text[marks[i]:marks[i + 1]].strip()


def time_of(entry: dict, char: int) -> float:
    for a, _b, t0, _t1 in entry["words"]:
        if a >= char:
            return float(t0)
    return float(entry["words"][-1][3]) if entry["words"] else 0.0


def boards_of(view: dict, entry: dict) -> dict:
    """view name -> {title, kind} for the boards of this answer."""
    n = entry.get("n")
    out = {}
    for e in view.get("entries", []):
        if e.get("who") == "board" and e.get("view"):
            out[e["view"]] = {"title": e.get("text") or "", "kind": e.get("kind") or "",
                              "answer": e.get("answer")}
    return out


def moments_of(view: dict, entry: dict) -> list[dict]:
    boards = boards_of(view, entry)
    text = entry.get("text", "")
    out = []
    for c in entry.get("cues") or []:
        kind = c.get("kind")
        if kind not in ("front", "frame"):
            continue
        t = time_of(entry, int(c.get("at", 0)))
        b = boards.get(c.get("view"), {"title": c.get("view"), "kind": "?"})
        out.append({"t": t, "what": "board" if kind == "front" else "point", "cue": c,
                    "caption": sentence_at(text, int(c.get("at", 0))), "board": dict(b)})
    out.sort(key=lambda m: (m["t"], 0 if m["what"] == "board" else 1))
    return out


# --------------------------------------------------------------------------- the browser


GRID_JS = """() => { const g = document.querySelector('.md.grid table'); if (!g) return null;
  const r = (e) => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height].map((x) => Math.round(x * 10) / 10); };
  const wrap = g.closest('.tablewrap');
  return { table: r(g), wrap: r(wrap), pane: r(document.querySelector('.pbody') || wrap),
    head: r(g.querySelector('thead')), rows: [...g.querySelectorAll('tbody tr')].map((e) => r(e)[3]),
    cols: [...g.querySelectorAll('thead th')].map((e) => r(e)[2]),
    scroll: [wrap.scrollLeft, wrap.scrollTop, wrap.scrollWidth, wrap.scrollHeight, wrap.clientWidth, wrap.clientHeight],
    key: (g.querySelector('td.key') ? r(g.querySelector('td.key'))[2] : 0),
    lit: [...g.querySelectorAll('tr.g-cur, td.k-focus, th.g-col')].map((e) => ({tag: e.tagName, rect: r(e)})) }; }"""


def grid_geometry(page):
    """The table board's boxes as the browser laid them out, from the stage frame (None when no table is up)."""
    for fr in page.frames:
        try:
            got = fr.evaluate(GRID_JS)
        except Exception:
            continue
        if got:
            return got
    return None


class Shooter:
    def __init__(self, out: Path, frames: list, console: list):
        self.out, self.frames, self.console, self.n = out, frames, console, 0

    def shot(self, page, prefix: str, label: str, t: float, caption: str, board: dict, width: int, theme: str):
        self.n += 1
        name = f"{prefix}{self.n:02d}-{label}.png"
        page.screenshot(path=str(self.out / name))
        self.frames.append({"file": name, "width": width, "theme": theme, "t": round(t, 2),
                            "caption": caption, "board": board, "grid": grid_geometry(page)})
        log(f"shot {name} t={t:.1f}s {board.get('kind', '')}:{board.get('title', '')}")


def watch(page, console: list, tag: str) -> None:
    page.on("console", lambda m: console.append(f"[{tag}] console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: console.append(f"[{tag}] pageerror: {e}"))
    page.on("requestfailed", lambda r: console.append(f"[{tag}] requestfailed: {r.url} {r.failure}"))
    page.on("response", lambda r: console.append(f"[{tag}] http {r.status}: {r.url}") if r.status >= 400 else None)


def front_board_at_rest(view: dict, entry: dict) -> dict:
    boards = boards_of(view, entry)
    front = None
    for c in entry.get("cues") or []:
        if c.get("kind") in ("front", "frame"):
            front = c.get("view")
    return boards.get(front, {"title": "", "kind": ""}) if front else {"title": "", "kind": ""}


def play_through(page, shooter: Shooter, prefix: str, width: int, theme: str, moments: list[dict], entry: dict,
                 rest_board: dict, take_moments: bool = True, speed: float = 1.0, user_play: bool = False) -> None:
    if user_play:
        page.evaluate("togglePlay()")
    else:
        # a new answer plays by itself; wait for it to start
        pass
    deadline = time.time() + 60
    while time.time() < deadline and not page.evaluate("audio.currentTime > 0 || !audio.paused"):
        page.wait_for_timeout(100)
    if speed != 1.0:
        page.evaluate(f"audio.playbackRate = {speed}")
    start = time.time()
    i = 0
    while time.time() - start < MAX_PLAY_S:
        st = page.evaluate("({t: audio.currentTime, ended: audio.ended, paused: audio.paused, stop: !!stopped})")
        if st["ended"]:
            break
        if st["stop"] and st["paused"]:
            if take_moments:
                shooter.shot(page, prefix, "stop", st["t"], "(the answer asks and waits)", {"title": "", "kind": "stop"}, width, theme)
            page.evaluate("togglePlay()")
            page.wait_for_timeout(300)
            continue
        if take_moments and i < len(moments) and st["t"] >= moments[i]["t"] + 0.15:
            m = moments[i]
            i += 1
            page.evaluate("audio.pause()")
            page.wait_for_timeout(int(SETTLE_S * 1000))
            shooter.shot(page, prefix, m["what"], st["t"], m["caption"], m["board"], width, theme)
            page.evaluate(f"audio.playbackRate = {speed}; audio.play()")
            continue
        if st["paused"] and not st["stop"]:
            page.evaluate(f"audio.playbackRate = {speed}; audio.play()")
        page.wait_for_timeout(40)
    else:
        log("pass abandoned: it ran past MAX_PLAY_S")
    page.wait_for_timeout(int(REST_WAIT_S * 1000))
    shooter.shot(page, prefix, "rest", float(entry["words"][-1][3]) if entry["words"] else 0.0,
                 "(the answer is over, every board shown whole)", rest_board, width, theme)


# --------------------------------------------------------------------------- main


def main() -> int:
    global _repo_for_cleanup
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path, help="the claude-annotate checkout whose talk and stage are rendered")
    ap.add_argument("--answer", required=True, type=Path, help="a file holding the answer in talk's tag language")
    ap.add_argument("--code", required=True, type=Path, help="the folder the boards read from (talk --code)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--question", help="what the user asked: typed on the call, so the answer is a reply to it")
    ap.add_argument("--topic", help="the call's topic (default: the question, or the answer file's name)")
    ap.add_argument("--pace", type=float, default=1.0, help="speaking time scale: 1.0 calm, 0.5 twice as fast")
    ap.add_argument("--no-phone", action="store_true")
    ap.add_argument("--tv", action="store_true", help="also replay at 1920x1080 (t* shots)")
    ap.add_argument("--no-dark", action="store_true")
    args = ap.parse_args()
    repo, code, out = args.repo.resolve(), args.code.resolve(), args.out.resolve()
    if not (repo / "skills" / "talk" / "talk.py").is_file():
        raise SystemExit(f"--repo: no skills/talk/talk.py in {repo}")
    if not code.is_dir():
        raise SystemExit(f"--code: not a folder: {code}")
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("*.png")) + [out / n for n in ("frames.json", "reply.txt", "console.txt")]:
        old.unlink(missing_ok=True)
    answer = args.answer.read_text()
    _repo_for_cleanup = repo
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    run_dir = out / "_run"
    env = clean_env(run_dir, args.pace)
    frames: list = []
    console: list = []
    code_ok = False
    try:
        port = free_port()
        log(f"repo {repo}; talk server on port {port} (never {LIVE_PORT})")
        start_server(repo, run_dir, port, env)
        topic = args.topic or args.question or args.answer.stem
        call = open_call(repo, code, run_dir, port, env, topic[:80])
        log(f"call {call['id']}, stage {call['stage_url']}")
        import threading
        view_box: dict = {}

        def sender():
            reply = send_answer(repo, call, answer, args.question, env, port)
            (out / "reply.txt").write_text(reply)
            view_box["state"], view_box["entry"] = wait_answer(port, call)

        thread = threading.Thread(target=sender, daemon=True)
        run_browser_after(args, call, port, out, frames, console, thread, view_box)
        code_ok = True
    except SystemExit:
        raise
    finally:
        (out / "console.txt").write_text("\n".join(console) + ("\n" if console else ""))
        (out / "frames.json").write_text(json.dumps(frames, indent=1, ensure_ascii=False))
        cleanup()
    log(f"done: {len(frames)} shots in {out}")
    return 0 if code_ok and frames else 1


def run_browser_after(args, call, port, out, frames, console, thread, view_box):
    """Open the page, send the answer, wait until its timings exist, then play it through."""
    from playwright.sync_api import sync_playwright

    shooter = Shooter(out, frames, console)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        try:
            def new(width, height, theme, tag, mobile=False):
                kw = dict(viewport={"width": width, "height": height}, color_scheme=theme)
                if mobile:
                    kw.update(is_mobile=True, has_touch=True, device_scale_factor=2)
                ctx = browser.new_context(**kw)
                ctx.add_init_script(f"try{{localStorage.setItem('talk.theme', JSON.stringify('{theme}'))}}catch(e){{}}")
                page = ctx.new_page()
                watch(page, console, tag)
                page.goto(call["url"])
                page.wait_for_function("typeof audio !== 'undefined' && typeof view !== 'undefined'", timeout=30000)
                return ctx, page

            ctx, page = new(*DESKTOP, "light", "desktop")
            page.wait_for_timeout(1500)
            thread.start()                       # the session's reply reaches the open page
            deadline = time.time() + 240
            while thread.is_alive() and time.time() < deadline:
                page.wait_for_timeout(300)
            if "entry" not in view_box:
                raise SystemExit("the answer was not made: see reply.txt")
            view, entry = view_box["state"], view_box["entry"]
            moments = moments_of(view, entry)
            rest_board = front_board_at_rest(view, entry)
            log(f"{len(moments)} moments: " + ", ".join(f"{m['what']}@{m['t']:.1f}" for m in moments))
            started = time.time() + 40
            while time.time() < started and not page.evaluate("!!current"):
                page.wait_for_timeout(200)
            user_play = False
            if not page.evaluate("!!current"):
                log("the page did not start the answer by itself; pressing Play")
                user_play = True
            play_through(page, shooter, "d", DESKTOP[0], "light", moments, entry, rest_board, user_play=user_play)
            ctx.close()
            if not args.no_phone:
                ctx, page = new(*PHONE, "light", "phone", mobile=True)
                page.wait_for_function("!!lastAnswer()", timeout=30000)
                page.wait_for_timeout(2500)
                play_through(page, shooter, "p", PHONE[0], "light", moments, entry, rest_board, user_play=True)
                ctx.close()
            if args.tv:
                ctx, page = new(1920, 1080, "light", "tv")
                page.wait_for_function("!!lastAnswer()", timeout=30000)
                page.wait_for_timeout(2500)
                play_through(page, shooter, "t", 1920, "light", moments, entry, rest_board, user_play=True)
                ctx.close()
            if not args.no_dark:
                ctx, page = new(*DESKTOP, "dark", "dark")
                page.wait_for_function("!!lastAnswer()", timeout=30000)
                page.wait_for_timeout(2500)
                play_through(page, shooter, "k", DESKTOP[0], "dark", moments, entry, rest_board,
                             take_moments=False, speed=4.0, user_play=True)
                ctx.close()
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
