# Compact Control and Coherence Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the annotate page's private fold with a `compact` round control that removes content from the page while absorbing its information into the surviving prose, and add a document-wide coherence sweep that runs after every round and before the page unlocks.

**Architecture:** Compact becomes a fourth kind in the existing round vocabulary, so it reuses the round's storage, wire format, submit path and owner gate — the only server change is one tuple entry. The sweep is a contract change in `references/handling-events.md` with no code at all: it is a reasoning pass Claude performs over a `blocks.json` it has already read, positioned between applying the round and writing the `.ack` that unlocks the page.

**Tech Stack:** Python 3 stdlib (`http.server`, no framework), vanilla browser JS (no build step, no bundler), plain CSS with custom properties, `unittest` + `pytest` for tests. Skill contracts are markdown under `skills/annotate/references/`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-annotate-compact-and-sweep-design.md`. Read it before starting.
- Branch: `annotate-compact-and-sweep`, already created, spec already committed.
- Baseline: `python3 -m pytest skills/ -q` → **742 passed**. Every task must end green.
- **No off-page store of compacted content.** Not in `blocks.json`, not in a side file, not anywhere. The page is the contract.
- **No on-page residue of a compact.** No trailer, no count, no stub, no "3 compacted" chip.
- Compact is **owner-only**. It must never be usable on a read-only link.
- Frontend has no build step. Files under `skills/annotate/static/` are served verbatim; edit them directly.
- Smoke tests in this repo are **source-string assertions** (see `test_smoke_dismiss_lock.py` for the house style). They read the file and assert substrings. Match that style exactly — do not introduce a JS test runner.
- Run tests with `python3 -m pytest` from the repo root, never bare `pytest`.

### One deviation from the spec, deliberate

The spec's "Frontend" section says the fold's classes get renamed —
`.unit-read` → `.unit-compact`, `.hover-read` → `.hover-compact` — because it
assumed compact would need a separately-appended button like the fold had.

Reading the render loops showed it does not. The card-header loop already
routes anything that is not `comment` to `toggleBlockMark`, and the sub-unit
loop needs only `textContent` → `innerHTML` to carry an SVG glyph. So compact
joins `ACTION_TYPES` and `CONTROL_SPECS` as an ordinary fourth entry and is
addressed by `[data-kind="compact"]` / `[data-type="compact"]`, exactly like
the other three. **No `.unit-compact` or `.hover-compact` class is created.**

This is strictly smaller and keeps all four controls on one code path. Where
this plan and the spec disagree on that detail, follow the plan. Everything
else in the spec stands.

---

### Task 1: Server accepts `compact` as a round kind

The server validates round reactions against an allowlist tuple. Compact travels on the existing `/api/submit` route with `type: "round"`, so this one tuple entry is the entire server change. Writes are gated on `_dispatch_post` in the shared engine rather than per-route, so compact inherits the owner 403 with no extra code.

**Files:**
- Modify: `skills/annotate/server.py:480`
- Test: `skills/annotate/tests/test_server_round.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the wire kind string `"compact"`, valid at `scope: "unit"` and `scope: "block"`, carrying an empty `text`. Tasks 2 and 3 emit it from the browser; Task 4 tells Claude what to do with it.

- [ ] **Step 1: Write the failing tests**

Append to `skills/annotate/tests/test_server_round.py`, inside `class SubmitRoundTests`:

```python
    def test_compact_is_a_round_kind_at_both_scopes(self):
        """Compact rides the round like the other three kinds.

        Unit scope anchors by selected_text; block scope by block_id alone.
        """
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("compact"),
            {"kind": "compact", "scope": "block", "block_id": "section-2",
             "selected_text": ""},
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual([r["kind"] for r in evt["reactions"]],
                         ["compact", "compact"])
        self.assertEqual(evt["reactions"][0]["scope"], "unit")
        self.assertEqual(evt["reactions"][1]["scope"], "block")

    def test_compact_carries_no_text(self):
        """Only `comment` requires non-empty text. Compact says nothing —
        it is a request to remove, not a message."""
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("compact", text=""),
        ]})
        self.assertEqual(status, 202, body)

    def test_unknown_kind_is_still_refused(self):
        """Guard the allowlist itself: widening it for compact must not
        turn it into a pass-through."""
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("squash"),
        ]})
        self.assertEqual(status, 422, body)
        self.assertIn("bad kind", body)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest skills/annotate/tests/test_server_round.py -q -k compact
```

Expected: 2 failures. `test_compact_is_a_round_kind_at_both_scopes` and `test_compact_carries_no_text` both get 422 with `bad kind 'compact'` instead of 202. (`test_unknown_kind_is_still_refused` passes already — it is a regression guard, not a driver.)

- [ ] **Step 3: Add the kind**

In `skills/annotate/server.py`, line 480, change:

```python
    _ROUND_KINDS = ("delete", "keep", "comment")
```

to:

```python
    # `compact` removes content from the page but NOT from the plan: Claude
    # absorbs its contribution into the surviving prose. That is what makes it
    # a distinct kind rather than an alias for delete, which means "out of
    # scope, never act on this again". See references/handling-events.md.
    _ROUND_KINDS = ("delete", "keep", "comment", "compact")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest skills/annotate/tests/test_server_round.py -q
```

Expected: all pass.

- [ ] **Step 5: Run the full suite**

```bash
python3 -m pytest skills/ -q
```

Expected: `745 passed` (742 baseline + 3 new).

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/server.py skills/annotate/tests/test_server_round.py
git commit -m "feat(annotate): the round vocabulary accepts compact"
```

---

### Task 2: Remove the private fold

The fold is being replaced, not extended, so it comes out first and in full. This leaves a working page with three controls and no eye button — a correct intermediate state, just without compact yet.

The fold's two behavioural exemptions come out with it. Read-only mode currently keeps the fold alive as the one thing a guest can do; that carve-out is exactly what must not survive, since compact is an owner-only edit. The `is-busy` exemption goes for the same reason: compact is a round control and must be locked while a round is in flight.

`_ICON_FOLD` is deleted here and re-added as `_ICON_COMPACT` in Task 3. That is deliberate — leaving an unused constant behind for one commit is worse than re-adding five lines.

**Files:**
- Modify: `skills/annotate/static/subunits.js`
- Modify: `skills/annotate/static/script.js:124-136`
- Modify: `skills/annotate/static/style.css`
- Modify: `skills/annotate/server.py` (the `_ICON_FOLD` constant and `_LEGEND_HTML`)
- Modify: `skills/annotate/tests/test_smoke_read_only.py`
- Create: `skills/annotate/tests/test_smoke_compact.py`
- Delete: `skills/annotate/tests/test_smoke_read_fold.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a `.unit-strip` containing exactly the three `CONTROL_SPECS` buttons, a `.hover-actions` containing exactly the three `ACTION_TYPES` buttons, and a `window.AnnotateSubunits` export object with no read/fold members. Task 3 adds the fourth control to both.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_compact.py`:

```python
"""Structural guards for the compact control.

Compact replaced the private fold. Its first guarantee is therefore a
negative one: the fold apparatus must be gone, not merely unreferenced.
A surviving `data-read` rule or an orphaned `toggleUnitRead` is how a
replaced feature comes back to life six months later.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"
SERVER_PY = REPO / "skills" / "annotate" / "server.py"

# Every identifier the fold owned. None may survive in any form.
FOLD_JS_SYMBOLS = (
    "annotate.read.", "READ_KEY", "loadRead", "saveRead",
    "toggleUnitRead", "toggleBlockRead", "applyReadState", "applyBlockRead",
    "readKeyForUnit", "foldable", "READ_ICON", "READ_TITLE",
)
FOLD_CSS_SELECTORS = ('[data-read="1"]', ".unit-read", ".hover-read")


def test_the_private_fold_is_gone_from_the_javascript():
    for path in (SUBUNITS_JS, SCRIPT_JS):
        src = path.read_text()
        for dead in FOLD_JS_SYMBOLS:
            assert dead not in src, f"{path.name} still carries {dead!r}"


def test_the_private_fold_is_gone_from_the_css():
    css = STYLE_CSS.read_text()
    for dead in FOLD_CSS_SELECTORS:
        assert dead not in css, f"style.css still styles {dead!r}"


def test_the_round_store_survived_the_removal():
    """The fold had its own key space. Deleting it must not have taken the
    marks store with it."""
    src = SUBUNITS_JS.read_text()
    assert "annotate.round." in src, "the round storage key vanished"


def test_no_control_survives_a_read_only_link():
    """The fold used to be the one thing a guest could do, because it never
    reached the server. Compact is an edit, so nothing is left to exempt."""
    css = STYLE_CSS.read_text()
    assert "body.read-only .hover-actions button," in css, \
        "read-only no longer hides every header control"
    assert "body.read-only .unit-strip button," in css, \
        "read-only no longer hides every sub-unit control"
    assert ":not(.hover-read)" not in css and ":not(.unit-read)" not in css, \
        "a read-only carve-out for the deleted fold survived"


def test_the_busy_lock_covers_every_strip_button():
    """Folding was exempt from the busy lock because it changed nothing
    Claude would see. Every remaining control is feedback, so none is."""
    css = STYLE_CSS.read_text()
    assert "body.is-busy .unit-strip button { display: none; }" in css, \
        "the busy lock still exempts something from the strip"


def test_the_legend_does_not_advertise_a_private_control():
    src = SERVER_PY.read_text()
    assert ">Fold<" not in src, "the legend still lists the removed fold"
    assert "legend-private" not in src, \
        "the legend still marks a row as private to the browser"
    assert "Claude is never told" not in src, \
        "the legend still promises a control that sends nothing"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_compact.py -q
```

Expected: 6 failures — the fold is still fully present.

- [ ] **Step 3: Strip the fold out of `subunits.js`**

Delete each of the following from `skills/annotate/static/subunits.js`, including the comment block attached to each:

1. The `READ_KEY` constant and the paragraph above it explaining the separate key space (the block beginning *"Read state is a SEPARATE store from marks"*).
2. `let read = loadRead();`, `function loadRead()`, `function saveRead()`, and the `// read: { [markKey]: 1 } ...` comment above them.
3. The `READ_ICON` and `READ_TITLE` constants, and the comment block above them beginning *"The read control is deliberately NOT in CONTROL_SPECS"*.
4. `function foldable(el)` and its `// Table rows are excluded` comment.
5. `function readKeyForUnit`, `function toggleUnitRead`, `function applyReadState`, `function toggleBlockRead`, `function applyBlockRead`.

Then, inside `decorate()`:

- Delete both `applyReadState(content, el, blockId);` calls (one in the already-decorated early-return branch, one at the end of the `forEach`).
- Delete the whole `if (foldable(el)) { ... }` block that appends the `unit-read` button.
- Delete the `el.addEventListener("click", ...)` handler immediately below it — the one guarded by `if (el.dataset.read !== "1") return;` that unfolds a stub.
- Delete the `applyBlockRead(blockId);` call near `paintBlock(blockId);`.

Inside `repaintBlocks()`, delete the trailing loop and its comment:

```js
    // Folded blocks are keyed independently of marks, so they need their own
    // sweep — and this is where a rewritten block unfolds itself, since
    // applyBlockRead drops any fold whose stored version has moved on.
    for (const key of Object.keys(read)) {
      if (key.endsWith("::__block__")) applyBlockRead(key.slice(0, -"::__block__".length));
    }
```

Finally, in the `window.AnnotateSubunits = {` export block, delete the last entry and its comment so it reads:

```js
  window.AnnotateSubunits = {
    decorate, onPoll,
    // Block/step scope, driven by the card header strip in script.js.
    toggleBlockMark, pinComment, blockMark, repaintBlocks, renderDock,
    CONTROLS,
  };
```

- [ ] **Step 4: Strip the fold out of `script.js`**

In `skills/annotate/static/script.js`, delete the entire `readBtn` block inside `renderHoverActions()` — the comment beginning *"The fold control sits apart from the three round controls"* through `wrap.appendChild(readBtn);` inclusive.

- [ ] **Step 5: Strip the fold out of `style.css`**

Delete these rule groups from `skills/annotate/static/style.css`:

- `.unit-strip .unit-read { ... }`
- `.unit-strip .unit-read svg, .hover-actions .hover-read svg { ... }`
- `.hover-actions .hover-read { ... }` and `.hover-actions .hover-read:hover { ... }`
- The whole `/* === Fold (read marker) === */` banner comment.
- `.sub-unit[data-read="1"] { ... }`, `.sub-unit[data-read="1"]:hover { ... }`, `.sub-unit[data-read="1"] .unit-strip { ... }` and the comment above them.
- All four `section.block[data-read="1"] ...` rules and the comment above them.

Then replace the read-only block. Change:

```css
body.read-only .hover-actions .hover-read { opacity: 1; pointer-events: auto; }
body.read-only .hover-actions button:not(.hover-read),
body.read-only .unit-strip button:not(.unit-read),
body.read-only #round-dock,
body.read-only .unit-composer,
body.read-only .comment-card { display: none; }
/* The strip would otherwise be an empty box hovering next to every title. */
body.read-only section.block:not([data-read="1"]) .hover-actions { border: none; }
```

to:

```css
body.read-only .hover-actions button,
body.read-only .unit-strip button,
body.read-only #round-dock,
body.read-only .unit-composer,
body.read-only .comment-card { display: none; }
/* The strip would otherwise be an empty box hovering next to every title. */
body.read-only section.block .hover-actions { border: none; }
```

Update the banner comment above it — it currently promises the fold survives. Replace its last sentence so the block reads:

```css
/* === Read-only mode ==================================================
   A shared link renders the document and nothing that would be refused.
   Every control, the round dock and the comment composers go away. There is
   no longer an exception: the fold used to survive here because it never
   left the reader's browser, but compact replaced it and compact is an edit,
   which belongs to whoever owns the workspace. */
```

And change the busy lock. Replace:

```css
/* The round controls go away while a round is in flight — they'd be editing
   a document that is mid-rewrite. The fold control stays: it changes nothing
   Claude will ever see, so there is no reason to take reading aids away. */
body.is-busy .unit-strip button:not(.unit-read) { display: none; }
```

with:

```css
/* Every strip control goes away while a round is in flight — they would all
   be editing a document that is mid-rewrite. */
body.is-busy .unit-strip button { display: none; }
```

- [ ] **Step 6: Strip the fold out of the legend**

In `skills/annotate/server.py`, delete the `_ICON_FOLD` constant (the four-line eye-off SVG string, immediately above `_LEGEND_HTML`).

In `_LEGEND_HTML`, delete the fold row:

```python
    f'<tr class="legend-private"><td class="legend-btn">{_ICON_FOLD}<span>Fold</span></td>'
    '<td><em>Nothing &mdash; Claude is never told</em></td>'
    '<td>Nothing. Collapses on your screen only, private to this browser, '
    'click the stub to bring it back</td></tr>'
```

and replace the closing note:

```python
    '<p class="legend-note">The first three are feedback and are sent when you '
    'submit the round. Folding is just a reading aid &mdash; use it on the parts '
    'you have read and are happy with, so what stays on screen is what still '
    'needs you. A folded section springs back open if Claude rewrites it.</p>'
```

with:

```python
    '<p class="legend-note">All of these are feedback, and none of them does '
    'anything until you submit the round. Until then every mark is local and '
    'clicking the same button again takes it back.</p>'
```

Leave `.legend-private` in `style.css` for now — Task 3 confirms nothing uses it and removes it.

- [ ] **Step 7: Rewrite the read-only test**

The fold exemption it guards no longer exists, so the test that guards it must assert the opposite. Replace the module docstring and the first two tests in `skills/annotate/tests/test_smoke_read_only.py`, leaving `test_the_page_says_it_is_read_only` and `test_pushing_doc_separates_the_shareable_url_from_the_owner_one` untouched:

```python
"""Structural guards for how a shared, read-only link renders.

The server refuses the writes regardless — that is tested in the engine. What
these guard is the page not *offering* what will be refused. There used to be
one exception, the private fold; compact replaced it, and compact is an edit,
so a guest is now offered nothing at all.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
```

```python
def test_feedback_controls_are_hidden_for_a_guest():
    """Removed, not disabled: a greyed-out trash can invites a click and then
    explains itself with a 403."""
    css = STYLE_CSS.read_text()
    assert "body.read-only .hover-actions button," in css, \
        "block feedback controls are still offered on a read-only link"
    assert "body.read-only .unit-strip button," in css, \
        "sub-unit feedback controls are still offered on a read-only link"
    assert "body.read-only #round-dock" in css, \
        "the submit dock is still shown on a read-only link"


def test_a_guest_is_offered_no_exception():
    """The fold was the one thing a guest could still do, because it never
    reached the server. Compact is an edit and belongs to the owner, so the
    carve-outs that kept the fold alive must be gone rather than retargeted."""
    css = STYLE_CSS.read_text()
    assert ":not(.hover-read)" not in css, \
        "the header read-only rule still exempts a control"
    assert ":not(.unit-read)" not in css, \
        "the sub-unit read-only rule still exempts a control"
    assert ":not(.hover-compact)" not in css and ":not(.unit-compact)" not in css, \
        "the fold exemption was retargeted at compact instead of removed"
```

- [ ] **Step 8: Delete the fold's own test file**

```bash
git rm skills/annotate/tests/test_smoke_read_fold.py
```

Every behaviour it guarded is either gone or now guarded by `test_smoke_compact.py`, with one exception carried forward in Task 3: `test_legend_uses_the_real_glyphs` asserted that the legend's eye-off glyph matches the button's. Compact keeps that glyph, so that guarantee is re-established in Task 3 rather than lost.

- [ ] **Step 9: Run the tests**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_compact.py skills/annotate/tests/test_smoke_read_only.py -q
```

Expected: all pass.

- [ ] **Step 10: Run the full suite**

```bash
python3 -m pytest skills/ -q
```

Expected: green. Count drops by the 7 deleted fold tests and rises by the 6 new ones plus the extra read-only test.

- [ ] **Step 11: Verify the page still renders**

The smoke tests are string assertions and cannot catch a JS syntax error from the deletions. Check the file parses and no fold symbol is reachable:

```bash
node --check skills/annotate/static/subunits.js
node --check skills/annotate/static/script.js
```

Expected: no output from either (success). If `node` is unavailable, open a demo push in the browser and confirm the console is clean and three buttons appear on hovering a sentence.

- [ ] **Step 12: Commit**

```bash
git add -A skills/annotate/
git commit -m "refactor(annotate): remove the private fold

Compact replaces it. The fold's two exemptions go with it: read-only
mode kept it alive as the one thing a guest could do, and the busy lock
let it run mid-round. Compact is an owner-only edit and a round control,
so neither carve-out survives."
```

---

### Task 3: Add compact as the fourth round control

Both strips already have a loop that does exactly the right thing with a fourth entry, so this is mostly two list entries rather than two new buttons.

The card-header loop in `script.js` already routes anything that is not `comment` to `toggleBlockMark`, so adding compact to `ACTION_TYPES` wires it completely. The sub-unit loop in `subunits.js` needs one adjustment: it assigns `b.textContent = glyph`, which cannot carry the eye-off SVG. Changing it to `innerHTML` lets compact join `CONTROL_SPECS` as a peer of the other three instead of needing a special-cased append. Both glyph sets are static module constants, so there is no injection surface.

**Files:**
- Modify: `skills/annotate/static/subunits.js` (`CONTROL_SPECS`, the strip render loop, exports)
- Modify: `skills/annotate/static/script.js` (`ICON`, `ACTION_TYPES`)
- Modify: `skills/annotate/static/style.css`
- Modify: `skills/annotate/server.py` (`_ICON_COMPACT`, `_LEGEND_HTML`)
- Test: `skills/annotate/tests/test_smoke_compact.py`

**Interfaces:**
- Consumes: the wire kind `"compact"` accepted by the server (Task 1); a strip with exactly three controls and a fold-free export object (Task 2).
- Produces: a fourth button in both strips carrying `data-kind="compact"` (unit scope) and `data-type="compact"` (block scope), submitting `{scope, kind: "compact", block_id, selected_text, text: "", images: []}` through the existing `submitRound`. Task 4 defines what Claude does on receipt.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_smoke_compact.py`:

```python
EYE_OFF = '<line x1="1" y1="1" x2="23" y2="23"/>'


def test_compact_is_in_the_wire_vocabulary():
    """CONTROL_SPECS is the list of kinds that reach Claude. Compact belongs
    in it — that is precisely the difference from the fold it replaced."""
    src = SUBUNITS_JS.read_text()
    start = src.index("const CONTROL_SPECS")
    end = src.index("const CONTROLS")
    spec = src[start:end]
    for kind in ('"delete"', '"keep"', '"comment"', '"compact"'):
        assert kind in spec, f"round vocabulary is missing {kind}"


def test_the_strip_can_render_an_icon_glyph():
    """The three original controls are emoji, compact is an SVG. A strip loop
    that assigns textContent silently renders the SVG source as text."""
    src = SUBUNITS_JS.read_text()
    assert "b.textContent = glyph" not in src, \
        "the strip loop still assigns glyphs as text; the SVG will not render"
    assert "b.innerHTML = glyph" in src, "the strip loop does not render glyphs"


def test_both_scopes_offer_compact_with_the_same_glyph():
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    assert "COMPACT_ICON" in subunits, "subunits.js does not define the glyph"
    assert EYE_OFF in subunits, "the sub-unit glyph is not the eye-off icon"
    assert EYE_OFF in script, "the header glyph is not the eye-off icon"
    assert '{ id: "compact"' in script, \
        "the header strip does not carry compact in ACTION_TYPES"


def test_compact_is_gated_on_the_busy_lock():
    """It is a round control, so it must not be clickable mid-round. Guarded
    by the shared rule from Task 2 plus the loop's own guard."""
    src = SUBUNITS_JS.read_text()
    start = src.index("for (const [kind, glyph, title] of CONTROLS.unit)")
    end = src.index("el.appendChild(strip)")
    assert 'classList.contains("is-busy")' in src[start:end], \
        "the strip loop lost its busy guard"


def test_table_rows_can_be_compacted():
    """The fold excluded <tr> because a row cannot be height-clamped. Compact
    clamps nothing, so the exclusion must not have been carried over."""
    src = SUBUNITS_JS.read_text()
    assert 'tagName !== "TR"' not in src, \
        "the fold's table-row exclusion survived into compact"


def test_compact_has_its_own_pending_appearance():
    """Delete strikes through, keep tints green. Compact must not be
    mistakable for either — it is the only one that is lossy AND silent."""
    css = STYLE_CSS.read_text()
    assert '.sub-unit[data-mark="compact"]' in css, \
        "a pending unit-scope compact is invisible"
    assert 'section.block[data-block-mark="compact"]' in css, \
        "a pending block-scope compact does not light its control"


def test_the_legend_explains_compact_honestly():
    """The legend is the only place the lossiness is stated. If it claims
    nothing is lost, the control is mis-sold."""
    src = SERVER_PY.read_text()
    assert ">Compact<" in src, "the legend does not list compact"
    assert "_ICON_COMPACT" in src, "the legend draws no compact glyph"
    assert EYE_OFF in src, "the legend glyph drifted from the button's"


def test_the_dead_private_legend_style_is_gone():
    css = STYLE_CSS.read_text()
    assert ".legend-private" not in css, \
        "styling survives for a legend row that no longer exists"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_compact.py -q
```

Expected: 8 failures. The 6 tests from Task 2 still pass.

- [ ] **Step 3: Add compact to the sub-unit strip**

In `skills/annotate/static/subunits.js`, add the glyph constant immediately above `const CONTROL_SPECS`:

```js
  // Compact's glyph is the eye-off icon the private fold used to carry. The
  // gesture the user learned — "take this off my screen" — is unchanged; what
  // changed is that it now reaches Claude and slims the document instead of
  // collapsing a stub locally. Kept as SVG rather than an emoji because there
  // is no emoji that reads as "hide" without also reading as "delete".
  const COMPACT_ICON =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>' +
    '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>' +
    '<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/>' +
    '<line x1="1" y1="1" x2="23" y2="23"/></svg>';
```

Add the fourth entry to `CONTROL_SPECS`:

```js
  const CONTROL_SPECS = [
    ["delete",  "🗑", "Delete — removed for good (undo until you submit)"],
    ["keep",    "✓", "Keep — don't rewrite this"],
    ["comment", "💬", "Comment — fold a response into this"],
    ["compact", COMPACT_ICON,
     "Compact — take this off the page; its point is folded into what stays"],
  ];
```

In the strip render loop inside `decorate()`, change:

```js
        b.textContent = glyph;
```

to:

```js
        // innerHTML, not textContent: three of the four glyphs are emoji but
        // compact's is an inline SVG. Every glyph here is a module constant —
        // nothing user-supplied reaches this line.
        b.innerHTML = glyph;
```

The loop's existing `if (kind === "comment") ... else toggleMark(...)` branch already routes compact correctly, and its `is-busy` guard already applies. No other change is needed in the loop.

- [ ] **Step 4: Add compact to the card-header strip**

In `skills/annotate/static/script.js`, add an entry to the `ICON` map alongside `delete` / `keep` / `comment`:

```js
    compact: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
```

and a fourth entry to `ACTION_TYPES`:

```js
  const ACTION_TYPES = [
    { id: "delete",  title: "Delete — removed for good (undo until you submit)" },
    { id: "keep",    title: "Keep — don't rewrite this section" },
    { id: "comment", title: "Comment — fold a response into this section" },
    { id: "compact", title: "Compact — take this section off the page; its point is folded into what stays" },
  ];
```

No change to the loop below it: it already sends everything that is not `comment` to `toggleBlockMark`, and already returns early when `is-busy`.

- [ ] **Step 5: Style the control and its pending state**

In `skills/annotate/static/style.css`, add the SVG sizing rule for the sub-unit scope. The header scope is already covered by the existing `.hover-actions button svg` rule at 15px; the strip has no equivalent, so add near the other `.unit-strip` rules:

```css
/* Three of the four strip glyphs are emoji and size themselves. Compact's is
   an inline SVG and needs the stroke treatment the header buttons already
   get from `.hover-actions button svg`. */
.unit-strip button[data-kind="compact"] svg {
  width: 13px; height: 13px;
  fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round;
}
```

Add the pending unit-scope appearance beside the existing `.sub-unit[data-mark="keep"]` / `[data-mark="delete"]` / `[data-mark="comment"]` rules:

```css
/* Pending compact: dimmed and washed, but NOT struck through. Strikethrough
   is delete's, and the two must never be confused — delete drops the idea,
   compact keeps it and drops only the page space. Violet because the other
   three already own red, green and accent-blue. */
.sub-unit[data-mark="compact"] {
  background: color-mix(in srgb, #7c3aed 8%, transparent);
  opacity: .55;
}
.sub-unit[data-mark="compact"]:hover { opacity: .8; }
.sub-unit[data-mark="compact"] .unit-strip button[data-kind="compact"] {
  background: #7c3aed; border-color: #7c3aed; color: #fff;
}
```

Add compact to the block-scope lit-control group. Change:

```css
section.block[data-block-mark="keep"] .hover-actions button[data-type="keep"],
section.block[data-block-mark="delete"] .hover-actions button[data-type="delete"],
section.block[data-block-mark="comment"] .hover-actions button[data-type="comment"] {
```

to:

```css
section.block[data-block-mark="keep"] .hover-actions button[data-type="keep"],
section.block[data-block-mark="delete"] .hover-actions button[data-type="delete"],
section.block[data-block-mark="comment"] .hover-actions button[data-type="comment"],
section.block[data-block-mark="compact"] .hover-actions button[data-type="compact"] {
```

Add the block-scope pending body treatment, beside the `[data-block-mark="delete"]` rules:

```css
/* A card marked compact dims whole, the same reversible-until-submit promise
   the pending delete makes, without the strikethrough that would claim the
   content is being dropped from the plan. */
section.block[data-block-mark="compact"] .card-body { opacity: .5; }
section.block[data-block-mark="compact"] .card-title { color: var(--text-dim); }
```

Add the hover treatment beside the other three `.hover-actions button[data-type=...]:hover` rules:

```css
.hover-actions button[data-type="compact"]:hover {
  color: #7c3aed;
  border-color: #7c3aed;
  border-style: solid;
  background: color-mix(in srgb, #7c3aed 10%, transparent);
}
```

Finally delete the two now-dead legend rules:

```css
.legend-private td { color: var(--text-dim); }
.legend-private .legend-btn { color: var(--text-dim); }
```

- [ ] **Step 6: Put compact in the legend**

In `skills/annotate/server.py`, re-add the glyph constant where `_ICON_FOLD` used to sit, immediately above `_LEGEND_HTML`:

```python
_ICON_COMPACT = (
    '<svg class="legend-icon" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>'
    '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>'
    '<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/>'
    '<line x1="1" y1="1" x2="23" y2="23"/></svg>')
```

Add the fourth row to `_LEGEND_HTML`, after the Comment row and before `'</tbody></table>'`:

```python
    f'<tr><td class="legend-btn">{_ICON_COMPACT}<span>Compact</span></td>'
    '<td>&ldquo;I&rsquo;m fine with this &mdash; it just doesn&rsquo;t need '
    'the space&rdquo;</td>'
    '<td>Taken off the page. What it contributes is folded into the sentences '
    'that stay, so the plan gets shorter without losing the thread. Detail '
    'that nothing else can carry is lost &mdash; this cannot be undone once '
    'the round is submitted</td></tr>'
```

- [ ] **Step 7: Widen the existing both-scopes guard to cover compact**

`test_smoke_subunits.py::test_one_vocabulary_at_both_scopes` guards that the
header and the strip never drift to different verb sets. It passes unchanged
with four controls, but it would not notice compact appearing in one scope and
not the other — which is the exact regression it exists to catch. Widen it.

In `skills/annotate/tests/test_smoke_subunits.py`, replace that test with:

```python
def test_one_vocabulary_at_both_scopes():
    """The card header and the sub-unit strip must offer the same four
    controls. The original confusion was two overlapping strips with
    different verbs (comment/reject/dismiss vs agree/dismiss/comment), so
    a drift back to different verb sets is the regression to catch."""
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    for kind in ("delete", "keep", "comment", "compact"):
        assert f'"{kind}"' in subunits, f"subunits.js lost the {kind!r} control"
        assert f'id: "{kind}"' in script, f"script.js header strip lost {kind!r}"
```

- [ ] **Step 8: Run the tests**

```bash
python3 -m pytest skills/annotate/tests/test_smoke_compact.py skills/annotate/tests/test_smoke_subunits.py -q
```

Expected: all pass — 14 in `test_smoke_compact.py`.

- [ ] **Step 9: Verify the JS parses**

```bash
node --check skills/annotate/static/subunits.js
node --check skills/annotate/static/script.js
```

Expected: no output from either.

- [ ] **Step 10: Run the full suite**

```bash
python3 -m pytest skills/ -q
```

Expected: green.

- [ ] **Step 11: Confirm it renders**

String assertions cannot tell a rendered SVG from a black blob. Push the demo and look:

```bash
python3 skills/annotate/demo/mockup_demo.py
```

Confirm, in the browser: four buttons on hovering a sentence; the fourth is a recognisable eye-off outline and not a filled shape; clicking it dims the sentence violet without striking it through; the dock counts it; a second click takes the mark back.

- [ ] **Step 12: Commit**

```bash
git add -A skills/annotate/
git commit -m "feat(annotate): compact is the fourth round control

Both strips already had a loop that handles a fourth entry, so this is
two list entries plus the strip loop switching from textContent to
innerHTML — three of the glyphs are emoji, compact's is an SVG.

Table rows gain the control for free: the fold excluded them because a
row cannot be height-clamped, and compact clamps nothing."
```

---

### Task 4: Claude's contract — applying compact, and the sweep before the ack

No code. This is the half of the feature Claude executes, and it lives in the reference the round pipeline already loads.

The sweep's placement is the load-bearing decision and the reason it belongs in the numbered step list rather than in a section of its own advice: the page is locked behind *"Claude is updating…"* until the `.ack` is written, so the ack is the moment the user sees the answer. A sweep after the ack would be a sweep the user watches happen.

**Files:**
- Modify: `skills/annotate/references/handling-events.md`
- Test: `skills/annotate/tests/test_round_contract.py` (create)

**Interfaces:**
- Consumes: the `compact` wire kind from Tasks 1–3, arriving inside a `type: "round"` payload's `reactions` list at `scope: "unit"` or `scope: "block"`.
- Produces: nothing downstream. This is the last task.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_round_contract.py`:

```python
"""Guards on the round contract Claude executes.

Everything else in this feature is a control that queues an intent. This file
guards the half that acts on it. Two failure modes are worth a test each: the
contract describing compact as if it were delete, and the sweep drifting to
after the ack — which is when the user sees the page, so a sweep after it is
a sweep the user watches happen.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "skills" / "annotate" / "references" / "handling-events.md"


def test_compact_is_in_the_kind_table():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "`compact`" in doc, "the contract does not mention compact"


def test_compact_is_distinguished_from_delete():
    """The single most important line in the contract. If compact reads as a
    synonym for delete, Claude stops acting on content the user only wanted
    off the page."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still binds" in doc, \
        "the contract does not say a compacted idea still binds the plan"
    assert "out of scope" in doc, \
        "the contract lost the phrase that makes delete's meaning explicit"


def test_keep_beats_compact():
    """A user can protect one sentence and compact its neighbour in the same
    round. The absorb wants to rewrite the protected one."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "keep` beats compact" in doc or "keep beats compact" in doc, \
        "the contract does not resolve keep against a neighbouring compact"


def test_nothing_is_stored_off_page():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "no hidden store" in doc.lower() or "not retained" in doc.lower(), \
        "the contract does not forbid retaining compacted content"


def test_the_sweep_runs_before_the_ack():
    """Order is the whole point: the ack unlocks the page."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "sweep" in doc.lower(), "the contract has no coherence sweep"
    sweep = doc.lower().index("coherence sweep")
    section = doc[sweep:sweep + 2500].lower()
    assert "before" in section and "ack" in section, \
        "the sweep does not state its position relative to the ack"


def test_the_sweep_is_bounded():
    """An unbounded 'make it all coherent' pass churns the whole document
    every round and inflates versions on blocks the user never touched."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still reads true" in doc, \
        "the contract does not forbid rewriting blocks that are still true"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python3 -m pytest skills/annotate/tests/test_round_contract.py -q
```

Expected: 6 failures.

- [ ] **Step 3: Add compact to the model table**

In `skills/annotate/references/handling-events.md`, in the "The model in one paragraph" section, change the table to:

```markdown
| `kind` | Survives? | What you do |
|--------|-----------|-------------|
| `delete` | **No** | Remove it, re-thread what's left, never reintroduce it |
| `keep` | Yes, untouched | Nothing — explicitly do not rewrite this |
| `comment` | Yes, rewritten | Fold a response into the prose |
| `compact` | **Not on the page** | Remove it, but fold what it contributes into the prose that stays |
```

and add this paragraph immediately below the table:

```markdown
`delete` and `compact` both remove words; they differ in what happens to the
idea. A `delete` puts the idea **out of scope** — you stop acting on it. A
`compact` says only that the idea does not deserve page space: it **still
binds** the plan, and you keep acting on it. Delete the sentence about health
checks and you build no health check. Compact it and you still build one; the
plan just stops spending six lines saying so.
```

- [ ] **Step 4: Add the compact application rules**

In the `WEBCOMPANION_EVENT` with `type: "round"` section, extend the block-scope list (step 2) with a compact entry after `keep`:

```markdown
   - **`compact`** — the whole block leaves the page. Fold what it contributes
     into a neighbouring block, then `blocks.remove_block(doc, block_id)` and
     re-thread the survivors exactly as for a delete. The difference is what
     you carry forward: the block's content still binds the plan, so keep
     acting on it. Unit reactions on that block are absorbed rather than
     dropped — answer a `comment` inside it first, and let the answer be what
     travels into the neighbour.
```

and extend the unit-scope list (step 3) with:

```markdown
   - **`compact`** — cut that sub-unit from the block's markdown, and fold
     what it contributes into the nearest surviving sub-unit that already
     covers that ground. The page gets shorter and denser. Do not leave a
     stub, a trailer, or a "compacted" note behind — there must be no residue.
     If no surviving sub-unit can carry it, the detail is dropped; that is
     expected, not an error.
```

Then add this block immediately after step 3's list:

```markdown
Three rules govern compact, and all three matter:

- **`keep` beats compact.** If the only surviving sub-unit that could carry
  the absorbed material is marked `keep`, do not rewrite it — `keep` is an
  explicit "do not rewrite this" and that is the whole reason it exists.
  Carry the material somewhere else, or drop it. A user must be able to
  protect one sentence and compact its neighbour in the same round without
  the protection quietly failing.
- **There is no hidden store.** Compacted text is not retained — not in
  `blocks.json`, not in a side file, not carried in your head past this turn.
  Whatever survived the absorb is the document, and it is the whole of what
  you act on. If you find yourself about to use a detail that is no longer on
  the page, you have lost it: ask, or pick a sensible default and say so.
- **Compact is lossy, and that is accepted.** Do not compensate by writing
  longer surviving sentences than the material warrants, and do not refuse to
  compact because detail would be lost.
```

- [ ] **Step 5: Add the sweep to the numbered pipeline**

Still in the `type: "round"` section, replace the final steps 4 and 5:

```markdown
4. Persist each changed block via `blocks.update_block(doc, block_id,
   new_markdown)` (content-hash-safe), then `blocks.drop_unused_terms(doc)`,
   then ONE `blocks.save_atomic`.
5. Write ONE `<consumed_dir>/<event_id>.ack`. End your turn. No terminal
   output; the watcher stays armed.
```

with:

```markdown
4. Persist each changed block via `blocks.update_block(doc, block_id,
   new_markdown)` (content-hash-safe), then `blocks.drop_unused_terms(doc)`.
5. **Run the coherence sweep** — see the section below. This is not optional
   and it is not conditional on the round having deleted anything.
6. ONE `blocks.save_atomic`.
7. Write ONE `<consumed_dir>/<event_id>.ack`. End your turn. No terminal
   output; the watcher stays armed.
```

- [ ] **Step 6: Write the sweep section**

Add this as a new top-level section immediately after the `type: "round"` section and before `### WEBCOMPANION_FINISHED`:

```markdown
## The coherence sweep

After applying a round and **before writing the `.ack`**, re-read every block
and check it against the document you just produced.

The order is the point. The page is locked behind "Claude is updating…" until
the ack lands — `/poll` reports `busy: true` until then — so the ack is the
moment the user sees your answer. Sweeping after it would be sweeping in front
of them. It costs no extra tool calls: `blocks.json` is already in hand from
applying the round.

Steering block 4 while block 6 still describes what block 4 used to say is the
single most common way this document goes wrong, and nothing else catches it.
The block-rewrite contract's "touch only the blocks you actually need to
change" is a rule about *gratuitous* rewrites; it was never a licence to leave
a block saying something false.

**Fix exactly two things:**

1. **References that no longer resolve** — a pointer to a removed block, a
   step number that shifted, a count or total that stopped adding up, a
   glossary term whose referent is gone.
2. **Claims the round made false** — including claims that never name the
   block you changed. This is the case the smart-drop step cannot catch,
   because it looks for references rather than for meaning.

**Change nothing else.** Not wording, not tone, not ordering, not transitions,
not anything that **still reads true**. "Wordy but accurate" is left alone. A
block is rewritten only if leaving it would make the document lie.

Persist sweep fixes with `blocks.update_block`, which is content-hash-safe, so
a block that needed nothing costs no version bump. If a sweep fix itself makes
another block false, resolve that too in the same pass — the document settles
before the ack, not across turns.

This generalises the smart-drop step that block-scope `delete` and `compact`
already call for. Doing it there and again here is not wasted work: smart-drop
is scoped to what a removal broke, the sweep is scoped to the whole document.
```

- [ ] **Step 7: Run the tests**

```bash
python3 -m pytest skills/annotate/tests/test_round_contract.py -q
```

Expected: all 6 pass.

- [ ] **Step 8: Run the full suite**

```bash
python3 -m pytest skills/ -q
```

Expected: green.

- [ ] **Step 9: Check the docs audit still holds**

The repo has an audit skill that checks prose against the tree. The contract just changed substantially, so run it:

```
/audit-docs-truth
```

Expected: no findings against `handling-events.md`. Fix anything it reports before committing.

- [ ] **Step 10: Commit**

```bash
git add skills/annotate/references/handling-events.md skills/annotate/tests/test_round_contract.py
git commit -m "feat(annotate): compact application rules and the pre-ack sweep

The sweep re-reads every block after a round and before the ack, which
is the moment the page unlocks. It fixes references that stopped
resolving and claims the round made false, and touches nothing that
still reads true.

Compact's contract turns on one distinction: delete puts an idea out of
scope, compact only withdraws its page space. The idea still binds."
```

---

## Verification

After all four tasks:

- [ ] `python3 -m pytest skills/ -q` is green.
- [ ] `node --check` passes on both `subunits.js` and `script.js`.
- [ ] A demo push shows four controls at both scopes, the compact glyph renders as an outline, and a pending compact is violet and not struck through.
- [ ] A read-only URL for the same workspace shows **no** controls at all.
- [ ] `git log --oneline main..HEAD` shows five commits: the spec plus one per task.

## Notes on what this plan deliberately does not do

- No off-page store, no undo after submit, no guest compact queue, no on-page compact residue. All four were considered during design and cut; see the spec's "Explicitly out of scope".
- No user-visible report of what the sweep changed. Version bumps already show which blocks moved.
- No new JS test runner. The repo's frontend guards are source-string assertions, and Step 10 of Task 3 plus the Verification list cover what strings cannot.
