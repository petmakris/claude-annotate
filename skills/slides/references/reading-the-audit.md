# Reading the layout audit

Moved out of SKILL.md. Read it when the audit reports a gap and you must decide whether it is a defect.

### Reading the result

**Any overflow is a bug.** A healthy deck reports `overflow: []` on every slide — the
reference deck does.

**A gap is a question, not a verdict.** Two cases:

- *Bottom gap on a top-anchored slide* — an `.introb` or `.tree` slide with nothing pinned
  at the bottom. Fine. The reference deck's tree slides run 269–383px of floor gap.
- *A block sandwiched between the header and a bottom-pinned `.strip`* — **not fine if the
  two gaps differ much.** Centre the content in the band instead of leaving the slack at
  one end. Set the block's `top` so the space above it and below it match.

That is what the reference deck does, and it is what the audit should show:

| Slide | Above the block | Below it |
|---|---|---|
| 4 · before/after `.ctxp` pair | 86px | 82px |
| 7 · `.flow` chain | 133px | 126px |
| 10 · `.flow` chain | 102px | 94px |
| 11 · `.stab` + `.rails` | 72px | 67px |

Within about 10px is the target. A `.strip` at `bottom:36px` ends the usable band around
`y=640`, so a block of height `h` sitting under a header that ends at `y=hdr` wants
`top ≈ hdr + (640 − hdr − h) / 2`.

Two shortcuts that are not shortcuts: never fix an overflow by shrinking type below the
component's own scale. Split the slide.
