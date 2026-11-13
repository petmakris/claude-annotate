# webcompanion as a standalone always-on service

Status: design, awaiting approval. Supersedes the per-skill server model
described in `2026-08-12-install-robustness-design.md`.

## Why this change

Today five skills each run their own HTTP server. `/annotate` binds 3080,
`/deck` 3090, `/dataflow` 3100, `/interactive-review` 54620+, `/walkthrough`
54660+; each has its own `server.py`, its own `ensure_server.sh` wrapper, its
own state directory under `~/.claude/<skill>/`, and its own copy of the
startup dance — preflight, mkdir lock, health probe, code fingerprint, kill
and respawn. The servers are not really five servers: they all import one
engine from `skills/_shared/web_companion/` and differ only in their routes
and their page. The duplication is in the lifecycle, not the logic.

That lifecycle is the cost. A skill invocation cannot assume a server; it has
to start one, and starting one means serialising against other invocations,
fingerprinting the source tree to detect a stale build, and killing a live
process that is holding the port. When it goes wrong the user sees a skill
that hangs for five seconds and then prints a log path.

After this change there is one process. It is installed once, supervised by
the operating system, listens on a fixed loopback port, and is running before
any skill asks for it. A skill's first act is a health check; if the service
is not there the skill stops and prints the command that installs it. No
skill ever spawns a server again.

## Glossary

- **daemon** — the always-on `webcompanion serve` process. One per machine.
- **package** — the PyPI distribution `webcompanion`, in its own repository.
- **skill** — one of the five Claude Code skills in `claude-annotate` that
  drive the daemon: `annotate`, `deck`, `dataflow`, `interactive_review`,
  `walkthrough`.
- **session** — one pushed document with its own URL. Has a `sid`, an
  optional human `slug`, and a `kind`.
- **kind** — an opaque string naming which skill owns a session. The daemon
  stores and filters on it and never interprets it.
- **item** — one addressable unit of a session's content: a block, a slide, a
  diff line, a graph node, a walkthrough step. Addressed by **anchor**.
- **anchor** — the item's stable id within its session, chosen by the skill.
- **code anchor** — a `{file, line}` reference an item may declare, which the
  daemon resolves by reading the file at request time.
- **runtime** — `core.js`, the daemon's own 4.7KB browser script: selection,
  composer, submit, refetch. It renders nothing.
- **renderer** — a skill's own browser bundle (annotate's markdown-it and
  highlight.js, dataflow's diagram code). Served by the daemon, owned by the
  skill.
- **event** — a user comment queued for Claude, drained by `webcompanion
  watch`, which prints `WEBCOMPANION_EVENT` to wake the session.
- **contract** — the integer version of the HTTP API. Currently 1.

## Decisions

| # | Decision |
|---|---|
| D1 | One daemon for all five skills. Generic: it never learns what a slide or a diff line is. |
| D2 | Content moves over HTTP as opaque addressable items. The daemon ships the interaction runtime and serves each skill's renderer as session assets. |
| D3 | Installed as an OS service on a fixed loopback port. Skills never spawn it. |
| D4 | Clean break: all five skills and the IntelliJ plugin end up on the daemon, and the old mechanism is deleted from the tree. Released in four ordered steps (see Rollout). |
| D5 | New repository `petmakris/webcompanion`, published to PyPI. `claude-annotate` becomes a consumer. |

D2 was originally written as "skills upload HTML with `data-wc-block`
attributes and the daemon swaps `innerHTML`". Review found that describes a
page shape none of the five views have — annotate returns an empty
`<main class="prose">` and ships blocks as JSON markdown rendered
client-side (`skills/annotate/server.py:467-573`, `:600-630`); dataflow
returns `<div id="app"></div>` and draws its diagram in JS
(`skills/dataflow/server.py:104`); deck mounts an iframe per slide over the
user's own `.html` file (`skills/deck/server.py:106-141`). The daemon
therefore addresses **opaque JSON items**, not HTML, and swaps nothing.

Both reviewers recommended keeping the filesystem as the content channel for
v1, which would have made the extraction mechanical. That was considered and
rejected: the network boundary is the point of the exercise, and doing it
later means doing the migration twice. The accepted cost is that the push
path and `serve_root` in all five skills, plus every reference doc, are
rewritten in the same release.

## What the daemon owns, and what it refuses to know

The daemon owns everything that is true of all five views: sessions and their
registry, the slug namespace, workspaces on disk, the item store, the version
chain, comment threads, the event queue, uploads, the SSE stream, the session
browser, retention and cleanup, the write gate, and `open in editor`.

It owns exactly one thing that looks skill-shaped, and does so deliberately:
**code anchors**. An item may declare `{file, line, lines}`, and the daemon
reads that file when the item is requested. This exists because annotate's
anchors are resolved at read time against the live working tree by design —
`skills/annotate/anchors.py:1-10` states the rule, and `/raw` refetches once
per second per open tab. Claude edits the repository *during* a session, so
an anchor snapshotted at push time is a lie within one turn. Resolving at
request time is not an annotate concept; dataflow and walkthrough want it
too. It moves into the package as a first-class capability, bounded to the
session's `_cwd`.

The daemon refuses to know: what markdown is, what a slide is, how a diagram
is laid out, what a PR is, and what any item's JSON body means. It stores
item bodies verbatim, hashes them for versioning, and serves them back.

Everything currently computed inside a skill's `serve_root` or
`create_session_extra` moves to the client side, with two consequences worth
naming. `interactive_review` shells out to `gh pr diff` inside
`/api/sessions` (`skills/interactive_review/server.py:258`); that moves into
the skill, which means the daemon can no longer reject a session on a bad PR
ref, and the 5MB diff limit at `:262-266` becomes the CLI's job or it
evaporates. `deck`'s `create_session_extra` resolves and stats a
user-supplied path (`skills/deck/server.py:84-105`); same move.

`/api/open` stays server-side — a browser cannot launch an editor — so the
daemon keeps exactly one subprocess capability, already `_cwd`-contained at
`skills/_shared/web_companion/server.py:897`.

## HTTP contract, version 1

Every request carries `X-WebCompanion-Contract: 1`. A mismatch is answered
**426 Upgrade Required** with a body naming which side is old.

### Session lifecycle

    POST   /api/sessions              {kind, cwd, slug?, title?, supersede?}
                                      -> {sid, slug, url, token}
    GET    /api/sessions?cwd=&kind=   -> [{sid, slug, kind, title, updated}]
    GET    /api/sessions?scope=all    -> every session on the machine (owner-gated)
    POST   /s/<sid>/api/finish
    POST   /s/<sid>/api/cancel

`kind` is **mandatory** on create and on discovery. Without it, merging the
five daemons breaks both IntelliJ clients: `ReviewSessionClient.java:400` and
`WalkthroughSessionClient.java:279` both poll `/api/sessions?cwd=<project>`,
which is unambiguous today only because they hit different ports. One daemon
returns every kind for that cwd and the row shape carries no discriminator,
so the walkthrough panel would latch an annotate session and poll it forever.

`supersede` replaces the per-skill `supersede_by_claude_session` class
attribute (annotate `True`, deck `False` — `skills/deck/server.py:80`).

### Items

    PUT    /s/<sid>/items/<anchor>    body = skill-defined JSON
    PATCH  /s/<sid>/items            bulk upsert, one request per push
    GET    /s/<sid>/items            -> {anchor: {body, version}}
    GET    /s/<sid>/items/<anchor>   -> {body, version, code?}
    DELETE /s/<sid>/items/<anchor>

`version` is derived by the daemon, never sent by the client. It is the
length of a per-anchor hash chain over the canonical-JSON body — the
mechanism already in `skills/annotate/versions.py`, which is server-derived,
normalises cosmetic noise, and contains no annotate concepts. It moves into
the package unchanged in behaviour.

`code` is present only when the item declares a code anchor; the daemon
resolves it per request and returns the current file text.

### Assets and the page

    POST   /s/<sid>/api/assets       {static_root}   registers the renderer
    GET    /s/<sid>/assets/<path>    serves from that root
    GET    /_wc/core.js              the daemon's runtime
    GET    /s/<sid>/                 the shell page

The shell is a minimal document that loads `core.js` and the session's
registered entry point. annotate's ~480KB of static — `script.js` 129k,
`style.css` 99k, `highlight.min.js` 122k, plus fuse, diagram, export,
subunits, voice — is a **renderer**, not a runtime, and stays with annotate.
It is served through `/s/<sid>/assets/`. Only `core.js` (4.7KB, "polling
loop, composer, submit, finish") is the daemon's.

### Interaction and events

    POST   /s/<sid>/api/submit       {anchor, text} -> 202 {event_id}
    GET    /s/<sid>/poll             version vector + watcher heartbeat
    GET    /s/<sid>/stream           SSE
    POST   /s/<sid>/api/threads/delete
    POST   /api/open                 {file, line}  (owner-gated, _cwd-contained)
    GET    /health                   -> {banner, contract, version, uptime}

SSE emits two generic frames and no others:

    item-changed      {anchor, version}
    document-changed  {version}

This replaces `stream.py`'s `extra` hook, which takes **a Python callable**
so each skill can add its own frames on the shared loop — walkthrough's
`steps-changed`, dataflow's `flow-changed` recomputed per tick
(`skills/dataflow/server.py:156-186`). A standalone daemon cannot call into
skill code, and every one of those frames is really "X changed to version N".
The hook is deleted. Frame names must be checked against
`SseClient.Parser` (`ide-plugin/.../SseClient.java:23-55`) and
`WalkthroughSessionClient.java:404`, which switch on event name.

## Package, distribution, and the service

### Layout

    webcompanion/
      pyproject.toml           requires-python = ">=3.9", zero dependencies
      src/webcompanion/
        engine/                sessions, items, versions, threads, events,
                               uploads, stream, cleanup, paths, atomic, anchors
        server.py              routes, write gate, ThreadingHTTPServer
        static/core.js         the runtime
        service/               launchd plist and systemd unit templates
        cli.py                 push | update | watch | end | serve |
                               install-service | status | doctor | migrate
      tests/

`[project.scripts] webcompanion = "webcompanion.cli:main"`.

Static assets are package data read through `importlib.resources.as_file`.
`Path(__file__).resolve().parent / "static"` (`server.py:34`) survives a
wheel but not a zipapp, so it must change.

`requires-python = ">=3.9"` holds: `int | None` is safe under
`from __future__ import annotations`, and `Path.is_relative_to` is 3.9+.
`threads.py:21` imports `fcntl`, so the package's own README must state
macOS/Linux only — not only `claude-annotate`'s.

### Distribution: zipapp, not a venv

The package is stdlib-only, which makes a virtualenv pure liability. A pipx
venv is bound to the interpreter that created it; when Homebrew retires that
Python the venv's interpreter dangles, the entry point fails to exec, and
launchd `KeepAlive` respawn-loops the job forever at the default 10s
`ThrottleInterval` — `launchctl list` shows the job, every skill sees
connection refused, and nothing says why.

So: ship a **zipapp**. The plist runs `/usr/bin/env python3
~/.local/share/webcompanion/webcompanion.pyz serve`. Nothing to break on an
interpreter upgrade, and the zero-dependency claim survives intact. The
package is still on PyPI and `pipx install webcompanion` still works for
people who want the CLI on their PATH; `install-service` writes the zipapp
and points the service at it either way.

`install-service` sets `ThrottleInterval` and `StandardErrorPath`, and
restarts the service as its final step.

### Configuration

One file, `~/.claude/webcompanion/config.json`, mode 0600:

    {"port": 3080, "token": "...", "retention_days": null,
     "workspace_root": null, "bind": "127.0.0.1"}

Written by `install-service`. Read by the daemon, the CLI, and the IntelliJ
plugin. Fixed known path — no discovery poll, no `server.json`.

The token must be **durable**. It is currently minted per server start
(`server.py:332-340`); an always-on service that reshuffles it on every
restart breaks any non-loopback client mid-session.

All environment-based configuration moves into this file.
`WEBCOMPANION_RETENTION_DAYS`, `WEBCOMPANION_WORKSPACE_ROOT`,
`WEBCOMPANION_BIND` and `WEBCOMPANION_PUBLIC_HOST` are read from the
*daemon's* environment; under launchd or systemd the daemon has a fixed
environment and the user's shell variables never reach it. Left alone this
presents as "my setting stopped working" with no error.

### Version compatibility

`ensure_server.sh` currently hashes the source tree and kills any server
whose `/health` fingerprint disagrees. Deleting it removes the only upgrade
path: replacing package files under a live process changes nothing, because
the process already imported the old modules, and the idle watchdog will not
save you — it defaults to 24h, resets on every request, and explicitly
refuses to shut down while any watcher heartbeats
(`server.py:443-445`, `:1061-1065`).

The rule that replaces it:

- `/health` reports `{"contract": 1, "version": "1.3.0"}`.
- Every client sends `X-WebCompanion-Contract`.
- Contract mismatch → **426**, body names the old side.
- The CLI additionally compares package versions and prints
  `launchctl kickstart -k gui/$UID/dev.webcompanion` on mismatch.
- `install-service` restarts the service as its last step.
- The daemon never self-restarts on file change.

The 24h idle shutdown (`server.py:444`, `:1054-1067`) is **deleted**. Under
`KeepAlive` it means a daily restart that drops every open SSE stream and
every IntelliJ `SseClient`, and `core.js` has no reconnect logic.

## Concurrency, at merged scale

`_ThreadedHTTPServer(ThreadingMixIn, HTTPServer)` with `daemon_threads`
(`server.py:433-435`) is thread-per-request and sound across projects.
`Registry` is lock-guarded (`sessions.py:26`) and `events.append` is unique
per process (`events.py:31`). Three hazards are not sound at merged scale:

1. **SSE threads are unbounded.** Every browser tab and IntelliJ client parks
   a thread in `waiter.wait(timeout=30)` for the life of the connection
   (`stream.py:61-62`). That load is spread over five processes today, each
   of which shuts down when idle. One process, no idle shutdown, every
   project — needs a connection cap and a documented ceiling.
2. **`_waiters` never GCs.** One `threading.Event` per sid forever, dropped
   only in `unregister` (`sessions.py:204-209`). A slow leak matters in a
   process that now never restarts.
3. **`note_change` is `set()` then immediate `clear()`**
   (`sessions.py:217-218`) — a lost-wakeup edge, masked today only because
   `stream.py:72` re-reads on every 30s timeout. Replace with a monotonic
   version counter.

Also keep `_port_holder()` (`server.py:350-370`): "port 3080 held by node
(pid 4821)" is the most useful diagnostic in that file, and a fixed port
makes collisions more likely, not less. The `SO_REUSEADDR` split-brain
documented at `server.py:322-340` becomes reachable under a supervisor that
restarts on crash, so the daemon needs a pidfile and a startup self-check,
not just `KeepAlive`.

## One state root

Workspaces live under `~/.claude/webcompanion/workspaces/`. Two consequences:

- **Slug namespaces merge.** `register_with_slug` dedups globally
  (`sessions.py:87-94`), so `/annotate` and `/deck` can no longer both own
  `my-plan` — one silently becomes `my-plan-2`, changing a URL users
  memorise. Namespace by kind on disk —
  `~/.claude/webcompanion/workspaces/<kind>/<sid>/` — and in the slug index,
  so a slug resolves as `(kind, slug) -> sid`. Canonical routes stay
  `/s/<sid>/...`; the friendly URL becomes `/s/<kind>/<slug>` and redirects
  to the sid form, which is what today's `/a/<slug>` alias already does.
- **GC blast radius widens.** `_sweep_strays` rmtrees any sid-shaped
  directory no registry row points at (`cleanup.py:187-220`). Under one
  shared root a registry bug in one skill could delete another's workspaces.
  Namespacing by kind contains this too.

## Migration

Existing workspaces are **migrated, not discarded**. Retention defaults to
infinite (`cleanup.py:51-64`) and `/annotate resume <slug>` is a shipped,
documented feature, so users have workspaces going back to install day.

`cleanup.migrate_workspaces()` (`cleanup.py:238-316`) already moves trees and
re-roots `sessions.json`, and was written for exactly this shape of move.
`webcompanion migrate` reuses `_reroot` to merge the five roots into one,
adding the `kind` field to each row and resolving slug collisions by kind
namespace. Estimated ~80 lines.

Items are the exception: v1 changes the content channel, so a migrated
workspace's `blocks.json` must be read once and PUT as items. The migration
does this per session, or marks the session read-only if it cannot.

## Security, at merged scale

The write gate (`server.py:550-606`) is sound — loopback is the owner by
construction, and `Sec-Fetch-Site` blocks the CORS simple-request gadget that
would otherwise let any visited web page reach the local server as owner. Its
blast radius is what changes:

- `/` and `/api/sessions?scope=all` already list every workspace on the
  machine and are owner-gated for that reason (`server.py:704-733`). Merging
  makes that index five times denser, and the gate becomes the only thing
  between a visited page and the user's entire session history.
- `WEBCOMPANION_BIND=0.0.0.0` (`server.py:316-324`) now exposes every project
  ever annotated on one port. `/s/<slug>/` is world-readable by design and
  slugs are guessable. When bound beyond loopback, `/s/` reads must require
  the token.
- `/api/open` now reaches into every repository the user has ever run a skill
  in. `_cwd` containment (`server.py:897`) is the whole defence and must be
  tested as such.

## The IntelliJ plugin

Three changes, all in the same plugin build:

- Discovery: two files (`~/.claude/interactive-review/server.json`,
  `~/.claude/walkthrough/server.json`) become one config file; two fallbacks
  (54620, 54660) become one port.
- Session discovery sends `kind`.
- `WalkthroughService.java:33` resolves the base URL **once at construction**
  and never re-reads it. A daemon restart or a version mismatch strands the
  panel until IDE restart, with no explanation. It must re-resolve and must
  show a visible banner on 426 — never a silent dead poll.

`FakeReviewServer.java` (used by ten cases in `ReviewSessionClientTest`) must
change in the same commit as the routes, or the Java tests keep passing
against a contract that no longer exists.

## The fifth consumer

`skills/annotate/hooks/progress_publish.py` runs in the Claude Code hook
process, outside the model loop. It reads
`~/.claude/annotate/pending-<session_id>.json` (`:94`) and writes directly
into `state_dir/progress/` (`:128`), hard-coding the annotate state layout
that D4 deletes. It becomes a `webcompanion progress` CLI call.

## Rollout

Big-bang is not executable. The IntelliJ plugin ships as a zip downloaded by
hand from Releases; users update it late or never, while skills update on
`/plugin marketplace update` effectively immediately. Cutting both at once
guarantees a window where the skills are on 3080, the plugin is still polling
54620, and both IDE views die silently.

1. **Publish `webcompanion` 1.0 to PyPI.** Contract 1, listening on 3080.
   Nothing consumes it yet.
2. **Ship the IntelliJ build that speaks contract 1** and retains the old
   discovery as a fallback. Announce as required. This step needs time to
   propagate — it is the only slow channel.
3. **Cut the five skills over in one `claude-annotate` release.** Delete all
   five `server.py`, all five `ensure_server.sh`, `skills/_shared/web_companion/`,
   `annotate-doctor`, and the per-skill state directories. Rewrite the push
   path and reference docs.
4. **Ship the IntelliJ build that drops the fallback.**

The end state is D4's: one mechanism, no dual-mode in the tree. Steps 2 and 4
exist only because the IDE release channel is slower than the marketplace's,
and cost roughly twenty lines in `ReviewSessionService.resolveServerUrl` and
`WalkthroughService.resolveServerUrl`.

## Failure messages

Three distinguishable failures, three messages. The model to copy is already
in `ensure_server.sh:24-70`: state the requirement, name the fix command,
never install anything.

- **Not installed** — connect refused, no config file →
  `pipx install webcompanion && webcompanion install-service`
- **Installed but down** — config exists, connect refused →
  `webcompanion status`, then
  `launchctl kickstart -k gui/$UID/dev.webcompanion`, and the log path.
- **Up but wrong contract** — 426 → name which side is old and how to update
  it.

`webcompanion doctor` succeeds `annotate-doctor`, shipped by the thing it
diagnoses. It must additionally detect a dangling interpreter and a
respawn-looping service.

## Tests

The 24 files in `skills/_shared/web_companion/tests/` are the package's real
asset and move with it. Three test the launcher being deleted —
`test_preflight.py`, `test_doctor.py`, `test_ensure_server.py` — and are
replaced by plist/unit generation tests rather than dropped.
`skills/tests/test_bootstrap_guard.py` and `test_broken_machine_e2e.py`
encode spawn-on-demand and die with it. 98 test files in total; the churn is
part of the budget.

New coverage this design requires: contract-version negotiation and 426, the
`kind` filter on discovery, code-anchor resolution bounded to `_cwd`, item
version chains across a daemon restart, slug collision across kinds, the
migration, and the three concurrency fixes.

## Out of scope

- Any view redesign. The five views look and behave as they do today.
- Remote or multi-user access. Loopback remains the intended deployment.
- Windows support.
