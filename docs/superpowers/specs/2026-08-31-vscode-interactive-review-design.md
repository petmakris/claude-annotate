# Per-line interactive review for VS Code, via show-diff

Status: design, awaiting approval. Builds on
`2026-08-29-webcompanion-standalone-service-design.md` — this is the first
skill written natively against the `webcompanion` v1 daemon rather than the
legacy per-skill `server.py` model `interactive_review` and `walkthrough`
still use today.

## Why this change

`/interactive-review` gives per-line threaded Q&A on a diff, but only inside
IntelliJ. IntelliJ's own PR-viewing experience is the reason this matters:
reviewing a pull request in IntelliJ is unusable enough that the user's
actual daily diff-reading tool is `show-diff`, a `dashboard` skill that opens
VS Code's native multi-file diff editor. Today that view is read-only —
`show-diff.sh` opens the diff and stops. The goal is to put the same
per-line Q&A `interactive_review` gives IntelliJ onto that VS Code diff, for
local diffs (branch-vs-base, commit-vs-previous, uncommitted worktree), not
just GitHub PRs.

`walkthrough` is explicitly out of scope. It was raised and then withdrawn
during scoping — it stays exactly as it is, IntelliJ-only.

## Repo restructuring

Three repos are involved today, and all three consolidate into
`claude-annotate`, matching how the IntelliJ plugin already lives alongside
the skills it serves rather than in its own repo:

- `dashboard/skills/show-diff/` → `claude-annotate/skills/show_diff/`, added
  to the `claude-ide-review` plugin entry in `marketplace.json` next to
  `interactive_review` and `walkthrough`.
- `env/apps/ide-themes/vscode/` (the whole `petros-makris-vscode` extension —
  markdown theme switching and the diff URI handler both) → a new
  `claude-annotate/vscode-plugin/`, mirroring `ide-plugin/`. Distributed the
  same way: a built artifact from GitHub Releases, not a marketplace skill.
  The theme-switching code moves as-is; it is unrelated to review but the
  user has chosen to treat all of this as personal tooling that belongs in
  one place, the way `ide-plugin/` already does for IntelliJ.

Before deleting the old locations: check `dashboard/.claude-plugin/marketplace.json`
for a `show-diff` entry to remove, and grep both repos for any other script
that shells out to `show-diff.sh` or the extension by path, so nothing is
left pointing at a location that no longer exists.

## Mechanism

### Diff resolution and session creation (show_diff skill)

`show-diff.sh` is unchanged up through opening the native VS Code diff — it
still resolves the checkout/base/head triple via `wp diffable` and reports
it. What's new is a step after: the skill computes the local diff itself
(`git diff <base>...<head>`, or the worktree equivalent for `--worktree`),
parses it with `interactive_review/diff.py`'s existing `parse_unified_diff`
and reuses its `<path>:<side>:<linenum>` anchor scheme unchanged — that
module lives under the skill, not `_shared/web_companion`, so it is
untouched by the webcompanion cutover and needs no porting.

Verification during planning found the diff content itself doesn't need to
go to the daemon at all: `diff.py`'s own docstring says nothing in
production ever consumes its parsed structure — IntelliJ's diff viewer
parses `diff.patch` client-side, and VS Code's diff view already has the
real files open natively. So the session carries one small item,
`__meta__` (`{checkout, base, head}`), not the diff's content:

```
webcompanion push --kind show-diff --cwd <checkout> --items items.json --eval
```

This creates the session and returns `sid`/`url` (via `--eval`'s
`WC_SID=`/`WC_URL=` output, extended during planning to also report
`WC_STATE_DIR=` so the skill can snapshot `diff.patch` into the session's
own workspace — the same consistency guarantee `interactive_review`
already gives a long-lived PR review). The skill then arms a watcher exactly as
`interactive_review` does today, substituting `webcompanion watch --sid
<sid>` for `watcher.sh` — same `WEBCOMPANION_EVENT` / `WEBCOMPANION_FINISHED`
/ `WEBCOMPANION_CANCELLED` / `WEBCOMPANION_DROPPED` banners, same
event-payload shape, same append-only per-anchor thread files. Mode-D
handling (read payload → compose an answer from the diff and surrounding
source → append to the thread) carries over from `interactive_review`'s
`SKILL.md` unchanged in shape, because the daemon's item/thread/event model
is generic — it never had a PR concept to remove. `gh` is never invoked
anywhere in this path.

Worktree diffs (uncommitted work) get no special handling: the right-hand
side is a live file, so a thread anchored to a line can drift if the user
keeps editing after opening the review. `interactive_review` accepts the
same risk for any long session; anchors stay pinned to line numbers, and
nothing re-diffs mid-session.

### The VS Code client (vscode-plugin)

`diff.js` already builds the `resourceUri`/blob-URI pair for each side of
the diff it opens, so it already holds the one piece of state a comment
thread needs: which file, which side, which revision. It gains a new module
registering a `vscode.CommentController` with a `commentingRangeProvider`
scoped to those same URIs — every line of a diff already open becomes
askable, with no second rendering surface and no webview.

That module is a plain HTTP client of the daemon's v1 contract, built fresh
(there's no JS client to hand-port from) against a fixed, already-specified
surface. Verification during planning read `webcompanion/src/webcompanion/
server.py` and `stream.py` directly rather than trusting this spec's first
draft, which named an SSE `document-changed` frame that was never
implemented — the daemon's real change-notification frames are
`item-changed`, `thread-changed`, and `thread-deleted`. Given that, and
given a documented poll endpoint already exists, the client polls instead
of opening an SSE stream — no reconnect/backoff logic needed in an
extension host, and a show-diff session is short-lived enough that a ~2s
poll interval costs nothing a reader would notice:

```
GET  /api/sessions?cwd=<repo>&kind=show-diff   -> find the open session
POST /s/<sid>/api/submit   {anchor, text}       -> ask a question
GET  /s/<sid>/poll                              -> {threads: {anchor: version}, ...}
GET  /s/<sid>/threads/<anchor>                  -> pull the updated thread
```

Every request carries `X-WebCompanion-Contract: 1`; a `426` response is
shown as a visible warning naming which side is old, never a silent dead
poll. This is simpler than porting `ReviewSessionClient.java`'s *current*
implementation, because that Java client is itself due to be rewritten onto
this same v1 contract once the five-skill cutover plan (referenced but not
yet written, per the webcompanion spec's Rollout section) lands — building
VS Code against v1 now means both IDE clients converge on one protocol,
rather than VS Code copying a Java implementation that is about to change
under it.

## Testing

- `webcompanion` itself needed two small, verified-missing pieces before
  `show_diff` could be built on it at all: a CLI command to post a thread
  reply without shell-interpolating arbitrary markdown (nothing did this;
  `update.py` only replaces an item's body), and a way for `push --eval` to
  report the session's `state_dir` (needed to snapshot `diff.patch`, since
  the HTTP response never carries a local filesystem path). Both get tests
  in `webcompanion`'s own suite, run against the real daemon
  (`python3 -m webcompanion serve` in the test process, via its existing
  `wired`/`daemon` fixtures) — not a fake server double, which is already
  the pattern its 350-test suite uses.
- The VS Code client is new test surface for this repo — no existing harness
  covers a VS Code extension here. Needs its own (`@vscode/test-electron` or
  a mocked `vscode` module); the implementation plan pins down which.
- `walkthrough` and the IntelliJ plugin are untouched by any of this.

## Out of scope

- Any change to `walkthrough` — raised, then explicitly withdrawn.
- The five-skill webcompanion cutover itself (interactive_review,
  walkthrough, annotate, deck, dataflow moving off the legacy model) — this
  design only ensures the new skill never touches the legacy model in the
  first place; migrating the other five is separate, already-planned work.
- PR-based review from VS Code. This covers `show-diff`'s local diffs only;
  a GitHub PR diff reviewed from VS Code is a future extension, not this one.
