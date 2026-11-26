"""Reading Claude Code transcripts: the readers the session index's one parser is built on, and the headless calls
that describe a session, answer a question from it and search descriptions by meaning.

The session index (fleet/docs/session-index.md) is the one list of sessions. This module keeps no list: the
`conversations` table it once filled is left on disk untouched (the importer reads it once), and nothing writes or
reads it as a source any more (phase 3). Transcripts stay where Claude Code put them; this module only reads them.
Stdlib only, Python 3.9+.
"""
import json
import os
import re
import shlex
import subprocess
import tempfile
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  session_id TEXT PRIMARY KEY, cwd TEXT, transcript_path TEXT,
  started_at REAL, last_seen_at REAL, ended_at REAL, end_reason TEXT,
  manual_name TEXT, name_custom TEXT, name_ai TEXT, name_agent TEXT, first_prompt TEXT,
  description TEXT, described_size INTEGER, described_at REAL, describe_error TEXT, describe_tried_at REAL,
  origin TEXT, unreadable INTEGER);
CREATE INDEX IF NOT EXISTS conversations_cwd ON conversations(cwd);
"""

HEAD_BYTES = 256 * 1024     # the first prompt is near the top
HEAD_LINE_MAX = 16 * 1024 * 1024  # most that is read of a first line longer than HEAD_BYTES
TAIL_BYTES = 1024 * 1024    # a name is restated every turn, so the end of the file has the newest
DESCRIBE_LIMIT = 10         # sessions `fleet history describe` describes in one run
SETTLED = 600               # seconds a transcript must be quiet before it is described in a batch
SEARCH_MAX = 10
SEARCH_BUDGET = 150000      # characters of descriptions one search call reads
ASK_BUDGET = 80000          # characters of transcript one ask call reads

MACHINE_PREFIXES = ("<task-notification>", "<system-reminder>", "<local-command-", "<bash-input>", "<bash-stdout>",
                    "<bash-stderr>", "<user-prompt-submit-hook>")
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
NAME_KEYS = (("custom-title", "customTitle", "name_custom"), ("ai-title", "aiTitle", "name_ai"),
             ("agent-name", "agentName", "name_agent"))


class HistoryError(Exception):
    pass


# ---------------------------------------------------------------- reading a transcript

def clip(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "..."


def message_text(msg):
    """The text of a message, or None when it is a tool result (those outnumber real prompts many to one)."""
    content = msg.get("content")
    if isinstance(content, str):
        return _REMINDER.sub("", content) or None
    if not isinstance(content, list):
        return None
    parts = []
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_result":
            return None
        if b.get("type") == "text":
            parts.append(_REMINDER.sub("", b.get("text") or ""))
    return "".join(parts) or None


def human_prompt(rec):
    """What a person typed, or None when the record is anything else (a tool result, a side thread, machine text)."""
    if rec.get("type") != "user" or rec.get("isSidechain") or rec.get("isMeta"):
        return None
    msg = rec.get("message")
    text = (message_text(msg) or "").strip() if isinstance(msg, dict) else ""
    if not text:
        return None
    if "<command-name>" in text:
        m = _COMMAND_NAME.search(text)
        if not m or not m.group(1).strip():
            return None
        a = _COMMAND_ARGS.search(text)
        return m.group(1).strip() + (" " + " ".join(a.group(1).split()) if a and a.group(1).strip() else "")
    if text.startswith(MACHINE_PREFIXES) or text.startswith("<"):
        return None  # an unknown tag is more likely a record type we have not seen than a prompt
    return " ".join(text.split())


def assistant_text(rec):
    if rec.get("type") != "assistant" or rec.get("isSidechain"):
        return None
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return None
    t = " ".join(" ".join((b.get("text") or "").split()) for b in content
                 if isinstance(b, dict) and b.get("type") == "text").strip()
    return t or None


def records(path, head=None, tail=None):
    """Records of a transcript. With head or tail, only that many bytes from that end (a torn line is dropped);
    a malformed line is skipped, since a live transcript's last line is often half written."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if tail is not None and size > tail:
                f.seek(size - tail)
                f.readline()
                data = f.read()
            elif head is not None and size > head:
                data = f.read(head)
                if b"\n" in data:
                    data = data[:data.rfind(b"\n") + 1]
                else:  # one long first line: read to its end, or it would be dropped whole
                    data += f.readline(HEAD_LINE_MAX)
            else:
                data = f.read()
    except OSError:
        return
    for line in data.splitlines():
        if line.strip():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def newest_names(recs):
    """{column: name}: for each kind of name the newest non-blank one in the records."""
    out = {}
    for rec in recs:
        for rtype, key, col in NAME_KEYS:
            v = rec.get(key) if rec.get("type") == rtype else None
            if isinstance(v, str) and v.strip():
                out[col] = v.strip()
    return out


def conversation(path):
    """The whole transcript read once: {prompts, replies, names}."""
    prompts, replies, names = [], [], {}
    for rec in records(path):
        names.update(newest_names([rec]))
        p = human_prompt(rec)
        if p:
            prompts.append(p)
        else:
            a = assistant_text(rec)
            if a:
                replies.append(a)
    return {"prompts": prompts, "replies": replies, "names": names}


def turns(path):
    """The transcript as ordered (who, text) turns."""
    out = []
    for rec in records(path):
        p = human_prompt(rec)
        if p:
            out.append(("person", p))
            continue
        a = assistant_text(rec)
        if a:
            out.append(("claude", a))
    return out


# ---------------------------------------------------------------- recognising a transcript
#
# The transcript format is Claude Code's and not documented. When an update changes it, every read here would
# quietly find nothing, so a transcript that holds records but none this module can use is reported: the recorder
# hook (fleet_index_hook) logs it to hooks.log and keeps it in index/unreadable.json, and `fleet history ls` and
# `fleet sessions` warn.

CONVERSATION_TYPES = ("user", "assistant")
BIG_ENOUGH = 2048  # bytes: a smaller file may only hold the session's first bookkeeping records


def unreadable_reason(path):
    """Why nothing can be read from this transcript, or None when it is fine, empty, or too small to tell."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size == 0:
        return None
    typed = convo = used = 0
    for rec in records(path, head=HEAD_BYTES):
        if not isinstance(rec.get("type"), str):
            continue
        typed += 1
        if rec["type"] in CONVERSATION_TYPES and not rec.get("isSidechain"):
            convo += 1
        if human_prompt(rec) or assistant_text(rec) or newest_names([rec]):
            used += 1
    if typed == 0 and size >= 64:
        why = "no line is a JSON record with a type"
    elif typed and not convo and size >= BIG_ENOUGH:
        why = "%d records but no user or assistant record" % typed
    elif convo >= 2 and not used:
        why = "%d user/assistant records but no prompt, reply or name could be read from them" % convo
    else:
        return None
    return "cannot read %s (%d bytes): %s. Has the transcript format changed?" % (path, size, why)


# ---------------------------------------------------------------- headless calls

def headless(prompt, model, timeout=180):
    """One `claude -p` call with the prompt on stdin. FLEET_CLAUDE_BIN replaces the binary. It leaves no session
    behind and FLEET_NO_RECORD keeps the recording hook from noting it."""
    cmd = [os.environ.get("FLEET_CLAUDE_BIN") or "claude", "-p", "--model", model, "--no-session-persistence",
           "--tools", "", "--strict-mcp-config"]  # no tools: it reads transcript text, which can hold instructions
    cmd += shlex.split(os.environ.get("FLEET_CLAUDE_ARGS") or "")
    env = dict(os.environ, FLEET_NO_RECORD="1")
    env.pop("FLEET_JOIN_NAME", None)
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env,
                           cwd=tempfile.gettempdir())
    except (OSError, subprocess.SubprocessError) as e:
        raise HistoryError("fleet: could not run %s: %s" % (cmd[0], e))
    if r.returncode != 0:
        raise HistoryError("fleet: claude -p failed (exit %d): %s" % (r.returncode, (r.stderr or r.stdout).strip()[:300]))
    return r.stdout


def describe_prompt(cwd, prompts, replies):
    ps, used = [], 0
    for i, p in enumerate(prompts):
        t = "%d. %s" % (i + 1, clip(p, 600))
        if used + len(t) > 12000:
            break
        ps.append(t)
        used += len(t)
    picks = replies if len(replies) <= 6 else replies[:3] + replies[-3:]
    rs, used = [], 0
    for r in picks:
        t = "- " + clip(r, 300)
        if used + len(t) > 3000:
            break
        rs.append(t)
        used += len(t)
    return "\n".join(
        ["Below is a Claude Code session: the folder it ran in, what the person typed, and a few of Claude's replies.",
         "Describe what the session was about in two or three plain sentences, for someone searching their history later.",
         "Say which project it concerned, what the person was trying to do, and what was produced or decided.",
         "Name the specific things involved: products, tickets, tools, files. Answer with the sentences only.",
         "", "Folder: %s" % (cwd or "unknown"), "", "What the person typed:"] + ps
        + (["", "Some of Claude's replies:"] + rs if rs else []))


def describe_transcript(path, cwd=None):
    """Describe one session from its transcript now (one headless call), whatever its state; returns the
    description, at most 800 characters. `fleet session describe` runs it on the row's machine and journals it."""
    if not path or not os.path.exists(path):
        raise HistoryError("fleet: the transcript is not on this machine.")
    c = conversation(path)
    if not c["prompts"]:
        raise HistoryError("fleet: the session has no prompt to describe.")
    model = os.environ.get("FLEET_DESCRIBE_MODEL") or "haiku"
    text = " ".join(headless(describe_prompt(cwd, c["prompts"], c["replies"]), model, 180).split())
    if len(text) < 20:
        raise HistoryError("the model gave no description")
    return clip(text, 800)


# ---------------------------------------------------------------- ask and search

def ask_prompt(cwd, question, ts):
    """The transcript's turns within ASK_BUDGET characters: when it is longer, the start and the end are kept."""
    lines = ["%s: %s" % (who, clip(t, 1500)) for who, t in ts]
    if sum(len(x) for x in lines) > ASK_BUDGET:
        head, tail, used = [], [], 0
        for x in lines[:len(lines) // 2 + 1]:
            if used + len(x) > ASK_BUDGET // 2:
                break
            head.append(x)
            used += len(x)
        used = 0
        for x in reversed(lines[len(head):]):
            if used + len(x) > ASK_BUDGET // 2:
                break
            tail.insert(0, x)
            used += len(x)
        lines = head + ["[... %d turns left out ...]" % (len(lines) - len(head) - len(tail))] + tail
    return "\n".join(
        ["Below is the transcript of a past Claude Code session (folder: %s). Answer the question from it alone."
         % (cwd or "unknown"), "If the transcript does not say, say so. Be brief and concrete.", "",
         "Question: %s" % question, "", "Transcript:"] + lines)


def ask_transcript(path, cwd, question):
    """Answer `question` from the transcript at `path` with one headless call."""
    if not (question or "").strip():
        raise HistoryError("fleet: ask needs a question.")
    if not path or not os.path.exists(path):
        raise HistoryError("fleet: the transcript is not on this machine (%s)." % (path or "no path"))
    ts = turns(path)
    if not ts:
        raise HistoryError("fleet: the transcript holds no conversation.")
    out = headless(ask_prompt(cwd, question.strip(), ts), os.environ.get("FLEET_ASK_MODEL") or "sonnet", 180).strip()
    if not out:
        raise HistoryError("fleet: the model gave no answer.")
    return out


def search_prompt(query, entries):
    return "\n".join(
        ["You help a person find one of their past Claude Code sessions.",
         "Below, each line is a session: its number, the date it was last active, the folder it ran in, and a description.",
         "Pick the sessions that match what the person is looking for, best match first, at most %d." % SEARCH_MAX,
         "Match on meaning, not wording: they describe the session from memory, in their own words.",
         "Include a session only if it plausibly is the one they mean; return fewer, or none, rather than pad.",
         'Answer with JSON only: an array of {"n": <session number>, "why": "<one short sentence on why it matches>"}.',
         "", "They are looking for: %s" % query, "", "Sessions:"]
        + ["[%d] %s %s: %s" % (i + 1, e["date"], e["folder"], e["description"]) for i, e in enumerate(entries)])


def parse_search(text, n):
    """The model's JSON array (a sentence or fence around it is fine), as [(index, why)]: unknown numbers and
    repeats dropped."""
    raw, dec = [], json.JSONDecoder()
    for m in re.finditer(r"\[", text):  # the first array that decodes and looks like hits; brackets in prose are skipped
        try:
            val, _ = dec.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(val, list) and any(isinstance(h, dict) and "n" in h for h in val):
            raw = val
            break
    seen, out = set(), []
    for h in raw if isinstance(raw, list) else []:
        i = h.get("n") if isinstance(h, dict) else None
        if isinstance(i, int) and 1 <= i <= n and i not in seen:
            seen.add(i)
            out.append((i - 1, str(h.get("why") or "")))
    return out[:SEARCH_MAX]


def search(query, rows):
    """Sessions of `rows` that match `query` by meaning: one call reads every description (newest first, within the
    budget) and names the best matches. `rows` are the session index's rows (`sid`, `cwd`, `description`, `updated`,
    `started`). -> {hits: [{row, why}], described, total}."""
    if not (query or "").strip():
        raise HistoryError("fleet: search needs words to look for.")
    rows = sorted(rows, key=lambda r: r.get("updated") or r.get("started") or 0, reverse=True)
    described = [r for r in rows if r.get("description")]
    entries, used = [], 0
    for r in described:
        e = {"row": r, "date": time.strftime("%Y-%m-%d", time.localtime(r.get("updated") or r.get("started") or 0)),
             "folder": r.get("cwd") or "", "description": r["description"]}
        used += len(e["description"]) + len(e["folder"]) + 20
        if used > SEARCH_BUDGET:
            break
        entries.append(e)
    if not entries:
        return {"hits": [], "described": 0, "total": len(rows)}
    out = headless(search_prompt(query.strip(), entries), os.environ.get("FLEET_ASK_MODEL") or "sonnet", 180)
    hits = [{"row": entries[i]["row"], "why": why} for i, why in parse_search(out, len(entries))]
    return {"hits": hits, "described": len(described), "total": len(rows)}
