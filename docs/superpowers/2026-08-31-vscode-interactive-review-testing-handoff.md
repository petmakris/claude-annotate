# VS Code per-line interactive review — testing handoff

**Written:** 2026-08-31 · **Branch:** `main`, direct commits, already pushed in all four repos
**For:** a fresh session running the manual test pass this feature has never had.

Read this first, then `docs/superpowers/specs/2026-08-31-vscode-interactive-review-design.md`
(the design) and `docs/superpowers/plans/2026-08-31-vscode-interactive-review.md` (the
9-task build log, with real code in every step) if you need the reasoning behind something
below. This build's own SDD ledger was deleted per process once its final review went clean
— the durable record from here on is git history and this document.

---

## 1. What the feature is, in one paragraph

`show-diff` opens a diff in VS Code's native multi-file diff editor, same as always. It now
also creates a `webcompanion` session for that diff and reports its `sid`; a new VS Code
module (`vscode-plugin/src/reviewComments.js`) registers a `CommentController` scoped to
that diff's files, so every changed line is clickable. Click a line, ask a question, and the
question is posted to the daemon as an event; a `webcompanion watch` loop armed by the
`show_diff` skill wakes Claude, who reads the diff, composes an answer, posts it with
`webcompanion reply`, and acks the event. The VS Code side polls the daemon every 2s and
renders the reply into the same comment thread — no reload needed. Read-only: nothing in
this flow ever modifies the checkout.

**Four repos, all on `main`, nothing merged as a branch because there was no branch — direct
commits by explicit choice.** `claude-annotate` (7bb5cb3) has the bulk of it: `skills/show_diff/`
(moved from `dashboard`) and `vscode-plugin/` (moved from `env/apps/ide-themes/vscode/`).
`webcompanion` (6b8d817) gained a `reply` CLI command and a few `Client` accessor methods.
`dashboard` (d0635ae) and `env` (745aa37) each lost a directory and gained a stale-path fix
or a forwarder script — nothing else in either repo changed.

**It has real test coverage, and one real gap.** 23/23 shell, 10/10 JS, 355/357 Python (the
2 failures are a pre-existing, unrelated environment condition — see §4). **The live,
interactive, click-a-line-in-a-real-VS-Code-window flow has never been run.** Everything
that tests it does so headlessly — stubbed binaries, mocked `vscode`, direct daemon HTTP
calls. Two real bugs were found and fixed by *reading* the code during the final review,
specifically because nothing in the test suite could have caught them. That's what this
session is for.

---

## 2. Before you touch anything — three setup checks

1. **Restart VS Code fully (quit, don't reload a window).** The extension's own build note
   is explicit: a running VS Code keeps executing whatever it loaded at startup, and a
   window reload doesn't re-scan installed extensions. Confirm activation:
   `Cmd+Shift+P` → "Petros: Set Markdown Preview Theme" should appear.
2. **Refresh this Claude Code session's view of the plugin.** Before this handoff was
   written, an already-open session still listed the skill as `dashboard:show-diff` — stale
   from before the move. Run whatever refreshes marketplaces in your session
   (`/plugin marketplace update` or equivalent) and confirm `show-diff` now shows under
   `claude-annotate`'s `claude-ide-review` plugin, not `dashboard`.
3. **Confirm the daemon is live:** `webcompanion status`. Nothing server-side changed in
   this build (verified during design — every new CLI command calls routes that already
   existed), so this is just ruling out an unrelated environment problem before you go
   hunting for one in this feature.

If all three check out, the extension is already rebuilt and installed as of this repo's
current `HEAD` (7bb5cb3) — no build step needed before testing.

---

## 3. The test pass itself

Run these in order. Each states what confirms it passed and what to do if it doesn't.

1. **Open a diff.** `/show-diff` on any repo with a real change — your own uncommitted work
   is simplest (`show-diff.sh <repo> HEAD --worktree` if you want to invoke it directly).
   → *Confirms:* the diff opens as before, AND the terminal output now includes a
   `comments: open in VS Code, click a line, ask a question` line plus `WC_SID=`/`WC_URL=`.
   → *If the comments line is missing:* `webcompanion` was unreachable when the script ran —
   recheck §2.3, then re-run.

2. **Ask one question.** Click a changed line, type a question, submit.
   → *Confirms:* within ~2s a task-notification wakes Claude, an answer appears in that
   comment thread, no reload needed.

3. **Ask a second question on a different line before the first is 30 minutes old** — fire
   it right after step 2, don't wait. This is the exact shape of the Critical bug fixed in
   this build (§4.1).
   → *Confirms:* both get answered independently, neither comes back a second or third time.
   → *If you see a duplicate reply, or a `WEBCOMPANION_DROPPED` notice:* the ack step
   regressed. This is the single most important thing this test pass exists to catch — stop
   and report it exactly as observed (which question, how many times answered, any
   `WEBCOMPANION_*` banners you saw in the Claude session).

4. **Close and reopen the same diff** (or reload the VS Code window), then check the thread
   from step 2 is still there and rendering in place. This is the exact shape of the
   Important URI-mismatch bug fixed in this build (§4.2).
   → *Confirms:* the thread reappears attached to the correct line.
   → *If the thread is gone or attached to nothing:* the URI fix regressed — report which
   side (left/base or right/head) and whether the diff was a worktree diff or a rev pair.

5. **Try a worktree diff specifically** (uncommitted changes, not two commits) — steps 1-4
   again but starting from `--worktree`. This path has its own line-siding logic
   (`anchorFor`'s worktree branch) that was itself buggy once (§4.4, fixed) — worth one full
   pass on its own.

6. **Try an added file** (a new, untracked file in the diff) and ask a question on it.
   → *Confirms:* the question anchors to the right side (`R`, since an added file has no
   base/left content) — this is the specific case Finding 4 (§4.4) was about.

7. **Optional, if you want to stress it further:** let a question sit unanswered-by-you for
   a while, or open two diffs in two different VS Code windows at once and confirm each
   polls and answers independently (`current`/`openThreads` state in `reviewComments.js` is
   module-level per extension-host process, not per-window — worth knowing if something
   seems to leak between windows, though nothing in this build's design should cause that).

---

## 4. What's already fixed — don't re-report these unless they've regressed

The final whole-branch review (an Opus-tier review reading actual code, not just diffs)
found these; all were fixed and independently re-verified against source before this branch
was pushed. Listed so you recognize them if they resurface rather than treating them as new.

1. **Critical — Mode D never acked events.** `webcompanion watch` blocks up to 30 minutes
   per event waiting for an ack, re-emitting (and re-waking Claude) up to 3 times without
   one. `show_diff/SKILL.md`'s Mode D was missing the ack step entirely. Fixed: step 6 now
   runs `webcompanion ack --sid <sid> --event-id <event_id>` after a successful reply.
2. **Important — pmdiff URI mismatch.** `diff.js` built comment-thread URIs with an
   absolute path (`path.join(repo, gitPath)`); `reviewComments.js`'s `renderThread` built
   them repo-relative. Any thread the poll loop constructed (i.e., any thread surviving a
   diff reopen) attached to a URI no open editor held, so it silently never rendered. Fixed
   to match exactly.
3. **Important — stale pre-move paths** in `SKILL.md`, the extension's `README.md`, and
   dashboard's ADR 0032. Fixed.
4. **Minor — `anchorFor` mis-sided an added file's left pane** in worktree mode (the
   `worktree && !ref` check fired before the ref comparisons, and an added file's
   `originalRef` is also `''`). Fixed by reordering; step 6 above re-exercises this live.
5. **Minor — the poll loop never stopped**, even after a session ended (`webcompanion end`),
   silently re-reading the daemon config file forever. Fixed: stops on `finished`/`cancelled`.
6. **Minor — a 426 contract mismatch was silently swallowed**, contradicting the spec's
   explicit requirement to surface it. Fixed: shows a warning and stops polling.
7. **Minor — anchor parsing broke on a colon in a file path.** Fixed to parse from the right.
8. Three more cosmetic/hygiene minors (a broken shebang, an undocumented test-fixture
   coupling, unused imports) — see the plan file's Task-by-task log or `git log` on the four
   repos for the exact commits if you want the detail; none are behavior-relevant to testing.

**The two `webcompanion` pytest failures you may see** (`test_a_missing_daemon_...`,
`test_migrate_apply_under_the_guard_...`) are not from this branch — they happen because a
real `webcompanion` daemon is running on the machine, which is the normal, correct state for
manual testing. They were independently reproduced against the pre-branch commit twice
during this build. Ignore them; the suite is green with the service stopped.

---

## 5. Scope boundaries — not bugs if you notice them

- `walkthrough` and the IntelliJ plugin (`ide-plugin/`) are untouched by this entire build,
  by design. If you're testing IntelliJ's own `/interactive-review`, that's a different,
  unrelated, already-working feature.
- Reviewing a GitHub PR from VS Code is out of scope. This only covers `show-diff`'s local
  diffs (branch-vs-base, commit-vs-previous, uncommitted worktree).
- Cross-repo git history was not preserved for the two moves (`dashboard`→`claude-annotate`,
  `env`→`claude-annotate`) — a deliberate plain copy-then-delete, not an oversight.
- `dashboard` and `env` both currently have unrelated dirty/uncommitted files from other,
  concurrent work in this environment (frontend components in `dashboard`, `SECRETS.md`/
  `CLAUDE.md` in `env`) — nothing to do with this feature; don't touch them as part of this
  test pass.

---

## 6. Where the durable records are

| | |
|---|---|
| `docs/superpowers/specs/2026-08-31-vscode-interactive-review-design.md` | the design, corrected once during planning to match the daemon's real contract (verified against source, not assumed) |
| `docs/superpowers/plans/2026-08-31-vscode-interactive-review.md` | the 9-task build log — every task has the real code written, plus a couple of inline plan-defect fixes (an off-by-one, a garbled sentence) made and noted during execution |
| `git log` on `claude-annotate`, `webcompanion`, `dashboard`, `env` | every ruling and every fix is in a commit message — the SDD ledger that tracked them live was deleted per process once the final review went clean, exactly as it's meant to be |
