"""The narration writer, against a real daemon.

annotate's page went mute after the daemon cutover: `applyProgress` in
script.js has been fed `undefined` ever since, because compat.js's synthesised
delta has no `progress` key and the hook that used to produce labels went
dormant. This module is the replacement's writing half — the thing Claude calls
between steps so the reader learns something during a five-minute silence.

It talks to the live daemon rather than a stub on purpose: the failure mode
being designed against is "the write path silently does nothing", and a stub
that accepts anything would reproduce it.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skills.annotate import progress

REPO = Path(__file__).resolve().parents[3]
CONFIG = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))


def _daemon_url():
    if not CONFIG.is_file():
        pytest.skip("no webcompanion daemon configured on this machine")
    port = json.loads(CONFIG.read_text())["port"]
    url = f"http://127.0.0.1:{port}"
    try:
        urllib.request.urlopen(url + "/health", timeout=3).read()
    except (urllib.error.URLError, OSError):
        pytest.skip(f"webcompanion daemon is not answering on {url}")
    return url


def _call(base, method, path, body=None):
    cfg = json.loads(CONFIG.read_text())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-WebCompanion-Contract", "1")
    if cfg.get("token"):
        req.add_header("X-WebCompanion-Token", cfg["token"])
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


@pytest.fixture
def sid():
    """A throwaway session, deleted afterwards."""
    base = _daemon_url()
    s = _call(base, "POST", "/api/sessions",
              {"kind": "annotate", "cwd": str(REPO), "title": "progress writer suite"})
    sid = s["sid"]
    try:
        yield sid
    finally:
        _call(base, "POST", f"/s/{sid}/api/finish")
        try:
            _call(base, "DELETE", f"/s/{sid}/?force=1")
        except Exception as e:                       # noqa: BLE001
            import warnings
            warnings.warn(f"progress writer suite leaked session {sid}: {e}")


def _stored(sid):
    return _call(_daemon_url(), "GET", f"/s/{sid}/items/{progress.ANCHOR}")["body"]


def test_the_first_note_creates_the_item(sid):
    progress.note(sid, "Read your comment on section-3")
    body = _stored(sid)
    assert body["state"] == "working"
    assert [s["text"] for s in body["steps"]] == ["Read your comment on section-3"]
    assert body["started_at"] > 0


def test_notes_accumulate_in_order(sid):
    progress.note(sid, "one")
    progress.note(sid, "two")
    progress.note(sid, "three")
    assert [s["text"] for s in _stored(sid)["steps"]] == ["one", "two", "three"]


def test_finish_closes_the_round_without_losing_the_trail(sid):
    progress.note(sid, "one")
    progress.finish(sid)
    body = _stored(sid)
    assert body["state"] == "done"
    assert body["ended_at"] >= body["started_at"]
    assert [s["text"] for s in body["steps"]] == ["one"]


def test_a_note_after_done_starts_a_fresh_round(sid):
    # Each event gets its own trail. Appending to a finished one would show
    # the reader a feed that begins mid-way through work they already saw
    # answered.
    progress.note(sid, "old round")
    progress.finish(sid)
    progress.note(sid, "new round")
    body = _stored(sid)
    assert body["state"] == "working"
    assert [s["text"] for s in body["steps"]] == ["new round"]
    assert body["ended_at"] is None


def test_the_event_id_is_carried_when_given(sid):
    progress.note(sid, "one", event_id="evt-42")
    assert _stored(sid)["event_id"] == "evt-42"


def test_the_trail_is_capped_so_a_long_session_cannot_grow_forever(sid):
    # Seeded in one write rather than looped: each note() is a GET plus a PUT,
    # and 210 of them is 420 round trips to prove one bound — the kind of slow
    # test that gets deleted rather than fixed.
    import time as _t
    now = int(_t.time())
    _call(_daemon_url(), "PUT", f"/s/{sid}/items/{progress.ANCHOR}", {
        "id": progress.ANCHOR, "kind": "progress", "state": "working",
        "started_at": now, "ended_at": None, "event_id": None,
        "steps": [{"t": now, "text": f"step {i}"} for i in range(progress.MAX_STEPS)],
    })
    progress.note(sid, "the newest line")
    steps = _stored(sid)["steps"]
    assert len(steps) == progress.MAX_STEPS, "the trail grows without bound"
    # Oldest dropped, newest kept — the reader cares about what is happening
    # now, and the newest line is the one the panel pins to.
    assert steps[-1]["text"] == "the newest line"
    assert steps[0]["text"] == "step 1", "the wrong end of the trail was dropped"


def test_a_push_does_not_delete_the_trail(sid, tmp_path):
    """The source test proves the code is there; this proves it works."""
    from skills.annotate import push as push_mod

    progress.note(sid, "found the divergence")
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps({
        "response_id": "resp-progress-suite",
        "title": "progress suite",
        "blocks": [{"id": "section-1", "kind": "markdown", "title": "One",
                    "markdown": "Body."}],
    }))
    stray_sid = None
    try:
        res = push_mod.push(blocks, str(REPO), slug=None, title="progress suite")
        stray_sid = res["sid"]

        # The push above created its OWN session; re-push into ours by slug is
        # what the skill actually does, so drive that path instead.
        rows = _call(_daemon_url(), "GET", f"/api/sessions?cwd={REPO}&kind=annotate")
        row = next(r for r in rows if r["sid"] == sid)
        push_mod.push(blocks, str(REPO), slug=row["slug"], title="progress suite")

        body = _stored(sid)
        assert [s["text"] for s in body["steps"]] == ["found the divergence"], \
            "the push wiped the narration it had just produced"
    finally:
        # push_mod.push's first call, with no slug, created its own session as
        # a side effect. It is not the `sid` fixture's session, so the fixture
        # teardown never sees it — delete it here or it leaks into the
        # registry the way an earlier suite leaked 28 of them before anyone
        # counted.
        if stray_sid is not None:
            base = _daemon_url()
            _call(base, "POST", f"/s/{stray_sid}/api/finish")
            try:
                _call(base, "DELETE", f"/s/{stray_sid}/?force=1")
            except Exception as e:                       # noqa: BLE001
                import warnings
                warnings.warn(f"progress writer suite leaked session {stray_sid}: {e}")


# --- the CLI, exactly as the skill documents it -------------------------
#
# Every test above calls note()/finish() as Python functions, which is not how
# narration ever actually runs: the skill tells Claude to run a shell command,
# from whatever working directory the turn happens to be in. That gap let ten
# documented invocations ship bare — no PYTHONPATH — which raises
# ModuleNotFoundError from any cwd that is not the plugin root. Because
# narration is contractually allowed to fail without failing the turn, it
# failed silently, and the reader got the spinner this whole feature exists to
# remove. These drive the module the way the documentation does.

def _cli(cwd, *args, env=None):
    import subprocess
    return subprocess.run(
        ["python3", "-m", "skills.annotate.progress", *args],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def test_the_documented_command_runs_from_a_foreign_working_directory(sid, tmp_path):
    # tmp_path is the point: a cwd with no `skills` package under it, which is
    # every cwd Claude is ever in while handling an event.
    env = dict(os.environ, PYTHONPATH=str(REPO))
    r = _cli(tmp_path, "--sid", sid, "--text", "Reading how anchors resolve", env=env)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stderr == "", r.stderr
    assert [s["text"] for s in _stored(sid)["steps"]] == ["Reading how anchors resolve"]


def test_the_documented_done_flag_closes_the_trail_from_a_foreign_cwd(sid, tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    assert _cli(tmp_path, "--sid", sid, "--text", "one", env=env).returncode == 0
    r = _cli(tmp_path, "--sid", sid, "--done", env=env)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    body = _stored(sid)
    assert body["state"] == "done"
    assert [s["text"] for s in body["steps"]] == ["one"]


def test_without_the_pythonpath_the_command_cannot_even_import_itself(sid, tmp_path):
    # The shape of the bug, pinned so nobody "simplifies" the documented
    # prefix away again: bare, from a foreign cwd, it does not run at all.
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    r = _cli(tmp_path, "--sid", sid, "--text", "never arrives", env=env)
    assert r.returncode != 0
    assert "No module named 'skills'" in r.stderr


def test_a_missing_daemon_config_is_reported_not_raised(tmp_path):
    # main()'s ProgressError catch. Narration must never take down the turn it
    # is narrating, so this exits non-zero with a message rather than a
    # traceback — and the documented commands ignore the exit code.
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, PYTHONPATH=str(REPO), HOME=str(home))
    r = _cli(tmp_path, "--sid", "whatever", "--text", "x", env=env)
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "webcompanion is not configured" in r.stderr


def test_neither_text_nor_done_is_a_usage_error(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    r = _cli(tmp_path, "--sid", "whatever", env=env)
    assert r.returncode == 2
    assert "--text or --done" in r.stderr


def test_a_write_to_an_unknown_session_is_reported_not_swallowed(tmp_path):
    """`_request` returned None on ANY 404, so a PUT with a wrong `--sid`
    narrated into the void and exited 0 — a typo looked exactly like a working
    narration channel. Only the READ may treat 404 as "no trail yet"."""
    env = dict(os.environ, PYTHONPATH=str(REPO))
    r = _cli(tmp_path, "--sid", "no-such-session", "--text", "into the void", env=env)
    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "404" in r.stderr, r.stderr


def test_the_read_still_treats_a_missing_trail_as_no_trail(sid):
    # The first line of a round: nothing is stored yet, the GET 404s, and that
    # is the ordinary case rather than an error.
    body = progress.note(sid, "first line of this round")
    assert [s["text"] for s in body["steps"]] == ["first line of this round"]


# --- the commands exactly as the document ships them --------------------
#
# The three tests above hand the subprocess `PYTHONPATH=str(REPO)`
# themselves. That proves the prefixed FORM imports, and says nothing about
# whether the variable is populated when Claude runs the line — it is not.
# Environment variables do not survive between Bash tool calls, so a
# `PLUGIN_ROOT` a probe exported "once per turn, before the first of them"
# is empty in every later call: the prefix expands to `PYTHONPATH=""` and
# the command dies with the very ModuleNotFoundError the prefix was added to
# prevent, silently, because narration may not fail the turn. These take the
# line out of the document and run it with nothing inherited.

CONTRACT = REPO / "skills" / "annotate" / "references" / "handling-events.md"


def _documented_narration_commands():
    """Every runnable narration invocation the contract prints, verbatim."""
    import re
    found = []
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        if "skills.annotate.progress" not in line or "--sid" not in line:
            continue
        spans = [s for s in re.findall(r"`([^`]+)`", line)
                 if "skills.annotate.progress" in s and "--sid" in s]
        found.extend(spans or [line.strip()])
    assert found, "the contract prints no runnable narration command any more"
    return sorted(set(found))


def _fresh_shell_env(sid, **extra):
    """What a Bash tool call actually gets: no PYTHONPATH, no plugin root."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "CLAUDE_PLUGIN_ROOT")}
    env["WC_SID"] = sid
    env.update(extra)
    return env


def _run_documented(cmd, cwd, env):
    import subprocess
    return subprocess.run(["bash", "-c", cmd], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=60)


def test_every_documented_command_resolves_its_own_root_off_path(sid, tmp_path):
    """Copied verbatim, run from a foreign cwd, inheriting nothing.

    The only thing this hands the command is a plugin `bin` directory on
    PATH — the first of the two places the documented probe looks, and how an
    installed plugin is reachable at all. It is not told where to import
    from; it has to work that out for itself, on every single call.
    """
    env = _fresh_shell_env(sid, PATH=f"{REPO / 'bin'}{os.pathsep}{os.environ['PATH']}")
    for cmd in _documented_narration_commands():
        r = _run_documented(cmd, tmp_path, env)
        assert "No module named 'skills'" not in r.stderr, \
            f"this line cannot import itself when copied out of the doc:\n{cmd}"
        assert r.returncode == 0, \
            f"{cmd}\nstdout={r.stdout!r} stderr={r.stderr!r}"
    texts = [s["text"] for s in _stored(sid)["steps"]]
    assert "Read your round of feedback" in texts, texts


def test_a_documented_command_resolves_its_own_root_off_the_marketplace(sid, tmp_path):
    """The probe's other branch, with nothing on PATH that could answer."""
    import shutil
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "webcompanion").mkdir(parents=True)
    shutil.copy(CONFIG, home / ".claude" / "webcompanion" / "config.json")
    (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"claude-annotate": {"installLocation": str(REPO)}}))
    cmd = next(c for c in _documented_narration_commands() if "--text" in c)
    r = _run_documented(cmd, tmp_path, _fresh_shell_env(sid, HOME=str(home)))
    assert "No module named 'skills'" not in r.stderr, \
        f"this line cannot import itself when copied out of the doc:\n{cmd}"
    assert r.returncode == 0, f"{cmd}\nstdout={r.stdout!r} stderr={r.stderr!r}"
