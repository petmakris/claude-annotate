# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "aiohttp>=3.10,<4",
#   "azure-cognitiveservices-speech>=1.40,<2",
# ]
# ///
"""talk: a spoken conversation with a Claude Code session, one turn at a time.

    browser page: press Talk, speak, press Send
        -> this script -> speech to text -> a turn the session collects (talk_client.py doorbell)
    the session answers (talk_client.py reply)
        -> board tags go on the stage, the rest -> text to speech, the whole answer in one go,
           -> one audio file the page plays, with pause, skip back and speed buttons

    uv run --script talk.py --topic "The findings deck" --code <repo>
    uv run --script talk.py --doctor
    uv run --script talk.py --restart

One server on this machine holds every call, one per Claude Code session. A launch starts it when
none runs, opens a call on it and exits; the server exits once no call is left. The user talks in
one call at a time: that call holds the floor, and every other call's voice pauses.

A call outlives the process that serves it. Each open call keeps its state in the run folder, and a
server that stops (`--restart`, a kill, a crash) ends none of them: the next server on the port
carries them on under the same id and token, and the page and the session's doorbell reconnect.

Speech runs on Azure when its key is found, else in the VoiceStudio app on this machine (speech.py).
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import concurrent.futures
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html import escape as html_escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_turns import TurnQueue  # noqa: E402
import talk_files  # noqa: E402
import talk_service  # noqa: E402
import speech  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skills.stage import stage as stage_mod  # noqa: E402
from skills.stage import model as stage_model  # noqa: E402
from skills.stage import scene as stage_scene  # noqa: E402

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "talk"
SESSIONS_DIR = DATA_DIR / "sessions"
DEFAULT_PORT = 8766
LINGER_S = 30 * 60  # after the call ends, the page can still replay its answers for this long
PAGE_GONE_S = 30.0  # an ended call whose page has not polled for this long shuts down
STAGE_SETTLE_S = 5.0  # how long a reply waits for its stage shows, so their problems reach it
MAX_RECORDING_BYTES = 16 * 1024 * 1024  # about eight minutes of 16 kHz speech
IDLE_EXIT_S = 5 * 60  # the server exits after this long with no call open
HANDOVER_S = 8.0
SERVER_START_S = 30.0  # how long a launch waits for a server it started to answer
PORT_WAIT_S = 10.0
REGISTER_S = 180.0  # how long a launch waits for its call: VoiceStudio may need a minute to start
HOME_COOKIE = "talk_home"
SKILL_DIR = Path(__file__).resolve().parent
STATIC_DIR = SKILL_DIR / "static"
STATIC_TYPES = {".css": "text/css", ".js": "text/javascript"}


def say(line: str) -> None:
    print(line, flush=True)


def new_call_id() -> str:
    """A call id that never starts with '-' or '_', so `--call <id>` is never read as an option."""
    while True:
        call_id = secrets.token_urlsafe(16)
        if call_id[0].isalnum():
            return call_id


def code_version() -> str:
    """A hash of the code a server runs, so a launch can tell a server that runs older code."""
    digest = hashlib.sha1()
    for path in sorted([*SKILL_DIR.glob("*.py"), *(SKILL_DIR / "static").glob("*"),
                        *(SKILL_DIR.parent / "stage").glob("*.py")]):
        try:
            digest.update(path.name.encode() + path.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()[:12]


# ---------------------------------------------------------------------------
# One VoiceStudio queue for every call
# ---------------------------------------------------------------------------


class SpeechQueue:
    """VoiceStudio runs one speech job at a time, so every call shares one queue and one worker.
    Each job waits in a lane, and the worker always takes the job whose lane ranks first at that
    moment. Lanes rank: recordings to turn into text, then the answers of the call that holds the
    floor, then every other call's answers. The rank is read when a job is taken, so a call that
    takes the floor is served next."""

    def __init__(self):
        self._jobs: list[tuple] = []  # (lane, seq, future, fn, args, kwargs)
        self._cv = threading.Condition()
        self._seq = 0
        self._thread: threading.Thread | None = None
        self._closed = False

    def lane(self, rank) -> "SpeechLane":
        """`rank` is a function returning a number; the lowest goes first."""
        return SpeechLane(self, rank)

    def _submit(self, lane: "SpeechLane", fn, args, kwargs) -> concurrent.futures.Future:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        with self._cv:
            if self._closed or lane.closed:
                raise RuntimeError("the speech queue is shut down")
            self._seq += 1
            self._jobs.append((lane, self._seq, fut, fn, args, kwargs))
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="speech", daemon=True)
                self._thread.start()
            self._cv.notify()
        return fut

    def _take(self):
        with self._cv:
            while not self._jobs and not self._closed:
                self._cv.wait()
            if not self._jobs:
                return None
            job = min(self._jobs, key=lambda j: (j[0].ranked(), j[1]))
            self._jobs.remove(job)
            return job

    def _work(self) -> None:
        while (job := self._take()) is not None:
            _, _, fut, fn, args, kwargs = job
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(*args, **kwargs))
            except BaseException as err:  # noqa: BLE001 - handed to whoever waits on the future
                fut.set_exception(err)

    def drop(self, lane: "SpeechLane") -> None:
        """Cancel the jobs of one lane that have not started."""
        with self._cv:
            for job in [j for j in self._jobs if j[0] is lane]:
                self._jobs.remove(job)
                job[2].cancel()

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        with self._cv:
            self._closed = True
            for job in self._jobs:
                job[2].cancel()
            self._jobs.clear()
            self._cv.notify_all()


class SpeechLane(concurrent.futures.Executor):
    """One call's way into the shared queue; usable with loop.run_in_executor like any executor."""

    def __init__(self, queue: SpeechQueue, rank):
        self.queue, self.rank, self.closed = queue, rank, False

    def ranked(self) -> int:
        try:
            return int(self.rank())
        except Exception:  # noqa: BLE001 - a broken rank must not stop the worker
            return 9

    def submit(self, fn, /, *args, **kwargs):
        return self.queue._submit(self, fn, args, kwargs)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.closed = True
        self.queue.drop(self)




# ---------------------------------------------------------------------------
# Speech normalisation and the board
# ---------------------------------------------------------------------------


DEMO_FILE = SKILL_DIR / "demo.md"


def load_demo(path: Path = None) -> list[str]:
    """The stage demo's answers: demo.md without its opening comment, split on lines holding only ---."""
    text = (path or DEMO_FILE).read_text()
    text = re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.DOTALL)
    return [a.strip() for a in re.split(r"(?m)^---\s*$", text) if a.strip()]


def demo_move(said: str, at: int, count: int) -> int:
    """Which demo answer a turn asks for: again, back, start over, or else the next one."""
    words = " ".join(spoken_words(said))
    if re.search(r"\b(start over|from the start|restart|from the beginning)\b", words):
        return 0
    if re.search(r"\b(again|repeat|replay|once more)\b", words):
        return max(at, 0)
    if re.search(r"\b(back|previous|go back)\b", words):
        return max(at - 1, 0)
    return min(at + 1, count - 1)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "session"


def view_slug(title: str, kind: str, taken: bool = False, salt: str = "") -> str:
    """A stage view name for a board title: its ASCII slug, made unique by a hash of the whole title
    (and `salt`) when the title has letters the slug drops (Greek), when the slug is empty, or when it
    is `taken`."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:56].strip("-")
    sha = hashlib.sha1((title + salt).encode()).hexdigest()[:6]
    if not slug:
        return f"{kind}-{sha}"
    if taken or any(ord(c) > 127 and c.isalpha() for c in title):
        return f"{slug}-{sha}"
    return slug


def stage_view(item: dict) -> tuple[str, dict, str]:
    """A board item as a stage view: (name, source, title). The name is the one its call gave it."""
    title = item.get("title") or item["kind"]
    name = item.get("view") or view_slug(item.get("title") or "", item["kind"])
    if item["kind"] == "code":
        source = {"type": "inline", "format": "code", "path": item["path"], "start": item["start"],
                  "lines": item["lines"], "highlight": item["highlight"], "lang": item["lang"]}
    elif item["kind"] == "change":
        source = {k: item[k] for k in CHANGE_FIELDS}
    elif item["kind"] in VISUAL_KINDS:
        source = item["visual"]
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


def spoken_words(text: str) -> list[str]:
    """The words of a sentence, lowercased, without punctuation: for comparing what was heard."""
    return re.findall(r"\w+", text.lower())


# Words people cut in with. Longer ones first, so "hold on" is matched before "hold".
CUE_WORDS = ("hold on", "wait a second", "wait", "sorry", "listen", "excuse me", "stop",
             "περίμενε", "συγγνώμη", "άκου", "σταμάτα")
# Replies that mean "go on": over an answer they never become a turn.
BACKCHANNELS = {"mm", "mhm", "mm hm", "mmhm", "hmm", "uh huh", "yeah", "yes", "yep", "ok", "okay", "right", "sure",
                "i see", "got it", "alright", "go on", "continue", "ναι", "εντάξει", "μάλιστα", "συνέχισε"}


def after_keyword(text: str, keywords=CUE_WORDS) -> str | None:
    """The text after a leading cue word ("Wait, why is that?" -> "why is that?"), "" for the cue word
    alone, None when the text does not start with one."""
    for keyword in ([keywords] if isinstance(keywords, str) else keywords):
        words = spoken_words(keyword)
        if not words:
            continue
        m = re.match(r"\W*" + r"\W+".join(map(re.escape, words)) + r"\b[\s,.:;!?…-]*", text, re.IGNORECASE)
        if m:
            return text[m.end():].strip()
    return None


def is_backchannel(text: str) -> bool:
    return " ".join(spoken_words(text)) in BACKCHANNELS


# Live mode's spoken commands: the whole utterance, and the page acts on it without a turn.
COMMANDS = {"go on": "resume", "continue": "resume", "carry on": "resume", "keep going": "resume", "resume": "resume",
            "pause": "pause", "stop": "pause", "be quiet": "pause",
            "repeat": "repeat", "repeat that": "repeat", "say that again": "repeat", "come again": "repeat",
            "go back": "back", "back": "back",
            "scratch that": "withdraw", "never mind": "withdraw", "nevermind": "withdraw", "forget it": "withdraw",
            "cancel": "withdraw", "cancel that": "withdraw",
            "stop listening": "mute",
            "συνέχισε": "resume", "σταμάτα": "pause", "ξαναπές το": "repeat", "πάλι": "repeat", "πίσω": "back",
            "άκυρο": "withdraw", "άσε": "withdraw", "σταμάτα να ακούς": "mute"}
COURTESY = {"please", "claude", "ok", "okay", "now", "παρακαλώ"}


def command_of(text: str) -> str | None:
    words = spoken_words(text)
    while words and words[0] in COURTESY:
        words = words[1:]
    while words and words[-1] in COURTESY:
        words = words[:-1]
    return COMMANDS.get(" ".join(words))


# A sentence that stops on one of these is a thought still going: live mode waits for the rest.
DANGLING = {"and", "but", "so", "or", "because", "um", "uh", "erm", "er", "the", "a", "an", "to", "of", "with", "if",
            "that", "then", "like", "which", "when", "is", "my", "your", "και", "αλλά", "γιατί", "ότι", "το", "η", "ο"}
LIVE_JOIN_S = 4.0  # how long a thought left hanging waits for its end before it goes as it is


def dangling(text: str) -> bool:
    words = spoken_words(text)
    return bool(words) and (words[-1] in DANGLING or text.rstrip().endswith(("...", "…", "-", "—")))


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



def align_words(text: str, start: int, end: int, heard: list, duration: float, offset: float) -> list[list]:
    """[first char, last char, start s, end s] for every shown word of text[start:end], timed from
    the words the engine said (Azure) or heard in its audio (Whisper). A word Whisper heard differently ("Lowercasing" as "Lower
    casing", "60" as "sixty") gets a time shared out by length between its timed neighbours; with
    nothing heard, the piece's whole duration is shared out that way."""
    tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", text[start:end])]
    key = lambda word: re.sub(r"[^\w]", "", word.lower())  # noqa: E731
    shown = [key(text[start + a:start + b]) for a, b in tokens]
    said = [key(word) for word, _, _ in heard]
    times: list = [None] * len(tokens)
    for block in difflib.SequenceMatcher(None, shown, said, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            times[block.a + k] = (heard[block.b + k][1], heard[block.b + k][2])
    i = 0
    while i < len(tokens):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(tokens) and times[j] is None:
            j += 1
        t0 = times[i - 1][1] if i else 0.0
        t1 = max(t0, times[j][0] if j < len(tokens) else duration)
        sizes = [tokens[k][1] - tokens[k][0] for k in range(i, j)]
        t = t0
        for k, size in zip(range(i, j), sizes):
            share = (t1 - t0) * size / (sum(sizes) or 1)
            times[k] = (t, t + share)
            t += share
        i = j
    return [[start + a, start + b, round(offset + t0, 3), round(offset + t1, 3)]
            for (a, b), (t0, t1) in zip(tokens, times)]


BOARD_KINDS = ("code", "change", "diagram", "table", "sequence", "flowchart")
VISUAL_KINDS = ("sequence", "flowchart")  # drawn by the shared tools from a JSON spec; any other body is Mermaid
LINE_KINDS = ("code", "change")  # one-line tags: their source is read from disk, so no body follows
KIND_ALIASES = {"mermaid": "diagram", "graph": "diagram", "flow": "diagram",
                "grid": "table", "diff": "change", "edit": "change"}
CHANGE_FIELDS = ("type", "format", "path", "rev", "hunks", "added", "removed", "more", "lang")
KEY_VIEW = "key-points"  # the one Key points view of a call
MAX_KEY_CHARS = 120
_HEAD = re.compile(r"(?:(?P<show>show)(?![a-z0-9])\s*[:\-_]?\s*)?(?P<kind>[a-z][a-z0-9_]*)?(?:(?:\s*:\s*|\s+)(?P<rest>.*))?\Z",
                   re.IGNORECASE | re.DOTALL)


def parse_head(marker: str) -> tuple[str | None, str, str, str]:
    """A tag's parts: (verb, kind, rest, title). verb is 'show', '/show' or None (not a board tag).

    Forgiving: `show table`, `show: table`, `show-table`, `show_table` and a bare `table` all read the same, case is
    ignored, and mermaid, graph and flow mean diagram, grid means table. A sequence or flowchart whose body is
    not a JSON spec is read as a Mermaid diagram when the block closes. After `show`, an
    unknown kind is kept as it was written, so the board can say what it did not know.
    """
    head, _, title = marker.partition("|")
    head, title = head.strip(), title.strip()
    if re.fullmatch(r"/\s*show", head, re.IGNORECASE):
        return "/show", "", "", title
    m = _HEAD.match(head)
    if not m:  # e.g. "show chart!": still a show, of a kind the board does not know
        if head.lower().startswith("show"):
            return "show", (re.sub(r"^show\W*", "", head.lower()).split() or [""])[0], "", title
        return None, "", "", title
    kind = (m["kind"] or "").lower()
    kind = KIND_ALIASES.get(kind, kind)
    rest = (m["rest"] or "").strip()
    if m["show"] or kind in BOARD_KINDS:
        return "show", kind, rest, title
    return None, kind, rest, title


def board_block_kind(marker: str) -> str | None:
    """The kind of a tag whose body follows up to [[/show]], else None. That is a diagram or table,
    and also a kind the board does not know, so its body is kept out of the speech."""
    verb, kind, _, _ = parse_head(marker)
    if verb != "show" or kind in LINE_KINDS:
        return None
    return kind or "?"


def block_head(kind: str, body: str) -> tuple[str, str]:
    """Split a block that was never closed: (the block-shaped head, the rest, given back to speech).
    A table is the run of lines starting with '|'; a JSON spec runs to the end of its object; a
    diagram runs to its closing ``` when it began with a fence, else to the first blank line."""
    if kind != "table" and body.lstrip().startswith("{"):
        lead = len(body) - len(body.lstrip())
        try:
            _, end = json.JSONDecoder().raw_decode(body, lead)
            return body[:end], body[end:]
        except ValueError:
            pass
    lines = body.splitlines(keepends=True)
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    first = lines[i].strip() if i < len(lines) else ""
    j = i
    if kind == "table" or (kind not in BOARD_KINDS and first.startswith("|")):
        while j < len(lines) and lines[j].strip().startswith("|"):
            j += 1
    elif first.startswith("```"):
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith("```"):
            j += 1
        if j < len(lines):
            j += 1
        else:  # no closing fence either: the first blank line ends it
            j = i + 1
            while j < len(lines) and lines[j].strip():
                j += 1
    else:
        while j < len(lines) and lines[j].strip():
            j += 1
    return "".join(lines[:j]), "".join(lines[j:])


MERMAID_TYPES = {
    "graph", "flowchart", "sequenceDiagram", "classDiagram", "classDiagram-v2", "stateDiagram", "stateDiagram-v2",
    "erDiagram", "gantt", "pie", "mindmap", "timeline", "journey", "gitGraph", "quadrantChart", "xychart",
    "xychart-beta", "block", "block-beta", "sankey", "sankey-beta", "requirementDiagram", "packet", "packet-beta",
    "architecture", "architecture-beta", "kanban", "radar", "radar-beta",
}


def diagram_problems(body: str, title: str) -> list[str]:
    """What Mermaid will choke on, said before the stage shows its error card."""
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]
    if lines and lines[0] == "---":  # front matter: title and config
        end = next((k for k in range(1, len(lines)) if lines[k] == "---"), None)
        lines = lines[end + 1 :] if end is not None else lines
    first = re.match(r"[A-Za-z0-9-]*", lines[0]).group() if lines else ""
    if first not in MERMAID_TYPES and not first.startswith("C4"):
        return [f'diagram "{title}" does not start with a Mermaid type such as graph TD']
    if first in ("graph", "flowchart"):
        for label in re.findall(r"\[(?!\")([^\[\]]*)\]", "\n".join(lines[1:] + [lines[0]])):
            inner = label[1:-1] if label.startswith("(") and label.endswith(")") else label
            if not inner.startswith('"') and re.search(r"[()]", inner):
                return [f'diagram "{title}": quote labels with brackets: A["f(x)"]']
    return []


# A table's separator row, as GFM reads it: `|---|`, `|:-|-:|` and `--|--` all count.
_TABLE_SEP = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_MERMAID_FENCE = re.compile(r"^[ \t]*```[ \t]*mermaid[ \t]*\n(?P<body>.*?)^[ \t]*```[ \t]*$\n?",
                            re.MULTILINE | re.DOTALL | re.IGNORECASE)


def untagged_boards(text: str) -> list[tuple[int, int, str, str, str]]:
    """Markdown tables and ```mermaid fences written without a tag: (start, end, kind, title, body),
    in order. Tables inside other code fences are left alone."""
    found, prev = [], 0
    for m in _MERMAID_FENCE.finditer(text):
        before = re.sub(r"(?m)^[ \t]*#+[ \t]*", "", text[prev : m.start()].replace(CUE, " "))
        before = before.strip().rstrip(":").strip()
        prev = m.end()
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", before) if s.strip()]
        title = sentences[-1].strip().rstrip(".!?:").strip()[:60] if sentences else ""
        found.append((m.start(), m.end(), "diagram", title or "Diagram", m["body"].strip()))
    fenced = [(a, b) for a, b, *_ in found]
    pos, run, in_fence = 0, [], False

    def bare(line: str) -> str:
        return line.replace(CUE, "").strip()

    def end_run():
        if len(run) >= 2 and any(_TABLE_SEP.match(bare(ln)) for _, ln in run[1:]):
            start, end = run[0][0], run[-1][0] + len(run[-1][1])
            cells = table_cells(bare(run[0][1]))
            title = " · ".join(c for c in cells if c)[:60] if not _TABLE_SEP.match(bare(run[0][1])) else ""
            found.append((start, end, "table", title or "Table",
                          "".join(ln for _, ln in run).replace(CUE, "").strip()))
        run.clear()

    for line in text.splitlines(keepends=True):
        s = bare(line)
        inside = any(a <= pos < b for a, b in fenced)
        if s.startswith("```") and not inside:
            in_fence = not in_fence
        if not inside and not in_fence and len(s) >= 2 and s.startswith("|") and s.count("|") >= 2:
            run.append((pos, line))
        else:
            end_run()
        pos += len(line)
    end_run()
    return sorted(found)


CUE = ""  # a private sentinel: where a board or point tag stood in the answer, until it is a cue
_KEY_HEAD = re.compile(r"key(?:[ \t]*points?|s)?[ \t]*:(?P<text>.*)\Z", re.IGNORECASE | re.DOTALL)


def parse_key(marker: str) -> str | None:
    """A [[key: ...]] tag's text (`key point:` and `keys:` read the same), or None when it is not one."""
    m = _KEY_HEAD.match(marker.strip())
    return " ".join(m["text"].split()) if m else None


def cut_words(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word boundary, with an ellipsis when cut."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if " " in head and not text[limit - 1].isspace():
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:.-") + "…"


_POINT_HEAD = re.compile(r"point(?![a-z0-9])\s*(?P<rest>.*)\Z", re.IGNORECASE | re.DOTALL)
_POINT_TARGET = re.compile(
    r"(?:(?:(?P<old>old)\s+)?(?P<line>lines?)\s+(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?"
    r"|rows?\s+(?:(?P<n>\d+)(?:\s*[-–]\s*(?P<n2>\d+))?|\"(?P<text>[^\"]+)\"|“(?P<curly>[^”]+)”|'(?P<single>[^']+)')"
    r"|cells?\s+(?P<cell>[^\[\]]+?/[^\[\]]+?)"
    r"|nodes?\s+(?P<node>[^\s:\[\]][^:\[\]]*?)|steps?\s+(?P<step>[^\s:\[\]][^:\[\]]*?))\s*\Z", re.IGNORECASE)
POINT_FORMS = 'expected line N, lines A-B, old line N, row N, rows A-B, row "text", cell "row" / "column", node ID or step ID'


def parse_point(marker: str) -> tuple[str, str] | None:
    """A [[point ...]] tag's (board title, target), or None when the tag is not a point.
    `point: lines 2-3` has no title; `point Request path: node B` names its board, and a title may
    hold a colon of its own, so the split is at the first colon whose remainder is a target."""
    m = _POINT_HEAD.match(marker.strip())
    if not m:
        return None
    rest = m["rest"].strip()
    if rest.startswith(":"):
        return "", rest[1:].strip()
    colons = [i for i, c in enumerate(rest) if c == ":"]
    for i in colons:
        if _POINT_TARGET.fullmatch(rest[i + 1 :].strip()):
            return rest[:i].strip(), rest[i + 1 :].strip()
    if colons:
        return rest[: colons[-1]].strip(), rest[colons[-1] + 1 :].strip()
    return "", rest


def fold(text: str) -> str:
    """For matching what was said against what is shown: no case, no accents (Greek tonos too)."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).casefold().strip()


def fold_like_stage(text: str) -> str:
    """fold() as stage.js folds a row's text: no accents, lower() rather than casefold(), so a row
    the server accepts is one the stage can find."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).lower().strip()


def table_cells(row: str) -> list[str]:
    """A markdown table row's cells, split at pipes that are not escaped, with `\\|` read as `|`."""
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", row)]


def table_first_cells(body: str) -> list[str]:
    """The first cell of every body row of the first markdown table, as the stage counts its rows:
    after the separator, every line up to the first blank one, with or without a leading pipe."""
    lines = [ln.strip() for ln in body.splitlines()]
    sep = next((i for i, ln in enumerate(lines) if _TABLE_SEP.match(ln)), None)
    if sep is None:
        return [table_cells(ln)[0] for ln in lines if ln.startswith("|")][1:]
    rows = []
    for ln in lines[sep + 1 :]:
        if not ln:
            break
        rows.append(ln)
    return [table_cells(ln)[0] for ln in rows]


def table_header(body: str) -> list[str]:
    """The header cells of the first markdown table: the line above its separator."""
    lines = [ln.strip() for ln in body.splitlines()]
    sep = next((i for i, ln in enumerate(lines) if _TABLE_SEP.match(ln)), None)
    return table_cells(lines[sep - 1]) if sep else []


def cell_text(cell: str) -> str:
    """A markdown table cell as the stage shows it: links become their text, and code and emphasis
    marks go, so a row named by what the reader sees matches what the server checked."""
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    t = t.replace("`", "")
    t = re.sub(r"(?<!\w)([*_]{1,3})(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", t)
    return t.strip()


def spec_tool(body: str) -> str | None:
    """Which shared tool a JSON body is written for, by its keys: nodes for a flowchart, actors or
    steps for a sequence. None when it is not a JSON object or names neither."""
    try:
        spec = json.loads(body)
    except ValueError:
        return None
    if not isinstance(spec, dict):
        return None
    if "nodes" in spec:
        return "flowchart"
    if "actors" in spec or "steps" in spec:
        return "sequence"
    return None


def scene_model(item: dict) -> stage_scene.SceneModel | None:
    kind = item["kind"]
    if kind == "code":
        return stage_scene.lines_model(range(item["start"], item["start"] + len(item["lines"])))
    if kind == "change":
        return stage_scene.change_model(item["hunks"])
    if kind == "table":
        return stage_scene.rows_model([cell_text(c) for c in table_first_cells(item["body"])],
                                      [cell_text(c) for c in table_header(item["body"])])
    if kind == "diagram":
        return stage_scene.flowchart_model(item["body"])
    if kind == "sequence":
        return stage_scene.sequence_model(item["visual"]["spec"])
    if kind == "flowchart":
        return stage_scene.flowchart_spec_model(item["visual"]["spec"])
    return None


def sentence_starts(text: str) -> list[int]:
    return [m.end() for m in re.finditer(r"(?:[.!?…][\"')\]]*\s+|\n\s*)(?=\S)", text)]


def _sub_tracked(pattern: str, repl: str, text: str, marks: list[int]) -> tuple[str, list[int]]:
    """re.sub that carries positions along: a position inside a replaced span moves to the end of
    its replacement, so a cue between two spaces lands on the word after them."""
    out, new_marks, spans, last, delta = [], list(marks), [], 0, 0
    for m in re.finditer(pattern, text):
        out.append(text[last : m.start()])
        out.append(repl)
        spans.append((m.start(), m.end(), m.start() + delta, len(repl)))
        delta += len(repl) - (m.end() - m.start())
        last = m.end()
    out.append(text[last:])
    for k, p in enumerate(marks):
        shift, inside = 0, None
        for a, b, new_a, n in spans:
            if p <= a:
                break
            if p < b:
                inside = new_a + n
                break
            shift += n - (b - a)
        new_marks[k] = inside if inside is not None else p + shift
    return "".join(out), new_marks


def place_cues(shown: str) -> tuple[str, list[int]]:
    """The answer as said, with the position of every CUE in it, after the whitespace is tidied the
    way a tag taken out of a sentence needs."""
    # A tag that opened a line leaves no indent behind it: the line starts with the word after it.
    shown = re.sub(rf"(^|\n)[ \t]*({CUE}+)[ \t]+", r"\1\2", shown)
    text, marks = "", []
    for c in shown:
        if c == CUE:
            marks.append(len(text))
        else:
            text += c
    text, marks = _sub_tracked(r"(?<=\S)[ \t]{2,}(?=\S)", " ", text, marks)  # where a tag was taken out
    text, marks = _sub_tracked(r"\n{3,}", "\n\n", text, marks)
    text, marks = _sub_tracked(r"[ \t]+\n", "\n", text, marks)
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    # A cue fires on the word after it: one left on the space or the line break before that word moves
    # onto it, so two cues meant for one word never stand at two places.
    marks = [min(max(0, p - lead), len(text)) for p in marks]
    return text, [p + len(text[p:]) - len(text[p:].lstrip()) for p in marks]


BLOCK_TAG = re.compile(r"\[\[([^\[\]]*)\]\]")


def block_tag(buf: str, m: re.Match) -> str | None:
    """What a [[...]] inside a diagram or table block is: 'close' ([[/show]], spaced as parse_head
    allows), 'open' (a new board tag of a known kind, not glued to a word as Mermaid's A[[Sub]] is),
    or None, body text."""
    verb, kind, _, _ = parse_head(m[1].strip())
    if verb == "/show":
        return "close"
    if verb == "show" and kind in BOARD_KINDS and not (m.start() and re.match(r"\w", buf[m.start() - 1])):
        return "open"
    return None


class MarkerFilter:
    """Pulls [[...]] markers out of streamed text, even when split across chunks.

    Inside a diagram or table block only [[/show]] is a marker: Mermaid's A[[Sub]] is body text.
    A new [[show ...]] there ends the block as never closed ("unclosed"), and is read as a marker.
    """

    def __init__(self):
        self._buf = ""
        self.in_block = False
        self.dropped = ""  # set by flush(): a tag that was never closed with ]]

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
        """What is left at the end. A tag never closed with ]] is dropped up to the end of its line,
        and named in `dropped`; the lines after it are still said."""
        rest, self.dropped = self._buf, ""
        if rest.startswith("[[") and not self.in_block:
            tag, nl, after = rest.partition("\n")
            rest, self.dropped = nl + after, tag
        self._buf, self.in_block = "", False
        return rest

    def _block_text(self, out: list[tuple[str, str]]) -> bool:
        """Body text up to [[/show]]; True once the block has closed."""
        for m in BLOCK_TAG.finditer(self._buf):
            what = block_tag(self._buf, m)
            if what == "open":
                # A new board tag before any [[/show]]: the open block was never closed. The new tag
                # stays in the buffer, to be read as a marker of its own.
                if m.start():
                    out.append(("text", self._buf[: m.start()]))
                out.append(("unclosed", ""))
                self._buf, self.in_block = self._buf[m.start() :], False
                return True
            if what == "close":
                if m.start():
                    out.append(("text", self._buf[: m.start()]))
                out.append(("marker", "/show"))
                self._buf, self.in_block = self._buf[m.end() :], False
                return True
        # Hold back a tail that may be a tag split across chunks.
        keep = 0
        start = self._buf.rfind("[[")
        if start >= 0 and "]]" not in self._buf[start:]:
            keep = len(self._buf) - start
        elif self._buf.endswith("["):
            keep = 1
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
        self.cues: list[dict] = []  # this reply's cues, in tag order; a show cue gets its view once accepted
        self.spill = ""

    def marker(self, text: str) -> bool:
        """Handle a board marker; False if the marker isn't a board marker. Every show tag records a
        cue where it stood, and so does a point tag that can be shown."""
        point = parse_point(text)
        if point is not None:
            self.point(*point)
            return True
        step = stage_scene.parse_verb(text)
        if step is not None:
            self.verb(step)
            return True
        verb, kind, rest, title = parse_head(text)
        if verb == "/show":
            self.spill += self.close_block()  # with no open block a stray [[/show]] is harmless
            return True
        if verb != "show":
            return False
        if kind in LINE_KINDS:
            self.spill += self.close_block()
            cue, n = self.new_cue(), len(self.items)
            (self.add_code if kind == "code" else self.add_change)(rest, title)
            if len(self.items) > n:
                cue["view"] = self.items[-1]["view"]
            return True
        self.spill += self.close_block()
        title = title or rest  # [[show table: Ports]] names the board like [[show table | Ports]]
        if not kind:
            self.problem("board kind missing after show, use code, change, diagram or table")
        elif kind not in BOARD_KINDS:
            self.problem(f'unknown board kind "{kind}", use code, change, diagram or table')
        self.open = {"kind": kind or "?", "title": title, "body": "", "cue": self.new_cue()}
        return True

    def new_cue(self) -> dict:
        """A cue to front a board; its view is set when the board is accepted, else it is dropped."""
        cue = {"kind": "front", "view": None}
        self.cues.append(cue)
        return cue

    def find(self, title: str, kind: str | None = None) -> dict | None:
        """The board a point means: the one titled so, or with no title the last board shown, earlier
        in this reply or else earlier in the call. Among boards of that title, one of `kind` (code
        counts a change too) wins, then one titled exactly so, then the latest."""
        if not title:
            return self.items[-1] if self.items else None
        want = fold(title)

        def bare(item):
            return re.sub(r" \(first \d+ lines\)$", "", item.get("title") or "")

        found = [item for item in self.items
                 if want in (fold(item.get("title") or ""), fold(bare(item)), item["view"])]
        if kind:
            found = [i for i in found if (i["kind"] if i["kind"] not in LINE_KINDS else "code") == kind] or found
        exact = [i for i in found if title.strip() in (i.get("title"), bare(i))]
        return (exact or found)[-1] if found else None

    def item_for(self, view: str) -> dict | None:
        return next((i for i in reversed(self.items) if i["view"] == view), None)

    def verb(self, step: stage_scene.Verb) -> None:
        if step.name in stage_scene.LATER:
            self.problem(f'"{step.name}" is not supported yet; dropped')
            return
        item = self.find(step.title)
        if item is None:
            self.problem(f'{step.name} not shown: no board titled "{step.title}" in this call' if step.title
                         else f"{step.name} not shown: no board has been shown yet")
            return
        self.cues.append({"kind": "frame", "view": item["view"], "verb": step})

    def point(self, title: str, raw: str) -> None:
        """[[point ...]]: a cue that lights up lines of code, a table row or a diagram node."""
        m = _POINT_TARGET.fullmatch(raw.strip())
        if not m:
            self.problem(f"point not shown: {POINT_FORMS}")
            return
        row_text = m["text"] or m["curly"] or m["single"]
        wanted = "code" if m["line"] else "table" if (m["n"] or row_text or m["cell"]) else "diagram"
        item = self.find(title, wanted)
        if item is None:
            self.problem(f'point not shown: no board titled "{title}" in this call' if title
                         else "point not shown: no board has been shown yet")
            return
        name, kind = item.get("title") or item["kind"], item["kind"]
        if kind in VISUAL_KINDS:
            self.point_visual(item, name, m)
            return
        use = {"code": "line N or lines A-B", "change": "line N or lines A-B (new line numbers), or old line N",
               "table": 'row N, rows A-B, row "text" or cell "row" / "column"', "diagram": "node ID"}[kind]
        if m["step"]:
            self.problem(f'point not shown: "{name}" is a {kind}; use {use}')
            return
        if (kind if kind not in LINE_KINDS else "code") != wanted or (m["old"] and kind != "change"):
            self.problem(f'point not shown: "{name}" is a {kind}; use {use}')
            return
        if kind == "change" and m["old"]:
            # A removed line, by its number before the change.
            a, b = sorted((int(m["a"]), int(m["b"] or m["a"])))
            gone = [r["old"] for h in item["hunks"] for r in h["lines"] if r["op"] == "-"]
            if not all(n in gone for n in range(a, b + 1)):
                said = f"old line {a} is" if a == b else f"old lines {a}-{b} are"
                self.problem(f'point not shown: {said} not removed in "{name}"'
                             + (f" (removed: {', '.join(map(str, gone))})" if gone else " (it removes no line)"))
                return
            target = {"type": "keys", "keys": [f"old:{n}" for n in range(a, b + 1)]}
        elif kind == "change":
            a = int(m["a"])
            b = int(m["b"]) if m["b"] else a
            a, b = min(a, b), max(a, b)
            spans = [(min(n), max(n)) for n in ([r["new"] for r in h["lines"] if r["new"] is not None]
                                                 for h in item["hunks"]) if n]
            if not any(lo <= a and b <= hi for lo, hi in spans):
                said = f"line {a} is" if a == b else f"lines {a}-{b} are"
                shown = ", ".join(f"{lo}-{hi}" for lo, hi in spans)
                self.problem(f'point not shown: {said} not in the new lines shown in "{name}" ({shown})')
                return
            # the lines as they are shown, with any line removed between them
            target = {"type": "keys", "keys": stage_scene.resolve(scene_model(item), f"{a}-{b}", name)[0]}
        elif kind == "code":
            a = int(m["a"])
            b = int(m["b"]) if m["b"] else a
            a, b = min(a, b), max(a, b)
            first, last = item["start"], item["start"] + len(item["lines"]) - 1
            if a < first or b > last:
                said = f"line {a} is" if a == b else f"lines {a}-{b} are"
                self.problem(f'point not shown: {said} outside lines {first}-{last} of "{name}"')
                return
            target = {"type": "lines", "a": a, "b": b}
        elif kind == "table" and m["cell"]:
            # One cell, read as the scene reads it: its row by number or first cell, its column by number or header.
            keys, _ = stage_scene.resolve(scene_model(item), "cell " + m["cell"], name)
            if not keys:
                self.problem(f'point not shown: no cell {m["cell"].strip()} in "{name}"')
                return
            target = {"type": "key", "key": keys[0]}
        elif kind == "table":
            cells = table_first_cells(item["body"])
            if m["n"]:
                a, b = sorted((int(m["n"]), int(m["n2"] or m["n"])))
                if not 1 <= a <= b <= len(cells):
                    said = f"row {a}" if a == b else f"rows {a}-{b}"
                    self.problem(f'point not shown: "{name}" has {len(cells)} rows, not {said}')
                    return
                target = {"type": "row", "n": a, "b": b}
            else:
                # Matched as the stage sees the row: by its first cell's text, not its markdown.
                said = cell_text(row_text)
                if fold_like_stage(said) not in [fold_like_stage(cell_text(c)) for c in cells]:
                    self.problem(f'point not shown: no row of "{name}" starts with "{row_text}"')
                    return
                target = {"type": "row", "text": said}
        else:
            # The stage lights what the scene keys, so a node is one the scene found: a subgraph too.
            node, model = m["node"].strip(), scene_model(item)
            if model is None:
                self.problem(f'point not shown: "{name}" is not a graph or flowchart, so the stage cannot light a node in it')
                return
            key = next((k for k in (f"node:{node}", f"group:{node}") if k in model.keys), None)
            if key is None:
                self.problem(f'point not shown: no node {node} in "{name}"')
                return
            target = {"type": "key", "key": key}
        self.cues.append({"kind": "frame", "view": item["view"],
                          "verb": stage_scene.Verb("focus", keys=self.target_keys(item, target))})

    def point_visual(self, item: dict, name: str, m: re.Match) -> None:
        """A point at a sequence's step or a flowchart's node: lit by its key."""
        want = ("step", m["step"]) if item["kind"] == "sequence" else ("node", m["node"])
        if not want[1]:
            use = "step ID" if item["kind"] == "sequence" else "node ID"
            self.problem(f'point not shown: "{name}" is a {item["kind"]}; use {use}')
            return
        key = f"{want[0]}:{want[1].strip()}"
        if want[0] == "node" and key not in scene_model(item).keys:
            key = f"group:{want[1].strip()}"  # a subgraph of a Mermaid graph drawn as a map
        if key not in scene_model(item).keys:
            self.problem(f'point not shown: no {want[0]} {want[1]} in "{name}"')
            return
        self.cues.append({"kind": "frame", "view": item["view"], "verb": stage_scene.Verb("focus", keys=[key])})

    @staticmethod
    def target_keys(item: dict, target: dict) -> list[str]:
        if target["type"] == "lines":
            return [f"line:{n}" for n in range(target["a"], target["b"] + 1)]
        if target["type"] == "keys":
            return target["keys"]
        if target["type"] == "row":
            if "n" in target:
                return [f"row#{n}" for n in range(target["n"], target.get("b", target["n"]) + 1)]
            cells = [fold_like_stage(cell_text(c)) for c in table_first_cells(item["body"])]
            return [f"row#{cells.index(fold_like_stage(target['text'])) + 1}"]
        return [target["key"]]

    def close_block(self, cut: bool = False) -> str:
        """Put an open diagram or table on the board, without a ``` fence the model may have wrapped it in.
        `cut`: the block was never closed with [[/show]], so only its block-shaped head is shown and
        the rest is returned, to be said after all. A block of an unknown kind is never shown."""
        if not self.open:
            return ""
        item, self.open = self.open, None
        kind, title = item["kind"], item["title"] or item["kind"]
        body, rest = item["body"], ""
        if cut:
            body, rest = block_head(kind, body)
            if kind in BOARD_KINDS:
                self.problem(f'missing [[/show]] after "{title}", closed it at the end of the {kind}')
        if kind not in BOARD_KINDS:
            return rest
        body = body.strip()
        fence = re.match(r"\A```[\w+-]*[ \t]*\n", body)
        if fence:
            end = re.search(r"^[ \t]*```[ \t]*$", body[fence.end():], re.MULTILINE)
            if end:
                rest = body[fence.end() + end.end():].strip() + ("\n" + rest if rest else "")
                body = body[fence.end(): fence.end() + end.start()]
            else:
                body = body[fence.end():]
        body = re.sub(r"\n?```\Z", "", body)
        if "```" in body:
            self.problem(f'{kind} "{title}" holds a ``` fence inside it; write the {kind} without fences')
        item["body"] = body.strip()
        if not item["body"]:
            self.problem(f'empty {kind} "{title}" not shown')
            return rest
        if kind in VISUAL_KINDS and not item["body"].startswith("{"):
            item["kind"] = kind = "diagram"
        elif kind == "diagram" and item["body"].startswith("{"):
            tool = spec_tool(item["body"])
            if tool:
                self.problem(f'"{title}" is a {tool} spec, so it was drawn as one; write [[show {tool} | ...]]')
                item["kind"] = kind = tool
        if kind == "diagram":
            # A call draws no Mermaid: a graph or a state diagram becomes a map, anything else is not shown.
            spec = stage_scene.mermaid_spec(item["body"])
            if spec is None:
                self.problem(f'"{title}" not shown: a call draws no Mermaid; use a sequence, a flowchart or a table')
                return rest
            kind = item["kind"] = "flowchart"
            item["body"] = json.dumps(spec)
        if kind in VISUAL_KINDS:
            try:
                item["visual"] = stage_model.visual_source(kind, item["body"])
            except stage_model.SourceError as e:
                other = spec_tool(item["body"])
                hint = f"; this looks like a {other} spec, write [[show {other} | ...]]" if other not in (None, kind) else ""
                self.problem(f'{kind} "{title}" not shown: {str(e).split(": ", 1)[-1]}{hint}')
                return rest
        if kind == "diagram":
            for problem in diagram_problems(item["body"], title):
                self.problem(problem)
        self.add(item)
        return rest

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
        if b > len(all_lines):
            b = len(all_lines)
            self.problem(f"code cut at line {b}, the end of {m['path'].strip()}")
        if b - a + 1 > self.MAX_LINES:
            b = a + self.MAX_LINES - 1
            title += f" (first {self.MAX_LINES} lines)"
            self.problem(f"code cut to lines {a}-{b} of {m['path'].strip()}: at most {self.MAX_LINES} lines")
        lines = all_lines[a - 1 : b]
        highlight = None
        if m["ha"]:
            ha, hb = int(m["ha"]), int(m["hb"] or m["ha"])
            ha, hb = min(ha, hb), max(ha, hb)
            if hb < a or ha > b:
                self.problem(f"highlight {ha}-{hb} is outside lines {a}-{b} shown of {m['path'].strip()}; not marked")
            else:
                highlight = [max(ha, a), min(hb, b)]
        self.add({"kind": "code", "title": title, "path": str(path.relative_to(self.code_dir)),
                  "start": a, "lines": lines, "highlight": highlight,
                  "lang": path.suffix.lstrip(".") or "text"})

    def add_change(self, spec: str, title: str) -> None:
        """[[show change: <path> [since <rev>] | title]]: what changed in a file, read from git."""
        if not self.code_dir:
            self.problem(f"change not shown, talk was started without --code: {spec}")
            return
        try:
            src = stage_model.change_source(self.code_dir, spec)
        except stage_model.SourceError as err:
            self.problem(f"change not shown, {err}")
            return
        title = title or f"What changed in {Path(src['path']).name}"
        self.add({"kind": "change", "title": title, **src})

    def add(self, item: dict) -> None:
        cue = item.pop("cue", None)
        ident = item.pop("ident", item.get("path", ""))
        item["id"] = len(self.items)
        item["view"] = self.log.view_name(item.get("title") or "", item["kind"], ident)
        # A board shown again just as it was keeps the scenes the answers before said it with; one that
        # changed starts over, since their frames name parts of the old drawing.
        before = self.item_for(item["view"])
        if before and before.get("scenes") and stage_view(before)[1] == stage_view(item)[1]:
            item["scenes"] = dict(before["scenes"])
        if cue is not None:
            cue["view"] = item["view"]
        self.items.append(item)
        self.log.board_item(item)
        if self.on_add:
            self.on_add(item)



# ---------------------------------------------------------------------------
# The call: what was said, what is on the stage, and the audio of every answer
# ---------------------------------------------------------------------------


class Call:
    """Everything one call holds. The page reads it through /api/state; the session through the turns."""

    def __init__(self, args, topic: str, out_dir: Path, fresh: bool = True):
        self.args = args
        self.topic = topic
        self.out_dir = out_dir
        self.audio_dir = out_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.live_held: dict | None = None   # a live thought left hanging, waiting for its end
        self.demo: list[str] | None = None    # a demo call: these answers play instead of a Claude session's
        self.demo_at = -1                     # the demo answer played last
        self.demo_starting = False
        self.said_lines: dict[int, dict] = {}  # entry id -> its line in the turn queue, to take it back
        self.filler: str | None = None        # "audio/filler.<ext>": "One moment." in this call's voice
        self.filler_making = False
        self.transcript = out_dir / "transcript.md"
        if fresh:
            self.transcript.write_text(f"# {topic}\n\n_talk · {dt.datetime.now():%Y-%m-%d %H:%M} · "
                                       f"{speech.name()} voice {args.voice or speech.default_voice()}_\n\n")
        self.entries: list[dict] = []
        self.version = 0
        self.turns = TurnQueue()
        self.turn_count = 0
        self.board = Board(args.code, self, on_add=self.show_on_stage)
        self.voice = args.voice or speech.default_voice()  # resolved to the engine's own name by open_call()
        self.activity: list[dict] = []
        self.owner_session = ""  # the session whose doorbell collects turns: only its tool calls are shown
        self.ended: str | None = None
        self.ended_at = 0.0
        self.closed = asyncio.Event()
        self.started = time.time()
        self.last_seen = 0.0  # the page's last poll
        self.last_turn = time.time()  # the last entry of any kind: the idle clock
        self.stage_cwd: str | None = None  # set by open_call(); None in tests means "no stage"
        self.stage_slug: str | None = None  # this call's own stage, set by open_call()
        self.stage_sid: str | None = None
        # board title -> stage view name, for this call; the Key points view's name is taken from the start
        self.view_names: dict[str, str] = {"\0keys": KEY_VIEW}
        self.keys: list[dict] = []  # every [[key: ...]] of the call, in order: {answer, text}
        self.answer_no = 0  # the number the reply being split will get
        self.reply_cues: list[dict] = []  # the cues of the reply just split: {at, view, kind, n?, index?}
        self.reply_shows = 0  # boards of the reply being split put on the stage so far: only the first fronts
        self.reply_items: list[dict] = []
        self.stage_pending: list = []
        # Speech calls and stage shows block: they run off the loop. Stage shows one at a time,
        # since each reads the stage's layout and writes it back.
        # VoiceStudio runs one speech job at a time; queueing here keeps a transcription behind one answer, not four.
        self.speech_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="speech")
        self.listen_pool = self.speech_pool  # a server swaps both for lanes of its shared queue
        self.id = ""  # the call id in the page's link, set by the server that holds the call
        self.token = ""  # the key the page and the session send with every request
        self.stage_url: str | None = None
        self.heard_upto = -1  # the last answer played on the page: later ones are new to the user
        self.stage_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage")
        self.reply_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="reply")
        self.saved_key = None

    # -- carried over to the next server ------------------------------------

    def snapshot(self) -> dict:
        """What a server on this port needs to carry the call on after this process has gone."""
        return {"format": talk_files.CALL_FORMAT, "call": self.id, "token": self.token, "pid": os.getpid(),
                "topic": self.topic, "out": str(self.out_dir),
                "args": {"code": str(self.args.code) if self.args.code else None, "voice": self.args.voice,
                         "language": self.args.language, "idle_minutes": self.args.idle_minutes},
                "voice": self.voice, "entries": list(self.entries), "version": self.version,
                "turn_count": self.turn_count, "turns": self.turns.snapshot(), "owner_session": self.owner_session,
                "started": self.started, "last_seen": self.last_seen, "last_turn": self.last_turn,
                "stage": {"cwd": self.stage_cwd, "slug": self.stage_slug, "sid": self.stage_sid, "url": self.stage_url},
                "view_names": [[list(k) if isinstance(k, tuple) else k, v] for k, v in list(self.view_names.items())],
                "keys": list(self.keys), "board": list(self.board.items), "heard_upto": self.heard_upto,
                "demo": self.demo_at if self.demo is not None else None}

    @classmethod
    def restore(cls, state: dict) -> "Call":
        """The call a snapshot describes, on this server, with its record and transcript as they were."""
        if state.get("format") != talk_files.CALL_FORMAT:
            raise ValueError(f"state format {state.get('format')!r}")
        given = state["args"]
        args = argparse.Namespace(code=Path(given["code"]) if given.get("code") else None, voice=given.get("voice"),
                                  language=given.get("language") or "auto",
                                  idle_minutes=int(given.get("idle_minutes") or 60))
        call = cls(args, state["topic"], Path(state["out"]), fresh=False)
        call.id, call.token = state["call"], state["token"]
        call.voice = state.get("voice") or call.voice
        call.entries = list(state["entries"])
        call.version = int(state.get("version") or 0) + 1
        call.turn_count = int(state.get("turn_count") or 0)
        call.turns.restore(state.get("turns") or {})
        call.owner_session = state.get("owner_session") or ""
        call.started = float(state.get("started") or call.started)
        call.last_seen = float(state.get("last_seen") or 0.0)
        if state.get("demo") is not None:
            call.demo, call.demo_at = load_demo(), int(state["demo"])
        call.last_turn = float(state.get("last_turn") or call.last_turn)
        stage = state.get("stage") or {}
        call.stage_cwd, call.stage_slug, call.stage_sid = stage.get("cwd"), stage.get("slug"), stage.get("sid")
        call.stage_url = stage.get("url")
        call.view_names = {tuple(k) if isinstance(k, list) else k: v for k, v in state.get("view_names") or []}
        call.view_names.setdefault("\0keys", KEY_VIEW)
        call.keys = list(state.get("keys") or [])
        call.board.items = list(state.get("board") or [])
        call.heard_upto = int(state.get("heard_upto", -1))
        return call

    def unspoken(self) -> list[dict]:
        """Answers whose audio a previous server was still making when it went."""
        return [e for e in self.entries if e["who"] == "claude" and e.get("speech") in ("pending", "making")]

    # -- the record ---------------------------------------------------------

    def add(self, who: str, text: str, **extra) -> dict:
        entry = {"id": len(self.entries), "who": who, "text": text, "at": time.time(), **extra}
        self.entries.append(entry)
        self.last_turn = entry["at"]
        self.changed()
        label = {"you": "You", "claude": "Claude", "status": "Claude, working", "note": "Note",
                 "board": "On the stage", "system": "Call"}[who]
        self.record(label, text)
        return entry

    def record(self, label: str, text: str) -> None:
        with self.transcript.open("a") as f:
            f.write(f"**{label}:** {text}\n\n")

    def changed(self) -> None:
        self.version += 1

    def board_item(self, item: dict) -> None:
        """Board's hook: every item it adds is listed in the conversation, with its view and answer."""
        item["answer"] = self.answer_no
        self.add("board", item.get("title") or item["kind"], view=item["view"], kind=item["kind"],
                 answer=item["answer"])

    def view_name(self, title: str, kind: str, ident: str = "") -> str:
        """The stage view for a board: the same title (compared as fold() compares it, the way a point
        finds its board), kind and `ident` (a code board's path) always get the same view in this call,
        and two boards that differ in any of them never share one. An untitled board always gets a view
        of its own."""
        key = (kind, fold(title), ident) if title.strip() else f"\0{kind}{len(self.view_names)}"
        if key not in self.view_names:
            if not title.strip():
                name = f"{kind}-{hashlib.sha1(key.encode()).hexdigest()[:6]}"
            else:
                name = view_slug(title, kind)
                n = 0
                while name in self.view_names.values():
                    name = view_slug(title, kind, taken=True, salt=f"\0{kind}\0{ident}\0{n or ''}")
                    n += 1
            self.view_names[key] = name
        return self.view_names[key]

    # -- turns --------------------------------------------------------------

    def offer(self, text: str, typed: bool, interrupted: dict | None = None, live: bool = False) -> dict:
        self.turn_count += 1
        entry = self.add("you", text, typed=typed, **({"interrupted": interrupted} if interrupted else {}))
        said = {"who": "you", "text": text}
        if interrupted:
            said["interrupted"] = interrupted
        if self.turns.working:  # said while Claude works on the last turn: an addition to it, not a new question
            said["while_working"] = True
        self.said_lines[entry["id"]] = said
        if self.demo is not None:  # no Claude session: what is said picks the demo's next answer
            asyncio.get_running_loop().create_task(self.demo_play(demo_move(text, self.demo_at, len(self.demo))))
            return entry
        self.turns.offer(f"t{self.turn_count}", [said])
        if live:
            self.want_filler()
        return entry

    async def demo_play(self, i: int) -> None:
        """Play demo answer i, as a Claude session's reply would come: boards, voice and all. A first line
        `page: <path> | <title>` puts that file behind the boards first, as a page opens in a call."""
        self.demo_at = i
        text = self.demo[i]
        first, _, rest = text.partition("\n")
        m = re.fullmatch(r"page:\s*(?P<path>[^|]+?)\s*(?:\|\s*(?P<title>.+))?", first.strip())
        if m and self.stage_cwd:
            path, title = m["path"], (m["title"] or m["path"]).strip()
            cwd, slug, owner = self.stage_cwd, self.stage_sid or self.stage_slug, self.stage_owner()
            code = Path(self.args.code or cwd)

            def show_page():
                source = stage_model.parse_source(path, code)
                stage_mod.show(cwd, slugify(title) or "page", source, title=title, slug=slug, owner=owner, background=True)
            try:
                await asyncio.get_running_loop().run_in_executor(self.stage_pool, show_page)
            except Exception as err:  # noqa: BLE001
                self.board.problem(f"the demo page {path} was not shown: {err}")
            text = rest
        await self.answer(text)

    def withdraw(self, entry_id) -> bool:
        """Take back what the user said, while no doorbell has collected it."""
        said = self.said_lines.get(entry_id)
        if said is None or not self.turns.withdraw(said):
            return False
        for entry in self.entries:
            if entry["id"] == entry_id:
                entry["withdrawn"] = True
        self.changed()
        return True

    def withdraw_last(self) -> bool:
        """"Never mind": a thought still hanging, else the last thing said if Claude does not have it yet."""
        if self.live_held:
            self.live_held["timer"].cancel()
            self.live_held = None
            return True
        last = next((e for e in reversed(self.entries) if e["who"] == "you" and not e.get("withdrawn")), None)
        return last is not None and self.withdraw(last["id"])

    def live_join(self, text: str, interrupted: dict | None) -> tuple[str, dict | None]:
        """What was said, after the thought it finishes, if one was left hanging."""
        held, self.live_held = self.live_held, None
        if not held:
            return text, interrupted
        held["timer"].cancel()
        return f"{held['text']} {text}".strip(), held["interrupted"] or interrupted

    def live_hold(self, text: str, interrupted: dict | None) -> None:
        timer = asyncio.get_running_loop().call_later(LIVE_JOIN_S, self.live_flush)
        self.live_held = {"text": text, "interrupted": interrupted, "timer": timer}

    def live_flush(self) -> None:
        """No end came for a hanging thought: it goes as it is."""
        held, self.live_held = self.live_held, None
        if held and not self.ended:
            self.offer(held["text"], typed=False, interrupted=held["interrupted"], live=True)

    def want_filler(self) -> None:
        """Make "One moment." once, in this call's voice, for the page to say while Claude works."""
        if self.filler or self.filler_making:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self.filler_making = True

        async def make() -> None:
            try:
                made = await loop.run_in_executor(self.speech_pool, speech.speak, "One moment.", self.voice)
                path = self.audio_dir / f"filler.{made.ext}"
                path.write_bytes(made.audio)
                self.filler = f"audio/{path.name}"
                self.changed()
            except Exception as err:  # noqa: BLE001
                say(f"speech: the filler was not made: {type(err).__name__}: {err}")
            finally:
                self.filler_making = False

        loop.create_task(make())

    def interruption(self, entry_id, at) -> dict | None:
        """What the user had heard of an answer when they cut in: its number and its last words before
        `at`, a character offset into its text. None when the page named no answer this call holds."""
        try:
            entry_id, at = int(entry_id), int(at)
        except (TypeError, ValueError):
            return None
        n = 0
        for entry in self.entries:
            if entry["who"] == "claude":
                n += 1
                if entry["id"] == entry_id:
                    heard = entry["text"][:max(0, at)].rstrip()
                    tail = heard[-160:]
                    return {"answer": n, "heard": ("…" if len(tail) < len(heard) else "") + tail,
                            "rest_unheard": at < len(entry["text"].rstrip())}
        return None

    def echo_of(self, text: str, entry_id, at) -> bool:
        """Mostly the answer's own words from around where it was playing: the microphone heard the
        speaker, not the user."""
        entry = next((e for e in self.entries if e["who"] == "claude" and str(e["id"]) == str(entry_id)), None)
        if entry is None:
            return False
        try:
            at = int(at)
        except (TypeError, ValueError):
            return False
        # Echo repeats a run of the answer's words in order; a question that borrows a few of them does not.
        near, said = spoken_words(entry["text"][max(0, at - 400):at + 400]), spoken_words(text)
        run = 0
        for i in range(len(said)):
            for j in range(len(near)):
                k = 0
                while i + k < len(said) and j + k < len(near) and said[i + k] == near[j + k]:
                    k += 1
                run = max(run, k)
        return run >= 4 and run >= 0.6 * len(said)

    def collected(self) -> None:
        self.activity = []
        self.changed()

    def record_activity(self, body: dict) -> bool:
        """One tool call from the answering session. The hook runs in every session on this machine:
        the doorbell's own call names the session that answers, and every other session is ignored."""
        session = str(body.get("session_id", ""))
        if body.get("doorbell"):
            self.owner_session = session or self.owner_session
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

    def busy(self, within: float) -> bool:
        """A turn is being worked on, and the session made a tool call within the last `within` seconds."""
        return self.turns.working and time.monotonic() - self.turns.last_activity < within

    def activity_view(self) -> list[dict]:
        now = time.monotonic()
        return [{"label": a["label"], "state": a["state"],
                 "seconds": a["seconds"] if a["seconds"] is not None else round(now - a["started"], 1)}
                for a in self.activity[-8:]]

    # -- answers ------------------------------------------------------------

    def split_reply(self, text: str) -> str:
        """Take the markers out of a reply: board tags go to the stage, notes to the record.
        Returns what is left, the text that is shown and read aloud. Where each board or point tag
        stood becomes a cue in `reply_cues`, so the stage can follow the voice."""
        self.answer_no = sum(1 for e in self.entries if e["who"] == "claude") + 1
        self.board.cues, self.reply_shows, self.reply_items = [], 0, []
        keys_before = len(self.keys)
        shown = ""

        def take(text: str) -> None:
            # The rest of a block never closed with [[/show]] is taken again, so its own tags still work.
            nonlocal shown
            markers = MarkerFilter()
            for kind, chunk in markers.feed_ordered(text) + [("text", markers.flush())]:
                if kind == "unclosed":
                    take(self.board.close_block(cut=True))
                elif kind == "marker":
                    if chunk.lower().startswith("note:"):
                        self.add("note", chunk[5:].strip())
                        continue
                    key = parse_key(chunk)
                    if key is not None:
                        shown += self.add_key(key)
                        continue
                    before = len(self.board.cues)
                    if not self.board.marker(chunk):
                        shown += f"[[{chunk}]]"
                    shown += CUE * (len(self.board.cues) - before)
                    spill, self.board.spill = self.board.spill, ""
                    if spill:
                        take(" " + spill)
                elif not self.board.text(chunk):
                    shown += chunk
            rest = self.board.close_block(cut=True)
            if rest:
                take(rest)
            if markers.dropped:
                self.board.problem(f"a tag was not closed with ]]: {markers.dropped[:40]}")

        take(text)
        # Tables and Mermaid written without a tag still go on the stage, never into the speech.
        found = untagged_boards(shown)
        placed = list(zip([i for i, c in enumerate(shown) if c == CUE], self.board.cues))
        for start, end, kind, title, body in found:
            self.board.problem(f"{kind} shown without a tag; wrap it in [[show {kind} | title]] next time")
            if kind == "diagram":
                for problem in diagram_problems(body, title):
                    self.board.problem(problem)
            cue = self.board.new_cue()
            placed.append((start, cue))
            self.board.add({"kind": kind, "title": title, "body": body, "cue": cue,
                            "ident": f"untagged-{len(self.board.items)}"})
        for start, end, *_ in reversed(found):
            shown = shown[:start] + CUE + "\n" + CUE * shown[start:end].count(CUE) + shown[end:]
        placed.sort(key=lambda pc: pc[0])  # stable: the i-th CUE in `shown` is the i-th cue here
        shown, marks = place_cues(shown)
        timed = self.compile_scenes(shown, [(at, cue) for (_, cue), at in zip(placed, marks) if cue["view"]])
        self.reply_cues = [{"at": at, **{k: v for k, v in cue.items() if v is not None}} for at, cue in timed]
        boards = [c for c in self.reply_cues if c["kind"] == "front"]  # a key belongs after its sentence
        if len(boards) >= 2 and all(c["at"] == len(shown) for c in boards):
            self.board.problem("all boards were placed after the last sentence, so the stage cannot follow "
                               "the voice; put each tag before the sentence about it")
        if len(self.keys) > keys_before:
            self.show_keys(len(self.keys) - keys_before)
        items, self.reply_items = self.reply_items, []
        for item in items:
            self.put_on_stage(item)
        return shown

    def split_reply_safely(self, text: str) -> str:
        """split_reply, but a board that breaks never costs the answer: the turn is already taken, so
        the words are said without the boards and a board: line says why."""
        try:
            return self.split_reply(text)
        except Exception as e:
            traceback.print_exc()
            self.board.open, self.board.spill, self.board.cues = None, "", []
            self.reply_cues, self.reply_items = [], []
            self.board.problem(f"the boards of this answer failed ({type(e).__name__}: {e}), so it is said without them")
            text = re.sub(r"\[\[\s*show\b(?:(?!\[\[\s*/\s*show\s*\]\]).)*\[\[\s*/\s*show\s*\]\]", "", text,
                          flags=re.IGNORECASE | re.DOTALL)
            return re.sub(r"\[\[[^\[\]]*\]\]", "", text).strip()

    def compile_scenes(self, shown: str, timed: list) -> list:
        runs: dict[str, list] = {}
        for at, cue in timed:
            if cue["kind"] == "frame":
                view_runs = runs.setdefault(cue["view"], [])
                if view_runs and view_runs[-1][0] == at:
                    view_runs[-1][1].append(cue)
                else:
                    view_runs.append([at, [cue]])
        fronts = [(at, cue["view"]) for at, cue in timed if cue["kind"] == "front"]
        starts = sentence_starts(shown)
        auto: set[str] = set()  # the boards that came in with the sentences said about them
        for i, (at, view) in enumerate(fronts):
            item = self.board.item_for(view)
            own = runs.get(view, [])
            reveals = any(c["verb"].name in ("+", "next", "all") for _, cues in own for c in cues)
            # A sequence or flowchart comes in with the sentences that name its parts unless its verbs reveal
            # it themselves: a point brings in what it lights, and the sentences bring in the rest.
            stepped = item is not None and (view not in runs or (item["kind"] in VISUAL_KINDS and not reveals))
            model = scene_model(item) if stepped else None
            if model is None or at >= len(shown):
                continue
            end = fronts[i + 1][0] if i + 1 < len(fronts) else len(shown)
            bounds = [at] + [s for s in starts if at < s < end]
            sentences = [shown[a:b] for a, b in zip(bounds, bounds[1:] + [end])]
            title = item.get("title") or item["kind"]
            # The board's own points, by the sentence they stand in: each is the reveal for its sentence.
            pointed: dict[int, list[str]] = {}
            first_run: dict[int, tuple] = {}
            for pos, cues in own:
                if at <= pos < end:
                    n = bisect.bisect_right(bounds, pos) - 1
                    first_run.setdefault(n, (pos, cues))
                    for c in cues:
                        v = c["verb"]
                        keys = v.keys if v.keys is not None else [
                            k for t in v.targets if t.lower() != "none" for k in stage_scene.resolve(model, t, title)[0]]
                        pointed.setdefault(n, []).extend(keys)
            plan, by_order = stage_scene.auto_steps(model, sentences, pointed)
            if not plan:
                continue
            auto.add(view)
            if item["kind"] not in VISUAL_KINDS:
                self.board.problem(f'"{title}" has {len(model.order)} elements and no verbs, '
                                   "so it came in with the sentences said about it (dump); tag the word that names each thing")
            elif by_order:
                self.board.problem(f'{len(by_order)} of {len(model.order)} parts of "{title}" are named by no sentence, '
                                   "so they came in by order; point at each where it is said")
            for n, reveals in plan.items():
                auto = [{"kind": "frame", "view": view, "verb": stage_scene.Verb("+", keys=keys)} for keys in reveals]
                pos, cues = first_run.get(n, (bounds[n], None))
                if cues is not None:  # with the point, before it: the point is what is said
                    cues[:0] = auto
                else:
                    own.append([pos, auto])
                timed.extend((pos, cue) for cue in auto)
            runs[view] = sorted(own, key=lambda run: run[0])
        for view, view_runs in runs.items():
            item = self.board.item_for(view)
            title = item.get("title") or item["kind"]
            model = scene_model(item)
            if model is None:
                built, notes = None, [f'verbs step flowcharts, code, changes and tables for now; "{title}" is shown whole']
            else:
                built, notes = stage_scene.compile_scene(model, [[c["verb"] for c in cues] for _, cues in view_runs], title)
            for note in notes:
                self.board.problem(note)
            for n, (_, cues) in enumerate(view_runs, 1):
                for k, cue in enumerate(cues):
                    cue.pop("verb")
                    cue["n"] = n if built and k == 0 else None
            if built:
                # Each answer keeps its own scene on the board, under its number: its cues count frames in
                # that scene, so a replay of an earlier answer steps the scene it was said with.
                item["scene"] = {**built, "auto": True} if view in auto else built
                item.setdefault("scenes", {})[str(self.answer_no)] = item["scene"]
                if not any(i is item for i in self.reply_items):
                    self.reply_items.append(item)
        timed = [(at, cue) for at, cue in timed if cue["kind"] != "frame" or cue.get("n")]
        timed.sort(key=lambda t: t[0])
        return timed

    def add_key(self, text: str) -> str:
        """[[key: ...]]: a takeaway kept for the whole call, on the Key points board. Silent: it returns
        only the CUE where it stood, which lights it up on the board when the voice gets there."""
        if not text:
            self.board.problem("key point empty, not kept")
            return ""
        if len(text) > MAX_KEY_CHARS:
            self.board.problem("key point too long, keep it under 12 words")
            text = cut_words(text, MAX_KEY_CHARS)
        self.keys.append({"answer": self.answer_no, "text": text})
        self.record("Key point", text)
        self.board.cues.append({"kind": "key", "view": KEY_VIEW, "index": len(self.keys)})
        return CUE

    def show_keys(self, added: int) -> None:
        """After a reply that added key points: one chip for the reply, and the Key points board, updated
        in the background so the board in front stays on the explanation."""
        self.add("board", f"Key points: +{added}", view=KEY_VIEW, kind="points", answer=self.answer_no,
                 added=added)
        if not self.stage_cwd:
            return
        source = {"type": "inline", "format": "points",
                  "items": [{"n": i + 1, "text": k["text"], "answer": k["answer"]} for i, k in enumerate(self.keys)]}
        cwd, slug, owner = self.stage_cwd, self.stage_sid or self.stage_slug, self.stage_owner()

        def show():
            stage_mod.show(cwd, KEY_VIEW, source, title="Key points", slug=slug, background=True,
                           extra={"kind": "points", "pinned": True}, owner=owner)

        self.stage_pending.append(self.stage_pool.submit(show))

    async def answer(self, text: str) -> dict:
        """Show an answer at once, then read it aloud in the background."""
        # Off the loop: a change tag reads git, and the page's polls and audio must not wait for it.
        # One reply at a time, since splitting writes the board's and the call's state.
        shown = await asyncio.get_running_loop().run_in_executor(self.reply_pool, self.split_reply_safely, text)
        if not shown:
            return {}
        # Every key the speech thread sets exists already, so a page poll never sees the entry change size.
        entry = self.add("claude", shown, audio=None, speech="pending", cues=self.reply_cues, words=[],
                         speech_started=None, speech_estimate=None)
        asyncio.get_running_loop().create_task(self.speak(entry))
        return entry

    async def speak(self, entry: dict) -> None:
        """Read the whole answer in one request, so it plays without a pause or a click between
        sentences. While it is made, the page shows a progress bar from `speech_started` and
        `speech_estimate`. Every shown word is timed, for the page to highlight as it is said."""
        loop = asyncio.get_running_loop()
        text = entry["text"]
        spoken = speakable(text)

        def make():
            # Runs when the queue gets to it: the bar starts now, not while the job waits its turn.
            started = time.time()
            entry.update(speech="making", speech_started=started, speech_estimate=speech.estimate(spoken))
            loop.call_soon_threadsafe(self.changed)
            made = speech.speak(spoken, self.voice)
            speech.learn(spoken, time.time() - started)
            return made

        try:
            made = await loop.run_in_executor(self.speech_pool, make)
            path = self.audio_dir / f"{entry['id']:04d}.{made.ext}"
            path.write_bytes(made.audio)
            entry.update(audio=f"audio/{path.name}", speech="ready",
                         words=align_words(text, 0, len(text), made.words, made.duration, 0.0))
        except Exception as err:  # noqa: BLE001
            entry.update(speech="failed", speech_error=str(err) or type(err).__name__)
            say(f"speech: {type(err).__name__}: {err}")
        self.changed()

    # -- the stage ----------------------------------------------------------

    def show_on_stage(self, item: dict) -> None:
        """Board's hook: a board item goes on the stage once its reply is split, with its frames."""
        self.reply_items.append(item)

    def put_on_stage(self, item: dict) -> None:
        """Put a board item on the stage, on the stage thread. A failure is a board problem."""
        if not self.stage_cwd:
            return
        name, source, title = stage_view(item)
        cwd, slug, owner = self.stage_cwd, self.stage_sid or self.stage_slug, self.stage_owner()
        extra = {"answer": item.get("answer", self.answer_no), "kind": item["kind"]}
        if item.get("scene"):
            extra["scene"] = item["scene"]
        if item.get("scenes"):
            extra["scenes"] = item["scenes"]
        # Only a reply's first board comes to the front now; its cues front the others as the voice
        # reaches them.
        more = {"background": True} if self.reply_shows else {}
        self.reply_shows += 1

        def show():
            stage_mod.show(cwd, name, source, title=title, slug=slug, extra=extra, owner=owner, **more)

        fut = self.stage_pool.submit(show)
        self.stage_pending.append(fut)

    def stage_owner(self) -> str:
        return f"talk call {self.id or '?'}"

    async def stage_settled(self, timeout: float | None = None) -> None:
        """Wait a little for this reply's stage shows; a show still running is carried to the next
        reply, so its failure is reported there rather than lost."""
        timeout = STAGE_SETTLE_S if timeout is None else timeout
        pending, self.stage_pending = self.stage_pending, []
        if not pending:
            return
        done, not_done = await asyncio.get_running_loop().run_in_executor(
            None, lambda: concurrent.futures.wait(pending, timeout=timeout))
        for fut in pending:
            if fut in done and not fut.cancelled() and fut.exception():
                self.board.problem(f"not shown on the stage: {fut.exception()}")
        if not_done:
            self.stage_pending = [f for f in pending if f in not_done] + self.stage_pending
            self.board.problem(f"{len(not_done)} board(s) still going onto the stage after {timeout:g} s; "
                               "a failure shows with the next reply")

    # -- the end ------------------------------------------------------------

    def end(self, reason: str) -> None:
        if self.ended:
            return
        self.ended, self.ended_at = reason, time.time()
        self.add("system", f"The call ended: {reason}.")
        self.turns.finish(reason, str(self.transcript))
        if self.id:
            talk_files.mark_ended(talk_files.call_file(self.id), os.getpid())
        say(f"talk: call ended ({reason}). Transcript {self.transcript}")

    def view(self) -> dict:
        return {"v": self.version, "entries": self.entries, "working": self.turns.working,
                "stalled": self.turns.stalled, "activity": self.activity_view() if self.turns.working else [],
                "ended": self.ended, "heard_upto": self.heard_upto, "filler": self.filler}


# ---------------------------------------------------------------------------
# HTTP: the page, the session's doorbell and replies, the activity hook
# ---------------------------------------------------------------------------


def stage_preconnect(stage_url: str | None) -> str:
    """A preconnect hint to the stage's origin, so the embedded stage starts its handshake with the page."""
    if not stage_url:
        return ""
    parts = urllib.parse.urlsplit(stage_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f'\n<link rel="preconnect" href="{html_escape(parts.scheme + "://" + parts.netloc)}">'


class Server:
    """Every open call on this machine, and what they share: one VoiceStudio queue, and the floor.

    The floor is the call the user is talking in. Pressing Talk, sending text or playing an answer
    takes it. Every other call's page then pauses its voice, and only the call holding the floor
    plays new answers on its own. The other calls keep working and keep their answers, which show
    as new on the switcher until they are played."""

    def __init__(self, token: str, port: int = 0, home_key: str | None = None):
        self.token, self.port = token, port
        self.home_key = home_key or secrets.token_urlsafe(24)  # the cookie that opens the list of calls
        self.calls: dict[str, Call] = {}
        self.gone_tokens: set[str] = set()  # calls closed since: their session hears that they ended
        self.floor: str | None = None
        self.floor_n = 0  # counts every change of floor, so a page can tell an old answer from a new one
        self.speech = SpeechQueue()
        self.code = code_version()
        self.service = False  # launchd runs it: it stays with no call, and a launch restarts it through launchd
        self.warm: set[str] = set()  # voices loaded since this server started
        self.empty_since = time.time()
        self.registering = 0
        self.tasks: list[asyncio.Task] = []
        self.stop = asyncio.Event()
        self.handing_over = False
        self.inflight = 0

    def open_count(self) -> int:
        return self.registering + sum(1 for c in self.calls.values() if not c.ended)

    def add(self, call: Call, call_id: str | None = None, token: str | None = None,
            stage_url: str | None = None) -> Call:
        call.id = call_id or call.id or new_call_id()
        call.token = token or call.token or secrets.token_urlsafe(24)
        call.stage_url = stage_url if stage_url is not None else call.stage_url
        own = call.speech_pool
        call.speech_pool = self.speech.lane(lambda: 1 if self.floor == call.id else 2)
        call.listen_pool = self.speech.lane(lambda: 0)
        own.shutdown(wait=False)
        self.calls[call.id] = call
        return call

    def by_token(self, token: str) -> Call | None:
        if not token:
            return None
        return next((c for c in self.calls.values() if secrets.compare_digest(token, c.token)), None)

    def is_server(self, token: str) -> bool:
        return bool(token) and secrets.compare_digest(token, self.token)

    def take_floor(self, call: Call, heard=None) -> int:
        """`call` is where the user talks now. `heard` is the answer whose playing took the floor."""
        if self.floor != call.id:
            self.floor, self.floor_n = call.id, self.floor_n + 1
        if isinstance(heard, int) and not isinstance(heard, bool) and heard > call.heard_upto:
            call.heard_upto = heard
        return self.floor_n

    def summary(self, call: Call) -> dict:
        return {"id": call.id, "topic": call.topic, "ended": bool(call.ended),
                "working": call.turns.working and not call.ended,
                "unheard": sum(1 for e in call.entries if e["who"] == "claude" and e["id"] > call.heard_upto),
                "floor": self.floor == call.id, "started": call.started}

    def summaries(self) -> list[dict]:
        return sorted((self.summary(c) for c in self.calls.values()), key=lambda s: s["started"])

    def stamp(self, call: Call) -> tuple[str, list[dict]]:
        """The page's version of its state, which also moves when the floor or another call changes."""
        others = [s for s in self.summaries() if s["id"] != call.id]
        sig = hashlib.sha1(json.dumps([others, self.floor, self.floor_n]).encode()).hexdigest()[:8]
        return f"{call.version}.{sig}", others

    def view(self, call: Call) -> dict:
        v, others = self.stamp(call)
        return {**call.view(), "v": v, "floor_call": self.floor, "floor_n": self.floor_n, "calls": others,
                "now": time.time()}

    def write_call_file(self, call: Call) -> None:
        talk_files.write_private(talk_files.call_file(call.id), {
            "port": self.port, "token": call.token, "call": call.id, "path": f"/c/{call.id}", "pid": os.getpid(),
            "out": str(call.out_dir), "stage_sid": call.stage_sid, "format": talk_files.CALL_FORMAT})

    def save_state(self, call: Call, force: bool = False) -> None:
        """Write the call's state file when anything in it has changed since it was last written."""
        key = (call.version, call.turns.state_key(), call.owner_session, call.heard_upto, bool(call.last_seen),
               self.floor == call.id, self.floor_n)
        if call.ended or (key == call.saved_key and not force):
            return
        try:
            talk_files.write_private(talk_files.state_file(call.id),
                                     {**call.snapshot(), "floor": self.floor == call.id, "floor_n": self.floor_n})
        except (RuntimeError, OSError, TypeError, ValueError) as err:
            say(f"talk: call {call.id}: its state was not saved: {err}")
            return
        call.saved_key = key

    def save_calls(self) -> None:
        for call in list(self.calls.values()):
            self.save_state(call)

    def adopt(self, call: Call, state: dict) -> Call:
        """Carry on a call a previous server on this port left open: same id, token, record and stage."""
        self.add(call, call.id, call.token, call.stage_url)
        if state.get("floor"):
            self.floor = call.id
        self.floor_n = max(self.floor_n, int(state.get("floor_n") or 0))
        self.write_call_file(call)
        self.save_state(call, force=True)
        self.keep(call)
        loop = asyncio.get_running_loop()
        for entry in call.unspoken():
            entry.update(speech="pending", speech_started=None, speech_estimate=None)
            loop.create_task(call.speak(entry))
        say(f"talk: call {call.id} carried over: {call.topic}")
        return call

    async def hand_over(self) -> None:
        """Stop taking requests, let the ones running finish, and leave every open call's state for the
        next server on this port. Nothing is ended: the call goes on when that server starts."""
        self.handing_over = True
        for call in self.calls.values():
            if not call.ended:
                call.turns.suspend()
        deadline = time.time() + HANDOVER_S
        while self.inflight and time.time() < deadline:
            await asyncio.sleep(0.05)
        for call in list(self.calls.values()):
            self.save_state(call, force=True)

    def write_files(self) -> None:
        """This server's file and its calls' files, written again whenever one is missing or names
        another process: the session and the launch find the server only through them."""
        mine = os.getpid()
        if (talk_files.read(talk_files.server_file(self.port)) or {}).get("pid") != mine:
            talk_files.write_private(talk_files.server_file(self.port), {
                "port": self.port, "token": self.token, "pid": mine, "code": self.code,
                "activity_script": str(SKILL_DIR / "talk_activity.py")})
        for call in list(self.calls.values()):
            if not call.ended and (talk_files.read(talk_files.call_file(call.id)) or {}).get("pid") != mine:
                self.write_call_file(call)

    def keep(self, call: Call) -> None:
        """Watch a call until it closes, then let it go. A call still open when the server stops is
        left for the next one."""
        async def run():
            await watch(call)
            if call.ended:
                await self.close(call)
        self.tasks.append(asyncio.get_running_loop().create_task(run()))

    async def close(self, call: Call) -> None:
        if self.calls.get(call.id) is not call:
            return
        # A doorbell already waiting gets the end at once; a few seconds more cover one re-arming now.
        try:
            await asyncio.wait_for(call.turns.end_collected.wait(), 5)
        except asyncio.TimeoutError:
            pass
        self.calls.pop(call.id, None)
        self.gone_tokens.add(call.token)
        if self.floor == call.id:
            self.floor = None
        talk_files.remove_if_pid(talk_files.call_file(call.id), os.getpid())
        talk_files.remove_if_pid(talk_files.state_file(call.id), os.getpid())
        for pool in (call.speech_pool, call.listen_pool, call.stage_pool, call.reply_pool):
            pool.shutdown(wait=False, cancel_futures=True)
        if not self.calls:
            self.empty_since = time.time()
        if call.stage_sid:
            try:
                await asyncio.get_running_loop().run_in_executor(None, stage_mod.wc.finish_session, call.stage_sid)
            except stage_mod.DAEMON_ERRORS as err:
                say(f"talk: call {call.id}: its stage {call.stage_slug} was not ended: {err}")
        say(f"talk: call {call.id} closed; {len(self.calls)} open")


def build_app(server: Server):
    from aiohttp import web

    def token_of(request) -> str:
        return request.headers.get("X-Talk-Token", "")

    def call_of(request) -> Call | None:
        return server.by_token(token_of(request))

    def forbidden():
        return web.json_response({"error": "forbidden"}, status=403)

    def refused(request):
        """A request no open call takes: 410 for a call that has closed since, else 403."""
        if token_of(request) in server.gone_tokens:
            return web.json_response({"error": "the call has ended"}, status=410)
        return forbidden()

    def by_link(request) -> Call | None:
        return server.calls.get(request.match_info.get("call", ""))

    def may_list(request) -> bool:
        """The list of calls is for whoever has opened one of them: that page set the cookie."""
        return (secrets.compare_digest(request.cookies.get(HOME_COOKIE, ""), server.home_key)
                or call_of(request) is not None or server.is_server(token_of(request)))

    @web.middleware
    async def handover_gate(request, handler):
        if server.handing_over:
            return web.json_response({"error": "the talk server is restarting; try again in a moment"}, status=503)
        server.inflight += 1
        try:
            return await handler(request)
        finally:
            server.inflight -= 1

    async def gone(request):
        return web.Response(text=GONE_PAGE, status=404, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def home(request):
        if not may_list(request):
            return web.Response(text=HOME_LOCKED, status=404, content_type="text/html",
                                headers={"Cache-Control": "no-store"})
        return web.Response(text=HOME_PAGE, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def calls_list(request):
        if not may_list(request):
            return forbidden()
        return web.json_response({"calls": server.summaries()})

    async def page(request):
        call = by_link(request)
        if call is None:
            return await gone(request)
        config = {"topic": call.topic, "token": call.token, "call": call.id, "stageUrl": call.stage_url, "demo": call.demo is not None,
                  "language": call.args.language, "languages": list(speech.LANGUAGES),
                  "engine": speech.name(), "voice": call.voice}
        html = PAGE.replace("__PRECONNECT__", stage_preconnect(call.stage_url)).replace(
            "__CONFIG__", json.dumps(config).replace("</", "<\\/"))
        resp = web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})
        resp.set_cookie(HOME_COOKIE, server.home_key, max_age=30 * 86400, httponly=True, samesite="Lax", path="/")
        return resp

    async def audio(request):
        call = by_link(request)
        if call is None or not re.fullmatch(r"(\d{4}|filler)\.(wav|mp3)", request.match_info["name"]):
            return web.Response(status=404)
        path = call.audio_dir / request.match_info["name"]
        if not path.is_file():
            return web.Response(status=404)
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def static(request):
        body = STATIC.get(request.match_info["name"])
        if body is None:
            return web.Response(status=404)
        return web.Response(body=body, content_type=STATIC_TYPES[Path(request.match_info["name"]).suffix],
                            headers={"Cache-Control": "no-cache"})

    async def state(request):
        call = call_of(request)
        if call is None:
            return refused(request)
        call.last_seen = time.time()
        if call.demo is not None and call.demo_at < 0 and not call.demo_starting:
            # A demo starts once its page is open, so the first answer plays by itself.
            call.demo_starting = True
            asyncio.get_running_loop().create_task(call.demo_play(0))
        since = request.query.get("v")
        v, _ = server.stamp(call)
        if since is not None and since == v:
            return web.json_response({"v": v, "same": True})
        return web.json_response(server.view(call))

    async def listen(request):
        """A recording from the page, as a 16 kHz mono WAV, becomes a turn."""
        call = call_of(request)
        if call is None:
            return refused(request)
        if call.ended:
            return web.json_response({"error": "the call has ended"}, status=410)
        lang = request.query.get("lang", call.args.language)
        language = speech.LANGUAGES.get(lang, speech.LANGUAGES.get(call.args.language))
        wav = await request.read()
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(call.listen_pool, speech.transcribe, wav, language)
        except speech.SpeechError as err:
            return web.json_response({"error": str(err)}, status=502)
        if not text.strip():
            return web.json_response({"text": ""})
        # Live mode: the user spoke over an answer. Its own words heard back are an echo, not a turn;
        # "mm-hm" means go on; with cue words, only words that start with one interrupt, and a cue word
        # alone means "stop and listen".
        q = request.query
        live = q.get("live") == "1"
        if "interrupted" in q and call.echo_of(text, q.get("interrupted"), q.get("at")):
            return web.json_response({"text": "", "echo": True})
        # A spoken command is acted on by the page and is no turn. "Never mind" takes back what Claude
        # does not have yet; once it does, the words go to Claude as said.
        command = command_of(text) if live else None
        if command == "withdraw" and call.withdraw_last():
            return web.json_response({"text": "", "command": "withdraw", "withdrawn": True})
        if command and command != "withdraw":
            return web.json_response({"text": "", "command": command})
        if "interrupted" in q and is_backchannel(text):
            return web.json_response({"text": "", "backchannel": True})
        if q.get("keyword"):
            rest = after_keyword(text)
            if rest is None:
                return web.json_response({"text": text, "ignored": True})
            if not rest:
                return web.json_response({"text": "", "keyword": True})
            text = rest
        interrupted = call.interruption(q.get("interrupted"), q.get("at")) if "interrupted" in q else None
        if server.handing_over:  # past the last save: the page keeps the turn and sends it to the next server
            return web.json_response({"error": "the talk server is restarting; try again in a moment"}, status=503)
        if live:
            # A thought that stops on "and", "um", "the"... waits a few seconds for the rest of it.
            text, interrupted = call.live_join(text, interrupted)
            if dangling(text):
                call.live_hold(text, interrupted)
                return web.json_response({"text": text, "held": True})
        return web.json_response({"text": text, "entry": call.offer(text, typed=False, interrupted=interrupted, live=live)})

    async def demo(request):
        """The gear's Stage demo: the demo call that is open, else a new one, for the page to open in a tab."""
        call = call_of(request)
        if call is None:
            return refused(request)
        ready = next((c for c in server.calls.values() if c.demo is not None and not c.ended), None)
        if ready:
            return web.json_response({"path": f"/c/{ready.id}", "call": ready.id})
        base = urllib.parse.urlsplit(call.stage_url or "")
        resp = await _register_call(server, {
            "topic": "Stage demo", "demo": True, "code": str(SKILL_DIR.parents[1]),
            "out": str(SESSIONS_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-stage-demo"), "voice": call.args.voice,
            "language": call.args.language, "stage_base": f"{base.scheme}://{base.netloc}" if base.netloc else None})
        body = json.loads(resp.text)
        if resp.status != 200:
            return web.json_response({"error": body.get("error", "the demo did not open")}, status=resp.status)
        return web.json_response({"path": body["path"], "call": body["call"]})

    async def withdraw(request):
        """Undo: take back what was said, while Claude does not have it yet."""
        call = call_of(request)
        if call is None:
            return refused(request)
        body = await request.json() if request.can_read_body else {}
        entry = body.get("entry") if isinstance(body, dict) else None
        if not isinstance(entry, int) or isinstance(entry, bool):
            return web.json_response({"error": "name the entry to take back"}, status=400)
        return web.json_response({"withdrawn": call.withdraw(entry)})

    async def typed(request):
        call = call_of(request)
        if call is None:
            return refused(request)
        if call.ended:
            return web.json_response({"error": "the call has ended"}, status=410)
        body = await request.json()
        text = str(body.get("text", "")).strip() if isinstance(body, dict) else ""
        if not text:
            return web.json_response({"error": "nothing to send"}, status=400)
        if server.handing_over:
            return web.json_response({"error": "the talk server is restarting; try again in a moment"}, status=503)
        return web.json_response({"text": text, "entry": call.offer(text[:4000], typed=True)})

    async def floor(request):
        call = call_of(request)
        if call is None:
            return refused(request)
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        heard = body.get("heard") if isinstance(body, dict) else None
        return web.json_response({"floor_n": server.take_floor(call, heard)})

    async def stop(request):
        call = call_of(request)
        if call is not None:
            call.end("ended from the page")
        return web.json_response({})

    async def close(request):
        call = call_of(request)
        if call is not None:
            call.end("ended from the page")
            call.closed.set()
        return web.json_response({})

    async def next_turn(request):
        call = call_of(request)
        if call is None:
            return refused(request)
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
        """The activity hook runs in every session on this machine. A doorbell names its call and so
        makes its session that call's owner; every other event goes to the calls that session owns."""
        call = call_of(request)
        if call is None and not server.is_server(token_of(request)):
            return forbidden()
        body = await request.json()
        body = body if isinstance(body, dict) else {}
        if call is not None:
            return web.json_response({"recorded": call.record_activity(body)})
        if body.get("doorbell"):
            target = server.calls.get(str(body.get("call") or ""))
            if target is None and not body.get("call") and len(server.calls) == 1:
                target = next(iter(server.calls.values()))
            return web.json_response({"recorded": bool(target and target.record_activity(body))})
        session = str(body.get("session_id", ""))
        owned = [c for c in server.calls.values() if session and c.owner_session == session]
        return web.json_response({"recorded": any([c.record_activity(body) for c in owned])})

    async def post_reply(request):
        call = call_of(request)
        if call is None:
            return refused(request)
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"error": "a JSON object is required"}, status=400)
        status, text, end = str(body.get("status", "")).strip(), str(body.get("text", "")), bool(body.get("end"))
        if status and end:
            return web.json_response({"error": "a status cannot end the call; send the wrap-up with end"},
                                     status=400)
        if call.ended:
            return web.json_response({"error": "the call has ended", "transcript": str(call.transcript)}, status=410)
        if not status and not text.strip() and not end:
            return web.json_response({"error": "nothing to say: the reply is empty"}, status=400)
        result = call.turns.accept_reply(str(body.get("id", "")), final=not status)
        if result == "unknown":
            return web.json_response({"error": "no such turn in this call"}, status=404)
        if status:
            if result != "ok":
                return web.json_response({"ok": True, "ignored": "the turn was already answered; status not shown"})
            call.add("status", status[:120])
            return web.json_response({"ok": True})
        if result != "ok":
            return web.json_response({"ok": True, "ignored": "the turn was already answered; this reply was "
                                                             "not shown or said again"})
        problems_from = len(call.board.problems)
        await call.answer(text)
        await call.stage_settled()
        if end:
            call.end("wrapped up by Claude")
        return web.json_response({"ok": True, "board_problems": call.board.problems[problems_from:]})

    async def health(request):
        if not server.is_server(token_of(request)):
            return forbidden()
        return web.json_response({"code": server.code, "calls": len(server.calls), "pid": os.getpid(),
                                  "open": server.open_count(), "engine": speech.name(wait=False), "handover": True,
                                  "service": server.service})

    async def register(request):
        if not server.is_server(token_of(request)):
            return forbidden()
        body = await request.json()
        return await register_call(server, body if isinstance(body, dict) else {})

    async def quit_server(request):
        """Stop the server. With handover, open calls are left for the next server rather than refused."""
        if not server.is_server(token_of(request)):
            return forbidden()
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        handover = isinstance(body, dict) and bool(body.get("handover"))
        if server.registering or (server.open_count() and not handover):
            return web.json_response({"error": "calls are open"}, status=409)
        server.stop.set()
        return web.json_response({})

    app = web.Application(client_max_size=MAX_RECORDING_BYTES, middlewares=[handover_gate])
    app.add_routes([
        web.get("/", home),
        web.get("/api/calls", calls_list),
        web.post("/api/calls", register),
        web.get("/api/health", health),
        web.post("/api/quit", quit_server),
        web.get("/c/{call}", page),
        web.get("/c/{call}/audio/{name}", audio),
        web.get("/static/{name}", static),
        web.get("/api/state", state),
        web.post("/api/listen", listen),
        web.post("/api/say", typed),
        web.post("/api/withdraw", withdraw),
        web.post("/api/demo", demo),
        web.post("/api/floor", floor),
        web.post("/api/stop", stop),
        web.post("/api/close", close),
        web.get("/api/turn", next_turn),
        web.post("/api/reply", post_reply),
        web.post("/api/activity", activity),
    ])
    return app


async def watch(call: Call) -> None:
    """End a call nobody talks in; close an ended one once its page is gone."""
    while not call.closed.is_set():
        await asyncio.sleep(1)
        now = time.time()
        if not call.ended:
            if (call.demo is None and now - call.last_turn > call.args.idle_minutes * 60
                and not call.busy(call.args.idle_minutes * 60)):  # a demo stays ready: it never goes idle
                call.end(f"nothing was said for {call.args.idle_minutes} minutes")
        elif now - call.ended_at > LINGER_S or now - call.last_seen > PAGE_GONE_S:
            call.closed.set()


def warm_up(voice: str) -> None:
    """Load the voice and the word-timing model, or open Azure's connection: seconds the first time."""
    try:
        speech.speak("Ready.", voice)
    except speech.SpeechError as err:
        say(f"speech: warm-up failed: {err}")


class CallError(Exception):
    """A call could not be opened; the message says why, for the session to relay."""


def open_call(args, topic: str, out_dir: Path, cwd: Path, stage_base: str | None = None) -> tuple[Call, list[str]]:
    """Make a call: its record, a stage of its own and its voice. Blocks, so a server runs it off the loop.
    Returns the call and the lines its launch prints."""
    # The same folder `stage.py show` falls back to (the git root), so both reach one stage.
    stage_cwd = str(args.code) if args.code else stage_mod.repo_root(Path(cwd))
    call_id = new_call_id()
    # A stage of its own for every call, so one call's boards never land among another's.
    stage_slug = stage_mod.wc.slugify(f"{stage_mod.PRIVATE_SLUG_PREFIX}{call_id[:8]}")
    try:
        stage_row = stage_mod.ensure_stage(stage_cwd, slug=stage_slug, title=f"Talk · {topic}")
    except stage_mod.wc.SlugMismatch as err:
        raise CallError(f"talk could not open this call's stage: {err}")
    except stage_mod.DAEMON_ERRORS + (ValueError,) as err:
        raise CallError(f"talk needs the webcompanion daemon for its stage: {err}")
    if stage_row.get("slug", stage_slug) != stage_slug or not stage_row.get("sid"):
        raise CallError(f"the stage for this call came back as {stage_row.get('slug')!r} "
                        f"(sid {stage_row.get('sid')!r}), not {stage_slug!r}")
    call = Call(args, topic, out_dir)
    call.id = call_id
    call.stage_cwd, call.stage_slug, call.stage_sid = stage_cwd, stage_row["slug"], stage_row["sid"]
    call.stage_url = rebase(stage_row["url"], stage_base)
    call.voice, problem = speech.resolve_voice(args.voice)
    lines = [f"Speech {speech.name()}, voice {args.voice or call.voice}"
             + (f" (profile {call.voice})" if args.voice and call.voice != args.voice else "")]
    if problem:
        lines.append(f"speech: {problem}")
    return call, lines


async def register_call(server: Server, body: dict):
    """POST /api/calls from a launch: open a call on this server and tell the launch where it is."""
    from aiohttp import web

    if server.stop.is_set():
        return web.json_response({"error": "the talk server is stopping; run again"}, status=503)
    server.registering += 1
    server.empty_since = time.time()
    try:
        return await _register_call(server, body)
    finally:
        server.registering -= 1
        server.empty_since = time.time()


async def _register_call(server: Server, body: dict):
    from aiohttp import web

    def refuse(status: int, error: str):
        return web.json_response({"error": error}, status=status)

    topic = str(body.get("topic") or "").strip()
    if not topic or not body.get("out"):
        return refuse(400, "a call needs a topic and an out folder")
    language = str(body.get("language") or "auto")
    if language not in speech.LANGUAGES:
        return refuse(400, f"unknown language {language}")
    code = Path(body["code"]) if body.get("code") else None
    if code is not None and not code.is_dir():
        return refuse(400, f"--code: not a folder: {code}")
    args = argparse.Namespace(code=code, voice=body.get("voice") or None, language=language,
                              idle_minutes=int(body.get("idle_minutes") or 60))
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: speech.ensure_running(say=say))
    except speech.SpeechError as err:
        return refuse(503, f"{err}. {speech.fix()}, then run again.")
    try:
        call, lines = await loop.run_in_executor(None, open_call, args, topic, Path(body["out"]),
                                                 Path(body.get("cwd") or Path.cwd()), body.get("stage_base"))
    except CallError as err:
        return refuse(502, str(err))
    if body.get("demo"):
        call.demo = load_demo()
    server.add(call)
    path = f"/c/{call.id}"
    server.write_call_file(call)
    server.save_state(call, force=True)
    server.keep(call)
    if call.voice not in server.warm:
        # The first speech loads VoiceStudio's model (about 11 s) or opens Azure's connection: pay that before the first answer.
        server.warm.add(call.voice)
        loop.run_in_executor(call.speech_pool, warm_up, call.voice)
    say(f"talk: call {call.id} opened: {topic}; {len(server.calls)} open")
    return web.json_response({"call": call.id, "path": path, "stage_url": call.stage_url,
                              "stage_cwd": call.stage_cwd, "stage_slug": call.stage_slug,
                              "stage_sid": call.stage_sid, "lines": lines})


def home_key() -> str:
    """The list-of-calls cookie, kept across servers so a page opened yesterday still opens the list."""
    path = talk_files.run_dir() / "home.json"
    key = (talk_files.read(path) or {}).get("key")
    if not key:
        key = secrets.token_urlsafe(24)
        talk_files.write_private(path, {"key": key})
    return key


def drop_stale_call(call_id: str, data: dict) -> None:
    if data.get("stage_sid"):
        try:
            stage_mod.wc.finish_session(data["stage_sid"])
        except stage_mod.DAEMON_ERRORS as err:
            say(f"talk: stale call {call_id}: its stage {data['stage_sid']} was not ended: {err}")
    talk_files.call_file(call_id).unlink(missing_ok=True)
    talk_files.state_file(call_id).unlink(missing_ok=True)


def drop_stale_calls(port: int) -> None:
    """Calls a server that was on this port before left behind and the next one cannot carry on: those
    that had ended, and those written by code that kept no state. Their stages are ended and their
    files removed. Another port's are not ours."""
    for stale in talk_files.call_ids():
        data = talk_files.read(talk_files.call_file(stale)) or {}
        if data.get("port") == port and not (talk_files.adoptable(data) and talk_files.state_file(stale).is_file()):
            drop_stale_call(stale, data)


def wait_for_exit(pid) -> None:
    """A previous server may still be on its way out after letting go of the port: let it finish."""
    if not pid or pid == os.getpid():
        return
    deadline = time.time() + PORT_WAIT_S
    while talk_files.pid_alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    if talk_files.pid_alive(pid):
        say(f"talk: the previous server, pid {pid}, has not exited; carrying its calls over anyway")


def adopt_calls(server: Server) -> list[Call]:
    """Carry on every open call a previous server on this port left behind; end the rest. Runs before
    the loop serves a request, so no page or doorbell is refused for a call that is about to be adopted."""
    drop_stale_calls(server.port)
    adopted = []
    for call_id in talk_files.call_ids():
        data = talk_files.read(talk_files.call_file(call_id)) or {}
        if data.get("port") != server.port or call_id in server.calls:
            continue
        wait_for_exit(data.get("pid"))
        data = talk_files.read(talk_files.call_file(call_id)) or {}
        state = talk_files.read(talk_files.state_file(call_id)) or {}
        try:
            if not talk_files.adoptable(data) or state.get("call") != call_id or state.get("token") != data.get("token"):
                raise ValueError("its files do not match")
            call = Call.restore(state)
        except (KeyError, TypeError, ValueError, OSError) as err:
            say(f"talk: call {call_id} could not be carried over: {err}")
            drop_stale_call(call_id, data)
            continue
        adopted.append(server.adopt(call, state))
    return adopted


async def run_server(port: int, stay: bool = False) -> int:
    """The one talk server of this machine: it holds every call, and exits once none is left, unless
    it stays (launchd runs it as a service, and would only start it again)."""
    from aiohttp import web

    server = Server(secrets.token_urlsafe(24), port, home_key=home_key())
    server.service = stay
    runner = web.AppRunner(build_app(server), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", port).start()
    except OSError as err:
        holder = port_holder(port)
        say(f"talk: port {port} is in use{f' by pid {holder}' if holder else ''}: {err}")
        await runner.cleanup()
        return 1
    loop = asyncio.get_running_loop()
    # Chosen off the loop: TALK_AZURE_KEY_COMMAND may take seconds, and no request should wait on it.
    loop.run_in_executor(None, speech.name)
    adopt_calls(server)
    server.write_files()
    say(f"talk: server on port {port}, pid {os.getpid()}, code {server.code}, {len(server.calls)} call(s) carried over")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, server.stop.set)
    try:
        while not server.stop.is_set():
            try:
                await asyncio.wait_for(server.stop.wait(), 1)
            except asyncio.TimeoutError:
                pass
            server.write_files()
            server.save_calls()
            if not stay and not server.calls and not server.registering and time.time() - server.empty_since > IDLE_EXIT_S:
                say(f"talk: no call for {IDLE_EXIT_S // 60} minutes, stopping")
                break
    finally:
        await server.hand_over()
        for call in list(server.calls.values()):
            call.closed.set()
        if server.tasks:
            await asyncio.wait(server.tasks, timeout=8)
        talk_files.remove_if_pid(talk_files.server_file(port), os.getpid())
        server.speech.shutdown()
        await runner.cleanup()
    return 0


# ---------------------------------------------------------------------------
# Launch: start the server if none runs, then open a call on it
# ---------------------------------------------------------------------------


def server_request(info: dict, method: str, path: str, body: dict | None = None, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{info['port']}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Talk-Token": info.get("token", ""), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def server_health(info: dict | None) -> dict | None:
    if not info or not info.get("port"):
        return None
    try:
        return server_request(info, "GET", "/api/health", timeout=3)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def running_server(port: int) -> dict | None:
    """The talk server on `port` that answers with the token in its file: this code's file, else the
    one file a server on older code wrote for every port."""
    for path in (talk_files.server_file(port), talk_files.legacy_server_file()):
        info = talk_files.read(path)
        if info and info.get("port") == port and server_health(info):
            return info
    return None


def port_held(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def port_holder(port: int) -> str:
    """The pid(s) listening on `port`, comma separated, or "" when lsof cannot say."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return ",".join(out.stdout.split())


def port_answer(port: int) -> str:
    """What answers a request without a token on `port`: 'talk' (403 forbidden, as every talk server
    answers it), 'busy' (no answer in time), or 'other'."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3):
            return "other"
    except urllib.error.HTTPError as err:
        try:
            body = json.loads(err.read() or b"{}")
        except ValueError:
            body = {}
        return "talk" if err.code == 403 and isinstance(body, dict) and body.get("error") == "forbidden" else "other"
    except (TimeoutError, socket.timeout):
        return "busy"
    except urllib.error.URLError as err:
        return "busy" if isinstance(err.reason, (TimeoutError, socket.timeout)) else "other"
    except OSError:
        return "other"


def port_report(port: int) -> str:
    """Who holds `port` when no server this launch can reach does, and what to do about it."""
    who = {"talk": "a talk server this launch has no token for (its run file is missing or stale)",
           "busy": "a server that does not answer within 3 s",
           "other": "a program that is not a talk server"}[port_answer(port)]
    holder = port_holder(port)
    fix = f"stop it with `kill {holder.replace(',', ' ')}`" if holder else "stop it"
    return f"port {port} is held by {who}, pid {holder or 'unknown'}; {fix}, or pass --port <another port>"


def spawn_server(port: int, log_path: Path) -> subprocess.Popen:
    """Start the server detached from this launch, so it outlives the session that started it."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as log:
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", "--port", str(port)],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True, cwd=str(SKILL_DIR))


def start_server(port: int) -> dict:
    """The server of this machine, started when none answers. A server on older code is replaced when
    it holds no call; while it holds calls, new calls join it and it updates once they have ended."""
    info = running_server(port)
    if info is None and port_held(port):
        deadline = time.time() + PORT_WAIT_S
        while info is None and port_held(port) and time.time() < deadline:
            time.sleep(0.5)
            info = running_server(port)
        if info is None and port_held(port):
            raise SystemExit(f"talk: {port_report(port)}")
    if info:
        health = server_health(info) or {}
        if health.get("code") == code_version():
            return info
        if health.get("open", health.get("calls")):
            later = (", or now with `talk.py --restart`, which keeps them open" if health.get("handover") else "")
            say(f"talk: the server (pid {health.get('pid')}) runs older code {health.get('code')} and has calls "
                f"open, so this call joins it; it updates once they have all ended{later}")
            return info
        if health.get("service") and talk_service.installed():
            return service_up(port, restart=True)
        try:
            server_request(info, "POST", "/api/quit")
        except urllib.error.HTTPError as err:
            if err.code == 409:
                say(f"talk: the server (pid {health.get('pid')}) runs older code {health.get('code')} and a call "
                    "opened on it meanwhile, so this call joins it; it updates once they have all ended")
                return info
        except (urllib.error.URLError, OSError, ValueError):
            pass
        deadline = time.time() + 10
        while server_health(info) and time.time() < deadline:
            time.sleep(0.2)
        if server_health(info):
            raise SystemExit(f"talk: the server on port {port} (pid {health.get('pid')}, older code "
                             f"{health.get('code')}) did not stop when asked; stop it with `kill {health.get('pid')}`")
    return bring_up(port)


def bring_up(port: int) -> dict:
    """With the service installed, launchd starts the server, with the settings in its plist; without
    it, this launch starts one, with this session's environment."""
    return service_up(port) if talk_service.installed() else spawn_and_wait(port)


def service_up(port: int, restart: bool = False) -> dict:
    """Ask launchd for the server, and wait for one that answers. With restart, the running service
    stops first (its calls are handed over) and only a server with another pid counts."""
    before = (server_health(running_server(port)) or {}).get("pid") if restart else None
    try:
        talk_service.kickstart(restart)
    except (talk_service.ServiceError, OSError, subprocess.TimeoutExpired) as err:
        raise SystemExit(f"talk: {err}")
    deadline = time.time() + SERVER_START_S + (HANDOVER_S if restart else 0)
    while time.time() < deadline:
        info = running_server(port)
        if info and (server_health(info) or {}).get("pid") not in (None, before):
            return info
        time.sleep(0.2)
    raise SystemExit(f"talk: the service {talk_service.LABEL} did not answer within {SERVER_START_S:.0f} s "
                     f"(log {talk_files.run_dir() / 'server.log'})")


def spawn_and_wait(port: int) -> dict:
    log_path = talk_files.run_dir() / "server.log"
    proc = spawn_server(port, log_path)
    deadline = time.time() + SERVER_START_S
    while time.time() < deadline:
        info = running_server(port)
        if info:
            return info
        if proc.poll() is not None:
            # Another launch may have started a server at the same moment: use that one.
            info = running_server(port)
            if info:
                health = server_health(info) or {}
                if health.get("code") != code_version():
                    say(f"talk: joined the server another launch reached first, pid {health.get('pid')}, "
                        f"which runs older code {health.get('code')}")
                return info
            if port_held(port):
                raise SystemExit(f"talk: the server did not start: {port_report(port)}")
            tail = log_path.read_text(errors="replace").strip().splitlines()[-3:]
            raise SystemExit(f"talk: the server did not start: {' / '.join(tail) or 'no output'} (log {log_path})")
        time.sleep(0.2)
    raise SystemExit(f"talk: the server did not answer within {SERVER_START_S:.0f} s (log {log_path})")


def restart_server(port: int) -> int:
    """Replace the server on `port` with one on this code, carrying its open calls over: their links,
    pages and doorbells keep working. A server on code that would end its calls when stopped is left
    alone while it holds any."""
    info = running_server(port)
    if info is None:
        if port_held(port):
            raise SystemExit(f"talk: {port_report(port)}")
        info = bring_up(port)
        health = server_health(info) or {}
        say(f"talk: no server was running; started pid {health.get('pid')}, "
            f"{health.get('open', 0)} call(s) carried over")
        return 0
    health = server_health(info) or {}
    open_now = health.get("open", health.get("calls")) or 0
    if open_now and not health.get("handover"):
        say(f"talk: the server (pid {health.get('pid')}, code {health.get('code')}) would end its {open_now} open "
            "call(s) if stopped, so it was not restarted; it updates once they have ended")
        return 2
    if health.get("service") and talk_service.installed():
        info = service_up(port, restart=True)
    else:
        stopped = stop_server(port, info, health)
        if stopped:
            return stopped
        info = bring_up(port)
    new = server_health(info) or {}
    say(f"talk: restarted on port {port}: pid {new.get('pid')}, code {new.get('code')}, "
        f"{new.get('open', 0)} call(s) carried over")
    return 0


def stop_server(port: int, info: dict, health: dict) -> int:
    """Stop the server, its open calls kept for the next one; 0 once the port is free, else 2."""
    try:
        server_request(info, "POST", "/api/quit", {"handover": True})
    except urllib.error.HTTPError as err:
        try:
            message = json.loads(err.read()).get("error")
        except (OSError, ValueError, AttributeError):
            message = None
        say(f"talk: the server (pid {health.get('pid')}) refused to stop: {message or f'HTTP {err.code}'}; "
            "nothing was changed")
        return 2
    except (urllib.error.URLError, OSError, ValueError):
        pass
    deadline = time.time() + PORT_WAIT_S + HANDOVER_S
    while (server_health(info) or port_held(port)) and time.time() < deadline:
        time.sleep(0.2)
    if server_health(info) or port_held(port):
        say(f"talk: the server (pid {health.get('pid')}) did not stop when asked; nothing was changed. "
            f"`kill {health.get('pid')}` stops it" + (" and keeps its calls for the next server" if health.get("handover") else ""))
        return 2
    return 0


def install_service(port: int) -> int:
    """Run the server under launchd from now on. A server a session started is stopped first, its
    calls handed over to the service, so its environment stops mattering at once."""
    info = running_server(port)
    health = (server_health(info) or {}) if info else {}
    if info and not health.get("service"):
        if (health.get("open", health.get("calls")) or 0) and not health.get("handover"):
            say(f"talk: the server (pid {health.get('pid')}) would end its open calls if stopped; "
                "install the service once they have ended")
            return 2
        stopped = stop_server(port, info, health)
        if stopped:
            return stopped
    elif info is None and port_held(port):
        raise SystemExit(f"talk: {port_report(port)}")
    try:
        spec = talk_service.install(Path(__file__).resolve(), port, talk_files.run_dir() / "server.log")
    except (talk_service.ServiceError, OSError, subprocess.TimeoutExpired) as err:
        say(f"talk: the service was not installed: {err}")
        return 2
    info = service_up(port)
    new = server_health(info) or {}
    deadline = time.time() + 25  # the engine is chosen off the loop: the key command may take a while
    while not new.get("engine") and time.time() < deadline:
        time.sleep(0.5)
        new = server_health(info) or new
    env = spec["EnvironmentVariables"]
    speech_from = (f"key from `{env['TALK_AZURE_KEY_COMMAND']}`" if env.get("TALK_AZURE_KEY_COMMAND")
                   else f"TALK_SPEECH={env.get('TALK_SPEECH')}")
    say(f"talk: installed {talk_service.plist_path()}; launchd runs the server (pid {new.get('pid')}, "
        f"{new.get('open', 0)} call(s) carried over), speaking with {new.get('engine') or 'an engine still being chosen'} "
        f"({speech_from})")
    say("talk: install it again after the speech settings change; a session's own environment no longer matters")
    return 0


def uninstall_service(port: int) -> int:
    if not talk_service.uninstall():
        say("talk: the service was not installed")
        return 0
    say(f"talk: removed {talk_service.LABEL}; its open calls are kept, and the next launch starts a server itself")
    return 0


def launch(args) -> int:
    info = start_server(args.port)
    out_dir = (args.out or SESSIONS_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(args.topic)}").resolve()
    body = {"topic": args.topic, "code": str(args.code) if args.code else None, "out": str(out_dir),
            "voice": args.voice, "language": args.language, "idle_minutes": args.idle_minutes,
            "stage_base": args.stage_base, "cwd": str(Path.cwd()), "demo": bool(getattr(args, "demo", False))}
    try:
        got = server_request(info, "POST", "/api/calls", body, timeout=REGISTER_S)
    except urllib.error.HTTPError as err:
        try:
            message = json.loads(err.read()).get("error")
        except (OSError, ValueError, AttributeError):
            message = None
        say(f"talk: {message or f'the server refused the call: HTTP {err.code}'}")
        return 2
    except (urllib.error.URLError, OSError) as err:
        say(f"talk: the server stopped answering: {err}")
        return 1
    for line in got.get("lines", []):
        say(line)
    local = f"http://127.0.0.1:{info['port']}{got['path']}"
    say(f"Open {local}")
    if args.url_base:
        say(f"Link {args.url_base.rstrip('/')}{got['path']}")
    say(f"Stage {got['stage_url']} (folder {got['stage_cwd']}, slug {got['stage_slug']}, "
        f"sid {got.get('stage_sid') or got['stage_slug']})")
    say(f"Call {got['call']}")
    if args.url_base:
        say(f"Calls {args.url_base.rstrip('/')}/")
    if not args.no_open:
        webbrowser.open(local)
    return 0


# ---------------------------------------------------------------------------
# Doctor: the speech engine, a round trip through it, the stage's daemon
# ---------------------------------------------------------------------------


def doctor(args) -> int:
    ok = True
    try:
        chosen = speech.engine().NAME
        if speech.key_failure and chosen != "Azure":
            say(f"[--] TALK_AZURE_KEY_COMMAND is set but gave no key: {speech.key_failure}")
        info = speech.ensure_running(say=say)
        say(f"[ok] {speech.describe(info)}")
    except speech.SpeechError as err:
        say(f"[FAIL] {err}")
        return 1
    phrase = "The doorbell is ready."
    voice, problem = speech.resolve_voice(args.voice)
    say(f"[--] voice: {problem}" if problem else f"[ok] voice {voice}")
    try:
        t = time.time()
        made = speech.speak(phrase, voice, wav=True)
        say(f"[ok] text to speech in {time.time() - t:.1f}s, {len(made.words)} words timed")
        t = time.time()
        heard = speech.transcribe(made.audio, "en")
        good = "doorbell" in heard.lower()
        ok &= good
        say(f"[{'ok' if good else 'FAIL'}] speech to text heard {heard!r} in {time.time() - t:.1f}s")
    except speech.SpeechError as err:
        ok = False
        say(f"[FAIL] {err}")
    problem = stage_mod.daemon_status()
    ok &= not problem
    say(f"[FAIL] webcompanion daemon (the stage): {problem}" if problem else "[ok] webcompanion daemon (the stage)")
    info = running_server(args.port)
    health = server_health(info) if info else None
    if health:
        stale = "" if health.get("code") == code_version() else (
            "; it runs older code: `talk.py --restart` updates it and keeps its calls" if health.get("handover")
            else "; it runs older code and updates once its calls end")
        say(f"[ok] talk server on port {args.port}, pid {health.get('pid')}, "
            f"{health.get('open', health.get('calls'))} call(s) open{stale}")
        holder = port_holder(args.port)
        if holder and str(health.get("pid")) not in holder.split(","):
            ok = False
            say(f"[FAIL] the server file names pid {health.get('pid')}, but pid {holder} listens on port {args.port}")
        engine = health.get("engine")
        if engine and engine != "choosing" and engine != speech.name():
            say(f"[--] the server speaks with {engine}, while this environment would choose {speech.name()}; "
                "it changes when the server restarts")
    elif port_held(args.port):
        ok = False
        say(f"[FAIL] no talk server this launch can reach, yet {port_report(args.port)}")
    else:
        say(f"[--] no talk server on port {args.port}; the first call starts it")
    say("all checks passed" if ok else "some checks failed")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A spoken conversation with a Claude Code session.")
    parser.add_argument("--topic", help="what the call is about (required unless --doctor)")
    parser.add_argument("--code", type=Path, help="the folder [[show code: ...]] reads from, and the stage's folder")
    parser.add_argument("--out", type=Path, help="where the transcript and audio go")
    parser.add_argument("--voice", default=os.environ.get("TALK_VOICE"),
                        help="an Azure neural voice (default en-US-AvaMultilingualNeural), or with VoiceStudio a "
                             "voice profile by name or id (default Talk); without a profile, every answer comes "
                             "in a different random voice")
    parser.add_argument("--language", choices=list(speech.LANGUAGES), default=os.environ.get("TALK_LANGUAGE", "auto"),
                        help="the language the page listens for first; auto detects it; the page can switch "
                             "(default auto)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TALK_PORT", DEFAULT_PORT)))
    parser.add_argument("--url-base", default=os.environ.get("TALK_URL_BASE"),
                        help="this server's https address (scheme and host), as the browser reaches it; "
                             "printed as the Link line")
    parser.add_argument("--stage-base", default=os.environ.get("TALK_STAGE_BASE"),
                        help="the webcompanion daemon's address as reached from the browser "
                             "(scheme and host); default: the daemon's own")
    parser.add_argument("--no-open", action="store_true", help="don't open the page in the default browser")
    parser.add_argument("--idle-minutes", type=int, default=60, help="end the call after this long with no turn")
    parser.add_argument("--doctor", action="store_true", help="check the speech engine with a round trip, and the stage")
    parser.add_argument("--demo", action="store_true",
                        help="open a call that shows every board of the stage, played from demo.md, with no Claude session")
    parser.add_argument("--restart", action="store_true",
                        help="replace the running server with one on this code, keeping its open calls")
    parser.add_argument("--serve", action="store_true",
                        help="run the server that holds every call of this machine; a launch starts it itself")
    parser.add_argument("--stay", action="store_true", help="with --serve: keep running with no call (launchd)")
    parser.add_argument("--install-service", action="store_true",
                        help="run the server under launchd, with this shell's speech settings (macOS)")
    parser.add_argument("--uninstall-service", action="store_true", help="stop running the server under launchd")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.serve:
        return asyncio.run(run_server(args.port, stay=args.stay))
    if args.install_service:
        return install_service(args.port)
    if args.uninstall_service:
        return uninstall_service(args.port)
    if args.restart:
        return restart_server(args.port)
    if args.code:
        args.code = args.code.expanduser().resolve()
        if not args.code.is_dir():
            parser.error(f"--code: not a folder: {args.code}")
    if args.doctor:
        return doctor(args)
    if args.demo:
        args.topic = args.topic or "Stage demo"
        args.code = args.code or SKILL_DIR.parents[1]  # the demo's boards show this repository
    if not args.topic:
        parser.error("--topic is required")
    return launch(args)


GONE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Talk</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F5F6F8;color:#1B2230;
font:15px/1.6 Inter,system-ui,-apple-system,sans-serif;padding:0 16px}main{max-width:420px}h1{font-size:18px;margin:0 0 6px}
p{margin:0;color:#667085}</style></head><body><main><h1>This call link is not active</h1>
<p>The call may have ended, or the link is incomplete. Ask the Claude session for the current link.</p></main></body></html>"""


# The call page and the list of calls live in static/. All of it is read once, when the server
# starts, so a page reloaded after a git pull still gets markup and code of one version; a launch
# replaces a server whose code is stale (code_version).
PAGE = (STATIC_DIR / "call.html").read_text()
HOME_PAGE = (STATIC_DIR / "home.html").read_text()
STATIC = {path.name: path.read_bytes() for path in STATIC_DIR.iterdir() if path.suffix in STATIC_TYPES}


HOME_LOCKED = GONE_PAGE.replace("This call link is not active", "Open a call first").replace(
    "The call may have ended, or the link is incomplete. Ask the Claude session for the current link.",
    "The list of calls opens in a browser that has opened one call's link. Ask the Claude session for its link.")
assert HOME_LOCKED != GONE_PAGE


if __name__ == "__main__":
    sys.exit(main())
