# ask-diff

Per-line threaded Q&A on a GitHub PR diff, surfaced in IntelliJ via the IDE plugin.

## What it does

Fetches a PR diff and exposes per-line threads through the IntelliJ plugin, where every changed line is clickable. The user clicks a line, types a question, and Claude's answer appears as an inline threaded reply. No code is modified — the view is read-only. The goal is *understanding* a PR through targeted conversation, not reviewing it comprehensively in one pass.

The IDE client lives in `ide-plugin/` (a sibling of this repo's `skills/`). This skill is headless — it has no browser review page; IntelliJ is the only review surface.

## How to invoke

```
/ask-diff <PR>
```

where `<PR>` is:

- A PR number (`123`) — uses the current repo.
- A full GitHub URL (`https://github.com/org/repo/pull/123`).
- A local branch name (`feature/foo`) — pre-PR review against `main`.

## How it works

On invocation, the skill fetches the PR diff via `gh pr diff` and `gh pr view`, then pushes it straight to the **webcompanion daemon** — one always-on service shared by every migrated skill and IDE plugin — as the session's `__diff__`/`__meta__` items. There is no server of ask-diff's own: `push.py` mints the daemon session and installs those items in one call.

`install_hooks.sh` installs `post-commit`/`post-rewrite`/`post-checkout` git hooks in the repo being reviewed. When one of those fires, it runs `sync.py`, which re-fetches the diff and migrates every thread's anchor against the branch's new state — the live-sync mechanism that keeps a session from going stale after a local commit, rebase, or amend on the reviewed branch. A line that moved too far to relocate automatically raises an `anchor_orphaned` event instead of silently losing the thread.

The IntelliJ plugin discovers the session by cwd and polls/streams it directly from the daemon. When the user submits a question on a line, the daemon queues an event; the shared `webcompanion watch` process (armed by this skill, not a script of its own) wakes Claude with the anchor and the question. Claude reads the diff and other threads for context, composes a short answer, and appends it to the line's thread via the shared client. The IDE streams new thread entries over SSE and refreshes the thread in place.

Each question is one wake-up; Claude answers that question and goes back to sleep. The user iterates by clicking more lines or asking follow-ups on existing threads.

## Architecture

- **Daemon:** the shared `webcompanion` service — one long-lived process per machine, serving every migrated skill's sessions. No per-skill server.
- **Session data:** the daemon's own `__diff__`/`__meta__` items (the diff snapshot and PR metadata) and per-anchor comment threads, all in the daemon's session directories — nothing lives under the reviewed repo itself.
- **`push.py`** — fetches the PR diff/metadata and creates or attaches to the daemon session.
- **`sync.py`** — the live-sync engine: finds every live session matching the branch a git hook just fired for, re-fetches the diff, and migrates each thread's anchor (or orphans it if the line is gone).
- **`install_hooks.sh`** — idempotently installs the git hooks that invoke `sync.py`.
- **`diff.py`** — diff parsing, hunk extraction, and PR-ref validation.
- **Watcher:** `webcompanion watch` (the shared daemon CLI, not a script of this skill's own) emits `WEBCOMPANION_EVENT` / `WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED` / `WEBCOMPANION_DROPPED`.

## Files

- `SKILL.md` — Full skill definition: invocation, hook installation, session creation, watcher protocol, Mode D event handling, edge cases.
- `push.py` — Fetches the PR diff/metadata and pushes it to the daemon as a new or attached session.
- `sync.py` — Live-sync engine invoked by the installed git hooks; also usable as `python3 -m skills.ask_diff.sync` directly.
- `install_hooks.sh` — Idempotent git-hook installer for the live-sync mechanism.
- `diff.py` — Diff parsing, hunk extraction, and PR-ref validation.
- `tests/` — Unit tests.

See `SKILL.md` for the full protocol.
