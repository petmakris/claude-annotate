---
name: audit-tests
description: Audit whether the tests keep up with the code. Plants small bugs in the product lines changed since the last audit (`tools/audit_tests.py changed`) and reports every one no test fails on, which is a change that landed without a test guarding it. Also lists tests that run exactly the same lines as another test in their file, or no product code at all (`tools/audit_tests.py redundant`), as candidates to merge or drop. Use when the user says "/audit-tests", "do the tests still catch bugs", "are the tests keeping up", or after a run of fast changes to talk, the stage or annotate.
user-invocable: true
---

# /audit-tests — do the tests still catch what the code does?

Product code here moves fast, and a test suite can fall behind in two ways that every green run hides. A change lands with no test that would fail if it broke: `talk.py --serve` and `--install-service` had none until a mutation run found it. Or a test keeps passing while it no longer guards anything: the two-calls scene passed with both calls listening, because it checked `!!live` rather than whether a page was listening. This audit measures both by running, not by reading.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — do not duplicate them

- `skills/tests/test_audit_suite.py` checks this skill's frontmatter, its required sections and its row in `/audit`'s table.
- The suite itself is the source of truth for what is guarded. Never judge a gap by reading a test; plant the bug and run it.

## Step 1 — plant bugs in what changed

Run, from the repository root:

    python3 tools/audit_tests.py changed --out <scratchpad>/audit-tests

It diffs the product files (`skills/**/*.py` and `*.js`, not tests) from the commit in `.claude/skills/audit-tests/last-audit` (or `HEAD~20` when there is none, or `--base REV`) to HEAD. It samples up to 30 bugs on the changed lines, one per line and spread over the files: a flipped comparison, a negated condition, `and`/`or` swapped, a deleted call, a return emptied, a constant moved. It runs each against the tests of that skill (the stage's are also run against talk's, which embed it) in a throwaway worktree of HEAD. First come the tests without a browser, then the browser tests if the bug survived those. It refuses to plant anything when the tests fail untouched.

Expect about a second per bug that dies in the fast tests (a JavaScript bug meets them too: some of them run the page's JavaScript under node), and one to two minutes per bug that reaches the browser tests. Tell the user the count before it runs; run it in the background when it is over ten minutes. It works in its own worktree, so the user's checkout is never touched; say so once.

## Step 2 — judge every survivor

For each `survived` row in `changed.json`, read the mutated line in context at HEAD and decide one of three:

- **Equivalent** — the change cannot alter behaviour: a dead branch, a value nothing reads, a guard the caller already ensures. Allowlisted below; never reported.
- **Gap** — it can. Name what a user of the product would see break, in one sentence, and which test file should catch it. This is a **Violation**.
- **Unsure** — run the narrowest test that should catch it with the bug planted (edit a scratch copy in a worktree, never the user's checkout). If it still passes, it is a gap.

Also check every `killed` row whose killing test cannot reach the mutated code: a stage-only bug killed by a two-calls microphone scene, say. Run that test five times on the untouched tree (`-n 0 -k <name>`). If it fails even once, the test is **flaky**, which is a **Violation**: a flaky test kills bugs at random and passes broken code at random. That is how scene 19 was found to hide a real race.

## Step 3 — candidates for removal

Run:

    python3 tools/audit_tests.py redundant skills/talk/tests skills/stage/tests --out <scratchpad>/audit-tests

(or the folders the changed files belong to; no folder means all of `skills`). It measures which Python lines each test without a browser runs. It lists groups of tests in one file that run exactly the same lines, and tests that run no product code at all. JavaScript coverage is not measured, so browser tests never appear here; say so in the report.

Read each group's tests. Report a group as a **Decision** only when two of its tests assert the same behaviour with inputs that take the same path. Ask whether to merge them, and name the one to keep. Tests that run the same lines but check different inputs, values or outcomes (four `dir_rev` cases, a boundary and its general case) are not candidates; skip them. A test that runs no product code is a Decision when it checks nothing the product depends on. It is not one when it checks a data file the product reads (`demo.md`, the token CSS, a SKILL.md table); skip those.

## The rules

- **Rule 1 — a change is guarded.** A planted bug on a changed line that survives every test of its skill, and is not equivalent, is a **Violation**. Severity: **Critical** when a user would notice the break in normal use (a call stops listening, a reply is lost, a board draws wrong, a command exits 0 on failure). **Medium** when only an edge or a message is affected.
- **Rule 2 — a test fails only for a bug.** A test that fails at least once in five runs on the untouched tree is a **Critical** Violation. Quote the failing assertion.
- **Rule 3 — every test earns its place.** Groups and idle tests that survive Step 3's reading are **Decisions**, never Violations: whether two tests are one is the user's call.

## Closed allowlist — never flag these

1. A survivor in logging, a message's wording, a timing constant whose only effect is speed (a poll interval, a retry delay), or a busy-wait's sleep.
2. A survivor in code only a real outside service reaches (Azure speech, launchd itself, the system microphone), when a test double stands in for it at the boundary. Report the boundary's own logic, not the service.
3. A survivor on a line the base commit already had, when the diff only re-indented or moved it.
4. Browser tests in Step 3: their coverage is not measured.

## Step 4 — the fix loop

For every Violation the user asks to fix (`fix N`):

1. Write the test in the skill's own test file, in the file's style, asserting behaviour a user would see, with exact values.
2. Plant the same bug again (the row's `old` and `new` lines) and run the new test: it must **fail**. Paste the failing line.
3. Restore the line and run it: it must **pass**. Paste it. Run with `PYTHONDONTWRITEBYTECODE=1`, or a restore within the same second at the same size runs the bug again from Python's cache.
4. For a flaky test, find whether the flake is in the test (a fixed wait racing the state) or in the product (a race the test exposes) before touching it. Fix the product when the product is wrong.

When the report is delivered and the fixes the user wanted are in, write HEAD's full hash to `.claude/skills/audit-tests/last-audit` and commit it with them, so the next run starts from here.

## Output template

```
Tests audit — actionable items

Planted {N} bugs in {L} lines changed since {base} ({date}) across {F} files: {K} killed, {S} survived ({E} equivalent).
Measured {T} tests without a browser for redundancy.
Verdict: {one sentence.}

**Critical — a change nobody would notice breaking**
1. {file:line}: {what the bug does, as a user would see it}. {The test to add, in which file}.

**Critical — a flaky test**
2. {test}: failed {n} of 5 untouched runs ({assertion}). {Whether the race is in the test or the product}.

**Medium — an edge left unguarded**
3. ...

**Decision — tests that may be one**
4. {test A} and {test B} ({file}) assert {the same thing}. Merge into {A}, or keep both?

Clean / tracked (no action): {equivalent survivors in one line; groups skipped as different inputs, in one line}.

Want detail on any item? Say "explain N" and I'll show the planted bug and the code around it. "fix N" writes the test and shows it failing with the bug and passing without it.
```

## After delivering the report

Stop and wait. `explain N` shows the planted line beside the original, the function around it, and the tests that ran. `fix N` follows Step 4. A false positive (an equivalent bug reported as a gap) means adding its case to the allowlist first, then dropping the item. Once the user is done, update `last-audit` as Step 4 says.

## Anti-patterns (do not do these)

- Do not judge a gap by reading tests. Plant the bug and run them.
- Do not plant bugs in the user's checkout. The script works in its own worktree; a manual check does the same.
- Do not delete a test because Step 3 listed it. Read it, and ask.
- Do not count a kill by a test that cannot reach the mutated code as a kill until that test has passed five untouched runs.
- Do not raise `--max` past 30 without telling the user how long it will take.
