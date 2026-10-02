# Annotate Fold Shortcuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ⌘K ⌘0 collapses every section and ⌘K ⌘J expands every section on the annotate reading page (the user's VS Code fold bindings), and the per-section fold chevron becomes a 26×26px round button matching the header action icons.

**Architecture:** One new self-contained IIFE in `skills/annotate/static/script.js` (a global keydown chord listener that reuses the existing `applyCollapsed()`/`collapseKey()` machinery), plus CSS in `skills/annotate/static/style.css` (a transient "⌘K …" pill and the chevron restyle). No server, HTML, or Python changes. The live server (port 3080) serves static assets from this checkout on every request with `Cache-Control: no-store`, so active sessions pick up the change on browser reload.

**Tech Stack:** Vanilla JS/CSS; pytest source-string smoke tests; Playwright `.e2e.cjs` scripts run with the global playwright package.

**Spec:** `docs/superpowers/specs/2026-08-10-annotate-fold-shortcuts-design.md`

## Global Constraints

- Chords are exactly **⌘K ⌘0** (fold all) and **⌘K ⌘J** (unfold all); Ctrl works in place of ⌘ (the code checks `metaKey || ctrlKey`, matching the file's existing shortcut idiom).
- `preventDefault()` must fire on ⌘K and on the second chord key (⌘K focuses Chrome's address bar; ⌘0 resets zoom).
- Chord armed state times out after 2000 ms; any non-modifier key that isn't a chord key disarms silently.
- Shortcuts are inert while typing (input, textarea, or contentEditable focused) — same guard as the existing "g" shortcut.
- Fold-all/unfold-all must write the same localStorage keys the chevron writes (`annotate.collapsed:<responseId>:<blockId>`), via the existing `collapseKey()`.
- Chevron button: 26×26px, `border-radius: 50%`, 1px dashed `var(--border)`, `background: var(--surface)` — the `.hover-actions button` family (style.css:276).
- All code lives INSIDE script.js's existing outer module wrapper (the whole file is one closure — `applyCollapsed` and `collapseKey` are only reachable from inside it).

---

### Task 1: Fold-all / unfold-all chord

**Files:**
- Test: `skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs` (new)
- Test: `skills/annotate/tests/test_smoke_fold_shortcuts.py` (new)
- Modify: `skills/annotate/static/script.js` (insert after the composer-open IIFE that ends `})();` near line 1331)
- Modify: `skills/annotate/static/style.css` (append a new section at the end)

**Interfaces:**
- Consumes: `applyCollapsed(section, chev, collapsed)` (script.js:803), `collapseKey(blockId)` (script.js:783), CSS class `collapsed` on `section.block.card`, CSS var tokens `--surface`, `--border`, `--text-dim`.
- Produces: CSS class `.chord-pill` (Task 2's smoke test and Task 3's curl check reference it).

- [ ] **Step 1: Write the failing e2e test**

Create `skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs`. The harness section (everything from `const { chromium }` through the `deck()` helper) is copied verbatim from `skills/annotate/tests/e2e/reading-chrome.e2e.cjs` lines 23–78 — same `startServer`, `postJSON`, `writeBlocks`, `para`, `deck`. Then the main body:

```js
#!/usr/bin/env node
/*
 * Playwright end-to-end for the fold chords: ⌘K ⌘0 collapses every card,
 * ⌘K ⌘J expands every card, the chord is inert while typing, and the state
 * survives a reload because it goes through the same localStorage keys the
 * per-card chevron writes.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs
 */

// … harness copied from reading-chrome.e2e.cjs lines 23–78 …

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  let beat;
  const cleanup = () => {
    try { clearInterval(beat); } catch (_) {}
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "fold-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));
    writeBlocks(sess.response_dir, deck(null));

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1512, height: 900 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-4"]', { timeout: 8000 });
    log("✓ blocks rendered");

    const collapsedCount = () => page.evaluate(
      () => document.querySelectorAll("section.block.card.collapsed").length);
    const cardCount = await page.evaluate(
      () => document.querySelectorAll("section.block.card").length);
    if (cardCount !== 5) fail("expected 5 cards, got " + cardCount);
    if ((await collapsedCount()) !== 0) fail("cards start collapsed");

    // ── 1. ⌘K arms the chord and shows the pill ────────────────────────────
    await page.keyboard.press("Meta+KeyK");
    const pillShown = await page.evaluate(
      () => getComputedStyle(document.querySelector(".chord-pill")).display !== "none");
    if (!pillShown) fail("the ⌘K pill did not appear while the chord is armed");
    log("✓ ⌘K arms, pill visible");

    // ── 2. ⌘0 folds every card, pill goes away ─────────────────────────────
    await page.keyboard.press("Meta+Digit0");
    if ((await collapsedCount()) !== 5) fail("⌘K ⌘0 collapsed " + (await collapsedCount()) + "/5 cards");
    const bodyGone = await page.evaluate(
      () => getComputedStyle(document.querySelector('section.block[data-block-id="b-0"] .card-body')).display);
    if (bodyGone !== "none") fail("collapsed card body still painted: display=" + bodyGone);
    const pillGone = await page.evaluate(
      () => getComputedStyle(document.querySelector(".chord-pill")).display === "none");
    if (!pillGone) fail("the pill stayed on screen after the chord resolved");
    log("✓ ⌘K ⌘0 folds all 5, pill dismissed");

    // ── 3. The fold went through the chevron's localStorage keys ───────────
    const stored = await page.evaluate(() => {
      const rid = document.body.dataset.responseId || "default";
      return ["b-0", "b-1", "b-2", "b-3", "b-4"].map(
        (id) => localStorage.getItem(`annotate.collapsed:${rid}:${id}`));
    });
    if (!stored.every((v) => v === "1")) fail("localStorage after fold-all: " + JSON.stringify(stored));
    log("✓ localStorage keys written");

    // ── 4. Fold state survives a reload ────────────────────────────────────
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-4"]', { timeout: 8000 });
    if ((await collapsedCount()) !== 5) fail("fold-all did not survive reload");
    log("✓ fold survives reload");

    // ── 5. ⌘K ⌘J unfolds every card ────────────────────────────────────────
    await page.keyboard.press("Meta+KeyK");
    await page.keyboard.press("Meta+KeyJ");
    if ((await collapsedCount()) !== 0) fail("⌘K ⌘J left " + (await collapsedCount()) + " cards folded");
    log("✓ ⌘K ⌘J unfolds all");

    // ── 6. A non-chord second key disarms without folding ──────────────────
    await page.keyboard.press("Meta+KeyK");
    await page.keyboard.press("KeyX");
    if ((await collapsedCount()) !== 0) fail("stray key after ⌘K folded something");
    const pillOff = await page.evaluate(
      () => getComputedStyle(document.querySelector(".chord-pill")).display === "none");
    if (!pillOff) fail("stray key after ⌘K left the pill armed");
    log("✓ stray second key disarms");

    // ── 7. Inert while typing in the composer ──────────────────────────────
    await page.locator("#composer-open").click();
    await page.waitForSelector("#general-input");
    await page.keyboard.press("Meta+KeyK");
    await page.keyboard.press("Meta+Digit0");
    if ((await collapsedCount()) !== 0) fail("the chord fired while typing in the composer");
    log("✓ chord inert while typing");

    log("ALL PASS");
  } finally {
    cleanup();
  }
})().catch((e) => { log(String(e && e.stack || e)); process.exit(1); });
```

- [ ] **Step 2: Run the e2e test to verify it fails**

Run: `cd ~/projects/claude-annotate && NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs`
Expected: FAIL at check 1 — `.chord-pill` does not exist yet (the `getComputedStyle(...)` evaluate throws or returns no element → script exits 1). Watch it fail before writing any implementation.

- [ ] **Step 3: Implement the chord listener in script.js**

Insert INSIDE the file's outer module wrapper, immediately after the composer-open IIFE (the block containing `openBtn.addEventListener("click", open)` that ends `})();` near line 1331):

```js
  // ── Fold-all / unfold-all chords (⌘K ⌘0 / ⌘K ⌘J) ─────────────────────────
  // The user's VS Code fold bindings, verbatim. ⌘K arms a two-step chord —
  // intercepted so the browser's address-bar focus never fires — and the
  // second key acts on every card through the same applyCollapsed +
  // localStorage path the per-card chevron uses, so a fold-all survives
  // reload and a single chevron click afterwards still toggles one card.
  (function () {
    let armed = null; // timeout id while waiting for the second chord key
    const pill = document.createElement("div");
    pill.className = "chord-pill";
    pill.textContent = "⌘K …";
    pill.hidden = true;
    document.body.appendChild(pill);

    function disarm() {
      if (armed !== null) { clearTimeout(armed); armed = null; }
      pill.hidden = true;
    }

    function foldAll(collapsed) {
      document.querySelectorAll("section.block.card").forEach((section) => {
        const chev = section.querySelector(".card-chevron");
        applyCollapsed(section, chev, collapsed);
        try {
          localStorage.setItem(collapseKey(section.dataset.blockId), collapsed ? "1" : "0");
        } catch (_) {}
      });
    }

    document.addEventListener("keydown", (e) => {
      const active = document.activeElement;
      const typing = active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        (active && active.isContentEditable);
      if (typing) { disarm(); return; }
      if (armed === null) {
        if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey &&
            (e.key === "k" || e.key === "K")) {
          e.preventDefault();
          pill.hidden = false;
          armed = setTimeout(disarm, 2000);
        }
        return;
      }
      // While armed, the modifier keys themselves (releasing/re-pressing ⌘
      // between the two strokes) neither resolve nor cancel the chord.
      if (e.key === "Meta" || e.key === "Control" || e.key === "Shift" || e.key === "Alt") return;
      if ((e.metaKey || e.ctrlKey) && e.key === "0") {
        e.preventDefault();
        foldAll(true);
      } else if ((e.metaKey || e.ctrlKey) && (e.key === "j" || e.key === "J")) {
        e.preventDefault();
        foldAll(false);
      }
      disarm();
    });
  })();
```

- [ ] **Step 4: Add the pill styles to style.css**

Append at the end of `skills/annotate/static/style.css` (highest existing z-index is 40, so the pill takes 50):

```css
/* === Fold-chord pill ================================================= */
/* Transient "⌘K …" indicator while the fold chord is armed — the role
   VS Code's status bar plays for a pending chord. Display-gated on the
   [hidden] attribute explicitly: an author display rule would beat the UA
   default, the exact cascade bug .general-composer[hidden] guards against. */
.chord-pill {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 50;
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1;
  pointer-events: none;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.chord-pill[hidden] { display: none; }
```

- [ ] **Step 5: Run the e2e test to verify it passes**

Run: `cd ~/projects/claude-annotate && NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs`
Expected: all seven `✓` lines then `ALL PASS`, exit 0.

- [ ] **Step 6: Write the source-string smoke test**

Create `skills/annotate/tests/test_smoke_fold_shortcuts.py`:

```python
"""Structural guards for the fold-all / unfold-all chords (⌘K ⌘0 / ⌘K ⌘J).

Source-string checks in the repo's smoke-test idiom; everything that needs a
rendered page (chord keystrokes, computed styles, localStorage) is asserted
in tests/e2e/fold-shortcuts.e2e.cjs.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"


def test_the_fold_chord_exists_and_reuses_the_chevron_machinery():
    """The whole point of the chord going through applyCollapsed +
    collapseKey is that fold-all state and per-chevron state are ONE state:
    a fold-all survives reload and a later chevron click toggles one card.
    A rewrite that folds cards by toggling classList directly would pass a
    bare existence check and silently fork the state."""
    src = SCRIPT_JS.read_text()
    assert "foldAll" in src, "no fold-all implementation in script.js"
    assert 'section.querySelector(".card-chevron")' in src, (
        "fold-all no longer routes through each card's chevron element"
    )
    assert "collapseKey(section.dataset.blockId)" in src, (
        "fold-all no longer writes the chevron's own localStorage keys — "
        "fold state and chevron state have forked"
    )


def test_the_chord_intercepts_the_browser_defaults():
    """⌘K focuses Chrome's address bar and ⌘0 resets zoom; without
    preventDefault the chord types into the omnibox instead of folding."""
    src = SCRIPT_JS.read_text()
    start = src.index("Fold-all / unfold-all chords")
    body = src[start:src.index("})();", start)]
    assert body.count("e.preventDefault()") >= 3, (
        "the chord block preventDefaults fewer than 3 times (⌘K, ⌘0, ⌘J) — "
        "a browser default is leaking through"
    )


def test_the_chord_pill_is_styled_and_actually_hides():
    """Same cascade trap test_the_collapsed_composer_is_actually_hidden
    guards: `pill.hidden = true` does nothing against an author display
    rule, so .chord-pill needs its own [hidden] { display: none }."""
    css = STYLE_CSS.read_text()
    assert ".chord-pill" in css, "style.css missing .chord-pill"
    assert ".chord-pill[hidden]" in css, (
        ".chord-pill has no [hidden] display:none rule — the pill's author "
        "display rule beats the bare hidden attribute and it never dismisses"
    )
```

- [ ] **Step 7: Run the smoke test and the full annotate suite**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_smoke_fold_shortcuts.py -v`
Expected: 3 passed.

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/ -q`
Expected: all pass, no regressions.

- [ ] **Step 8: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/static/script.js skills/annotate/static/style.css \
        skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs \
        skills/annotate/tests/test_smoke_fold_shortcuts.py
git commit -m "feat(annotate): fold-all/unfold-all chords (⌘K ⌘0 / ⌘K ⌘J)"
```

---

### Task 2: Chevron as a 26px round button

**Files:**
- Modify: `skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs` (append one check before `log("ALL PASS")`)
- Modify: `skills/annotate/tests/test_smoke_fold_shortcuts.py` (append one test)
- Modify: `skills/annotate/static/style.css:615-628` (the `.card-chevron` rule)

**Interfaces:**
- Consumes: `.card-chevron` button element (script.js:696), `.hover-actions button` visual family (style.css:276) — values copied, no shared selector.
- Produces: nothing downstream; Task 3 verifies the bytes reach the live server.

- [ ] **Step 1: Append the failing e2e check**

In `fold-shortcuts.e2e.cjs`, immediately before `log("ALL PASS")`:

```js
    // ── 8. The chevron is a 26px round button, not a 14px text glyph ───────
    const chev = await page.evaluate(() => {
      const el = document.querySelector('section.block[data-block-id="b-0"] .card-chevron');
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { w: Math.round(r.width), h: Math.round(r.height),
               radius: cs.borderRadius, border: cs.borderTopStyle };
    });
    if (chev.w !== 26 || chev.h !== 26) fail("chevron is " + chev.w + "×" + chev.h + ", expected 26×26");
    if (chev.radius !== "50%") fail("chevron border-radius = " + chev.radius);
    if (chev.border !== "dashed") fail("chevron border-style = " + chev.border + ", expected dashed");
    log("✓ chevron is a 26×26 round dashed button");
```

- [ ] **Step 2: Run the e2e test to verify the new check fails**

Run: `cd ~/projects/claude-annotate && NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs`
Expected: checks 1–7 pass, then FAIL with `chevron is 14×…, expected 26×26`. Watch it fail.

- [ ] **Step 3: Restyle .card-chevron**

Replace the whole `.card-chevron` rule at `style.css:615-627` (keep the separate `.card-head:hover .card-chevron` rule below it):

```css
.card-chevron {
  width: 26px;
  height: 26px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  /* Same control family as .hover-actions button: an easy 26px round
     target instead of the bare 14px text glyph it used to be. */
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: 50%;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  transition: color 120ms ease, border-color 120ms ease, background 120ms ease;
}
```

- [ ] **Step 4: Run the e2e test to verify it passes**

Run: `cd ~/projects/claude-annotate && NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs`
Expected: all eight `✓` lines then `ALL PASS`.

- [ ] **Step 5: Append the smoke test**

Add to `test_smoke_fold_shortcuts.py`:

```python
def test_the_chevron_is_a_round_button_not_a_text_glyph():
    """The chevron was a bare 14px-wide text glyph — the smallest target in
    the header. It now matches the 26px .hover-actions button family."""
    css = STYLE_CSS.read_text()
    start = css.index(".card-chevron {")
    rule = css[start:css.index("}", start)]
    for needle in ("width: 26px", "height: 26px", "border-radius: 50%",
                   "border: 1px dashed var(--border)"):
        assert needle in rule, f".card-chevron lost {needle!r}"
```

- [ ] **Step 6: Run all annotate tests**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/ -q`
Expected: all pass (the new file now reports 4 passed within the run).

- [ ] **Step 7: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/static/style.css \
        skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs \
        skills/annotate/tests/test_smoke_fold_shortcuts.py
git commit -m "feat(annotate): chevron becomes a 26px round button like the header actions"
```

---

### Task 3: Verify the live server serves the new code

The running server (PID may differ; port 3080, `plugin_root` in `~/.claude/annotate/server.json` = this checkout) reads static files from disk per request with `Cache-Control: no-store` (`skills/_shared/web_companion/static_serve.py:38`), so committed edits are live on the next browser reload of any active session — no restart. This task proves it instead of asserting it.

**Files:** none (verification only).

**Interfaces:**
- Consumes: `.chord-pill` (Task 1), the 26px `.card-chevron` rule (Task 2).
- Produces: nothing — the user-facing "reload your tab" instruction.

- [ ] **Step 1: Confirm the live server is this checkout**

Run: `python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/annotate/server.json")))["plugin_root"])'`
Expected: `~/projects/claude-annotate`. If it's a different path or the file is missing, STOP and report — the live sessions are being served from somewhere else and reloading won't show the change.

- [ ] **Step 2: Fetch the assets from the live port and grep for the new code**

Run:
```bash
curl -s http://127.0.0.1:3080/static/script.js | grep -c "chord-pill"
curl -s http://127.0.0.1:3080/static/style.css | grep -c "chord-pill"
curl -s http://127.0.0.1:3080/static/style.css | grep -A3 "^\.card-chevron {" | grep -c "26px"
```
Expected: every command prints a nonzero count. This is the same bytes-from-disk path a session page load takes, so a reload of `/s/demo-272/` gets exactly this code.

- [ ] **Step 3: Confirm no stale caching header crept in**

Run: `curl -sI http://127.0.0.1:3080/static/script.js | grep -i cache-control`
Expected: `Cache-Control: no-store` — the browser will not reuse a stale copy.

- [ ] **Step 4: Tell the user**

Report: reload the annotate tab (e.g. `/s/demo-272/`), then ⌘K ⌘0 folds all sections, ⌘K ⌘J unfolds, and the chevron is now a full-size round button.
