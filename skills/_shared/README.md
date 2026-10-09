# `skills/_shared`

Code and page assets shared by more than one skill. Nothing here is a server,
and nothing here starts one: every skill pushes to the separately installed
**webcompanion daemon** through `webcompanion_client.py`.

| Path | What it is |
|---|---|
| `webcompanion_client.py` | The one Python client for the daemon, with the `DaemonError` hierarchy and the `run_cli` wrapper every push command uses. |
| `visuals/` | The drawing tools: sequence diagrams and flowcharts, their layout (ELK through Node, with a Python fallback) and font metrics. Annotate draws them in its answers; stage and talk draw them on the stage, keyed for frames. |
| `static/` | The canonical page assets (`core.css`, `visuals.css`, fonts with Geist and JetBrains Mono for the stage, `markdown-it.min.js`, `wc-threads.js`, `wc-boot.js`, `wc-open.js`). Each skill keeps a checked-in copy in its own `static/`, because the daemon serves one folder per session; `skills/tests/test_shared_static_copies.py` fails when a copy differs from its source here. |

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

## History

`web_companion/` used to hold annotate's own HTTP server: the routes,
sessions, uploads, the event stream, `ensure_server.sh` and `watcher.sh`.
Every skill moved onto the daemon, and the server was deleted along with its
tests; git history has it. The single-skill modules that sat beside it moved
into their one consumer: `anchor_migrate.py` into `skills/ask_diff/`,
`atomic.py` and `html_escape` into `skills/annotate/`, the workspace marker
reader into `skills/annotate/check_anchors.py`. `doctor.sh` moved to
`skills/annotate-doctor/`.
