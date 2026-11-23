# Rich editing in annotate

Date: 2026-10-02. Status: direction approved by the user ("C is amazing"; Rich / Source switch; markdown for new pages). Written spec awaiting review.

Builds on: `docs/superpowers/specs/2026-10-01-editing-design.md` (the in-place editor, saves, `mine`, holds, the push guard). Everything there still holds unless this spec says otherwise.

Evidence the decisions rest on:
- Four prototypes of how to edit a section stored as HTML, on branch `html-edit-options` (`d2181c6`). The user chose C, "edit the page itself".
- A ProseMirror spike on branch `rich-edit-spike` (`25daee7`). It passed 17 of 17 measured checks in Chromium against the live daemon, on an HTML page (ABC-314) and a markdown page (ABC-270). The measurement scripts are in `skills/annotate/rich/spike/` on that branch.

## 1. What this changes, and why

Today the editor shows a section's stored text in CodeMirror. When Claude wrote the section as HTML, which it often does, that is one unreadable line of tags. The user wants to shape the words, not the markup.

So the default editor becomes the page itself. The section stays rendered, exactly as it reads, and the user types into it. Formatting comes from markdown-style shortcuts and the usual keys. The stored text, HTML or markdown, is changed only where the user changed it.

Success looks like this:

- Pressing `e` or ✎ makes the rendered section editable in place. Nothing moves, and the cursor lands at the selected words.
- A one-word edit saves as exactly that word. Every other byte of the stored text is unchanged, including attributes such as `data-annotate-id` and `style`, hard-wrapped lines, and the blank lines between blocks.
- Opening and closing without an edit leaves the stored text byte-identical.
- Typing `## `, `- `, `1. `, `> `, ```` ``` ````, `**x**`, `*x*` or `` `x` `` produces a heading, list, quote, code block, bold, italic or code. The stored form is clean markdown in a markdown section and clean HTML in an HTML section.
- Pasted rich text, from Slack, Confluence or a browser, is reduced to the same clean set.
- One switch shows the exact stored text in a Source view, and switching back and forth loses nothing.
- New pages are written in markdown.

## 2. Decisions

| # | Question | Decision |
|---|----------|----------|
| A | Default editing surface | **Rich**: the rendered section, editable (ProseMirror). For every text section, HTML or markdown. |
| B | Access to the markup | A **Rich / Source** switch in the edit bar. Source is today's CodeMirror editor on the exact stored text. Live and Split go away, because Rich already shows the rendering. |
| C | What is stored | Whatever the section already is. HTML stays HTML and markdown stays markdown. Only the blocks the user changed are rewritten (§3.4). No migration. |
| D | Format of new pages | Markdown. The authoring guide stops asking for HTML and `data-annotate-id`, and keeps HTML for what markdown cannot express (§3.6). |
| E | "What will be saved" | Kept as a bar toggle: a word diff of the stored text against what Done would save. |

## 3. Behaviour

### 3.1 Opening

- **Ways in are unchanged.** `e` on a focused section, ✎ in the selection menu, and a whole-section selection all open the editor. They now open the **Rich** view.
- **The cursor** goes to the start of the selected words. With no selection it goes to the start of the section.
- **The card** keeps its layout. The section's content is replaced by the editable rendering, which uses the page's own styles, so nothing shifts. The card gets the same 2px accent outline as today.
- **Sections that can't open in Rich** open in Source with a note in the bar: "Rich editing isn't available for this section — showing the source". This applies when the stored text cannot be split into blocks (§3.4) or holds content the editor's model cannot represent (§3.3).
- **Unchanged:** non-text kinds (choice, sequence, diagram, flowchart, mockup) are not editable, and neither is a read-only page.

### 3.2 The edit bar

- The bar shows, from left to right:
  - the state dot and state text ("Editing", "Unsaved changes", "Saving…")
  - the **Rich | Source** switch
  - the key hint
  - **What will be saved**
  - **Discard** and **Done**
- **Keys:**
  - `⌘/` flips Rich and Source.
  - `⌘S` saves, and `Esc` is Done.
  - `F6` moves focus between the text and the bar.
- **The hint in Rich** reads `⌘B bold · ⌘I italic · ⌘E code · ⌘K link · ## heading · - list · F6 bar · esc done`. In Source it shows today's hint.
- **Unchanged from the editing spec:** the conflict prompt, the removed-section bar, the draft restore and the hold-lost notice.

### 3.3 Editing in Rich

- **Structure the model holds:**
  - Blocks: paragraph, heading (levels 1 to 6), bullet list, ordered list, list item, blockquote, code block (with language), horizontal rule, hard break, table (header row, rows, cells).
  - Marks: bold, italic, inline code, link.
- **Attributes:** every node and mark keeps unknown HTML attributes it was parsed with, such as `data-annotate-id`, `style` and `class`. They are written back unchanged.
- **Input rules (typed):**
  - `## ` at the start of a block gives a heading, with the level set by the number of `#`.
  - `- ` or `* ` gives a bullet list, and `1. ` an ordered list.
  - `> ` gives a quote, and ```` ``` ```` a code block.
  - `**x**` gives bold, `*x*` italic, and `` `x` `` code.
- **Keys:**
  - ⌘B, ⌘I and ⌘E toggle bold, italic and code.
  - ⌘K links the selection. It asks for the URL inside the bar, never with a browser prompt.
  - ⌘Z and ⇧⌘Z undo and redo.
  - In a list, Enter makes a new item, and Enter on an empty item leaves the list. Tab and ⇧Tab indent and outdent.
  - In a table, Tab moves to the next cell without selecting its text.
- **Paste** is parsed through the same model. Anything outside it (spans, inline styles, classes from foreign pages, `data-*` from other apps) is dropped, and the text and the structure the model holds are kept. Plain text pastes as text.
- **Code blocks** show the page's syntax colours while editing.
- **The selection menu** stays quiet inside the editor, as it does today.

### 3.4 Saving: only what changed

The stored text is the truth. Rich editing never re-writes a block the user did not change.

1. **On open**, the stored text is split into top-level blocks, each with its exact byte range.
   - For markdown, the blocks come from markdown-it's block tokens and their line maps.
   - For HTML, they are the top-level elements.
   - The bytes between blocks, called separators, are recorded too.
2. **Each block** is parsed into the editor's model, and the model remembers which block every top-level node came from.
3. **On save**, each top-level node of the edited document is matched to its origin:
   - An **unchanged node** writes its original bytes, verbatim.
   - A **changed node** has the editor's own text changes replayed onto the original bytes of its block. The result is kept only if it re-parses to the edited node. Otherwise that one block is written fresh, as HTML in an HTML section and as markdown in a markdown section.
   - A **new node** is written fresh.
   - A **deleted node** drops its byte range and one adjacent separator.
4. **Separators** between two original neighbours are kept as they were. A new block gets the section's most common separator.
5. **What is sent** is the resulting text. It goes through the existing save path: If-Match, `mine` computed from the stored text before and after, the `edit` round mark, holds, and the push guard.

Hard-wrapped markdown keeps its line breaks through an edit, because the replay works on the original bytes. A fresh write happens only when replay can't reproduce the edit. The fresh block is then written as one line per paragraph. That is the one place this design can change bytes the user didn't type, and it is limited to the block they edited.

### 3.5 Source view

- **Source** is today's CodeMirror editor on the exact text.
- **Switching from Rich to Source** runs §3.4 on the current Rich document and opens Source on the resulting text. The cursor is placed in the block it was in.
- **Switching from Source to Rich** re-splits and re-parses the Source text.
  - If the text can't be shown in Rich (§3.1), the switch is refused with the reason, and Source stays.
- Undo history is per view. A switch starts a new history, and the bar's Discard still reverts to the stored text.

### 3.6 Authoring: markdown first

`references/pushing.md` and the block-kind references change:

- **Text sections are written in markdown.** Use headings, lists, tables, bold, code and links.
- **The `data-annotate-id` instruction is removed for prose, lists and tables.** Since the selection menu, any selected words can be commented on.
- **HTML stays allowed only where markdown can't express the thing:**
  - merged table cells;
  - a coloured callout that the page has no markdown form for;
  - `kind: "mockup"`.
- **`step_id` stays supported.** A section that still carries `data-annotate-id` keeps reporting it in reactions, so older pages keep working.

`handling-events.md` gains one line: when rewriting a section, keep its format. An HTML section stays HTML unless the reader asks otherwise.

## 4. Architecture

| Unit | Where | Does |
|------|-------|------|
| `rich/` source | `skills/annotate/rich/src/` | ProseMirror schema with attribute pass-through, parsers (markdown via the page's markdown-it, HTML via DOM), serialisers (markdown via prosemirror-markdown, HTML via DOM), input rules, keymap, the block map and minimal-change save, and paste rules. `index.js` exposes `window.AnnotateRich.mount(host, {text, format, onChange, onSave, onDone}) → {getText, focusAt(offset), destroy}`. |
| `rich` build | `skills/annotate/rich/package.json` + `build.mjs` | esbuild, pinned versions, one IIFE file. It reuses the page's markdown-it instead of bundling a second copy. |
| `static/vendor/rich.min.js` | committed build output | Loaded lazily the first time Rich opens, like `editor.min.js`. About 270 KB minified (85 KB gzipped) in the spike. The first line carries a freshness hash. |
| `edit.js` | existing | Gains the Rich view, the Rich / Source switch with the conversion in §3.5, the ⌘K link field in the bar, and the "What will be saved" toggle. Live and Split are removed. Save, holds, conflict, drafts and `mine` are unchanged and work on the text either view produces. |
| `editor/` (CodeMirror) | existing | Kept for Source. The live-preview code becomes unused and is removed from the bundle. |
| `references/pushing.md`, block-kind references | docs | Markdown first (§3.6). |
| `references/handling-events.md` | docs | Keep a section's format when rewriting. |

Format detection: a section is **HTML** when its first non-blank block is an HTML element and the rest consists of HTML elements. Otherwise it is **markdown**, and HTML blocks inside it are parsed as HTML blocks with their own byte ranges. The spike handled a raw `<table>` inside a markdown section this way.

## 5. Errors and limits

| Situation | What the user sees |
|-----------|--------------------|
| The Rich bundle fails to load | The editor opens in Source with "Rich editing could not load (HTTP n)". |
| The stored text can't be shown in Rich | The editor opens in Source with the reason (§3.1). |
| Replay can't reproduce an edit to a block | Nothing visible on save. That block is written fresh, and "What will be saved" shows it. |
| HTML whose tags don't close | It becomes one block. Edits still replay onto its bytes, with fresh write as the fallback. |
| Markdown with reference-style links (`[x][1]`) | The definitions are kept verbatim as their own block, and the links still resolve. |
| Safari input differences | Covered by a manual check before release (§6). |

## 6. Testing

- **Unit (bare page):**
  - Block splitting and separators for markdown and HTML.
  - Minimal-change save, written as one test per spike case: a word in a paragraph, a list item, a table cell (markdown and HTML), a new bullet, a new heading, bold and code typed, delete a block, untouched save, a hard-wrapped paragraph, attributes kept.
  - Paste cleaning on a Slack fragment and a Confluence fragment.
  - Every input rule and key.
- **Browser (daemon-backed):**
  - `e` and ✎ open Rich in place with no layout shift (measured), and the cursor is at the selected words.
  - Done stores exactly the expected bytes.
  - Rich → Source → Rich keeps every edit.
  - The conflict, draft, holds and `mine` paths work in Rich, by re-running the existing editing tests with Rich as the default.
  - A section that can't open in Rich opens in Source with the reason.
- **Real pages:** the spike's ABC-314 and ABC-270 measurements become a fixture-based regression test, with the two pages' stored text copied into the test data.
- **Docs:** source-string tests for the markdown-first authoring rules and the keep-format rule.
- **Manual before release:** Safari on the Mac and iOS. Check typing, accents and dead keys, autocorrect, paste from Slack, and selection across table cells.

## 7. Out of scope

- Converting existing HTML sections to markdown.
- Editing non-text kinds (choice, sequence, diagram, flowchart, mockup) richly.
- Comments or suggestions inside the editor (track changes).
- Merged-cell table editing in Rich. Such tables open in Source.
