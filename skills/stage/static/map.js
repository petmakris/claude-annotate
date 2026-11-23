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

export function renderMap(box, spec, embedded) {
  box.dataset.room = 16;   // the foot of the board the map keeps clear: the call's panel sits beside the stage, not over it
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
// Every map reads in one direction, whatever loops it has. A way back is drawn as a curve under the map
// (or up a lane on the right, top to bottom), and an arrow from a part to itself as a small loop over it.
// There is no ring: laying parts round a circle loses the direction, and the reader cannot tell where the
// flow starts or ends.
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
  return { cols: cols.filter(Boolean), back, self };
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
  const plan = across(box, st, L, width, height) || down(box, st, L, width, height);
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
    const hr = halves(box, w, false), hc = halves(box, cw, true);
    const big = (id) => Math.max(hr.get(id), hc.get(id));
    const looped = new Set([...self].map((i) => edges[i].from));
    const step = c > 1 ? Math.min(w + GAP_X * 2.2, (width - 2 * SIDE - cw) / (c - 1)) : 0;
    const left = (width - step * (c - 1)) / 2;
    const xy = new Map();
    let lowest = 0, highest = Infinity;
    const colOf = new Map();
    cols.forEach((col, i) => {
      const ys = [0];
      for (let j = 1; j < col.length; j++) {
        const [a, b] = [col[j - 1], col[j]];
        const need = Math.max(hr.get(a) + hc.get(b), hc.get(a) + hr.get(b)) + AIR_Y + (looped.has(b) ? LOOP : 0);
        ys.push(ys[j - 1] + Math.max(need, Math.min(H + GAP_Y * 2, (height - 40) / col.length)));
      }
      const span = ys[ys.length - 1], over = big(col[0]) + (looped.has(col[0]) ? LOOP : 0);
      const top = Math.max(SIDE + over, height / 2 - span / 2);
      col.forEach((id, j) => {
        xy.set(id, [left + i * step, top + ys[j]]); colOf.set(id, i);
        lowest = Math.max(lowest, top + ys[j] + big(id)); highest = Math.min(highest, top + ys[j] - big(id));
      });
    });
    const tall = Math.max(height, lowest + SIDE + (back.size ? 40 + 26 * back.size : 0));
    return { mode: "across", w, cw, xy, hr, hc, lowest, highest, colOf, tall, back, self, width };
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

// The arrows, their heads and their labels, for where the parts are and which of them is the card being
// said: an arrow stops at the edge of the card it meets, however large that card is now.
function draw(box) {
  const st = box._map, P = st.plan;
  if (!P) return;
  const svg = box.querySelector(".m-edges"), edges = st.spec.edges || [];
  const half = (id) => (st.cur === "node:" + id ? [P.cw / 2, P.hc.get(id)] : [P.w / 2, P.hr.get(id)]);
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
    g.classList.toggle("m-back", P.back.has(i));
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

// A way back: across, out of the foot of one card, under the map and up into the foot of the other; when a
// card sits under either end and none over them, out of the top and over the map instead, so the arrow never
// runs through a card. Top to bottom, out of one card's right side, up the lane on the right and into the other's.
function backArrow(P, e, half, k) {
  const a = P.xy.get(e.from), b = P.xy.get(e.to), [aw, ah] = half(e.from), [bw, bh] = half(e.to);
  let p0, p1, p2, p3;
  if (P.mode === "across") {
    const o = (k - (P.back.size - 1) / 2) * 18, above = P.highest - 22 - 26 * k;
    const beside = (id, sign) => [...P.xy].some(([other, [, y]]) => other !== id && P.colOf.get(other) === P.colOf.get(id) && sign * (y - P.xy.get(id)[1]) > 0);
    const over = above > SIDE && (beside(e.from, 1) || beside(e.to, 1)) && !beside(e.from, -1) && !beside(e.to, -1);
    if (over) {
      p0 = [a[0] + o, a[1] - ah]; p3 = [b[0] + o, b[1] - bh - 5]; p1 = [p0[0], above]; p2 = [p3[0], above];
    } else {
      const below = P.lowest + 22 + 26 * k;
      p0 = [a[0] + o, a[1] + ah]; p3 = [b[0] + o, b[1] + bh + 5]; p1 = [p0[0], below]; p2 = [p3[0], below];
    }
  } else {
    const side = P.lane + 14 + 22 * k;
    p0 = [a[0] + aw, a[1]]; p3 = [b[0] + bw + 5, b[1]]; p1 = [side, a[1]]; p2 = [side, b[1]];
  }
  return [{ d: path(p0, p1, p2, p3), end: p3, toward: p2, start: p0, away: p1 }, ALONG.map(bezier(p0, p1, p2, p3))];
}

// An arrow from a part to itself: a small loop over its card, its label beyond the loop. Both its ends sit
// on the card's rim.
function selfLoop(P, id, half, spread) {
  const [x, y] = P.xy.get(id), [hw, hh] = half(id);
  const ux = 0, uy = -1;
  const t = Math.min(hw / Math.abs(ux || 1e-6), hh / Math.abs(uy || 1e-6));
  const reach = 44 + 16 * Math.abs(spread), px = x + ux * t, py = y + uy * t, vx = -uy, vy = ux;
  const onCard = ([qx, qy]) => [Math.min(Math.max(qx, x - hw), x + hw), Math.min(Math.max(qy, y - hh), y + hh)];
  const s = onCard([px + vx * 16, py + vy * 16]), back = onCard([px - vx * 16, py - vy * 16]);
  const end = [back[0] + ux * 5, back[1] + uy * 5];
  const c1 = [s[0] + ux * reach + vx * 26, s[1] + uy * reach + vy * 26], c2 = [end[0] + ux * reach - vx * 26, end[1] + uy * reach - vy * 26];
  const tip = [px + ux * (reach * 0.75 + 14), py + uy * (reach * 0.75 + 14)];
  return [{ d: path(s, c1, c2, end), end, toward: c2, start: s, away: c1 },
    [tip, [tip[0] + 60, tip[1]], [tip[0] - 60, tip[1]]]];
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
