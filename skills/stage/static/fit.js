// How the stage fits a board into its pane: a table's columns, and where a scrolling pane is moved to. Pure: no DOM,
// so a test can run it under node.
//
// -- columns
//
// Each column has a share (what its text asks for, a fraction of the table) and a floor (its longest word in the
// cell's own font plus the cell's padding, in px). Chromium reads `width: max(40%, 97px)` on a <col> as `auto`, so
// the floor never held and the first column came out narrower than its own words and printed over the next one:
// the widths are worked out here, in px, and set on the columns.
//
//   columnWidths(shares, floors, total) -> px for each column
// A column whose share is under its floor is held at the floor; the others share what is left by their shares, and
// that can push another under its floor, so it repeats. When the floors alone are wider than `total` they are the
// widths (the caller then lets the table scroll sideways).

export function columnWidths(shares, floors, total) {
  const n = shares.length, held = new Array(n).fill(false), out = new Array(n).fill(0);
  if (!n) return out;
  for (let round = 0; round <= n; round++) {
    const heldSum = floors.reduce((a, f, i) => a + (held[i] ? f : 0), 0);
    const freeShare = shares.reduce((a, s, i) => a + (held[i] ? 0 : Math.max(s, 0)), 0);
    const left = Math.max(0, total - heldSum);
    let more = false;
    for (let i = 0; i < n; i++) {
      if (held[i]) { out[i] = floors[i]; continue; }
      out[i] = freeShare > 0 ? left * Math.max(shares[i], 0) / freeShare : left / (n - held.filter(Boolean).length);
      if (out[i] < floors[i]) { held[i] = true; out[i] = floors[i]; more = true; }
    }
    if (!more) break;
  }
  return out.map((w) => Math.round(w * 10) / 10);
}

// Where a scrolling pane moves to so what is being said is in view. `top` and `bottom`: the span of what is said,
// `box` {top, height}: the pane's box, `view`: the room it has (the foot kept clear), `scroll`: where it is now,
// `lead`: the bottom of the slide's title, in the pane's content (0 for a board with none).
// What fits is centred, what is taller than the pane starts at its top. A slide's title is never left cut by the
// pane's edge: when the move would leave it half hidden it shows whole if what is said still fits under it,
// else the pane moves past it.
export function centreTarget({ top, bottom, box, view, scroll, lead = 0 }) {
  const height = bottom - top;
  let to = scroll + (height <= view ? top + height / 2 - (box.top + view / 2) : top - box.top - 12);
  to = Math.max(0, to);
  if (lead > 0 && to > 0 && to < lead) to = bottom - box.top + scroll <= view ? 0 : lead;
  return to;
}
