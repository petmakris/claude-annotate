# Annotate UX Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make three invisible things visible — the round before you submit it, what Claude is doing while it works, and what changed when it finishes — and fix two bugs found alongside them.

**Architecture:** Almost all of it is client-side. One server change writes a snapshot of `blocks.json` when a mutating event is queued, because `versions.json` stores content hashes and cannot reconstruct prior text; one read route serves that snapshot back. Attribution of a change to *you asked* versus *the sweep decided* is derived in the browser from the block ids the client just submitted, so it needs neither the server nor Claude and cannot drift.

**Tech Stack:** Python 3 stdlib `http.server`, vanilla browser JS (no build step, no bundler), plain CSS with custom properties, `unittest` under `pytest`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-annotate-ux-pass-design.md`. Read it before starting.
- The approved design is a set of five interactive mockups. Where spec prose and mockup disagree, the mockup is the intent.
- Branch `annotate-ux-pass`, already checked out. Baseline: `python3 -m pytest skills/ -q` → **764 passed**. Every task ends green.
- Run tests from the repo root with `python3 -m pytest`, never bare `pytest`.
- **No build step.** Vanilla JS, plain CSS. Files under `skills/annotate/static/` are served verbatim.
- **Python stdlib only.** No new dependencies.
- Smoke tests here are source-string assertions (see `skills/annotate/tests/test_smoke_dismiss_lock.py`). Match that style. Do not add a JS test runner.
- Writes are owner-only, gated centrally at `_dispatch_post` in `skills/_shared/web_companion/server.py`. Reads are ungated. Do not add per-route gates.
- After any JS edit run `node --check` on the edited file — string assertions cannot catch a syntax error.

---

### Task 1: Snapshot the document when a mutating event is queued

Nothing can show "what changed" today because `versions.json` holds only content hashes. This writes the missing baseline and serves it back.

The snapshot is taken **when the event is queued**, not when Claude applies it: that is exactly the document the user was looking at when they pressed Submit, which is the correct baseline for "what changed since I submitted".

**Files:**
- Modify: `skills/annotate/server.py`
- Test: `skills/annotate/tests/test_server_round.py`

**Interfaces:**
- Produces: `<response_dir>/blocks.prev.json` — a verbatim copy of `blocks.json` as it stood when the last mutating event was queued. And a read route `GET /s/<sid>/prev` returning `{"ok": true, "blocks": {<block_id>: <markdown or null>}}`, or `{"ok": false}` when no snapshot exists. Task 4 consumes both.

- [ ] **Step 1: Write the failing tests**

Append to `skills/annotate/tests/test_server_round.py` inside `class SubmitRoundTests`:

```python
    def test_queuing_a_round_snapshots_the_document(self):
        """The snapshot is the document the user was looking at when they
        pressed Submit — so it is taken at queue time, not at apply time."""
        prev = Path(self.sess["response_dir"]) / "blocks.prev.json"
        self.assertFalse(prev.exists(), "snapshot existed before any event")
        status, _ = self._submit({"type": "round", "reactions": [_reaction("keep")]})
        self.assertEqual(status, 202)
        self.assertTrue(prev.exists(), "queuing a round wrote no snapshot")
        snap = json.loads(prev.read_text())
        ids = [b["id"] for b in snap["blocks"]]
        self.assertEqual(ids, ["section-1", "section-2"])

    def test_the_snapshot_is_overwritten_not_accumulated(self):
        """Only the most recent round is described by the change bar."""
        prev = Path(self.sess["response_dir"]) / "blocks.prev.json"
        self._submit({"type": "round", "reactions": [_reaction("keep")]})
        first = prev.read_text()
        _write_blocks(Path(self.sess["response_dir"]), "resp-rd", "T", [
            {"id": "section-1", "title": "A", "markdown": "rewritten"},
            {"id": "section-2", "title": "B", "markdown": "beta"},
        ])
        self._submit({"type": "round", "reactions": [
            _reaction("keep", selected_text="rewritten")]})
        self.assertNotEqual(prev.read_text(), first,
                            "the snapshot did not move with the document")
        self.assertIn("rewritten", prev.read_text())

    def test_prev_route_serves_the_snapshot(self):
        self._submit({"type": "round", "reactions": [_reaction("keep")]})
        conn = HTTPConnection("localhost", self.info["port"], timeout=2)
        conn.request("GET", f"/s/{self.sess['sid']}/prev")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read().decode())
        self.assertTrue(body["ok"])
        self.assertIn("alpha one", body["blocks"]["section-1"])

    def test_prev_route_is_honest_when_there_is_no_snapshot(self):
        conn = HTTPConnection("localhost", self.info["port"], timeout=2)
        conn.request("GET", f"/s/{self.sess['sid']}/prev")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertFalse(json.loads(resp.read().decode())["ok"])
```

Add `from pathlib import Path` to that file's imports if it is not already there.

- [ ] **Step 2: Run them to verify they fail**

```bash
python3 -m pytest skills/annotate/tests/test_server_round.py -q -k "snapshot or prev"
```

Expected: 4 failures.

- [ ] **Step 3: Write the snapshot at queue time**

In `skills/annotate/server.py`, add this helper next to the other module-level helpers:

```python
def _snapshot_blocks(response_dir: Path) -> None:
    """Copy blocks.json aside before a mutating event is applied.

    versions.json stores content hashes, not text, so without this the page
    can say a block changed but never what it said before. Written at QUEUE
    time on purpose: that is the document the user was looking at when they
    submitted, which is the baseline "what changed" has to mean. Best-effort —
    a failed snapshot must never block the user's submission.
    """
    src = response_dir / "blocks.json"
    if not src.exists():
        return
    try:
        write_text_atomic(response_dir / "blocks.prev.json", src.read_text())
    except OSError:
        pass
```

`write_text_atomic` lives at `skills._shared.web_companion.atomic` — the same import `blocks.py:27` and `versions.py:30` already use. Add it to `server.py`'s imports if it is not already there.

Call it from `handle_submit`, immediately after the terminal-state check and before any branch dispatches — one call covers round, choice, comment, reject and dismiss:

```python
        if _is_terminal(Path(dirs["state_dir"])):
            _send_text(h, 409, "session closed")
            return
        # Every branch below can mutate blocks.json. Snapshot once, here, so
        # no future submit type can be added without coverage.
        _snapshot_blocks(Path(dirs["response_dir"]))
```

- [ ] **Step 4: Serve the snapshot back**

In `serve_data` in `skills/annotate/server.py`, add a branch beside the existing `statusline` one:

```python
        # /prev — the document as it stood when the last mutating event was
        # queued, so the client can diff against it. A read, so it stays
        # outside the owner write gate and works on read-only links.
        if query == "prev":
            prev_path = Path(dirs["response_dir"]) / "blocks.prev.json"
            if not prev_path.exists():
                _send_json(h, 200, {"ok": False, "blocks": {}})
                return
            try:
                snap = json.loads(prev_path.read_text())
            except (json.JSONDecodeError, OSError):
                _send_json(h, 200, {"ok": False, "blocks": {}})
                return
            out = {}
            for b in snap.get("blocks", []):
                if isinstance(b, dict) and isinstance(b.get("id"), str):
                    out[b["id"]] = b.get("markdown")
            _send_json(h, 200, {"ok": True, "blocks": out})
            return
```

- [ ] **Step 5: Run the tests**

```bash
python3 -m pytest skills/annotate/tests/test_server_round.py -q
python3 -m pytest skills/ -q
```

Expected: both green.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/server.py skills/annotate/tests/test_server_round.py
git commit -m "feat(annotate): snapshot the document when a mutating event is queued

versions.json stores content hashes, so the page could say a block
changed but never what it said before. The snapshot is taken at queue
time because that is the document the user was looking at when they
pressed Submit."
```

---

### Task 2: Say what Claude is doing, and stop freezing the marking controls

The highest-value change in this plan and among the smallest. The progress pipeline already exists end to end and its output is currently discarded because a round never registers its event id.

**Files:**
- Modify: `skills/annotate/static/subunits.js`
- Modify: `skills/annotate/static/script.js`
- Modify: `skills/annotate/static/style.css`
- Test: `skills/annotate/tests/test_smoke_progress.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `window.AnnotateSubunits.submittedBlockIds()` returning an array of the `block_id`s in the most recently submitted round, and `window.AnnotatePage.registerRoundEvent(eventId, blockIds)` which puts the round into `pendingEvents` so `applyProgress` sees it. Task 4 consumes both.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_progress.py`:

```python
"""Structural guards for round progress and the un-freezing of marking.

Two separate promises. First: a round must register its event id, or the
progress labels the hook publishes and /poll serves are computed and thrown
away — which is what happened for the whole life of the round feature.
Second: marking is local until Submit, so only Submit ever needed the busy
lock; freezing the whole vocabulary took away work the user could still do.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"


def test_a_round_registers_its_event_id():
    """Without this the label never reaches applyProgress."""
    subunits = SUBUNITS_JS.read_text()
    assert "registerRoundEvent" in subunits, \
        "submitRound does not register its event id for progress"


def test_the_page_exposes_a_way_to_register():
    script = SCRIPT_JS.read_text()
    assert "registerRoundEvent" in script, \
        "script.js exposes no round registration hook"
    assert "AnnotatePage" in script, "no page export object for subunits.js"


def test_progress_labels_reach_the_banner():
    script = SCRIPT_JS.read_text()
    assert "bb-label" in script, "the busy banner has no live label element"


def test_marking_survives_the_busy_lock():
    """Marks are local; only Submit talks to Claude."""
    css = STYLE_CSS.read_text()
    assert "body.is-busy .unit-strip button { display: none; }" not in css, \
        "the busy lock still hides every marking control"


def test_the_block_being_rewritten_is_still_locked():
    """Un-freezing the page must not make a mid-rewrite block markable."""
    css = STYLE_CSS.read_text()
    assert "section.block.is-updating" in css, \
        "the per-block updating lock disappeared with the page-wide one"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_progress.py -q
```

Expected: 4 failures (`test_the_block_being_rewritten_is_still_locked` already passes — it is a regression guard).

- [ ] **Step 3: Expose a registration hook from `script.js`**

`pendingEvents` is module-private in `script.js`. Add an export object near the end of that file's IIFE, beside wherever other globals are assigned:

```js
  // subunits.js owns the round; script.js owns the poll loop and the progress
  // map. The round has to land in pendingEvents or applyProgress skips it —
  // that omission is why round progress was computed and discarded.
  window.AnnotatePage = {
    registerRoundEvent(eventId, blockIds) {
      if (!eventId) return;
      pendingEvents.set(String(eventId), {
        round: true,
        blockIds: Array.isArray(blockIds) ? blockIds.slice() : [],
      });
    },
  };
```

- [ ] **Step 4: Register the round at submit**

In `skills/annotate/static/subunits.js`, in `submitRound`, the success handler currently reads:

```js
    WebCompanion.api.submit({ type: "round", reactions }).then((res) => {
      pendingRound = res && res.event_id ? String(res.event_id) : null;
      renderDock();
    })
```

Change it to capture the submitted block ids and register the event:

```js
    // Captured HERE, not read back later: clearRound() wipes `marks` on ack,
    // so this is the only moment the "what did the user actually ask for" set
    // exists. Task 4's attribution split depends on it.
    lastSubmittedBlockIds = [...new Set(reactions.map(r => r.block_id))];
    WebCompanion.api.submit({ type: "round", reactions }).then((res) => {
      pendingRound = res && res.event_id ? String(res.event_id) : null;
      window.AnnotatePage?.registerRoundEvent(pendingRound, lastSubmittedBlockIds);
      renderDock();
    })
```

Declare `let lastSubmittedBlockIds = [];` beside the other module-level state (near `let pendingRound = null;`), and export a reader on the `window.AnnotateSubunits` object:

```js
    submittedBlockIds: () => lastSubmittedBlockIds.slice(),
```

Do **not** clear `lastSubmittedBlockIds` in `clearRound()` — the change bar reads it after the ack.

- [ ] **Step 5: Make the banner carry a label**

In `setBusy` in `skills/annotate/static/script.js`, replace the single static label with labelled parts. The current construction is:

```js
        const label = document.createElement("span");
        label.textContent = "Claude is updating the plan… the page is locked until it replies.";
        banner.append(spin, label);
```

Replace with:

```js
        const label = document.createElement("span");
        label.className = "bb-label";
        label.textContent = "Claude is applying your round…";
        const sub = document.createElement("span");
        sub.className = "bb-sub";
        const timer = document.createElement("span");
        timer.className = "bb-timer";
        banner.append(spin, label, sub, timer);
        banner.dataset.startedAt = String(Date.now());
```

Then, still inside `setBusy`'s `busy` branch and after the banner exists, start a ticking timer, and clear it when busy goes false:

```js
      if (!busyTimer) {
        busyTimer = setInterval(() => {
          const b = document.getElementById("busy-banner");
          if (!b) return;
          const t = Math.floor((Date.now() - Number(b.dataset.startedAt || Date.now())) / 1000);
          const el = b.querySelector(".bb-timer");
          if (el) el.textContent = `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
        }, 1000);
      }
```

and in the `else` branch (busy false), before removing the banner:

```js
      if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
```

Declare `let busyTimer = null;` beside the other module state.

- [ ] **Step 6: Feed round progress into the banner**

In `applyProgress` in `script.js`, the loop currently handles `pend.blockId` and general comments. Add a round branch inside the same loop, after the existing `if (pend.blockId)` handling:

```js
      if (pend.round) {
        const b = document.getElementById("busy-banner");
        if (b) {
          const el = b.querySelector(".bb-label");
          if (el && label) el.textContent = label;
        }
        continue;
      }
```

- [ ] **Step 7: Un-freeze marking, keep the mid-rewrite block locked**

In `skills/annotate/static/style.css`, replace:

```css
/* Every strip control goes away while a round is in flight — they would all
   be editing a document that is mid-rewrite. */
body.is-busy .unit-strip button { display: none; }
```

with this comment and **no rule at all** — delete the declaration outright:

```css
/* Marking stays LIVE while a round is in flight, so there is deliberately no
   `body.is-busy .unit-strip` rule here. Marks are local until Submit, so the
   only thing that ever needed the lock is Submit itself — freezing the whole
   vocabulary took away work the user could still do on the sections Claude
   is not touching. A block genuinely being rewritten is still locked, by
   `section.block.is-updating` above. Marks made now queue for the next
   round, and the dock says so. */
```

Delete rather than override: `.unit-strip button` sets no `display` of its own
(it inherits the default `inline-block`), so re-declaring one here would
silently re-centre every glyph in the strip.

Then find the `body.is-busy .hover-actions` rule that sets `pointer-events: none; opacity: 0.4;` and remove `.hover-actions` from that selector list, leaving the other selectors in it untouched. The comment above it mentions freezing every affordance — update it to say that only submission is frozen.

- [ ] **Step 8: Make the dock say marks are queued for the next round**

In `renderDock` in `subunits.js`, the disabled line is:

```js
    btn.disabled = !!pendingRound || document.body.classList.contains("is-busy");
```

Leave the disabling in place, but when busy give the button honest text. Immediately above that line add:

```js
    if (document.body.classList.contains("is-busy") && !pendingRound) {
      btn.textContent = count
        ? `${count} queued for next round`
        : "Claude is working…";
      btn.title = "Keep marking — this submits once Claude finishes.";
    }
```

- [ ] **Step 9: Verify and commit**

```bash
node --check skills/annotate/static/subunits.js
node --check skills/annotate/static/script.js
python3 -m pytest skills/ -q
```

```bash
git add -A skills/annotate/
git commit -m "feat(annotate): the busy banner speaks, and marking no longer freezes

The progress pipeline already existed end to end — a hook publishes
labels, /poll serves them, applyProgress renders them — but a round
never registered its event id, so every label was computed, sent and
discarded.

Marks are local until Submit, so only Submit needed the lock."
```

---

### Task 3: Turn the round dock into a review drawer

**Files:**
- Modify: `skills/annotate/static/subunits.js`
- Modify: `skills/annotate/static/style.css`
- Test: `skills/annotate/tests/test_smoke_round_drawer.py` (create)

**Interfaces:**
- Consumes: the existing `marks` store and `renderDock` from `subunits.js`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_round_drawer.py`:

```python
"""Structural guards for the round review drawer.

`Submit round (12)` was the entire record of twelve irreversible decisions
made across six screens. The drawer's job is that the user can see and edit
the batch before it is sent, so the guards are: a manifest exists, a single
mark can be removed from it, and it says nothing has reached Claude yet.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
STYLE_CSS = STATIC / "style.css"


def test_the_dock_renders_a_manifest():
    src = SUBUNITS_JS.read_text()
    assert "rd-list" in src, "the drawer renders no mark list"
    assert "rd-row" in src, "the drawer renders no per-mark row"


def test_a_single_mark_can_be_removed():
    src = SUBUNITS_JS.read_text()
    assert "rd-x" in src, "no per-mark remove control"


def test_a_row_can_be_jumped_to():
    src = SUBUNITS_JS.read_text()
    assert "scrollIntoView" in src, "drawer rows do not scroll to their mark"


def test_the_drawer_says_nothing_has_been_sent():
    """The sentence that makes the drawer safe to explore."""
    src = SUBUNITS_JS.read_text()
    assert "undoable until you submit" in src, \
        "the drawer does not tell the user the batch is still local"


def test_the_drawer_is_styled():
    css = STYLE_CSS.read_text()
    for needle in (".round-drawer", ".rd-head", ".rd-list", ".rd-row", ".rd-x"):
        assert needle in css, f"style.css missing {needle}"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_round_drawer.py -q
```

Expected: 5 failures.

- [ ] **Step 3: Rebuild `renderDock` as a drawer**

In `skills/annotate/static/subunits.js`, `renderDock` currently creates `#round-dock` containing one button. Rewrite it so the dock element contains a header (caret, per-kind counts, Submit) and an expandable list. Keep the existing element id `#round-dock` and the existing Submit button id `#round-submit` so nothing else breaks.

Keep all current behaviour: the dock disappears when there are no marks and no in-flight round; Submit shows `Submit round (n)`; the error state shows `Submit failed — retry`; the busy text from Task 2 still applies.

Add:

```js
  // Open/closed is remembered for the session so the drawer does not
  // re-collapse under the user every time a mark changes.
  let drawerOpen = false;

  function markRows() {
    // Stable order: document order by block, then by the mark's ordinal, so
    // the manifest reads like the page rather than like a hash map.
    const order = [...document.querySelectorAll("section.block[data-block-id]")]
      .map(s => s.dataset.blockId);
    return Object.entries(marks).map(([key, m]) => ({ key, m })).sort((a, b) => {
      const ai = order.indexOf(a.m.block_id), bi = order.indexOf(b.m.block_id);
      if (ai !== bi) return ai - bi;
      return (a.m.ordinal || 0) - (b.m.ordinal || 0);
    });
  }

  function blockTitleFor(blockId) {
    const s = document.querySelector(
      `section.block[data-block-id="${CSS.escape(blockId)}"]`);
    const n = s?.querySelector(".section-pill .sp-sec")?.textContent || "?";
    const t = s?.querySelector(".card-title")?.textContent || blockId;
    return `§${n} · ${t}`;
  }

  function jumpToMark(m) {
    const s = document.querySelector(
      `section.block[data-block-id="${CSS.escape(m.block_id)}"]`);
    if (!s) return;
    const target = m.selected_text
      ? [...s.querySelectorAll(".sub-unit")].find(
          el => unitText(stripClone(el)) === m.selected_text) || s
      : s;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("rd-flash");
    setTimeout(() => target.classList.remove("rd-flash"), 1200);
  }

  function removeMark(key) {
    delete marks[key];
    saveMarks();
    repaintBlocks();
    document.querySelectorAll("section.block .block-content").forEach(root => {
      const bid = root.closest("section.block")?.dataset.blockId;
      if (bid) root.querySelectorAll(".sub-unit").forEach(
        el => applyMarkState(root, el, bid));
    });
    renderDock();
  }
```

Build each row with the kind glyph (reuse `CONTROL_SPECS`' glyph for that kind), `blockTitleFor(m.block_id)` in a `.rd-where`, the mark's `selected_text` in a `.rd-text`, the mark's `text` in a `.rd-said` when present, and a `.rd-x` button calling `removeMark(key)` with `stopPropagation`. Clicking the row calls `jumpToMark(m)`. The list ends with a `.rd-foot` containing exactly:

```
Click any row to jump to it. Nothing has reached Claude yet — every mark is undoable until you submit.
```

Toggle `dataset.open` on the dock from the header click, ignoring clicks that land on the Submit button.

- [ ] **Step 4: Style the drawer**

Add to `skills/annotate/static/style.css`, replacing the existing `#round-dock` rules (keep `#round-dock button` styling for the Submit button by retargeting it at `#round-submit`):

```css
/* ── Round review drawer ──────────────────────────────────────────────
   The collapsed state is the old dock. Expanded, it is the manifest for a
   batch of irreversible decisions the user made across several screens —
   which is why every row can be jumped to and removed. */
#round-dock {
  position: fixed; left: 50%; transform: translateX(-50%); bottom: 16px;
  z-index: 40; width: min(560px, calc(100vw - 40px));
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden;
  box-shadow: 0 10px 34px rgba(15,23,42,.20), 0 2px 8px rgba(15,23,42,.10);
}
.rd-head {
  display: flex; align-items: center; gap: 10px; padding: 10px 13px;
  cursor: pointer; border-bottom: 1px solid var(--border);
  background: var(--surface-soft);
}
.rd-caret { color: var(--text-dim); font-size: 11px; transition: transform 140ms ease; }
#round-dock[data-open="true"] .rd-caret { transform: rotate(180deg); }
.rd-summary { display: flex; gap: 9px; align-items: center; flex-wrap: wrap;
  font-size: 12px; color: var(--text-dim); }
.rd-summary b { color: var(--text-strong); font-variant-numeric: tabular-nums; }
#round-submit {
  margin-left: auto; flex: none; border: none; border-radius: 999px;
  padding: 8px 17px; font: inherit; font-size: 12.5px; font-weight: 700;
  cursor: pointer; background: var(--text-strong); color: #fff;
}
#round-submit:disabled { opacity: .45; cursor: default; }
.rd-list { max-height: 268px; overflow-y: auto; display: none; }
#round-dock[data-open="true"] .rd-list { display: block; }
.rd-row {
  display: flex; align-items: flex-start; gap: 9px; padding: 8px 13px;
  border-bottom: 1px solid var(--surface-soft); cursor: pointer; font-size: 12.5px;
}
.rd-row:last-child { border-bottom: none; }
.rd-row:hover { background: var(--hover-tint); }
.rd-k {
  flex: none; width: 21px; height: 21px; border-radius: 5px; color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: 10px;
}
.rd-k svg { width: 12px; height: 12px; fill: none; stroke: currentColor;
  stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.rd-k[data-kind="delete"]  { background: #dc2626; }
.rd-k[data-kind="keep"]    { background: #16a34a; }
.rd-k[data-kind="comment"] { background: var(--accent); }
.rd-k[data-kind="compact"] { background: #7c3aed; }
.rd-body { flex: 1; min-width: 0; }
.rd-where { color: var(--text-dim); font-size: 10.5px; margin-bottom: 1px; }
.rd-text { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rd-said { color: var(--accent); font-style: italic; margin-top: 2px; font-size: 11.5px; }
.rd-x {
  flex: none; border: none; background: transparent; color: var(--text-dim);
  cursor: pointer; font-size: 15px; line-height: 1; padding: 2px 4px; border-radius: 4px;
}
.rd-x:hover { color: #dc2626; background: color-mix(in srgb, #dc2626 10%, transparent); }
.rd-foot {
  padding: 7px 13px; font-size: 11px; color: var(--text-dim);
  background: var(--surface-soft); border-top: 1px solid var(--border);
}
/* Brief highlight when a drawer row scrolls you to its mark. */
.rd-flash { animation: rd-flash 1.2s ease; }
@keyframes rd-flash {
  0%, 100% { background: transparent; }
  30%      { background: color-mix(in srgb, var(--accent) 22%, transparent); }
}
```

- [ ] **Step 5: Verify and commit**

```bash
node --check skills/annotate/static/subunits.js
python3 -m pytest skills/ -q
```

```bash
git add -A skills/annotate/
git commit -m "feat(annotate): the round dock becomes a review drawer

A count was the entire record of a batch of irreversible decisions made
across several screens. The drawer lists each mark with where it is and
what you said, jumps to it on click, and lets you drop one without
clearing the round."
```

---

### Task 4: Show what changed, and who changed it

**Files:**
- Modify: `skills/annotate/static/script.js`
- Modify: `skills/annotate/static/style.css`
- Test: `skills/annotate/tests/test_smoke_change_bar.py` (create)

**Interfaces:**
- Consumes: `GET /s/<sid>/prev` from Task 1; `window.AnnotateSubunits.submittedBlockIds()` from Task 2.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_change_bar.py`:

```python
"""Structural guards for the change summary bar and per-block diff.

The coherence sweep's whole job is changing blocks the user never marked.
Before this, the only signal that anything moved was a version pill in a
card corner — so the sweep edited unmarked sections invisibly and the user
had to take it on faith. These guard that the signal exists AND that it
distinguishes what the user asked for from what the sweep decided.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"


def test_a_change_bar_is_rendered():
    src = SCRIPT_JS.read_text()
    assert "change-bar" in src, "no change summary bar"
    assert "sections changed" in src, "the bar does not say how many moved"


def test_the_bar_splits_asked_from_swept():
    """The entire reason the bar earns its space."""
    src = SCRIPT_JS.read_text()
    assert "coherence sweep" in src, \
        "the bar does not attribute changes to the sweep"
    assert "submittedBlockIds" in src, \
        "attribution is not derived from what the user actually submitted"


def test_changed_blocks_carry_an_attribution_chip():
    src = SCRIPT_JS.read_text()
    assert "attr-chip" in src, "changed blocks carry no attribution chip"


def test_the_diff_reads_the_snapshot():
    src = SCRIPT_JS.read_text()
    assert "/prev" in src, "the client never fetches the pre-round snapshot"


def test_the_diff_is_styled():
    css = STYLE_CSS.read_text()
    for needle in (".change-bar", ".attr-chip", ".diff-pane", ".card-diff-toggle"):
        assert needle in css, f"style.css missing {needle}"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_change_bar.py -q
```

Expected: 5 failures.

- [ ] **Step 3: Detect the change set on ack**

`script.js` already tracks per-block versions across polls. In the poll handler, when a round's ack arrives (busy goes false and versions moved), compute:

```js
  // Which blocks moved, and who moved them. The user's own set is whatever
  // they submitted — captured at submit time in subunits.js, because
  // clearRound() wipes the marks on ack and this is the only surviving
  // record. Everything else that moved was the coherence sweep.
  function computeChangeSet(prevVersions, nextVersions) {
    const asked = new Set(window.AnnotateSubunits?.submittedBlockIds?.() || []);
    const changed = [];
    for (const [bid, v] of Object.entries(nextVersions || {})) {
      const before = prevVersions ? prevVersions[bid] : undefined;
      if (before !== undefined && v > before) {
        changed.push({ blockId: bid, bySweep: !asked.has(bid) });
      }
    }
    return changed;
  }
```

`core.js` already passes a `lastVersions` value into the poll callback which `script.js` currently drops — use it rather than adding new bookkeeping. If it is not usable, keep a module-level `let lastVersions = null;` updated at the end of each poll.

- [ ] **Step 4: Render the bar**

```js
  function renderChangeBar(changed) {
    document.getElementById("change-bar")?.remove();
    if (!changed.length) return;
    const swept = changed.filter(c => c.bySweep).length;
    const asked = changed.length - swept;
    const bar = document.createElement("div");
    bar.id = "change-bar";
    bar.className = "change-bar";
    bar.setAttribute("role", "status");
    const dot = document.createElement("span");
    dot.className = "cb-dot";
    const txt = document.createElement("span");
    const parts = [];
    if (asked) parts.push(`${asked} you marked`);
    if (swept) parts.push(`${swept} by the coherence sweep`);
    txt.innerHTML = `<b>${changed.length} section${changed.length > 1 ? "s" : ""} changed</b>`
      + (parts.length ? ` — <span class="cb-split">${parts.join(", ")}</span>` : "");
    const nav = document.createElement("span");
    nav.className = "cb-nav";
    let idx = -1;
    const go = (d) => {
      if (!changed.length) return;
      idx = (idx + d + changed.length) % changed.length;
      document.querySelector(
        `section.block[data-block-id="${CSS.escape(changed[idx].blockId)}"]`
      )?.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    for (const [label, d] of [["↑ prev", -1], ["next ↓", 1]]) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.addEventListener("click", () => go(d));
      nav.appendChild(b);
    }
    const dis = document.createElement("button");
    dis.type = "button"; dis.textContent = "dismiss";
    dis.addEventListener("click", () => bar.remove());
    nav.appendChild(dis);
    bar.append(dot, txt, nav);
    const header = document.querySelector(".page-header");
    if (header) header.insertAdjacentElement("afterend", bar);
  }
```

- [ ] **Step 5: Mark changed cards and add the diff toggle**

For each entry in the change set, add to that block's `.card-head`, before the section pill: an `.attr-chip` with class `a-you` reading `you asked` or `a-sweep` reading `sweep`; and a `.card-diff-toggle` button reading `what changed` that toggles `dataset.diff` on the section between `""` and `"open"` and flips its own `aria-pressed`.

Both are removed when the next round starts, so a card never carries stale attribution.

- [ ] **Step 6: Render the diff**

Fetch the snapshot once per change set:

```js
  async function loadPrev() {
    try {
      const r = await fetch(WebCompanion.base + "prev");
      if (!r.ok) return null;
      const d = await r.json();
      return d && d.ok ? d.blocks : null;
    } catch { return null; }
  }
```

Use whatever base-URL helper `script.js` already uses for its other fetches rather than inventing one — match the existing call sites.

For a block with previous text, render a `.diff-pane` inside the section after `.card-body`, containing a `.diff-h` heading — `changed from v<n>` normally, and `changed from v<n> — you did not mark this section` when `bySweep` — followed by a word-level diff of previous versus current markdown, with removals in `<del>` and additions in `<ins>`.

Implement the word diff inline; do not add a dependency:

```js
  // Word-level LCS. Small documents, runs once per changed block, so an
  // O(n·m) table is fine and keeps the whole thing dependency-free.
  function wordDiff(a, b) {
    const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
    const n = A.length, m = B.length;
    const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1
                                 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) { out.push(["=", A[i]]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(["-", A[i]]); i++; }
      else { out.push(["+", B[j]]); j++; }
    }
    while (i < n) out.push(["-", A[i++]]);
    while (j < m) out.push(["+", B[j++]]);
    return out;
  }
```

Render each run with `document.createTextNode` inside `<del>` / `<ins>` / a bare span — **never** by string-concatenating into `innerHTML`, since block markdown is arbitrary text.

If the block carries a `change_note` field (Task 5), render it below the diff in a `.diff-why`.

- [ ] **Step 7: Style it**

Add to `style.css` the `.change-bar`, `.cb-dot`, `.cb-split`, `.cb-nav`, `.attr-chip` (with `.a-you` / `.a-sweep`), `.card-diff-toggle`, `.diff-pane` (shown only when `section.block[data-diff="open"]`), `.diff-h`, `.diff-why`, and `del` / `ins` styling. Copy the declarations verbatim from the approved mockup at `/tmp/claude-scratch/1de9890d-3c3e-490b-a4d6-3fb75ae23293/scratchpad/mockroot/index.html` — search that file for `NEW ── Change summary bar` and `NEW ── Per-block "what changed"` and take those two blocks as written.

- [ ] **Step 8: Verify and commit**

```bash
node --check skills/annotate/static/script.js
python3 -m pytest skills/ -q
```

```bash
git add -A skills/annotate/
git commit -m "feat(annotate): show what changed and who changed it

Attribution is derived in the browser from the block ids the client
submitted, so it needs neither the server nor Claude and cannot drift.
The diff reads the pre-round snapshot, which is the only record of what
a block said before."
```

---

### Task 5: Let Claude explain a change, and name what compact lost

A mechanical diff shows what the text became but not why, and for a compact it cannot show what was dropped — that exists only in Claude's head at apply time.

**Files:**
- Modify: `skills/annotate/references/handling-events.md`
- Test: `skills/annotate/tests/test_round_contract.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an optional `change_note` string field on a block in `blocks.json`, consumed by Task 4's diff pane.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_round_contract.py`:

```python
def test_the_contract_describes_the_change_note():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "change_note" in doc, "the contract does not mention change_note"


def test_a_compact_must_name_what_it_lost():
    """Compact is lossy and irreversible after submit. The change note is the
    only place the user could ever learn what it actually discarded."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "Lost:" in doc, \
        "the contract does not require a compact to name the dropped detail"


def test_the_change_note_is_optional():
    """A feature that breaks when Claude forgets a field is a broken feature."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "optional" in doc.lower(), \
        "the contract does not state that change_note is optional"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_round_contract.py -q -k "change_note or lost or optional"
```

Expected: 3 failures.

- [ ] **Step 3: Document the field**

Add a section to `handling-events.md`, immediately after `## The coherence sweep`:

```markdown
## Explaining a change: `change_note`

The page can show a mechanical diff of any block you rewrite — it snapshots
the document when the event is queued. What it cannot derive is **why** you
changed something, and for a `compact` it cannot know **what you dropped**,
because that judgement existed only while you were applying the round.

So when you rewrite a block, you may set an optional `change_note` string on
it. Keep it to one or two sentences, in this shape:

    Why: you asked whether this holds when the consumer is idle. It doesn't,
    so the claim is now conditional.

For a block where a `compact` discarded detail that no surviving sentence
could carry, add a second line naming exactly what is gone:

    Lost: the flag key `ingest.v2.writes`.

**The `Lost:` line is the honest half of compact.** Compact is lossy and
irreversible once the round is submitted, and this note is the only place a
user could ever find out what it actually discarded. Write it whenever detail
was dropped; do not write it when nothing was.

`change_note` is **optional** and describes only the most recent rewrite.
Clear it on a block you rewrite without anything worth explaining, rather than
leaving a note that describes an older change. The diff renders with or
without it — never withhold a rewrite because you cannot phrase the note.
```

- [ ] **Step 4: Verify and commit**

```bash
python3 -m pytest skills/ -q
```

```bash
git add skills/annotate/references/handling-events.md skills/annotate/tests/test_round_contract.py
git commit -m "feat(annotate): change_note lets Claude say why, and what compact lost

A mechanical diff shows what the text became. It cannot show why, and for
a compact it cannot show what was dropped — that judgement exists only at
apply time. Optional by design: the diff renders without it."
```

---

### Task 6: Give the reading surface back to the document

**Files:**
- Modify: `skills/annotate/server.py` (the page shell)
- Modify: `skills/annotate/static/script.js`
- Modify: `skills/annotate/static/style.css`
- Test: `skills/annotate/tests/test_smoke_reading_chrome.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_reading_chrome.py`:

```python
"""Structural guards for the reading surface.

Three problems, one theme: the document was not the most prominent thing on
its own page. The composer held the space above the fold, nothing told a
first-time reader the page was interactive, and a long plan had no shape.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"
SERVER_PY = REPO / "skills" / "annotate" / "server.py"


def test_the_composer_starts_collapsed():
    server = SERVER_PY.read_text()
    assert "composer-collapsed" in server, \
        "the general composer still opens as a full textarea"


def test_a_first_run_hint_exists():
    src = SCRIPT_JS.read_text()
    assert "discover-hint" in src, "nothing tells a first-time reader the page is interactive"
    assert "annotate.hint." in src, "the hint's dismissal is not remembered"


def test_a_document_map_is_rendered():
    src = SCRIPT_JS.read_text()
    assert "map-rail" in src, "no document map"
    assert "map-item" in src, "the map has no section entries"


def test_the_map_shows_pending_marks():
    """The rail is the surface every other signal reuses."""
    src = SCRIPT_JS.read_text()
    assert "map-dot" in src, "the map shows no per-section state"


def test_the_reading_chrome_is_styled():
    css = STYLE_CSS.read_text()
    for needle in (".map-rail", ".map-item", ".composer-collapsed", ".discover-hint"):
        assert needle in css, f"style.css missing {needle}"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_reading_chrome.py -q
```

Expected: 5 failures.

- [ ] **Step 3: Collapse the composer**

In `skills/annotate/server.py`, wrap the existing `<section class="general-composer">` so it renders hidden by default, preceded by a trigger button:

```python
            f'<button id="composer-open" type="button" class="composer-collapsed">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" aria-hidden="true">'
            f'<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 '
            f'8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 '
            f'8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'
            f'</svg>Comment on the whole response'
            f'<span class="cc-kbd">G</span></button>'
```

and add `hidden` to the `general-composer` section element. In `script.js`, wire `#composer-open` to unhide the section, hide the button, and focus `#general-input`. Bind `g` (when no input is focused) to the same action.

- [ ] **Step 4: Add the first-run hint**

In `script.js`, on load, if `localStorage.getItem("annotate.hint." + RID)` is unset, insert before the prose:

```js
  function renderDiscoverHint() {
    const key = "annotate.hint." + (document.body.dataset.responseId || "");
    try { if (localStorage.getItem(key)) return; } catch { return; }
    const hint = document.createElement("div");
    hint.className = "discover-hint";
    const glyphs = document.createElement("span");
    glyphs.className = "dh-glyphs";
    for (const g of ["🗑", "✓", "💬"]) {
      const s = document.createElement("span"); s.textContent = g; glyphs.appendChild(s);
    }
    const eye = document.createElement("span");
    eye.innerHTML = window.AnnotateSubunits?.COMPACT_ICON || "";
    glyphs.appendChild(eye);
    const txt = document.createElement("span");
    txt.textContent = "Hover any sentence to mark it. Marks batch up — nothing reaches Claude until you submit.";
    const x = document.createElement("button");
    x.type = "button"; x.className = "dh-x"; x.textContent = "×";
    x.title = "Dismiss";
    x.addEventListener("click", () => {
      try { localStorage.setItem(key, "1"); } catch {}
      hint.remove();
    });
    hint.append(glyphs, txt, x);
    proseEl?.parentNode?.insertBefore(hint, proseEl);
  }
```

Call it once after the first render. Use whatever variable `script.js` already holds the prose element in rather than re-querying.

- [ ] **Step 5: Add the document map rail**

In `script.js`, build a `<nav class="map-rail">` and place it as a sibling of `main.prose`, wrapping both in a flex container. Rebuild its items whenever blocks render:

```js
  function renderMapRail() {
    let rail = document.getElementById("map-rail");
    if (!rail) {
      rail = document.createElement("nav");
      rail.id = "map-rail";
      rail.className = "map-rail";
      proseEl?.parentNode?.insertBefore(rail, proseEl);
    }
    const sections = [...document.querySelectorAll("section.block[data-block-id]")];
    const frag = document.createDocumentFragment();
    const head = document.createElement("div");
    head.className = "map-rail-head";
    const h1 = document.createElement("span"); h1.textContent = "Document";
    const h2 = document.createElement("span");
    h2.className = "map-count";
    h2.textContent = `${sections.length} section${sections.length === 1 ? "" : "s"}`;
    head.append(h1, h2);
    frag.appendChild(head);
    sections.forEach((s, i) => {
      const item = document.createElement("div");
      item.className = "map-item";
      const n = document.createElement("span");
      n.className = "map-n"; n.textContent = String(i + 1);
      const t = document.createElement("span");
      t.className = "map-t";
      t.textContent = s.querySelector(".card-title")?.textContent || s.dataset.blockId;
      const dots = document.createElement("span");
      dots.className = "map-dots";
      // One dot per distinct mark kind pending in this section, plus one for
      // a section changed by the last round.
      const kinds = new Set();
      s.querySelectorAll(".sub-unit[data-mark]").forEach(u => kinds.add(u.dataset.mark));
      if (s.dataset.blockMark) kinds.add(s.dataset.blockMark);
      for (const k of kinds) {
        const d = document.createElement("span");
        d.className = "map-dot d-" + k;
        dots.appendChild(d);
      }
      if (s.dataset.diff !== undefined && s.querySelector(".attr-chip")) {
        const d = document.createElement("span");
        d.className = "map-dot " + (s.querySelector(".a-sweep") ? "d-swept" : "d-changed");
        dots.appendChild(d);
      }
      item.append(n, t, dots);
      item.addEventListener("click", () =>
        s.scrollIntoView({ behavior: "smooth", block: "start" }));
      frag.appendChild(item);
    });
    rail.replaceChildren(frag);
  }
```

Call it after every block render and after any mark change.

- [ ] **Step 6: Style the reading chrome**

Copy the `.map-rail`, `.map-rail-head`, `.map-item`, `.map-n`, `.map-t`, `.map-dots`, `.map-dot` (with `d-comment` / `d-delete` / `d-compact` / `d-keep` / `d-changed` / `d-swept`), `.composer-collapsed`, `.cc-kbd`, `.discover-hint`, `.dh-glyphs` and `.dh-x` declarations verbatim from the approved mockup at `/tmp/claude-scratch/1de9890d-3c3e-490b-a4d6-3fb75ae23293/scratchpad/mockroot/index.html` — search for `NEW ── Document map rail`, `NEW ── Collapsed general composer` and `NEW ── First-run discovery hint`.

Add the flex shell so the rail and the document sit side by side, and hide the rail below 900px:

```css
.reading-shell { display: flex; gap: 20px; align-items: flex-start;
  max-width: var(--content-max); margin: 0 auto; }
@media (max-width: 900px) { .map-rail { display: none; } }
```

- [ ] **Step 7: Verify and commit**

```bash
node --check skills/annotate/static/script.js
python3 -m pytest skills/ -q
```

```bash
git add -A skills/annotate/
git commit -m "feat(annotate): give the reading surface back to the document

The composer collapses to one line, a dismissible hint says the page is
interactive, and a map rail gives a long plan a shape. The rail is also
the surface pending marks and changed sections reuse."
```

---

### Task 7: Fix compact's severity, rename keep, and close two bugs

**Files:**
- Modify: `skills/annotate/static/style.css`
- Modify: `skills/annotate/static/subunits.js`
- Modify: `skills/annotate/static/script.js`
- Modify: `skills/annotate/server.py` (legend)
- Test: `skills/annotate/tests/test_smoke_compact.py`, `skills/annotate/tests/test_smoke_dismiss_lock.py`

**Interfaces:**
- Consumes: nothing. Produces: nothing.

- [ ] **Step 1: Write the failing tests**

Append to `skills/annotate/tests/test_smoke_compact.py`:

```python
def test_compact_reads_as_heavier_than_it_did():
    """Compact discards detail the user never chose to lose, so it must not
    look gentler than delete, which removes content they did choose to."""
    css = STYLE_CSS.read_text()
    assert 'border-left: 2px solid #7c3aed' in css, \
        "the compact mark has no severity spine"
    assert '.sub-unit[data-mark="compact"]::after' in css, \
        "the compact mark states no consequence at the point of decision"


def test_compact_still_is_not_delete():
    """Heavier, but never struck through — strikethrough is delete's, and
    conflating them is the failure this styling exists to avoid."""
    css = STYLE_CSS.read_text()
    i = css.index('.sub-unit[data-mark="compact"]')
    assert "line-through" not in css[i:i + 400], \
        "compact was made to look like delete"


def test_keep_is_labelled_by_what_it_does():
    """The tick reads as approval and gets clicked liberally; it costs a
    round and does nothing outside two narrow cases."""
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    assert "Leave as written" in subunits, "unit strip still calls it Keep"
    assert "Leave as written" in script, "header strip still calls it Keep"
    assert '"keep"' in subunits, "the wire kind must stay `keep`"
```

Append to `skills/annotate/tests/test_smoke_dismiss_lock.py`:

```python
def test_submit_is_blocked_while_a_comment_is_open():
    """Drafts and round marks live in separate stores and submitRound reads
    only the second, so submitting with an editor open silently omits the
    comment the user believes they left."""
    src = SUBUNITS_JS.read_text()
    i = src.index("btn.disabled")
    assert "is-editing" in src[i:i + 200], \
        "the dock can still submit while a comment editor is open"


def test_the_dead_session_banner_does_not_claim_the_round_was_lost():
    """The event stays queued and a fresh watcher re-emits it. Saying it was
    not processed invites the user to submit the same round twice."""
    src = SCRIPT_JS.read_text()
    assert "was not processed" not in src, \
        "the dead-session banner still claims the submission was lost"
    assert "annotate resume" in src, \
        "the banner does not name the way to pick the page back up"
```

Add whatever module-level path constants those two files need (`SUBUNITS_JS`, `SCRIPT_JS`, `STYLE_CSS`) if they are not already defined there.

- [ ] **Step 2: Run them to verify they fail**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_compact.py skills/annotate/tests/test_smoke_dismiss_lock.py -q
```

Expected: 5 failures.

- [ ] **Step 3: Raise compact's severity**

In `style.css`, replace the existing `.sub-unit[data-mark="compact"]` rule with:

```css
/* Pending compact: heavier than it was, and never struck through.
   Strikethrough belongs to delete, and the two must stay distinguishable —
   but compact is the one that discards detail the user never chose to lose,
   so it cannot be the gentler-looking of the pair. The consequence is
   written where the user is about to click, because the legend they would
   otherwise learn it from is collapsed by default. */
.sub-unit[data-mark="compact"] {
  background: color-mix(in srgb, #7c3aed 13%, transparent);
  opacity: .62;
  border-left: 2px solid #7c3aed;
  padding-left: 8px;
}
.sub-unit[data-mark="compact"]::after {
  content: "compacted — its point is folded into what stays; the rest is lost";
  display: block; margin-top: 3px;
  font-size: 10.5px; font-style: italic; color: #6d28d9;
}
.sub-unit[data-mark="compact"]:hover { opacity: .8; }
```

- [ ] **Step 4: Rename keep at both scopes and in the legend**

The wire kind stays `keep`; only the label changes.

In `subunits.js`, `CONTROL_SPECS`: change the keep entry's title to `"Leave as written — don't rewrite this"`.
In `script.js`, `ACTION_TYPES`: change the keep entry's title to `"Leave as written — don't rewrite this section"`.
In `server.py`, `_LEGEND_HTML`: change the Check row's button label from `<span>Check</span>` to `<span>Leave as written</span>`.

- [ ] **Step 5: Stop Submit swallowing an open comment**

In `subunits.js`, `renderDock`, change:

```js
    btn.disabled = !!pendingRound || document.body.classList.contains("is-busy");
```

to:

```js
    // `is-editing` matters as much as the other two: drafts live in
    // script.js's store and round marks live here, and submitRound only
    // reads the latter — so submitting with an editor open silently drops
    // the comment the user believes they just left.
    const editing = document.body.classList.contains("is-editing");
    btn.disabled = !!pendingRound
      || document.body.classList.contains("is-busy")
      || editing;
    if (editing && !pendingRound) {
      btn.title = "Finish or discard the open comment first.";
    }
```

- [ ] **Step 6: Correct the dead-session banner**

In `script.js`, replace the banner text:

```js
        label.textContent =
          "Claude's session is gone. Your last submission is still queued — " +
          "it will be picked up when a Claude session reattaches to this page. " +
          "Run `/annotate resume` from a Claude session to continue. " +
          "Don't resubmit; it would apply the same round twice.";
```

Find where the dock is re-armed on a dead watcher (in `subunits.js`'s `onPoll`, the branch that clears `pendingRound` when `watcher_age_s` exceeds the threshold) and leave `pendingRound` set so Submit stays disabled, updating the button text to `Session gone — see the banner`.

- [ ] **Step 7: Verify and commit**

```bash
node --check skills/annotate/static/subunits.js
node --check skills/annotate/static/script.js
python3 -m pytest skills/ -q
```

```bash
git add -A skills/annotate/
git commit -m "fix(annotate): compact severity, keep's label, and two real bugs

Compact discards detail the user never chose to lose and looked gentler
than delete, which removes content they did. Keep read as approval.
Submit silently omitted an open comment. The dead-session banner claimed
a queued round was lost, inviting a duplicate."
```

---

## Verification

- [ ] `python3 -m pytest skills/ -q` green.
- [ ] `node --check` clean on `script.js` and `subunits.js`.
- [ ] Drive a real page: mark several sections, open the drawer, remove one mark, jump to another, submit; confirm the banner labels the work and marking still functions on untouched sections; confirm the change bar appears with a correct asked/swept split and the diffs render.
- [ ] Open a read-only URL for the same workspace: no marking controls, no drawer, and the diff still renders.

## Out of scope

Search that navigates rather than filters; unifying the two comment editors; a suggested-wording field; per-reaction failure reporting; multi-tab mark reconciliation; the dead code both reviews catalogued.
