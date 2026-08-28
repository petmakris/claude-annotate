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

## On every invocation: ensure the server is running

Run this once at the top of every invocation, before anything else:

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
NAME, MARKER = "claude-annotate", "skills/dataflow/ensure_server.sh"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
for skill in ("dataflow", "annotate", "walkthrough"):
    try:
        root = json.load(open(os.path.expanduser(f"~/.claude/{skill}/server.json")))["plugin_root"]
    except Exception:
        continue
    if ok(root):
        print(root); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit(f"could not locate the {NAME} plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
"$PLUGIN_ROOT/skills/dataflow/ensure_server.sh"
```

Idempotent and fast (<100 ms when already up). Do **not** use
`run_in_background: true`. If it exits non-zero, surface the stderr and stop.

## Create the session

Do this **before** exploring, so the user has a page to watch while you read.

Write the seed to `~/.claude/dataflow/.seed.txt` and the question to
`~/.claude/dataflow/.question.txt` with the `Write` tool, so neither passes
through the shell. Then:

```bash
SERVER_URL=$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/dataflow/server.json")))["url"])')
BODY=$(CWD="$PWD" python3 -c '
import json, os
p = os.path.expanduser("~/.claude/dataflow/")
seed = open(p + ".seed.txt").read().strip()
q = open(p + ".question.txt").read().strip() or seed
print(json.dumps({"cwd": os.environ["CWD"], "seed": seed, "question": q,
                  "claude_session_id": os.environ.get("CLAUDE_CODE_SESSION_ID", "")}))
')
curl -sf --max-time 90 -X POST "$SERVER_URL/api/sessions" \
  -H 'Content-Type: application/json' -d "$BODY"
```

`cwd` **must be the repository root** — it is the root `/api/open` resolves
every node path against, so a node's `file` is relative to it. The response
carries `sid`, `url`, `state_dir`, `events_dir`, `consumed_dir`. Save them.

Prior dataflows created by *this Claude session* are cancelled server-side
automatically.

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

`Write` the draft to `<state_dir>/.dataflow.draft.json`, then validate and
install it — never hand-write `dataflow.json`:

```bash
PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/dataflow/server.json")))["plugin_root"])')
PYTHONPATH="$PLUGIN_ROOT" STATE_DIR="$STATE_DIR" python3 - <<'PY'
import json, os, time
from pathlib import Path
from skills.dataflow.flow import write_flow, count_nodes
sd = Path(os.environ["STATE_DIR"])
doc = json.loads((sd / ".dataflow.draft.json").read_text())
doc["generated_ts"] = int(time.time())
write_flow(sd, doc)
print(f"wrote {count_nodes(doc)} nodes in {len(doc['slices'])} slices")
PY
```

`ValueError` lists every problem at once. Fix the draft and re-run — do not
create a second session.

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

Arm it **immediately** after telling the user, before any other work. Until the
watcher writes its first heartbeat the server has no liveness signal and falls
back to the session's age; past `NEVER_ARMED_GRACE` (30 min) it reports the
session dead on every poll.

Start it with `Monitor` (`persistent: true`):

```bash
PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/dataflow/server.json")))["plugin_root"])')
SKILL=dataflow \
SID="<sid>" \
STATE_DIR="<state_dir>" \
EVENTS_DIR="<events_dir>" \
CONSUMED_DIR="<consumed_dir>" \
CLAUDE_SID="$CLAUDE_CODE_SESSION_ID" \
"$PLUGIN_ROOT/skills/_shared/web_companion/watcher.sh"
```

Banners: `WEBCOMPANION_EVENT skill=dataflow sid=<sid> event_id=<id>`,
`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`.

## Handling a watcher event

### `WEBCOMPANION_EVENT` (a question on a node)

1. **Parse the banner** for `sid` and `event_id`.
2. **Read the payload** between `---payload---` and `---end---`:
   `anchor` is always `node:<id>`; `type` is `comment` or `reject`; `text` is
   the question; `images` is `[{token, path}]` — `Read` each before answering.
3. **Compose the answer:**
   - Read `<state_dir>/dataflow.json` and find the node by id. Its `file`,
     `line`, `summary` and `note` are the subject.
   - `Read` the anchored file around that line. `Grep`/`Glob` for whatever the
     question pulls in beyond it.
   - Other nodes' threads (`ls <state_dir>/threads/`) are READ-ONLY background.
     Never write into another node's thread.
   - 2–4 sentences, naming actual methods, fields and line numbers. Do not
     modify code.
4. **Append to that node's thread:**

   a. `Write` the answer (raw markdown) to `<state_dir>/.reply.md`.

   b. `Write` `<state_dir>/.reply.meta.json`:
   ```json
   {"anchor": "node:icm", "title": "<short headline>", "source_event_id": "<event_id>"}
   ```

   c. Run — appends the reply AND acks the event in one command:
   ```bash
   PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/dataflow/server.json")))["plugin_root"])')
   PYTHONPATH="$PLUGIN_ROOT" STATE_DIR="$STATE_DIR" \
     python3 -m skills._shared.web_companion.reply_cli --ack "$EVENT_ID"
   ```
5. **End your turn. No terminal output.** The watcher stays armed.

**When the answer needs a node that is not on the diagram**, you may regenerate
`dataflow.json` — re-run the install command with the new draft and a fresh
`generated_ts`. The page redraws itself over SSE. **Keep every existing node
id**: an id that disappears takes its thread's rendering with it. Say in the
reply what you added.

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
- **Headline title.** `title` in `.reply.meta.json`: plain text, ≤ 6 words.

## Terminal cancellation

If the user says "scrap it" / "close the dataflow" while a watcher is armed,
`POST /s/<sid>/api/cancel`; the watcher prints `WEBCOMPANION_CANCELLED` and
exits on its own.
