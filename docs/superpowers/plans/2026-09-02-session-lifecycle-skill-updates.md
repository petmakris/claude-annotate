# Session Lifecycle: Skill-Level Explicit End Steps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the skill-side half of the session-leak problem: none of `dataflow`, `deck`,
`walkthrough`, or `ask_diff`'s `SKILL.md` files ever instruct Claude to call `webcompanion end`
(finish, not cancel) when a session's interaction naturally concludes — the only existing call
site in each is a "Terminal cancellation" section triggered by the user explicitly saying "scrap
it," which is a different, already-correct path this plan does not touch.

**Architecture:** This is documentation-only — `webcompanion end --sid <sid>` (no `--cancel`)
already does exactly what's needed; no daemon or client code changes. Each skill gets one new
section, distinct from its existing "Terminal cancellation" section, naming the natural-
completion signal specific to that skill's own flow and instructing Claude to call `end` then.

**Spec:** `~/projects/webcompanion/docs/2026-09-02-session-lifecycle-design.md` (a separate repo
— read it for full context on why this matters; Decision 3 and the "Skill-level explicit finish
steps" section are this plan's own authority). A companion plan in that repo covers the
daemon-side auto-expiry/un-finish work; this plan is independent of it and can be implemented in
either order — `webcompanion end` already exists today and needs no daemon change to be called.

## Global Constraints

- Do not touch any skill's existing "Terminal cancellation" section — that is the correct,
  already-working explicit-cancel path and is out of scope.
- Do not touch `show_diff` or `annotate`'s `SKILL.md` — same gap, but out of this program's own
  scope; flagged as a follow-up in the design spec, not this plan's job.
- Do not invent a daemon-side capability that doesn't exist — `webcompanion end --sid <sid>`
  (finish) is already fully functional; this plan only adds documentation telling Claude when to
  call it.
- Each skill's natural-completion signal must be genuinely native to that skill's own existing
  flow — do not invent a generic "say goodbye" heuristic that doesn't fit how the skill actually
  ends a conversation today. Read each skill's own SKILL.md in full for what "done" already looks
  like before writing its new section.

---

## Task 1: Add a natural-completion "finish" step to all four skills

This is one task covering four same-shape edits — batched per this program's own established
convention for small, independent, identically-shaped changes.

**Files:**
- Modify: `skills/dataflow/SKILL.md`
- Modify: `skills/deck/SKILL.md`
- Modify: `skills/walkthrough/SKILL.md`
- Modify: `skills/ask_diff/SKILL.md`

**Interfaces:**
- Consumes: `webcompanion end --sid <sid>` (existing CLI, unchanged).

- [ ] **Step 1: Read all four skills' full current flow before writing anything**

  For each skill, read its `SKILL.md` in full (not just the "Terminal cancellation" section) to
  find its own natural conclusion signal. Candidates to verify against the real text, not assume:
  - `dataflow`: does the user ever say something like "got it, thanks" / navigate away, or is
    the diagram meant to stay open indefinitely as a reference? Read the skill's own framing of
    what a session's lifetime is meant to be before assuming it "ends."
  - `deck`: the user finishing a review pass — does the skill's existing flow have any explicit
    "I'm done reviewing this deck" moment, or does deck review tend to be open-ended across a
    long editing session? If genuinely open-ended with no natural end signal, say so in the
    report rather than inventing one — Decision 3's own scope note in the design spec already
    accepts that a skill might not have a clean signal, and the daemon-side auto-expiry (a
    separate initiative) exists precisely as the safety net for exactly this case.
  - `walkthrough`: the tour reaching its last step and the user having no more questions — this
    one has an unusually clear natural end (the step sequence is finite).
  - `ask_diff`: the user indicating the review is complete — "looks good," "approved," "done
    reviewing" — or all threads being resolved.

  For any skill where a real, clear natural-completion signal exists, proceed to Step 2. For any
  skill where it genuinely does not (open-ended by design), do not force one — record that
  finding in the task report instead, and skip that skill's Step 2 edit. This is a legitimate,
  expected outcome for at least `deck` per the reasoning above — confirm with real reading, don't
  assume it going in.

- [ ] **Step 2: Add a "Natural completion" section to each skill that has a real signal**

  Place it near the existing "Terminal cancellation" section (immediately before or after — match
  whichever reads more naturally given each file's own structure) with a distinct heading (e.g.
  "## Ending the session" or "## When the walkthrough is done" — match each skill's own heading
  voice, don't force identical wording across all four). Content: name the specific signal from
  Step 1, then:

  ```bash
  webcompanion end --sid "<sid>"
  ```

  followed by one line noting the watcher will print `WEBCOMPANION_FINISHED` and exit — mirroring
  how the existing "Terminal cancellation" section already describes `WEBCOMPANION_CANCELLED`'s
  aftermath, for consistency within the same file.

- [ ] **Step 3: Confirm nothing else in each file needs to change**

  The existing `WEBCOMPANION_FINISHED` handling section in each skill (already present — see
  e.g. `dataflow/SKILL.md`'s "`WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED`" section) already
  correctly describes what to say when that event arrives, regardless of whether the browser's
  own Done button, this new proactive step, or (once built) the daemon's own auto-expiry caused
  it — confirm this is genuinely still accurate and needs no wording change, since the event's
  meaning doesn't change based on what triggered it.

- [ ] **Step 4: Run the test suite**

  Run: `cd <this worktree> && python3 -m pytest skills -q`
  Expected: unchanged from baseline (1085 passed, 24 subtests) — this task touches only
  documentation, no test should be affected. If any test DOES reference these files' content
  (unlikely, but check), confirm it still passes.

- [ ] **Step 5: Commit**

  ```bash
  git add skills/dataflow/SKILL.md skills/deck/SKILL.md skills/walkthrough/SKILL.md skills/ask_diff/SKILL.md
  git commit -m "docs: add explicit natural-completion webcompanion end steps to migrated skills"
  ```

---

## Testing strategy

Documentation-only change; the existing Python test suite is the only verification surface, and
it should be unaffected. There is no automated way to verify "Claude actually calls this at the
right moment" — that is inherently a live-usage observation, not a unit-testable property. If
this initiative later needs stronger confidence, that would be a live-session accuracy review, not
part of this plan.

## Known limitations (accepted, not deferred silently)

- `show_diff` and `annotate` have the identical gap and are explicitly out of scope for this
  plan (see Global Constraints) — flagged in the design spec as a follow-up.
- At least one skill (expected: `deck`, pending Step 1's actual finding) may have no clean
  natural-completion signal at all — for those, the daemon-side auto-expiry safety net (a
  separate initiative, in the `webcompanion` repo) is the only mitigation, not this plan.
- This documents when Claude *should* call `end` — it cannot force Claude to actually do so in
  every live conversation. The daemon-level auto-expiry safety net exists precisely because this
  skill-level step, even once written, cannot be a complete guarantee.
