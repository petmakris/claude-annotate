# Shared visuals with frames: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Annotate's sequence and flowchart generators become shared tools that the stage draws and steps through in time with talk's voice, while annotate's output stays byte-identical.

**Architecture:** The generators move to `skills/_shared/visuals/` and gain opt-in `data-key` attributes and a `stage` font profile. The stage registers `skills/` as its asset root, renders a new `visual` inline format, and steps every board through one `data-key` frame engine. `scene.py` gains models for both specs and the arrow rule.

**Tech Stack:** Python 3.9+, pytest, Playwright, fontTools (offline metrics generation only), ELK through Node, the webcompanion daemon.

**Spec:** `docs/superpowers/specs/2026-10-06-shared-visuals-with-frames-design.md`

## Global Constraints

- Annotate's rendered output for the captured golden specs is byte-identical after every task.
- Every Python file compiles under 3.9. Talk's suite skips below 3.11.
- No new comments beyond one module docstring per new module; an existing comment made false is fixed in place.
- Browser tests run at most 4 workers on this Mac (`-n 4`).
- Commit messages are one line, with no attribution. Ask before pushing claude-annotate.
- Decided while building, and folded into the spec: `write_text_atomic` stays in annotate; `visuals.css` and the Geist fonts follow the existing `_shared/static/` canonical-plus-checked-copies pattern; the stage keeps its own asset root.

## Review Focus

1. A spec with a step whose id contains a character that is not a CSS identifier (`s-1.a`): keys must still match, so the engine looks keys up by attribute value, never by building a selector from the id.
2. A flowchart whose ELK run fails (no Node): the Python fallback layout still carries the keys.
3. A sequence spec of nothing but bands: `render_key` returns "" and the stage shows the grid alone, with no empty key column.
4. A stage page opened before this change, reloaded after it: the asset root moves, so a stale session must re-register its assets on the next `show`.
5. Dark mode: every token `visuals.css` reads is mapped in `stage.css` for both themes.

---

### Task 1: Capture annotate's golden output

- [ ] Write `skills/_shared/visuals/tests/golden_capture.py`, a pytest plugin that wraps `sequence.render`, `sequence.render_key`, `flowchart.render` and `flowchart.render_variants` while annotate's suite runs, and records every `(function, spec, block_id) -> output` to a JSON file.
- [ ] Run annotate's suite with it and commit the deduplicated result as `skills/_shared/visuals/tests/golden.json`.
- [ ] Write `test_golden.py`: replays every record and asserts the output is identical. Run: passes before the move.

### Task 2: Move the generators

- [ ] `git mv skills/annotate/diagrams skills/_shared/visuals`; `git mv skills/annotate/atomic.py skills/_shared/atomic.py`.
- [ ] Rewrite every `skills.annotate.diagrams` import and patch target to `skills._shared.visuals`, and every `skills.annotate.atomic` to `skills._shared.atomic`.
- [ ] Move the diagram test modules into `skills/_shared/visuals/tests/`.
- [ ] Update `tools/gen_font_metrics.py`'s target path and every doc that names the old path.
- [ ] Run the full suite (`-n 4`). Expected: all pass, golden test included. Commit.

### Task 3: Keys

- [ ] Failing tests: `render(spec, id, keyed=True)` puts `data-key="step:<id>"` on each step row and `data-key="actor:<id>"` on each actor box and label; `render_key(..., keyed=True)` puts `step:<id>` on each key row; flowchart nodes carry `node:<id>` and edges `edge:<a>-><b>#<n>`, on the ELK and the Python layouts; `keyed=False` output equals golden.
- [ ] Implement; run; commit.

### Task 4: The stage face

- [ ] Vendor Geist and Geist Mono woff2 (OFL, with licence files) into `skills/_shared/visuals/fonts/`.
- [ ] Extend `tools/gen_font_metrics.py` to emit `STAGE_SANS_400/600/700` and `STAGE_MONO` tables; regenerate `font_metrics.py`.
- [ ] Failing tests: `text_px(text, style, face="stage")` differs from the default and matches the Geist tables; `render(..., face="stage")` lays out wider or narrower boxes accordingly; default output equals golden.
- [ ] Thread `face` through `text_metrics`, `sequence`, `flowchart_layout`, `elk_layout` (its cache key includes the face) and `flowchart`. Run; commit.

### Task 5: One stylesheet

- [ ] Move the sequence and flowchart rules of `annotate/static/diagram.css` into `skills/_shared/visuals/visuals.css`, with font families through `--vis-sans` and `--vis-mono` (defaulting to annotate's fonts), and keep them in `diagram.css` between `/* visuals:begin */` and `/* visuals:end */`.
- [ ] Test: the marked block equals `visuals.css` byte for byte. Annotate's browser tests still pass. Commit.

### Task 6: Scene models and the arrow rule

- [ ] Failing tests in `stage/tests/test_scene.py`: revealing both ends of a Mermaid edge shows the edge; `sequence_model` keys, order and `up`; `flowchart_spec_model` keys, order and `edges`; `resolve` reads `step s3`, `s3`, a step label, `a->b`.
- [ ] Implement in `scene.py`; run; commit.

### Task 7: The stage draws visuals

- [ ] `stage.py` registers `skills/` as the asset root with entry `stage/static/entry.js`; `entry.js` loads `visuals.css` and the local fonts, and no longer loads Google Fonts.
- [ ] `stage.css`: map annotate's diagram tokens and `--vis-sans`/`--vis-mono` for light and dark; the `visual` layout (grid and key side by side from 1000px).
- [ ] `stage.js`: render `format: "visual"`; stamp `data-key` on code and change lines, table rows and Mermaid parts; Fit grows up to 2×; the step bar with Back and Next.
- [ ] `scene.js`: one engine over `[data-key]`, by attribute value.
- [ ] `stage.py show` and `model.parse_source` accept `sequence:-` and `flowchart:-`, render keyed with `face="stage"`, and attach the scene model.
- [ ] Browser tests from the spec's Testing section. Run talk and stage suites; commit.

### Task 8: Talk speaks in sequences and flowcharts

- [ ] Failing tests: `[[show sequence | T]] {…} [[/show]]` becomes a `visual` board with a scene; a bad spec is refused with the validator's message; `flowchart` with a non-JSON body stays Mermaid; auto-steps reveal steps one sentence at a time.
- [ ] Implement in `talk.py` (`BOARD_KINDS`, `parse_head`, `board_item`, the model choice) and document both tools in talk's and stage's SKILL.md with annotate's when-to-use rules. Run; commit.

### Task 9: Live check and delivery

- [ ] A talk call on a spare port showing the Montblanc story as a sequence and a flowchart, stepping with the voice; screenshots at each step, light and dark, phone width.
- [ ] Full suite under pre-push conditions; restart the user's talk server; ask before pushing.
