# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "aiohttp>=3.10,<4",
#   "anthropic>=1.0,<2",
#   "parakeet-mlx>=0.5,<0.6; sys_platform == 'darwin' and platform_machine == 'arm64'",
# ]
# ///
"""talk: full-duplex voice on top of a Claude Code session. GPT-Live is the voice, Claude is the brain.

    browser page (mic + speakers, WebRTC, browser echo cancellation)
        <-> OpenAI GPT-Live (gpt-live-1): listens and speaks at the same time,
            handles pauses and interruptions
                -- session.delegation.created -->  this script (sideband WebSocket)
                                                     -> the brain
                <-- session.commentary.append ---  the brain's reply, normalised for speech

GPT-Live runs in *client delegation* mode: whenever the user says something that
needs a real answer, it hands off to this script instead of answering itself.

The brain is chosen with --llm:
    session      the Claude Code session that launched this script. Each turn is queued,
                 collected with `talk_client.py doorbell` and answered with
                 `talk_client.py reply`. This is what /talk uses.
    claude-code  a fresh `claude -p` per turn, with an optional --brief as its system prompt.
    api          the Anthropic API with ANTHROPIC_API_KEY.

Audio runs in a local browser page, because the browser's getUserMedia gives
acoustic echo cancellation: laptop speakers or a Bluetooth speakerphone work
without headphones, and you can still interrupt.

    uv run --script talk.py --llm session --topic "The findings deck" --code <repo>
    uv run --script talk.py --doctor

Then open the printed URL and press Start. OPENAI_API_KEY comes from the environment
or ~/.config/talk/keys.env. TALK_OPENAI_API_KEY, from either, overrides it, so this tool
can have its own key and its own usage.
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
import statistics
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_turns import TurnQueue  # noqa: E402
import ear as ear_mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skills.stage import stage as stage_mod  # noqa: E402

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "talk"
KEYS_FILE = CONFIG_DIR / "keys.env"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "talk"
SESSIONS_DIR = DATA_DIR / "sessions"
LEDGER_FILE = DATA_DIR / "ledger.jsonl"  # one line per GPT-Live session, for the daily cap

DEFAULT_MODEL = "claude-sonnet-5"
LIVE_MODEL = "gpt-live-1"
LIVE_PRICE_PER_MIN = 0.05  # OpenAI's published gpt-live-1 rate, September 2026
SESSION_FLOOR_S = 15.0  # OpenAI bills every session at least 15 s: each one counts max(its seconds, 15)
DEFAULT_MAX_LIVE_MINUTES = 30  # paid live minutes per call
DEFAULT_DAILY_LIVE_MINUTES = 120  # paid live minutes per calendar day, all calls on this machine
DEFAULT_VOICE = "marin"
DEFAULT_PORT = 8766
OPENAI_API = "https://api.openai.com/v1"
BILLING_URL = "https://platform.openai.com/settings/organization/billing"
USAGE_URL = "https://platform.openai.com/usage"  # the real bill, which every cost shown here only estimates
CREATE_TIMEOUT_S = 30.0  # the page is told a session create failed after this long
CREATE_CEILING_S = 120.0  # the POST itself runs on to here: a session that arrives late is closed
CONNECT_TIMEOUT_MIN = 15  # give up if nobody presses Start within this long
STAGE_SETTLE_S = 5.0  # how long a reply waits for its stage shows; talk_client gives a reply 10 s
STATE_FILE = Path(os.environ.get("TALK_STATE")
                  or Path(os.environ.get("TMPDIR") or "/tmp") / "talk" / "session.json")
BUSY_LINE = "Tell the learner in one short sentence that you're still working on it."
OFFLINE_LINE = ("Tell the learner in one short sentence that the assistant behind you isn't responding "
                "right now, so they should check the terminal.")
REJOIN_SECONDS = 90  # after a lost connection, how long the page may start a new session for the same call
REJOIN_LINE = ("The call has just resumed after a dropped connection. Tell the learner in one short sentence "
               "that you're back, and ask them to carry on where they left off.")
# A meeting's voice speaks to "the person who asked", and says nothing where the room needs no word.
MEETING_BUSY_LINE = "Tell the person who asked, in one short sentence, that you're still working on it."
MEETING_OFFLINE_LINE = ("Tell the person who asked, in one short sentence, that the assistant behind you isn't "
                        "responding right now, so you can't answer that yet.")
MEETING_REJOIN_LINE = ("The call has just resumed after a dropped connection. Stay silent and wait to be addressed "
                       "by name; say nothing.")
LIVE_CAP_LINE = ("Tell the learner in one short sentence that this call has reached its live-minute cap, so the "
                 "voice is switching off now.")
REJOIN_INTRO = "This call was interrupted by a dropped connection and is resuming."
WAKE_INTRO = ("This call went quiet, so the live voice was switched off to save cost while a recognizer on the "
              "user's machine kept listening. It is back on now. What that recognizer heard meanwhile is below.")
WAKE_LINE = ('The user has just said: "{said}". Hand it to the backend now. Do not greet, and say nothing '
             "until the backend's reply arrives.")
HELD_REPLY_LINE = ("You were about to say this when the call went quiet. Say it now to {asker}, in natural spoken "
                   "words, adding nothing of your own: {reply}")
HELD_THEN_WAKE = (' When you have said all of it, hand these words, which woke you, to the backend: "{said}". Then say '
                  "nothing more until the backend's reply arrives.")
WAKE_NOW_LINE = "You are back after a quiet spell. Say in three or four words that you're listening, then listen."
MEETING_WAKE_INTRO = ("This call went quiet, so the live voice was switched off to save cost while a recognizer on "
                      "this machine kept listening. It is back on now. The room's talk was transcribed locally "
                      "while you were not connected. The speakers are several people, unnamed, labelled Room; "
                      "what was heard meanwhile is below.")
MEETING_WAKE_LINE = ('Someone in the room just said: "{said}". Hand it to the backend now. Do not greet, and say '
                     "nothing until the backend's reply arrives.")
MEETING_WAKE_NOW_LINE = ("You are back after a quiet spell. Stay silent and wait to be addressed by name; "
                         "say nothing.")
EAR_REPLACED = 4001  # the close code of an /api/ear socket a newer page has taken over
WAKE_HANDOFF_S = 4.0  # a woken voice that has not handed the wake words off by then: the server does it
WORK_SILENT_S = 120.0  # a collected turn with no status, reply or tool call for this long: the brain is gone
MUTED_SLEEP_S = 3  # a muted call sleeps this long after the voice's last words
WORK_SILENT_AFTER_STATUS_S = 300.0  # the same once the turn has sent a status: it said it is working
RUNNING_TOOL_MAX_S = 600.0  # a tool call still running counts as activity up to here (a prompt nobody answers)
HANDOFF_IDLE_S = 1.2  # after a held reply, the voice is done once its output has been quiet this long
HELD_SPEECH_MAX_S = 120.0  # the longest the backstop waits for a held reply to be said
START_TIMEOUT_S = 20.0  # a created session that has not started by then is closed: it bills while open


def apply_mode(args) -> str | None:
    """Fill in the defaults that depend on --mode, and switch dormancy off where the ear cannot run.
    Returns why the call cannot start (a meeting without local listening), or None."""
    meeting = args.mode == "meeting"
    if args.wake is None:
        args.wake = "name" if meeting else "speech"
    if args.max_minutes is None:
        args.max_minutes = 120 if meeting else 60
    if args.dormant_after is None:
        args.dormant_after = 20 if meeting else 45
    if meeting and args.dormant_after <= 0:
        return "a meeting listens locally between questions: --dormant-after must be above 0"
    if args.dormant_after <= 0:
        return None
    if problem := ear_mod.unavailable():
        if meeting:
            return f"/meet needs local listening: {problem}"
        say(f"Dormancy is off for this call: {problem}.")
        args.dormant_after = 0
    return None


def ear_doctor_lines() -> list[str]:
    """What --doctor says about local listening. Informational: /talk works without it."""
    if problem := ear_mod.unavailable():
        return [f"[--] local listening (dormancy, /meet): {problem}"]
    if ear_mod.model_cached():
        return [f"[ok] local listening: {ear_mod.MODEL_ID} is downloaded"]
    return [f"[--] local listening: {ear_mod.MODEL_ID} is not downloaded yet; the first dormant period downloads "
            f"it (about 2.5 GB). To do it now: {ear_mod.warm_command()}"]


def create_error_message(status: int, body) -> str:
    """What the page says when OpenAI refuses a session: what to do about it, not just the HTTP code."""
    err = body.get("error") if isinstance(body, dict) else None
    err = err if isinstance(err, dict) else {}
    code, message = str(err.get("code") or err.get("type") or ""), str(err.get("message") or "")
    if status == 429 and ("insufficient_quota" in code or "insufficient_quota" in message or "quota" in message.lower()):
        return f"OpenAI account has no credit — add credit at {BILLING_URL}"
    if status == 401:
        return f"OpenAI rejected the API key (HTTP 401) — check OPENAI_API_KEY in {KEYS_FILE} or the environment"
    if status >= 500:
        return f"OpenAI had a server error (HTTP {status}); try again in a moment."
    return f"session create HTTP {status}: {message or body}"[:300]


def parse_create_body(raw: str):
    try:
        return json.loads(raw)
    except ValueError:  # a proxy's or a gateway's HTML page
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()[:200]


def dropped_reply_message(cap: str | None) -> str:
    """Why a reply was refused: the call is dormant and a cap (which ends in a full stop) or its end keeps it so."""
    return f"the call is asleep and cannot wake: {cap or 'it has ended.'} The reply was not said."


def call_cap_message(minutes: float) -> str:
    return (f"Live-minute cap for this call reached ({minutes:g} min, ${cost_usd_of(minutes * 60):.2f}). "
            "End the call, or start a new one with a higher --max-live-minutes.")


def daily_cap_message(minutes: float) -> str:
    # The daily total is read from the ledger: an entry inflated by a laptop that slept mid-session can be
    # fixed there by hand. The per-call cap counts this call's own estimate, which the ledger does not change.
    return (f"Daily live-minute cap reached ({minutes:g} min, ${cost_usd_of(minutes * 60):.2f} today). Today's "
            f"sessions are listed in {LEDGER_FILE}; a wrong entry there can be corrected by hand.")


def ledger_today_seconds(day: str | None = None) -> float:
    """Billed seconds (measured plus the 15 s floor) the ledger holds for `day`, today by default."""
    day = day or dt.date.today().isoformat()
    try:
        lines = LEDGER_FILE.read_text().splitlines()
    except OSError:
        return 0.0
    total = 0.0
    for line in lines:
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and entry.get("date") == day:
                total += float(entry.get("seconds") or 0) + float(entry.get("floor_seconds") or 0)
        except (ValueError, TypeError):
            continue
    return total


def ledger_append(entry: dict) -> None:
    try:
        LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as err:  # the call goes on; the daily cap then undercounts, so say so
        say(f"error: could not write the live-minute ledger {LEDGER_FILE}: {err}")


def caps_doctor_lines(args) -> list[str]:
    today = ledger_today_seconds()
    return [f"[--] live-minute caps: {args.max_live_minutes:g} min per call "
            f"(${cost_usd_of(args.max_live_minutes * 60):.2f}), {args.daily_live_minutes:g} min per day "
            f"(${cost_usd_of(args.daily_live_minutes * 60):.2f}); today so far {today / 60:.1f} min "
            f"(${cost_usd_of(today):.2f}), ledger {LEDGER_FILE}"]


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
# Keys: real environment variables win over the keys file
# ---------------------------------------------------------------------------


def load_keys() -> None:
    if not KEYS_FILE.exists():
        return
    for raw in KEYS_FILE.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        value = value.strip("'\"")
        if name and value and not os.environ.get(name):
            os.environ[name] = value
    if dedicated := os.environ.get("TALK_OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = dedicated


def missing_keys(llm: str) -> list[str]:
    need = ["OPENAI_API_KEY"] + (["ANTHROPIC_API_KEY"] if llm == "api" else [])
    return [k for k in need if not os.environ.get(k)]


def read_key_terms(brief: str) -> list[str]:
    match = re.search(r"^\s*key terms\s*:\s*(.+)$", brief, re.IGNORECASE | re.MULTILINE)
    if not match:
        return []
    return [t.strip() for t in match.group(1).split(",") if t.strip()][:50]


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


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PRONUNCIATION = (
    "Read code identifiers and constants as ordinary words, never letter by letter: "
    'EXTERNAL_ONLY is "external only", INTERNAL_AND_EXTERNAL is "internal and external", '
    'SEND_PROPOSAL_AND_SHARE is "send proposal and share", user_id is "user id", '
    'portfolioProposal is "portfolio proposal". Say real acronyms such as API, SQL or JSON the way '
    "engineers normally say them."
)


def frontend_instructions(topic: str, key_terms: list[str]) -> str:
    """GPT-Live's prompt. Deliberately contains no briefing content: the voice must not teach."""
    terms = f"\nWords the learner may use: {', '.join(key_terms)}.\n" if key_terms else ""
    return f"""You are the voice of a thoughtful, sharp tutor in a live spoken discussion. The topic is: {topic}.
Speak warmly and naturally, at an unhurried pace. Be clear and direct, not overly cheerful. Keep your own turns short.

You are only the voice. A backend tutor holds the briefing for this session and does all of the teaching. You do not know the specifics of the learner's project or of this topic, and you never explain, answer, give examples or make claims about the topic from your own knowledge.

Backchannel policy: Stay silent while the learner is speaking. No "mm-hmm", no "right", no listening sounds of any kind: the learner often thinks aloud in fragments, and any sound from you cuts their thought in half.

Turn-taking policy: The learner's turn ends when they have finished a complete thought, not at the first pause. A pause mid-sentence, a trailing "the", "so" or "and", or a sentence that is plainly unfinished means they are still talking: keep waiting. When unsure, wait longer.

Interruption policy: Stop speaking when the learner interrupts. Listen to what they say. If what they say needs an answer, delegate it.

Delegation policy:
Backend tools:
- Tutor: holds the briefing; explains the topic, answers questions, reacts to the learner's answers and guesses, corrects misconceptions, decides what to cover next, saves notes, and wraps up the session.
Delegate to the backend when:
- The learner asks a question, makes a claim or a guess, answers a question the tutor asked, or says anything that needs a substantive reply.
- The learner asks you to remember something or save a note.
- The learner wants to stop, or says something like "let's stop here".
- A correction changes what they were asking.
Do not delegate to the backend when:
- The learner only makes a listening sound or a short acknowledgement while you are still speaking.
- The learner asks you to repeat or slow down something you just said.
- You could not hear them and need one short clarification.
- The learner is still in the middle of a thought, even if they paused.
Delegate before giving an answer that depends on backend work, and only once the learner's thought is complete.
Backend replies can take a while when the tutor is looking something up in the code; wait patiently and never fill the gap with content of your own. The learner's page has a board where the tutor shows code and diagrams, so phrases like "on the board" are expected.
Do not guess the result while waiting. While you wait, say nothing, or at most one bridge of two or three words such as "let me think", said once. Never say "good question" or other filler praise.

When the backend's reply arrives, say it in natural spoken words. Keep every fact, example and question it contains, in the same order, and add nothing of your own. If it ends with a question for the learner, ask it and then listen.

Pronunciation: {PRONUNCIATION}

Keep listening while the learner pauses to think. Do not treat a cough, music or nearby conversation as a new request.
{terms}"""


def meeting_instructions(name: str, topic: str, key_terms: list[str]) -> str:
    """GPT-Live's prompt in a meeting: a participant that speaks only when named, and briefly."""
    terms = f"\nWords people in the room may use: {', '.join(key_terms)}.\n" if key_terms else ""
    return f"""You are {name}, a participant in an in-person meeting. The meeting is about: {topic}.
Several people are in the room. Most of what you hear is them talking to each other, not to you.

You are only the voice. A backend assistant holds the context and does all of the thinking. You never answer, explain or give facts from your own knowledge.

When to speak: only when someone addresses you by name ("{name}, ..."), or when the same exchange continues right after you answered: the same voice, with no one else's turn in between, asking a direct follow-up ("and what about ...") without repeating your name. A new question after other people have spoken needs your name again. Everything else is the room talking among themselves: stay completely silent.
Never greet. Never backchannel: no "mm-hmm", no "right", no listening sounds. Never comment on the discussion, summarise it or offer help unprompted.

Delegation policy:
Backend tools:
- Assistant: holds the context of this meeting and the work behind it; answers every question put to {name}.
Delegate to the backend when:
- Someone asks {name} a question or asks {name} to do something.
- Someone asks a follow-up to the answer you just gave.
Do not delegate to the backend when:
- People are talking to each other, even about you.
- Someone only acknowledges your answer ("thanks", "okay").
Delegate at once, and say nothing at all while you wait: no bridge, no filler. The people in the room may see a board where the assistant shows things, so "on the screen" is expected.

When the backend's reply arrives, say it to the person who asked, in natural spoken words and in a few sentences, adding nothing of your own. Then go silent again.

Pronunciation: {PRONUNCIATION}
{terms}"""


BACKEND_PROMPT = f"""You are the mind of a tutor in a live voice conversation. The learner wants to understand a topic by discussing it rather than reading about it.

# How this conversation works

A separate real-time voice model talks with the learner. It listens and handles interruptions, but it knows nothing about the topic. Whenever the learner says something that needs a real reply, it hands the conversation to you. You write what the tutor says next, and the voice model says it aloud, paraphrasing lightly.

You receive the conversation as a speech-to-text transcript. "Learner" lines are what the learner said and may contain recognition errors; read them charitably. "Tutor" lines are what the voice actually said, which includes your earlier replies in paraphrase and a few words of its own. The last Tutor line may have been cut off by an interruption.

# How you write

- Write only what a person would say out loud: plain sentences. No markdown, lists, headings, code, URLs, emoji or symbols such as arrows, slashes or asterisks.
- {PRONUNCIATION} Better still, write identifiers as the words themselves, for example external only.
- Keep turns short: usually one to four sentences, one idea at a time. Go longer only when the learner asks for a full explanation, and even then stop at a natural checkpoint.
- Sound like a person: contractions, natural rhythm, no filler openers like "Great question".

# How you teach

- Start from what they already know and build from there, with concrete examples and analogies, then name the real concept precisely.
- Check understanding now and then by asking them to predict, explain back or compare, but don't end every turn with a question.
- Follow their lead. Give a direct answer when they want one; go with tangents; if they seem lost, try another angle; if they're ahead, skip ahead.
- Correct misconceptions directly and kindly.

# What you know

- The briefing below is your source of truth for anything specific to their project, codebase or situation. Use general knowledge freely for general concepts.
- Never invent project specifics that aren't in the briefing. Say plainly that it isn't in what you were given, and offer to save it as a note.
- Say so when you're unsure.

# Markers

These are removed before anything is spoken.
- [[note: text]]: when they ask you to remember something, or a point is better followed up in writing, add a one-line note and say in a few words that you've noted it.
- [[end]]: when they clearly want to stop, give a two or three sentence spoken wrap-up of what they now understand, optionally one thing worth exploring next, and put [[end]] at the very end. Never end on your own initiative or because they paused.
- [[skip]]: if the hand-off was a mistake and the latest learner words need no reply at all, answer with only [[skip]].
"""


BOARD_PROMPT = """
# The board

The learner's page has a board beside the captions. Put something on it whenever seeing beats hearing: real code, a small diagram, a comparison. Board tags are never spoken, and the voice cannot read them out, so refer to what you show in plain words: "look at the code on the board, lines fifty one and fifty two".
- [[show code: <path relative to the code folder>:<first line>-<last line> | <short title>]] shows those exact lines, read from disk. Add "highlight <a>-<b>" before the bar to mark the lines that matter, e.g. [[show code: advisory/src/.../EDR.java:45-60 highlight 51-52 | EDR tasks per status]]. At most sixty lines. Only show a range you have actually read in this reply, so the line numbers are right.
- [[show diagram | <short title>]] then Mermaid source, then [[/show]]: a small diagram, at most ten nodes, e.g. a state diagram of proposal statuses.
- [[show table | <short title>]] then a markdown table, then [[/show]]: a small comparison.
Board bodies are the one place where Mermaid and markdown belong; everything outside the tags stays plain speech. Show at most one or two items per reply, and put the tag before the sentence that talks about it.

# Looking things up

You can read and search the code folder with Read, Grep and Glob. When the learner asks about something the briefing doesn't settle, look it up instead of guessing: start your reply with the lookup, never with an answer you haven't checked. What you read in the code counts as ground truth alongside the briefing. The learner sees "thinking" meanwhile and hears one short line, so don't announce the lookup yourself, and write no text at all between look-ups: anything you write is spoken at once, so do every look-up first and then answer. Keep searches targeted; the learner is waiting.
"""


def backend_session_block(topic: str, brief: str, code_dir: Path | None = None) -> str:
    block = f"# This session\n\nTopic: {topic}\n"
    if code_dir:
        block += BOARD_PROMPT + f"\nThe code folder is {code_dir}.\n"
    if brief.strip():
        block += f"\n<briefing>\n{brief.strip()}\n</briefing>\n"
    return block


def conversation_block(intro: str, conversation: str) -> str:
    """The conversation so far, for a new session's instructions: the rejoin path and the wake path."""
    return (f"\n{intro} The conversation so far, most recent last:\n"
            f"<conversation>\n{conversation[-6000:]}\n</conversation>\n")


def wake_block(heard: list[dict], wake: dict | None, meeting: bool = False) -> str:
    """What a woken session is told: the dormant transcript, and the words that woke it."""
    lines = "\n".join(f"Room: {s['text']}" for s in heard if s is not wake and s["text"].strip())
    block = conversation_block(MEETING_WAKE_INTRO if meeting else WAKE_INTRO, lines or "(nothing was heard)")
    said = ((wake or {}).get("text") or "").strip()[:500]  # its own cap: outside the transcript's 6000-char cut
    if said:
        block += (f'\nJust said, answer this: "{said}"\nThese words woke you. Do not greet. Hand them to the '
                  "backend at once, and say nothing until its reply arrives.\n")
    return block


GREETING = (
    "Greet the learner now in English, in one or two short sentences: say hello, name the topic "
    "({topic}), and ask what they already know about it or what made them curious. Then pause and listen."
)


# ---------------------------------------------------------------------------
# Transcript: group GPT-Live's transcript fragments into turns
# ---------------------------------------------------------------------------


def cost_usd_of(voice_seconds: float) -> float:
    """USD cost of `voice_seconds` of GPT-Live audio, rounded to cents for display."""
    return round(voice_seconds / 60 * LIVE_PRICE_PER_MIN, 2)


class SessionLog:
    """Groups transcript deltas into turns and writes transcript.md as they close."""

    SPEAKERS = {"input": "You", "output": "Tutor"}
    WHO = {"You": "you", "Tutor": "voice", "Room": "room"}  # a turn's `said` lines
    LABEL = {"You": "Learner", "Tutor": "Tutor", "Room": "Room"}  # the conversation as Claude reads it

    def __init__(self, out_dir: Path, topic: str, label: str):
        self.out_dir = out_dir
        self.transcript = out_dir / "transcript.md"
        self.started = time.time()
        self.turns: list[tuple[str, str]] = []
        self.pending = {"You": "", "Tutor": ""}
        self.last_arrival = {"You": 0.0, "Tutor": 0.0}
        self.last_learner_speech = time.time()
        self.notes: list[str] = []
        self.latencies: list[float] = []
        self.voice_seconds: float | None = None
        self.dormant_seconds: float = 0.0  # set from outside (LiveController) once the call ends
        self.sessions = 0  # GPT-Live sessions opened, and what the 15 s minimum adds to the short ones:
        self.floor_seconds = 0.0  # both set by close_books()
        self.unsaid: str | None = None  # a held reply no session said, set by hand_over_end()
        self.end_reason = "stopped"
        self.last_error = ""
        self.sent_upto = 0
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.transcript.write_text(f"# Voice discussion: {topic}\n\n_{stamp} · {label}_\n\n")

    def delta(self, kind: str, text: str) -> None:
        speaker = self.SPEAKERS[kind]
        other = "Tutor" if speaker == "You" else "You"
        now = time.time()
        # The other side has gone quiet and this side is saying something real: close its turn.
        if text.strip() and self.pending[other].strip() and now - self.last_arrival[other] > 0.8:
            self.flush(other)
        self.pending[speaker] += text
        self.last_arrival[speaker] = now
        if speaker == "You" and text.strip():
            self.last_learner_speech = now

    def flush_idle(self, idle: float = 2.0) -> None:
        now = time.time()
        for speaker in ("You", "Tutor"):
            if self.pending[speaker].strip() and now - self.last_arrival[speaker] > idle:
                self.flush(speaker)

    def flush(self, speaker: str) -> None:
        text = re.sub(r"\s+", " ", self.pending[speaker]).strip()
        self.pending[speaker] = ""
        if not text:
            return
        self.turns.append((speaker, text))
        with self.transcript.open("a") as f:
            f.write(f"**{speaker}:** {text}\n\n")
        say(f"{speaker.lower()}: {text}")

    def flush_all(self) -> None:
        order = sorted(("You", "Tutor"), key=lambda s: self.last_arrival[s])
        for speaker in order:
            self.flush(speaker)

    def conversation_text(self, labels: dict[str, str] | None = None) -> str:
        """The conversation so far, including turns still in progress, for Claude.

        `labels` overrides `LABEL` (e.g. a meeting's rejoin block, which reads Room / <name>
        rather than Learner / Tutor)."""
        labels = labels or self.LABEL
        lines = [f"{labels[s]}: {t}" for s, t in self.turns]
        order = sorted(("You", "Tutor"), key=lambda s: self.last_arrival[s])
        for speaker in order:
            text = re.sub(r"\s+", " ", self.pending[speaker]).strip()
            if text:
                lines.append(f"{labels[speaker]}: {text}")
        return "\n".join(lines) or "(nothing has been said yet)"

    def new_lines(self) -> list[dict]:
        """Closed turns not yet handed to the session, oldest first."""
        self.flush_all()
        fresh = self.turns[self.sent_upto:]
        self.sent_upto = len(self.turns)
        return [{"who": self.WHO[s], "text": t} for s, t in fresh]

    def heard(self, text: str) -> None:
        """A segment the local recognizer heard while the call was dormant: a closed turn of its own."""
        self.flush_all()
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        self.turns.append(("Room", text))
        with self.transcript.open("a") as f:
            f.write(f"**Room:** {text}\n\n")
        say(f"heard: {text}")

    def aside(self, text: str) -> None:
        """A line about the call itself, such as dropped audio, kept in the transcript in italics."""
        self.flush_all()
        with self.transcript.open("a") as f:
            f.write(f"_{text}_\n\n")
        say(f"ear: {text}")

    def add_note(self, note: str) -> None:
        self.notes.append(note.strip())
        say(f"note saved: {note.strip()}")

    def board_item(self, item: dict) -> None:
        self.flush_all()
        if item["kind"] == "code":
            body = "\n".join(item["lines"])
            head = f"`{item['path']}` lines {item['start']}-{item['start'] + len(item['lines']) - 1}"
            block = f"{head}\n\n```{item['lang']}\n{body}\n```"
        elif item["kind"] == "diagram":
            block = f"```mermaid\n{item['body']}\n```"
        else:
            block = item["body"]
        with self.transcript.open("a") as f:
            f.write(f"> **On the board: {item['title']}**\n\n{block}\n\n")
        say(f"board: {item['kind']} · {item['title']}")

    def full_reply(self, text: str, board_titles: list[str]) -> None:
        """Claude's reply as sent, since the Tutor lines are only GPT-Live's paraphrase and may be cut off."""
        self.flush_all()
        text = text.strip()
        if not text and not board_titles:
            return
        lines = ["> **Claude's full reply:**", ">"] + [f"> {line}".rstrip() for line in text.splitlines()]
        if board_titles:
            lines += [">", f"> _Shown on the board: {', '.join(board_titles)}_"]
        with self.transcript.open("a") as f:
            f.write("\n".join(lines) + "\n\n")

    def finish(self) -> dict:
        self.flush_all()
        if self.end_reason == "stopped" and self.last_error:
            self.end_reason = f"error: {self.last_error}"
        minutes = (time.time() - self.started) / 60
        median = statistics.median(self.latencies) if self.latencies else None
        voice_seconds = self.voice_seconds or 0.0
        billed_seconds = voice_seconds + self.floor_seconds  # every session counted at least 15 s
        cost_usd = cost_usd_of(billed_seconds)
        voice_minutes, voice_secs = int(voice_seconds // 60), int(voice_seconds % 60)
        floor = ""
        if self.floor_seconds >= 0.5:
            floor += f", billed as {int(billed_seconds // 60)}m {int(billed_seconds % 60)}s"
        if self.sessions:
            floor += (f" ({self.sessions} session{'s' if self.sessions != 1 else ''}, each billed at least "
                      f"{SESSION_FLOOR_S:g} s)")
        dormant_minutes = round(self.dormant_seconds / 60)
        with self.transcript.open("a") as f:
            if self.unsaid:
                cut = self.unsaid if len(self.unsaid) <= 200 else self.unsaid[:200].rstrip() + "…"
                f.write(f"_Reply not said: {cut}_\n\n")
            if self.notes:
                f.write("## Notes saved during the session\n\n")
                f.writelines(f"- {n}\n" for n in self.notes)
                f.write("\n")
            f.write(
                f"---\n_{minutes:.1f} min · {len(self.turns)} turns · ended: {self.end_reason}"
                + (f" · median hand-off to first reply {median:.2f}s" if median else "")
                + (f" · {voice_minutes}m {voice_secs}s GPT-Live{floor} · ${cost_usd:.2f} (estimate; real bill: "
                   f"{USAGE_URL})" if billed_seconds else "")
                + (f" · {dormant_minutes}m asleep (free)" if self.dormant_seconds >= 60 else "")
                + "_\n"
            )
        summary = {
            "transcript": str(self.transcript),
            "minutes": round(minutes, 1),
            "turns": len(self.turns),
            "notes": self.notes,
            "ended": self.end_reason,
            "median_latency_secs": round(median, 2) if median else None,
            "voice_seconds": self.voice_seconds,
            "sessions": self.sessions,
            "billed_seconds": round(billed_seconds, 1),
            "cost_usd": cost_usd,
            "usage_url": USAGE_URL,
            "reply_not_said": self.unsaid[:2000] if self.unsaid else None,
            "dormant_seconds": round(self.dormant_seconds, 1),
            "engine": "talk (gpt-live-1 + Claude)",
        }
        (self.out_dir / "session.json").write_text(json.dumps(summary, indent=2))
        return summary


# ---------------------------------------------------------------------------
# The brain: Claude, through the API (default) or the logged-in claude CLI
# ---------------------------------------------------------------------------


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

    def __init__(self, code_dir: Path | None, log: "SessionLog", on_add=None):
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


def thinking_params(model: str) -> dict:
    """Thinking off for latency where the model allows it; lowest effort where it doesn't."""
    if any(k in model for k in ("opus-5-5", "fable", "mythos")):
        return {"output_config": {"effort": "low"}}
    if "haiku" in model:
        return {}
    return {"thinking": {"type": "disabled"}}


class ApiBrain:
    """No tools and no code folder: board tags need the claude-code brain."""

    def __init__(self, model: str, system_blocks: list[dict]):
        from anthropic import AsyncAnthropic

        self.model = model
        self.system = system_blocks
        self.client = AsyncAnthropic()
        self.last_usage = None

    async def stream(self, user_text: str, on_tool=None):
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=1024,
            system=self.system,
            messages=[{"role": "user", "content": user_text}],
            **thinking_params(self.model),
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            self.last_usage = final.usage
            if final.stop_reason == "refusal":
                yield " I'd rather not go into that one."


class CliBrain:
    """One `claude -p` per hand-off, on the user's subscription."""

    def __init__(self, model: str, system_prompt: str, workdir: Path, code_dir: Path | None = None):
        self.model = model
        self.system_prompt = system_prompt
        self.workdir = workdir
        self.code_dir = code_dir
        self.last_usage = None

    def tool_flags(self) -> list[str]:
        if not self.code_dir:
            return ["--tools", ""]
        # Read-only look-ups in the code folder, nothing else.
        return ["--tools", "Read,Grep,Glob", "--allowedTools", "Read", "Grep", "Glob",
                "--add-dir", str(self.code_dir)]

    async def stream(self, user_text: str, on_tool=None):
        self.workdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        env["MAX_THINKING_TOKENS"] = "0"
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose",
            *self.tool_flags(), "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
            "--model", self.model, "--system-prompt", self.system_prompt,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, cwd=self.workdir, limit=1 << 24,
        )
        try:
            proc.stdin.write(user_text.encode())
            await proc.stdin.drain()
            proc.stdin.close()
            while line := await proc.stdout.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "stream_event":
                    inner = event["event"]
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta["text"]
                    elif inner.get("type") == "content_block_start" and on_tool \
                            and inner.get("content_block", {}).get("type") == "tool_use":
                        await on_tool(inner["content_block"].get("name", "tool"))
                elif event.get("type") == "result" and event.get("is_error"):
                    raise RuntimeError(str(event.get("result"))[:200])
            await proc.wait()
            if proc.returncode:
                err = (await proc.stderr.read()).decode(errors="replace").strip()[-200:]
                raise RuntimeError(f"claude CLI exited {proc.returncode}: {err}")
        finally:
            if proc.returncode is None:
                proc.kill()


def build_brain(args, topic: str, brief: str, out_dir: Path):
    session_block = backend_session_block(topic, brief, args.code if args.llm == "claude-code" else None)
    if args.llm == "api":
        # The briefing is the stable prefix, cached across every hand-off in the session.
        return ApiBrain(
            args.model,
            [
                {"type": "text", "text": BACKEND_PROMPT},
                {"type": "text", "text": session_block, "cache_control": {"type": "ephemeral"}},
            ],
        )
    return CliBrain(args.model, BACKEND_PROMPT + "\n" + session_block, out_dir / "claude-workdir", args.code)


def handoff_prompt(conversation: str) -> str:
    return (
        f"<conversation>\n{conversation}\n</conversation>\n\n"
        "The voice has just handed the conversation to you. Write what the tutor says next, "
        "replying to the learner's latest words."
    )


# ---------------------------------------------------------------------------
# The live session: create over HTTP, control over the sideband WebSocket
# ---------------------------------------------------------------------------


class LiveController:
    def __init__(self, args, topic: str, brief: str, log: SessionLog, brain, http):
        self.args = args
        self.topic = topic
        self.brief = brief
        self.log = log
        self.brain = brain
        self.http = http  # aiohttp.ClientSession
        self.key = os.environ.get("OPENAI_API_KEY", "")
        self.session_id: str | None = None
        self.ws = None
        self.send_lock = asyncio.Lock()
        self.counter = 0
        self.task: asyncio.Task | None = None  # current Claude hand-off
        self.closing = False
        self.greeted = False
        self.muted = False
        self.attached = asyncio.Event()
        self.done = asyncio.Event()
        self.last_output = 0.0
        # The last question put to the voice (a hand-off) or reply from the brain. A meeting's follow-up
        # window runs from this and the voice's own speech, never from the room talking among itself.
        self.last_exchange = 0.0
        self.output_text = ""  # everything the voice has said, to tell an answer from a filler said instead
        self.stage_cwd: str | None = None  # set by serve(); None in tests means "no stage"
        # stage.show makes blocking HTTP calls: they run on one worker thread, off the loop, and
        # one at a time, since each reads the stage's layout and writes it back.
        self.stage_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage")
        self.publishing: set[asyncio.Future] = set()
        self.board = Board(args.code, log, on_add=self.publish)
        self.thinking = False  # Claude is looking something up; the page shows it
        self.turns = TurnQueue() if args.llm == "session" else None
        self.activity: list[dict] = []
        self.owner_session: str | None = None
        self.last_activity = 0.0
        self.sessions = 0  # GPT-Live sessions this call has had; more than one after a rejoin
        self.delegations: set[str] = set()  # hand-offs of the current session
        self.stale_delegations: set[str] = set()  # hand-offs of sessions lost since
        self.lost = False  # the current session closed with connection_lost
        self.rejoin_until: float | None = None
        self.rejoin_task: asyncio.Task | None = None
        self.voice_base = 0.0  # GPT-Live audio seconds of earlier sessions
        self.voice_marked_at: float | None = None  # wall time log.voice_seconds last became current, while live
        self.limit_at: float | None = None
        self.dormant_accum = 0.0  # completed dormant stretches this call, seconds
        self.dormant_started: float | None = None  # the current dormant stretch's start, if one is open
        # Dormancy: while nobody talks there is no GPT-Live session, and the page's audio goes to a
        # recognizer on this machine instead (the ear). A meeting starts that way.
        self.state = "dormant" if args.mode == "meeting" else "live"  # live | dormant | waking
        if self.state == "dormant":
            self.enter_dormant()
        self.ear = None  # an ear.Ear, set by serve() when dormancy is on
        self.ear_ws = None  # the page's open /api/ear socket
        self.ear_seen = False  # the page has streamed to /api/ear at least once
        self.heard_since: list[dict] = []  # segments since the last live session, for the next one
        self.heard_recent: list[str] = []  # the last few, for the page
        self.wake_segment: dict | None = None  # what woke the call, until a session opens with it
        self.woke_with: dict | None = None  # the same, handed to greet() of the session it opened
        self.sleeping_ws = None  # the ws sleep() is closing; set until rest() sees it gone
        self.rested = asyncio.Event()  # set when a session closed by sleep() is gone
        self.dormant_task: asyncio.Task | None = None
        self.away_task: asyncio.Task | None = None
        self.closed_ids: set[str] = set()  # sessions GPT-Live confirmed closed (session.closed)
        self.closes: set[asyncio.Task] = set()  # discard()s in flight, which the shutdown waits for
        self.creates: set[asyncio.Task] = set()  # create()s in flight, which the shutdown waits for too
        self.start_timeout = START_TIMEOUT_S
        self.wake_handoff_s = WAKE_HANDOFF_S
        self.handoff_idle_s = HANDOFF_IDLE_S
        self.start_task: asyncio.Task | None = None
        self.failed_starts = 0  # sessions closed because they never started; the page drops its peer
        self.wake_failures = 0  # the page's wake-failed reports, to catch one that raced a create
        # Caps on paid live time: per call (--max-live-minutes) and per day (--daily-live-minutes, the ledger).
        self.opened = 0  # GPT-Live sessions created, discarded ones included: each is billed at least 15 s
        self.ledgered: set[str] = set()  # sessions written to the ledger
        self.ledgered_seconds = 0.0  # what those lines add up to, each at least 15 s
        self.floor_topup = 0.0  # what the 15 s minimum added to the written sessions shorter than it
        self.capped: str | None = None  # a cap was reached: the page shows this, and wakes are refused
        self.capping = False
        self.capped_daily = False  # the cap is the daily one only, which lifts at midnight
        self.capped_day = ""
        self.cap_speech_wait = 3.0  # the cap line's first words, before the wait for a pause
        self.call_name = log.out_dir.name
        self.held_reply: str | None = None  # an answer that arrived while no session could say it
        # One automatic wake per held reply: a session that then fails (never starts, or the page cannot use
        # it) leaves the reply for a wake the user starts, never another paid session on its own.
        self.held_autowoke = False
        # A wrap-up (reply --end) that arrived while waking or connecting: the session on its way says it and
        # hangs up. It belongs to that wake only: if the wake fails, or the user wakes the call with new words,
        # it is dropped (it is in the transcript already), so a later session never says goodbye to a question.
        self.held_goodbye: str | None = None

    @property
    def meeting(self) -> bool:
        return self.args.mode == "meeting"

    @property
    def asker(self) -> str:
        """Whom the voice's spoken lines address: a room has no learner."""
        return "the person who asked" if self.meeting else "the learner"

    @property
    def session_live(self) -> bool:
        return self.ws is not None and not self.ws.closed

    @property
    def rejoinable(self) -> bool:
        return self.rejoin_until is not None and not self.done.is_set()

    @property
    def call_over(self) -> bool:
        return self.done.is_set() or self.closing or bool(self.turns and self.turns.ended)

    @property
    def never_started(self) -> bool:
        """Nobody pressed Start: no session yet, and no local listening either (a meeting starts that way)."""
        return not self.sessions and not self.ear_seen

    def publish(self, item: dict) -> None:
        """Put a board item on the stage. A failure is reported like any other board problem.

        Returns at once when a loop is running: the show runs on the stage thread, and
        `stage_settled` lets a reply wait for it so its failure reaches that reply."""
        if not self.stage_cwd:
            return
        name, source, title = stage_view(item)
        cwd = self.stage_cwd

        def show() -> None:
            stage_mod.show(cwd, name, source, title=title)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop (a direct call): nothing to block
            try:
                show()
            except Exception as err:  # the call goes on without the visual
                self.board.problem(f"not shown on the stage: {err}")
            return
        fut = loop.run_in_executor(self.stage_pool, show)
        self.publishing.add(fut)
        fut.add_done_callback(self._published)

    def _published(self, fut: asyncio.Future) -> None:
        self.publishing.discard(fut)
        if not fut.cancelled() and fut.exception() is not None:  # the call goes on without the visual
            self.board.problem(f"not shown on the stage: {fut.exception()}")

    async def stage_settled(self, timeout: float = STAGE_SETTLE_S) -> None:
        """Wait (bounded) for the stage shows in flight, so their problems reach the reply that
        drew them. One still running after `timeout` reports later, in the terminal only."""
        pending = set(self.publishing)
        if pending:
            # Done-callbacks run before this wakes: they were registered first.
            await asyncio.wait(pending, timeout=timeout)

    # -- session creation (called by the page's POST /api/session) --------

    def session_config(self) -> dict:
        terms = read_key_terms(self.brief)
        meeting = self.args.mode == "meeting"
        if meeting:
            instructions = meeting_instructions(self.args.name, self.topic, terms)
        else:
            instructions = frontend_instructions(self.topic, terms)
        if self.state != "live":
            instructions += wake_block(self.heard_since, self.wake_segment, meeting)
        elif self.sessions:
            labels = {"You": "Room", "Tutor": self.args.name} if meeting else None
            instructions += conversation_block(REJOIN_INTRO, self.log.conversation_text(labels))
        return {
            "model": LIVE_MODEL,
            "instructions": instructions,
            "audio": {"output": {"voice": self.args.voice}},
            "delegation": {"type": "client"},
        }

    async def create(self, sdp: str) -> tuple[int, dict]:
        me = asyncio.current_task()
        if me is not None:
            self.creates.add(me)
        try:
            return await self.open_session(sdp)
        finally:
            self.creates.discard(me)

    async def open_session(self, sdp: str) -> tuple[int, dict]:
        woken = self.state != "live"  # a wake, or "Wake now" pressed while dormant
        wake_failures = self.wake_failures
        self.refresh_cap()
        if cap := self.cap_reached():  # refused before OpenAI is asked: nothing is billed
            self.set_cap(cap)
            say(f"refused a new GPT-Live session: {cap}")
            if woken:
                self.state = "dormant"
                self.enter_dormant()
            return 429, {"error": cap}
        import aiohttp

        def failed(status: int, error: str, detail: str) -> tuple[int, dict]:
            self.log.last_error = detail[:300]  # OpenAI's own words, for the transcript and the terminal
            say(f"error: {self.log.last_error}")
            if woken:
                self.state = "dormant"  # still listening; the wake segment waits for the next attempt
                self.enter_dormant()
            return status, {"error": error}

        timed_out = (504, f"OpenAI did not answer the session create within {CREATE_TIMEOUT_S:g} s; try again.",
                     f"session create timed out after {CREATE_TIMEOUT_S:g} s")
        # The POST runs as its own task: OpenAI may still create the session after the page has been told
        # it failed, and a session that arrives then must be closed, since it bills from its create.
        post = asyncio.ensure_future(self.post_session(
            {"session": self.session_config(), "transport": {"type": "webrtc", "sdp": sdp}}))
        done, _ = await asyncio.wait({post}, timeout=CREATE_TIMEOUT_S)
        if not done:
            self.track_close(self.close_late_session(post))
            return failed(*timed_out)
        try:
            status, raw = post.result()
        except asyncio.TimeoutError:
            return failed(*timed_out)
        except aiohttp.ClientError as err:
            return failed(502, f"Could not reach OpenAI: {err}", f"session create: {err}")
        body = parse_create_body(raw)
        if status < 300:
            self.opened += 1  # billed from here, whatever happens to it next
        if status >= 300:
            err = (body.get("error") or {}) if isinstance(body, dict) else {}
            err = err if isinstance(err, dict) else {"message": str(err)}
            detail = ": ".join(str(x) for x in (err.get("code"), err.get("message")) if x) or str(body)
            return failed(status, create_error_message(status, body), f"session create HTTP {status}: {detail}")
        if not isinstance(body, dict) or not isinstance(body.get("session"), dict) or "id" not in body["session"]:
            return failed(502, "OpenAI sent an answer the call cannot read; try again.",
                          f"session create HTTP {status}: unreadable answer {str(body)[:200]}")
        if self.call_over:  # the call ended (End, the time limit) while this POST was in flight
            self.record_session(body["session"]["id"], 0.0)
            await self.discard(body["session"]["id"])
            return 410, {"error": "the call ended while the voice was connecting"}
        if self.wake_failures != wake_failures:  # the page gave up on this wake while the POST was in flight
            self.record_session(body["session"]["id"], 0.0)
            await self.discard(body["session"]["id"], why="arrived after the page gave up on the wake")
            return 410, {"error": "the page gave up on this wake while the voice was connecting"}
        self.session_id = body["session"]["id"]
        self.sessions += 1
        self.rejoin_until = None
        if self.rejoin_task:
            self.rejoin_task.cancel()
        if woken:
            self.woke_with = self.wake_segment or {}
            self.wake_segment = None
            self.heard_since = []
        self.exit_dormant()  # a no-op if wake() already closed the stretch; closes it if "Wake now" skipped wake()
        self.state = "live"
        self.voice_marked_at = time.time()
        say(f"GPT-Live session {self.session_id} created; attaching sideband")
        asyncio.create_task(self.run_sideband())
        self.start_task = asyncio.create_task(self.watch_start(self.session_id))
        return 201, body

    async def post_session(self, payload: dict) -> tuple[int, str]:
        import aiohttp
        async with self.http.post(
            f"{OPENAI_API}/live/sessions",
            headers={"Authorization": f"Bearer {self.key}"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=CREATE_CEILING_S, sock_connect=15),
        ) as resp:
            return resp.status, await resp.text()

    async def close_late_session(self, post: asyncio.Future) -> None:
        """A create the page gave up on: if OpenAI does create the session, count it and close it."""
        try:
            status, raw = await post
        except Exception:  # timed out at the ceiling, or the network: no session id to close
            return
        body = parse_create_body(raw)
        if status < 300 and isinstance(body, dict) and isinstance(body.get("session"), dict) \
                and "id" in body["session"]:
            self.opened += 1
            self.record_session(body["session"]["id"], 0.0)
            await self.discard(body["session"]["id"], why="arrived after its create timed out")

    async def watch_start(self, session_id: str) -> None:
        """A session bills from its create, audio or not: one that never starts must not stay open."""
        await asyncio.sleep(self.start_timeout)
        if not self.greeted and self.session_id == session_id and not self.call_over:
            await self.abandon_start(f"did not start within {self.start_timeout:g} s")

    async def abandon_start(self, why: str, wait: float = 5) -> None:
        """Close a session that never started, and put the call back where it was before create():
        dormant when it can listen locally, else a lost connection the page may rejoin. The wake words
        are not retried on their own: every attempt is billed at least 15 s."""
        session_id = self.session_id
        self.failed_starts += 1
        self.woke_with = None
        self.drop_goodbye("the session it was for never started")
        say(f"GPT-Live session {session_id} {why}; closing it")
        if self.args.dormant_after > 0:
            self.state = "dormant"  # first: the sideband's end then rests instead of ending the call
            self.rested = asyncio.Event()
            self.sleeping_ws = self.ws
        else:
            self.lost = True  # the sideband's end opens the rejoin window
        if not self.session_live:  # the sideband is not attached: close the session over one of its own
            self.close_later(session_id, "never attached")
            return
        ws = self.ws
        await self.send({"type": "session.close", "event_id": self.next_id("close")})
        deadline = time.time() + wait
        while self.session_id == session_id and time.time() < deadline:
            await asyncio.sleep(0.1)
        if self.session_id == session_id:
            await ws.close()  # the sideband's end re-attaches to close it, since no session.closed came

    def close_later(self, session_id: str, why: str) -> None:
        """discard() in the background; serve() waits for it before it closes the HTTP client."""
        self.track_close(self.discard(session_id, why=why))

    def track_close(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self.closes.add(task)
        task.add_done_callback(self.closes.discard)

    async def settle_closes(self, timeout: float = 8) -> None:
        """Wait for the closes in flight and the creates in flight, and for any close a create starts."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            pending = {t for t in self.closes | self.creates if not t.done() and t is not asyncio.current_task()}
            left = deadline - loop.time()
            if not pending or left <= 0:
                return
            await asyncio.wait(pending, timeout=left)

    async def wind_down(self, timeout: float = CREATE_CEILING_S + 10, hurry: asyncio.Event | None = None) -> None:
        """At the end of the call: write the open session's ledger line first (the wait below can be long, or
        cut short), settle every session still being created or closed, then close the books, so a session
        that arrived late is in the footer and the ledger too. `hurry` (a second signal) ends the wait."""
        if self.session_id and self.session_id not in self.ledgered:
            self.settle_session()
        waits = {asyncio.ensure_future(self.settle_closes(timeout))}
        if hurry is not None:
            waits.add(asyncio.ensure_future(hurry.wait()))
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        for task in waits:
            task.cancel()
        if hurry is not None and hurry.is_set() and any(not t.done() for t in self.closes | self.creates):
            say("stopping without waiting for GPT-Live sessions still being created or closed; "
                f"check {USAGE_URL}")
        self.close_books()

    async def discard(self, session_id: str, wait: float = 5, why: str = "arrived after the call ended") -> None:
        """Close a session nobody will use, over its own sideband, without attaching it to the call."""
        say(f"GPT-Live session {session_id} {why}; closing it")
        url = f"{OPENAI_API.replace('https://', 'wss://')}/live/sessions/{session_id}/attach"
        try:
            async with self.http.ws_connect(url, headers={"Authorization": f"Bearer {self.key}"},
                                            max_msg_size=0) as ws:
                await ws.send_str(json.dumps({"type": "session.close", "event_id": self.next_id("close")}))

                async def closed() -> None:
                    async for msg in ws:
                        if msg.type.name == "TEXT" and json.loads(msg.data).get("type") == "session.closed":
                            return

                try:
                    await asyncio.wait_for(closed(), timeout=wait)
                except asyncio.TimeoutError:
                    pass  # leaving the block closes the sideband all the same
        except Exception as err:  # network, auth: say so, since this session may still be billed
            say(f"error: could not close GPT-Live session {session_id}: {err}")

    # -- sideband -----------------------------------------------------------

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"

    async def send(self, event: dict) -> None:
        if not self.ws or self.ws.closed:
            return
        async with self.send_lock:
            await self.ws.send_str(json.dumps(event))

    async def append(self, kind: str, content: str, delegation_id: str | None = None) -> None:
        await self.send({
            "type": f"session.{kind}.append",
            "event_id": self.next_id(kind),
            "delegation_id": delegation_id,
            "content": content,
        })

    async def run_sideband(self) -> None:
        session_id = self.session_id
        url = f"{OPENAI_API.replace('https://', 'wss://')}/live/sessions/{session_id}/attach"
        try:
            async with self.http.ws_connect(
                url, headers={"Authorization": f"Bearer {self.key}"}, heartbeat=20, max_msg_size=0
            ) as ws:
                self.ws = ws
                self.attached.set()
                ticker = asyncio.create_task(self.tick())
                try:
                    async for msg in ws:
                        if msg.type.name == "TEXT":
                            await self.on_event(json.loads(msg.data))
                        elif msg.type.name in ("CLOSED", "ERROR"):
                            break
                finally:
                    ticker.cancel()
        except Exception as err:  # network, auth
            self.log.last_error = f"sideband: {err}"[:200]
            say(f"error: {self.log.last_error}")
        finally:
            self.sideband_ended(session_id)

    def sideband_ended(self, session_id: str | None = None) -> None:
        # Closing the sideband does not end a GPT-Live session, which bills while open: unless GPT-Live
        # confirmed the close, attach once more and ask it to close.
        session_id = session_id or self.session_id
        if session_id and session_id not in self.closed_ids:
            self.close_later(session_id, "ended its sideband without confirming a close")
        if self.state == "dormant" and not self.closing and not self.done.is_set():
            self.rest()
            return
        if self.lost and not self.closing and not self.done.is_set():
            self.open_rejoin_window()
            return
        if self.log.end_reason == "stopped" and not self.log.last_error:
            self.log.end_reason = "connection closed"
        self.settle_session()
        self.done.set()

    def forget_session(self) -> None:
        """The GPT-Live session is gone but the call is not: after a dropped connection, and after sleep()."""
        self.settle_session()
        self.session_id, self.ws = None, None
        self.attached = asyncio.Event()
        self.greeted = False
        self.thinking = False
        self.stale_delegations |= self.delegations
        self.delegations = set()
        if self.task and not self.task.done():
            self.task.cancel()
        self.log.flush_all()

    def open_rejoin_window(self) -> None:
        """The connection dropped: forget the session, keep the call, and let the page start a new session."""
        self.lost = False
        self.forget_session()
        self.rejoin_until = time.time() + REJOIN_SECONDS
        self.rejoin_task = asyncio.create_task(self.end_unless_rejoined())
        say(f"GPT-Live connection lost; the page may rejoin within {REJOIN_SECONDS} s")

    async def end_unless_rejoined(self) -> None:
        await asyncio.sleep(REJOIN_SECONDS)
        if not self.session_id and not self.done.is_set():
            if self.log.end_reason == "stopped":
                self.log.end_reason = "connection lost"
            say("nobody rejoined the call; ending it")
            self.rejoin_until = None
            self.done.set()

    # -- dormancy: sleep when quiet, wake on what the ear hears ------------------

    def should_sleep(self, now: float) -> bool:
        """Quiet for --dormant-after seconds: nobody spoke, the voice said nothing, no turn waits on the
        brain and the brain is not working. In a meeting, "nobody spoke" means nobody spoke to the voice:
        the room keeps talking among itself, so the window runs from the voice's last words and the last
        question or reply, and room speech alone never keeps a paid session open."""
        if self.args.dormant_after <= 0 or self.state != "live" or not self.greeted or self.call_over:
            return False
        if self.thinking or (self.task is not None and not self.task.done()):
            return False
        if self.turns and (self.turns.pending or self.turns.working
                            or any(not self.turns.known(d) for d in self.delegations)) \
                and not self.brain_absent():
            return False  # a delegation just created is still 0.35 s from becoming a turn
        if self.muted:
            return now - self.last_output >= MUTED_SLEEP_S
        if self.args.mode == "meeting":
            since = max(self.last_output, self.last_exchange)
        else:
            since = max(self.log.last_learner_speech, self.last_output)
        return now - since >= self.args.dormant_after

    def brain_absent(self) -> bool:
        """A turn nobody collects: the offline alert has fired, or it has waited past --idle-minutes. Or a
        turn collected and then abandoned (a crash, Esc, a permission prompt): no status, reply or tool call
        for WORK_SILENT_S. It then stops holding the session open, so the call sleeps (free) instead of
        staying live, and billed, until --max-minutes. The turn stays queued for a brain that comes back."""
        if not self.turns:
            return False
        if self.turns.working:
            now = self.turns.clock()
            if any(a["state"] == "running" and now - a["started"] < RUNNING_TOOL_MAX_S for a in self.activity):
                return False  # one long tool call: the brain is there, just busy
            last = max(self.turns.delivered_at, self.turns.last_activity, self.turns.replied_at)
            return now - last > (WORK_SILENT_AFTER_STATUS_S if self.turns.replied else WORK_SILENT_S)
        if not self.turns.pending:
            return False
        return ("offline" in self.turns.alerted
                or self.turns.clock() - self.turns.offered_at > self.args.idle_minutes * 60)

    def idle_expired(self, now: float) -> bool:
        """The --idle-minutes end, which only applies without dormancy: a dormant call costs nothing."""
        if self.args.dormant_after > 0 or (self.turns and self.turns.working and not self.brain_absent()):
            return False
        return now - self.log.last_learner_speech > self.args.idle_minutes * 60

    async def sleep(self, wait: float = 10) -> None:
        """Close the GPT-Live session because nobody is talking. Not a dropped connection, not the end."""
        if self.state != "live" or not self.session_live or self.call_over:
            return
        self.state = "dormant"  # first: the session.closed that follows must see it
        self.heard_since = []  # cleared here, not in rest(): a segment heard during the wait must survive it
        self.rested = asyncio.Event()
        ws = self.ws
        self.sleeping_ws = ws  # marks whose close this is; a wake before it arrives is deferred to rest()
        say("muted: closing the GPT-Live session" if self.muted
            else f"quiet for {self.args.dormant_after} s: closing the GPT-Live session, listening on this machine")
        await self.send({"type": "session.close", "event_id": self.next_id("close")})
        try:
            await asyncio.wait_for(self.rested.wait(), timeout=wait)
        except asyncio.TimeoutError:
            # The page sees the dormant state in its poll and drops its WebRTC peer itself.
            say(f"GPT-Live did not confirm the close within {wait:g} s: closing the sideband")
            await ws.close()  # the sideband's end then calls rest()

    def rest(self) -> None:
        """The session sleep() closed is gone: the call is dormant. Apply a wake that arrived while it closed."""
        self.sleeping_ws = None
        self.forget_session()
        self.lost = False
        self.rested.set()
        self.enter_dormant()
        self.start_dormant_watch()
        if self.wake_segment is not None:
            self.wake(self.wake_segment)
        elif self.held_reply:
            self.wake_for_held_reply()

    def wake_for_held_reply(self) -> bool:
        """The one automatic wake a held reply may have."""
        if self.held_autowoke or self.state != "dormant" or self.sleeping_ws is not None:
            return False
        if self.wake():
            self.held_autowoke = True
            return True
        return False

    # -- cost: what is billed is GPT-Live seconds only; dormant listening is local and free ------

    def enter_dormant(self) -> None:
        """Start counting a dormant stretch, if one is not already open (rest(), or a meeting's start)."""
        if self.dormant_started is None:
            self.dormant_started = time.time()

    def exit_dormant(self) -> None:
        """Close the current dormant stretch into the running total, when wake() moves the state on."""
        if self.dormant_started is not None:
            self.dormant_accum += time.time() - self.dormant_started
            self.dormant_started = None

    def dormant_seconds_total(self) -> float:
        """Completed dormant stretches plus the one still open, if the call is dormant right now."""
        total = self.dormant_accum
        if self.dormant_started is not None:
            total += time.time() - self.dormant_started
        return total

    def voice_estimate(self) -> float:
        """What voice_seconds is right now: the last reported total, plus the seconds the current
        session has been open since that report. It runs until the session is gone (session.closed, or
        its sideband's end), not just while live: a session sleep() is closing still bills."""
        base = self.log.voice_seconds if self.log.voice_seconds is not None else self.voice_base
        if self.session_id and self.voice_marked_at is not None:
            return base + (time.time() - self.voice_marked_at)
        return base

    def settle_session(self) -> None:
        """The current session is over: stop its clock, fold it into the total and write its ledger line."""
        total = self.voice_estimate()
        if self.voice_marked_at is not None or self.log.voice_seconds is not None:
            self.log.voice_seconds = total
        seconds = max(0.0, total - self.voice_base)
        self.voice_base, self.voice_marked_at = total, None
        if self.session_id:
            self.record_session(self.session_id, seconds)

    def close_books(self) -> None:
        """At the end of the call: a session still open is written to the ledger too, and the transcript's
        footer gets the live estimate (never below the last report) and the 15 s minimum of every session."""
        if self.session_id and self.session_id not in self.ledgered:
            self.settle_session()
        estimate = self.voice_estimate()
        if estimate or self.log.voice_seconds is not None:
            self.log.voice_seconds = max(self.log.voice_seconds or 0.0, estimate)
        self.log.sessions, self.log.floor_seconds = self.opened, self.floor_topup

    def record_session(self, session_id: str, seconds: float) -> None:
        if session_id in self.ledgered:
            return
        self.ledgered.add(session_id)
        billed = max(seconds, SESSION_FLOOR_S)
        floor = billed - seconds
        self.ledgered_seconds += billed
        self.floor_topup += floor
        now = dt.datetime.now()
        ledger_append({"date": now.date().isoformat(), "time": now.strftime("%H:%M:%S"), "call": self.call_name,
                       "session": session_id, "seconds": round(seconds, 1), "floor_seconds": round(floor, 1),
                       "usd": cost_usd_of(billed)})

    def billed_seconds(self) -> float:
        """This call's paid live time: the voice estimate, with every session counted at least 15 s
        (the open one included)."""
        total = self.voice_estimate()
        billed = total + self.floor_topup
        if self.session_id and self.session_id not in self.ledgered:
            billed += max(0.0, SESSION_FLOOR_S - (total - self.voice_base))
        return billed

    def unledgered_seconds(self) -> float:
        return max(0.0, self.billed_seconds() - self.ledgered_seconds)

    def today_seconds(self) -> float:
        """Today's paid live time on this machine: the ledger plus what this call has not written yet."""
        return ledger_today_seconds() + self.unledgered_seconds()

    def cap_reached(self) -> str | None:
        if self.billed_seconds() >= self.args.max_live_minutes * 60:
            return call_cap_message(self.args.max_live_minutes)
        if self.today_seconds() >= self.args.daily_live_minutes * 60:
            return daily_cap_message(self.args.daily_live_minutes)
        return None

    def set_cap(self, cap: str) -> None:
        self.capped = cap
        self.capped_daily = cap.startswith("Daily")
        self.capped_day = dt.date.today().isoformat()

    def refresh_cap(self) -> str | None:
        """The cap in force: a daily cap set on an earlier day is lifted, unless a cap is still reached."""
        if self.capped and self.capped_daily and self.capped_day != dt.date.today().isoformat():
            self.capped, self.capping, self.capped_daily = None, False, False
            if cap := self.cap_reached():
                self.set_cap(cap)
            else:
                say("a new day: the daily live-minute cap no longer applies")
        return self.capped

    async def reach_live_cap(self, cap: str) -> None:
        """A cap reached while live: one short line (none in a meeting), then dormant; wakes are refused
        from now on and local listening carries on for free. Without dormancy the call ends."""
        self.set_cap(cap)
        self.capping = True
        say(f"{cap}: closing the GPT-Live session")
        if not self.meeting and self.greeted:
            await self.append("instructions", LIVE_CAP_LINE)
        if self.args.dormant_after <= 0:
            which = (f"{self.args.max_live_minutes:g} min" if cap.startswith("Live-minute")
                     else f"{self.args.daily_live_minutes:g} min daily")
            self.log.end_reason = f"reached the {which} live-minute cap"
            asyncio.create_task(self.close_after_speech())
            return
        asyncio.create_task(self.sleep_after_speech())

    async def sleep_after_speech(self, max_wait: float = 15) -> None:
        await asyncio.sleep(self.cap_speech_wait)
        deadline = time.time() + max_wait
        while time.time() < deadline and time.time() - self.last_output < 2.5:
            await asyncio.sleep(0.5)
        await self.sleep()

    def cost_view(self) -> dict:
        """{"voice_seconds", "dormant_seconds", "cost_usd", "today_usd"}, for the page and /api/state.
        voice_seconds is the billed estimate: the live estimate, every session counted at least 15 s."""
        voice_seconds = self.billed_seconds()
        return {
            "voice_seconds": voice_seconds,
            "dormant_seconds": self.dormant_seconds_total(),
            "cost_usd": cost_usd_of(voice_seconds),
            "today_usd": cost_usd_of(self.today_seconds()),
        }

    def start_dormant_watch(self) -> None:
        if self.dormant_task is None or self.dormant_task.done():
            self.dormant_task = asyncio.create_task(self.dormant_watch())

    async def dormant_watch(self, every: float = 1.0) -> None:
        """No session means no tick(): this keeps the call's time limit while it is dormant or waking."""
        self.limit_at = self.limit_at or time.time() + self.args.max_minutes * 60
        while self.state != "live" and not self.done.is_set():
            if time.time() > self.limit_at:
                self.log.end_reason = f"reached the {self.args.max_minutes} min limit"
                say("time limit reached while dormant; ending the call")
                self.done.set()
                return
            await asyncio.sleep(every)

    def ear_opened(self, ws) -> None:
        """The page started streaming to the ear. The newest socket wins: a reload or a second tab
        must not interleave two streams in one segmenter."""
        old, self.ear_ws, self.ear_seen = self.ear_ws, ws, True
        if old is not None and not old.closed:  # 4001 tells that page not to reconnect
            asyncio.get_running_loop().create_task(old.close(code=EAR_REPLACED, message=b"replaced by a newer page"))
        if self.away_task:
            self.away_task.cancel()
            self.away_task = None
        self.ear.begin()
        self.start_dormant_watch()

    def ear_closed(self, ws) -> None:
        """A page stopped streaming. Unless the call went live, give the page the rejoin window to come back."""
        if ws is not self.ear_ws:
            return  # a socket already replaced by a newer one
        self.ear_ws = None
        self.ear.end()
        if self.state != "live" and not self.call_over:
            self.away_task = asyncio.create_task(self.end_unless_back(self.sessions))

    async def end_unless_back(self, sessions: int) -> None:
        await asyncio.sleep(REJOIN_SECONDS)
        if self.ear_ws is None and self.sessions == sessions and not self.done.is_set():
            if self.log.end_reason == "stopped":
                self.log.end_reason = "page closed while dormant"
            say("the page stopped listening and did not come back; ending the call")
            self.done.set()

    def wake_names(self) -> list[str]:
        extra = [s.strip() for s in (self.args.sounds_like or "").split(",")]
        return [self.args.name] + [s for s in extra if s]

    def hear(self, segment: dict) -> None:
        """A segment from the ear: kept for the transcript and the next session, and a wake when it qualifies."""
        if self.call_over:
            return
        text = segment["text"].strip()
        if text:
            if self.state != "live":  # the ear finishing its queue after a wake belongs to the log only
                self.heard_since.append(segment)
            self.heard_recent = (self.heard_recent + [text])[-5:]
            self.log.heard(text)
        if self.state == "dormant" and ear_mod.wakes(segment, self.args.wake, self.wake_names()):
            self.wake(segment)

    def wake(self, segment: dict | None = None) -> bool:
        """Dormant to waking: the page is told to open a session, seeded with what the ear heard."""
        self.refresh_cap()
        if self.call_over or self.capped:  # a cap refuses every wake; local listening carries on
            return False
        if segment is not None:
            self.wake_segment = segment
            if (segment.get("text") or "").strip():
                self.drop_goodbye("the user woke the call with new words")
        if self.sleeping_ws is not None:
            return False  # sleep()'s session is still closing; rest() retries this once it is gone
        if self.state != "dormant":
            return False
        self.exit_dormant()
        self.state = "waking"
        say(f"waking: {(segment or {}).get('text') or 'on request'}")
        self.tell_page({"state": "waking"})
        return True

    def wake_failed(self, reason: str) -> bool:
        """The page could not start the session a wake asked for (no microphone, WebRTC) before its POST:
        back to dormant, so the page's poll stops retrying. The wake words wait for the next attempt.
        After its POST (a session exists, never started), the session is useless and billed: close it."""
        self.wake_failures += 1
        if not self.greeted:
            self.drop_goodbye("the wake it was for failed")
        if self.session_id and not self.greeted and self.state == "live" and not self.call_over:
            asyncio.get_running_loop().create_task(self.abandon_start(f"cannot be used by the page ({reason[:200]})"))
            return False
        if self.state != "waking" or self.session_id or self.call_over:
            return False
        self.state = "dormant"
        self.enter_dormant()
        say(f"the page could not wake the voice ({reason[:200]}); listening again")
        return True

    def tell_page(self, message: dict) -> None:
        """Push to the page over its /api/ear socket: a background tab's poll can lag by a minute."""
        ws = self.ear_ws
        if ws is not None and not ws.closed:
            asyncio.get_running_loop().create_task(ws.send_str(json.dumps(message)))

    async def ensure_wake_handed_off(self, wait: float | None = None, after_speech: bool = False) -> None:
        """GPT-Live never heard the wake words itself and may not hand them off: if it has not within
        `wait`, offer them to the brain as a turn of the server's own, answered untied. After a held reply
        (`after_speech`), the voice first says that reply, so the wait starts once its output has gone quiet:
        an offer made while it is still speaking would be answered over it, and the words answered twice."""
        if after_speech:
            began = time.time()
            while not self.call_over and time.time() - began < HELD_SPEECH_MAX_S:
                spoke = self.last_output >= began
                if spoke and time.time() - self.last_output >= self.handoff_idle_s:
                    break
                if not spoke and time.time() - began >= 10:  # it never began: fall back to the plain wait
                    break
                await asyncio.sleep(0.1)
        await asyncio.sleep(self.wake_handoff_s if wait is None else wait)
        if self.delegations or not self.session_live or self.call_over:
            return
        turn_id = self.next_id("wake")
        self.stale_delegations.add(turn_id)  # no hand-off in this session to tie the answer to
        self.turns.offer(turn_id, self.log.new_lines())
        say("the voice did not hand off the wake words; offering them to the brain directly")

    async def greet(self) -> None:
        """Called when the page reports session.started, i.e. audio is flowing."""
        await self.attached.wait()
        if self.greeted:
            return
        self.greeted = True
        self.log.last_learner_speech = self.last_exchange = time.time()
        if self.held_reply or self.held_goodbye:  # an answer that came while the call slept: say it first
            goodbye = self.held_goodbye is not None
            reply = " ".join(r for r in (self.held_reply, self.held_goodbye) if r)
            self.held_reply, self.held_goodbye, self.held_autowoke = None, None, False
            said = ((self.woke_with or {}).get("text") or "").strip()[:500]
            self.woke_with = None
            # One instruction: a wake line appended after it ("say nothing") could cut the answer off.
            line = HELD_REPLY_LINE.format(asker=self.asker, reply=reply)
            await self.append("instructions", line + (HELD_THEN_WAKE.format(said=said) if said else ""))
            if said and self.turns:
                asyncio.create_task(self.ensure_wake_handed_off(after_speech=True))
            say("Back on the call to say an answer that arrived while it slept.")
            if goodbye:
                self.log.end_reason = "learner finished"
                asyncio.create_task(self.close_after_speech())
            return
        if self.woke_with is not None:
            meeting = self.args.mode == "meeting"
            said = (self.woke_with.get("text") or "").strip()
            self.woke_with = None
            if said:
                line = MEETING_WAKE_LINE if meeting else WAKE_LINE
                await self.append("instructions", line.format(said=said))
                if self.turns:
                    asyncio.create_task(self.ensure_wake_handed_off())
            else:
                await self.append("instructions", MEETING_WAKE_NOW_LINE if meeting else WAKE_NOW_LINE)
            say("Awake: GPT-Live is back on the call.")
            return
        if self.sessions > 1:
            await self.append("instructions", MEETING_REJOIN_LINE if self.meeting else REJOIN_LINE)
            say("Call resumed after a dropped connection.")
            return
        await self.append("instructions", GREETING.format(topic=self.topic))
        say(f"Session started: {self.topic}. Speak whenever you like; say you want to stop to end.")

    def usage_seconds(self, ev: dict) -> float | None:
        seconds = (ev.get("usage") or {}).get("seconds")
        return self.log.voice_seconds if seconds is None else self.voice_base + seconds

    def note_usage(self, ev: dict) -> None:
        """Adopt this report as the new voice_seconds, never lower than what was already showing."""
        reported = self.usage_seconds(ev)
        if reported is None:
            return
        self.log.voice_seconds = max(reported, self.voice_estimate())
        self.voice_marked_at = time.time()

    async def on_event(self, ev: dict) -> None:
        kind = ev.get("type", "")
        if (kind in ("session.input_transcript.delta", "session.output_transcript.delta", "session.usage.updated")
                and not self.greeted and self.state == "live" and self.sleeping_ws is None):
            asyncio.create_task(self.greet())  # audio is flowing, whether or not the page said so
        if kind == "session.input_transcript.delta":
            self.log.delta("input", ev.get("delta", ""))
        elif kind == "session.output_transcript.delta":
            self.log.delta("output", ev.get("delta", ""))
            self.last_output = time.time()
            self.output_text += ev.get("delta", "")
        elif kind == "session.delegation.created":
            delegation = ev.get("delegation", {})
            if delegation.get("target") == "client":
                self.last_exchange = time.time()
                self.delegations.add(delegation["id"])
                self.start_handoff(delegation["id"])
        elif kind == "session.usage.updated":
            self.note_usage(ev)
        elif kind == "session.closed":
            if self.session_id:
                self.closed_ids.add(self.session_id)
            self.note_usage(ev)
            self.voice_marked_at = None  # no longer billed: the estimate stops here
            reason = ev.get("reason", "closed")
            if self.state == "dormant":
                pass  # closed by sleep(): neither a dropped connection nor the end of the call
            elif reason == "connection_lost" and not self.closing:
                self.lost = True  # the sideband's end opens the rejoin window instead of ending the call
            elif self.log.end_reason == "stopped":
                self.log.end_reason = {
                    "remote_hangup": "browser hung up",
                    "connection_lost": "connection lost",
                    "expired": "GPT-Live session duration limit",
                    "content": "stopped by OpenAI safety filter",
                }.get(reason, reason)
            say(f"GPT-Live session closed ({reason})")
            if self.ws and (self.sleeping_ws is None or self.ws is self.sleeping_ws):
                await self.ws.close()  # never a newer session's ws, if one has already replaced it
        elif kind == "error":
            err = ev.get("error") or {}
            self.log.last_error = f"{err.get('code', '')}: {err.get('message', '')}"[:200]
            say(f"error: {self.log.last_error}")
        elif kind in ("info",) and self.args.verbose:
            say(f"info: {ev.get('message')}")
        elif self.args.verbose and not kind.endswith(("input_audio.append", "output_audio.delta")):
            say(f"(event {kind})")

    # -- hand-offs to Claude -------------------------------------------------

    def start_handoff(self, delegation_id: str) -> None:
        if self.turns:
            asyncio.create_task(self.enqueue_turn(delegation_id))
            return
        if self.task and not self.task.done():
            self.task.cancel()  # the learner moved on; the older request is superseded
        self.task = asyncio.create_task(self.handoff(delegation_id))

    async def enqueue_turn(self, turn_id: str) -> None:
        # The delegation event carries no text; let the learner's last words arrive first.
        await asyncio.sleep(0.35)
        self.turns.offer(turn_id, self.log.new_lines())

    def digest(self, parts: list[tuple[str, str]]) -> tuple[str, bool, bool]:
        """Board tags go to the board and notes to the log; returns (speech, end, skip)."""
        spoken, end, skip = "", False, False
        for kind, part in parts:
            if kind == "text":
                if not self.board.text(part):
                    spoken += part
                continue
            if self.board.marker(part):
                continue
            name, _, value = part.partition(":")
            name = name.strip().lower()
            if name == "note" and value.strip():
                self.log.add_note(value.strip())
            elif name == "end":
                end = True
            elif name == "skip":
                skip = True
        return spoken, end, skip

    def finish_digest(self, markers_filter: MarkerFilter) -> str:
        """The end of a reply: its held-back tail, and a diagram or table left open goes on the board."""
        spoken, _, _ = self.digest([("text", markers_filter.flush())])
        self.board.close_block()
        return spoken

    async def handoff(self, delegation_id: str) -> None:
        started = time.time()
        # The delegation event carries no text; let the learner's last words arrive first.
        await asyncio.sleep(0.35)
        prompt = handoff_prompt(self.log.conversation_text())
        markers_filter = MarkerFilter()
        pending, first_sent, end_requested, skipped = "", False, False, False
        announced, said, board_from = False, "", len(self.board.items)

        async def on_tool(name: str) -> None:
            nonlocal announced
            self.thinking = True
            if self.args.verbose:
                say(f"(claude is using {name})")
            if not announced and not first_sent:
                announced = True
                await self.append("commentary", "Let me check that in the code.", delegation_id)

        async def ship(text: str) -> None:
            nonlocal first_sent
            text = speakable(text)
            if not text:
                return
            await self.append("commentary", text, delegation_id)
            if self.args.verbose:
                say(f"(claude -> voice) {text}")
            if not first_sent:
                first_sent = True
                self.log.latencies.append(time.time() - started)
                if self.args.verbose:
                    say(f"(hand-off to first reply {time.time() - started:.2f}s)")

        try:
            async for chunk in self.brain.stream(prompt, on_tool=on_tool):
                self.thinking = False
                spoken, end, skip = self.digest(markers_filter.feed_ordered(chunk))
                end_requested |= end
                skipped |= skip
                pending += spoken
                said += spoken
                # Send the first sentence as soon as it's complete, then bigger pieces.
                threshold = 40 if not first_sent else 220
                cut = last_sentence_end(pending)
                if cut and cut >= threshold or len(pending) > 1200:
                    cut = cut or len(pending)
                    await ship(pending[:cut])
                    pending = pending[cut:]
            rest = self.finish_digest(markers_filter)
            pending += rest
            await ship(pending)
            self.log.full_reply(said + rest, [i["title"] for i in self.board.items[board_from:]])
            if skipped and not first_sent:
                await self.append("thinking", "No reply is needed to that. Keep listening.", delegation_id)
            if self.args.verbose and getattr(self.brain, "last_usage", None):
                u = self.brain.last_usage
                say(f"(claude usage: in {u.input_tokens}, cache read {u.cache_read_input_tokens}, "
                    f"cache write {u.cache_creation_input_tokens}, out {u.output_tokens})")
        except asyncio.CancelledError:
            self.thinking = False
            raise
        except Exception as err:
            self.thinking = False
            self.log.last_error = f"claude: {err}"[:200]
            say(f"error: {self.log.last_error}")
            await self.append(
                "instructions",
                f"The backend could not answer just now. Tell {self.asker} briefly that you lost your "
                "train of thought and ask them to say that again.",
                delegation_id,
            )
            return
        if end_requested:
            self.log.end_reason = "learner finished"
            asyncio.create_task(self.close_after_speech())

    async def voice_say(self, text: str, turn_id: str | None) -> None:
        # An answer that lands while the voice is still speaking a filler ("still working on it") is
        # dropped by GPT-Live without an error, so wait for a pause first (at most 8 s).
        deadline = time.time() + 8
        while time.time() < deadline and time.time() - self.last_output < 1.2:
            await asyncio.sleep(0.2)
        await self.append("commentary", text, turn_id)

    async def voice_instruction(self, text: str) -> None:
        # Never tied to a hand-off: GPT-Live ends a hand-off on a tagged instruction and drops the answer after it.
        await self.append("instructions", text)

    async def ensure_spoken(self, spoken: str, wait: float = 6.0) -> None:
        """GPT-Live silently drops an answer tied to a hand-off it has already closed (seen after the busy
        line): if no speech follows within a few seconds, say it again untied."""
        before = len(self.output_text)
        await asyncio.sleep(wait)
        # GPT-Live can say a filler ("still working on it") in place of the answer, so the test is whether
        # the answer's own words were said, not whether anything was.
        if not answer_was_said(spoken, self.output_text[before:]) and not self.closing and self.ws is not None:
            say("answer produced no speech; resending it untied to the hand-off")
            await self.voice_instruction(
                f"Say this to {self.asker} in natural spoken words, adding nothing of your own: {spoken}")

    async def answer(self, turn_id: str, text: str = "", status: str = "", end: bool = False) -> str:
        """'ok'; 'ignored' for a status that arrives after its turn was answered, or while no session is live;
        'held:waking', 'held:connecting' or 'held:later' for an answer kept for the next session, by whether
        a session to say it is on its way; 'dropped' when the call cannot wake (a cap); 'superseded';
        'unknown'."""
        if not self.turns.known(turn_id):
            return "unknown"
        if status and turn_id == self.turns.live_id and self.turns.answered:
            return "ignored"  # spoken now it would follow the answer it was meant to precede
        first = not self.turns.replied
        if not self.turns.accept_reply(turn_id, final=not status):
            return "superseded"
        if first:
            self.log.latencies.append(self.turns.clock() - self.turns.offered_at)
        self.log.last_learner_speech = self.last_exchange = time.time()  # a reply restarts the idle timer too
        asleep = self.state != "live" or not self.session_live  # dormant, waking, connecting or rejoining
        if status:
            if asleep:
                return "ignored"
            await self.voice_instruction(
                f"Tell {self.asker} in a few words that you are {status}. Say nothing else.")
            return "ok"
        markers_filter = MarkerFilter()
        board_from = len(self.board.items)
        spoken, end_marker, _ = self.digest(markers_filter.feed_ordered(text))
        spoken += self.finish_digest(markers_filter)
        self.log.full_reply(spoken, [i["title"] for i in self.board.items[board_from:]])
        spoken = speakable(spoken)
        if asleep:
            ending = end or end_marker
            if ending and (self.state == "dormant" or not spoken):
                # Dormant: no session to say the wrap-up, and waking one only to hang up is not worth paying
                # for. It is in the transcript. (Waking or connecting: the session on its way says it.)
                self.log.end_reason = "learner finished"
                asyncio.create_task(self.close())
                return "ended" if spoken else "ok"
            if spoken:
                return self.hold_reply(spoken, goodbye=ending)
            return "ok"
        if spoken and turn_id in self.stale_delegations:
            # Handed off by a session lost since: the current session has no such hand-off to answer.
            await self.voice_instruction(
                f"Say this to {self.asker} in natural spoken words, adding nothing of your own: {spoken}")
        elif spoken:
            await self.voice_say(spoken, turn_id)
            asyncio.create_task(self.ensure_spoken(spoken))
        if end or end_marker:
            self.log.end_reason = "learner finished"
            asyncio.create_task(self.close_after_speech())
        return "ok"

    def hand_over_end(self) -> None:
        """The call is over: flag a held reply or wrap-up no session said, in the footer and the doorbell's end."""
        unsaid = " ".join(r for r in (self.held_reply, self.held_goodbye) if r) or None
        self.log.unsaid = unsaid
        if self.turns:
            self.turns.finish(self.log.end_reason, str(self.log.transcript), unsaid=unsaid)

    def drop_goodbye(self, why: str) -> None:
        if self.held_goodbye is not None:
            self.held_goodbye = None
            self.log.aside(f"The wrap-up was not said and the call stays open: {why}.")

    def hold_reply(self, spoken: str, goodbye: bool = False) -> str:
        """Keep an answer no session can say now, and wake the call to say it: the wake path, seeded with it."""
        if self.refresh_cap() or self.call_over:
            return "dropped"
        if goodbye:
            self.held_goodbye = spoken
        else:
            self.held_reply = f"{self.held_reply} {spoken}" if self.held_reply else spoken
        self.wake_for_held_reply()  # deferred to rest() while sleep() is still closing the old session
        say("an answer arrived while no session could say it; keeping it for the next one")
        if self.state == "waking" or (self.sleeping_ws is not None and not self.held_autowoke):
            return "held:waking"
        if self.state == "live" and self.session_id:
            return "held:connecting"
        return "held:later"

    def record_activity(self, body: dict) -> bool:
        """One tool call from the brain session; the doorbell's own call names that session."""
        session = str(body.get("session_id", ""))
        if body.get("doorbell"):
            self.owner_session = self.owner_session or session
            return True
        if not self.turns or session != self.owner_session:
            return False
        self.turns.note_activity()  # alive, even through tools the page does not list
        now = self.turns.clock()
        if body.get("phase") == "stop":  # the session stopped (or failed): nothing of it is still running
            for item in self.activity:
                if item["state"] == "running":
                    item["state"], item["seconds"] = "done", round(now - item["started"], 1)
            return True
        if not body.get("label"):
            return False
        self.last_activity = now
        if body.get("phase") == "end":
            for item in reversed(self.activity):
                if item["tool"] == body.get("tool") and item["state"] == "running":
                    item["state"], item["seconds"] = "done", round(now - item["started"], 1)
                    break
            return True
        self.activity.append({"label": str(body["label"]), "tool": str(body.get("tool", "")),
                              "state": "running", "started": now, "seconds": None})
        return True

    def work_state(self) -> dict:
        if not self.turns or not self.turns.working:
            return {"working": False, "elapsed": 0, "quiet": 0, "activity": self.activity_view()}
        now = self.turns.clock()
        since = max(self.turns.delivered_at, self.last_activity)
        return {"working": True, "elapsed": round(now - self.turns.delivered_at, 1),
                "quiet": round(now - since, 1), "activity": self.activity_view()}

    def activity_view(self) -> list[dict]:
        now = self.turns.clock() if self.turns else 0
        return [{"label": a["label"], "state": a["state"],
                 "seconds": a["seconds"] if a["seconds"] is not None else round(now - a["started"], 1)}
                for a in self.activity]

    async def alert_if_stuck(self) -> None:
        alert = self.turns.check() if self.turns else None
        if alert == "busy":
            await self.voice_instruction(MEETING_BUSY_LINE if self.meeting else BUSY_LINE)
        elif alert == "offline":
            await self.voice_instruction(MEETING_OFFLINE_LINE if self.meeting else OFFLINE_LINE)

    # -- ending ---------------------------------------------------------------

    async def close_after_speech(self, max_wait: float = 30) -> None:
        """Let the wrap-up be spoken, then close the session gracefully."""
        if self.closing:
            return
        self.closing = True
        deadline = time.time() + max_wait
        await asyncio.sleep(3)
        while time.time() < deadline and time.time() - self.last_output < 2.5:
            await asyncio.sleep(0.5)
        await self.close()

    async def close(self, wait: float = 10) -> None:
        if self.ws and not self.ws.closed:
            await self.send({"type": "session.close", "event_id": self.next_id("close")})
            try:
                await asyncio.wait_for(self.done.wait(), timeout=wait)
            except asyncio.TimeoutError:
                await self.ws.close()
        self.done.set()

    async def reach_time_limit(self) -> None:
        """--max-minutes while live. A tutor says goodbye; a meeting's voice leaves without a word."""
        self.log.end_reason = f"reached the {self.args.max_minutes} min limit"
        if not self.meeting and self.greeted:  # an unstarted session has nobody to say goodbye to
            await self.append(
                "instructions",
                "Tell the learner in one sentence that you've reached the time limit for this "
                "session, so you'll stop here, and say goodbye.",
            )
        asyncio.create_task(self.close_after_speech())

    async def tick(self) -> None:
        # Once per call, not per session: a rejoin does not restart the clock.
        self.limit_at = self.limit_at or time.time() + self.args.max_minutes * 60
        limit = self.limit_at
        while True:
            await asyncio.sleep(0.5)
            self.log.flush_idle()
            if self.closing:
                continue
            if time.time() > limit:  # before the greeted guard: a session bills whether it started or not
                await self.reach_time_limit()
                continue
            if not self.capping and (cap := self.cap_reached()):
                await self.reach_live_cap(cap)
                continue
            if not self.greeted:
                continue
            await self.alert_if_stuck()
            if self.should_sleep(time.time()):
                asyncio.create_task(self.sleep())
            elif self.idle_expired(time.time()):
                self.log.end_reason = f"no speech for {self.args.idle_minutes} min"
                asyncio.create_task(self.close_after_speech(max_wait=5))


def answer_was_said(answer: str, said: str) -> bool:
    """A third of the answer's longer words were spoken: it was said, perhaps paraphrased."""
    words = {w for w in re.findall(r"[a-z0-9]+", answer.lower()) if len(w) > 3}
    if not words:
        return len(said.strip()) >= len(answer.strip()) // 2
    heard = set(re.findall(r"[a-z0-9]+", said.lower()))
    return len(words & heard) >= max(1, len(words) // 3)


def last_sentence_end(text: str) -> int:
    ends = [m.end() for m in re.finditer(r"[.!?](?:[\"')\]]*)\s", text + " ")]
    return min(ends[-1], len(text)) if ends else 0


# ---------------------------------------------------------------------------
# Local web server: the page, session creation, state for the page
# ---------------------------------------------------------------------------

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
  --acc:#0F6E74; --acc-soft:#EAF4F4; --acc-mid:#B7DADB; --you:#2F5BD3; --tutor:#A6520B; --bad:#B42318; --warn:#B54708; --warn-soft:#FEF6EE;
  --sans:"Inter",system-ui,-apple-system,sans-serif; --mono:"Geist Mono",ui-monospace,Menlo,monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 14px/1.5 var(--sans);-webkit-font-smoothing:antialiased;overflow:hidden}
.app{height:100%;display:grid;grid-template-columns:minmax(360px,420px) 1fr}
aside{background:var(--panel);border-right:1px solid var(--line);display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;grid-template-columns:minmax(0,1fr);min-height:0;min-width:0;overflow:hidden}
.top{display:flex;align-items:flex-start;gap:12px;padding:20px 22px 14px}
.title{flex:1;min-width:0}
.title h1{margin:0;font:600 17px/1.25 var(--sans);text-wrap:balance}
.title p{margin:3px 0 0;font-size:12.5px;color:var(--muted)}
.icon{width:34px;height:34px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--muted);display:grid;place-items:center;cursor:pointer;flex:none}
.icon:hover{color:var(--ink)}
.card{margin:0 16px;border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:12px;display:flex;flex-direction:column;gap:8px}
.lane{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}
.lane span{--c:var(--faint);position:relative;border-radius:7px;padding:6px 4px;text-align:center;font:600 12px var(--sans);color:var(--faint);background:var(--bg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background .2s,color .2s,box-shadow .08s linear}
.lane span.on{background:var(--c);color:var(--panel);box-shadow:0 0 0 calc(var(--lvl,0)*6px) color-mix(in srgb,var(--c) 25%,transparent)}
.lane span.turn{color:var(--c);box-shadow:inset 0 0 0 1.5px var(--c)}
.lane span.wait{color:var(--c);box-shadow:inset 0 0 0 1.5px var(--c);animation:pulse 1.2s ease-in-out infinite}
#laneyou{--c:var(--you)} #lanevoice{--c:var(--tutor)} #laneclaude{--c:var(--acc)}
body[data-state="dormant"] .lane,body[data-state="ended"] .lane{opacity:.45}
.card b{font:600 14px var(--sans);color:var(--ink)}
body[data-state="dormant"] .card b{color:var(--acc)}
.state{font-size:13px;color:var(--muted);min-height:1.4em}
.state.bad{color:var(--bad)}
.heard{font-size:13px;color:var(--ink);border-left:2px solid var(--line);padding-left:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.heard[hidden]{display:none}
#work{display:flex;flex-direction:column;gap:6px}
#work[hidden]{display:none}
.trace{background:#1C2230;color:#DDE3EC;border-radius:8px;padding:9px 11px;font:400 12px/1.6 var(--mono);display:flex;flex-direction:column;max-height:9.6em;overflow:auto}
.trace .row{display:flex;justify-content:space-between;gap:10px;min-width:0}
.trace .row span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trace .row span:last-child{flex:none;opacity:.55}
.trace .row.done{opacity:.6}
.trace .row.run span:first-child::after{content:"▍";margin-left:2px;animation:pulse 1s steps(1) infinite}
.trace .none{opacity:.6}
.stepnote{display:flex;justify-content:space-between;gap:10px;font:400 11.5px var(--mono);color:var(--muted)}
.stepnote span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stall{font-size:12.5px;color:var(--warn);background:var(--warn-soft);border-radius:6px;padding:6px 8px}
.stall[hidden]{display:none}
.act{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.act:not(:has(.go:not(:disabled):not([hidden]))){display:none}
.act .go{flex:none;font:600 13px var(--sans);padding:7px 14px;border-radius:8px;border:1px solid var(--acc);background:var(--acc);color:var(--panel);cursor:pointer;display:inline-flex;gap:8px;align-items:center}
.act .go kbd{color:inherit;opacity:.75}
.act .go:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.act .go:disabled,.act .go[hidden]{display:none}
.act .go.soft{background:var(--panel);color:var(--acc)}
body[data-state="dormant"] #start{display:none}
#cost{font-size:12px;color:var(--faint);min-height:1.2em;border-top:1px solid var(--line);padding-top:8px}
#cost a{color:inherit}
.captions{overflow:auto;padding:16px 22px;display:flex;flex-direction:column;gap:16px;min-height:0}
.turn .who{font:600 10.5px var(--sans);letter-spacing:.12em;text-transform:uppercase;margin-bottom:2px}
.turn.you .who{color:var(--you)} .turn.tutor .who{color:var(--tutor)}
.turn .text{font:400 15px/1.6 var(--sans);white-space:pre-wrap}
.empty{color:var(--faint);font-size:13.5px;margin:auto 0}
.controls{border-top:1px solid var(--line);padding:12px 16px;display:flex;flex-direction:column;gap:8px}
.row{display:flex;gap:8px}
.btn{flex:1;font:500 13px var(--sans);padding:9px 12px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;display:inline-flex;gap:8px;align-items:center;justify-content:center}
.btn:disabled{opacity:.45;cursor:default}
.btn.danger{color:var(--bad);border-color:#F3C5C0}
.btn[aria-pressed="true"]{background:var(--ink);color:var(--panel);border-color:var(--ink)}
kbd{font:400 11px var(--mono);color:var(--faint)}
.controls{min-width:0}
.devices{position:relative;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px}
.devchip{position:relative;display:flex;align-items:center;min-width:0;height:36px;border:1px solid var(--line);border-radius:8px;background:var(--panel);overflow:hidden}
.devbtn{flex:none;width:36px;height:100%;display:grid;place-items:center;border:0;border-right:1px solid var(--line);background:none;color:var(--muted);cursor:pointer}
.devbtn:hover{color:var(--ink)}
.devbtn[aria-pressed="true"]{color:var(--you);background:#EEF2FD}
.devbtn:disabled{opacity:.45;cursor:default}
.devname{flex:1;min-width:0;height:100%;display:flex;align-items:center;gap:6px;border:0;background:none;padding:0 10px;font:500 12.5px var(--sans);color:var(--ink);cursor:pointer;text-align:left}
.devname span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.devname svg{flex:none;color:var(--muted)}
.devname:hover{background:var(--bg)}
.devname:disabled{cursor:default;color:var(--muted)}
.devbtn:focus-visible,.devname:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
.devchip .meter{position:absolute;left:0;right:0;bottom:0;height:2px}
.devchip .meter i{display:block;height:100%;width:0;background:var(--you);transition:width .06s linear}
.menu{position:absolute;z-index:10;bottom:calc(100% + 6px);max-width:100%;background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 32px -8px rgba(16,24,40,.28);padding:4px;display:flex;flex-direction:column}
.menu[hidden]{display:none}
.menu .head{font:600 10.5px var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);padding:6px 10px 4px}
.opt{border:0;background:none;text-align:left;padding:8px 12px 8px 30px;border-radius:6px;font:13px var(--sans);color:var(--ink);cursor:pointer;position:relative;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.opt:hover,.opt:focus{background:var(--acc-soft);outline:none}
.opt.on::before{content:"✓";position:absolute;left:11px;color:var(--acc);font-weight:600}
.opt small{color:var(--muted);margin-left:6px}
.notes{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--acc-soft);color:var(--acc);max-width:100%;overflow-wrap:anywhere}
main{display:grid;min-height:0}
main iframe#stage{width:100%;height:100%;border:0;background:var(--bg)}
.boardempty{color:var(--faint);font-size:14px;max-width:44ch}
dialog{border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);padding:20px;width:min(420px,calc(100vw - 32px))}
dialog::backdrop{background:rgba(16,24,40,.35)}
dialog h2{font:600 16px var(--sans);margin:0 0 12px}
dialog label{display:block;font-size:12.5px;color:var(--muted);margin:12px 0 4px}
dialog select{width:100%;padding:9px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit}
dialog p{font-size:12.5px;color:var(--muted);margin:12px 0 0}
dialog .row{justify-content:flex-end;margin-top:16px}
dialog .btn{flex:none}
.pbar{display:none}
body.projector .app{grid-template-columns:1fr;height:calc(100% - 72px)}
body.projector aside{display:none}
body.projector #cost{display:none}
body.projector .pbar{display:flex;align-items:center;gap:16px;height:72px;padding:0 28px;background:var(--panel);border-bottom:1px solid var(--line);font:600 26px/1.25 var(--sans);color:var(--ink)}
body.projector .pbar .dot{width:16px;height:16px;border-radius:50%;background:var(--faint);flex:none}
body.projector .pbar #pbartext{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body.projector .pbar .btn{flex:none;margin-left:auto;font-size:18px;padding:10px 18px;border-radius:10px}
body.projector .pbar .btn[hidden]{display:none}
body.projector .pbar kbd{font-size:13px;opacity:.7;margin-left:6px}
body.projector[data-pbar="dormant"] .pbar .dot{background:var(--acc)}
body.projector[data-pbar="live"] .pbar .dot{background:var(--you)}
body.projector[data-pbar="tutor"] .pbar .dot{background:var(--tutor);animation:pulse 1.2s infinite}
body.projector[data-pbar="waking"] .pbar .dot,body.projector[data-pbar="thinking"] .pbar .dot{background:var(--acc);animation:breathe 1.4s ease-in-out infinite}
body.projector[data-pbar="muted"] .pbar .dot{background:var(--faint)}
body.projector[data-pbar="error"] .pbar .dot,body.projector[data-pbar="armed"] .pbar .dot{background:var(--bad)}
body.projector[data-pbar="error"] .pbar,body.projector[data-pbar="armed"] .pbar{color:var(--bad)}
body.projector[data-pbar="muted"] .pbar{color:var(--muted)}
@media (max-width:900px){
  body{overflow:auto}
  .app{display:flex;flex-direction:column;height:auto;min-height:100%}
  aside{border-right:0;border-bottom:1px solid var(--line)}
  .captions{max-height:40vh}
  main{min-height:60vh}
}
@media (prefers-reduced-motion:reduce){.lane span,.trace .row.run span::after,.pbar .dot{animation:none!important}}
</style></head>
<body data-state="idle">
<div class="pbar" id="pbar" aria-live="polite"><span class="dot"></span><span id="pbartext"></span><button class="btn danger" id="pend" type="button" hidden>End <kbd>Esc Esc</kbd></button><button class="btn" id="pstart" type="button">Start</button></div>
<div class="app">
  <aside>
    <div class="top">
      <div class="title"><h1 id="topic"></h1><p id="subtitle">Voice by GPT-Live · answers by this Claude session</p></div>
    </div>
    <div class="card" aria-live="polite">
      <div class="lane" aria-label="Who has the turn"><span id="laneyou">You</span><span id="lanevoice">Voice</span><span id="laneclaude">Claude</span></div>
      <b id="cardtitle">Ready</b>
      <div class="state" id="status">Speakers are fine: echo cancellation is on.</div>
      <div class="heard" id="heard" hidden></div>
      <div id="work" hidden>
        <div class="trace" id="trace"><span class="none">Reading your question</span></div>
        <div class="stepnote"><span id="stepnote">starting</span><span id="elapsed">0 s</span></div>
        <div class="stall" id="stall" hidden>No activity for 20 s. Check the terminal.</div>
      </div>
      <div class="act">
        <button class="go" id="start" aria-label="Start talking"><span id="orblabel">Start</span><kbd>Space</kbd></button>
        <button class="go soft" id="wake" type="button" hidden>Wake now</button>
      </div>
      <div id="cost"></div>
    </div>
    <div class="captions" id="log"><div class="empty" id="empty">Interrupt whenever you like. Say "let's stop here" to finish.</div></div>
    <div class="controls">
      <div class="devices" id="devices" aria-label="Audio devices">
        <div class="devchip">
          <button class="devbtn" id="checkmic" type="button" aria-pressed="false" title="Check the microphone" aria-label="Check the microphone"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>
          <button class="devname" id="micname" type="button" aria-haspopup="listbox" aria-expanded="false" title="Microphone"><span id="micnametext">Microphone</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg></button>
          <span class="meter" aria-hidden="true"><i id="micmeter"></i></span>
        </div>
        <div class="devchip">
          <button class="devbtn" id="testspk" type="button" title="Play a test sound" aria-label="Play a test sound"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/></svg></button>
          <button class="devname" id="spkname" type="button" aria-haspopup="listbox" aria-expanded="false" title="Speakers"><span id="spknametext">Speakers</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg></button>
        </div>
        <select id="mic" hidden></select><select id="spk" hidden></select>
        <div class="menu" id="devmenu" role="listbox" hidden></div>
      </div>
      <div class="row">
        <button class="btn" id="mute" aria-pressed="false" disabled>Mute <kbd>Space</kbd></button>
        <button class="btn danger" id="stop" disabled>End <kbd>Esc Esc</kbd></button>
      </div>
      <div class="notes" id="notes"></div>
    </div>
  </aside>
  <main>
    <iframe id="stage" title="Stage" allow="clipboard-read; clipboard-write"></iframe>
    <p class="boardempty" id="nostage" hidden>The stage is not available for this call.</p>
  </main>
</div>
<audio id="out" autoplay></audio>
<script type="module">
const CFG = __CONFIG__;
const $ = (id) => document.getElementById(id);
// ?view=projector: the stage fills the screen under a thin status bar, for a room to watch.
const PROJECTOR = new URLSearchParams(location.search).get("view") === "projector";
if (PROJECTOR) document.body.classList.add("projector");
$("pstart").onclick = () => $("start").click();
$("pend").onclick = () => $("stop").click();
if (CFG.stageUrl) $("stage").src = CFG.stageUrl; else { $("stage").remove(); $("nostage").hidden = false; }
$("topic").textContent = CFG.topic;
document.title = "Talk · " + CFG.topic;
let working = false, muted = false;
const status = (t, bad=false) => { $("status").textContent = t; $("status").className = "state" + (bad ? " bad" : ""); paintBar(); };
// GPT-Live seconds are billed; dormant listening is local and free; the brain runs on the plan.
const CLAUDE_COST_LABEL = CFG.llmMode === "api" ? "Claude: API, billed separately" : "Claude: your plan";
function paintCost(cost) {
  if (!cost) return;
  const m = Math.floor(cost.voice_seconds / 60), sec = Math.floor(cost.voice_seconds % 60);
  let line = `GPT-Live ${m}m ${sec}s · $${cost.cost_usd.toFixed(2)}`;
  if (cost.today_usd !== undefined) line += ` · today $${cost.today_usd.toFixed(2)}`;
  if (cost.dormant_seconds >= 60) line += ` · asleep ${Math.round(cost.dormant_seconds / 60)}m (free)`;
  // Every figure here is an estimate: the real bill is one click away.
  const bill = document.createElement("a");
  bill.href = "https://platform.openai.com/usage"; bill.textContent = "real bill ↗";
  $("cost").replaceChildren(line + " · " + CLAUDE_COST_LABEL + " · ", bill);
}
// Dormant audio goes to the machine running talk.py. Only a page served to loopback is on that machine;
// opened from another one (a tailnet name, a proxy), the PCM travels there, so "this Mac" would be untrue.
const LOCAL = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(location.hostname);
const HERE = LOCAL ? "this Mac" : "the talk machine";
const VOICE = CFG.wakeName || "Voice";
$("lanevoice").textContent = VOICE;
const TITLES = { idle: "Ready", connecting: "Connecting…", listening: "Your turn", you: "You're speaking",
  tutor: `${VOICE} is speaking`, thinking: "Claude is working on it", ended: "Call ended",
  dormant: `Dormant · listening on ${HERE} · free`, waking: "Waking…" };
const setState = (s, label) => {
  document.body.dataset.state = s; if (label !== undefined) $("orblabel").textContent = label;
  if (label) $("start").setAttribute("aria-label", label);
  $("cardtitle").textContent = label === "Muted" ? "Muted" : (TITLES[s] || "");
  paintLane(); paintBar();
};
// The lane shows who holds the turn: lit while that party is at it, outlined while it is theirs to take.
// The voice and Claude can both be lit: the voice speaks a status while Claude works.
function paintLane() {
  const s = document.body.dataset.state;
  const you = s === "you" ? "on" : s === "listening" && !muted ? "turn" : "";
  const voice = s === "tutor" ? "on" : s === "connecting" || s === "waking" ? "wait" : "";
  const claude = working ? "on" : s === "thinking" ? "wait" : "";
  $("laneyou").className = you; $("lanevoice").className = voice; $("laneclaude").className = claude;
}
// The bar mirrors the same signals the sidebar already shows (state, #status, the End arm, mute,
// the ear's own "loading"/"in use" messages) rather than tracking a second copy of them.
function paintBar() {
  if (!PROJECTOR) return;
  const s = document.body.dataset.state;
  if (s === "idle") {  // the only state reachable before `listening`/`muted` below are assigned
    $("pbartext").textContent = "Press Start to begin listening"; document.body.dataset.pbar = "idle";
    $("pstart").hidden = false; $("pstart").textContent = "Start"; $("pend").hidden = true;
    return;
  }
  const who = CFG.wakeName || "The voice", label = $("orblabel").textContent;
  const statusEl = $("status"), statusBad = statusEl.classList.contains("bad"), statusText = statusEl.textContent;
  const armed = $("stop").firstChild && $("stop").firstChild.textContent.trim() === "Again to end";
  const rejoin = label === "Rejoin";
  let text, kind;
  if (armed) { text = "Press again to end · Esc Esc also works"; kind = "armed"; }
  else if (rejoin) { text = "Connection lost · Rejoin"; kind = "error"; }
  else if (statusText.includes("live in another tab")) { text = "Open in another tab"; kind = "error"; }
  else if (statusText.includes("moved to another tab")) { text = "Listening moved to another tab"; kind = "error"; }
  else if (listening && (earShown === "loading" || earShown === "failed") && !wakeFailed) {
    text = earText(earShown, earWhy); kind = earShown === "failed" ? "error" : "dormant";
  } else if (statusBad) { text = statusText; kind = "error"; }
  // Speaking and working outrank muted, as in the sidebar's own `next` computation: "is speaking" and
  // "is looking it up" are the signals the room must never lose, so a mute press only adds a marker.
  else if (s === "tutor") { text = `${who} is speaking` + (muted ? " · Muted" : ""); kind = "tutor"; }
  else if (s === "thinking") { text = `${who} is looking it up…` + (muted ? " · Muted" : ""); kind = "thinking"; }
  else if (muted && (running || listening)) { text = "Muted · Space to unmute"; kind = "muted"; }
  else if (s === "dormant") { text = CFG.wakeName ? `Listening · say '${CFG.wakeName}' to ask` : "Listening"; kind = "dormant"; }
  else if (s === "waking") { text = `Waking ${who}…`; kind = "waking"; }
  else if (s === "connecting") { text = `${who} is joining…`; kind = "waking"; }
  else if (s === "ended") { text = "Call ended"; kind = "ended"; }
  else { text = `${who} is listening · follow-ups need no name`; kind = "live"; }
  $("pbartext").textContent = text; document.body.dataset.pbar = kind;
  $("pstart").hidden = !(s === "dormant" || rejoin); $("pstart").textContent = rejoin ? "Rejoin" : "Wake now";
  $("pend").hidden = $("stop").disabled;
}
paintBar();
let peer, events, mic, closeTimer, audioCtx, finalized = false, running = false, wasLive = false, micLevel = 0, outLevel = 0, escAt = 0;
// Dormancy: no GPT-Live session; the mic goes to the ear on the server as 16 kHz PCM.
let earWs = null, earCtx = null, earStream = null, earNode = null, listening = false, started = false, leaving = false;
let serverState = CFG.state, earShown = null, earWhy = "", earGen = 0, wakeFailed = false, ending = false;
// The server closes a session that never started (it bills from its create); a rise in its count while
// this page holds a peer that never started means that peer's session is gone.
let knownFailedStarts = 0, peerFailedStarts = 0, capShown = null;

function pick(list, hint) {
  if (!hint) return null;
  if (/^\d+$/.test(hint)) return list[Number(hint)] || null;
  return list.find(d => d.label.toLowerCase().includes(hint.toLowerCase())) || null;
}
async function listDevices() {
  const all = await navigator.mediaDevices.enumerateDevices();
  for (const [sel, kind, hint] of [[$("mic"), "audioinput", CFG.inputDevice], [$("spk"), "audiooutput", CFG.outputDevice]]) {
    const list = all.filter(d => d.kind === kind && d.deviceId !== "default" && d.deviceId !== "communications");
    const current = sel.value;
    sel.innerHTML = "";
    const sys = all.find(d => d.kind === kind && d.deviceId === "default");
    if (kind === "audioinput") hasDefaultMic = !!sys;
    const sysName = sys && sys.label ? sys.label.replace(/^Default\s*-\s*/, "") : "";
    const def = document.createElement("option"); def.value = ""; def.textContent = sysName ? "System default · " + sysName : "System default"; sel.append(def);
    list.forEach((d, i) => { if (!d.label) return; const o = document.createElement("option"); o.value = d.deviceId; o.textContent = d.label; sel.append(o); });
    const hinted = pick(list, hint);
    if (current && list.some(d => d.deviceId === current)) sel.value = current; else if (hinted) sel.value = hinted.deviceId;
    if (kind === "audiooutput" && !("setSinkId" in HTMLMediaElement.prototype)) { sel.disabled = true; sel.title = "This browser plays through the system default output."; }
  }
}
let hasDefaultMic = false;
const micConstraints = () => { const id = $("mic").value || (hasDefaultMic ? "default" : ""); return { audio: {
  deviceId: id ? { exact: id } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }; };
let preview = null, previewCtx = null, previewAn = null, micReader = -1;
const deviceName = (sel) => (sel.selectedOptions[0]?.textContent || "System default").replace(/^System default · /, "");
function showInUse() {
  const track = (mic || preview)?.getAudioTracks()[0];
  const micName = track ? track.label : deviceName($("mic"));
  $("micnametext").textContent = micName; $("micname").title = "Microphone: " + micName;
  const spkName = deviceName($("spk"));
  $("spknametext").textContent = spkName; $("spkname").title = "Speakers: " + spkName;
  $("spkname").disabled = $("spk").disabled; $("testspk").disabled = $("spk").disabled;
}
function closeMenu() {
  $("devmenu").hidden = true;
  for (const id of ["micname", "spkname"]) $(id).setAttribute("aria-expanded", "false");
}
function openMenu(sel, anchor, label) {
  const m = $("devmenu"); m.innerHTML = "";
  const head = document.createElement("div"); head.className = "head"; head.textContent = label; m.append(head);
  [...sel.options].forEach(o => {
    const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "option");
    b.className = "opt" + (o.value === sel.value ? " on" : "");
    b.setAttribute("aria-selected", String(o.value === sel.value));
    if (o.value === "") { b.textContent = "System default"; const sm = document.createElement("small"); sm.textContent = o.textContent.replace(/^System default · ?/, ""); b.append(sm); }
    else b.textContent = o.textContent;
    b.onclick = () => { closeMenu(); anchor.focus(); if (sel.value !== o.value) { sel.value = o.value; sel.dispatchEvent(new Event("change")); } };
    m.append(b);
  });
  const chip = anchor.closest(".devchip"), box = $("devices").getBoundingClientRect(), r = chip.getBoundingClientRect();
  m.style.left = (r.left - box.left) + "px"; m.style.minWidth = r.width + "px";
  m.style.maxWidth = (box.right - r.left) + "px";
  m.hidden = false; anchor.setAttribute("aria-expanded", "true");
  (m.querySelector(".opt.on") || m.querySelector(".opt"))?.focus();
}
$("micname").onclick = (e) => { e.stopPropagation(); $("devmenu").hidden ? openMenu($("mic"), $("micname"), "Microphone") : closeMenu(); };
$("spkname").onclick = (e) => { e.stopPropagation(); $("devmenu").hidden ? openMenu($("spk"), $("spkname"), "Speakers") : closeMenu(); };
document.addEventListener("click", (e) => { if (!$("devmenu").hidden && !$("devmenu").contains(e.target)) closeMenu(); });
$("devmenu").addEventListener("keydown", (e) => {
  const opts = [...$("devmenu").querySelectorAll(".opt")], i = opts.indexOf(document.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); opts[Math.min(opts.length - 1, i + 1)]?.focus(); }
  if (e.key === "ArrowUp") { e.preventDefault(); opts[Math.max(0, i - 1)]?.focus(); }
});
async function openPreview() {
  if (mic) return;
  preview?.getTracks().forEach(t => t.stop());
  try { preview = await navigator.mediaDevices.getUserMedia(micConstraints()); }
  catch (e) { status("Microphone blocked: " + e.message, true); return; }
  previewCtx ??= new AudioContext(); await previewCtx.resume();
  previewAn = previewCtx.createAnalyser(); previewAn.fftSize = 512;
  previewCtx.createMediaStreamSource(preview).connect(previewAn);
  $("checkmic").setAttribute("aria-pressed", "true"); $("checkmic").title = "Stop checking the microphone";
  await listDevices(); showInUse();
}
function closePreview() {
  preview?.getTracks().forEach(t => t.stop()); preview = null; previewAn = null;
  $("micmeter").style.width = "0%";
  $("checkmic").setAttribute("aria-pressed", "false"); $("checkmic").title = "Check the microphone";
  showInUse();
}
(function previewLoop() {
  if (!mic && previewAn) {
    const buf = new Uint8Array(512); previewAn.getByteTimeDomainData(buf);
    let sum = 0; for (const v of buf) { const x = (v - 128) / 128; sum += x * x; }
    $("micmeter").style.width = Math.min(100, Math.sqrt(sum / buf.length) * 400) + "%";
  }
  requestAnimationFrame(previewLoop);
})();
function beepUrl() {
  const rate = 44100, n = Math.floor(rate * 0.35), data = new DataView(new ArrayBuffer(44 + n * 2));
  const w = (o, t) => [...t].forEach((c, i) => data.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); data.setUint32(4, 36 + n * 2, true); w(8, "WAVEfmt "); data.setUint32(16, 16, true);
  data.setUint16(20, 1, true); data.setUint16(22, 1, true); data.setUint32(24, rate, true); data.setUint32(28, rate * 2, true);
  data.setUint16(32, 2, true); data.setUint16(34, 16, true); w(36, "data"); data.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) { const env = Math.min(1, i / 800, (n - i) / 800); data.setInt16(44 + i * 2, Math.sin(2 * Math.PI * 660 * i / rate) * 9000 * env, true); }
  return URL.createObjectURL(new Blob([data], { type: "audio/wav" }));
}
const beep = new Audio(beepUrl());
$("testspk").onclick = async () => {
  try { if (beep.setSinkId) await beep.setSinkId($("spk").value); beep.currentTime = 0; await beep.play(); }
  catch (e) { status("Could not play on that device: " + e.message, true); }
};
$("checkmic").onclick = () => preview ? closePreview() : openPreview();
$("mic").onchange = async () => {
  if (mic && peer) {
    let next;
    try { next = await navigator.mediaDevices.getUserMedia(micConstraints()); }
    catch (e) { status("Could not open that microphone: " + e.message, true); return; }
    const track = next.getAudioTracks()[0];
    track.enabled = !muted;
    const sender = peer.getSenders().find(x => x.track && x.track.kind === "audio");
    await sender.replaceTrack(track);
    mic.getTracks().forEach(t => t.stop());
    mic = next;
    if (micReader >= 0) readers[micReader] = levelOf(mic, v => micLevel = micLevel * 0.6 + v * 0.4);
    track.onended = () => status("That microphone went away. Pick another one.", true);
    status("Switched microphone.");
  } else if (listening) {
    stopEar(); await toDormant();
  } else if (preview) {
    await openPreview();
  }
  showInUse();
};
$("spk").onchange = async () => {
  try { if ($("out").setSinkId) await $("out").setSinkId($("spk").value); status("Switched speakers."); }
  catch (e) { status("Could not switch speakers: " + e.message, true); }
  showInUse();
};
navigator.mediaDevices.addEventListener("devicechange", async () => { await listDevices(); showInUse(); });
listDevices().then(showInUse);

// Captions: one block per speaker turn; a new block after a pause or a speaker change.
let last = { you: null, tutor: null }, lastAt = { you: 0, tutor: 0 }, lastSpeaker = null;
function caption(who, text) {
  $("empty")?.remove();
  const now = performance.now();
  if (!last[who] || lastSpeaker !== who || now - lastAt[who] > 2500) {
    const turn = document.createElement("div"); turn.className = "turn " + who;
    turn.innerHTML = `<div class="who">${who === "you" ? "You" : VOICE}</div><div class="text"></div>`;
    $("log").append(turn); last[who] = turn.querySelector(".text");
  }
  last[who].textContent += text.replace(/\[(hum|mhm|hmm|laugh)[^\]]*\]/gi, "");
  lastAt[who] = now; lastSpeaker = who;
  const log = $("log"); if (log.scrollHeight - log.scrollTop - log.clientHeight < 160) log.scrollTop = log.scrollHeight;
}

function levelOf(stream, onLevel) {
  const an = audioCtx.createAnalyser(); an.fftSize = 512;
  audioCtx.createMediaStreamSource(stream).connect(an);
  const buf = new Uint8Array(an.fftSize);
  return () => { an.getByteTimeDomainData(buf); let sum = 0; for (const v of buf) { const x = (v - 128) / 128; sum += x * x; } onLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4)); };
}
let thinking = false;
let workBase = 0;
function renderWork(s) {
  const was = working;
  working = !!s.working; document.body.classList.toggle("working", working);
  $("work").hidden = !working;
  if (was !== working) paintLane();
  if (!working) return;
  workBase = performance.now() - (s.elapsed || 0) * 1000;
  const acts = s.activity || [];
  const run = acts.filter(a => a.state === "running").pop();
  const done = acts.filter(a => a.state === "done").length;
  $("stepnote").textContent = !acts.length ? "starting" : run ? `step ${acts.length} · ${done} done` : `putting the answer together · ${done} done`;
  const trace = $("trace"), pinned = trace.scrollHeight - trace.scrollTop - trace.clientHeight < 8;
  trace.replaceChildren();
  if (!acts.length) { const n = document.createElement("span"); n.className = "none"; n.textContent = "Reading your question"; trace.append(n); }
  acts.forEach(a => {
    const row = document.createElement("div"); row.className = "row " + (a.state === "running" ? "run" : "done");
    row.innerHTML = "<span></span><span></span>";
    row.firstChild.textContent = a.label;
    row.lastChild.textContent = a.state === "running" ? "" : Number(a.seconds || 0).toFixed(1) + " s";
    trace.append(row);
  });
  if (pinned) trace.scrollTop = trace.scrollHeight;
  $("stall").hidden = (s.quiet || 0) < 20;
}
setInterval(() => { if (working) $("elapsed").textContent = ((performance.now() - workBase) / 1000).toFixed(1) + " s"; }, 100);
let readers = [], lastTutorAt = -1e9, lastYouAt = -1e9, shown = null;
function animate() {
  readers.forEach(r => r());
  if (running) {
    // Speech has gaps between words, so a speaker stays "on" for a moment after their level
    // drops; without this hold the state and its caption flicker on every syllable.
    const now = performance.now();
    if (outLevel > 0.06 && outLevel >= micLevel) lastTutorAt = now;
    if (!muted && micLevel > 0.08) lastYouAt = now;
    const next = thinking && now - lastTutorAt > 900 ? "thinking"
      : now - lastTutorAt < 900 ? "tutor" : now - lastYouAt < 700 ? "you" : muted ? "muted" : "listening";
    if (next !== shown) {
      shown = next;
      if (next === "thinking") { setState("thinking", ""); status("Looking things up. Every step shows below."); }
      else if (next === "tutor") { setState("tutor", ""); status("Tutor is speaking. Just talk to interrupt."); }
      else if (next === "you") { setState("you", ""); status("Listening…"); }
      else { setState("listening", next === "muted" ? "Muted" : ""); status(next === "muted" ? (CFG.dormancy ? "Microphone muted. The voice closes once it has finished, so nothing bills. Unmute and speak to bring it back." : "Microphone muted. Press Space to unmute.") : "Your turn. Take your time."); }
    }
    const lvl = document.body.dataset.state === "tutor" ? outLevel : (muted ? 0 : micLevel);
    $("micmeter").style.width = (muted ? 0 : Math.min(100, micLevel * 100)) + "%";
    document.body.style.setProperty("--lvl", lvl.toFixed(3));
  }
  if (audioCtx && audioCtx.state !== "closed") requestAnimationFrame(animate);
}

function cleanup(msg) {
  stopEar();
  closeVoice();  // closing the peer alone may not end a session GPT-Live bills by the second
  running = false; clearTimeout(closeTimer); readers = []; micReader = -1;
  mic?.getTracks().forEach(t => t.stop()); events?.close(); peer?.close();
  audioCtx?.close(); $("out").srcObject = null;
  $("stop").disabled = true; $("mute").disabled = true; $("start").disabled = true;
  document.body.style.setProperty("--lvl", 0); setState("ended", "Done");
  if (msg) status(msg);
}
// A dropped connection is not the end of the call: the server keeps it open for a while and the
// poll below turns the orb into Rejoin. Only the server says when the call is really over.
function dropped() {
  if (finalized) return;
  cleanup("Connection lost. Checking whether the call can be rejoined…");
  peer = null; events = null; mic = null; audioCtx = null;
}

// The ear: an AudioWorklet turns the mic into 16 kHz mono 16-bit PCM, 20 ms per message. The
// context asks for 16 kHz so Chrome resamples with a proper filter; where a browser ignores that,
// the worklet decimates from whatever rate it got.
const EAR_WORKLET = `class Pcm16k extends AudioWorkletProcessor {
  constructor() { super(); this.step = sampleRate / 16000; this.pos = 0; this.out = new Int16Array(320); this.n = 0; }
  process(inputs) {
    const ch = inputs[0][0]; if (!ch) return true;
    for (; this.pos < ch.length; this.pos += this.step) {
      const i = Math.floor(this.pos), f = this.pos - i, a = ch[i], b = i + 1 < ch.length ? ch[i + 1] : a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.out[this.n++] = v < 0 ? v * 32768 : v * 32767;
      if (this.n === 320) { this.port.postMessage(this.out.buffer, [this.out.buffer]); this.out = new Int16Array(320); this.n = 0; }
    }
    this.pos -= ch.length;
    return true;
  }
}
registerProcessor("pcm16k", Pcm16k);`;
// Created once: a fresh blob URL on every dormant entry would leak (never revoked).
const EAR_WORKLET_URL = URL.createObjectURL(new Blob([EAR_WORKLET], { type: "text/javascript" }));
const dormantHint = () => CFG.wakeName
  ? `Say "${CFG.wakeName}" to ask. ` + (LOCAL ? "Nothing leaves this Mac until then." : "Until then, audio goes only to the talk machine.")
  : "Speak to bring the voice back, or press Wake now." + (LOCAL ? "" : " Until then, audio goes only to the talk machine.");
// What the room is told about local listening itself. Until the model is ready only energy wakes a
// call, which a name can never match: with --wake name, Wake now is then the only way in.
function earText(ear, why) {
  if (ear === "loading") return "Preparing local listening (one-time download)… "
    + (CFG.wakeName ? "press Wake now to ask" : "wakes on any speech until then");
  if (ear === "failed") return "Local listening failed — "
    + (CFG.wakeName ? "press Wake now to ask" : "speaking still wakes the voice, or press Wake now") + (why ? ` (${why})` : "");
  return dormantHint();
}
function stopEar() {
  earGen++;  // invalidates any toDormant() still opening the ear
  listening = false;
  const ws = earWs; earWs = null;
  if (ws) { ws.onclose = null; ws.onmessage = null; ws.close(); }
  earNode?.port.close(); earNode?.disconnect();
  earStream?.getTracks().forEach(t => t.stop()); earCtx?.close().catch(() => {});
  earNode = null; earStream = null; earCtx = null; $("heard").hidden = true; $("wake").hidden = true;
}
// Leave the live session without ending the call: the server closed it (dormancy) or the page is waking.
function teardownLive() {
  closeVoice();
  running = false; readers = []; micReader = -1;
  if (events) { events.onclose = null; events.onmessage = null; }
  mic?.getTracks().forEach(t => t.stop()); events?.close(); peer?.close(); audioCtx?.close().catch(() => {});
  $("out").srcObject = null; peer = null; events = null; mic = null; audioCtx = null;
  $("mute").disabled = true; document.body.style.setProperty("--lvl", 0);
}
function setMuteUi() {
  $("mute").setAttribute("aria-pressed", String(muted));
  $("mute").firstChild.textContent = muted ? "Unmute " : "Mute ";
  if (listening && !wakeFailed) status(muted ? "Muted. Unmute and speak to bring the voice back, or press Wake now." : earText(earShown, earWhy));
  paintLane(); paintBar();  // dormant has no animation loop of its own to pick up a mute toggle
}
// A generation counter: a mic change mid-getUserMedia, or a failed wake's own retry, can start a
// second toDormant() while an earlier one is still opening. Only the newest run may touch the
// shared ear globals; a superseded run releases what it opened and returns quietly.
async function toDormant() {
  if (listening || finalized || ending) return;
  const gen = ++earGen;
  listening = true; teardownLive();
  setState("dormant", "Wake now"); $("start").disabled = false; $("stop").disabled = false;
  $("mute").disabled = false; setMuteUi(); $("checkmic").disabled = false; $("checkmic").title = "Check the microphone";
  $("wake").hidden = false; wakeFailed = false;
  earShown = null; status(dormantHint());
  let stream = null, ctx = null, node = null, ws = null;
  const stale = () => gen !== earGen;
  const release = () => {
    stream?.getTracks().forEach(t => t.stop());
    node?.port.close(); node?.disconnect();
    ctx?.close().catch(() => {});
    if (ws) { ws.onclose = null; ws.onmessage = null; ws.close(); }
  };
  try {
    // The same constraints as the live call: Chrome applies one echo-cancellation setting per device.
    stream = await navigator.mediaDevices.getUserMedia(micConstraints());
    if (stale()) return release();
    try { ctx = new AudioContext({ sampleRate: 16000 }); } catch { ctx = new AudioContext(); }
    await ctx.audioWorklet.addModule(EAR_WORKLET_URL);
    if (stale()) return release();
    node = new AudioWorkletNode(ctx, "pcm16k");
    ctx.createMediaStreamSource(stream).connect(node);
    node.connect(ctx.destination);  // keeps the node pulled; it writes only silence
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ear?token=${encodeURIComponent(CFG.token)}`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = ({ data }) => {
      let m = {}; try { m = JSON.parse(data); } catch {}
      if (m.state === "waking") { serverState = "waking"; startLive(); }
    };
    ws.onclose = (e) => {
      if (earWs !== ws) return;
      stopEar();
      if (e.code === 4001) {
        started = false; $("start").disabled = true; $("stop").disabled = true; $("mute").disabled = true;
        setState("ended", "In use"); status("Listening moved to another tab.", true);
      }
    };
    node.port.onmessage = ({ data }) => { if (!muted && ws.readyState === 1) ws.send(data); };
    if (stale()) return release();
    earStream = stream; earCtx = ctx; earNode = node; earWs = ws;
  } catch (e) {
    release();
    if (!stale()) { listening = false; $("wake").hidden = true; status(`Could not listen on ${HERE}: ` + (e.message || e), true); }
  }
}
// A session.closed from GPT-Live is a drop unless the server put the call to sleep.
async function closedByServer() {
  if (finalized || leaving || !peer) return;
  leaving = true;
  let s = null;
  try { s = await (await fetch("/api/state", { headers: { "X-Talk-Token": CFG.token } })).json(); } catch {}
  if (s && s.state === "dormant") { serverState = "dormant"; await toDormant(); } else dropped();
  leaving = false;
}

$("start").onclick = () => {
  if (running || peer) return;
  started = true;
  if (muted && listening) toggleMute();  // waking by hand means you mean to talk
  if (serverState === "dormant" && !listening) toDormant(); else startLive();
};
$("wake").onclick = () => $("start").click();
async function startLive() {
  if (running || peer) return;
  const waking = serverState !== "live";
  stopEar(); leaving = false; wakeFailed = false; peerFailedStarts = knownFailedStarts;
  $("start").disabled = true; $("stop").disabled = false;  // End works while waking or connecting too
  setState(waking ? "waking" : "connecting", ""); status(waking ? "Waking the voice…" : "Connecting…");
  try {
    peer = new RTCPeerConnection();
    audioCtx = new AudioContext();
    peer.ontrack = (e) => {
      const stream = new MediaStream([e.track]);
      $("out").srcObject = stream; $("out").play().catch(() => status("Click anywhere to allow audio playback.", true));
      readers.push(levelOf(stream, v => outLevel = outLevel * 0.6 + v * 0.4));
    };
    closePreview(); $("checkmic").disabled = true; $("checkmic").title = "The call is using the microphone";
    mic = await navigator.mediaDevices.getUserMedia(micConstraints());
    mic.getAudioTracks()[0].enabled = !muted;
    mic.getAudioTracks()[0].onended = () => status("That microphone went away. Pick another one.", true);
    await listDevices();
    if ($("out").setSinkId) { try { await $("out").setSinkId($("spk").value); } catch (e) { console.warn(e); } }
    showInUse();
    if (mic.getAudioTracks()[0].getSettings().echoCancellation === false) status("This browser did not enable echo cancellation; use headphones.", true);
    micReader = readers.push(levelOf(mic, v => micLevel = micLevel * 0.6 + v * 0.4)) - 1;
    for (const t of mic.getAudioTracks()) peer.addTrack(t, mic);
    events = peer.createDataChannel("oai-events");
    events.onmessage = ({ data }) => {
      const ev = JSON.parse(data);
      if (ev.type === "session.started") {
        running = true; wasLive = true; $("stop").disabled = false; $("mute").disabled = false; $("start").disabled = true;
        tellMute();  // the server may still hold a mute from before a reload
        requestAnimationFrame(animate);
        fetch("/api/started", { method: "POST", headers: { "X-Talk-Token": CFG.token } });
      } else if (ev.type === "session.input_transcript.delta") caption("you", ev.delta);
      else if (ev.type === "session.output_transcript.delta") caption("tutor", ev.delta);
      else if (ev.type === "session.closed") closedByServer();
      else if (ev.type === "error") console.warn(ev);
    };
    events.onclose = closedByServer;
    const offer = await peer.createOffer(); await peer.setLocalDescription(offer);
    if (peer.iceGatheringState !== "complete") await new Promise((res) => {
      const t = setTimeout(res, 5000);
      peer.addEventListener("icegatheringstatechange", () => { if (peer.iceGatheringState === "complete") { clearTimeout(t); res(); } });
    });
    const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json", "X-Talk-Token": CFG.token },
      body: JSON.stringify({ sdp: peer.localDescription.sdp }) });
    const body = await r.json();
    if (!r.ok) { const err = new Error(body.error || ("HTTP " + r.status)); err.status = r.status; throw err; }
    await peer.setRemoteDescription({ type: "answer", sdp: body.transport.sdp });
  } catch (e) {
    if (ending) { teardownLive(); return; }  // End while half-open: release a microphone that opened late
    if (waking && CFG.dormancy) {  // the server is dormant again and keeps the wake words for the next try
      // A failure before the POST (the microphone, WebRTC) leaves the server waking, and the poll would
      // retry every tick: say it failed first. A no-op when the POST itself failed; that is dormant already.
      // After the POST the server closes the session it created; either way this peer is dropped here.
      teardownLive();
      try { await fetch("/api/wake-failed", { method: "POST", headers: { "Content-Type": "application/json", "X-Talk-Token": CFG.token },
        body: JSON.stringify({ reason: String(e.message || e) }) }); } catch {}
      serverState = "dormant"; await toDormant();
      if (listening) {  // toDormant() itself may have failed to reopen the ear; its own message then stands
        // The old session id is only cleared once fully closed: a 409 here just means try again shortly.
        const msg = e.status === 409 ? "The voice is still closing; try again in a few seconds." : String(e.message || e);
        wakeFailed = true; status(msg + ` Still listening on ${HERE}.`, true);
      }
    } else if (e.status === 410) { cleanup(); status(String(e.message || e), true); }  // the call is over
    else {  // no credit, a bad key, OpenAI down: say so, and leave Start ready for another try
      teardownLive();
      $("stop").disabled = true; $("start").disabled = false;
      $("checkmic").disabled = false; $("checkmic").title = "Check the microphone";
      setState("idle", "Start"); status(String(e.message || e), true);
    }
  }
}
async function abandonUnstarted(s) {
  const msg = "The voice did not start, so it was closed to stop billing.";
  knownFailedStarts = s.failed_starts;
  teardownLive();
  if (s.state === "dormant" && CFG.dormancy) {
    serverState = "dormant"; await toDormant();
    if (listening) { wakeFailed = true; status(msg + ` Still listening on ${HERE}.`, true); }
  } else { $("start").disabled = false; setState("idle", "Start"); status(msg, true); }
}
// A muted call has nothing to hear, so the server lets the paid session sleep once the voice has finished.
const tellMute = () => fetch("/api/mute", { method: "POST", headers: { "Content-Type": "application/json", "X-Talk-Token": CFG.token },
  body: JSON.stringify({ muted }) }).catch(() => {});
function toggleMute() {
  if (!running && !listening) return;
  muted = !muted;
  mic?.getAudioTracks().forEach(t => t.enabled = !muted);
  tellMute();
  setMuteUi();
}
$("mute").onclick = toggleMute;
// Ending takes two presses of End or Escape within 1.5 s, so a stray click or key never drops the call.
function armEnd(hint) {
  if (Date.now() - escAt < 1500) return true;
  escAt = Date.now(); $("stop").firstChild.textContent = "Again to end "; status(hint);
  setTimeout(() => {
    if (Date.now() - escAt < 1500) return;
    $("stop").firstChild.textContent = "End "; shown = null;  // the animation loop repaints the status
    paintBar();  // dormant has no animation loop to repaint the bar's own arming hint
  }, 1600);
  return false;
}
// Live, dormant, or half-open: waking or connecting has a peer but no started session yet.
const endable = () => running || listening || !!peer;
function endSession() {
  if (!endable()) return;
  ending = true;  // the poll must never reopen the mic/ear once End was pressed
  if (!running && peer) teardownLive();  // waking or connecting: drop the half-open peer and microphone
  escAt = 0; $("stop").firstChild.textContent = "End ";
  $("stop").disabled = true; status("Finishing…");
  fetch("/api/stop", { method: "POST", headers: { "X-Talk-Token": CFG.token } });
  closeTimer = setTimeout(() => cleanup("Ended."), 15000);
}
$("stop").onclick = () => { if (endable() && armEnd("Click End again to end the call.")) endSession(); };
document.addEventListener("keydown", (e) => {
  if (!$("devmenu").hidden && e.key === "Escape") { e.preventDefault(); closeMenu(); return; }
  if (e.target.tagName === "SELECT" || $("devices").contains(e.target)) return;
  if (e.code === "Space") { e.preventDefault(); if (!e.repeat) (running || listening) ? toggleMute() : $("start").click(); }
  if (e.key === "Escape" && !e.repeat && endable() && armEnd("Press Escape again to end the call.")) endSession();
});
// Links never navigate this tab away from a live call: they open in a new one.
// SVG links (mermaid) carry xlink:href, and their .href is not a string, so read the attribute.
document.addEventListener("click", (e) => {
  const a = e.target.closest?.("a"); if (!a) return;
  const href = a.getAttribute("href") || a.getAttributeNS("http://www.w3.org/1999/xlink", "href");
  if (!href || href.startsWith("#")) return;
  e.preventDefault();
  let url; try { url = new URL(href, location.href); } catch { return; }
  if (url.protocol === "http:" || url.protocol === "https:") window.open(url.href, "_blank", "noopener");
}, true);
window.addEventListener("beforeunload", (e) => { if ((running || peer || listening) && !finalized) { e.preventDefault(); e.returnValue = ""; } });
// GPT-Live bills an open session by the second, and closing the peer alone may not end it: tell it to
// close over the page's own data channel. Only on pagehide: after beforeunload the user may still stay.
function closeVoice() {
  try { if (events && events.readyState === "open") events.send(JSON.stringify({ type: "session.close" })); } catch {}
}
window.addEventListener("pagehide", () => { if (peer) closeVoice(); });
// A dead talk.py cannot close the session for the page. After 20 s of failed polls with a peer open,
// the page closes it itself, then tears the call down: nothing it could do next reaches the server.
// A shorter outage (a laptop waking, a busy server) keeps the call.
const LOST_CONTACT = "Lost contact with the talk server; the voice was closed to stop billing.";
let pollFails = 0, pollFailSince = 0;
function pollFailed() {
  const now = performance.now();
  if (!pollFails++) pollFailSince = now;
  if (!peer || finalized || pollFails < 3 || now - pollFailSince < 20000) return;
  finalized = true;
  closeVoice();
  mic?.getTracks().forEach(t => t.stop());
  status(LOST_CONTACT, true);
  setTimeout(() => { cleanup(); status(LOST_CONTACT, true); }, 500);  // lets session.close leave first
}
// One poll at a time: requests stacked on a hung server would take the browser's few connections to it
// and starve /api/session.
let polling = false;
setInterval(async () => {
  if (polling) return;
  polling = true;
  try { await poll(); } finally { polling = false; }
}, 700);
async function poll() {
  let r = null;
  try { r = await fetch("/api/state", { headers: { "X-Talk-Token": CFG.token }, signal: AbortSignal.timeout(4000) }); } catch {}
  if (!r || (!r.ok && r.status !== 403)) { pollFailed(); return; }
  pollFails = 0;
  try {
    if (r.status === 403) { if (!finalized) { finalized = true; cleanup("This call has ended. Ask the Claude session for the current link."); } return; }
    const s = await r.json();
    thinking = !!s.thinking; renderWork(s);
    paintCost(s.cost);
    serverState = s.state || "live";
    if (peer && !running && !ending && !finalized && s.failed_starts > peerFailedStarts) abandonUnstarted(s);
    else if (!peer) knownFailedStarts = s.failed_starts || 0;
    // A live-minute cap: wakes are refused from now on, and the page says why instead of the ear's hint.
    if (s.cap && listening && s.cap !== capShown) { capShown = s.cap; wakeFailed = true; status(s.cap, true); }
    const heard = s.heard || [];
    $("heard").hidden = !listening || !heard.length;
    $("heard").textContent = heard.length ? "Heard: " + heard[heard.length - 1] : "";
    if (listening && s.ear !== earShown && !wakeFailed) {
      earShown = s.ear; earWhy = s.ear_error || ""; status(earText(s.ear, earWhy), s.ear === "failed");
    }
    // The ear socket pushes a wake at once; the poll backs it up if that message was lost. Neither
    // branch may fire once End was pressed or the call is over, or a closed page reopens the mic.
    // A sleep whose session.close GPT-Live never confirmed: the server has gone dormant, but this page
    // still holds the WebRTC peer, which can keep a paid voice open. Drop it as a sleep would.
    if (s.state === "dormant" && peer && running && !leaving && !finalized && !ending) closedByServer();
    else if (s.state === "waking" && listening && !ending && !s.done) startLive();
    else if (s.state === "dormant" && started && !listening && !peer && !finalized && !leaving && !ending && !s.done) toDormant();
    if (!running && !peer && !finalized && !listening && serverState === "live") {
      if (s.rejoinable) {
        $("start").disabled = false; setState("listening", "Rejoin");
        status(`Connection lost. Press Rejoin within ${s.rejoin_seconds} s to carry on the same call.`, true);
      } else if (s.session_live && !wasLive) {
        $("start").disabled = true; setState("ended", "In use");
        status("This call is live in another tab. Use that tab, or end it there first.", true);
      } else if (["In use", "Rejoin"].includes($("orblabel").textContent)) {
        // Nothing left to rejoin and nobody else holds the call: back to a clean Start.
        $("start").disabled = false; setState("idle", "Start"); status("");
      }
    }
    if (s.notes.length !== $("notes").children.length) {
      $("notes").innerHTML = ""; s.notes.forEach(n => { const c = document.createElement("span"); c.className = "chip"; c.textContent = "Note · " + n; $("notes").append(c); });
    }
    if (s.done && !finalized) { finalized = true; cleanup("Session ended: " + s.ended + ". You can close this tab."); }
  } catch {}
}
</script></body></html>
"""


def hurry_on_signals(loop) -> asyncio.Event:
    """From the shutdown on, a signal cuts its waits short instead of being swallowed."""
    hurry = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, hurry.set)
    return hurry


def build_app(args, topic: str, log: SessionLog, ctl: "LiveController", token: str, call_id: str,
              stage_url: str | None = None):
    from aiohttp import web

    def authorised(request) -> bool:
        return secrets.compare_digest(request.headers.get("X-Talk-Token", ""), token)

    async def gone(request):
        return web.Response(text=GONE_PAGE, status=404, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def page(request):
        if not secrets.compare_digest(request.match_info.get("call", ""), call_id):
            return await gone(request)
        config = {"topic": topic, "token": token,
                  "inputDevice": args.input_device, "outputDevice": args.output_device, "stageUrl": stage_url,
                  "mode": args.mode, "dormancy": args.dormant_after > 0, "state": ctl.state,
                  "wakeName": args.name if args.wake == "name" else None, "llmMode": args.llm}
        html = PAGE.replace("__CONFIG__", json.dumps(config).replace("</", "<\\/"))
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def create_session(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        if ctl.session_id or ctl.done.is_set():
            return web.json_response({"error": "this run already has a session; start talk again"}, status=409)
        body = await request.json()
        sdp = body.get("sdp", "") if isinstance(body, dict) else ""
        if not sdp.strip() or len(sdp) > 65536:
            return web.json_response({"error": "an SDP offer is required"}, status=400)
        status_code, payload = await ctl.create(sdp)
        return web.json_response(payload, status=status_code)

    async def started(request):
        if authorised(request):
            asyncio.create_task(ctl.greet())
        return web.json_response({})

    async def wake_failed(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        body = await request.json()
        reason = str(body.get("reason", "")) if isinstance(body, dict) else ""
        return web.json_response({"dormant": ctl.wake_failed(reason)})

    async def mute(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        ctl.muted = bool(body.get("muted")) if isinstance(body, dict) else False
        return web.json_response({"muted": ctl.muted})

    async def stop_session(request):
        if authorised(request):
            if log.end_reason == "stopped":
                log.end_reason = "ended from the page"
            asyncio.create_task(ctl.close())
        return web.json_response({})

    async def state(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        body = {"notes": log.notes, "done": ctl.done.is_set(), "ended": log.end_reason,
                "thinking": ctl.thinking or bool(ctl.turns and ctl.turns.working),
                "session_live": ctl.session_live, "rejoinable": ctl.rejoinable,
                "rejoin_seconds": max(0, round(ctl.rejoin_until - time.time())) if ctl.rejoinable else 0,
                "state": ctl.state, "heard": ctl.heard_recent[-3:], "ear": ctl.ear.status if ctl.ear else None,
                "ear_error": getattr(ctl.ear, "error", "") if ctl.ear else "",
                "wake_name": ctl.args.name if ctl.args.wake == "name" else None, "cost": ctl.cost_view(),
                "failed_starts": ctl.failed_starts, "cap": ctl.refresh_cap()}
        body.update(ctl.work_state())
        return web.json_response(body)

    async def ear_socket(request):
        """Binary PCM frames (16 kHz mono 16-bit) from the page while the call is dormant. A browser
        WebSocket cannot send headers, so the token comes as a query parameter."""
        if not secrets.compare_digest(request.query.get("token", ""), token):
            return web.json_response({"error": "forbidden"}, status=403)
        if ctl.ear is None:
            return web.json_response({"error": "local listening is off for this call"}, status=404)
        if ctl.call_over:
            return web.json_response({"error": "the call has ended"}, status=410)
        if ctl.state == "live":
            return web.json_response({"error": "the call is live; its audio goes to GPT-Live"}, status=409)
        ws = web.WebSocketResponse(max_msg_size=1 << 16, heartbeat=20)
        await ws.prepare(request)
        ctl.ear_opened(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.BINARY and ws is ctl.ear_ws:
                    ctl.ear.feed(msg.data)
        finally:
            ctl.ear_closed(ws)
        return ws

    async def next_turn(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        if not ctl.turns:
            return web.json_response({"error": "not in session mode"}, status=404)
        wait = min(max(float(request.query.get("wait", "25")), 0.0), 60.0)
        event = await ctl.turns.next(timeout=wait)
        if event is None:
            return web.Response(status=204)
        if event["type"] == "superseded":
            return web.json_response({"error": "a newer doorbell is waiting"}, status=409)
        if request.transport is None or request.transport.is_closing():
            ctl.turns.put_back(event)
            return web.Response(status=499)
        if event["type"] == "turn":
            ctl.activity = []
        return web.json_response(event)

    async def activity(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        body = await request.json()
        return web.json_response({"recorded": ctl.record_activity(body if isinstance(body, dict) else {})})

    async def post_reply(request):
        if not authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        if not ctl.turns:
            return web.json_response({"error": "not in session mode"}, status=404)
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"error": "a JSON object is required"}, status=400)
        if body.get("status") and body.get("end"):
            return web.json_response({"error": "a status cannot end the call; send the wrap-up with end"},
                                     status=400)
        if ctl.call_over:
            return web.json_response({"error": "the call has ended"}, status=410)
        problems_from = len(ctl.board.problems)
        result = await ctl.answer(str(body.get("id", "")), text=str(body.get("text", "")),
                                  status=str(body.get("status", "")), end=bool(body.get("end")))
        await ctl.stage_settled()
        if result == "unknown":
            return web.json_response({"error": "no such turn in this call"}, status=404)
        if result == "superseded":
            return web.json_response({"error": "superseded"}, status=409)
        if result == "ignored":
            return web.json_response({"ok": True, "ignored": "the turn was already answered, or the call is asleep; "
                                                             "status not spoken"})
        if result == "ended":
            return web.json_response({"ok": True, "ended": "the call was asleep; the wrap-up is only in the transcript"})
        if result.startswith("held:"):
            return web.json_response({"ok": True, "held": {
                "held:waking": "the call was asleep; it is waking to say this",
                "held:connecting": "the voice is connecting; it says this as soon as it is on",
                "held:later": "no session can say it now; it is kept for the next wake or rejoin",
            }[result]})
        if result == "dropped":
            return web.json_response({"error": dropped_reply_message(ctl.capped)}, status=423)
        return web.json_response({"ok": True, "board_problems": ctl.board.problems[problems_from:]})

    app = web.Application(client_max_size=1 << 17)
    app.add_routes([
        web.get("/", gone),
        web.get("/c/{call}", page),
        web.post("/api/session", create_session),
        web.post("/api/started", started),
        web.post("/api/stop", stop_session),
        web.post("/api/mute", mute),
        web.post("/api/wake-failed", wake_failed),
        web.get("/api/state", state),
        web.get("/api/ear", ear_socket),
        web.get("/api/turn", next_turn),
        web.post("/api/reply", post_reply),
        web.post("/api/activity", activity),
    ])
    return app


async def serve(args, topic: str, brief: str, log: SessionLog) -> None:
    import aiohttp
    from aiohttp import web

    # The same folder `stage.py show` falls back to (the git root), so both reach one stage.
    stage_cwd = str(args.code) if args.code else stage_mod.repo_root(Path.cwd())
    try:
        stage_row = stage_mod.ensure_stage(stage_cwd, title=f"Talk · {topic}")
    except stage_mod.DAEMON_ERRORS + (RuntimeError, ValueError) as err:  # RuntimeError: a refusal
        raise SystemExit(f"talk needs the webcompanion daemon for its stage: {err}")
    stage_url = rebase(stage_row["url"], args.stage_base)

    token = secrets.token_urlsafe(24)
    http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15))
    brain = None if args.llm == "session" else build_brain(args, topic, brief, log.out_dir)
    ctl = LiveController(args, topic, brief, log, brain, http)
    ctl.stage_cwd = stage_cwd
    if args.dormant_after > 0:
        ctl.ear = ear_mod.Ear(on_segment=ctl.hear, on_note=log.aside)
    stop = asyncio.Event()
    call_id = secrets.token_urlsafe(16)
    app = build_app(args, topic, log, ctl, token, call_id, stage_url=stage_url)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", args.port)
    await site.start()
    if ctl.turns:
        write_state_file(args.port, token, log.out_dir, f"/c/{call_id}")

    url = f"http://127.0.0.1:{args.port}/c/{call_id}"
    say(f"Open {url} and press Start. (Local port {args.port}; from another machine, reach this port "
        f"through a reverse proxy or tailnet name, keeping the /c/<call id> path.)")
    say(f"Stage {stage_url} (folder {stage_cwd})")
    if not args.no_open:
        webbrowser.open(url)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, stop.set)

    async def connect_deadline():
        await asyncio.sleep(CONNECT_TIMEOUT_MIN * 60)
        if ctl.never_started:
            log.end_reason = f"nobody pressed Start within {CONNECT_TIMEOUT_MIN} min"
            stop.set()

    deadline = asyncio.create_task(connect_deadline())
    done_wait = asyncio.create_task(ctl.done.wait())
    stop_wait = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({done_wait, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set() and not ctl.done.is_set():
            if log.end_reason == "stopped":
                log.end_reason = "interrupted"
            await ctl.close(wait=4)
        await asyncio.sleep(2.5)  # let the page see the final state
    finally:
        # Every create and close in flight settled, then the footer's figures; another signal stops the wait.
        await ctl.wind_down(hurry=hurry_on_signals(loop))
        log.dormant_seconds = ctl.dormant_seconds_total()  # log.finish() runs after ctl is gone
        for t in (deadline, done_wait, stop_wait):
            t.cancel()
        for t in (ctl.task, ctl.rejoin_task, ctl.dormant_task, ctl.away_task, ctl.start_task):
            if t and not t.done():
                t.cancel()
        ctl.hand_over_end()
        if ctl.turns:
            # A doorbell already waiting gets the end at once; a few seconds more cover one re-arming now.
            try:
                await asyncio.wait_for(ctl.turns.end_collected.wait(), 5)
            except asyncio.TimeoutError:
                pass
            remove_state_file(args.port)
        ctl.stage_pool.shutdown(wait=False, cancel_futures=True)
        if ctl.ear:
            ctl.ear.close()
        await http.close()
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Doctor: keys, OpenAI model access, one Claude reply. No audio is touched.
# ---------------------------------------------------------------------------


def http_status(url: str, headers: dict[str, str]) -> int:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def openai_doctor_line(status: int) -> tuple[bool, str]:
    """The models endpoint answers 200 with no credit on the account, so the doctor cannot say it has any."""
    if status == 200:
        return True, f"{LIVE_MODEL} access (credit not checked — see {BILLING_URL})"
    return False, f"OpenAI key + {LIVE_MODEL} access: HTTP {status}"


def doctor(args) -> int:
    ok = True

    def report(passed: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        say(f"[{'ok' if passed else 'FAIL'}] {label}{': ' + detail if detail else ''}")

    say(f"keys file: {KEYS_FILE}")
    say("OpenAI key: " + ("TALK_OPENAI_API_KEY, this tool's own" if os.environ.get("TALK_OPENAI_API_KEY")
                          else "OPENAI_API_KEY, shared with other tools"))
    if key := os.environ.get("OPENAI_API_KEY"):
        status = http_status(f"{OPENAI_API}/models/{LIVE_MODEL}", {"Authorization": f"Bearer {key}"})
        report(*openai_doctor_line(status))
    else:
        report(False, "OPENAI_API_KEY", f"missing. Create a project key at https://platform.openai.com/api-keys "
               f"and add a line OPENAI_API_KEY=... to {KEYS_FILE}")

    started = time.time()
    try:
        brain = build_brain(args, "a doctor check", "", SESSIONS_DIR / "_doctor")

        async def one_reply() -> str:
            return "".join([t async for t in brain.stream("Reply with just the word ready.")])

        if args.llm == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
            report(False, "ANTHROPIC_API_KEY", f"missing from {KEYS_FILE} and the environment "
                   "(https://console.anthropic.com/settings/keys), or run with --llm claude-code")
        else:
            reply = asyncio.run(one_reply()).strip()
            report(bool(reply), f"Claude ({args.model} via {args.llm})",
                   f"replied {reply[:40]!r} in {time.time() - started:.1f}s")
    except Exception as err:
        report(False, f"Claude ({args.model} via {args.llm})", str(err)[:200])

    problem = stage_mod.daemon_status()
    report(problem is None, "webcompanion daemon (the stage)", problem or "")

    for line in ear_doctor_lines() + caps_doctor_lines(args):
        say(line)

    say(f"normalisation: {speakable('Set it to EXTERNAL_ONLY or SEND_PROPOSAL_AND_SHARE.')!r}")
    say("audio: handled by the browser page (WebRTC with echo cancellation); pick devices there")
    say("all checks passed" if ok else "some checks failed")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def minutes_type(env: str):
    """A positive number of minutes; a bad value (from the flag or from `env`) is a usage error."""
    def parse(value: str) -> float:
        try:
            minutes = float(value)
        except ValueError:
            minutes = float("nan")
        if not minutes > 0 or minutes == float("inf"):
            raise argparse.ArgumentTypeError(
                f"{value!r} is not a positive number of minutes (check the flag, or {env} in the environment)")
        return minutes
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full-duplex voice discussion: GPT-Live is the voice, Claude is the brain."
    )
    parser.add_argument("--topic", help="what to discuss")
    parser.add_argument("--brief", type=Path, help="markdown briefing Claude treats as ground truth")
    parser.add_argument("--code", type=Path, help="a code folder Claude may read and search during the "
                        "session and show on the page's board (needs --llm claude-code or session)")
    parser.add_argument("--out", type=Path, help=f"session output directory (default under {SESSIONS_DIR})")
    parser.add_argument("--model", default=os.environ.get("TALK_MODEL", DEFAULT_MODEL), help="Claude model")
    parser.add_argument(
        "--llm", choices=["api", "claude-code", "session"], default=os.environ.get("TALK_LLM", "claude-code"),
        help="claude-code: your logged-in claude CLI (default); api: ANTHROPIC_API_KEY with prompt caching; "
             "session: the Claude Code session that launched this answers through talk_client.py",
    )
    parser.add_argument("--voice", default=os.environ.get("TALK_VOICE", DEFAULT_VOICE),
                        help="GPT-Live voice, e.g. marin, cedar, meridian, gleam, vesper (default marin)")
    parser.add_argument("--input-device", default=os.environ.get("TALK_INPUT_DEVICE"),
                        help="microphone to preselect in the page: index or part of its name")
    parser.add_argument("--output-device", default=os.environ.get("TALK_OUTPUT_DEVICE"),
                        help="speakers to preselect in the page: index or part of its name")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TALK_PORT", DEFAULT_PORT)))
    parser.add_argument("--stage-base", default=os.environ.get("TALK_STAGE_BASE"),
                        help="the webcompanion daemon's address as reached from the browser "
                             "(scheme and host, e.g. https://wc.example); default: the daemon's own")
    parser.add_argument("--no-open", action="store_true", help="don't open the page in the default browser")
    parser.add_argument("--max-minutes", type=int, default=None, help="default 60, or 120 with --mode meeting")
    parser.add_argument("--max-live-minutes", type=minutes_type("TALK_MAX_LIVE_MINUTES"),
                        default=os.environ.get("TALK_MAX_LIVE_MINUTES") or str(DEFAULT_MAX_LIVE_MINUTES),
                        help=f"paid GPT-Live minutes this call may use, each session counted at least 15 s; then "
                             f"the call goes dormant and refuses to wake (default {DEFAULT_MAX_LIVE_MINUTES})")
    parser.add_argument("--daily-live-minutes", type=minutes_type("TALK_DAILY_LIVE_MINUTES"),
                        default=os.environ.get("TALK_DAILY_LIVE_MINUTES") or str(DEFAULT_DAILY_LIVE_MINUTES),
                        help=f"paid GPT-Live minutes all calls on this machine may use per calendar day, kept "
                             f"in {LEDGER_FILE} (default {DEFAULT_DAILY_LIVE_MINUTES})")
    parser.add_argument("--idle-minutes", type=int, default=5,
                        help="with --dormant-after 0, end a call after this long without speech; with "
                             "dormancy, a turn the brain has not collected for this long stops keeping it live")
    parser.add_argument("--mode", choices=["talk", "meeting"], default="talk",
                        help="meeting: start dormant, wake only on --name, answer only when asked (/meet)")
    parser.add_argument("--dormant-after", type=int, default=None, metavar="SECONDS",
                        help="close the GPT-Live session after this long without speech and listen on this "
                             "machine for free until spoken to (default 45, 20 with --mode meeting; 0 = never)")
    parser.add_argument("--wake", choices=["speech", "name"], default=None,
                        help="what wakes a dormant call: any speech of two words or more (talk's default), "
                             "or the --name (meeting's default)")
    parser.add_argument("--name", default="Nova", help="the wake name for --wake name (default Nova)")
    parser.add_argument("--sounds-like", default="",
                        help='comma-separated spellings the recognizer may produce for the name, e.g. "Noa,Nover"')
    parser.add_argument("--doctor", action="store_true", help="check keys, OpenAI access and one Claude reply")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.code:
        args.code = args.code.expanduser().resolve()
        if not args.code.is_dir():
            parser.error(f"--code: not a folder: {args.code}")

    load_keys()
    if args.doctor:
        return doctor(args)

    if problem := apply_mode(args):
        say(problem)
        return 2

    if missing := missing_keys(args.llm):
        say(f"Missing API keys: {', '.join(missing)}. Add them to {KEYS_FILE} and run again.")
        return 2
    if not args.topic:
        parser.error("--topic is required")

    brief = args.brief.read_text() if args.brief else ""
    out_dir = args.out or SESSIONS_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(args.topic)}"
    brain_label = "this Claude Code session" if args.llm == "session" else f"{args.model} via {args.llm}"
    log = SessionLog(out_dir, args.topic,
                     f"talk · {LIVE_MODEL} voice {args.voice} · brain {brain_label}")
    try:
        asyncio.run(serve(args, args.topic, brief, log))
    except KeyboardInterrupt:
        log.end_reason = "interrupted"
    except OSError as err:
        log.end_reason = f"error: {err}"
        say(f"Error: {err}. Is port {args.port} already in use? Try --port.")
    finally:
        summary = log.finish()
        say("SESSION_SUMMARY " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
