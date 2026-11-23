---
name: dataflow
description: Map one feature's path through a codebase — controller, DTO, mapper, service, domain, repository, table — as an interactive diagram in the browser, where every node opens in the editor and any node can be questioned. Use when someone asks how a feature is wired end to end, what classes are involved in X, where a value goes between the API and the database, or says they cannot follow the flow. Also draws the field-level view — which field of one object becomes which field of another, as a standalone HTML file — when someone asks where a field comes from, how a DTO or payload is built, or what a mapper drops or renames. Triggered by /dataflow <class or feature> or /dataflow fields <source> → <destination>. Watcher events are WEBCOMPANION_EVENT / WEBCOMPANION_FINISHED / WEBCOMPANION_CANCELLED.
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Monitor
---

# /dataflow — one feature's path through the code, drawn

Answer "what is the data flow from the controller down to the database and
back" with a diagram instead of prose: columns of nodes, mappers hanging off
the arrows between them, every node openable in the editor, every node
questionable in place.

Use this when the honest answer is *a set of classes and how they connect*.
Use `/walkthrough` instead when the honest answer is *an ordered path to walk*.
No code is modified — this is a tool for understanding.

## Invocation

```
/dataflow <class or feature>
/dataflow <class or feature> — <the specific question>
/dataflow fields <source type> → <destination type>
```

The first two draw the **class view** below: nodes and arrows on the
webcompanion board. The third draws the **field view**, which needs no daemon
and produces one standalone HTML file: for it, **`Read`
`references/field-mode.md` and follow that instead of the rest of this file**.
Read it too when the question is about a field rather than a feature.

The argument is a seed: a class name from any layer, a feature name, or an
endpoint path. You resolve it to real classes yourself.

## On every invocation: the daemon must be running

This applies to the class view; field mode skips it. dataflow no longer ships
a server. Storage, comment threads, the event queue and the page itself all
belong to the **webcompanion daemon** — one always-on service per machine,
shared with every other skill and IDE plugin that talks to it. It is installed and kept alive by launchd (macOS) or systemd (Linux),
so there is nothing to start per session and no port to negotiate.

Confirm it is up before doing anything else:

```bash
webcompanion status
```

If that fails, stop and tell the user — do **not** try to start it yourself
(a client that auto-starts a service races every other client doing the same):

```
webcompanion doctor      # both interpreters, config, zipapp, launchd job, health
```

If `webcompanion` is not on PATH at all, the daemon has never been installed
on this machine:

```
pipx install webcompanion && webcompanion install-service
```

## Running the plugin's own code

`skills.dataflow.push` and `skills.dataflow.flow` both run out of the plugin's own tree, and `$CLAUDE_PLUGIN_ROOT` is
**not** exported into the Bash tool's shell. Reach them through
`claude-annotate`, the plugin's runner: Claude Code puts the plugin's `bin/` on
`PATH`, the runner finds the plugin root from its own location, and on a
machine with no python3 it prints a sentence naming the plugin and the fix
instead of a traceback. Each command below is self-contained — nothing has to
be resolved first or carried between Bash calls.

**There is no longer a step that creates an empty session before you explore.**
`push.py` mints the session and installs the document in the same call, and it
needs a real document to push — so the page now appears once you have traced
the code and written `dataflow.json`, in "Write the document" below, not
before.

## Trace the code

Explore, then write the document. This is the part that decides whether the
page is worth opening.

Four steps, in full in [`references/trace-the-code.md`](references/trace-the-code.md):

1. **Find both ends.** Walk up from the seed to an HTTP entry point and down to a real table, and read the migration that creates it. A repository interface is not an answer.
2. **Name every mapping, including the ones with no file.** Jackson writing a blob, an ORM flattening an embedded value or mapping an entity: each is a `mapper` node with `implicit: true`. **Never omit an implicit mapping.**
3. **Decide how many slices there are.** One path from entry point to storage is one slice; add a second only when the feature really has two independent paths, and mark where they meet with `join: true`.
4. **Write the model:** 2-5 claims a reader could be wrong about, each stating what is, not what to do.

## Write the document

`Write` the draft to your scratchpad as `dataflow.draft.json`, then validate
it — never push an unvalidated document:

```bash
claude-annotate python - <<'PY'
import json, time
from pathlib import Path
from skills.dataflow import flow
p = Path("<scratchpad>/dataflow.draft.json")
doc = json.loads(p.read_text())
doc["generated_ts"] = int(time.time())
errors = flow.validate(doc)
if errors:
    raise SystemExit("\n".join(errors))
p.write_text(json.dumps(doc, indent=2))
print(f"validated: {flow.count_nodes(doc)} nodes in {len(doc['slices'])} slices")
PY
```

A non-zero exit lists every problem at once. Fix the draft and re-run — do not
push an invalid document.

Then push it. **First push of a conversation**: this both mints the session
and installs the document as the `__flow__` item in one call:

```bash
claude-annotate dataflow.push \
  --flow <scratchpad>/dataflow.draft.json --cwd "$PWD" --title "<seed>"
```

Run this from the repository you are tracing, so `$PWD` really is the repo
root — `claude-annotate` never changes directory, and it is what makes
`skills.dataflow.push` importable regardless of where you stand.

`--cwd` **must be the repository root** — `push.py` stores it as the
document's own `cwd` field, and `dataflow.js` joins that onto each node's
repository-relative `file` to build the absolute path it POSTs to
`/api/open`. The daemon's `/api/open` does no path resolution itself: it only
accepts an absolute path already inside a session's workspace, so get `--cwd`
wrong and every "open in editor" click 403s. The output is JSON: `sid`,
`slug`, `kind`, `url`, `token`. Save `sid` and `url` — you need `sid` to arm
the watcher and to answer questions, and `url` is what you tell the user.

**Second `/dataflow` in one conversation:** it does not close the first; old sessions pile up as browser tabs. **Regenerating mid-session** (a node is missing): rewrite the draft keeping every existing node id, re-run the validation, then push again with `--slug "<slug>"` added. [`references/pushing-and-regenerating.md`](references/pushing-and-regenerating.md) says why.

### Document shape

Read [`references/document-shape.md`](references/document-shape.md) before writing `dataflow.draft.json`: the full JSON shape (`seed`, `question`, `model`, `slices`, nodes, edges, routes) and what each field means. `flow.validate` rejects a draft that departs from it.

## Generation contract

Hard rules. A diagram that breaks one is a defect, not a style choice.

- **Both ends are real.** Top node is an entry point; bottom node is a table
  or column with its migration file. Never end at a repository.
- **Never guess a line number.** Anchor only to files you `Read` this turn.
- **Every shape change has a mapper node**, implicit ones included.
- **6–14 nodes per slice.** Fewer means the question deserved a paragraph in
  terminal — answer it there and do not create a session. More means the
  question is too broad: narrow it, or build the best 14 and say what you left
  out.
- **Nodes read in request order**, not file or package order.
- **`note` earns its place.** It says what a competent reader would assume
  wrongly. A note that restates the summary is noise.
- **Signatures are verbatim.** Copy them from the file you read, with return
  type and parameter types. A signature you shortened is a signature the
  reader will not find.
- **Trace the properties that are hard, not all of them.** A route earns its
  place when following the property by hand costs several files — a rename, a
  fork, a crossing between slices. A field that keeps its name from DTO to
  column does not need one, except as one deliberate contrast so the reader
  can see what ordinary looks like. Aim for 2–6 routes.
- **Every rename is marked.** A route that walks through a rename without
  `rename: true` has hidden the single most expensive hop in it.
- **Cross-node re-pass.** Before writing, read the nodes together and fix what
  only shows up in aggregate: a mapper whose two sides do not match, an edge
  with no counterpart, a summary that repeats its neighbour, a slice whose
  claim the nodes do not support.

## Tell the user where to look

One sentence in terminal, then stop:

**"Dataflow ready — `<N>` nodes across `<M>` slices for `<seed>`: `<url>`. Click any node to expand it, ⌘ to open it in your editor, ✻ to ask me about it."**

## Arm the watcher

There is no watcher script of dataflow's own any more — the daemon ships its
own, and it emits the same banners this skill has always read. Arm it
**immediately** after telling the user, before any other work.

```bash
webcompanion watch --kind dataflow --sid "<sid>"
```

Pass that as the `Monitor` tool's `command` with `persistent: true` and a
`description` like `"dataflow-wait sid=<sid>"`.

Banners: `WEBCOMPANION_EVENT skill=dataflow sid=<sid> event_id=<id>`,
`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`.

## Handling a watcher event

When a task-notification's first stdout line is `WEBCOMPANION_EVENT`,
`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED` or `WEBCOMPANION_DROPPED`,
**`Read` `references/handling-events.md` and follow it** — it covers reading
the question, composing the answer, appending it to the node's thread, acking,
and the reply style.

## Natural completion

When the user indicates they have what they needed from the diagram —
"thanks, that answers it," moving on to something unrelated, or asking to
close it — end the session:

```bash
webcompanion end --sid "<sid>"
```

The watcher prints `WEBCOMPANION_FINISHED` and exits on its own.

## Terminal cancellation

If the user says "scrap it" / "close the dataflow" while a watcher is armed,
run `webcompanion end --sid "<sid>" --cancel`; the watcher prints
`WEBCOMPANION_CANCELLED` and exits on its own.
