# Rich Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** annotate's section editor opens as the rendered page, editable in place (ProseMirror), for every text section. A small edit saves as a small change to the stored text, whether that text is HTML or markdown. A Rich / Source switch gives the exact text.

**Architecture:** A new lazily-loaded bundle `static/vendor/rich.min.js`, built from `skills/annotate/rich/src/`, does the work. It splits the stored text into blocks with their byte ranges and parses them into a ProseMirror document. On save it writes back only the blocks that changed, by replaying the edit onto the original bytes, and writes a block fresh only when replay fails. `edit.js` mounts it as the default view. CodeMirror stays for Source. The authoring guide switches to markdown first.

**Tech Stack:** ProseMirror (state 1.4.4, view 1.42.6, model 1.25.12, transform 1.12.2, commands 1.7.2, keymap 1.2.3, history 1.5.1, inputrules 1.5.1, schema-list 1.5.1, tables 1.8.5, markdown 1.13.8), esbuild 0.28.2, the page's markdown-it (global `window.markdownit`), Playwright + pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-rich-editing-design.md`. It builds on `docs/superpowers/specs/2026-10-01-editing-design.md`.

**Spike to port from:** branch `rich-edit-spike` (commit `25daee7`, worktree `~/projects/claude-annotate-worktrees/rich-spike`). Read its files with `git show rich-edit-spike:<path>`:
- `skills/annotate/rich/src/{schema,parse,serialize,save,diff,index,markdown-it-shim}.js`
- `skills/annotate/rich/{package.json,build.mjs}`
- `skills/annotate/rich/spike/tests.py` (the 17 measured checks)
- the `edit.js` diff `git diff 8914281 rich-edit-spike -- skills/annotate/static/edit.js`

The spike's `html-edit.js`, `turndown.js` and the `__doc__.html_edit` switch are prototype-only and are NOT carried over.

## Global Constraints

- **The stored text is the truth.** An untouched block keeps its original bytes verbatim. Opening and then Done without an edit leaves the stored text byte-identical.
- **A one-word edit** saves as exactly that word. No other byte changes, including attributes (`data-annotate-id`, `style`, `class`), hard-wrapped lines and separators.
- **Formats are never converted.** An HTML section stays HTML, a markdown section stays markdown, and new blocks are written in the section's format.
- **Paste** keeps only the schema's structure: paragraph, heading, lists, blockquote, code block, hr, hard break, table, and the bold, italic, code and link marks. Foreign spans, styles, classes and `data-*` are dropped.
- **Unchanged from the editing spec:** the save path (If-Match), `mine`, the `edit` round mark, holds, the push guard, drafts, the conflict prompt and the removed-section bar. They all operate on the text the Rich or Source view produces.
- **The edit bar:** state dot and text · `Rich | Source` · key hint · `What will be saved` · `Discard` · `Done`. Live and Split are removed.
- **The Rich hint:** `⌘B bold · ⌘I italic · ⌘E code · ⌘K link · ## heading · - list · F6 bar · esc done`.
- **⌘K** asks for the URL in a field inside the bar, never with `window.prompt`.
- **No browser dialogs** (alert, confirm, prompt) anywhere.
- **Bundles:** both are lazy-loaded, the first line is `/* annotate-rich <sha256 of the sources> */`, and a freshness test fails when sources change without a rebuild.
- **Commits:** one line, no body, no trailers. Never stash, `reset --hard`, `checkout --` or `clean`. Never restart the webcompanion daemon.

## Review Focus

1. **Inline HTML inside a markdown paragraph** (`<kbd>`, `<br>`, `<span style>`, `<sup>`): editing a word elsewhere in that paragraph must keep the inline HTML byte for byte. Replay handles this; a test pins it (Task 1).
2. **Emoji, non-BMP characters, CRLF and lone-CR text:** edits stay byte-exact around them, and an untouched save is identical (Task 1).
3. **Nested and task lists** (`- [ ] item`, a bullet inside an ordered item): an edit inside one keeps the markers and indentation of the rest (Task 1).
4. **A large section** (about 60 KB of markdown): open plus a one-word save each finish in under 1 s in headless Chromium (Task 1).
5. **Rich → Source → Rich with edits in both,** then Discard: the stored text is unchanged. Done saves both sets of edits (Task 2).

---

### Task 1: The rich bundle

**Files:**
- Create: `skills/annotate/rich/package.json`, `skills/annotate/rich/package-lock.json`, `skills/annotate/rich/build.mjs`, `skills/annotate/rich/.gitignore` (`node_modules/`)
- Create: `skills/annotate/rich/src/{schema,parse,serialize,save,diff,keys,paste,index,markdown-it-shim}.js`
- Create: `skills/annotate/static/vendor/rich.min.js` (built)
- Create: `skills/annotate/tests/test_browser_rich.py`, `skills/annotate/tests/test_rich_bundle_fresh.py`
- Create: `skills/annotate/tests/data/rich/abc-314.html.txt`, `skills/annotate/tests/data/rich/abc-270.md.json` (real stored texts: copy the spike's fixtures from `git show rich-edit-spike:skills/annotate/rich/spike/...` or from the live sessions `rich-spike-abc-314` / `rich-spike-markdown` via GET items)

**Interfaces:**
- Produces `window.AnnotateRich`:
  - `formatOf(text) -> "html" | "md"`. HTML when the first non-blank block is an HTML element and every top-level block is an HTML element; otherwise md.
  - `canShow(text, format) -> null | string`. Null when Rich can show it. Otherwise a reason string: `"this section has a table with merged cells"`, or `"this section couldn't be read as blocks"`.
  - `mount(host, {text, format, onChange, onSave, onDone}) -> handle`. It appends one element `.block-content.ed-rich` to `host`.
- The handle:
  - `getText() -> string`: the minimal-change save of the current document.
  - `stats() -> {kept, fresh, hunks}`.
  - `focusAt(offset)`: the offset is a character offset into the rendered plain text (`host.innerText` of the original rendering, as `AnnotateAnchors.textOf` measures it). It places the cursor at the matching document position, or at the start.
  - `setText(text)`: a new base, used to restore a draft or take theirs.
  - `focus()`, `isFocused() -> bool`, `destroy()`.
  - `linkAt() -> {from, to, href} | null` and `setLink(href | null)`, which back the bar's ⌘K field.
  - `onLinkRequest`: a callback the handle calls when ⌘K is pressed.
  - `view`: the ProseMirror EditorView, for tests only.

- [ ] **Step 1: Write the failing tests.** `test_browser_rich.py` uses a bare page, as `test_browser_editor.py` does. It sets content with `static/vendor/markdown-it.min.js` (or whatever `script.js` loads; find it with `grep -n markdownit skills/annotate/static/*.js skills/annotate/static/entry.js`) plus `rich.min.js`. Helpers:

```python
def mount(page, text, fmt=None):
    return page.evaluate("""([t, f]) => {
        document.body.innerHTML = '<div id=h></div>';
        const fmt = f || AnnotateRich.formatOf(t);
        window.ed = AnnotateRich.mount(document.getElementById('h'), {text: t, format: fmt});
        return fmt; }""", [text, fmt])

def edit_word(page, old, new):
    """Select the first `old` in the document and type `new` over it, as a reader would."""
    assert page.evaluate("w => { const v = ed.view; let at = null;"
        " v.state.doc.descendants((n, p) => { if (at || !n.isText) return !at;"
        "   const i = n.text.indexOf(w); if (i >= 0) at = [p + i, p + i + w.length]; return false; });"
        " if (!at) return false; const {TextSelection} = AnnotateRich.pm;"
        " v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, at[0], at[1]))); v.focus(); return true; }", old)
    page.keyboard.insert_text(new)

def saved(page):
    return page.evaluate("() => ed.getText()")
```

(`AnnotateRich.pm` re-exports `TextSelection` for tests.)

Cases. Each asserts the exact saved string, built as `original.replace(old, new, 1)` or an exact expected string:
- **HTML (ABC-314 fixture):** `posted`→`sent`; `Fill`→`Populate` inside a `<li data-annotate-id>`; an untouched save is byte-identical; the counts of `data-annotate-id` (20) and `style=` (3) are unchanged after an edit.
- **Markdown (ABC-270 fixture):**
  - `later`→`follow-up`;
  - an edit inside a list item;
  - an edit inside a markdown table cell;
  - an edit inside a raw `<table>` cell within markdown;
  - an untouched save is identical;
  - a hard-wrapped paragraph edited across a wrap point keeps every `\n`.
- **Typed structure:**
  - In markdown, after the last block, type Enter, then `- `, then `A new bullet with **bold** and `code` typed.` Expect exactly one added block, `- A new bullet with **bold** and `code` typed.`, and nothing else changed.
  - Then `## A new heading`, giving `## A new heading`.
  - The same in HTML gives `<ul><li>…<strong>bold</strong>…<code>code</code>…</li></ul>` and `<h2>A new heading</h2>`.
- **Paste:** dispatch a paste of the spike's Slack fragment (`git show rich-edit-spike:skills/annotate/rich/spike/tests.py`, search for "Slack"). It stores as the spike's clean HTML or markdown, with no `style`, `class`, `span` or `data-stringify`.
- **Keys:** ⌘B, ⌘I and ⌘E toggle marks; ⌘Z undoes. Enter on an empty list item leaves the list, Tab in a list item indents it, and Tab in a table cell moves to the next cell without selecting its text (the selection is empty afterwards).
- **Review Focus 1:** the markdown `Press <kbd>Esc</kbd> to close.<br>Then **save** the file.` with `close`→`dismiss` is byte-exact otherwise.
- **Review Focus 2:**
  - `Ship it 🚀 now.\r\nNext line 😀 here.\r\n` with `now`→`today` is byte-exact; an untouched save of it is identical.
  - A lone-CR text is byte-exact.
- **Review Focus 3:** with `1. First\n   - nested a\n   - nested b\n2. Second\n\n- [ ] todo one\n- [x] done two\n`, editing `nested b`→`nested bee` keeps everything else; editing `todo one`→`todo uno` keeps `- [ ] `.
- **Review Focus 4:** a 60 KB markdown text (repeat the ABC-270 fixture until it is at least 60,000 chars). `mount` plus a one-word `edit_word` plus `getText` take under 1000 ms (`performance.now()` in the page).
- **canShow and formatOf:**
  - A table with `colspan="2"` returns the merged-cells reason.
  - `formatOf` returns `"html"` for ABC-314 and `"md"` for ABC-270 and for `"Text\n\n<table>…</table>\n"`.
- **focusAt:** mount ABC-270, call `focusAt(textOf(original rendering).indexOf("follow"))`, type `X`, and assert `X` lands right before `follow`.

`test_rich_bundle_fresh.py` mirrors `test_editor_bundle_fresh.py`: the first line of `rich.min.js` carries the sha256 of the concatenated `rich/src/*.js` plus `package-lock.json`, in sorted path order.

- [ ] **Step 2: Run, and confirm they fail.** Run `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_rich.py skills/annotate/tests/test_rich_bundle_fresh.py -q -n 0`. Expected: they FAIL with `rich.min.js` missing.

- [ ] **Step 3: Implement.** Port the spike's `src/*.js`, with these changes:
  - Split `index.js` so that input rules and the keymap move to `keys.js`, and paste cleaning (`cleanPastedHtml`, `stripSlice`) moves to `paste.js`.
  - Replace `linkCmd`'s `window.prompt` with `onLinkRequest(handle)`. The bar (Task 2) calls `setLink`.
  - Add `formatOf`, `canShow` and `focusAt`. For `focusAt`, walk the document's text nodes and accumulate text length, counting block boundaries the way `innerText` does: `\n\n` between paragraphs and `\n` for a hard break. Then map the offset to a position. Verify it against the rendered text in the test.
  - Add `setText`, `isFocused` and `pm`, which re-exports `{TextSelection}`.
  - Keep the spike's shim-free API: no `view.dispatch(spec)` emulation.
  - `build.mjs` writes the freshness header line before the minified code and prints its size.
  - Pin `package.json` to the Tech Stack versions and commit `package-lock.json`.
  - Run `npm ci` in `skills/annotate/rich`, then `node build.mjs`.

- [ ] **Step 4: Run and confirm they pass.** Run the same command. Expected: all PASS. Then break one byte-exactness path on purpose (for example, make `minimalSave` always write fresh), watch three cases fail, and restore it.

- [ ] **Step 5: Commit.** `git add skills/annotate/rich skills/annotate/static/vendor/rich.min.js skills/annotate/tests/test_browser_rich.py skills/annotate/tests/test_rich_bundle_fresh.py skills/annotate/tests/data/rich && git commit -m "feat(annotate): the rich editor bundle — edit the rendered section, save only what changed"`

### Task 2: Rich is the default view in the editor

**Files:**
- Modify: `skills/annotate/static/edit.js` (mount and view switch, bar, ⌘K field, What will be saved, fallback to Source, focusAt, F6, hint)
- Modify: `skills/annotate/static/style.css` (`.ed-rich` styles that match `.block-content`, code colours, the bar's link field, the Rich / Source switch)
- Modify: `skills/annotate/tests/test_browser_edit.py` (drive Rich by default, and Source where a test needs exact typing)
- Test: `skills/annotate/tests/test_browser_edit_rich.py` (new)

**Interfaces:**
- Consumes `AnnotateRich` from Task 1, and the existing `AnnotateEditor.mount(...)` CodeMirror handle for Source.
- Produces:
  - `AnnotateEdit.view() -> "rich" | "source"`.
  - `AnnotateEdit.editor()`, which now returns `{kind: "rich" | "source", getText, focus, ...}`. Tests use `AnnotateEdit.editor().getText()`.
  - `AnnotateEdit.setView("rich" | "source")`.

- [ ] **Step 1: Write the failing tests** in `test_browser_edit_rich.py`. Reuse the `document`, `page`, `_put_block` and `_call` fixtures from `test_browser_review.py`, as `test_browser_edit.py` does.
  - **Opening:**
    - `e` opens Rich. `.ed-rich` is visible, `AnnotateEdit.view() == "rich"`, and the card's top and width are unchanged within 1 px.
    - The bar shows `Rich` and `Source`, and has no `Live` or `Split`.
    - The hint text equals the Global Constraints string.
  - **Cursor:** select the words "long enough" in section-1, click ✎ in the menu, and type `X`. The stored markdown after Done has `X` immediately before "long enough".
  - **Saving:**
    - Type a word in Rich, press ⌘S, and GET the item: the markdown equals the original with only that word inserted.
    - Open and Done untouched: the version is unchanged and no PUT is sent (count requests).
  - **Switching:**
    - Rich edit, ⌘/ to Source: the CodeMirror text contains the Rich edit.
    - Edit in Source, ⌘/ back to Rich, then Done: the stored text has both edits.
    - **Review Focus 5:** Rich edit, Source edit, Rich, then Discard and confirm: the stored text is unchanged.
  - **Fallback:** a section whose markdown has a `<table>` with `colspan="2"` opens in Source with the bar text "Rich editing isn't available for this section — showing the source". ⌘/ is refused with the reason in a toast.
  - **⌘K:** select a word, press ⌘K, and the bar shows a URL field. Type `https://x.test` and Enter. The stored markdown has `[word](https://x.test)`. No dialog event fires; register `page.on("dialog")` and assert it was never called.
  - **What will be saved:** after an edit, clicking it shows a diff with exactly one change. Clicking again hides it.
  - **F6** from the text focuses the bar's first button, and F6 again returns focus to the text.
  - **Bundle failure:** route `**/vendor/rich.min.js` to 404. The editor opens in Source with "Rich editing could not load (HTTP 404)".
  - **Code blocks:** a fenced `py` block shows the page's colour classes inside `.ed-rich` (use the same `hljs-*` or `tok-*` classes `script.js` emits; find them with `grep -n "hljs\|highlight" skills/annotate/static/script.js`).

- [ ] **Step 2: Run, and confirm they fail.** Run `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_edit_rich.py -q -n 0`. Expected: FAIL.

- [ ] **Step 3: Implement** in `edit.js`:
  - **Loading:** lazy-load `rich.min.js` the same way `editor.min.js` is loaded.
  - **On open:** call `canShow`. Mount Rich, or fall back to Source with the reason. Rich mounts into the card in place of `.block-content`, so the page styles apply.
  - **Switching:** `getText()` from the current view becomes the new view's text.
    - Rich → Source mounts CodeMirror with that text.
    - Source → Rich calls `canShow` first and refuses with a toast when it returns a reason.
  - **Dirty tracking** compares `getText()` with the stored text.
  - **Unchanged paths:** the save path, drafts, conflict, take theirs (`setText`), holds and `mine` stay as they are, all fed by `getText()`.
  - **Bar:** replace the Live / Source / Split segment with Rich | Source and update the hint per view.
  - **⌘K:** add the link field. It is an `<input>` in the bar, shown on `onLinkRequest`; Enter calls `setLink`, and Esc cancels and refocuses the text.
  - **F6** moves focus between the text and the bar.
  - **Code blocks:** use a node view or decoration that runs the page's highlighter over the code text.
  - **Migration:** update `test_browser_edit.py` helpers (`_set_text` and others) to work through `AnnotateEdit.editor().getText()` and Source where they type raw markdown. Keep every existing assertion's meaning.

- [ ] **Step 4: Run and confirm they pass.** Run `test_browser_edit_rich.py`, `test_browser_edit.py` and `test_browser_edit_diff.py` with `-n 0`. Expected: PASS. Then run the full suite once: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`.

- [ ] **Step 5: Commit.** `git commit -am "feat(annotate): sections open as the page itself, with a Rich / Source switch"`. Run `git add` on the new test file first.

### Task 3: Source-only CodeMirror bundle

**Files:**
- Modify: `skills/annotate/editor/src/index.ts`, `skills/annotate/editor/src/livePreview.ts` (delete), `skills/annotate/editor/build.mjs` if it lists files
- Modify: `skills/annotate/static/vendor/editor.min.js` (rebuilt)
- Modify: `skills/annotate/tests/test_browser_editor.py`

**Interfaces:**
- Produces `AnnotateEditor.mount(host, {doc, onSave, onDone, onChange})`. It always uses the source mode, and `setMode` is removed. Task 2's caller passes no `mode`; if Task 2 still passes `mode`, it is ignored.

- [ ] **Step 1: Write the failing test.** In `test_browser_editor.py`, assert that `AnnotateEditor.mount(...)` without `mode` shows line numbers. Assert that the bundle contains no live-preview class names (`"cm-lp-"` not in the `editor.min.js` text). Delete the live-mode-only cases. Keep every byte-exactness sample, run in source mode.
- [ ] **Step 2: Run, and confirm it fails.** Run `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_editor.py skills/annotate/tests/test_editor_bundle_fresh.py -q -n 0`. Expected: FAIL on `cm-lp-`.
- [ ] **Step 3: Implement.** Remove the live preview and its CSS from `style.css` (`cm-lp-*` rules), then rebuild with `node build.mjs` in `skills/annotate/editor`.
- [ ] **Step 4: Run and confirm they pass.** Run the same tests plus `test_browser_edit.py` and `test_browser_edit_rich.py` with `-n 0`. Expected: PASS. Report the new bundle size.
- [ ] **Step 5: Commit.** `git commit -am "refactor(annotate): the CodeMirror bundle is source view only"`.

### Task 4: Markdown first

**Files:**
- Modify: `skills/annotate/references/pushing.md` (around lines 175-290: the `data-annotate-id` instructions and HTML examples), and the block-kind references under `skills/annotate/references/block-kinds/` that tell Claude to write HTML for prose, lists or tables
- Modify: `skills/annotate/references/handling-events.md` (one keep-format rule)
- Test: `skills/annotate/tests/test_round_contract.py`, or the existing reference-doc source-string tests (find them with `grep -rln "pushing.md" skills/annotate/tests`)

- [ ] **Step 1: Write the failing tests.** Slice each to its own paragraph or bullet:
  - `pushing.md` says text sections are written in markdown.
  - It no longer instructs `data-annotate-id` for prose, lists or tables. Assert that the old sentence "Mark commentable sub-units with `data-annotate-id`" is gone.
  - It names the three HTML exceptions: merged table cells, a callout with no markdown form, and `kind: "mockup"`.
  - `handling-events.md` says to keep a section's format when rewriting it: "An HTML section stays HTML unless the reader asks otherwise."
  - It says `step_id` still arrives for sections that carry `data-annotate-id`.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Rewrite the docs** in their existing voice. Replace HTML examples for prose, lists and tables with markdown examples.
- [ ] **Step 4: Run and confirm they pass.** Run the full suite once.
- [ ] **Step 5: Commit.** `git commit -am "docs(annotate): write sections in markdown, HTML only where markdown can't say it"`.

### Task 5 (controller): live check

1. Serve fresh copies of ABC-314 and ABC-270 from the worktree. Use the Task 8 script of the editing plan (`scratchpad/live/live_check.py`) adapted to Rich.
2. In Rich, run each check and confirm the stored diff:
   - a one-word edit;
   - a new bullet with `**bold**`;
   - a `## ` heading;
   - a ⌘K link;
   - Rich → Source → Rich;
   - a Claude push while the section is open (held);
   - a conflict from a foreign PUT.
3. Take light and dark screenshots of Rich and Source, and send them to the user.
4. Merge to main, push, and remove the worktree. The user then checks Safari by hand.
