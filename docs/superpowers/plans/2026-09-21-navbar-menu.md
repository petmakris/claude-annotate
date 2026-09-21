# Navbar Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse annotate's twelve-control page header down to a magnifier, a menu icon carrying the watcher's status colour, and `Done`.

**Architecture:** The menu is new markup plus a thin controller. Every header control that another module owns by `getElementById` is **moved** into the menu's DOM, not reimplemented, so `export.js`, `fullscreen.js`, `highlighter.js` and `wireViewControls` keep working against the same elements. `#menu-pop` joins the existing `initTopPanels` panel array and inherits Esc, click-outside, one-at-a-time and focus restoration for free. Three panes inside the panel (root / settings / help) swap via a `data-pane` attribute.

**Tech Stack:** Vanilla ES modules, no build step. Python 3 stdlib + `unittest`/`pytest` for source-level smoke tests, Playwright + Chromium for browser tests against a live webcompanion daemon.

**Spec:** `docs/superpowers/specs/2026-09-21-navbar-menu-design.md`

## Global Constraints

- **All new CSS goes in `skills/annotate/static/style.css`. Never add rules to `skills/annotate/static/core.css`.** That file is a deliberately diverged copy of `skills/_shared/web_companion/static/core.css` (`skills/deck/static/core.css` is a third copy); its own header block lists the divergences and says not to re-sync. This change only *removes* annotate-only rules from `core.css`.
- **`shell.js` is a line-continued template literal. Every line of the literal must end with a backslash** and no line may introduce a newline or leading whitespace into the string. `test_smoke_shell_source.py` enforces this. Break lines only between tags.
- **Never decode `shell.js` by hand in a test.** Use `from .shell_source import shell_html`. `test_one_decoder_not_eleven` fails any test module that hardcodes the encoding.
- **Commit messages are a single line. No body, no trailers, no attribution.** (User's `CLAUDE.md`.)
- Python 3.9+, standard library only. No new dependencies of any kind.
- Menu panel width is **288px**. Everything in the help pane must fit that measure.
- Run the full suite with `python3 -m pytest skills/annotate/tests -q`. The browser suites skip cleanly if Playwright or the daemon is absent; on this machine both are present, so they must actually run and pass.

---

### Task 1: Delete review progress, both halves

The `0/21` pill and the per-block `✓` are one feature. Annotate is not a progress tracker. This task removes it and inverts its tests into guards so it cannot come back by habit.

**Files:**
- Modify: `skills/annotate/static/shell.js:55` (delete the `#review-progress` button)
- Modify: `skills/annotate/static/script.js:2679-2718` (delete `initReviewProgress`)
- Modify: `skills/annotate/static/style.css:393-414` (delete `.review-progress` rules) and `:415-433` (delete the `✓` rule and its comment)
- Modify: `skills/annotate/tests/test_smoke_review_ergonomics.py:104-134` (replace `TestReviewProgress`)
- Modify: `skills/annotate/tests/test_smoke_shell_source.py:62` (drop `"review-progress"` from the inventory)
- Modify: `skills/annotate/tests/test_browser_review.py:178-186` (delete `test_the_progress_counter_follows_the_marks`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. No later task depends on this one; it is first because it shrinks the surface every later task has to reason about.

- [ ] **Step 1: Write the failing guard test**

Replace the whole `TestReviewProgress` class in `skills/annotate/tests/test_smoke_review_ergonomics.py` (lines 104-134) with:

```python
class TestReviewProgressIsGone(unittest.TestCase):
    """Deleted on purpose, 2026-09-21. Annotate is not a progress tracker, and
    a counter invites completion for its own sake. These are guards, not
    coverage: each one fails if the feature is reintroduced by habit."""

    def test_the_pill_is_not_in_the_shell(self):
        self.assertNotIn("review-progress", SHELL)

    def test_the_pill_has_no_stylesheet_rule_left_behind(self):
        self.assertNotIn(".review-progress", CSS)

    def test_the_counter_machinery_is_gone_from_the_page_code(self):
        self.assertNotIn("initReviewProgress", JS)
        self.assertNotIn("reviewState", JS)

    def test_the_per_block_tick_is_gone(self):
        # The other half of the same feature: a ✓ after the title of a block
        # already dealt with. It read as a score on a page that is not scored.
        self.assertNotIn("data-review-state", CSS)
        self.assertNotIn("data-review-state", JS)
```

Also update the module docstring: the third bullet (`the round dock said what was PENDING and nothing said what was LEFT`) describes a feature that no longer exists. Replace that bullet with:

```
  * (the counter that answered this was removed on 2026-09-21 — see
    TestReviewProgressIsGone below);
```

and delete the clause `the counter went 0/8 → 1/8 → 2/8 as blocks were marked, its click moved the cursor to the first untouched block, and` from the verification paragraph.

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_review_ergonomics.py -q`
Expected: FAIL — four failures, each an `assertNotIn` finding the thing still present.

- [ ] **Step 3: Delete the markup**

In `skills/annotate/static/shell.js`, delete this entire line (line 55):

```
<button id="review-progress" type="button" class="review-progress" hidden aria-label="Review progress">0/0</button>\
```

- [ ] **Step 4: Delete the page code**

In `skills/annotate/static/script.js`, delete the whole block from the comment banner `// ── Review progress ─────` through the closing `})();` of `initReviewProgress` — lines 2667 to 2718 inclusive, ending with the line `  })();` that closes the IIFE and immediately precedes the `// ── Keyboard review (j / k / c / f) ─────` banner.

Do not delete the keyboard-review banner that follows it.

- [ ] **Step 5: Delete the stylesheet rules**

In `skills/annotate/static/style.css`, delete two blocks:

1. The `.review-progress` family — the comment beginning `/* ... button-shaped thing here would compete with Share and Done for the eye.` through `body.read-only .review-progress { pointer-events: none; }`.
2. The per-block tick — the comment beginning `/* The per-block half of the same idea.` through the closing brace of `section.block[data-review-state="touched"] .card-title::after { ... }`.

- [ ] **Step 6: Drop it from the shell inventory**

In `skills/annotate/tests/test_smoke_shell_source.py`, line 62, change:

```python
                        "review-progress", "highlighter-toggle", "highlighter-clear",
```

to:

```python
                        "highlighter-toggle", "highlighter-clear",
```

- [ ] **Step 7: Delete the browser test**

In `skills/annotate/tests/test_browser_review.py`, delete the whole function `test_the_progress_counter_follows_the_marks` (lines 178-186, from the `def` through the final `assert ... == "touched"` line).

- [ ] **Step 8: Run the suite to verify it passes**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS. No test may be skipped that was not skipped before — check the skip count against a run on `main` if anything looks off.

- [ ] **Step 9: Commit**

```bash
git add -A skills/annotate
git commit -m "Delete the review progress counter and the per-block tick"
```

---

### Task 2: Let export.js and fullscreen.js write to a slot instead of the whole button

Both modules overwrite their button's entire contents. As bar buttons that is fine — the button *is* a word or an icon. As menu rows they would wipe the icon or the label. Each takes a one-line change that falls back to today's behaviour when no slot is present, so this task is safe and testable **before** the menu exists.

**Files:**
- Modify: `skills/annotate/static/export.js:317-332`
- Modify: `skills/annotate/static/fullscreen.js:30-36`
- Test: `skills/annotate/tests/test_smoke_menu_slots.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: the contract Task 3's markup relies on — a menu row may carry `<span data-label>` (export) or `<span data-icon>` (fullscreen), and the owning module will write into that span rather than the button. Task 3 puts those spans in the markup.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_menu_slots.py`:

```python
"""The two modules that write THROUGH their button, not to an attribute on it.

`export.js` swaps the button's text for "Preparing…" and back; `fullscreen.js`
swaps its innerHTML between two icons. Both are correct for a button whose
whole content is that one thing, and both destroy a menu row, which is an icon
AND a label. Each learns to prefer a slot, and to fall back to the button
itself when there is none — so this change is invisible to any caller that
never adds a slot.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
EXPORT = (STATIC / "export.js").read_text()
FULLSCREEN = (STATIC / "fullscreen.js").read_text()


class TestExportWritesToItsLabel(unittest.TestCase):
    def test_it_looks_for_a_label_slot(self):
        self.assertIn('querySelector("[data-label]")', EXPORT)

    def test_it_falls_back_to_the_button(self):
        # A caller that never adds a slot must see exactly today's behaviour.
        self.assertIn('querySelector("[data-label]") || btn', EXPORT)

    def test_it_no_longer_writes_the_buttons_whole_text(self):
        self.assertNotIn('btn.textContent = "Preparing', EXPORT)
        self.assertNotIn("const label = btn.textContent", EXPORT)


class TestFullscreenWritesToItsIcon(unittest.TestCase):
    def test_it_looks_for_an_icon_slot(self):
        self.assertIn('querySelector("[data-icon]")', FULLSCREEN)

    def test_it_falls_back_to_the_button(self):
        self.assertIn('querySelector("[data-icon]") || btn', FULLSCREEN)

    def test_it_no_longer_writes_the_buttons_whole_html(self):
        self.assertNotIn("btn.innerHTML =", FULLSCREEN)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_menu_slots.py -q`
Expected: FAIL — six failures, all on strings that do not exist yet.

- [ ] **Step 3: Give export.js a label slot**

In `skills/annotate/static/export.js`, replace the body of `wire()` (lines 317-332) with:

```js
  function wire() {
    const btn = document.getElementById("export-btn");
    if (!btn) return;
    // As a bar button this element's whole content was the word "Share", so
    // writing its textContent was the same as writing its label. As a menu row
    // it is an icon AND a label, and textContent would eat the icon. The slot
    // is optional so a caller that never adds one keeps today's behaviour.
    const label = btn.querySelector("[data-label]") || btn;
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      const original = label.textContent;
      btn.disabled = true;
      label.textContent = "Preparing…";
      try {
        save(await buildDocument());
        label.textContent = "Saved ✓";
      } catch (e) {
        label.textContent = "Failed";
        if (window.console) console.error("export failed", e);
      }
      setTimeout(() => { label.textContent = original; btn.disabled = false; }, 1600);
    });
  }
```

- [ ] **Step 4: Give fullscreen.js an icon slot**

In `skills/annotate/static/fullscreen.js`, replace `sync()` (lines 30-36) with:

```js
  // Same reason as export.js's label slot: this element used to be an icon and
  // nothing else, so innerHTML was its icon. In a menu row it is an icon and a
  // label, and the label must survive the swap.
  const iconSlot = btn.querySelector("[data-icon]") || btn;

  function sync() {
    const on = !!document.fullscreenElement;
    iconSlot.innerHTML = on ? ICON_EXIT : ICON_ENTER;
    btn.title = on ? "Exit full screen" : "Full screen — hide the browser chrome";
    btn.setAttribute("aria-label", btn.title);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }
```

Place the `const iconSlot = ...` line immediately above `function sync()`, after the `ICON_EXIT` declaration.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_menu_slots.py -q`
Expected: PASS, 6 passed.

- [ ] **Step 6: Run the full suite — the fallback must be invisible**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS. Nothing has a slot yet, so every existing test must still pass unchanged. If `test_smoke_export.py` fails, the fallback is wrong.

- [ ] **Step 7: Commit**

```bash
git add -A skills/annotate
git commit -m "Let export and fullscreen write to an optional slot instead of the whole button"
```

---

### Task 3: The menu — markup, controller, and the reduced bar

The centre of the change. Nine controls leave the bar; the elements themselves move into `#menu-pop`.

**Files:**
- Modify: `skills/annotate/static/shell.js` (the whole `<header>` and its popovers)
- Modify: `skills/annotate/static/script.js` (panel array entry + two small controllers)
- Modify: `skills/annotate/static/style.css` (all new rules)
- Modify: `skills/annotate/static/core.css` (deletions only)
- Modify: `skills/annotate/tests/test_smoke_shell_source.py`
- Test: `skills/annotate/tests/test_smoke_menu.py` (create)

**Interfaces:**
- Consumes: the `[data-label]` / `[data-icon]` slot contract from Task 2.
- Produces, for Tasks 4-6:
  - `#menu-toggle` — the bar's menu button. Carries `watcher-live` / `watcher-stale` as a class; Task 4 paints it.
  - `#menu-pop` — the panel. `data-pane` is `"root"`, `"settings"` or `"help"`.
  - `#menu-status` — the status block container at the top of the root pane, holding `.menu-status-dot`, `#menu-status-title`, `#menu-status-sub` and `#menu-resume`. Task 4 fills it.
  - `#legend-pop` — keeps its id and its `.legend-pop` class, and is now the help pane. Task 6 restacks its contents.
  - Any element with `data-pane-to="<name>"` switches the panel to that pane on click.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_menu.py`:

```python
"""The bar is three controls and a mode indicator. Everything else is in the menu.

The bar reached twelve controls twice — see the comment above SETTINGS in
script.js, which describes the first cut, from twelve to nine. These are the
tests that make the second cut stick: an inventory of what the bar may hold,
and a check that every element the behaviour modules look up still exists
somewhere in the shell after being moved into the menu.
"""
import re
import unittest
from pathlib import Path

from .shell_source import shell_html

STATIC = Path(__file__).resolve().parents[1] / "static"
SHELL = shell_html()
CSS = (STATIC / "style.css").read_text()
CORE = (STATIC / "core.css").read_text()
JS = (STATIC / "script.js").read_text()


def header_html():
    """Just the <header>, so 'in the bar' means what it says."""
    m = re.search(r"<header class=\"page-header\">(.*?)</header>", SHELL, re.S)
    assert m, "the shell no longer has a page-header"
    return m.group(1)


def bar_html():
    """The header MINUS the menu panel — what a reader actually sees."""
    h = header_html()
    i = h.index('id="menu-pop"')
    # back up to the opening tag of the panel, forward to its end
    start = h.rindex("<div", 0, i)
    return h[:start] + h[h.index('<button id="done-btn"'):]


class TestTheBarIsThreeControls(unittest.TestCase):
    def test_the_bar_holds_only_what_it_is_allowed_to(self):
        # Deliberately an inventory, not a count: a count passes while one
        # control is swapped for another, which is exactly how a bar grows.
        allowed = {"block-search", "block-search-clear", "highlighter-toggle",
                   "menu-toggle", "done-btn", "hdr-title", "hdr-respid"}
        found = set(re.findall(r'id="([^"]+)"', bar_html()))
        self.assertEqual(found - allowed, set(),
                         "a control came back into the bar")

    def test_the_separators_are_gone(self):
        self.assertNotIn("header-sep", SHELL)

    def test_the_watching_pill_is_gone(self):
        self.assertNotIn("watcher-badge", SHELL)
        self.assertNotIn(".watcher-badge", CORE)


class TestTheHighlighterKeepsItsIndicator(unittest.TestCase):
    """The one escape. The highlighter is a MODE — it changes what dragging
    over text does — and a mode with no indicator is a bug, not a
    simplification. highlighter.js already maintains aria-pressed on it."""

    def test_the_toggle_is_still_in_the_bar(self):
        self.assertIn('id="highlighter-toggle"', bar_html())

    def test_it_is_invisible_unless_armed(self):
        self.assertIn('#highlighter-toggle:not([aria-pressed="true"])', CSS)

    def test_the_eraser_did_not_get_the_same_escape(self):
        # Clearing is a command, not a mode. It lives in the menu.
        self.assertNotIn('id="highlighter-clear"', bar_html())
        self.assertIn('id="highlighter-clear"', SHELL)


class TestTheMovedElementsSurvived(unittest.TestCase):
    """The decision this whole change rests on: the behaviour modules keep
    their elements, so moving one into the menu changes nothing they observe.
    Derived by grepping the modules rather than hand-maintained, so a new
    getElementById in any of them is covered the day it is written."""

    def test_every_id_the_modules_look_up_still_exists(self):
        wanted = set()
        for f in sorted(STATIC.glob("*.js")):
            if f.name.endswith(".min.js"):
                continue
            for m in re.finditer(r'getElementById\("([a-z0-9-]+)"\)', f.read_text()):
                wanted.add(m.group(1))
        # Elements the page BUILDS at runtime rather than shipping in the
        # shell, so they are looked up but never in shell.js. Derived by
        # running this grep against the tree, not guessed: each of the first
        # five is assigned with `el.id = ...` in script.js or subunits.js.
        # `highlighter-palette` is a dead lookup left over from when the
        # palette was re-homed as #palette-pop — guarded, inert, and out of
        # this plan's scope (see ledger Ruling P3).
        runtime = {"attached-pill", "busy-banner", "change-bar", "round-dock",
                   "watcher-dead-banner", "highlighter-palette"}
        missing = sorted(i for i in wanted - runtime
                         if f'id="{i}"' not in SHELL)
        self.assertEqual(missing, [],
                         f"the shell lost ids the page code still reaches for: {missing}")


class TestThePanesAreOnePanel(unittest.TestCase):
    def test_the_panel_declares_a_pane(self):
        self.assertIn('id="menu-pop"', SHELL)
        self.assertIn('data-pane="root"', SHELL)

    def test_settings_and_help_are_panes_of_it(self):
        self.assertIn('data-pane-to="settings"', SHELL)
        self.assertIn('data-pane-to="help"', SHELL)
        self.assertIn('data-pane-to="root"', SHELL)

    def test_the_old_toggles_are_gone(self):
        for dead in ("settings-toggle", "legend-toggle", "resume-toggle"):
            self.assertNotIn(f'id="{dead}"', SHELL, f"#{dead} should be gone")

    def test_the_menu_joins_the_existing_panel_machinery(self):
        # Esc, click-outside, one-at-a-time and aria-expanded all come from
        # initTopPanels. A second implementation of any of them is a bug.
        body = JS[JS.index("function initTopPanels()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn('getElementById("menu-pop")', body)
        self.assertIn("dismissOnOutsideClick: true", body)

    def test_the_menu_reopens_at_the_root(self):
        self.assertIn("initMenuPanes", JS)

    def test_the_panel_is_the_agreed_width(self):
        pop = CSS[CSS.index(".menu-pop {"):]
        pop = pop[:pop.index("}")]
        self.assertIn("288px", pop)
        self.assertIn("overflow-y: auto", pop)


class TestTheHighlighterRowIsAProxy(unittest.TestCase):
    """The one row in the menu that is not the real element, because the real
    element has to stay in the bar. It clicks the bar button and mirrors it,
    so highlighter.js remains the only owner of the state."""

    def test_the_row_exists_and_defers_to_the_button(self):
        self.assertIn('id="menu-highlighter"', SHELL)
        body = JS[JS.index("function initHighlighterMenuRow()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn('getElementById("highlighter-toggle")', body)
        self.assertIn("btn.click()", body)
        self.assertIn("aria-pressed", body)

    def test_it_disappears_with_the_feature(self):
        # highlighter.js hides the toggle when the browser has no Highlight
        # API. A menu row for a feature that cannot run is worse than none.
        body = JS[JS.index("function initHighlighterMenuRow()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn("row.hidden = btn.hidden", body)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_menu.py -q`
Expected: FAIL, with the first error an `AssertionError` from `bar_html()` — `'id="menu-pop"'` is not in the shell yet.

- [ ] **Step 3: Rewrite the header in `shell.js`**

Replace everything in `skills/annotate/static/shell.js` from `<header class="page-header">` up to and including `</header>\` with the markup below. Everything after `</header>` (the `#general-composer` section and `<main class="prose">`) is unchanged.

Keep the existing SVG path data verbatim wherever the old markup had it — the gear, the pencil, the eraser, the expand arrows, the speech bubble, the question mark and the whole legend table are copied across unaltered. Only their position in the tree changes.

```
<header class="page-header"><div class="header-title"><span class="header-emoji">📝</span>\
<span class="header-text" id="hdr-title"></span><span class="header-respid" id="hdr-respid"></span></div>\
<div class="header-actions"><div class="header-search">\
<svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\
<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>\
<input id="block-search" class="search-input" type="text" placeholder="Search blocks…" autocomplete="off" spellcheck="false" aria-label="Search blocks">\
<span class="search-kbd">/</span>\
<button id="block-search-clear" type="button" class="search-clear" aria-label="Clear search" tabindex="-1">&times;</button>\
</div>\
<button id="highlighter-toggle" type="button" class="icon-btn hl-btn" aria-pressed="false" title="Reading highlighter — drag over text to mark it read" aria-label="Reading highlighter">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 4.5l4 4L10 18H6v-4z"/>\
<line x1="4" y1="21" x2="20" y2="21"/></svg></button>\
<span class="icon-btn-wrap">\
<button id="menu-toggle" type="button" class="icon-btn menu-btn" aria-expanded="false" aria-controls="menu-pop" title="Menu" aria-label="Menu">\
<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="4" y1="7" x2="20" y2="7"/>\
<line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg></button>\
<div id="menu-pop" class="menu-pop" data-pane="root" role="dialog" aria-label="Menu" hidden>\
<div class="menu-pane" data-pane-name="root">\
<div class="menu-status" id="menu-status"><span class="menu-status-dot" aria-hidden="true"></span>\
<div class="menu-status-text"><div class="menu-status-title" id="menu-status-title">Checking…</div>\
<div class="menu-status-sub" id="menu-status-sub"></div>\
<div class="menu-resume" id="menu-resume" hidden>\
<p class="resume-hint">Paste this in any terminal to open <code id="resume-cwd"></code> and attach a live session here:</p>\
<div class="resume-cmd-row"><code id="resume-cmd" class="resume-cmd"></code>\
<button id="resume-copy" type="button" class="resume-copy-btn" title="Copy the command">Copy</button></div>\
<p class="resume-status" id="resume-status" aria-live="polite"></p></div>\
<div class="menu-readonly read-only-badge" title="This link can read the document but not change it.">&#128065; Read-only</div>\
</div></div>\
<div class="menu-sec">This response</div>\
<button id="composer-toggle" type="button" class="menu-item" aria-expanded="false" aria-controls="general-composer" title="Comment on the whole response (G)">\
<svg viewBox="0 0 24 24" aria-hidden="true">\
<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>\
</svg><span class="menu-item-label">Comment on the whole response</span><span class="menu-item-hint">G</span></button>\
<button id="menu-highlighter" type="button" class="menu-item" aria-pressed="false">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 4.5l4 4L10 18H6v-4z"/>\
<line x1="4" y1="21" x2="20" y2="21"/></svg>\
<span class="menu-item-label">Reading highlighter</span><span class="menu-item-hint" data-state>off</span></button>\
<button id="highlighter-clear" type="button" class="menu-item" title="Clear every highlight on this page">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.5l7-7 6.5 6.5-4 4H7z"/>\
<line x1="12.5" y1="8" x2="19" y2="14.5"/><line x1="4" y1="21" x2="20" y2="21"/></svg>\
<span class="menu-item-label">Clear every highlight</span></button>\
<div class="menu-sec">View</div>\
<button id="fullscreen-toggle" type="button" class="menu-item" aria-pressed="false" title="Full screen — hide the browser chrome">\
<span class="menu-item-icon" data-icon><svg viewBox="0 0 24 24" aria-hidden="true">\
<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>\
<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg></span>\
<span class="menu-item-label">Full screen</span></button>\
<button type="button" class="menu-item" data-pane-to="settings">\
<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/>\
<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>\
</svg><span class="menu-item-label">Settings</span>\
<svg class="menu-chev" viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg></button>\
<div class="menu-sec">Document</div>\
<button id="export-btn" type="button" class="menu-item" title="Save this document as a single standalone HTML file you can send to anyone">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"/>\
<polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>\
<span class="menu-item-label" data-label>Share a copy…</span></button>\
<button type="button" class="menu-item" data-pane-to="help">\
<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>\
<path d="M9.2 9.3a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.4-2.8 4"/><path d="M12 17.2h.01"/></svg>\
<span class="menu-item-label">Buttons &amp; keyboard</span>\
<svg class="menu-chev" viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg></button>\
</div>\
<div class="menu-pane" data-pane-name="settings">\
<button type="button" class="menu-back" data-pane-to="root">\
<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>\
<span>Settings</span></button>\
<div id="settings-pop" class="settings-pop">\
<div id="settings-groups"></div><div class="set-group" id="set-group-highlight">\
<span class="set-label">Highlight colour</span>\
<div id="palette-pop" class="palette-pop" role="group" aria-label="Highlight colour">\
<button type="button" data-color="yellow" aria-pressed="false" title="Yellow" aria-label="Yellow highlight">\
</button>\
<button type="button" data-color="green" aria-pressed="false" title="Green" aria-label="Green highlight">\
</button>\
<button type="button" data-color="orange" aria-pressed="false" title="Orange" aria-label="Orange highlight">\
</button>\
<button type="button" data-color="blue" aria-pressed="false" title="Blue" aria-label="Blue highlight">\
</button>\
<button type="button" data-color="pink" aria-pressed="false" title="Pink" aria-label="Pink highlight">\
</button></div></div>\
<button id="settings-reset" type="button" class="set-reset" title="Back to defaults. Fonts and reading size are shared with every annotate document.">Reset</button>\
</div></div>\
<div class="menu-pane" data-pane-name="help">\
<button type="button" class="menu-back" data-pane-to="root">\
<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>\
<span>Buttons &amp; keyboard</span></button>\
<div id="legend-pop" class="legend-pop">\
<div class="legend-body">LEGEND_BODY_UNCHANGED</div></div>\
</div></div></span>\
<button id="done-btn" type="button" class="done-btn">Done</button></div></header>\
```

`LEGEND_BODY_UNCHANGED` is a marker for this plan only — **do not type it**. Copy the existing `<table class="legend-table">…</table>`, `<div class="legend-keys">…</div>` and `<p class="legend-note">…</p>` from the current `shell.js` verbatim into that position. Task 6 restacks them; this task only moves them.

Three details that are load-bearing:

- `#settings-pop` keeps its id and class so `test_smoke_settings_panel.py` keeps finding it, but it is no longer `hidden` and no longer a popover — it is the body of a pane. Its CSS changes in Step 5.
- `#legend-pop` likewise keeps its id and `.legend-pop` class, so `test_the_taller_legend_is_clamped` still finds a rule with `max-height` and `overflow-y: auto`.
- The read-only badge moved inside `#menu-status`. It keeps the `read-only-badge` class so `body.read-only` rules still reach it.

- [ ] **Step 4: Add the two controllers to `script.js`**

In `skills/annotate/static/script.js`, inside the `initTopPanels` panel array, delete the `settings-toggle` and `resume-toggle` entries and the `legend-toggle` entry, and add the menu. The array becomes:

```js
    const panels = [
      { btn: document.getElementById("composer-toggle"),
        el: document.getElementById("general-composer"),
        focus: () => document.getElementById("general-input") },
      // One panel where there were four: settings, the legend and the resume
      // command are panes of this one now, not popovers of their own. The
      // pane machinery is initMenuPanes below; everything else about opening
      // and closing — Esc, click-outside, one-at-a-time, aria-expanded — is
      // this function's and is unchanged.
      { btn: document.getElementById("menu-toggle"),
        el: document.getElementById("menu-pop"),
        focus: () => null, dismissOnOutsideClick: true },
    ].filter((p) => p.btn && p.el);
```

Then add both controllers immediately after the closing `})();` of `initTopPanels`:

```js
  // ── Menu panes ───────────────────────────────────────────────────────────
  // Settings and the legend used to be popovers with their own toggles in the
  // bar. They are panes of the one menu now, pushed and popped by a data
  // attribute; the stylesheet shows exactly one pane at a time.
  //
  // The reset-to-root hangs off the panel being HIDDEN rather than off the
  // toggle being clicked, and deliberately: initTopPanels closes this panel
  // from four different places (its own toggle, Esc, a click outside, another
  // panel opening), and only one of them is a click on the button. Watching
  // the attribute catches all four without knowing about any of them.
  (function initMenuPanes() {
    const pop = document.getElementById("menu-pop");
    if (!pop) return;
    pop.querySelectorAll("[data-pane-to]").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.preventDefault();
        pop.dataset.pane = b.dataset.paneTo;
      });
    });
    new MutationObserver(() => {
      if (pop.hidden) pop.dataset.pane = "root";
    }).observe(pop, { attributes: true, attributeFilter: ["hidden"] });
  })();

  // ── The highlighter's menu row ───────────────────────────────────────────
  // The one proxy in the menu, and a proxy precisely because its real element
  // cannot come here: the highlighter is a MODE, so its button stays in the
  // bar as the only indicator that dragging over text now marks it. This row
  // clicks that button and mirrors it, which keeps highlighter.js the single
  // owner of the state — a second copy of "is it on" would be one more thing
  // to keep in step, and this page has been bitten by that before.
  (function initHighlighterMenuRow() {
    const row = document.getElementById("menu-highlighter");
    const btn = document.getElementById("highlighter-toggle");
    if (!row || !btn) return;
    const state = row.querySelector("[data-state]");
    row.addEventListener("click", (e) => { e.preventDefault(); btn.click(); });
    function sync() {
      const on = btn.getAttribute("aria-pressed") === "true";
      row.setAttribute("aria-pressed", on ? "true" : "false");
      if (state) state.textContent = on ? "on" : "off";
      // highlighter.js hides the toggle when the browser has no Highlight
      // API. A menu row for a feature that cannot run is worse than none.
      row.hidden = btn.hidden;
    }
    new MutationObserver(sync).observe(
      btn, { attributes: true, attributeFilter: ["aria-pressed", "hidden"] });
    sync();
  })();
```

- [ ] **Step 5: Add the stylesheet rules to `style.css`**

Append to `skills/annotate/static/style.css`. Also **replace** the existing `.settings-pop { … }` rule block (the positioning half only) as noted below.

```css
/* === The menu ==========================================================
   Nine controls left the bar for this panel. It reuses .icon-btn-wrap for
   anchoring and the initTopPanels machinery for opening and closing, so the
   only genuinely new thing here is the pane switch.

   288px because the help pane's widest line is a shortcut description, and
   because a menu wider than that stops reading as a menu and starts reading
   as a dialog. max-height + scroll for the same reason .settings-pop had
   them: the settings pane holds seven sections and the next preference is a
   row in script.js's SETTINGS spec. */
.menu-pop {
  position: absolute; top: calc(100% + 9px); right: 0; z-index: 60;
  display: flex; flex-direction: column;
  width: 288px; max-height: 78vh; overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 12px 34px rgba(20, 22, 28, .20), 0 2px 6px rgba(20, 22, 28, .08);
  font-size: 12.5px;
}
.menu-pop[hidden] { display: none; }

/* Exactly one pane at a time, chosen by the attribute initMenuPanes writes.
   Panes are siblings rather than a scroller so the panel's height is the
   height of the pane you are on, not of the tallest one. */
.menu-pane { display: none; flex-direction: column; gap: 2px; padding: 6px; }
.menu-pop[data-pane="root"] [data-pane-name="root"],
.menu-pop[data-pane="settings"] [data-pane-name="settings"],
.menu-pop[data-pane="help"] [data-pane-name="help"] { display: flex; }

.menu-sec {
  padding: 9px 9px 4px;
  font-size: 10px; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: var(--text-dim);
}
.menu-item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 7px 9px; border: 0; border-radius: 7px; background: none;
  font-family: inherit; font-size: 12.5px; color: var(--text); text-align: left;
  cursor: pointer;
}
.menu-item:hover { background: var(--hover-tint); }
.menu-item[hidden] { display: none; }
.menu-item > svg, .menu-item-icon svg {
  width: 15px; height: 15px; flex: none;
  fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round;
  color: var(--text-dim);
}
.menu-item-icon { display: inline-flex; flex: none; }
.menu-item-label { flex: 1; }
.menu-item-hint {
  font-family: var(--font-code); font-size: 10.5px; color: var(--text-dim);
}
.menu-chev { margin-left: auto; width: 13px; height: 13px; }
/* A row whose thing is currently ON. The highlighter is the only one today. */
.menu-item[aria-pressed="true"] { color: var(--accent); }
.menu-item[aria-pressed="true"] > svg,
.menu-item[aria-pressed="true"] .menu-item-hint { color: var(--accent); }

.menu-back {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 8px 9px; border: 0; border-bottom: 1px solid var(--border);
  background: none; cursor: pointer;
  font-family: inherit; font-size: 12.5px; font-weight: 600; color: var(--text);
}
.menu-back svg {
  width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; color: var(--text-dim);
}

/* === The status block ==================================================
   What the Watching pill said, with room to say what it means. The dot on
   #menu-toggle is the same fact at a glance; this is the same fact in
   words, plus the resume command when nothing is attached. */
.menu-status { display: flex; gap: 9px; align-items: flex-start; padding: 10px; }
.menu-status-dot {
  width: 8px; height: 8px; border-radius: 50%; margin-top: 4px; flex: none;
  background: var(--text-dim);
}
.menu-status.watcher-live .menu-status-dot { background: var(--status-live-fg); }
.menu-status.watcher-stale .menu-status-dot { background: var(--type-reject-fg); }
.menu-status-text { min-width: 0; }
.menu-status-title { font-weight: 600; font-size: 12.5px; color: var(--text); }
.menu-status-sub {
  font-size: 11.5px; color: var(--text-dim); line-height: 1.5; margin-top: 2px;
}
.menu-resume { margin-top: 8px; }
.menu-resume[hidden] { display: none; }
/* The read-only badge is the only thing in the menu that is not a control:
   it describes what the page IS. Hidden unless the body says so. */
.menu-readonly { display: none; margin-top: 8px; }
body.read-only .menu-readonly { display: inline-flex; }

/* === The menu button ===================================================
   The watcher's colour, absorbed. The button stays a menu button — a tinted
   or filled button reads as "this control is active", which is a different
   claim from "something is watching this page". */
.menu-btn { position: relative; overflow: visible; }
.menu-btn::after {
  content: ""; position: absolute; top: -3px; right: -3px;
  width: 8px; height: 8px; border-radius: 50%;
  border: 2px solid var(--surface-soft);
  background: var(--text-dim);
}
.menu-btn.watcher-live::after { background: var(--status-live-fg); }
.menu-btn.watcher-stale::after { background: var(--type-reject-fg); }

/* === The highlighter's escape ==========================================
   The one control allowed back into the bar, and only while it is armed.
   The highlighter is a MODE: it changes what dragging over text does, and a
   mode whose only indicator is buried in a menu is a mode nobody can see.
   highlighter.js already maintains aria-pressed here, so this rule is the
   entire feature — no JavaScript knows about it. */
#highlighter-toggle:not([aria-pressed="true"]) { display: none; }
```

Then **replace the positioning half of `.settings-pop`** — it is a pane body now, not a popover. Change the existing rule to:

```css
/* Was a popover with its own toggle; it is the settings PANE's body now.
   The panel around it owns the position, the shadow and the scroll, so this
   keeps only what is about the settings themselves. */
.settings-pop {
  display: flex; flex-direction: column; gap: 12px;
  padding: 12px;
}
```

Delete the old `.settings-pop[hidden] { display: none; }` line — the element is never hidden now; its pane is.

- [ ] **Step 6: Delete the dead rules from `core.css`**

In `skills/annotate/static/core.css`, delete:

1. The whole `.watcher-badge` family — the comment beginning `/* Whether a Claude Code session is actually watching this page` through `.watcher-badge--clickable:hover,` / `.watcher-badge--clickable:focus-visible { border-color: currentColor; }`.
2. The `.header-sep { … }` rule.
3. The `.export-btn` family — the comment beginning `/* Share: same shape as Done` through `.export-btn:disabled { cursor: default; }`. Share is a menu row now and takes `.menu-item`.

Do not touch `.icon-btn`, `.icon-btn-wrap`, `.done-btn`, `.page-header`, `.header-title` or `.header-actions`. Add nothing.

Also delete the now-dead `.resume-pop` family from `style.css` (the rule at `.resume-pop {` and its `[hidden]` companion), keeping `.resume-hint`, `.resume-cmd-row`, `.resume-cmd`, `.resume-copy-btn` and `.resume-status`, which the status block still uses.

**And strip `.legend-pop`'s popover geometry now, not in Task 6.** It is a pane body from this task onward, and a pane body carrying `position: absolute` renders detached from the panel. Replace the `.legend-pop { … }` rule with:

```css
/* A pane of the menu now, not a popover of its own. It keeps the clamp it
   grew when the keyboard section took it from ~430px to 621px, measured —
   the menu's own max-height would otherwise let it push the panel past the
   viewport edge on a laptop. */
.legend-pop {
  padding: 10px;
  max-height: 62vh;
  overflow-y: auto;
}
```

Delete `.legend-pop::before` and `.legend-pop[hidden]` with it. Task 6 then only restacks the legend's contents.

- [ ] **Step 7: Update the shell inventory test**

In `skills/annotate/tests/test_smoke_shell_source.py`, the inventory list must drop the three dead toggles and gain the menu. Replace the tuple with:

```python
        for control in ("block-search", "settings-pop",
                        "settings-groups", "settings-reset", "palette-pop",
                        "highlighter-toggle", "highlighter-clear",
                        "fullscreen-toggle", "menu-toggle", "menu-pop",
                        "menu-status", "menu-highlighter",
                        "composer-toggle", "legend-pop",
                        "general-composer", "general-input", "general-send",
                        "export-btn", "done-btn", "hdr-title", "hdr-respid",
                        "resume-cwd", "resume-cmd", "resume-copy"):
```

- [ ] **Step 8: Run the new tests**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_menu.py -q`
Expected: PASS.

- [ ] **Step 9: Run the whole source-level suite**

Run: `python3 -m pytest skills/annotate/tests -q -k "not browser"`
Expected: PASS. `test_smoke_top_panels.py::test_both_panel_toggles_are_rendered` will fail — it asserts `#legend-toggle` is rendered as a bar toggle. Update it to assert the composer toggle and `#menu-toggle` instead, keeping its docstring's intent (both panels have a way in).

- [ ] **Step 10: Commit**

```bash
git add -A skills/annotate
git commit -m "Collapse nine header controls into one anchored menu with panes"
```

---

### Task 4: The watcher dot and the status block

`entry.js` paints a pill that no longer exists. It repoints at the dot and the block, and the resume command comes with it.

**Files:**
- Modify: `skills/annotate/static/entry.js:202-240` (`setupResumeControl`) and `:262-322` (`makeWatcherBadgeClickable`, `paintWatcherHealth`)
- Test: `skills/annotate/tests/test_smoke_watcher_status.py` (create)

**Interfaces:**
- Consumes: `#menu-toggle`, `#menu-status`, `#menu-status-title`, `#menu-status-sub`, `#menu-resume`, `#resume-cwd`, `#resume-cmd`, `#resume-copy`, `#resume-status` from Task 3.
- Produces: `#menu-toggle` carries exactly one of `watcher-live` / `watcher-stale`, or neither before the first poll answers.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_watcher_status.py`:

```python
"""The watcher signal, split in two.

The pill said "Watching" and had room for nothing else — not what watching
means, not how long ago the session was last seen, and not the command that
would attach one. The dot on the menu icon carries the state at a glance; the
status block at the top of the menu carries the sentence, and absorbs the
resume popover, which was the same subject behind a second button.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
ENTRY = (STATIC / "entry.js").read_text()
CSS = (STATIC / "style.css").read_text()


class TestTheBadgeIsGone(unittest.TestCase):
    def test_entry_no_longer_reaches_for_it(self):
        self.assertNotIn("watcher-badge", ENTRY)
        self.assertNotIn("makeWatcherBadgeClickable", ENTRY)


class TestTheDotCarriesTheState(unittest.TestCase):
    def test_it_paints_the_menu_button(self):
        self.assertIn('getElementById("menu-toggle")', ENTRY)
        self.assertIn("watcher-live", ENTRY)
        self.assertIn("watcher-stale", ENTRY)

    def test_the_dot_has_a_rule_for_each_state(self):
        self.assertIn(".menu-btn.watcher-live::after", CSS)
        self.assertIn(".menu-btn.watcher-stale::after", CSS)


class TestTheBlockCarriesTheSentence(unittest.TestCase):
    def test_it_writes_a_title_and_a_subtitle(self):
        self.assertIn('getElementById("menu-status-title")', ENTRY)
        self.assertIn('getElementById("menu-status-sub")', ENTRY)

    def test_the_staleness_threshold_did_not_move(self):
        # 180s is the daemon's own convention and the IntelliJ plugin's
        # REAP_AFTER_MS. This reads a fact everyone already agrees on.
        self.assertIn("WATCHER_STALE_MS = 180_000", ENTRY)


class TestTheResumeCommandCameWithIt(unittest.TestCase):
    def test_the_popover_and_its_toggle_are_gone(self):
        self.assertNotIn("resume-toggle", ENTRY)
        self.assertNotIn(".resume-pop {", CSS)

    def test_the_command_renders_in_the_status_block(self):
        self.assertIn('getElementById("menu-resume")', ENTRY)
        self.assertIn('getElementById("resume-cmd")', ENTRY)

    def test_it_is_shown_only_when_nothing_is_attached(self):
        # An attached session needs no instructions for attaching one.
        self.assertIn("resumeEl.hidden", ENTRY)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_watcher_status.py -q`
Expected: FAIL — `watcher-badge` is still in `entry.js`.

- [ ] **Step 3: Replace the resume control setup**

In `skills/annotate/static/entry.js`, replace the tail of `setupResumeControl` — from `const toggle = document.getElementById("resume-toggle");` through the `makeWatcherBadgeClickable();` call and its comment — with:

```js
      const cwdEl = document.getElementById("resume-cwd");
      const cmdEl = document.getElementById("resume-cmd");
      const copyBtn = document.getElementById("resume-copy");
      const statusEl = document.getElementById("resume-status");
      if (cwdEl && cmdEl) {
        cwdEl.textContent = row.cwd || "the session's project";
        cmdEl.textContent = resumeCommand;
        if (copyBtn) copyBtn.addEventListener("click", () => copyResumeCommand(statusEl));
      }
      // The command just became available and the current paint (from whatever
      // checkWatcherHealth tick already ran) does not know that yet — it is
      // what decides whether the resume row is shown at all.
      paintWatcherHealth(lastSeenAt);
```

- [ ] **Step 4: Delete `makeWatcherBadgeClickable` and rewrite `paintWatcherHealth`**

Delete the entire `makeWatcherBadgeClickable` function, its `let watcherBadgeClickable = false;` line and the comment block above them. Click-to-copy on the badge existed because the command was otherwise hidden behind a second button; it is on screen now.

Replace `paintWatcherHealth` with:

```js
  // The last value /poll reported, so setupResumeControl can re-paint when the
  // command arrives without waiting up to 15s for the next tick.
  let lastSeenAt = null;

  function paintWatcherHealth(seenAt) {
    lastSeenAt = seenAt;
    const btn = document.getElementById("menu-toggle");
    const block = document.getElementById("menu-status");
    const title = document.getElementById("menu-status-title");
    const sub = document.getElementById("menu-status-sub");
    const resumeEl = document.getElementById("menu-resume");
    if (!btn || !title || !sub) return;

    const live = seenAt != null && (Date.now() - seenAt * 1000) <= WATCHER_STALE_MS;
    const cls = live ? "watcher-live" : "watcher-stale";
    btn.classList.remove("watcher-live", "watcher-stale");
    btn.classList.add(cls);
    if (block) {
      block.classList.remove("watcher-live", "watcher-stale");
      block.classList.add(cls);
    }

    if (live) {
      title.textContent = "Watching";
      sub.textContent = "A live Claude Code session is watching this page and "
        + "will answer comments here.";
    } else if (seenAt == null) {
      title.textContent = "Unwatched";
      sub.textContent = "No Claude Code session has watched this page yet — "
        + "a comment will queue, but nothing will answer it.";
    } else {
      const mins = Math.round((Date.now() - seenAt * 1000) / 60000);
      title.textContent = "Unwatched";
      sub.textContent = "The session that answers comments here has been "
        + "silent for " + mins + " min.";
    }

    // Only when nothing is attached, and only once the command is known: an
    // attached session needs no instructions for attaching one, and a
    // read-only viewer could not run the command anyway.
    if (resumeEl) resumeEl.hidden = live || !resumeCommand;
    // The button says what it is for at a glance, in a tooltip, without
    // opening the menu.
    btn.title = live ? "Menu — a session is watching this page"
                     : "Menu — nothing is watching this page";
  }
```

Leave `checkWatcherHealth` and its `setInterval` exactly as they are.

- [ ] **Step 5: Close the pending exception Task 3 left behind**

Task 3's `test_every_id_the_modules_look_up_still_exists` carries a `pending`
set holding `watcher-badge` and `resume-toggle`: `entry.js` still named them
after Task 3 deleted them from the shell, and this task is what removes the
last references. Delete that set from `skills/annotate/tests/test_smoke_menu.py`
now, along with its comment, and fold it out of the `missing` comprehension so
the assertion is back to `wanted - runtime`.

Run: `python3 -m pytest skills/annotate/tests/test_smoke_menu.py -q`
Expected: PASS. A failure here naming either id means `entry.js` still
references it — fix `entry.js`, never the allowlist.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_watcher_status.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole source-level suite**

Run: `python3 -m pytest skills/annotate/tests -q -k "not browser"`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A skills/annotate
git commit -m "Move the watcher signal onto the menu icon and its status block"
```

---

### Task 5: Search collapses to a magnifier and takes the bar on focus

No change to `search.js`'s filtering, its index, its `/` shortcut or its Esc handling. The input stays in the DOM at all times — collapsing it with CSS rather than removing it is what keeps every one of those working untouched.

**Files:**
- Modify: `skills/annotate/static/search.js:133-175` (add takeover sync inside `init`)
- Modify: `skills/annotate/static/style.css:899-975` (the `.header-search` family)
- Test: `skills/annotate/tests/test_smoke_search_takeover.py` (create)

**Interfaces:**
- Consumes: `#block-search` and `.header-search` from Task 3's markup (unchanged from today).
- Produces: `.page-header` carries `data-searching="1"` while the field is focused or holds a query.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_search_takeover.py`:

```python
"""A magnifier that becomes the whole bar, and a filter that did not change.

The field is never removed from the DOM — it is collapsed to the width of its
own icon. That is the entire reason search.js needed four lines rather than a
rewrite: the index, the `/` shortcut, the Esc handler and the mutation
observer all still have the element they were written against.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "search.js").read_text()
CSS = (STATIC / "style.css").read_text()


class TestTheBarKnowsItIsSearching(unittest.TestCase):
    def test_focus_and_a_live_query_both_count(self):
        self.assertIn("syncTakeover", JS)
        self.assertIn("document.activeElement === input", JS)
        self.assertIn("input.value.trim().length", JS)

    def test_it_writes_the_attribute_the_stylesheet_reads(self):
        self.assertIn('dataset.searching', JS)
        self.assertIn('.page-header[data-searching="1"]', CSS)


class TestTheFieldCollapses(unittest.TestCase):
    def test_the_resting_width_is_one_icon(self):
        rule = CSS[CSS.index(".header-search {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("26px", rule)

    def test_it_takes_the_whole_bar_when_searching(self):
        self.assertIn('.page-header[data-searching="1"] .header-search', CSS)
        self.assertIn('.page-header[data-searching="1"] .header-title', CSS)


class TestTheFilterWasNotTouched(unittest.TestCase):
    """Four lines were added to init(). Nothing else in this file moved."""

    def test_the_slash_shortcut_still_exists(self):
        self.assertIn('e.key === "/" && !inField', JS)

    def test_escape_still_clears_and_blurs(self):
        self.assertIn('e.key === "Escape" && active === input', JS)
        self.assertIn("input.blur()", JS)

    def test_there_is_still_exactly_one_result_count(self):
        # search.js already renders "Showing N of M blocks" into main.prose.
        # A second count in the bar would be two answers to one question.
        self.assertIn('"Showing " + matched.size + " of "', JS)
        self.assertNotIn("search-count-bar", CSS)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_search_takeover.py -q`
Expected: FAIL — `syncTakeover` does not exist.

- [ ] **Step 3: Add the takeover sync to `search.js`**

In `init()`, immediately after the `refresh` function's closing brace, add:

```js
    // The bar's two states. The field is never removed from the DOM — the
    // index, the `/` shortcut, the Esc handler and the mutation observer are
    // all written against this element — so "collapsed" is a width in the
    // stylesheet and this attribute is the only thing that changes.
    //
    // A live query keeps the bar taken over even after the field loses focus:
    // the document underneath is filtered, and collapsing the field would hide
    // the reason it looks short.
    const hdr = input.closest(".page-header");
    function syncTakeover() {
      const on = document.activeElement === input
        || input.value.trim().length > 0;
      if (hdr) hdr.dataset.searching = on ? "1" : "0";
    }
    input.addEventListener("focus", syncTakeover);
    input.addEventListener("blur", syncTakeover);
```

Then add `syncTakeover();` as the last line inside `refresh()`, after the `has-query` toggle, so typing and clearing both re-evaluate it.

- [ ] **Step 4: Rewrite the search rules in `style.css`**

Replace the `.header-search` rule and add the takeover rules. The rest of the `=== Block search ===` section (`.search-icon`, `.search-input`, `.search-kbd`, `.search-clear`, `.search-hidden`) is unchanged except for the two additions marked below.

```css
.header-search {
  position: relative;
  /* One icon wide at rest. The input is still here and still focusable —
     clicking it is what opens the bar — but it shows nothing but its own
     magnifier until it does. */
  width: 26px;
  transition: width 160ms ease;
}
```

Add immediately after the existing `.search-input:focus` rule:

```css
/* Collapsed, the field is a button: no placeholder to read at 26px, and a
   pointer that says "this opens something". */
.header-search .search-input { cursor: pointer; }
.page-header[data-searching="1"] .search-input { cursor: text; }
.page-header:not([data-searching="1"]) .search-input::placeholder {
  color: transparent;
}
```

And append to the section:

```css
/* === The takeover ======================================================
   Focused, the field is the bar. The title steps aside rather than shrinking
   — a truncated title beside a search box is worse than no title, and the
   title is still one Esc away. Everything else in the actions goes with it,
   including Done: nothing in the bar is worth clicking while you are typing
   a filter, and the row must not reflow as the field grows. */
.page-header[data-searching="1"] .header-title { display: none; }
.page-header[data-searching="1"] .header-actions { flex: 1; }
.page-header[data-searching="1"] .header-search { width: 100%; }
.page-header[data-searching="1"] .header-actions > *:not(.header-search) {
  display: none;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_search_takeover.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole source-level suite**

Run: `python3 -m pytest skills/annotate/tests -q -k "not browser"`
Expected: PASS. `test_smoke_block_search.py` must pass untouched — if it does not, `search.js` was changed more than it should have been.

- [ ] **Step 7: Commit**

```bash
git add -A skills/annotate
git commit -m "Collapse the search field to a magnifier that takes the bar when focused"
```

---

### Task 6: Restack the help pane for 288px

The legend is a 3-column table. Three columns do not fit 288px. Same content, stacked.

**Files:**
- Modify: `skills/annotate/static/shell.js` (the legend body inside `#legend-pop`)
- Modify: `skills/annotate/static/style.css:1476-1560` (the `.legend-*` family)
- Modify: `skills/annotate/tests/test_smoke_review_ergonomics.py:88-102`

**Interfaces:**
- Consumes: `#legend-pop` as the help pane from Task 3.
- Produces: nothing later depends on this.

- [ ] **Step 1: Write the failing test**

In `skills/annotate/tests/test_smoke_review_ergonomics.py`, replace `test_the_taller_legend_is_clamped` with:

```python
    def test_the_legend_fits_the_menu_measure(self):
        # It was a 3-column table in a popover as wide as it liked. It is a
        # pane of a 288px menu now, and three columns do not fit that.
        self.assertNotIn("legend-table", SHELL,
                         "the legend is still a table")
        self.assertIn("legend-entry", SHELL)
        for cls in ("legend-entry-name", "legend-entry-tells",
                    "legend-entry-does"):
            self.assertIn(cls, CSS, f".{cls} has no rule")

    def test_the_legend_still_scrolls_rather_than_overflowing(self):
        pop = CSS[CSS.index(".legend-pop {"):]
        pop = pop[:pop.index("}")]
        self.assertIn("max-height", pop)
        self.assertIn("overflow-y: auto", pop)
```

`test_the_keys_are_documented_where_the_buttons_are` is unchanged and must keep passing — the keyboard table stays a 2-column table and fits.

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_review_ergonomics.py -q`
Expected: FAIL — `legend-table` is still in the shell.

- [ ] **Step 3: Restack the legend in `shell.js`**

Replace the `<table class="legend-table">…</table>` inside `#legend-pop` with four entries of this shape. The four SVG icons and all four pairs of strings are copied verbatim from the table being replaced — trash, leave-as-written, comment, compact, in that order.

```
<div class="legend-entry"><div class="legend-entry-name">\
<svg class="legend-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/>\
<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>\
<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg><span>Trash</span></div>\
<p class="legend-entry-tells">&ldquo;This is irrelevant &mdash; cut it&rdquo;</p>\
<p class="legend-entry-does">Removed from the document for good, and Claude is told never to bring it back</p></div>\
```

Repeat for the other three, keeping each one's icon, name, "what it tells Claude" string and "what happens to the content" string exactly as the table had them. The `<thead>` row is dropped — a stacked entry does not need column headers, and `.legend-entry-tells` / `.legend-entry-does` carry the distinction in the stylesheet instead.

Leave `<div class="legend-keys">…</div>` and `<p class="legend-note">…</p>` exactly as they are.

- [ ] **Step 4: Restyle the legend in `style.css`**

Delete the `.legend-table` rules. `.legend-pop` itself was already reduced to a pane body in Task 3 (padding, `max-height`, `overflow-y`) — leave that rule alone. Then add:

```css
.legend-entry { padding: 9px 0; border-bottom: 1px solid var(--border); }
.legend-entry:last-of-type { border-bottom: 0; }
.legend-entry-name {
  display: flex; align-items: center; gap: 7px;
  font-size: 12.5px; font-weight: 600; color: var(--text);
}
.legend-entry-name .legend-icon {
  width: 14px; height: 14px; flex: none;
  fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; color: var(--text-dim);
}
/* What it tells Claude, in Claude's voice — quoted in the copy, so it is set
   as speech. What happens to the content is the consequence, set quieter. */
.legend-entry-tells {
  margin: 5px 0 0; font-size: 12px; color: var(--text); font-style: italic;
}
.legend-entry-does {
  margin: 3px 0 0; font-size: 11.5px; color: var(--text-dim); line-height: 1.5;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_review_ergonomics.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole source-level suite**

Run: `python3 -m pytest skills/annotate/tests -q -k "not browser"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A skills/annotate
git commit -m "Restack the button legend so it fits the menu's measure"
```

---

### Task 7: Prove it in a browser, and measure it

Three CSS defects in this page's history passed every source-level test and were caught only by computed styles and rects. Nothing in Tasks 3-6 is finished until a real browser agrees.

**Files:**
- Modify: `skills/annotate/tests/test_browser_review.py` (repoint the settings test, add four)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Repoint the settings browser test**

In `skills/annotate/tests/test_browser_review.py`, replace `test_the_settings_panel_paints_and_persists`'s first two lines:

```python
    page.click("#settings-toggle")
    page.wait_for_selector("#settings-pop:not([hidden])")
```

with:

```python
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'",
        timeout=3000)
```

The rest of the test — clicking a font, clicking a size, asserting the computed `fontFamily` reached the prose — is unchanged.

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_browser_review.py -q`
Expected: FAIL before Tasks 3-6 are in; PASS once they are. If you are running this task after them, expect PASS and move on.

- [ ] **Step 3: Write the four new browser tests**

Append to `skills/annotate/tests/test_browser_review.py`:

```python
def test_the_menu_pushes_a_pane_and_comes_back(page):
    """The one genuinely new interaction. Everything else in the menu is an
    element that moved, and the module that owns it never noticed."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    assert page.eval_on_selector(
        "#menu-pop", "el => el.dataset.pane") == "root"

    page.click('[data-pane-to="help"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'help'")
    # Exactly one pane visible — the rule is a display swap, and a swap that
    # shows two is a panel twice as tall as it should be.
    assert page.eval_on_selector_all(
        ".menu-pane", "els => els.filter(e => e.offsetParent !== null).length") == 1

    page.click('.menu-pane[data-pane-name="help"] [data-pane-to="root"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'root'")

    # Closing and reopening must land on root, however it was closed.
    page.click('[data-pane-to="settings"]')
    page.keyboard.press("Escape")
    page.wait_for_selector("#menu-pop[hidden]")
    page.click("#menu-toggle")
    assert page.eval_on_selector("#menu-pop", "el => el.dataset.pane") == "root", \
        "the menu remembered where you were last time"


def test_the_bar_is_three_controls_wide(page):
    """Measured, not asserted from source: a rule that does not match paints
    nothing, and a source test cannot tell the difference."""
    visible = page.eval_on_selector_all(
        ".header-actions > *",
        "els => els.filter(e => e.offsetParent !== null)"
        ".map(e => e.id || e.className)")
    # The search wrapper, the menu's icon-btn-wrap, and Done. The highlighter
    # is not armed, so it must not be painting.
    assert len(visible) == 3, f"the bar is painting {len(visible)} controls: {visible}"
    assert page.eval_on_selector(
        "#highlighter-toggle", "el => el.offsetParent === null"), \
        "the highlighter is visible while disarmed"


def test_arming_the_highlighter_brings_its_button_back(page):
    """A mode with no indicator is a bug. This is the whole escape clause."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click("#menu-highlighter")
    page.wait_for_function(
        "() => document.getElementById('highlighter-toggle')"
        ".getAttribute('aria-pressed') === 'true'", timeout=3000)
    assert page.eval_on_selector(
        "#highlighter-toggle", "el => el.offsetParent !== null"), \
        "the highlighter is armed and its button is still invisible"

    # And the proxy mirrors it rather than keeping a second copy of the truth.
    assert page.eval_on_selector(
        "#menu-highlighter", "el => el.getAttribute('aria-pressed')") == "true"


def test_the_two_slot_writers_land_in_their_slots(page):
    """Task 2 taught export.js and fullscreen.js to write to a slot instead of
    over the whole button, because a menu row is an icon AND a label. Nothing
    proved that at runtime — both modules are covered only by source-string
    assertions, and a wrong selector would silently eat one or the other.
    fullscreen.js's sync() runs at init, so its slot is already exercised by
    the time this page is ready."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")

    # Full screen: the icon went INTO the slot, and the label survived it.
    assert page.eval_on_selector(
        "#fullscreen-toggle", "el => !!el.querySelector('[data-icon] svg')"), \
        "fullscreen.js wrote its icon somewhere other than the slot"
    assert "Full screen" in page.text_content("#fullscreen-toggle"), \
        "fullscreen.js's icon write ate the row's label"

    # Share: click it and watch the LABEL change, not the whole row. The click
    # really does build and download the document, so the download is accepted
    # and discarded — expect_download also keeps the click from hanging.
    with page.expect_download() as dl:
        page.click("#export-btn")
    dl.value
    page.wait_for_function(
        "() => document.querySelector('#export-btn [data-label]')"
        ".textContent.trim() === 'Saved ✓'", timeout=10000)
    assert page.eval_on_selector(
        "#export-btn", "el => !!el.querySelector('svg')"), \
        "export.js's status write ate the row's icon"


def test_search_takes_the_bar_and_gives_it_back(page):
    page.click("#block-search")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching === '1'")
    title_hidden = page.eval_on_selector(
        ".header-title", "el => el.offsetParent === null")
    assert title_hidden, "the title did not step aside"

    # The field must actually be wide — a takeover that leaves it at 26px is
    # the defect this test exists for.
    width = page.eval_on_selector(
        ".header-search", "el => el.getBoundingClientRect().width")
    assert width > 400, f"the field took the bar and stayed narrow: {width}px"

    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching !== '1'")
    assert page.eval_on_selector(
        ".header-title", "el => el.offsetParent !== null"), \
        "the title did not come back"
```

- [ ] **Step 4: Run the browser suite**

Run: `python3 -m pytest skills/annotate/tests/test_browser_review.py -q`
Expected: PASS, no skips. A skip here means the daemon is not answering — fix that before claiming the task is done; a skipped browser suite is the failure mode this task exists to prevent.

- [ ] **Step 5: Run everything**

Run: `python3 -m pytest skills/annotate/tests -q`
Expected: PASS.

- [ ] **Step 6: Look at it**

Push a real document and open it. Confirm by eye, at 1512px and again at 900px: the bar reads as three controls; the dot is green against a live session; the menu opens under the icon and does not overhang the viewport; the settings pane's controls still change the page; the search takeover does not reflow the row as it grows.

This step has no assertion because its job is to catch what no assertion was written for.

- [ ] **Step 7: Commit**

```bash
git add -A skills/annotate
git commit -m "Drive the menu, the highlighter escape and the search takeover in a browser"
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the reduced bar and the highlighter escape (Task 3), decisions 1-3 on element ownership and panes (Tasks 2-3), decisions 4-6 on the watcher and the status block (Task 4), decision 7 on review progress (Task 1), decision 8 on where CSS goes (Global Constraints, enforced by Task 3 Step 6), decision 9 on search (Task 5), the menu contents table (Task 3), the two write-through modules (Task 2), the deletions table (Tasks 1, 3, 4), and the test list (every task, plus Task 7).

**One spec correction, made here rather than silently.** The spec's decision 9 says the takeover "shows a live match count while open". `search.js:121` already renders `Showing N of M blocks` into `main.prose`. A second count would be two answers to one question, so the plan drops it and `test_smoke_search_takeover.py` guards against one being added. The spec should be amended to match.

**One spec simplification.** The spec says the help legend becomes a stacked list; it did not say the keyboard table stays a table. It does — it is 2 columns and fits.
