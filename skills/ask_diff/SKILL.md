---
name: ask-diff
description: Per-line threaded Q&A on a GitHub PR diff, surfaced in IntelliJ via the IDE plugin. User clicks any diff line, asks a question, Claude wakes via WEBCOMPANION_EVENT, appends a reply to the line's thread, and the IDE refreshes that thread. Triggered by /ask-diff <PR> (called /interactive-review before 2026-09-02). Watcher events are WEBCOMPANION_EVENT / WEBCOMPANION_FINISHED / WEBCOMPANION_CANCELLED.
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Monitor
---

# /ask-diff — per-line threaded Q&A on a PR diff

> Requires the companion IntelliJ plugin. Without it this skill has nowhere to
> render — install the `.zip` from the repository's Releases page first.

> **The command renamed, the wire did not.** This skill answered to
> `/interactive-review` until 2026-09-02; it was renamed because three separate
> tools were called "review" and only one of them judges a PR. The daemon
> `kind` identifier stays the literal string `interactive-review` everywhere
> below — in `push.py`, `sync.py`, the `webcompanion watch --kind` argument
> and the IDE plugin's `KIND` constant — never `ask-diff` or `ask_diff`,
> because the separately-installed webcompanion daemon and the shipped
> plugin `.zip` both key off that string. Changing it would need all three
> released together; renaming the command needed nothing on the wire.

Surface a GitHub PR diff in IntelliJ (via the IDE plugin) where the user clicks any changed line to open a threaded conversation on it. Claude answers in that thread; the IDE refreshes the thread in place. No code is modified — this is a tool for *understanding* a PR, not rewriting it.

Use this when you want to walk through a PR line-by-line, ask questions about specific changes, or discuss a diff with a collaborator. The session is anchored to a diff snapshot taken at session-open, kept fresh by a git hook (see "Install the live-sync git hooks" below) so a local commit, rebase, or amend on the reviewed branch doesn't leave threads pointing at lines that no longer exist. The conversation persists as a thread per anchor so you can return to earlier questions.

If a fix is warranted, suggest it as a markdown code block inside the thread. Never modify the diff itself — code is immutable in this view.

## Invocation

The user types:

```
/ask-diff <PR>
```

where `<PR>` is one of:

- A number (`123`) — current repo's PR #123.
- A full URL (`https://github.com/org/repo/pull/123`).
- A branch name (`feature/foo`) — resolves to **that branch's open PR**, the
  same way `gh pr view feature/foo` does. It is not a pre-PR review: a branch
  with no PR fails at the push with `gh pr fetch failed`. The base is always
  the PR's own base branch.

## On every invocation: the daemon must be running

ask-diff no longer ships a server. Storage, comment threads and the event
queue all belong to the **webcompanion daemon** — one always-on service per
machine, shared with every other skill and IDE plugin that talks to it. It is
installed and kept alive by launchd (macOS) or systemd (Linux), so there is
nothing to start per session and no port to negotiate.

Confirm it is up before doing anything else:

```bash
webcompanion status
```

If that fails, stop and tell the user — do **not** try to start it yourself
(a client that auto-starts a service races every other client doing the same):

```
webcompanion doctor      # both interpreters, config, zipapp, launchd job, health
```

If `webcompanion` is not on PATH at all, the daemon has never been installed
on this machine:

```
pipx install webcompanion && webcompanion install-service
```

## Running the plugin's own code

`skills.ask_diff.push` and `skills.ask_diff.sync` run out of the plugin's own
tree, and `$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash tool's shell.
Reach them through `claude-annotate`, the plugin's runner: Claude Code puts
the plugin's `bin/` on `PATH`, the runner finds the plugin root from its own
location, and on a machine with no python3 it prints a sentence naming the
plugin and the fix instead of a traceback. Each command below is
self-contained — nothing has to be resolved first or carried between Bash
calls.

## Install the live-sync git hooks

Run this once per repo clone, at the top of every invocation — cheap to check, so it is transparently repeated
whenever it turns out to be missing rather than assumed done from a prior
run:

```bash
HOOKS_DIR="$(git -C "$PWD" rev-parse --git-path hooks 2>/dev/null)"
if [ -n "$HOOKS_DIR" ] && ! grep -qF "# claude-annotate: skills.ask_diff.sync" "$HOOKS_DIR/post-commit" 2>/dev/null; then
  "$(claude-annotate root)/skills/ask_diff/install_hooks.sh" "$PWD"
fi
```

`install_hooks.sh` is idempotent and never overwrites a hook. If it refuses, it prints why and exits 0: say so in one sentence and continue, without live sync for this repo. [`references/live-sync-hooks.md`](references/live-sync-hooks.md) says what the hooks do.

## Push the diff and create a session

```bash
claude-annotate ask_diff.push \
  --pr "$PR_REF" --cwd "$PWD" --claude-session-id "$CLAUDE_CODE_SESSION_ID"
```

The output is JSON with `sid`, `slug`, `kind`, `cwd`, `title`, `url`, and `warning` and `omitted_files` only when present. Save `sid`, `url` and `title`; name any omitted files and append any `warning` to the "review session ready" sentence below. The call ends any other live review at this `cwd` (`supersede=True`).

When `push.py` fails (the `gh` fetch, a diff over 1,984 KB, or an unreachable daemon) it exits 1 with a message: surface it verbatim, never retry and never start the daemon yourself. [`references/push-details.md`](references/push-details.md) has the JSON, the limits and each error's wording.

## Tell the user where to review

One sentence in terminal:

**"Review session ready for `<title>` — open the project in IntelliJ; the plugin shows per-line annotations on the diff. Click any line to ask a question and my answer appears as a threaded reply inline."**

## Arm the watcher

Arm it **immediately** after telling the user, before any other work — before
seeding threads, before reading code, before answering anything.

```bash
webcompanion watch --kind interactive-review --sid "<sid>"
```

Pass that as the `Monitor` tool's `command` with `persistent: true` and a
`description` like `"ask-diff-wait sid=<sid>"`.

Banners: `WEBCOMPANION_EVENT skill=interactive-review sid=<sid> event_id=<id>`,
`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`.
Each stdout line wakes you once; the watcher stays alive across many events
until the session terminates.

**Never stop the monitor while the review is open**, however long it has been
quiet, and never to save turns. The IDE plugin treats a heartbeat older than
180s as an ended session (`DaemonSessionClient.REAP_AFTER_MS`) and latches it
one-way for that sid: the user sees "session ended — read-only", and re-arming
does not undo it — only a new session does. Only `webcompanion end` ends a
review.

## Handling a watcher event — read the matching reference

Every wake-up after this point is a watcher banner. **`Read` the named file
before doing the work**; do not load one the situation does not need.

| Situation | Read & follow |
|-----------|---------------|
| A task-notification's first stdout line is `WEBCOMPANION_EVENT`, `WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED` or `WEBCOMPANION_DROPPED` | `references/handling-events.md` — payload parsing, composing the answer, appending it and acking |
| The event's `text` decodes to `"event_kind": "anchor_orphaned"` — `sync.py` could not keep a thread live, no user asked anything | `references/orphaned-anchors.md` — what to tell the user for each `reason` |
| You are writing a reply into a thread | `references/response-style.md` — length, links, the title, and the markdown the IDE renders specially |

## Resolving a finding

If the user says a thread is resolved / no longer relevant (in terminal, or
by asking you to clear it), delete it rather than leaving a stale thread
behind for `sync.py`'s next anchor-migration pass to carry forward:

```bash
claude-annotate python -c "
from skills._shared import webcompanion_client as wc
wc.delete_thread('<sid>', '<anchor>', kind='interactive-review')
"
```

One library call through the already-shared client — there is no separate
CLI wrapper for this, unlike the pre-daemon design's dedicated
`resolve_cli.py`, which existed only because that design had no shared client
to call into directly.

## Ending the review

When the user indicates the review is complete — "looks good," "approved,"
"done reviewing" — end the session:

```bash
webcompanion end --sid "<sid>"
```

The watcher prints `WEBCOMPANION_FINISHED` and exits on its own.

## Terminal cancellation

If the user says "scrap it" / "stop the review" / equivalent while a watcher is armed:

```bash
webcompanion end --sid "<sid>" --cancel
```

The watcher prints `WEBCOMPANION_CANCELLED` on its next tick and exits on its
own — handle it per `references/handling-events.md`, then continue with whatever the user actually
wanted.

## Edge cases

Read [`references/edge-cases.md`](references/edge-cases.md) for gh failures, an empty PR, local and remote PR changes, a very large PR, a malformed event and an unreachable daemon. Two rules always hold: never start the daemon yourself, and answer each event specifically, in 2-4 sentences.
