# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "aiohttp>=3.10,<4",
# ]
# ///
"""talk: a spoken conversation with a Claude Code session, one turn at a time, on local speech.

    browser page: press Talk, speak, press Send
        -> this script -> VoiceStudio speech to text -> a turn the session collects (talk_client.py doorbell)
    the session answers (talk_client.py reply)
        -> board tags go on the stage, the rest -> VoiceStudio text to speech -> an mp3 the page plays,
           with pause, skip back and speed buttons

    uv run --script talk.py --topic "The findings deck" --code <repo>
    uv run --script talk.py --doctor

Speech runs in the VoiceStudio app on this machine, at VOICESTUDIO_URL (default http://127.0.0.1:3900).
"""

import argparse
import asyncio
import concurrent.futures
import datetime as dt
import json
import os
import re
import secrets
import signal
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_turns import TurnQueue  # noqa: E402
import voicestudio as speech  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skills.stage import stage as stage_mod  # noqa: E402

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "talk"
SESSIONS_DIR = DATA_DIR / "sessions"
DEFAULT_PORT = 8766
OPEN_TIMEOUT_MIN = 15  # end the call if the page is never opened within this long
LINGER_S = 30 * 60  # after the call ends, the page can still replay its answers for this long
PAGE_GONE_S = 30.0  # an ended call whose page has not polled for this long shuts down
STAGE_SETTLE_S = 5.0  # how long a reply waits for its stage shows, so their problems reach it
MAX_RECORDING_BYTES = 16 * 1024 * 1024  # about eight minutes of 16 kHz speech
STATE_FILE = Path(os.environ.get("TALK_STATE")
                  or Path(os.environ.get("TMPDIR") or "/tmp") / "talk" / "session.json")


def write_state_file(port: int, token: str, out_dir: Path, path: str = "/") -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.unlink(missing_ok=True)
    fd = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"port": port, "token": token, "out": str(out_dir), "pid": os.getpid(), "path": path,
                   "activity_script": str(Path(__file__).resolve().parent / "talk_activity.py")}, f)


def remove_state_file(port: int) -> None:
    """Only this server's own state file: a newer talk may have written its own since."""
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return
    if state.get("pid") == os.getpid() and state.get("port") == port:
        STATE_FILE.unlink(missing_ok=True)


def say(line: str) -> None:
    print(line, flush=True)




# ---------------------------------------------------------------------------
# Speech normalisation and the board
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "session"


def stage_view(item: dict) -> tuple[str, dict, str]:
    """A board item as a stage view: (name, source, title)."""
    title = item.get("title") or item["kind"]
    name = re.sub(r"[^a-z0-9]+", "-", (item.get("title") or "").lower()).strip("-")[:64]
    if not name:
        name = f"{item['kind']}-{item['id']}"
    if item["kind"] == "code":
        source = {"type": "inline", "format": "code", "path": item["path"], "start": item["start"],
                  "lines": item["lines"], "highlight": item["highlight"], "lang": item["lang"]}
    else:
        source = {"type": "inline", "format": item["kind"], "body": item["body"]}
    return name, source, title


def rebase(url: str, base: str | None) -> str:
    """The stage URL as reached from `base` (scheme and host), for a user at another machine."""
    if not base:
        return url
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return base.rstrip("/") + parts.path + (f"?{parts.query}" if parts.query else "")


# ---------------------------------------------------------------------------
# Speech normalisation: identifiers become words, markdown disappears
# ---------------------------------------------------------------------------

# Real acronyms are left alone; everything else in caps is read as words.
ACRONYMS = {
    "API", "APIS", "SQL", "JSON", "YAML", "HTTP", "HTTPS", "URL", "UUID", "CSV", "PDF", "HTML",
    "CSS", "JWT", "REST", "GRPC", "AWS", "GCP", "CPU", "GPU", "RAM", "SDK", "CLI", "IDE", "ADR",
    "PR", "CI", "CD", "UI", "UX", "ID", "IDS", "DB", "ETL", "KPI", "OK", "NAV", "ISIN", "FX",
    "ESG", "KYC", "AML", "MVCC", "ACID", "OAUTH", "SSO", "DNS", "TCP", "UDP", "IP", "VPN",
}

_SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_+[A-Za-z0-9]+)+\b")
_CAMEL = re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b")
_PASCAL = re.compile(r"\b(?:[A-Z][a-z0-9]+){2,}\b")
_CAPS_WORD = re.compile(r"\b[A-Z]{4,}\b")


def _words_of_identifier(token: str) -> str:
    parts = [p for p in re.split(r"_+", token) if p]
    out = []
    for part in parts:
        if part.isupper() and part not in ACRONYMS:
            out.append(part.lower())
        else:
            out.append(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", part).lower() if not part.isupper() else part)
    return " ".join(out)


def _split_humps(token: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", token).lower()


def speakable(text: str) -> str:
    """Make text safe to hand to a voice: EXTERNAL_ONLY -> 'external only', no markdown."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = text.replace("`", "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # markdown links
    text = _SNAKE.sub(lambda m: _words_of_identifier(m.group(0)), text)
    text = _CAMEL.sub(lambda m: _split_humps(m.group(0)), text)
    text = _PASCAL.sub(lambda m: _split_humps(m.group(0)), text)
    text = _CAPS_WORD.sub(lambda m: m.group(0) if m.group(0) in ACRONYMS else m.group(0).lower(), text)
    text = re.sub(r"\s*(->|=>|→)\s*", " to ", text)
    text = re.sub(r"(?m)^\s*(#+|[-*•]|\d+\.)\s+", "", text)  # headings, bullets
    text = re.sub(r"[*#>|~]", "", text)
    text = re.sub(r"(?<=\w)/(?=\w)", " or ", text)
    return re.sub(r"\s+", " ", text).strip()



def board_block_kind(marker: str) -> str | None:
    """'diagram' or 'table' when the marker opens a board block whose body follows, else None."""
    head = marker.partition("|")[0].strip().lower()
    if not head.startswith("show"):
        return None
    kind = head[4:].partition(":")[0].strip()
    return kind if kind in ("diagram", "table") else None


CLOSE_SHOW = re.compile(r"\[\[\s*/show\s*\]\]", re.IGNORECASE)


class MarkerFilter:
    """Pulls [[...]] markers out of streamed text, even when split across chunks.

    Inside a diagram or table block only [[/show]] is a marker: Mermaid's A[[Sub]] is body text.
    """

    def __init__(self):
        self._buf = ""
        self.in_block = False

    def feed(self, text: str) -> tuple[str, list[str]]:
        self._buf += text
        spoken, markers = "", []
        while True:
            start = self._buf.find("[[")
            if start < 0:
                keep = 1 if self._buf.endswith("[") else 0
                spoken += self._buf[: len(self._buf) - keep]
                self._buf = self._buf[len(self._buf) - keep :]
                return spoken, markers
            spoken += self._buf[:start]
            close = self._buf.find("]]", start)
            if close < 0:
                self._buf = self._buf[start:]
                return spoken, markers
            markers.append(self._buf[start + 2 : close].strip())
            self._buf = self._buf[close + 2 :]

    def flush(self) -> str:
        rest = "" if self._buf.startswith("[[") and not self.in_block else self._buf
        self._buf, self.in_block = "", False
        return rest

    def _block_text(self, out: list[tuple[str, str]]) -> bool:
        """Body text up to [[/show]]; True once the block has closed."""
        close = CLOSE_SHOW.search(self._buf)
        if close:
            if close.start():
                out.append(("text", self._buf[: close.start()]))
            out.append(("marker", "/show"))
            self._buf, self.in_block = self._buf[close.end() :], False
            return True
        # Hold back a tail that may be the start of [[/show]] split across chunks.
        keep = 0
        start = self._buf.rfind("[")
        if start > 0 and self._buf[start - 1] == "[":
            start -= 1
        if start >= 0 and "[[/show]]".startswith(re.sub(r"\s+", "", self._buf[start:]).lower()):
            keep = len(self._buf) - start
        if len(self._buf) - keep:
            out.append(("text", self._buf[: len(self._buf) - keep]))
        self._buf = self._buf[len(self._buf) - keep :]
        return False

    def feed_ordered(self, text: str) -> list[tuple[str, str]]:
        """Like feed, but keeps text and markers in the order they arrived."""
        self._buf += text
        out: list[tuple[str, str]] = []
        while True:
            if self.in_block and not self._block_text(out):
                return out
            start = self._buf.find("[[")
            if start < 0:
                keep = 1 if self._buf.endswith("[") else 0
                if len(self._buf) - keep:
                    out.append(("text", self._buf[: len(self._buf) - keep]))
                self._buf = self._buf[len(self._buf) - keep :]
                return out
            if start:
                out.append(("text", self._buf[:start]))
            close = self._buf.find("]]", start)
            if close < 0:
                self._buf = self._buf[start:]
                return out
            marker = self._buf[start + 2 : close].strip()
            out.append(("marker", marker))
            self._buf = self._buf[close + 2 :]
            self.in_block = board_block_kind(marker) is not None


class Board:
    """What the tutor shows on the page. Code is read from disk, never retyped by the model."""

    MAX_LINES = 60

    def __init__(self, code_dir: Path | None, log: "Call", on_add=None):
        self.code_dir = code_dir.resolve() if code_dir else None
        self.log = log
        self.items: list[dict] = []
        self.open: dict | None = None  # a diagram or table whose body is still streaming in
        self.problems: list[str] = []  # tags that could not be shown as asked, for the reply's sender
        self.on_add = on_add  # puts each item on the stage

    def marker(self, text: str) -> bool:
        """Handle a board marker; False if the marker isn't a board marker."""
        head, _, title = text.partition("|")
        head, title = head.strip(), title.strip()
        low = head.lower()
        if low == "/show":
            self.close_block()
            return True
        if not low.startswith("show"):
            return False
        kind, _, rest = head[4:].strip().partition(":")
        kind = kind.strip().lower()
        if board_block_kind(text):
            self.close_block()
            self.open = {"kind": kind, "title": title, "body": ""}
        elif kind == "code":
            self.add_code(rest.strip(), title)
        return True

    def close_block(self) -> None:
        """Put an open diagram or table on the board, without a ``` fence the model may have wrapped it in."""
        if not self.open:
            return
        body = self.open["body"].strip()
        body = re.sub(r"\A```[\w+-]*[ \t]*\n", "", body)
        body = re.sub(r"\n?```\Z", "", body)
        self.open["body"] = body.strip()
        self.add(self.open)
        self.open = None

    def problem(self, text: str) -> None:
        self.problems.append(text)
        say(f"board: {text}")

    def text(self, chunk: str) -> bool:
        """Swallow text that belongs to an open diagram or table; True when swallowed."""
        if self.open is None:
            return False
        self.open["body"] += chunk
        return True

    def add_code(self, spec: str, title: str) -> None:
        m = re.match(r"(?P<path>.+?):(?P<a>\d+)\s*-\s*(?P<b>\d+)(?:\s+highlight\s+(?P<ha>\d+)(?:\s*-\s*(?P<hb>\d+))?)?\s*$", spec)
        if not self.code_dir:
            self.problem(f"code not shown, talk was started without --code: {spec}")
            return
        if not m:
            self.problem(f"code not shown, expected <path>:<first>-<last>: {spec}")
            return
        path = (self.code_dir / m["path"].strip()).resolve()
        if not path.is_relative_to(self.code_dir) or not path.is_file():
            self.problem(f"code not shown, no such file in the code folder: {m['path'].strip()}")
            return
        a, b = int(m["a"]), int(m["b"])
        if a < 1 or b < a:
            self.problem(f"code not shown, bad line range {a}-{b} in {m['path'].strip()}")
            return
        all_lines = path.read_text(errors="replace").splitlines()
        if a > len(all_lines):
            self.problem(f"code not shown, {m['path'].strip()} has only {len(all_lines)} lines")
            return
        title = title or path.name
        if b - a + 1 > self.MAX_LINES:
            b = a + self.MAX_LINES - 1
            title += f" (first {self.MAX_LINES} lines)"
            self.problem(f"code cut to lines {a}-{b} of {m['path'].strip()}: at most {self.MAX_LINES} lines")
        elif b > len(all_lines):
            self.problem(f"code cut at line {len(all_lines)}, the end of {m['path'].strip()}")
        lines = all_lines[a - 1 : b]
        ha = int(m["ha"]) if m["ha"] else None
        hb = int(m["hb"]) if m["hb"] else ha
        self.add({"kind": "code", "title": title, "path": str(path.relative_to(self.code_dir)),
                  "start": a, "lines": lines, "highlight": [ha, hb] if ha else None,
                  "lang": path.suffix.lstrip(".") or "text"})

    def add(self, item: dict) -> None:
        item["id"] = len(self.items)
        self.items.append(item)
        self.log.board_item(item)
        if self.on_add:
            self.on_add(item)



# ---------------------------------------------------------------------------
# The call: what was said, what is on the stage, and the audio of every answer
# ---------------------------------------------------------------------------


class Call:
    """Everything one call holds. The page reads it through /api/state; the session through the turns."""

    def __init__(self, args, topic: str, out_dir: Path):
        self.args = args
        self.topic = topic
        self.out_dir = out_dir
        self.audio_dir = out_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript = out_dir / "transcript.md"
        self.transcript.write_text(f"# {topic}\n\n_talk · {dt.datetime.now():%Y-%m-%d %H:%M} · "
                                   f"VoiceStudio voice {args.voice}_\n\n")
        self.entries: list[dict] = []
        self.version = 0
        self.turns = TurnQueue()
        self.turn_count = 0
        self.board = Board(args.code, self, on_add=self.show_on_stage)
        self.activity: list[dict] = []
        self.owner_session = ""  # the session whose doorbell collects turns: only its tool calls are shown
        self.ended: str | None = None
        self.ended_at = 0.0
        self.closed = asyncio.Event()
        self.started = time.time()
        self.last_seen = 0.0  # the page's last poll
        self.last_turn = time.time()  # the last entry of any kind: the idle clock
        self.stage_cwd: str | None = None  # set by serve(); None in tests means "no stage"
        self.stage_pending: list = []
        # Speech calls and stage shows block: they run off the loop. Stage shows one at a time,
        # since each reads the stage's layout and writes it back.
        # VoiceStudio runs one speech job at a time; queueing here keeps a transcription behind one answer, not four.
        self.speech_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="speech")
        self.stage_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage")

    # -- the record ---------------------------------------------------------

    def add(self, who: str, text: str, **extra) -> dict:
        entry = {"id": len(self.entries), "who": who, "text": text, "at": time.time(), **extra}
        self.entries.append(entry)
        self.last_turn = entry["at"]
        self.changed()
        label = {"you": "You", "claude": "Claude", "status": "Claude, working", "note": "Note",
                 "board": "On the stage", "system": "Call"}[who]
        with self.transcript.open("a") as f:
            f.write(f"**{label}:** {text}\n\n")
        return entry

    def changed(self) -> None:
        self.version += 1

    def board_item(self, item: dict) -> None:
        """Board's hook: every item it adds is listed in the conversation."""
        self.add("board", item.get("title") or item["kind"])

    # -- turns --------------------------------------------------------------

    def offer(self, text: str, typed: bool) -> dict:
        self.turn_count += 1
        entry = self.add("you", text, typed=typed)
        self.turns.offer(f"t{self.turn_count}", [{"who": "you", "text": text}])
        return entry

    def collected(self) -> None:
        self.activity = []
        self.changed()

    def record_activity(self, body: dict) -> bool:
        """One tool call from the answering session. The hook runs in every session on this machine:
        the doorbell's own call names the session that answers, and every other session is ignored."""
        session = str(body.get("session_id", ""))
        if body.get("doorbell"):
            self.owner_session = self.owner_session or session
            return True
        if session != self.owner_session:
            return False
        self.turns.note_activity()  # alive, even through tools the page does not list
        now = time.monotonic()
        if body.get("phase") == "stop":  # the session stopped (or failed): nothing of it is still running
            for item in self.activity:
                if item["state"] == "running":
                    item["state"], item["seconds"] = "done", round(now - item["started"], 1)
            self.changed()
            return True
        if not body.get("label"):
            return False
        if body.get("phase") == "end":
            for item in reversed(self.activity):
                if item["tool"] == body.get("tool") and item["state"] == "running":
                    item["state"], item["seconds"] = "done", round(now - item["started"], 1)
                    break
            self.changed()
            return True
        self.activity.append({"label": str(body["label"])[:80], "tool": str(body.get("tool", "")),
                              "state": "running", "started": now, "seconds": None})
        self.changed()
        return True

    def activity_view(self) -> list[dict]:
        now = time.monotonic()
        return [{"label": a["label"], "state": a["state"],
                 "seconds": a["seconds"] if a["seconds"] is not None else round(now - a["started"], 1)}
                for a in self.activity[-8:]]

    # -- answers ------------------------------------------------------------

    def split_reply(self, text: str) -> str:
        """Take the markers out of a reply: board tags go to the stage, notes to the record.
        Returns what is left, the text that is shown and read aloud."""
        markers = MarkerFilter()
        parts = markers.feed_ordered(text) + [("text", markers.flush())]
        shown = ""
        for kind, chunk in parts:
            if kind == "marker":
                if chunk.lower().startswith("note:"):
                    self.add("note", chunk[5:].strip())
                elif not self.board.marker(chunk):
                    shown += f"[[{chunk}]]"
            elif not self.board.text(chunk):
                shown += chunk
        self.board.close_block()
        return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", shown)).strip()

    async def answer(self, text: str) -> dict:
        """Show an answer at once, then read it aloud in the background."""
        shown = self.split_reply(text)
        if not shown:
            return {}
        entry = self.add("claude", shown, audio=None, speech="pending")
        asyncio.get_running_loop().create_task(self.speak(entry))
        return entry

    async def speak(self, entry: dict) -> None:
        spoken = speakable(entry["text"])
        path = self.audio_dir / f"{entry['id']:04d}.mp3"
        loop = asyncio.get_running_loop()
        try:
            audio = await loop.run_in_executor(self.speech_pool, speech.synthesize, spoken, self.args.voice)
            path.write_bytes(audio)
            entry.update(audio=f"audio/{path.name}", speech="ready")
        except (speech.SpeechError, OSError) as err:
            entry.update(speech="failed", speech_error=str(err))
            say(f"speech: {err}")
        self.changed()

    # -- the stage ----------------------------------------------------------

    def show_on_stage(self, item: dict) -> None:
        """Put a board item on the stage, on the stage thread. A failure is a board problem."""
        if not self.stage_cwd:
            return
        name, source, title = stage_view(item)
        cwd = self.stage_cwd

        def show():
            stage_mod.show(cwd, name, source, title=title)

        fut = self.stage_pool.submit(show)
        self.stage_pending.append(fut)

    async def stage_settled(self, timeout: float = STAGE_SETTLE_S) -> None:
        pending, self.stage_pending = self.stage_pending, []
        if not pending:
            return
        done, _ = await asyncio.get_running_loop().run_in_executor(
            None, lambda: concurrent.futures.wait(pending, timeout=timeout))
        for fut in done:
            if fut.exception():
                self.board.problem(f"not shown on the stage: {fut.exception()}")

    # -- the end ------------------------------------------------------------

    def end(self, reason: str) -> None:
        if self.ended:
            return
        self.ended, self.ended_at = reason, time.time()
        self.add("system", f"The call ended: {reason}.")
        self.turns.finish(reason, str(self.transcript))
        say(f"talk: call ended ({reason}). Transcript {self.transcript}")

    def view(self) -> dict:
        return {"v": self.version, "entries": self.entries, "working": self.turns.working,
                "stalled": self.turns.stalled, "activity": self.activity_view() if self.turns.working else [],
                "ended": self.ended}


# ---------------------------------------------------------------------------
# HTTP: the page, the session's doorbell and replies, the activity hook
# ---------------------------------------------------------------------------


def build_app(call: Call, token: str, call_id: str, stage_url: str | None = None):
    from aiohttp import web

    def authorised(request) -> bool:
        return secrets.compare_digest(request.headers.get("X-Talk-Token", ""), token)

    def ours(request) -> bool:
        return secrets.compare_digest(request.match_info.get("call", ""), call_id)

    def forbidden():
        return web.json_response({"error": "forbidden"}, status=403)

    async def gone(request):
        return web.Response(text=GONE_PAGE, status=404, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def page(request):
        if not ours(request):
            return await gone(request)
        config = {"topic": call.topic, "token": token, "stageUrl": stage_url, "language": call.args.language,
                  "languages": list(speech.LANGUAGES)}
        html = PAGE.replace("__CONFIG__", json.dumps(config).replace("</", "<\\/"))
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def audio(request):
        if not ours(request) or not re.fullmatch(r"\d{4}\.mp3", request.match_info["name"]):
            return web.Response(status=404)
        path = call.audio_dir / request.match_info["name"]
        if not path.is_file():
            return web.Response(status=404)
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def state(request):
        if not authorised(request):
            return forbidden()
        call.last_seen = time.time()
        since = request.query.get("v")
        if since is not None and since == str(call.version):
            return web.json_response({"v": call.version, "same": True})
        return web.json_response(call.view())

    async def listen(request):
        """A recording from the page, as a 16 kHz mono WAV, becomes a turn."""
        if not authorised(request):
            return forbidden()
        if call.ended:
            return web.json_response({"error": "the call has ended"}, status=410)
        lang = request.query.get("lang", call.args.language)
        language = speech.LANGUAGES.get(lang, speech.LANGUAGES.get(call.args.language))
        wav = await request.read()
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(call.speech_pool, speech.transcribe, wav, language)
        except speech.SpeechError as err:
            return web.json_response({"error": str(err)}, status=502)
        if not text.strip():
            return web.json_response({"text": ""})
        return web.json_response({"text": text, "entry": call.offer(text, typed=False)})

    async def typed(request):
        if not authorised(request):
            return forbidden()
        if call.ended:
            return web.json_response({"error": "the call has ended"}, status=410)
        body = await request.json()
        text = str(body.get("text", "")).strip() if isinstance(body, dict) else ""
        if not text:
            return web.json_response({"error": "nothing to send"}, status=400)
        return web.json_response({"text": text, "entry": call.offer(text[:4000], typed=True)})

    async def stop(request):
        if authorised(request):
            call.end("ended from the page")
        return web.json_response({})

    async def close(request):
        if authorised(request):
            call.end("ended from the page")
            call.closed.set()
        return web.json_response({})

    async def next_turn(request):
        if not authorised(request):
            return forbidden()
        wait = min(max(float(request.query.get("wait", "25")), 0.0), 60.0)
        event = await call.turns.next(timeout=wait)
        if event is None:
            return web.Response(status=204)
        if event["type"] == "superseded":
            return web.json_response({"error": "a newer doorbell is waiting"}, status=409)
        if request.transport is None or request.transport.is_closing():
            call.turns.put_back(event)
            return web.Response(status=499)
        if event["type"] == "turn":
            call.collected()
        return web.json_response(event)

    async def activity(request):
        if not authorised(request):
            return forbidden()
        body = await request.json()
        return web.json_response({"recorded": call.record_activity(body if isinstance(body, dict) else {})})

    async def post_reply(request):
        if not authorised(request):
            return forbidden()
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"error": "a JSON object is required"}, status=400)
        status, text, end = str(body.get("status", "")).strip(), str(body.get("text", "")), bool(body.get("end"))
        if status and end:
            return web.json_response({"error": "a status cannot end the call; send the wrap-up with end"},
                                     status=400)
        if call.ended:
            return web.json_response({"error": "the call has ended"}, status=410)
        result = call.turns.accept_reply(str(body.get("id", "")), final=not status)
        if result == "unknown":
            return web.json_response({"error": "no such turn in this call"}, status=404)
        if status:
            if result != "ok":
                return web.json_response({"ok": True, "ignored": "the turn was already answered; status not shown"})
            call.add("status", status[:120])
            return web.json_response({"ok": True})
        problems_from = len(call.board.problems)
        await call.answer(text)
        await call.stage_settled()
        if end:
            call.end("wrapped up by Claude")
        return web.json_response({"ok": True, "board_problems": call.board.problems[problems_from:]})

    app = web.Application(client_max_size=MAX_RECORDING_BYTES)
    app.add_routes([
        web.get("/", gone),
        web.get("/c/{call}", page),
        web.get("/c/{call}/audio/{name}", audio),
        web.get("/api/state", state),
        web.post("/api/listen", listen),
        web.post("/api/say", typed),
        web.post("/api/stop", stop),
        web.post("/api/close", close),
        web.get("/api/turn", next_turn),
        web.post("/api/reply", post_reply),
        web.post("/api/activity", activity),
    ])
    return app


async def watch(call: Call) -> None:
    """End a call nobody opened or nobody talks in; close an ended one once its page is gone."""
    while not call.closed.is_set():
        await asyncio.sleep(1)
        now = time.time()
        if not call.ended:
            if not call.last_seen and now - call.started > OPEN_TIMEOUT_MIN * 60:
                call.end(f"the page was not opened within {OPEN_TIMEOUT_MIN} minutes")
            elif now - call.last_turn > call.args.idle_minutes * 60:
                call.end(f"nothing was said for {call.args.idle_minutes} minutes")
        elif now - call.ended_at > LINGER_S or now - call.last_seen > PAGE_GONE_S:
            call.closed.set()


def warm_up(voice: str) -> None:
    try:
        speech.synthesize("Ready.", voice)
    except speech.SpeechError as err:
        say(f"speech: warm-up failed: {err}")


async def serve(call: Call) -> None:
    from aiohttp import web

    args = call.args
    # The same folder `stage.py show` falls back to (the git root), so both reach one stage.
    stage_cwd = str(args.code) if args.code else stage_mod.repo_root(Path.cwd())
    try:
        stage_row = stage_mod.ensure_stage(stage_cwd, title=f"Talk · {call.topic}")
    except stage_mod.DAEMON_ERRORS + (ValueError,) as err:
        raise SystemExit(f"talk needs the webcompanion daemon for its stage: {err}")
    stage_url = rebase(stage_row["url"], args.stage_base)
    call.stage_cwd = stage_cwd

    token = secrets.token_urlsafe(24)
    call_id = secrets.token_urlsafe(16)
    runner = web.AppRunner(build_app(call, token, call_id, stage_url=stage_url), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    write_state_file(args.port, token, call.out_dir, f"/c/{call_id}")

    path = f"/c/{call_id}"
    say(f"Open http://127.0.0.1:{args.port}{path}")
    if args.url_base:
        say(f"From another machine: {args.url_base.rstrip('/')}{path}")
    say(f"Stage {stage_url} (folder {stage_cwd})")
    if not args.no_open:
        webbrowser.open(f"http://127.0.0.1:{args.port}{path}")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, lambda: (call.end("interrupted"), call.closed.set()))
    watcher = asyncio.create_task(watch(call))
    # The first speech after VoiceStudio starts loads its model (about 11 s): pay that before the first answer.
    loop.run_in_executor(call.speech_pool, warm_up, args.voice)
    try:
        await call.closed.wait()
    finally:
        watcher.cancel()
        # A doorbell already waiting gets the end at once; a few seconds more cover one re-arming now.
        try:
            await asyncio.wait_for(call.turns.end_collected.wait(), 5)
        except asyncio.TimeoutError:
            pass
        remove_state_file(args.port)
        call.speech_pool.shutdown(wait=False, cancel_futures=True)
        call.stage_pool.shutdown(wait=False, cancel_futures=True)
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Doctor: VoiceStudio, a round trip through it, the stage's daemon
# ---------------------------------------------------------------------------


def doctor(args) -> int:
    ok = True
    try:
        info = speech.ensure_running(say=say)
        say(f"[ok] VoiceStudio at {speech.base_url()}: {info.get('status')} on {info.get('device')}, "
            f"version {info.get('version')}")
    except speech.SpeechError as err:
        say(f"[FAIL] {err}")
        return 1
    phrase = "The doorbell is ready."
    try:
        t = time.time()
        wav = speech.synthesize(phrase, args.voice, fmt="wav")
        say(f"[ok] text to speech with {args.voice} in {time.time() - t:.1f}s")
        t = time.time()
        heard = speech.transcribe(wav, "en")
        good = "doorbell" in heard.lower()
        ok &= good
        say(f"[{'ok' if good else 'FAIL'}] speech to text heard {heard!r} in {time.time() - t:.1f}s")
    except speech.SpeechError as err:
        ok = False
        say(f"[FAIL] {err}")
    problem = stage_mod.daemon_status()
    ok &= not problem
    say(f"[FAIL] webcompanion daemon (the stage): {problem}" if problem else "[ok] webcompanion daemon (the stage)")
    say("all checks passed" if ok else "some checks failed")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A spoken conversation with a Claude Code session, on VoiceStudio speech.")
    parser.add_argument("--topic", help="what the call is about (required unless --doctor)")
    parser.add_argument("--code", type=Path, help="the folder [[show code: ...]] reads from, and the stage's folder")
    parser.add_argument("--out", type=Path, help="where the transcript and audio go")
    parser.add_argument("--voice", default=os.environ.get("TALK_VOICE", speech.DEFAULT_VOICE),
                        help=f"VoiceStudio voice: an OpenAI voice name, which maps to the active engine's default "
                             f"voice, or a VoiceStudio profile id (default {speech.DEFAULT_VOICE})")
    parser.add_argument("--language", choices=list(speech.LANGUAGES), default=os.environ.get("TALK_LANGUAGE", "auto"),
                        help="the language the page listens for first; auto detects it; the page can switch "
                             "(default auto)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TALK_PORT", DEFAULT_PORT)))
    parser.add_argument("--url-base", default=os.environ.get("TALK_URL_BASE"),
                        help="this server's address as reached from another machine (scheme and host), "
                             "printed as a second link")
    parser.add_argument("--stage-base", default=os.environ.get("TALK_STAGE_BASE"),
                        help="the webcompanion daemon's address as reached from the browser "
                             "(scheme and host); default: the daemon's own")
    parser.add_argument("--no-open", action="store_true", help="don't open the page in the default browser")
    parser.add_argument("--idle-minutes", type=int, default=60, help="end the call after this long with no turn")
    parser.add_argument("--doctor", action="store_true", help="check VoiceStudio with a round trip, and the stage")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.code:
        args.code = args.code.expanduser().resolve()
        if not args.code.is_dir():
            parser.error(f"--code: not a folder: {args.code}")
    if args.doctor:
        return doctor(args)
    if not args.topic:
        parser.error("--topic is required")
    try:
        speech.ensure_running(say=say)
    except speech.SpeechError as err:
        say(f"{err}. Start the VoiceStudio app, then run again.")
        return 2
    out_dir = args.out or SESSIONS_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(args.topic)}"
    out_dir.mkdir(parents=True, exist_ok=True)

    async def run():
        await serve(Call(args, args.topic, out_dir))

    try:
        asyncio.run(run())
    except OSError as err:
        say(f"Error: {err}. Is port {args.port} already in use? Try --port.")
        return 1
    return 0


GONE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Talk</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F5F6F8;color:#1B2230;
font:15px/1.6 Inter,system-ui,-apple-system,sans-serif;padding:0 16px}main{max-width:420px}h1{font-size:18px;margin:0 0 6px}
p{margin:0;color:#667085}</style></head><body><main><h1>This call link is not active</h1>
<p>The call may have ended, or the link is incomplete. Ask the Claude session for the current link.</p></main></body></html>"""


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Talk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  color-scheme:light;
  --bg:#F5F6F8; --panel:#FFFFFF; --line:#E1E5EA; --ink:#1B2230; --muted:#667085; --faint:#98A2B3;
  --acc:#0F6E74; --acc-soft:#EAF4F4; --acc-mid:#B7DADB; --you:#2F5BD3; --you-soft:#EEF2FD; --claude:#A6520B; --claude-soft:#FDF3EA;
  --bad:#B42318; --bad-soft:#FEF3F2; --warn:#B54708; --warn-soft:#FEF6EE;
  --sans:"Inter",system-ui,-apple-system,sans-serif; --mono:"Geist Mono",ui-monospace,Menlo,monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 14px/1.5 var(--sans);-webkit-font-smoothing:antialiased;overflow:hidden}
button{font:inherit;color:inherit}
.app{height:100%;display:grid;grid-template-columns:minmax(380px,440px) 1fr}
aside{background:var(--panel);border-right:1px solid var(--line);display:grid;grid-template-rows:auto minmax(0,1fr) auto auto;grid-template-columns:minmax(0,1fr);min-height:0;min-width:0;overflow:hidden}
aside > *{min-width:0}
.top{display:flex;align-items:center;gap:12px;padding:16px 18px;border-bottom:1px solid var(--line)}
.top .title{flex:1;min-width:0}
.top h1{margin:0;font:600 16px/1.25 var(--sans);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.top p{margin:2px 0 0;font-size:12px;color:var(--muted)}
.btn{font:500 13px var(--sans);padding:8px 12px;border-radius:8px;border:1px solid var(--line);background:var(--panel);cursor:pointer;display:inline-flex;gap:6px;align-items:center;justify-content:center;min-height:36px;white-space:nowrap}
.btn:hover:not(:disabled){background:var(--bg)}
.btn:disabled{opacity:.45;cursor:default}
.btn:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.btn.danger{color:var(--bad);border-color:#F3C5C0}
.btn.primary{background:var(--acc);border-color:var(--acc);color:#fff}
.btn.primary:hover:not(:disabled){background:#0B5A5F}
.btn.rec{background:var(--bad);border-color:var(--bad);color:#fff}
.btn[aria-pressed="true"]{background:var(--ink);border-color:var(--ink);color:var(--panel)}
.btn.toggle[aria-pressed="true"]{background:var(--acc-soft);border-color:var(--acc-mid);color:var(--acc)}
.btn svg{flex:none}
.convo{overflow:auto;padding:16px 18px;display:flex;flex-direction:column;gap:14px;min-height:0}
.empty{color:var(--faint);font-size:13.5px;margin:auto 0;text-align:center}
.turn .who{font:600 10.5px var(--sans);letter-spacing:.12em;text-transform:uppercase;margin-bottom:2px;display:flex;gap:8px;align-items:baseline}
.turn .who small{font:400 11px var(--sans);letter-spacing:0;text-transform:none;color:var(--faint)}
.turn.you .who{color:var(--you)} .turn.claude .who{color:var(--claude)}
.turn .text{font:400 15px/1.6 var(--sans);white-space:pre-wrap;overflow-wrap:anywhere}
.turn.claude{border-left:3px solid transparent;padding-left:10px;margin-left:-13px}
.turn.claude.now{border-left-color:var(--claude)}
.turn .play{margin-top:6px}
.turn .speech{margin-top:6px;font-size:12.5px;color:var(--muted)}
.turn .speech.bad{color:var(--bad)}
.line{font-size:12.5px;color:var(--muted)}
.line.status::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--acc);margin-right:8px;vertical-align:middle}
.chip{align-self:flex-start;font-size:12px;padding:3px 10px;border-radius:999px;background:var(--acc-soft);color:var(--acc);max-width:100%;overflow-wrap:anywhere}
.chip.note{background:var(--warn-soft);color:var(--warn)}
.line.system{text-align:center;color:var(--faint)}
.working{display:flex;flex-direction:column;gap:4px;padding:10px 12px;border-radius:10px;background:var(--acc-soft)}
.working b{font:600 13px var(--sans);color:var(--acc);display:flex;gap:8px;align-items:center}
.working ol{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:2px}
.working li{font:400 12px var(--mono);color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.working li.run{color:var(--ink)}
.stall{font-size:12.5px;color:var(--warn);background:var(--warn-soft);border-radius:8px;padding:8px 10px}
.spin{width:12px;height:12px;border-radius:50%;border:2px solid var(--acc);border-right-color:transparent;animation:spin .8s linear infinite;flex:none}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
.player{border-top:1px solid var(--line);padding:12px 16px;display:flex;flex-direction:column;gap:8px;background:var(--claude-soft)}
.player[hidden]{display:none}
.ptitle{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;color:var(--muted)}
.ptitle b{font-weight:600;color:var(--claude);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.ptitle span{font:400 12px var(--mono);white-space:nowrap}
input[type=range]{width:100%;accent-color:var(--claude);margin:0}
.prow{display:flex;gap:6px}
.prow .btn{flex:1;padding:8px 6px}
.prow .btn.big{flex:1.6}
.speeds{display:flex;gap:4px;align-items:center}
.speeds .lbl{font-size:12px;color:var(--muted);margin-right:4px}
.speeds .btn{flex:1;padding:6px 4px;min-height:32px;font-size:12.5px}
.compose{border-top:1px solid var(--line);padding:12px 16px 14px;display:flex;flex-direction:column;gap:8px}
.crow{display:flex;gap:8px;align-items:stretch}
.crow .grow{flex:1}
.talk{flex:1;min-height:48px;font-size:15px}
.recinfo{flex:1;display:flex;flex-direction:column;justify-content:center;gap:4px;font:500 13px var(--sans);color:var(--bad)}
.recinfo .meter{height:4px;border-radius:2px;background:var(--bad-soft);overflow:hidden}
.recinfo .meter i{display:block;height:100%;width:0;background:var(--bad);transition:width .06s linear}
.recinfo .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--bad);margin-right:6px;animation:pulse 1.2s infinite}
.lang{display:flex;gap:4px}
.lang .btn{min-width:44px;padding:6px 8px}
textarea{flex:1;resize:none;font:400 14px/1.4 var(--sans);padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);min-height:38px;max-height:120px}
textarea:focus{outline:2px solid var(--acc);outline-offset:-1px;background:var(--panel)}
.err{font-size:12.5px;color:var(--bad)}
.err:empty{display:none}
.ended{font-size:13px;color:var(--muted);background:var(--bg);border-radius:8px;padding:8px 10px;display:flex;gap:8px;align-items:center;justify-content:space-between}
[hidden]{display:none!important}
main{display:grid;min-height:0}
main iframe#stage{width:100%;height:100%;border:0;background:var(--bg)}
.nostage{color:var(--faint);font-size:14px;margin:auto}
@media (max-width:900px){
  body{overflow:auto}
  .app{display:flex;flex-direction:column;height:auto;min-height:100%}
  aside{border-right:0;border-bottom:1px solid var(--line);height:100dvh;position:sticky;top:0}
  main{min-height:80vh}
}
@media (prefers-reduced-motion:reduce){.spin,.recinfo .dot{animation:none!important}}
</style></head>
<body>
<div class="app">
<aside>
  <header class="top">
    <div class="title"><h1 id="topic"></h1><p>Talk · press Talk, speak, press Send</p></div>
    <button class="btn danger" id="end" type="button">End call</button>
  </header>
  <section class="convo" id="convo" aria-live="polite"><p class="empty" id="empty">Press <b>Talk</b> below and say what you want to discuss.</p></section>
  <section class="player" id="player" aria-label="Answer player">
    <div class="ptitle"><b id="ptitle">No answer yet</b><span id="ptime">0:00 / 0:00</span></div>
    <input type="range" id="seek" min="0" max="0" step="0.1" value="0" aria-label="Position">
    <div class="prow">
      <button class="btn" id="back15" type="button" aria-label="Back 15 seconds">&#8634; 15s</button>
      <button class="btn" id="back5" type="button" aria-label="Back 5 seconds">&#8634; 5s</button>
      <button class="btn primary big" id="playpause" type="button">Play</button>
      <button class="btn" id="fwd5" type="button" aria-label="Forward 5 seconds">5s &#8635;</button>
    </div>
    <div class="speeds" id="speeds"><span class="lbl">Speed</span></div>
    <div class="prow"><button class="btn toggle" id="autoplay" type="button" aria-pressed="true">Auto-play new answers: on</button></div>
    <audio id="audio" preload="auto"></audio>
  </section>
  <section class="compose" id="compose">
    <div class="crow" id="idle">
      <button class="btn primary talk" id="talk" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5"/></svg>
        Talk</button>
      <div class="lang" id="lang" role="group" aria-label="Language I speak"></div>
    </div>
    <div class="crow" id="recording" hidden>
      <div class="recinfo"><span><span class="dot"></span>Recording <span id="rectime">0:00</span></span><div class="meter"><i id="meter"></i></div></div>
      <button class="btn" id="cancel" type="button">Cancel</button>
      <button class="btn primary" id="send" type="button">Send</button>
    </div>
    <div class="crow" id="busy" hidden><div class="recinfo" style="color:var(--acc)"><span><span class="spin" style="display:inline-block;vertical-align:middle;margin-right:8px"></span>Turning your words into text…</span></div></div>
    <div class="crow" id="typed">
      <textarea id="text" rows="1" placeholder="Or type here" aria-label="Type a message"></textarea>
      <button class="btn" id="sendtext" type="button">Send text</button>
    </div>
    <div class="ended" id="ended" hidden><span id="endedtext">The call has ended.</span><button class="btn" id="close" type="button">Close</button></div>
    <div class="err" id="err" role="alert"></div>
  </section>
</aside>
<main><iframe id="stage" title="Stage" allow="clipboard-read; clipboard-write"></iframe><p class="nostage" id="nostage" hidden>The stage is not available for this call.</p></main>
</div>
<script>
const CFG = __CONFIG__;
const $ = id => document.getElementById(id);
const SPEEDS = [0.75, 0.85, 1, 1.25, 1.5];
const store = {get(k, d){ try { const v = localStorage.getItem("talk." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
               set(k, v){ try { localStorage.setItem("talk." + k, JSON.stringify(v)); } catch {} }};
const api = (path, opts = {}) => fetch(path, {...opts, headers: {"X-Talk-Token": CFG.token, ...(opts.headers || {})}});
const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };

$("topic").textContent = CFG.topic; document.title = "Talk · " + CFG.topic;
if (CFG.stageUrl) $("stage").src = CFG.stageUrl; else { $("stage").remove(); $("nostage").hidden = false; }

// ---- state -------------------------------------------------------------
let view = {v: -1, entries: [], working: false, stalled: false, activity: [], ended: null};
let seen = null;            // ids of answers that existed when the page loaded: never auto-played
let current = null;         // the entry in the player
let language = store.get("language", CFG.language);
let speed = store.get("speed", 1);
let autoplay = store.get("autoplay", true);
let recorder = null;
let busy = false;
let errTimer = null;

function showError(text) { $("err").textContent = text || ""; clearTimeout(errTimer); if (text) errTimer = setTimeout(() => $("err").textContent = "", 12000); }

// ---- the conversation --------------------------------------------------
function render() {
  const box = $("convo"), atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren();
  if (!view.entries.length && !view.working) { const p = document.createElement("p"); p.className = "empty"; p.innerHTML = "Press <b>Talk</b> below and say what you want to discuss."; box.append(p); }
  for (const e of view.entries) {
    let el;
    if (e.who === "you" || e.who === "claude") {
      el = document.createElement("div"); el.className = "turn " + e.who + (current && current.id === e.id ? " now" : "");
      const who = document.createElement("div"); who.className = "who"; who.textContent = e.who === "you" ? "You" : "Claude";
      if (e.who === "claude") { const s = document.createElement("small"); s.textContent = "answer " + e.n; who.append(s); }
      if (e.typed) { const s = document.createElement("small"); s.textContent = "typed"; who.append(s); }
      const text = document.createElement("div"); text.className = "text"; text.textContent = e.text;
      el.append(who, text);
      if (e.who === "claude") {
        if (e.speech === "ready") {
          const b = document.createElement("button"); b.className = "btn play"; b.type = "button";
          const playing = current && current.id === e.id && !$("audio").paused;
          b.textContent = playing ? "Pause" : "▶ Play"; b.onclick = () => playing ? audio.pause() : load(e, true); el.append(b);
        } else {
          const s = document.createElement("div"); s.className = "speech" + (e.speech === "failed" ? " bad" : "");
          s.textContent = e.speech === "failed" ? "Not read aloud: " + (e.speech_error || "speech failed") : "Preparing the audio…"; el.append(s);
        }
      }
    } else if (e.who === "status") {
      el = document.createElement("div"); el.className = "line status"; el.textContent = "Claude: " + e.text;
    } else if (e.who === "board" || e.who === "note") {
      el = document.createElement("div"); el.className = "chip" + (e.who === "note" ? " note" : ""); el.textContent = (e.who === "note" ? "Noted: " : "On the stage: ") + e.text;
    } else {
      el = document.createElement("div"); el.className = "line system"; el.textContent = e.text;
    }
    box.append(el);
  }
  if (view.working && !view.ended) {
    const w = document.createElement("div"); w.className = "working";
    const b = document.createElement("b"); b.innerHTML = '<span class="spin"></span>Claude is working'; w.append(b);
    if (view.activity.length) { const ol = document.createElement("ol"); for (const a of view.activity) { const li = document.createElement("li"); const run = a.state === "running"; li.className = run ? "run" : ""; li.textContent = (run ? "→ " : "✓ ") + a.label + "  " + Math.round(a.seconds) + "s"; ol.append(li); } w.append(ol); }
    box.append(w);
  }
  if (view.stalled && !view.ended) { const s = document.createElement("div"); s.className = "stall"; s.textContent = "Claude has not picked this up yet. Check the terminal: the session may be waiting for a permission."; box.append(s); }
  if (atEnd) box.scrollTop = box.scrollHeight;
  const ended = !!view.ended;
  $("ended").hidden = !ended; $("endedtext").textContent = ended ? "The call has ended: " + view.ended + ". Answers can still be replayed." : "";
  $("idle").hidden = ended || !!recorder || busy; $("typed").hidden = ended; $("end").disabled = ended;
}

async function poll() {
  for (;;) {
    try {
      const r = await api("/api/state?v=" + view.v);
      if (r.ok) {
        const body = await r.json();
        if (!body.same) {
          view = body;
          if (seen === null) seen = new Set(view.entries.filter(e => e.who === "claude").map(e => e.id));
          let n = 0; for (const e of view.entries) if (e.who === "claude") e.n = ++n;
          if (current) current = view.entries.find(e => e.id === current.id) || current;
          maybeAutoplay();
          render();
        }
      }
    } catch (err) { /* the server may be gone after the call ended */ }
    await new Promise(r => setTimeout(r, 800));
  }
}

// ---- the player --------------------------------------------------------
const audio = $("audio");
function audioUrl(e) { return location.pathname.replace(/\/$/, "") + "/" + e.audio; }
function load(e, play) {
  current = e; $("player").hidden = false;
  if (audio.dataset.id !== String(e.id)) { audio.src = audioUrl(e); audio.dataset.id = e.id; }
  audio.playbackRate = speed; audio.preservesPitch = true;
  $("ptitle").textContent = "Answer " + (e.n || "") + " · " + e.text.slice(0, 60) + (e.text.length > 60 ? "…" : "");
  if (play) audio.play().catch(() => showError("The browser blocked playback. Press Play."));
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({title: "Answer " + (e.n || ""), artist: "Claude", album: CFG.topic});
  render(); paintPlayer();
}
function maybeAutoplay() {
  const fresh = view.entries.filter(e => e.who === "claude" && e.speech === "ready" && !seen.has(e.id));
  if (!fresh.length) return;
  for (const e of fresh) seen.add(e.id);
  const last = fresh[fresh.length - 1];
  if (!current || audio.paused || audio.ended) load(last, autoplay && !recorder);
}
function paintPlayer() {
  for (const id of ["back15", "back5", "playpause", "fwd5", "seek"]) $(id).disabled = !current;
  $("playpause").textContent = audio.paused ? (audio.ended || audio.currentTime >= (audio.duration || 1) ? "Play again" : "Play") : "Pause";
  $("seek").max = audio.duration || 0; $("seek").value = audio.currentTime || 0;
  $("ptime").textContent = fmt(audio.currentTime) + " / " + fmt(audio.duration);
  for (const b of $("speeds").querySelectorAll("button")) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === speed));
  $("autoplay").setAttribute("aria-pressed", String(autoplay)); $("autoplay").textContent = "Auto-play new answers: " + (autoplay ? "on" : "off");
}
function skip(by) { audio.currentTime = Math.min(Math.max(0, audio.currentTime + by), audio.duration || 0); paintPlayer(); }
$("playpause").onclick = () => { if (audio.paused) audio.play().catch(() => {}); else audio.pause(); };
$("back15").onclick = () => skip(-15); $("back5").onclick = () => skip(-5); $("fwd5").onclick = () => skip(5);
$("seek").oninput = () => { audio.currentTime = Number($("seek").value); paintPlayer(); };
for (const s of SPEEDS) {
  const b = document.createElement("button"); b.className = "btn"; b.type = "button"; b.dataset.speed = s; b.textContent = s + "×";
  b.onclick = () => { speed = s; store.set("speed", s); audio.playbackRate = s; paintPlayer(); };
  $("speeds").append(b);
}
$("autoplay").onclick = () => { autoplay = !autoplay; store.set("autoplay", autoplay); paintPlayer(); };
for (const ev of ["play", "pause", "ended", "timeupdate", "durationchange", "loadedmetadata"]) audio.addEventListener(ev, paintPlayer);
for (const ev of ["play", "pause", "ended"]) audio.addEventListener(ev, render);
if ("mediaSession" in navigator) {
  const ms = navigator.mediaSession;
  ms.setActionHandler("play", () => audio.play()); ms.setActionHandler("pause", () => audio.pause());
  ms.setActionHandler("seekbackward", d => skip(-(d.seekOffset || 5))); ms.setActionHandler("seekforward", d => skip(d.seekOffset || 5));
}
paintPlayer();

// ---- talking -----------------------------------------------------------
for (const code of CFG.languages) {
  const b = document.createElement("button"); b.className = "btn"; b.type = "button";
  b.textContent = code === "auto" ? "Auto" : code.toUpperCase();
  b.title = {auto: "Detect the language I speak", en: "I speak English", el: "I speak Greek"}[code] || code;
  b.onclick = () => { language = code; store.set("language", code); paintLang(); };
  b.dataset.lang = code; $("lang").append(b);
}
function paintLang() { for (const b of $("lang").children) b.setAttribute("aria-pressed", String(b.dataset.lang === language)); }
paintLang();

function setMode(mode) {
  busy = mode === "busy";
  $("idle").hidden = mode !== "idle" || !!view.ended; $("recording").hidden = mode !== "recording"; $("busy").hidden = mode !== "busy";
}

async function startRecording() {
  showError("");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showError("This page cannot reach a microphone. Open it over https or on localhost."); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}}); }
  catch (err) { showError("No microphone: " + err.message); return; }
  audio.pause();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  node.onaudioprocess = ev => {
    const d = ev.inputBuffer.getChannelData(0); chunks.push(new Float32Array(d));
    let peak = 0; for (let i = 0; i < d.length; i += 16) peak = Math.max(peak, Math.abs(d[i]));
    $("meter").style.width = Math.min(100, peak * 160) + "%";
  };
  source.connect(node); node.connect(ctx.destination);
  const started = Date.now();
  const timer = setInterval(() => $("rectime").textContent = fmt((Date.now() - started) / 1000), 250);
  recorder = {stream, ctx, source, node, chunks, timer};
  $("rectime").textContent = "0:00"; setMode("recording");
}

function stopRecording() {
  const r = recorder; recorder = null;
  clearInterval(r.timer); r.node.disconnect(); r.source.disconnect();
  r.stream.getTracks().forEach(t => t.stop()); r.ctx.close();
  return r;
}

function toWav(chunks, rate) {
  const total = chunks.reduce((n, c) => n + c.length, 0), all = new Float32Array(total);
  let at = 0; for (const c of chunks) { all.set(c, at); at += c.length; }
  const ratio = rate / 16000, n = Math.floor(total / ratio), pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), b = Math.min(total, Math.max(a + 1, Math.floor((i + 1) * ratio)));
    let sum = 0; for (let j = a; j < b; j++) sum += all[j];
    const v = Math.max(-1, Math.min(1, sum / (b - a))); pcm[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
  }
  const buf = new ArrayBuffer(44 + pcm.byteLength), dv = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); dv.setUint32(4, 36 + pcm.byteLength, true); str(8, "WAVE"); str(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, 16000, true);
  dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, "data"); dv.setUint32(40, pcm.byteLength, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], {type: "audio/wav"});
}

async function sendRecording() {
  const r = stopRecording();
  const wav = toWav(r.chunks, r.ctx.sampleRate);
  setMode("busy");
  try {
    const resp = await api("/api/listen?lang=" + language, {method: "POST", body: wav, headers: {"Content-Type": "audio/wav"}});
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) showError(body.error || "Sending failed: HTTP " + resp.status);
    else if (!body.text) showError("Nothing was heard. Try again, a little closer to the microphone.");
    view.v = -1;
  } catch (err) { showError("Sending failed: " + err.message); }
  setMode("idle");
}

async function sendText() {
  const text = $("text").value.trim(); if (!text) return;
  $("sendtext").disabled = true;
  try {
    const resp = await api("/api/say", {method: "POST", body: JSON.stringify({text}), headers: {"Content-Type": "application/json"}});
    const body = await resp.json().catch(() => ({}));
    if (resp.ok) { $("text").value = ""; view.v = -1; } else showError(body.error || "Sending failed: HTTP " + resp.status);
  } catch (err) { showError("Sending failed: " + err.message); }
  $("sendtext").disabled = false;
}

$("talk").onclick = startRecording;
$("send").onclick = sendRecording;
$("cancel").onclick = () => { stopRecording(); setMode("idle"); };
$("sendtext").onclick = sendText;
$("text").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendText(); } });
$("end").onclick = () => api("/api/stop", {method: "POST"}).then(() => { view.v = -1; });
$("close").onclick = () => api("/api/close", {method: "POST"}).finally(() => { $("close").disabled = true; $("endedtext").textContent = "Closed. You can close this tab."; });

setMode("idle");
poll();
</script>
</body></html>
"""


if __name__ == "__main__":
    sys.exit(main())
