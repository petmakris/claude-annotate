# Selection menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace annotate's two feedback strips with one menu that opens on any text selection. It offers Comment, Delete and Compact on exactly the selected words, or on the whole section when the title is selected.

**Architecture:**
- `anchors.js` (new) turns a DOM Range into a text anchor (`selected_text` plus 32 characters of `prefix`/`suffix`) and back. It paints marks with the CSS Custom Highlight API, so the page's DOM is never wrapped or split.
- `subunits.js` keeps the round (store, dock, submit) and gains span marks keyed by their anchor. It loses the per-sentence strip.
- `selection.js` (new) owns the menu, the span comment box and the keyboard.
- `script.js` loses the card-header strip.

The round's wire format does not change.

**Tech Stack:** Vanilla JS (no bundler), loaded in order by `skills/annotate/static/entry.js`. CSS Custom Highlight API. pytest with Playwright (browser tests skip when Playwright is absent, as in CI).

**Spec:** `docs/superpowers/specs/2026-10-01-selection-menu-and-speech-design.md`, §2 (decisions A2, B3, no title buttons), §3.1–3.3, §4.1–4.3, §6, §7.

**Later plans build on this:** read-aloud (Plan 3) adds the Explain split button and editing (Plan 4) adds ✎ Edit, both through `AnnotateSelection.registerAction` (Task 3). This plan ships the menu with the three feedback buttons only.

## Global Constraints

- Menu shape A2, in this order: Comment, Delete, Compact. Icons are the line SVGs from `script.js`'s current `ICON` object (moved, not redrawn). Each button has a tooltip and an `aria-label` naming its action and key.
- Keys while the menu is open and focus is not in a text field: `c` comment, `d` delete, `x` compact, `Esc` close. With no menu, no selection, and a block focused by `j`/`k`: `c` (unchanged), `d` and `x` act on the whole section.
- B3: nothing happens until the reader selects. A plain click on prose does nothing. A click on an existing mark opens the menu showing that mark.
- Selecting any part of a section's title selects the whole section: a 2px accent outline, and the menu's first item reads `Whole section`.
- A selection crossing two sections opens a one-line menu: `Select within one section`.
- A new mark that overlaps an existing span mark in the same block replaces it. Before anything is pressed, the menu names what will be replaced (`Replaces a delete`).
- Pressing the same kind again on the same span removes that mark (undo), as the strip did.
- Anchors: `selected_text` is trimmed of surrounding whitespace. `prefix` and `suffix` are always sent, up to 32 characters each. `step_id` is the nearest enclosing `data-annotate-id` inside the block content.
- Marks never wrap or split DOM text. Painting uses the Highlight registries `annotate-delete`, `annotate-compact`, `annotate-comment` and `annotate-scope`.
- No menu: on a read-only page (`body.read-only`), while the reading highlighter is on (`body[data-highlighter="on"]`), inside a choice block's options (`section.block[data-kind="choice"] .block-content`), inside a code pane (`.code-col`), or in a browser without `CSS.highlights`.
- The round wire shape is unchanged: `{scope, kind, block_id, selected_text, text, images, step_id?, prefix?, suffix?}`.
- Commit messages are one line, with no body and no trailers.
- Test command: `cd <worktree> && uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`. Daemon-backed browser tests live in `skills/annotate/tests/test_browser_review.py` and need the local daemon. `uv run -q --with playwright python -m playwright install chromium` fetches a browser if one is missing.

## Review Focus

1. **Selections that start or end on element boundaries** (a triple-click on a paragraph, a drag from the margin, a select-all inside a list item). The anchor must still resolve to the visible words. Pinned in Task 1 (`anchorFor` on an element-bounded range).
2. **The same words appearing twice in one block** ("the draft", "EDR"). The mark must land on the occurrence that was selected, after a reload too. Pinned in Task 1 (`locate` picks by prefix/suffix) and Task 3 (browser).
3. **Claude rewrites the block while a mark is pending.** A delete or compact whose words are gone is dropped. A comment moves to the whole section, quoting the old words, and is never lost. Pinned in Task 2.
4. **A fast double-click on a title.** The second mouseup must not close the menu the first one opened, as the mockup showed. Pinned in Task 3.
5. **Glossary and search re-render text nodes.** Marks must still paint after the glossary popover redecorates or a search highlights hits. Pinned in Task 3 by repainting on `annotate:rendered` and after glossary decoration.

---

### Task 1: `anchors.js`, from selection to anchor and back

**Files:**
- Create: `skills/annotate/static/anchors.js`
- Modify: `skills/annotate/static/entry.js` (load `anchors.js` before `script.js`)
- Modify: `skills/annotate/static/highlighter.js` (use `AnnotateAnchors` for the walker, offsets and ranges)
- Test: `skills/annotate/tests/test_browser_anchors.py` (new; runs in a bare browser, no daemon)

**Interfaces:**
- Produces `window.AnnotateAnchors`:
  - `supported() -> boolean`
  - `contentOf(section) -> Element|null`, which is `section.querySelector(".block-content")`
  - `textOf(root) -> string`
  - `offsetsOf(root, range) -> [start, end] | null`
  - `rangeFrom(root, start, end) -> Range | null`
  - `anchorFor(section, range) -> {block_id, selected_text, prefix, suffix, step_id?} | null`
  - `locate(section, anchor) -> [start, end] | null`
  - `rangeFor(section, anchor) -> Range | null`
  - `offsetAt(root, clientX, clientY) -> number | null`
  - `paint(items)`, where `items` is `[{section, anchor, kind}]` and `kind` is one of `delete`, `compact`, `comment`
  - `setScope(range | null)`
  - `SKIP` (selector string)

- [ ] **Step 1: Write the failing tests**

```python
# skills/annotate/tests/test_browser_anchors.py
"""AnnotateAnchors in a bare page: no daemon, no annotate shell. The module
is pure DOM + text, so it is tested against the smallest page that has the
shape it reads (section.block > .block-content)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"

PAGE = """<!doctype html><main class="prose">
<section class="block" data-block-id="b1"><div class="card-head"><span class="card-title">T</span></div>
<div class="block-content"><p id="p1">The draft leaves it open. <b>EDR</b> confirms.</p>
<ol><li data-annotate-id="client-split" id="li1">Which clients. The draft leaves it open.</li></ol>
<span class="sel-chip">💬 a chip that is UI, not prose</span></div></section></main>"""


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content(PAGE)
        pg.add_script_tag(path=str(STATIC / "anchors.js"))
        yield pg
        b.close()


def _anchor(page, js_range):
    return page.evaluate(f"""() => {{
      const s = document.querySelector('section.block');
      const r = document.createRange(); {js_range}
      return AnnotateAnchors.anchorFor(s, r); }}""")


def test_prose_text_skips_ui_inside_the_content(page):
    t = page.evaluate("() => AnnotateAnchors.textOf(document.querySelector('.block-content'))")
    assert "a chip that is UI" not in t
    assert "The draft leaves it open. EDR confirms." in t


def test_an_anchor_carries_trimmed_text_context_and_step_id(page):
    a = _anchor(page, """const t = document.getElementById('li1').firstChild;
                         r.setStart(t, 14); r.setEnd(t, 40);""")
    assert a["selected_text"] == "The draft leaves it open."
    assert a["block_id"] == "b1"
    assert a["step_id"] == "client-split"
    assert a["prefix"].rstrip().endswith("Which clients.")
    assert len(a["prefix"]) <= 32 and len(a["suffix"]) <= 32


def test_an_element_bounded_range_still_anchors_to_its_words(page):
    a = _anchor(page, "r.selectNodeContents(document.getElementById('p1'));")
    assert a["selected_text"] == "The draft leaves it open. EDR confirms."
    assert "step_id" not in a


def test_whitespace_only_selection_is_no_anchor(page):
    a = _anchor(page, """const t = document.getElementById('p1').firstChild;
                         r.setStart(t, 25); r.setEnd(t, 26);""")
    assert a is None


def test_the_second_of_two_identical_phrases_is_found_by_its_context(page):
    out = page.evaluate("""() => {
      const s = document.querySelector('section.block');
      const t = document.getElementById('li1').firstChild;
      const r = document.createRange(); r.setStart(t, 15); r.setEnd(t, 24);
      const a = AnnotateAnchors.anchorFor(s, r);
      const span = AnnotateAnchors.locate(s, a);
      const text = AnnotateAnchors.textOf(AnnotateAnchors.contentOf(s));
      return {sel: a.selected_text, first: text.indexOf('the draft'.replace('t','T')), span};
    }""")
    assert out["sel"] == "The draft"
    assert out["span"][0] > out["first"], "located the first 'The draft', not the selected one"


def test_a_vanished_anchor_locates_nothing(page):
    span = page.evaluate("""() => AnnotateAnchors.locate(document.querySelector('section.block'),
        {block_id: 'b1', selected_text: 'words that are not there', prefix: '', suffix: ''})""")
    assert span is None


def test_paint_registers_one_highlight_per_kind(page):
    sizes = page.evaluate("""() => {
      const s = document.querySelector('section.block');
      const t = document.getElementById('p1').firstChild;
      const r = document.createRange(); r.setStart(t, 0); r.setEnd(t, 9);
      const a = AnnotateAnchors.anchorFor(s, r);
      AnnotateAnchors.paint([{section: s, anchor: a, kind: 'delete'}]);
      return ['delete','compact','comment'].map(k => CSS.highlights.get('annotate-' + k).size);
    }""")
    assert sizes == [1, 0, 0]


def test_offset_at_a_point_maps_into_prose_text(page):
    off = page.evaluate("""() => {
      const p = document.getElementById('p1').getBoundingClientRect();
      return AnnotateAnchors.offsetAt(document.querySelector('.block-content'), p.left + 2, p.top + p.height / 2);
    }""")
    assert off is not None and 0 <= off <= 2
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with playwright python -m pytest skills/annotate/tests/test_browser_anchors.py -q -n 0`
Expected: every test errors in the fixture with `Error: ENOENT ... anchors.js` (the file does not exist yet).

- [ ] **Step 3: Write `anchors.js`**

```javascript
// skills/annotate/static/anchors.js
/* Anchors: a selection on the page ⇄ the words it covers.
 *
 * A mark has to survive what the page does to its own DOM: Claude rewrites
 * a block's innerHTML, the glossary wraps terms in spans and unwraps them
 * again, search inserts <mark> and normalises it away. So a mark is never
 * stored as a DOM Range. It is stored as text: the selected words plus up to
 * 32 characters either side, and found again by searching the block's prose
 * for those words and preferring the occurrence whose surroundings match.
 *
 * Prose is counted by ONE walker that skips UI living inside a block's
 * content (the comment box and chips). Storing and finding must agree on
 * that text exactly, or a mark comes back on the wrong words.
 *
 * Marks are painted with the CSS Custom Highlight API, so nothing here ever
 * wraps or splits the page's text nodes either.
 */
(function () {
  "use strict";

  const SKIP = ".sel-composer, .sel-chip, .inline-comments, .code-col, .card-head";
  const CONTEXT = 32;
  const KINDS = ["delete", "compact", "comment"];

  function supported() {
    return typeof CSS !== "undefined" && !!CSS.highlights && typeof Highlight === "function";
  }
  function contentOf(section) {
    return section ? section.querySelector(".block-content") : null;
  }

  function walker(root) {
    return document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const p = node.parentElement;
        return p && p.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
  }

  function textOf(root) {
    const w = walker(root);
    let out = "", n;
    while ((n = w.nextNode())) out += n.textContent;
    return out;
  }

  // A DOM range → [start, end] over prose text, or null when it does not
  // fall in this root's prose. Element endpoints (a triple-click, a
  // select-all) are resolved to the extent of the text nodes they touch.
  function offsetsOf(root, range) {
    const w = walker(root);
    let seen = 0, start = null, end = null, lo = null, hi = null, n;
    while ((n = w.nextNode())) {
      const len = n.textContent.length;
      if (n === range.startContainer) start = seen + range.startOffset;
      if (n === range.endContainer) end = seen + range.endOffset;
      if (range.intersectsNode(n)) { if (lo === null) lo = seen; hi = seen + len; }
      seen += len;
    }
    if (start === null) start = lo;
    if (end === null) end = hi;
    if (start === null || end === null || end <= start) return null;
    return [start, end];
  }

  function rangeFrom(root, start, end) {
    const w = walker(root);
    const range = document.createRange();
    let seen = 0, haveStart = false, n;
    while ((n = w.nextNode())) {
      const len = n.textContent.length;
      if (!haveStart && start < seen + len) { range.setStart(n, start - seen); haveStart = true; }
      if (haveStart && end <= seen + len) { range.setEnd(n, end - seen); return range; }
      seen += len;
    }
    return null;
  }

  function anchorFor(section, range) {
    const root = contentOf(section);
    if (!root || !section.dataset.blockId) return null;
    const span = offsetsOf(root, range);
    if (!span) return null;
    const text = textOf(root);
    let [s, e] = span;
    while (s < e && /\s/.test(text[s])) s++;
    while (e > s && /\s/.test(text[e - 1])) e--;
    if (e <= s) return null;
    const a = {
      block_id: section.dataset.blockId,
      selected_text: text.slice(s, e),
      prefix: text.slice(Math.max(0, s - CONTEXT), s),
      suffix: text.slice(e, e + CONTEXT),
    };
    const c = range.commonAncestorContainer;
    const el = c.nodeType === 1 ? c : c.parentElement;
    const authored = el && el.closest("[data-annotate-id]");
    if (authored && root.contains(authored)) a.step_id = authored.dataset.annotateId;
    return a;
  }

  function commonTail(a, b) {
    let i = 0;
    while (i < a.length && i < b.length && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
    return i;
  }
  function commonHead(a, b) {
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i++;
    return i;
  }

  // Every occurrence of the words, scored by how much of the stored context
  // still surrounds it; the best wins, the first on a tie.
  function locate(section, anchor) {
    const root = contentOf(section);
    if (!root || !anchor || !anchor.selected_text) return null;
    const text = textOf(root);
    const want = anchor.selected_text, pre = anchor.prefix || "", suf = anchor.suffix || "";
    let best = -1, bestScore = -1, i = -1;
    while ((i = text.indexOf(want, i + 1)) !== -1) {
      const score = commonTail(text.slice(Math.max(0, i - pre.length), i), pre)
        + commonHead(text.slice(i + want.length, i + want.length + suf.length), suf);
      if (score > bestScore) { best = i; bestScore = score; }
    }
    return best < 0 ? null : [best, best + want.length];
  }

  function rangeFor(section, anchor) {
    const span = locate(section, anchor);
    return span ? rangeFrom(contentOf(section), span[0], span[1]) : null;
  }

  // The prose offset under a point, or null when the point is not on prose.
  function offsetAt(root, x, y) {
    let node = null, off = 0;
    if (document.caretPositionFromPoint) {
      const p = document.caretPositionFromPoint(x, y);
      if (p) { node = p.offsetNode; off = p.offset; }
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (r) { node = r.startContainer; off = r.startOffset; }
    }
    if (!node || node.nodeType !== 3 || !root.contains(node)) return null;
    const w = walker(root);
    let seen = 0, n;
    while ((n = w.nextNode())) {
      if (n === node) return seen + off;
      seen += n.textContent.length;
    }
    return null;
  }

  function registry(name) {
    let h = CSS.highlights.get(name);
    if (!h) { h = new Highlight(); CSS.highlights.set(name, h); }
    return h;
  }

  function paint(items) {
    if (!supported()) return;
    for (const k of KINDS) registry("annotate-" + k).clear();
    for (const it of items || []) {
      if (KINDS.indexOf(it.kind) < 0) continue;
      const r = rangeFor(it.section, it.anchor);
      if (r) registry("annotate-" + it.kind).add(r);
    }
  }

  function setScope(range) {
    if (!supported()) return;
    const h = registry("annotate-scope");
    h.clear();
    if (range) h.add(range);
  }

  window.AnnotateAnchors = {
    SKIP, supported, contentOf, textOf, offsetsOf, rangeFrom, anchorFor,
    locate, rangeFor, offsetAt, paint, setScope,
  };
})();
```

- [ ] **Step 4: Run the tests and see them pass**

Run: the command from Step 2.
Expected: `8 passed`.

- [ ] **Step 5: Load it, and make the highlighter use it**

In `skills/annotate/static/entry.js`, add `"anchors.js"` to the script list immediately before `"script.js"`. Keep the existing list's quoting and format exactly.

In `skills/annotate/static/highlighter.js`:
- Delete its own `SKIP` constant, `proseWalker`, `offsetsOf`, `elementBounds` and `rangeFrom`.
- Replace their uses with `window.AnnotateAnchors.offsetsOf(root, range)` and `window.AnnotateAnchors.rangeFrom(root, s, e)`.
- Change its header comment's paragraph about `.unit-strip` offsets to: "Offsets are counted over prose only, by AnnotateAnchors' one walker, which the selection menu's marks also use — if storing and restoring ever disagreed, a highlight would reload onto the wrong words."
- Keep its `.code-col` early return as it is.

- [ ] **Step 6: Run the whole suite**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`
Expected: everything passes. That includes the existing highlighter tests, because the walker change only drops strip selectors and adds `.sel-composer` / `.sel-chip`, which do not exist yet.

- [ ] **Step 7: Commit**

```bash
git add skills/annotate/static/anchors.js skills/annotate/static/entry.js skills/annotate/static/highlighter.js skills/annotate/tests/test_browser_anchors.py
git commit -m "feat(annotate): anchors turn any selection into words-plus-context and paint marks without touching the DOM"
```

---

### Task 2: span marks in the round store

**Files:**
- Modify: `skills/annotate/static/subunits.js`
- Test: `skills/annotate/tests/test_browser_review.py` (append; daemon-backed)

**Interfaces:**
- Consumes: `AnnotateAnchors.locate`, `rangeFor`, `paint`, `setScope`, `contentOf`, `offsetAt` (Task 1).
- Produces these additions to `window.AnnotateSubunits`:
  - `setSpanMark(anchor, kind, text?) -> void`. `kind` is `delete`, `compact` or `comment`. Calling it again with the same anchor and kind and no `text` removes the mark.
  - `overlapping(anchor) -> [{key, m}]`, the existing span marks in the same block whose located spans overlap the anchor's.
  - `spanMarkAt(section, clientX, clientY) -> {key, m} | null`
  - `removeMarkByKey(key) -> void`
  - `paintSpans() -> void`
- Span mark object: `{scope: "unit", block_id, kind, selected_text, prefix, suffix, step_id?, text?}`.
- Span key: `` `${block_id}::__span__::${prefix}␟${selected_text}␟${suffix}` `` (U+241F is the visible separator symbol, which cannot occur in a mark's own words).

- [ ] **Step 1: Write the failing browser tests**

```python
# append to skills/annotate/tests/test_browser_review.py

def _anchor_of(page, anchor, needle):
    """Anchor for the first occurrence of `needle` in a block, built the way
    the selection menu will build it."""
    return page.evaluate("""([sel, needle]) => {
      const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s);
      const i = AnnotateAnchors.textOf(root).indexOf(needle);
      return AnnotateAnchors.anchorFor(s, AnnotateAnchors.rangeFrom(root, i, i + needle.length));
    }""", [SEL.format(anchor), needle])


def _round(page):
    return json.loads(page.evaluate(
        "() => localStorage.getItem('annotate.round.resp-browser-suite')") or "{}")


def test_a_span_mark_goes_into_the_round_with_its_context(page):
    a = _anchor_of(page, "section-1", "long enough")
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'compact')", a)
    [m] = _round(page).values()
    assert m["scope"] == "unit" and m["kind"] == "compact"
    assert m["selected_text"] == "long enough"
    assert m["prefix"].endswith("Paragraph one of block 1, ")
    assert m["suffix"].startswith(" to scroll past.")
    assert page.evaluate("() => CSS.highlights.get('annotate-compact').size") == 1


def test_the_same_kind_on_the_same_span_takes_the_mark_back(page):
    a = _anchor_of(page, "section-1", "long enough")
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    assert _round(page) == {}
    assert page.evaluate("() => CSS.highlights.get('annotate-delete').size") == 0


def test_an_overlapping_mark_replaces_the_old_one(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-1", "long enough to scroll"))
    b = _anchor_of(page, "section-1", "enough to scroll past")
    assert [x["m"]["kind"] for x in page.evaluate("b => AnnotateSubunits.overlapping(b)", b)] == ["delete"]
    page.evaluate("b => AnnotateSubunits.setSpanMark(b, 'compact')", b)
    marks = list(_round(page).values())
    assert [(m["kind"], m["selected_text"]) for m in marks] == [("compact", "enough to scroll past")]


def test_span_marks_survive_a_reload_and_repaint(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'comment', 'why?')",
                  _anchor_of(page, "section-2", "Paragraph two"))
    page.reload()
    page.wait_for_function("() => !!window.AnnotateSubunits")
    page.wait_for_function("() => CSS.highlights.get('annotate-comment')?.size === 1", timeout=5000)


def test_a_rewritten_block_drops_a_delete_and_moves_a_comment_to_the_section(page, document):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-3", "Paragraph one"))
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'comment', 'keep this point')",
                  _anchor_of(page, "section-3", "Paragraph two"))
    _put_block(document, "section-3", "Entirely new words.", title="Block 3")
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-3')}').textContent.includes('Entirely new')",
        timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate("() => AnnotateSubunits.renderDock()")
    marks = list(_round(page).values())
    assert [m["kind"] for m in marks] == ["comment"]
    assert marks[0]["scope"] == "block"
    assert "Paragraph two" in marks[0]["text"] and "keep this point" in marks[0]["text"]


def test_a_mark_is_found_by_the_point_it_is_painted_at(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-1", "long enough"))
    hit = page.evaluate("""(sel) => {
      const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFor(s, Object.values(JSON.parse(
          localStorage.getItem('annotate.round.resp-browser-suite')))[0]);
      const b = r.getBoundingClientRect();
      return AnnotateSubunits.spanMarkAt(s, b.left + 3, b.top + b.height / 2)?.m.kind;
    }""", SEL.format("section-1"))
    assert hit == "delete"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with playwright python -m pytest skills/annotate/tests/test_browser_review.py -q -n 0 -k "span or overlapping or rewritten_block or point_it_is"`
Expected: each fails with `TypeError: AnnotateSubunits.setSpanMark is not a function` (or `spanMarkAt`, `overlapping`).

- [ ] **Step 3: Implement the span store in `subunits.js`**

Add, next to `blockMarkKey`:

```javascript
  // A span mark is keyed by the words AND their surroundings, so the same
  // words twice in one block are two marks. U+241F cannot occur in prose a
  // reader selected, which keeps the three parts unambiguous.
  function spanKey(a) {
    return `${a.block_id}::__span__::${a.prefix || ""}␟${a.selected_text}␟${a.suffix || ""}`;
  }
  function isSpan(m) {
    return m && m.scope === "unit" && !!m.selected_text && m.kind !== "choice";
  }
  function sectionFor(blockId) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(blockId)}"]`);
  }
  function spanOf(m) {
    const s = sectionFor(m.block_id);
    return s && window.AnnotateAnchors ? window.AnnotateAnchors.locate(s, m) : null;
  }

  function overlapping(anchor) {
    const mine = spanOf(anchor);
    if (!mine) return [];
    return Object.entries(marks)
      .filter(([, m]) => isSpan(m) && m.block_id === anchor.block_id)
      .map(([key, m]) => ({ key, m, span: spanOf(m) }))
      .filter((x) => x.span && x.span[0] < mine[1] && mine[0] < x.span[1])
      .map(({ key, m }) => ({ key, m }));
  }

  function setSpanMark(anchor, kind, text) {
    const key = spanKey(anchor);
    const existing = marks[key];
    if (existing && existing.kind === kind && !text) {
      delete marks[key];                                // undo
    } else {
      for (const { key: k } of overlapping(anchor)) delete marks[k];
      const m = { scope: "unit", block_id: anchor.block_id, kind,
                  selected_text: anchor.selected_text,
                  prefix: anchor.prefix || "", suffix: anchor.suffix || "" };
      if (anchor.step_id) m.step_id = anchor.step_id;
      if (text) m.text = text;
      marks[key] = m;
    }
    saveMarks();
    paintSpans();
    renderDock();
  }

  function paintSpans() {
    if (!window.AnnotateAnchors) return;
    const items = [];
    for (const m of Object.values(marks)) {
      if (!isSpan(m)) continue;
      const section = sectionFor(m.block_id);
      if (section) items.push({ section, anchor: m, kind: m.kind });
    }
    window.AnnotateAnchors.paint(items);
  }

  function spanMarkAt(section, x, y) {
    const root = window.AnnotateAnchors?.contentOf(section);
    if (!root) return null;
    const off = window.AnnotateAnchors.offsetAt(root, x, y);
    if (off === null) return null;
    for (const [key, m] of Object.entries(marks)) {
      if (!isSpan(m) || m.block_id !== section.dataset.blockId) continue;
      const sp = spanOf(m);
      if (sp && sp[0] <= off && off < sp[1]) return { key, m };
    }
    return null;
  }
```

Then change these existing functions:

1. **`pruneMarks`.** Replace the unit branch (the block starting `const content = contentByBlock.get(m.block_id);` through its closing brace) with:

```javascript
      if (isSpan(m) && !spanOf(m)) {
        // The words it pointed at were rewritten. A bare delete/compact has
        // nothing left to act on and goes. A comment is words the reader
        // wrote, so it is never dropped in silence: it moves to the whole
        // section, quoting the text it was about.
        if (m.text) marks[orphanMarkKey(m)] = orphaned(m);
        delete marks[key];
        pruned = true;
      }
```

   Remove the now-unused `contentByBlock` map. Keep the rest of the function unchanged, including the `if (m.step_id) continue;` line, but move that line *below* the new span check so that span marks inside an authored item are re-resolved too. Then change the guard above it from `if (m.scope && m.scope !== "unit") continue;` to `if (m.scope && m.scope !== "unit") continue;` followed by `if (!isSpan(m) && m.step_id) continue;`.

2. **`orphanMarkKey`.** Replace `${m.ordinal || 0}` with `${m.prefix || ""}`.

3. **`markRows`.** Sort within a block by `(spanOf(a.m)?.[0] ?? -1) - (spanOf(b.m)?.[0] ?? -1)` instead of by `ordinal`.

4. **`jumpToMark`.** When `isSpan(m)`, resolve `AnnotateAnchors.rangeFor(s, m)`. If it resolves, scroll so the range is centred (`window.scrollBy(0, rect.top + rect.height / 2 - innerHeight / 2)` with `behavior: "smooth"`), flash it with `AnnotateAnchors.setScope(range)`, and clear it after 1200 ms with `setScope(null)`. Otherwise keep the existing whole-section scroll and `rd-flash`.

5. **`removeMark`, `clearRound`, `repaintAll`.** Call `paintSpans()` alongside their existing repaint calls. Leave the `.sub-unit` loops in place for now; Task 5 removes them.

6. **`pinComment`.** The key becomes `step_id ? stepMarkKey(...) : (selected_text ? spanKey({block_id, selected_text, prefix, suffix}) : blockMarkKey(block_id))`, and `scope` is `"unit"` whenever `step_id || selected_text`. This stops a quoted comment from overwriting the section's mark.

7. **Repaint after render.** At the bottom, after the boot catch-up, add:

```javascript
  // Every render path ends with this event (loadAndRenderBlocks, reconcile).
  // Ranges are rebuilt from text each time, so a rewrite, a glossary pass or
  // a search never leaves a mark painted on stale nodes.
  document.addEventListener("annotate:rendered", () => { paintSpans(); renderDock(); });
  armBootTimer();
  paintSpans();
```

8. **Exports.** Add `setSpanMark, overlapping, spanMarkAt, removeMarkByKey: removeMark, paintSpans` to `window.AnnotateSubunits`.

- [ ] **Step 4: Run the new tests, then the whole suite**

Run: the command from Step 2. Expected: `6 passed`.
Then: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`. Expected: all green. The strips still exist and are untouched in behaviour.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/static/subunits.js skills/annotate/tests/test_browser_review.py
git commit -m "feat(annotate): the round keeps marks on any span, keyed by their words and surroundings"
```

---

### Task 3: `selection.js`, the menu

**Files:**
- Create: `skills/annotate/static/selection.js`
- Modify: `skills/annotate/static/entry.js` (load `selection.js` after `subunits.js`)
- Modify: `skills/annotate/static/script.js` (expose `AnnotatePage.openComment(blockId)`, and repaint spans after glossary redecoration)
- Modify: `skills/annotate/static/style.css` (menu, composer, chip, highlight paint)
- Test: `skills/annotate/tests/test_browser_review.py` (append)

**Interfaces:**
- Consumes: `AnnotateAnchors.*` (Task 1); `AnnotateSubunits.setSpanMark`, `overlapping`, `spanMarkAt`, `removeMarkByKey`, `toggleBlockMark`, `blockMark` (Task 2 and existing).
- Produces `window.AnnotateSelection`:
  - `isOpen() -> boolean`
  - `close() -> void`
  - `registerAction(fn)`. Every registered `fn(target, menuEl)` is called, in registration order, on every menu open that has a target, after a divider the menu adds once. `target` is `{section, anchor | null, range, whole: boolean}`. Each `fn` appends its own buttons to `menuEl` and may append nothing. Plan 3 registers Explain and Plan 4 registers ✎ Edit. Nothing calls it in this plan.
- Produces `window.AnnotatePage.openComment(blockId) -> void` (script.js), which opens the existing comment card for the whole section.

- [ ] **Step 1: Write the failing browser tests**

```python
# append to skills/annotate/tests/test_browser_review.py

def _release(page, x=None, y=None):
    """A mouseup where a drag would end. `page.mouse.up()` without a matching
    down is not a reliable mouseup in Chromium, so the event is dispatched on
    the element under the point (or <body>) with its coordinates."""
    page.evaluate("""([x, y]) => {
      const el = (x === null ? null : document.elementFromPoint(x, y)) || document.body;
      el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, clientX: x || 0, clientY: y || 0}));
    }""", [x, y])


def _select(page, anchor, needle, nth=0):
    """Select the nth occurrence of `needle` in a block, as a drag would,
    then release the mouse over it so the page sees a real mouseup."""
    box = page.evaluate("""([sel, needle, nth]) => {
      const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s);
      const text = AnnotateAnchors.textOf(root);
      let i = -1; for (let k = 0; k <= nth; k++) i = text.indexOf(needle, i + 1);
      const r = AnnotateAnchors.rangeFrom(root, i, i + needle.length);
      const sel2 = getSelection(); sel2.removeAllRanges(); sel2.addRange(r);
      const b = r.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2};
    }""", [SEL.format(anchor), needle, nth])
    _release(page, box["x"], box["y"])
    page.wait_for_selector(".sel-menu", timeout=3000)


def _menu(page, kind):
    page.click(f'.sel-menu button[data-act="{kind}"]')


def test_selecting_words_opens_the_menu_and_delete_marks_exactly_them(page):
    _select(page, "section-1", "long enough")
    labels = page.eval_on_selector_all(".sel-menu button", "bs => bs.map(b => b.dataset.act)")
    assert labels == ["comment", "delete", "compact"]
    _menu(page, "delete")
    [m] = _round(page).values()
    assert (m["kind"], m["selected_text"]) == ("delete", "long enough")
    assert page.locator(".sel-menu").count() == 0


def test_a_plain_click_on_prose_opens_nothing(page):
    page.click(SEL.format("section-1") + " .block-content p")
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_the_keys_act_on_the_selection(page):
    _select(page, "section-2", "Paragraph two")
    page.keyboard.press("x")
    [m] = _round(page).values()
    assert m["kind"] == "compact"


def test_comment_opens_a_box_quoting_the_selection_and_pins_it(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    box = page.locator(".sel-composer")
    assert "long enough" in box.locator(".sel-quote").inner_text()
    box.locator("textarea").fill("is it though?")
    box.locator("textarea").press("Enter")
    [m] = _round(page).values()
    assert (m["kind"], m["text"], m["selected_text"]) == ("comment", "is it though?", "long enough")
    assert page.locator(".sel-chip").count() == 1


def test_a_title_double_click_scopes_the_whole_section(page):
    page.dblclick(SEL.format("section-2") + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=3000)
    page.wait_for_timeout(150)          # the second mouseup of the double-click
    assert page.locator(".sel-menu").count() == 1
    assert "Whole section" in page.inner_text(".sel-menu")
    assert page.locator(SEL.format("section-2") + "[data-sel-scope]").count() == 1
    _menu(page, "delete")
    assert page.locator(SEL.format("section-2") + '[data-block-mark="delete"]').count() == 1


def test_a_selection_across_two_sections_is_refused(page):
    page.evaluate("""() => {
      const a = document.querySelectorAll('section.block .block-content p');
      const r = document.createRange(); r.setStart(a[0].firstChild, 0); r.setEnd(a[2].firstChild, 5);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""")
    _release(page)
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert "Select within one section" in page.inner_text(".sel-menu")
    assert page.locator(".sel-menu button[data-act]").count() == 0


def test_the_menu_says_what_a_new_mark_replaces(page):
    _select(page, "section-1", "long enough to scroll")
    _menu(page, "delete")
    _select(page, "section-1", "enough to scroll past")
    assert "Replaces a delete" in page.inner_text(".sel-menu")


def test_clicking_a_mark_opens_its_state_and_can_remove_it(page):
    _select(page, "section-1", "long enough")
    _menu(page, "compact")
    page.evaluate("() => getSelection().removeAllRanges()")
    pos = page.evaluate("""(sel) => {
      const s = document.querySelector(sel);
      const m = Object.values(JSON.parse(localStorage.getItem('annotate.round.resp-browser-suite')))[0];
      const b = AnnotateAnchors.rangeFor(s, m).getBoundingClientRect();
      return {x: b.left + 4, y: b.top + b.height / 2}; }""", SEL.format("section-1"))
    page.mouse.click(pos["x"], pos["y"])
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert "Marked compact" in page.inner_text(".sel-menu")
    _menu(page, "remove")
    assert _round(page) == {}


def test_no_menu_while_the_reading_highlighter_is_on(page):
    page.evaluate("() => { document.body.dataset.highlighter = 'on'; }")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFrom(AnnotateAnchors.contentOf(s), 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format("section-1"))
    _release(page)
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_the_menu_paints_with_no_page_errors(page):
    _select(page, "section-3", "Paragraph one")
    assert page.__dict__["js_errors"] == []


def test_registered_actions_join_the_menu_after_a_divider(page):
    page.evaluate("""() => AnnotateSelection.registerAction((t, menu) => {
      const b = document.createElement('button'); b.dataset.act = 'probe'; b.textContent = 'Probe';
      menu.appendChild(b); })""")
    _select(page, "section-1", "long enough")
    acts = page.eval_on_selector_all(".sel-menu > *", "els => els.map(e => e.dataset.act || e.className)")
    assert acts[-2:] == ["sel-sep", "probe"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with playwright python -m pytest skills/annotate/tests/test_browser_review.py -q -n 0 -k "menu or plain_click or keys_act or quoting or title_double or two_sections or replaces or clicking_a_mark or highlighter_is_on"`
Expected: they fail with a `TimeoutError` waiting for `.sel-menu`. `test_a_plain_click_on_prose_opens_nothing` and `test_no_menu_while_the_reading_highlighter_is_on` pass already. Note this in the report, since they guard behaviour the new code must keep.

- [ ] **Step 3: Expose the comment card for the whole section, in `script.js`**

Find `window.AnnotatePage` (it is defined with `registerRoundEvent`, around line 3889) and add:

```javascript
    // The selection menu's Comment on a whole section opens the same rich
    // card the keyboard's `c` opens: one door for whole-section comments.
    openComment(blockId) {
      const section = document.querySelector(
        `section.block[data-block-id="${cssEsc(blockId)}"]`);
      if (section) openAnnotation(section, "comment", {});
    },
```

In `syncGlossary` (around line 3712), after the glossary's `refreshAll` call, add `window.AnnotateSubunits?.paintSpans?.();`. Glossary redecoration rebuilds text nodes, so the ranges must be rebuilt from text.

- [ ] **Step 4: Write `selection.js`**

```javascript
// skills/annotate/static/selection.js
/* The one control: select any words and act on exactly them.
 *
 * A selection opens a small menu above it: Comment, Delete, Compact. Select
 * any part of a section's title and the menu acts on the whole section.
 * Nothing else on the page takes feedback, and a plain click does nothing,
 * so there is one way to react and it is always the same.
 *
 * The menu never edits the page's DOM around the words. Marks are text
 * anchors kept in the round (subunits.js) and painted by AnnotateAnchors.
 * The comment box and the comment chips are the only things inserted into
 * a block, and AnnotateAnchors skips them when counting text.
 */
(function () {
  "use strict";

  const ICON = {
    comment: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    compact: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
    remove: '<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  };
  const ACTS = [
    ["comment", "Comment", "c"],
    ["delete", "Delete — removed for good (undo until you submit)", "d"],
    ["compact", "Compact — off the page; its point folds into what stays", "x"],
  ];
  const KIND_WORD = { delete: "a delete", compact: "a compact", comment: "a comment" };
  const IGNORE = "button, a, input, textarea, select, label, .sel-menu, .sel-composer, "
    + ".sel-chip, .page-header, footer, #round-dock, .inline-comments, .code-col";

  let menu = null, target = null, suppressUntil = 0;
  const extras = [];

  function A() { return window.AnnotateAnchors; }
  function S() { return window.AnnotateSubunits; }
  function enabled() {
    const b = document.body;
    return !!(A() && A().supported() && S())
      && !b.classList.contains("read-only") && b.dataset.highlighter !== "on";
  }
  function sectionOf(node) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    return el ? el.closest("main.prose section.block[data-block-id]") : null;
  }
  function inTitle(node) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    return !!(el && el.closest(".card-head"));
  }
  function excluded(node, section) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!el) return true;
    if (el.closest(".code-col")) return true;
    if (section && section.dataset.kind === "choice" && el.closest(".block-content")) return true;
    return !(el.closest(".block-content") || el.closest(".card-head"));
  }

  function close() {
    if (menu) menu.remove();
    menu = null;
    if (target && target.whole) delete target.section.dataset.selScope;
    target = null;
    A()?.setScope(null);
  }

  function place(rect) {
    const w = menu.offsetWidth, h = menu.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const x = Math.min(Math.max(rect.left + rect.width / 2 - w / 2, 8), vw - w - 8);
    const above = rect.top - h - 8;
    const y = above >= 8 ? above : rect.bottom + 8;
    menu.style.left = `${x + window.scrollX}px`;
    menu.style.top = `${y + window.scrollY}px`;
  }

  function button(act, label, key, icon) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.act = act;
    b.innerHTML = icon + (act === "remove" ? "<span>Remove</span>" : "");
    b.title = key ? `${label} (${key})` : label;
    b.setAttribute("aria-label", b.title);
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", (e) => { e.stopPropagation(); act === "remove" ? removeCurrent() : run(act); });
    return b;
  }

  function open(t, rect, opts) {
    close();
    target = t;
    menu = document.createElement("div");
    menu.className = "sel-menu";
    menu.setAttribute("role", "toolbar");
    menu.setAttribute("aria-label", "Selection actions");
    if (opts.refuse) {
      menu.innerHTML = '<span class="sel-state">Select within one section</span>';
    } else {
      if (opts.state) {
        const s = document.createElement("span");
        s.className = "sel-state";
        s.textContent = opts.state;
        menu.appendChild(s);
      }
      if (opts.removable) menu.appendChild(button("remove", "Remove this mark", "", ICON.remove));
      if (opts.state || opts.removable) {
        const sep = document.createElement("span");
        sep.className = "sel-sep";
        menu.appendChild(sep);
      }
      for (const [act, label, key] of ACTS) menu.appendChild(button(act, label, key, ICON[act]));
      if (extras.length && t) {
        const sep = document.createElement("span");
        sep.className = "sel-sep";
        menu.appendChild(sep);
        for (const fn of extras) { try { fn(t, menu); } catch (_) {} }
        // A divider with nothing after it is noise: drop it if no extra added a button.
        if (menu.lastElementChild === sep) sep.remove();
      }
    }
    document.body.appendChild(menu);
    place(rect);
    if (t && t.whole) { t.section.dataset.selScope = ""; A().setScope(t.range); }
  }

  function openForSelection(range) {
    const s1 = sectionOf(range.startContainer), s2 = sectionOf(range.endContainer);
    if (!s1 && !s2) return close();
    if (s1 !== s2) return open(null, range.getBoundingClientRect(), { refuse: true });
    if (excluded(range.startContainer, s1) || excluded(range.endContainer, s1)) return close();
    if (inTitle(range.startContainer) || inTitle(range.endContainer)) return openWhole(s1);
    const anchor = A().anchorFor(s1, range);
    if (!anchor) return close();
    const over = S().overlapping(anchor);
    const state = over.length ? `Replaces ${KIND_WORD[over[0].m.kind] || "a mark"}` : "";
    open({ section: s1, anchor, range: range.cloneRange(), whole: false },
         range.getBoundingClientRect(), { state });
  }

  function openWhole(section) {
    getSelection()?.removeAllRanges();
    const head = section.querySelector(".card-head");
    const range = document.createRange();
    range.selectNodeContents(section);
    const mark = S().blockMark(section.dataset.blockId);
    const state = mark ? `Section marked ${mark.kind}` : "Whole section";
    open({ section, anchor: null, range, whole: true },
         (head || section).getBoundingClientRect(), { state, removable: !!mark });
    // A double-click on the title fires two mouseups; the second must not
    // close what the first opened.
    suppressUntil = Date.now() + 400;
  }

  function openForMark(section, hit) {
    const range = A().rangeFor(section, hit.m);
    if (!range) return close();
    open({ section, anchor: hit.m, range, whole: false, key: hit.key },
         range.getBoundingClientRect(), { state: `Marked ${hit.m.kind}`, removable: true });
  }

  function removeCurrent() {
    if (!target) return;
    if (target.whole) {
      const m = S().blockMark(target.section.dataset.blockId);
      if (m) S().toggleBlockMark(target.section.dataset.blockId, m.kind);
    } else if (target.key) {
      S().removeMarkByKey(target.key);
    }
    close();
  }

  function run(act) {
    if (!target) return;
    const t = target;
    if (t.whole) {
      close();
      if (act === "comment") window.AnnotatePage?.openComment(t.section.dataset.blockId);
      else S().toggleBlockMark(t.section.dataset.blockId, act);
      return;
    }
    getSelection()?.removeAllRanges();
    close();
    if (act === "comment") openComposer(t.section, t.anchor, t.range);
    else S().setSpanMark(t.anchor, act);
  }

  // ── the comment box for a span ──────────────────────────────────────────
  let composer = null;
  function closeComposer() { if (composer) composer.remove(); composer = null; }

  function hostFor(range, section) {
    const content = A().contentOf(section);
    let el = range.endContainer.nodeType === 1 ? range.endContainer : range.endContainer.parentElement;
    const block = el && el.closest("li, p, pre, blockquote, table, h1, h2, h3, h4, h5, h6");
    return block && content.contains(block) ? block : content;
  }

  function openComposer(section, anchor, range) {
    closeComposer();
    const box = document.createElement("div");
    box.className = "sel-composer";
    const quote = document.createElement("div");
    quote.className = "sel-quote";
    quote.textContent = anchor.selected_text.length > 140
      ? anchor.selected_text.slice(0, 139) + "…" : anchor.selected_text;
    const ta = document.createElement("textarea");
    ta.rows = 1;
    ta.placeholder = "Ask or push back on this…";
    ta.setAttribute("aria-label", "Comment on the selected words");
    const grow = () => { ta.style.height = "auto"; ta.style.height = `${ta.scrollHeight + 2}px`; };
    ta.addEventListener("input", grow);
    const row = document.createElement("div");
    row.className = "sel-row";
    row.innerHTML = '<span class="card-submit-hint"><kbd>↩</kbd> to add · '
      + '<kbd>⇧</kbd><kbd>↩</kbd> new line · <kbd>Esc</kbd> to close</span>';
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "sel-cancel"; cancel.textContent = "Cancel";
    const add = document.createElement("button");
    add.type = "button"; add.className = "card-submit-btn"; add.textContent = "Add to round";
    const commit = () => {
      const v = ta.value.trim();
      closeComposer();
      if (v) S().setSpanMark(anchor, "comment", v);
    };
    cancel.addEventListener("click", (e) => { e.stopPropagation(); closeComposer(); });
    add.addEventListener("click", (e) => { e.stopPropagation(); commit(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
      if (e.key === "Escape") { e.preventDefault(); closeComposer(); }
    });
    row.append(cancel, add);
    box.append(quote, ta, row);
    const host = hostFor(range, section);
    if (host === A().contentOf(section) || host.tagName === "LI") host.appendChild(box);
    else host.insertAdjacentElement("afterend", box);
    composer = box;
    grow();
    ta.focus();
  }

  // ── events ──────────────────────────────────────────────────────────────
  document.addEventListener("mouseup", (ev) => {
    if (!enabled()) return;
    if (ev.target instanceof Element && ev.target.closest(IGNORE)) return;
    const x = ev.clientX, y = ev.clientY;
    setTimeout(() => {
      const sel = getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount) return openForSelection(sel.getRangeAt(0));
      if (Date.now() < suppressUntil) return;
      const section = sectionOf(ev.target);
      if (section && inTitle(ev.target) && S().blockMark(section.dataset.blockId)) return openWhole(section);
      const hit = section && S().spanMarkAt(section, x, y);
      if (hit) return openForMark(section, hit);
      close();
    }, 0);
  });

  document.addEventListener("mousedown", (ev) => {
    if (menu && !(ev.target instanceof Element && ev.target.closest(".sel-menu"))) close();
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const a = document.activeElement;
    const typing = a instanceof HTMLInputElement || a instanceof HTMLTextAreaElement
      || (a && a.isContentEditable);
    if (typing) return;
    if (menu) {
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(); return; }
      const act = { c: "comment", d: "delete", x: "compact" }[ev.key];
      if (act && target) { ev.preventDefault(); ev.stopPropagation(); run(act); }
      return;
    }
    // No menu, no selection: d and x act on the block j/k chose. `c` is
    // script.js's, and stays where it is.
    if (ev.key !== "d" && ev.key !== "x") return;
    if (!enabled() || getSelection()?.toString()) return;
    const id = window.AnnotateKeyboard?.focusedId?.();
    if (!id) return;
    ev.preventDefault();
    S().toggleBlockMark(id, ev.key === "d" ? "delete" : "compact");
  }, true);

  // A rewrite replaces the section the menu points into.
  document.addEventListener("annotate:rendered", () => {
    if (target && !document.contains(target.section)) close();
  });

  window.AnnotateSelection = {
    isOpen: () => !!menu,
    close,
    registerAction(fn) { if (typeof fn === "function" && extras.indexOf(fn) < 0) extras.push(fn); },
  };
})();
```

In `entry.js`, add `"selection.js"` immediately after `"subunits.js"`.

Make `AnnotateSubunits.paintSpans` also render the comment chips. In `subunits.js`, at the end of `paintSpans`, add:

```javascript
    // A comment's words are shown where it was made: one chip under the
    // paragraph (or list item) the commented words end in.
    document.querySelectorAll(".sel-chip").forEach((c) => c.remove());
    for (const [key, m] of Object.entries(marks)) {
      if (!isSpan(m) || m.kind !== "comment" || !m.text) continue;
      const section = sectionFor(m.block_id);
      const r = section && window.AnnotateAnchors.rangeFor(section, m);
      if (!r) continue;
      const content = window.AnnotateAnchors.contentOf(section);
      const end = r.endContainer.nodeType === 1 ? r.endContainer : r.endContainer.parentElement;
      const host = (end && end.closest("li, p, pre, blockquote, table")) || content;
      const chip = document.createElement("span");
      chip.className = "sel-chip";
      chip.dataset.key = key;
      chip.textContent = `💬 ${m.text}`;
      if (host === content || host.tagName === "LI") host.appendChild(chip);
      else host.insertAdjacentElement("afterend", chip);
    }
```

- [ ] **Step 5: Style it in `style.css`**

Append at the end of `style.css`:

```css
/* ── The selection menu ─────────────────────────────────────────────────
   One dark bar above whatever is selected. Icon buttons, then whatever later
   features register (Explain, Edit) after a divider. Dark on the light theme and light on the dark one, so
   it reads as floating above the page in both. */
.sel-menu {
  position: absolute; z-index: 60; display: flex; align-items: center; gap: 2px;
  padding: 4px; border-radius: 10px; white-space: nowrap; font-size: 12.5px;
  background: var(--text-strong); color: var(--surface);
  box-shadow: 0 10px 30px rgba(0, 0, 0, .28);
}
.sel-menu button {
  border: 0; background: transparent; color: inherit; font: inherit; font-weight: 500;
  padding: 6px 7px; border-radius: 7px; display: inline-flex; align-items: center; gap: 6px;
  cursor: pointer;
}
.sel-menu button:hover, .sel-menu button:focus-visible {
  background: color-mix(in srgb, var(--surface) 16%, transparent); outline: none;
}
.sel-menu svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; }
.sel-menu .sel-state { padding: 0 8px; font-weight: 600; }
.sel-menu .sel-sep { width: 1px; align-self: stretch; margin: 4px 3px;
  background: color-mix(in srgb, var(--surface) 35%, transparent); }

/* A whole section is the scope: the card says so, not just the menu. */
section.block[data-sel-scope] { box-shadow: 0 0 0 2px var(--accent), var(--card-shadow, none); }
::highlight(annotate-scope) { background-color: color-mix(in srgb, var(--accent) 10%, transparent); }

/* Marks on the selected words. The same three meanings as the dock. */
::highlight(annotate-delete) {
  color: var(--type-reject-fg); text-decoration: line-through;
  background-color: color-mix(in srgb, var(--type-reject-fg) 10%, transparent);
}
::highlight(annotate-compact) {
  background-color: color-mix(in srgb, #7c3aed 14%, transparent);
  text-decoration: underline 2px color-mix(in srgb, #7c3aed 65%, transparent);
}
::highlight(annotate-comment) {
  background-color: color-mix(in srgb, var(--accent) 14%, transparent);
  text-decoration: underline 2px var(--accent);
}

.sel-composer {
  display: block; margin: 8px 0 4px; padding: 10px 12px; border-radius: 10px;
  background: var(--type-comment-wash);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 16%, transparent);
  font-weight: 400; font-style: normal;
}
.sel-quote { font-size: 12px; font-style: italic; color: var(--text-dim);
  border-left: 2px solid var(--accent); padding-left: 8px; margin-bottom: 8px; }
.sel-composer textarea {
  display: block; width: 100%; box-sizing: border-box; min-height: 40px; max-height: 240px;
  resize: none; padding: 8px 12px; font: inherit; font-size: 14px; line-height: 1.5;
  border: 1px solid var(--control-border); border-radius: 7px;
  background: var(--surface); color: var(--text); caret-color: var(--accent);
}
.sel-composer textarea:focus { outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.sel-row { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.sel-cancel { padding: 6px 12px; font: inherit; font-size: 13px; font-weight: 500;
  border: 1px solid var(--control-border); border-radius: 5px; background: transparent;
  color: var(--text); cursor: pointer; }
.sel-chip {
  display: block; margin: 6px 0 2px; padding: 4px 9px; font-size: 13px; border-radius: 8px;
  color: var(--type-comment-fg); background: var(--type-comment-wash);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border));
}
body.read-only .sel-menu, body.read-only .sel-composer { display: none; }
```

Check `--card-shadow`: if `style.css` names the card's resting shadow differently, use that variable instead. Search for `box-shadow` on `section.block` first. If there is no variable, write the card's literal shadow.

- [ ] **Step 6: Run the new tests, measure in the browser, run everything**

Run: the command from Step 2. Expected: all 10 pass.

Then check the paint for real, because source-level tests cannot see it. In the `page` fixture, after `_select(page, "section-1", "long enough")` and `_menu(page, "delete")`, take a screenshot of `SEL.format("section-1")` in light and in dark (`document.body.dataset.pageTheme = 'dark'`). Read both screenshots and confirm three things: the struck words are legible, the menu is not clipped at the page's right edge, and the menu sits above the words. Put both screenshot paths in the report.

Then: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`. Expected: all green. The old strips still work beside the menu, and `test_smoke_menu.py`'s id check stays green because `selection.js` looks up no element ids.

- [ ] **Step 7: Commit**

```bash
git add skills/annotate/static/selection.js skills/annotate/static/entry.js skills/annotate/static/script.js skills/annotate/static/subunits.js skills/annotate/static/style.css skills/annotate/tests/test_browser_review.py
git commit -m "feat(annotate): one menu on any selection: comment, delete or compact exactly those words, or the whole section from its title"
```

---

### Task 4: remove the card-header strip

**Files:**
- Modify: `skills/annotate/static/script.js`, `style.css`, `export.js`, `shell.js`
- Modify tests: `test_browser_review.py`, `test_smoke_subunits.py`, `test_smoke_compact.py`, `test_smoke_dismiss_lock.py`, `test_smoke_read_only.py`, `test_smoke_review_ergonomics.py`, `test_smoke_export.py`

**Interfaces:**
- Consumes: the selection menu (Task 3) as the only whole-section control; `AnnotatePage.openComment` (Task 3).
- Produces: no `.hover-actions` anywhere. The test helpers `_block_mark(page, anchor, kind)` and `_comment_on_block(page, anchor, text)` keep their signatures but go through a title double-click and the menu.

- [ ] **Step 1: Point the shared test helpers at the menu**

In `test_browser_review.py`, replace `_block_mark`:

```python
def _block_mark(page, anchor, kind):
    """Whole-section mark, the way a reader makes one now: double-click the
    title, then pick from the menu."""
    page.dblclick(SEL.format(anchor) + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=3000)
    page.click(f'.sel-menu button[data-act="{kind}"]')
```

`_comment_on_block` keeps its body. It calls `_block_mark(..., "comment")`, which now opens the comment card through `AnnotatePage.openComment`.

- [ ] **Step 2: Run the suite and watch what the header strip still holds up**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`
Expected: everything still passes, because the strip is still there. Record the count.

- [ ] **Step 3: Remove the strip from `script.js`**

Delete these:
- `ICON`, `ACTION_TYPES`, `ACTION_NAMES`, `HOVER_LINGER_MS` and `renderHoverActions`, including the long comment block above `ICON` that explains the strip's glyphs.
- `onHoverAction`.
- The two `renderHoverActions();` calls, in `loadAndRenderBlocks` and at the end of `reconcile`.

Change these:
- In `blockSnippet`, delete the line that strips `.hover-actions`.
- In the Add-to-round handler, the refocus becomes `home?.querySelector(".card-chevron")?.focus();`. Update the comment above it to say focus returns to the section's fold button.
- In `openAnnotation`'s header comment, nothing refers to the strip, so leave it.

- [ ] **Step 4: Remove its CSS and its export entry**

In `style.css`, delete every rule whose selector names `.hover-actions`. The map shows them at lines 199-205 (only the `.hover-actions` parts of the read-only list), 253-331, 364, 641-644 and 1150; search by selector rather than trusting these numbers. Also delete the `section.block[data-block-mark] .hover-actions` rules.

Keep `section.block[data-block-mark=...]` card painting. Add the section badge:

```css
section.block[data-block-mark] .card-title::after {
  margin-left: 8px; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;
  color: #fff; vertical-align: 2px;
}
section.block[data-block-mark="delete"] .card-title::after { content: "✕ delete section"; background: var(--type-reject-fg); }
section.block[data-block-mark="compact"] .card-title::after { content: "⤓ compact section"; background: #7c3aed; }
section.block[data-block-mark="comment"] .card-title::after { content: "💬 section"; background: var(--accent); }
```

In `export.js`'s STRIP list, replace `.hover-actions` with `.sel-menu, .sel-composer, .sel-chip`.

In `shell.js`'s legend, replace the copy that says the controls appear on hover with: "Select any words — or double-click a section's title for the whole section — and a menu offers Comment, Delete and Compact." Then add rows `d` "Delete the selection, or the chosen section" and `x` "Compact the selection, or the chosen section" to the keyboard table beside `c`. `shell.js` stores HTML in a JS string; follow its existing escaping exactly.

- [ ] **Step 5: Migrate the tests that named the strip**

For each test below, make the stated change. Then run that test file and see it pass.

- `test_browser_review.py`:
  - `test_the_comment_icon_opens_a_comment` and `test_a_second_comment_is_refused_out_loud`: open the card with `_block_mark(page, "section-1", "comment")` instead of hovering the header.
  - `test_the_keyboard_walks_the_document`: delete the assertion that `.hover-actions` is revealed. Keep the j/k/c assertions.
  - `test_the_touch_header_strip_reads_as_live`: delete.
  - `test_every_glyph_button_says_what_it_does_and_to_what`: assert instead that every `.sel-menu button` has an `aria-label` naming its action and key, after `_select(page, "section-1", "long enough")`.
  - `test_the_round_drawer_works_from_the_keyboard` and `test_marks_are_announced`: make the mark with `_block_mark(page, "section-1", "compact")`.
  - `test_adding_a_comment_to_the_round_keeps_the_caret`: open with `_block_mark(page, "section-1", "comment")`, then assert focus ends on `.card-chevron`.
- `test_smoke_subunits.py`:
  - `test_one_vocabulary_at_both_scopes`: assert `selection.js` defines `comment`, `delete` and `compact` acts, and that neither `selection.js` nor `subunits.js` uses `"agree"` or `"reject"`.
  - `test_block_controls_reveal_from_anywhere_in_the_header`: delete.
- `test_smoke_compact.py`:
  - `test_no_control_survives_a_read_only_link`: assert `body.read-only .sel-menu` is hidden in `style.css`.
  - `test_both_scopes_offer_compact_with_the_same_glyph`: assert `selection.js` has a `compact` act with the eye-off SVG (`<line x1="1" y1="1" x2="23" y2="23"/>`).
  - `test_compact_has_its_own_pending_appearance`: assert `::highlight(annotate-compact)` and `section.block[data-block-mark="compact"]` rules exist.
- `test_smoke_dismiss_lock.py`:
  - `test_busy_and_editing_css_present`: drop the `.hover-actions` selector from its list.
  - `test_delete_is_queued_not_submitted`: assert `selection.js` calls `toggleBlockMark` and `setSpanMark`, and keep its absence checks.
  - `test_block_controls_live_next_to_the_card_title`: delete.
- `test_smoke_read_only.py`, `test_feedback_controls_are_hidden_for_a_guest`: assert `body.read-only .sel-menu` and `body.read-only .sel-composer` are hidden.
- `test_smoke_review_ergonomics.py`, `test_focus_and_the_cursor_reveal_the_strip`: delete.
- `test_smoke_export.py`, `test_the_export_deletes_every_comment_carrier`: add `.sel-menu`, `.sel-composer` and `.sel-chip` to its expected list, and remove `.hover-actions`.

- [ ] **Step 6: Run the whole suite**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`
Expected: all green. `grep -rn "hover-actions" skills/annotate/static skills/annotate/tests` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add -A skills/annotate/static skills/annotate/tests
git commit -m "feat(annotate): the section title strip is gone; a double-clicked title opens the same menu"
```

---

### Task 5: remove the per-sentence strip, and convert old marks

**Files:**
- Modify: `skills/annotate/static/subunits.js`, `script.js`, `a11y.js`, `style.css`, `export.js`
- Modify tests: `test_browser_review.py`, `test_smoke_subunits.py`, `test_smoke_compact.py`, `test_smoke_dismiss_lock.py`

**Interfaces:**
- Consumes: span marks (Task 2) and the menu (Task 3).
- Produces: `AnnotateSubunits` without `decorate`. Old unit marks (keyed `block::text::ordinal`) are converted to span marks on load.

- [ ] **Step 1: Write the failing conversion test**

```python
# append to skills/annotate/tests/test_browser_review.py

def test_a_mark_saved_by_the_old_sentence_strip_still_counts(page):
    page.evaluate("""() => localStorage.setItem('annotate.round.resp-browser-suite', JSON.stringify({
      'section-1::Paragraph two of block 1.::0': {scope: 'unit', block_id: 'section-1', kind: 'delete',
        selected_text: 'Paragraph two of block 1.', ordinal: 0}}))""")
    page.reload()
    page.wait_for_function("() => CSS.highlights.get('annotate-delete')?.size === 1", timeout=5000)
    [(key, m)] = _round(page).items()
    assert "::__span__::" in key and "ordinal" not in m
    assert m["prefix"] == "" and m["suffix"] == ""
```

- [ ] **Step 2: Watch it fail**

Run: `uv run -q --with pytest --with playwright python -m pytest skills/annotate/tests/test_browser_review.py -q -n 0 -k old_sentence_strip`
Expected: FAIL. The old strip repaints it as `.sub-unit[data-mark]`, the key still has no `::__span__::`, and no `annotate-delete` highlight appears.

- [ ] **Step 3: Convert on load, and delete the strip code**

In `subunits.js`, in `loadMarks`, after the existing legacy `keep` filter, add:

```javascript
    // Marks made by the old per-sentence strip were keyed by the sentence's
    // text and its position among same-text sentences. Their words are all a
    // span mark needs; the position is dropped, and an empty prefix/suffix
    // lets `locate` take the first match, which is what ordinal 0 meant.
    for (const [k, m] of Object.entries(stored)) {
      if (!m || m.scope !== "unit" || !m.selected_text || k.includes("::__")) continue;
      delete stored[k];
      const { ordinal, ...rest } = m;
      const conv = { ...rest, prefix: m.prefix || "", suffix: m.suffix || "" };
      stored[`${conv.block_id}::__span__::${conv.prefix}␟${conv.selected_text}␟${conv.suffix}`] = conv;
    }
```

Then delete, with everything that only they use:
- `markKey`, `unitOrdinal`, `UNIT_VERBS`, `snippet`, `UNIT_SELECTOR` and `decorate`
- `toggleMark`, `stripClone`, `buildMark` and `applyMarkState`
- `openComposer`, `closeComposer` and `outsideClose`
- the boot catch-up loop that calls `decorate`
- every `.sub-unit` / `.unit-chip` loop in `removeMark`, `clearRound` and `repaintAll`. `paintSpans()` already covers them.
- the `closeComposer()` call in `resetForResponse`. Call `window.AnnotateSelection?.close()` there instead.
- the `decorate` entry in the export object
- the header comment's "TWO SCOPES" paragraph. Rewrite it as: "TWO SCOPES: a span (any words the reader selected, carried as selected_text plus prefix/suffix) and a block (the whole section, chosen by selecting its title). Both are set from the selection menu in selection.js."
- the "Unit identity on the wire" paragraph. Rewrite it as: "A span mark goes on the wire as its words plus up to 32 characters either side, always, so Claude finds the right occurrence even when the words repeat."

Keep `armBootTimer` and call it once at load (Task 2 already added this). Also keep `unitText`, `occurrences` and `nthIndexOf` if anything still calls them; delete any that `grep` shows are now unused.

In `script.js`, delete the two `AnnotateSubunits.decorate(content, section)` calls (in `createBlockSection` and `updateBlockContent`).

In `a11y.js`, delete `syncStripTabOrder` and its call in the observer, keeping `onRoundChange`. Delete the touch-tap handler for `.sub-unit` / `.unit-strip`, and the `data-kb-focus` attribute filter if nothing else needs it. Update the file's comments to match.

In `style.css`, delete every `.sub-unit`, `.unit-strip`, `.unit-chip` and `.unit-composer` rule. That includes the read-only list entries and the `.sub-unit[data-mark=...]` mark styles, at map lines 1181-1343, 343-346 and 199-205. Search by selector.

In `export.js`, delete `.unit-strip, .unit-chip, .unit-composer` from STRIP, `data-mark` from STATE_ATTRS, and the `.sub-unit` CSS reset.

In `highlighter.js`, nothing names the strip any more after Task 1. Confirm with `grep`.

- [ ] **Step 4: Migrate the tests that drove the sentence strip**

- `test_browser_review.py`:
  - Delete `_unit_button`, `FIRST_UNIT`, `test_an_invisible_unit_strip_cannot_be_tapped`, `test_a_shown_unit_strip_covers_no_text_on_a_phone`, `test_the_unit_strips_are_not_tab_stops_until_the_block_is_chosen` and `test_the_sentence_comment_box_can_be_closed`.
  - Change `_decorated(pg)` to wait only for `window.AnnotateSelection`.
  - `test_a_tap_on_a_sentence_shows_its_controls`: delete. Task 6 adds the touch sheet's own test.
  - `test_marks_come_back_on_every_load`: make the unit mark with `_select(page, "section-1", "Paragraph one")` and `_menu(page, "compact")`, then wait for `CSS.highlights.get('annotate-compact').size === 1` after each reload instead of `.sub-unit[data-mark]`.
  - `test_a_rewritten_paragraph_keeps_its_comment`: comment through `_select` + `_menu(page, "comment")`, then fill `.sel-composer textarea` and press Enter.
  - `test_a_second_click_takes_a_mark_back`: select the same words twice and press the same act twice. The round ends empty.
  - `test_the_second_of_two_identical_lines_says_which_it_is`: select the second occurrence with `_select(page, anchor, text, nth=1)`, and assert the submitted reaction's `prefix` ends with the text that precedes the second line.
  - `test_an_authored_list_item_can_be_commented`: `_select` inside the authored item, comment through the menu, and assert `step_id == "client-split"`.
- `test_smoke_subunits.py`:
  - Delete `test_subunits_cover_prose_unit_types`, `test_table_rows_are_not_sub_units`, `test_subunits_marks_are_ordinal_aware`, `test_script_js_calls_decorate_on_both_render_paths` and `test_style_css_has_subunit_styles`.
  - `test_subunits_js_exists_with_public_api`: assert `setSpanMark`, `spanMarkAt` and `paintSpans` are exported.
  - `test_subunits_anchors_authored_annotate_ids_by_id`: assert `anchors.js` contains `closest("[data-annotate-id]")` and sets `step_id`.
- `test_smoke_compact.py`:
  - Delete `test_the_strip_can_render_an_icon_glyph` and `test_compact_stays_clickable_mid_round`.
  - `test_compact_reads_as_heavier_than_it_did` and `test_compact_still_is_not_delete`: read the `::highlight(annotate-compact)` rule. Assert it has no `line-through`, and that delete's rule does.
- `test_smoke_dismiss_lock.py`, `test_pending_delete_is_reversible`: assert `::highlight(annotate-delete)` exists, and that `selection.js` offers a `remove` act on an existing mark.

- [ ] **Step 5: Run everything**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`
Expected: all green.
`grep -rnE "sub-unit|unit-strip|unit-chip|unit-composer|decorate\(" skills/annotate/static` prints only the glossary's own `AnnotateGlossary.decorate`.

- [ ] **Step 6: Commit**

```bash
git add -A skills/annotate/static skills/annotate/tests
git commit -m "feat(annotate): the per-sentence strip is gone; marks it saved convert to span marks on load"
```

---

### Task 6: the touch sheet

**Files:**
- Modify: `skills/annotate/static/selection.js`, `style.css`
- Test: `skills/annotate/tests/test_browser_review.py` (append)

**Interfaces:**
- Consumes: `open`, `run`, `removeCurrent` inside `selection.js` (Task 3).
- Produces: on a touch screen (`matchMedia("(hover: none) and (pointer: coarse)")`), the menu renders as `.sel-menu.sel-sheet`, fixed to the bottom of the viewport. It opens from `selectionchange` (debounced 350 ms), because touch selection does not end in a reliable mouseup.

- [ ] **Step 1: Write the failing test**

```python
# append to skills/annotate/tests/test_browser_review.py

def test_on_a_phone_the_menu_is_a_bottom_sheet_quoting_the_selection(document):
    with _phone(document) as pg:
        pg.evaluate("""(sel) => { const s = document.querySelector(sel);
          const root = AnnotateAnchors.contentOf(s);
          const i = AnnotateAnchors.textOf(root).indexOf('long enough');
          const r = AnnotateAnchors.rangeFrom(root, i, i + 11);
          getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format("section-1"))
        pg.wait_for_selector(".sel-menu.sel-sheet", timeout=3000)
        box = pg.eval_on_selector(".sel-sheet", "e => e.getBoundingClientRect().toJSON()")
        assert abs(box["bottom"] - 800) <= 1 and box["width"] >= 380
        assert "long enough" in pg.inner_text(".sel-sheet .sel-quote")
        sizes = pg.eval_on_selector_all(".sel-sheet button[data-act]",
                                        "bs => bs.map(b => b.getBoundingClientRect().height)")
        assert min(sizes) >= 44, "touch targets under 44px"
        pg.click('.sel-sheet button[data-act="delete"]')
        assert pg.locator(".sel-sheet").count() == 0
```

- [ ] **Step 2: Watch it fail**

Run: `uv run -q --with pytest --with playwright python -m pytest skills/annotate/tests/test_browser_review.py -q -n 0 -k bottom_sheet`
Expected: FAIL with a timeout waiting for `.sel-menu.sel-sheet`.

- [ ] **Step 3: Implement**

In `selection.js`:
- Add `const touch = window.matchMedia("(hover: none) and (pointer: coarse)");`.
- In `open()`, when `touch.matches`, add the class `sel-sheet`. Prepend a `<div class="sel-quote">` holding the selection's text (truncate to 140 characters with "…") when `t && t.anchor`, or the section title when `t && t.whole`. Skip `place(rect)`.
- Give each act button a visible text label after its icon in the sheet: `Comment`, `Delete`, `Compact`.
- Add a debounced `selectionchange` listener that runs only while `touch.matches && enabled()`. After 350 ms of no change, if the selection is non-empty it calls `openForSelection(getSelection().getRangeAt(0))`. If the selection is empty, it closes the menu unless focus is inside the menu.

In `style.css`, append:

```css
.sel-menu.sel-sheet {
  position: fixed; left: 0; right: 0; bottom: 0; top: auto; border-radius: 16px 16px 0 0;
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;
  padding: 10px 12px calc(14px + env(safe-area-inset-bottom, 0px));
  background: var(--surface); color: var(--text); white-space: normal;
  box-shadow: 0 -8px 24px rgba(0, 0, 0, .18);
}
.sel-sheet .sel-quote { grid-column: 1 / -1; font-size: 12px; font-style: italic; color: var(--text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sel-sheet .sel-state, .sel-sheet .sel-sep { grid-column: 1 / -1; }
.sel-sheet button { min-height: 48px; justify-content: center; flex-direction: column; gap: 2px;
  border: 1px solid var(--border); background: var(--surface-soft); color: var(--text); }
```

- [ ] **Step 4: Run it, check it on a phone-sized screen, run everything**

Run: the command from Step 2. Expected: PASS.
Take one screenshot inside the `_phone` context with the sheet open, in light and in dark. Read both, and confirm that the page's own text behind the sheet is not covered by it above the fold line, and that the labels read. Put the screenshot paths in the report.
Then run the full suite. Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/static/selection.js skills/annotate/static/style.css skills/annotate/tests/test_browser_review.py
git commit -m "feat(annotate): on a phone the selection menu is a bottom sheet with full-size targets"
```

---

### Task 7: what Claude reads

**Files:**
- Modify: `skills/annotate/references/handling-events.md`
- Modify: `skills/annotate/references/pushing.md`
- Test: `skills/annotate/tests/test_round_contract.py` (append)

**Interfaces:**
- Consumes: nothing in code.
- Produces: the partial-span rules and the glossary rule from spec §4.3.

- [ ] **Step 1: Write the failing contract tests**

```python
# append to skills/annotate/tests/test_round_contract.py

PUSHING = REPO / "skills" / "annotate" / "references" / "pushing.md"


def test_a_partial_sentence_delete_is_cut_and_repaired():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "part of a sentence" in doc
    assert "grammatical" in doc


def test_a_partial_compact_folds_into_the_same_sentence_first():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "same sentence" in doc


def test_a_comment_is_about_exactly_the_quoted_words():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "exactly the quoted words" in doc


def test_scope_is_no_longer_described_by_hovering():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "hovered the card header" not in doc
    assert "selected its title" in doc


def test_every_abbreviation_a_listener_may_not_know_gets_a_glossary_entry():
    doc = PUSHING.read_text(encoding="utf-8")
    assert "read-aloud" in doc and "dictation" in doc
    assert "abbreviation" in doc
```

- [ ] **Step 2: Watch them fail**

Run: `uv run -q --with pytest python -m pytest skills/annotate/tests/test_round_contract.py -q -n 0`
Expected: the five new tests fail on their first assertion.

- [ ] **Step 3: Write the rules**

In `handling-events.md`, in "The model in one paragraph" (the `scope` explanation around lines 86-90), replace the `scope` sentence with:

> `scope` says what the reaction is anchored to: `"block"` (the whole section — the reader selected its title) or `"unit"` (exactly the words the reader selected, anchored by `selected_text` plus `prefix`/`suffix`, and by `step_id` when the words sit inside an authored `data-annotate-id` element).

In the `type: "round"` section, replace the sentence about "marking whole blocks from the card header and individual sub-units… Tables and pictures have no sub-units" with:

> The reader selected words — any span, from two words to several paragraphs — and marked them, or selected a section's title and marked the whole section. Tables and pictures are marked whole, through their title.

Then add these bullets to the unit-reaction rules list (step 5):

> - A unit `delete` or `compact` may cover **part of a sentence**. Cut exactly those words, then repair the sentence so it stays grammatical. Never delete the rest of the sentence to avoid the repair.
> - A unit `compact` of part of a sentence folds its point into the **same sentence** where it can, before looking at neighbouring sentences.
> - A `comment` is about **exactly the quoted words**, not the whole paragraph they sit in. Answer that, and rewrite the paragraph only as far as the answer needs.

In `pushing.md`, add this under "When to emit a glossary entry":

> Read-aloud and dictation both use the glossary: read-aloud to expand an abbreviation instead of guessing at it, dictation to recognise it. So **every abbreviation or project term a listener might not know** gets an entry, even when a reader of the page would work it out from context.

- [ ] **Step 4: Run them, then the whole suite**

Run: the command from Step 2. Expected: all pass.
Then run the full suite. Expected: all green, including the `index()`ed headings tests in `test_round_contract.py`.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/references/handling-events.md skills/annotate/references/pushing.md skills/annotate/tests/test_round_contract.py
git commit -m "docs(annotate): Claude's rules for marks on part of a sentence, and a glossary entry for every abbreviation"
```

