# Webcompanion Cutover — Phase 4 (ask-diff) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the skill formerly called `interactive_review` — renamed to `ask_diff` on
2026-08-28, command renamed to `/ask-diff` on 2026-09-02, but its wire identifier
(`SKILL`/`kind`) staying `interactive-review` by the rename's own explicit decision (see
Global Constraints) — onto the webcompanion daemon, delete its private server, and build the
live-sync mechanism that is this whole 4-phase program's original motivation: a PR's diff and
thread anchors currently snapshot once at session-open and never refresh, so a push, rebase, or
squash on the reviewed branch silently strands every open thread.

**This is the last phase and the biggest.** Phases 1-3 (dataflow, deck, walkthrough) were ports
of Claude-authored, session-local documents onto new wire shapes. This phase has that same port
(diff snapshot, threads, events) PLUS a genuinely new capability with no Phase 1-3 precedent:
external state (the PR) can drift after the session opens, and nothing today notices.

**Architecture:**
- `skills/ask_diff/push.py` (new) creates/attaches the daemon session (`kind="interactive-review"`
  — see Global Constraints, this is not `"ask_diff"`), fetches the PR diff exactly as
  `create_session_extra` does today, and pushes it as two items: `__diff__` (raw patch text) and
  `__meta__` (`pr_ref`/`title`/`head`/`base`/`author`/`url`/`head_oid`/`fetched_at`) — replacing
  `diff.patch`/`meta.json` as local files. No `register_assets` call — this skill has no browser
  page, same as walkthrough.
- `skills/ask_diff/sync.py` (new) is the live-sync engine: given a `sid`, re-fetches the diff,
  runs every existing thread's anchor through `anchor_migrate.locate()` (already implemented,
  already merged to `main`, storage-agnostic — reused verbatim, zero changes), migrates each
  thread that moved by replaying its messages onto the new anchor and deleting the old one,
  fires an `anchor_orphaned` event for anything that didn't, and re-pushes `__diff__`/`__meta__`
  so the daemon's own item-versioning + SSE stream notify any open IDE panel — no bespoke
  `/resync` HTTP endpoint exists to add it to any more, so this is a **CLI**, invoked by a git
  hook exactly as the pre-daemon design specified, just calling a Python entry point instead of
  POSTing to a server.
- `skills/ask_diff/install_hooks.sh` and the git-hook trigger mechanism are unchanged in shape
  from the already-approved 2026-09-01 design (see spec pointer below) — they know nothing about
  HTTP or the daemon, only about invoking a Python entry point, so the daemon migration does not
  touch them beyond what they invoke.
- `ide-plugin/.../ReviewSessionClient.java` is reworked onto the daemon's real routes — **this is
  the single largest and highest-risk task in the whole 4-phase program.** The master spec
  (`docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md`, `### interactive-review
  (Phase 4)` section) claims this is "a no-op change... not a rewrite" because
  `ServerDiscovery`'s existing daemon-first/legacy-fallback logic already exists in the file.
  **This claim is wrong, verified directly against the current code during this plan's own
  research — see Global Constraints for the evidence.** `ServerDiscovery` only resolves which
  *base URL* to use; every route this client actually calls once it has that URL
  (`/threads.json`, `/poll` with no `?kind=`, `/stream` with no `?kind=`, no `/items` route at
  all) is the OLD private server's wire shape, none of which exist on the daemon. The daemon
  fallback logic today only ever finds an empty session list (because nothing has ever created a
  session there) and falls straight back to the legacy server, which is why this has never been
  exercised. Once `push.py` starts creating real sessions on the daemon, every one of those
  routes needs the same class of rework Phase 3's `WalkthroughSessionClient` got — kind
  filtering, max-sid selection, bulk-thread-derive-on-`thread-changed`, submit-payload rework,
  poll rework — on a *larger* file (885 lines vs. ~700) with a real, load-bearing `type` field
  (`"comment"` used, `"reject"` mentioned in `SKILL.md` but never actually constructed anywhere
  in the Java tree today — confirmed by grep during this plan's research, so it is dead exactly
  like walkthrough's was, not a live distinction to preserve).

**Tech Stack:** Python 3.9+ stdlib only (Tasks 1-2). Java 17, existing `HttpClient`/Gson stack,
no new dependency (Task 3).

**Spec:** Two documents govern this phase, and they disagree in one place (see above and Global
Constraints) — this plan is the tiebreaker, correcting the master spec's Java-side claim with
live evidence:
- `docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md`'s `### interactive-review
  (Phase 4)` section — the daemon-migration shape (items, threads, the redesigned `sync.py` CLI,
  the `submit_event`/JSON-envelope bridge for orphaned-anchor events). Written before the
  rename; every `interactive_review`/`interactive-review` name in it now means `ask_diff`'s
  *module path*, but see Global Constraints on the *wire identifier* staying
  `interactive-review`.
- `docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md` — the original,
  already-approved live-sync design (git-hook trigger, explicit-resolve-only, resolved-means-
  deleted, automatic anchor migration, orphaned-anchor-wakes-Claude). Its five **decisions**
  (section "Decisions taken") are unchanged and still the authority for *what* live-sync does.
  Its **Components** section (1-5) describes *how*, against the old private-server
  architecture (a bespoke `/resync` HTTP endpoint, `notify_change` POSTing to it) — that
  mechanism is superseded by the master spec's later, daemon-era redesign (`sync.py` as a CLI).
  Read both; the master spec's Phase 4 section is the authority on mechanism, this design doc is
  the authority on behavior/decisions.

Also read, as direct prior art:
- `docs/superpowers/plans/2026-09-02-webcompanion-cutover-phase3-walkthrough.md` (merged,
  `main`) — the closest precedent for a Java-client-rework-heavy phase. Its final review found
  defects specific to *stateful client lifecycles* (a version-tracking field never reset on
  session switch; a race between an HTTP round-trip and a concurrent session switch) — budget
  Task 3's final review for the same CLASS of risk. `ReviewSessionClient` is a similarly
  stateful, long-lived object, though its state shape differs (per-line-comment threads keyed by
  `path:side:line`, not per-step tour state).
- `ide-plugin/src/main/java/com/petros/ireview/WebCompanionHttp.java` (new from walkthrough's
  final-review fix round) — the shared contract-header helper. Reuse it; do not reinvent.
- `skills/_shared/webcompanion_client.py` (Phase 1) — the shared Python client. Reuse
  `create_or_attach`, `put_items`, `get_items`, `get_threads`, `append_thread`, `delete_thread`,
  `submit_event` exactly as they exist today; this phase needs no shared-client changes (see
  Global Constraints on the one timestamp caveat this implies).
- `skills/_shared/static/wc-threads.js` — the canonical thread-derivation logic every phase's
  Java/JS port has mirrored (last-agent-message = synthesis, last-user-message = question, no
  agent message yet = omit the anchor). This skill's threads use `role: "claude"`/`role: "user"`
  today (not `"agent"`/`"user"` like every other migrated skill) — see Global Constraints.
- `skills/_shared/web_companion/anchor_migrate.py` (already on `main`, already tested against a
  shared Java/Python fixture in `ide-plugin/src/test/resources/anchor_migration_fixtures.json`)
  — a direct port of `AnchorResolver.resolve()`, storage-agnostic. **Reused verbatim. No task in
  this plan modifies it.**

## Global Constraints

- No new third-party Python dependency. No new third-party Java dependency.
- **The daemon `kind` for this skill is the literal string `"interactive-review"`, NOT
  `"ask_diff"` or `"ask-diff"`.** `skills/ask_diff/SKILL.md`'s own header note (added at the
  rename) says this explicitly and gives the reason: "the separately-installed webcompanion
  daemon and the shipped plugin `.zip` both key off that string. Changing it would need all
  three released together; changing the command needed nothing." Every `create_or_attach`,
  `put_items`, `get_items`, `get_threads`, `append_thread`, `delete_thread`, `submit_event` call
  in this phase's Python code, and every `?kind=` query param in the Java rework, uses
  `interactive-review`. `~/.claude/interactive-review/` (the legacy server.json's directory) and
  the watcher's `skill=interactive-review` field are unaffected either way — daemon `kind` and
  the legacy per-skill directory name happen to already match, which is convenient, not a
  coincidence to rely on for anything beyond this one string.
- **`ReviewSessionClient.java` does NOT already talk to the daemon in any partial way — correcting
  the master spec.** Verified directly during this plan's research: every route it calls
  (`/threads.json`, `/poll`, `/stream`, `/api/sessions?cwd=` with no `kind` filter, `/api/submit`,
  `/api/cancel`, `/api/threads/delete`) is the legacy private server's exact shape. `/threads.json`
  in particular does not exist on the daemon at all (`~/projects/webcompanion/src/webcompanion/
  server.py`'s route regex is `^/s/([^/]+)/threads$`, no `.json` suffix, different response
  shape — a bulk map keyed by anchor with `{anchor, version, messages, title}` per entry, not
  `{latest_synthesis, version, updated_at, anchor_text, title, question}` per entry).
  `ServerDiscovery`'s daemon-first check has never actually mattered in practice because nothing
  has ever created an `interactive-review`-kind session on the daemon — `fetchNewestSession()`
  always gets an empty list back from the daemon and falls through to
  `fetchFromLegacyServer()`, which rebinds `baseUrl` for every subsequent call. Once Task 1's
  `push.py` starts creating real daemon sessions, this fallback stops firing and every one of
  those seven routes needs the daemon-shaped rework Task 3 specifies. Treat this exactly like
  Phase 3's Java task in scope and risk — it is not smaller because `ServerDiscovery` exists.
- **The `type` field (`"comment"`/`"reject"`) is dead in the Java client, confirmed by grep.**
  `ReviewSessionClient.java`'s submit payload always sends the literal `"comment"`; no code path
  anywhere in `ide-plugin/src/main/java` constructs `"reject"`. `SKILL.md`'s own text ("or
  rarely `reject` if the user disagrees with a prior reply") describes a distinction the current
  IDE plugin has never actually sent. **Server-side, `handle_submit` DOES accept and forward
  `"reject"`** (`comment_type not in ("comment", "reject")` is a real validation branch) — but
  with nothing upstream ever sending it, this is dead code on both sides of the wire today, not
  a live feature this migration must preserve behaviorally. Drop `type` from the daemon-era
  submit payload entirely (the daemon's real `/api/submit` body is `{anchor, text, images?}`,
  no `type` field, matching every other migrated skill) — do not build a JSON-envelope bridge
  for it; there is nothing structured left to carry once `type` is gone, the same conclusion
  walkthrough's Task 2 Step 3 reached for its own dead `type` field.
- **This skill's threads use `role: "claude"`, not `role: "agent"`.** Every other migrated
  skill's server-side code (and the daemon's own `_append_to_thread` default,
  `msg.setdefault("role", "agent")`) uses `"agent"`. `ask_diff/server.py`'s `threads_bulk()`
  filters on `role == "claude"` explicitly. Task 2 must decide, and document its choice
  explicitly in its report: either (a) Claude's reply path passes `role="claude"` on every
  `append_thread` call (the shared client's `role` parameter defaults to `"agent"` but accepts
  any string), preserving the historical role name across the migration, or (b) switch to the
  daemon's own default (`"agent"`), matching every other skill, and update `SKILL.md`'s Mode D
  to say so. Either is defensible; **do not silently pick one without a stated reason**, since
  it affects every future thread-derivation read (Task 2's Java-side `deriveThreads`-equivalent
  must filter on whichever role Task 1 actually writes).
- **`anchor_text` propagation loses its current path and needs a new one.** Today,
  `handle_submit` reads `anchor_text` directly off the *user's* submit payload and calls
  `threads_module.set_anchor_text_if_absent` server-side, independent of Claude's reply. The
  daemon's `/api/submit` has no such side effect — it only queues an event. Under the daemon,
  `set_anchor_text_if_absent`'s daemon-side equivalent is only reachable via `append_thread`'s
  own `anchor_text` parameter, which fires when *Claude* replies, not when the *user* asks.

  **Settled during this plan's own pre-dispatch review (not an open question for Task 3 —
  confirmed directly against the daemon's source):** `server.py`'s `_submit` handler
  (`~/projects/webcompanion/src/webcompanion/server.py:838-856`) reconstructs the stored event as
  exactly `events.append(dirs["events_dir"], {"anchor": anchor, "text": text, "images":
  image_refs})` — it reads `anchor`/`text`/`images` off the client's payload and discards every
  other key. A bare extra `anchor_text` field in the submit body is silently dropped, never
  reaches the stored event, and Claude's watcher would never see it. **The only viable mechanism
  is the JSON-envelope-in-`text` bridge** — Task 3 (Java) must send `anchor_text` bridged into
  `text` as a small JSON envelope (e.g. `{"anchor_text": "...", "comment": "..."}`, or whatever
  shape Task 3 and Task 4 agree on), so that Task 1's `push.py`/reply-path code can
  `json.loads()` it back out and pass `anchor_text` through to the *first* `append_thread` call
  on a new anchor, matching first-write-wins semantics (`set_anchor_text_if_absent`) the daemon's
  `append_thread` route already implements natively. Do not spend implementation time
  re-investigating whether a bare extra field survives — it does not.
- **Anchor migration replays messages without preserving original timestamps.** The shared
  client's `append_thread(sid, anchor, text, *, kind, role="agent", source_event_id=None,
  title=None, anchor_text=None)` has no `ts` parameter — a replayed message during anchor
  migration gets a new server-assigned timestamp, not its original one. This is a real, accepted
  behavior change from the pre-daemon design (which never mutated timestamps since it edited
  the anchor key in place, not the message content) — **do not extend the shared client to add a
  `ts` passthrough for this**; it is a small, contained loss (only visibly wrong if a user
  compares a migrated thread's displayed timestamps against, e.g., its git blame — no functional
  breakage) and extending a shared module for one caller's one edge case is disproportionate.
  Preserve `source_event_id` (idempotency — replaying a migration twice must not duplicate
  messages) and the first message's `anchor_text`/`title` on replay, per the master spec's own
  text; accept the timestamp loss and say so plainly in `sync.py`'s own module docstring.
- **The orphaned-anchor event reuses `/api/submit` with a JSON-encoded envelope in `text`** — the
  same bridge pattern `deck.js`'s submit envelope and `annotate/static/compat.js` both already
  use for structured payloads, since the daemon's event body is flat `{anchor, text, images?}`
  with no room for a custom `event_kind` field. `sync.py` calls
  `webcompanion_client.submit_event(sid, anchor, json.dumps({"event_kind": "anchor_orphaned",
  "thread_title": ..., "old_anchor_text": ...}), kind="interactive-review")`. `SKILL.md`'s Mode D
  must `json.loads()` the event payload's `text` field and check for `event_kind ==
  "anchor_orphaned"` *before* falling through to normal comment handling — mirroring exactly how
  `deck`'s own event-handling section already documents unwrapping its JSON envelope.
- **Git hooks stay entirely daemon-agnostic.** `install_hooks.sh` and the `post-commit`/
  `post-rewrite`/`post-checkout` hook bodies it installs are unchanged from the original
  2026-09-01 design in every respect that matters to this phase — they invoke a Python entry
  point with no arguments and know nothing about HTTP, the daemon, or `kind`. Only the entry
  point's own internals (Task 2's `sync.py`/`notify_change` merge) change.
- Never delete a file's test coverage without repointing it at whatever survived (Phase 1-3's
  own precedent) — applies to `skills/ask_diff/tests/test_server.py` (Task 4) and
  `ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java` (Task 3), which pin
  the *old* wire shapes today and must be rewritten to pin the *real* ones, not deleted.
- `FakeReviewServer.java` (shared with `WalkthroughSessionClientTest`, already extended once by
  Phase 3 with a bulk `/threads` route) needs the SAME route this phase's Task 3 needs — confirm
  it already exists and is reusable before adding a second, subtly-different one.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `skills/ask_diff/push.py` (new) | Creates/attaches the daemon session (`kind="interactive-review"`), fetches the PR diff via the existing `diff.fetch_pr_diff`, pushes `__diff__`/`__meta__`. No asset registration. |
| `skills/ask_diff/tests/test_push.py` (new) | Tests for `push.py`, mirroring Phase 1-3's `test_push.py` pattern. |
| `skills/ask_diff/sync.py` (new) | The live-sync engine: re-fetch, migrate every thread's anchor via `anchor_migrate.locate()`, replay-and-delete for moved anchors, `submit_event` for orphaned ones, re-push `__diff__`/`__meta__`. Also finds which session(s) match the firing repo/branch (`notify_change`'s job, merged into this module or kept as a thin wrapper around it — implementer's choice, state which in the report). |
| `skills/ask_diff/tests/test_sync.py` (new) | Tests for `sync.py`: a mocked failing diff fetch leaves items untouched; migration runs before the new diff is pushed; an orphaned anchor fires the right event shape; idempotent re-run (a migration that already happened does not duplicate messages). |
| `skills/ask_diff/install_hooks.sh` (new, ported near-verbatim from the abandoned 2026-09-01 plan's own design — no daemon awareness needed) | Installs `post-commit`/`post-rewrite`/`post-checkout` hooks that invoke `sync.py`'s entry point, marker-comment-guarded against overwriting a foreign hook. |
| `skills/ask_diff/tests/test_install_hooks.py` (new) | Three fixture repos: no existing hook, a foreign hook (assert survival), already-installed (assert no duplicate on re-run) — per the original design's own testing section. |
| `skills/_shared/web_companion/anchor_migrate.py` (unchanged, already on `main`) | Reused verbatim — no task touches it. |
| `skills/ask_diff/server.py`, `ensure_server.sh`, `tests/test_server.py` (delete) | Superseded entirely by the daemon + the new CLIs. |
| `skills/ask_diff/SKILL.md` (modify) | Documents the daemon-based flow, the corrected event-payload shape (no `type`, an `event_kind` branch for orphaned anchors), hook installation as a one-time-per-clone session-create step, the resolve action (`delete_thread` replacing `resolve_cli.py`). |
| `skills/ask_diff/README.md` (modify, if it describes the old server — check first) | Same correction class as Phase 1-3. |
| `ide-plugin/src/main/java/com/petros/ireview/ReviewSessionClient.java` (modify) | The real weight of this phase — reworked per Global Constraints: session discovery (the `&kind=` query param — client-side filtering/max-sid already existed), a one-time `__meta__` fetch for `prRef` only (NOT a diff-content rewrite — see Task 3 Step 2's correction: the actual diff view is rendered by `GhPrDiffOpener` via JetBrains' own GitHub plugin, entirely separate from the daemon), thread bulk-fetch-and-derive (replacing direct SSE-frame parsing), submit payload (drop `type`, resolve the `anchor_text` gap), poll rework, contract header via the existing `WebCompanionHttp` helper on every new/changed route. |
| `ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java` (modify) | Every fixture encoding the *old* wire shapes rewritten to encode the real ones — mirroring Phase 3's Task 2 Step 7 in shape and rigor. |
| `ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java` (modify, if needed) | Confirm Phase 3's added bulk `/threads` route is directly reusable here (same daemon shape) before adding anything new. |

---

### Task 1: `push.py` and the shared-client-only Python plumbing

**Files:**
- Create: `skills/ask_diff/push.py`
- Create: `skills/ask_diff/tests/test_push.py`

**Interfaces:**
- Consumes: `skills._shared.webcompanion_client` (`create_or_attach`, `put_items`) — unchanged,
  no shared-client edits in this phase (see Global Constraints on the `ts`-passthrough decision:
  do not add one). `skills.ask_diff.diff.fetch_pr_diff` (existing, unchanged).
- Produces: `push(pr_ref: str, cwd: str, claude_session_id: str, *, slug: str | None = None) ->
  dict`, `main(argv=None) -> int` (`python3 -m skills.ask_diff.push --pr <ref> --cwd <repo root>
  --claude-session-id <id> [--slug ...]`). Task 4's `SKILL.md` rewrite references this exact CLI
  shape.

- [ ] **Step 1: Resolve the supersede-scope gap — read this before writing any code**

  The current server sets `supersede_by_claude_session = True` as a class attribute: creating a
  new review session cancels *every* prior review session this same Claude conversation started,
  **regardless of cwd** (explicitly to prevent forgotten-cleanup watcher leaks — this skill's own
  server comment says so). The shared client's `create_or_attach(kind, cwd, *, title=None,
  slug=None, supersede=False)` has **no `claude_session_id`-scoped supersede at all** — its
  `supersede` flag is scoped to `(kind, cwd)` only (confirmed by reading
  `~/projects/webcompanion/src/webcompanion/server.py`'s `_supersede_siblings`, which takes
  `(kind, cwd, sid)`, nothing about a Claude session). This is the same shape of gap Phase 3
  found for `walkthrough`'s own supersede semantics, but the STAKES are different here: dropping
  cross-cwd auto-cancel for `ask_diff` specifically **reopens the watcher-leak problem this
  server-side flag was added to prevent**, and this whole program has a live, tracked initiative
  about exactly that leak (session-leak investigation, noted in Phase 2's ledger, not yet
  scheduled). Decide and document the tradeoff explicitly in this task's report:
  - **Recommended:** accept `supersede=True` scoped to `(kind, cwd)` — same mechanism as
    walkthrough, same accepted limitation (a Claude conversation reviewing PRs in two different
    repos concurrently no longer auto-cancels the first when the second opens). This is
    consistent with the rest of the program and requires zero daemon changes. Name this
    explicitly as *reopening* a leak-prevention guarantee the original author built specifically
    against, not merely "the same limitation as walkthrough" — walkthrough's tours are rarer and
    shorter-lived than PR reviews are, so the actual leak risk this reopens is real, not
    theoretical, and belongs in this phase's Known Limitations section, cross-referenced to the
    session-leak initiative.
  - **Alternative — confirmed NOT AVAILABLE without a daemon change, do not attempt it.**
    Verified independently during this plan's own pre-dispatch review: `server.py`'s `_row()`
    (`~/projects/webcompanion/src/webcompanion/server.py:372-381`) returns exactly `{sid, slug,
    kind, cwd, title, url}` for every session row, with no `claude_session_id` field and nothing
    else exposing one — `create_or_attach`'s request body is never echoed back into anything
    Claude-side code can read later. Cross-cwd tracking by Claude session is therefore not
    possible today without modifying the separate `webcompanion` package, which is out of scope
    for this branch (matching this whole program's standing rule against touching the daemon
    itself). **The recommended path is the only one available — implement it, do not spend time
    re-verifying this.**

  Implement the recommended `(kind, cwd)`-scoped `supersede=True` and state the ruling plainly in
  the report, citing this plan's own confirmation above rather than re-deriving it.

- [ ] **Step 2: Write `push.py`**

  Follow `skills/walkthrough/push.py`'s shape (read it in full — closest template: one
  session, no assets) but pushing TWO items instead of one. Reuse
  `skills.ask_diff.diff.fetch_pr_diff(pr_ref, cwd)` exactly as `create_session_extra` calls it
  today (same function, same signature, same error handling for a `gh` failure and the
  1MB/5MB size thresholds — port those checks into `push.py` verbatim, they are pure validation
  logic with no server dependency). `KIND = "interactive-review"` (see Global Constraints — not
  `"ask_diff"`). Push `{"__diff__": diff_text, "__meta__": {...}}` via one `put_items(sid,
  {...}, kind=KIND, replace=True)` call, mirroring the existing `meta.json` field set exactly
  (`pr_ref`, `title`, `head`, `base`, `author`, `url`, `head_oid`, `fetched_at`).

- [ ] **Step 3: Write `test_push.py`**

  Mirror `skills/walkthrough/tests/test_push.py`'s structure. At minimum: validation/size-limit
  failures surface cleanly and never call the daemon client; the supersede decision from Step 1
  is actually exercised (assert whichever mechanism was chosen is actually invoked); both items
  are pushed in one `put_items` call with the right `kind`; `register_assets` is never called.

- [ ] **Step 4: Run the test suite for this task**

  Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff && python3 -m pytest skills/ask_diff skills/_shared -q`
  Expected: all new tests pass; no regressions in `_shared`.

- [ ] **Step 5: Commit**

  ```bash
  cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff
  git add skills/ask_diff/push.py skills/ask_diff/tests/test_push.py
  git commit -m "Add ask_diff's push.py: PR diff onto the webcompanion daemon"
  ```

---

### Task 2: `sync.py` — the live-sync engine (the phase's genuinely new capability)

**Files:**
- Create: `skills/ask_diff/sync.py`
- Create: `skills/ask_diff/tests/test_sync.py`
- Create: `skills/ask_diff/install_hooks.sh`
- Create: `skills/ask_diff/tests/test_install_hooks.py`

**Interfaces:**
- Consumes: `skills._shared.webcompanion_client` (`get_items`, `put_items`, `get_threads`,
  `append_thread`, `delete_thread`, `submit_event` — all existing, unchanged),
  `skills._shared.web_companion.anchor_migrate.locate` (existing, unchanged, storage-agnostic —
  read its real signature from the file, do not guess it), `skills.ask_diff.diff.fetch_pr_diff`
  (existing, unchanged), `skills.ask_diff.push`'s `KIND` constant (import it, do not redefine).
- Produces: `resync(sid: str, cwd: str) -> dict` (a summary: how many threads migrated, how many
  orphaned, whether the diff fetch itself failed), `find_matching_sessions(cwd: str, head: str)
  -> list[str]` (sids), `main(argv=None) -> int` (`python3 -m skills.ask_diff.sync` — no
  arguments, resolves `$PWD` and the current branch itself, matching the original
  `notify_change` design's own invocation shape).

- [ ] **Step 1: Read the two governing specs' relevant sections before writing anything**

  `docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md`'s "Decisions taken"
  and "Data flow" sections (the *behavior*: git-hook trigger, explicit-resolve-only,
  resolved-means-deleted, automatic anchor migration, orphaned-anchor-wakes-Claude — unchanged).
  `docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md`'s `### interactive-review
  (Phase 4)` section, specifically its "Live sync, redesigned" bullet (the *mechanism*: a CLI,
  not an HTTP endpoint, replay-and-delete for anchor migration, `submit_event` with a JSON
  envelope for orphaned anchors).

- [ ] **Step 2: Session matching — `find_matching_sessions`**

  The old design matched sessions by `(cwd, head branch)` read from `sessions.json`'s own
  recorded fields. The daemon's session rows carry no custom "head branch" field (`_row()`'s
  fixed shape is `{sid, slug, kind, cwd, title, url}`). Resolve this by reading each candidate
  session's own `__meta__` item (pushed by Task 1's `push.py`, carries `head`) via `get_items`:
  `GET /api/sessions?cwd=<hook's $PWD>&kind=interactive-review` for candidates, then
  `get_items(sid, kind="interactive-review")["__meta__"]["body"]["head"]` for each, comparing
  against the branch the hook detected (`git branch --show-current` at hook-fire time). Match
  on equality; a session with no `__meta__` item yet (never successfully pushed) is skipped, not
  an error. Return every match — multiple matches all get resynced, per the original design's
  own "cheap, and safer than guessing which one is 'the' session" reasoning, unchanged.

- [ ] **Step 3: `resync()` — the core algorithm**

  1. Re-fetch the diff via `fetch_pr_diff` (same function `push.py` uses). On failure: return a
     summary indicating failure, touch nothing else — matches the original design's "a session
     with a stale-but-known-good snapshot is strictly better than one half-overwritten."
  2. `get_threads(sid, kind="interactive-review")` — the daemon's bulk shape.
  3. For each thread, extract its anchor's `path`/`side`/`line` (or `line_start`/`line_end`),
     locate the corresponding file's current lines (read from the newly-fetched diff or the
     working tree — decide which and say why in the report; the original `AnchorResolver`
     algorithm needs the file's current *line list*, not a diff — read `anchor_migrate.py`'s own
     docstring/signature to confirm exactly what it expects before choosing the source), and
     call `anchor_migrate.locate(lines, recorded_line, anchor_text, k=25)`.
  4. **EXACT or MOVED**: if the line changed, migrate — read the old anchor's full thread via
     `get_threads`'s already-fetched bulk result (no extra call needed), replay every message
     onto the new anchor via repeated `append_thread(sid, new_anchor, msg["text"], kind=KIND,
     role=<the role decided in Global Constraints>, source_event_id=msg.get("source_event_id"),
     title=<only on the last/most relevant call — check append_thread's own semantics for
     whether title is per-call or thread-level>, anchor_text=<only on the first replayed message,
     matching first-write-wins>)`, in original message order, then `delete_thread(sid,
     old_anchor, kind=KIND)`. **Do this before the new `__diff__`/`__meta__` are pushed** (Step
     5) — matches the original design's "never leave a thread pointing at the old file's line
     numbers against the new file's content, even for the instant between writes."
  5. **STALE**: `submit_event(sid, old_anchor, json.dumps({"event_kind": "anchor_orphaned",
     "thread_title": <thread's title>, "old_anchor_text": <thread's stored anchor_text>}),
     kind=KIND)` — per Global Constraints' JSON-envelope bridge. Leave the thread untouched (its
     anchor stays what it was; the panel keeps showing it at its last known line until Claude or
     the user acts, per the original design).
  6. Push the new `__diff__`/`__meta__` via `put_items` — this is what makes the daemon's own
     `item-changed` SSE frame fire, notifying any open IDE panel that the diff refreshed. This
     step happens LAST, after every migration in Step 4 has already moved threads onto the new
     anchors, so nothing is ever inconsistent even for an instant.
  7. **Idempotency**: if `resync()` runs twice against an unchanged diff (e.g., a hook fires
     twice for one logical change, or a retry), every thread's `locate()` call returns EXACT with
     an unchanged line — no migration, no duplicate messages, no wasted `append_thread` calls.
     Write a test for this specifically (Task's own test file, Step 5 below).

- [ ] **Step 4: `install_hooks.sh` and `main()`'s hook-invocation entry point**

  Port near-verbatim from the original 2026-09-01 design's own spec text (component 2): three
  hooks (`post-commit`, `post-rewrite`, `post-checkout`), a marker comment
  (`# claude-annotate: notify_change` — or update the marker string to name `sync.py` instead if
  that reads more accurately; state which you chose), append-not-overwrite semantics for a
  foreign existing hook, no-op on a second install. `main()` resolves `$PWD` via `git
  rev-parse --show-toplevel` and the current branch via `git branch --show-current`, calls
  `find_matching_sessions` then `resync` for each match, and — critically, per the original
  design's own error-handling table — **exits 0 on every failure path** (server unreachable, no
  match, a resync that itself failed) since a git hook must never block the git command that
  triggered it. Wrap the whole `main()` body in a broad `except Exception: return 0` for exactly
  this reason, with a comment explaining why a broad catch is correct here (this is the
  documented exception to "never swallow exceptions broadly" — a git hook's failure mode is
  categorically different from a server's).

- [ ] **Step 5: Write `test_sync.py` and `test_install_hooks.py`**

  `test_sync.py`: mock a failing diff fetch (assert nothing else runs); an EXACT match (no
  migration); a MOVED match (assert the new anchor has the full message history, the old anchor
  is gone, `source_event_id`s survived); a STALE match (assert the right event shape was
  submitted, the thread itself untouched); the idempotent double-run case from Step 3.7.
  `test_install_hooks.py`: three fixture repos per the original design's own testing section — no
  existing hook, a foreign hook (assert its content survives, in order, after the appended call),
  an already-installed repo (assert no duplicate lines after a second run).

- [ ] **Step 6: Run the test suite for this task**

  Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff && python3 -m pytest skills/ask_diff skills/_shared -q`

- [ ] **Step 7: Commit**

  ```bash
  cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff
  git add skills/ask_diff/sync.py skills/ask_diff/install_hooks.sh skills/ask_diff/tests/test_sync.py skills/ask_diff/tests/test_install_hooks.py
  git commit -m "Add ask_diff's live-sync engine: anchor migration, orphaned-anchor events, git-hook trigger"
  ```

---

### Task 3: Rework `ReviewSessionClient.java` — the phase's real weight

**This is the single largest Java task in the whole program.** Every finding in Global
Constraints was independently verified against the live code and the live daemon during this
plan's research — re-verify anything surprising yourself before writing code, the same
discipline Phase 3's Task 2 used.

**Files:**
- Modify: `ide-plugin/src/main/java/com/petros/ireview/ReviewSessionClient.java`
- Modify: `ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java`
- Modify (if needed): `ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java`

**Interfaces:**
- Consumes: the daemon's real routes directly, with `WebCompanionHttp.withContract(...)` on
  every request builder (existing helper from Phase 3's fix round — reuse, do not reinvent).
- Produces: whatever `SessionInfo`/`ThreadState`-equivalent records this file already exposes to
  its listeners, with the SAME external shape as today wherever nothing forces a change — read
  the file's own `Listener` interface and record definitions first, and change only what the
  daemon's real shapes force you to change, matching Phase 3's own discipline of not touching
  consumer classes (`AnnotationsPanel.java` etc.) unless their inputs' shape genuinely changed.

- [ ] **Step 1: Session discovery — `fetchNewestSession()`**

  **Correcting this plan's own research — a prior session already partially daemon-shaped this
  method before this program's cutover began**, so the gap is narrower than "add kind filtering
  from scratch." Confirmed by reading the current code directly: a `private static final String
  KIND = "interactive-review"` constant already exists, and `parseFirstSession` (line ~848)
  already does client-side kind filtering AND max-sid selection (`if (kind != null &&
  !KIND.equals(kind)) continue; ... str(o,"sid").compareTo(...) > 0`) — this part is already
  correct and needs no rework. **What is still missing**: `fetchNewestSession()`'s own query
  string (line ~419, `baseUrl + "/api/sessions?cwd=" + ...`) never actually sends `&kind=`
  server-side — it relies entirely on the client-side filter above, which works but is wasteful
  (fetches every skill's sessions for the cwd every time). Add `&kind=interactive-review` to the
  URL now that Task 1's `push.py` is the only thing creating real sessions.

  Pick the lexicographically-greatest `sid` is ALREADY correct (see above) — Task 1's
  `supersede=True` (settled, not a live choice — see this plan's own Global Constraints) is what
  makes this a hard guarantee rather than a convention; state this cross-reference in the report,
  don't re-derive it.

  **Delete `fetchFromLegacyServer()` and its call site entirely** once this phase's `push.py` is
  the only thing creating sessions — unlike Phase 3, this client currently has bespoke
  legacy-fallback logic beyond what `ServerDiscovery` itself provides (see Global Constraints).
  Confirm nothing else in the file calls `fetchFromLegacyServer` before deleting it, and confirm
  `ServerDiscovery.readLegacyServerJson` (package-visible specifically for this caller, per its
  own javadoc) has no other caller left afterward — if it doesn't, that comment on
  `ServerDiscovery` itself is now stale and should be corrected in this task too (a two-line doc
  fix, not a `ServerDiscovery` behavior change).

  **`SessionInfo`'s field set also needs to change, for a reason Step 2 below explains in full**:
  drop `stateDir` (confirmed by grep during this plan's pre-dispatch review: `.stateDir()` is
  never called anywhere in `ide-plugin/src/main/java` or `.../src/test/java` — dead exactly like
  Phase 3's equivalent field), and change how `prRef` gets populated — see Step 2.

- [ ] **Step 2: `SessionInfo.prRef` — NOT a diff/meta-loading rewrite; a smaller, different gap
  than this plan originally assumed**

  **Major correction, made during this plan's own pre-dispatch review — read this whole step
  before writing any code, it replaces the plan's original premise entirely.** This plan's
  research assumed `ReviewSessionClient.java` has a method that loads diff *content*
  (`diff.patch`) and compares it for changes, the way `WalkthroughSessionClient.loadSteps()`
  does for `__steps__`. **It does not, and there is nothing like it to replace.** Verified
  directly: grepping the whole file for `diff.patch`, `meta.json`, and any method name containing
  "diff"/"meta" (case-insensitively, beyond the unrelated `parseFirstSession`/`SessionInfo`
  fields) returns nothing. The actual PR diff the user sees is rendered by a completely separate
  mechanism, `GhPrDiffOpener.java` — its own javadoc says it explicitly: "Drive the REAL
  JetBrains GitHub PR diff... instead of an isolated, locally-rebuilt diff." It calls
  `session.prRef()` to parse a PR number, then hands off to the bundled GitHub plugin's own
  `GHPRProjectViewModel.openPullRequestDiff`, which talks to GitHub directly — it never reads the
  daemon's stored `__diff__` item, never reads `diff.patch`, and is completely unaffected by
  anything this migration does to session/item routes. **Do not build any diff-content
  fetching/comparison/version-tracking logic in this file — there is nothing for it to replace,
  and Phase 3's "reset the version field on session switch" lesson does not apply here because
  there is no such field to begin with.**

  The REAL gap Step 1 flagged: today, `parseFirstSession` reads `pr_ref` directly off the session
  list response (`str(newest, "pr_ref")`, line ~860) — this works against the LEGACY server
  (which controls its own response shape and includes `pr_ref` per session) but **will not work
  against the daemon**, whose `_row()` (`~/projects/webcompanion/src/webcompanion/server.py:372-381`)
  returns a FIXED shape — `{sid, slug, kind, cwd, title, url}` — with no `pr_ref` field at all,
  confirmed directly against the daemon's source during this plan's pre-dispatch review. `title`
  IS present on the daemon's row (matching what Task 1's `push.py` sets via
  `create_or_attach(..., title=title)`), so `SessionInfo.title` can still be populated straight
  from the session-list response, unchanged. `prRef` cannot — it must come from a separate fetch
  of the `__meta__` item Task 1's `push.py` pushes: `GET /s/{sid}/items?kind=interactive-review`,
  extract `.__meta__.body.pr_ref` (daemon items shape: `{anchor: {body, version}}`, confirmed
  against `items.py` during Phase 2/3's own research). Since `pr_ref`/`title` are set once at
  push time and never change for a session's lifetime (unlike `__diff__`'s content, which
  `sync.py` does refresh), a single fetch right after `attach()` — not a poll-driven or
  SSE-driven re-fetch — is sufficient; there is no staleness concern for these two fields to
  guard against, and no version-tracking field is needed for them either. Populate
  `SessionInfo.prRef()` from this one-time `__meta__` fetch, falling back to an empty string if
  the fetch fails or the item doesn't exist yet (matching this file's existing "never let a
  missing field crash discovery" posture), and note this explicitly in the report so the
  reviewer knows to check for exactly one `__meta__` fetch per attach, not a polling loop.

  **Before writing this step's code, confirm independently that nothing else in this file or in
  `AnnotationsPanel.java`/`AnchorResolver.java` reads diff CONTENT (not just `prRef`) from
  anywhere daemon-related** — this plan's pre-dispatch review checked `ReviewSessionClient.java`
  and `GhPrDiffOpener.java` directly but did not exhaustively trace every consumer class in the
  IDE plugin; if you find a genuine diff-content consumer this review missed, treat that as a
  real new finding, say so plainly in the report, and handle it (most likely by fetching
  `__diff__` similarly to `__meta__` above) rather than silently working around it.

- [ ] **Step 3: Thread deltas — bulk-fetch-and-derive**

  Replace whatever currently parses `thread-changed`'s SSE payload directly (or reads
  `/threads.json`'s bulk shape) with `GET /s/{sid}/threads?kind=interactive-review` (the daemon's
  real bulk shape: `{anchor: {anchor, version, messages: [{text, role, ts}], title,
  anchor_text}}`), deriving each anchor's synthesis/question the same way
  `skills/_shared/static/wc-threads.js`'s `derive()` and Phase 3's own Java port do — filtering
  on whichever `role` value Task 1 decided (`"claude"` or `"agent"` — this task MUST match
  whatever Task 1 actually wrote; if Task 1 hasn't run yet when this task starts, treat this as a
  blocking dependency and confirm the ruling before writing this step's code). A thread with no
  matching-role message yet is omitted, matching every prior phase's identical rule.

  **Apply Phase 3's Important-1 fix from the start, not as an afterthought**: whatever HTTP
  round-trip this bulk fetch requires inside an SSE-event handler, re-check the client's
  generation/closed state immediately after the fetch returns and before applying results —
  Phase 3's final review found this exact race (a superseded session's in-flight response
  landing in the new session's cache) in walkthrough's own equivalent code, and its fix round
  needed a second, narrower fix after the first one missed a variant of it. Design this file's
  version of the guard carefully enough the first time that it doesn't need two rounds.

- [ ] **Step 4: Submit — drop `type`, resolve the `anchor_text` gap**

  Drop `type` from the payload map entirely (see Global Constraints — confirmed dead). Implement
  the `anchor_text` propagation per Global Constraints' now-settled resolution: the daemon's
  `_submit` handler discards any payload key beyond `anchor`/`text`/`images` (confirmed during
  this plan's own pre-dispatch review, not something to re-investigate), so JSON-encode
  `anchor_text` into `text` alongside the comment body — pick the envelope shape (this plan
  suggests `{"anchor_text": "...", "comment": "..."}` but the exact field names are this task's
  call) and state it plainly in the report, since Task 4's `SKILL.md` rewrite must parse the
  identical shape.

- [ ] **Step 5: Poll rework**

  Same shape as Phase 3's Task 2 Step 5: `?kind=interactive-review` on the URL; recompute
  `ended`/`ended_reason`-equivalent client-side from the daemon's real `{finished, cancelled,
  watcher_seen_at, items, threads}` shape (no `ended_reason` differentiation exists on the
  daemon — if this file's current `ended_reason` distinguishes cancelled/finished/dead
  differently anywhere downstream, e.g. in `AnnotationsPanel`'s own UI text, check whether that
  distinction is worth preserving client-side or can collapse the same way Phase 3's did).

- [ ] **Step 6: Every other daemon route in this file gets `?kind=interactive-review`**

  Grep the whole file for every `HttpRequest.newBuilder`/`URI.create(baseUrl + ...)` construction
  (there are more routes here than Phase 3 had — `/api/cancel`, `/api/threads/delete`, `/stream`,
  at minimum, per this plan's own research) and confirm each one carries the query param and is
  wrapped in `WebCompanionHttp.withContract(...)`.

- [ ] **Step 7: Rewrite `ReviewSessionClientTest.java`'s fixtures**

  Every fixture encoding the old wire shapes (`sessionsRow` without a `kind` field if one exists,
  `/threads.json`-shaped bulk responses, submit-body assertions containing `"type"`,
  `ended_reason`-shaped poll responses) gets rewritten to the real daemon shapes. **Confirmed
  during this plan's own pre-dispatch review — no `FakeReviewServer.java` changes are needed for
  the bulk `/threads` route.** Its field is `public volatile String bulkThreadsJson = "{}";`
  (`FakeReviewServer.java:32`), served verbatim at the `/threads` path
  (`FakeReviewServer.java:170-171`) — a raw passthrough, not a hardcoded shape. A test that needs
  an `anchor_text` field in the bulk response sets `bulkThreadsJson` to a JSON string that
  includes it; nothing in `FakeReviewServer.java` itself constrains the shape. Add tests for:
  max-sid selection,
  the kind-mismatch defensive check, the version-reset-on-switch fix from Step 2 (a direct
  regression test, following Phase 3's fix-round pattern rather than waiting for a final review
  to demand one), and the generation-guard fix from Step 3.

- [ ] **Step 8: Run the Java test suite**

  Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff/ide-plugin && ./gradlew test --tests "com.petros.ireview.ReviewSessionClientTest"` then the full suite `./gradlew test` to confirm nothing else (e.g. `AnnotationsPanel`'s own tests, if any exist) broke.

- [ ] **Step 9: Commit**

  ```bash
  cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff
  git add ide-plugin/src/main/java/com/petros/ireview/ReviewSessionClient.java \
          ide-plugin/src/main/java/com/petros/ireview/ServerDiscovery.java \
          ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java \
          ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java
  git commit -m "Rework ReviewSessionClient onto the daemon's real wire shapes"
  ```

---

### Task 4: Delete the old server; hook installation in SKILL.md; migrate docs; smoke test

**Files:**
- Delete: `skills/ask_diff/server.py`
- Delete: `skills/ask_diff/ensure_server.sh`
- Delete: `skills/ask_diff/tests/test_server.py` (coverage triaged first)
- Modify: `skills/ask_diff/SKILL.md`
- Modify: `skills/ask_diff/README.md` (if it describes the old server — check first)

**Interfaces:**
- Consumes: `push.py`/`sync.py`/`install_hooks.sh` (Tasks 1-2), the reworked
  `ReviewSessionClient.java` (Task 3).

- [ ] **Step 1: Confirm `test_server.py`'s coverage before deleting**

  Same discipline as every prior phase's own Task-3-equivalent Step 1: run
  `python3 -m pytest skills/ask_diff/tests/test_server.py -v --collect-only`, check every test
  against `Handlers`' methods, confirm `diff.py`'s own validation logic is covered independently
  of the deleted server (in `test_diff.py`) before deleting anything that isn't.

- [ ] **Step 2: Delete the old server**

  ```bash
  cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff
  git rm skills/ask_diff/server.py skills/ask_diff/ensure_server.sh skills/ask_diff/tests/test_server.py
  ```

- [ ] **Step 3: Update `SKILL.md`**

  Read `skills/walkthrough/SKILL.md` (Phase 3, merged) as the closest prior-art shape. Replace:
  - The `ensure_server.sh`/curl-based session-create block → `python3 -m skills.ask_diff.push
    --pr "$PR_REF" --cwd "$PWD" --claude-session-id "$CLAUDE_CODE_SESSION_ID"`.
  - Add a new step, run once per repo at session-create (checking a marker rather than
    unconditionally re-running, matching the original design's "one-time-per-clone, transparently
    repeated if missing" framing): invoke `install_hooks.sh` against the current repo.
  - The watcher-arm step → `webcompanion watch --kind interactive-review --sid <sid>` (note: the
    daemon `kind` here is `interactive-review`, not `ask-diff` or `ask_diff` — restate the Global
    Constraints identifier rule inline in the doc itself, since a future editor of this file is
    exactly who needs the reminder).
  - Mode D's event-payload description → drop `type` entirely from the documented shape (per
    Task 3 Step 4's resolution — coordinate the exact final shape with whatever Task 3 actually
    shipped), and add the `event_kind == "anchor_orphaned"` branch per the master spec's own
    described JSON-envelope shape, checked BEFORE falling through to normal comment handling.
  - The reply step (`reply_cli.py`) → per this program's established finding (walkthrough's Task
    1: `reply_cli.py` was never actually daemon-aware anywhere in this program) inline
    `webcompanion_client.append_thread(sid, anchor, text, kind="interactive-review",
    role=<Task 1's chosen role>, source_event_id=..., title=..., anchor_text=<only on a thread's
    first reply>)` directly, then `webcompanion ack --sid <sid> --event-id <event_id>` — matching
    dataflow's and walkthrough's own Mode-D shape exactly. **Do not reference `reply_cli.py`
    anywhere in the rewritten file.**
  - Add a new "resolving a finding" section: `webcompanion_client.delete_thread(sid, anchor,
    kind="interactive-review")` replaces `resolve_cli.py`'s `threads.delete()` call — per the
    original live-sync design's Component 5, though note that design's own thin CLI wrapper
    (`resolve_cli.py`) is no longer needed at all now that this is one library call through the
    already-shared client, not a new file.

  Keep every response-style-guide section unchanged — none of it is server-related.

- [ ] **Step 4: Update `README.md` if it describes the old server**

  Check first; correct the same way every prior phase's `README.md` fix did.

- [ ] **Step 5: Manual smoke test against the real live daemon**

  Confirm `webcompanion status`. Using a real, small PR against a repo you can safely test
  against (or a synthetic branch-ref review against this very `claude-annotate` repo, per this
  skill's own "local branch ref — pre-PR review against main" invocation form, avoiding any need
  for a real GitHub PR):

  1. Push via `push.py`, confirm `__diff__`/`__meta__` land correctly via `GET
     /s/{sid}/items?kind=interactive-review`.
  2. Post a thread message via `curl` mimicking the IDE's submit, confirm it lands via `GET
     /s/{sid}/threads?kind=interactive-review`, confirm a `thread-changed` SSE frame arrives on
     `/s/{sid}/stream?kind=interactive-review`.
  3. **Exercise the live-sync path end to end** — this is the phase's actual point and must not
     be skipped: install hooks against a real test repo (or the review repo itself, if safe),
     make a real local commit or amend that shifts a reviewed line's position, confirm the
     `post-commit` hook fires `sync.py`, confirm the thread's anchor actually migrated (read the
     daemon's stored thread data directly) and the IDE (if runnable in this environment) or the
     raw `GET /s/{sid}/threads?...` shows it at the new line, with its full message history
     intact.
  4. Force a STALE case (delete or drastically rewrite the reviewed line) and confirm an
     `anchor_orphaned` event actually reaches the events queue and a `webcompanion watch` picks
     it up.
  5. If a real IntelliJ instance can be run in this environment, run the actual IDE plugin
     against a live session — per Phase 3's own precedent, this is "not optional to skip if a way
     to run the IDE plugin locally exists"; if it genuinely does not, say so plainly and name it
     as an accepted gap for the human to verify by hand, the same way Phase 3's Task 3 did.
  6. Finish the test session; confirm no session is left dangling.

- [ ] **Step 6: Run both full suites**

  Run: `python3 -m pytest skills -q` (expect the current baseline plus this phase's new tests,
  minus `test_server.py`'s deleted tests, zero failures) and `cd ide-plugin && ./gradlew test`
  (expect the current baseline plus Task 3's new tests, zero failures).

- [ ] **Step 7: Commit**

  ```bash
  cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover-ask-diff
  git add -A skills/ask_diff/
  git commit -m "Migrate ask_diff (interactive-review) onto the webcompanion daemon; delete its private server"
  ```

---

## Testing strategy

Python: real unit tests for `push.py` and `sync.py` (Tasks 1-2), matching every prior phase's
pattern (mocked daemon client, real validation/migration logic) — `sync.py`'s tests are this
phase's highest-value tests, since the live-sync mechanism has no precedent to fall back on if
it's wrong. Java: `ReviewSessionClientTest.java`, rewritten to pin the daemon's real shapes
(Task 3) plus new regression tests for both lessons carried forward from Phase 3's final review
(version-reset-on-switch, generation-guard-after-HTTP-round-trip) written from the start rather
than discovered by a review. A live-daemon smoke test (Task 4 Step 5) is the only thing that can
verify the git-hook-triggered resync path end to end — it is the load-bearing test for this
phase's actual reason for existing.

## Known limitations (accepted, not deferred silently)

- **Cross-cwd watcher auto-cancel may be gone**, depending on Task 1's Step 1 ruling — if the
  recommended `(kind, cwd)`-scoped `supersede=True` is chosen, a Claude conversation reviewing
  PRs in two different repos concurrently no longer auto-cancels the first review when the
  second opens. Unlike walkthrough's identical limitation, this one directly reopens a
  leak-prevention guarantee the original `ask_diff/server.py` author built specifically to avoid
  — cross-reference this program's own tracked session-leak initiative when reporting this
  phase's completion.
- **Remote-side PR changes remain invisible** — no hook exists for "someone else pushed" or "I
  pushed from another machine." Unchanged from the original 2026-09-01 design's own accepted
  limitation; not revisited by the daemon migration.
- **Anchor-migration replay does not preserve original message timestamps** — see Global
  Constraints. A cosmetic loss, not a functional one.
- **No daemon-side session expiry** — old, finished review sessions accumulate in `GET
  /api/sessions?cwd=` forever, same as every prior phase's identical limitation; out of scope
  here, tracked by the separate session-leak initiative.
