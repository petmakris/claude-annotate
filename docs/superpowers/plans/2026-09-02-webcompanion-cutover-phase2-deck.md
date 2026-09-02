# Webcompanion Cutover — Phase 2 (deck) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `deck` onto the webcompanion daemon — delete its private server entirely, following the pattern Phase 1 (`dataflow`) already proved, adapted for deck's real difference: its content is the user's own arbitrary, potentially large `.html` file, not something Claude generates fresh each time.

**Architecture:** `skills/deck/push.py` (new) copies the user's current deck file, plus deck's own plugin-shipped static assets, into one directory it controls, and registers that directory as the session's asset root — the fix for the size mismatch documented in the full-cutover spec's `deck` section (item bodies cap at 2MB; deck files run to tens of megabytes; assets carry no such cap, but the daemon's containment check requires everything served to physically exist inside the one registered directory, ruling out symlinks). A small `__model__` item (deck's existing `parse_deck()` output, computed at push time) tells the browser what to render and doubles as the daemon's change-notification signal — Claude re-runs `push.py` after every edit, which re-copies the file and re-pushes `__model__`, and the browser reacts to that item's `item-changed` SSE delta to reload, replacing the old fingerprint-polling mechanism entirely. `deck.js` is updated to call `window.WebCompanion.init({onDelta})` (the daemon's real runtime) instead of `init({onPollDelta})` (the *old* shared engine's `core.js`, which deck was actually written against — confirmed by reading the file, not assumed) and to reconstruct the "Claude is editing" busy indicator client-side, the same "lock on submit, unlock when it actually changes" pattern `annotate/static/compat.js` already established. Comment structure (deck/slide/path/ord/component/line_start/line_end/text/comment) has nowhere to go in the daemon's flat `{anchor, text, images}` submit body, so it travels JSON-encoded inside `text` — the same bridge `compat.js` uses for annotate's own multi-shape feedback.

**Scope discipline:** deck has no thread/comment-history model today (confirmed: `server.py`'s `handle_submit` never touches `threads_module` — comments are pure fire-and-forget events, unlike every other migrated skill). Adopting the daemon's thread system to give deck comment history for free is a real, named opportunity in the full-cutover spec, but it is **out of scope for this phase** — this migration is a faithful port, not a feature addition. Note it as a follow-up, do not build it.

**Tech Stack:** Python 3.9+ stdlib only. Vanilla JS, no new test framework (matches Phase 1's own finding: none exists for skill static JS).

**Spec:** `docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md` — read its `deck (Phase 2)` section before starting; this plan implements it. Also read `docs/superpowers/plans/2026-09-01-webcompanion-cutover-phase1-dataflow.md` (Phase 1's plan, now merged as commit `292d8b7` on `main`) as the closest prior art for `push.py`'s and `entry.js`'s shape — do not re-derive patterns it already established, reference them.

## Global Constraints

- No new third-party Python dependency.
- `kind` for deck is the literal string `"deck"` (the canonical spelling in `contract.md`'s kind table).
- Claude-authored content uses `role: "agent"` where applicable (deck currently has no thread messages at all — this constraint has no call site in this phase, noted for completeness).
- Every session-scoped daemon call goes through `skills/_shared/webcompanion_client.py` (Phase 1) — do not hand-roll a second HTTP client. `append_thread`/`get_threads`/`delete_thread` are not used by this phase (deck has no threads); `create_or_attach`, `put_items`, `get_items`, `register_assets`, `submit_event` are.
- Never delete a file's test coverage without repointing it at whatever survived, per Phase 1's own established precedent.
- The controlled directory `push.py` copies into must be a *real* directory containing *real* files — never symlinks — because the daemon's asset route resolves symlinks before its containment check and rejects anything that resolves outside the registered root (verified against `~/projects/webcompanion/src/webcompanion/server.py:786-796` during this program's design phase).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `skills/deck/push.py` (new) | Copies the plugin's `deck.js`/`deck.css`/`entry.js` (and `core.css`, if Task 2 determines deck genuinely needs it — see that task) plus a fixed-name copy of the user's current deck file into one directory under the session's own workspace; pushes `__model__`; registers that directory as the asset root. The only thing that knows how a deck maps onto the daemon. |
| `skills/deck/tests/test_push.py` (new) | Tests for `push.py`, client mocked for the daemon calls; real filesystem operations (via `tmp_path`) for the copy logic, since that's the part unique to this phase. |
| `skills/deck/server.py` (delete) | Superseded entirely by the daemon. |
| `skills/deck/ensure_server.sh` (delete) | No server to ensure. |
| `skills/deck/tests/test_server.py` (delete) | Tested the deleted server. |
| `skills/deck/static/entry.js` (new) | Registered asset entry point — loads whatever CSS/JS deck's page needs, in order, mirroring Phase 1's `dataflow/static/entry.js`. |
| `skills/deck/static/deck.js` (modify) | Talks to `/s/{sid}/items/__model__` and the fixed-name copied asset for the iframe; `window.WebCompanion.init({onDelta})`; client-side busy reconstruction; JSON-encoded submit payload. |
| `skills/deck/SKILL.md` (modify) | Documents the daemon-based flow: `push.py` for session creation and for re-pushing after every edit, `webcompanion watch`/`ack` for the Mode-D loop, JSON-decoding the event payload. |
| `skills/deck/README.md` (modify, if it exists and describes the old server — check first) | Same correction class as Phase 1's README fix. |

---

### Task 1: `entry.js` and `push.py` — the file-copy design

**Files:**
- Create: `skills/deck/static/entry.js`
- Create: `skills/deck/push.py`
- Create: `skills/deck/tests/test_push.py`

**Interfaces:**
- Consumes: `skills._shared.webcompanion_client` (Phase 1, unchanged) — `create_or_attach`, `put_items`, `register_assets`. `skills.deck.model.parse_deck` (existing, unchanged).
- Produces: `entry.js` (a static file `push.py` copies and registers — no Python interface, but `push.py`'s `PLUGIN_ASSETS` list names it, so it must exist before `push.py`'s own tests can pass). `push(deck_path: Path, cwd: str, *, slug: str | None = None, title: str | None = None) -> dict`, a `main(argv=None) -> int` CLI entry point (`python3 -m skills.deck.push --deck <path> --cwd <repo root> [--slug ...] [--title ...]`). Task 2 and Task 3 (SKILL.md) both reference this exact CLI shape.

**Note on ordering:** `entry.js` is created in this task, not Task 2, even though Task 2 is where its content gets finalized (Task 2 Step 1 may need to add a `core.css` load to it). `push.py`'s own tests copy real files out of `skills/deck/static/` — if `entry.js` didn't exist yet when this task's tests run, `_refresh_copy_dir` would raise `FileNotFoundError` on every test. Write a correct, working `entry.js` here (Step 1 below); Task 2 edits it in place only if its `core.css` investigation says to.

- [ ] **Step 1: Write `entry.js`**

Mirror `skills/dataflow/static/entry.js`'s shape (Phase 1) — a small IIFE loader, scripts appended to `document.body`, a visible `fail()` state. Before writing it, check whether `deck.js` already builds its own `#deckhead`/`#deckbody` markup on load, or whether that markup used to come from the now-deleted `server.py`'s `_page()` function (read that function now, ahead of Task 3's deletion, specifically to answer this one question) — if `deck.js` needs it injected, add that to `entry.js`; if `deck.js` already creates it, don't.

```javascript
/* entry.js — deck's registered asset entry point.
   Loads deck.css then deck.js, in that order. Mirrors
   dataflow/static/entry.js's own loader-stub role (Phase 1) — the daemon
   serves a session's renderer from exactly one directory, so anything
   deck's page needs beyond its own top-level script is loaded here.

   core.css is deliberately NOT loaded here yet — Task 2 Step 1 determines
   whether deck.css actually depends on it and updates this file if so.
*/
(function () {
  "use strict";
  const base = new URL("./", import.meta.url);
  const asset = (name) => new URL(name, base).href;

  function fail(message) {
    document.body.innerHTML = '<main class="waiting"><p></p></main>';
    document.body.querySelector("p").textContent = message;
  }
  function loadStylesheet(href) {
    return new Promise((resolve) => {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = href;
      l.onload = l.onerror = () => resolve();
      document.head.appendChild(l);
    });
  }
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("failed to load " + src));
      document.body.appendChild(s);
    });
  }

  loadStylesheet(asset("deck.css"))
    .then(() => loadScript(asset("deck.js")))
    .catch((e) => fail("This page failed to load: " + e.message));
})();
```

**The core design, spelled out precisely before any code:**

1. Resolve the deck's real path (`Path(deck_path).expanduser().resolve()`), same validation `server.py`'s old `create_session_extra` did: must exist, must be a file, suffix must be `.html` (case-insensitive) — read the old `server.py`'s exact validation before deleting it in Task 3, and replicate the same checks and error messages here, since Task 3's SKILL.md update assumes these checks already happened at push time, not session-creation time (there is no separate session-creation step any more — `push.py` IS session creation, the same shift Phase 1's `dataflow/push.py` made).
2. Compute (or reuse) a **stable, session-scoped working directory** to copy into. Use the daemon's own workspace convention: `Path.home() / ".claude" / "webcompanion" / "workspaces" / "deck" / <sid> / "assets"` is the daemon's OWN storage and not something `push.py` should write into directly (that would be reaching into another process's private state) — instead, create a directory `push.py` owns and controls, e.g. under the **session's `cwd`-independent** scratch area: `Path(tempfile.gettempdir()) / "claude-deck-assets" / <sid>` (created with `mkdir(parents=True, exist_ok=True)`), OR simpler and more inspectable: reuse the pattern every other migrated skill's `push.py` already uses for `STATIC_DIR` — a directory *inside the plugin itself* would be wrong here (it can't hold copies of files from arbitrary user repos across multiple concurrent sessions safely) — **use a directory keyed by `sid`, created after `create_or_attach` returns a real `sid`,** so the copy destination is deterministic and traceable to exactly one session, cleaned up naturally by the OS's temp-directory lifecycle (never delete it yourself — a session may still be open and the browser may still be requesting from it; do not build cleanup logic this phase does not need).
3. Copy into that directory, **every push** (both the first push and every re-push after an edit): the plugin's `skills/deck/static/entry.js`, `deck.js`, `deck.css` (and `core.css`/fonts if Task 2 determines they're needed — see that task's own resolution), plus the user's deck file under a **fixed name** (`content.html`, not the original filename) — a fixed name means `deck.js`'s iframe `src` never needs to know the original filename, only `assets/content.html`.
4. `put_items(sid, {"__model__": model}, kind="deck", replace=True)` where `model = parse_deck(deck.read_text(encoding="utf-8"))` — same shape `server.py`'s old `serve_data?query=model` produced, minus the two locally-computed fields it used to add (`deck`, an absolute path meaningless to a browser reading the daemon's item, and `fingerprint`, superseded entirely by the item's own daemon-computed `version` — the browser now reacts to `item-changed`'s `version` field, not a client-computed SHA1).
5. `register_assets(sid, str(copy_dir), "entry.js", kind="deck")` — same call shape as Phase 1's `dataflow/push.py`, re-sent on every push (idempotent, and necessary here since the copied `content.html` changes on every push).

**Write the failing tests first**, matching Phase 1's `dataflow/tests/test_push.py`'s mocking style (client functions mocked, real filesystem via `tmp_path`):

```python
# skills/deck/tests/test_push.py
from pathlib import Path
from unittest.mock import patch

from skills.deck import push


MINIMAL_DECK_HTML = """<!doctype html><html><body>
<div class="deck"><section class="slide"><div class="pro"><p>Point one</p></div></section></div>
</body></html>"""


def test_push_creates_session_copies_files_and_pushes_model(tmp_path):
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)

    with patch("skills.deck.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "s1", "kind": "deck",
                            "url": "http://127.0.0.1:3080/s/s1/", "token": "tok"}) as mock_create, \
         patch("skills.deck.push.wc.put_items") as mock_put, \
         patch("skills.deck.push.wc.register_assets") as mock_assets:
        res = push.push(deck_file, str(tmp_path), title="MyDeck")

    mock_create.assert_called_once_with("deck", str(tmp_path), title="MyDeck", slug=None)
    assert res["sid"] == "s1"

    # The pushed model item is real parse_deck() output, not a stub.
    put_call = mock_put.call_args
    assert put_call.args[0] == "s1"
    items = put_call.args[1]
    assert set(items.keys()) == {"__model__"}
    assert items["__model__"]["slides"][0]["elements"][0]["component"] == "pro"
    assert "deck" not in items["__model__"]      # locally-meaningless field dropped
    assert "fingerprint" not in items["__model__"]  # superseded by the item's own version
    assert put_call.kwargs == {"kind": "deck", "replace": True}

    # The copy directory actually contains a fixed-name copy of the deck, plus
    # the plugin's own static files, and register_assets points at it.
    assets_call = mock_assets.call_args
    assert assets_call.args[0] == "s1"
    copy_dir = Path(assets_call.args[1])
    assert assets_call.args[2] == "entry.js"
    assert assets_call.kwargs == {"kind": "deck"}
    assert (copy_dir / "content.html").read_text() == MINIMAL_DECK_HTML
    assert (copy_dir / "entry.js").is_file()
    assert (copy_dir / "deck.js").is_file()
    assert (copy_dir / "deck.css").is_file()


def test_push_rejects_a_non_html_file(tmp_path):
    not_html = tmp_path / "deck.txt"
    not_html.write_text("nope")
    try:
        push.push(not_html, str(tmp_path))
        assert False, "expected a ValueError"
    except ValueError as e:
        assert "html" in str(e).lower()


def test_push_rejects_a_missing_file(tmp_path):
    try:
        push.push(tmp_path / "nope.html", str(tmp_path))
        assert False, "expected a ValueError"
    except ValueError as e:
        assert "not found" in str(e).lower() or "no such" in str(e).lower()


def test_push_re_copies_updated_content_on_a_second_push(tmp_path):
    """The whole change-notification design depends on this: an edited file's
    new bytes must actually land in the copy directory on the next push, not
    a stale copy from the first push."""
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)

    with patch("skills.deck.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "myslug", "kind": "deck",
                            "url": "http://127.0.0.1:3080/s/myslug/", "token": "tok"}), \
         patch("skills.deck.push.wc.put_items") as mock_put, \
         patch("skills.deck.push.wc.register_assets") as mock_assets:
        push.push(deck_file, str(tmp_path), slug="myslug")
        copy_dir = Path(mock_assets.call_args.args[1])

        deck_file.write_text(MINIMAL_DECK_HTML.replace("Point one", "Point one, edited"))
        push.push(deck_file, str(tmp_path), slug="myslug")

    assert "Point one, edited" in (copy_dir / "content.html").read_text()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck && python3 -m pytest skills/deck/tests/test_push.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'skills.deck.push'`

- [ ] **Step 3: Read `skills/deck/server.py`'s exact validation logic before writing `push.py`**

`create_session_extra`'s current checks (resolve-before-suffix-check, must be a file, must be `.html`) must be replicated with the same reasoning (a symlinked non-`.html` file must not slip through a check run on the unresolved path) — read the comments in the current file, they explain exactly why the order matters, and this plan's own description above is not a substitute for reading the real code.

- [ ] **Step 4: Write `push.py`**

```python
"""Push a deck's current content to the webcompanion daemon.

Replaces the old flow — a per-skill server on a fixed port, reading the deck
file off disk on every request. There is no deck server any more: the
daemon owns the session, and this module is the only thing that knows how a
deck maps onto it.

The mapping:
    __model__    parse_deck()'s output — what deck.js renders

The deck's raw HTML is not pushed as an item (items cap at 2MB; real decks
run to tens of megabytes) — it is copied, under a fixed name, into a
directory this module controls and registers as the session's asset root,
alongside this skill's own static JS/CSS. Re-copied on every push, including
after every edit, which is also this design's change-notification signal:
`__model__`'s version changes each push, and the browser reacts to that
item's `item-changed` delta to reload — see skills/deck/static/entry.js and
docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md's
`deck (Phase 2)` section for the full reasoning.

Usage:
    python3 -m skills.deck.push --deck <path> --cwd <repo root>
                                [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.deck import model as model_module

KIND = "deck"
MODEL_ANCHOR = "__model__"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"
DECK_COPY_NAME = "content.html"
# Every plugin-owned static file that must be reachable from the copy
# directory alongside the deck itself. Kept as an explicit list, not a
# directory copy, so a stray file added to skills/deck/static/ later
# (a scratch file, an editor swapfile) is never silently shipped into a
# session's asset root.
PLUGIN_ASSETS = ["entry.js", "deck.js", "deck.css"]


def _resolve_deck(raw: str) -> Path:
    # Resolve BEFORE checking the suffix — see server.py's own comment on
    # this ordering, which this replicates: checking the supplied path's
    # suffix would let a symlink named `deck.html` pointing at a non-html
    # file through, and every read under a session's /s/<slug>/ is ungated
    # by design.
    deck = Path(raw).expanduser().resolve()
    if not deck.is_file():
        raise ValueError(f"deck not found: {deck}")
    if deck.suffix.lower() != ".html":
        raise ValueError(f"deck must be an .html file (resolved to {deck.name}): {deck}")
    return deck


def _copy_dir_for(sid: str) -> Path:
    d = Path(tempfile.gettempdir()) / "claude-deck-assets" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _refresh_copy_dir(copy_dir: Path, deck: Path) -> None:
    for name in PLUGIN_ASSETS:
        shutil.copyfile(STATIC_DIR / name, copy_dir / name)
    shutil.copyfile(deck, copy_dir / DECK_COPY_NAME)


def push(deck_path: Path, cwd: str, slug: str | None = None,
        title: str | None = None) -> dict:
    deck = _resolve_deck(str(deck_path))
    title = title or deck.stem

    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug)
    sid = res["sid"]

    copy_dir = _copy_dir_for(sid)
    _refresh_copy_dir(copy_dir, deck)

    model = model_module.parse_deck(deck.read_text(encoding="utf-8"))
    wc.put_items(sid, {MODEL_ANCHOR: model}, kind=KIND, replace=True)

    # Re-sent on every push — the copy directory's content.html just changed,
    # and re-registering is idempotent (same reasoning as Phase 1's push.py).
    wc.register_assets(sid, str(copy_dir), ENTRY, kind=KIND)

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.deck.push")
    ap.add_argument("--deck", required=True, help="path to the deck .html")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.deck), a.cwd, a.slug, a.title)
    except ValueError as e:
        print("deck push: %s" % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("deck push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Note for the implementer:** `model_module.parse_deck`'s exact return shape must be read from `skills/deck/model.py` before assuming the test's assertion (`items["__model__"]["slides"][0]["elements"][0]["component"]`) matches — adjust the test to the real shape if it differs; the point of the test is proving a *real* `parse_deck()` call happened and its *real* output (minus the two locally-computed fields) is what gets pushed, not matching this plan's guess at the exact key path.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck && python3 -m pytest skills/deck/tests/test_push.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck
git add skills/deck/static/entry.js skills/deck/push.py skills/deck/tests/test_push.py
git commit -m "Add deck's entry.js and push.py: file-copy asset design for the webcompanion daemon"
```

---

### Task 2: `deck.js` — daemon runtime, change notification, submit

**Files:**
- Modify: `skills/deck/static/deck.js`
- Modify: `skills/deck/static/entry.js` (created in Task 1 — edit in place only if Step 1 below finds `core.css` is needed)

**Interfaces:**
- Consumes: `push.py`'s `content.html`/`__model__` mapping (Task 1); `window.WebCompanion` (the daemon's runtime, `_wc/core.js`, loaded automatically by the shell page); `entry.js` (Task 1 — already exists and already works for the no-`core.css` case).

- [ ] **Step 1: Determine whether `core.css` is actually needed, and update `entry.js` if so**

Read `skills/deck/static/deck.css` in full and check whether it depends on anything `skills/_shared/web_companion/static/core.css` defines (CSS custom properties under `:root`, font-face declarations `deck.css` doesn't itself declare, a reset `deck.css` assumes). If deck's page looks correct with only `deck.css` loaded (Task 1's `entry.js` already does this), you're done — no edit needed. If `deck.css` genuinely depends on `core.css`: add `"core.css"` to `push.py`'s `PLUGIN_ASSETS` list (Task 1's file, revisit it here), copy `skills/_shared/web_companion/static/core.css` — plus its font files if it `@font-face`s them with a relative path that would break once served from deck's own directory — into `skills/deck/static/` as a checked-in copy (same "canonical source, per-skill copy" pattern `wc-threads.js` and `markdown-it.min.js` established in Phase 1), and add a `loadStylesheet(asset("core.css"))` call to `entry.js`'s existing `Promise` chain, loaded before `deck.css`. Verify by actually opening the page in a browser during Task 3's smoke test, not by reading CSS in isolation — a missing custom property fails silently (falls back to the browser default), not with an error.

- [ ] **Step 2: Update `deck.js`'s `fetchJSON("model")` call and the iframe's `src`**

Locate the exact current lines (`renderDeck()`'s `fetchJSON("model")` call, `mountSlide`'s `f.src = BASE + "deck#slide-" + index`) — do not trust this plan's line numbers, re-locate them in the real file.

```javascript
  async function renderDeck() {
    const item = await fetchJSON("items/__model__");
    state.model = item.body;
    // ... rest of renderDeck unchanged
  }
```

```javascript
    f.src = BASE + "assets/content.html#slide-" + index;
```

`fetchJSON` itself (the plain `fetch(BASE + path, {cache: "no-store"})` wrapper near the top of the file) does not need to change — it already builds a same-origin, cache-busted GET, which is exactly right for `items/__model__`. Leave it as a raw `fetch`, not `window.WebCompanion.api.fetchJSON` — **this is a deliberate divergence from Phase 1's dataflow.js, not an oversight**: dataflow.js switched to `window.WebCompanion.api.*` specifically so the contract header and write token travel automatically on every read; deck's `items/__model__` read is a GET with no write concern, and `fetchJSON`'s existing `{cache: "no-store"}` option has no equivalent in the daemon's `api.fetchJSON` signature — check `_wc/core.js`'s actual `fetchJSON` implementation before deciding definitively, but do not assume the two must be unified just because Phase 1 used the daemon's version; use whichever preserves `{cache: "no-store"}`'s real behavior (still fetching fresh content on every poll-triggered reload).

- [ ] **Step 3: Replace `onPoll`'s wiring — `init({onDelta})`, not `init({onPollDelta})`**

This is the one genuinely new piece of logic in this phase (not a straight port from Phase 1, which had no equivalent — dataflow's `boot()`/`connect()` never had a "busy" concept). Read `skills/annotate/static/compat.js`'s `setBusyLocal`/`toOldShape` functions (Phase before this program started, already shipped) as the precedent for exactly this problem — "lock on submit, unlock when an item actually changes" — before writing this, since it is solving the identical problem deck now has (the daemon reports no unacked-event state, where the old server did).

```javascript
  let busyLocal = false;
  function setBusyLocal(v) {
    busyLocal = !!v;
    setBusy(busyLocal, 0);   // deck's existing setBusy(on, queued) — queued
                             // has no daemon equivalent; always 0 once locked
  }

  function connect() {
    window.WebCompanion.init({
      onDelta(ev) {
        if (ev.kind === "item" && ev.anchor === "__model__" && !ev.initial) {
          setBusyLocal(false);
          reloadEverything().catch(e =>
            console.warn("deck reload failed, will retry on the next change", e));
        }
      },
    });
  }
```

Replace the `DOMContentLoaded` listener's `window.WebCompanion.init({ onPollDelta: onPoll })` call with `connect()`. Delete `onPoll` and `lastFingerprint` entirely (superseded by the item-delta approach — there is no longer a fingerprint to compare, `item-changed` on `__model__` already means "content changed").

Wire `setBusyLocal(true)` into the submit path (Step 5 below), matching annotate's own "lock on submit" half of the pattern.

- [ ] **Step 4: Update the submit call — JSON-encode the structured payload**

Locate `submit()` inside `openPopup`'s closure (around the code that currently does `await window.WebCompanion.api.submit({slide, path, ord, component, line_start, line_end, text, comment})`). The daemon's `/api/submit` stores exactly `{anchor, text, images}` and drops every other key — the same constraint annotate's own migration already documented and solved.

```javascript
    async function submit() {
      const text = ta.value.trim();
      if (!text) { err.textContent = "Say what should change."; err.style.display = ""; return; }
      send.disabled = true;
      send.textContent = "Sending…";
      const anchor = "slide:" + e.slide + ":" + e.path + ":" + (e.ord || 0);
      const envelope = {
        type: "deck_comment", deck: state.model.deck, slide: e.slide, path: e.path,
        ord: e.ord || 0, component: e.component, line_start: e.line_start,
        line_end: e.line_end, text: e.text, comment: text,
      };
      try {
        await window.WebCompanion.api.submit({ anchor, text: JSON.stringify(envelope) });
        setBusyLocal(true);
        if (sel.node) sel.node.classList.add("deck-working");
        closePopup();
      } catch (ex) {
        err.textContent = String(ex.message || ex);
        err.style.display = "";
        send.disabled = false;
        send.textContent = "Send to Claude";
      }
    }
```

**Note:** `state.model.deck` no longer exists (Task 1 dropped that field from the pushed `__model__` item, since it was an absolute path meaningless to a browser). Read the current `submit()` code to see what it actually does with `deck` in the payload today (the old event shape includes a `"deck"` field with the absolute path, which `SKILL.md`'s Mode-D handler reads to know which file to `sed`/`Edit`) — since the browser no longer has this value, either (a) drop it from the envelope and have Claude's Mode-D handler resolve the deck path from the session's own `meta.json`/registry instead (check whether the daemon's session object exposes `cwd`+something deck-specific, or whether `push.py` should stash the absolute deck path onto `__model__` after all, accepting the minor inconsistency, since unlike `dataflow`'s `cwd` field this one is never read by the browser, only by Claude reading the event later) — **resolve this by checking what SKILL.md's Mode-D handler actually needs and where it can get it now**, not by guessing; this is exactly the kind of thing Task 3 (which rewrites SKILL.md) needs to get right, so coordinate the two tasks' understanding of where the deck's absolute path lives post-migration before finalizing either.

- [ ] **Step 5: Manual smoke test note for Task 3**

This task's own changes cannot be fully verified without a live daemon and a real deck file (the "does core.css matter" question especially) — Task 3 owns the actual smoke test; this task's implementer should still sanity-check with a quick local read-through and, if time allows, a preliminary browser check, but the authoritative verification is Task 3's.

- [ ] **Step 6: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck
git add skills/deck/static/entry.js skills/deck/static/deck.js
git commit -m "Rewire deck.js onto the daemon's real runtime (init/onDelta, item-based model, JSON-encoded submit)"
```

---

### Task 3: Delete deck's server; update SKILL.md/README.md; smoke test

**Files:**
- Delete: `skills/deck/server.py`
- Delete: `skills/deck/ensure_server.sh`
- Delete: `skills/deck/tests/test_server.py`
- Modify: `skills/deck/SKILL.md`
- Modify: `skills/deck/README.md` (if it references the old server — check first)

**Interfaces:**
- Consumes: `push.py` (Task 1), the daemon-facing `deck.js` (Task 2).

- [ ] **Step 1: Confirm `test_server.py`'s coverage before deleting, same discipline as Phase 1's Task 3 Step 1**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck && python3 -m pytest skills/deck/tests/test_server.py -v --collect-only`, check every test against `Handlers`' methods, confirm none test `model.py` independently of the deleted server (if any do, move them to `test_model.py` first).

- [ ] **Step 2: Read `server.py`'s `_page()` function before deleting it**

This resolves Task 2 Step 2's open question about `#deckhead`/`#deckbody` markup — confirm whether `deck.js` itself builds this DOM on load (in which case `entry.js` needs no injection) or whether the old server's shell printed it (in which case `entry.js` must inject it, the same way Phase 1's `dataflow/static/entry.js` injects `#app`). Fix Task 2's `entry.js` now if it guessed wrong.

- [ ] **Step 3: Resolve the `state.model.deck` question from Task 2 Step 4**

Read the current `SKILL.md`'s "Handling a comment" section (the JSON payload example with `"deck":"/abs/path/deck.html"`) to see exactly how Claude currently learns the deck's absolute path from an event. Decide, and implement consistently across `deck.js`'s `submit()` envelope (Task 2) and `SKILL.md`'s new documentation (this task):
- If `push.py` is changed to also stash the absolute deck path onto `__model__` (accepting that one field is browser-irrelevant but Claude-relevant), update Task 2's `push.py`/`test_push.py` accordingly (this reopens Task 1 — note it in your report if this is the path taken, since it means Task 1's "dropped meaningless field" framing was wrong and needs a one-line correction in `push.py`'s own comment).
- If instead the deck's path should come from somewhere else entirely (the session's own `cwd` plus a filename convention, or a value `create_or_attach`'s response already carries), use that instead and leave `push.py` as Task 1 wrote it.
Pick one, implement it consistently, and say which in your report — do not leave the two files disagreeing about where this value lives.

- [ ] **Step 4: Delete the old server**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck
git rm skills/deck/server.py skills/deck/ensure_server.sh skills/deck/tests/test_server.py
```

- [ ] **Step 5: Update `SKILL.md`**

Read `skills/dataflow/SKILL.md` (Phase 1, already migrated, on `main`) as the closest prior art for the daemon-era section shape. Replace:
- "Ensure the server is running, then create or attach a workspace" (the whole `ensure_server.sh`/`curl POST /api/sessions` block) → `python3 -m skills.deck.push --deck "$DECK_PATH" --cwd "$PWD" --title "$DECK_NAME"`, printing the returned `url`.
- The watcher arm step → `webcompanion watch --kind deck --sid <sid>` (Monitor), matching Phase 1's own SKILL.md wording.
- The event payload description → note that `text` is now a JSON-encoded envelope (matching Task 2's `submit()` envelope shape exactly — copy the real field names from the actual `deck.js` code, not from this plan's sketch) that Claude must `json.loads()` before reading `deck`/`slide`/`path`/etc.
- The `curl ".../model"` post-edit check → **re-running `push.py` with the same `--slug`**, which both re-copies the edited file (so the browser's iframe reload shows the new content) and re-pushes `__model__` (so the daemon notifies the browser at all — without this, the browser never learns the edit happened). This is the load-bearing change: the old "browser repaints on its own within a second of the file changing" claim (a fingerprint-polling behavior) is no longer true on its own — the repaint now happens only because Claude's own edit workflow re-runs `push.py`. State this plainly, since it changes what Claude must do, not just how a URL is spelled.
- The ack step (`touch "<consumed_dir>/<event_id>.ack"`) → `webcompanion ack --sid <sid> --event-id <event_id>`.

Keep every house-style/wording/grounding section (the whole "Ground the words before you write them" through "Rules that are not negotiable" block) completely unchanged — none of that is server-related.

- [ ] **Step 6: Update `README.md` if it describes the old server**

Check first (`grep -n "server\|ensure_server\|port 3090" skills/deck/README.md`); if it does, correct it the same way Phase 1's `dataflow/README.md` was corrected.

- [ ] **Step 7: Manual smoke test against the real live daemon**

The authoritative verification for this whole phase. Confirm the daemon is running (`webcompanion status`). Using a real, non-trivial local `.html` deck file (construct a small multi-slide fixture if none is conveniently at hand — it must have at least two slides and at least one `.pro`/`.con`-style classed element, matching what `model.py`'s `parse_deck` actually expects; read `skills/deck/tests/test_model.py`'s existing fixtures for a ready-made real example rather than inventing shapes that might not parse):

1. Push it via `push.py`, open the returned URL in a real browser (`playwright-headless` if available).
2. Confirm the deck actually renders — slides visible, styled (this is where Task 2 Step 1's `core.css` question gets its real answer).
3. Click an element, submit a comment, and confirm — by reading the daemon's own event file on disk, not just "no error was thrown" — that the stored `text` is the JSON-encoded envelope with every field Task 2's `submit()` sends.
4. Simulate Claude's side: edit the actual deck file's underlying HTML (a small, real text change), re-run `push.py --slug <same slug>`, and confirm — with the browser page left open, no reload — that the iframe's content actually updates live (this is the core mechanism this whole phase's design rests on; it is not optional to skip).
5. Ack the event (`webcompanion ack`), finish the session (`POST .../api/finish`), confirm cleanup.

- [ ] **Step 8: Run the full suite**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck && python3 -m pytest skills -q`
Expected: same 1107 baseline (from `main`, post-Phase-1) plus this phase's new tests, minus `test_server.py`'s deleted tests, zero failures.

- [ ] **Step 9: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-deck
git add -A skills/deck/
git commit -m "Migrate deck onto the webcompanion daemon; delete its private server"
```

---

## Testing strategy

Same shape as Phase 1: real unit tests for the Python side (client already tested in Phase 1; this phase's own `push.py` gets real filesystem-backed tests), no new JS test framework (none exists, none introduced), and a mandatory manual smoke test against the real running daemon as the only verification for the browser-facing change-notification mechanism — Phase 1's final review found exactly the class of bug (a silently broken user-facing affordance) that only a real smoke test catches, so this phase's Task 3 smoke test explicitly exercises the live-edit-reload path end to end, not just an initial page load.

## Final verification

- [ ] `python3 -m pytest skills -q` — clean, no unexpected failures.
- [ ] Manual smoke test (Task 3, Step 7) completed and recorded, including the live-edit-reload proof.
- [ ] `grep -rn "from skills._shared.web_companion\|import skills._shared.web_companion" skills/deck/` returns nothing.
- [ ] Confirm the daemon is left healthy (`webcompanion doctor`) and the smoke-test session was finished, not left dangling.
