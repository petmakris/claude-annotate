---
name: audit-demo
description: Audit the talk stage demo (`skills/talk/demo.md`, the gear's Stage demo and `talk.py --demo`) against the boards it exists to show — that every board kind and every way to steer one appears, that its narration tells the truth about the code it puts on the stage, and that board features added since the demo last changed are shown in it. Finds a code board whose pointed lines no longer hold what the voice says, a change board whose revision no longer diffs, a claim about talk the code contradicts, and stage features the demo never shows. Reports in plain English. Use when the user says "/audit-demo", "check the demo", or after work on the stage's boards.
user-invocable: true
---

# /audit-demo — does the demo still show every board as it is now?

The stage demo is talk's tutorial: the gear's **Stage demo** opens it in a tab, and every answer in it is written the way a Claude session writes one, so it is also the working example of every board tag. It only teaches if it keeps up. Boards change often (Lanes replaced the numbered sequence, the map replaced Mermaid, tables gained cell points within a day), and a demo that still shows the old board, or whose voice describes lines that have since moved, teaches the wrong thing while every test passes.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/talk/tests/test_demo.py::test_every_demo_answer_goes_through_the_reply_parser_without_a_board_problem` — every answer parses with no `board:` problem, and the demo shows code, change, sequence, flowchart and table.
- `skills/talk/tests/test_demo.py::test_the_demo_shows_every_board_kind_and_every_way_to_steer_one` — every kind in talk's `BOARD_KINDS` (but Mermaid's `diagram`), every point form (lines, row or cell, node, step), and the `next`, `+` and `key` tags and a `page:` line all appear. Do not re-report a missing kind or form; run the test instead.
- `skills/talk/tests/test_demo.py` also covers next, again, back and start over, and the gear's demo being reused.

## Step 1 — inventory

Read `skills/talk/demo.md`, `skills/talk/SKILL.md` (its board table, pointing forms, verbs and the sentences on how each board draws), and the board renderers: `skills/stage/static/lanes.js`, `map.js`, `stage.js` (`paintTable`, `paintFrame`), `stage.css`, `skills/stage/scene.py`, and the board code in `skills/talk/talk.py`. Then `git log --format='%h %ad %s' --date=short -- skills/talk/demo.md | head -1` for when the demo last changed, and `git log --format='%h %ad %s' --date=short <that commit>..HEAD -- skills/stage/static skills/stage/scene.py skills/talk/talk.py` for every board change since.

## The rules

- **Rule 1 — a code board's voice matches its lines.** For every `[[show code: path:a-b]]` and each `[[point: lines x-y]]` after it, read those lines at HEAD. When the narration names a function, class or behaviour ("offer puts it in the queue") and the pointed lines do not hold it, that is **Critical**: the demo points at one thing and says another.
- **Rule 2 — a change board still diffs.** Every `[[show change: path since <rev>]]` must name a revision that exists (`git rev-parse <rev>`) with a non-empty diff for that path, and its pointed lines must fall in the new side of a hunk that holds what the voice describes. A missing revision or an empty diff is **Critical**; pointed lines that moved is **Critical** under Rule 1's test.
- **Rule 3 — what it says about talk is true.** A sentence in the demo that states how talk or the stage behaves (the engines' speed and cost, what launchd does, what a page is, how a map draws loops) and that `SKILL.md` or the code contradicts is **Critical**. Check each against its source.
- **Rule 4 — a board feature since the demo is shown.** For each board change in the Step 1 log that adds something a reader can see or a reply can ask for (a new field drawn, a new point form, a new verb, a new layout behaviour), the demo should show it. A new pointing form or verb that `SKILL.md` documents and the demo never uses is **Medium**. A change that may or may not need showing (a layout tweak, a size change) is a **Decision**: name the commit and ask.
- **Rule 5 — it plays.** Run `uv run -q --with-requirements requirements-test.txt python -m pytest skills/talk/tests/test_demo.py -q -n 0`. A failure is **Critical**; quote it.

## Closed allowlist — never flag these

1. The demo's opening HTML comment — it describes the file format, not the boards.
2. Words the demo says to steer it ("say next", "start over") — they are the demo's own controls.
3. A board in the demo that uses fewer fields than the spec allows, when the board still reads well — the demo shows each board, not every field of it.
4. Mermaid: a call draws no Mermaid by design (`SKILL.md`), so the demo has no `diagram` board.

## Step 2 — scan

Apply Rules 1 to 3 answer by answer, reading every file and revision they name at HEAD. Apply Rule 4 commit by commit over the Step 1 log. Run Rule 5's command last.

## Step 3 — severity

Critical: the demo teaches something false or does not play. Medium: it never shows something a reply can now do. Low: wording that is true but stale ("a second" where it is now "a second or two"). Decision: whether a change needs showing at all.

## Output template

```
Demo audit — actionable items

Checked {N} answers, {M} boards and {K} board changes since the demo last changed ({commit}, {date}).
Verdict: {one sentence.}

**Critical — fix first**
1. {What the demo says or shows, and what is actually true}. {Imperative fix}. — demo.md answer {n}

**Medium — the demo has fallen behind**
2. {The feature, the commit that added it}. {Add it to answer n, or a new answer}.

**Low — wording**
3. ...

**Decision — needs your call**
4. {Commit} changed {what}. Show it in the demo, or leave it?

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the lines and the fix. "fix N" edits demo.md and reruns the demo tests.
```

## After delivering the report

Stop and wait. `explain N` quotes the demo's sentence and the code or commit beside it. `fix N` edits `skills/talk/demo.md`, reruns `skills/talk/tests/test_demo.py`, and says which answer to play again (the gear's Stage demo, then "back" or "start over"). A false positive means fixing this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not restate what `test_demo.py` already checks; run it.
- Do not rewrite the narration for style; only for truth or to show a missing feature.
- Do not add a demo answer per field; one answer per board, showing what a reader would notice.
- Do not change board code from this audit; report what the demo lacks.
