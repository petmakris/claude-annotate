// Where a flowchart's arrows run (map.js draws what this decides). Pure: no DOM, so a test can run it under node.
//
// Parts sit in ranks (the columns of a map read left to right, the rows of one read top to bottom). The router works
// in the direction of the flow: `u` runs along it, `v` across it. An arrow forward is orthogonal. It leaves its part
// by a port on the side that faces forward, runs in the free corridor of every rank it crosses (a dummy part per
// rank: a long arrow never goes through a part in between), and turns in the gap between two ranks on a lane of its
// own, so two arrows never lie one over the other. An arrow back runs round the parts, under them (or over them, or
// up a side channel), by the first of its candidate routes that touches no part.
//
//   routeEdges({ mode, nodes, rank, edges, bounds }) -> Map(edge index -> { pts, kind })
//   nodes: Map(id -> { x, y, hw, hh })  the centre and half size of each part as it is now
//   rank:  Map(id -> number)            the column (mode "across") or row (mode "down") of each part
//   edges: [{ i, from, to, back, self }]
//   bounds: { width, tall, side, laneBase, laneStep }
//
// `pts` are [x, y] corners, the last one where the arrow's head points. A self loop has no points (kind "loop").

export const ARROW = 5;       // the head stops this far short of the part it enters
const PORT = 16;              // the most two ports of one side are apart
const CORRIDOR = 4;           // clear space kept round a part in a corridor
const LANE = 9;               // the least two arrows in one corridor or gap are apart
const BACK_PORT = 14;

export function routeEdges({ mode, nodes, rank, edges, bounds }) {
  const across = mode === "across";
  // the flow frame: u along the flow, v across it
  const N = new Map();
  for (const [id, n] of nodes) N.set(id, across ? { u: n.x, v: n.y, hu: n.hw, hv: n.hh } : { u: n.y, v: n.x, hu: n.hh, hv: n.hw });
  const out = (u, v) => (across ? [u, v] : [v, u]);
  const R = Math.max(0, ...[...rank.values()]) + 1;
  const members = Array.from({ length: R }, () => []);
  for (const [id, r] of rank) if (N.has(id)) members[r].push(id);
  const uLo = members.map((m) => Math.min(...m.map((id) => N.get(id).u - N.get(id).hu)));
  const uHi = members.map((m) => Math.max(...m.map((id) => N.get(id).u + N.get(id).hu)));
  const vMin = bounds.side ?? 12, vMax = Math.max(...[...N.values()].map((n) => n.v + n.hv));
  const vTop = Math.min(...[...N.values()].map((n) => n.v - n.hv));
  const gapMid = (g) => (uHi[g] + uLo[g + 1]) / 2;
  const result = new Map();
  const fwd = [], back = [];
  for (const e of edges) {
    if (e.self) { result.set(e.i, { kind: "loop", pts: [] }); continue; }
    (e.back || rank.get(e.to) <= rank.get(e.from) ? back : fwd).push({ ...e, ra: rank.get(e.from), rb: rank.get(e.to) });
  }

  // -- ports: an arrow leaves and enters a part at its own height, in the order of where it goes ---------------------
  const ports = (list, end, other, key) => {
    const by = new Map();
    for (const e of list) (by.get(e[end]) || by.set(e[end], []).get(e[end])).push(e);
    for (const [id, es] of by) {
      const n = N.get(id);
      es.sort((a, b) => N.get(a[other]).v - N.get(b[other]).v || a.i - b.i);
      const step = es.length > 1 ? Math.min(PORT, Math.max(6, (2 * n.hv - 8) / (es.length - 1))) : 0;
      es.forEach((e, k) => { e[key] = n.v + (k - (es.length - 1) / 2) * step; });
    }
  };
  ports(fwd, "from", "to", "pa");
  ports(fwd, "to", "from", "pb");

  // -- corridors: the free stretches of each rank, across the flow ----------------------------------------------------
  const corridors = members.map((m) => {
    const iv = m.map((id) => [N.get(id).v - N.get(id).hv - CORRIDOR, N.get(id).v + N.get(id).hv + CORRIDOR]).sort((a, b) => a[0] - b[0]);
    const free = [];
    let at = Math.min(vMin, iv[0][0] - 24);
    for (const [lo, hi] of iv) { if (lo - at >= 10) free.push({ lo: at, hi: lo }); at = Math.max(at, hi); }
    free.push({ lo: at, hi: Math.max(at + 40, vMax + 60) });
    return free;
  });
  const pick = (k, want) => {
    let best = null;
    corridors[k].forEach((c, ci) => {
      const d = want < c.lo ? c.lo - want : want > c.hi ? want - c.hi : 0;
      if (!best || d < best.d - 0.5) best = { d, ci };
    });
    return best.ci;
  };

  // each arrow's level in every rank it crosses: it keeps its height while a corridor holds it
  const crossing = new Map();   // "rank:corridor" -> [{ e, want }]
  for (const e of fwd) {
    e.level = new Map();
    let v = e.pa;
    for (let k = e.ra + 1; k < e.rb; k++) {
      const ci = pick(k, v), c = corridors[k][ci];
      v = Math.max(c.lo + 3, Math.min(c.hi - 3, v));
      const key = k + ":" + ci;
      (crossing.get(key) || crossing.set(key, []).get(key)).push({ e, k, want: v });
    }
  }
  for (const [key, list] of crossing) {
    const [k, ci] = key.split(":").map(Number), c = corridors[k][ci];
    list.sort((a, b) => a.want - b.want || a.e.i - b.e.i);
    const lo = c.lo + 3, hi = c.hi - 3;
    let prev = -Infinity;
    for (const it of list) { it.v = Math.max(it.want, prev + LANE); prev = it.v; }
    const over = list[list.length - 1].v - hi;
    if (over > 0) {   // no room below: pushed back up, and spread evenly where they do not fit
      let next = Infinity;
      for (let j = list.length - 1; j >= 0; j--) { list[j].v = Math.min(list[j].v, next - LANE, hi); next = list[j].v; }
      if (list[0].v < lo) list.forEach((it, j) => { it.v = list.length > 1 ? lo + ((hi - lo) * j) / (list.length - 1) : lo; });
    }
    for (const it of list) it.e.level.set(it.k, it.v);
  }

  // -- gaps: where an arrow changes level it does so on a lane of its own -----------------------------------------------
  const lanes = Array.from({ length: Math.max(0, R - 1) }, () => []);   // per gap: [{ e, v1, v2 }]
  for (const e of fwd) {
    e.levels = [e.pa];
    for (let k = e.ra + 1; k < e.rb; k++) e.levels.push(e.level.get(k));
    e.levels.push(e.pb);
    for (let g = e.ra; g < e.rb; g++) {
      const a = e.levels[g - e.ra], b = e.levels[g - e.ra + 1];
      if (Math.abs(a - b) >= 0.5) lanes[g].push({ e, g, a, b, v1: Math.min(a, b), v2: Math.max(a, b) });
    }
  }
  const laneX = lanes.map((segs, g) => {
    segs.sort((a, b) => a.v1 - b.v1 || a.e.i - b.e.i);
    const ends = [];
    for (const s of segs) {
      let l = ends.findIndex((end) => end < s.v1 - 6);
      if (l < 0) l = ends.length;
      ends[l] = s.v2; s.lane = l;
    }
    // A runs out to the lane at the height B runs in from it at: A's lane must lie to the left of B's, else the two
    // horizontals would lie one over the other between them.
    const near = (s, t) => s.v1 <= t.v2 + 6 && t.v1 <= s.v2 + 6;
    for (let pass = 0; pass < 6; pass++) {
      let moved = false;
      for (const A of segs) for (const B of segs) {
        if (A === B || !near(A, B) || Math.abs(A.a - B.b) > 1.5 || A.lane < B.lane) continue;
        let l = A.lane + 1;
        while (segs.some((o) => o !== B && o.lane === l && near(o, B))) l++;
        B.lane = l; moved = true;
      }
      if (!moved) break;
    }
    return { n: Math.max(0, ...segs.map((s) => s.lane + 1)), mid: gapMid(g), w: Math.max(0, uLo[g + 1] - uHi[g]) };
  });
  const xOf = (g, lane, extra = 0) => {
    const L = laneX[g], n = L.n + extra, step = Math.min(12, Math.max(3, (L.w - 14) / Math.max(n, 1)));
    return L.mid + (lane - (n - 1) / 2) * step;
  };
  for (const g of lanes.keys()) for (const s of lanes[g]) s.e.laneAt = Object.assign(s.e.laneAt || {}, { [g]: xOf(g, s.lane) });

  for (const e of fwd) {
    const a = N.get(e.from), b = N.get(e.to), pts = [[a.u + a.hu, e.pa]];
    for (let g = e.ra; g < e.rb; g++) {
      const x = e.laneAt?.[g], v1 = e.levels[g - e.ra], v2 = e.levels[g - e.ra + 1];
      if (x !== undefined) pts.push([x, v1], [x, v2]);
    }
    pts.push([b.u - b.hu - ARROW, e.pb]);
    result.set(e.i, { kind: "forward", pts: tidy(pts).map(([u, v]) => out(u, v)) });
  }

  // -- ways back -------------------------------------------------------------------------------------------------------
  const rects = [...N.entries()].map(([id, n]) => ({ id, u0: n.u - n.hu - 3, u1: n.u + n.hu + 3, v0: n.v - n.hv - 3, v1: n.v + n.hv + 3 }));
  const hits = (pts, skip) => {
    let c = 0;
    for (let i = 1; i < pts.length; i++) {
      const [u1, v1] = pts[i - 1], [u2, v2] = pts[i];
      for (const r of rects) if (!skip.includes(r.id) && Math.min(u1, u2) < r.u1 && Math.max(u1, u2) > r.u0 && Math.min(v1, v2) < r.v1 && Math.max(v1, v2) > r.v0) c++;
    }
    return c;
  };
  const base = bounds.laneBase ?? 22, step = bounds.laneStep ?? 26;
  let bottom = 0, top = 0, side = 0;
  const m = back.length;
  back.sort((x, y) => x.i - y.i).forEach((e, k) => {
    const a = N.get(e.from), b = N.get(e.to), po = (k - (m - 1) / 2) * BACK_PORT;
    const below = vMax + base + step * bottom, above = vTop - base - step * top;
    const aFoot = [a.u + po, a.v + a.hv], bFoot = [b.u + po, b.v + b.hv + ARROW];
    const aTop = [a.u + po, a.v - a.hv], bTop = [b.u + po, b.v - b.hv - ARROW];
    const gA = e.ra < R - 1 ? gapMid(e.ra) + (laneX[e.ra].n / 2 + 1 + side) * 7 : uHi[R - 1] + 16 + 12 * side;
    const gB = e.rb > 0 ? gapMid(e.rb - 1) + (laneX[e.rb - 1].n / 2 + 1 + side) * 7 : uLo[0] - 14 - 12 * side;
    const outA = [a.u + a.hu, a.v], inB = [b.u - b.hu - ARROW, b.v + po / 2];
    const cands = [
      ["bottom", [aFoot, [aFoot[0], below], [bFoot[0], below], bFoot]],
      ...(above > 6 ? [["top", [aTop, [aTop[0], above], [bTop[0], above], bTop]]] : []),
      ["side", [outA, [gA, outA[1]], [gA, below], [bFoot[0], below], bFoot]],
      ["into", [aFoot, [aFoot[0], below], [gB, below], [gB, inB[1]], inB]],
      ["round", [outA, [gA, outA[1]], [gA, below], [gB, below], [gB, inB[1]], inB]],
    ];
    let pick2 = null;
    for (const [name, pts] of cands) {
      const h = hits(pts, [e.from, e.to]);
      if (!pick2 || h < pick2.h) pick2 = { name, pts, h };
      if (h === 0) break;
    }
    if (pick2.name === "bottom" || pick2.name === "side" || pick2.name === "into" || pick2.name === "round") bottom++;
    else top++;
    if (pick2.name === "side" || pick2.name === "round" || pick2.name === "into") side++;
    result.set(e.i, { kind: "back", via: pick2.name, hits: pick2.h, pts: tidy(pick2.pts).map(([u, v]) => out(u, v)) });
  });
  return result;
}

// Drops repeated points and the middle of three on a line.
function tidy(pts) {
  const p = pts.filter((q, i) => i === 0 || Math.abs(q[0] - pts[i - 1][0]) > 0.01 || Math.abs(q[1] - pts[i - 1][1]) > 0.01);
  return p.filter((q, i) => {
    if (i === 0 || i === p.length - 1) return true;
    const a = p[i - 1], b = p[i + 1];
    return !((Math.abs(a[0] - q[0]) < 0.01 && Math.abs(q[0] - b[0]) < 0.01) || (Math.abs(a[1] - q[1]) < 0.01 && Math.abs(q[1] - b[1]) < 0.01));
  });
}

// A polyline as an SVG path with its corners rounded (radius r, less where a segment is short).
export function rounded(pts, r = 12) {
  if (pts.length < 2) return "";
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1], [x, y] = pts[i], [nx, ny] = pts[i + 1];
    const l1 = Math.hypot(x - px, y - py), l2 = Math.hypot(nx - x, ny - y), k = Math.min(r, l1 / 2, l2 / 2);
    const ax = x - ((x - px) / l1) * k, ay = y - ((y - py) / l1) * k, bx = x + ((nx - x) / l2) * k, by = y + ((ny - y) / l2) * k;
    d += ` L ${ax} ${ay} Q ${x} ${y} ${bx} ${by}`;
  }
  const [lx, ly] = pts[pts.length - 1];
  return d + ` L ${lx} ${ly}`;
}

// What is wrong with a set of routes: an arrow through a part that is not one of its ends, and two arrows that
// lie one on the other for more than a few pixels. Empty when the routes are clean.
export function routeProblems(routes, nodes, edges, pad = 2) {
  const out = [];
  const segs = [];
  for (const e of edges) {
    const r = routes.get(e.i);
    if (!r || !r.pts.length) continue;
    for (let k = 1; k < r.pts.length; k++) {
      const [x1, y1] = r.pts[k - 1], [x2, y2] = r.pts[k];
      segs.push({ i: e.i, x1, y1, x2, y2 });
      for (const [id, n] of nodes) {
        if (id === e.from || id === e.to) continue;
        if (Math.min(x1, x2) < n.x + n.hw - pad && Math.max(x1, x2) > n.x - n.hw + pad && Math.min(y1, y2) < n.y + n.hh - pad && Math.max(y1, y2) > n.y - n.hh + pad) out.push({ kind: "through", edge: e.i, node: id });
      }
    }
  }
  for (let a = 0; a < segs.length; a++) for (let b = a + 1; b < segs.length; b++) {
    const s = segs[a], t = segs[b];
    if (s.i === t.i) continue;
    const sh = Math.abs(s.y1 - s.y2) < 0.01 && Math.abs(t.y1 - t.y2) < 0.01 && Math.abs(s.y1 - t.y1) < 2;
    const sv = Math.abs(s.x1 - s.x2) < 0.01 && Math.abs(t.x1 - t.x2) < 0.01 && Math.abs(s.x1 - t.x1) < 2;
    const lap = sh ? Math.min(Math.max(s.x1, s.x2), Math.max(t.x1, t.x2)) - Math.max(Math.min(s.x1, s.x2), Math.min(t.x1, t.x2))
      : sv ? Math.min(Math.max(s.y1, s.y2), Math.max(t.y1, t.y2)) - Math.max(Math.min(s.y1, s.y2), Math.min(t.y1, t.y2)) : 0;
    if ((sh || sv) && lap > 3) out.push({ kind: "overlap", edges: [s.i, t.i] });
  }
  return out;
}
