import { drawOn, flowchartKeys, isEdgePath, resetDraw } from "./svg_keys.js";

const GAP_MS = 50, LAST_MS = 550;
let seq = 0;

function linesKeys(box) {
  const found = new Map();
  for (const ln of box.querySelectorAll(".ln[data-line]")) {
    const key = "line:" + ln.dataset.line;
    if (!found.has(key)) found.set(key, []);
    found.get(key).push(ln);
  }
  return found;
}

function rowsKeys(box) {
  const found = new Map();
  [...box.querySelectorAll("tbody tr")].forEach((tr, i) => found.set("row#" + (i + 1), [tr]));
  return found;
}

const ADAPTERS = {
  lines: { ready: (box) => !!box.querySelector(".ln"), keys: linesKeys, holder: (box) => box },
  rows: { ready: (box) => !!box.querySelector("tbody tr"), keys: rowsKeys, holder: (box) => box.querySelector("table") || box },
  flowchart: {
    ready: (box) => !!box.querySelector("svg"),
    keys: (box) => flowchartKeys(box.querySelector("svg")),
    holder: (box) => box.querySelector("svg"),
    enter: (el, delay) => { if (isEdgePath(el)) drawOn(el, delay); },
    settle: (el) => { if (isEdgePath(el)) resetDraw(el); },
  },
};

const rank = (key) => (key.startsWith("group:") ? 0 : key.startsWith("edge:") ? 2 : 1);

function paintCard(scene, box, n) {
  let card = box.querySelector(":scope > .k-card");
  if (scene.kind !== "flowchart" || scene.start !== "empty" || n !== 0) { card?.remove(); return; }
  if (!card) { card = document.createElement("div"); card.className = "k-card"; box.append(card); }
  card.textContent = `${scene.title} · 0/${scene.steps}`;
}

export function stepLabel(scene, n) {
  return scene.steps ? `${Math.min(Math.max(n, 0), scene.steps)}/${scene.steps}` : "";
}

export function applyFrame(scene, box, n, from = null) {
  const adapter = ADAPTERS[scene.kind];
  if (!adapter || !box || !adapter.ready(box)) return null;
  const found = adapter.keys(box), last = scene.frames.length - 1;
  const at = (i) => scene.frames[Math.max(0, Math.min(i, last))];
  const show = new Set(at(n).show), focus = new Set(at(n).focus);
  const before = from === null ? null : new Set(at(from).show);
  const mine = String(++seq), entering = [];
  let focused = null;
  for (const key of scene.keys) {
    for (const el of found.get(key) || []) {
      el.classList.add("k-key");
      el.classList.toggle("k-focus", focus.has(key));
      if (focus.has(key) && !focused) focused = el;
      el.dataset.kSeq = mine;
      el.style.transitionDelay = "";
      if (adapter.settle) adapter.settle(el);
      if (show.has(key) && before && !before.has(key)) entering.push([key, el]);
      else el.classList.toggle("k-hidden", !show.has(key));
    }
  }
  adapter.holder(box)?.classList.toggle("k-dim", focus.size > 0);
  entering.sort((a, b) => rank(a[0]) - rank(b[0]));
  let i = -1, prev = null;
  for (const [key, el] of entering) {
    if (key !== prev) { i += 1; prev = key; }
    const delay = Math.min(i * GAP_MS, LAST_MS);
    el.classList.add("k-hidden");
    el.style.transitionDelay = delay + "ms";
    if (adapter.enter) adapter.enter(el, delay);
    requestAnimationFrame(() => { if (el.dataset.kSeq === mine) el.classList.remove("k-hidden"); });
  }
  paintCard(scene, box, n);
  return { missing: scene.keys.filter((k) => !found.has(k)), focused };
}
