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

`install_hooks.sh` appends `post-commit`/`post-rewrite`/`post-checkout` hooks
that fire `python3 -m skills.ask_diff.sync` in the background — the mechanism
that keeps a session's diff and thread anchors from going stale after a local
commit, rebase, or amend on the reviewed branch. It never overwrites an
existing hook (appends behind its own marker) and is itself idempotent, but
checking the marker here first avoids re-running it — and re-`grep`ping every
hook file it touches — on every single invocation once it has already
succeeded once for this clone. If it refuses (a repo-tracked `core.hooksPath`
outside `.git`), it prints why and exits 0 — session creation still proceeds,
just without live sync for this repo; say so to the user in one sentence and
continue.

## Push the diff and create a session

```bash
claude-annotate ask_diff.push \
  --pr "$PR_REF" --cwd "$PWD" --claude-session-id "$CLAUDE_CODE_SESSION_ID"
```

This fetches the PR diff via `gh pr diff`/`gh pr view`, then does two things
in one call: creates (or attaches to) the daemon session for `kind=
interactive-review` at this `cwd`, and writes the diff and its metadata as
that session's `__diff__`/`__meta__` items. When `gh pr diff` refuses (GitHub
will not serve a diff over 300 files), the diff is built locally instead —
`git diff <base>...<head>` against the PR's base branch (`origin/<base>` when
this clone has it), leaving out `*.json` unless
`INTERACTIVE_REVIEW_LOCAL_EXCLUDE` names other globs. The output is JSON:

```json
{
  "sid": "...",
  "slug": "...",
  "kind": "interactive-review",
  "cwd": "...",
  "title": "...",
  "url": "http://127.0.0.1:PORT/s/<sid>/",
  "warning": "...",
  "omitted_files": ["..."]
}
```

`warning` is present only for diffs over 1 MB (annotations may be slow).
`omitted_files` is present only when files were dropped: any file whose diff
carries a line over 2,000 characters — a minified bundle, a generated page
with content inlined — is left out of the review, and its path listed here
(and in the session's `__meta__` item). Name the omitted files in the "review
session ready" sentence below so the user knows they are not in the IDE. Save
`sid`, `url`, and `title` for the rest of this turn.

**One active review per `(cwd, kind)` — enforced by `supersede=True` on this
call.** Opening a new review for this repo ends any other live
`interactive-review` session at this same `cwd` first, in the same call — no
separate list-then-cancel step. This is coarser than the pre-daemon server's
own per-Claude-session supersede: two PR reviews opened concurrently in
*different* repos from the same Claude conversation no longer auto-cancel
each other. Accepted limitation — see the plan's Known Limitations.

**gh failure:** `push.py` prints `ask_diff push: gh pr fetch failed: <error>`
to stderr and exits 1. Surface this verbatim in terminal: *"Couldn't fetch PR
diff: `<error>`. Check `gh auth status` and try again."* Do not retry.

**Diff too large:** rejected when the diff, after dropping minified files and
measured as the JSON the daemon stores, is over 1,984 KB — just under the
daemon's 2 MB item limit. `push.py` prints `ask_diff push: diff is <N> KB,
over the … limit` and exits 1 before creating any session; surface it like a
gh failure and stop. Diffs over 1 MB succeed but carry `warning`; append it to
the "review session ready" sentence below.

**Daemon unreachable/not configured:** `push.py` prints the daemon client's
own error (which names the fix — `webcompanion status` or `pipx install
webcompanion && webcompanion install-service`) and exits 1. Do not try to
start the daemon yourself.

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

- **gh failure** — session creation fails with a descriptive error. Surface verbatim; don't retry.
- **Empty PR (no diff)** — the diff snapshot is empty; the IDE shows no annotatable lines. General comments (`__general__` anchor) still work.
- **PR updated locally mid-session** — a commit, rebase, amend, or checkout on
  the reviewed branch fires the installed git hook, which resyncs the diff
  and migrates every thread's anchor automatically (see "Install the
  live-sync git hooks"). A line that moved too far to relocate, or one whose
  new position collides with another thread's, is reported via an
  `anchor_orphaned` event (see `references/orphaned-anchors.md`), not silently
  dropped. This only covers *local* changes to the branch — see "Remote-side
  PR changes" below.
- **Remote-side PR changes** — if someone else pushed to the PR, or you
  pushed from another machine, nothing here notices; there is no hook for
  that. The session's diff stays as of its last local sync. Recommend the
  user restart the session if they suspect this.
- **Very large PR** — soft warning above 1 MB of diff; hard reject above 1,984 KB (just under 2 MB); files with minified lines are dropped first and listed as `omitted_files`. The user can review a narrower PR instead.
- **Malformed event payload** — no reply; run `webcompanion ack --sid "<sid>" --event-id "<event_id>"` directly so the event isn't re-emitted forever.
- **Daemon unreachable** — do not try to start it yourself; run `webcompanion status` / `webcompanion doctor` and tell the user what they reported.

## Token budget

Each event wake-up is a single question on a single anchor. Answer specifically what was asked. 2-4 sentences is right for most questions; expand only when code context genuinely requires it. The user iterates by asking more questions — don't try to anticipate them.
