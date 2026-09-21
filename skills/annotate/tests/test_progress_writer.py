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
