---
name: dataflow
description: Map one feature's path through a codebase — controller, DTO, mapper, service, domain, repository, table — as an interactive diagram in the browser, where every node opens in the editor and any node can be questioned. Use when someone asks how a feature is wired end to end, what classes are involved in X, where a value goes between the API and the database, or says they cannot follow the flow. Triggered by /dataflow <class or feature>. Watcher events are WEBCOMPANION_EVENT / WEBCOMPANION_FINISHED / WEBCOMPANION_CANCELLED.
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
```

The argument is a seed: a class name from any layer, a feature name, or an
endpoint path. You resolve it to real classes yourself.

## On every invocation: the daemon must be running

dataflow no longer ships a server. Storage, comment threads, the event queue
and the page itself all belong to the **webcompanion daemon** — one always-on
service per machine, shared with every other skill and IDE plugin that talks
to it. It is installed and kept alive by launchd (macOS) or systemd (Linux),
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

## Resolve the plugin root

`skills.dataflow.push` and `skills.dataflow.flow` both run out of the plugin's
own tree, and `$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash tool's
shell. Run this once per turn, before the first command that needs it — the
guard is not ceremony: without it, a machine with no python3 gets a bare
traceback instead of a sentence naming the plugin and the fix.

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.
claude-annotate is the marketplace that ships this plugin and claude-ide-review.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '
import json, os, sys
NAME, MARKER = "claude-annotate", "skills/dataflow/push.py"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit(f"could not locate the {NAME} plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
```

Two candidates, in order: every `bin/` directory on `PATH` (Claude Code adds
`<plugin-root>/bin` for both `--plugin-dir` and marketplace installs, even
when that directory does not exist), then the marketplace registry. Each
candidate must actually contain `skills/dataflow/push.py`, so the check is a
marker file rather than a directory name and survives the plugin being cloned
under any name.

**There is no longer a step that creates an empty session before you explore.**
`push.py` mints the session and installs the document in the same call, and it
needs a real document to push — so the page now appears once you have traced
the code and written `dataflow.json`, in "Write the document" below, not
before.

## Trace the code

Explore, then write the document. This is the part that decides whether the
page is worth opening.

### 1. Find both ends

From the seed, walk **up** until you hit an HTTP entry point, and **down**
until you hit a real table. Do not stop at a repository interface: a
repository is not an answer to "where does it go", the table is. Open the
migration that creates the table or column and read it.

### 2. Name every mapping, including the ones with no file

Between any two adjacent nodes, the value either keeps its shape or changes
it. Where it changes, there is a mapper — and **the mapper often has no class
of its own**:

- an explicit converter, mapper or `…ConversionService` → a `mapper` node with
  `implicit: false`, anchored at the class
- Jackson serializing an aggregate into a blob column → a `mapper` node with
  `implicit: true`, anchored at the line that configures the `ObjectMapper`
- an ORM flattening an embedded value into columns → a `mapper` node with
  `implicit: true`, anchored at the annotation
- an ORM mapping an entity to its table → same treatment

**Never omit an implicit mapping.** A reader who cannot find the second mapper
concludes the code is missing something. Naming it, and saying it has no file,
is the single most useful thing this diagram does.

### 3. Decide how many slices there are

A slice is one path from an entry point to storage. Ask whether the seed
appears in more than one:

- **One slice** — one entry point, one path down. Most features.
- **Two or more** — e.g. one path that *configures* something and another that
  *uses* it, each with its own controller, its own storage, and different
  persistence mechanics. Give each its own slice, and mark the method where
  they meet with `join: true` on the edges in both directions.

Do not invent a second slice to look thorough. Two slices is a claim: that
they are independent except at named points.

### 4. Write the model

`model` is 2–5 claims a reader could be wrong about — the things you had to
read the code to learn. Each states what **is**, not what to do. If a claim is
also visible in a node, keep it in both: the model is the summary, the node is
the evidence.

Good: "The two slices are linked only by a string. Nothing enforces it — no
foreign key, no validation on read."
Bad: "This feature has a controller, a service and a repository."

## Write the document

`Write` the draft to your scratchpad as `dataflow.draft.json`, then validate
it — never push an unvalidated document:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 - <<'PY'
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
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.dataflow.push \
  --flow <scratchpad>/dataflow.draft.json --cwd "$PWD" --title "<seed>"
```

Run this from the repository you are tracing — never from `$PLUGIN_ROOT` — so
`$PWD` really is the repo root; `PYTHONPATH` alone is what makes
`skills.dataflow.push` importable regardless of where you stand.

`--cwd` **must be the repository root** — `push.py` stores it as the
document's own `cwd` field, and `dataflow.js` joins that onto each node's
repository-relative `file` to build the absolute path it POSTs to
`/api/open`. The daemon's `/api/open` does no path resolution itself: it only
accepts an absolute path already inside a session's workspace, so get `--cwd`
wrong and every "open in editor" click 403s. The output is JSON: `sid`,
`slug`, `kind`, `url`, `token`. Save `sid` and `url` — you need `sid` to arm
the watcher and to answer questions, and `url` is what you tell the user.

**A second `/dataflow` in one conversation no longer closes the first one.**
The old per-skill server set `supersede_by_claude_session = True` so a repeat
invocation replaced the earlier session rather than leaving two armed
watchers racing. `push.py` deliberately does not pass the daemon's own
`supersede` flag (see `webcompanion_client.create_or_attach`): that flag ends
every OTHER live session of the same kind in the same repo, regardless of
which Claude conversation started it — turning it on here would also end an
unrelated concurrent conversation's dataflow trace in the same repo, which
the old flag never did. The accepted tradeoff is old sessions accumulating as
extra browser tabs rather than risking silently ending someone else's work.

**Regenerating the diagram mid-session** (the answer to a question needed a
node that is not on the diagram): rewrite the draft with the new node added —
**keep every existing node id**, since an id that disappears takes its
thread's rendering with it — re-run the validation snippet above, then re-run
the same push command with `--slug "<slug>"` added, so it lands on the page
the user already has open instead of minting a second one. `push.py` sends
`PATCH .../items {replace: true}`, which overwrites the stored `__flow__`
item wholesale, and the page redraws itself over the daemon's own live-update
stream.

### Document shape

```json
{
  "seed": "OrderShare",
  "question": "how does a shared order get from the API to the database",
  "generated_ts": 0,
  "model": [
    "Sharing is stored as a row, but the *policy* that allows it is a JSON blob — two different persistence mechanics in one feature."
  ],
  "slices": [
    {
      "id": "share",
      "title": "Sharing an order",
      "question": "what happens when the user presses Share?",
      "nodes": [
        {"id": "ctl", "layer": "api", "role": "Controller",
         "name": "OrderShareController",
         "file": "src/main/java/com/acmeshop/api/OrderShareController.java", "line": 24,
         "summary": "The only HTTP way in or out of sharing.",
         "members": [
           {"text": "public ShareResultDto share(@PathVariable long id, @RequestBody ShareRequestDto body)",
            "line": 31, "tag": "POST",
            "detail": "Converts, then delegates. Returns the **re-read** result, not the payload it was handed."},
           {"text": "private final ShareService shareService", "line": 27}],
         "edges": [{"to": "conv", "label": "converts via"}]},

        {"id": "conv", "layer": "mapper", "role": "Mapper — has a file",
         "name": "ShareDtoConverter",
         "file": "src/main/java/com/acmeshop/api/convert/ShareDtoConverter.java", "line": 18,
         "summary": "reshapes `Map<Locale,String>` ⇄ `en` / `fr`",
         "edges": [{"to": "svc", "label": "feeds"}]},

        {"id": "orm", "layer": "mapper", "role": "Mapper — no file", "implicit": true,
         "name": "Hibernate @Embeddable",
         "file": "src/main/java/com/acmeshop/domain/ShareTarget.java", "line": 12,
         "summary": "three fields flatten into three columns",
         "note": "**There is no mapper class to open here.** The ORM generates it.",
         "edges": [{"to": "tbl", "label": "produces"}]},

        {"id": "tbl", "layer": "db", "role": "Table", "name": "order_shares",
         "flag": "no foreign key",
         "file": "src/main/resources/db/changelog/changelog-14-order-shares.xml", "line": 7,
         "summary": "share_id BIGINT `PK`\nshared_with VARCHAR(255)",
         "members": [{"text": "shared_with VARCHAR(255)", "line": 11}]}
      ]
    }
  ]
}
```

Field rules:

- `file` is **repository-relative** (no leading `/`, no `..`) and `line` is a
  real line. **Every node needs both** — the only way the reader reaches code
  is `POST /api/open`, so a node without an anchor is a dead end. For an
  implicit mapper, anchor the place the framework is configured.
- `id` is unique across the **whole** document — it is the thread anchor.
- `layer` is one of `api`, `mapper`, `application`, `domain`, `infra`, `db`.
  `mapper` nodes render on the arrow between their neighbours; every other
  layer is a box in the column. Order the nodes the way the request travels.
- `role` is the small label above the name: `Controller`, `DTO`, `Service`,
  `Domain`, `Repository`, `Table`, `Mapper — has a file`, `Mapper — no file`.
- `summary` is **one line** (180 chars max, enforced): what this node *is* and
  why it is on the path. **Never a list of its members** — the members list
  them, and a summary that repeats them makes the reader read the same
  endpoints twice and the node's own claim not at all.
- `members` are the body of the node — one row each, and the reader's index
  into the file:
  - `text` is the **real signature, copied from the source**, return type
    included: `public ResponseEntity<ProposalConfigDto> saveConfigForOrganization(ProposalConfigDto dto)`,
    not `saveConfigForOrganization(dto)`. The reader is looking for the line
    they are about to open; a paraphrase is not what they will find there.
  - `line` opens that exact line. Omit it only for a row that describes the
    node rather than sitting on one line.
  - `detail` is optional markdown that **makes the row expandable in place** —
    what this method does, what it calls, what surprises. Put it on the rows
    that carry the behaviour; a row with no detail stays a one-liner.
  - `tag` is an optional badge of at most 12 characters: `GET`, `PUT`,
    `@Transactional`, `throws`, `record`, `PK`.
  - `field` is an optional slug that makes the row **addressable by a route**
    (below). Give it to rows that carry one property: a record component, a
    column, a JSON key, or the expression that moves the value at that hop.
  - **One row per endpoint, per field, per column.** Do not merge two methods
    into one row, and do not add a row that summarises the other rows.
- `routes` (optional, top level) is what makes this a property tool rather
  than a class diagram. **A route is one property's path, expressed as an
  ordered list of rows that already exist** — selecting it dims the rest of
  the board, opens the nodes it passes through, and lights those rows. There
  is no second diagram.

  ```json
  "routes": [
    {"id": "code", "label": "code",
     "title": "InteractionChannelDto.code → client_interaction_channel",
     "note": "Seven hops and **two renames** — no grep follows that.",
     "hops": [{"node": "dto",  "field": "code"},
              {"node": "icm",  "field": "code", "fork": true},
              {"node": "ci",   "field": "channel", "rename": true},
              {"node": "tbl2", "field": "channel", "destination": true}]}
  ]
  ```

  - Every hop must resolve to a member row that declares that `field`, or the
    document is rejected — a hop that highlights nothing reads as the route
    being wrong about the code.
  - `rename: true` marks the hop where **the property changes name**. Those
    are the hops no grep and no "find usages" survives, and they are the
    reason the tool exists — never leave one unmarked.
  - `fork: true` marks a hop where one property becomes several, or where the
    path splits between slices.
  - `destination: true` marks a resting place: a column, a JSON key, or a
    decision the value is consumed by.
- `edges` point at other node ids, with a verb-ish `label`. Set `join: true`
  on an edge that crosses between slices; both nodes then show a ◆ JOIN badge.
- `flag` is a short amber warning on the node header: `no foreign key`,
  `no JPA entity`, `serialized blob`.
- `note` is the paragraph a reader would otherwise get wrong. Lead with the
  claim in bold. Omit it rather than pad it.

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

### `WEBCOMPANION_EVENT` (a question on a node)

1. **Parse the banner** for `sid` and `event_id`.
2. **Read the payload** between `---payload---` and `---end---`: the daemon
   stores exactly `{anchor, text, images}` — `anchor` is always `node:<id>`,
   `text` is the question, `images` is `[{token, path}]` — `Read` each before
   answering.
3. **Compose the answer:**
   - Fetch the current document —
     `skills._shared.webcompanion_client.get_items(sid, kind="dataflow")["__flow__"]["body"]`
     — and find the node by id. Its `file`, `line`, `summary` and `note` are
     the subject.
   - `Read` the anchored file around that line. `Grep`/`Glob` for whatever the
     question pulls in beyond it.
   - Other nodes' threads —
     `skills._shared.webcompanion_client.get_threads(sid, kind="dataflow")`
     — are READ-ONLY background. Never write into another node's thread.
   - 2–4 sentences, naming actual methods, fields and line numbers. Do not
     modify code.
4. **Append to that node's thread, then acknowledge the event:**

   a. `Write` the answer (raw markdown) to your scratchpad as
      `dataflow-reply.md`.

   b. Run — appends the reply to the node's thread:
   ```bash
   PYTHONPATH="$PLUGIN_ROOT" python3 -c "
   import pathlib
   from skills._shared import webcompanion_client as wc
   text = pathlib.Path('<scratchpad>/dataflow-reply.md').read_text()
   wc.append_thread('<sid>', 'node:<id>', text, kind='dataflow', role='agent',
                    source_event_id='<event_id>', title='<short headline>')
   "
   ```

   c. Then, and only then, acknowledge the event — or the daemon re-emits it
      three times, thirty minutes apart, and finally drops it:
   ```bash
   webcompanion ack --sid "<sid>" --event-id "<event_id>"
   ```
5. **End your turn. No terminal output.** The watcher stays armed.

**When the answer needs a node that is not on the diagram**, you may
regenerate the document — see "Regenerating the diagram mid-session" under
"Write the document" above. Say in the reply what you added.

### `WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED`

Terminal: *"Dataflow for `<seed>` closed."* / *"…cancelled."*

### `WEBCOMPANION_DROPPED`

An event went unanswered through every re-emit. Say so plainly: *"A dataflow
question went unanswered and was dropped — please re-ask it on the node."*

## Response style guide

- **Self-contained synthesis.** Each reply answers *all* questions asked on
  that node so far; the page renders only your most recent reply.
- **Short.** 2–4 sentences in most cases.
- **Code-aware.** Name the actual variables, methods and lines.
- **Cite nodes by name** when the answer lives elsewhere on the diagram.
- **Honest uncertainty.** Name exactly what you would need to know.
- **Headline title.** The `title` passed to `append_thread`: plain text,
  ≤ 6 words.

## Terminal cancellation

If the user says "scrap it" / "close the dataflow" while a watcher is armed,
run `webcompanion end --sid "<sid>" --cancel`; the watcher prints
`WEBCOMPANION_CANCELLED` and exits on its own.
