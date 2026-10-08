// The map: a flowchart drawn by the stage itself, for a talk call. The whole map is there from the
// start as faint dashed ghosts, so the reader sees the size of what is coming; the voice lights it
// part by part. The part being said is a large card with its detail; every arrow that arrives on a step
// forward draws in, and a dot travels along the one into that card.
//
// The scene engine (scene.js) shows and lights the keys (`node:<id>`, `edge:<a>-><b>#<n>`); on this
// board a key not shown yet is a ghost rather than hidden (stage.css), and after each frame
// layoutMap marks the part the frame names as being said, and the arrow into it.

import { beingSaid } from "./scene.js";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// a long name breaks between its words: before a capital that follows a small letter, after . _ / -
const breakable = (t) => esc(t).replace(/([a-z0-9])(?=[A-Z])|([._/-])(?=\w)/g, "$1$2<wbr>");
const TONE = { entry: "edge", code: "plain", call: "plain", decision: "internal", success: "good", error: "hot" };
const W = 180, H = 52;         // a part at rest; the one being said grows to a card over it
const GAP_X = 70, GAP_Y = 34;  // between columns, between parts in a column
const ROOM = 210;              // in a call, the map stays clear of the subtitles below it

export function renderMap(box, spec, embedded) {
  box.dataset.room = embedded ? ROOM : 16;
  box._map = { spec, embedded };
  const nodes = spec.nodes || [], edges = spec.edges || [];
  const seen = new Map();
  const ekeys = edges.map((e) => {
    const pair = e.from + "->" + e.to, n = seen.get(pair) || 0;
    seen.set(pair, n + 1);
    return `edge:${pair}#${n}`;
  });
  box._map.ekeys = ekeys;
  box.innerHTML = `<svg class="m-edges" aria-hidden="true"><defs></defs>${edges.map((e, i) => {
      const tone = TONE[(nodes.find((n) => n.id === e.from) || {}).role] || "plain";
      return `<g class="m-edge t-${tone}" data-key="${esc(ekeys[i])}"><path class="m-line"/><path class="m-tip"/>
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
  }
}

// Columns by depth: a part sits one column right of the deepest part that leads to it. A loop (a state
// machine going back to listening) is cut at the arrow that goes back, found walking forward from where
// the flow starts; that arrow is drawn as a curve under the others. In a column, parts are ordered by
// where the parts feeding them sit, so arrows cross as little as they can.
function layers(spec) {
  const nodes = spec.nodes || [], edges = spec.edges || [];
  const ids = new Set(nodes.map((n) => n.id));
  const out = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e, i) => { if (ids.has(e.from) && ids.has(e.to)) out.get(e.from).push(i); });
  const back = new Set(), state = new Map();  // 1: on the walk, 2: done
  const walk = (id) => {
    state.set(id, 1);
    for (const i of out.get(id)) {
      const to = edges[i].to;
      if (state.get(to) === 1 || to === id) back.add(i);
      else if (!state.has(to)) walk(to);
    }
    state.set(id, 2);
  };
  const hasIn = new Set(edges.map((e) => e.to));
  const starts = [...nodes.filter((n) => n.role === "entry"), ...nodes.filter((n) => !hasIn.has(n.id)), ...nodes];
  for (const n of starts) if (!state.has(n.id)) walk(n.id);
  const ins = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e, i) => { if (!back.has(i) && ids.has(e.from) && ids.has(e.to)) ins.get(e.to).push(e.from); });
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
  return { cols: cols.filter(Boolean), back };
}

function place(box) {
  const st = box._map;
  if (!st) return;
  const { cols, back } = layers(st.spec);
  const width = box.clientWidth || 900;
  const scroller = box.closest(".pbody");
  const height = Math.max(320, (scroller ? scroller.clientHeight - 32 : 480) - (+box.dataset.room || 16));
  if (back.size) { ring(box, st, cols.flat(), width, height); return; }  // a state machine: its loop is a ring
  // Left to right while the columns fit, narrowing the parts a little first; top to bottom when there are
  // still too many for the width.
  const fits = ([w, gap]) => cols.length * w + (cols.length - 1) * gap <= width - 40;
  const size = [[W, GAP_X], [150, 40], [130, 28]].find(fits);
  const across = !!size;
  const [w, gapX] = size || [W, GAP_X];
  box.style.setProperty("--mw", w + "px");
  const xy = new Map();
  if (across) {
    const step = cols.length > 1 ? Math.min(w + gapX * 2.2, (width - 40 - w) / (cols.length - 1)) : 0;
    const left = (width - (step * (cols.length - 1))) / 2;
    cols.forEach((c, i) => {
      const gap = Math.min(H + GAP_Y * 2, (height - 40) / Math.max(c.length, 1));
      const top = height / 2 - (gap * (c.length - 1)) / 2;
      c.forEach((id, j) => xy.set(id, [left + i * step, top + j * gap]));
    });
  } else {
    const gap = Math.min(H + GAP_Y * 1.6, (Math.max(height, cols.length * (H + GAP_Y)) - 40) / Math.max(cols.length - 1, 1));
    cols.forEach((c, i) => {
      const step = Math.min(W + GAP_X, (width - 40) / Math.max(c.length, 1));
      const left = width / 2 - (step * (c.length - 1)) / 2;
      c.forEach((id, j) => xy.set(id, [left + j * step, 40 + i * gap]));
    });
  }
  st.xy = xy; st.across = across;
  const lowest = Math.max(...[...xy.values()].map(([, y]) => y + H));
  const tall = Math.max(height, lowest + (back.size ? 40 + 26 * back.size : 0));
  box.style.height = tall + "px";
  for (const el of box.querySelectorAll(".m-node")) {
    const [x, y] = xy.get(el.dataset.node);
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  const svg = box.querySelector(".m-edges");
  svg.setAttribute("viewBox", `0 0 ${width} ${tall}`);
  svg.style.height = tall + "px";
  (st.spec.edges || []).forEach((e, i) => {
    const g = svg.querySelector(`[data-key="${st.ekeys[i]}"]`), a = xy.get(e.from), b = xy.get(e.to);
    if (!g || !a || !b) return;
    let d, mx, my;
    const k = [...back].indexOf(i);
    if (k >= 0) {
      // an arrow back: out of the bottom of one part, under the map, into the bottom of the other
      const below = lowest + 22 + 26 * k;
      if (across) {
        // arrows back into the same part land side by side, not on one point
        const o = (k - (back.size - 1) / 2) * 18, ax = a[0] + o, bx = b[0] + o;
        const y1 = a[1] + H / 2, y2 = b[1] + H / 2 + 4;
        d = `M ${ax} ${y1} C ${ax} ${below}, ${bx} ${below}, ${bx} ${y2}`;
        mx = (ax + bx) / 2; my = below - 6;
      } else {
        const x1 = a[0] + W / 2, x2 = b[0] + W / 2 + 4, side = Math.max(a[0], b[0]) + W / 2 + 40 + 26 * k;
        d = `M ${x1} ${a[1]} C ${side} ${a[1]}, ${side} ${b[1]}, ${x2} ${b[1]}`;
        mx = side - 10; my = (a[1] + b[1]) / 2;
      }
    } else if (across) {
      const x1 = a[0] + w / 2, x2 = b[0] - w / 2 - 4, c = (x2 - x1) / 2;
      d = `M ${x1} ${a[1]} C ${x1 + c} ${a[1]}, ${x2 - c} ${b[1]}, ${x2} ${b[1]}`;
      mx = (x1 + x2) / 2; my = (a[1] + b[1]) / 2;
    } else {
      const y1 = a[1] + H / 2, y2 = b[1] - H / 2 - 4, c = (y2 - y1) / 2;
      d = `M ${a[0]} ${y1} C ${a[0]} ${y1 + c}, ${b[0]} ${y2 - c}, ${b[0]} ${y2}`;
      mx = (a[0] + b[0]) / 2; my = (y1 + y2) / 2;
    }
    g.querySelector(".m-line").setAttribute("d", d);
    // the head: a small triangle at the receiving end, in the arrow's own colour
    const tip = g.querySelector(".m-tip");
    if (k >= 0 && across) {                                                                                // up into its bottom
      const bx = b[0] + (k - (back.size - 1) / 2) * 18;
      tip.setAttribute("d", `M ${bx} ${b[1] + H / 2 + 2} l -6 11 l 12 0 z`);
    }
    else if (k >= 0) tip.setAttribute("d", `M ${b[0] + W / 2 + 2} ${b[1]} l 11 -6 l 0 12 z`);            // left into its side
    else if (across) tip.setAttribute("d", `M ${b[0] - w / 2 - 2} ${b[1]} l -11 -6 l 0 12 z`);
    else tip.setAttribute("d", `M ${b[0]} ${b[1] - H / 2 - 2} l -6 -11 l 12 0 z`);
    g.classList.toggle("m-back", k >= 0);
    const label = g.querySelector(".m-elabel");
    if (label) {
      const t = label.querySelector("text"), r = label.querySelector("rect");
      t.setAttribute("x", mx); t.setAttribute("y", my + 4);
      const lw = (t.getComputedTextLength ? t.getComputedTextLength() : 60) + 14;
      // a label wider than the gap it names sits above that arrow, clear of the parts on either side
      if (k < 0 && across && Math.abs(b[0] - a[0]) - w < lw + 8 && Math.abs(b[1] - a[1]) < 4) {
        my = a[1] - H / 2 - 16;
        t.setAttribute("y", my + 4);
      }
      r.setAttribute("x", mx - lw / 2); r.setAttribute("y", my - 10); r.setAttribute("width", lw); r.setAttribute("height", 20);
    }
  });
}

// After a frame: the part being said and the arrow into it, as the frame names them (beingSaid). On a step
// forward (`stepped`: the frame before this one was the one on the board), every arrow that arrived with
// the frame draws in and the dot travels along the one being said; Back, a jump and a repaint draw the
// same picture still.
export function layoutMap(box, scene, n, stepped = false) {
  const st = box._map;
  if (!st) return;
  const said = scene && n != null ? beingSaid(scene, n) : [];
  const node = said.filter((k) => k.startsWith("node:")).pop() || null;
  if (box.classList.contains("m-ring") && st.cur !== node) { st.cur = node; place(box); }
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
}

// A map with loops (a state machine) is a ring: the states round an ellipse in the order the flow reaches
// them, clockwise from the top. An arrow to the next state round bows outward; any other (a way back, a
// skip) curves across the inside. Arrows stop at their state's card, the one being said being larger, and
// labels that would land on each other are pushed apart along their curves.
const RW = 170, RH = 52;
function ring(box, st, order, width, height) {
  box.classList.add("m-ring");
  box.style.setProperty("--mw", RW + "px");
  box.style.height = height + "px";
  const n = order.length, cx = width / 2, cy = height / 2;
  const rx = Math.max(160, Math.min(width / 2 - RW / 2 - 40, 420)), ry = Math.max(110, Math.min(height / 2 - RH / 2 - 30, 200));
  const xy = new Map(), at = new Map(order.map((id, i) => [id, i]));
  order.forEach((id, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    xy.set(id, [cx + rx * Math.cos(a), cy + ry * Math.sin(a)]);
  });
  st.xy = xy;
  for (const el of box.querySelectorAll(".m-node")) {
    const [x, y] = xy.get(el.dataset.node);
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  const svg = box.querySelector(".m-edges");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.height = height + "px";
  // the box round a card, with a little air; the card being said is wider and taller
  const half = (id) => (st.cur === "node:" + id ? [140, 48] : [RW / 2 + 8, RH / 2 + 8]);
  const edge = (x1, y1, x2, y2, id) => {
    const [hw, hh] = half(id), dx = x2 - x1, dy = y2 - y1;
    const t = Math.min(hw / Math.abs(dx || 1e-6), hh / Math.abs(dy || 1e-6), 1);
    return [x1 + dx * t, y1 + dy * t];
  };
  const labels = [];
  (st.spec.edges || []).forEach((e, i) => {
    const g = svg.querySelector(`[data-key="${st.ekeys[i]}"]`), a = xy.get(e.from), b = xy.get(e.to);
    if (!g || !a || !b) return;
    const next = (at.get(e.from) + 1) % n === at.get(e.to);
    // bend at right angles to the straight line between the two states: away from the middle for the next
    // state round, towards it for the rest; a line through the middle bends to its left
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    let px = -(b[1] - a[1]) / len, py = (b[0] - a[0]) / len;
    const toMiddle = (cx - mx) * px + (cy - my) * py;
    if (Math.abs(toMiddle) > 8 && (toMiddle > 0) === next) { px = -px; py = -py; }
    const bow = next ? 40 : Math.min(70, len * 0.18);
    const qx = mx + px * bow, qy = my + py * bow;
    const [sx, sy] = edge(a[0], a[1], qx, qy, e.from), [tx, ty] = edge(b[0], b[1], qx, qy, e.to);
    const d = `M ${sx} ${sy} Q ${qx} ${qy} ${tx} ${ty}`;
    const line = g.querySelector(".m-line");
    line.setAttribute("d", d);
    if (!g.classList.contains("m-cur")) line.classList.remove("m-draw");  // a stale dash would cut the new line short
    // the head points along the curve's last stretch, from its control point into the card
    const ang = Math.atan2(ty - qy, tx - qx), c = Math.cos(ang), s = Math.sin(ang);
    const pt = (u, v) => `${tx - c * u + s * v} ${ty - s * u - c * v}`;
    g.querySelector(".m-tip").setAttribute("d", `M ${tx} ${ty} L ${pt(12, 6)} L ${pt(12, -6)} Z`);
    g.classList.toggle("m-back", !next);
    const label = g.querySelector(".m-elabel");
    if (label) labels.push({ label, at: (t) => [(1 - t) ** 2 * sx + 2 * (1 - t) * t * qx + t ** 2 * tx, (1 - t) ** 2 * sy + 2 * (1 - t) * t * qy + t ** 2 * ty] });
  });
  // each label slides along its own curve to the first spot clear of the labels placed before it and of
  // the cards, so it always sits on the arrow it names
  const cards = [...xy.entries()].map(([id, [x, y]]) => { const [hw, hh] = half(id); return [x - hw + 4, y - hh + 4, x + hw - 4, y + hh - 4]; });
  const placed = [];
  const clear = (x, y, w) => ![...placed, ...cards].some(([l, t, r, b]) => x + w / 2 > l && x - w / 2 < r && y + 11 > t && y - 11 < b);
  for (const L of labels) {
    const t = L.label.querySelector("text");
    L.w = (() => { t.setAttribute("x", 0); return (t.getComputedTextLength ? t.getComputedTextLength() : 60) + 18; })();
    const spot = [0.5, 0.4, 0.6, 0.32, 0.68, 0.25, 0.75].map(L.at).find(([x, y]) => clear(x, y, L.w)) || L.at(0.5);
    [L.x, L.y] = spot;
    placed.push([L.x - L.w / 2 - 4, L.y - 13, L.x + L.w / 2 + 4, L.y + 13]);
  }
  for (const L of labels) {
    const t = L.label.querySelector("text"), r = L.label.querySelector("rect");
    t.setAttribute("x", L.x); t.setAttribute("y", L.y + 4);
    r.setAttribute("x", L.x - L.w / 2); r.setAttribute("y", L.y - 11); r.setAttribute("width", L.w); r.setAttribute("height", 22);
  }
}
