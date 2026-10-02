# Choice Block v2 (Selectable Cards + Note) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the annotate choice block so options render as selectable cards with an optional free-text note, note-only submission means "none of these — here's my direction", and a `recommended` spec flag renders as a badge.

**Architecture:** The submit payload shape is unchanged (`type: "choice"`, `selected_options`, `text`) — the client stops hardcoding `text: ""` and may now send an empty `selected_options` when a note is present. Validation lives in `blocks.validate_choice_selection`, which gains a `has_text` keyword; the HTTP layer in `server.py` passes it through. The UI rework is confined to `renderChoice` in `script.js` plus the `.choice-*` CSS.

**Tech Stack:** Python 3 stdlib (http.server-based companion server), vanilla JS + CSS (no frameworks, no build step), pytest for tests.

**Spec:** `docs/superpowers/specs/2026-08-11-choice-block-v2-design.md`

## Global Constraints

- No new dependencies anywhere (Python is stdlib-only; JS is vanilla, inline in `static/`).
- Wire payload shape is unchanged: `type: "choice"`, `selected_options` (list, may be empty), `text` (string). No new payload fields.
- Old browser tabs sending a pick with `text: ""` must remain valid (no compatibility break).
- Note placeholder copy, verbatim: `Add a note (optional) — or answer in your own words`
- All tests run from the repo root: `python3 -m pytest skills/annotate/tests/ -q`
- Commit style: `feat(annotate): …` / `fix(annotate): …` / `docs(annotate): …`, body ends with the Co-Authored-By + Claude-Session trailer used by recent commits.

---

### Task 1: `validate_choice_selection` learns note-only submissions

**Files:**
- Modify: `skills/annotate/blocks.py:152-167` (`validate_choice_selection`)
- Test: `skills/annotate/tests/test_blocks.py` (choice section, after line ~341)

**Interfaces:**
- Consumes: existing `choice_option_ids(spec)` (unchanged).
- Produces: `validate_choice_selection(spec: dict, selected: Any, *, has_text: bool = False) -> str | None`. Empty `selected` list is valid iff `has_text` is True. All other rules unchanged. Default `False` preserves every existing caller's behaviour.

- [ ] **Step 1: Write the failing tests**

Append to the choice-validation test group in `skills/annotate/tests/test_blocks.py` (near the existing `test_validate_choice_empty_selection_rejected` around line 317; `_choice_spec` helper already exists at line 292):

```python
def test_validate_choice_empty_selection_with_note_is_valid():
    assert validate_choice_selection(_choice_spec(), [], has_text=True) is None


def test_validate_choice_empty_selection_without_note_still_invalid():
    err = validate_choice_selection(_choice_spec(), [], has_text=False)
    assert err is not None


def test_validate_choice_note_does_not_excuse_unknown_ids():
    err = validate_choice_selection(_choice_spec(), ["o9"], has_text=True)
    assert "o9" in err


def test_validate_choice_note_does_not_excuse_two_picks_on_single_select():
    err = validate_choice_selection(_choice_spec(multi=False), ["o1", "o2"], has_text=True)
    assert err is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/annotate/tests/test_blocks.py -q -k "note"`
Expected: FAIL — `TypeError: validate_choice_selection() got an unexpected keyword argument 'has_text'`

- [ ] **Step 3: Implement**

In `skills/annotate/blocks.py`, replace the function (lines 152–167) with:

```python
def validate_choice_selection(
    spec: dict[str, Any], selected: Any, *, has_text: bool = False
) -> str | None:
    """Validate a submitted selection against a choice spec.

    Returns None when valid, else a short human-readable error string.
    An empty selection is valid only when the submission carries a note
    (has_text) — that is the "none of these, here's my direction" case.
    """
    if not isinstance(selected, list) or not all(isinstance(s, str) for s in selected):
        return "selected_options must be a list of strings"
    if not selected:
        return None if has_text else "selected_options must not be empty"
    valid = set(choice_option_ids(spec))
    unknown = [s for s in selected if s not in valid]
    if unknown:
        return f"unknown option id(s): {', '.join(unknown)}"
    if not spec.get("multiSelect") and len(selected) != 1:
        return "single-select choice requires exactly one option"
    return None
```

- [ ] **Step 4: Run the whole blocks suite**

Run: `python3 -m pytest skills/annotate/tests/test_blocks.py -q`
Expected: PASS (new tests plus the existing empty-selection tests at lines 317 and 341, which use the default `has_text=False`).

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/blocks.py skills/annotate/tests/test_blocks.py
git commit -m "feat(annotate): choice validation accepts note-only submissions"
```

---

### Task 2: Server passes the note through to validation

**Files:**
- Modify: `skills/annotate/server.py:508` (the `validate_choice_selection` call inside the `/api/submit` handler)
- Test: `skills/annotate/tests/test_server.py` (choice section, after `test_submit_choice_empty_selection_returns_422` at line 827)

**Interfaces:**
- Consumes: `validate_choice_selection(spec, selected, *, has_text)` from Task 1. The handler's local `text` variable (line 463, already validated as `str` at line 476).
- Produces: HTTP contract — POST `/s/<sid>/api/submit` with `type: "choice"`, `selected_options: []`, non-empty `text` → 202, event records both; empty/whitespace `text` with empty selection → 422. The stored event already includes `text` (line 544) and `selected_options` (line 549) — no storage change.

- [ ] **Step 1: Write the failing tests**

Append after `test_submit_choice_empty_selection_returns_422` (line 833) in `skills/annotate/tests/test_server.py`, same class, using the existing `_choice_blocks` / `_post_json` / `_write_blocks` helpers:

```python
    def test_submit_choice_note_only_succeeds(self):
        response_dir = Path(self.sess["response_dir"])
        _write_blocks(response_dir, "resp-chn", "T", self._choice_blocks())
        status, _ = self._post_json(self.base + "/api/submit", {
            "block_id": "b-0", "type": "choice", "selected_options": [],
            "text": "none of these — try nautical names",
        })
        self.assertEqual(status, 202)
        events_dir = Path(self.sess["events_dir"])
        evt = json.loads(list(events_dir.glob("*.json"))[0].read_text())
        self.assertEqual(evt["type"], "choice")
        self.assertEqual(evt["selected_options"], [])
        self.assertEqual(evt["text"], "none of these — try nautical names")

    def test_submit_choice_pick_with_note_records_both(self):
        response_dir = Path(self.sess["response_dir"])
        _write_blocks(response_dir, "resp-chpn", "T", self._choice_blocks())
        status, _ = self._post_json(self.base + "/api/submit", {
            "block_id": "b-0", "type": "choice", "selected_options": ["o1"],
            "text": "but lowercase it",
        })
        self.assertEqual(status, 202)
        events_dir = Path(self.sess["events_dir"])
        evt = json.loads(list(events_dir.glob("*.json"))[0].read_text())
        self.assertEqual(evt["selected_options"], ["o1"])
        self.assertEqual(evt["text"], "but lowercase it")

    def test_submit_choice_whitespace_note_only_returns_422(self):
        response_dir = Path(self.sess["response_dir"])
        _write_blocks(response_dir, "resp-chw", "T", self._choice_blocks())
        status, _ = self._post_json(self.base + "/api/submit", {
            "block_id": "b-0", "type": "choice", "selected_options": [],
            "text": "   ",
        })
        self.assertEqual(status, 422)
```

- [ ] **Step 2: Run tests to verify the right ones fail**

Run: `python3 -m pytest skills/annotate/tests/test_server.py -q -k "note or whitespace_note"`
Expected: `test_submit_choice_note_only_succeeds` FAILS (422 != 202). `test_submit_choice_whitespace_note_only_returns_422` may already pass (empty selection is rejected today) — that's fine; it pins the behaviour so Task 2's change doesn't over-accept.

- [ ] **Step 3: Implement**

In `skills/annotate/server.py` line 508, change the call:

```python
            err = blocks_model.validate_choice_selection(
                blk.get("spec") or {}, selected_options,
                has_text=bool(text.strip()))
```

Nothing else changes — `text` is already stored in the event dict (line 544) and `selected_options` is already copied in (line 549), which now may be `[]`.

- [ ] **Step 4: Run the server suite**

Run: `python3 -m pytest skills/annotate/tests/test_server.py -q`
Expected: PASS, including the pre-existing `test_submit_choice_empty_selection_returns_422` (its payload has no `text` key, so `text` defaults to `""` → still 422).

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/server.py skills/annotate/tests/test_server.py
git commit -m "feat(annotate): /api/submit accepts note-only choice answers"
```

---

### Task 3: End-to-end coverage of the note flows

**Files:**
- Modify: `skills/annotate/tests/test_smoke_e2e_choice.py`

**Interfaces:**
- Consumes: the Task 2 HTTP contract; existing helpers `_create_session`, `_http_get`, `_start_server`, `_write_blocks` (imported at the top of the file already); `blocks_model.update_spec_block` for the re-propose simulation.
- Produces: nothing downstream — this is the regression net for the full loop.

- [ ] **Step 1: Write the failing test**

Append to `ChoiceSmokeTests` in `skills/annotate/tests/test_smoke_e2e_choice.py`:

```python
    def test_e2e_note_only_then_repropose(self):
        response_dir = Path(self.sess["response_dir"])
        spec = {
            "question": "New name for the bot?",
            "multiSelect": False,
            "options": [
                {"id": "o1", "label": "Koumbaras", "recommended": True},
                {"id": "o2", "label": "Ovolos"},
            ],
        }
        _write_blocks(response_dir, "resp-note", "note-smoke", [
            {"id": "b-0", "kind": "choice", "spec": spec, "version": 1},
        ])

        # 1. Note-only submit: no pick, a direction instead → 202.
        status, _ = self._post_json(self.base + "/api/submit", {
            "block_id": "b-0", "type": "choice", "selected_options": [],
            "text": "none of these — try nautical names",
        })
        self.assertEqual(status, 202)
        events_dir = Path(self.sess["events_dir"])
        evt = json.loads(list(events_dir.glob("*.json"))[0].read_text())
        self.assertEqual(evt["selected_options"], [])
        self.assertEqual(evt["text"], "none of these — try nautical names")

        # 2. Simulate Claude re-proposing (spec update, NOT resolution).
        blocks_path = response_dir / "blocks.json"
        doc = blocks_model.load(blocks_path)
        new_spec = {
            "question": "New name for the bot?",
            "multiSelect": False,
            "options": [
                {"id": "o1", "label": "Trata"},
                {"id": "o2", "label": "Kaiki"},
            ],
        }
        self.assertTrue(blocks_model.update_spec_block(doc, "b-0", new_spec))
        blocks_model.save_atomic(blocks_path, doc)

        # 3. /raw still shows a choice block, new options, bumped version.
        status, body = _http_get("localhost", self.info["port"], self.base + "/raw")
        self.assertEqual(status, 200)
        blk = next(b for b in json.loads(body)["blocks"] if b["id"] == "b-0")
        self.assertEqual(blk["kind"], "choice")
        self.assertEqual(blk["spec"], new_spec)
        self.assertEqual(blk["version"], 2)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_e2e_choice.py -q`
Expected: the new test FAILS at step 1 (202 expected) only if Tasks 1–2 are not yet merged; with Tasks 1–2 done it should PASS immediately. If it passes on first run, temporarily assert `status == 999` to watch it fail, then restore — never trust a test you haven't seen fail.

- [ ] **Step 3: Run the full annotate suite**

Run: `python3 -m pytest skills/annotate/tests/ -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/annotate/tests/test_smoke_e2e_choice.py
git commit -m "test(annotate): e2e note-only choice answer and re-propose loop"
```

---

### Task 4: Card UI, note field, recommended badge (client)

**Files:**
- Modify: `skills/annotate/static/script.js:393-469` (`renderChoice`)
- Modify: `skills/annotate/static/style.css:672-730` (the `.choice-*` section) and `style.css:958` (the `body.is-busy` rule)

**Interfaces:**
- Consumes: `WebCompanion.api.submit(payload)`, `pendingEvents`, `startUpdatingOverlay(section)` — all already used by the current `renderChoice`. Spec fields: `question`, `multiSelect`, `options[].{id,label,description,recommended}`.
- Produces: the DOM/CSS contract only. Payload sent: `{block_id, step_id: null, type: "choice", selected_options: [...], text: "<trimmed note>", selected_text: "", images: []}` where `selected_options` may be `[]` when the note is non-empty.

- [ ] **Step 1: Replace `renderChoice`**

Replace the whole function body (script.js lines 393–469) with:

```js
  // Render a choice block's interactive body: selectable option cards, an
  // optional note field, and Submit. A card click toggles selection (single-
  // select moves it); Submit enables on a pick OR a non-empty note. Note-only
  // means "none of these — here's my direction". On submit, POST and show the
  // same "updating" overlay the comment path uses.
  function renderChoice(section, content, blk) {
    const spec = blk.spec || {};
    const multi = !!spec.multiSelect;
    const options = Array.isArray(spec.options) ? spec.options : [];

    const wrap = document.createElement("div");
    wrap.className = "choice-block";

    // The question is shown in the card header (derived from spec.question by
    // blockTitle) — don't repeat it in the body.

    const list = document.createElement("div");
    list.className = "choice-options";
    list.setAttribute("role", multi ? "group" : "radiogroup");
    const cards = [];
    const selected = new Set();

    const setChecked = (card, on) => {
      card.classList.toggle("selected", on);
      card.setAttribute("aria-checked", String(on));
    };
    const toggleAt = (idx) => {
      const opt = options[idx];
      if (selected.has(opt.id)) {
        selected.delete(opt.id);
        setChecked(cards[idx], false);
      } else {
        if (!multi) {
          selected.clear();
          cards.forEach(c => setChecked(c, false));
        }
        selected.add(opt.id);
        setChecked(cards[idx], true);
      }
      refreshSubmit();
    };

    options.forEach((opt, idx) => {
      const card = document.createElement("div");
      card.className = "choice-option";
      card.tabIndex = 0;
      card.setAttribute("role", multi ? "checkbox" : "radio");
      card.setAttribute("aria-checked", "false");
      const textWrap = document.createElement("span");
      textWrap.className = "choice-option-text";
      const head = document.createElement("span");
      head.className = "choice-option-head";
      const label = document.createElement("span");
      label.className = "choice-option-label";
      label.textContent = opt.label || opt.id;
      head.appendChild(label);
      if (opt.recommended) {
        const badge = document.createElement("span");
        badge.className = "choice-badge";
        badge.textContent = "recommended";
        head.appendChild(badge);
      }
      textWrap.appendChild(head);
      if (opt.description) {
        const desc = document.createElement("span");
        desc.className = "choice-option-desc";
        desc.textContent = opt.description;
        textWrap.appendChild(desc);
      }
      card.appendChild(textWrap);
      card.addEventListener("click", () => toggleAt(idx));
      card.addEventListener("keydown", (e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          toggleAt(idx);
        } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          cards[(idx + 1) % cards.length].focus();
        } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          cards[(idx - 1 + cards.length) % cards.length].focus();
        }
      });
      cards.push(card);
      list.appendChild(card);
    });
    wrap.appendChild(list);

    // Digit shortcuts 1..9 toggle the corresponding option while focus is
    // anywhere in the block except the note field (typing digits there is
    // just typing).
    wrap.addEventListener("keydown", (e) => {
      if (e.target === note) return;
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= options.length) {
        e.preventDefault();
        toggleAt(n - 1);
      }
    });

    const footer = document.createElement("div");
    footer.className = "choice-footer";
    const note = document.createElement("textarea");
    note.className = "choice-note";
    note.rows = 1;
    note.placeholder = "Add a note (optional) — or answer in your own words";
    note.addEventListener("input", () => {
      note.style.height = "auto";
      note.style.height = note.scrollHeight + "px";
      refreshSubmit();
    });
    note.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!submitBtn.disabled) doSubmit();
      }
    });

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "choice-submit-btn";
    submitBtn.textContent = "Submit";
    submitBtn.disabled = true;
    function refreshSubmit() {
      submitBtn.disabled = selected.size === 0 && !note.value.trim();
    }

    function doSubmit() {
      const picked = options.filter(o => selected.has(o.id)).map(o => o.id);
      const text = note.value.trim();
      if (!picked.length && !text) return;
      submitBtn.disabled = true;
      const payload = {
        block_id: blk.id,
        step_id: null,
        type: "choice",
        selected_options: picked,
        text,
        selected_text: "",
        images: [],
      };
      WebCompanion.api.submit(payload).then((res) => {
        const eventId = res && res.event_id;
        if (eventId) pendingEvents.set(String(eventId), { blockId: blk.id });
        startUpdatingOverlay(section);
      }).catch(() => {
        refreshSubmit();
      });
    }
    submitBtn.addEventListener("click", doSubmit);

    footer.append(note, submitBtn);
    wrap.appendChild(footer);
    content.appendChild(wrap);
  }
```

- [ ] **Step 2: Rework the `.choice-*` CSS**

In `style.css`, replace lines 672–730 (from the `/* ── Choice blocks ─...` banner through `.choice-submit-btn:disabled { … }`) with:

```css
/* ── Choice blocks ──────────────────────────────────────────────────────── */
.choice-block {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.choice-options {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.choice-option {
  display: flex;
  align-items: flex-start;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
  user-select: none;
  transition: border-color 0.12s ease, background 0.12s ease, box-shadow 0.12s ease;
}
.choice-option:hover {
  border-color: var(--accent);
  background: var(--surface-soft);
}
.choice-option:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.choice-option.selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface));
  box-shadow: inset 0 0 0 1px var(--accent);
}
.choice-option-text {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.choice-option-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.choice-option-label {
  color: var(--text-strong);
  font-weight: 500;
}
.choice-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  border-radius: 999px;
  padding: 1px 8px;
}
.choice-option-desc {
  color: var(--text-dim);
  font-size: 0.85em;
}
.choice-footer {
  display: flex;
  align-items: flex-end;
  gap: 0.6rem;
}
.choice-note {
  flex: 1;
  resize: none;
  overflow: hidden;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  line-height: 1.4;
}
.choice-note:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.15);
}
.choice-note::placeholder { color: var(--text-dim); }
.choice-submit-btn {
  flex: none;
  padding: 0.45rem 1rem;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.choice-submit-btn:disabled {
  opacity: 0.45;
  cursor: default;
}
```

Then extend the busy gate at line 958 so the note field freezes with the submit buttons:

```css
body.is-busy .choice-submit-btn,
body.is-busy .choice-note,
body.is-busy .card-submit-btn,
body.is-editing .hover-actions {
  pointer-events: none;
  opacity: 0.4;
}
```

- [ ] **Step 3: Confirm the server suite still passes (contract untouched)**

Run: `python3 -m pytest skills/annotate/tests/ -q`
Expected: PASS — this task changes only static assets.

- [ ] **Step 4: Visual + behavioural check in a real browser**

Write `/tmp/claude-scratch/6572e242-e5bb-4dea-8daf-d55a285aed48/scratchpad/choice_demo.py` (run from the repo root):

```python
"""Boot a throwaway annotate session showing one choice block; prints the URL."""
import tempfile
from pathlib import Path

from skills.annotate.tests.test_server import (
    _create_session, _start_server, _write_blocks,
)

home = Path(tempfile.mkdtemp(prefix="choice-demo-home-"))
project = Path(tempfile.mkdtemp(prefix="choice-demo-proj-"))
proc, info = _start_server(home)
sess = _create_session(info["port"], project)
_write_blocks(Path(sess["response_dir"]), "resp-demo", "Choice v2 demo", [
    {"id": "b-0", "kind": "choice", "spec": {
        "question": "New name for the expense bot (replacing “Tameio”)?",
        "multiSelect": False,
        "options": [
            {"id": "o1", "label": "Koumbaras",
             "description": "Κουμπαράς — piggy bank. Closest fit to what the bot does.",
             "recommended": True},
            {"id": "o2", "label": "Ovolos",
             "description": "Οβολός — the obol, the small ancient Greek coin."},
            {"id": "o3", "label": "Apodeixi",
             "description": "Απόδειξη — receipt. Literal."},
        ]}, "version": 1},
])
print(f"http://localhost:{info['port']}/s/{sess['sid']}/", flush=True)
proc.wait()
```

Run it in the background (`python3 <scratchpad>/choice_demo.py`), then with the Playwright MCP tools: navigate to the printed URL and verify, via snapshot/screenshot —

1. Options render as cards with no radio circles; "Koumbaras" shows a `recommended` badge (not prose).
2. Clicking a card highlights it; clicking another card moves the highlight (single-select); clicking the highlighted card clears it.
3. Submit is disabled with no pick and no note; typing a note alone enables it; clearing the note disables it again.
4. Pressing `2` toggles the second card; arrow keys move focus between cards.
5. Submit with a pick + note fires the updating overlay (the POST returns 202 — check the network tab or server log).
6. Take a screenshot for the record; kill the demo server process.

Expected: all six observed as described. Fix and re-check anything that isn't.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/static/script.js skills/annotate/static/style.css
git commit -m "feat(annotate): choice blocks become selectable cards with an optional note"
```

---

### Task 5: Docs — authoring contract and event handling

**Files:**
- Modify: `skills/annotate/references/block-kinds/choice.md`
- Modify: `skills/annotate/references/handling-events.md` (lines 69 and 82–92)

**Interfaces:**
- Consumes: the contracts fixed in Tasks 1–4 (nothing new is invented here — docs mirror code).
- Produces: the authoring + event-handling contract future Claude sessions follow.

- [ ] **Step 1: Update `choice.md`**

In the **Block shape** section, replace the example spec and the paragraph under it with:

```markdown
    {"id": "section-N", "kind": "choice", "spec": {
      "question": "<the decision, one line>",
      "multiSelect": false,
      "options": [
        {"id": "o1", "label": "<terse choice>", "description": "<optional sub-text>", "recommended": true},
        {"id": "o2", "label": "...", "description": "..."}
      ]
    }}

Block id is `section-N` (assigned by `next_block_id`). Option ids are `o1`, `o2`, … minted by hand, stable across rewrites. `multiSelect: false` allows exactly one pick; `true` allows several. `description` is optional. Use 2–4 options. Mark at most ONE option `"recommended": true` — it renders as a badge on the card; never write "(recommended)" inside `description` prose.

A choice block carries no `markdown`, and the question is shown in the card header — don't repeat it in the spec elsewhere. The user picks in the browser and may attach a free-text note; a **note-only** submission (no pick, non-empty note) means "none of these — here's my direction". You resolve or re-propose on the watcher event.
```

Also update the "When a choice block is the right block" bullet `A closed answer space — picking beats free-text.` to:

```markdown
- A mostly closed answer space — picking beats free-text. (The rendered block still lets the user add a note or answer in their own words, so near-misses are fine.)
```

- [ ] **Step 2: Update `handling-events.md`**

Line 69, the `selected_options` bullet, becomes:

```markdown
   - `selected_options` — for `type: "choice"`: the option id(s) the user picked (a list, possibly EMPTY when the user answered with a note instead). Absent otherwise.
```

Replace the `### WEBCOMPANION_EVENT with type: "choice"` subsection body (lines 84–92) with:

```markdown
The user answered a choice block. `selected_options` holds the picked id(s) — map them to labels via the block's `spec.options` — and `text` may carry a free-text note riding along with the pick.

**Pick (with or without a note):**

1. Read `<response_dir>/blocks.json`, find the block by `block_id`.
2. **Resolve the choice into a decision** — convert the block from `kind: "choice"` to a markdown block whose prose states the decision, folds in the reasoning, AND folds in the note when present (e.g. *"Decision: Koumbaras, lowercased per your note…"*). The options disappear; the answer is final. Use `blocks.convert_block_to_markdown(doc, block_id, markdown)` — it sets the markdown, drops `kind`/`spec`, and is content-hash-safe (a no-op rewrite doesn't bump the version).
3. **Continue the task** — the pick drives the next step. Append follow-up blocks to `blocks.json` and/or take the implied action, as the decision warrants.
4. Run the coherence sweep (see below — this path is the universal rule's highest-risk case, since it both resolves the block and appends new ones).
5. `save_atomic` the doc, write the `<consumed_dir>/<event_id>.ack`, end your turn. No terminal output; the watcher stays armed.

**Note-only (`selected_options` is `[]`, `text` non-empty):** the user rejected the slate and gave a direction instead. Do NOT resolve. Either rewrite the block's spec with re-proposed options that follow the direction (`blocks.update_spec_block` — the version bumps), or, when the note itself settles the question, resolve to a decision paragraph built from the note. Then continue as in steps 3–5 above.

Multi-select: the decision prose names all picked options. There is no `reject` on a choice — an empty pick always carries a note.
```

- [ ] **Step 3: Sanity-check the docs render and cross-references**

Run: `grep -n "recommended" skills/annotate/references/block-kinds/choice.md skills/annotate/references/handling-events.md` and re-read both changed sections top-to-bottom for contradictions with the code (payload field names, function names).
Expected: `recommended` documented once in choice.md; no stale "picking beats free-text" absolutism; function names `convert_block_to_markdown` / `update_spec_block` match `blocks.py`.

- [ ] **Step 4: Full suite one last time**

Run: `python3 -m pytest skills/annotate/tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/references/block-kinds/choice.md skills/annotate/references/handling-events.md
git commit -m "docs(annotate): choice v2 contract — note, note-only re-propose, recommended badge"
```
