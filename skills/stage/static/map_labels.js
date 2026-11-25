// Where a flowchart's arrow labels sit (map.js draws them). Pure: no DOM, so a test can run it under node.
//
// Every label belongs to one arrow and sits on it, at the middle of the longest stretch that has room, or just beside
// it with a short leader when no stretch has. A label never goes on a part, on another label, on another arrow's head
// or across another arrow if any place avoids that; the least bad place wins only when every place is bad.
//
//   placeEdgeLabels({ labels, cards, routes, width, side, across }) -> Map(edge index -> { x, y, rect, off, at })
//   labels: [{ i, pts, spots, end, start, w, h }]  the label's size is measured by the caller (w, h in px)
//   cards:  [[x0, y0, x1, y1]]                     every part as it is now, with its margin
//   routes: Map(edge index -> { pts })             every arrow's corners
//   spots:  [[x, y]] | null                        fixed places for a label (an arrow from a part to itself)

const area = (r, q) => Math.max(0, Math.min(r[2], q[2]) - Math.max(r[0], q[0])) * Math.max(0, Math.min(r[3], q[3]) - Math.max(r[1], q[1]));
const cutBy = (r, s) => Math.min(s.a[0], s.b[0]) < r[2] && Math.max(s.a[0], s.b[0]) > r[0] && Math.min(s.a[1], s.b[1]) < r[3] && Math.max(s.a[1], s.b[1]) > r[1];
const near = (q, r, m) => q && q[0] > r[0] - m && q[0] < r[2] + m && q[1] > r[1] - m && q[1] < r[3] + m;

export function placeEdgeLabels({ labels, cards, routes, width, side, across }) {
  const lines = [], heads = [];
  for (const [i, r] of routes) {
    for (let k = 1; k < r.pts.length; k++) lines.push({ i, a: r.pts[k - 1], b: r.pts[k] });
    if (r.pts.length) heads.push({ i, p: r.pts[r.pts.length - 1] }, { i, p: r.pts[0] });
  }
  for (const L of labels) for (const q of [L.end, L.start]) if (q && !heads.some((h) => h.i === L.i && h.p === q)) heads.push({ i: L.i, p: q });
  const placed = [], out = new Map();
  // the longest labels first: they have the fewest places to go
  for (const L of labels.slice().sort((a, b) => b.w - a.w)) {
    const { w, h } = L, cand = [];
    if (L.spots) L.spots.forEach(([x, y]) => cand.push([x, y, false]));
    else {
      const segs = L.pts.slice(1).map((q, k) => ({ a: L.pts[k], b: q, len: Math.hypot(q[0] - L.pts[k][0], q[1] - L.pts[k][1]) })).sort((x, y) => y.len - x.len);
      // on the arrow: at the middle of each stretch, then along it
      for (const sg of segs) for (const f of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) cand.push([sg.a[0] + (sg.b[0] - sg.a[0]) * f, sg.a[1] + (sg.b[1] - sg.a[1]) * f, false]);
      // beside it, with a short leader: across the flow from a stretch that runs along it
      for (const sg of segs) {
        const horizontal = Math.abs(sg.a[1] - sg.b[1]) < 0.01;
        for (const gap of [12, 30]) for (const f of [0.5, 0.3, 0.7, 0.15, 0.85]) for (const dir of [-1, 1]) {
          const mx = sg.a[0] + (sg.b[0] - sg.a[0]) * f, my = sg.a[1] + (sg.b[1] - sg.a[1]) * f;
          cand.push(horizontal ? [mx, my + dir * (h / 2 + gap), true, [mx, my]] : [mx + dir * (w / 2 + gap), my, true, [mx, my]]);
        }
      }
    }
    let best = null;
    cand.forEach(([cx, cy, off, anchor], k) => {
      const x = Math.max(side + w / 2, Math.min(width - side - w / 2, cx)), y = cy;
      const r = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      let cost = k * 0.5 + (off ? 30 : 0);
      for (const c of cards) cost += area(r, c) * 4 + (area(r, c) ? 600 : 0);
      for (const q of placed) cost += area(r, q) * 4 + (area(r, q) ? 1000 : 0);
      for (const s of lines) if (s.i !== L.i && cutBy(r, s)) cost += 150;
      for (const hd of heads) if (near(hd.p, r, hd.i === L.i ? 14 : 10)) cost += hd.i === L.i ? 500 : 300;
      if (x !== cx) cost += 30;
      if (!best || cost < best.cost) best = { cost, x, y, rect: r, off, at: anchor || [cx, cy] };
    });
    placed.push(best.rect);
    out.set(L.i, best);
  }
  return out;
}
