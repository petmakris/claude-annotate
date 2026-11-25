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
import { routeEdges, rounded } from "./route.js";
import { placeEdgeLabels } from "./map_labels.js";

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
        <b style="overflow-wrap:normal">${breakable(n.label || n.id)}</b>${detail ? `<code>${breakable(detail)}</code>` : ""}${n.sub ? `<span class="m-sub">${breakable(n.sub)}</span>` : ""}</div>`;
    }).join("")}`;
  place(box);
  if (!box._mapObserved) {
    box._mapObserved = true;
    // The pane changes height when the sentence strip comes and goes. A pane that shrinks places the board again (it
    // would not fit); one that grows leaves it where it is, pinned to the pane's top, so the row of parts does not move
    // when the answer is over and the strip is gone.
    const ro = new ResizeObserver(() => {
      const sc = box.closest(".pbody"), now = [box.clientWidth, sc ? sc.clientHeight : 0], was = box._mapPane;
      if (was && now[0] === was[0] && now[1] >= was[1] - 2) return;
      place(box);
    });
    ro.observe(box);
    if (box.closest(".pbody")) ro.observe(box.closest(".pbody"));
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
  box.style.transform = ""; box.style.marginBottom = "";   // measured at its own size; fitScale scales it again at the end
  const L = layers(st.spec);
  const width = box.clientWidth || 900;
  const scroller = box.closest(".pbody");
  // the room the pane leaves the board: its height less everything else in it (padding, gaps, what stands beside the
  // board), so the board fits whole and the pane never scrolls by a few pixels when a part is said (stage.js `centre`
  // scrolls it then, and the row of parts jumped)
  const others = scroller ? Math.max(0, scroller.scrollHeight - box.offsetHeight) : 32;
  const height = Math.max(320, (scroller ? scroller.clientHeight - others : 480) - (+box.dataset.room || 16));
  const need = wordNeed(box);
  // As large as the pane lets it be (up to 1.8 times; type grows with it, --ms), so a map on a TV does not sit as a
  // small block in an empty pane; one that does not fit even at its own size scrolls, as before.
  let plan = null;
  for (const s of [1.8, 1.6, 1.4, 1.25, 1.12]) {
    const p = across(box, st, L, width, height, s, need);
    if (p && p.tall <= height + 1) { plan = p; break; }
  }
  plan = plan || across(box, st, L, width, height, 1, need) || down(box, st, L, width, height, need);
  plan.avail = height;
  box.style.setProperty("--ms", plan.s || 1);
  box._mapPane = [box.clientWidth, scroller ? scroller.clientHeight : 0];
  box.dataset.layout = plan.mode;
  box.style.setProperty("--mw", plan.w + "px");
  box.style.setProperty("--mc", plan.cw + "px");
  box.style.height = plan.tall + "px";
  st.plan = plan;
  fitScale(box);
  for (const el of box.querySelectorAll(".m-node")) {
    const [x, y] = plan.xy.get(el.dataset.node);
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  const svg = box.querySelector(".m-edges");
  svg.setAttribute("viewBox", `0 0 ${width} ${plan.tall}`);
  svg.style.height = plan.tall + "px";
  draw(box);
}

// The least width a part needs so that no word of its name breaks in the middle: its longest word, measured at the type's
// own size (`--ms` 1) as a copy laid out at its minimum content width, for the part at rest and for the card being said.
// Scaled with the type by `needW`.
function wordNeed(box) {
  const keep = box.style.getPropertyValue("--ms");
  box.style.setProperty("--ms", "1");
  const out = { rest: 0, cur: 0 };
  for (const el of box.querySelectorAll(":scope > .m-node")) {
    for (const cur of [false, true]) {
      const c = el.cloneNode(true);
      c.classList.remove("k-hidden", "k-focus", "m-cur");
      if (cur) c.classList.add("m-cur");
      c.style.cssText = "width:min-content;left:0;top:0;transition:none;animation:none;visibility:hidden";
      box.append(c);
      const w = c.getBoundingClientRect().width;
      c.remove();
      out[cur ? "cur" : "rest"] = Math.max(out[cur ? "cur" : "rest"], w);
    }
  }
  if (keep) box.style.setProperty("--ms", keep); else box.style.removeProperty("--ms");
  return out;
}
// A need at type scale s: the type grows with s, the padding (28 at rest, 36 as the card) does not.
const needW = (need, s, pad) => Math.min(260 * s, Math.max(0, (need - pad) * s + pad));

// At rest the whole board is in view: a board taller than its pane is scaled down to the pane (down to half its size), where it
// used to be cropped at the foot and scrolled. While a part is said the board is at its own size and the stage keeps
// that part in view.
function fitScale(box) {
  const st = box._map, P = st && st.plan;
  if (!P) return;
  const fits = P.avail / P.tall;   // a board that would have to shrink below half its size is left at its own size, to scroll
  const k = st.cur === null && fits < 1 && fits >= 0.5 ? fits : 1;
  box.style.transformOrigin = "top center";
  box.style.transition = "transform .3s";
  box.style.transform = k < 1 ? `scale(${k})` : "";
  box.style.marginBottom = k < 1 ? `${-(1 - k) * P.tall}px` : "";
  box.dataset.fit = k < 1 ? k.toFixed(3) : "1";
}

// The card being said is larger than a part at rest by how much room the board has: up to 260px wide,
// and never so wide that it would reach a neighbour or the board's edge (`fit`, for n parts in a line).
const fit = (n, w, room, air, most) => Math.min(most, n > 1 ? (room - (n - 1) * (w / 2 + air)) / ((n + 1) / 2) : room);

// Left to right while the columns fit, narrowing the parts a little first. In a column the parts are as
// far apart as either of two neighbours needs when it is the card being said; a column taller than the
// board makes the board scroll, and the card being said is kept in view (layoutMap).
function across(box, st, L, width, height, s = 1, need = { rest: 0, cur: 0 }) {
  const { cols, back, self } = L, c = cols.length, edges = st.spec.edges || [];
  const sizes = [[W * s, 260 * s], [150 * s, 240 * s], [130 * s, 220 * s]];
  const nr = needW(need.rest, s, 28), nc = needW(need.cur, s, 36);   // no part's name breaks inside a word
  for (const [k, [size, most]] of sizes.entries()) {
    const w = Math.max(size, nr);
    const cw = fit(c, w, width - 2 * SIDE, AIR_X, most);
    if (cw < Math.max(nc, k < sizes.length - 1 ? Math.min(most, w + 60) : w)) continue;
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
        ys.push(ys[j - 1] + Math.max(need, Math.min((H + GAP_Y * 2) * s, (height - 40) / col.length)));
      }
      const span = ys[ys.length - 1], over = big(col[0]) + (looped.has(col[0]) ? LOOP : 0);
      const top = Math.max(SIDE + over, height / 2 - span / 2);
      col.forEach((id, j) => {
        xy.set(id, [left + i * step, top + ys[j]]); colOf.set(id, i);
        lowest = Math.max(lowest, top + ys[j] + big(id)); highest = Math.min(highest, top + ys[j] - big(id));
      });
    });
    const tall = Math.max(height, lowest + SIDE + (back.size ? 40 + 26 * back.size : 0));
    return { mode: "across", s, w, cw, xy, hr, hc, lowest, highest, colOf, rank: colOf, tall, back, self, width };
  }
  return null;
}

// Top to bottom when the columns do not fit across: each column becomes a row, split over more rows when
// it holds more parts than the width does. The parts narrow to fit their row; ways back run down a lane
// kept clear on the right.
function down(box, st, L, width, height, need = { rest: 0, cur: 0 }) {
  const { cols, back, self } = L, edges = st.spec.edges || [];
  const lane = back.size ? 24 + 22 * back.size : 0, room = width - 2 * SIDE - lane;
  const most = Math.max(...cols.map((c) => c.length));
  let rows, w, cw;
  for (let per = most; per >= 1 && !rows; per--) {
    for (const size of [W, 150, 130, 120, 110]) {
      w = Math.min(Math.max(size, needW(need.rest, 1, 28)), room);
      cw = fit(per, w, room, AIR_X / 2, 260);
      if (cw >= w && (cw >= needW(need.cur, 1, 36) || per === 1)) { rows = cols.flatMap((c) => Array.from({ length: Math.ceil(c.length / per) }, (_, i) => c.slice(i * per, i * per + per))); break; }
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
  const rank = new Map();
  rows.forEach((row, r) => row.forEach((id) => rank.set(id, r)));
  return { mode: "down", w, cw, xy, hr, hc, lowest, tall: lowest + SIDE + 16, back, self, width, lane: SIDE + room, rank };
}

// The arrows, their heads and their labels, for where the parts are and which of them is the card being
// said: an arrow stops at the edge of the card it meets, however large that card is now. The routes come from
// route.js (round every part, each on a lane of its own); a label sits on its own arrow, where nothing else is.
const MAXLINE = 170;   // a label wraps at this width
function draw(box) {
  const st = box._map, P = st.plan;
  if (!P) return;
  const svg = box.querySelector(".m-edges"), edges = st.spec.edges || [];
  const half = (id) => (st.cur === "node:" + id ? [P.cw / 2, P.hc.get(id)] : [P.w / 2, P.hr.get(id)]);
  const nodes = new Map([...P.xy].map(([id, [x, y]]) => { const [hw, hh] = half(id); return [id, { x, y, hw, hh }]; }));
  const list = edges.map((e, i) => ({ i, from: e.from, to: e.to, back: P.back.has(i), self: P.self.has(i) })).filter((e) => P.xy.has(e.from) && P.xy.has(e.to));
  const routes = routeEdges({ mode: P.mode, nodes, rank: P.rank, edges: list,
    bounds: { width: P.width, tall: P.tall, side: SIDE, laneBase: P.mode === "across" ? 22 : 16, laneStep: P.mode === "across" ? 26 : 20 } });
  st.routes = routes;
  const seen = new Map(), labels = [];
  edges.forEach((e, i) => {
    const g = svg.querySelector(`[data-key="${st.ekeys[i]}"]`), r = routes.get(i);
    if (!g || !r) return;
    const pair = e.from + "->" + e.to, nth = seen.get(pair) || 0, count = st.pairs.get(pair) || 1;
    seen.set(pair, nth + 1);
    let d, end, toward, start, away, spots = null, pts = r.pts;
    if (r.kind === "loop") {
      const [curve, sp] = selfLoop(P, e.from, half, nth - (count - 1) / 2);
      d = curve.d; end = curve.end; toward = curve.toward; start = curve.start; away = curve.away; spots = sp; pts = [];
    } else {
      d = rounded(pts, 12); end = pts[pts.length - 1]; toward = pts[pts.length - 2]; start = pts[0]; away = pts[1];
    }
    const line = g.querySelector(".m-line");
    line.setAttribute("d", d);
    if (line.classList.contains("m-draw")) line.style.setProperty("--len", Math.ceil(line.getTotalLength ? line.getTotalLength() : 600));
    // the head points along the last stretch, into the card; a head at the start along its first
    const tip = ([tx, ty], [qx, qy]) => {
      const ang = Math.atan2(ty - qy, tx - qx), c = Math.cos(ang), s2 = Math.sin(ang);
      const pt = (u, v) => `${tx - c * u + s2 * v} ${ty - s2 * u - c * v}`;
      return `M ${tx} ${ty} L ${pt(12, 6)} L ${pt(12, -6)} Z`;
    };
    g.querySelector(".m-tip:not(.m-tail)")?.setAttribute("d", tip(end, toward));
    g.querySelector(".m-tail")?.setAttribute("d", tip(start, away));
    g.classList.toggle("m-back", P.back.has(i));
    const label = g.querySelector(".m-elabel");
    if (label) labels.push({ i, label, pts, spots, end, start, text: e.label });
  });
  placeLabels(P, labels, nodes, routes);
}

// Each label (wrapped to MAXLINE, padded 8 by 3) goes to the place on its own arrow that costs least (map_labels.js decides:
// on a part, on another label, on another arrow or its head all cost; the middle of the longest stretch is the first choice).
function placeLabels(P, labels, nodes, routes) {
  const cards = [...nodes.values()].map((n) => [n.x - n.hw - 3, n.y - n.hh - 3, n.x + n.hw + 3, n.y + n.hh + 3]);
  const sized = labels.map((L) => {
    const rows = wrap(L.label.querySelector("text"), L.text, MAXLINE);
    return { ...L, rows, w: Math.max(...rows.map((x) => x.w)) + 16, h: rows.length * 15 + 6 };
  });
  const spots = placeEdgeLabels({ labels: sized, cards, routes, width: P.width, side: SIDE, across: P.mode === "across" });
  for (const L of sized) {
    const best = spots.get(L.i), { x, y } = best, { rows, w, h } = L;
    const t = L.label.querySelector("text");
    const top = y - (rows.length * 15) / 2;
    t.replaceChildren();
    rows.forEach((row, k) => {
      const ts = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
      ts.setAttribute("x", x); ts.setAttribute("y", top + 11.5 + k * 15); ts.textContent = row.text; t.append(ts);
    });
    // an arrow's label off the arrow is joined to it by a leader, from the label to the nearest point of its arrow
    let lead = L.label.querySelector(".m-lead");
    if (best.off) {
      if (!lead) { lead = document.createElementNS("http://www.w3.org/2000/svg", "path"); lead.setAttribute("class", "m-lead"); L.label.prepend(lead); }
      lead.setAttribute("d", `M ${best.at[0]} ${best.at[1]} L ${x} ${y}`);
    } else lead?.remove();
    const rc = L.label.querySelector("rect");
    rc.setAttribute("x", x - w / 2); rc.setAttribute("y", y - h / 2); rc.setAttribute("width", w); rc.setAttribute("height", h);
  }
}

// A label's words in lines no wider than `max`, each with its width (the text element measures, in its own font).
function wrap(t, text, max) {
  const words = String(text || "").split(/\s+/).filter(Boolean), rows = [];
  const width = (s) => { t.textContent = s; return t.getComputedTextLength ? t.getComputedTextLength() : s.length * 7; };
  let cur = "";
  for (const wd of words) {
    const next = cur ? cur + " " + wd : wd;
    if (cur && width(next) > max) { rows.push({ text: cur, w: width(cur) }); cur = wd; } else cur = next;
  }
  if (cur) rows.push({ text: cur, w: width(cur) });
  return rows.length ? rows.slice(0, 3) : [{ text: "", w: 0 }];
}

const path = (p0, p1, p2, p3) => `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`;

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
  if (st.cur !== node) { st.cur = node; draw(box); fitScale(box); }  // the arrows meet the card being said at its new size; at rest the board fits whole
  // of the arrows named, the one into that card, else one out of it, else the last
  const named = said.filter((k) => k.startsWith("edge:")), id = node && node.slice(5);
  const edge = named.find((k) => node && k.endsWith("->" + id + k.slice(k.lastIndexOf("#"))))
    || named.find((k) => node && k.startsWith("edge:" + id + "->")) || named.pop() || null;
  const last = scene ? Math.min(n ?? 0, scene.frames.length - 1) : 0;
  const before = stepped && last > 0 ? new Set(scene.frames[last - 1].show) : null;
  const arrived = new Set(before ? scene.frames[last].show.filter((k) => k.startsWith("edge:") && !before.has(k)) : []);
  // once the answer is over the whole map shows from its start, not from wherever the last part left the view
  if (node === null && st.wasCur && box.closest(".pbody")) box.closest(".pbody").scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  st.wasCur = node !== null;
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
  // the card being said, and for an arrow the two parts it joins and its label: all of them stay in view together
  const ends = edge ? edge.slice(5).replace(/#\d+$/, "").split("->") : [];
  const keep = [box.querySelector(".m-node.m-cur"), ...ends.map((id) => box.querySelector(`.m-node[data-node="${CSS.escape(id)}"]`)),
    edge ? [...box.querySelectorAll(".m-edge")].find((g) => g.dataset.key === edge) : null].filter(Boolean);
  return keep.length ? keep : null;
}
