# Block kind: `explain`

A snippet where **the explanation rides on the code**. Spans are marked in
place and their labels hang off the exact columns they describe; a group of
lines gets a bracket. There is no prose column — this kind exists to delete
the read-the-prose-then-find-the-code ping-pong that a `markdown` block plus a
`code` anchor forces on the reader.

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

## Ranges

A note with `"lines": [from, to]` and no `span` draws a bracket beside those
lines instead of marking a span. Use it when the claim is about a clause that
spans lines and would be a lie if pinned to any one of them. Ranges may not
overlap — a line belongs to at most one.

## The presentation is chosen for you

Do not ask for a style; there is no field for one.

- **1–2 marks on a line** → each gets an underline and a label hanging from
  its own column, stacked rightmost-first the way a compiler stacks them.
- **3+ marks on a line** → the underlines stay, but the labels become a
  numbered list under the line, because three stems threaded past each other
  is a knot rather than a ladder.

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
