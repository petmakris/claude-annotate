# `skills/_shared`

Code and page assets shared by more than one skill. Nothing here is a server,
and nothing here starts one: every skill pushes to the separately installed
**webcompanion daemon** through `webcompanion_client.py`.

| Path | What it is |
|---|---|
| `webcompanion_client.py` | The one Python client for the daemon, with the `DaemonError` hierarchy and the `run_cli` wrapper every push command uses. |
| `static/` | The canonical page assets (`core.css`, fonts, `markdown-it.min.js`, `wc-threads.js`, `wc-boot.js`, `wc-open.js`). Each skill keeps a checked-in copy in its own `static/`, because the daemon serves one folder per session; `skills/tests/test_shared_static_copies.py` fails when a copy differs from its source here. |

## The rule

A module stays in `skills/_shared` only while at least two skills import it
from production code. With one importer it moves into that skill; with none
it is deleted. Tests never count as importers.
`skills/tests/test_smoke_engine_status.py` enforces this, and fails on any
script (`.sh`) placed here: a script belongs to the skill that runs it.

## History

`web_companion/` used to hold annotate's own HTTP server: the routes,
sessions, uploads, the event stream, `ensure_server.sh` and `watcher.sh`.
Every skill moved onto the daemon, and the server was deleted along with its
tests; git history has it. The single-skill modules that sat beside it moved
into their one consumer: `anchor_migrate.py` into `skills/ask_diff/`,
`atomic.py` and `html_escape` into `skills/annotate/`, the workspace marker
reader into `skills/annotate/check_anchors.py`. `doctor.sh` moved to
`skills/annotate-doctor/`.
