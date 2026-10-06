import { drawOn, flowchartKeys, resetDraw } from "./svg_keys.js";

const GAP_MS = 50, LAST_MS = 550;
let seq = 0;

// Every board marks what the eye can land on with data-key, and the engine reads nothing else. The
// shared sequence and flowchart tools key their own drawing; code lines, table rows and a Mermaid
// drawing are keyed here, once they are painted.
function stampKeys(kind, box) {
  if (box.querySelector("[data-key]")) return true;
  if (kind === "lines") {
    const lines = box.querySelectorAll(".ln[data-line]");
    for (const ln of lines) ln.dataset.key = "line:" + ln.dataset.line;
    return lines.length > 0;
  }
  if (kind === "rows") {
    const rows = [...(box.querySelector("table")?.querySelectorAll("tbody tr") || [])];
    rows.forEach((tr, i) => { tr.dataset.key = "row#" + (i + 1); });
    return rows.length > 0;
  }
  const svg = box.querySelector("svg");
  if (!svg) return false;
  for (const [key, els] of flowchartKeys(svg)) for (const el of els) el.dataset.key = key;
  return true;
}

function keyedElements(box) {
  const found = new Map();
  for (const el of box.querySelectorAll("[data-key]")) {
    const key = el.dataset.key;
    if (!found.has(key)) found.set(key, []);
    found.get(key).push(el);
  }
  return found;
}

const isEdgePath = (key, el) => key.startsWith("edge:") && el.tagName.toLowerCase() === "path";
const rank = (key) => (key.startsWith("group:") || key.startsWith("actor:") ? 0 : key.startsWith("edge:") ? 2 : 1);
const DIAGRAMS = new Set(["flowchart", "sequence"]);

function paintCard(scene, box, n) {
  let card = box.querySelector(":scope > .k-card");
  if (!DIAGRAMS.has(scene.kind) || scene.start !== "empty" || n !== 0) { card?.remove(); return; }
  if (!card) { card = document.createElement("div"); card.className = "k-card"; box.append(card); }
  card.textContent = scene.title;
}

export function stepLabel(scene, n) {
  if (!scene.steps) return "";
  if (n >= scene.rest) return "All shown";
  const at = Math.min(Math.max(n, 0), scene.steps);
  return at === 0 ? `${scene.steps} ${scene.steps === 1 ? "step" : "steps"}` : `Step ${at} of ${scene.steps}`;
}

export function applyFrame(scene, box, n, from = null) {
  if (!box || !stampKeys(scene.kind, box)) return null;
  const found = keyedElements(box), last = scene.frames.length - 1;
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
      if (isEdgePath(key, el)) resetDraw(el);
      if (show.has(key) && before && !before.has(key)) entering.push([key, el]);
      else el.classList.toggle("k-hidden", !show.has(key));
    }
  }
  box.classList.toggle("k-dim", focus.size > 0);
  entering.sort((a, b) => rank(a[0]) - rank(b[0]));
  let i = -1, prev = null;
  for (const [key, el] of entering) {
    if (key !== prev) { i += 1; prev = key; }
    const delay = Math.min(i * GAP_MS, LAST_MS);
    el.classList.add("k-hidden");
    el.style.transitionDelay = delay + "ms";
    if (isEdgePath(key, el)) drawOn(el, delay);
    requestAnimationFrame(() => { if (el.dataset.kSeq === mine) el.classList.remove("k-hidden"); });
  }
  paintCard(scene, box, n);
  return { missing: scene.keys.filter((k) => !found.has(k)), focused };
}
