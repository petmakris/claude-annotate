---
name: audit-failing-tests
description: Run the whole test suite the way a fresh machine would (a clean worktree of origin/main, an empty HOME, Python 3.9 and the newest Python) and fix every test that fails, each fix proven and committed. Only a typed "/audit-failing-tests" starts it. Under `/audit` it reports the failures and fixes nothing.
user-invocable: true
disable-model-invocation: true
---

# /audit-failing-tests — does the suite pass everywhere, and if not, fix it

The repository has no GitHub workflows. The pre-push hook (`.githooks/pre-push`) is the only gate, and it runs the full suite under one Python only. Under Python 3.9 it just compiles and collects. So a test can fail under 3.9, or on a machine without your daemon config, and nothing says so. This skill runs the suite in those settings and fixes what fails.

## The audit contract (read first)

- **Violation** — a test that fails on an untouched worktree of origin/main in one of the runs below. True 100% of the time: the run is the proof.
- **Decision** — a fix that needs the user: deleting, skipping or loosening a test, a change to what the product does, or a failure caused by the machine and not by the code. Never fixed on your own; asked.

## Covering tests — do not duplicate them

- `skills/tests/test_audit_suite.py` checks this skill's frontmatter, its required sections and its row in `/audit`'s table.

## Mode

- Typed `/audit-failing-tests`: run Steps 1 to 5.
- Run by `/audit` (or by any agent that cannot edit): run Steps 1 and 2 only and return the report. Fix nothing.

## Step 1 — a clean worktree

Never run or fix in the user's checkout. Other sessions work in it.

    git fetch -q origin
    wt=<scratchpad>/failing-tests
    git worktree add --detach "$wt" origin/main

All commands below run in `$wt`.

## Step 2 — run the suite in every setting

Each run uses the pinned tools and an empty `HOME`, so no `~/.claude/webcompanion/config.json` is reachable:

    home=$(mktemp -d)
    for py in 3.9 3; do
      uv run -q --python "$py" --with-requirements requirements-test.txt \
        env HOME="$home" python -m pytest skills -q -rs -p no:cacheprovider \
        > "<scratchpad>/run-$py.txt" 2>&1
    done

`3.9` is the declared floor (README, `requirements-test.txt`). `3` is the newest Python uv finds. Say which version that was in the report (`uv run --python 3 python -V`).

Node runs the tests that load the page's code. Use the node on PATH and name its version in the report. A test that is **skipped** because node or another tool is missing counts as a failure: list the `-rs` reasons.

Then run each failing test alone, three times, on the Python it failed on (`-n 0 -p no:cacheprovider '<nodeid>'`):

- fails 3 of 3: **stable**.
- fails 1 or 2 of 3: **flaky**.
- passes 3 of 3 alone: **order-dependent**. Another test leaves state behind. Find it with `-n 0` on that test's file.

If every run is green and nothing is skipped, report that, remove the worktree, and stop.

## Step 3 — find the cause of each failure

Group failures that share one error (27 tests failing on the same line of `call.js` are one failure). For each group, read the assertion and the code it tests, and name the cause. It is one of:

1. **Product bug** — the code is wrong under that Python, node or empty HOME. Fix the code.
2. **Stale test** — the code changed on purpose and the test still expects the old behaviour. Fix the test so it pins the new behaviour with exact values. Check `git log -p` on the code to show the change was meant.
3. **Test leans on the machine** — a path, a clock, a locale, a home config, a tool's version. Make the test set what it needs itself.
4. **Machine, not code** — the setting is one the project does not support (an end-of-life node, say). This is a **Decision**: report it, change nothing.

A flaky or order-dependent test is a cause of its own. Find the race or the shared state. Never add a retry or a sleep to make it pass.

## Step 4 — fix, one cause at a time

For each cause from 1 to 3, in `$wt`:

1. Make the smallest fix at the cause.
2. Prove it. Run the failing test alone with the fix, and with the fix removed. Paste both runs: failing without it, passing with it. Set `PYTHONDONTWRITEBYTECODE=1` for these runs, or Python's cache can run the old file. For a stale test, the proof is the test passing, then failing when you plant the old behaviour back in the code.
3. Commit it in `$wt` with a one-line message naming what was wrong (`talk: call.js reads navigator only where it exists`). Stage by path.

Never, without asking the user first: delete a test, add `skip` or `xfail`, loosen an assertion, or widen a tolerance. Those are **Decisions**.

## Step 5 — run everything once more, then land it

Run all of Step 2 again in `$wt`. It must be green on every Python. Then:

    git fetch -q origin && git rebase origin/main
    git push origin HEAD:main

The pre-push hook runs the suite once more. claude-annotate is the user's personal tooling, so pushing needs no ask. If the user's checkout is on main with no changes of its own, `git pull --ff-only` there. Otherwise tell them it is behind. Remove the worktree: `git worktree remove "$wt"`.

If a fix needs product judgment, or Step 5 is not green, push nothing. Report what is committed in `$wt` and leave the worktree for the user.

## Output template

```
Failing tests — claude-annotate — origin/main at {short sha}

Ran: Python 3.9 and {newest}, node {version}, empty HOME.
Verdict: {one sentence: "all green", or "N failures from M causes, K fixed and pushed".}

**Fixed**
1. **{cause in a few words}** — {which tests, on which Python}. {what the fix changed}. Commit {sha}.

**Decisions — your call**
1. **{cause}** — {which tests}. {the choice, as a question}.

**Still failing**
1. **{cause}** — {why it is not fixed yet}.

Skipped for a missing tool: {list, or "none"}.
```

Under `/audit`, use the same template with **Failing** in place of **Fixed**, and no commits.

## After delivering the report

Stop and wait. `explain N` shows the failing assertion, the cause in the code and the two proof runs. When the user decides a Decision, carry it out as Step 4 and land it as Step 5.

## Anti-patterns (do not do these)

- Do not run or fix in the user's checkout. Use the worktree.
- Do not make a test pass by skipping it, retrying it, sleeping, or loosening what it checks.
- Do not fix a group test by test when one cause breaks them all.
- Do not report a fix without the two pasted proof runs.
- Do not push when any run is still red.
