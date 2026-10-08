// The map: a flowchart drawn by the stage itself, for a talk call. The whole map is there from the
// start as faint dashed ghosts, so the reader sees the size of what is coming; the voice lights it
// part by part. The part being said is a large card with its detail; every arrow that arrives on a step
// forward draws in, and a dot travels along the one into that card.
//
// The scene engine (scene.js) shows and lights the keys (`node:<id>`, `edge:<a>-><b>#<n>`); on this
// board a key not shown yet is a ghost rather than hidden (stage.css), and after each frame
// layoutMap marks the part the frame names as being said, and the arrow into it.
//
// The parts are placed once for the board's size, with room round every one of them for the large card
// it becomes when said, so that cards, labels and heads stay clear of each other and on the board. Only
// the arrows and their labels are redrawn when the card being said changes, to meet its edge.

import { beingSaid } from "./scene.js";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// a long name breaks between its words: before a capital that follows a small letter, after . _ / -
const breakable = (t) => esc(t).replace(/([a-z0-9])(?=[A-Z])|([._/-])(?=\w)/g, "$1$2<wbr>");
const TONE = { entry: "edge", code: "plain", call: "plain", decision: "internal", success: "good", error: "hot" };
const W = 180, H = 52;         // a part at rest; the one being said grows to a card over it
const GAP_X = 70, GAP_Y = 34;  // between columns, between parts in a column, when there is room
const AIR_X = 26, AIR_Y = 30;  // the least room between two cards: an arrow and its head still show in it
const SIDE = 12;               // the board's margin, which no card crosses
const LOOP = 58;               // above a part with an arrow to itself: the loop and its label
const ROOM = 210;              // in a call, the map stays clear of the subtitles below it

export function renderMap(box, spec, embedded) {
  box.dataset.room = embedded ? ROOM : 16;
  box.style.marginBottom = embedded ? ROOM + "px" : "";  // the board centres the map with its room, so the room is all below it
  box._map = { spec, embedded, cur: null };
  const nodes = spec.nodes || [], edges = spec.edges || [];
  const seen = new Map();
  const ekeys = edges.map((e) => {
    const pair = e.from + "->" + e.to, n = seen.get(pair) || 0;
    seen.set(pair, n + 1);
    return `edge:${pair}#${n}`;
  });
  box._map.ekeys = ekeys;
  box._map.pairs = seen;
  box.innerHTML = `<svg class="m-edges" aria-hidden="true"><defs></defs>${edges.map((e, i) => {
      // a Mermaid link keeps its look: dashed for a dotted one, a head at both ends or at neither
      const tone = TONE[(nodes.find((n) => n.id === e.from) || {}).role] || "plain";
      const heads = e.heads === "none" ? "" : `<path class="m-tip"/>${e.heads === "both" ? '<path class="m-tip m-tail"/>' : ""}`;
      return `<g class="m-edge t-${tone}${e.line === "dashed" ? " m-dashed" : ""}" data-key="${esc(ekeys[i])}"><path class="m-line"/>${heads}
        ${e.label ? `<g class="m-elabel"><rect rx="8"/><text>${esc(e.label)}</text></g>` : ""}</g>`;
    }).join("")}</svg>
    ${nodes.map((n) => {
      const detail = n.method || n.ref;
      return `<div class="m-node t-${TONE[n.role] || "plain"} m-${esc(n.role || "code")}" data-key="node:${esc(n.id)}" data-node="${esc(n.id)}">
        <b>${breakable(n.label || n.id)}</b>${detail ? `<code>${breakable(detail)}</code>` : ""}${n.sub ? `<span class="m-sub">${breakable(n.sub)}</span>` : ""}</div>`;
    }).join("")}`;
  place(box);
  if (!box._mapObserved) {
    box._mapObserved = true;
    new ResizeObserver(() => place(box)).observe(box);
    document.fonts?.ready.then(() => place(box));  // the cards are measured: again once the stage's fonts are in
  }
}

// Columns by depth: a part sits one column right of the deepest part that leads to it. A loop is cut at
// the arrow that goes back, found walking forward from where the flow starts. In a column, parts are
// ordered by where the parts feeding them sit, so arrows cross as little as they can.
//
// A real state machine is drawn as a ring (`ring`): one with several loops, or with its entry inside a
// loop. A single way back (a retry) is drawn in the columns, as a curve under the map, and an arrow from a
// part to itself as a small loop over that part; neither turns a pipeline into a ring.
function layers(spec) {
  const nodes = spec.nodes || [], edges = spec.edges || [];
  const ids = new Set(nodes.map((n) => n.id));
  const out = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e, i) => { if (ids.has(e.from) && ids.has(e.to)) out.get(e.from).push(i); });
  const back = new Set(), self = new Set(), state = new Map();  // 1: on the walk, 2: done
  const walk = (id) => {
    state.set(id, 1);
    for (const i of out.get(id)) {
      const to = edges[i].to;
      if (to === id) self.add(i);
      else if (state.get(to) === 1) back.add(i);
      else if (!state.has(to)) walk(to);
    }
    state.set(id, 2);
  };
  const hasIn = new Set(edges.map((e) => e.to));
  const starts = [...nodes.filter((n) => n.role === "entry"), ...nodes.filter((n) => !hasIn.has(n.id)), ...nodes];
  for (const n of starts) if (!state.has(n.id)) walk(n.id);
  const ins = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e, i) => { if (!back.has(i) && !self.has(i) && ids.has(e.from) && ids.has(e.to)) ins.get(e.to).push(e.from); });
  const depth = new Map();
  const deep = (id) => {
    if (depth.has(id)) return depth.get(id);
    depth.set(id, 0);
    const d = Math.max(0, ...ins.get(id).map((p) => deep(p) + 1));
    depth.set(id, d);
    return d;
  };
  nodes.forEach((n) => deep(n.id));
  const cols = [];
  nodes.forEach((n) => { (cols[depth.get(n.id)] ||= []).push(n.id); });
  const pos = new Map();
  cols.forEach((c) => c.forEach((id, i) => pos.set(id, i)));
  for (let sweep = 0; sweep < 2; sweep++) {
    for (const c of cols.slice(1)) {
      const bary = (id) => { const ps = ins.get(id); return ps.length ? ps.reduce((s, p) => s + pos.get(p), 0) / ps.length : pos.get(id); };
      c.sort((a, b) => bary(a) - bary(b));
      c.forEach((id, i) => pos.set(id, i));
    }
  }
  // the entry is inside a loop when it reaches the loop's way back and the way back reaches it
  const reach = (from) => {
    const got = new Set([from]), todo = [from];
    while (todo.length) for (const i of out.get(todo.pop())) if (!got.has(edges[i].to)) { got.add(edges[i].to); todo.push(edges[i].to); }
    return got;
  };
  const entries = nodes.filter((n) => n.role === "entry").map((n) => n.id);
  const looped = entries.some((id) => [...back].some((i) => reach(id).has(edges[i].from) && reach(edges[i].to).has(id)));
  return { cols: cols.filter(Boolean), back, self, ring: back.size > 1 || (back.size === 1 && looped) };
}

// Half the height of every part at a width, at rest or as the card being said, measured on a copy laid
// out where the real one is. A board not laid out yet (a hidden pane) measures nothing: then a guess,
// and the board is placed again when it shows.
function halves(box, w, cur) {
  const out = new Map();
  for (const el of box.querySelectorAll(":scope > .m-node")) {
    const c = el.cloneNode(true);
    c.classList.remove("k-hidden", "k-focus", "m-cur");
    if (cur) c.classList.add("m-cur");
    c.style.cssText = `width:${w}px;left:0;top:0;transition:none;animation:none;visibility:hidden`;
    box.append(c);
    const h = c.getBoundingClientRect().height;
    c.remove();
    out.set(el.dataset.node, (h || (cur ? 100 : H)) / 2);
  }
  return out;
}

function place(box) {
  const st = box._map;
  if (!st) return;
  const L = layers(st.spec);
  const width = box.clientWidth || 900;
  const scroller = box.closest(".pbody");
  const height = Math.max(320, (scroller ? scroller.clientHeight - 32 : 480) - (+box.dataset.room || 16));
  const plan = (L.ring && ring(box, st, L, width, height)) || across(box, st, L, width, height) || down(box, st, L, width, height);
  box.classList.toggle("m-ring", plan.mode === "ring");
  box.dataset.layout = plan.mode;
  box.style.setProperty("--mw", plan.w + "px");
  box.style.setProperty("--mc", plan.cw + "px");
  box.style.height = plan.tall + "px";
  st.plan = plan;
  for (const el of box.querySelectorAll(".m-node")) {
    const [x, y] = plan.xy.get(el.dataset.node);
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  const svg = box.querySelector(".m-edges");
  svg.setAttribute("viewBox", `0 0 ${width} ${plan.tall}`);
  svg.style.height = plan.tall + "px";
  draw(box);
}

// The card being said is larger than a part at rest by how much room the board has: up to 260px wide,
// and never so wide that it would reach a neighbour or the board's edge (`fit`, for n parts in a line).
const fit = (n, w, room, air, most) => Math.min(most, n > 1 ? (room - (n - 1) * (w / 2 + air)) / ((n + 1) / 2) : room);

// Left to right while the columns fit, narrowing the parts a little first. In a column the parts are as
// far apart as either of two neighbours needs when it is the card being said; a column taller than the
// board makes the board scroll, and the card being said is kept in view (layoutMap).
function across(box, st, L, width, height) {
  const { cols, back, self } = L, c = cols.length, edges = st.spec.edges || [];
  const sizes = [[W, 260], [150, 240], [130, 220]];
  for (const [k, [w, most]] of sizes.entries()) {
    const cw = fit(c, w, width - 2 * SIDE, AIR_X, most);
    if (cw < (k < sizes.length - 1 ? Math.min(most, w + 60) : w)) continue;
    box.classList.remove("m-ring");
    const hr = halves(box, w, false), hc = halves(box, cw, true);
    const big = (id) => Math.max(hr.get(id), hc.get(id));
    const looped = new Set([...self].map((i) => edges[i].from));
    const step = c > 1 ? Math.min(w + GAP_X * 2.2, (width - 2 * SIDE - cw) / (c - 1)) : 0;
    const left = (width - step * (c - 1)) / 2;
    const xy = new Map();
    let lowest = 0;
    cols.forEach((col, i) => {
      const ys = [0];
      for (let j = 1; j < col.length; j++) {
        const [a, b] = [col[j - 1], col[j]];
        const need = Math.max(hr.get(a) + hc.get(b), hc.get(a) + hr.get(b)) + AIR_Y + (looped.has(b) ? LOOP : 0);
        ys.push(ys[j - 1] + Math.max(need, Math.min(H + GAP_Y * 2, (height - 40) / col.length)));
      }
      const span = ys[ys.length - 1], over = big(col[0]) + (looped.has(col[0]) ? LOOP : 0);
      const top = Math.max(SIDE + over, height / 2 - span / 2);
      col.forEach((id, j) => { xy.set(id, [left + i * step, top + ys[j]]); lowest = Math.max(lowest, top + ys[j] + big(id)); });
    });
    const tall = Math.max(height, lowest + SIDE + (back.size ? 40 + 26 * back.size : 0));
    return { mode: "across", w, cw, xy, hr, hc, lowest, tall, back, self, width };
  }
  return null;
}

// Top to bottom when the columns do not fit across: each column becomes a row, split over more rows when
// it holds more parts than the width does. The parts narrow to fit their row; ways back run down a lane
// kept clear on the right.
function down(box, st, L, width) {
  const { cols, back, self } = L, edges = st.spec.edges || [];
  const lane = back.size ? 24 + 22 * back.size : 0, room = width - 2 * SIDE - lane;
  const most = Math.max(...cols.map((c) => c.length));
  let rows, w, cw;
  for (let per = most; per >= 1 && !rows; per--) {
    for (const size of [W, 150, 130, 120, 110]) {
      w = Math.min(size, room);
      cw = fit(per, w, room, AIR_X / 2, 260);
      if (cw >= w) { rows = cols.flatMap((c) => Array.from({ length: Math.ceil(c.length / per) }, (_, i) => c.slice(i * per, i * per + per))); break; }
    }
  }
  if (!rows) { w = cw = Math.max(80, room); rows = cols.flatMap((c) => c.map((id) => [id])); }
  box.classList.remove("m-ring");
  const hr = halves(box, w, false), hc = halves(box, cw, true);
  const looped = new Set([...self].map((i) => edges[i].from)), labelled = new Set(edges.filter((e) => e.label).map((e) => e.to));
  const most2 = (row, m) => Math.max(...row.map((id) => m.get(id)));
  const xy = new Map(), mid = SIDE + room / 2;
  let y = 0, lowest = 0;
  rows.forEach((row, r) => {
    if (r === 0) y = SIDE + Math.max(most2(row, hr), most2(row, hc)) + (row.some((id) => looped.has(id)) ? LOOP : 0);
    else {
      const prev = rows[r - 1];
      const need = Math.max(most2(prev, hc) + most2(row, hr), most2(prev, hr) + most2(row, hc)) + AIR_Y
        + (row.some((id) => labelled.has(id)) ? 24 : 0) + (row.some((id) => looped.has(id)) ? LOOP : 0);
      y += Math.max(need, H + GAP_Y * 1.6);
    }
    const step = row.length > 1 ? Math.min(W + GAP_X, (room - cw) / (row.length - 1)) : 0;
    row.forEach((id, j) => { xy.set(id, [mid + (j - (row.length - 1) / 2) * step, y]); lowest = Math.max(lowest, y + Math.max(hr.get(id), hc.get(id))); });
  });
  return { mode: "down", w, cw, xy, hr, hc, lowest, tall: lowest + SIDE + 16, back, self, width, lane: SIDE + room };
}

// A state machine is a ring: the states round an ellipse in the order the flow reaches them, clockwise
// from the top. An arrow to the next state round bows outward; any other (a way back, a skip) curves
// across the inside. The ring narrows its states on a narrow board; one that still cannot hold them apart,
// with room for the card being said at any of them, is drawn top to bottom instead.
const RW = 170;
function ring(box, st, L, width, height) {
  const order = L.cols.flat(), n = order.length, cx = width / 2, cy = height / 2;
  box.classList.add("m-ring");
  for (const [w, most] of [[RW, 270], [150, 230], [130, 190]]) {
    const hr = halves(box, w, false), hcAt = halves(box, Math.min(most, width - 2 * SIDE), true);
    const tallest = Math.max(...hcAt.values());
    const cw = Math.min(most, width - 2 * SIDE);
    const rx = Math.min(width / 2 - cw / 2 - SIDE, 420), ry = Math.min(height / 2 - tallest - SIDE, 200);
    if (rx < w / 2 || ry < H) continue;
    const xy = new Map();
    order.forEach((id, i) => {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
      xy.set(id, [cx + rx * Math.cos(a), cy + ry * Math.sin(a)]);
    });
    const plan = { mode: "ring", w, cw, xy, hr, hc: hcAt, tall: height, back: L.back, self: L.self, width, cx, cy, at: new Map(order.map((id, i) => [id, i])) };
    if (apart(plan, width)) return plan;
  }
  box.classList.remove("m-ring");
  return null;
}

// No two parts at rest touch, and none touches the card being said, whichever part that is; and the card
// being said stays on the board.
function apart(plan, width) {
  const ids = [...plan.xy.keys()];
  const rest = (id, air) => { const [x, y] = plan.xy.get(id), h = plan.hr.get(id); return [x - plan.w / 2 - air, y - h - air, x + plan.w / 2 + air, y + h + air]; };
  const big = (id) => { const [x, y] = plan.xy.get(id), h = plan.hc.get(id); return [x - plan.cw / 2, y - h, x + plan.cw / 2, y + h]; };
  const hit = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  for (const a of ids) {
    const card = big(a);
    if (card[0] < SIDE - 1 || card[2] > width - SIDE + 1 || card[1] < 0) return false;
    for (const b of ids) if (a !== b && (hit(rest(a, 6), rest(b, 6)) || hit(card, rest(b, 8)))) return false;
  }
  return true;
}

// The arrows, their heads and their labels, for where the parts are and which of them is the card being
// said: an arrow stops at the edge of the card it meets, however large that card is now.
function draw(box) {
  const st = box._map, P = st.plan;
  if (!P) return;
  const svg = box.querySelector(".m-edges"), edges = st.spec.edges || [];
  const half = (id) => (st.cur === "node:" + id ? [P.cw / 2, P.hc.get(id)] : [P.w / 2, P.hr.get(id)]);
  // where a line from a card's middle towards (x, y) leaves the card, with a little air
  const rim = (id, x, y, air = 5) => {
    const [cx, cy] = P.xy.get(id), [hw, hh] = half(id), dx = x - cx, dy = y - cy;
    const t = Math.min((hw + air) / Math.abs(dx || 1e-6), (hh + air) / Math.abs(dy || 1e-6), 1);
    return [cx + dx * t, cy + dy * t];
  };
  const under = (id, x, y) => { const [cx, cy] = P.xy.get(id), [hw, hh] = half(id); return Math.abs(x - cx) < hw + 8 && Math.abs(y - cy) < hh + 8; };
  const seen = new Map(), labels = [];
  edges.forEach((e, i) => {
    const g = svg.querySelector(`[data-key="${st.ekeys[i]}"]`), a = P.xy.get(e.from), b = P.xy.get(e.to);
    if (!g || !a || !b) return;
    // arrows between the same two parts bend apart, each on its own curve
    const pair = e.from + "->" + e.to, nth = seen.get(pair) || 0, count = st.pairs.get(pair) || 1;
    seen.set(pair, nth + 1);
    const spread = (nth - (count - 1) / 2);
    let curve, spots;
    if (P.self.has(i)) [curve, spots] = selfLoop(P, e.from, half, spread);
    else if (P.mode === "ring") [curve, spots] = ringArrow(P, e, rim, under, spread);
    else if (P.back.has(i)) [curve, spots] = backArrow(P, e, half, [...P.back].indexOf(i));
    else [curve, spots] = forward(P, e, half, spread);
    const line = g.querySelector(".m-line");
    line.setAttribute("d", curve.d);
    if (line.classList.contains("m-draw")) line.style.setProperty("--len", Math.ceil(line.getTotalLength ? line.getTotalLength() : 600));
    // the head points along the curve's last stretch, into the card; a head at the start along its first
    const tip = ([tx, ty], [qx, qy]) => {
      const ang = Math.atan2(ty - qy, tx - qx), c = Math.cos(ang), s = Math.sin(ang);
      const pt = (u, v) => `${tx - c * u + s * v} ${ty - s * u - c * v}`;
      return `M ${tx} ${ty} L ${pt(12, 6)} L ${pt(12, -6)} Z`;
    };
    g.querySelector(".m-tip:not(.m-tail)")?.setAttribute("d", tip(curve.end, curve.toward));
    g.querySelector(".m-tail")?.setAttribute("d", tip(curve.start, curve.away));
    g.classList.toggle("m-back", P.mode === "ring" ? !curve.next : P.back.has(i));
    const label = g.querySelector(".m-elabel");
    // last, the same spots a little off the arrow
    if (label) labels.push({ label, spots: [...spots, ...spots.flatMap(([x, y]) => [[x, y - 24], [x, y + 24]])] });
  });
  // each label takes the first of its spots (on its own arrow first) that is clear of the cards and of the
  // labels placed before it, else the one that covers least
  const cards = [...P.xy.keys()].map((id) => { const [x, y] = P.xy.get(id), [hw, hh] = half(id); return [x - hw - 2, y - hh - 2, x + hw + 2, y + hh + 2]; });
  const placed = [];
  const cover = (x, y, w) => [...placed, ...cards].reduce((s, [l, t, r, b]) =>
    s + Math.max(0, Math.min(x + w / 2, r) - Math.max(x - w / 2, l)) * Math.max(0, Math.min(y + 12, b) - Math.max(y - 12, t)), 0);
  for (const L of labels) {
    const t = L.label.querySelector("text");
    t.setAttribute("x", 0);
    const w = (t.getComputedTextLength ? t.getComputedTextLength() : 60) + 18;
    const keep = ([x, y]) => [Math.max(SIDE + w / 2, Math.min(P.width - SIDE - w / 2, x)), y];
    let best = null;
    for (const spot of L.spots.map(keep)) {
      const c = cover(spot[0], spot[1], w + 4);
      if (!best || c < best.c) best = { spot, c };
      if (c === 0) break;
    }
    const [x, y] = best.spot;
    placed.push([x - w / 2 - 4, y - 13, x + w / 2 + 4, y + 13]);
    t.setAttribute("x", x); t.setAttribute("y", y + 4);
    const r = L.label.querySelector("rect");
    r.setAttribute("x", x - w / 2); r.setAttribute("y", y - 11); r.setAttribute("width", w); r.setAttribute("height", 22);
  }
}

const bezier = (p0, p1, p2, p3) => (t) => [0, 1].map((k) => (1 - t) ** 3 * p0[k] + 3 * (1 - t) ** 2 * t * p1[k] + 3 * (1 - t) * t ** 2 * p2[k] + t ** 3 * p3[k]);
const path = (p0, p1, p2, p3) => `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`;
const ALONG = [0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78];

// An arrow forward: out of one card's side (or foot, top to bottom) into the next's.
function forward(P, e, half, spread) {
  const a = P.xy.get(e.from), b = P.xy.get(e.to), [aw, ah] = half(e.from), [bw, bh] = half(e.to);
  let p0, p3, p1, p2;
  if (P.mode === "across") {
    const o = spread * 10, x1 = a[0] + aw, x2 = b[0] - bw - 5, c = (x2 - x1) / 2;
    p0 = [x1, a[1] + o]; p3 = [x2, b[1] + o]; p1 = [x1 + c, a[1] + spread * 36]; p2 = [x2 - c, b[1] + spread * 36];
  } else {
    const o = spread * 10, y1 = a[1] + ah, y2 = b[1] - bh - 5, c = (y2 - y1) / 2;
    p0 = [a[0] + o, y1]; p3 = [b[0] + o, y2]; p1 = [a[0] + spread * 36, y1 + c]; p2 = [b[0] + spread * 36, y2 - c];
  }
  const at = bezier(p0, p1, p2, p3);
  const top = Math.min(a[1] - ah, b[1] - bh) - 14, foot = Math.max(a[1] + ah, b[1] + bh) + 14, mx = (a[0] + b[0]) / 2;
  const beside = P.mode === "across" ? [[mx, top], [mx, foot]] : [[Math.max(a[0] + aw, b[0] + bw) + 60, (a[1] + b[1]) / 2]];
  return [{ d: path(p0, p1, p2, p3), end: p3, toward: p2, start: p0, away: p1 }, [...ALONG.map(at), ...beside]];
}

// A way back: across, out of the foot of one card, under the map and up into the foot of the other; top to
// bottom, out of one card's right side, up the lane on the right and into the other's.
function backArrow(P, e, half, k) {
  const a = P.xy.get(e.from), b = P.xy.get(e.to), [aw, ah] = half(e.from), [bw, bh] = half(e.to);
  let p0, p1, p2, p3;
  if (P.mode === "across") {
    const below = P.lowest + 22 + 26 * k, o = (k - (P.back.size - 1) / 2) * 18;
    p0 = [a[0] + o, a[1] + ah]; p3 = [b[0] + o, b[1] + bh + 5]; p1 = [p0[0], below]; p2 = [p3[0], below];
  } else {
    const side = P.lane + 14 + 22 * k;
    p0 = [a[0] + aw, a[1]]; p3 = [b[0] + bw + 5, b[1]]; p1 = [side, a[1]]; p2 = [side, b[1]];
  }
  return [{ d: path(p0, p1, p2, p3), end: p3, toward: p2, start: p0, away: p1 }, ALONG.map(bezier(p0, p1, p2, p3))];
}

// An arrow from a part to itself: a small loop over its card (on the ring, on its outer side), its label
// beyond the loop.
function selfLoop(P, id, half, spread) {
  const [x, y] = P.xy.get(id), [hw, hh] = half(id);
  let ux = 0, uy = -1;
  if (P.mode === "ring") { const dx = x - P.cx, dy = y - P.cy, n = Math.hypot(dx, dy) || 1; ux = dx / n; uy = dy / n; }
  const t = Math.min(hw / Math.abs(ux || 1e-6), hh / Math.abs(uy || 1e-6));
  const reach = 44 + 16 * Math.abs(spread), px = x + ux * t, py = y + uy * t, vx = -uy, vy = ux;
  const s = [px + vx * 16, py + vy * 16], end = [px - vx * 16 + ux * 5, py - vy * 16 + uy * 5];
  const c1 = [s[0] + ux * reach + vx * 26, s[1] + uy * reach + vy * 26], c2 = [end[0] + ux * reach - vx * 26, end[1] + uy * reach - vy * 26];
  const tip = [px + ux * (reach * 0.75 + 14), py + uy * (reach * 0.75 + 14)];
  return [{ d: path(s, c1, c2, end), end, toward: c2, start: s, away: c1 },
    [tip, [tip[0] + 60, tip[1]], [tip[0] - 60, tip[1]]]];
}

// On the ring: bent at right angles to the straight line between the two states, away from the middle for
// the next state round, towards it for the rest; a line through the middle bends to its left. Arrows
// between the same two states bow by different amounts.
function ringArrow(P, e, rim, under, spread) {
  const a = P.xy.get(e.from), b = P.xy.get(e.to), n = P.at.size;
  const next = (P.at.get(e.from) + 1) % n === P.at.get(e.to);
  const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  let px = -(b[1] - a[1]) / len, py = (b[0] - a[0]) / len;
  const toMiddle = (P.cx - mx) * px + (P.cy - my) * py;
  if (Math.abs(toMiddle) > 8 && (toMiddle > 0) === next) { px = -px; py = -py; }
  // a bend that would sit under one of the two cards (the card being said is large) is flattened until it
  // clears them, and a line too short to bend runs straight from rim to rim
  let bow = (next ? 40 : Math.min(70, len * 0.18)) + spread * 34, qx, qy;
  for (;; bow /= 2) {
    qx = mx + px * bow; qy = my + py * bow;
    if (Math.abs(bow) < 4) { bow = 0; qx = mx; qy = my; break; }
    if (!under(e.from, qx, qy) && !under(e.to, qx, qy)) break;
  }
  let [sx, sy] = rim(e.from, qx, qy), [tx, ty] = rim(e.to, qx, qy);
  if (under(e.from, qx, qy) || under(e.to, qx, qy)) { [sx, sy] = rim(e.from, b[0], b[1]); [tx, ty] = rim(e.to, a[0], a[1]); qx = (sx + tx) / 2; qy = (sy + ty) / 2; }
  const at = (t) => [(1 - t) ** 2 * sx + 2 * (1 - t) * t * qx + t ** 2 * tx, (1 - t) ** 2 * sy + 2 * (1 - t) * t * qy + t ** 2 * ty];
  return [{ d: `M ${sx} ${sy} Q ${qx} ${qy} ${tx} ${ty}`, end: [tx, ty], toward: [qx, qy], start: [sx, sy], away: [qx, qy], next },
    ALONG.map(at)];
}

// After a frame: the part being said and the arrow into it, as the frame names them (beingSaid). On a step
// forward (`stepped`: the frame before this one was the one on the board), every arrow that arrived with
// the frame draws in and the dot travels along the one being said; Back, a jump and a repaint draw the
// same picture still. Returns the card being said, which the board keeps in view.
export function layoutMap(box, scene, n, stepped = false) {
  const st = box._map;
  if (!st) return null;
  const said = scene && n != null ? beingSaid(scene, n) : [];
  const node = said.filter((k) => k.startsWith("node:")).pop() || null;
  if (st.cur !== node) { st.cur = node; draw(box); }  // the arrows meet the card being said at its new size
  // of the arrows named, the one into that card, else one out of it, else the last
  const named = said.filter((k) => k.startsWith("edge:")), id = node && node.slice(5);
  const edge = named.find((k) => node && k.endsWith("->" + id + k.slice(k.lastIndexOf("#"))))
    || named.find((k) => node && k.startsWith("edge:" + id + "->")) || named.pop() || null;
  const last = scene ? Math.min(n ?? 0, scene.frames.length - 1) : 0;
  const before = stepped && last > 0 ? new Set(scene.frames[last - 1].show) : null;
  const arrived = new Set(before ? scene.frames[last].show.filter((k) => k.startsWith("edge:") && !before.has(k)) : []);
  for (const el of box.querySelectorAll(".m-node")) el.classList.toggle("m-cur", el.dataset.key === node);
  for (const g of box.querySelectorAll(".m-edge")) {
    const key = g.dataset.key, on = key === edge;
    g.classList.toggle("m-cur", on);
    g.querySelector(".m-dot")?.remove();
    const line = g.querySelector(".m-line");
    if (!arrived.has(key)) { line.classList.remove("m-draw"); continue; }
    line.classList.remove("m-draw"); void line.getBBox(); line.classList.add("m-draw");
    line.addEventListener("animationend", () => line.classList.remove("m-draw"), { once: true });
    line.style.setProperty("--len", Math.ceil(line.getTotalLength ? line.getTotalLength() : 600));
    if (on && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("r", "6"); dot.setAttribute("class", "m-dot");
      dot.innerHTML = `<animateMotion dur="1.1s" begin="indefinite" fill="freeze" path="${line.getAttribute("d")}"/>`;
      g.append(dot);
      dot.firstElementChild.beginElement();
    }
  }
  return box.querySelector(".m-node.m-cur");
}
