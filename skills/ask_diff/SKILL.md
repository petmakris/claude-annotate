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
- A local branch ref (`feature/foo`) — pre-PR review against `main`.

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

## Resolve the plugin root

`skills.ask_diff.push` and `skills.ask_diff.sync` both run out of the
plugin's own tree, and `$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash
tool's shell. Run this once per turn, before the first command that needs it:

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.
claude-annotate is the marketplace that ships this plugin and claude-ide-review.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '
import json, os, sys
NAME, MARKER = "claude-annotate", "skills/ask_diff/push.py"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit(f"could not locate the {NAME} plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
```

Two candidates, in order: every `bin/` directory on `PATH` (Claude Code adds
`<plugin-root>/bin` for both `--plugin-dir` and marketplace installs, even
when that directory does not exist), then the marketplace registry. Each
candidate must actually contain `skills/ask_diff/push.py`, so the check is a
marker file rather than a directory name and survives the plugin being
cloned under any name.

## Install the live-sync git hooks

Run this once per repo clone, at the top of every invocation, right after
resolving `$PLUGIN_ROOT` — cheap to check, so it is transparently repeated
whenever it turns out to be missing rather than assumed done from a prior
run:

```bash
HOOKS_DIR="$(git -C "$PWD" rev-parse --git-path hooks 2>/dev/null)"
if [ -n "$HOOKS_DIR" ] && ! grep -qF "# claude-annotate: skills.ask_diff.sync" "$HOOKS_DIR/post-commit" 2>/dev/null; then
  "$PLUGIN_ROOT/skills/ask_diff/install_hooks.sh" "$PWD"
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
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.ask_diff.push \
  --pr "$PR_REF" --cwd "$PWD" --claude-session-id "$CLAUDE_CODE_SESSION_ID"
```

This fetches the PR diff via `gh pr diff`/`gh pr view`, then does two things
in one call: creates (or attaches to) the daemon session for `kind=
interactive-review` at this `cwd`, and writes the diff and its metadata as
that session's `__diff__`/`__meta__` items. The output is JSON:

```json
{
  "sid": "...",
  "slug": "...",
  "kind": "interactive-review",
  "cwd": "...",
  "title": "...",
  "url": "http://127.0.0.1:PORT/s/<sid>/",
  "warning": "..."
}
```

`warning` is present only for diffs over 1 MB (annotations may be slow);
save `sid`, `url`, and `title` for the rest of this turn.

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

**Diff too large:** rejected over 5 MB (same message shape as above — surface
it like a gh failure and stop). Diffs over 1 MB succeed but carry `warning`;
append it to the "review session ready" sentence below.

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

## Mode D — handling a watcher event

You wake here when a task-notification arrives whose first stdout line is one
of the `WEBCOMPANION_*` banners.

### `WEBCOMPANION_EVENT`

1. **Parse the banner:** extract `sid`, `event_id`.
2. **Read the payload** between `---payload---` and `---end---` — the daemon
   stores exactly `{anchor, text, images}` (there is no `type` field on the
   wire; the daemon's `_submit` handler keeps only these three keys from
   whatever was posted):
   - `anchor` — `<path>:<L|R>:<line>` or `<path>:<L|R>:<start>-<end>`, or
     `__general__` for a whole-PR comment.
   - `text` — a plain string, but it may itself be JSON encoding one of two
     structured envelopes. Check in this order, since a plain user comment
     can never legally match either:
     1. `json.loads(text)` succeeds, the result is a dict, and it has
        `"event_kind": "anchor_orphaned"` — this did **not** come from a
        user question. It is `sync.py`'s own notification that a git hook
        just ran and this anchor could not be kept live: `{"event_kind":
        "anchor_orphaned", "thread_title": "<...>", "old_anchor_text":
        "<...>", "reason": "stale" | "collision" | "cycle",
        "attempted_anchor": "<present when reason is "collision" or
        "cycle">"}`. Handle it under "`anchor_orphaned` events" below, not
        as a question.
     2. Otherwise, `json.loads(text)` succeeds, the result is a dict, and it
        has a `"v"` key — this is `ReviewSessionClient.postComment`'s
        anchor-text envelope: `{"v": 1, "anchor_text": "<line text at
        submit time, or "">", "comment": "<the user's actual question>"}`.
        Check `v == 1` (the only version this SKILL.md's parser knows); if
        `v` is anything else, don't guess at unfamiliar fields — fall back
        to treating the raw `text` string as the comment, with no
        `anchor_text`. On a recognized `v == 1`, the real question is
        `envelope["comment"]`, and `envelope["anchor_text"]` is the
        reviewed line's own text at the moment the user submitted (may be
        `""`).
     3. Otherwise (not JSON, or JSON without `event_kind`/`v`) — `text` is
        the comment verbatim, with no `anchor_text`.
   - `images` — `[{token, path}]`. `Read` each `path` before composing your
     answer if non-empty.

### `anchor_orphaned` events (a thread could not be kept live)

The payload's `thread_title` and `old_anchor_text` name the thread and the
line it used to sit on. There is no reply to write into that thread — the
thread itself is untouched and still holds its full history for audit, just
no longer reachable by clicking a line in the IDE. Three distinct root causes
share this event, told apart by `reason`, and they are not interchangeable —
saying "moved too far to track" about a line that was located exactly is
simply false:

- **`reason` is `"stale"`** (or absent, for an older `sync.py`): the
  reviewed line's content drifted too far for `sync.py` to relocate it
  automatically — there is nowhere left to point the thread at. Tell the
  user in terminal, one sentence: **"A reviewed line moved too far for me to
  re-anchor automatically — the thread on `<thread_title>`
  (`<old_anchor_text>`) is still there if you want to revisit it, but you'll
  need to re-ask on the new line."**
- **`reason` is `"collision"`**: `sync.py` DID find exactly where this line
  went — `attempted_anchor` names it — but that position isn't free. Either
  another thread is sitting there and is not itself moving (possibly because
  it, too, was blocked and had to stay put), or a second thread is
  converging on the very same line; merging any of them would silently mix
  two unrelated conversations into one. Tell the user in terminal, one
  sentence: **"A reviewed line now sits exactly where another comment does
  (`<attempted_anchor>`), so I couldn't move `<thread_title>` there
  automatically — it's still tracking `<old_anchor_text>`'s old position."**
- **`reason` is `"cycle"`**: this line swapped places with another commented
  line (`attempted_anchor` names where it went), so migrating either one
  first would overwrite the other before it could move — neither is
  touched. Tell the user in terminal, one sentence: **"A reviewed line
  swapped places with another commented line, so I couldn't safely move
  either one automatically — `<thread_title>` is still tracking
  `<old_anchor_text>`'s old position."**

Either way, then acknowledge the event (same `webcompanion ack` call as any
other event — there is nothing else to do). Do not treat this as a question
and do not `append_thread`.

### Composing an answer (a real question)

1. Fetch the diff and PR metadata once per turn if you don't already have
   them cached:
   ```bash
   PYTHONPATH="$PLUGIN_ROOT" python3 -c "
   from skills._shared import webcompanion_client as wc
   items = wc.get_items('<sid>', kind='interactive-review')
   print(items['__diff__']['body'])
   "
   ```
   For specific-line anchors, narrow to the relevant hunk. For `__general__`,
   scan the whole diff.
2. **Read other open threads as background context.**
   `webcompanion_client.get_threads(sid, kind="interactive-review")` returns
   every anchor's thread. Skim them. A question the user asked on
   `Foo.java:42` may sharpen what you say about `Bar.java:113`, and vice
   versa. These threads are READ-ONLY input — they inform your synthesis on
   the active anchor; never write into another anchor's thread. The same
   call tells you whether the active anchor's thread already has a non-empty
   `anchor_text` (needed for the append step below).
3. Use `Read`, `Grep`, `Glob` to pull in surrounding source context if the
   diff alone isn't enough.
4. Write a short, code-aware answer in markdown: 2–4 sentences typically.
   Fenced code blocks for snippet suggestions.
5. If you spot a real bug, flag it and suggest a fix as a code block. **Do
   not modify the diff.**
6. Avoid hedging. If you genuinely need more context, say so concretely
   ("I'd need to see how `foo()` is called elsewhere") — don't ramble.

### Appending the reply and acknowledging

Write ONLY to the active anchor's thread (the one in the event payload).
Thread isolation is load-bearing: never mutate any other anchor's thread in
response to this event.

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -c "
from skills._shared import webcompanion_client as wc
wc.append_thread(
    '<sid>', '<anchor>', '''<your markdown answer>''',
    kind='interactive-review', role='agent',
    source_event_id='<event_id>', title='<short headline>',
    anchor_text=<'<envelope anchor_text>' if this is the thread's first reply else None>,
)
"
webcompanion ack --sid "<sid>" --event-id "<event_id>"
```

Only pass `anchor_text` when this is the thread's *first* Claude reply (the
`get_threads` read above came back with no `anchor_text` yet for this
anchor) — `set_anchor_text_if_absent` on the daemon's side is first-write-wins,
so sending it again on a follow-up is harmless but redundant; omit it there.
Never interpolate the answer or the anchor into a shell string — route
free-form content through Python's own triple-quoted literal (or, if it
contains `'''`, write it to a scratch file with `Write` and read it back in
the same `python3 -c`) rather than composing a shell command from it. Ack
only after the append succeeds — a crashed append means the event is
re-emitted and retried safely (see "Re-apply safety" below); acking first
would lose the question.

**End your turn. No terminal output.** The watcher stays armed.

### `WEBCOMPANION_FINISHED`

The user clicked Done. Ack in terminal: *"Review session for `<title>` closed."*

### `WEBCOMPANION_CANCELLED`

The user cancelled (IDE, terminal `scrap it`, or superseded by a newer
review from this Claude session). Ack in terminal: *"Review session for
`<title>` cancelled."*

### `WEBCOMPANION_DROPPED`

An event went unanswered through every re-emit (an earlier wake-up was
interrupted or compacted away). Tell the user plainly: *"A review question
went unanswered and was dropped — please re-ask it on the line."*

## Resolving a finding

If the user says a thread is resolved / no longer relevant (in terminal, or
by asking you to clear it), delete it rather than leaving a stale thread
behind for `sync.py`'s next anchor-migration pass to carry forward:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -c "
from skills._shared import webcompanion_client as wc
wc.delete_thread('<sid>', '<anchor>', kind='interactive-review')
"
```

One library call through the already-shared client — there is no separate
CLI wrapper for this, unlike the pre-daemon design's dedicated
`resolve_cli.py`, which existed only because that design had no shared client
to call into directly.

## Response style guide

- **Self-contained synthesis.** Each reply should stand on its own as the
  answer to *all* questions asked so far on this anchor, not just the
  latest one. Absorb prior questions; do not assume the reader has scrolled
  back. The IDE surface renders only your most recent reply — older replies
  are stored for audit but not displayed.
- **Link references inline.** When you reference a specific file, method,
  or symbol from the code, render it as a markdown link whose target is
  the project-relative file path optionally followed by `:line`, e.g.
  `[forDashboard](src/main/java/.../OrderListService.java:18)`. For
  ticket IDs and external URLs, use a normal markdown link with the
  absolute URL.
- **Short.** 2–4 sentences in most cases. Answer the question; don't
  review the whole PR.
- **Code-aware.** Reference specific lines, variable names, and functions
  from the diff.
- **Suggest, don't ask.** When a fix is warranted, show it as a markdown
  code block immediately. The user copies it themselves.
- **Honest uncertainty.** If you need more context, name exactly what you
  need ("I'd need to see `<file>:<function>` to know"). Don't hedge.
- **No general reviews per event.** Each wake-up is one question on one
  anchor. Answer that; let the user iterate.
- **Headline title.** Pass a `title` to `append_thread`: plain text (no
  markdown), ≤ ~6 words / 60 chars, a noun phrase naming the thread's topic
  (e.g. "Null check on portfolio lookup", "Why the fee branch is skipped").
  Refresh it each answer so it stays accurate as the synthesis absorbs new
  questions. The IDE panel shows this as the row's title.
- **Structure, don't just write prose.** The IDE renders four markdown
  patterns specially — use them, don't just write one dense paragraph:
  - **Opening verdict.** If the reply has a one-line takeaway, open with a
    block quote whose first character is a severity symbol: `✓` (agrees /
    correct), `!` (critical), or `⚠` (important). It renders as a colour-coded
    pill instead of quoted text, and also drives the thread list's severity
    dot (see `AnnotationsPanel.severityColor`) — so use it whenever the
    finding actually has one of those three severities, not decoratively. A
    second line in the same quote renders as a dimmer subtitle underneath.
  - **Section labels.** Use `####` to break the answer into named sections
    (e.g. `#### Why one method, not two`, `#### Evidence`) — it renders as a
    small-caps label with a trailing rule, not a fourth heading weight.
  - **Evidence as code, not inline chips.** When you're citing something
    provable — two call sites that differ by one argument, a stack trace,
    the shape of a fix — put it in a fenced code block rather than stringing
    inline `` `code` `` spans through a sentence. Inline code stays for
    naming a symbol mid-sentence; fenced code is for showing something.
  - **Later block quotes are asides.** Any `>` block that is *not* the
    opening line renders as an accent-tinted callout card, for a genuinely
    separate side note (e.g. "one thing this doesn't fix").

  Example:
  ````markdown
  > ✓ Correct and intentional
  > confirmed against the OpenAPI contract and the test file

  #### Why one method, not two

  `sendOrders` isn't defined in `HttpDatasourceHttpClient` itself — it comes
  from `CoreBankingOrdersContract` in the external `wp_integration_layer_contract`
  library. The contract already models a check and a real transmission as
  one endpoint with a `dryRun` flag, not two endpoints.

  #### Evidence

  ```java
  httpClient.sendOrders(BANK_ID_STRING, false, "fr", ...) // real send
  httpClient.sendOrders(BANK_ID_STRING, true,  "fr", ...) // pre-trade check
  ```

  > New at this boundary: `OrdersEndpointTimeoutClient` applies a dedicated
  > read timeout only to `/orders`, because this call now runs synchronously
  > while an advisor waits.
  ````
  Not every reply needs all four — a quick factual answer with no verdict and
  no aside is still fine as plain prose. Reach for structure when the reply
  actually has a verdict, distinct sections, or provable evidence to show.

## Re-apply safety

`append_thread`'s daemon-side handler dedups by `source_event_id`. If the
watcher restarts and re-emits an event you've already handled, the second
call is a no-op. Process the event normally each time — storage handles
dedup.

## Terminal cancellation

If the user says "scrap it" / "stop the review" / equivalent while a watcher is armed:

```bash
webcompanion end --sid "<sid>" --cancel
```

The watcher prints `WEBCOMPANION_CANCELLED` on its next tick and exits on its
own — handle per Mode D, then continue with whatever the user actually
wanted.

## Edge cases

- **gh failure** — session creation fails with a descriptive error. Surface verbatim; don't retry.
- **Empty PR (no diff)** — the diff snapshot is empty; the IDE shows no annotatable lines. General comments (`__general__` anchor) still work.
- **PR updated locally mid-session** — a commit, rebase, amend, or checkout on
  the reviewed branch fires the installed git hook, which resyncs the diff
  and migrates every thread's anchor automatically (see "Install the
  live-sync git hooks"). A line that moved too far to relocate, or one whose
  new position collides with another thread's, is reported via an
  `anchor_orphaned` event (see that section's `reason` branch), not silently
  dropped. This only covers *local* changes to the branch — see "Remote-side
  PR changes" below.
- **Remote-side PR changes** — if someone else pushed to the PR, or you
  pushed from another machine, nothing here notices; there is no hook for
  that. The session's diff stays as of its last local sync. Recommend the
  user restart the session if they suspect this.
- **Very large PR** — soft warning above 1 MB of diff; hard reject above 5 MB. The user can request narrower review by passing a branch or a more focused PR.
- **Malformed event payload** — no reply; run `webcompanion ack --sid "<sid>" --event-id "<event_id>"` directly so the event isn't re-emitted forever.
- **Daemon unreachable** — do not try to start it yourself; run `webcompanion status` / `webcompanion doctor` and tell the user what they reported.

## Token budget

Each event wake-up is a single question on a single anchor. Answer specifically what was asked. 2-4 sentences is right for most questions; expand only when code context genuinely requires it. The user iterates by asking more questions — don't try to anticipate them.
