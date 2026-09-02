# Webcompanion Cutover — Phase 3 (walkthrough) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `walkthrough` onto the webcompanion daemon — delete its private server entirely. The Python side is a small, proven port (Phase 1/2's shape). The real weight is `ide-plugin/.../WalkthroughSessionClient.java`: the daemon's wire shapes for session discovery, thread deltas and event submission all differ from what this client parses today, in ways verified live against the running daemon during this plan's own research (not assumed from `contract.md` prose) — see each finding cited below with its exact evidence.

**Architecture:** `skills/walkthrough/push.py` (new) pushes the already-validated `steps.json` document as a `__steps__` item and creates/attaches the session with `supersede=True` — unlike Phase 1's `dataflow`, which deliberately does *not* set `supersede` (see Global Constraints below for why walkthrough's case is different). Walkthrough has no browser page (`IDE_PAGE`/`CLOSED_PAGE` in the deleted server are just a "go open IntelliJ" placeholder), so `push.py` never calls `register_assets` — this phase has no `entry.js`, no `static/` directory, no browser JS at all. `WalkthroughSessionClient.java` is reworked to speak the daemon's real routes: `GET /api/sessions?cwd=&kind=walkthrough` (a raw array, no `state_dir` field, not guaranteed sorted — the client must pick the session correctly itself), `GET /s/{sid}/items?kind=walkthrough` for `__steps__` (replacing `/steps.json`), `GET /s/{sid}/threads?kind=walkthrough` for the bulk thread map (already used for the initial seed; now also re-fetched on every `thread-changed` SSE event, since that frame carries only `{anchor, version}` and no derived content), `POST /s/{sid}/api/submit?kind=walkthrough` with a flat `{anchor, text}` body (dropping `type`, which the IDE has only ever sent as the literal `"comment"` — confirmed dead, see Task 2 Step 3), and `GET /s/{sid}/poll?kind=walkthrough` (whose shape has no `ended`/`steps_generated_at` fields — both are recomputed client-side from what the daemon's poll actually returns).

**Scope discipline:** This is a faithful port of walkthrough's existing behavior onto new wire shapes, not a feature change. The one deliberate behavior change (using `supersede=True` where `dataflow` chose not to) is justified in Global Constraints and is a *simplification* of an existing guarantee already documented in the current `SKILL.md` ("one active tour per project"), not a new guarantee. Do not add thread history features, do not change the IDE's UI, do not touch `WalkthroughController.java`/`WalkthroughPanel.java`/`WalkthroughDoc.java`/`WalkthroughNavigator.java`/`WalkthroughActions.java` — all four were read during this plan's research and confirmed to consume only `WalkthroughSessionClient`'s already-derived Java objects (`SessionInfo`, `ThreadState`, `WalkthroughDoc`, the `Listener` callbacks), never raw HTTP/JSON themselves. Only `WalkthroughSessionClient.java` and its test talk to the wire.

**Tech Stack:** Python 3.9+ stdlib only (Task 1). Java 17, existing `HttpClient`/Gson stack, no new dependency (Task 2).

**Spec:** `docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md` — read its `walkthrough (Phase 3)` section and `## The shared client module` section before starting; this plan implements and, in three places, corrects it against live-daemon evidence the spec itself didn't have (each correction is called out inline below). Also read `docs/superpowers/plans/2026-09-02-webcompanion-cutover-phase2-deck.md` (Phase 2, merged as commit `3a0b50a` on `main`) for `push.py`'s proven shape, and `skills/dataflow/push.py` (Phase 1, merged as part of `292d8b7`) as the closer template for this phase specifically, since — like dataflow, unlike deck — walkthrough pushes one Claude-generated JSON document and needs no asset-copying machinery.

## Global Constraints

- No new third-party Python dependency. No new third-party Java dependency.
- `kind` for walkthrough is the literal string `"walkthrough"`.
- Every session-scoped daemon call from Python goes through `skills/_shared/webcompanion_client.py` (Phase 1) — do not hand-roll a second HTTP client. `create_or_attach`, `put_items`, `get_items` are used; `register_assets` is **not** (no browser page); `append_thread`/`get_threads`/`delete_thread`/`submit_event` are not used by `push.py` (Claude's own reply path still uses `skills._shared.web_companion.reply_cli`'s daemon-aware successor from Phase 1/2's own retrofit — confirm this module already routes through the daemon before assuming it needs changes here; if it doesn't yet, that is this phase's Task 1 responsibility too, see Task 1 Step 4).
- **`push.py` passes `supersede=True` to `create_or_attach` — the one deliberate deviation from Phase 1's dataflow, which does not.** `dataflow/SKILL.md` documents exactly why it opted out: the daemon's `supersede` flag ends every *other* live session of the same `(kind, cwd)` pair regardless of which Claude conversation started it, and dataflow's UX tolerates old sessions accumulating as extra browser tabs rather than risk silently ending a different conversation's trace. Walkthrough's UX does not have that tolerance — the IDE panel shows exactly one tour at a time per project, and the *current* `SKILL.md` (`## Create a session`, "One active tour per project") already documents walkthrough intentionally cancelling any pre-existing walkthrough session for the same cwd on every new invocation, regardless of which Claude conversation created it — the daemon's `supersede` flag is a direct, atomic replacement for that already-accepted behavior, not a new one. The one real behavior *change*: today, `supersede_by_claude_session = True` also cancels a walkthrough in a **different** cwd if it was started by the *same* Claude conversation; `supersede=True` is scoped to `(kind, cwd)` and does not reach across cwds. Accepted limitation, named here rather than replicated: a Claude session that runs `/walkthrough` in project A and then in project B no longer auto-closes project A's tour. Its watcher stays armed and still answers questions if any arrive; it does not interfere with project B's tour, since they are different `cwd`s and thus different sessions. Do not build cross-cwd tracking to replicate this — YAGNI, and it was never load-bearing for correctness, only tidiness.
- **The daemon's `GET /api/sessions?cwd=...&kind=...` response is a raw JSON array of rows shaped `{sid, slug, kind, cwd, title, url}` — confirmed live against the running daemon during this plan's research, not assumed from `contract.md` prose.** There is **no `state_dir` field** (the field `WalkthroughSessionClient.SessionInfo.stateDir` reads today) — and nothing in `WalkthroughController`/`WalkthroughPanel`/`WalkthroughDoc`/`WalkthroughNavigator`/`WalkthroughActions` ever reads `SessionInfo.stateDir()` either (confirmed by grep during this plan's research: the field is only ever written, never read) — so it is dropped from `SessionInfo`, not replaced with an empty string.
- **The array is not guaranteed sorted, and does not exclude finished/cancelled sessions — both confirmed by reading `webcompanion/src/webcompanion/registry.py`'s `find()` (used by the daemon's `_list_sessions`) during this plan's research: it returns matches in registry-iteration order with no sort, and `_row()` (the shape each match is serialized to) carries no `finished`/`cancelled`/`ended` field at all.** Today's `fetchNewestSession()` blindly takes `array[0]`, which was safe under the old per-skill server (one process, one session pool, always freshly created) but is not safe against the daemon, where old terminal sessions for the same cwd persist in the list indefinitely (no default retention sweep — confirmed separately during this program's session-leak investigation). This is a correction to the master spec, which did not anticipate ordering or terminal-session accumulation as a concern for this route. The session's own `sid` embeds a lexicographically sortable creation timestamp (observed live: `260902-095534-fb23f0457a77037d`, `YYMMDD-HHMMSS-<hex>` — confirmed by creating two sessions moments apart and comparing), so the fix is to pick the row with the lexicographically greatest `sid` among the matches, never `array[0]`. Combined with the `supersede=True` decision above, this is correct: the newest `sid` for `(kind=walkthrough, cwd)` is always the one Claude most recently created (and by definition the only one still live), regardless of how many terminal ones preceded it.
  This invariant carries two narrow preconditions, not a guarantee the daemon enforces unconditionally: (1) `Registry.make_sid` (`~/projects/webcompanion/src/webcompanion/registry.py`) builds the sortable sid prefix from **local** time (`time.strftime('%y%m%d-%H%M%S')`), so a DST fall-back — or a machine's clock moving backward for any other reason — could invert sid ordering for two sessions created in the repeated hour. (2) The `webcompanion` CLI's own `push --kind walkthrough` command defaults `--supersede` off (`action="store_true"` in `commands/push.py`) — "the newest sid is the only one still live" is a convention this phase's `push.py` honors by always passing `supersede=True`, not something the daemon itself guarantees for every writer. A session created any other way (e.g. someone hand-running the daemon's own CLI without `--supersede`) would not honor it.
- **The `GET /api/sessions` call itself must pass `&kind=walkthrough`.** Confirmed live: omitting `kind` returns sessions of *every* kind for that cwd (a `dataflow` session was returned by an unfiltered query against the same cwd during this plan's research) — today's `fetchNewestSession()` sends no `kind` param at all, which is a live latent bug once pointed at a daemon session (it would attach to another skill's session for the same project and try to parse it as a walkthrough). Defense in depth: after filtering by the query param, also assert the row's own `"kind"` field equals `"walkthrough"` before accepting it, the same defensive-parsing posture `create_or_attach`'s dual-shape handling already models for this exact class of daemon-response mistrust.
- **The `thread-changed` SSE frame is `{anchor, version}` only — confirmed live** (posted a thread message against a real session and captured the actual SSE bytes: `event: thread-changed` / `data: {"anchor": "step:1", "version": 1}`, no `initial` key on a non-initial change). `toThreadState(data)` today parses that same JSON object as if it already carried `latest_synthesis`/`title`/`question` — it never will under the daemon. The fix: on any `thread-changed` (and the existing initial `seedThreads()` path), fetch `GET /s/{sid}/threads?kind=walkthrough` (bulk; confirmed live shape: `{anchor: {anchor, version, messages: [{text, role, ts}], title}}`) and derive `latest_synthesis`/`question`/`updated_at` the same way `skills/_shared/static/wc-threads.js`'s `derive()` function already does in JS for every browser-facing migrated skill: the last `role: "agent"` message's `text` is `latest_synthesis`, its `ts` is `updated_at`, the last `role: "user"` message's `text` is `question`, and a thread with **no** agent message yet is omitted entirely (matches today's own `threads_bulk()` Python behavior exactly — read it at `skills/walkthrough/server.py:78-111` before writing the Java port, it is the same derivation, just in Python).
- **`/api/submit`'s body has no `type` field — confirmed live** (`{"anchor":"step:1","text":"probe question"}` was accepted with a 202 and no server-side complaint about a missing field). `postAsk` today sends `{anchor, type: "comment", text}`; `type` is dropped, not bridged into a JSON-encoded envelope. This is a real, evidence-based correction to the spec, which assumed a bridge (matching `annotate`/`deck`'s own JSON-in-`text` pattern) might be needed for the `"comment"`/`"reject"` distinction. Task 2 Step 3 confirms why a bridge is unnecessary here specifically.
- Claude-authored thread messages use `role: "agent"` (the daemon's default, per every other migrated skill) — `reply_cli`'s successor already sets this; confirm it during Task 1, do not assume.
- Never delete a file's test coverage without repointing it at whatever survived (Phase 1/2's own precedent) — this applies to `skills/walkthrough/tests/test_server.py` (Task 3) and to the Java `WalkthroughSessionClientTest.java` fixtures (Task 2), which pin the *old* wire shapes today and must be rewritten to pin the *real* ones, not deleted.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `skills/walkthrough/push.py` (new) | Validates and pushes `steps.json` as the `__steps__` item; creates/attaches with `supersede=True`. The only thing that knows how a walkthrough document maps onto the daemon. No asset registration — walkthrough has no browser page. |
| `skills/walkthrough/tests/test_push.py` (new) | Tests for `push.py`: validation failure surfaces cleanly, `supersede=True` is actually passed, the daemon client calls are exercised (mocked) with the right `kind`. |
| `skills/walkthrough/server.py` (delete) | Superseded entirely by the daemon. |
| `skills/walkthrough/ensure_server.sh` (delete) | No server to ensure. |
| `skills/walkthrough/tests/test_server.py` (delete, coverage triaged first) | Tested the deleted server; `steps.py`'s own validation logic (tested indirectly through `test_server.py` today) must already be covered by `skills/walkthrough/tests/test_steps.py` — confirm before deleting, per Task 3 Step 1. |
| `skills/walkthrough/SKILL.md` (modify) | Documents the daemon-based flow: `push.py` for session creation (replacing the curl-based create-and-cancel-prior-tour dance, now atomic via `supersede=True`), `webcompanion watch`/`ack` for Mode D (already the pattern Phase 1/2 use), the simplified event payload (`type` gone), reading `__steps__` back via `wc.get_items`. |
| `skills/walkthrough/README.md` (modify, if it exists and describes the old server — check first) | Same correction class as Phase 1/2's README fixes. |
| `ide-plugin/src/main/java/com/petros/ireview/WalkthroughSessionClient.java` (modify) | The real weight of this phase — reworked per the Global Constraints above: session discovery (`kind` filter, max-`sid` selection, dropped `stateDir`), thread-delta derivation (bulk-fetch + Java port of `wc-threads.js`'s `derive()`), submit payload (drop `type`), poll (daemon's real `/poll` shape). |
| `ide-plugin/src/test/java/com/petros/ireview/WalkthroughSessionClientTest.java` (modify) | Every fixture that encodes the *old* wire shapes (`sessionsRow`'s `state_dir` field, `thread-changed` payloads carrying `latest_synthesis` directly, submit-body assertions) is rewritten to encode the *real* ones. The fake test server (`FakeReviewServer`, shared with `ReviewSessionClientTest` — confirm its actual location before editing) needs a way to serve the bulk `/threads` route's real shape if it does not already. |

---

### Task 1: `push.py` — the Python side

**Files:**
- Create: `skills/walkthrough/push.py`
- Create: `skills/walkthrough/tests/test_push.py`

**Interfaces:**
- Consumes: `skills._shared.webcompanion_client` (Phase 1, unchanged) — `create_or_attach`, `put_items`. `skills.walkthrough.steps.validate`/`write_steps`/`load_steps` (existing, unchanged — `push.py` validates before pushing the same way `dataflow/push.py` validates before pushing).
- Produces: `push(steps_path: Path, cwd: str, *, slug: str | None = None, title: str | None = None) -> dict`, `main(argv=None) -> int` (`python3 -m skills.walkthrough.push --steps <path> --cwd <repo root> [--slug ...] [--title ...]`). Task 3's `SKILL.md` rewrite references this exact CLI shape.

- [ ] **Step 1: Confirm `reply_cli`'s current daemon-awareness**

Read `skills/_shared/web_companion/reply_cli.py` (or wherever Phase 1's retrofit left it — check `skills/dataflow/SKILL.md`'s own Mode-D section for the exact module path it invokes today, since Phase 1 already retrofitted this for its own Mode D). Confirm it already calls `webcompanion_client.append_thread(..., kind=<whatever kind the caller passes>)` rather than the old `threads_module.append_message`. If it does, walkthrough's `SKILL.md` (Task 3) invokes it exactly the way `dataflow/SKILL.md` does, with `kind="walkthrough"` (or however the CLI takes the kind argument — read the actual CLI's `argparse` block, do not guess). If it does **not** yet support an arbitrary `kind`, that is a real gap this task must also close (a small, additive change — do not use it as license to redesign the module) — note whichever is true in your report, since it changes what Task 3's SKILL.md can assume.

- [ ] **Step 2: Write `push.py`**

Follow `skills/dataflow/push.py`'s exact shape (read it in full first — it is the closest template: one Claude-authored JSON document, no assets). Key differences from dataflow, both load-bearing:

```python
"""Push a steps.json document to the webcompanion daemon.

Replaces the old flow -- a per-skill server serving steps.json and per-step
threads off disk. There is no walkthrough server any more: the daemon owns
storage, comment threads and the event queue, and this module is the only
thing that knows how a walkthrough document maps onto it.

The mapping:

    __steps__    the full steps.json body, unchanged shape (see steps.py)

Usage:
    python3 -m skills.walkthrough.push --steps <steps.json> --cwd <repo root>
                                       [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.walkthrough import steps as steps_module

KIND = "walkthrough"
STEPS_ANCHOR = "__steps__"


def push(steps_path: Path, cwd: str, slug: str | None = None,
        title: str | None = None) -> dict:
    doc = json.loads(steps_path.read_text())

    errors = steps_module.validate(doc)
    if errors:
        raise ValueError(
            "steps.json failed validation:\n" + "\n".join("  - " + e for e in errors))

    title = title or doc.get("question") or "Walkthrough"

    # Unlike dataflow, walkthrough turns supersede on: the IDE panel shows
    # exactly one tour per project, and the current (pre-daemon) SKILL.md
    # already cancels any pre-existing walkthrough session for this cwd on
    # every new invocation, regardless of which Claude conversation created
    # it -- supersede=True is an atomic replacement for that already-accepted
    # behavior, not a new one. See the plan's Global Constraints for the one
    # named behavior change (no more cross-cwd auto-cancel within one Claude
    # conversation).
    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug, supersede=True)
    sid = res["sid"]

    wc.put_items(sid, {STEPS_ANCHOR: doc}, kind=KIND, replace=True)

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.walkthrough.push")
    ap.add_argument("--steps", required=True, help="path to steps.json")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.steps), a.cwd, a.slug, a.title)
    except ValueError as e:
        print("walkthrough push: %s" % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("walkthrough push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Do **not** call `wc.register_assets` — walkthrough has no browser page to serve.

- [ ] **Step 3: Write `test_push.py`**

Mirror `skills/dataflow/tests/test_push.py`'s structure (mock `webcompanion_client`'s functions, assert they're called with the right arguments). At minimum:

```python
def test_push_validates_before_calling_daemon(tmp_path, monkeypatch):
    bad = tmp_path / "steps.json"
    bad.write_text(json.dumps({"question": "", "kind": "explain", "generated_ts": 1, "steps": []}))
    calls = []
    monkeypatch.setattr(wc, "create_or_attach", lambda *a, **k: calls.append(("create", a, k)))
    with pytest.raises(ValueError, match="question must be a non-empty string"):
        push.push(bad, "/repo")
    assert calls == []


def test_push_passes_supersede_true(tmp_path, monkeypatch):
    doc = {"question": "how does X work", "kind": "explain", "generated_ts": 1,
           "steps": [{"id": 1, "title": "t", "file": "a.py", "line": 1,
                      "snippet": "x", "role": "context", "markdown": "m"}]}
    p = tmp_path / "steps.json"
    p.write_text(json.dumps(doc))
    seen = {}
    monkeypatch.setattr(wc, "create_or_attach",
        lambda kind, cwd, **k: seen.update(kind=kind, cwd=cwd, **k) or {"sid": "s1"})
    monkeypatch.setattr(wc, "put_items", lambda *a, **k: None)
    res = push.push(p, "/repo")
    assert res == {"sid": "s1"}
    assert seen["supersede"] is True
    assert seen["kind"] == "walkthrough"


def test_push_never_registers_assets(tmp_path, monkeypatch):
    # walkthrough has no browser page; register_assets must never be called.
    doc = {"question": "q", "kind": "explain", "generated_ts": 1,
           "steps": [{"id": 1, "title": "t", "file": "a.py", "line": 1,
                      "snippet": "x", "role": "context", "markdown": "m"}]}
    p = tmp_path / "steps.json"
    p.write_text(json.dumps(doc))
    called = []
    monkeypatch.setattr(wc, "create_or_attach", lambda *a, **k: {"sid": "s1"})
    monkeypatch.setattr(wc, "put_items", lambda *a, **k: None)
    monkeypatch.setattr(wc, "register_assets", lambda *a, **k: called.append(True))
    push.push(p, "/repo")
    assert called == []
```

Adjust import paths/fixtures to match this repo's actual test conventions (check `skills/dataflow/tests/test_push.py` for the real import style before writing these from scratch).

- [ ] **Step 4: Run the test suite for this task**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough && python3 -m pytest skills/walkthrough skills/_shared -q`
Expected: all new tests pass; no regressions in `_shared`.

- [ ] **Step 5: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough
git add skills/walkthrough/push.py skills/walkthrough/tests/test_push.py
git commit -m "Add walkthrough's push.py: steps.json onto the webcompanion daemon, supersede=True"
```

---

### Task 2: Rework `WalkthroughSessionClient.java`

**This is the phase's real weight.** Every finding below was independently verified live against the running daemon during this plan's research (curl against port 3080 with the real `~/.claude/webcompanion/config.json` token) — not assumed from `contract.md`. Re-verify anything you find surprising against the live daemon yourself before writing code; `webcompanion status` confirms it is running.

**Files:**
- Modify: `ide-plugin/src/main/java/com/petros/ireview/WalkthroughSessionClient.java`
- Modify: `ide-plugin/src/test/java/com/petros/ireview/WalkthroughSessionClientTest.java`

**Interfaces:**
- Consumes: the daemon's real routes directly (no shared Java client module exists yet — this is the first Java code in this whole program to talk to the daemon; Phase 4's `interactive-review` migration will be the second, and should reuse whatever proves itself here rather than reinventing). `ServerDiscovery.resolve(...)` (unchanged — already daemon-first, legacy-fallback, and already wired into `WalkthroughService.java`'s construction of this client's `baseUrlSupplier`; confirm this during Step 1 but do not expect to touch `ServerDiscovery.java` or `WalkthroughService.java`).
- Produces: `SessionInfo(String sid, String title)` (drops `stateDir` — see Step 1), `ThreadState` (unchanged shape, `record ThreadState(String synthesis, int version, String title, String question)` — only its construction changes, not its fields, so `WalkthroughController`/`WalkthroughPanel` need no changes). `Listener` interface unchanged.

- [ ] **Step 1: Session discovery — `fetchNewestSession()`**

Current code (`WalkthroughSessionClient.java:295-311`):

```java
private SessionInfo fetchNewestSession() throws Exception {
    String url = baseUrl + "/api/sessions?cwd="
        + URLEncoder.encode(projectCwd, StandardCharsets.UTF_8);
    HttpRequest req = HttpRequest.newBuilder(URI.create(url)).timeout(REQUEST_TIMEOUT).GET().build();
    HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
    if (resp.statusCode() != 200) throw new IOException("HTTP " + resp.statusCode());
    var root = JsonParser.parseString(resp.body());
    if (!root.isJsonArray() || root.getAsJsonArray().isEmpty()) return null;
    JsonObject o = root.getAsJsonArray().get(0).getAsJsonObject();
    return new SessionInfo(str(o, "sid"), str(o, "title"), str(o, "state_dir"));
}
```

Rewrite it to:
1. Add `&kind=walkthrough` to the query string.
2. Among the returned array's elements, defensively re-check each row's own `"kind"` field equals `"walkthrough"` before considering it (belt-and-braces against a daemon that ever ignored the query filter — cheap, matches this program's established defensive-parsing posture).
3. Pick the element with the lexicographically greatest `"sid"` string — **not** `array[0]` — since `supersede=True` (Task 1) guarantees the newest `sid` for this `(kind, cwd)` is the only one still live, and the array is not guaranteed sorted and does not exclude terminal sessions (see this plan's Global Constraints for the live evidence). An empty array (after the kind re-check) still returns `null`, unchanged.
4. Drop the `state_dir` field entirely from `SessionInfo`'s construction and from its record definition — grep the whole `ide-plugin/src/main/java` tree for `.stateDir()` first to confirm nothing outside this file reads it (this plan's own research found zero call sites; re-confirm, don't just trust this document).

Update `record SessionInfo(String sid, String title, String stateDir) {}` to `record SessionInfo(String sid, String title) {}` and fix its one other call site (`attach(SessionInfo s)` and anywhere else `new SessionInfo(...)` or `.stateDir()` appears).

- [ ] **Step 2: Fetching `__steps__` — replace `loadSteps()`'s `/steps.json` call**

Current code fetches `GET /s/{sid}/steps.json` and parses the body directly as the steps document. Under the daemon, this becomes `GET /s/{sid}/items?kind=walkthrough`, whose real response shape — confirmed by reading the daemon's own `_list_items`/`items.snapshot` source directly (`~/projects/webcompanion/src/webcompanion/items.py:138-143`: `{a: {"body": b, "version": versions.get(a, 1)} for a, b in bodies.items()}`), not merely inferred — is `{"__steps__": {"body": <the steps document>, "version": <int>}}`, with no `code` key (that only appears on the single-anchor `GET /s/{sid}/items/<anchor>` route, which this task does not need). Extract `.get("__steps__").get("body")`, not the whole response — and treat a response with no `__steps__` key as "nothing pushed yet" (empty doc), the same absent-key handling `loadSteps`'s retry loop already needs for a session that was just created and hasn't been pushed to. `WalkthroughDoc.parse(...)` (unchanged, in `WalkthroughDoc.java`) should be handed exactly that inner document, same shape as before — this task changes *how the bytes are fetched*, not `WalkthroughDoc`'s own parsing.

The unchanged-guard (`prev.generatedTs() == next.generatedTs() && prev.steps().size() == next.steps().size()`) stays exactly as it is.

**This step also fixes a second, separate gap the spec itself named but this plan had not yet wired up: `handleSseEvent()`'s SSE-driven reload trigger.** Current code:

```java
if ("steps-changed".equals(name)) {
    loadSteps(sid, gen);
    return;
}
```

There is no `steps-changed` frame under the daemon — walkthrough's own per-step-changed frame doesn't exist there either. The daemon's generic `item-changed` frame (`{anchor, version, initial?}`) fires for *any* item change, including `__steps__` (confirmed by this whole program's shared understanding of the daemon's SSE vocabulary — `contract.md`'s frame list has no per-skill custom frames). Replace the branch with:

```java
if ("item-changed".equals(name)) {
    JsonObject data;
    try {
        data = JsonParser.parseString(e.data()).getAsJsonObject();
    } catch (Exception ex) {
        return;
    }
    if ("__steps__".equals(str(data, "anchor"))) loadSteps(sid, gen);
    return;
}
```

placed before the existing `thread-changed`/`thread-deleted` handling further down `handleSseEvent()` (which already parses `data` from `e.data()` itself — do not parse it twice; restructure so the JSON parse happens once and both this check and the thread-anchor check that follows share it, rather than duplicating the try/catch).

- [ ] **Step 3: Submitting a question — `postAsk()`**

Current code (`WalkthroughSessionClient.java:183-213`) builds `{anchor, type: "comment", text}`. Confirmed live: the daemon's `/api/submit` accepts (and this code has never sent anything but) `{anchor, text}` — `type` was always the literal string `"comment"` (grep the whole `ide-plugin/src/main/java` tree for `"reject"` to confirm no code path ever constructs the other documented value; this plan's own research found zero — re-confirm). Drop `type` from the payload map entirely:

```java
Map<String, String> payload = new java.util.LinkedHashMap<>();
payload.put("anchor", anchor);
payload.put("text", text);
```

Also update the URL to include `?kind=walkthrough` (every daemon route in this file needs this query param — `cancelSession()`'s `/api/cancel` route too, see Step 5).

Do not build a JSON-envelope bridge (the pattern `deck.js`/`annotate` use for structured payloads) — there is nothing structured left to carry once `type` is dropped; a bridge here would be solving a problem that no longer exists.

- [ ] **Step 4: Thread deltas — `toThreadState()`, `handleSseEvent()`, `seedThreads()`**

This is the biggest behavioral change in the file. Current `toThreadState(JsonObject o)` reads `latest_synthesis`/`title`/`question` directly off whatever JSON object it's handed — today that's either the SSE frame's own `data` (wrong under the daemon: confirmed live, the frame is only `{anchor, version}`) or one entry from the bulk `/threads.json` fetch (right shape, just wrong route name).

Fix:
1. Add a private method, `Map<String, ThreadState> deriveThreads(String sid)`, that does `GET /s/{sid}/threads?kind=walkthrough` (confirmed live shape: `{anchor: {anchor, version, messages: [{text, role, ts}], title}}`) and derives, per anchor, the same way `skills/_shared/static/wc-threads.js`'s `derive()` does (read that file — 38 lines, read it in full, it is the exact logic to port): filter `messages` to `role == "agent"`; if none, **omit this anchor from the result entirely** (matches today's own `threads_bulk()` Python behavior at `skills/walkthrough/server.py:78-111` — read it too, for the human-readable version of the same rule); otherwise `latest_synthesis` = last agent message's `text`, `updated_at` = its `ts` (not currently a `ThreadState` field — check whether anything downstream needs it before adding it; if nothing does, do not add it, YAGNI); `question` = the last `role == "user"` message's `text`, or `""` if there are none; `title` = the thread object's own `title` field.
2. `seedThreads(sid, gen)` (currently GETs `/threads.json` and calls `toThreadState` per-entry) becomes: call `deriveThreads(sid)`, then `applyThread(anchor, state)` for each entry — the retry/backoff loop around it is unchanged.
3. `handleSseEvent()`'s `thread-changed` branch (currently parses `data` and calls `toThreadState(data)` directly) becomes: on `thread-changed`, call `deriveThreads(sid)` again (cheap — walkthrough tours are 5-12 steps, never more) and `applyThread` for the one anchor named in the event (or, more simply, for every anchor in the fresh bulk fetch — `applyThread`'s own existing version/synthesis-equality check already no-ops anything unchanged, so re-deriving everything and letting that guard filter is simpler and no less correct than threading the single anchor through). `thread-deleted`'s handling (`threads.remove(anchor)`) is unchanged — it needs no daemon-shape fix, only the `?kind=walkthrough` query param on wherever its own route is constructed (check `_serve_stream`'s equivalent — the daemon's generic `/s/{sid}/stream` route, confirmed to need `?kind=walkthrough` the same way every other route here does).
4. Remove `toThreadState(JsonObject o)` entirely once nothing calls it, or repurpose it as a private helper inside `deriveThreads` if that reads more cleanly — implementer's judgment, since both are equally correct; say which you chose in your report.

- [ ] **Step 5: Poll — `pollLiveness()`**

Current code GETs `/s/{sid}/poll` and reads `watcher_seen_at`, `steps_generated_at`, `ended`. Confirmed live, the daemon's real `/s/{sid}/poll?kind=walkthrough` response is `{"finished": bool, "cancelled": bool, "watcher_seen_at": int|null, "items": {"__steps__": <version int>}, "threads": {<anchor>: <version int>, ...}}` — no `ended` boolean, no `steps_generated_at` field.

Rework:
1. Add `?kind=walkthrough` to the URL.
2. Compute `ended` client-side as `finished || cancelled` — this is strictly simpler than today's three-way `ended_reason` (cancelled/finished/dead), because "dead by watcher-heartbeat age" was already handled separately from `ended` in this method's own existing logic (the `STALE_AFTER`-driven `PAUSED` state, lines ~372-385) and is *not* itself one of the three `ended_reason` values worth re-deriving — except one: today's `dead = age > wc_server.REAP_AFTER` (180 seconds — confirmed the exact value in `skills/_shared/web_companion/server.py:43`, which is being deleted) sets the **hard** `ended` latch, distinct from the **soft** `STALE_AFTER` (15s)-driven `PAUSED` state. The daemon's poll has no equivalent of this hard cutoff at all (confirmed: no default retention/expiry sweep exists today — a separate, not-yet-built initiative). Reproduce the 180s threshold client-side, next to the existing `STALE_AFTER` constant, with a comment naming where the value came from (`skills/_shared/web_companion/server.py`'s `REAP_AFTER`, a file this migration deletes) so a future reader isn't left wondering why an odd round number appears with no daemon-side source. `ended` becomes: `finished || cancelled || (seenAt > 0 && ageMs > REAP_AFTER_MS)`.
3. Replace the `steps_generated_at`-driven freshness reload (lines ~372-375: `if (stepsGeneratedAt > 0 && stepsGeneratedAt != doc.get().generatedTs()) loadSteps(...)`) with a version-driven equivalent: read `items.get("__steps__")` from the poll response (an integer version, absent if no `__steps__` item has ever been pushed for this session — treat absence as "no reload needed" the same way `stepsGeneratedAt == 0` was treated before) and compare it against a new field this client must track — the `__steps__` item's version as of the last successful `loadSteps()` call (there is currently nothing tracking this, since `WalkthroughDoc` itself carries no version field, only `generatedTs()`; add a small `private volatile int lastStepsVersion` next to the existing `doc` field, set it inside `loadSteps()` on every successful fetch, and compare against it here). This is the same "poll fills the gap between SSE events" role the old code played (steps regenerate mid-session; the SSE stream's `item-changed` on `__steps__` would eventually carry this too, but this poll-based fallback bounds the delay the same way the comment on the *old* code already explains — read that comment, it still applies, only the field name changes).

- [ ] **Step 6: Every other daemon route in this file gets `?kind=walkthrough`**

Grep the file for every `baseUrl + "/s/"` and `baseUrl + "/api/sessions"` construction (there are more than the ones named above — at minimum `cancelSession()`'s `/api/cancel` route and `openSse()`'s `/stream` route) and confirm each carries the query param. Missing it on even one route is a silent 400/404 under the daemon (every route in `contract.md` is kind-scoped) that would not show up in a narrow unit test exercising only the routes this task's author remembered to check — grep, don't rely on memory.

- [ ] **Step 7: Rewrite `WalkthroughSessionClientTest.java`'s fixtures**

Every test's `sessionsJson`/`stepsJson`/SSE payload strings currently encode the *old* wire shapes. Rewrite each to encode the *real* ones documented above:
- `sessionsRow(sid)` (a test helper at the top of the file, line ~32): drop `state_dir` from the constructed JSON.
- Any test asserting on `lastSubmitBody`: it must no longer contain `"type":"comment"`.
- `threadChangedEventUpdatesCacheAndClearsPending` (and any other test pushing a `thread-changed` SSE event with a full `latest_synthesis`/`title`/`question` payload): the pushed SSE event becomes the real slim shape (`{"anchor":"step:2","version":1}`), and the test's fake server needs a way to serve the *bulk threads* route with the full derivation inputs (`{anchor: {version, messages: [...], title}}`) so `deriveThreads()` has something real to fetch after the frame arrives. **Confirmed during this plan's own pre-dispatch review (not "check first" — this is settled): `ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java` (221 lines) currently serves only the *old* server's routes — `/api/sessions`, `/steps.json`, `/threads.json` (a single flat JSON blob, `volatile String threadsJson`), `/poll`, `/api/submit`, `/api/cancel`, `/api/threads/delete`, `/stream` (`handleSessions`/`handleSession` in `FakeReviewServer.java:96-97,103,123`). There is no route matching the daemon's real `/s/{sid}/threads` (bulk, no trailing path segment, returns `{anchor: {...}}` keyed by anchor) — this task must add one. Add a new branch in `handleSession` (alongside the existing `path.endsWith("/threads.json")` one, `FakeReviewServer.java:133`) matching the path exactly (`/threads` with no suffix, distinct from `/threads.json` and from the per-anchor `/threads/<anchor>` shape neither client nor this fixture currently needs) and a new settable field (e.g. `volatile String bulkThreadsJson = "{}"`) the way `threadsJson` already works for the old route — do not repurpose `threadsJson` itself, since `WalkthroughSessionClientTest.java`'s other tests may still reference the old field name if any old-server-shaped test survives triage elsewhere; check before removing it. `FakeReviewServer` is shared with `ReviewSessionClientTest.java` (confirmed via grep) — adding a route is additive and safe for that other test, but do not modify or remove any existing route/field while doing so.
- Add tests for the two new pieces of client logic this task introduces: max-`sid` selection when the discovery array contains more than one row (construct a fake array with two rows, older-sid-first, and assert the client attaches to the newer one), and the `kind` mismatch defensive check (a row whose `kind` is not `"walkthrough"` is ignored).

- [ ] **Step 8: Run the Java test suite**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough/ide-plugin && ./gradlew test --tests "com.petros.ireview.WalkthroughSessionClientTest"`
Expected: all tests pass, including the two new ones from Step 7.

- [ ] **Step 9: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough
git add ide-plugin/src/main/java/com/petros/ireview/WalkthroughSessionClient.java \
        ide-plugin/src/test/java/com/petros/ireview/WalkthroughSessionClientTest.java
git commit -m "Rework WalkthroughSessionClient onto the daemon's real wire shapes"
```

---

### Task 3: Delete walkthrough's server; update SKILL.md/README.md; smoke test

**Files:**
- Delete: `skills/walkthrough/server.py`
- Delete: `skills/walkthrough/ensure_server.sh`
- Delete: `skills/walkthrough/tests/test_server.py` (coverage triaged first)
- Modify: `skills/walkthrough/SKILL.md`
- Modify: `skills/walkthrough/README.md` (if it exists and describes the old server — check first)

**Interfaces:**
- Consumes: `push.py` (Task 1), the reworked `WalkthroughSessionClient.java` (Task 2).

- [ ] **Step 1: Confirm `test_server.py`'s coverage before deleting**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough && python3 -m pytest skills/walkthrough/tests/test_server.py -v --collect-only`. Check every test against `Handlers`' methods and against `skills/walkthrough/tests/test_steps.py`'s existing coverage. Anything testing `steps_module.validate`/`write_steps` purely through the HTTP layer, with no equivalent already in `test_steps.py`, gets ported there first (matching Phase 1/2's own precedent for this exact step).

- [ ] **Step 2: Delete the old server**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough
git rm skills/walkthrough/server.py skills/walkthrough/ensure_server.sh skills/walkthrough/tests/test_server.py
```

- [ ] **Step 3: Update `SKILL.md`**

Read `skills/dataflow/SKILL.md` (Phase 1, merged) as the closest prior art for the daemon-era section shape — walkthrough's is closer to dataflow's than deck's, since like dataflow it pushes one Claude-authored document with no asset story. Replace:
- `## On every invocation: ensure the server is running` through `## Create a session`'s curl block → resolve `PLUGIN_ROOT` the same way (still needed to locate `skills/walkthrough/push.py`'s module), then `python3 -m skills.walkthrough.push --steps <path to the written steps.json> --cwd "$PWD" --title "<question>"`. Note: `push.py` needs a real `steps.json` file to read — the "Generate the steps" section's own flow (write `.steps.draft.json`, validate via `write_steps` into `steps.json` in the *session's* state dir) has an ordering dependency worth being explicit about in the rewritten doc: does `push.py` create the session first (so there is a `state_dir` to write `steps.json` into) and get pushed to *after* generation, or does generation happen against a scratch path first and `push.py` runs once, after, reading that scratch path? Resolve this explicitly — read how `dataflow/SKILL.md`'s own rewritten flow sequences "write the document" against "call push.py" for its own analogous ordering question, and match its answer unless walkthrough has a real reason to differ (say so if it does).
- The **"One active tour per project"** paragraph → delete the curl-based list-then-cancel dance entirely; `supersede=True` inside `push.py` (Task 1) now does this atomically. State plainly that this is now automatic and needs no separate step.
- The watcher-arm step → unchanged in shape (`webcompanion watch --kind walkthrough --sid <sid>`, matching Phase 1/2's own SKILL.md wording exactly).
- The event payload description (Mode D, `## Mode D`) → drop the `type` field from the documented payload shape entirely (no more `"comment"`/`"reject"` distinction to explain — Task 2 Step 3 confirmed `"reject"` was always dead).
- The ack step → `webcompanion ack --sid <sid> --event-id <event_id>`, matching Phase 1/2.
- Anywhere `steps.json` is read back for verification (if such a step exists in the current doc) → `wc.get_items(sid, kind="walkthrough")["__steps__"]`, matching the read-back pattern Phase 1/2's own SKILL.md rewrites use.

Keep the entire **"Generate the steps"** section's content rules (5-12 steps, real anchors, execution order, markdown quality, the "Generation contract" block) and the entire **"Response style guide"** completely unchanged — none of it is server-related.

- [ ] **Step 4: Update `README.md` if it describes the old server**

Check first (`grep -n "server\|ensure_server\|PORT_RANGE" skills/walkthrough/README.md`); if it does, correct it the same way Phase 1/2's `README.md` fixes did.

- [ ] **Step 5: Manual smoke test against the real live daemon**

Confirm the daemon is running (`webcompanion status`). Using a small real question against this very repository:

1. Generate a short (5-step minimum) real `steps.json` by hand or by actually running the skill's own generation logic against a trivial question about this codebase (e.g. "how does push.py talk to the daemon").
2. Push it via `push.py`, confirm the response's `sid`.
3. Confirm `GET /s/{sid}/items?kind=walkthrough` returns the pushed `__steps__` document with the expected step count.
4. Post a thread message directly (via `curl`, mimicking what Claude's Mode-D reply path will do) on `step:1`, confirm `GET /s/{sid}/threads?kind=walkthrough` shows it, and confirm a `thread-changed` SSE frame arrives on `/s/{sid}/stream?kind=walkthrough` shaped exactly `{anchor, version}` (re-confirm this plan's own finding hasn't changed).
5. Run the actual IntelliJ plugin against this session if the environment allows it (build the plugin, point `ServerDiscovery` at the live daemon via its existing config file, open the project) and confirm the tour actually renders and a posted question's reply actually appears in the panel — this is the closest equivalent to Phase 1/2's browser-based live-edit-reload proof, and it is not optional to skip if a way to run the IDE plugin locally exists in this environment. If it genuinely does not (no IntelliJ available in this environment), say so plainly in the report and rely on the `WalkthroughSessionClientTest.java` suite (Task 2 Step 7-8) plus the direct-HTTP verification in this step as the best available evidence, and name this as an accepted gap for the human to verify by hand before merging.
6. Finish the probe session (`POST /s/{sid}/api/finish?kind=walkthrough`) and confirm `webcompanion status`'s session count returns to its pre-test value — do not leave a probe session live (this program's own session-leak investigation found abandoned probe/test sessions to be a real, non-trivial fraction of daemon clutter; clean up after yourself).

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough && python3 -m pytest skills -q`
Expected: same baseline as `main` (1083 passed as of this plan's writing) plus this phase's new tests, minus `test_server.py`'s deleted tests, zero failures.

Also run: `cd ide-plugin && ./gradlew test` (the full Java suite, not just `WalkthroughSessionClientTest`) — confirm nothing else in the plugin depended on `WalkthroughSessionClient`'s old shapes in a way `WalkthroughSessionClientTest.java` alone wouldn't catch.

- [ ] **Step 7: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-walkthrough
git add -A skills/walkthrough/
git commit -m "Migrate walkthrough onto the webcompanion daemon; delete its private server"
```

---

## Testing strategy

Python: real unit tests for `push.py` (Task 1), matching Phase 1/2's own pattern (mocked daemon client, real validation logic). Java: the existing `WalkthroughSessionClientTest.java` suite, rewritten to pin the daemon's real shapes rather than the old server's (Task 2) — this is the load-bearing test surface for this phase's hardest logic (max-sid selection, thread derivation, kind filtering), since there is no browser to smoke-test the way Phase 1/2 had. A live-daemon HTTP smoke test (Task 3 Step 5) covers what the Java unit tests, run against a fake server, cannot: that the daemon's *actual* routes behave the way this plan's research found them to, not just the way the fakes were told to pretend. Running the real IDE plugin against a live tour, if the environment allows it, is the closest equivalent to Phase 1/2's real-browser proof and should not be skipped without a stated reason.

## Known limitations (accepted, not deferred silently)

- **Cross-cwd auto-cancel is gone.** A Claude conversation that runs `/walkthrough` in project A and then in project B no longer auto-closes project A's tour (see Global Constraints for the full reasoning). Its watcher stays armed and harmless; nothing breaks, but the old tidiness guarantee is gone. Not rebuilt — YAGNI, never load-bearing for correctness.
- **No daemon-side session expiry.** Old, finished walkthrough sessions accumulate in `GET /api/sessions?cwd=` forever (confirmed live, no default retention sweep). This phase's `fetchNewestSession()` fix (max-`sid` selection) makes this harmless for *this client's* correctness, but does not reduce the daemon's own storage growth — that is the separate, already-identified webcompanion session-leak initiative, out of scope here.
- **No IDE-side smoke test if the environment cannot run IntelliJ.** Named explicitly in Task 3 Step 5 rather than silently skipped — if this environment cannot build/run the plugin, the human merging this branch should do this check by hand before relying on it in production.
