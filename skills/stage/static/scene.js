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
    for (const ln of box.querySelectorAll(".ln[data-line], .ln[data-old]")) ln.dataset.key = ln.dataset.line ? "line:" + ln.dataset.line : "old:" + ln.dataset.old;
    return lines.length > 0;
  }
  if (kind === "rows") {
    const rows = [...(box.querySelector("table")?.querySelectorAll("tbody tr") || [])];
    rows.forEach((tr, i) => {
      tr.dataset.key = "row#" + (i + 1);
      [...tr.children].forEach((td, j) => { td.dataset.key = `cell#${i + 1}.${j + 1}`; });
    });
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

// The board's title, over a diagram that starts empty. Not on the map or the lanes, which are never empty:
// their ghosts already show what is coming, and a title in the middle of the board would sit on one of them.
function paintCard(scene, box, n) {
  let card = box.querySelector(":scope > .k-card");
  if (!DIAGRAMS.has(scene.kind) || scene.start !== "empty" || n !== 0 || box.classList.contains("map") || box.classList.contains("lanes")) { card?.remove(); return; }
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
  const focused = [];  // every element lit, kept in view together
  for (const key of scene.keys) {
    for (const el of found.get(key) || []) {
      el.classList.add("k-key");
      el.classList.toggle("k-focus", focus.has(key));
      if (focus.has(key)) focused.push(el);
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
  return { focused };  // a key with nothing drawn for it lights nothing: the keys come from the drawing's own spec
}

// What is being said in frame n: what the frame names (`cur`, written by the scene compiler), so the page
// draws that and guesses nothing. Nothing is being said in frame 0 or at rest. A scene saved before frames
// named it gets a guess: what is pointed at (a cell as its row), else the newest thing that arrived, with
// the arrow that arrived into it.
export function beingSaid(scene, n) {
  if (!scene || !(n > 0) || n >= scene.rest) return [];
  const last = scene.frames.length - 1, frame = scene.frames[Math.min(n, last)];
  if (Array.isArray(frame.cur)) return frame.cur;
  const before = new Set(scene.frames[Math.min(n, last) - 1].show);
  const part = (k) => (k.startsWith("cell#") ? "row#" + k.slice(5).split(".")[0] : k);
  const arrived = frame.show.filter((k) => !before.has(k));
  const pointed = [...new Set(frame.focus.map(part))];
  const cur = pointed.length ? pointed : arrived.filter((k) => !/^(edge:|actor:|cell#|group:)/.test(k)).slice(-1);
  const node = cur.filter((k) => k.startsWith("node:")).pop();
  if (node) {
    const ends = (e) => e.slice(5).replace(/#\d+$/, "").split("->");
    const edges = arrived.filter((k) => k.startsWith("edge:"));
    const edge = edges.find((e) => "node:" + ends(e)[1] === node) || edges.find((e) => "node:" + ends(e)[0] === node);
    if (edge) cur.push(edge);
  }
  return cur;
}

// A scene saved before its frames named what is being said (no `cur`) may come from before the compiler
// showed an arrow as soon as both its ends show (a saved call replayed from then lit its arrows a frame or
// more late). Such a scene gets that rule here, as the compiler now writes it; a scene with `cur` is drawn
// exactly as it is.
export function settled(scene) {
  if (!scene || !Array.isArray(scene.frames) || scene.frames.every((f) => Array.isArray(f.cur))) return scene;
  const keys = new Set(scene.keys || []), ends = new Map();
  const end = (id) => ["node:" + id, "group:" + id].find((k) => keys.has(k));
  for (const k of keys) {
    if (!k.startsWith("edge:")) continue;
    const pair = k.slice(5).replace(/#\d+$/, "");
    for (let i = pair.indexOf("->"); i > 0; i = pair.indexOf("->", i + 1)) {  // an id may hold "->" itself
      const a = end(pair.slice(0, i)), b = end(pair.slice(i + 2));
      if (a && b) { ends.set(k, [a, b]); break; }
    }
  }
  if (!ends.size) return scene;
  const frames = scene.frames.map((f) => {
    const show = new Set(f.show);
    for (const [k, [a, b]] of ends) if (show.has(a) && show.has(b)) show.add(k);
    return { ...f, show: scene.keys.filter((k) => show.has(k)) };
  });
  return { ...scene, frames };
}
