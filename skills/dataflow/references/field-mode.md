# dataflow — field mode: where does this field come from?

Read this for `/dataflow fields <A> → <B>`, or whenever the question is about
a field rather than a feature, and follow it instead of the class-view steps
in SKILL.md. Field mode needs no daemon, no watcher and no board.

The class view answers *which classes*; it cannot answer *which field becomes
which* once a mapper drops some fields, renames others and collapses four into
one. Field mode draws that: the records side by side, one arrow per field
mapping, on a full-page canvas where hovering a field lights its whole route and
dims the rest.

Use it for `/dataflow fields <A> → <B>`, or when the question is about a field
rather than a feature. If the mapping is one-to-one with matching names, write
a sentence instead; the value is the shapes prose hides — a fan-out, a fan-in, a
dropped field, a rename that loses meaning.

Field mode does **not** use the daemon, the watcher or the board. Its
deliverable is one self-contained HTML file.

## Steps

1. **Read the real code.** Every field must exist. Open the records and the
   mapper; do not infer names from a payload alone — the JSON name is often not
   the source name, and that difference is usually the finding.
2. **Write a spec** as JSON. The examples ship in the plugin, under
   `"$(claude-annotate root)/skills/dataflow/fields/"`:
   `fields/example-order.json` is a complete worked spec (a fan-out, a fan-in, dropped fields, a rename),
   `fields/example-bypass.json` adds wires that skip columns, and
   `fields/example-context.json` and `fields/example-sketch.json` add values that
   come from the context rather than an argument; copy one. List cards and edges
   in any order: nothing in the spec places a card.
3. **Render it with the check**, to a file named after what it maps, somewhere
   the user will find it — not a temp directory:
   ```bash
   claude-annotate dataflow.fields.render spec.json --check order-provenance.html
   ```
   This writes the page, a screenshot beside it (`order-provenance.png`), and
   prints the layout report. It needs Playwright; without it, it says so and
   exits 2.
4. **Look before you hand over.** Read the PNG and the report.
   - Five targets must be 0, and the command exits 1 when one is not:
     `behind_card`, `label_overlaps`, `source_slack`, `improvable_swaps` and
     `loose_sources`.
   - A nonzero `behind_card`, `source_slack`, `improvable_swaps` or
     `loose_sources` is an engine regression, not a spec problem: hand the file
     over, say which target failed, and leave the spec alone.
   - A nonzero `label_overlaps` is the one target you fix, with a shorter label
     or note (step 5).
   - The rest (`crossings`, `dock_inversions`, `max_dock_climb`, `copy_bend`,
     `straight` of `hops`, `travel`, `max_steepness`, `detour`, `width`,
     `height`) are for judgment. Compare them with what you see.
   - In the picture, look for a fan you cannot tell apart, a label sitting on
     the wrong wire, a figure too wide to read.
5. **Fix through the spec, never the coordinates.** The tools, in the order to
   try them:
   - `"rows": "follow"` on a card whose field order means nothing (method
     arguments, wire parameters), so its wired rows reorder against their
     wires. Never on a record whose declaration order matters.
   - A shorter `label` or `note` where one still collides.
   - Splitting the figure into two specs.
   - `"lane": "above"` or `"below"` on an edge that skips columns, only for a
     deliberate side channel: a long wire already runs between cards on its own.
   Re-render with `--check`. Stop after **three rounds**, whether or not every
   judgment measure improved.
6. **Hand over the file.** Say what the shapes are in a sentence or two, give
   its location, and say what you adjusted after the check, if anything. Do not
   paste the HTML, and do not re-describe the diagram in prose.

## The page

The diagram fills the window. Drag or two-finger scroll pans; pinch or ⌘-scroll
zooms toward the pointer; double-click zooms in; `F` fits the diagram, or the
lit path when a field is selected; `1` is 100%. A minimap and zoom buttons sit
bottom-right. The title chip's **About** button opens the `lede`, the `caption`
and the sources table. The legend is a strip at bottom-left.

## The file stays offline

`render.py` emits a complete document with **no external references at all** —
no webfont, no CDN, no script src, no image URL — so it renders the same when
emailed, opened on a plane or behind a proxy. Anything added to the renderer
must keep that true; `skills/dataflow/tests/test_fields.py` enforces it.

Nothing is hand-placed. `render.py` validates the spec and inlines it with the
engine: the three parts of `fields/engine/` (`validate.js`, `layout.js`,
`view.js`), joined in that order. The engine computes every coordinate from the
cards and wires alone, without measuring the page. The diagram is read from a field back
to its origin, and the engine guarantees nine rules for that reader:

- **R1.** A wire spans as few columns as the stages allow; a source sits one
  column before the nearest card it feeds.
- **R2.** A column is ordered by crossings first, then by the rows its items
  feed: no two neighbours can swap to remove a crossing.
- **R3.** A 1:1 copy (one wire out of its row, one into its target) is drawn
  straight unless the stacking forbids it.
- **R4.** A source sits as level with the row it feeds as its column allows,
  otherwise on that row's side of whatever holds the height.
- **R5.** A long wire runs flat across the columns it skips, between cards if
  that is where the order puts it, never behind one.
- **R6.** Wires that share a row get their own ports, ordered by their other
  ends, each at least 8 px inside the row.
- **R7.** A card is one rigid record: its rows touch, in declared order unless
  it says `"rows": "follow"`.
- **R8.** Spec order and `slot` place nothing; only separate flows stack in the
  order of their first cards, and a card without wires joins its spec
  neighbour's column.
- **R9.** The same spec always draws the same picture. Edit the spec and
  re-render; never adjust coordinates.

## Spec format

```jsonc
{
  "title":   "Order Field Provenance",     // the page name, 2-4 words
  "eyebrow": "checkout service",           // optional kicker
  "lede":    "…",                          // one paragraph, HTML allowed; in About
  "caption": "…",                          // name the shapes; in About
  "legend":  [ { "tone": "raw", "text": "minor units, never converted" } ],
  "cards": [                               // any order: columns come from the wires
    { "id": "entity",
      "stage": "ENTITY", "name": "Order", "sub": "module · OuterClass",
      "tone": "accent",                    // optional frame colour
      "rows": "follow",                    // optional: wired rows follow their wires, the rest trail;
                                           // "real" (the default) keeps declaration order
      "fields": [
        { "id": "total", "label": "totalCents", "tone": "raw" },
        { "id": "notes", "label": "internalNotes", "muted": true },
        { "id": "id",    "label": "id", "strong": true }
      ] }
  ],
  "edges": [
    { "from": "entity.total", "to": "dto.total",
      "tone": "raw", "label": "drawn beside the wire", "note": "a second, quieter line",
      "lane": "below" }                    // optional, rare: a deliberate side channel for a wire
  ],                                       // that skips columns, above or below its flow
  "sources": { "head": ["Stage","File","Detail"], "rows": [["…","…","…"]] }
}
```

Cards never feed each other in a loop, and a field never feeds its own card. If
a value comes back, draw the object twice, before and after. An older spec may
still carry `slot` on its cards or a `gaps` table: both are ignored, with a
one-line note on stderr.

**Tones** (`raw`, `group`, `accent`, `muted`) encode a property that repeats —
which unit a number is in, which side of a boundary it sits on — never
decoration. Say what each means in `legend`.

**`muted: true`** marks a source field the mapper does not carry forward. It
renders faded with no arrow leaving it. Look for these deliberately.

**There is no notes section.** Words go in three places only: the `lede`, the
`caption`, and the drawing itself (an edge `label` or `note`, a field `tone`, a
`legend` line). A fact lives on the one wire or field it is about.

## What makes one worth reading

- **Real fields.** One invented field and the reader stops trusting the drawing.
- **Real order, unless the order means nothing.** Use `"rows": "follow"` only
  where a reader would not miss the declared order.
- **Name the shapes in the caption.** "Three amounts converge on one `total`" is
  the finding; the arrows are the evidence.
- **Label a fan-in** with what tells the sources apart afterwards.
- **Stop at the boundaries that matter** — the hops where a value's name, shape
  or meaning changes.

## Failure modes

| Symptom | Cause |
|---|---|
| `KeyError: … has no field 'x'` | an edge names a field id no card declares |
| `ValueError: cards feed each other in a loop: …` | a value comes back to a card it left — draw the later stage of one of them as its own card |
| `ValueError: edge … stays inside card …` | an edge joins two fields of one card |
| `ValueError: edge … appears twice` | the same edge is listed twice |
| `ValueError: … lane must be one of` | `lane` is not `"above"` or `"below"` |
| `--check` exits 1 | a target is nonzero — `label_overlaps`: shorten a label or note (step 5); any other: an engine regression, hand over and say so |
| `--check` exits 2 | Playwright or its Chromium is missing (the message names the install command) — hand over the unchecked file and say so |
| `--check` exits 3 | the engine threw on this spec; the message is the browser's error — fix the spec, not the layout |
| `ValueError: card … has no fields` | a card declares no fields |
| Wires cross confusingly | `"rows": "follow"` on a card whose order means nothing, or split the figure into two specs |
