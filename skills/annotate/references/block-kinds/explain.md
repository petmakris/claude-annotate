# Block kind: `explain`

A snippet where **the explanation rides on the code**. Spans are marked in
place and their labels hang off the exact columns they describe; a group of
lines gets a bracket. There is no prose column — this kind exists to delete
the read-the-prose-then-find-the-code ping-pong that a `markdown` block plus a
`code` anchor forces on the reader.

The pane **walks**: it opens on note 1 with that note's spans marked and the
rest of the snippet stepped back, and the reader moves with `‹ ›`, the arrow
keys, or by clicking a note's numbered pin. So the order you write the notes
in is the order they are read in — see "The notes are a sequence" below.

## When to use
- You are explaining **how a specific piece of code works**, and the claims
  are about named spans: this field, that call, this branch.
- Several things on one line need saying — common in Java, where a line is
  often `ofNullable(this.x).map(...)`.
- A step in an argument is "these three lines, together".

## When NOT to use
- The code is incidental and the prose is the point → `markdown` with a `code`
  anchor, which is still the right shape for "here is my argument, and here is
  the file it is about".
- You are showing code without explaining any part of it → a fenced block in
  `markdown`.
- The shape of a flow, not the text of it → `flowchart`.
- More than ~25 lines. This kind annotates a snippet, not a file; quote the
  part the claims are about.

## Block shape

    {"id": "section-N", "kind": "explain", "spec": {
      "project": "portfolios",                  // optional, tints the header pill
      "file": "ValuedPosition.java",            // optional
      "line": 261,                              // optional, the snippet's first line
      "lang": "java",                           // optional, for syntax highlighting
      "code": "private Amount adjust(...) {\n    return ofNullable(this.price)\n}",
      "notes": [
        {"line": 2, "span": "this.price", "label": "**reference currency** — already FX-converted"},
        {"spans": [{"line": 3, "span": "p.multiply(qty)"},
                   {"line": 9, "span": "p.multiply(qty)"}],
         "label": "**the same multiplication**, both times"},
        {"lines": [2, 4], "label": "**one computation** — the three lines only mean anything together"}
      ]
    }}

`line` numbers in `notes` are **1-based within `spec.code`**, not file line
numbers. The snippet is the coordinate system.

## Quote the span; never measure it

`span` is **a literal substring of that line**, copied from the code. Do not
compute columns — there is no `col`/`len` field, deliberately. A column is
something nothing checks at authoring time, so an off-by-three paints a
confident underline under the wrong tokens and the page looks correct.

- A span that does not occur on its line is **refused at push**, and the block
  renders an error naming the line and the quote. Fix the spec and push again.
- A span that occurs **more than once** on its line is also refused. Add
  `"nth": 2` to say which one, or quote more of the line until it is unique —
  prefer the second, since it is self-describing.
- Tabs are expanded to 4 spaces before anything is measured, so a tab-indented
  snippet needs nothing special.

## Showing the number, not just the claim

A place — a `span`, or one entry inside `spans` — may carry a `"value"`: the
concrete number this example produces at that exact point. It renders as a
small chip immediately after the underline, escaped the same restricted
markdown as `label`, and it stays visible in every mode, walked or static —
unlike the step counter, it isn't restating something shown elsewhere.

    {"line": 2, "span": "priceInReferenceCurrency", "value": "166.62 × 0.944573 = 157.36",
     "label": "**reference currency** — already FX-converted"}

This is for a reader **tracking one worked example through the code**, not
for documenting the field in general — a `value` is the number *this* capture
produced, the same way the rest of the block is grounded in one real run. Skip
it on a note that is explaining shape rather than following a number.

A `spans` note gives each place its own `value` — the same claim, ordinarily
two different numbers (a loop, or the same computation in two currencies):

    {"spans": [{"line": 3, "span": "p.multiply(qty)", "value": "100 × 1 = 100"},
               {"line": 9, "span": "p.multiply(qty)", "value": "100 × 1 = 100 (EUR)"}],
     "label": "**the same multiplication**, both times"}

`value` never substitutes for `label` — a chip with no sentence behind it is a
number with no claim, which is the ping-pong this kind exists to remove, just
walked in the other direction.

## One note, several places

A claim is often true in more than one place — the same call in two methods,
the same field read twice. Write it **once**, with `spans`:

    {"spans": [{"line": 3, "span": "p.multiply(qty)"},
               {"line": 9, "span": "p.multiply(qty)"}],
     "label": "**the same multiplication**, both times"}

Every entry is quoted and refused exactly as a single `span` is, and each one
is marked on its own line. The label is printed once, under the first; the
others are underlined and silent. Do not write "both times" while marking one
of them — that is a claim the pane does not back up, and it is the reader who
has to go looking for the second.

A note quotes `span` **or** `spans`, never both. Use `nth` inside a `spans`
entry the same way you would outside one.

## The notes are a sequence

The pane walks them in the order you write them, so `notes` is **reading
order, not file order**. An explanation that starts at the second method and
works back is written that way; do not re-sort by line number to look tidy.

Each step is titled by its label's bold lead-in — `**reference currency.** …`
gives *"step 2 of 3 — reference currency"*. That is lifted from the label, so
there is nothing extra to write and nothing that can drift out of step with
the sentence under it. A label with no bold lead-in still walks; it just has
no name in the counter, which is one more reason to lead with one.

Keep a block to the number of stops an argument actually has. Twelve notes is
twelve clicks, and is usually two blocks.

## What a reader without a browser sees

An exported or printed page has no JavaScript, so it shows the pane the way it
was before the walk existed: every label at once, in the ladder. Nothing is
lost and nothing is frozen mid-walk. That is why the labels are still written
to stand on their own — a step that only makes sense after the previous one
reads as a non-sequitur in the exported file.

## Ranges

A note with `"lines": [from, to]` and no `span` draws a bracket beside those
lines instead of marking a span. Use it when the claim is about a clause that
spans lines and would be a lie if pinned to any one of them. Ranges may not
overlap — a line belongs to at most one.

## The presentation is chosen for you

Do not ask for a style; there is no field for one — and there is no field for
starting, skipping or disabling the walk either.

Under the walk, the static layout is what the pane falls back to, and it still
follows from the count:

- **1–2 marks on a line** → each gets an underline and a label hanging from
  its own column, stacked rightmost-first the way a compiler stacks them.
- **3+ marks on a line** → the underlines stay, but the labels become a
  numbered list under the line, because three stems threaded past each other
  is a knot rather than a ladder.

A silent mark — the second and later places of a `spans` note — is underlined
but counts toward neither, since it has no label to stack.

This follows from the note count, so a line that grows a third annotation
re-lays itself out instead of degrading. Write the notes; the pane decides.

## Labels

`label` takes **bold, italic and inline code only** — `**lead-in**`, `*stress*`
and `` `ident` ``. Everything else is escaped and renders as text. A label is
one or two sentences pinned to a line of code; if it needs a list or a heading,
it is an argument and belongs in a `markdown` block beside this one.

Lead with a bold two-or-three-word subject, then an em-dash, then the claim.
The bold half is what makes a pane skimmable — a reader takes the subjects
first and reads the bodies only where a subject surprises them.

## No `code` anchors on this kind

An `explain` block carries its own snippet, so a `code` anchor on it is
dropped at push (same as `mockup`). A second pane of the same file beside the
first would restate exactly the split this kind removes. If you want the
anchor's live-resolution behaviour instead, that is a `markdown` block with a
`code` anchor — see `references/code-anchors.md`.

## Commenting and rewriting

The block is commented as a whole, from the card header. On a rewrite, edit
`spec` via `update_spec_block` (same helper as a diagram's `spec.source`; see
`references/handling-events.md`) — change the `notes`, and change `code` only
if the snippet itself was wrong. Keep the spans quoted; a rewrite that
replaces a quote with a column is refused the same way an original would be.
