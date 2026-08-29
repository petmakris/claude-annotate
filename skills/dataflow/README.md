# dataflow

One feature's path through a codebase, drawn. `/dataflow <class or feature>`
traces the seed up to an HTTP entry point and down to a real table, then serves
an interactive board: columns of nodes per slice, mappers hanging off the
arrows between them.

Everything a reader needs is **inside a node** — path, members, edges, the
gotcha, the thread. There is deliberately no separate class-reference section:
hopping away from the diagram to read about it is the thing this replaces.

- Skill contract: `SKILL.md`
- Server: `server.py` (handlers over `skills/_shared/web_companion`), fixed port
  3100, state root `~/.claude/dataflow/`.
- Page: `static/dataflow.css` + `static/dataflow.js`. The board is rendered
  client-side from `dataflow.json` so that one renderer also handles the redraw
  when the document is regenerated mid-session.
- Per-session state lives in `<project>/.claude/dataflow/<sid>/state/`:
  `dataflow.json`, `threads/` (one file per node anchor), `events/`,
  `consumed/`.

## Three things it does that a static diagram cannot

**Opening code.** Every node carries a repository-relative `file` and a `line`,
and the page opens it through `POST /api/open` — the server runs
`idea --line N <file>` itself. The `jetbrains://` scheme had to guess the IDE's
project name from a directory basename and failed silently when it guessed
wrong; a local process does not have that problem. The session's `cwd` is the
repository root, which is what every node path resolves against.

**Asking about a node.** `✻` posts to `/s/<sid>/api/submit` with
`anchor: "node:<id>"`. That queues an event, the watcher wakes Claude, and the
answer is appended to that node's thread and pushed back over SSE. The answer
appears in the node, not in a terminal.

**Tracing one property.** The class board above answers "which classes are
involved"; a route answers "where does this one field go, and what is it
called when it gets there" — the multi-file hunt that survives no grep once a
value is renamed. A route is not a second diagram: a member row that carries
a `field` slug is already addressable, and a route is just an ordered list of
`(node, field)` hops over rows that already exist. Selecting one (via the
"trace a field" bar, or the `⇢ trace` button on any routable row) dims the
board, opens the nodes on the path, and lights those rows — marking every
**rename** (the property changes name), **fork** (one value becomes several,
or the path splits), and **destination** (where it comes to rest).

## The document

`dataflow.json` is written by Claude and rendered by the server. The server
knows nothing about Java, Spring, DDD or layering — `flow.py` validates
structure only, and `SKILL.md` owns the tracing method. That is what keeps the
skill usable on a codebase nobody anticipated.

Node ids are unique across the whole document because a thread anchor is
`node:<id>`; per-slice ids would make two nodes share one thread.

`routes` is optional and lives at the top level, alongside `slices` — it
never duplicates a node or a member, only points at ones that already exist.
A hop naming a `(node, field)` that no member declares fails validation
rather than rendering, since a hop that highlights nothing reads as the route
being wrong about the code rather than about itself.

Run the tests from the repo root:

```bash
python3 -m pytest skills/dataflow/tests/ -v
```
