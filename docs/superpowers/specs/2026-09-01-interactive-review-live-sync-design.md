# interactive-review live sync — keeping a review session current

**Date:** 2026-09-01
**Status:** approved design, ready for an implementation plan

## The problem

`interactive-review` snapshots a PR's diff once, at session-open, into
`diff.patch`/`meta.json`, and every thread anchor (`path:side:line`) is a plain
string computed against that one snapshot. Nothing ever looks at either file
again. The session has no idea the PR moved.

In one afternoon this bit the same session twice: a follow-up commit landed on
the PR, then a rebase+squash replaced the head entirely, and both times every
anchor silently pointed at code that no longer existed at that location. The
only way back was manual — re-fetch the diff, recompute every anchor's line
number by hand, verify each one against the new content — done twice, outside
any supported workflow, because the skill's own documented answer to a stale
session is "restart it," which throws away every thread's history.

A second, related gap: a thread has no lifecycle. "Fixed" is markdown text
with a ✓ in the body, not a state the server or the panel understands. The
only way to remove a thread is a manual per-anchor delete button in the IDE.
Nothing distinguishes "still open" from "addressed" except a human rereading
prose.

Both gaps have the same shape: the session's idea of "what's true" drifts from
reality, and nothing notices. This design closes that gap for the case that
actually caused the pain — local changes to the reviewed branch — and is
explicit about the case it does not close.

## What already exists, and is being reused rather than reinvented

| Thing | Where | Why it matters here |
|---|---|---|
| Diff fetch logic | `fetch_pr_diff()` — `skills/interactive_review/diff.py:173` | The resync path re-fetches with the exact same call `create_session_extra` already makes; no second diff-fetching implementation. |
| Per-anchor thread files, `delete()` | `skills/_shared/web_companion/threads.py:76-135` | Resolve-by-delete needs no new schema — the primitive already exists and is already safe under the per-anchor flock. |
| Session registry | `skills/_shared/web_companion/sessions.py` (`Registry`, `sessions.json`) | `notify_change` finds which live session(s) belong to a given repo+branch without inventing a second registry. |
| Generic event injection | `events.append(events_dir, payload)` — `skills/_shared/web_companion/events.py:25` | Not comment-specific — any dict is a valid event. The orphaned-anchor wake-up is a second producer into a queue the watcher already tails; `watcher.sh` needs no changes. |
| Live thread updates to the IDE | SSE stream — `skills/_shared/web_companion/stream.py` | A resync's changes (migrated anchors, refreshed diff) reach the open panel without a session restart. |
| Text-based anchor re-location | `AnchorResolver.resolve()` — `ide-plugin/src/main/java/com/petros/ireview/AnchorResolver.java:24-51` | The exact algorithm this design ports to Python for server-side migration — not reinvented, ported. |
| `reply_cli.py`'s shape | `skills/_shared/web_companion/reply_cli.py` | Template for `notify_change` and `resolve_cli.py`: thin CLI, no shell-interpolated payloads, routes through files or well-defined args. |

## Decisions taken

1. **Sync trigger: local git hooks, not polling.** A `post-commit` /
   `post-rewrite` / `post-checkout` hook notifies the server the instant a
   local commit, rebase, or checkout happens on the reviewed repo. No
   background timer, no `gh` API calls between hook firings.
   - **Explicitly out of scope:** a remote-side change (someone else pushes to
     the PR, or you push from a different machine) triggers nothing — there is
     no hook on the remote. This is a known, accepted gap, not an oversight.
2. **Resolve is explicit, not inferred.** A thread only closes when Claude or
   the user actively marks it — never auto-resolved because its anchor merely
   drifted or vanished. A vanished anchor is a *question* ("is this finding
   still valid?"), not evidence the finding was fixed.
3. **Resolved means deleted, not archived.** Matches the existing
   `threads.delete()` primitive exactly — no new "resolved" state, no filtered
   view to build. Simpler than an archive model, at the cost of losing the
   finding's history once removed (accepted trade-off).
4. **Anchor migration is automatic on every sync.** The server re-locates each
   thread's anchor using the same text-matching algorithm the IDE panel
   already uses client-side, so an anchor that only moved (common after a
   rebase) is fixed without anyone noticing it needed fixing. This is exactly
   the manual work done twice by hand today, automated.
5. **A genuinely orphaned anchor wakes Claude, not just a UI badge.** Reuses
   the existing `WEBCOMPANION_EVENT` watcher path with a new event shape, so
   Claude reviews the surrounding code and decides (delete / leave open with a
   note / ask) rather than the thread silently sitting mislabeled until a
   human happens to look.

## Components

### 1. `notify_change` (new — `skills/_shared/web_companion/notify_change.py` + thin CLI)

Invoked by a git hook with no arguments. Resolves `$PWD` to a repo root and
current branch (`git rev-parse --show-toplevel`, `git branch --show-current`),
reads `sessions.json` via the existing `Registry`, and POSTs to `/resync` on
every session whose recorded `cwd`+`head` branch matches. Multiple matches all
get notified — cheap, and safer than guessing which one is "the" session.
Failure (server not running, no match) exits 0 silently: a git hook must never
block or fail the git command that triggered it.

### 2. Hook installer (new — `skills/interactive_review/install_hooks.sh`)

Installs `post-commit`, `post-rewrite`, `post-checkout` in the target repo's
`.git/hooks/`. Never overwrites blindly:

- No file at that path → write one that calls `notify_change`.
- A file exists and does **not** already contain our marker comment
  (`# claude-annotate: notify_change`) → append a call to `notify_change` as
  an additional line, preserving everything already there, so a repo's
  existing hook (husky, lefthook, hand-written like montblanc's `pre-push`)
  keeps working.
- A file exists and **does** already contain the marker → no-op. Re-running
  the installer is always safe.

Run once per repo, invoked from `/interactive-review`'s session-create step
the first time a session is opened against that repo (not on every
invocation — installed hooks persist in `.git/hooks`, which is local and
untracked, so this is a one-time-per-clone step, transparently repeated if
missing).

### 3. `/resync` endpoint + `sync.py` (server, new)

`handle_resync` (new method on `interactive_review/server.py`'s `Handlers`,
alongside the existing `handle_thread_delete`/`handle_submit`): takes a `sid`,
calls `sync.resync(dirs)`.

`sync.resync`:

1. Re-fetch the diff via the *existing* `fetch_pr_diff()` — same function,
   same fallback to local `git diff` for a branch-ref session, no duplicate
   logic.
2. On fetch failure: log and return without touching `diff.patch`/`meta.json`.
   A session with a stale-but-known-good snapshot is strictly better than one
   half-overwritten. The next hook firing retries.
3. On success: run every existing thread through `anchor_migrate.locate()`
   against the new diff, **before** the new `diff.patch` is written — so a
   thread is never left pointing at the old file's line numbers against the
   new file's content, even for the instant between writes.
4. Write the new `diff.patch`/`meta.json` (same atomic write helper
   `create_session_extra` already uses).
5. For each thread: EXACT or MOVED → update `anchor` in place if it changed,
   append one `migration_history` entry (`{from, to, kind, ts}`) for
   auditability; STALE → emit an `anchor_orphaned` event (component 4) and
   leave the thread untouched (still shows at its last known line until
   Claude or the user acts).

### 4. `anchor_migrate.py` (server, new)

A direct Python port of `AnchorResolver.resolve()` — same signature shape
(`locate(lines, recorded_line, anchor_text, k=25) -> (kind, line)`), same
three outcomes (`EXACT`, `MOVED`, `STALE`), same ambiguous-match-is-STALE rule.
No new algorithm invented; this exists purely so the server can do what the
IDE panel already does, without requiring the IDE to be open.

**Orphaned-anchor event shape** (via the existing `events.append`):

```json
{
  "event_kind": "anchor_orphaned",
  "sid": "<sid>",
  "anchor": "<old path:side:line>",
  "thread_title": "<existing thread title>",
  "old_anchor_text": "<the line text that could no longer be found>"
}
```

`event_kind` is new — today's comment events carry `type` (`"comment"` /
`"reject"`) with no `event_kind` key, so Mode D branches on
`payload.get("event_kind") == "anchor_orphaned"` first, falling through to
existing comment handling otherwise. No change to `watcher.sh`: it already
just tails new files in `events_dir` and emits the banner; it has never
inspected payload shape.

### 5. `resolve_cli.py` (new, thin — mirrors `reply_cli.py`)

```
PYTHONPATH="$PLUGIN_ROOT" STATE_DIR="$STATE_DIR" \
  python3 -m skills._shared.web_companion.resolve_cli --anchor "<anchor>"
```

Calls `threads.delete()`. Exists so Claude has the same "route through a
documented command, never interpolate" pattern as replying, for the one new
action SKILL.md's Mode D gains: after fixing and verifying a finding, delete
its thread.

## Data flow

**Local change → resync:**
commit/rebase/checkout → hook fires → `notify_change` finds matching
session(s) in `sessions.json` → `POST /resync` → `sync.resync` re-fetches the
diff, migrates every thread's anchor against it, writes the new snapshot →
existing SSE stream pushes the change to any open IDE panel. No session
restart, no lost history.

**Thread resolved:**
Claude verifies a fix (or you click the existing ✕ in the IDE) → `delete()`
removes the thread file → SSE stream reflects the removal. No new state to
maintain — "resolved" was never persisted, only its absence.

**Anchor orphaned:**
`anchor_migrate.locate()` returns `STALE` during a resync → `sync.resync`
writes an `anchor_orphaned` event → existing watcher emits
`WEBCOMPANION_EVENT` → Claude's Mode D reads `event_kind`, looks at what
actually happened to that code (the file, the diff, the commit that touched
it), and either deletes the thread (finding moot), appends a note and leaves
it open (finding still applies, just moved further than the ±25-line search
window), or asks the user when genuinely ambiguous.

## Error handling

| Failure | Behavior |
| --- | --- |
| `gh`/network failure during resync | `diff.patch`/`meta.json` untouched; failure logged; next hook firing retries |
| Hook fires but server isn't running | `notify_change` exits 0 silently — never blocks the git command |
| Hook installer meets a foreign hook | Appends behind a marker comment; never overwrites |
| Hook installer re-run on an already-installed repo | No-op (marker already present) |
| Multiple sessions match one branch | All are resynced |
| Ambiguous anchor match (two identical lines in the search window) | Treated as `STALE` (same rule `AnchorResolver` already applies), routed to the orphaned-anchor path rather than guessed |
| Remote-side PR change | Not detected — named limitation, not silently dropped |

## Testing

- **`anchor_migrate.py`**: a shared JSON fixture
  (`{lines, recorded_line, anchor_text, k, expected_kind, expected_line}`)
  consumed by both the new Python test suite and the existing
  `AnchorResolverTest`, so a behavior change in one implementation that isn't
  mirrored in the other fails CI on both sides. Plus interactive-review-
  specific cases: a thread whose file was renamed, a thread whose file was
  deleted outright.
- **`sync.py`**: mock a failing `gh` call and assert `diff.patch`/`meta.json`
  are byte-identical to before the attempt; assert migration runs against
  every thread before the new diff is committed to disk.
- **Hook installer**: three fixture repos — no existing hook, a foreign hook
  (assert the foreign content survives, in order, after ours), an
  already-installed repo (assert no duplicate lines after a second run).
- **End-to-end**: script a rebase+squash against a fixture repo with a handful
  of threads at known anchors, run the hook, assert every thread's anchor
  lands correctly with zero manual intervention — the direct regression test
  for today's incident.

## Known limitations (accepted, not deferred silently)

- **Remote-side changes are invisible.** No hook exists for "someone else
  pushed" or "I pushed from another machine." A manual `/resync` trigger
  (calling the endpoint directly, or re-invoking `/interactive-review` on the
  same PR) remains the answer for that case; this design does not add a
  polling fallback, per the earlier explicit choice to avoid background cost.
- **The ±25-line search window is inherited, not reconsidered.** A change
  large enough to move an anchor's text more than 25 lines away still reads as
  orphaned rather than moved. Same behavior the IDE panel already has;
  unchanged here.
- **Hook installation is local-repo, not global.** Each clone needs the hooks
  installed once (handled transparently by `/interactive-review`'s
  session-create step) — a fresh clone of the same repo on another machine
  needs its own install, same as any other git hook.
