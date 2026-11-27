# `skills/_shared`

Code and page assets shared by more than one skill. Nothing here is a server,
and nothing here starts one: every skill pushes to the separately installed
**webcompanion daemon** through `webcompanion_client.py`.

The one allowed server in this repository is talk's: `skills/talk/talk.py` runs an
aiohttp server for the call page, because the call page is a long-lived speech
server that launchd keeps up, one per machine, and not a push to the daemon.
No other skill binds a port; `skills/tests/test_smoke_engine_status.py` fails if
any does (its `SERVER_SKILLS` allowlist names talk only).

| Path | What it is |
|---|---|
| `webcompanion_client.py` | The one Python client for the daemon, with the `DaemonError` hierarchy and the `run_cli` wrapper every push command uses. |
| `atomic.py` | `write_text_atomic`: write a file whole under a unique temp name, then `os.replace` (with a `mode` for owner-only files). Annotate, journey, talk and the layout cache use it. |
| `devdomains.py` | `webcompanion_url`: the daemon's public address from `@devdomains url webcompanion`. Canvas and journey use it. |
| `visuals/` | The drawing tools: sequence diagrams and flowcharts, their layout (ELK through Node, with a Python fallback) and font metrics. Annotate draws them in its answers; stage and talk draw them on the stage, keyed for frames. `map_svg.py` (architecture maps) and `sequence_svg.py` (lane sequences), with `player.py`, are the two diagrams every project draws through; `docs/vz.md` is their guide. |
| `static/` | The canonical page assets (`core.css`, `visuals.css`, `vz.css` and `vz-reveal.js` for maps and lane sequences, fonts with Inter and JetBrains Mono for the stage, `markdown-it.min.js`, `wc-threads.js`, `wc-boot.js`, `wc-open.js`). Each skill keeps a checked-in copy in its own `static/`, because the daemon serves one folder per session; `skills/tests/test_shared_static_copies.py` fails when a copy differs from its source here. |

## The rule

A module stays in `skills/_shared` only while at least two skills import it
from production code. A package such as `visuals/` counts as one unit: its
modules import each other, and what matters is how many skills import the
package. With one importer it moves into that skill; with none it is deleted.
Tests never count as importers.
`skills/tests/test_smoke_engine_status.py` enforces this, and fails on any
other file placed here: a script belongs to the skill that runs it. The only
exceptions are a package's `vendor/` folder and a file one of its own modules
names and runs or reads, such as `visuals/elk_driver.mjs`.

## Waking a session by message

`ask_diff`, `dataflow`, `walkthrough` and `deck` arm no watcher and use no
`Monitor`. The webcompanion daemon wakes the Claude session that opened the
page with one **fleet message** each time a question is queued. A message
reaches a session that is idle with nothing running in it, so a review can sit
for hours and still answer.

Why: a `Monitor` dies after 30 minutes at most, and Claude Code has no option
to keep one alive. With a watcher as the Monitor, the watcher died with it, its
heartbeat went stale, and the IDE froze the panel read-only for good.

### What sets it up

The skill's push names this Claude session to the daemon
(`webcompanion_client.wake_to`, which posts `CLAUDE_CODE_SESSION_ID` to
`/s/<sid>/api/wake-to`). The push's JSON carries the answer as `wake`:

| `wake` | Meaning | Do |
|---|---|---|
| `alive: true` | A message reaches this session now | Nothing |
| `member: false` and a `note` | The session is not in the fleet, so nothing can wake it | Run `fleet join`; if it asks for a name, run `fleet name <name>` first. No new push: the daemon asks fleet at each question. |
| a `note` about the daemon | The daemon is older than this | Run `webcompanion install-service`, then push again |

Fleet delivers the message: the same code as a `fleet tell`, with its check in
the transcript and its fallback. The daemon only asks fleet for it
(`fleet _deliver-session`). Its log is `wake.log` in the session's state folder.

### What arrives

A message from the fleet, whose text starts like this:

    Fleet tell 412 from webcompanion: WEBCOMPANION_EVENT skill=<kind> sid=<sid> event_id=<id>

The second line repeats how to read and ack the event. Handle it exactly as the
skill's event reference says: read the event with
`webcompanion event --sid <sid> --event-id <id>`, answer it, then
`webcompanion ack --sid <sid> --event-id <id>`.

**Then ack the message too: `fleet ack 412`** (the number after `Fleet tell`).
An unacked message is sent again when the session joins the fleet again.

When the user ends the session from the IDE or the page, the message carries
`WEBCOMPANION_FINISHED skill=<kind> sid=<sid>` or
`WEBCOMPANION_CANCELLED ...`. An end Claude makes itself (`webcompanion end`)
sends nothing.

### When the session was not running

The daemon keeps the event queued whatever happens. Fleet keeps the message and
delivers it when this session joins the fleet again: `fleet respawn` does that
by itself, and a session resumed by hand runs `fleet join`. A message older
than 24 hours is not sent again.

So after a resume, catch up before anything else: for every
`WEBCOMPANION_EVENT` message not yet acked, check the event still waits
(`webcompanion event` reads it; an event already acked in `webcompanion`
needs only `fleet ack`).

### What the IDE shows

The panel is live while a message would reach this session, or while a watcher
beats. When neither is so (the session stopped), it says "Claude isn't
listening — your question is saved" and still takes questions. It goes back to
live by itself. Only a finished, cancelled or superseded session is read-only.

### A watcher still works

`webcompanion watch --kind <kind> --sid <sid>` still prints the same banners.
While a watcher beats, the daemon sends no message, so a question is never
answered twice. It is not needed, and a Monitor still ends it after 30 minutes.

## History

`web_companion/` used to hold annotate's own HTTP server: the routes,
sessions, uploads, the event stream, `ensure_server.sh` and `watcher.sh`.
Every skill moved onto the daemon, and the server was deleted along with its
tests; git history has it. The single-skill modules that sat beside it moved
into their one consumer: `anchor_migrate.py` into `skills/ask_diff/`,
`html_escape` into `skills/annotate/`, the workspace marker
reader into `skills/annotate/check_anchors.py`. `doctor.sh` moved to
`skills/annotate-doctor/`.
