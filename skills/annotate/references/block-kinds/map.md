# `kind: "map"` block

Read this when you've decided (from the kind menu in SKILL.md) that a block
should be an architecture map, and you need the contract to emit or rewrite it.

## When a map is the right block

Use a map to show how a system is built:

- the parts of a system and what each one holds;
- where each caller comes in (a screen, an API, an assistant);
- where the rules live, and which paths share them.

A map can also show one request's path through those parts. The reader
presses **Follow the request** and the path lights up one step at a time.

**Do NOT use a map for:**

- A request over time, where the order of the calls is the point — use a
  `kind: "sequence"` block.
- Branching logic: guards, validation, success and error outcomes — use a
  `kind: "flowchart"` block.
- Two or three parts with one arrow between them — a sentence says it.

One map per system. Frame it with a short prose block.

## Block shape

    {"id": "section-N", "kind": "map", "spec": {
      "title": "<the claim, a sentence with a verb>",
      "subtitle": "<optional>",
      "columns": ["Who asks", "Entry point", "The services"],
      "boxes": [{"id": "chat", "col": 0, "row": 0, "tone": "blue", "name": "A person in the chat",
                 "lines": ["\"I paid the bill\""], "b": 1, "r": 1}, ...],
      "zones": [...], "arrows": [...], "legend": [...],
      "captions": {"build": [{"title", "text"}, ...], "route": [{"title", "text"}, ...]}
    }}

The full spec contract — boxes on the grid, children, lines, zones, arrows
and their paths, the build steps (`b`), the route steps (`r`, route arrows
with a badge `n`), the four tones and the captions — is in the guide `vz.md`, in the plugin's
`docs` folder (`claude-annotate root` prints the plugin's folder): § Map spec
and § Rules for every diagram. Read it before writing a map; it
is not repeated here.

On this page:

- The part's heading shows `title`, and the drawing leaves it out. The
  `subtitle` shows under the heading as plain text.
- `captions` show one at a time under the drawing while the reader steps
  through it. In a Confluence page they are written out as a numbered list
  under the picture.
- A spec the renderer refuses shows a small "diagram render failed" pill with
  the reason in its tooltip. Fix the spec and push again.

## Check before you push

Draw the spec and check it, as for any map:

    root="$(claude-annotate root)"
    python3 "$root/tools/vz.py" svg spec.json -o map.svg
    uv run "$root/tools/vz_check.py" check map.svg

Push only at 0 faults. `points` on an arrow are canvas coordinates of the
drawing with its title, which is how the page lays it out too.

## Rewriting a map after a comment

A map is commented as a whole, from its heading, so comments arrive with
`step_id: null`. Follow `references/handling-events.md` § "Diagram
block-rewrite contract", with box and arrow ids where it says step ids.
Persist with `blocks.update_spec_block(doc, block_id, new_spec)`.
