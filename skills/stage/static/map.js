// The map: a flowchart drawn by the stage itself, for a talk call. The whole map is there from the
// start as faint dashed ghosts, so the reader sees the size of what is coming; the voice lights it
// part by part. The part being said is a large card with its detail, and the arrow that just
// arrived draws in with a dot travelling along it.
//
// The scene engine (scene.js) shows and lights the keys (`node:<id>`, `edge:<a>-><b>#<n>`); on this
// board a key not shown yet is a ghost rather than hidden (stage.css), and after each frame
// layoutMap marks the current part: the one that just arrived, else the one pointed at.

import { currentKey } from "./scene.js";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
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
        <b>${esc(n.label || n.id)}</b>${detail ? `<code>${esc(detail)}</code>` : ""}${n.sub ? `<span class="m-sub">${esc(n.sub)}</span>` : ""}</div>`;
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

// After a frame: the part being said, and the arrow that just arrived.
export function layoutMap(box, scene, n) {
  const st = box._map;
  if (!st) return;
  const node = scene && n != null ? currentKey(scene, n, "node:") : null;
  const edge = scene && n != null ? currentKey(scene, n, "edge:") : null;
  const arrived = scene && n != null && n > 0 && !new Set(scene.frames[n - 1].show).has(edge);
  for (const el of box.querySelectorAll(".m-node")) el.classList.toggle("m-cur", el.dataset.key === node);
  for (const g of box.querySelectorAll(".m-edge")) {
    const on = g.dataset.key === edge && arrived;
    g.classList.toggle("m-cur", on);
    g.querySelector(".m-dot")?.remove();
    if (on && st.lastEdge !== edge) {
      const line = g.querySelector(".m-line");
      line.classList.remove("m-draw"); void line.getBBox(); line.classList.add("m-draw");
      line.style.setProperty("--len", Math.ceil(line.getTotalLength ? line.getTotalLength() : 600));
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("r", "6"); dot.setAttribute("class", "m-dot");
        dot.innerHTML = `<animateMotion dur="1.1s" begin="indefinite" fill="freeze" path="${line.getAttribute("d")}"/>`;
        g.append(dot);
        dot.firstElementChild.beginElement();
      }
    }
  }
  st.lastEdge = arrived ? edge : null;
}
