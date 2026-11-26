"""The recorder: fleet's one hook writes every session's SessionStart, UserPromptSubmit, Stop and SessionEnd into
this machine's journal, then sends the journal to the hub in a detached child, so a hook never waits for the
network. A work session's entry is masked before it is written. It never fails a session: it always exits 0 and
logs a problem to `$FLEET_HOME/hooks.log`. Contract: `fleet/docs/session-index.md`, section 6.
Stdlib only, no fleet imports (`fleet_index_cli` imports fleet only inside its functions).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fleet_history as hist  # noqa: E402
import fleet_index_cache as cache  # noqa: E402
import fleet_index_journal as journal  # noqa: E402
import fleet_index_parse as parse  # noqa: E402
import fleet_index_store as store  # noqa: E402
import fleet_sessions  # noqa: E402
import fleet_work  # noqa: E402

EVENTS = {"SessionStart": "start", "UserPromptSubmit": "prompt", "Stop": "stop", "SessionEnd": "end"}
OBSERVED = {"start": (True, "idle"), "prompt": (True, "busy"), "stop": (True, "idle"), "end": (False, "ended")}


def _fleet_home(environ):
    return environ.get("FLEET_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "fleet")


def _sessions_rules(fleet_home):
    try:
        with open(os.path.join(fleet_home, "sessions.json")) as f:
            conf = json.load(f)
        return conf if isinstance(conf, dict) else {}
    except (OSError, ValueError):
        return {}


def log(fleet_home, text):
    try:
        os.makedirs(fleet_home, mode=0o700, exist_ok=True)
        path = os.path.join(fleet_home, "hooks.log")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s index-hook: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


UNREADABLE = "unreadable.json"  # {sid: reason} under $FLEET_HOME/index: transcripts the parser could not read


def unreadable(fleet_home):
    """{sid: reason} of this machine's transcripts that hold data but nothing the parser can use."""
    try:
        with open(os.path.join(fleet_home, "index", UNREADABLE)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def note_readable(fleet_home, sid, transcript):
    """Check a transcript at stop and end. One that cannot be read is logged to hooks.log and kept in
    unreadable.json, so the lists warn: a changed transcript format must never pass as sessions with no words."""
    reason = hist.unreadable_reason(transcript)
    if reason:
        log(fleet_home, reason)
    have = unreadable(fleet_home)
    if have.get(sid) == reason:
        return reason
    if reason:
        have[sid] = reason
    else:
        have.pop(sid, None)
    d = os.path.join(fleet_home, "index")
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, UNREADABLE)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(have, f)
    os.replace(tmp, path)
    return reason


def entry_for(hook, *, environ, fleet_home, machine, rules, now=None):
    """{sid, event, fields, epoch_seen} for one hook input, masked when the session is work; None for an event the
    index does not record."""
    now = time.time() if now is None else now
    if not isinstance(hook, dict):
        return None
    event = EVENTS.get(hook.get("hook_event_name"))
    sid = hook.get("session_id")
    if not event or not isinstance(sid, str) or not store.SID_RE.match(sid):
        return None
    transcript = hook.get("transcript_path") or parse.find_transcript(sid)
    if transcript and not os.path.isfile(transcript):
        transcript = None
    cwd = hook.get("cwd") or environ.get("PWD") or None
    facts = parse.session_facts(transcript, event=event, hook=hook) if transcript or event == "prompt" else {}
    fields = {k: v for k, v in facts.items() if k in ("first_prompt", "last_prompt", "last_answer")}
    names = []
    if facts.get("name"):
        names.append((facts["name_source"], facts["name"]))
    job = environ.get("CLAUDE_DETACH_NAME")
    is_job = bool(job) and environ.get("CLAUDE_CODE_ENTRYPOINT") != "cli"
    if is_job:
        names.append(("job", parse.cut(job, 200)))
    if names:
        src, name = min(names, key=lambda n: store.NAME_RANK.index(n[0]))
        fields["name"], fields["name_source"] = name, src
    if is_job:
        fields["kind"] = "job"
    else:
        fields["kind"] = fleet_sessions.kind_of(fields.get("name"), cwd, _sessions_rules(fleet_home))
    if cwd and len(cwd) <= store.LIMITS["cwd"]:
        fields["cwd"] = cwd
    cfg = fleet_work.config_dir_of(transcript) or environ.get("CLAUDE_CONFIG_DIR") or os.path.join(rules.home, ".claude")
    account = fleet_work.account_of(cfg, rules)
    if account:
        fields["account"] = parse.cut(account, 64)
    if environ.get("FLEET_RC_NAME"):
        fields["rc_name"] = parse.cut(environ["FLEET_RC_NAME"], 200)
    if event == "end":
        fields["end_reason"] = parse.cut(hook.get("reason") or "other", 64)
    live, state = OBSERVED[event]
    fields["observed"] = {"live": live, "state": state, "observed_at": now}
    work = fleet_work.is_work(cwd, transcript, rules)
    fields["work"] = bool(work)
    if work:
        fields = fleet_work.mask_fields(fields)
    epoch_seen = None
    if event == "start" and hook.get("source") == "resume" and cache.read(fleet_home, sid) is None:
        epoch_seen = 0  # a resumed session this machine knows nothing of: the hub's reply teaches it the owner
    return {"sid": sid, "event": event, "fields": fields, "epoch_seen": epoch_seen}


def flush_detached(fleet_home, environ):
    """Send the journal in a child that outlives the hook. FLEET_INDEX_FOREGROUND=1 sends it here, for tests."""
    import fleet_index_cli as cli
    if environ.get("FLEET_INDEX_FOREGROUND") == "1":
        cli.flush_now(fleet_home)
        return
    env = dict(environ, FLEET_HOME=fleet_home, FLEET_NO_RECORD="1")
    with open(os.devnull, "rb") as dn_in, open(os.devnull, "wb") as dn_out:
        subprocess.Popen([sys.executable, os.path.join(HERE, "fleet_index_cli.py"), "flush"], env=env,
                         stdin=dn_in, stdout=dn_out, stderr=dn_out, start_new_session=True, close_fds=True)


def record(hook, *, environ=None, fleet_home=None, now=None):
    """Append the hook's entry to this machine's journal and send it on. Always 0."""
    environ = dict(os.environ) if environ is None else environ
    fleet_home = fleet_home or _fleet_home(environ)
    try:
        if environ.get("FLEET_NO_RECORD"):
            return 0
        import fleet_index_cli as cli
        machine = cli.self_name(fleet_home)
        rules = fleet_work.load_rules(fleet_home)
        e = entry_for(hook, environ=environ, fleet_home=fleet_home, machine=machine, rules=rules, now=now)
        if e is None:
            return 0
        journal.append(fleet_home, machine, e["sid"], e["event"], e["fields"], epoch_seen=e["epoch_seen"], at=now)
        flush_detached(fleet_home, environ)
        transcript = hook.get("transcript_path") or parse.find_transcript(e["sid"])
        if e["event"] in ("stop", "end") and transcript and os.path.isfile(transcript):
            note_readable(fleet_home, e["sid"], transcript)
    except BaseException as ex:  # noqa: B902 - a recording problem may cost an entry, never a session
        log(fleet_home, "%s: %s" % (type(ex).__name__, ex))
    return 0


def main():
    try:
        hook = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    return record(hook)


if __name__ == "__main__":
    sys.exit(main())
