# Rich Choice Options and Choice Queues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a choice option carry rendered markdown (code included), and let consecutive choice blocks that share a `group` render as a one-question-at-a-time queue.

**Architecture:** Two optional spec fields, validated in `blocks.py` at load. `renderChoice` in `static/script.js` renders `options[].markdown` through the page's existing markdown-it and Shiki pipeline. A new `static/choice-queue.js` runs after every page render, finds runs of grouped choice sections, hides all but the current one, and inserts a navigation bar above the run. Every member stays an ordinary choice section, so the round, comments, rewrites and the event payload are untouched.

**Tech Stack:** Python 3 (stdlib), vanilla JS modules loaded by `static/entry.js`, markdown-it, Shiki via `CodePaint`, pytest, Playwright against a live webcompanion daemon.

**Spec:** `docs/superpowers/specs/2026-09-29-rich-choice-queue-design.md`

## Global Constraints

- Both fields are optional and additive. A choice block with neither renders and behaves exactly as today.
- `spec.group`: a string, 1 to 80 characters after nothing is stripped, not blank. It is the queue's title.
- `options[].markdown`: a string, rendered with the same `blockMd` and `sanitizeFreeHtml` as a markdown block.
- A queue is a run of **two or more adjacent** choice sections with equal `group`. A lone grouped choice renders as an ordinary choice.
- The event payload does not change. Each pick is a `kind: "choice"` reaction with the member's own `block_id`.
- Per-viewer queue state lives in `localStorage` under `annotate.queue:<responseId>:<runKey>:<at|all>`, every access in try/catch.
- Commit messages are one line, no body, no trailers, no attribution.
- Run tests from the repo root with `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest <path> -q -n 0`. Browser tests need the local webcompanion daemon and skip without it.

## Review Focus

1. **A rewrite of the current member while the queue is collapsed.** Expected: the rewritten question stays the one on screen, not a jump to question 1. Pinned in Task 3 by `test_a_rewrite_keeps_the_current_question`.
2. **A pick on the last undecided question.** Expected: the queue stays on that question and the progress reads "N of N decided", with no wrap to an already-decided one. Pinned in Task 3 by `test_the_last_pick_stays_put`.
3. **Two runs of the same `group` split by another block.** Expected: two independent queues with independent positions. Pinned in Task 3 by `test_two_runs_of_one_group_are_two_queues`.
4. **Selecting code inside an option to copy it.** Expected: no pick. `.choice-option` is `user-select: none` today, so without the new CSS a selection is impossible at all. Pinned in Task 2 by `test_selecting_text_in_an_option_does_not_pick_it`.
5. **Storage blocked (private window).** Expected: the queue still renders, starting at the first undecided question. Pinned in Task 3 by `test_the_queue_works_with_storage_blocked`.

---

## File Map

| File | Change |
|---|---|
| `skills/annotate/blocks.py` | `ChoiceSpecError`, `_check_choice_specs`, called from `load` |
| `skills/annotate/tests/test_blocks.py` | validation tests |
| `skills/annotate/static/script.js` | rich option body, click guards, `section.dataset.group`, `annotate:rendered` and `annotate:choice-picked` events, queue-aware J/K |
| `skills/annotate/static/subunits.js` | `annotate:choice-changed` event |
| `skills/annotate/static/choice-queue.js` | new: the queue |
| `skills/annotate/static/entry.js` | load `choice-queue.js` after `subunits.js` |
| `skills/annotate/static/style.css` | `.choice-option-body`, `.cq-*` rules |
| `skills/annotate/static/search.js` | `annotate:search` event from `applyFilter` |
| `skills/annotate/static/export.js` | strip `.cq-bar`, un-hide `.cq-hidden` |
| `skills/annotate/confluence/body.py` | option markdown in the open-question panel |
| `skills/annotate/tests/test_confluence_body.py` | one test |
| `skills/annotate/tests/test_browser_choice_queue.py` | new: browser tests |
| `skills/annotate/references/block-kinds/choice.md` | two new sections |
| `skills/annotate/SKILL.md` | one clause in the block-kind menu |
| `skills/annotate/docs/gallery.html` | a rich choice and a three-question queue |

---

### Task 1: Validate `group` and option `markdown` at load

**Files:**
- Modify: `skills/annotate/blocks.py` (classes near line 51, `load` near line 110)
- Test: `skills/annotate/tests/test_blocks.py` (append)

**Interfaces:**
- Produces: `class ChoiceSpecError(ValueError)` in `skills.annotate.blocks`. `load(path)` raises it. `push.py` already catches `ValueError` at line 246 and prints it, so a bad spec fails the push with the message and changes nothing.

- [ ] **Step 1: Write the failing tests**

Append to `skills/annotate/tests/test_blocks.py`:

```python
def _choice_file(tmp_path, **spec):
    base = {"question": "Which?",
            "options": [{"id": "o1", "label": "A"}, {"id": "o2", "label": "B"}]}
    base.update(spec)
    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": "section-7", "kind": "choice", "spec": base}]}))
    return p


@pytest.mark.parametrize("group", [3, "", "   ", "x" * 81, None])
def test_a_malformed_choice_group_is_refused(tmp_path, group):
    from skills.annotate.blocks import ChoiceSpecError
    with pytest.raises(ChoiceSpecError) as e:
        load(_choice_file(tmp_path, group=group))
    assert "section-7" in str(e.value)
    assert "group" in str(e.value)


def test_a_group_of_exactly_80_characters_loads(tmp_path):
    doc = load(_choice_file(tmp_path, group="x" * 80))
    assert doc.blocks[0]["spec"]["group"] == "x" * 80


def test_option_markdown_that_is_not_a_string_is_refused(tmp_path):
    from skills.annotate.blocks import ChoiceSpecError
    opts = [{"id": "o1", "label": "A", "markdown": ["not", "a", "string"]},
            {"id": "o2", "label": "B"}]
    with pytest.raises(ChoiceSpecError) as e:
        load(_choice_file(tmp_path, options=opts))
    assert "section-7" in str(e.value)
    assert "o1" in str(e.value)


def test_rich_options_and_a_group_load(tmp_path):
    opts = [{"id": "o1", "label": "A", "markdown": "```java\nclass A {}\n```"},
            {"id": "o2", "label": "B", "markdown": ""}]
    doc = load(_choice_file(tmp_path, group="Decisions", options=opts))
    assert doc.blocks[0]["spec"]["options"][0]["markdown"].startswith("```java")


def test_a_choice_without_the_new_fields_loads_as_before(tmp_path):
    doc = load(_choice_file(tmp_path))
    assert "group" not in doc.blocks[0]["spec"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_blocks.py -q -n 0 -k "group or option_markdown or rich_options or new_fields"`
Expected: the refusal tests FAIL with `ImportError: cannot import name 'ChoiceSpecError'`. The two "loads" tests pass already.

- [ ] **Step 3: Implement**

In `skills/annotate/blocks.py`, after `class BlocksFileError`:

```python
class ChoiceSpecError(ValueError):
    """A choice block's `group`, or an option's `markdown`, has the wrong shape.

    Both are optional. A wrong shape is refused at push time rather than
    rendered, because the page would otherwise drop the field in silence: a
    numeric group would form no queue, and a list in `markdown` would render
    as nothing under its option."""


CHOICE_GROUP_MAX = 80


def _check_choice_specs(blocks: list[dict[str, Any]]) -> None:
    problems = []
    for b in blocks:
        if b.get("kind") != "choice":
            continue
        bid = b.get("id", "?")
        spec = b.get("spec") or {}
        if "group" in spec:
            g = spec["group"]
            if not isinstance(g, str) or not g.strip():
                problems.append(f"{bid}: `group` must be a non-blank string")
            elif len(g) > CHOICE_GROUP_MAX:
                problems.append(f"{bid}: `group` is {len(g)} characters, "
                                f"over the {CHOICE_GROUP_MAX} limit")
        for o in spec.get("options") or []:
            if "markdown" in o and not isinstance(o["markdown"], str):
                problems.append(f"{bid}: option {o.get('id', '?')!r} has a "
                                f"`markdown` that is not a string")
    if problems:
        raise ChoiceSpecError(
            f"{len(problems)} choice spec problem(s), and the page would drop "
            f"the field in silence — " + "; ".join(problems[:4]))
```

In `load`, directly before `return BlocksDoc(`:

```python
    _check_choice_specs(blocks)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_blocks.py -q -n 0`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/blocks.py skills/annotate/tests/test_blocks.py
git commit -m "feat(annotate): refuse a malformed choice group or option markdown at push"
```

---

### Task 2: Render an option's markdown inside its card

**Files:**
- Modify: `skills/annotate/static/script.js` (`renderChoice`, from line 576)
- Modify: `skills/annotate/static/style.css` (after `.choice-option-desc`, near line 830)
- Create: `skills/annotate/tests/test_browser_choice_queue.py`

**Interfaces:**
- Consumes: `blockMd`, `sanitizeFreeHtml` already in `script.js` scope.
- Produces: `.choice-option-body` inside `.choice-option-text`. `.choice-option.has-body` on cards that carry one. `section.dataset.group` on every choice section whose spec has a string `group`. Task 3 reads `dataset.group`.

- [ ] **Step 1: Write the browser test module and the failing tests**

Create `skills/annotate/tests/test_browser_choice_queue.py`:

```python
"""Rich choice options and choice queues, in a real browser.

Reuses the live-daemon harness in test_browser_review.py: its `document`
fixture creates a throwaway session served from this checkout, and `page`
opens it in Chromium. Skips without playwright or without a daemon."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")

from skills.annotate.tests.test_browser_review import (  # noqa: E402,F401
    BLOCKS, REPO, _call, document, page)

JAVA = "public record Asset(\n    String id\n) {}"


def _rich(anchor, question, group=None):
    spec = {"question": question, "options": [
        {"id": "o1", "label": "Original", "markdown": f"```java\n{JAVA}\n```"},
        {"id": "o2", "label": "Now",
         "markdown": "Plain **text** and a [link](https://example.com/x)."},
        {"id": "o3", "label": "Mix", "description": "Name the fields"},
    ]}
    if group:
        spec["group"] = group
    return {"id": anchor, "kind": "choice", "spec": spec}


def _md(anchor, text):
    return {"id": anchor, "kind": "markdown", "markdown": text}


def _publish(page, document, blocks):
    base, sid = document["base"], document["sid"]
    for b in blocks:
        _call(base, "PUT", f"/s/{sid}/items/{b['id']}", b)
    _call(base, "PUT", f"/s/{sid}/items/__doc__",
          {"response_id": "resp-browser-suite", "title": "annotate browser suite",
           "order": BLOCKS + [b["id"] for b in blocks], "cwd": str(REPO),
           "glossary": []})
    page.reload()
    page.wait_for_selector(
        f'section.block[data-block-id="{blocks[-1]["id"]}"]', state="attached")


def _opt(anchor, n):
    return f'section.block[data-block-id="{anchor}"] .choice-option >> nth={n}'


def test_a_rich_option_renders_its_code_highlighted(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    code = page.locator(
        'section.block[data-block-id="rich"] .choice-option >> nth=0'
    ).locator(".choice-option-body pre code.sk-fence.language-java")
    assert code.count() == 1
    assert "public record Asset(" in code.inner_text()
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.has-body').count() == 2
    assert page.js_errors == []


def test_selecting_text_in_an_option_does_not_pick_it(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    page.evaluate("""() => {
      const code = document.querySelector(
        'section.block[data-block-id="rich"] .choice-option-body code');
      const r = document.createRange(); r.selectNodeContents(code);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      code.click();
    }""")
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 0
    selected_text = page.evaluate("() => getSelection().toString()")
    assert "public record Asset(" in selected_text, "the code cannot be selected"

    page.evaluate("() => getSelection().removeAllRanges()")
    page.click(_opt("rich", 0) + " >> .choice-option-label")
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 1


def test_a_link_in_an_option_does_not_pick_it(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    page.evaluate("""() => document.addEventListener('click', e => {
      if (e.target.closest('a[href]')) e.preventDefault(); }, true)""")
    page.click(_opt("rich", 1) + " >> .choice-option-body a")
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 0


def test_a_plain_choice_is_unchanged(page, document):
    plain = {"id": "plain", "kind": "choice", "spec": {"question": "Size?",
             "options": [{"id": "o1", "label": "S"}, {"id": "o2", "label": "L"}]}}
    _publish(page, document, [plain])
    assert page.locator('section.block[data-block-id="plain"] .choice-option-body').count() == 0
    assert page.locator('section.block[data-block-id="plain"] .has-body').count() == 0
    page.click(_opt("plain", 1))
    assert page.locator('section.block[data-block-id="plain"] .choice-option.selected').count() == 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_choice_queue.py -q -n 0`
Expected: `test_a_rich_option_renders_its_code_highlighted`, `test_selecting_text…` and `test_a_link…` FAIL (no `.choice-option-body`). `test_a_plain_choice_is_unchanged` PASSES.

- [ ] **Step 3: Implement the option body in `renderChoice`**

In `static/script.js`, at the top of `renderChoice` after `const options = …`:

```js
    // A queue is a run of choice sections sharing this; choice-queue.js reads it.
    if (typeof spec.group === "string" && spec.group.trim()) section.dataset.group = spec.group;
    else delete section.dataset.group;
```

In the `options.forEach` body, change `const textWrap = document.createElement("span");` to `"div"` (it now holds block content; `.choice-option-text` is `display:flex` either way). Then, after the `if (opt.description) { … }` block and before `card.appendChild(textWrap);`, add:

```js
      // An option may carry content: code, a table, prose. It renders through
      // the same markdown-it and Shiki path as a markdown block, so a fenced
      // java sample in an option looks exactly like one in the page.
      if (typeof opt.markdown === "string" && opt.markdown.trim() && blockMd) {
        const optBody = document.createElement("div");
        optBody.className = "choice-option-body";
        optBody.id = `choice-body-${blk.id}-${opt.id}`;
        optBody.innerHTML = blockMd.render(opt.markdown);
        sanitizeFreeHtml(optBody);
        textWrap.appendChild(optBody);
        card.classList.add("has-body");
        card.setAttribute("aria-describedby", optBody.id);
      }
```

Replace `card.addEventListener("click", () => toggleAt(idx));` with:

```js
      // The body is content the reader reads and copies from. A click that
      // ends a selection, or lands on a link, is not a pick.
      card.addEventListener("click", (e) => {
        if (e.target.closest && e.target.closest(".choice-option-body a[href]")) return;
        const sel = window.getSelection && window.getSelection();
        if (sel && !sel.isCollapsed && card.contains(sel.anchorNode)) return;
        toggleAt(idx);
      });
```

- [ ] **Step 4: Add the styles**

In `static/style.css`, after the `.choice-option-desc` rule:

```css
/* An option that carries content. The card stays `user-select: none` so a
   click reads as a pick; the body opts back in, because code in an option is
   something the reader copies. */
.choice-option.has-body .choice-option-text { flex: 1; min-width: 0; }
.choice-option-body {
  margin-top: 0.5rem;
  user-select: text;
  cursor: text;
  color: var(--text);
}
.choice-option-body > :first-child { margin-top: 0; }
.choice-option-body > :last-child { margin-bottom: 0; }
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_choice_queue.py skills/annotate/tests/test_browser_review.py -q -n 0 -k "choice or option"`
Expected: all PASS, including the existing choice tests in `test_browser_review.py`.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/static/script.js skills/annotate/static/style.css skills/annotate/tests/test_browser_choice_queue.py
git commit -m "feat(annotate): a choice option can carry markdown, rendered and highlighted inside its card"
```

---

### Task 3: The queue

**Files:**
- Create: `skills/annotate/static/choice-queue.js`
- Modify: `skills/annotate/static/entry.js` (the `JS` list)
- Modify: `skills/annotate/static/script.js` (`loadAndRenderBlocks` end, `reconcile` end, `renderChoice` `toggleAt`)
- Modify: `skills/annotate/static/subunits.js` (`setChoice`, `syncChoices`)
- Modify: `skills/annotate/static/style.css` (append)
- Test: `skills/annotate/tests/test_browser_choice_queue.py` (append)

**Interfaces:**
- Consumes: `section.dataset.group` and `section.dataset.kind` (Task 2), `window.AnnotateSubunits.choiceMark(blockId)`, `window.AnnotateKeyboard.focusBlock(id)`.
- Produces: `window.AnnotateChoiceQueue = { refresh(), stepFrom(blockId, delta) -> string|null }`. Events it listens to: `annotate:rendered`, `annotate:choice-picked` (`detail.blockId`), `annotate:choice-changed`, `annotate:search` (`detail.active: boolean`, added in Task 4). DOM it produces: `.cq-bar[data-run]` before each run's first section; `.cq-hidden` on hidden member sections and their `.inline-comments` sibling.

- [ ] **Step 1: Write the failing tests**

Append to `skills/annotate/tests/test_browser_choice_queue.py`:

```python
def _queue(page, document, n=3, group="Decisions", extra=()):
    blocks = [_rich(f"q{i}", f"Question {i}?", group) for i in range(1, n + 1)]
    _publish(page, document, blocks + list(extra))


def _visible(page, anchor):
    return page.locator(f'section.block[data-block-id="{anchor}"]').is_visible()


def test_grouped_choices_collapse_into_one_queue(page, document):
    loose = {"id": "loose", "kind": "choice", "spec": {"question": "Loose?",
             "options": [{"id": "o1", "label": "Y"}, {"id": "o2", "label": "N"}]}}
    _queue(page, document, extra=[loose])
    bar = page.locator('.cq-bar')
    assert bar.count() == 1
    assert "Decisions" in bar.inner_text()
    assert "1 / 3" in bar.inner_text()
    assert _visible(page, "q1") and not _visible(page, "q2") and not _visible(page, "q3")
    assert _visible(page, "loose")
    assert page.js_errors == []


def test_a_pick_records_on_the_member_and_moves_on(page, document):
    _queue(page, document)
    posts = []
    page.on("request", lambda r: posts.append(r.post_data or "") if r.method == "POST" else None)
    page.click(_opt("q1", 0) + " >> .choice-option-label")
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('[data-block-id=\"q2\"]')).display !== 'none'")
    assert "1 of 3 decided" in page.inner_text(".cq-bar")
    page.fill('section.block[data-block-id="q2"] .choice-note', "typing does not move")
    page.wait_for_timeout(300)
    assert _visible(page, "q2")

    page.click("#round-submit")
    page.wait_for_function("() => document.body.classList.contains('is-busy')", timeout=10000)
    sent = [p for p in posts if "selected_options" in p]
    env = json.loads(json.loads(sent[0])["text"])
    by_block = {r["block_id"]: r for r in env["reactions"]}
    assert by_block["q1"]["selected_options"] == ["o1"]
    assert by_block["q2"]["text"] == "typing does not move"


def test_the_last_pick_stays_put(page, document):
    _queue(page, document, n=2)
    page.click(_opt("q1", 0) + " >> .choice-option-label")
    page.wait_for_function("() => document.querySelector('.cq-bar').innerText.includes('2 / 2')")
    page.click(_opt("q2", 1) + " >> .choice-option-label")
    page.wait_for_timeout(400)
    assert _visible(page, "q2")
    assert "2 of 2 decided" in page.inner_text(".cq-bar")


def test_j_and_k_walk_the_queue_then_leave_it(page, document):
    _queue(page, document, n=2, extra=[_md("after", "The block after the queue.")])
    page.evaluate("() => window.AnnotateKeyboard.focusBlock('q1')")
    page.keyboard.press("j")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'q2'")
    assert _visible(page, "q2") and not _visible(page, "q1")
    page.keyboard.press("j")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'after'")
    page.keyboard.press("k")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'q2'")
    page.keyboard.press("k")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'q1'")
    assert _visible(page, "q1")


def test_show_all_expands_and_survives_a_reload(page, document):
    _queue(page, document)
    page.check(".cq-bar .cq-all input")
    assert all(_visible(page, f"q{i}") for i in (1, 2, 3))
    page.reload()
    page.wait_for_selector(".cq-bar")
    assert all(_visible(page, f"q{i}") for i in (1, 2, 3))
    page.uncheck(".cq-bar .cq-all input")
    assert sum(_visible(page, f"q{i}") for i in (1, 2, 3)) == 1


def test_the_position_survives_a_reload(page, document):
    _queue(page, document)
    page.click('.cq-bar .cq-dot >> nth=2')
    assert _visible(page, "q3")
    page.reload()
    page.wait_for_selector(".cq-bar")
    assert _visible(page, "q3") and not _visible(page, "q1")


def test_two_runs_of_one_group_are_two_queues(page, document):
    blocks = [_rich("a1", "A1?", "G"), _rich("a2", "A2?", "G"), _md("split", "between"),
              _rich("b1", "B1?", "G"), _rich("b2", "B2?", "G")]
    _publish(page, document, blocks)
    assert page.locator(".cq-bar").count() == 2
    page.locator(".cq-bar >> nth=1").locator(".cq-dot >> nth=1").click()
    assert _visible(page, "b2") and _visible(page, "a1")


def test_a_lone_grouped_choice_is_an_ordinary_choice(page, document):
    _publish(page, document, [_rich("solo", "Solo?", "G")])
    assert page.locator(".cq-bar").count() == 0
    assert _visible(page, "solo")


def test_a_rewrite_keeps_the_current_question(page, document):
    _queue(page, document)
    page.click('.cq-bar .cq-dot >> nth=1')
    base, sid = document["base"], document["sid"]
    rewritten = _rich("q2", "Question 2, reworded?", "Decisions")
    _call(base, "PUT", f"/s/{sid}/items/q2", rewritten)
    page.wait_for_function(
        "() => document.querySelector('[data-block-id=\"q2\"] .card-title')"
        ".textContent.includes('reworded')", timeout=15000)
    assert _visible(page, "q2") and not _visible(page, "q1")


def test_the_queue_works_with_storage_blocked(page, document):
    # Only the queue's own keys throw, so the rest of the page boots normally
    # and the test is about the queue's try/catch, not the whole page's.
    page.add_init_script("""
      for (const m of ['getItem', 'setItem']) {
        const orig = Storage.prototype[m];
        Storage.prototype[m] = function (k, ...rest) {
          if (String(k).startsWith('annotate.queue:')) throw new Error('blocked');
          return orig.call(this, k, ...rest);
        };
      }
    """)
    _queue(page, document)
    assert page.locator(".cq-bar").count() == 1
    assert _visible(page, "q1")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_choice_queue.py -q -n 0 -k "queue or pick or show_all or position or runs or lone or rewrite or storage or j_and_k"`
Expected: FAIL with `.cq-bar` count 0, or a timeout waiting for it.

- [ ] **Step 3: Announce renders, picks and mark changes**

In `static/script.js`, as the last line of `loadAndRenderBlocks` (after `applyEngagedStyling();`) and as the last line of `reconcile` (after its `applyEngagedStyling();`):

```js
    document.dispatchEvent(new CustomEvent("annotate:rendered"));
```

In `renderChoice`'s `toggleAt`, after `saveAnswer();`:

```js
      // A pick, not a clear: the queue moves on to the next undecided question.
      if (selected.has(opt.id)) {
        document.dispatchEvent(new CustomEvent("annotate:choice-picked",
          { detail: { blockId: blk.id } }));
      }
```

In `static/subunits.js`, at the end of `setChoice` (after `renderDock();`) and at the end of `syncChoices`:

```js
    document.dispatchEvent(new CustomEvent("annotate:choice-changed"));
```

- [ ] **Step 4: Write `static/choice-queue.js`**

```js
// Choice queues. Adjacent choice blocks sharing a spec.group (script.js puts
// it on the section as data-group) show one question at a time, under a bar
// with progress and navigation. Every member stays an ordinary choice section
// rendered by renderChoice, so its answer, comments and rewrites are the ones
// any block has; the queue only decides which member is on screen.
//
// The bar is rebuilt from scratch after every render: reconcile() inserts new
// sections relative to their neighbours, and a bar left in place would end up
// on the wrong side of one.
(function () {
  "use strict";

  const HIDDEN = "cq-hidden";
  let searching = false;
  const at = {};            // run key -> block id of the current member

  const prose = () => document.querySelector("main.prose");
  const rid = () => document.body.dataset.responseId || "default";
  const skey = (run, what) => `annotate.queue:${rid()}:${run.key}:${what}`;
  function load(run, what) {
    try { return window.localStorage.getItem(skey(run, what)); } catch (_) { return null; }
  }
  function save(run, what, v) {
    try { window.localStorage.setItem(skey(run, what), v); } catch (_) {}
  }

  function decided(sec) {
    return !!window.AnnotateSubunits?.choiceMark(sec.dataset.blockId);
  }

  // Runs of two or more adjacent choice sections with equal data-group. Comment
  // wrappers and our own bars sit between sections and do not break a run.
  function runs() {
    const root = prose();
    if (!root) return [];
    const out = [];
    let cur = null;
    for (const el of root.children) {
      if (el.classList.contains("inline-comments") || el.classList.contains("cq-bar")) continue;
      const g = el.matches("section.block") && el.dataset.kind === "choice" ? el.dataset.group : "";
      if (g && cur && cur.group === g) cur.members.push(el);
      else if (g) { cur = { group: g, members: [el] }; out.push(cur); }
      else cur = null;
    }
    const queues = out.filter((r) => r.members.length > 1);
    queues.forEach((r) => { r.key = r.group + "|" + r.members[0].dataset.blockId; });
    return queues;
  }

  const expanded = (run) => searching || load(run, "all") === "1";
  const ids = (run) => run.members.map((m) => m.dataset.blockId);

  function currentIndex(run) {
    let i = ids(run).indexOf(at[run.key] || load(run, "at"));
    if (i < 0) i = run.members.findIndex((m) => !decided(m));
    return i < 0 ? 0 : i;
  }

  function setCurrent(run, i) {
    const id = run.members[i].dataset.blockId;
    at[run.key] = id;
    save(run, "at", id);
  }

  function setHidden(sec, hide) {
    sec.classList.toggle(HIDDEN, hide);
    const ic = sec.nextElementSibling;
    if (ic && ic.classList.contains("inline-comments")) ic.classList.toggle(HIDDEN, hide);
  }

  function bar(run, i, all) {
    const n = run.members.length;
    const done = run.members.filter(decided).length;
    const el = document.createElement("div");
    el.className = "cq-bar";
    el.dataset.run = run.key;
    el.innerHTML =
      '<div class="cq-head"><span class="cq-title"></span>' +
      `<span class="cq-pos">${i + 1} / ${n}</span>` +
      `<label class="cq-all"><input type="checkbox"${all ? " checked" : ""}${searching ? " disabled" : ""}> Show all</label></div>` +
      `<div class="cq-nav"${all ? " hidden" : ""}>` +
      '<button type="button" class="cq-btn" data-step="-1">← Prev</button>' +
      `<div class="cq-progress" role="progressbar" aria-label="Decided" aria-valuemin="0" aria-valuemax="${n}" aria-valuenow="${done}"><i style="width:${(done / n) * 100}%"></i></div>` +
      `<span class="cq-count">${done} of ${n} decided</span>` +
      '<button type="button" class="cq-btn" data-step="1">Skip</button>' +
      '<button type="button" class="cq-btn cq-primary" data-step="1">Next →</button></div>' +
      `<div class="cq-dots"${all ? " hidden" : ""}></div>`;
    el.querySelector(".cq-title").textContent = run.group;
    const dots = el.querySelector(".cq-dots");
    run.members.forEach((m, j) => {
      const d = document.createElement("button");
      d.type = "button";
      d.className = "cq-dot" + (decided(m) ? " done" : "") + (j === i ? " cur" : "");
      d.title = m.querySelector(".card-title")?.textContent || "";
      d.setAttribute("aria-label", `Question ${j + 1}${decided(m) ? ", decided" : ""}`);
      d.addEventListener("click", () => go(run.key, j));
      dots.appendChild(d);
    });
    el.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
      go(run.key, currentIndex(run) + Number(b.dataset.step));
    }));
    el.querySelector(".cq-all input").addEventListener("change", (e) => {
      save(run, "all", e.target.checked ? "1" : "0");
      refresh();
    });
    return el;
  }

  function refresh() {
    const root = prose();
    if (!root) return;
    root.querySelectorAll(":scope > .cq-bar").forEach((b) => b.remove());
    root.querySelectorAll("." + HIDDEN).forEach((el) => el.classList.remove(HIDDEN));
    for (const run of runs()) {
      const all = expanded(run);
      const i = currentIndex(run);
      run.members.forEach((m, j) => setHidden(m, !all && j !== i));
      run.members[0].insertAdjacentElement("beforebegin", bar(run, i, all));
    }
  }

  function reveal(sec) {
    window.AnnotateKeyboard?.focusBlock(sec.dataset.blockId);
    sec.scrollIntoView({ block: "nearest" });
  }

  function go(key, j) {
    const run = runs().find((r) => r.key === key);
    if (!run) return;
    setCurrent(run, Math.max(0, Math.min(run.members.length - 1, j)));
    refresh();
    reveal(run.members[currentIndex(run)]);
  }

  // The page's J/K walker asks this first. It moves within the collapsed
  // queue the block belongs to and returns the new current block id, or null
  // when the step would leave the queue and the walker should carry on.
  function stepFrom(blockId, delta) {
    const run = runs().find((r) => ids(r).includes(blockId));
    if (!run || expanded(run)) return null;
    const j = ids(run).indexOf(blockId) + delta;
    if (j < 0 || j >= run.members.length) return null;
    setCurrent(run, j);
    refresh();
    return run.members[j].dataset.blockId;
  }

  let queued = 0;
  function refreshSoon() {
    if (queued) return;
    queued = requestAnimationFrame(() => { queued = 0; refresh(); });
  }

  document.addEventListener("annotate:rendered", refresh);
  document.addEventListener("annotate:choice-changed", refreshSoon);
  document.addEventListener("annotate:search", (e) => {
    searching = !!(e.detail && e.detail.active);
    refresh();
  });
  document.addEventListener("annotate:choice-picked", (e) => {
    const id = e.detail && e.detail.blockId;
    const run = runs().find((r) => ids(r).includes(id));
    if (!run || expanded(run)) return;
    const i = ids(run).indexOf(id);
    const later = run.members.map((_, j) => j).filter((j) => j > i);
    const earlier = run.members.map((_, j) => j).filter((j) => j < i);
    const next = later.concat(earlier).find((j) => !decided(run.members[j]));
    if (next === undefined) return;
    // Long enough to see the pick land before the question changes.
    setTimeout(() => {
      setCurrent(run, next);
      refresh();
      reveal(run.members[next]);
    }, 180);
  });

  window.AnnotateChoiceQueue = { refresh, stepFrom };
  refresh();
})();
```

- [ ] **Step 5: Load it**

In `static/entry.js`, in the `JS` array, directly after `"subunits.js",`:

```js
  // After subunits.js and script.js: it reads choice marks and the sections
  // script.js builds, and only rearranges what is already on the page.
  "choice-queue.js",
```

- [ ] **Step 6: Make J/K queue-aware**

In `static/script.js`, in the keyboard block's `keydown` handler, replace:

```js
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        move(e.key === "j" ? 1 : -1);
        return;
      }
```

with:

```js
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const delta = e.key === "j" ? 1 : -1;
        // Inside a collapsed choice queue, J/K walk its questions first; past
        // either end they fall through to the ordinary block walk.
        const next = focusId && window.AnnotateChoiceQueue?.stepFrom(focusId, delta);
        if (next) {
          focusId = next;
          const el = paint();
          if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
        move(delta);
        return;
      }
```

- [ ] **Step 7: Style the bar**

Append to `static/style.css`:

```css
/* === Choice queues ===================================================== */
.cq-hidden { display: none !important; }
.cq-bar {
  background: var(--surface);
  border-radius: 14px;
  padding: 12px 18px;
  margin: 0 0 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.cq-head { display: flex; align-items: center; gap: 12px; }
.cq-title { font-weight: 600; color: var(--text-strong); margin-right: auto; }
.cq-pos {
  font: 11px var(--font-code);
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 7px;
}
.cq-all { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-dim); cursor: pointer; }
.cq-nav { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.cq-nav[hidden], .cq-dots[hidden] { display: none; }
.cq-btn {
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  border: 1px solid var(--control-border);
  background: var(--surface);
  color: var(--text-strong);
  border-radius: 8px;
  padding: 5px 12px;
  cursor: pointer;
}
.cq-btn:hover { border-color: var(--accent); }
.cq-btn.cq-primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
.cq-progress { flex: 1; min-width: 120px; height: 8px; background: var(--surface-soft); border-radius: 99px; overflow: hidden; }
.cq-progress i { display: block; height: 100%; background: var(--accent); }
.cq-count { font-size: 13px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
.cq-dots { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.cq-dot {
  width: 12px; height: 12px; padding: 0;
  border-radius: 50%;
  border: 1px solid var(--control-border);
  background: var(--surface-soft);
  cursor: pointer;
}
.cq-dot.done { background: var(--accent); border-color: var(--accent); }
.cq-dot.cur { outline: 2px solid var(--text-strong); outline-offset: 1px; }
.cq-dot:focus-visible, .cq-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

- [ ] **Step 8: Run the tests and watch them pass**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_choice_queue.py -q -n 0`
Expected: all PASS.

Then the whole browser review suite, since J/K and `setChoice` changed: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_review.py -q -n 0`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add skills/annotate/static/choice-queue.js skills/annotate/static/entry.js skills/annotate/static/script.js skills/annotate/static/subunits.js skills/annotate/static/style.css skills/annotate/tests/test_browser_choice_queue.py
git commit -m "feat(annotate): adjacent choices sharing a group render as a one-question-at-a-time queue"
```

---

### Task 4: Search and export see every member

**Files:**
- Modify: `skills/annotate/static/search.js` (`applyFilter`, near line 99)
- Modify: `skills/annotate/static/export.js` (`STRIP` near line 18, `buildProse` near line 205)
- Test: `skills/annotate/tests/test_browser_choice_queue.py` (append)

**Interfaces:**
- Produces: `annotate:search` with `detail.active: boolean`, dispatched on every `applyFilter` call. Task 3's queue listens to it.

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_a_search_shows_the_matching_member_then_collapses_back(page, document):
    _queue(page, document)
    page.fill("#block-search", "Question 3")
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('[data-block-id=\"q3\"]')).display !== 'none'")
    assert page.locator(".cq-bar .cq-all input").is_disabled()
    page.fill("#block-search", "")
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-block-id^=\"q\"]')]"
        ".filter(s => getComputedStyle(s).display !== 'none').length === 1")


def test_an_export_has_every_member_and_no_bar(page, document):
    _queue(page, document)
    html = page.evaluate("() => window.AnnotateExport.buildProse()")
    assert "cq-bar" not in html
    assert "cq-hidden" not in html
    for i in (1, 2, 3):
        assert f'data-block-id="q{i}"' in html
```

`buildProse` is private to `export.js` today; Step 3 exposes it for this test.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_choice_queue.py -q -n 0 -k "search or export"`
Expected: the search test times out (members stay hidden). The export test FAILS on `cq-bar` in the output.

- [ ] **Step 3: Implement**

In `static/search.js`, as the first line inside `applyFilter`'s `try {`:

```js
      // Queues show every member while a query is active, so the filter below
      // sees them like any block (choice-queue.js listens).
      document.dispatchEvent(new CustomEvent("annotate:search",
        { detail: { active: !!(query || "").trim() } }));
```

In `static/export.js`, add to the `STRIP` array:

```js
    ".cq-bar",              // a choice queue's navigation: a view, not content
```

at the end of `export.js`'s IIFE, so the browser test can read what an export would contain:

```js
  window.AnnotateExport = Object.assign(window.AnnotateExport || {}, { buildProse });
```

and in `buildProse`, next to the existing `.search-hidden` loop:

```js
    // A collapsed queue hides all but one question; the export carries them all.
    clone.querySelectorAll(".cq-hidden").forEach((n) => n.classList.remove("cq-hidden"));
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_choice_queue.py skills/annotate/tests/test_smoke_export.py -q -n 0`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/static/search.js skills/annotate/static/export.js skills/annotate/tests/test_browser_choice_queue.py
git commit -m "feat(annotate): search and export see every question in a choice queue"
```

---

### Task 5: Confluence publish shows option content

**Files:**
- Modify: `skills/annotate/confluence/body.py` (the `choice` branch, near line 219)
- Test: `skills/annotate/tests/test_confluence_body.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_an_option_that_carries_markdown_publishes_it_under_its_label():
    out = body.render_block(
        {"id": "section-5", "kind": "choice",
         "spec": {"question": "Which?", "group": "Decisions", "options": [
             {"id": "a", "label": "Original", "markdown": "```java\nclass A {}\n```"},
             {"id": "b", "label": "Now"}]}},
        [])
    assert "Original" in out and "class A {}" in out
    assert out.index("Original") < out.index("class A {}") < out.index("Now")
    assert "Decisions" not in out
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_confluence_body.py -q -n 0 -k markdown_publishes`
Expected: FAIL, `class A {}` not in output.

- [ ] **Step 3: Implement**

Replace the `options = …` expression in the `choice` branch with:

```python
        options = "".join(
            "<li><p>%s</p>%s</li>" % (
                escape(str(o.get("label", ""))),
                to_html(o["markdown"]) if isinstance(o.get("markdown"), str) else "")
            for o in (spec.get("options") or []))
```

- [ ] **Step 4: Run the Confluence tests**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_confluence_body.py -q -n 0`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/confluence/body.py skills/annotate/tests/test_confluence_body.py
git commit -m "feat(annotate): Confluence publish carries a choice option's markdown"
```

---

### Task 6: Teach the skill, and show it in the gallery

**Files:**
- Modify: `skills/annotate/references/block-kinds/choice.md`
- Modify: `skills/annotate/SKILL.md` (the `choice` row of the block-kind menu)
- Modify: `skills/annotate/docs/gallery.html`
- Modify: `docs/superpowers/specs/2026-09-29-rich-choice-queue-design.md` (one line: the two-member minimum)

- [ ] **Step 1: Add to `choice.md`, after "## Block shape"**

```markdown
## Options that carry content

When the options ARE content, such as two versions of a file, two SQL queries or two table
layouts, put the content in the option, not in a separate block above the question:

    {"id": "o1", "label": "Original PR", "markdown": "```java\n...\n```"}

`markdown` renders under the label with the page's normal markdown and code highlighting.
Keep `label` short: it is the option's heading. Use `description` for a one-line gloss beside
the label, and `markdown` for anything longer. The reader can select and copy text inside an
option without picking it.

Questions never nest. When one part of an option needs its own decision, give that part its
own block with its own question.

## Many similar questions: groups

When a page asks the same kind of question many times (one per file, one per finding), give
each question its own choice block and the same `group`:

    "spec": {"question": "What should Asset.java carry?", "group": "Annotation decisions", ...}

Two or more ADJACENT choice blocks with an equal `group` render as one queue: one question
at a time, with progress, Prev and Next, and a "Show all" switch. Keep a group's blocks
together; a block of another kind between them splits the queue in two. Write `group` as a
heading, because it is the queue's title. It is at most 80 characters.

Each question is still its own block: answers arrive as ordinary `choice` reactions with the
question's own `block_id`, and you rewrite or resolve one question without touching the
others.
```

- [ ] **Step 2: Update the `choice` row in `SKILL.md`**

Change the "Use when" cell of the `choice` row to:

```markdown
| `choice` | A decision point with 2–4 discrete options where the pick drives the next step. Options may carry `markdown` (code, tables) when the options are content; many similar questions share a `group` and render as a queue. | `references/block-kinds/choice.md` |
```

- [ ] **Step 3: Pin the two-member minimum in the spec**

In the spec's "Authoring contract" section, after the sentence ending "form one queue.", add: `A run needs at least two blocks; a lone grouped choice renders as an ordinary choice.`

- [ ] **Step 4: Add the gallery samples**

Open `skills/annotate/docs/gallery.html`, find how it declares its sample blocks (`grep -n '"kind": "choice"' skills/annotate/docs/gallery.html`), and add next to the existing choice sample, in the same format:

- one choice block with `"question": "Which version should Asset.java keep?"`, option `o1` labelled "Original PR" with a six-line fenced `java` record carrying two `@Schema` annotations, and option `o2` labelled "Confluence only" with the same record carrying one;
- three adjacent choice blocks with `"group": "Gallery queue"`, questions "First question?", "Second question?" and "Third question?", each with two plain options "Yes" and "No".

Open the gallery in a browser and confirm the rich option shows highlighted Java and the three grouped blocks show one queue bar reading "1 / 3".

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/references/block-kinds/choice.md skills/annotate/SKILL.md skills/annotate/docs/gallery.html docs/superpowers/specs/2026-09-29-rich-choice-queue-design.md
git commit -m "docs(annotate): teach rich choice options and grouped queues, with gallery samples"
```

---

### Task 7: Full suite and the acceptance page

- [ ] **Step 1: Run the whole suite**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`
Expected: all PASS (parallel, about 40 seconds).

- [ ] **Step 2: Reinstall the plugin so the live daemon serves this checkout**

Run whatever `CLAUDE.md` or `docs/` in this repo names for refreshing the installed plugin, then reload an annotate page and confirm `choice-queue.js` is requested (browser network tab, or `curl -s <page>/assets/entry.js | grep choice-queue`).

- [ ] **Step 3: Rebuild the ABC-270 decision page in the new format**

Regenerate `pr2139.json` so each of the 60 files is ONE choice block with `"group": "Annotation decisions"` and three options: `o1` "Original PR" with the `pr-tip` Java as `markdown`, `o2` "Confluence only" (or "No annotations") with the current Java or the line "The file stays exactly as it is on main.", and `o3` "Mix" with `description` "Name the fields to restore in the note". Keep the "How to decide" markdown block first. Push it to the live `abc-270-annotation-decisions` session with `claude-annotate push --slug abc-270-annotation-decisions`.

- [ ] **Step 4: Check it by eye and by payload**

In the browser: the page shows one queue bar reading "1 / 60", rich options with highlighted Java, and J/K walks the questions. Pick two options and submit the round; the event arriving on the watcher carries two `choice` reactions with the two members' own block ids.
