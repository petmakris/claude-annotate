---
name: specimen
description: Use when the user cannot follow what data a Java class or method operates on, asks what an object actually holds, asks for an example of a class populated with real values, says a class or a line of code makes no sense to them, or names a type and asks what is inside it. Triggered by /specimen <ClassName>. Watcher events are WEBCOMPANION_EVENT / WEBCOMPANION_FINISHED / WEBCOMPANION_CANCELLED.
how: "Reads a class's shape from Java source by resolving every type through its own import block, populates one instance with real identifiers and chosen numbers, and serves it as a local page where any field can be questioned."
argument-hint: "<ClassName> [--worktree <path>]"
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Monitor
---

# /specimen — one populated instance of a Java type

Show a row, not a declaration. Use this when someone cannot follow what data a
class holds. Use `/dataflow` instead when the question is which classes connect
to which.

No code is modified. This is a tool for understanding.

## 1. Pick the checkout

The checkout is the repository the session is working in (`git rev-parse
--show-toplevel`), or the path given with `--worktree`. Shapes differ between
branches, so never guess between two checkouts: if it is unclear which one is
meant, ask.

`$SCRATCH` below is this session's scratchpad directory.

## 2. Load the project profile, if there is one

A **profile** carries what this skill cannot know about a particular codebase:
how to pick among several checkouts, which types look alike but are not, and a
capture of real values for types that have no source on this machine. Profiles
live outside this plugin, so a project's specifics never ship with it.

Look in each directory of `$SPECIMEN_PROFILES` (colon-separated), falling back to
`~/.config/specimen/profiles`, for a subdirectory named after the checkout's
repository directory — `basename "$(git rev-parse --show-toplevel)"`. If one
exists:

- **Read its `profile.md` now.** Its rules are about this codebase and override
  the defaults below wherever they conflict — for example a profile may say how
  to choose the checkout in step 1.
- **Its `leaves.json`**, if present, is the capture that step 4 fills leaf
  types from, and that step 5 passes as `--leaves`.

No profile is normal. Then there is no capture: every leaf type's fields stay
`{"kind": "null"}` or unset, and nothing on the page is tagged `captured`.

## 3. Locate the skill, then extract the shapes

`claude-annotate` (the plugin's `bin/` runner, on PATH) finds the plugin root and checks
for python3 itself:

```bash
claude-annotate specimen.extract_types <ClassName> \
    --worktree <checkout> --out $SCRATCH/types.json
```

Exit codes: `0` ok. `2` the name matched several classes, or none, or `--worktree` is
not a directory — it prints which. Ask which class, do not pick; a large codebase
often has several classes with one simple name. `3` the provenance check in
`emit.py` refused the payload, because some type reached the page without a
source file or some field without a line. That is a bug in the extractor, not in
the checkout; report it rather than working around it.

Read `$SCRATCH/types.json`. A type's `source` and each field's `line` are what the
page's `⌘` button opens in the editor, through the daemon's `/api/open`. Each type has
one of the four `kind`s `typegraph.py::classify` emits:

- `"data"` — a class this tool read from source. Its `fields` are what step 4
  populates.
- `"behaviour"` — a class this tool also read from source, whose fields are
  collaborators (services, repositories, properties) rather than data. The entry
  class of a service page is normally this. Its fields get rows and anchors like any
  other, and they normally carry no value; the data types its methods and nested
  classes mention are the sections worth populating.
- `"leaf"` — a type with no source in this checkout (it comes from a jar or another
  repository). Its values come from the profile's `leaves.json`, never invented.
- `"unhandled"` — a source file was found but no declaration in it matches the name.
  It stays on the page unhandled; do not guess a value for it either.

`references/page-format.md` describes what each column, token and section on the
finished page means. Read it if a reader asks what something on the page is saying.

## 4. Write specimen.json

The value-node schema, fixed by `document.py` and `build_items`:

```json
{
  "root": "com.example.analytics.model.AnalyticsResult",
  "instance": {
    "kind": "object",
    "type": "com.example.analytics.model.AnalyticsResult",
    "fields": {
      "charts": {
        "kind": "list",
        "element": "com.example.analytics.model.AnalyticsResult$Chart",
        "items": [
          {
            "kind": "object",
            "type": "com.example.analytics.model.AnalyticsResult$Chart",
            "fields": {
              "groupingClassificationId": { "kind": "scalar", "value": "54", "provenance": "captured" },
              "riskContributions": {
                "kind": "list",
                "element": "com.example.analytics.model.AnalyticsResult$CategoryRiskContribution",
                "items": [
                  {
                    "kind": "object",
                    "type": "com.example.analytics.model.AnalyticsResult$CategoryRiskContribution",
                    "fields": {
                      "category": { "kind": "scalar", "value": "1295", "provenance": "captured" },
                      "current": {
                        "kind": "object",
                        "type": "com.example.analytics.service.RiskContribution",
                        "fields": {
                          "totalContribution": { "kind": "scalar", "value": "0.0412", "provenance": "chosen" }
                        }
                      },
                      "proposed": { "kind": "null" }
                    }
                  }
                ]
              }
            }
          }
        ]
      },
      "totalWealthAfter": { "kind": "null" }
    }
  }
}
```

Every level in a specimen must be a level the real class actually has, checked
against `extract_types` output: in the example, `charts` is a `List<Chart>`,
`Chart.riskContributions` a `List<CategoryRiskContribution>`, and
`CategoryRiskContribution.current` is declared `RiskContribution` — an object with
its own fields, not a number. Skipping a level, or giving an object field a scalar,
puts values under `(type, field)` pairs that do not exist and the rows they belong to
stay empty.

Four value-node kinds: `object` (has `type` and `fields`), `list` (has `element` and
`items`), `scalar` (has `value` and `provenance`), `null` (nothing else — a fact,
not an absence). A field left out of `fields` is not the same as `{"kind": "null"}`:
it renders as an unset dash (`specimen-unset`), which tells the reader nothing,
while an explicit null renders as a visible `null` badge and is the point of the
page. So the populator rule is:

**Every scalar field of every rendered type needs a value.** Walk `types.json` and
give every field of every `data` type a node — a `scalar` if it has one, `{"kind":
"null"}` only where the field is genuinely meant to be absent. Never leave a field
out because filling it felt like extra work; an unset dash reads as "nobody looked,"
not as a fact about the class.

**Real identifiers, chosen magnitudes.** Identifiers of leaf types — ids, codes,
names — come from the profile's `leaves.json`, tagged `provenance: "captured"`, using
the values that file actually contains. Everything else — weights, amounts, dates,
free text — is tagged `provenance: "chosen"`. A field whose declared type is a leaf
with no captured instances gets a chosen value of the right shape, never a
`captured` one.

**An uncaptured leaf stays uncaptured.** Before filling in any leaf field, run
`missing_leaves(types_payload, leaves)` — `skills/specimen/leaves.py` — which reports a
leaf both when its key is absent from `leaves.json` and when it is present with an
empty `instances` list. Anything it names is missing: leave its fields
`{"kind": "null"}` or unset, whichever is true, but never invent a
plausible-looking value and tag it `"captured"`. A `captured` tag is a claim that the
value came from the real system; making that claim for a value you typed is the one
thing this tool must never do.

**Small enough to read.** Three items, not the forty-seven a real dataset holds. This is a
teaching instrument, and a real dataset is not one.

**Put the interesting case in on purpose.** If a field is `@Nullable`, at least one
instance must carry `{"kind": "null"}` for it. That row is why the reader opened the
page.

**The page is the tree you write here.** It draws `instance` node by node: an
object-valued field expands into that object's own fields underneath it, and each
item of a list is its own node. So a null on the first of five items sits on the item
that holds it, and a category id repeated across sibling lists is visibly the same id in
all of them. Whatever you write in this file is what the reader walks.

**Shape comes from `types.json`, not from what you filled in.** An object node lists
every field its type DECLARES. A field you leave out of `fields` is drawn as an unset
dash beside its declared type, which reads as "nobody looked" — that is why the rule
above says to give every scalar field a node.

**One anchor per (type, field), shared by every node of that type.** A comment
attaches to `<fqn>#<field>`, never to a list position, because a position is what the
next push can invalidate. Three `Contributor` items therefore show three separate
`proposedRiskContribution` rows carrying one comment thread between them. Answer a
question about a field knowing it may have been asked from any of those rows.

Keep invented numbers internally consistent: allocations summing to `1.0000`, and the
same category id appearing across sibling lists.

## 5. Push and hand over the URL

```bash
claude-annotate specimen.push \
    --types $SCRATCH/types.json --specimen $SCRATCH/specimen.json \
    --cwd <checkout> [--leaves <profile>/leaves.json]
```

On success it prints the session as JSON — `sid`, `slug`, `url` — and exits `0`.
Any failure exits `1` with one `specimen push: ...` line on stderr, the same as
every other skill's push. If that line says `webcompanion` is not configured or
not answering, say so and stop. Do not write an HTML file instead — a page you
cannot ask questions of is not what was asked for. If the daemon answered and
refused the push, the line carries its reason, and that is the thing to fix, not
to retry around.

Pass `--leaves` whenever the specimen uses captured values: that file's `captured`
timestamp and `deployment` string are rendered in the page header, so the reader can
see where the real identifiers came from.

The page opens as a tree. Appending `#table` to the URL opens the same document as one
table per type instead, a row per instance and a column per field — the view for reading
three contributors under each other. A field whose value is an object is a column that
opens into its own fields, to any depth, so a value three levels down still lands in a
real column; `#table/all` opens every one of them. Say so when handing the URL over,
along with the fact that `✻` is how a question gets asked, on a row in the tree and on a
column header in the table; clicking a row or a header itself only opens and closes it.
Every type name on the page is a pill that copies its fully qualified name, with the
nested-class `$` written as a dot, which is the form an IDE's class search accepts.

Give the person the `url`. Then arm a watcher on the session's `sid` (printed beside it
in the same JSON) and answer questions as they arrive:

```bash
webcompanion watch --kind specimen --sid <sid>
```

Run that inside `Monitor`, since each event line is a question landing on a field's
comment thread — the anchor is `<fqn>#<field>`, the same anchor the field's row
carries as `data-wc-anchor`. A notification arrives as `WEBCOMPANION_EVENT` /
`WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED`; on `WEBCOMPANION_EVENT`, read
what was asked and reply on that anchor:

```bash
webcompanion reply --sid <sid> --anchor <fqn>#<field> --text <path-to-answer-file>
```

If the code the specimen describes changed and the page is stale, re-run
`extract_types` and `push`. Know what superseding does before you do: `push.py`
asks for it on every push, and it **closes any other live `specimen`
session for the same `--cwd`**, taking that session's comment threads with it. That
is the right behaviour for a re-push of the same page. It is the wrong behaviour if
someone is still reading a specimen of a different class in the same checkout — their
page dies. If that is a risk, ask before re-pushing.

## 6. Answer questions on the page

After handing over the URL, arm the watcher and keep answering until the page is
finished or cancelled. The full procedure is in `references/answering.md`. Read it
before handling the first event.

The short version: parse the banner, read the payload's anchor, call
`skills.specimen.answer.context_for`, read the source line it names, reply with
`webcompanion reply`, `ack` the event, and keep reading the same watcher's output
for the next one.

## What this does not do

It never parses method bodies. Types are found through fields and method signatures,
walking into nested classes and nested types. So a page for a service can show types
some of its methods never touch, and a type a body builds locally and holds in no
field is missed. Say so if it bears on the question.

It shows shape, not behaviour. What a method *does* to the data is not on the page.
