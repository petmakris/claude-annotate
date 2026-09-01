# The webcompanion cutover — every skill on one daemon, one client

**Date:** 2026-09-01
**Status:** approved design, ready for implementation plans (one per phase)

## The problem

Five skills each ran their own private HTTP server (`server.py` + `ensure_server.sh`),
duplicating the same session registry, thread storage, event queue and SSE loop five times
over — the shared engine at `skills/_shared/web_companion/` exists only because nobody had
cut that duplication down to one process. `annotate` was cut over today onto `webcompanion`,
a real always-on daemon that already does all of this once, for every client. Three skills
remain on the old model: `dataflow`, `walkthrough`, `deck`. A fourth, `interactive-review`,
is also still on it and was mid-design for an unrelated feature (live sync) when this program
started — that feature is folded into its migration rather than built twice.

`TODO.md`'s own "Plan 3" already named this as the next big step and flagged two hazards
worth restating here because they bound everything below: **do not run
`webcompanion migrate --apply` until every skill has actually cut over** (mid-way, it moves a
skill's history out from under code still reading the old location), and **each skill must
push its non-item-shaped artifact again** (`steps.json`, `dataflow.json`, `diff.patch`) since
the daemon's migration tool cannot convert those — they were never items to begin with.

## What already exists, and is being reused rather than reinvented

| Thing | Where | Why it matters here |
|---|---|---|
| The daemon's HTTP contract | `~/projects/webcompanion/docs/contract.md` | Sessions, items, threads, SSE, assets — one contract, versioned (`X-WebCompanion-Contract`), already serving `annotate` in production. |
| Thread route with idempotency + first-write-wins anchor text | `POST /s/{sid}/threads/<anchor>` — `source_event_id`, `anchor_text` (contract.md) | Matches `threads.py`'s semantics today exactly; the daemon becomes the thread store, `threads.py`'s local-file machinery is deleted per skill, not ported. |
| Native thread delete | `POST /s/{sid}/api/threads/delete` | Every skill's resolve/delete-a-thread action becomes one HTTP call. |
| Generic event queue + ack | `POST /s/{sid}/api/submit` (returns `event_id`), `webcompanion ack --sid --event-id` (CLI, no HTTP ack route) | Replaces `events.py` + the local `.ack` file convention. |
| Generic watcher | `webcompanion watch --kind <kind> --sid <sid>` | Replaces `watcher.sh` — confirmed in production use for `annotate` today. |
| SSE vocabulary | `connected`, `item-changed`, `thread-changed`, `thread-deleted`, `session-ended`, `heartbeat` (contract.md) | Already what the IDE plugin and every skill's own JS consumes; no client-side rewrite needed for the base events. |
| The "push at push-time, not serve-time" pattern | `skills/annotate/push.py` (commits `8c18997`, `b0ba2c4`, `8ebf419`) | The proven shape: the client computes/renders, the daemon only stores. Every migration below follows it. |
| IDE dual discovery | `ide-plugin/.../ServerDiscovery.java` | Already daemon-first, legacy-fallback, already shipped (TODO.md's "Plan 2" is done, not pending as that file's date implies). |
| The plugin's zero-pip-dependency rule | claude-annotate's own bootstrap messaging ("needs Python 3.9+ — standard library only, nothing to pip install") | Binding on everything here. `webcompanion` itself is only `pipx`-installed (confirmed: `python3 -c "import webcompanion"` fails on the plain interpreter) — so no skill imports it. A client is written once, in stdlib, inside claude-annotate. |

## Decisions taken

1. **One shared client module, not five hand-rolled ones.** `annotate/push.py` hand-rolled
   its own `_request()` and a single flat `DaemonError` for every failure — reasonable in
   isolation, but the user's explicit goal is shared, scalable interfaces, and four more
   skills are about to need the identical HTTP calls. `skills/_shared/webcompanion_client.py`
   is written once (stdlib `urllib`, the same `X-WebCompanion-Contract`/`X-WebCompanion-Token`
   headers `push.py` already sends), with a typed exception split — `DaemonNotConfigured` /
   `DaemonUnreachable` / `ContractMismatch` — that mirrors **webcompanion's own internal**
   `webcompanion/src/webcompanion/client.py`, not `push.py`'s (`push.py`'s single `DaemonError`
   is the thing being improved on, not prior art to preserve). `annotate/push.py` is
   retrofitted onto the new shared module as part of this program, gaining the finer-grained
   exceptions along the way — not left as a fifth, divergent implementation.
2. **Migration order: smallest and least-coupled first — revised after Phase 1 shipped.**
   Originally ordered by Python-side size alone (`dataflow` → `walkthrough` → `deck` →
   `interactive-review`), which undercounted the real risk: `walkthrough` and
   `interactive-review` both have an IntelliJ-plugin Java client
   (`WalkthroughSessionClient.java`, `ReviewSessionClient.java`) with a genuinely
   sophisticated state machine — retry loops, SSE reconnection, generation counters guarding
   against stale publishes — none of which is visible from the Python side alone, and both of
   which need real rework, not a port: the daemon's `thread-changed` SSE frame carries only
   `{anchor, version, initial?}`, not the full synthesis the old per-skill server inlined
   (discovered reading `WalkthroughSessionClient.toThreadState`, which today consumes the SSE
   frame's data directly), and `/api/submit`'s body has no `type` field for the old
   comment/reject distinction. `deck` has zero IDE-plugin involvement (confirmed by grep — no
   hits anywhere under `ide-plugin/src`), so the revised order is **`dataflow` → `deck` →
   `walkthrough` → `interactive-review`**: the two migrations with no Java surface first, so
   the shared client module and the push-time pattern are proven twice over in the lower-risk
   half before either Java client gets touched, and `interactive-review` — the piece the user
   actually asked for first — comes last of all, once a Java-client migration has already been
   done once (on `walkthrough`) and its pitfalls are known.
3. **Live sync is redesigned against the daemon, not ported from the abandoned plan.** The
   2026-09-01 live-sync plan (`docs/superpowers/plans/2026-09-01-interactive-review-live-sync.md`,
   partially executed — Task 1's `anchor_migrate.py` is complete and 100% reusable, being a
   pure function with no server dependency) assumed a per-skill HTTP server to add a `/resync`
   endpoint to. There is no such thing to extend once interactive-review is a daemon client —
   resync becomes a **CLI command**, invoked directly by the git hook, that does the work
   itself (re-fetch diff, migrate anchors, PATCH the daemon's items and threads) rather than
   asking a server to do it. Sections 6-7 below carry the updated design; Tasks 1-3 of the old
   plan (the algorithm port, the resolve primitive, the git hook installer/notifier shape) are
   reused verbatim or near-verbatim, cited by task number below.
4. **`webcompanion migrate --apply` runs exactly once, after all four skills are cut over and
   verified, with an explicit stop-and-confirm gate before it runs.** Not a design decision so
   much as a restatement of `TODO.md`'s own instruction, made binding here because it is easy
   to lose sight of four phases later: every phase below leaves the daemon's real session
   history untouched until this point.
5. **`skills/_shared/web_companion/` is deleted only after all four skills stop importing it**,
   confirmed by grep, not by assumption — the same "verify before deleting" discipline that
   caught the `anchor_migrate.py` recovery earlier in this program.

## The shared client module

`skills/_shared/webcompanion_client.py` — stdlib-only, no third-party imports. Surface, kept
deliberately small (only what a push script or a resync CLI actually needs; the daemon's own
`webcompanion.client.Client` is broader because it also backs the CLI's own commands):

```python
class DaemonNotConfigured(Exception): ...   # ~/.claude/webcompanion/config.json missing
class DaemonUnreachable(Exception): ...      # config exists, connection/timeout failed
class ContractMismatch(Exception): ...       # 426 from the daemon

def load_config() -> dict: ...                                    # raises DaemonNotConfigured
def create_or_attach(kind, cwd, *, title=None, slug=None,
                      supersede=False) -> dict: ...                # POST /api/sessions
def put_items(sid, items: dict, *, kind, replace=False) -> dict: ...    # PATCH /s/{sid}/items
def get_items(sid, *, kind) -> dict: ...                                # GET /s/{sid}/items
def register_assets(sid, static_root, entry, *, kind) -> None: ...      # POST /s/{sid}/api/assets
def get_threads(sid, *, kind) -> dict: ...                              # GET /s/{sid}/threads
def append_thread(sid, anchor, text, *, kind, role="agent",
                   source_event_id=None, title=None, anchor_text=None) -> dict: ...  # POST /s/{sid}/threads/<anchor>
def delete_thread(sid, anchor, *, kind) -> bool: ...                    # POST /s/{sid}/api/threads/delete
def submit_event(sid, anchor, text, *, kind, images=None) -> str: ...   # POST /s/{sid}/api/submit -> event_id
```

`kind` is a required keyword argument on every function except `create_or_attach` (where it is
positional) and `load_config` — the daemon multiplexes every migrated skill's items, assets and
threads through one process, and `kind` is how a call is scoped to the right one; there is no
default to fall back on. `create_or_attach`'s `supersede` is passed through to the daemon's
`POST /api/sessions` body only on the create path — never on the attach-by-slug path, which does
not create a session and so has nothing to supersede — and it ends every OTHER live session of the
same `(kind, cwd)` pair, not just ones from the same Claude conversation (see `dataflow/SKILL.md`'s
note on why `dataflow`'s own `push.py` does not turn it on).

Every function raises `DaemonNotConfigured`/`DaemonUnreachable`/`ContractMismatch` with the
same remedy text `push.py` already writes (`webcompanion doctor` / `pipx install webcompanion`
/ `webcompanion status`), so five call sites don't each invent their own wording.

## Per-skill migration shape

### `dataflow` (Phase 1)

- Item `__flow__` holds `dataflow.json`'s full body (it is already the complete, self-
  contained document `flow_module.load_flow` reads — no splitting needed, unlike annotate's
  per-block items, because dataflow's client already fetches the whole document in one
  request: `serve_data?query=dataflow.json`).
- Threads: unchanged shape (`node:<id>` anchors), moved to the daemon's native thread routes.
- The `flow-changed` SSE frame (today's `stream.py` `extra` hook) has no daemon equivalent —
  the daemon's `item-changed {anchor: "__flow__", version}` frame carries the same information
  (a new version exists); `dataflow.js` is updated to treat that as the regenerate signal
  instead of a bespoke frame name.
- `push.py` (new, `skills/dataflow/push.py`): built on the shared client, mirrors
  `annotate/push.py`'s `push()` shape — resolve-or-create session, `put_items(sid, {"__flow__": doc})`.

### `walkthrough` (Phase 3)

- Item `__steps__` holds `steps.json`'s full body — same reasoning as dataflow's `__flow__`.
- Threads: unchanged (`step:<id>` anchors), moved to daemon routes.
- `steps-changed` SSE frame: same treatment as dataflow's `flow-changed` — `item-changed` on
  `__steps__` carries the same signal.
- `push.py` (new, `skills/walkthrough/push.py`), following Phase 1/2's proven shape.
- **The IDE-plugin Java client needs real rework, not a port** — this is the phase's real
  weight, unlike its small Python side. `WalkthroughSessionClient.java` today: (a) parses
  `GET /api/sessions?cwd=...` as a raw JSON array with a `state_dir` field per row — the
  daemon's shape and whether an equivalent local path is even meaningful under it both need
  verifying directly against a running daemon, not assumed from `contract.md` prose alone
  (`annotate/push.py` itself defensively handles the response as "array or `{sessions: [...]}`",
  suggesting even that already-shipped code isn't fully certain of the shape); (b) consumes
  `thread-changed`'s SSE payload as the full derived thread info directly (`toThreadState(data)`)
  — the daemon's `thread-changed` frame carries only `{anchor, version, initial?}`, so the
  client must follow up with a fetch and derive `latest_synthesis`/`question` itself, the same
  responsibility shift `wc-threads.js` gives the browser side, needing a Java equivalent (no
  code sharing across languages, but the same derivation logic); (c) sends `postAsk`'s payload
  as `{anchor, type: "comment", text}` — the daemon's `/api/submit` body has no `type` field,
  so whether `"reject"` (the type's other value) is meaningfully used anywhere in walkthrough's
  actual flow needs checking before deciding whether to drop it or JSON-encode it into `text`
  the way `annotate`'s bridge does for its own structured feedback. `cancelSession()`'s route
  (`POST /s/{sid}/api/cancel`) is unchanged — one of the few things here that ports as-is.

### `deck` (Phase 2)

Deck's migration turned out harder than its Python-side size suggested — its content isn't
Claude-generated, it's an arbitrary, potentially large, user-owned `.html` file, and neither of
the daemon's two content primitives fits it directly:

- **The item route is out.** `PUT`/`PATCH` item bodies cap at 2 MB (`contract.md`), and deck's
  own server code notes "a deck with embedded images runs to tens of megabytes" — the entire
  reason today's server streams the file byte-for-byte with an ETag instead of ever holding it
  as JSON.
- **The asset route (`register_assets`/`POST /s/{sid}/api/assets`) needs the file to physically
  live inside the one registered `static_root` directory — copying, not linking.** Checked
  directly against the daemon's source (`server.py:786-796`): the asset-serving path resolves
  symlinks *before* its containment check (`target = (root / relpath).resolve()`, then
  `target.is_relative_to(root)`), specifically to stop a registered root from being used to
  escape to files outside it — so a `static_root` full of symlinks pointing at the plugin's real
  `skills/deck/static/` files and the user's real deck path elsewhere would be rejected as an
  escape attempt, correctly. `static_root` itself has no path restriction (any resolvable
  directory is accepted, per `server.py:748-763`), but it must be one real directory containing
  real files, not a directory of links into others.
- **The resolution: `push.py` copies, into one directory it controls.** Assets have no 2 MB cap
  — only items do — so the fix is for `skills/deck/push.py` to maintain a small directory (under
  the session's own workspace, or a scratch dir it owns) holding a copy of the plugin's
  `deck.js`/`deck.css`/`entry.js` *and* a fresh copy of the user's current deck `.html`,
  re-copying the deck file on every push (including after Claude edits it), and registering
  that combined directory as `static_root`. No `webcompanion` change needed — this stays a
  `claude-annotate`-side migration like every other phase. The cost is a file copy per push,
  cheap for the vast majority of decks and not prohibitive even at "tens of megabytes."
- **First take on this got it wrong and is worth naming so it isn't repeated:** an earlier draft
  of this section concluded the size mismatch might require changing `webcompanion` itself. That
  was based on the item-size limit alone, before actually reading the daemon's asset-serving
  source — the asset route was never size-capped, only assumed (wrongly) to require the file to
  already live inside a plugin-owned directory. Reading the actual containment-check code before
  concluding is what turned this from "blocked, escalate upstream" into "solvable entirely on
  this side." Worth remembering for Phase 3/4's own harder-looking corners too.

What is still expected to hold:
- Item `__model__` holds `parse_deck`'s output (computed at push time by `push.py`, the same
  push-time-computation pattern as annotate's rendering — the daemon never parses HTML).
- The `deck_comment` event rides the generic `/api/submit` pattern. **Correction from the
  original draft of this section:** deck's `handle_submit` today does **not** append a thread
  message at all — it only queues an event (`type: deck_comment`, no `threads_module` usage
  anywhere in `server.py`). Deck has no comment-history model today. Adopting the daemon's
  thread system for these comments (anchored at something like `slide:<n>:<path>:<ord>`) would
  give deck comment history for free — a genuine improvement, not just a port, and the same
  "documented extension point, currently unused" opportunity the `annotate` migration's own
  handover already named as a possible future bridge fix for annotate's structured feedback.
- `deck.js` already targets a `window.WebCompanion.api.submit(...)`/`.writable` global — the
  *name* already matches the daemon's own runtime, which is a good sign, but the *shape* it
  expects from polling (`onPoll(poll)` reading `poll.busy`/`poll.queued`/`poll.blocks.deck`) has
  no daemon equivalent: `/poll` and the SSE frames carry no `busy`/`queued` concept at all. This
  needs the same client-side reconstruction `annotate/static/compat.js` already built for its
  own busy-state ("lock on submit, unlock when an item actually changes").
- `push.py` (new, `skills/deck/push.py`) — its exact shape depends on how the size question above
  resolves.

### `interactive-review` (Phase 4)

- Items `__diff__` (the raw patch text) and `__meta__` (`pr_ref`/`head`/`head_oid`/etc.)
  replace `diff.patch`/`meta.json` as local files.
- Threads: unchanged anchor shape (`path:side:line[-line]`), moved to daemon routes —
  `threads.py`'s local file store, its locking, and `resolve_cli.py`'s local `delete()` call
  are all replaced by `webcompanion_client.delete_thread`/`append_thread`.
- Session creation (`create_session_extra`'s PR-fetch step) is unchanged in substance — it
  still calls `diff_module.fetch_pr_diff` — only the *write* target changes, from
  `write_text_atomic(state_dir / "diff.patch", ...)` to `put_items(sid, {"__diff__": ..., "__meta__": ...})`.
- **Live sync, redesigned:** a `sync.py` **CLI** (not an HTTP endpoint — there is no
  per-skill server left to add one to) does the whole resync: re-fetch the diff via
  `fetch_pr_diff`, `get_threads(sid)` from the daemon, run `anchor_migrate.locate()` (Task 1 of
  the old plan, already implemented, unchanged) against the real current file for each thread,
  and for anything that moved: read the old thread's messages via `get_threads`, replay them
  onto the new anchor via `append_thread` (preserving each message's original
  `source_event_id` for idempotency, and the first message's `anchor_text`/`title`), then
  `delete_thread` the old anchor. A thread that resolves `STALE` triggers the same
  orphaned-anchor event this design already specified (`submit_event` with a payload tagged
  `event_kind: "anchor_orphaned"`, since `/api/submit`'s body is `{anchor, text, images?}` and
  accepts arbitrary encoding in `text` — matches annotate's own bridge for structured feedback,
  which JSON-encodes structure into `text` because "the daemon is not supposed to understand
  any client's vocabulary").
- `notify_change` (Task 6 of the old plan) is unchanged in shape — it still finds the matching
  local session(s) and invokes the resync — except it now calls the `sync.py` CLI directly
  (a subprocess, or an in-process function call if `notify_change` and `sync.py` are merged
  into one module) instead of POSTing to a `/resync` HTTP route.
- `install_hooks.sh`/`notify.sh` (Task 7 of the old plan) are unchanged verbatim — they know
  nothing about the daemon at all, only about invoking a Python entry point.
- Claude's Mode D reply flow changes: instead of writing `.reply.md`/`.reply.meta.json` and
  running `reply_cli.py --ack`, Claude calls `webcompanion_client.append_thread(...)` (a new
  thin `reply_cli.py`-equivalent CLI, or SKILL.md documents the direct module call) then shells
  out to `webcompanion ack --sid <sid> --event-id <event_id>`.
- No IDE-side fallback exists once the legacy server is deleted — `ReviewSessionClient.java`'s
  existing "try daemon, fall back to legacy, stick to whichever answered" logic simply never
  takes the legacy branch any more (the legacy `server.json` stops being written), which is a
  no-op change on the Java side, not a rewrite.

## Sequencing and the final gate

Four independent phases (dataflow, walkthrough, deck, interactive-review), each: its own
implementation plan, its own worktree/branch off `origin/main`, its own subagent-driven
execution with the review discipline already established in this program (fresh implementer
per task, task review, fix loop, final whole-phase review). A phase's branch merges to `main`
only once its own final review is clean — phases do not block each other except through the
shared client module (Phase 1 builds it; Phases 2-4 consume it, fixing forward if Phase 1's
interface needs to grow rather than duplicating).

After all four phases are merged and each skill's `SKILL.md` documents the daemon-only flow:

1. Grep-confirm nothing under `skills/` still imports `skills._shared.web_companion` except
   test files being deleted in the same change.
2. Delete `skills/_shared/web_companion/` and its tests.
3. **Stop here and get explicit confirmation before the next two steps** — they touch live,
   shared, currently-in-use production data (38+ real sessions were serving when this program
   started) and are the one part of this program that fits this project's own "ask before an
   irreversible, shared-system-affecting action" rule regardless of how much autonomy has been
   granted for the implementation work itself:
   - Stop the daemon (`webcompanion migrate --apply` refuses while `/health` answers).
   - Run `webcompanion migrate --apply`, verify the reported counts against the rehearsal
     numbers already on record (`TODO.md`: "30 sessions → 15 migrated, 14 needs-repush, 1
     read-only, 96 comment threads preserved" — the real number will differ since more sessions
     exist now, but the *shape* of the report should match), restart the daemon, and have each
     migrated skill re-push its `needs_repush` sessions' non-item content.
4. Drop the IDE plugin's legacy discovery path (`TODO.md`'s "Plan 4") once the above has run
   and settled — a follow-up, not part of this program's critical path.

## Testing strategy

- `webcompanion_client.py`: unit tests per function against a fake HTTP server (stdlib
  `http.server` fixture, matching the pattern `skills/_shared/web_companion/tests/` already
  uses for its own server) — no real daemon required for the test suite.
- Each skill's `push.py`: unit tests with the client mocked. **Verified during this design
  pass: `skills/annotate/push.py` itself has no dedicated unit test file today** — the only
  hits for "push" in `skills/annotate/tests/` are assertions about `references/pushing.md`'s
  *prose* (`test_skill_structure.py:90`, `test_smoke_read_only.py:100-107`), not about
  `push.py`'s HTTP logic. There is no prior art to mirror; this program adds the first real
  one, for `webcompanion_client.py` and every skill's `push.py` alike — a genuine gap worth
  closing, not a pattern to copy.
- Each skill's server-side code that is *deleted* (old `server.py`, `ensure_server.sh`) takes
  its tests with it, exactly as annotate's `8ebf419` did — coverage is repointed at what
  survives (the push script, the parsing/validation logic), never left dangling.
- Cross-skill: one shared integration test (new) that boots the real daemon against a fixture
  workspace root and runs each skill's `push.py` against it end-to-end, catching a contract
  drift no per-skill mock would.
- `anchor_migrate.py` (Phase 4): already fully tested (old plan's Task 1); no new test debt.

## Known limitations (accepted, not deferred silently)

- **PyPI publication is not part of this program.** It needs credentials only the user holds
  (`TODO.md` step 1). Nothing here blocks on it — the daemon is already running via `pipx`
  from a local build, which is sufficient for every phase's development and testing.
- **The final `migrate --apply` cutover is explicitly gated**, per Decision 4 above — every
  phase's own implementation and testing proceeds without it.
- **Deck gains SSE it didn't have before** — a genuine behavior change (poll-only to
  push-driven), not a like-for-like port. Called out here so it isn't mistaken for a smaller
  change than it is; `deck.js`'s poll fallback keeps the old behavior available if SSE
  ever regresses.
