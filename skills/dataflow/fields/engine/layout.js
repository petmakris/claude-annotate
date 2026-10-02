  // ── layout ──

// Network simplex (Gansner, Koutsofios, North, Vo 1993, section 2.3) with Graphviz's
// incremental updates: a pivot reranks only the subtree it cuts off, updates cut values
// only along the cycle it closes, and renumbers only below the cycle's top node.
//
// Solves: minimise  sum_e weight(e) * (r[head(e)] - r[tail(e)])
//         subject to r[head(e)] - r[tail(e)] >= minlen(e)   for every edge
// The graph must be acyclic and connected. Deterministic: every scan has a fixed order and
// ties go to the first edge met. Returns ranks normalised so the minimum is 0.
// opt: init (start ranks, raised to feasibility), feasible (init already satisfies every
// edge: it is used as is, and the graph may then hold cycles, as pinned equalities do),
// stats (filled with pivots and capped),
// maxPivots, searchSize, and checkCuts, a debug flag that recomputes every cut value after
// each pivot and throws if the incremental update drifted.

function networkSimplex(n, edgeList, opt = {}) {
  if (n === 0) return new Float64Array(0);
  const seen = new Map(), E = [];
  for (const e of edgeList) {          // parallel edges merge: weights add, the tighter minlen wins
    const k = e.v * 4194304 + e.w;
    const o = seen.get(k);
    if (o) { o.weight += e.weight; if (e.minlen > o.minlen) o.minlen = e.minlen; }
    else { const c = { v: e.v, w: e.w, minlen: e.minlen, weight: e.weight }; seen.set(k, c); E.push(c); }
  }
  const m = E.length;
  const tl = new Int32Array(m), hd = new Int32Array(m), ml = new Float64Array(m), wt = new Float64Array(m);
  for (let i = 0; i < m; i++) { tl[i] = E[i].v; hd[i] = E[i].w; ml[i] = E[i].minlen; wt[i] = E[i].weight; }
  const start = new Int32Array(n + 1);
  for (let i = 0; i < m; i++) { start[tl[i] + 1]++; start[hd[i] + 1]++; }
  for (let v = 0; v < n; v++) start[v + 1] += start[v];
  const inc = new Int32Array(2 * m), fill = start.slice(0, n);
  for (let i = 0; i < m; i++) { inc[fill[tl[i]]++] = i; inc[fill[hd[i]]++] = i; }

  // 1. feasible ranks: longest path in topological order
  const rank = new Float64Array(n);
  if (opt.feasible) rank.set(opt.init);
  else {
    const indeg = new Int32Array(n), topo = new Int32Array(n), set = new Uint8Array(n);
    for (let i = 0; i < m; i++) indeg[hd[i]]++;
    let qh = 0, qt = 0;
    for (let v = 0; v < n; v++) if (!indeg[v]) topo[qt++] = v;
    while (qh < qt) {
      const v = topo[qh++];
      if (!set[v]) { set[v] = 1; rank[v] = opt.init ? opt.init[v] : 0; }
      else if (opt.init && opt.init[v] > rank[v]) rank[v] = opt.init[v];
      for (let k = start[v]; k < start[v + 1]; k++) {
        const i = inc[k];
        if (tl[i] !== v) continue;
        const w = hd[i], r = rank[v] + ml[i];
        if (!set[w] || r > rank[w]) { rank[w] = r; set[w] = 1; }
        if (--indeg[w] === 0) topo[qt++] = w;
      }
    }
    if (qt < n) throw new Error("network simplex: the constraints form a cycle");
  }
  const slack = (i) => rank[hd[i]] - rank[tl[i]] - ml[i];
  const EPS = 1e-7;

  // 2. a spanning tree of tight edges, grown from node 0
  const inTree = new Uint8Array(n), isTree = new Uint8Array(m), tnodes = new Int32Array(n), st = new Int32Array(n);
  let tsize = 0;
  const grow = (s) => {
    let sp = 0;
    st[sp++] = s;
    while (sp) {
      const x = st[--sp];
      for (let k = start[x]; k < start[x + 1]; k++) {
        const i = inc[k], y = tl[i] === x ? hd[i] : tl[i];
        if (!inTree[y] && Math.abs(slack(i)) < EPS) { inTree[y] = 1; isTree[i] = 1; tnodes[tsize++] = y; st[sp++] = y; }
      }
    }
  };
  inTree[0] = 1; tnodes[tsize++] = 0; grow(0);
  while (tsize < n) {
    let best = -1, bs = Infinity;
    for (let i = 0; i < m; i++) if (inTree[tl[i]] !== inTree[hd[i]]) { const s = slack(i); if (s < bs) { bs = s; best = i; } }
    if (best < 0) throw new Error("network simplex: the graph is disconnected");
    const d = inTree[tl[best]] ? bs : -bs;
    for (let j = 0; j < tsize; j++) rank[tnodes[j]] += d;
    for (let i = 0; i < m; i++) {
      if (inTree[tl[i]] === inTree[hd[i]] || Math.abs(slack(i)) >= EPS) continue;
      const y = inTree[tl[i]] ? hd[i] : tl[i];
      if (inTree[y]) continue;
      inTree[y] = 1; isTree[i] = 1; tnodes[tsize++] = y; grow(y);
    }
  }

  // tree adjacency (per node, in a flat array sized by degree), and the list of tree edges
  const tadj = new Int32Array(2 * m), tcnt = new Int32Array(n);
  const tAdd = (v, i) => { tadj[start[v] + tcnt[v]++] = i; };
  const tDel = (v, i) => {
    const b = start[v];
    for (let k = 0; k < tcnt[v]; k++) if (tadj[b + k] === i) { tadj[b + k] = tadj[b + tcnt[v] - 1]; tcnt[v]--; return; }
  };
  const treeList = [], treePos = new Int32Array(m).fill(-1);
  for (let i = 0; i < m; i++) if (isTree[i]) { tAdd(tl[i], i); tAdd(hd[i], i); treePos[i] = treeList.length; treeList.push(i); }

  // 3. postorder numbering: low/lim ranges, parent edges, and post[lim] = node
  const low = new Int32Array(n), lim = new Int32Array(n), par = new Int32Array(n), post = new Int32Array(n + 2);
  const sv = new Int32Array(n), sk = new Int32Array(n);
  const renumber = (root, rootPar, low0) => {
    let next = low0, sp = 0;
    par[root] = rootPar; low[root] = next; sv[sp] = root; sk[sp] = 0; sp++;
    while (sp) {
      const v = sv[sp - 1];
      if (sk[sp - 1] < tcnt[v]) {
        const i = tadj[start[v] + sk[sp - 1]++];
        if (i === par[v]) continue;
        const w = tl[i] === v ? hd[i] : tl[i];
        par[w] = i; low[w] = next; sv[sp] = w; sk[sp] = 0; sp++;
      } else { lim[v] = next; post[next] = v; next++; sp--; }
    }
  };
  renumber(0, -1, 1);

  // 4. cut values, children before parents
  const cutValues = (cut) => {
    for (let t = 1; t < n; t++) {
      const child = post[t], i = par[child], childIsTail = tl[i] === child;
      let cv = wt[i];
      for (let k = start[child]; k < start[child + 1]; k++) {
        const j = inc[k];
        if (j === i) continue;
        const toHead = (tl[j] === child) === childIsTail;
        cv += toHead ? wt[j] : -wt[j];
        if (isTree[j]) cv += toHead ? -cut[j] : cut[j];
      }
      cut[i] = cv;
    }
    return cut;
  };
  const cut = cutValues(new Float64Array(m));

  // 5. pivots
  const SEARCH = opt.searchSize ?? 30;
  let Si = 0;
  const leave = () => {             // the most negative of the next SEARCH negative cut values, cyclically
    let rv = -1, cnt = 0;
    const j = Si;
    for (; Si < treeList.length; Si++) {
      const f = treeList[Si];
      if (cut[f] < -EPS) { if (rv < 0 || cut[rv] > cut[f]) rv = f; if (++cnt >= SEARCH) return rv; }
    }
    if (j > 0) for (Si = 0; Si < j; Si++) {
      const f = treeList[Si];
      if (cut[f] < -EPS) { if (rv < 0 || cut[rv] > cut[f]) rv = f; if (++cnt >= SEARCH) return rv; }
    }
    return rv;
  };
  const treeUpdate = (v, w, cv, dir) => {
    while (!(low[v] <= lim[w] && lim[w] <= lim[v])) {
      const t = par[v], d = v === tl[t] ? dir : !dir;
      cut[t] += d ? cv : -cv;
      v = lim[tl[t]] > lim[hd[t]] ? tl[t] : hd[t];
    }
    return v;
  };
  const cap = opt.maxPivots ?? 40 * n + 200;
  let pivots = 0;
  for (; pivots < cap; pivots++) {
    const e = leave();
    if (e < 0) break;
    // the subtree cut off by e, and the cheapest non-tree edge back across in the right direction
    const S = lim[tl[e]] < lim[hd[e]] ? tl[e] : hd[e], out = S === hd[e], lo = low[S], hi = lim[S];
    let f = -1, fs = Infinity;
    for (let t = lo; t <= hi && fs > 0; t++) {
      const x = post[t];
      for (let k = start[x]; k < start[x + 1]; k++) {
        const i = inc[k];
        if (isTree[i] || (out ? tl[i] : hd[i]) !== x) continue;
        const y = out ? hd[i] : tl[i];
        if (lo <= lim[y] && lim[y] <= hi) continue;
        const s = slack(i);
        if (s < fs) { fs = s; f = i; if (s <= 0) break; }
      }
    }
    if (f < 0) throw new Error("network simplex: no entering edge");
    if (fs !== 0) { const d = out ? fs : -fs; for (let t = lo; t <= hi; t++) rank[post[t]] += d; }
    const cv = cut[e];
    const lca = treeUpdate(tl[f], hd[f], cv, true);
    treeUpdate(hd[f], tl[f], cv, false);
    cut[f] = -cv; cut[e] = 0;
    isTree[e] = 0; isTree[f] = 1;
    tDel(tl[e], e); tDel(hd[e], e); tAdd(tl[f], f); tAdd(hd[f], f);
    treeList[treePos[e]] = f; treePos[f] = treePos[e]; treePos[e] = -1;
    renumber(lca, par[lca], low[lca]);
    if (opt.checkCuts) {
      // debug: a sign slip in the incremental update gives a feasible, suboptimal answer
      // and no error, so recompute every cut value from scratch and compare
      const fresh = cutValues(new Float64Array(m));
      for (const i of treeList) if (Math.abs(fresh[i] - cut[i]) > EPS) throw new Error(`network simplex: cut value of edge ${i} drifted (${cut[i]} != ${fresh[i]})`);
    }
  }
  let mn = Infinity;
  for (let v = 0; v < n; v++) if (rank[v] < mn) mn = rank[v];
  for (let v = 0; v < n; v++) rank[v] -= mn;
  if (opt.stats) { opt.stats.pivots = pivots; opt.stats.nodes = n; opt.stats.edges = m; opt.stats.capped = pivots >= cap; }
  return rank;
}

// The layout. Pure: spec in, geometry out; nothing measures the DOM. Docs:
// docs/superpowers/specs/2026-10-02-dataflow-field-layout-design.md (R1-R9 and stages 0-11).
//
//  0 model     validate; number cards by id and edges by their two ends, so spec order
//              places nothing (R8)
//  1 columns   network simplex on the card graph: least total wire span; a card nothing
//              feeds docks one column before its nearest consumer
//  2 lanes     a wire that skips columns gets one lane item per skipped column
//  3 rows      a row grows a port per extra wire; a 1:1 copy keeps both rows the same height
//  4 order     port-aware barycentre sweeps (right to left first), sifting, transposition,
//              exact refinement moves and a closing pass, all on exact crossing counts;
//              ties go to the order of what an item feeds
//  5 ports     wires sharing a row leave it in the order of their other ends
//  6 heights   network simplex on the stacking constraints: least weighted |wire climb| (L1)
//  7 x         column width = widest card; a gap fits its labels and its steepest climb
//  8 wires     a cubic per hop, flat at both ends; a straight run along each lane
//  9 labels    beside the start, beside the arrowhead (one-hop wires), or on the curve;
//              a gap widens until they fit
// 10 measures  measure(), recomputed from what stage 11 publishes
// 11 publish   window.__layout, __layoutReport, __layoutTiming

// Every length that reaches a solver is an integer and every weight is an integer, so both
// solves run in exact arithmetic and every y is an integer.
const K = {
  HEADER_H: 46, ROW_H: 26, PAD_X: 13, MIN_GAP: 120, MIN_CARD_W: 130, MARGIN: 20,
  // Advance widths for the faces the page uses. Overestimating buys padding; underestimating clips.
  MONO_11: 6.65, MONO_13: 7.9, SANS_95: 5.3, LABEL_ADV: 5.1, LABEL_H: 11,
  PORT: 10,                     // a row grows this much per extra wire, and ports sit this far apart
  // clearance between vertical neighbours: card→card, card→lane, lane→card (24 + an 18 px
  // stage label), lane→lane. 13 under a card lets a lane run one row pitch below it, so a
  // source stacked above the lane can still sit level with the row next to the lane's.
  CLEAR_CC: 40, CLEAR_CL: 13, CLEAR_LC: 42, CLEAR_LL: 16,
  STEEP: 1, STEEP_CAP: 480, PER_WIRE: 8,      // gap width from the climb across it
  // hop weights: dot's 1/2/8 for row→row, row↔lane and lane→lane, ×1000 to stay integer. A 1:1
  // copy weighs four plain wires; a source's first hop 7/4 of its kind, so a 1:1 source hop
  // (7000) outweighs one copy but not a block of two (8000). Stage 6 only: the ordering stage
  // uses the base weight, which keeps it independent of spec order.
  W_ROW: 1000, W_MIX: 2000, W_RUN: 8000, W_COPY: 4, W_DOCK: 1.75, TIE: 1,
  SLIDE: 5,                     // largest port slide, px: every port stays >= 8 px inside its row
  SWEEPS: 12, PATIENCE: 3, ROUNDS: 2, REFINE_PASSES: 4, LABEL_ROUNDS: 4,
  // stage 4 work units, counted rather than timed so every machine draws the same picture
  SWEEP_BUDGET: 800000, ORDER_BUDGET: 1500000,
};

// ── wire and label geometry ──
// Shared by the layout and by a drag: a wire re-routed after a move is built by the same
// code from the same hop list, so it cannot look different from a laid-out one.

// a point on one hop's cubic: flat at both ends, the bend weighted towards the target
function cubicAt(x1, y1, x2, y2, t) {
  const gw = x2 - x1, c1 = [x1 + gw * 0.55, y1], c2 = [x2 - gw * 0.35, y2], u = 1 - t;
  return [u * u * u * x1 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * x2, u * u * u * y1 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * y2];
}

// hopGeo is [x1, y1, x2, y2] per gap crossed; between two hops the wire runs straight along
// its lane. Returns the path, both ends, the samples the label scorer and the report walk,
// and the straight runs a label may sit on.
function wireRoute(hopGeo) {
  let d = "", head = null, tail = null;
  const samples = [], runs = [];
  hopGeo.forEach(([x1, y1, x2, y2], i) => {
    const gw = x2 - x1;
    if (i === 0) { d = `M ${x1} ${y1}`; head = [x1, y1]; }
    else {
      const [px, py] = samples[samples.length - 1];
      runs.push({ x0: px, x1, y: y1 });
      for (let k = 1; k <= 12; k++) samples.push([lerp(px, x1, k / 12), lerp(py, y1, k / 12)]);
      d += ` L ${x1} ${y1}`;
    }
    const c1 = [x1 + gw * 0.55, y1], c2 = [x2 - gw * 0.35, y2];
    d += ` C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${x2} ${y2}`;
    for (let k = 0; k <= 24; k++) samples.push(cubicAt(x1, y1, x2, y2, k / 24));
    tail = [x2, y2];
  });
  return { d, head, tail, samples, runs, hopGeo };
}

// what a label must keep off: each card with the stage line above it
const cardBoxes = (cs) => cs.map((c) => ({ x: c.x - 2, y: c.y - 24, w: c.w + 4, h: c.h + 24 }));

// wireHits(box, own): how many samples of other wires fall inside box, on a 40-unit grid
function wireGrid(routes) {
  const CELL = 40, grid = new Map();
  routes.forEach((R, ei) => R.samples.forEach(([sx, sy]) => {
    const k = Math.floor(sx / CELL) + "," + Math.floor(sy / CELL);
    (grid.get(k) || grid.set(k, []).get(k)).push([sx, sy, ei]);
  }));
  return (b, own) => {
    let n = 0;
    for (let gx = Math.floor(b.x / CELL); gx <= Math.floor((b.x + b.w) / CELL); gx++)
      for (let gy = Math.floor(b.y / CELL); gy <= Math.floor((b.y + b.h) / CELL); gy++)
        for (const [sx, sy, ei] of grid.get(gx + "," + gy) || []) if (ei !== own && sx >= b.x && sx <= b.x + b.w && sy >= b.y && sy <= b.y + b.h) n++;
    return n;
  };
}

// one label or note on wire R: beside its start, beside its arrowhead (oneHop only), on a
// straight run, or on the curve of its first or last hop; least box overlap first, then
// fewest other wires under it. score[0] > 0 is an overlap the report counts.
function placeText(P, t, R, oneHop, boxes, wireHits) {
  const w = t.text.length * P.LABEL_ADV + 4;
  const area = (b) => boxes.reduce((a, o) => a + Math.max(0, Math.min(b.x + b.w, o.x + o.w) - Math.max(b.x, o.x)) *
    Math.max(0, Math.min(b.y + b.h, o.y + o.h) - Math.max(b.y, o.y)), 0);
  const cands = [{ x: R.head[0] + 10, y: R.head[1] - 6, anchor: "start" }, { x: R.head[0] + 10, y: R.head[1] + 13, anchor: "start" }];
  if (oneHop)
    cands.push({ x: R.tail[0] - 12, y: R.tail[1] - 6, anchor: "end" }, { x: R.tail[0] - 12, y: R.tail[1] + 13, anchor: "end" });
  for (const run of R.runs) if (run.x1 - run.x0 >= w + 16)
    cands.push({ x: (run.x0 + run.x1) / 2, y: run.y - 6, anchor: "middle" }, { x: (run.x0 + run.x1) / 2, y: run.y + 13, anchor: "middle" });
  {
    const f = R.hopGeo[0];
    for (const tt of [0.5, 0.3, 0.7]) { const [bx, by] = cubicAt(...f, tt); cands.push({ x: bx, y: by - 6, anchor: "middle" }, { x: bx, y: by + 13, anchor: "middle" }); }
    if (R.hopGeo.length > 1) { const l = R.hopGeo[R.hopGeo.length - 1], [bx, by] = cubicAt(...l, 0.5); cands.push({ x: bx, y: by - 6, anchor: "middle" }, { x: bx, y: by + 13, anchor: "middle" }); }
  }
  let pick = null, score = null;
  for (const c of cands) {
    c.box = { x: c.anchor === "end" ? c.x - w : c.anchor === "middle" ? c.x - w / 2 : c.x, y: c.y - 9, w, h: P.LABEL_H };
    const sc = [area(c.box), wireHits(c.box, t.ei)];
    if (!score || sc[0] < score[0] || (sc[0] === score[0] && sc[1] < score[1])) { pick = c; score = sc; }
  }
  return { pick, score };
}

// opt overrides any constant of K, and adds now (a clock for __layoutTiming), CHECK_CUTS, and
// pin: a viewer's arrangement, { colX, cards: { id: { y, h, order, tops } } }. Pinned, every
// card keeps that place, height and row order, and only the wires are laid out again, by the
// same stages: lanes take the gaps the cards leave (stage 4 pinned), ports fan by the order of
// their far ends (5), and the height solve straightens the lanes around fixed cards (6).
function computeLayout(SPEC, opt = {}) {
  const P = Object.assign({}, K, opt), PIN = opt.pin || null;
  const clock = opt.now || (() => 0), T = {}, solves = [], tStart = clock();
  let t0 = tStart;
  const mark = (k) => { const t = clock(); T[k] = r2(t - t0); t0 = t; };   // milliseconds per stage
  const r2 = (v) => Math.round(v * 100) / 100;
  const solve = (n, E, o = {}) => {
    const stats = {}, y = networkSimplex(n, E, { ...o, stats, checkCuts: P.CHECK_CUTS });
    solves.push({ pivots: stats.pivots, capped: stats.capped });
    return y;
  };

  // ── 0 model ──
  validate(SPEC);
  const canon = new Map(SPEC.cards.map((c) => c.id).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)).map((id, i) => [id, i]));
  const cards = SPEC.cards.map((c, i) => ({
    id: c.id, idx: i, ck: canon.get(c.id), spec: c, follow: c.rows === "follow",
    w: Math.max(P.MIN_CARD_W, c.name.length * P.MONO_13 + 2 * P.PAD_X, (c.sub || "").length * P.SANS_95 + 2 * P.PAD_X,
      ...c.fields.map((f) => f.label.length * P.MONO_11 + 2 * P.PAD_X)),
  }));
  const rowOf = new Map();
  for (const c of cards) c.rows = c.spec.fields.map((f, j) => {
    const r = { kind: "row", card: c, f, j, id: `${c.id}.${f.id}`, L: [], R: [] };
    rowOf.set(r.id, r);
    return r;
  });
  const cmpS = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const edgesSorted = (SPEC.edges || []).slice().sort((x, y) => cmpS(x.from, y.from) || cmpS(x.to, y.to));
  const edges = edgesSorted.map((e, i) => ({ e, i, a: rowOf.get(e.from), b: rowOf.get(e.to) }));
  const succ = new Map(cards.map((c) => [c, new Map()])), pred = new Map(cards.map((c) => [c, new Map()]));
  for (const E of edges) {
    const u = E.a.card, v = E.b.card;
    succ.get(u).set(v, (succ.get(u).get(v) || 0) + 1);
    pred.get(v).set(u, (pred.get(v).get(u) || 0) + 1);
  }
  const wsum = (m) => { let s = 0; for (const x of m.values()) s += x; return s; };

  // ── 1 columns ──
  const comp = new Map();
  let nComp = 0;
  for (const c of cards) {             // components, numbered in spec order of their first card
    if (comp.has(c) || (!succ.get(c).size && !pred.get(c).size)) continue;
    comp.set(c, nComp);
    const st = [c];
    while (st.length) {
      const x = st.pop();
      for (const y of [...succ.get(x).keys(), ...pred.get(x).keys()]) if (!comp.has(y)) { comp.set(y, nComp); st.push(y); }
    }
    nComp++;
  }
  const layer = new Map();
  for (let k = 0; k < nComp; k++) {
    const nodes = cards.filter((c) => comp.get(c) === k).sort((a, b) => a.ck - b.ck), ix = new Map(nodes.map((c, i) => [c, i]));
    const E = [];
    for (const u of nodes) for (const [v, w] of succ.get(u)) E.push({ v: ix.get(u), w: ix.get(v), minlen: 1, weight: w });
    const r = solve(nodes.length, E);
    // equal weight in and out costs the same anywhere in range: sit next to what it feeds
    const desc = nodes.map((_, i) => i).sort((a, b) => r[b] - r[a] || b - a);   // i is now the canonical rank
    for (const i of desc) {
      const c = nodes[i];
      if (!succ.get(c).size || wsum(succ.get(c)) !== wsum(pred.get(c))) continue;
      let hi = Infinity;
      for (const v of succ.get(c).keys()) hi = Math.min(hi, r[ix.get(v)] - 1);
      if (hi > r[i]) r[i] = hi;
    }
    nodes.forEach((c, i) => layer.set(c, r[i]));
  }
  for (const c of cards) {             // a card with no wires: under the connected card listed before it
    if (comp.has(c)) continue;
    let ref = null;
    for (let i = c.idx - 1; i >= 0 && !ref; i--) if (comp.get(cards[i]) < nComp) ref = cards[i];
    for (let i = c.idx + 1; i < cards.length && !ref; i++) if (comp.get(cards[i]) < nComp) ref = cards[i];
    layer.set(c, nComp ? layer.get(ref) : c.idx);     // a spec without edges: one column per card, in spec order
    comp.set(c, nComp);
  }
  const used = [...new Set(cards.map((c) => layer.get(c)))].sort((a, b) => a - b), dense = new Map(used.map((l, i) => [l, i]));
  for (const c of cards) c.col = dense.get(layer.get(c));
  const nCol = used.length;
  mark("columns");

  // ── 2 lanes and hops ──
  const cols = Array.from({ length: nCol }, () => []);
  for (const c of cards) {
    // cards without wires form their own group under everything else, in spec order (R8)
    const it = { kind: "card", card: c, comp: comp.get(c), cls: 1, key: comp.get(c) < nComp ? c.ck : c.idx, ports: c.rows.slice() };
    c.item = it;
    for (const r of c.rows) r.item = it;
    cols[c.col].push(it);
  }
  const hops = [], gapHops = Array.from({ length: Math.max(0, nCol - 1) }, () => []);
  for (const E of edges) {
    const chain = [E.a];
    for (let k = E.a.card.col + 1; k < E.b.card.col; k++) {
      const p = { kind: "lane", E, col: k, L: [], R: [], h: 0, off: 0 };
      p.item = { kind: "lane", E, comp: comp.get(E.a.card), key: cards.length + E.i, ports: [p],
        cls: E.e.lane === "above" ? 0 : E.e.lane === "below" ? 2 : 1 };
      cols[k].push(p.item);
      chain.push(p);
    }
    chain.push(E.b);
    E.hops = [];
    const docked = pred.get(E.a.card).size === 0;
    for (let i = 0; i + 1 < chain.length; i++) {
      const a = chain[i], b = chain[i + 1];
      const wo = a.kind === "row" && b.kind === "row" ? P.W_ROW : a.kind === "row" || b.kind === "row" ? P.W_MIX : P.W_RUN;
      // h.wo orders (stage 4), h.w solves the heights (stage 6)
      const h = { a, b, w: i === 0 && docked ? wo * P.W_DOCK : wo, wo, E, gap: a.kind === "row" ? a.card.col : a.col, pa: 0, pb: 0 };
      a.R.push(h); b.L.push(h); hops.push(h); gapHops[h.gap].push(h); E.hops.push(h);
    }
  }
  for (const h of hops)                // a 1:1 copy: its left row sends one wire, its right row receives one
    if (h.a.kind === "row" && h.b.kind === "row" && h.a.R.length === 1 && h.b.L.length === 1) h.w *= P.W_COPY;
  mark("lanes");

  // ── 3 row heights ──
  const rows = cards.flatMap((c) => c.rows);
  for (const r of rows) r.h = P.ROW_H + Math.max(0, Math.max(r.L.length, r.R.length) - 1) * P.PORT;
  for (let changed = true; changed;) {
    changed = false;
    for (const h of hops) {
      if (h.a.kind !== "row" || h.b.kind !== "row" || h.a.R.length !== 1 || h.b.L.length !== 1 || h.a.h === h.b.h) continue;
      h.a.h = h.b.h = Math.max(h.a.h, h.b.h);
      changed = true;
    }
  }
  const shape = (it) => {
    if (it.kind === "lane") { it.span = 0; it.top = 0; it.bot = 0; return; }
    let o = 0;
    it.ports.forEach((p, i) => { if (i) o += (it.ports[i - 1].h + p.h) / 2; p.off = o; });
    it.span = o; it.top = it.ports[0].h / 2 + P.HEADER_H; it.bot = o + it.ports[it.ports.length - 1].h / 2;
  };
  const clear = (u, v) => u.kind === "card" ? (v.kind === "card" ? P.CLEAR_CC : P.CLEAR_CL) : (v.kind === "card" ? P.CLEAR_LC : P.CLEAR_LL);
  const stack = (k) => {               // compact estimate of a column, centred on 0 (top-aligned without wires)
    const its = cols[k];
    let y = 0;
    its.forEach((it, i) => { if (i) y += its[i - 1].bot + clear(its[i - 1], it) + it.top; it.y = y; });
    const s = its.length && nComp ? (its[its.length - 1].y + its[its.length - 1].bot - its[0].top) / 2 : 0;
    for (const it of its) { it.y -= s; for (const p of it.ports) p.y = it.y + p.off; }
  };
  const rankCol = (k) => { let r = 0; for (const it of cols[k]) for (const p of it.ports) p.rank = r++; };
  const group = (u, v) => u.comp - v.comp || u.cls - v.cls;

  // ── 4 order ──
  const other = (h, p) => (h.a === p ? h.b : h.a);
  const on = (p, s) => (s === "L" ? p.L : p.R);
  const unwired = (p) => (p.L.length + p.R.length ? 0 : 1);
  let work = 0;
  if (!PIN) {
    for (const c of cards) if (c.follow) {            // a follow card starts with its wired rows first
      const wired = (r) => (r.L.length + r.R.length ? 0 : 1);
      c.item.ports.sort((p, q) => wired(p) - wired(q) || p.j - q.j);
    }
    for (let k = 0; k < nCol; k++) { cols[k].sort((u, v) => group(u, v) || u.key - v.key); cols[k].forEach(shape); stack(k); rankCol(k); }
    const rowBary = (p, s) => {
      const hs = on(p, s);
      if (!hs.length) return null;
      let a = 0, w = 0;
      for (const h of hs) { a += h.wo * other(h, p).y; w += h.wo; }
      return a / w;
    };
    const itemBary = (it, s) => {         // where the item's centre would sit if each port met its wire level
      let a = 0, w = 0;
      for (const p of it.ports) for (const h of on(p, s)) { a += h.wo * (other(h, p).y - p.off); w += h.wo; }
      return w ? a / w + it.span / 2 : null;
    };
    const reorder = (k, s) => {
      const alt = s === "L" ? "R" : "L";
      for (const it of cols[k]) {
        if (it.kind === "card" && it.card.follow) {
          // wired rows follow their wires; rows with no wire trail in declared order
          const rb = new Map(it.ports.map((p) => [p, rowBary(p, s) ?? rowBary(p, alt) ?? 0]));
          it.ports.sort((p, q) => unwired(p) - unwired(q) || (unwired(p) ? 0 : rb.get(p) - rb.get(q)) || p.j - q.j);
          shape(it);
        }
        it.bc = itemBary(it, s) ?? itemBary(it, alt) ?? it.y + it.span / 2;
      }
      cols[k].sort((u, v) => group(u, v) || u.bc - v.bc || u.key - v.key);
      stack(k); rankCol(k);
    };
    const inversions = (pairs) => {      // pairs [a, b]: count i<j with a_i < a_j and b_i > b_j; ties never count
      if (pairs.length < 2) return 0;
      pairs.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
      const bs = [...new Set(pairs.map((x) => x[1]))].sort((x, y) => x - y), bi = new Map(bs.map((b, i) => [b, i + 1]));
      const bit = new Int32Array(bs.length + 1);
      let tot = 0, cnt = 0;
      for (let i = 0; i < pairs.length;) {
        let j = i;
        while (j < pairs.length && pairs[j][0] === pairs[i][0]) j++;
        for (let t = i; t < j; t++) { let s = 0; for (let x = bi.get(pairs[t][1]); x > 0; x -= x & -x) s += bit[x]; tot += cnt - s; }
        for (let t = i; t < j; t++) { for (let x = bi.get(pairs[t][1]); x <= bs.length; x += x & -x) bit[x]++; cnt++; }
        i = j;
      }
      return tot;
    };
    const totalCross = () => { let s = 0; for (const hs of gapHops) { s += inversions(hs.map((h) => [h.a.rank, h.b.rank])); work += hs.length; } return s; };
    // each item's other-end ranks per side, sorted; refreshed whenever a neighbour column may have changed
    const endRanks = (k) => {
      for (const it of cols[k]) for (const s of ["L", "R"]) {
        const a = [];
        for (const p of it.ports) for (const h of on(p, s)) a.push(other(h, p).rank);
        it[s] = a.sort((x, y) => x - y);
      }
    };
    const merge = (A, B) => {            // [#(a > b), #(a < b)] over all pairs, by one merge pass
      let gt = 0, lt = 0, j = 0, k = 0;
      for (const a of A) {
        while (j < B.length && B[j] < a) j++;
        while (k < B.length && B[k] <= a) k++;
        gt += j; lt += B.length - k;
      }
      return [gt, lt];
    };
    const pairCross = (u, v) => {        // crossings between two items' wires, [u above v, v above u], both gaps
      work += u.L.length + v.L.length + u.R.length + v.R.length + 1;
      const [c1, r1] = merge(u.L, v.L), [c2, r2] = merge(u.R, v.R);
      return [c1 + c2, r1 + r2];
    };
    const sift = (k) => {
      const its = cols[k];
      endRanks(k);
      let moved = false;
      for (const u of its.slice()) {
        const i0 = its.indexOf(u);
        let lo = i0, hi = i0;
        while (lo > 0 && !group(its[lo - 1], u)) lo--;
        while (hi + 1 < its.length && !group(its[hi + 1], u)) hi++;
        if (hi === lo) continue;
        const rest = its.slice(lo, hi + 1).filter((x) => x !== u), pr = rest.map((v) => pairCross(u, v));
        let cost = 0;
        for (const [c] of pr) cost += c;
        let best = cost, bestP = 0, cur = i0 === lo ? cost : null;
        for (let p = 1; p <= rest.length; p++) {
          cost += pr[p - 1][1] - pr[p - 1][0];
          if (p === i0 - lo) cur = cost;
          if (cost < best) { best = cost; bestP = p; }
        }
        if (best < cur) { rest.splice(bestP, 0, u); its.splice(lo, hi - lo + 1, ...rest); rankCol(k); moved = true; }
      }
      if (moved) stack(k);
    };
    // adjacent swaps that remove crossings; at equal crossings the order of what each item feeds
    // wins, so (crossings, inversions of that order) falls strictly and the loop ends
    const transpose = () => {
      for (let round = 0, swapped = true; swapped && round < P.ROUNDS; round++) {   // wants refreshed per round
      swapped = false;
      for (const its of cols) for (const it of its) {
        it.want = itemBary(it, "R") ?? itemBary(it, "L") ?? it.y + it.span / 2;
        for (const p of it.ports) p.want = rowBary(p, "R") ?? rowBary(p, "L") ?? p.y;
      }
      for (let any = true; any;) {
        any = false;
        for (let k = 0; k < nCol; k++) {
          const its = cols[k];
          endRanks(k);
          for (let i = 0; i + 1 < its.length; i++) {
            const u = its[i], v = its[i + 1];
            if (group(u, v)) continue;
            const [c, r] = pairCross(u, v);
            if (r < c || (r === c && u.want > v.want + 1e-6)) { its[i] = v; its[i + 1] = u; rankCol(k); any = true; }
          }
          for (const it of its) {
            if (it.kind !== "card" || !it.card.follow) continue;
            for (let i = 0; i + 1 < it.ports.length; i++) {
              const p = it.ports[i], q = it.ports[i + 1];
              if (unwired(p) || unwired(q)) continue;
              let c = 0, r = 0;
              for (const s of ["L", "R"]) for (const h of on(p, s)) for (const g of on(q, s)) {
                const a = other(h, p).rank, b = other(g, q).rank;
                if (a > b) c++; else if (a < b) r++;
              }
              if (r < c || (r === c && p.want > q.want + 1e-6)) { it.ports[i] = q; it.ports[i + 1] = p; shape(it); rankCol(k); any = true; }
            }
          }
          stack(k);
        }
        if (any) swapped = true;
      }
      }
    };
    const snap = () => cols.map((its) => its.map((it) => [it, it.kind === "card" && it.card.follow ? it.ports.slice() : null]));
    const restore = (s) => s.forEach((its, k) => {
      cols[k] = its.map(([it, ports]) => { if (ports) { it.ports = ports.slice(); shape(it); } return it; });
      stack(k); rankCol(k);
    });
    const climb = () => { let s = 0; for (const h of hops) s += h.wo * Math.abs(h.a.y - h.b.y); return s; };   // compact-stack proxy of stage 6
    transpose();                         // every kept order, the first included, is one transposition left converged
    let best = snap(), bestC = totalCross(), bestK = climb(), stale = 0;
    T.sweeps = 0;
    for (let sw = 0; sw < P.SWEEPS && stale < P.PATIENCE && work < P.SWEEP_BUDGET; sw++) {
      if (sw % 2 === 0) for (let k = nCol - 2; k >= 0; k--) reorder(k, "R");   // provenance first
      else for (let k = 1; k < nCol; k++) reorder(k, "L");
      for (let k = 0; k < nCol; k++) sift(k);
      transpose();
      const c = totalCross();
      T.sweeps++;
      const kk = climb();
      stale = c < bestC ? 0 : stale + 1;                  // patience counts sweeps that remove no crossing
      if (c < bestC || (c === bestC && kk < bestK)) { bestC = c; bestK = kk; best = snap(); }
    }
    restore(best);
    // exact re-placement of one long wire's lane items across all the columns it crosses (a DP over
    // the chain), kept only when it strictly removes crossings
    const moveChain = (E) => {
      const hs = E.hops;
      if (hs.length < 2) return false;
      const lanes = hs.slice(1).map((h) => h.a.item);
      if (lanes[0].cls !== 1) return false;
      const ks = hs.slice(1).map((h) => h.a.col);
      const S = hs[0].a, T = hs[hs.length - 1].b, n = lanes.length;
      const cur = lanes.map((it, t) => cols[ks[t]].indexOf(it));
      lanes.forEach((it, t) => cols[ks[t]].splice(cur[t], 1));
      const ranges = lanes.map((it, t) => {
        const c = cols[ks[t]];
        let lo = 0, hi = 0;
        for (const o of c) { const g = group(o, it); if (g < 0) lo++; if (g <= 0) hi++; }
        return [lo, hi];
      });
      const ixOf = new Map();
      for (const k of ks) cols[k].forEach((o, i) => ixOf.set(o, i));
      const IX = (p) => ixOf.get(p.item);
      const first = new Float64Array(cols[ks[0]].length + 1);
      for (const h of gapHops[hs[0].gap]) {
        if (h.E === E || h.a === S) continue;
        const above = h.a.rank < S.rank, B = IX(h.b);
        for (let j = 0; j < first.length; j++) if (above !== (B < j)) first[j]++;
        work += first.length;
      }
      const mids = [];
      for (let t = 0; t + 1 < n; t++) {
        const ni = cols[ks[t]].length + 1, nj = cols[ks[t + 1]].length + 1;
        const D = Array.from({ length: ni + 1 }, () => new Float64Array(nj + 1));
        const rect = (i0, i1, j0, j1) => { if (i0 > i1 || j0 > j1) return; D[i0][j0]++; D[i0][j1 + 1]--; D[i1 + 1][j0]--; D[i1 + 1][j1 + 1]++; };
        for (const h of gapHops[ks[t]]) {
          if (h.E === E) continue;
          const A = IX(h.a), B = IX(h.b);
          rect(A + 1, ni - 1, 0, B); rect(0, A, B + 1, nj - 1);
        }
        for (let i = 0; i < ni; i++) for (let j = 0; j < nj; j++) D[i][j] += (i ? D[i - 1][j] : 0) + (j ? D[i][j - 1] : 0) - (i && j ? D[i - 1][j - 1] : 0);
        work += ni * nj + gapHops[ks[t]].length;
        mids.push(D);
      }
      const last = new Float64Array(cols[ks[n - 1]].length + 1);
      for (const h of gapHops[ks[n - 1]]) {
        if (h.E === E || h.b === T) continue;
        const above = h.b.rank < T.rank, A = IX(h.a);
        for (let i = 0; i < last.length; i++) if ((A < i) !== above) last[i]++;
        work += last.length;
      }
      const costOf = (sl) => { let v = first[sl[0]] + last[sl[n - 1]]; for (let t = 0; t + 1 < n; t++) v += mids[t][sl[t]][sl[t + 1]]; return v; };
      let bestV = new Float64Array(cols[ks[0]].length + 1).fill(Infinity);
      for (let j = ranges[0][0]; j <= ranges[0][1]; j++) bestV[j] = first[j];
      const arg = [];
      for (let t = 1; t < n; t++) {
        const nv = new Float64Array(cols[ks[t]].length + 1).fill(Infinity), na = new Int32Array(nv.length).fill(-1);
        for (let j = ranges[t][0]; j <= ranges[t][1]; j++)
          for (let i = ranges[t - 1][0]; i <= ranges[t - 1][1]; i++) { const v = bestV[i] + mids[t - 1][i][j]; if (v < nv[j]) { nv[j] = v; na[j] = i; } }
        arg.push(na); bestV = nv;
      }
      let bv = Infinity, bj = -1;
      for (let i = ranges[n - 1][0]; i <= ranges[n - 1][1]; i++) { const v = bestV[i] + last[i]; if (v < bv) { bv = v; bj = i; } }
      const sl = new Array(n); sl[n - 1] = bj;
      for (let t = n - 1; t > 0; t--) sl[t - 1] = arg[t - 1][sl[t]];
      const better = bv < costOf(cur);
      const put = better ? sl : cur;
      lanes.forEach((it, t) => cols[ks[t]].splice(put[t], 0, it));
      for (const k of ks) { stack(k); rankCol(k); }
      return better;
    };
    // a chain whose end row sits in a follow card: try every slot of that row among the card's wired
    // rows, re-place the chain by the DP for each, keep the strict best (crossings counted in the
    // gaps that can change only)
    const crossIn = (gs) => { let v = 0; for (const g of gs) { v += inversions(gapHops[g].map((h) => [h.a.rank, h.b.rank])); work += gapHops[g].length; } return v; };
    const moveChainFree = (E) => {
      let improved = false;
      for (const end of [E.hops[0].a, E.hops[E.hops.length - 1].b]) {
        const it = end.item;
        if (!it.card.follow) continue;
        const k = it.card.col;
        const wired = it.ports.filter((p) => !unwired(p));
        if (wired.length < 2) continue;
        const ks = E.hops.slice(1).map((h) => h.a.col);
        const G = [...new Set([k - 1, k, ...E.hops.map((h) => h.gap)])].filter((g) => g >= 0 && g < nCol - 1);
        const base = crossIn(G), start = it.ports.slice(), saved = ks.map((kk) => cols[kk].slice());
        let best = base, bestPorts = null, bestCols = null;
        for (let pos = 0; pos < wired.length; pos++) {
          const rest = wired.filter((p) => p !== end);
          rest.splice(pos, 0, end);
          it.ports = [...rest, ...it.ports.filter((p) => unwired(p))];
          shape(it); stack(k); rankCol(k);
          moveChain(E);
          const v = crossIn(G);
          if (v < best) { best = v; bestPorts = it.ports.slice(); bestCols = ks.map((kk) => cols[kk].slice()); }
          ks.forEach((kk, t) => { cols[kk] = saved[t].slice(); stack(kk); rankCol(kk); });
        }
        if (bestPorts) { it.ports = bestPorts; ks.forEach((kk, t) => { cols[kk] = bestCols[t]; stack(kk); rankCol(kk); }); improved = true; }
        else it.ports = start;
        shape(it); stack(k); rankCol(k);
      }
      return improved;
    };
    // exact re-placement of a path of items, one per consecutive column, everything else fixed
    const colOfItem = (it) => (it.kind === "card" ? it.card.col : it.ports[0].col);
    const movePath = (path) => {
      const n = path.length, k0 = colOfItem(path[0]);
      if (path.some((it) => it.cls !== 1)) return false;
      const cur = path.map((it, t) => cols[k0 + t].indexOf(it));
      path.forEach((it, t) => cols[k0 + t].splice(cur[t], 1));
      const ranges = path.map((it, t) => {
        let lo = 0, hi = 0;
        for (const o of cols[k0 + t]) { const g = group(o, it); if (g < 0) lo++; if (g <= 0) hi++; }
        return [lo, hi];
      });
      const ixOf = new Map();
      for (let k = Math.max(0, k0 - 1); k <= Math.min(nCol - 1, k0 + n); k++) cols[k].forEach((o, i) => ixOf.set(o, i));
      const inP = new Map(path.map((it, t) => [it, t]));
      const unary = path.map((_, t) => new Float64Array(cols[k0 + t].length + 1));
      const pair = [];
      for (let g = k0 - 1; g <= k0 + n - 1; g++) {
        if (g < 0 || g >= nCol - 1) continue;
        const tl = g - k0, tr = g + 1 - k0, hasL = tl >= 0 && tl < n, hasR = tr >= 0 && tr < n;
        const ni = hasL ? cols[g].length + 1 : 1, nj = hasR ? cols[g + 1].length + 1 : 1;
        const D = Array.from({ length: ni + 1 }, () => new Float64Array(nj + 1));
        work += ni * nj;
        const rect = (i0, i1, j0, j1) => { i0 = Math.max(0, i0); j0 = Math.max(0, j0); i1 = Math.min(ni - 1, i1); j1 = Math.min(nj - 1, j1); if (i0 > i1 || j0 > j1) return; D[i0][j0]++; D[i0][j1 + 1]--; D[i1 + 1][j0]--; D[i1 + 1][j1 + 1]++; };
        const hs = gapHops[g], H = hs.length;
        const Lv = hs.map((h) => inP.has(h.a.item)), Rv = hs.map((h) => inP.has(h.b.item));
        const LB = hs.map((h, x) => (Lv[x] ? -1 : ixOf.get(h.a.item))), RB = hs.map((h, x) => (Rv[x] ? -1 : ixOf.get(h.b.item)));
        for (let x = 0; x < H; x++) {
          if (!Lv[x] && !Rv[x]) continue;
          for (let z = 0; z < H; z++) {
            if (z === x || ((Lv[z] || Rv[z]) && z < x)) continue;
            const X = hs[x], Z = hs[z];
            let lc = 0, lw = 0, lv = -1, rc = 0, rw = 0, rv = -1;
            if (Lv[x] && Lv[z]) lc = X.a === Z.a ? 0 : X.a.rank < Z.a.rank ? 1 : -1;
            else if (Lv[x]) { lw = 1; lv = LB[z]; } else if (Lv[z]) { lw = 2; lv = LB[x]; }
            else lc = X.a === Z.a ? 0 : X.a.rank < Z.a.rank ? 1 : -1;
            if (Rv[x] && Rv[z]) rc = X.b === Z.b ? 0 : X.b.rank < Z.b.rank ? 1 : -1;
            else if (Rv[x]) { rw = 1; rv = RB[z]; } else if (Rv[z]) { rw = 2; rv = RB[x]; }
            else rc = X.b === Z.b ? 0 : X.b.rank < Z.b.rank ? 1 : -1;
            if ((!lw && lc === 0) || (!rw && rc === 0)) continue;
            work += 4;
            for (let a = 0; a < (lw ? 2 : 1); a++) {
              const i0 = lw ? (a ? lv + 1 : 0) : 0, i1 = lw ? (a ? ni - 1 : lv) : ni - 1;
              const va = lw ? ((a === 0) === (lw === 1) ? 1 : -1) : lc;
              for (let b2 = 0; b2 < (rw ? 2 : 1); b2++) {
                const j0 = rw ? (b2 ? rv + 1 : 0) : 0, j1 = rw ? (b2 ? nj - 1 : rv) : nj - 1;
                const vb = rw ? ((b2 === 0) === (rw === 1) ? 1 : -1) : rc;
                if (va !== vb) rect(i0, i1, j0, j1);
              }
            }
          }
        }
        for (let i = 0; i < ni; i++) for (let j = 0; j < nj; j++) D[i][j] += (i ? D[i - 1][j] : 0) + (j ? D[i][j - 1] : 0) - (i && j ? D[i - 1][j - 1] : 0);
        if (hasL && hasR) pair[tl] = D;
        else if (hasL) for (let i = 0; i < ni; i++) unary[tl][i] += D[i][0];
        else if (hasR) for (let j = 0; j < nj; j++) unary[tr][j] += D[0][j];
      }
      const costOf = (sl) => sl.reduce((a, s2, t) => a + unary[t][s2] + (t + 1 < n ? pair[t][s2][sl[t + 1]] : 0), 0);
      let bestV = new Float64Array(cols[k0].length + 1).fill(Infinity);
      for (let j = ranges[0][0]; j <= ranges[0][1]; j++) bestV[j] = unary[0][j];
      const arg = [];
      for (let t = 1; t < n; t++) {
        const nv = new Float64Array(cols[k0 + t].length + 1).fill(Infinity), na = new Int32Array(nv.length).fill(-1);
        for (let j = ranges[t][0]; j <= ranges[t][1]; j++) {
          for (let i = ranges[t - 1][0]; i <= ranges[t - 1][1]; i++) { const v = bestV[i] + pair[t - 1][i][j]; if (v < nv[j]) { nv[j] = v; na[j] = i; } }
          nv[j] += unary[t][j];
        }
        arg.push(na); bestV = nv;
      }
      let bv = Infinity, bj = -1;
      for (let i = ranges[n - 1][0]; i <= ranges[n - 1][1]; i++) if (bestV[i] < bv) { bv = bestV[i]; bj = i; }
      const sl = new Array(n); sl[n - 1] = bj;
      for (let t = n - 1; t > 0; t--) sl[t - 1] = arg[t - 1][sl[t]];
      const better = bv < costOf(cur) - 1e-9;
      const put = better ? sl : cur;
      path.forEach((it, t) => cols[k0 + t].splice(put[t], 0, it));
      for (let t = 0; t < n; t++) { stack(k0 + t); rankCol(k0 + t); }
      return better;
    };
    const heavyPath = (it0) => {
      const out = [it0];
      for (const dir of [1, -1]) {
        let x = it0;
        for (;;) {
          const k = colOfItem(x), cnt = new Map();
          for (const p of x.ports) for (const h of (dir > 0 ? p.R : p.L)) { const y = (dir > 0 ? h.b : h.a).item; cnt.set(y, (cnt.get(y) || 0) + 1); }
          if (!cnt.size) break;
          const y = [...cnt.entries()].sort((p, q) => q[1] - p[1])[0][0];
          if (out.includes(y) || colOfItem(y) !== k + dir) break;
          if (dir > 0) out.push(y); else out.unshift(y);
          x = y;
        }
      }
      return out;
    };
    // refinement: exact moves of a long wire's lanes, of a follow card's end row with them, and
    // of whole paths; each starts only while work < ORDER_BUDGET and is kept only when it
    // strictly removes crossings. The candidate paths are listed once per pass, before any moves.
    T.refinePasses = 0;
    for (let pass = 0; pass < P.REFINE_PASSES && work < P.ORDER_BUDGET; pass++) {
      T.refinePasses++;
      let improved = false;
      for (const E of edges) { if (work >= P.ORDER_BUDGET) break; if (E.hops.length > 1 && moveChain(E)) improved = true; }
      for (const E of edges) { if (work >= P.ORDER_BUDGET) break; if (E.hops.length > 1 && moveChainFree(E)) improved = true; }
      const cands = [];
      for (const E of edges) if (E.hops.length > 1) cands.push([E.hops[0].a.item, ...E.hops.slice(1).map((h) => h.a.item), E.hops[E.hops.length - 1].b.item]);
      for (const its of cols) for (const it of its) if (it.kind === "card") { const hp = heavyPath(it); if (hp.length > 1) cands.push(hp); }
      for (const pth of cands) { if (work >= P.ORDER_BUDGET) break; if (movePath(pth)) improved = true; }
      if (!improved) break;
      for (let k = 0; k < nCol; k++) sift(k);
      transpose();
    }
    {
      // closing pass, never budgeted: adjacent swaps while any strictly removes crossings, ties
      // broken by frozen wants, so (crossings, inversions of the wants) falls and it ends with
      // improvable_swaps = 0
      for (const its of cols) for (const it of its) {
        it.want = itemBary(it, "R") ?? itemBary(it, "L") ?? it.y + it.span / 2;
        for (const p of it.ports) p.want = rowBary(p, "R") ?? rowBary(p, "L") ?? p.y;
      }
      T.closeSwaps = 0;
      for (let any = true; any;) {
        any = false;
        for (let k = 0; k < nCol; k++) {
          const its = cols[k];
          endRanks(k);
          for (let i = 0; i + 1 < its.length; i++) {
            const u = its[i], v = its[i + 1];
            if (group(u, v)) continue;
            const [c, r] = pairCross(u, v);
            if (r < c || (r === c && u.want > v.want + 1e-6)) { T.closeSwaps++; its[i] = v; its[i + 1] = u; rankCol(k); endRanks(k); any = true; }
          }
          for (const it of its) {
            if (it.kind !== "card" || !it.card.follow) continue;
            for (let i = 0; i + 1 < it.ports.length; i++) {
              const p = it.ports[i], q = it.ports[i + 1];
              if (unwired(p) || unwired(q)) continue;
              let c = 0, r = 0;
              for (const s of ["L", "R"]) for (const h of on(p, s)) for (const g of on(q, s)) {
                const a = other(h, p).rank, b = other(g, q).rank;
                if (a > b) c++; else if (a < b) r++;
              }
              if (r < c || (r === c && p.want > q.want + 1e-6)) { it.ports[i] = q; it.ports[i + 1] = p; shape(it); rankCol(k); any = true; }
            }
          }
          stack(k); rankCol(k);
        }
      }
    }
  } else {
    // pinned: each card is where the viewer put it, its rows in the viewer's order and place;
    // a lane goes into a gap its column leaves between cards (13 under one, 42 over the next,
    // 16 between lanes), at one level along its whole chain if any level inside the span of
    // its two ends is free in every column it crosses, else as near its straight line as each
    // column allows; lanes sharing a gap stack by that level
    for (const c of cards) {
      const a = PIN.cards[c.id], it = c.item, byF = new Map(c.rows.map((r) => [r.f.id, r]));
      it.ports = a.order.map((id) => byF.get(id));
      const t0 = a.tops[0] + it.ports[0].h / 2;
      it.ports.forEach((p, i) => { p.off = a.tops[i] + p.h / 2 - t0; });
      it.span = it.ports[it.ports.length - 1].off; it.top = t0; it.bot = a.h - t0;
      it.y = a.y + t0;
      for (const p of it.ports) p.y = it.y + p.off;
    }
    const slots = cols.map((its) => {
      const cs = its.filter((it) => it.kind === "card").sort((u, v) => u.y - u.top - (v.y - v.top) || u.key - v.key), S = [];
      let lo = -Infinity;                 // under every card above, the tallest included: cards may overlap
      for (let j = 0; j <= cs.length; j++) {
        if (j) lo = Math.max(lo, cs[j - 1].y + cs[j - 1].bot + P.CLEAR_CL);
        const hi = j < cs.length ? cs[j].y - cs[j].top - P.CLEAR_LC : Infinity;
        const cap = lo === -Infinity || hi === Infinity ? Infinity : hi >= lo ? Math.floor((hi - lo) / P.CLEAR_LL) + 1 : 0;
        S.push({ j, lo, hi, cap, lanes: [], card: cs[j] });
      }
      return S;
    });
    const free = (k, cls) => slots[k].filter((sl, j) => sl.lanes.length < sl.cap && (cls === 1 || j === (cls === 0 ? 0 : slots[k].length - 1)));
    const nearest = (S, y) => S.reduce((b, sl) => { const d = y < sl.lo ? sl.lo - y : y > sl.hi ? y - sl.hi : 0; return !b || d < b.d ? { sl, d } : b; }, null).sl;
    for (const E of edges) {
      if (E.hops.length < 2) continue;
      const ya = E.hops[0].a.y, yb = E.hops[E.hops.length - 1].b.y, lanes = E.hops.slice(1).map((h) => h.a), n = lanes.length;
      const cls = lanes[0].item.cls;
      let I = [[Math.min(ya, yb), Math.max(ya, yb)]];
      for (const p of lanes) {
        const S = free(p.col, cls), J = [];
        for (const [l, h] of I) for (const sl of S) { const lo = Math.max(l, sl.lo), hi = Math.min(h, sl.hi); if (lo <= hi) J.push([lo, hi]); }
        I = J;
      }
      let level = null;
      for (const [l, h] of I) { const y = Math.min(Math.max(ya, l), h); if (level === null || Math.abs(y - ya) < Math.abs(level - ya)) level = y; }
      let plan;
      if (level !== null) plan = lanes.map((p) => [nearest(free(p.col, cls), level), level]);
      else {
        // no one level: walk the chain from either end, each column keeping the level of the one
        // before as far as its gaps allow, and keep the walk the height solve would price lower
        const walk = (ps, y) => ps.map((p) => { const sl = nearest(free(p.col, cls), y); y = Math.min(Math.max(y, sl.lo), sl.hi); return [sl, y]; });
        const cost = (pl) => pl.reduce((a, [, y], t) => a + (t ? P.W_RUN * Math.abs(y - pl[t - 1][1]) : 0), P.W_MIX * (Math.abs(ya - pl[0][1]) + Math.abs(pl[n - 1][1] - yb)));
        const fwd = walk(lanes, ya), bwd = walk(lanes.slice().reverse(), yb).reverse();
        plan = cost(bwd) < cost(fwd) ? bwd : fwd;
      }
      lanes.forEach((p, t) => {
        plan[t][0].lanes.push(p);
        p.want = plan[t][1]; p.ya = ya; p.yb = yb;
      });
    }
    slots.forEach((S, k) => {
      cols[k] = [];
      for (const sl of S) {
        sl.lanes.sort((p, q) => p.want - q.want || p.ya - q.ya || p.yb - q.yb || p.E.i - q.E.i);
        const m = sl.lanes.length;
        sl.lanes.forEach((p, i) => {
          // a start that meets every constraint, which the pinned height solve requires
          p.y = sl.lo === -Infinity ? sl.hi - (m - 1 - i) * P.CLEAR_LL : sl.lo + i * P.CLEAR_LL;
          p.item.y = p.y;
          shape(p.item);
          cols[k].push(p.item);
        });
        if (sl.card) cols[k].push(sl.card);
      }
      rankCol(k);
    });
  }
  T.work = work;
  mark("order");

  // ── 5 ports ──
  for (const its of cols) for (const it of its) for (const p of it.ports) for (const s of ["L", "R"]) {
    const hs = on(p, s).slice().sort((g, h) => other(g, p).rank - other(h, p).rank || g.E.i - h.E.i);
    hs.forEach((h, i) => {
      const o = p.kind === "row" ? (i - (hs.length - 1) / 2) * P.PORT : 0;
      if (h.a === p) h.pa = o; else h.pb = o;
    });
  }

  // ── 6 heights ──
  let nv = 0;
  for (const its of cols) for (const it of its) { const v = nv++; for (const p of it.ports) { p.v = v; p.vo = p.off; } }
  const NE = [];
  for (const its of cols) for (let i = 1; i < its.length; i++) {
    const u = its[i - 1], v = its[i];
    if (PIN && u.kind === "card" && v.kind === "card") continue;   // both pinned: nothing to keep apart
    NE.push({ v: u.ports[0].v, w: v.ports[0].v, minlen: u.bot + clear(u, v) + v.top, weight: P.TIE });
  }
  if (PIN) for (const its of cols) {
    // a pinned card can reach below the card under it; a lane keeps clear of the lowest bottom above it
    let low = null;
    its.forEach((it, i) => {
      if (it.kind === "card") { if (!low || it.y + it.bot > low.y + low.bot) low = it; return; }
      if (low && its[i - 1] !== low) NE.push({ v: low.ports[0].v, w: it.ports[0].v, minlen: low.bot + clear(low, it), weight: 0 });
    });
  }
  // One root above the first item of every column, at no cost, keeps the graph connected
  // when a column holds no wire (a spec without edges). Never connect it with large negative
  // minlens instead: they bind, and draw a wireless spec millions of px tall.
  const root = nv + hops.length, init = new Float64Array(root + 1);
  if (!PIN) {
    for (const its of cols) for (const it of its) init[it.ports[0].v] = Math.round(it.y);
    init[root] = Infinity;
    for (const its of cols) if (its.length) {
      NE.push({ v: root, w: its[0].ports[0].v, minlen: 0, weight: 0 });
      init[root] = Math.min(init[root], init[its[0].ports[0].v]);
    }
  } else {
    // pinned: the root is y = 0 and every card is held at its y by a pair of opposite edges;
    // the start is the viewer's arrangement with each lane in its gap, feasible by construction
    for (const its of cols) for (const it of its) {
      init[it.ports[0].v] = it.y;
      if (it.kind === "card") NE.push({ v: root, w: it.ports[0].v, minlen: it.y, weight: 0 }, { v: it.ports[0].v, w: root, minlen: -it.y, weight: 0 });
    }
    init[root] = 0;
  }
  for (const h of hops) {
    const x = nv++;
    NE.push({ v: x, w: h.a.v, minlen: -(h.a.vo + h.pa), weight: h.w });
    NE.push({ v: x, w: h.b.v, minlen: -(h.b.vo + h.pb), weight: h.w });
    init[x] = PIN ? Math.min(h.a.y + h.pa, h.b.y + h.pb) : Math.min(Math.round(h.a.y + h.pa), Math.round(h.b.y + h.pb));
  }
  let Y = solve(root + 1, NE, { init, feasible: !!PIN });
  let y0 = PIN ? Y[root] : 0;
  for (const its of cols) for (const it of its) { it.y = Y[it.ports[0].v] - y0; for (const p of it.ports) p.y = it.y + p.off; }
  {
    // bounded port slide: shift each fan inside its row toward the median of its far ports, then re-solve once
    const fanPass = (order) => {
      for (const k of order) for (const it of cols[k]) for (const p of it.ports) {
        if (p.kind !== "row") continue;
        for (const s of ["L", "R"]) {
          const hs = on(p, s);
          if (!hs.length) continue;
          const sorted = hs.slice().sort((g, h) => other(g, p).rank - other(h, p).rank || g.E.i - h.E.i);
          const nominal = (i) => (i - (sorted.length - 1) / 2) * P.PORT;
          const want = sorted.map((h, i) => (h.a === p ? (h.b.y + h.pb) : (h.a.y + h.pa)) - (p.y + nominal(i))).sort((a, b) => a - b);
          const lo = want[(want.length - 1) >> 1], hi = want[want.length >> 1];
          const cur = (sorted[0].a === p ? sorted[0].pa : sorted[0].pb) - nominal(0);
          let t = cur >= lo && cur <= hi ? cur : (cur < lo ? lo : hi);
          t = Math.round(Math.max(-P.SLIDE, Math.min(P.SLIDE, t)));
          sorted.forEach((h, i) => { if (h.a === p) h.pa = nominal(i) + t; else h.pb = nominal(i) + t; });
        }
      }
    };
    const ks = cols.map((_, k) => k);
    fanPass(ks); fanPass(ks.slice().reverse());
    let e = NE.length - 2 * hops.length;
    const init2 = new Float64Array(root + 1);
    for (const its of cols) for (const it of its) init2[it.ports[0].v] = it.y;
    init2[root] = PIN ? 0 : Y[root];
    for (const h of hops) {
      NE[e].minlen = -(h.a.vo + h.pa); NE[e + 1].minlen = -(h.b.vo + h.pb);
      init2[NE[e].v] = Math.min(h.a.y + h.pa, h.b.y + h.pb);
      e += 2;
    }
    Y = solve(root + 1, NE, { init: init2, feasible: !!PIN });
    y0 = PIN ? Y[root] : 0;
    for (const its of cols) for (const it of its) { it.y = Y[it.ports[0].v] - y0; for (const p of it.ports) p.y = it.y + p.off; }
  }
  if (PIN) for (const c of cards) { c.y = PIN.cards[c.id].y; c.h = PIN.cards[c.id].h; }
  else {
    for (const c of cards) {
      const ps = c.item.ports, p0 = ps[0], pl = ps[ps.length - 1];
      c.y = p0.y - p0.h / 2 - P.HEADER_H;
      c.h = pl.y + pl.h / 2 - c.y;
    }
    let top = Infinity;
    for (const c of cards) top = Math.min(top, c.y - 30);
    for (const its of cols) for (const it of its) if (it.kind === "lane") top = Math.min(top, it.y - 20);
    for (const c of cards) c.y -= top;
    for (const its of cols) for (const it of its) { it.y -= top; for (const p of it.ports) p.y -= top; }
  }
  mark("heights");

  // ── 7-9 x, wires, labels, with a gap fixpoint for labels that still collide ──
  const colW = cols.map((its) => Math.max(P.MIN_CARD_W, ...its.filter((i) => i.kind === "card").map((i) => i.card.w)));
  const need = new Array(nCol).fill(0);
  const textW = (t) => t.length * P.LABEL_ADV + 4;
  const texts = [];
  edges.forEach((E) => {
    if (E.e.label) texts.push({ ei: E.i, kind: "label", text: E.e.label });
    if (E.e.note) texts.push({ ei: E.i, kind: "note", text: E.e.note });
  });
  for (const t of texts) { const g = edges[t.ei].hops[0].gap; need[g] = Math.max(need[g], textW(t.text) + 42); }
  const portY = (h, end) => (end === "a" ? h.a.y + h.pa : h.b.y + h.pb);
  let colX, gapW, routes, labelOverlaps, rounds = 0;
  for (;;) {
    gapW = gapHops.map((hs, g) => {
      let climb = 0;
      for (const h of hs) climb = Math.max(climb, Math.abs(portY(h, "b") - portY(h, "a")));
      return Math.max(P.MIN_GAP, need[g], Math.min(P.STEEP_CAP, climb * P.STEEP + hs.length * P.PER_WIRE));
    });
    colX = [];
    for (let k = 0, x = P.MARGIN; k < nCol; k++) { colX[k] = x; x += colW[k] + (gapW[k] || 0); }
    if (PIN) colX = PIN.colX.slice();     // pinned: nothing moves sideways, so no gap widens
    for (const c of cards) { c.x = colX[c.col]; c.w = colW[c.col]; }
    routes = edges.map((E) => ({ ...wireRoute(E.hops.map((h) => {
      const g = h.gap;
      return [colX[g] + colW[g], portY(h, "a"), colX[g + 1], portY(h, "b")];
    })), texts: [] }));
    const boxes = cardBoxes(cards), wireHits = wireGrid(routes);
    labelOverlaps = 0;
    const failing = [];
    for (const t of texts) {
      const { pick, score } = placeText(P, t, routes[t.ei], edges[t.ei].hops.length === 1, boxes, wireHits);
      if (score[0] > 0) { labelOverlaps++; failing.push(t); }
      routes[t.ei].texts.push({ ...t, x: pick.x, y: pick.y, anchor: pick.anchor, box: pick.box });
      boxes.push(pick.box);
    }
    if (PIN || !failing.length || rounds >= P.LABEL_ROUNDS) break;
    rounds++;
    const byGap = new Map();
    for (const t of texts) { const g = edges[t.ei].hops[0].gap; (byGap.get(g) || byGap.set(g, []).get(g)).push(textW(t.text)); }
    for (const g of new Set(failing.map((t) => edges[t.ei].hops[0].gap))) {
      const ws = byGap.get(g).sort((p, q) => q - p);
      const want = (ws[0] || 0) + (ws[1] || 0) + 46;
      need[g] = Math.max(need[g] + 40 * (want <= gapW[g] ? 1 : 0), want);
    }
  }
  T.labelRounds = rounds;
  mark("labels");

  // ── 11 publish ──
  // Published arrays keep spec order (the page draws and traces by spec index); every
  // number is rounded to 0.01 so the determinism test can compare the JSON byte for byte.
  const specIx = new Map((SPEC.edges || []).map((e, i) => [e, i]));
  const bySpec = edges.slice().sort((x, y) => specIx.get(x.e) - specIx.get(y.e));
  const pub = {
    cards: Object.fromEntries(cards.map((c) => [c.id, {
      x: r2(c.x), y: r2(c.y), w: r2(c.w), h: r2(c.h), col: c.col, order: cols[c.col].indexOf(c.item),
      rowOrder: c.item.ports.map((p) => p.f.id),
      rows: Object.fromEntries(c.item.ports.map((p) => [p.f.id, { y: r2(p.y), h: r2(p.h) }])) }])),
    columns: cols.map((its, k) => ({ x: r2(colX[k]), w: r2(colW[k]),
      items: its.map((it) => (it.kind === "card" ? { card: it.card.id } : { lane: specIx.get(it.E.e) })) })),
    wires: bySpec.map((E) => { const R = routes[E.i];
      return { from: E.e.from, to: E.e.to, start: R.head.map(r2), end: R.tail.map(r2),
        hops: R.hopGeo.map((g) => g.map(r2)), samples: R.samples.map((q) => q.map(r2)) }; }),
    labels: bySpec.flatMap((E) => routes[E.i].texts.map((t) => ({ edge: specIx.get(E.e), kind: t.kind,
      ...Object.fromEntries(Object.entries(t.box).map(([k, v]) => [k, r2(v)])) }))),
  };
  mark("publish");
  const report = measure(SPEC, pub);
  mark("report");
  T.total = r2(clock() - tStart);
  T.solves = solves;
  return { cards, cols, edges, routes, colX, layout: pub, report, T };
}

// The measures of the layout, recomputed from what was published and nothing else:
// ranks come from `columns` and `rowOrder`, coordinates from `wires[].hops` and the card
// boxes, so a test can feed in a mutated copy, and a fault in the ordering stage cannot
// certify itself through the same code that made it.
//
// Targets (render.py --check fails unless each is 0): behind_card, label_overlaps,
// source_slack, improvable_swaps, loose_sources. The rest are reported for judgment.
function measure(spec, L) {
  const edges = spec.edges || [], cardOf = (end) => end.slice(0, end.indexOf("."));
  const ins = new Map(), outs = new Map(), fedBy = new Map(), feeds = new Map();
  for (const c of spec.cards) { feeds.set(c.id, new Set()); fedBy.set(c.id, new Set()); }
  for (const e of edges) {
    outs.set(e.from, (outs.get(e.from) || 0) + 1); ins.set(e.to, (ins.get(e.to) || 0) + 1);
    feeds.get(cardOf(e.from)).add(cardOf(e.to)); fedBy.get(cardOf(e.to)).add(cardOf(e.from));
  }
  // a source is a card that nothing feeds and that feeds something; a card without wires is not one
  const isSource = (id) => !fedBy.get(id).size && feeds.get(id).size > 0;
  const isSink = (id) => !feeds.get(id).size && fedBy.get(id).size > 0;
  const follow = new Set(spec.cards.filter((c) => c.rows === "follow").map((c) => c.id));
  // groups: (flow, lane class); flows are weakly connected components, cards without wires share one
  const flow = new Map();
  let nFlow = 0;
  for (const c of spec.cards) {
    if (flow.has(c.id) || (!feeds.get(c.id).size && !fedBy.get(c.id).size)) continue;
    const st = [c.id];
    flow.set(c.id, nFlow);
    while (st.length) for (const y of [...feeds.get(st[st.length - 1]), ...fedBy.get(st.pop())]) if (!flow.has(y)) { flow.set(y, nFlow); st.push(y); }
    nFlow++;
  }
  const r2 = (v) => Math.round(v * 100) / 100;

  // ports: a row or a lane; each knows its column, rank, item and the hops on its two sides
  const items = [], portOf = new Map(), lanePort = new Map();
  L.columns.forEach((col, k) => {
    let rank = 0;
    col.items.forEach((x, order) => {
      const it = x.card !== undefined
        ? { card: x.card, k, order, group: [flow.get(x.card) ?? nFlow, 1], ports: [] }
        : { lane: x.lane, k, order, group: [flow.get(cardOf(edges[x.lane].from)), edges[x.lane].lane === "above" ? 0 : edges[x.lane].lane === "below" ? 2 : 1], ports: [] };
      const ids = it.card !== undefined ? L.cards[it.card].rowOrder.map((f) => `${it.card}.${f}`) : [null];
      for (const id of ids) {
        const p = { id, item: it, k, rank: rank++, L: [], R: [] };
        it.ports.push(p);
        if (id) portOf.set(id, p); else lanePort.set(`${it.lane}@${k}`, p);
      }
      items.push(it);
    });
  });
  const hops = [], byGap = new Map();
  L.wires.forEach((w, ei) => {
    const e = edges[ei], k0 = L.cards[cardOf(e.from)].col;
    w.hops.forEach(([x1, y1, x2, y2], t) => {
      const a = t === 0 ? portOf.get(e.from) : lanePort.get(`${ei}@${k0 + t}`);
      const b = t === w.hops.length - 1 ? portOf.get(e.to) : lanePort.get(`${ei}@${k0 + t + 1}`);
      const h = { ei, t, a, b, x1, y1, x2, y2, gap: k0 + t };
      a.R.push(h); b.L.push(h); hops.push(h);
      (byGap.get(h.gap) || byGap.set(h.gap, []).get(h.gap)).push(h);
    });
  });
  const far = (h, p) => (h.a === p ? h.b : h.a);
  const sameGroup = (u, v) => u.group[0] === v.group[0] && u.group[1] === v.group[1];

  // behind_card: wire samples strictly inside a card that is not one of the wire's ends,
  // tested against the cards of the column whose x-range holds the sample
  let behind = 0;
  const colCards = L.columns.map((col) => col.items.filter((x) => x.card !== undefined).map((x) => [x.card, L.cards[x.card]]));
  L.wires.forEach((w, ei) => {
    const own = [cardOf(edges[ei].from), cardOf(edges[ei].to)];
    for (const [x, y] of w.samples) {
      const k = L.columns.findIndex((c) => x > c.x + 1 && x < c.x + c.w - 1);
      if (k < 0) continue;
      for (const [id, c] of colCards[k]) if (!own.includes(id) && y > c.y + 1 && y < c.y + c.h - 1) behind++;
    }
  });

  // label_overlaps: texts whose box overlaps a card (with its stage-label band) or another text
  const boxes = Object.values(L.cards).map((c) => ({ x: c.x - 2, y: c.y - 24, w: c.w + 4, h: c.h + 24 }));
  const hit = (b, o) => Math.min(b.x + b.w, o.x + o.w) - Math.max(b.x, o.x) > 0 && Math.min(b.y + b.h, o.y + o.h) - Math.max(b.y, o.y) > 0;
  const labelOverlaps = L.labels.filter((t, i) => boxes.some((o) => hit(t, o)) || L.labels.some((o, j) => j !== i && hit(t, o))).length;

  // source_slack: how far each source sits left of one column before its nearest consumer
  let slack = 0;
  for (const c of spec.cards) if (isSource(c.id)) slack += Math.min(...[...feeds.get(c.id)].map((v) => L.cards[v].col)) - L.cards[c.id].col - 1;

  // improvable_swaps: neighbours in one column (same group), and neighbouring wired rows of a
  // follow card, whose swap would strictly remove crossings; counted hop pair by hop pair
  const swapGain = (P, Q) => {
    let c = 0, r = 0;
    for (const s of ["L", "R"]) for (const p of P) for (const h of p[s]) for (const q of Q) for (const g of q[s]) {
      const a = far(h, p).rank, b = far(g, q).rank;
      if (a > b) c++; else if (a < b) r++;
    }
    return r < c;
  };
  let improvable = 0;
  const wired = (p) => p.L.length + p.R.length > 0;
  for (let i = 0; i + 1 < items.length; i++) {
    const u = items[i], v = items[i + 1];
    if (u.k === v.k && sameGroup(u, v) && swapGain(u.ports, v.ports)) improvable++;
  }
  for (const it of items) if (it.card !== undefined && follow.has(it.card))
    for (let i = 0; i + 1 < it.ports.length; i++) {
      const p = it.ports[i], q = it.ports[i + 1];
      if (wired(p) && wired(q) && swapGain([p], [q])) improvable++;
    }

  // loose_sources: sources that could move 1 px up or down without breaking a separation in
  // their column and would thereby lower the weighted climb of their own wires (stage 6's ω)
  const omega = (h) => {
    const rr = h.a.id && h.b.id;
    let w = rr ? 1000 : h.a.id || h.b.id ? 2000 : 8000;
    if (rr && outs.get(h.a.id) === 1 && ins.get(h.b.id) === 1) w *= 4;
    if (h.t === 0 && !fedBy.get(cardOf(edges[h.ei].from)).size) w = (w * 7) / 4;
    return w;
  };
  const top = (it) => (it.card !== undefined ? L.cards[it.card].y : it.ports[0].R[0].y1);
  const bot = (it) => (it.card !== undefined ? L.cards[it.card].y + L.cards[it.card].h : it.ports[0].R[0].y1);
  const clear = (u, v) => (u.card !== undefined ? (v.card !== undefined ? 40 : 13) : (v.card !== undefined ? 42 : 16));
  let loose = 0;
  items.forEach((it, i) => {
    if (it.card === undefined || !isSource(it.card)) return;
    const up = items[i - 1], down = items[i + 1];
    const upFree = !up || up.k !== it.k || top(it) - bot(up) - clear(up, it) >= 1 - 1e-9;
    const downFree = !down || down.k !== it.k || top(down) - bot(it) - clear(it, down) >= 1 - 1e-9;
    const cost = (d) => it.ports.reduce((x, p) => x + p.R.reduce((y, h) => y + omega(h) * Math.abs(h.y1 + d - h.y2), 0), 0);
    if ((upFree && cost(-1) < cost(0) - 1e-9) || (downFree && cost(1) < cost(0) - 1e-9)) loose++;
  });

  // crossings: crossing points; all hops in one gap share x(t), so two cross exactly once
  // when their end ranks are inverted and never otherwise
  let crossings = 0;
  for (const hs of byGap.values()) for (let i = 0; i < hs.length; i++) for (let j = i + 1; j < hs.length; j++)
    if ((hs[i].a.rank - hs[j].a.rank) * (hs[i].b.rank - hs[j].b.rank) < 0) crossings++;

  // dock_inversions: neighbours where a source stacks on the wrong side of the other's wires
  // (right side), or a card that feeds nothing on the wrong side (left side)
  let dockInv = 0;
  const ends = (it, s) => it.ports.flatMap((p) => p[s].map((h) => (s === "R" ? h.y2 : h.y1)));
  for (let i = 0; i + 1 < items.length; i++) {
    const u = items[i], v = items[i + 1];
    if (u.k !== v.k || !sameGroup(u, v)) continue;
    const src = (it) => it.card !== undefined && isSource(it.card), snk = (it) => it.card !== undefined && isSink(it.card);
    for (const s of ["R", "L"]) {
      if (!(s === "R" ? src(u) || src(v) : snk(u) || snk(v))) continue;
      const eu = ends(u, s), ev = ends(v, s);
      if (eu.length && ev.length && Math.min(...eu) > Math.max(...ev) + 0.5) dockInv++;
    }
  }

  let dock = 0, straight = 0, travel = 0, steep = 0;
  for (const h of hops) {
    const d = Math.abs(h.y2 - h.y1);
    travel += d; if (d < 0.5) straight++;
    steep = Math.max(steep, d / (h.x2 - h.x1));
    if (h.t === 0 && isSource(cardOf(edges[h.ei].from))) dock = Math.max(dock, d);
  }
  // copy_bend: the worst climb inside an order-preserving block of two or more 1:1 copies
  // between the same two cards
  let copyBend = 0;
  const blocks = new Map();
  for (const h of hops) if (h.a.id && h.b.id && outs.get(h.a.id) === 1 && ins.get(h.b.id) === 1) {
    const key = h.a.item.card + ">" + h.b.item.card;
    (blocks.get(key) || blocks.set(key, []).get(key)).push(h);
  }
  for (const hs of blocks.values()) {
    if (hs.length < 2) continue;
    hs.sort((g, h) => g.a.rank - h.a.rank);
    if (hs.every((h, i) => !i || h.b.rank > hs[i - 1].b.rank)) for (const h of hs) copyBend = Math.max(copyBend, Math.abs(h.y2 - h.y1));
  }
  // detour: the worst multi-column wire's length minus its chord
  let detour = 0;
  for (const w of L.wires) {
    if (w.hops.length < 2) continue;
    let len = 0;
    for (let k = 1; k < w.samples.length; k++) len += Math.hypot(w.samples[k][0] - w.samples[k - 1][0], w.samples[k][1] - w.samples[k - 1][1]);
    detour = Math.max(detour, len - Math.hypot(w.end[0] - w.start[0], w.end[1] - w.start[1]));
  }
  // extent: what the camera fits, card boxes with their stage band and samples with 10 px around them
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const c of Object.values(L.cards)) { x0 = Math.min(x0, c.x); x1 = Math.max(x1, c.x + c.w); y0 = Math.min(y0, c.y - 30); y1 = Math.max(y1, c.y + c.h); }
  for (const w of L.wires) for (const [, y] of w.samples) { y0 = Math.min(y0, y - 10); y1 = Math.max(y1, y + 10); }
  return {
    behind_card: behind, label_overlaps: labelOverlaps, source_slack: slack, improvable_swaps: improvable, loose_sources: loose,
    crossings, dock_inversions: dockInv, max_dock_climb: r2(dock), copy_bend: r2(copyBend), straight, hops: hops.length,
    travel: r2(travel), max_steepness: r2(steep), detour: r2(detour), width: r2(x1 - x0), height: r2(y1 - y0),
  };
}

