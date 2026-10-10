# Annotate without sections: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The annotate page reads as one document, so the reader never sees a section, a card, a section number or a version pill.

**Architecture:** Blocks stay the unit that Claude writes and rewrites, and that comments and marks point at. Only the page changes:
- A block renders as plain flow, with its authored title as an `h2`.
- Pictures and questions sit in a light frame.
- Folding goes by heading.
- A comment opens in one floating window that the reader can move and resize.
- A selection may cross a heading. That adds `spans` to the round.

Three small pure modules (`fold-groups.js`, `window-place.js`, `spans.js`) carry the logic that can be executed under node. Everything else is DOM and CSS, guarded by the repo's source-string smoke tests and checked in a live browser.

**Tech Stack:** Plain browser JavaScript (no build), CSS, and pytest with node-run `.cjs` suites, run through `uv`.

**Spec:** `skills/annotate/docs/no-sections-design.md`

## Global Constraints

- Run the suite with `uv run -q --with-requirements requirements-test.txt python -m pytest skills -q` from the repo root. Every task ends green.
- No browser tests, and no test starts a daemon. Pure logic goes into a UMD module tested by a `.cjs` suite plus a pytest runner, the way `block-title.js` is tested.
- These class names must not appear in `skills/annotate/static/` once Task 2 is done: `card-head`, `card-title`, `card-chevron`, `section-pill`, `card-body`, `block card`. The comment-card parts (`card-submit-row`, `card-submit-btn`, `card-step-*`, `card-diff-toggle`) stay.
- Text the reader sees never says "section" or "block". It says "part", as in "1 part changed".
- Every commit message is a single line. Stage by path, never `-A`. Commit only when the maintainer has said to commit.
- Every UI task ends with a check in a live browser on a real workspace, through `mcp__playwright-headless__*`. Quote `getComputedStyle` and `getBoundingClientRect` values. A workspace URL comes from `python3 -m skills.annotate.session lookup --cwd <repo>`. Point the browser at the `@devdomains url` form of the daemon, never at `localhost`.
- When a test guards a fix, paste two runs: one failing with the fix removed, and one passing with the fix restored. Set `PYTHONDONTWRITEBYTECODE=1` while planting.

## Review Focus

1. **A page where no block has a title.** It shows no fold buttons, Fold all is hidden, and nothing is stuck folded from an older visit. The test belongs to Task 4.
2. **A comment window open while Claude rewrites or removes the commented words.** The reader's words are never lost. Save turns them into a comment on the whole part, quoting the old text, or sends them to the general box when the part is gone. The test belongs to Task 6.
3. **A window narrower than 600 px.** The comment window opens below or above the selection, full width less 16 px each side, and still moves. The test belongs to Task 6.
4. **A selection that runs over a diagram or a question between two paragraphs.** The picture's part is left out, and the comment covers the text on either side. The test belongs to Task 7.
5. **The browser window shrinks while the comment window is near its edge.** The window is pulled back fully on screen. The test belongs to Task 6.

---

### Task 1: The visible title is only an authored one

**Files:**
- Modify: `skills/annotate/static/block-title.js`
- Test: `skills/annotate/tests/block_title.test.cjs`

**Interfaces:**
- Produces: `AnnotateBlockTitle.visibleTitle(blk) -> string` returns `""` when nothing was authored. `blockTitle(blk)` is unchanged except for its last fallback, which becomes `"Text"`.

- [ ] **Step 1: Write the failing tests.** In `block_title.test.cjs`:
  - Change the require line to `const { blockTitle, visibleTitle } = require(...)`.
  - Change line 84's expectation from `"Section"` to `"Text"`.
  - Add this test before the summary line:

```js
test("only an authored name is shown as a heading", () => {
  eq(visibleTitle({ kind: "markdown", title: "Where it runs", markdown: "x" }), "Where it runs");
  eq(visibleTitle({ kind: "markdown", markdown: "## Heading in the text\n\nbody" }), "");
  eq(visibleTitle({ kind: "markdown", markdown: "" }), "");
  eq(visibleTitle({ kind: "flowchart", spec: { title: "Outbound" } }), "Outbound");
  eq(visibleTitle({ kind: "sequence", spec: {} }), "");
  eq(visibleTitle({ kind: "choice", spec: { question: "One story or two" } }), "One story or two");
  eq(visibleTitle({ kind: "mockup" }), "");
  eq(visibleTitle(null), "");
});
```

- [ ] **Step 2: Run it and see it fail.**
  Run: `node skills/annotate/tests/block_title.test.cjs`
  Expected: FAIL. `visibleTitle is not a function`, and line 84 expects `"Text"` but gets `"Section"`.

- [ ] **Step 3: Implement.** In `block-title.js`:
  - Replace `return t || "Section";` with `return t || "Text";`.
  - Add this function after `blockTitle`:

```js
  // What the reader sees as a heading: only a name someone authored, either
  // the block's title or a picture's or question's own. A derived name (the
  // first line of the text, a kind's fallback) labels the part for screen
  // readers and the round dock and is never painted, or the first line of
  // a paragraph would show twice.
  function visibleTitle(blk) {
    blk = blk || {};
    const own = clean(blk.title);
    if (own) return own;
    const rule = SPEC_TITLED[blk.kind || "markdown"];
    if (!rule) return "";
    const spec = blk.spec || {};
    for (const key of rule.keys) {
      const t = clean(spec[key]);
      if (t) return t;
    }
    return "";
  }
```

  - Change the export to `return { blockTitle, visibleTitle, MAX_LEN };`.
  - Update the header comment: point 4's fallback list now reads `"Diagram", "Decision", "Text"`.

- [ ] **Step 4: Run it and see it pass.**
  Run: `node skills/annotate/tests/block_title.test.cjs && uv run -q --with-requirements requirements-test.txt python -m pytest skills/annotate/tests/test_block_title.py -q`
  Expected: `N/N passed`, and pytest passes.

- [ ] **Step 5: Commit.**
  `git add skills/annotate/static/block-title.js skills/annotate/tests/block_title.test.cjs && git commit -m "annotate: a part's visible title is only an authored one"`

---

### Task 2: A block renders as part of one document

**Files:**
- Modify: `skills/annotate/static/script-blocks.js` (`createBlockSection` 273–382, `setupCollapse`, `applyCollapsed`, `renderVersionBadge` 412–434)
- Modify: `skills/annotate/static/script.js` (`blockTitle` 479, `setCardTitle` 484, `renderChoice` 506–513)
- Modify: `skills/annotate/static/script-reconcile.js` (310–321)
- Modify: `skills/annotate/static/anchors.js` (21), `selection.js` (60–75, 160–164, 278–290, 343–347), `script-cards.js` (291–295), `edit.js` (355–362, 759–766, 950–952, 1345), `maximize.js` (126–131, 167–174, 266–288), `script-changes.js` (135–166, 299, 313–316), `subunits.js` (393–399, 610), `export.js` (STRIP, EXPORT_CSS), `script-chrome.js` (`foldAll` 480–488, key `f` 429–438)
- Modify: `skills/annotate/static/style.css` (253–294, 336–347, 486–560, 628–690), `style-code.css`, `style-edit.css`, `style-maximize.css`, `style-selection.css`
- Test: create `skills/annotate/tests/test_smoke_document_blocks.py`. Modify `test_smoke_code_panes.py`, `test_smoke_empty_draft.py`, `test_smoke_maximize.py`, `test_smoke_fold_shortcuts.py` and `test_smoke_round_drawer.py`.

**Interfaces:**
- Consumes: `AnnotateBlockTitle.visibleTitle` (Task 1).
- Produces:
  - `blockLabel(blk) -> HTMLElement`. With a title it is `h2.block-label.block-heading#block-label-<id>`, holding `button.fold-btn` and `span.block-heading-text`. Without one it is `div.block-label.block-meta#block-label-<id>`.
  - `setBlockLabel(section, blk)`, which replaces the label in place.
  - `focusHome(section)`, which moves focus to the fold button or, failing that, to the section (`tabIndex = -1`).
  - Body wrapper `div.block-body`.
  - `section.aria-label = blockTitle(blk)`.
  - The section class is `block` (no `card`).

- [ ] **Step 1: Write the failing guard.** Create `skills/annotate/tests/test_smoke_document_blocks.py`:

```python
"""The page reads as one document: no card, no section number, no chevron.

A block is still the unit Claude rewrites and a comment points at; the reader
just never sees it. These names were the card's, and none may come back.
"""
import re
from pathlib import Path

from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

STATIC = Path(__file__).resolve().parents[1] / "static"
GONE = ("card-head", "card-title", "card-chevron", "section-pill", "card-body", "block card")


def _all_static_text():
    for p in sorted(STATIC.glob("*.js")) + sorted(STATIC.glob("*.css")):
        if p.name.endswith(".min.js"):
            continue
        yield p.name, p.read_text()


def test_no_static_file_names_the_card():
    found = [(name, word) for name, text in _all_static_text() for word in GONE if word in text]
    assert found == [], f"the card is still named in: {found}"


def test_a_block_is_built_without_a_box():
    src = SCRIPT_JS.read_text()
    i = src.index("function createBlockSection(")
    body = src[i:src.index("\n}", i)]
    assert 'section.className = "block";' in body
    assert "blockLabel(blk)" in body
    assert 'body.className = "block-body"' in body
    assert "renderVersionBadge" not in src


def test_a_heading_is_only_an_authored_title():
    src = SCRIPT_JS.read_text()
    i = src.index("function blockLabel(")
    body = src[i:src.index("\n}", i)]
    assert "visibleTitle(blk)" in body
    assert '"h2"' in body


def test_the_page_ground_is_the_text_surface():
    css = STYLE_CSS.read_text()
    assert re.search(r"body\s*\{[^}]*background:\s*var\(--surface\)", css), \
        "the page still sits on the grey card ground"
```

- [ ] **Step 2: Run it and see it fail.**
  Run: `uv run -q --with-requirements requirements-test.txt python -m pytest skills/annotate/tests/test_smoke_document_blocks.py -q`
  Expected: 4 failed. The first lists every file that still names the card.

- [ ] **Step 3: Build the block without a card.** In `script-blocks.js`, replace the start of `createBlockSection` up to `const body = ...` with:

```js
function createBlockSection(blk) {
  const section = document.createElement("section");
  section.className = "block";
  section.dataset.blockId = blk.id;
  section.dataset.version = String(blk.version ?? 1);
  const kind = blk.kind || "markdown";
  section.dataset.kind = kind;
  // The reader's own words in this block (edit.js paints them).
  section._mine = Array.isArray(blk.mine) ? blk.mine : [];
  // A part of one document: no box and no header bar. Its name for screen
  // readers and the round dock is the derived title; what shows is only an
  // authored one (blockLabel). Focus comes back here when a comment or the
  // editor closes, so the section itself can take it.
  section.setAttribute("aria-label", blockTitle(blk));
  section.tabIndex = -1;
  section.appendChild(blockLabel(blk));

  const body = document.createElement("div");
  body.className = "block-body";
```

  Leave the content branches as they are. Replace the tail of the function, from `section.appendChild(body);` to the end, with:

```js
  section.appendChild(body);
  return section;
}

// The part's visible name. An authored title is an h2 with the fold button
// before it. A part without one gets an empty line instead, which shows only
// when a mark or a change chip needs a place to sit.
function blockLabel(blk) {
  const title = visibleTitle(blk);
  const el = document.createElement(title ? "h2" : "div");
  el.className = title ? "block-label block-heading" : "block-label block-meta";
  el.id = `block-label-${blk.id}`;
  if (!title) return el;
  const fold = document.createElement("button");
  fold.type = "button";
  fold.className = "fold-btn";
  fold.textContent = "▾";
  fold.setAttribute("aria-label", "Fold");
  fold.setAttribute("aria-expanded", "true");
  fold.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const section = el.closest("section.block");
    setFolded(blk.id, !section.classList.contains("collapsed"));
  });
  const text = document.createElement("span");
  text.className = "block-heading-text";
  text.textContent = title;
  el.append(fold, text);
  return el;
}

function setBlockLabel(section, blk) {
  const fresh = blockLabel(blk);
  const old = section.querySelector(".block-label");
  if (old) old.replaceWith(fresh);
  else section.prepend(fresh);
  section.setAttribute("aria-label", blockTitle(blk));
}

function focusHome(section) {
  if (!section || !document.contains(section)) return;
  (section.querySelector(".fold-btn") || section).focus({ preventScroll: true });
}

function visibleTitle(blk) {
  return window.AnnotateBlockTitle.visibleTitle(blk);
}
```

  Replace `collapseKey`, `setupCollapse`, `applyCollapsed` and `renderVersionBadge` (384–434) with the following. Task 4 replaces `applyFolds` with the grouped version.

```js
function collapseKey(blockId) {
  const rid = (document.body.dataset.responseId || "default");
  return `annotate.collapsed:${rid}:${blockId}`;
}

function readFolded(blockId) {
  try { return localStorage.getItem(collapseKey(blockId)) === "1"; } catch (_) { return false; }
}

function setFolded(blockId, on) {
  try { localStorage.setItem(collapseKey(blockId), on ? "1" : "0"); } catch (_) {}
  applyFolds();
}

// One part at a time for now: a titled part folds its own body. Task 4 makes
// a heading fold the untitled parts after it too.
function applyFolds() {
  document.querySelectorAll("main.prose section.block[data-block-id]").forEach((s) => {
    const titled = !!s.querySelector(".block-heading");
    const on = titled && readFolded(s.dataset.blockId);
    s.classList.toggle("collapsed", on);
    const b = s.querySelector(".fold-btn");
    if (b) {
      b.textContent = on ? "▸" : "▾";
      b.setAttribute("aria-label", on ? "Unfold" : "Fold");
      b.setAttribute("aria-expanded", String(!on));
    }
  });
}
document.addEventListener("annotate:rendered", applyFolds);
```

  In `script.js`, replace `setCardTitle` (484–487) with nothing. Its only caller now uses `setBlockLabel`. In `renderChoice`:
  - Replace `const titleId = section.querySelector(".card-title")?.id;` with `const titleId = section.querySelector(".block-label")?.id;`.
  - Change the comment above it to say that the question is the part's visible title (`visibleTitle` reads `spec.question`).

  In `script-reconcile.js` `updateBlockContent`:
  - Delete `renderVersionBadge(section, blk.version ?? srvVer);`.
  - Replace `setCardTitle(section, blk);` with `setBlockLabel(section, blk);`.
  - Replace `section.querySelector(".card-body")` with `section.querySelector(".block-body")`.

- [ ] **Step 4: Point every reader of the card at the new names.**
  - **`anchors.js` 21:** `const SKIP = ".sel-composer, .sel-chip, .inline-comments, .code-col, .block-label, .sp-card";`
  - **`selection.js`:**
    - `inTitle` returns `!!(el && el.closest(".block-label"))`.
    - The last line of `excluded` becomes `return !(el.closest(".block-content") || el.closest(".block-label"));`.
    - The sheet quote (163) reads `t.section.getAttribute("aria-label") || ""`.
    - In `openWhole`, use `const head = section.querySelector(".block-label");`. The states become `` mark ? `Part marked ${mark.kind}` : "Whole part" ``.
    - `homeFocus`'s last line becomes `focusHome(home);`.
  - **`script-cards.js` 295:** `focusHome(home);`
  - **`edit.js`:**
    - Every `"This section …"` / `"rewriting this section"` string in `refusal` (357–362) says "part".
    - `placeHost` and `mount` read `.block-body` where they read `.card-body`.
    - Line 1345 becomes `if (hadFocus) focusHome(live);`.
  - **`maximize.js`:**
    - Delete the two chevron lines in `open` (130–131).
    - `reapply` sets `titleEl.textContent = section.getAttribute("aria-label") || "Diagram";`.
    - In `decorate`, mount into `section.querySelector(".block-label")`. Replace the pill lookup and `insertBefore` with `head.appendChild(btn);`.
  - **`script-changes.js`:**
    - In `markChangedCard`, use `const head = section.querySelector(".block-label");`.
    - Replace the `pill` branch (159–165) with `head.append(chip, toggle);`.
    - The tooltip and the diff label say "part" instead of "section".
    - `renderDiffPane` reads `.block-body`.
  - **`subunits.js`:**
    - `blockTitleFor` becomes the body below.
    - Line 610's `"whole section"` becomes `"whole part"`.

```js
  function blockTitleFor(blockId) {
    const s = document.querySelector(
      `section.block[data-block-id="${CSS.escape(blockId)}"]`);
    return s?.getAttribute("aria-label") || blockId;
  }
```

  - **`export.js`:**
    - In STRIP, replace `".card-chevron",` and `".section-pill",` with `".fold-btn",          // folding is meaningless once nothing can fold`.
    - Delete the `body.exported section.block .card-head { cursor: default; }` line.
  - **`script-chrome.js`:**
    - Replace `foldAll`'s body with a loop over `document.querySelectorAll("main.prose section.block .block-heading")` that writes each section's key, followed by one `applyFolds()`. The code is below.
    - Key `f` calls `setFolded(el.dataset.blockId, !el.classList.contains("collapsed"));`.

```js
  function foldAll(collapsed) {
    document.querySelectorAll("main.prose section.block .block-heading").forEach((h) => {
      const section = h.closest("section.block");
      try {
        localStorage.setItem(collapseKey(section.dataset.blockId), collapsed ? "1" : "0");
      } catch (_) {}
    });
    applyFolds();
  }
```

- [ ] **Step 5: Restyle the block as prose.** In `style.css`:
  - Replace "Card layout" (486–560) and "Card collapse" plus "Section · version pill" (628–690) with the rules below.
  - In 253–294, rename `.card-body` to `.block-body` and `.card-title` to `.block-label`. The `::after` badges move to `section.block[...] .block-label::after`. The descendant selector also reaches a framed part's head, which Task 3 nests inside `.block-frame`.
  - Change the badge words to `"✕ delete"`, `"⤓ compact"` and `"💬 comment"`.
  - The struck-through title rule targets `.block-heading-text`.
  - Line 346 becomes `section.block[data-kb-focus] .block-heading-text { color: var(--text-strong); }`.

```css
/* === One document ====================================================
   A block is a part of one document: no box, no header bar, no number.
   An authored title is an h2 (main.prose h2 sizes it); the body follows. */
body { background: var(--surface); }
section.block { position: relative; margin: 0; }
section.block:focus { outline: none; }
.block-heading { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.block-heading-text { min-width: 0; }
/* An untitled part's label line: there only when a mark or chip needs it. */
.block-meta { display: flex; align-items: center; gap: 8px; margin: 4px 0 0; }
section.block:not([data-block-mark]):not([data-mine]) > .block-meta:empty { display: none; }
.block-body { position: relative; border-left: 3px solid transparent; padding-left: 12px; margin-left: -15px; }
section.block[data-engaged-type="comment"] .block-body { border-left-color: var(--type-comment-fg); }
section.block[data-engaged-type="reject"]  .block-body { border-left-color: var(--type-reject-fg); }
main.prose .block-body p,
main.prose .block-body li,
main.prose .block-body blockquote { padding-right: 12px; }
main.prose .block-body h1, main.prose .block-body h2, main.prose .block-body h3,
main.prose .block-body h4, main.prose .block-body h5, main.prose .block-body h6 { padding-right: 12px; }
.block-body > .block-content { padding: 0 0 4px; }
.block-body > .block-content > :first-child { margin-top: 4px; }

/* === Folding ========================================================= */
section.block.collapsed .block-body { display: none; }
.fold-btn {
  width: 26px; height: 26px; flex: none;
  display: inline-flex; align-items: center; justify-content: center; padding: 0;
  background: var(--surface); border: 1px dashed var(--border); border-radius: 50%;
  color: var(--text-dim); cursor: pointer; font-size: 12px; line-height: 1;
  transition: color 120ms ease, border-color 120ms ease;
}
.fold-btn:hover { color: var(--text-strong); border-color: var(--control-border); }
```

  - Keep the "Block updating overlay" rules (561–627), but delete `border-radius: inherit;`.
  - In the other stylesheets, list every hit with `grep -n -E 'card-(head|title|chevron|body)|section-pill|block\.card' skills/annotate/static/*.css`. Rename `.card-body` to `.block-body`, and `section.block.card` to `section.block`. Delete rules that style only the head, the chevron or the pill.

- [ ] **Step 6: Update the tests that named the card.**
  - **`test_smoke_code_panes.py`:** every `.card-body` becomes `.block-body`. The collapse guard reads `section.block.collapsed .block-body`.
  - **`test_smoke_empty_draft.py:80`:** `'[data-engaged-type="comment"] .block-body'`.
  - **`test_smoke_maximize.py`:** the docstring at 70 says `.block-label`. The promotion test reads `section.block.is-maximized`.
  - **`test_smoke_fold_shortcuts.py`:**
    - The first test asserts `"foldAll"`, `"collapseKey(section.dataset.blockId)"` and `"applyFolds()"`.
    - The last test reads `.fold-btn {` and keeps its four needles.
  - **`test_smoke_round_drawer.py:83–84`:** `"whole part"`.

- [ ] **Step 7: Run the whole suite.**
  Run: `uv run -q --with-requirements requirements-test.txt python -m pytest skills -q`
  Expected: all pass, `test_smoke_document_blocks.py` included.

- [ ] **Step 8: Check in the browser.** Open the "Delivery listener" workspace (sid `261006-153502-1320eb816b9e2f04`).
  - `getComputedStyle(document.body).backgroundColor` is `rgb(248, 249, 251)`.
  - `document.querySelectorAll('.card-head,.section-pill').length` is `0`.
  - The first `h2.block-heading` and the first `.block-content p` start at the same `getBoundingClientRect().left`, give or take 1 px.
  - Clicking a fold button hides that part's `.block-body`, and the state survives a reload.

- [ ] **Step 9: Commit.**
  `git add` every file listed under **Files**, then `git commit -m "annotate: a block renders as part of one document, with no card, number or chevron"`.

---

### Task 3: Pictures, questions and code sit in a light frame

**Files:**
- Modify: `skills/annotate/static/script-blocks.js` (`createBlockSection`, `blockLabel`)
- Modify: `skills/annotate/static/maximize.js` (`decorate`)
- Modify: `skills/annotate/static/style.css`
- Test: `skills/annotate/tests/test_smoke_document_blocks.py`

**Interfaces:**
- Consumes: `blockLabel`, `.block-body` (Task 2).
- Produces: `FRAMED = ["sequence", "flowchart", "mockup", "choice", "explain"]`. A framed part is `section.block > div.block-frame > [div.block-label.block-frame-head, div.block-body]`. The frame head holds `span.block-heading-text[role=heading][aria-level=2]` when titled, then `span.block-frame-space`, then the maximise button.

- [ ] **Step 1: Write the failing test.** Append to `test_smoke_document_blocks.py`:

```python
def test_pictures_and_questions_get_a_frame_with_their_title_on_it():
    src = SCRIPT_JS.read_text()
    assert 'const FRAMED = ["sequence", "flowchart", "mockup", "choice", "explain"];' in src
    i = src.index("function blockLabel(")
    body = src[i:src.index("\n}", i)]
    assert "block-frame-head" in body
    css = STYLE_CSS.read_text()
    assert ".block-frame {" in css and "var(--diagram-ground)" in css[css.index(".block-frame {"):]


def test_the_maximise_button_sits_on_the_frame():
    src = (STATIC / "maximize.js").read_text()
    assert 'section.querySelector(".block-frame-head")' in src
```

- [ ] **Step 2: Run it and see it fail.** Run the file. Expected: 2 failed.

- [ ] **Step 3: Implement.** In `script-blocks.js`, add above `createBlockSection`:

```js
// Kinds that work differently from prose — a picture you can maximise, a
// question waiting for a pick, code walked note by note — sit in a light
// frame with their title on it, so the reader sees where prose stops.
const FRAMED = ["sequence", "flowchart", "mockup", "choice", "explain"];
```

  At the top of `blockLabel`, before `const title = …`, add:

```js
  if (FRAMED.includes(blk.kind || "markdown")) {
    const head = document.createElement("div");
    head.className = "block-label block-frame-head";
    head.id = `block-label-${blk.id}`;
    const t = visibleTitle(blk);
    if (t) {
      const text = document.createElement("span");
      text.className = "block-heading-text";
      text.setAttribute("role", "heading");
      text.setAttribute("aria-level", "2");
      text.textContent = t;
      head.appendChild(text);
    }
    const space = document.createElement("span");
    space.className = "block-frame-space";
    head.appendChild(space);
    return head;
  }
```

  In `createBlockSection`, delete `section.appendChild(blockLabel(blk));` near the top. Replace the final `section.appendChild(body);` with:

```js
  const label = blockLabel(blk);
  if (FRAMED.includes(kind)) {
    const frame = document.createElement("div");
    frame.className = "block-frame";
    frame.append(label, body);
    section.appendChild(frame);
  } else {
    section.append(label, body);
  }
```

  Folding: `applyFolds` already looks for `.block-heading`, which a frame head does not carry, so a framed part never folds by itself.

  In `maximize.js` `decorate`, use `const head = section.querySelector(".block-frame-head");`.

  In `style.css`, after the "One document" rules:

```css
/* === Frames: pictures, questions, walked code ======================== */
.block-frame { border: 1px solid var(--border); border-radius: 12px; background: var(--diagram-ground); margin: 14px 0 10px; overflow: hidden; }
.block-frame-head { display: flex; align-items: center; gap: 10px; padding: 9px 14px; border-bottom: 1px solid var(--border); background: var(--surface-soft); }
.block-frame-head .block-heading-text { font-size: 14px; font-weight: 600; color: var(--text-strong); }
.block-frame-space { flex: 1; }
.block-frame .block-body { margin-left: 0; padding: 12px 14px; border-left: 0; }
```

- [ ] **Step 4: Run the suite.** It is expected to pass.

- [ ] **Step 5: Check in the browser.**
  - On "Delivery listener", the sequence part's `.block-frame` has `border-top-width: 1px` and `border-radius: 12px`.
  - `.max-toggle` sits inside `.block-frame-head`: `closest('.block-frame-head')` is not null.
  - On "Stress-test selection" (sid `261008-214205-d2e2b7762aa70a5a`), the choice's frame head reads "One story or two".
  - The option group's `aria-labelledby` resolves to that head.

- [ ] **Step 6: Commit.**
  `git add skills/annotate/static/script-blocks.js skills/annotate/static/maximize.js skills/annotate/static/style.css skills/annotate/tests/test_smoke_document_blocks.py && git commit -m "annotate: pictures, questions and walked code sit in a light frame with their title"`

---

### Task 4: A heading folds everything up to the next heading

**Files:**
- Create: `skills/annotate/static/fold-groups.js`, `skills/annotate/tests/fold_groups.test.cjs`, `skills/annotate/tests/test_fold_groups.py`
- Modify: `skills/annotate/static/entry.js` (JS list), `script-blocks.js` (`applyFolds`), `script-chrome.js` (key `f`, `foldAll`, a Fold all button), `shell.js` (header), `style.css`, `export.js`
- Test: `skills/annotate/tests/test_smoke_fold_shortcuts.py`

**Interfaces:**
- Consumes: `readFolded`, `setFolded`, `collapseKey` (Task 2).
- Produces:
  - `AnnotateFolds.foldPlan(blocks)`. It takes `blocks = [{id, heading, collapsed}]` in page order and returns `{folded: Set<id>, hidden: Set<id>}`.
  - `AnnotateFolds.ownerOf(blocks, id) -> id|null`.
  - The CSS class `fold-hidden`.
  - The button `#fold-all`.

- [ ] **Step 1: Write the failing suite.** Create `skills/annotate/tests/fold_groups.test.cjs`:

```js
#!/usr/bin/env node
/* Folding goes by heading: a heading folds its own part and every untitled
 * part after it, up to the next heading. Run: node skills/annotate/tests/fold_groups.test.cjs */
const path = require("path");
const { foldPlan, ownerOf } = require(path.join(__dirname, "..", "static", "fold-groups.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(a, b, what) {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error((what || "") + " expected " + B + ", got " + A);
}
const sorted = (s) => [...s].sort();

test("a folded heading hides the untitled parts after it", () => {
  const p = foldPlan([
    { id: "a", heading: true, collapsed: true },
    { id: "b", heading: false, collapsed: false },
    { id: "c", heading: false, collapsed: false },
    { id: "d", heading: true, collapsed: false },
    { id: "e", heading: false, collapsed: false },
  ]);
  eq(sorted(p.folded), ["a"]);
  eq(sorted(p.hidden), ["b", "c"]);
});

test("an open heading hides nothing", () => {
  const p = foldPlan([{ id: "a", heading: true, collapsed: false }, { id: "b", heading: false, collapsed: true }]);
  eq(sorted(p.folded), []);
  eq(sorted(p.hidden), []);
});

test("untitled parts before the first heading never fold", () => {
  const p = foldPlan([{ id: "a", heading: false, collapsed: true }, { id: "b", heading: true, collapsed: true }]);
  eq(sorted(p.folded), ["b"]);
  eq(sorted(p.hidden), []);
});

test("a page with no headings folds nothing, whatever an old visit stored", () => {
  const p = foldPlan([{ id: "a", heading: false, collapsed: true }, { id: "b", heading: false, collapsed: true }]);
  eq(sorted(p.folded), []);
  eq(sorted(p.hidden), []);
});

test("a part's fold owner is the heading above it", () => {
  const blocks = [{ id: "x", heading: false }, { id: "a", heading: true }, { id: "b", heading: false }];
  eq(ownerOf(blocks, "b"), "a");
  eq(ownerOf(blocks, "a"), "a");
  eq(ownerOf(blocks, "x"), null);
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
```

  Create `skills/annotate/tests/test_fold_groups.py`:

```python
"""Runs the fold-groups suite under pytest; skips without node."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("fold_groups.test.cjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_fold_groups_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m and int(m.group(2)) >= 5, proc.stdout
```

- [ ] **Step 2: Run it and see it fail.**
  Run: `node skills/annotate/tests/fold_groups.test.cjs`
  Expected: `Cannot find module …/fold-groups.js`.

- [ ] **Step 3: Implement the rule.** Create `skills/annotate/static/fold-groups.js`:

```js
// annotate — which parts a fold hides.
//
// The page reads as one document, so folding goes by heading, as in any
// document: a heading folds its own part and every untitled part after it,
// up to the next heading. A part with no heading above it never folds, and
// a page with no headings folds nothing, whatever an older visit stored.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateFolds = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function foldPlan(blocks) {
    const folded = new Set(), hidden = new Set();
    let owner = null;
    for (const b of blocks || []) {
      if (b.heading) {
        owner = b;
        if (b.collapsed) folded.add(b.id);
      } else if (owner && owner.collapsed) {
        hidden.add(b.id);
      }
    }
    return { folded, hidden };
  }

  function ownerOf(blocks, id) {
    let owner = null;
    for (const b of blocks || []) {
      if (b.heading) owner = b.id;
      if (b.id === id) return owner;
    }
    return null;
  }

  return { foldPlan, ownerOf };
});
```

  In `entry.js`, add `"fold-groups.js",` right after `"block-title.js",`, with the comment `// Before script.js: applyFolds reads the fold rule.`

- [ ] **Step 4: Run it and see it pass.** Run the node suite and `test_fold_groups.py`. Expected: `5/5 passed`, and pytest passes.

- [ ] **Step 5: Use it on the page.** In `script-blocks.js`, replace the Task 2 `applyFolds` with:

```js
// Folding goes by heading (fold-groups.js): a heading folds its own part and
// the untitled parts after it. Recomputed whole after every change and every
// render, so a rewrite that adds or drops a heading regroups at once.
function foldList() {
  return [...document.querySelectorAll("main.prose section.block[data-block-id]")].map((s) => ({
    id: s.dataset.blockId,
    section: s,
    heading: !!s.querySelector(".block-heading"),
    collapsed: readFolded(s.dataset.blockId),
  }));
}

function applyFolds() {
  const list = foldList();
  const { folded, hidden } = window.AnnotateFolds.foldPlan(list);
  for (const b of list) {
    const on = folded.has(b.id);
    b.section.classList.toggle("collapsed", on);
    b.section.classList.toggle("fold-hidden", hidden.has(b.id));
    const btn = b.section.querySelector(".fold-btn");
    if (btn) {
      btn.textContent = on ? "▸" : "▾";
      btn.setAttribute("aria-label", on ? "Unfold" : "Fold");
      btn.setAttribute("aria-expanded", String(!on));
    }
  }
  const all = document.getElementById("fold-all");
  if (all) {
    const heads = list.filter((b) => b.heading);
    all.hidden = !heads.length;
    const every = heads.length && heads.every((b) => folded.has(b.id));
    all.textContent = every ? "Unfold all" : "Fold all";
    all.dataset.next = every ? "unfold" : "fold";
  }
}
```

  In `script-chrome.js`, key `f` folds the owner:

```js
    if (e.key === "f") {
      const el = focused();
      if (!el) return;
      const owner = window.AnnotateFolds.ownerOf(foldList(), el.dataset.blockId);
      if (!owner) return;
      e.preventDefault();
      const section = document.querySelector(`section.block[data-block-id="${cssEsc(owner)}"]`);
      setFolded(owner, !section.classList.contains("collapsed"));
      return;
    }
```

  At the end of the chord IIFE, add before `})();`:

```js
  document.getElementById("fold-all")?.addEventListener("click", (e) => {
    foldAll(e.currentTarget.dataset.next !== "unfold");
  });
```

  In `shell.js`, insert this line before the `<button id="highlighter-toggle"` line:

```
<button id="fold-all" type="button" class="text-btn fold-all-btn" title="Fold every heading (⌘K ⌘0)" hidden>Fold all</button>\
```

  In `style.css`, add:

```css
section.block.fold-hidden { display: none; }
.fold-all-btn { font: 600 12.5px var(--font-prose); border: 1px solid var(--border); background: var(--surface); border-radius: 7px; padding: 6px 12px; color: var(--text); cursor: pointer; }
.fold-all-btn[hidden] { display: none; }
```

  In `export.js` STRIP, add `"#fold-all",`. In STATE_ATTRS there is nothing to add: `fold-hidden` is a class, so add this to EXPORT_CSS instead: `body.exported section.block.fold-hidden, body.exported section.block.collapsed .block-body { display: revert; }`.

- [ ] **Step 6: Guard the button.** Append to `test_smoke_fold_shortcuts.py`:

```python
def test_fold_all_is_a_visible_button_that_hides_with_no_headings():
    shell = (STATIC / "shell.js").read_text()
    assert 'id="fold-all"' in shell
    src = SCRIPT_JS.read_text()
    assert "all.hidden = !heads.length" in src, "Fold all shows on a page with no headings"
    css = STYLE_CSS.read_text()
    assert ".fold-all-btn[hidden]" in css
```

- [ ] **Step 7: Run the suite.** It is expected to pass, `test_smoke_shell_source.py` included.

- [ ] **Step 8: Check in the browser.**
  - On "Delivery listener", fold "How it hears about sandboxes". Every `section.fold-hidden` that follows has `getComputedStyle(...).display === "none"`, and the next heading stays visible.
  - Fold all turns into Unfold all, and both survive a reload.
  - On a workspace whose parts have no titles, `#fold-all` has `hidden`.

- [ ] **Step 9: Commit.**
  `git add skills/annotate/static/fold-groups.js skills/annotate/static/entry.js skills/annotate/static/script-blocks.js skills/annotate/static/script-chrome.js skills/annotate/static/shell.js skills/annotate/static/style.css skills/annotate/static/export.js skills/annotate/tests/fold_groups.test.cjs skills/annotate/tests/test_fold_groups.py skills/annotate/tests/test_smoke_fold_shortcuts.py && git commit -m "annotate: a heading folds everything up to the next heading, with a Fold all button"`

---

### Task 5: A rewrite is marked on its heading, and a part being rewritten shows it

**Files:**
- Modify: `skills/annotate/static/script-changes.js` (88, 135–166, 299)
- Modify: `skills/annotate/static/script-reconcile.js` (`registerRoundEvent` 362)
- Modify: `skills/annotate/static/script-poll.js` (`handleConsumedEvents` 19–33)
- Modify: `skills/annotate/static/script-cards.js` (comment above `startUpdatingOverlay`)
- Test: `skills/annotate/tests/test_smoke_change_bar.py`, `skills/annotate/tests/test_smoke_progress.py`

**Interfaces:**
- Consumes: `.block-label` (Tasks 2 and 3), `startUpdatingOverlay(section)` and `clearUpdatingOverlay(section)` (existing).
- Produces: the bar text `"<n> part(s) changed — <a> you asked for, <b> by the coherence sweep"`. The overlay goes on every block a round names, and clears on that round's ack.

- [ ] **Step 1: Write the failing tests.**
  - In `test_smoke_change_bar.py`, change line 23 to `assert 'part${changed.length > 1 ? "s" : ""} changed' in src, "the bar does not say how many parts moved"`.
  - Add `assert "section" not in src[src.index("function renderChangeBar"):src.index("function renderDiffPane")]`.
  - Append to `test_smoke_progress.py`:

```python
def test_a_round_puts_the_updating_overlay_on_every_part_it_names():
    src = SCRIPT_JS.read_text()
    i = src.index("registerRoundEvent(eventId, blockIds)")
    body = src[i:src.index("\n  },", i)]
    assert "startUpdatingOverlay(" in body, "submitting a round shows nothing on the parts"


def test_the_ack_clears_every_part_of_the_round():
    src = SCRIPT_JS.read_text()
    i = src.index("function handleConsumedEvents(")
    body = src[i:src.index("\n}", i)]
    assert "pend.blockIds" in body, "a round's overlays outlive its ack"
```

- [ ] **Step 2: Run and see them fail.**
  Run: `uv run -q --with-requirements requirements-test.txt python -m pytest skills/annotate/tests/test_smoke_change_bar.py skills/annotate/tests/test_smoke_progress.py -q`
  Expected: 3 failed.

- [ ] **Step 3: Implement.**
  - **`script-changes.js` `renderChangeBar`:**
    - `if (asked) parts.push(`${asked} you asked for`);`
    - `` txt.innerHTML = `<b>${changed.length} part${changed.length > 1 ? "s" : ""} changed</b>` `` followed by the unchanged tail.
    - Update the file's header comment, which quotes the old sentence.
  - **`markChangedCard`:** it already uses `.block-label` (Task 2). A titled part shows the chip after its text inside the `h2`. An untitled part shows it on the `.block-meta` line, which is no longer `:empty`. The tooltip reads `"Rewritten by the coherence sweep — you did not mark this part"`.
  - **`renderDiffPane`:** `" — you did not mark this part"`.
  - **`script-reconcile.js` `registerRoundEvent`:** after `pendingEvents.set(...)`, add:

```js
    // Every part the round names shows that Claude is rewriting it, until
    // the ack (handleConsumedEvents) or its new version clears it. Parts the
    // sweep rewrites are not known in advance and get none.
    for (const id of blockIds || []) {
      startUpdatingOverlay(document.querySelector(`section.block[data-block-id="${cssEsc(id)}"]`));
    }
```

  - **`script-poll.js` `handleConsumedEvents`:** after the `if (pend.blockId) { … }` branch, add:

```js
    } else if (pend.round) {
      for (const id of pend.blockIds || []) {
        const section = document.querySelector(`section.block[data-block-id="${cssEsc(id)}"]`);
        if (section) clearUpdatingOverlay(section);
      }
```

  - **`script-cards.js`:** the comment above `startUpdatingOverlay` reads `// Started on every part a submitted round names (registerRoundEvent), cleared by its ack or its new version.`

- [ ] **Step 4: Prove the overlay test guards the fix.** With `PYTHONDONTWRITEBYTECODE=1`:
  1. Delete the loop added to `registerRoundEvent` and run `test_smoke_progress.py`. Paste the failure.
  2. Restore the loop and run it again. Paste the pass.

- [ ] **Step 5: Run the suite.** It is expected to pass.

- [ ] **Step 6: Check in the browser.** On a scratch workspace, made with the push in `references/pushing.md`:
  - Comment on one part and submit. That part gets `.updating-overlay`, and its `getBoundingClientRect()` matches the section's.
  - After the ack it is gone, and the chip "you asked" sits inside `h2.block-heading`.

- [ ] **Step 7: Commit.**
  `git add skills/annotate/static/script-changes.js skills/annotate/static/script-reconcile.js skills/annotate/static/script-poll.js skills/annotate/static/script-cards.js skills/annotate/tests/test_smoke_change_bar.py skills/annotate/tests/test_smoke_progress.py && git commit -m "annotate: a rewrite is marked on its heading, and a part being rewritten shows it"`

---

### Task 6: A comment opens in a floating window that moves and resizes

**Files:**
- Create: `skills/annotate/static/window-place.js`, `skills/annotate/static/comment-window.js`, `skills/annotate/static/style-comment-window.css`, `skills/annotate/tests/window_place.test.cjs`, `skills/annotate/tests/test_window_place.py`, `skills/annotate/tests/test_smoke_comment_window.py`
- Modify: `skills/annotate/static/entry.js` (both lists)
- Modify: `selection.js` (32–36, 325–456, 661–664), `script-cards.js` (`buildCard`, `renderComments`, `focusComment`, `revealOpenDraft`), `script.js` (`openAnnotation`)
- Modify: `script-reconcile.js` (174–176, 214–217), `choice-queue.js` (39, 71–75), `search.js` (141–155), `edit.js` (1326–1327), `export.js` (STRIP), `voice.js` (192), `anchors.js` (21)
- Modify: `core.css` (404), `style.css` (`.comment-card.is-calling` and the read-only list), `style-selection.css` (55–98)
- Test: modify `test_smoke_comment_open.py`, `test_smoke_export.py`, `test_smoke_compact.py`, `test_smoke_read_only.py` and `test_smoke_card_structure.py`

**Interfaces:**
- Produces:
  - `AnnotateWindowPlace.place({sel, content, view, size}) -> {left, top, width, height}`. All arguments are plain numbers: `sel` and `content` are `{left, top, right, bottom}`, `view` is `{w, h}` and `size` is `{w, h}`.
  - `AnnotateWindowPlace.clamp(box, view) -> box`.
  - `AnnotateCommentWindow.open({owner, quote, body, near, onClose}) -> HTMLElement`.
  - `AnnotateCommentWindow.close(owner?)`, `.isOpen()`, `.owner()`, `.hasWords()`, `.call()`, `.element()`.
  - Owners are `"span"` for the selection's box and `"card:<draftId>"` for a whole-part or step comment.

- [ ] **Step 1: Write the failing placement suite.** Create `skills/annotate/tests/window_place.test.cjs`:

```js
#!/usr/bin/env node
/* Where the comment window opens. Run: node skills/annotate/tests/window_place.test.cjs */
const path = require("path");
const { place, clamp, MIN } = require(path.join(__dirname, "..", "static", "window-place.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(a, b, what) {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error((what || "") + " expected " + B + ", got " + A);
}
const overlaps = (w, s) => w.left < s.right && s.left < w.left + w.width && w.top < s.bottom && s.top < w.top + w.height;

test("with room beside the text it opens there, level with the selection", () => {
  const out = place({ sel: { left: 100, top: 300, right: 500, bottom: 340 }, content: { left: 40, top: 0, right: 900, bottom: 3000 },
                      view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(out, { left: 916, top: 290, width: 420, height: 280 });
});

test("with no room beside the text it stays off the selected words", () => {
  const sel = { left: 60, top: 300, right: 700, bottom: 360 };
  const out = place({ sel, content: { left: 40, top: 0, right: 1460, bottom: 3000 }, view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(overlaps(out, sel), false, "covers the selection");
  eq(out.left + out.width <= 1500 - 16 && out.top >= 16 && out.top + out.height <= 1000 - 16, true, "off screen");
});

test("a selection across the full width puts the window below it", () => {
  const sel = { left: 40, top: 200, right: 1460, bottom: 260 };
  const out = place({ sel, content: { left: 40, top: 0, right: 1460, bottom: 3000 }, view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(out.top, 272);
  eq(overlaps(out, sel), false);
});

test("near the bottom it goes above the selection", () => {
  const sel = { left: 40, top: 800, right: 1460, bottom: 860 };
  const out = place({ sel, content: { left: 40, top: 0, right: 1460, bottom: 3000 }, view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(out.top, 800 - 12 - 280);
});

test("on a narrow screen it is full width less a 16px gutter", () => {
  const out = place({ sel: { left: 16, top: 100, right: 300, bottom: 140 }, content: { left: 16, top: 0, right: 374, bottom: 3000 },
                      view: { w: 390, h: 800 }, size: { w: 420, h: 280 } });
  eq([out.left, out.width], [16, 358]);
  eq(out.top, 152);
});

test("a remembered size below the minimum is raised to it", () => {
  const out = place({ sel: { left: 100, top: 300, right: 500, bottom: 340 }, content: { left: 40, top: 0, right: 900, bottom: 3000 },
                      view: { w: 1500, h: 1000 }, size: { w: 10, h: 10 } });
  eq([out.width, out.height], [MIN.w, MIN.h]);
});

test("a window left off screen by a smaller browser is pulled back", () => {
  eq(clamp({ left: 1300, top: 900, width: 420, height: 280 }, { w: 1000, h: 700 }), { left: 564, top: 404, width: 420, height: 280 });
  eq(clamp({ left: -50, top: -20, width: 2000, height: 900 }, { w: 1000, h: 700 }), { left: 16, top: 16, width: 968, height: 668 });
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
```

  Create `skills/annotate/tests/test_window_place.py`, a copy of `test_fold_groups.py` with `SUITE = Path(__file__).with_name("window_place.test.cjs")`, the test named `test_window_place_suite_passes`, and `>= 7`.

- [ ] **Step 2: Run it and see it fail.**
  Run: `node skills/annotate/tests/window_place.test.cjs`
  Expected: `Cannot find module`.

- [ ] **Step 3: Implement the placement.** Create `skills/annotate/static/window-place.js`:

```js
// annotate — where the comment window opens, as plain numbers.
//
// Beside the text when there is room, level with the first selected line.
// Otherwise at the right edge if that does not cover the selected words,
// else below them, else above them. On a screen under 600px wide it is full
// width less a 16px gutter. Always fully on screen.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateWindowPlace = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const GAP = 16, NEAR = 12, NARROW = 600;
  const MIN = { w: 300, h: 200 };

  function clamp(box, view) {
    const width = Math.min(Math.max(box.width, MIN.w), view.w - 2 * GAP);
    const height = Math.min(Math.max(box.height, MIN.h), view.h - 2 * GAP);
    const left = Math.min(Math.max(box.left, GAP), view.w - GAP - width);
    const top = Math.min(Math.max(box.top, GAP), view.h - GAP - height);
    return { left, top, width, height };
  }

  function covers(b, s) {
    return b.left < s.right && s.left < b.left + b.width && b.top < s.bottom && s.top < b.top + b.height;
  }

  function vertical(sel, height, view) {
    const below = sel.bottom + NEAR;
    if (below + height <= view.h - GAP) return below;
    return sel.top - NEAR - height;
  }

  function place({ sel, content, view, size }) {
    let width = Math.max(size.w, MIN.w), height = Math.max(size.h, MIN.h);
    if (view.w < NARROW) {
      width = view.w - 2 * GAP;
      return clamp({ left: GAP, top: vertical(sel, height, view), width, height }, view);
    }
    const level = sel.top - 10;
    if (view.w - content.right - GAP >= width + GAP) {
      return clamp({ left: content.right + GAP, top: level, width, height }, view);
    }
    const edge = clamp({ left: view.w - GAP - width, top: level, width, height }, view);
    if (!covers(edge, sel)) return edge;
    return clamp({ left: Math.max(sel.left, GAP), top: vertical(sel, height, view), width, height }, view);
  }

  return { place, clamp, MIN };
});
```

- [ ] **Step 4: Run it and see it pass.** Run the node suite and `test_window_place.py`. Expected: `7/7 passed`.

- [ ] **Step 5: Write the failing page guards.** Create `skills/annotate/tests/test_smoke_comment_window.py`:

```python
"""Every comment opens in one floating window: the selection's box and the
whole-part card alike. It is moved by its title bar and resized from its
corner, and a rewrite can never take it, or the reader's words, away."""
from pathlib import Path

from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

STATIC = Path(__file__).resolve().parents[1] / "static"
WIN = (STATIC / "comment-window.js").read_text() if (STATIC / "comment-window.js").exists() else ""
SEL = (STATIC / "selection.js").read_text()


def _fn(src, name):
    i = src.index("function %s(" % name)
    return src[i:src.index("\n}", i) if "\n}" in src[i:] else len(src)]


def test_the_window_moves_by_its_bar_and_resizes_from_its_corner():
    assert "comment-window-bar" in WIN and "pointerdown" in WIN
    assert "comment-window-resize" in WIN
    assert "AnnotateWindowPlace.clamp" in WIN, "a move can push the window off screen"


def test_the_window_lives_on_the_body_not_in_a_part():
    assert "document.body.appendChild(win)" in WIN


def test_a_shrinking_browser_pulls_the_window_back():
    assert 'addEventListener("resize"' in WIN


def test_the_selection_box_and_the_card_both_open_it():
    assert "AnnotateCommentWindow.open(" in SEL
    assert "AnnotateCommentWindow.open(" in _fn(SCRIPT_JS.read_text(), "renderComments")
    assert "insertAdjacentElement" not in _fn(SEL, "openComposer"), "the box is still put inside the text"


def test_no_comment_box_is_mounted_in_the_text_any_more():
    src = SCRIPT_JS.read_text()
    assert '"inline-comments"' not in src
    assert "hostFor(" not in SEL


def test_words_typed_before_a_rewrite_are_kept():
    commit = SEL[SEL.index("const commit = () =>"):]
    commit = commit[:commit.index("};")]
    assert "rangeFor" in commit, "Save no longer checks the words are still there"
    assert "pinComment" in commit and "annotate:orphan-comment" in commit, \
        "words on rewritten text are dropped instead of moved"


def test_the_window_is_styled_and_readable():
    css = STYLE_CSS.read_text()
    assert ".comment-window {" in css and "position: fixed" in css[css.index(".comment-window {"):]
    assert ".comment-window.is-calling" in css
```

- [ ] **Step 6: Run and see them fail.** Run the file. Expected: every test fails.

- [ ] **Step 7: Implement the window.** Create `skills/annotate/static/comment-window.js`:

```js
// annotate — the one comment window.
//
// Every comment opens here: words chosen in the text (selection.js) and a
// comment on a whole part or a picture's step (script-cards.js). It floats
// on the page, free of the text: moved by its title bar, resized from its
// corner, opened beside the words it is about (window-place.js). One at a
// time; an owner that would replace a window holding words calls it instead.
// It lives on <body>, so no rewrite of a part can take it away.
(function () {
  "use strict";

  const SIZE_KEY = "annotate.commentWindow.size";
  let win = null, current = null;

  function storedSize() {
    try {
      const s = JSON.parse(localStorage.getItem(SIZE_KEY) || "null");
      if (s && s.w > 0 && s.h > 0) return s;
    } catch (_) {}
    return { w: 420, h: 280 };
  }
  function saveSize(w, h) {
    try { localStorage.setItem(SIZE_KEY, JSON.stringify({ w: Math.round(w), h: Math.round(h) })); } catch (_) {}
  }
  function view() { return { w: document.documentElement.clientWidth, h: window.innerHeight }; }
  function apply(box) {
    win.style.left = box.left + "px"; win.style.top = box.top + "px";
    win.style.width = box.width + "px"; win.style.height = box.height + "px";
  }
  function box() {
    const r = win.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height };
  }

  function build() {
    win = document.createElement("div");
    win.className = "comment-window";
    win.setAttribute("role", "dialog");
    win.setAttribute("aria-label", "Comment");
    win.innerHTML =
      '<div class="comment-window-bar"><span class="comment-window-grip" aria-hidden="true"></span>'
      + '<span class="comment-window-title">Comment</span><span class="comment-window-space"></span>'
      + '<button type="button" class="comment-window-close" aria-label="Close comment">×</button></div>'
      + '<div class="comment-window-quote"></div><div class="comment-window-body"></div>'
      + '<div class="comment-window-resize" title="Drag to resize"></div>';
    document.body.appendChild(win);
    win.querySelector(".comment-window-close").addEventListener("click", () => close());

    const bar = win.querySelector(".comment-window-bar");
    bar.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button")) return;
      e.preventDefault();
      const start = box(), x = e.clientX, y = e.clientY;
      bar.setPointerCapture(e.pointerId);
      win.classList.add("is-moving");
      const move = (ev) => apply(window.AnnotateWindowPlace.clamp(
        { ...start, left: start.left + ev.clientX - x, top: start.top + ev.clientY - y }, view()));
      const up = () => {
        win.classList.remove("is-moving");
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
        bar.removeEventListener("pointercancel", up);
      };
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
      bar.addEventListener("pointercancel", up);
    });

    const grip = win.querySelector(".comment-window-resize");
    grip.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const start = box(), x = e.clientX, y = e.clientY;
      grip.setPointerCapture(e.pointerId);
      win.classList.add("is-moving");
      const move = (ev) => apply(window.AnnotateWindowPlace.clamp(
        { ...start, width: start.width + ev.clientX - x, height: start.height + ev.clientY - y }, view()));
      const up = () => {
        win.classList.remove("is-moving");
        const b = box();
        saveSize(b.width, b.height);
        grip.removeEventListener("pointermove", move);
        grip.removeEventListener("pointerup", up);
        grip.removeEventListener("pointercancel", up);
      };
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", up);
      grip.addEventListener("pointercancel", up);
    });

    win.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    });
    window.addEventListener("resize", () => {
      if (win && !win.hidden) apply(window.AnnotateWindowPlace.clamp(box(), view()));
    });
  }

  function contentRect() {
    const c = document.querySelector("main.prose .block-content");
    const r = c ? c.getBoundingClientRect() : { left: 0, right: view().w };
    return { left: r.left, top: 0, right: r.right, bottom: view().h };
  }

  // Open for `owner`, holding `body` (the editor the caller built). A window
  // already open for another owner is closed first, its onClose told so it
  // can drop an empty draft; the caller checks hasWords() before asking.
  function open({ owner, quote, body, near, onClose }) {
    if (!win) build();
    if (current && current.owner !== owner) close();
    current = { owner, onClose };
    win.querySelector(".comment-window-quote").textContent = quote || "";
    win.querySelector(".comment-window-quote").hidden = !quote;
    win.querySelector(".comment-window-body").replaceChildren(body);
    win.hidden = false;
    const s = storedSize();
    const sel = near || { left: 0, top: 80, right: 0, bottom: 80 };
    apply(window.AnnotateWindowPlace.place({ sel, content: contentRect(), view: view(), size: s }));
    return win;
  }

  function close(owner) {
    if (!win || win.hidden || !current) return;
    if (owner && current.owner !== owner) return;
    const was = current;
    current = null;
    win.hidden = true;
    win.querySelector(".comment-window-body").replaceChildren();
    try { was.onClose && was.onClose(); } catch (_) {}
  }

  function hasWords() {
    const ta = win && !win.hidden && win.querySelector("textarea");
    return !!(ta && ta.value.trim());
  }

  // The answer to "why did nothing open": the open window, pulsed, with the
  // caret in it. Restarted, so a second refusal pulses too.
  function call() {
    if (!win || win.hidden) return;
    win.classList.remove("is-calling");
    void win.offsetWidth;
    win.classList.add("is-calling");
    setTimeout(() => win && win.classList.remove("is-calling"), 1200);
    win.querySelector("textarea")?.focus({ preventScroll: true });
  }

  window.AnnotateCommentWindow = {
    open, close, hasWords, call,
    isOpen: () => !!(win && !win.hidden && current),
    owner: () => (current ? current.owner : null),
    element: () => win,
  };
})();
```

  In `entry.js`:
  - Add `"window-place.js",` and `"comment-window.js",` after `"anchors.js",`, with the comment `// Before script.js and selection.js: both open comments in this window.`
  - Add `"style-comment-window.css",` after `"style-selection.css",` in CSS.

  Create `skills/annotate/static/style-comment-window.css`:

```css
/* The one comment window (comment-window.js). */
.comment-window {
  position: fixed; z-index: 70; display: flex; flex-direction: column;
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  box-shadow: 0 1px 2px rgba(20, 24, 40, .06), 0 18px 48px rgba(20, 24, 40, .22);
  overflow: hidden; color: var(--text-strong); font-family: var(--font-prose);
}
.comment-window[hidden] { display: none; }
.comment-window-bar { display: flex; align-items: center; gap: 8px; padding: 7px 8px 7px 14px;
  background: var(--surface-soft); border-bottom: 1px solid var(--border); cursor: grab; user-select: none; }
.comment-window.is-moving, .comment-window.is-moving .comment-window-bar { cursor: grabbing; user-select: none; }
.comment-window-grip { width: 10px; height: 14px;
  background: radial-gradient(circle, var(--n-300) 1.3px, transparent 1.6px) 0 0 / 5px 5px; }
.comment-window-title { font-size: 13px; font-weight: 700; }
.comment-window-space { flex: 1; }
.comment-window-close { border: 0; background: none; color: var(--text-dim); font-size: 18px; line-height: 1;
  width: 28px; height: 28px; border-radius: 7px; cursor: pointer; }
.comment-window-close:hover { background: var(--surface-hover); color: var(--text-strong); }
.comment-window-quote { margin: 12px 14px 0; font-size: 13px; line-height: 1.45; color: var(--text);
  border-left: 3px solid var(--type-comment-fg); background: var(--type-comment-wash);
  padding: 6px 10px; border-radius: 0 7px 7px 0; max-height: 84px; overflow: auto; white-space: pre-line; }
.comment-window-quote[hidden] { display: none; }
.comment-window-body { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 10px 14px 14px; }
.comment-window-body > * { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
.comment-window-body textarea { flex: 1; min-height: 60px; width: 100%; box-sizing: border-box; resize: none;
  font: 14.5px/1.5 var(--font-prose); color: var(--text-strong); background: var(--surface);
  border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px; }
.comment-window-body textarea:focus { outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.comment-window-resize { position: absolute; right: 3px; bottom: 3px; width: 16px; height: 16px; cursor: nwse-resize;
  background: linear-gradient(135deg, transparent 0 55%, var(--n-300) 55% 61%, transparent 61% 72%, var(--n-300) 72% 78%, transparent 78%); }
.comment-window.is-calling { animation: card-calling 1.1s ease; }
@media (prefers-reduced-motion: reduce) { .comment-window.is-calling { animation: none; outline: 2px solid var(--accent); } }
body.read-only .comment-window { display: none; }
```

- [ ] **Step 8: Put the selection's box in the window.** In `selection.js`:
  - `IGNORE` replaces `.sel-composer, ` with `.comment-window, ` and drops `, .inline-comments`.
  - `OWN` becomes `".sel-menu, .comment-window, .sp-card"`.
  - `PANELS` replaces `.comment-card` with `.comment-window`.
  - Delete `hostFor`, `rescueDraft` and `homeFocus`. Replace `syncDraftLock`, `closeComposer` and `openComposer` with the code below. The `annotate:rendered` listener keeps only its first line.

```js
  let composer = null, draft = null;
  const W = () => window.AnnotateCommentWindow;
  function syncDraftLock() {
    const ta = composer && W().owner() === "span" && composer.querySelector("textarea");
    const on = !!(ta && ta.value.trim());
    if (document.body.classList.contains("has-sel-draft") === on) return;
    document.body.classList.toggle("has-sel-draft", on);
    S()?.renderDock();
  }
  function closeComposer() {
    W().close("span");
  }
  function homeFor(anchor) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(anchor.block_id)}"]`);
  }

  function openComposer(section, anchor, range, initial) {
    if (W().isOpen() && W().hasWords()) { W().call(); return; }
    const box = document.createElement("div");
    box.className = "sel-composer";
    const ta = document.createElement("textarea");
    ta.value = initial != null ? initial : commentOn(section, anchor);
    ta.placeholder = "Ask or push back on this…";
    ta.setAttribute("aria-label", "Comment on the selected words");
    ta.addEventListener("input", () => { if (draft) draft.text = ta.value; syncDraftLock(); });
    const row = document.createElement("div");
    row.className = "sel-row";
    row.innerHTML = '<span class="card-submit-hint"><kbd>↩</kbd> to add · '
      + '<kbd>⇧</kbd><kbd>↩</kbd> new line · <kbd>Esc</kbd> to close</span>';
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "sel-cancel"; cancel.textContent = "Cancel";
    const add = document.createElement("button");
    add.type = "button"; add.className = "card-submit-btn"; add.textContent = "Add to round";
    // The words may have been rewritten while the window was open. Still
    // there: the comment goes on them. Gone, part still there: it goes on
    // the part, quoting what it was about. Part gone too: the general box.
    const commit = () => {
      const v = ta.value.trim();
      const parts = anchor.spans || [anchor];
      closeComposer();
      if (!v) return;
      const home = homeFor(parts[0]);
      const live = parts.every((p) => { const s = homeFor(p); return s && A().rangeFor(s, p); });
      if (live) S().setSpanMark(anchor, "comment", v);
      else if (home) {
        const q = anchor.selected_text.length > 120 ? anchor.selected_text.slice(0, 117) + "…" : anchor.selected_text;
        S().pinComment({ block_id: parts[0].block_id, text: `On the passage that read "${q}": ${v}` });
      } else {
        document.dispatchEvent(new CustomEvent("annotate:orphan-comment",
          { detail: { text: v, quote: anchor.selected_text } }));
      }
      focusHome(home);
    };
    const dismiss = () => { closeComposer(); focusHome(homeFor((anchor.spans || [anchor])[0])); };
    cancel.addEventListener("click", (e) => { e.stopPropagation(); dismiss(); });
    add.addEventListener("click", (e) => { e.stopPropagation(); commit(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); dismiss(); }
    });
    row.append(cancel, add);
    box.append(ta, row);
    W().open({ owner: "span", quote: anchor.selected_text, body: box,
               near: range.getBoundingClientRect(),
               onClose: () => { composer = null; draft = null; syncDraftLock(); } });
    composer = box;
    draft = { anchor, text: ta.value };
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    syncDraftLock();
  }
```

- [ ] **Step 9: Put the part's card in the window.** In `script-cards.js` `buildCard`:
  - Delete the `closeBtn` block (71–84). The window's × closes.
  - Delete the `quote` block (113–119). The window shows the quote.
  - In the submit handler, replace `card.remove();` with `window.AnnotateCommentWindow.close("card:" + id);`.
  - Replace `renderComments`'s body after the prune with the code below.
  - `focusComment` reads `document.querySelector(".comment-window textarea")`.
  - `revealOpenDraft`'s body becomes `window.AnnotateCommentWindow.call();`.

```js
  const W = window.AnnotateCommentWindow;
  const entries = Object.entries(annotations);
  if (!entries.length) {
    if (W.owner() && W.owner().startsWith("card:")) W.close();
  } else {
    const [id, a] = entries[0];
    if (W.owner() !== "card:" + id) {
      const section = document.querySelector(`section.block[data-block-id="${cssEsc(a.block_id)}"]`);
      const step = a.step_id ? stepContextFor(a.block_id, a.step_id) : null;
      const label = (section && section.querySelector(".block-label")) || section;
      W.open({
        owner: "card:" + id,
        quote: a.selected_text || (step && step.label) || (section ? section.getAttribute("aria-label") : ""),
        body: buildCard(id, a),
        near: (step && step.node ? step.node : label).getBoundingClientRect(),
        // The window's × is the old card's ×: the draft goes with it.
        onClose: () => {
          if (!annotations[id]) return;
          delete annotations[id];
          saveDrafts();
          document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
          applyEngagedStyling();
          window.AnnotateSubunits?.renderDock();
        },
      });
    }
  }
```

  In `script.js` `openAnnotation`, the guard becomes:

```js
    if (Object.keys(annotations).length > 0
        || (window.AnnotateCommentWindow.isOpen() && window.AnnotateCommentWindow.hasWords())) {
      revealOpenDraft();
      return;
    }
```

- [ ] **Step 10: Remove the in-text wrappers everywhere else.**
  - **`script-reconcile.js`:**
    - Delete the two `ic` lines at 175–176.
    - At 214–217, replace the trailing anchor with `anchor = section;`.
    - Update the comment at 152–153.
  - **`choice-queue.js`:** line 39 becomes `if (el.classList.contains("cq-bar")) continue;`, and `setHidden` keeps only its first line.
  - **`search.js`:** delete the four `const ic …` / `if (ic …)` lines in 141–155.
  - **`edit.js`:** delete 1326–1327.
  - **`export.js` STRIP:** replace the `.sel-composer` and `.inline-comments` lines with `".comment-window",       // the open comment window`.
  - **`voice.js` 192:** `const box = row.closest(".comment-window");`.
  - **`anchors.js` 21:** `const SKIP = ".sel-chip, .code-col, .block-label, .sp-card";`
  - **`core.css`:** delete the `.inline-comments` rule at 404.
  - **`style-selection.css`:** keep only the `.sel-row` and `.sel-cancel` rules from 55–98, and drop the `.sel-composer` box border and placement.
  - **`style.css`:**
    - The read-only list replaces `body.read-only .sel-composer,` with `body.read-only .comment-window,`.
    - Delete `.comment-card.is-calling`. Keep `@keyframes card-calling`.

- [ ] **Step 11: Update the tests of the old boxes.**
  - **`test_smoke_comment_open.py`:**
    - `test_opening_a_comment_still_saves_renders_and_focuses` keeps its four steps.
    - `test_the_refusal_points_at_the_open_card` asserts `revealOpenDraft()` in `openAnnotation` and `AnnotateCommentWindow.call()` in `revealOpenDraft`.
    - `test_the_pulse_can_fire_twice_in_a_row` and `test_the_pulse_is_styled_and_respects_reduced_motion` read `call()` in `comment-window.js` and `.comment-window.is-calling` in CSS.
  - **`test_smoke_export.py:96–98`:** `".comment-window"` instead of the two old names.
  - **`test_smoke_compact.py:82` and `test_smoke_read_only.py:53`:** `"body.read-only .comment-window,"`.
  - **`test_smoke_card_structure.py`:** delete the `.card-close` offset test, since the card has no × now. Add the same reason to its module docstring.

- [ ] **Step 12: Prove two guards.** With `PYTHONDONTWRITEBYTECODE=1`, paste a failing and a passing run for each:
  - Remove the `rangeFor` check from `commit`: `test_words_typed_before_a_rewrite_are_kept` fails. Restore it: it passes.
  - Remove the `resize` listener: `test_a_shrinking_browser_pulls_the_window_back` fails. Restore it: it passes.

- [ ] **Step 13: Run the suite.** It is expected to pass.

- [ ] **Step 14: Check in the browser** on "Delivery listener" at 1500×1000, then at 390×800.
  - Select "After a long outage it starts over with the full list, so nothing is missed." and press Comment. The window's `getBoundingClientRect()` does not intersect the selection's rect.
  - Drag the bar by (−200, −100): `left` and `top` change by exactly that. Drag the corner by (+120, +60): the size grows by that, and `localStorage['annotate.commentWindow.size']` holds it.
  - Narrow the browser to 700 px: the window stays fully inside it.
  - At 390 px, `width` is 358 and `left` is 16.
  - With text typed, Comment on another part's heading: the window pulses, and no second window opens.

- [ ] **Step 15: Commit.**
  `git add` every file under **Files**, then `git commit -m "annotate: every comment opens in one floating window that moves and resizes"`.

---

### Task 7: A selection can cross a heading

**Files:**
- Create: `skills/annotate/static/spans.js`, `skills/annotate/tests/spans.test.cjs`, `skills/annotate/tests/test_spans.py`
- Modify: `skills/annotate/static/entry.js`, `anchors.js` (add `anchorsAcross`), `selection.js` (`openForSelection`, `sameWords`, `openByKeyboard`, `open` refusal), `subunits.js` (`spanKey`, `spanOf`, `overlapping`, `setSpanMark`, `paintSpans`, `spanMarkAt`, `pruneMarks`, `submitRound`)
- Modify: `skills/annotate/references/handling-events.md` (the round section, around 293–318)
- Test: `skills/annotate/tests/test_round_contract.py`, `skills/annotate/tests/test_smoke_subunits.py`

**Interfaces:**
- Consumes: `AnnotateAnchors.anchorFor`, `AnnotateCommentWindow` (Task 6).
- Produces (`AnnotateSpans`):
  - `partsOf(m) -> part[]`. A part is `{block_id, selected_text, prefix, suffix, step_id?}`.
  - `markKey(parts) -> string`. For one part it is exactly today's `spanKey`.
  - `joinQuote(parts) -> string`, joined with `"\n"`.
  - `blockIdsOf(m) -> string[]`.
  - `withSpans(parts) -> anchor`, which is one part as-is, or `{block_id, selected_text, prefix, suffix, spans}`.
  - `textOnly(parts, kindOf, wholeOnly) -> part[]`.
- Also produces `AnnotateAnchors.anchorsAcross(range) -> part[]`. A round reaction carries `spans` when its mark covers more than one part.

- [ ] **Step 1: Write the failing suite.** Create `skills/annotate/tests/spans.test.cjs`:

```js
#!/usr/bin/env node
/* A comment may cover the end of one part and the start of the next.
 * Run: node skills/annotate/tests/spans.test.cjs */
const path = require("path");
const S = require(path.join(__dirname, "..", "static", "spans.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(a, b, what) {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error((what || "") + " expected " + B + ", got " + A);
}
const a = { block_id: "section-10", selected_text: "never with a Jira token.", prefix: "flow, ", suffix: "" };
const b = { block_id: "section-1", selected_text: "Nomad publishes every change", prefix: "", suffix: " to a job" };

test("one part keeps today's key and shape", () => {
  eq(S.markKey([a]), "section-10::__span__::flow, ␟never with a Jira token.␟");
  eq(S.withSpans([a]), a);
  eq(S.partsOf(a), [a]);
});

test("two parts make one mark that names both blocks", () => {
  const m = S.withSpans([a, b]);
  eq(m.block_id, "section-10");
  eq(m.selected_text, "never with a Jira token.\nNomad publishes every change");
  eq(m.spans, [a, b]);
  eq(S.blockIdsOf(m), ["section-10", "section-1"]);
  eq(S.partsOf(m), [a, b]);
});

test("the key of a two-part mark differs from either part's", () => {
  const k = S.markKey([a, b]);
  eq(k === S.markKey([a]) || k === S.markKey([b]), false);
});

test("a picture or a question between the words is left out", () => {
  const pic = { block_id: "section-2", selected_text: "ON START", prefix: "", suffix: "" };
  const kinds = { "section-10": "markdown", "section-2": "sequence", "section-1": "markdown" };
  eq(S.textOnly([a, pic, b], (id) => kinds[id], ["choice", "sequence", "diagram", "flowchart"]), [a, b]);
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
```

  Create `skills/annotate/tests/test_spans.py`, a copy of `test_fold_groups.py` with `SUITE = …"spans.test.cjs"`, the test named `test_spans_suite_passes`, and `>= 4`.

- [ ] **Step 2: Run it and see it fail.** Expected: `Cannot find module`.

- [ ] **Step 3: Implement.** Create `skills/annotate/static/spans.js`:

```js
// annotate — a mark that covers words in more than one part.
//
// A selection may cross a heading. Each part it touches gives one anchor
// (anchors.js anchorsAcross); together they are one mark, and one reaction
// in the round that names every block it covers. A mark on one part keeps
// exactly the shape and key it always had, so nothing stored or sent before
// changes meaning.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateSpans = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function partsOf(m) {
    return m && Array.isArray(m.spans) && m.spans.length ? m.spans : [m];
  }
  function partKey(p) {
    return `${p.block_id}::__span__::${p.prefix || ""}␟${p.selected_text}␟${p.suffix || ""}`;
  }
  function markKey(parts) {
    return parts.map(partKey).join("⁞");
  }
  function joinQuote(parts) {
    return parts.map((p) => p.selected_text).join("\n");
  }
  function blockIdsOf(m) {
    return [...new Set(partsOf(m).map((p) => p.block_id))];
  }
  function withSpans(parts) {
    if (parts.length === 1) return parts[0];
    return { block_id: parts[0].block_id, selected_text: joinQuote(parts),
             prefix: parts[0].prefix || "", suffix: parts[parts.length - 1].suffix || "",
             spans: parts };
  }
  function textOnly(parts, kindOf, wholeOnly) {
    return parts.filter((p) => !wholeOnly.includes(kindOf(p.block_id)));
  }

  return { partsOf, partKey, markKey, joinQuote, blockIdsOf, withSpans, textOnly };
});
```

  In `entry.js`, add `"spans.js",` after `"window-place.js",`.

- [ ] **Step 4: Run it and see it pass.** Expected: `4/4 passed`.

- [ ] **Step 5: Find anchors across parts.** In `anchors.js`, add before the export, and add `anchorsAcross` to it:

```js
  // One anchor per part the range touches, in page order. anchorFor clips
  // the range to each part's prose, so a range that starts in one part and
  // ends in the next gives the tail of the first and the head of the second.
  function anchorsAcross(range) {
    const out = [];
    document.querySelectorAll("main.prose section.block[data-block-id]").forEach((s) => {
      if (!range.intersectsNode(s)) return;
      const a = anchorFor(s, range);
      if (a) out.push(a);
    });
    return out;
  }
```

- [ ] **Step 6: Open the menu on a crossing selection.** In `selection.js`:
  - Delete the `opts.refuse` branch in `open` (179–183) and its `else` wrapper.
  - Delete `trimSpill`. A triple-click spill now yields one part, because the next part contributes no words.
  - `openByKeyboard`'s guard becomes `if (!sectionOf(range.startContainer) && !sectionOf(range.endContainer)) return;`.
  - Replace `openForSelection` and `sameWords` with:

```js
  function kindOf(id) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(id)}"]`)?.dataset.kind || "markdown";
  }

  function openForSelection(range) {
    const s1 = sectionOf(range.startContainer), s2 = sectionOf(range.endContainer);
    if (!s1 && !s2) return close();
    if (s1 && s1 === s2) {
      if (inTitle(range.startContainer) && inTitle(range.endContainer)) return openWhole(s1);
      if (excluded(range.startContainer, s1) && excluded(range.endContainer, s1)) return close();
    }
    // Within one part or across a heading: one anchor per part the words
    // touch, leaving out parts that take no selection (a picture, a question).
    const parts = window.AnnotateSpans.textOnly(A().anchorsAcross(range), kindOf, WHOLE_ONLY);
    if (!parts.length) return close();
    const anchor = window.AnnotateSpans.withSpans(parts);
    const section = sectionOf(range.startContainer) && parts[0].block_id === sectionOf(range.startContainer).dataset.blockId
      ? sectionOf(range.startContainer)
      : document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(parts[0].block_id)}"]`);
    const all = S().overlapping(anchor);
    const same = all.find((x) => sameWords(x.m, anchor));
    const over = all.filter((x) => x !== same);
    const t = { section, anchor, range: range.cloneRange(), whole: false, fromSel: true };
    if (same && !over.length) {
      return open({ ...t, key: same.key }, range.getBoundingClientRect(),
                  { state: `Marked ${same.m.kind}`, removable: true });
    }
    const state = over.length ? `Replaces ${KIND_WORD[over[0].m.kind] || "a mark"}` : "";
    open(t, range.getBoundingClientRect(), { state });
  }

  function sameWords(a, b) {
    const pa = window.AnnotateSpans.partsOf(a), pb = window.AnnotateSpans.partsOf(b);
    if (pa.length !== pb.length) return false;
    return pa.every((p, i) => {
      const q = pb[i];
      if (p.block_id !== q.block_id) return false;
      const s = document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(p.block_id)}"]`);
      const x = s && A().locate(s, p), y = s && A().locate(s, q);
      return !!(x && y && x[0] === y[0] && x[1] === y[1]);
    });
  }
```

  - In `open`, run extras only for one part: `if (extras.length && t && !(t.anchor && t.anchor.spans)) {`.
  - `commentOn` calls `sameWords(x.m, anchor)`.

- [ ] **Step 7: Keep marks per part.** In `subunits.js`, add `const SP = () => window.AnnotateSpans;` and:
  - **`spanKey(a)`** becomes `return SP().markKey(SP().partsOf(a));`.
  - **`spanOf(m)`** locates the first part:

```js
  function locatePart(p) {
    const s = sectionFor(p.block_id);
    return s && window.AnnotateAnchors ? window.AnnotateAnchors.locate(s, p) : null;
  }
  function spanOf(m) { return locatePart(SP().partsOf(m)[0]); }
```

  - **`overlapping(anchor)`:**

```js
  function overlapping(anchor) {
    const want = SP().partsOf(anchor).map((p) => ({ p, span: locatePart(p) })).filter((x) => x.span);
    if (!want.length) return [];
    return Object.entries(marks)
      .filter(([, m]) => isSpan(m) && SP().partsOf(m).some((q) => {
        const qs = locatePart(q);
        return qs && want.some((w) => w.p.block_id === q.block_id && qs[0] < w.span[1] && w.span[0] < qs[1]);
      }))
      .map(([key, m]) => ({ key, m }));
  }
```

  - **`setSpanMark`:** after building `m`, add `if (anchor.spans) m.spans = anchor.spans.map((p) => ({ block_id: p.block_id, selected_text: p.selected_text, prefix: p.prefix || "", suffix: p.suffix || "" }));`.
  - **`paintSpans`:**
    - The first loop pushes one item per part: `for (const p of SP().partsOf(m)) { const section = sectionFor(p.block_id); if (section) items.push({ section, anchor: p, kind: m.kind }); }`.
    - The chip loop reads the last part: `const last = SP().partsOf(m).slice(-1)[0]; const section = sectionFor(last.block_id); const r = section && window.AnnotateAnchors.rangeFor(section, last);`.
  - **`spanMarkAt`:** loop over `SP().partsOf(m)` and test each part whose `block_id` equals the section's.
  - **`pruneMarks`:**
    - The block-gone test is `if (SP().blockIdsOf(m).some((id) => !liveBlockIds.has(id))) {`.
    - The unit test is `if (isSpan(m) && !SP().partsOf(m).every(locatePart)) {`.
  - **`submitRound`:**
    - Inside the map, add `if (m.spans && m.spans.length > 1) r.spans = m.spans;`.
    - `lastSubmittedBlockIds` becomes `[...new Set(reactions.flatMap((r) => r.spans ? r.spans.map((s) => s.block_id) : [r.block_id]))]`.

- [ ] **Step 8: Teach Claude the rule.** In `references/handling-events.md`, in the `reactions` list after the `step_id` bullet, add:

```markdown
  - `spans`, present only when the reader's selection crossed a heading: a
    list of `{block_id, selected_text, prefix, suffix}`, one per block the
    words cover, in page order. `block_id` is the first of them and
    `selected_text` is all of them joined by a newline. The reaction belongs
    to every block in `spans`: group it under each, and rewrite each.
```

  In step 1 of "Apply the WHOLE round", change "Group reactions by `block_id`." to "Group reactions by `block_id`, and a reaction with `spans` under every block it names."

  Append to `test_round_contract.py`:

```python
def test_a_reaction_across_a_heading_belongs_to_every_block_it_names():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "`spans`, present only when the reader's selection crossed a heading" in doc
    assert "a reaction with `spans` under every block it names" in doc
```

- [ ] **Step 9: Guard the page side.** Append to `test_smoke_subunits.py`:

```python
def test_a_crossing_selection_is_marked_not_refused():
    sel = (STATIC / "selection.js").read_text()
    assert "Select within one section" not in sel
    assert "anchorsAcross(range)" in sel


def test_a_round_names_every_block_a_mark_covers():
    sub = (STATIC / "subunits.js").read_text()
    i = sub.index("function submitRound(")
    body = sub[i:sub.index("\n  }\n", i)]
    assert "r.spans = m.spans" in body
    assert "r.spans.map((s) => s.block_id)" in body
```

  If `test_smoke_subunits.py` does not define `STATIC`, add `STATIC = Path(__file__).resolve().parents[1] / "static"`.

- [ ] **Step 10: Prove the round guard.** With `PYTHONDONTWRITEBYTECODE=1`:
  1. Remove `if (m.spans && m.spans.length > 1) r.spans = m.spans;`. `test_a_round_names_every_block_a_mark_covers` fails. Paste it.
  2. Restore the line. The test passes. Paste it.

- [ ] **Step 11: Run the suite.** It is expected to pass.

- [ ] **Step 12: Check in the browser** on "Delivery listener".
  - Select from "Writes to Jira through a PMP Automation flow" to "Nomad publishes every change to a job". The menu opens with no refusal.
  - Comment, and add the comment to the round. `CSS.highlights.get('annotate-comment').size` is `2`.
  - One `.sel-chip` sits in section-1.
  - The dock lists one row. Submitting sends one reaction whose `spans` has two entries. Read it from the event file under the workspace's `state/events`.
  - Both parts get the updating overlay.
  - A selection from section-1's last paragraph into the sequence diagram below yields one part, section-1's.

- [ ] **Step 13: Commit.**
  `git add skills/annotate/static/spans.js skills/annotate/static/entry.js skills/annotate/static/anchors.js skills/annotate/static/selection.js skills/annotate/static/subunits.js skills/annotate/references/handling-events.md skills/annotate/tests/spans.test.cjs skills/annotate/tests/test_spans.py skills/annotate/tests/test_round_contract.py skills/annotate/tests/test_smoke_subunits.py && git commit -m "annotate: a selection can cross a heading, and its comment covers every part it touches"`

---

### Task 8: The words and the docs match the page

**Files:**
- Modify: `skills/annotate/static/shell.js` (search input), `skills/annotate/static/search.js` (158)
- Modify: `skills/annotate/references/pushing.md` (219 and every "card" or "section header" wording about titles)
- Modify: `skills/annotate/SKILL.md` (maintainer notes), `skills/annotate/README.md`, `skills/annotate/docs/gallery.html`, `CLAUDE.md` (repo root)
- Test: `skills/annotate/tests/test_smoke_block_search.py`

- [ ] **Step 1: Write the failing test.** Append to `test_smoke_block_search.py`:

```python
def test_search_does_not_name_blocks():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "static"
    shell = (static / "shell.js").read_text()
    assert 'placeholder="Search…"' in shell and "Search blocks" not in shell
    assert " blocks" not in (static / "search.js").read_text().split("ensureCountEl()", 1)[1][:400]
```

- [ ] **Step 2: Run it and see it fail.**

- [ ] **Step 3: Implement.**
  - **`shell.js`:** `placeholder="Search…"` and `aria-label="Search"`.
  - **`search.js` 158:** `el.textContent = matched.size + " of " + sections.length + " match";`
  - **`pushing.md` 219:** replace the title sentence with: "Each block may carry a **`title`**, a 2–5 word noun phrase. A title is shown as a heading in the text, and a heading starts a part the reader can fold. Give one where a reader needs a heading, and leave it out where the text simply continues from the block above. Do not repeat a title as a leading `#`/`##` heading in the block's markdown." Then grep `pushing.md` for `card` and `section header` and fix each sentence about titles the same way.
  - **`SKILL.md` maintainer notes:** add `no-sections-design.md` (the decision record for the page without sections) and `no-sections-plan.md`.
  - **`README.md`:** replace any sentence that says the page shows cards or sections.
  - **`docs/gallery.html`:** rebuild it the way its header says. Open it, and check that each kind renders without a card.
  - **Repo `CLAUDE.md`:** add one paragraph to the one about the page: "The annotate page never shows a block: a block renders as part of one document (`createBlockSection`), an authored title is an `h2` (`visibleTitle`), folding goes by heading (`fold-groups.js`), and every comment opens in the one floating window (`comment-window.js`). Text the reader sees says "part", never "section" or "block"."

- [ ] **Step 4: Run the suite.** It is expected to pass.

- [ ] **Step 5: Run `/audit-docs-truth` and `/audit-tests`.** Fix what they report about the files this plan touched.

- [ ] **Step 6: Commit.**
  `git add skills/annotate/static/shell.js skills/annotate/static/search.js skills/annotate/references/pushing.md skills/annotate/SKILL.md skills/annotate/README.md skills/annotate/docs/gallery.html CLAUDE.md skills/annotate/tests/test_smoke_block_search.py && git commit -m "annotate: search, docs and the push contract describe a page without sections"`
