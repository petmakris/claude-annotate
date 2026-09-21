# Progress Narration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While Claude works on a reader's comment, the annotate page shows what it is doing, line by line, instead of a spinner with a dead caption.

**Architecture:** Claude writes narration lines into one ordinary item at anchor `__progress__` through the daemon's existing single-item `PUT` route. The daemon delivers it as a normal SSE item frame; `compat.js` re-broadcasts it as a DOM event; a new `progress.js` renders a panel under the header. No change to the `webcompanion` daemon at all.

**Tech Stack:** Python 3 stdlib (`urllib`, `json`) for the writer; vanilla ES modules for the page; `unittest`/`pytest` for source-level tests and Playwright + Chromium against a live daemon for behaviour.

**Spec:** `docs/superpowers/specs/2026-09-21-progress-narration-design.md`

## Global Constraints

- **All new CSS goes in `skills/annotate/static/style.css`. Add nothing to `skills/annotate/static/core.css`** — it is a deliberately diverged copy of the shared `skills/_shared/web_companion/static/core.css` (`skills/deck/static/core.css` is a third copy), and its header block lists the divergences and says not to re-sync.
- **Python 3 standard library only.** No pip dependencies. `webcompanion` itself is pipx-installed in an isolated venv the plain `python3` these skills run under cannot import — see `skills/_shared/webcompanion_client.py`'s module docstring.
- **Commit messages are a single line.** No body, no trailers, no attribution. (User's `CLAUDE.md`.)
- **`skills/annotate/static/shell.js` is a line-continued template literal** — every line of the literal ends with a backslash and no newline may enter the string. `test_smoke_shell_source.py` enforces it. (Only Task 4 touches it, and only if the panel needs a mount point.)
- **Never decode `shell.js` by hand in a test.** Use `from .shell_source import shell_html`.
- The anchor is exactly `__progress__`. The leading and trailing double underscores are what make it invisible to the document (`compat.js:51`, `:206`) — do not rename it to something without them.
- Run the suite with `python3 -m pytest skills/annotate/tests -q`. A live webcompanion daemon is present on this machine (port from `~/.claude/webcompanion/config.json`); browser and daemon tests must actually run, not skip.

---

### Task 1: The writer — `skills/annotate/progress.py`

The thing Claude calls. One job: append a line to the progress item, or close it out.

**Files:**
- Create: `skills/annotate/progress.py`
- Test: `skills/annotate/tests/test_progress_writer.py`

**Interfaces:**
- Consumes: nothing.
- Produces, for later tasks:
  - `ANCHOR = "__progress__"` — the item anchor.
  - `note(sid: str, text: str, event_id: str | None = None) -> dict` — appends a step, returns the stored body.
  - `finish(sid: str) -> dict` — flips `state` to `"done"`, stamps `ended_at`, returns the stored body.
  - Item body shape: `{"id": "__progress__", "kind": "progress", "state": "working"|"done", "started_at": int, "ended_at": int|None, "event_id": str|None, "steps": [{"t": int, "text": str}]}`.
  - CLI: `python3 -m skills.annotate.progress --sid SID --text "..."` and `--sid SID --done`.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_progress_writer.py`:

```python
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
    for i in range(progress.MAX_STEPS + 10):
        progress.note(sid, f"step {i}")
    steps = _stored(sid)["steps"]
    assert len(steps) == progress.MAX_STEPS
    # Oldest dropped, newest kept — the reader cares about what is happening
    # now, and the newest line is the one the panel pins to.
    assert steps[-1]["text"] == f"step {progress.MAX_STEPS + 9}"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_progress_writer.py -q`
Expected: FAIL at import — `cannot import name 'progress' from 'skills.annotate'`. If instead every test SKIPS, the daemon is not answering; fix that before continuing, because a skipped suite proves nothing here.

- [ ] **Step 3: Write the implementation**

Create `skills/annotate/progress.py`:

```python
"""Narration: what Claude is doing, while the page waits.

A reader comments on a block and Claude goes away for minutes. The page has a
spinner and a ticking timer, and until now nothing else: `applyProgress` in
script.js has been receiving `undefined` since the daemon cutover, and
hooks/progress_publish.py — which used to produce its labels — went dormant in
the same move.

This is the writing half of the replacement. Claude calls it between steps and
the line appears on the page within milliseconds, because the daemon already
pushes every item write down its SSE stream.

Why an ITEM and not a new daemon route: the daemon is a separate package,
pipx-installed, shared with deck, dataflow and walkthrough. Carrying strings
through the item channel it already has costs one anchor; a first-class
progress channel costs a release, a reinstall, and version skew in every
client. The anchor's `__` prefix is what keeps it out of the document —
compat.js:51 skips `__`-prefixed ids when building the block list and
compat.js:207 strips them from the version map — so it can never be mistaken
for a block.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTRACT = 1
ANCHOR = "__progress__"

# A long session can answer many events. The panel shows a window, not a
# transcript, and an unbounded list would grow the item forever and make every
# subsequent write larger than the last.
MAX_STEPS = 200


class ProgressError(RuntimeError):
    pass


def _config() -> dict:
    path = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))
    if not path.exists():
        raise ProgressError(
            "webcompanion is not configured on this machine "
            "(~/.claude/webcompanion/config.json is missing).")
    return json.loads(path.read_text())


def _request(cfg: dict, method: str, path: str, body=None):
    url = "http://127.0.0.1:%d%s" % (int(cfg["port"]), path)
    data = None
    headers = {"X-WebCompanion-Contract": str(CONTRACT)}
    if cfg.get("token"):
        headers["X-WebCompanion-Token"] = cfg["token"]
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read().decode(errors="replace").strip()
        raise ProgressError("%s %s -> %d %s" % (method, path, e.code, detail)) from None
    except urllib.error.URLError as e:
        raise ProgressError("webcompanion is not answering: %s" % e.reason) from None
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def _load(cfg: dict, sid: str) -> dict | None:
    one = _request(cfg, "GET", "/s/%s/items/%s" % (sid, ANCHOR))
    if not one:
        return None
    body = one.get("body")
    return body if isinstance(body, dict) else None


def _blank(now: int, event_id: str | None) -> dict:
    return {
        "id": ANCHOR,
        "kind": "progress",
        "state": "working",
        "started_at": now,
        "ended_at": None,
        "event_id": event_id,
        "steps": [],
    }


def note(sid: str, text: str, event_id: str | None = None) -> dict:
    """Append one narration line. Starts a fresh trail if the last one is closed."""
    cfg = _config()
    now = int(time.time())
    cur = _load(cfg, sid)
    # A finished trail belongs to work the reader has already seen answered.
    # Appending to it would show a feed that starts mid-way through a round
    # that is over.
    if not cur or cur.get("state") == "done":
        cur = _blank(now, event_id)
    if event_id and not cur.get("event_id"):
        cur["event_id"] = event_id
    steps = cur.get("steps")
    if not isinstance(steps, list):
        steps = []
    steps.append({"t": now, "text": str(text)})
    cur["steps"] = steps[-MAX_STEPS:]
    cur["state"] = "working"
    cur["ended_at"] = None
    _request(cfg, "PUT", "/s/%s/items/%s" % (sid, ANCHOR), cur)
    return cur


def finish(sid: str) -> dict:
    """Close the trail. The steps stay — how the answer was reached is evidence."""
    cfg = _config()
    now = int(time.time())
    cur = _load(cfg, sid) or _blank(now, None)
    cur["state"] = "done"
    cur["ended_at"] = now
    _request(cfg, "PUT", "/s/%s/items/%s" % (sid, ANCHOR), cur)
    return cur


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.progress")
    ap.add_argument("--sid", required=True)
    ap.add_argument("--text", help="one narration line")
    ap.add_argument("--event-id", dest="event_id")
    ap.add_argument("--done", action="store_true", help="close the trail")
    a = ap.parse_args(argv)
    if not a.text and not a.done:
        print("progress: pass --text or --done", file=sys.stderr)
        return 2
    try:
        if a.text:
            note(a.sid, a.text, a.event_id)
        if a.done:
            finish(a.sid)
    except ProgressError as e:
        # Narration must never take down the turn it is narrating. Report and
        # return non-zero; the caller is a shell step that ignores it.
        print("progress: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_progress_writer.py -q`
Expected: PASS, 6 passed, 0 skipped.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS, no new failures.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/progress.py skills/annotate/tests/test_progress_writer.py
git commit -m "Add the narration writer that puts what Claude is doing on the page"
```

---

### Task 2: Keep the trail across a push

`push.py:153` replaces the whole item set. The re-push that delivers Claude's answer would delete the record of how it got there, at the exact moment the reader would look at it.

**Files:**
- Modify: `skills/annotate/push.py:145-155`
- Test: `skills/annotate/tests/test_progress_survives_push.py`

**Interfaces:**
- Consumes: `progress.ANCHOR` from Task 1.
- Produces: nothing new; `__progress__` simply survives a push.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_progress_survives_push.py`:

```python
"""A push must not delete the narration it just finished producing.

push.py replaces the whole item set (`PATCH … replace: true`), which is how
`__prev__` came to be re-inserted by hand at push.py:148. `__progress__` needs
the same treatment for a sharper reason: the push that lands Claude's answer is
the moment the reader turns to the page, and the trail explaining how the
answer was reached would vanish in the same instant.
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "push.py").read_text()


def test_push_preserves_the_progress_anchor():
    assert "PROGRESS_ANCHOR" in SRC, "push.py does not know about the trail"
    # Carried the same way __prev__ is: read the stored items, re-insert.
    assert re.search(r"items\[PROGRESS_ANCHOR\]\s*=", SRC), \
        "push.py reads the anchor but never puts it back"


def test_it_is_re_inserted_before_the_replacing_patch():
    # Order matters: after the PATCH there is nothing left to preserve.
    put_back = SRC.index("items[PROGRESS_ANCHOR]")
    patch = SRC.index('"PATCH"')
    assert put_back < patch, "the trail is restored after the replace wipes it"


def test_the_anchor_is_imported_rather_than_retyped():
    # One spelling. A second literal is a rename waiting to break silently.
    assert "from .progress import ANCHOR as PROGRESS_ANCHOR" in SRC \
        or "from skills.annotate.progress import ANCHOR as PROGRESS_ANCHOR" in SRC, \
        "push.py hardcodes the anchor instead of importing it"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_progress_survives_push.py -q`
Expected: FAIL — `push.py does not know about the trail`.

- [ ] **Step 3: Implement**

In `skills/annotate/push.py`, add near the other imports:

```python
from .progress import ANCHOR as PROGRESS_ANCHOR
```

Then in `push()`, replace the `__prev__` preservation block (currently lines 145-151) with:

```python
    # The pre-round snapshot the diff pane reads. Written from what is
    # currently stored, BEFORE the replace lands — the old server kept this
    # by copying blocks.json on every mutating event, and losing it would
    # silently kill the "what changed since you commented" marks.
    prev = _existing_items(cfg, sid)
    trail = prev.pop(PROGRESS_ANCHOR, None)
    prev.pop(PREV_ANCHOR, None)
    if prev:
        items[PREV_ANCHOR] = prev
    # The narration trail survives the replace for the same reason __prev__
    # does, and a sharper one: this push IS the answer landing, which is
    # exactly when the reader looks at how it was reached.
    if trail is not None:
        items[PROGRESS_ANCHOR] = trail
```

Note the `prev.pop(PROGRESS_ANCHOR, ...)` happens *before* `prev` is stored as `__prev__` — the trail is not part of the document's previous state and must not be snapshotted into it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_progress_survives_push.py -q`
Expected: PASS, 3 passed.

- [ ] **Step 5: Prove it against a real daemon**

Append to `skills/annotate/tests/test_progress_writer.py`:

```python
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
    push_mod.push(blocks, str(REPO), slug=None, title="progress suite")

    # The push above created its OWN session; re-push into ours by slug is
    # what the skill actually does, so drive that path instead.
    rows = _call(_daemon_url(), "GET", f"/api/sessions?cwd={REPO}&kind=annotate")
    row = next(r for r in rows if r["sid"] == sid)
    push_mod.push(blocks, str(REPO), slug=row["slug"], title="progress suite")

    body = _stored(sid)
    assert [s["text"] for s in body["steps"]] == ["found the divergence"], \
        "the push wiped the narration it had just produced"
```

Run: `python3 -m pytest skills/annotate/tests/test_progress_writer.py -q`
Expected: PASS. If the first `push_mod.push` leaves a stray session behind, delete it in the test's teardown rather than leaving it in the registry — an earlier suite in this repo leaked 28 sessions before anyone counted.

- [ ] **Step 6: Run the whole suite and commit**

Run: `python3 -m pytest skills/annotate/tests -q` → PASS.

```bash
git add skills/annotate/push.py skills/annotate/tests/
git commit -m "Keep the narration trail alive across the push that answers the comment"
```

---

### Task 3: Deliver the line to the page — `compat.js`

Two edits, both small, both load-bearing.

**Files:**
- Modify: `skills/annotate/static/compat.js:209-211`
- Test: `skills/annotate/tests/test_smoke_progress_delivery.py`

**Interfaces:**
- Consumes: the anchor `__progress__`.
- Produces, for Task 4:
  - A DOM event `annotate:progress` on `document`, dispatched whenever the `__progress__` item changes. `detail` is `{version: <number>}`.
  - The existing route `window.WebCompanion.fetchJSON("raw?block=__progress__")`, which already resolves to the item body plus `version` (`compat.js:95-98`) and needs no change.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_progress_delivery.py`:

```python
"""Getting a narration line from the daemon to the panel.

compat.js:207 strips `__`-prefixed anchors out of the version map before
script.js sees it — correct, and it means script.js never hears about a
progress write. So the panel needs its own signal, and compat.js already has
the pattern: it dispatches `annotate:busy` at :189, which subunits.js:836
consumes.

The second edit is the sharp one. compat.js clears the page lock on ANY item
change, as a fallback for a daemon too old to send `event-acked`. For the
progress anchor that rule is exactly backwards: Claude's first narration line
would unlock the page and dismiss the very ribbon the narration captions.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
COMPAT = (STATIC / "compat.js").read_text()

ANCHOR = "__progress__"


class TestTheUnlockRuleExemptsTheTrail(unittest.TestCase):
    def test_the_anchor_is_named_in_the_unlock_guard(self):
        # The rule lives on one line; the exemption must be on it, not in a
        # comment nearby.
        m = re.search(r'if \(ev\.kind === "item".*?\n', COMPAT)
        self.assertIsNotNone(m, "the item-unlock rule is gone or reshaped")
        self.assertIn(ANCHOR, m.group(0),
                      "a progress write still clears the page lock")

    def test_the_lock_is_still_cleared_by_an_ordinary_item(self):
        # The fallback this rule exists for must survive the exemption.
        self.assertIn("setBusyLocal(false)", COMPAT)


class TestThePanelGetsItsOwnSignal(unittest.TestCase):
    def test_a_progress_delta_is_re_broadcast(self):
        self.assertIn("annotate:progress", COMPAT)

    def test_it_follows_the_event_the_page_already_uses(self):
        # annotate:busy is the precedent (compat.js:189, consumed by
        # subunits.js:836). One pattern, not two.
        self.assertIn('new CustomEvent("annotate:progress"', COMPAT)

    def test_the_signal_is_scoped_to_the_progress_anchor(self):
        idx = COMPAT.index("annotate:progress")
        window = COMPAT[max(0, idx - 400):idx]
        self.assertIn(ANCHOR, window,
                      "every item change dispatches a progress event")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_progress_delivery.py -q`
Expected: FAIL — 4 of the 5 fail; `test_the_lock_is_still_cleared_by_an_ordinary_item` passes already.

- [ ] **Step 3: Implement**

In `skills/annotate/static/compat.js`, replace lines 208-211 with:

```js
      if (ev.kind === "event-acked") { if (busyLocal) setBusyLocal(false); return; }
      // The narration trail is written WHILE the page is locked, so it must
      // not be mistaken for the work finishing. Every other item change still
      // unlocks — that fallback exists for a daemon too old to send
      // `event-acked` and is not being weakened, only made specific.
      if (ev.anchor === PROGRESS) {
        document.dispatchEvent(new CustomEvent("annotate:progress",
                                               { detail: { version: ev.version } }));
        return;
      }
      if (ev.kind === "item" && busyLocal) setBusyLocal(false);
      handler({ finished: false, busy: busyLocal, consumed: [], blocks, threads }, before);
```

and declare the anchor beside the existing `DOC` / `PREV` constants near the top of the file:

```js
  const PROGRESS = "__progress__";
```

Returning early for the progress anchor is deliberate: `blocks` and `threads`
already exclude `__`-prefixed anchors (`:206`), so handing `script.js` a delta
for one asks it to re-render nothing. The panel is the only listener that cares.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_progress_delivery.py -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS. `test_smoke_read_only.py` and `test_smoke_subunits.py` both assert on compat.js's shape — if either fails, read what it is protecting before changing it.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/static/compat.js skills/annotate/tests/test_smoke_progress_delivery.py
git commit -m "Broadcast a narration line to the page without unlocking it"
```

---

### Task 4: The panel — `progress.js` and its stylesheet

**Files:**
- Create: `skills/annotate/static/progress.js`
- Modify: `skills/annotate/static/style.css` (append)
- Modify: `skills/annotate/static/entry.js:28-45` (the `JS` list)
- Test: `skills/annotate/tests/test_smoke_progress_panel.py`

**Interfaces:**
- Consumes: `annotate:progress` and `window.WebCompanion.fetchJSON("raw?block=__progress__")` from Task 3; the item body shape from Task 1.
- Produces, for Task 7's browser tests:
  - `#progress-panel` — the panel element, inserted immediately after `.page-header`, absent from the DOM entirely when there is no trail or the viewer is read-only.
  - `.pg-line` — one per step, newest last. `.pg-line.now` on the newest.
  - `#progress-feed` — the scrolling body; pinned to its bottom as lines arrive.
  - `.pg-caret` — the disclosure button. `#progress-panel[data-open="1"]` when the feed is showing.
  - `#progress-panel[data-state="working"|"done"]`.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_progress_panel.py`:

```python
"""The panel's shape, at the level source strings can see.

The behaviour that matters — lines arriving, the newest staying visible, the
collapse on done, and nothing at all for a guest — is browser-tested in
test_browser_review.py. These are the structural guarantees.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "progress.js").read_text() if (STATIC / "progress.js").exists() else ""
CSS = (STATIC / "style.css").read_text()
ENTRY = (STATIC / "entry.js").read_text()
CORE = (STATIC / "core.css").read_text()


class TestItIsLoaded(unittest.TestCase):
    def test_progress_js_is_in_the_entry_list(self):
        self.assertIn('"progress.js"', ENTRY)

    def test_it_loads_after_script_js(self):
        # It mounts relative to .page-header, which the shell paints, and it
        # reads window.WebCompanion, which compat.js installs.
        self.assertLess(ENTRY.index('"script.js"'), ENTRY.index('"progress.js"'))


class TestItListensRatherThanPolls(unittest.TestCase):
    def test_it_consumes_the_broadcast(self):
        self.assertIn('addEventListener("annotate:progress"', JS)

    def test_it_reads_the_item_through_the_route_compat_already_serves(self):
        self.assertIn('raw?block=__progress__', JS)

    def test_it_never_polls_the_daemon(self):
        # A poll would work and would also be a second source of truth for
        # something the stream already pushes. The panel does own ONE timer —
        # the elapsed clock — which is local and reads nothing.
        import re as _re
        for m in _re.finditer(r"setInterval\((.{0,400}?)\}, \d+\)", JS, _re.S):
            self.assertNotIn("fetchJSON", m.group(1),
                             "the panel polls the daemon on a timer")


class TestTheGuestSeesNothing(unittest.TestCase):
    def test_the_panel_is_gated_on_writability(self):
        # The trail names file paths and repository structure. The document is
        # what the author chose to share; how it was produced is not.
        self.assertIn("writable", JS)

    def test_the_stylesheet_hides_it_too(self):
        # Belt and braces: a JS gate that regresses must not silently expose
        # the trail on a shared link.
        self.assertIn("body.read-only #progress-panel", CSS)


class TestTheFeedPinsToTheNewestLine(unittest.TestCase):
    def test_it_scrolls_the_feed(self):
        # Measured in the mockup: with a max-height and no scroll management
        # the current line is the one clipped off the bottom.
        self.assertIn("scrollTop", JS)
        self.assertIn("scrollHeight", JS)

    def test_the_feed_has_a_bounded_height_to_scroll_within(self):
        rule = CSS[CSS.index("#progress-feed"):]
        rule = rule[:rule.index("}")]
        self.assertIn("max-height", rule)
        self.assertIn("overflow-y: auto", rule)


class TestItIsQuietButStillReadsAsALock(unittest.TestCase):
    def test_the_panel_keeps_an_accent_edge(self):
        # The accent ribbon was the only thing saying "you cannot submit
        # another round". The panel is quiet; the edge keeps the lock legible.
        rule = CSS[CSS.index("#progress-panel {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("border-left", rule)
        self.assertIn("var(--accent)", rule)

    def test_nothing_was_added_to_the_shared_core_stylesheet(self):
        self.assertNotIn("#progress-panel", CORE)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_progress_panel.py -q`
Expected: FAIL — `progress.js` does not exist, so `JS` is `""` and every assertion against it fails.

- [ ] **Step 3: Write `progress.js`**

Create `skills/annotate/static/progress.js`:

```js
// The narration panel — what Claude is doing, while the page waits.
//
// A reader comments on a block and Claude goes away for minutes. The page had
// a spinner and a ticking timer and nothing else: script.js's applyProgress
// has been receiving `undefined` since the daemon cutover, because compat.js's
// synthesised delta never carried a `progress` key, and the hook that used to
// produce labels went dormant in the same move.
//
// This is the reading half. compat.js re-broadcasts a `__progress__` item
// change as `annotate:progress` (it cannot reach script.js: compat.js:207
// strips `__`-prefixed anchors out of the version map), and this file re-reads
// the item and paints it.
(function () {
  "use strict";

  const ROUTE = "raw?block=__progress__";
  const PANEL_ID = "progress-panel";
  const FEED_ID = "progress-feed";

  // Open while working, because the complaint this answers is silence: a panel
  // that needs a click to reveal that anything is happening does not answer
  // it. The reader's own choice wins once they make one.
  let openPref = null;

  function writable() {
    const wc = window.WebCompanion;
    // Absent means the shim has not installed yet; treat as not writable and
    // let the next broadcast re-decide, rather than flashing the trail at a
    // guest for one frame.
    return !!(wc && wc.writable);
  }

  function clock(secs) {
    const s = Math.max(0, Math.floor(secs));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function spoken(secs) {
    const s = Math.max(0, Math.floor(secs));
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    return m + " min " + (s % 60) + " s";
  }

  function remove() {
    const el = document.getElementById(PANEL_ID);
    if (el) el.remove();
  }

  function ensure() {
    let el = document.getElementById(PANEL_ID);
    if (el) return el;
    el = document.createElement("section");
    el.id = PANEL_ID;
    el.className = "pg-panel";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.innerHTML =
      '<div class="pg-head">' +
        '<span class="pg-mark"></span>' +
        '<span class="pg-now"></span>' +
        '<span class="pg-count"></span>' +
        '<span class="pg-timer"></span>' +
        '<button type="button" class="pg-caret" aria-expanded="true"' +
          ' aria-controls="' + FEED_ID + '" aria-label="Show what Claude has done">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true">' +
          '<polyline points="18 15 12 9 6 15"></polyline></svg>' +
        '</button>' +
      '</div>' +
      '<div class="pg-feed" id="' + FEED_ID + '"></div>';
    el.querySelector(".pg-caret").addEventListener("click", () => {
      openPref = el.dataset.open !== "1";
      paintOpen(el);
    });
    // Same anchor the busy ribbon uses: directly under the header, so it pins
    // flush to the top of the screen when the page scrolls.
    const header = document.querySelector(".page-header");
    if (header) header.insertAdjacentElement("afterend", el);
    else document.body.insertBefore(el, document.body.firstChild);
    return el;
  }

  function paintOpen(el) {
    const open = openPref === null ? el.dataset.state === "working" : openPref;
    el.dataset.open = open ? "1" : "0";
    const caret = el.querySelector(".pg-caret");
    caret.setAttribute("aria-expanded", open ? "true" : "false");
    caret.setAttribute("aria-label",
                       open ? "Hide what Claude has done" : "Show what Claude has done");
  }

  function paint(body) {
    if (!body || !Array.isArray(body.steps) || !body.steps.length) { remove(); return; }
    if (!writable()) { remove(); return; }

    const el = ensure();
    const done = body.state === "done";
    el.dataset.state = done ? "done" : "working";

    const started = Number(body.started_at) || 0;
    const ended = Number(body.ended_at) || 0;
    const steps = body.steps;
    const last = steps[steps.length - 1];

    // The clock reads this rather than re-fetching the item every second.
    el.dataset.startedAt = String(started);

    el.querySelector(".pg-mark").className = "pg-mark " + (done ? "pg-tick" : "pg-spin");
    el.querySelector(".pg-mark").textContent = done ? "✓" : "";
    el.querySelector(".pg-count").textContent =
      steps.length + (steps.length === 1 ? " step" : " steps");

    if (done) {
      el.querySelector(".pg-now").textContent =
        "Claude worked for " + spoken(ended - started) + " across " +
        steps.length + (steps.length === 1 ? " step" : " steps");
      el.querySelector(".pg-count").textContent = "";
      el.querySelector(".pg-timer").textContent = "";
    } else {
      el.querySelector(".pg-now").textContent = last ? last.text : "";
      el.querySelector(".pg-timer").textContent =
        clock((Date.now() / 1000) - started);
    }

    const feed = document.getElementById(FEED_ID);
    feed.textContent = "";
    steps.forEach((s, i) => {
      const row = document.createElement("div");
      row.className = "pg-line" + (i === steps.length - 1 && !done ? " now" : "");
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = clock((Number(s.t) || started) - started);
      const txt = document.createElement("span");
      // textContent, never innerHTML: this string is Claude's prose and the
      // page must not become a place where it can inject markup.
      txt.textContent = s.text;
      row.append(t, txt);
      feed.appendChild(row);
    });

    paintOpen(el);
    // Pin to the newest line. Without this the one line the reader most wants
    // — the current one — is the line clipped off the bottom, measured in the
    // mockup this design was chosen from.
    feed.scrollTop = feed.scrollHeight;

    // A block being rewritten should still say so on the block.
    document.querySelectorAll(".updating-label").forEach((n) => {
      if (last && !done) n.textContent = last.text;
    });
  }

  // The one local timer: the elapsed clock. It reads nothing from the daemon —
  // every LINE arrives on the stream. Started when a trail is working, stopped
  // the moment it is not, so a finished round leaves nothing ticking.
  let ticking = null;

  function tick() {
    const p = document.getElementById(PANEL_ID);
    if (!p || p.dataset.state !== "working") {
      clearInterval(ticking); ticking = null; return;
    }
    const t = p.querySelector(".pg-timer");
    if (t) t.textContent = clock((Date.now() / 1000) - Number(p.dataset.startedAt || 0));
  }

  async function refresh() {
    if (!writable()) { remove(); return; }
    let body = null;
    try {
      body = await window.WebCompanion.fetchJSON(ROUTE);
    } catch (_) {
      // No trail yet is the common case on a fresh page, and a failed read
      // must never be louder than the document it sits above.
      remove();
      return;
    }
    paint(body);
    const el = document.getElementById(PANEL_ID);
    if (el && el.dataset.state === "working" && !ticking) {
      ticking = setInterval(tick, 1000);
    }
  }

  document.addEventListener("annotate:progress", refresh);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", refresh);
  } else {
    refresh();
  }
})();
```

- [ ] **Step 4: Add the stylesheet**

Append to `skills/annotate/static/style.css`:

```css
/* === The narration panel ===============================================
   What Claude is doing, while the page waits. Same anchor and sticky
   behaviour as .busy-banner (it sits directly under the header and pins to
   the top of the screen), but deliberately NOT the accent ribbon: this is
   information to read, not an alarm. The accent survives as a left edge,
   because the ribbon's colour was the only thing saying "you cannot submit
   another round" and that meaning must not be lost with its background. */
#progress-panel {
  position: sticky;
  top: 0;
  z-index: 19;
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 0 0 10px 10px;
  color: var(--text);
  font-size: 13px;
}
#progress-panel[data-state="done"] { border-left-color: var(--status-live-fg); }
body.read-only #progress-panel { display: none; }

.pg-head { display: flex; align-items: center; gap: 9px; padding: 10px 13px; }
.pg-now { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
          white-space: nowrap; }
.pg-count, .pg-timer {
  font-family: var(--font-code); font-size: 11px; color: var(--text-dim);
  flex: none;
}
.pg-mark { width: 14px; height: 14px; flex: none; display: inline-flex;
           align-items: center; justify-content: center; }
.pg-spin {
  border: 2px solid var(--accent); border-top-color: transparent;
  border-radius: 50%; animation: busy-spin 0.8s linear infinite;
}
.pg-tick { color: var(--status-live-fg); font-size: 14px; }
.pg-caret {
  background: none; border: 0; padding: 2px 4px; cursor: pointer;
  color: var(--text-dim); display: inline-flex; align-items: center; flex: none;
}
.pg-caret svg { width: 14px; height: 14px; fill: none; stroke: currentColor;
                stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
#progress-panel[data-open="0"] .pg-caret svg { transform: rotate(180deg); }

#progress-feed {
  border-top: 1px solid var(--border);
  padding: 7px 13px 10px;
  max-height: 190px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
#progress-panel[data-open="0"] #progress-feed { display: none; }
.pg-line {
  display: flex; align-items: baseline; gap: 10px;
  padding: 3px 0; color: var(--text-dim); line-height: 1.5;
}
.pg-line .t {
  font-family: var(--font-code); font-size: 10.5px; color: var(--text-dim);
  flex: none; width: 38px; font-variant-numeric: tabular-nums; opacity: .75;
}
.pg-line.now { color: var(--text); font-weight: 500; }
```

`busy-spin` is already defined in this stylesheet by `.busy-banner`; the panel
reuses it rather than declaring a second identical keyframe.

- [ ] **Step 5: Register it in `entry.js`**

In `skills/annotate/static/entry.js`, add `"progress.js"` to the `JS` array immediately after `"script.js"`:

```js
  "script.js",
  // After script.js: it mounts relative to .page-header and reads
  // window.WebCompanion, which compat.js installs before this list runs.
  "progress.js",
  "export.js",
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_progress_panel.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS. `test_smoke_read_only.py` and `test_smoke_subunits.py` assert on the entry list's contents and load order — if either fails, it is telling you the position you chose is wrong.

- [ ] **Step 8: Commit**

```bash
git add skills/annotate/static/progress.js skills/annotate/static/style.css skills/annotate/static/entry.js skills/annotate/tests/test_smoke_progress_panel.py
git commit -m "Paint the narration trail under the header while Claude works"
```

---

### Task 5: Retire the dead caption path

**Files:**
- Modify: `skills/annotate/static/script.js:3039-3067` (delete `applyProgress`) and `:3611` (its call)
- Delete: `skills/annotate/hooks/progress_publish.py`
- Test: `skills/annotate/tests/test_smoke_progress_delivery.py` (extend)

**Interfaces:**
- Consumes: `progress.js` now owns `.updating-label` (Task 4).
- Produces: nothing.

- [ ] **Step 1: Write the failing guards**

Append to `skills/annotate/tests/test_smoke_progress_delivery.py`:

```python
SCRIPT = (STATIC / "script.js").read_text()
HOOKS = Path(__file__).resolve().parents[1] / "hooks"


class TestTheDeadCaptionPathIsGone(unittest.TestCase):
    """applyProgress captioned the ribbon from a map keyed by event id, fed by
    `data.progress`. compat.js has never carried that key, so it has been a
    no-op since the cutover. progress.js replaces it."""

    def test_the_function_is_deleted(self):
        self.assertNotIn("applyProgress", SCRIPT)

    def test_nothing_reads_the_key_that_never_existed(self):
        self.assertNotIn("data.progress", SCRIPT)

    def test_the_dormant_hook_is_gone(self):
        self.assertFalse((HOOKS / "progress_publish.py").exists(),
                         "a file documenting a feature nobody can reach")

    def test_the_block_caption_still_has_an_owner(self):
        # .updating-label is not being dropped — it moved to progress.js.
        progress_js = (STATIC / "progress.js").read_text()
        self.assertIn("updating-label", progress_js)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_progress_delivery.py -q`
Expected: FAIL on the three deletion guards.

- [ ] **Step 3: Delete the function and its call**

In `skills/annotate/static/script.js`, delete the whole `applyProgress` block —
the comment beginning `// Caption the spinner with the live label the PostToolUse hook published`
through the closing brace of `function applyProgress(progress) { … }` — and
delete the line `applyProgress(data.progress);` at `:3611`.

Leave `pendingEvents` and everything else in that neighbourhood alone: other
code uses it.

- [ ] **Step 4: Delete the dormant hook**

```bash
git rm skills/annotate/hooks/progress_publish.py
```

If `skills/annotate/hooks/` is then empty, remove the directory too. Check first whether any doc references it:

```bash
grep -rn "progress_publish" --include='*.md' --include='*.py' --include='*.json' . | grep -v '\.superpowers'
```

Fix any reference you find; a doc pointing at a deleted file is the same defect in a different place.

- [ ] **Step 5: Run the tests and the suite**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A skills/annotate
git commit -m "Retire the caption path that has been fed undefined since the cutover"
```

---

### Task 6: The narration contract in the skill

The channel is useless if nothing writes to it. This is the task that makes narration happen.

**Files:**
- Modify: `skills/annotate/references/handling-events.md`
- Modify: `skills/annotate/SKILL.md`
- Test: `skills/annotate/tests/test_smoke_narration_contract.py`

**Interfaces:**
- Consumes: the CLI from Task 1.
- Produces: nothing in code.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_narration_contract.py`:

```python
"""Narration has to be a step, not a suggestion.

The bug being fixed is silence. An instruction to "narrate as you go" is the
same instruction the page already effectively had, and it produced five-minute
gaps. So the contract is numbered steps in the event flow, with the same
standing as acknowledging the event.
"""
import re
import unittest
from pathlib import Path

REFS = Path(__file__).resolve().parents[1] / "references"
EVENTS = (REFS / "handling-events.md").read_text()
SKILL = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()

CMD = "skills.annotate.progress"


class TestEveryEventPathNarrates(unittest.TestCase):
    def test_the_command_is_documented_with_its_flags(self):
        self.assertIn(CMD, EVENTS)
        self.assertIn("--text", EVENTS)
        self.assertIn("--done", EVENTS)

    def test_each_event_subsection_carries_a_narration_step(self):
        # One per handled event type. A path that does not narrate is a path
        # that goes silent, which is the whole defect.
        heads = [m.start() for m in re.finditer(r"^### `WEBCOMPANION_EVENT", EVENTS, re.M)]
        self.assertGreaterEqual(len(heads), 3, "the event sections moved")
        bounds = heads + [len(EVENTS)]
        for i, start in enumerate(heads):
            section = EVENTS[start:bounds[i + 1]]
            title = section.splitlines()[0]
            self.assertIn(CMD, section, f"{title} never narrates")

    def test_narration_comes_before_the_work_not_after(self):
        # A line written after a ninety-second search arrives ninety seconds
        # too late — the silence it was meant to fill already happened.
        self.assertRegex(EVENTS, r"(?i)before (each|any|the) step")

    def test_a_step_is_defined_so_it_does_not_mean_every_tool_call(self):
        self.assertRegex(EVENTS, r"(?i)not an individual tool")


class TestTheSkillMentionsIt(unittest.TestCase):
    def test_the_skill_points_at_the_contract(self):
        self.assertIn("progress", SKILL.lower())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_narration_contract.py -q`
Expected: FAIL — the command appears nowhere.

- [ ] **Step 3: Add the contract to `handling-events.md`**

Add a section immediately after "## The model in one paragraph":

```markdown
## Narrating while you work

The reader is looking at a page with a spinner on it. Between the moment they
comment and the moment you re-push, the only thing they can learn about what is
happening is what you tell them. Before the daemon cutover the page captioned
its spinner from a tool-name hook; that hook is gone and the caption was dead
for months. This is its replacement, and it is deliberately not automatic —
you write the lines, so they say something a tool name cannot.

Write a line with:

    python3 -m skills.annotate.progress --sid "$WC_SID" --text "Reading how anchors resolve"

and close the trail when the answer is pushed:

    python3 -m skills.annotate.progress --sid "$WC_SID" --done

A *step* is a distinct piece of work — a search, a pass of reading, a command
run, a rewrite — **not an individual tool call**. Three greps answering one
question are one step and get one line.

Narrate **before each step, not after it.** A line written after a ninety-second
search arrives ninety seconds too late: the silence it was supposed to fill has
already happened. This is the single rule that makes the feature work.

The line is prose the reader sees. Say what you are doing and, where it is not
obvious, why — "Looking for where the currency conversion actually happens"
beats "Searching". Never paste output, secrets, or tokens into it.

These commands are cheap and must never fail the turn: if one errors, carry on.
```

- [ ] **Step 4: Add narration steps to each event path**

In each `### WEBCOMPANION_EVENT…` subsection's numbered list, insert narration
as real numbered steps and renumber the rest:

- In the per-comment path (currently steps 1-6), insert after "Read the event payload…":
  `Narrate that you have it: python3 -m skills.annotate.progress --sid "$WC_SID" --text "Read your comment on <block_id>" --event-id "<event_id>"`
  and before the ack step:
  `Close the trail: python3 -m skills.annotate.progress --sid "$WC_SID" --done`
- In the `choice` path, the `dismiss` path and the `round` path, do the same:
  one narration step on receipt, one `--done` immediately before the existing
  re-push-and-ack step.

Every `### WEBCOMPANION_EVENT` subsection must end up containing
`skills.annotate.progress` — the test in Step 1 checks each one individually,
so a path you skip will name itself.

- [ ] **Step 5: Point `SKILL.md` at it**

In `skills/annotate/SKILL.md`, in the section describing the webcompanion
daemon, add one sentence:

```markdown
While handling an event, narrate what you are doing with
`python3 -m skills.annotate.progress` — the page shows it live, and the reader
has nothing else to go on. See `references/handling-events.md` § Narrating
while you work.
```

- [ ] **Step 6: Run the tests and the suite**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS. `test_skill_structure.py` and `test_docs_truth`-style suites check the skill's prose against the tree — if one fails, it has found a claim you made that is not true.

- [ ] **Step 7: Commit**

```bash
git add skills/annotate/references/handling-events.md skills/annotate/SKILL.md skills/annotate/tests/test_smoke_narration_contract.py
git commit -m "Make narrating what you are doing a step in every event path"
```

---

### Task 7: Prove it in a browser, end to end

**Files:**
- Modify: `skills/annotate/tests/test_browser_review.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the browser tests**

Append to `skills/annotate/tests/test_browser_review.py`:

```python
def _put_progress(document, steps, state="working", started=None, ended=None):
    """Write the trail the way skills/annotate/progress.py does."""
    import time as _t
    started = started or int(_t.time())
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__progress__", {
        "id": "__progress__", "kind": "progress", "state": state,
        "started_at": started, "ended_at": ended, "event_id": "evt-browser",
        "steps": [{"t": started + i, "text": s} for i, s in enumerate(steps)],
    })


def test_narration_reaches_the_page_without_a_reload(page, document):
    """The whole point: the reader learns something during the silence."""
    _put_progress(document, ["Read your comment on section-1"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    assert "Read your comment on section-1" in page.text_content("#progress-panel")

    _put_progress(document, ["Read your comment on section-1",
                             "Looking for where the conversion happens"])
    page.wait_for_function(
        "() => document.querySelectorAll('#progress-panel .pg-line').length === 2",
        timeout=10000)


def test_the_newest_line_is_visible(page, document):
    """Measured, not assumed: with a max-height and no scroll management the
    current line is the one clipped off the bottom."""
    _put_progress(document, [f"step number {i}" for i in range(30)])
    page.wait_for_function(
        "() => document.querySelectorAll('#progress-panel .pg-line').length === 30",
        timeout=10000)
    visible = page.eval_on_selector(
        "#progress-feed",
        "el => { const last = el.querySelector('.pg-line:last-child');"
        " const f = el.getBoundingClientRect(), l = last.getBoundingClientRect();"
        " return l.bottom <= f.bottom + 1 && l.top >= f.top - 1; }")
    assert visible, "the newest narration line is scrolled out of sight"


def test_it_collapses_to_a_summary_when_the_work_is_done(page, document):
    started = 1700000000
    _put_progress(document, ["one", "two"], state="done",
                  started=started, ended=started + 260)
    page.wait_for_function(
        "() => document.querySelector('#progress-panel')?.dataset.state === 'done'",
        timeout=10000)
    head = page.text_content("#progress-panel .pg-now")
    assert "4 min 20 s" in head, f"the summary does not say how long it took: {head}"
    assert page.eval_on_selector(
        "#progress-feed", "el => el.offsetParent === null"), \
        "the feed is still open after the work finished"

    page.click("#progress-panel .pg-caret")
    assert page.eval_on_selector("#progress-feed", "el => el.offsetParent !== null"), \
        "the summary does not expand"


def test_a_progress_write_does_not_unlock_the_page(page, document):
    """compat.js clears the busy lock on any item change. For this anchor that
    rule is backwards — the first narration line would dismiss the ribbon the
    narration captions."""
    page.eval_on_selector("body", "el => el.classList.add('is-busy')")
    page.evaluate("() => window.dispatchEvent(new Event('noop'))")
    _put_progress(document, ["still working"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    assert page.eval_on_selector(
        "body", "el => el.classList.contains('is-busy')"), \
        "a narration line unlocked the page"


def test_the_trail_never_becomes_a_block(page, document):
    before = page.eval_on_selector_all("section.block", "els => els.length")
    _put_progress(document, ["one"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    after = page.eval_on_selector_all("section.block", "els => els.length")
    assert before == after, "the progress item rendered as a block"


def test_a_read_only_reader_sees_no_trail_at_all(page, document):
    """The document is what the author chose to share. How it was produced —
    which files, which paths — is not."""
    _put_progress(document, ["Read montblanc/pricing/Normalizer.java"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    page.evaluate("() => { window.WebCompanion.__forceReadOnly = true;"
                  " document.body.classList.add('read-only');"
                  " document.dispatchEvent(new CustomEvent('annotate:progress',"
                  " { detail: { version: 99 } })); }")
    hidden = page.eval_on_selector(
        "#progress-panel", "el => el === null || el.offsetParent === null",
        strict=False) if page.query_selector("#progress-panel") else True
    assert hidden, "a guest can read the trail"
```

**Note for the implementer:** the last test fakes read-only by adding the body
class, because `writable` comes from the daemon and cannot be flipped from the
page. If `progress.js`'s JS gate (not the CSS rule) is what you want to prove,
you will need a genuinely non-owner page — fetch the session URL without the
token fragment in a fresh context. Do whichever you can make honest, and say in
your report which one you proved.

- [ ] **Step 2: Run the browser suite**

Run: `python3 -m pytest skills/annotate/tests/test_browser_review.py -q`
Expected: PASS, no skips. A skip means the daemon is not answering — fix that; a skipped browser suite is the failure this task exists to prevent.

- [ ] **Step 3: Run everything**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS, 0 skipped.

- [ ] **Step 4: Look at it**

Push a real document, comment on a block, and drive `skills/annotate/progress.py`
by hand from a second terminal to simulate Claude narrating. Watch the panel at
1512px and at 900px. Confirm: lines arrive without a reload; the newest is
visible; the header's current line truncates rather than wrapping the row; the
panel does not cover the first block; `--done` collapses it; the accent edge
still reads as a lock.

Save screenshots to `.superpowers/sdd/2026-09-21-progress-narration/shots/`.
Report anything that looks wrong even if every test is green — that is the point
of this step.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/tests/test_browser_review.py
git commit -m "Drive the narration panel in a browser against a live daemon"
```

---

## Self-Review

**Spec coverage.** Decision 1 (narration not labels) → Tasks 1 and 6. Decision 2 (items channel) → Tasks 1 and 3. Decision 3 (`PUT`, and push preserves the trail) → Tasks 1 and 2. Decision 4 (compat exemption) → Task 3, browser-proved in Task 7. Decision 5 (quiet but still a lock) → Task 4's stylesheet and its test. Decision 6 (open while working, collapsed when done) → Task 4, browser-proved in Task 7. Decision 7 (hidden from a guest) → Task 4 and Task 7. Decision 8 (pins to newest) → Task 4, measured in Task 7. Decision 9 (mandatory, not encouraged) → Task 6. The deletions table → Task 5. Every test listed in the spec's Tests section maps to a step above.

**Placeholder scan.** Two notes-to-implementer are deliberate and specific, not placeholders: Task 4 Step 3 names a test that contradicts the code it ships beside and says exactly how to reconcile it, and Task 7 Step 1 names the read-only test's limitation and asks which variant was proved. Both demand a decision and a report line rather than deferring work.

**Type consistency.** `ANCHOR`/`__progress__`, `note`/`finish`, `MAX_STEPS`, `annotate:progress`, `#progress-panel`, `#progress-feed`, `.pg-line`, `data-state`, `data-open` are spelled identically in every task that names them. `PROGRESS_ANCHOR` in Task 2 is an import alias for Task 1's `ANCHOR`, asserted as such by that task's third test.

**One defect found and fixed inline.** The first draft of Task 4 shipped a `progress.js` that its own Step 1 test rejected — a local `setInterval` for the elapsed clock against a test forbidding `setInterval` outright — plus a redundant second read of the item (`currentStarted`) on every refresh. Rather than hand an implementer a contradiction to reconcile, the test now forbids what it actually meant (polling the daemon on a timer, checked by looking inside each `setInterval` body for `fetchJSON`), the clock reads `started_at` off the panel's dataset, and the double read is gone.
