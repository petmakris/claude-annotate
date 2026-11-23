"""Session history: every Claude Code session this machine has run, kept in the fleet store.

A plugin hook records each session (id, folder, names, times, transcript path). Transcripts stay where Claude
Code put them; this module only reads them. A short description per session, written on demand by one headless
call, is what search by meaning reads. Stdlib only, Python 3.9+. fleet.py owns the CLI and the page.
"""
import json
import os
import re
import shlex
import sqlite3
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
SETTLED = 600               # seconds a transcript must be quiet before it is described
RETRY = 3600                # seconds before a failed description is tried again
DESCRIBE_LIMIT = 10
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
# quietly find nothing, so a transcript that holds records but none this module can use is reported: `record`
# raises (the hook logs it to hooks.log) and `fleet history ls` warns.

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


def unreadable_count(con):
    return con.execute("SELECT COUNT(*) FROM conversations WHERE unreadable=1").fetchone()[0]


# ---------------------------------------------------------------- recording

def update(con, sid, **cols):
    keys = list(cols)
    con.execute("UPDATE conversations SET %s WHERE session_id=?" % ",".join(k + "=?" for k in keys),
                [cols[k] for k in keys] + [sid])


def record(con, data, now=None):
    """Apply one hook payload (SessionStart, Stop or SessionEnd). Cheap and bounded: it reads at most the first
    and last few hundred KB of the transcript, never calls a model."""
    now = now or time.time()
    event, sid = data.get("hook_event_name"), data.get("session_id")
    if not sid or event not in ("SessionStart", "Stop", "SessionEnd"):
        return
    cwd, tpath = data.get("cwd") or "", data.get("transcript_path") or ""
    con.execute("INSERT OR IGNORE INTO conversations(session_id, cwd, transcript_path, started_at, last_seen_at, origin)"
                " VALUES (?,?,?,?,?, 'hook')", (sid, cwd, tpath, now, now))
    row = con.execute("SELECT * FROM conversations WHERE session_id=?", (sid,)).fetchone()
    cols = {"last_seen_at": now}
    if cwd:
        cols["cwd"] = cwd
    if tpath:
        cols["transcript_path"] = tpath
    if event == "SessionStart":
        cols["ended_at"], cols["end_reason"] = None, None  # a resumed session is open again
    elif event == "SessionEnd":
        cols["ended_at"], cols["end_reason"] = now, data.get("reason") or "other"
    path = tpath or (row["transcript_path"] if row else "")
    bad = None
    if event != "SessionStart" and path and os.path.exists(path):
        bad = unreadable_reason(path)
        cols["unreadable"] = 1 if bad else 0
        cols.update(newest_names(records(path, tail=TAIL_BYTES)))
        if not (row and row["first_prompt"]):
            for rec in records(path, head=HEAD_BYTES):
                p = human_prompt(rec)
                if p:
                    cols["first_prompt"] = clip(p, 300)
                    break
    update(con, sid, **cols)
    if bad:
        raise HistoryError(bad)


# ---------------------------------------------------------------- reading the store

def display_name(r):
    return r["manual_name"] or r["name_custom"] or r["name_ai"] or r["name_agent"] or ""


def resume_command(r):
    return "cd %s && claude --resume %s" % (shlex.quote(r["cwd"] or "."), r["session_id"])


def view(r, fleet_name=""):
    """One row as the page and `--json` show it. A session with no name of its own (manual, custom, ai, agent)
    shows the name it has in the fleet, if it joined."""
    return {"id": r["session_id"], "name": display_name(r) or fleet_name or "", "fleet_name": fleet_name or "",
            "renamed": bool(r["manual_name"]), "folder": r["cwd"] or "",
            "about": r["first_prompt"] or "", "description": r["description"] or "", "started": r["started_at"],
            "last_seen": r["last_seen_at"], "ended": r["ended_at"], "end_reason": r["end_reason"] or "",
            "transcript": r["transcript_path"] or "", "resume": resume_command(r)}


def find(con, ident):
    """A row by id or unique id prefix."""
    ident = (ident or "").strip()
    rows = con.execute("SELECT * FROM conversations WHERE session_id LIKE ? ESCAPE '\\'",
                       (ident.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall() if ident else []
    exact = [r for r in rows if r["session_id"] == ident]
    if exact:
        return exact[0]
    if not rows:
        raise HistoryError("fleet: no session %r in the history." % ident)
    if len(rows) > 1:
        raise HistoryError("fleet: %r matches %d sessions (%s); give more of the id."
                           % (ident, len(rows), ", ".join(r["session_id"][:12] for r in rows[:5])))
    return rows[0]


def rows(con, folder=None):
    out = con.execute("SELECT * FROM conversations ORDER BY COALESCE(last_seen_at, started_at, 0) DESC").fetchall()
    if folder:
        f = os.path.abspath(os.path.expanduser(folder)).rstrip("/")
        out = [r for r in out if (r["cwd"] or "") == f or (r["cwd"] or "").startswith(f + "/")]
    return out


def counts(con):
    t = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    d = con.execute("SELECT COUNT(*) FROM conversations WHERE description IS NOT NULL AND description != ''").fetchone()[0]
    return {"total": t, "described": d}


def rename(con, ident, name):
    r = find(con, ident)
    update(con, r["session_id"], manual_name=" ".join((name or "").split()) or None)
    return find(con, r["session_id"])


def delete(con, ident):
    """Forget the row. The transcript is Claude Code's, and stays."""
    r = find(con, ident)
    con.execute("DELETE FROM conversations WHERE session_id=?", (r["session_id"],))
    return r


# ---------------------------------------------------------------- import

def iso_to_epoch(s):
    if not s:
        return None
    try:
        import calendar
        return float(calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        return None


def open_readonly(path):
    if not os.path.isfile(path):
        raise HistoryError("fleet: %s is not a file." % path)
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except sqlite3.Error as e:
        raise HistoryError("fleet: cannot read %s (%s)." % (path, e))
    return con


def import_store(con, path, descriptions=None):
    """Copy another store's `conversations` table (read only, idempotent). `descriptions` is a store with a
    `digests` table (id, size, digest, written_at); the given store is used when it has one. A row already here is
    kept as it is; a description is filled in only where this store has none. -> {read, added, kept, described}."""
    src = open_readonly(path)
    try:
        have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "conversations" not in have:
            raise HistoryError("fleet: %s has no conversations table." % path)
        cols = {r["name"] for r in src.execute("PRAGMA table_info(conversations)")}

        def pick(r, c):
            return r[c] if c in cols else None
        read = added = 0
        for r in src.execute("SELECT * FROM conversations"):
            read += 1
            kind, auto = pick(r, "auto_title_source"), pick(r, "auto_title")
            names = {"name_custom": None, "name_ai": None, "name_agent": None}
            if auto and kind in ("custom", "ai", "agent"):
                names["name_" + kind] = auto
            cur = con.execute(
                "INSERT OR IGNORE INTO conversations(session_id, cwd, transcript_path, started_at, last_seen_at, ended_at,"
                " end_reason, manual_name, name_custom, name_ai, name_agent, first_prompt, origin)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'import')",
                (r["conversation_id"], pick(r, "cwd"), pick(r, "transcript_path"), iso_to_epoch(pick(r, "started_at")),
                 iso_to_epoch(pick(r, "last_seen_at")), iso_to_epoch(pick(r, "ended_at")), pick(r, "end_reason"),
                 pick(r, "title") or None, names["name_custom"], names["name_ai"], names["name_agent"],
                 clip(pick(r, "first_prompt") or "", 300) or None))
            added += cur.rowcount
        described = 0
        dsrc = src
        if "digests" not in have and descriptions:
            dsrc = open_readonly(descriptions)
        try:
            if "digests" in {r[0] for r in dsrc.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                for d in dsrc.execute("SELECT id, size, digest, written_at FROM digests WHERE digest IS NOT NULL AND digest != ''"):
                    cur = con.execute("UPDATE conversations SET description=?, described_size=?, described_at=?"
                                      " WHERE session_id=? AND (description IS NULL OR description='')",
                                      (d["digest"], d["size"], (d["written_at"] or 0) / 1000.0, d["id"]))
                    described += cur.rowcount
        finally:
            if dsrc is not src:
                dsrc.close()
        return {"read": read, "added": added, "kept": read - added, "described": described}
    finally:
        src.close()


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


def pending(con, now=None, folder=None):
    """Sessions that need a description, newest first: someone typed in them, the transcript is there and quiet, and
    there is no description of its current size (or the last try failed over an hour ago)."""
    now = now or time.time()
    out = []
    for r in rows(con, folder):
        p = r["transcript_path"]
        try:
            st = os.stat(p) if p else None
        except OSError:
            st = None
        if not st or not r["first_prompt"]:
            continue
        if not r["ended_at"] and now - st.st_mtime < SETTLED:
            continue
        if r["describe_tried_at"] and r["describe_error"] and now - r["describe_tried_at"] < RETRY:
            continue
        if r["description"] and r["described_size"] == st.st_size:
            continue
        out.append((r, st.st_size))
    return out


def describe(con, limit=DESCRIBE_LIMIT, pause=None, log=None, folder=None):
    """Describe up to `limit` pending sessions, one headless call each, `pause` seconds apart (the rate limit).
    -> {described, failed, left}."""
    if pause is None:
        pause = float(os.environ.get("FLEET_DESCRIBE_PAUSE") or 2.0)
    todo = pending(con, folder=folder)
    ok = bad = 0
    model = os.environ.get("FLEET_DESCRIBE_MODEL") or "haiku"
    for i, (r, size) in enumerate(todo[:limit]):
        if i and pause:
            time.sleep(pause)
        c = conversation(r["transcript_path"])
        now = time.time()
        try:
            text = " ".join(headless(describe_prompt(r["cwd"], c["prompts"], c["replies"]), model, 180).split())
            if len(text) < 20:
                raise HistoryError("the model gave no description")
            update(con, r["session_id"], description=clip(text, 800), described_size=size, described_at=now,
                   describe_error=None, describe_tried_at=now, **c["names"])
            ok += 1
        except HistoryError as e:
            update(con, r["session_id"], describe_error=str(e)[:300], describe_tried_at=now)
            bad += 1
            if log:
                log("%s: %s" % (r["session_id"][:8], e))
    return {"described": ok, "failed": bad, "left": max(0, len(todo) - limit)}


# ---------------------------------------------------------------- ask and search

def ask_prompt(r, question, ts):
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
         % (r["cwd"] or "unknown"), "If the transcript does not say, say so. Be brief and concrete.", "",
         "Question: %s" % question, "", "Transcript:"] + lines)


def ask(con, ident, question):
    r = find(con, ident)
    if not (question or "").strip():
        raise HistoryError("fleet: ask needs a question.")
    if not r["transcript_path"] or not os.path.exists(r["transcript_path"]):
        raise HistoryError("fleet: the transcript of %s is gone (%s)." % (r["session_id"][:8], r["transcript_path"] or "no path"))
    ts = turns(r["transcript_path"])
    if not ts:
        raise HistoryError("fleet: the transcript of %s holds no conversation." % r["session_id"][:8])
    out = headless(ask_prompt(r, question.strip(), ts), os.environ.get("FLEET_ASK_MODEL") or "sonnet", 180).strip()
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


def search(con, query):
    """Sessions that match `query` by meaning: one call reads every description (newest first, within the budget)
    and names the best matches. -> {hits: [view + why], described, total}."""
    if not (query or "").strip():
        raise HistoryError("fleet: search needs words to look for.")
    entries, used = [], 0
    for r in rows(con):
        if not r["description"]:
            continue
        e = {"row": r, "date": time.strftime("%Y-%m-%d", time.localtime(r["last_seen_at"] or r["started_at"] or 0)),
             "folder": r["cwd"] or "", "description": r["description"]}
        used += len(e["description"]) + len(e["folder"]) + 20
        if used > SEARCH_BUDGET:
            break
        entries.append(e)
    c = counts(con)
    if not entries:
        return {"hits": [], "described": 0, "total": c["total"]}
    out = headless(search_prompt(query.strip(), entries), os.environ.get("FLEET_ASK_MODEL") or "sonnet", 180)
    hits = [dict(view(entries[i]["row"]), why=why) for i, why in parse_search(out, len(entries))]
    return {"hits": hits, "described": c["described"], "total": c["total"]}
