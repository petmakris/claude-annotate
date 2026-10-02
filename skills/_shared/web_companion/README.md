# `skills/_shared/web_companion`

Two things live in this package, and only one of them runs.

## The shared library — live, imported by five skills

| Module | Imported by |
|---|---|
| `atomic.py` | `annotate/blocks.py`, `annotate/confluence/state.py`, `walkthrough/steps.py`, `paths.py` |
| `anchor_migrate.py` | `ask_diff/sync.py` |
| `paths.py` | `annotate/check_anchors.py` |
| `templates.py` | `annotate/render.py` |
| `threads.py` | `ask_diff` tests |

These are ordinary dependencies. Change them with the usual care.

## The server — retired, and nothing launches it

`server.py`, `handlers.py`, `stream.py`, `static_serve.py`, `sessions.py`,
`events.py`, `uploads.py`, `cleanup.py`, `reply_cli.py`, `static/`,
`ensure_server.sh` and `watcher.sh` were annotate's own HTTP server. Every
skill now pushes to the **webcompanion daemon** instead — see
`skills/annotate/push.py`, which reads `~/.claude/webcompanion/config.json` and
talks to the daemon over HTTP. Nothing in this repo starts the server in this
package. Its 24 test files (213 tests) still pass, against code no user reaches.

**It is kept deliberately, and this file is the decision.** It is the only
readable description of the protocol the daemon implements — routes, the write
gate, the event queue, the anchor resolution — and annotate's client still
speaks that protocol through `compat.js`. Deleting it would also mean editing
three audit skills that describe it (`audit-engine-boundary`,
`audit-http-surface`, `audit-code-health`) and a shelf of design docs that cite
it as the reference.

### What that means in practice

**Do not fix bugs in the server half.** A bug there costs a user nothing, and
the effort is real: a probe-retry fix was once ported into `static/core.js`
here, carefully, for code that cannot run. If you find one, note it and move
on — or delete the server half, which is the honest alternative to maintaining
it.

**If you revive it**, this file is wrong and should say so. `test_smoke_engine_status.py`
asserts the live/dead split above, so wiring the server back up will fail that
test and bring you here.
