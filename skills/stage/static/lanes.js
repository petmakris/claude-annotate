// Lanes: a sequence diagram that unfolds with the voice. Each actor is a card in its own colour over its
// lifeline, every arrow carries its sentence above it and its call under it, and the step being said lies
// on an accent band: its arrow draws in, a dot travels from sender to receiver, and a bar marks the receiver.
//
// The scene engine (scene.js) shows and lights keys as frames go by; this file only draws the keys
// (`actor:<id>` on the chips, `step:<id>` on the rows) and, after each frame, lays the rows out
// around the step the frame names as being said. An actor pointed at lights its chip and its steps.

import { beingSaid } from "./scene.js";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const TONES = new Set(["plain", "edge", "internal", "service", "cheap", "hot", "good", "dropped"]);
const tone = (t) => "t-" + (TONES.has(t) ? t : "plain");
const MARGIN = 72;    // the columns' least inset from the board's edges, leaving the step numbers room
const NARROW = 52;    // that inset on a phone, where every pixel of the span goes to the chips
const EDGE = 4;       // nothing comes nearer the board's edge than this
const GAP = 10;       // between two chips on one line
const CHIP = 96;      // narrower than this, the chips take two lines, every other one on the lower
const NOTE_RIGHT = 16;  // a note's inset from the board's right edge
const BADGE = 38;       // the step numbers' column at the left: no words come nearer the edge than this
// An actor's colour: its tone's, or the next of six in turn, so neighbours never share one.
const actorColour = (a, i) => (a.tone && TONES.has(a.tone) && a.tone !== "plain" ? `var(--t-${a.tone})` : `var(--a${(i % 6) + 1})`);

export function renderLanes(box, spec, embedded) {
  const steps = spec.steps || [], actors = spec.actors || [];
  const phases = new Map((spec.phases || []).map((p) => [p.start_at, p.label]));
  box.dataset.room = 24;   // the current step stays this far above the bottom of the board
  const legend = (spec.legend || []).length
    ? `<div class="ln-legend">${spec.legend.map((l) => `<span class="${tone(l.tone)}"><i></i>${esc(l.label)}</span>`).join("")}</div>` : "";
  box.innerHTML = `<div class="ln-head"><div class="ln-actors">${actors.map((a, i) =>
      `<span class="ln-chip" style="--ac:${actorColour(a, i)}" data-key="actor:${esc(a.id)}" data-actor="${esc(a.id)}"><span>${esc(String(a.label || a.id).replace(/\n/g, " "))}</span>${a.sub ? `<small>${esc(a.sub)}</small>` : ""}</span>`).join("")}</div>${legend}</div>
    <div class="ln-body">${actors.map((a) => `<div class="ln-life" data-actor="${esc(a.id)}"></div>`).join("")}
    ${steps.map((s, i) => (phases.has(s.id) ? `<div class="ln-phase" data-at="${esc(s.id)}">${esc(phases.get(s.id))}</div>` : "") + row(s, i)).join("")}
    </div>`;
  box._lanes = { spec, cur: null };
  box.classList.toggle("ln-subs", steps.some((s) => s.sub));  // every row keeps room for a call under its arrow
  box.querySelector(".ln-body").style.paddingBottom = box.dataset.room + "px";
  place(box);
  if (!box._lanesObserved) {
    box._lanesObserved = true;
    new ResizeObserver(() => place(box)).observe(box);
    document.fonts?.ready.then(() => place(box));  // the chips are measured: again once the stage's fonts are in
  }
  layoutLanes(box, null);
}

function row(s, i) {
  const kind = ["request", "event", "self", "band"].includes(s.arrow) ? s.arrow : "request";
  const self = kind === "self" || (kind !== "band" && s.from === s.to);
  const shape = kind === "band" ? `<div class="ln-bar"></div>`
    : self ? `<div class="ln-loop"></div>`
    : `<div class="ln-arrow"><div class="ln-line"></div><div class="ln-head-tip"></div><div class="ln-dot"></div></div>`;
  return `<div class="ln-row ${tone(s.tone)} ln-${self ? "self" : kind}" data-key="step:${esc(s.id)}" data-step="${esc(s.id)}"
      data-from="${esc(s.from)}" data-to="${esc(s.to)}">${kind === "band" ? "" : `<span class="ln-act"></span>`}${shape}
    <div class="ln-lbl"><b>${esc(s.label)}</b>${s.sub ? `<code>${esc(s.sub)}</code>` : ""}</div>
    ${s.note ? `<span class="ln-note">${esc(s.note)}</span>` : ""}<span class="ln-num">${i + 1}</span></div>`;
}

// Columns spread evenly over the board's width; every row and chip is placed on them. The chips are measured
// first: the outer columns sit in far enough for the outer chips, and each chip is no wider than the space
// between two columns, wrapping its name inside it. When that leaves a chip too narrow to read, every
// other chip drops to a second line, so each has two columns' room. Labels are kept on the board.
function place(box) {
  const st = box._lanes;
  if (!st) return;
  const actors = st.spec.actors || [], w = st.w = box.clientWidth || 900, n = actors.length;
  const inset = w < 600 ? NARROW : MARGIN;
  box.classList.remove("ln-tight");
  const chips = actors.map((a) => box.querySelector(`.ln-chip[data-actor="${CSS.escape(String(a.id))}"]`));
  for (const c of chips) if (c) c.style.maxWidth = "none";
  const natural = chips.map((c) => (c ? c.offsetWidth : 0));
  const fit = (k) => {  // k: how many columns' room a chip has
    let cap = w - 2 * EDGE, lo = w / 2, d = 0;
    const end = (j) => Math.max(inset, Math.min(natural[j], cap) / 2 + EDGE);
    for (let i = 0; i < 12 && n > 1; i++) {
      lo = end(0); d = (w - lo - end(n - 1)) / (n - 1);
      cap = Math.min(i === 11 ? cap : Infinity, k * d - GAP);
    }
    return { cap: Math.max(cap, 0), lo, d };
  };
  let k = 1, at = fit(1);
  if (n > 2 && at.cap < CHIP) { k = 2; at = fit(2); }
  // a chip that has to wrap gives its name the dot's room: its border has the tone too
  box.classList.toggle("ln-tight", natural.some((nw) => nw > at.cap));
  const xs = new Map();
  actors.forEach((a, i) => xs.set(a.id, Math.round(n === 1 ? w / 2 : at.lo + at.d * i)));
  st.xs = xs;
  chips.forEach((c) => { if (c) c.style.maxWidth = Math.floor(at.cap) + "px"; });
  const tall = (odd) => Math.max(0, ...chips.filter((c, i) => c && i % 2 === odd).map((c) => c.offsetHeight));
  const second = k === 2 ? 2 + tall(0) + 6 : 2;
  chips.forEach((c, i) => { if (c) c.style.top = (i % 2 ? second : 2) + "px"; });
  const head = box.querySelector(".ln-actors");
  if (head) head.style.height = (k === 2 ? second + tall(1) : 2 + Math.max(tall(0), tall(1))) + 2 + "px";
  for (const el of box.querySelectorAll(".ln-chip, .ln-life")) el.style.left = xs.get(el.dataset.actor) + "px";
  for (const r of box.querySelectorAll(".ln-row")) {
    const a = xs.get(r.dataset.from) ?? inset, b = xs.get(r.dataset.to) ?? a;
    const lo = Math.min(a, b), hi = Math.max(a, b);
    r.style.setProperty("--lo", lo + "px");
    r.style.setProperty("--hi", hi + "px");
    r.style.setProperty("--mid", (lo + hi) / 2 + "px");
    // the receiver's bar, in the receiver's colour, while the step is being said
    const ri = actors.findIndex((x) => String(x.id) === r.dataset.to);
    r.style.setProperty("--rx", b + "px");
    if (ri >= 0) r.style.setProperty("--rc", actorColour(actors[ri], ri));
    r._span = [lo, hi];
    words(r, w);
    // a band reaches past its two columns, never past the board
    const bl = Math.max(EDGE, lo - 40);
    r.style.setProperty("--bl", bl + "px");
    r.style.setProperty("--bw", Math.min(w - EDGE, hi + 40) - bl + "px");
    r.classList.toggle("ln-back", b < a);
    // a step an actor makes to itself turns towards the side with room
    r.classList.toggle("ln-flip", r.classList.contains("ln-self") && a > w / 2);
  }
  notes(box);
  grow(box);
}

// The step being said is drawn large, its words wrapping onto as many lines as they need: its row is made tall
// enough for them, the arrow moved down for words above it and the foot for words below.
function grow(box) {
  for (const r of box.querySelectorAll(".ln-row")) {
    r.style.removeProperty("--y");
    r.style.removeProperty("height");
    r.querySelector(".ln-bar")?.removeAttribute("style");
    if (!r.classList.contains("ln-cur") || !r.hasAttribute("data-on")) continue;
    const css = getComputedStyle(r), y = parseFloat(css.getPropertyValue("--y")), h = parseFloat(css.getPropertyValue("--h"));
    const top = r.getBoundingClientRect().top, parts = [...r.querySelectorAll(".ln-lbl b, .ln-lbl code, .ln-note, .ln-bar")]
      .filter((e) => e.offsetParent).map((e) => e.getBoundingClientRect());
    if (!parts.length) continue;
    const down = Math.max(0, 8 - Math.min(...parts.map((b) => b.top - top)));
    const foot = Math.max(...parts.map((b) => b.bottom - top)) + down + 10;
    if (down) r.style.setProperty("--y", y + down + "px");
    // a band's sentence stays inside its band
    const bar = r.querySelector(".ln-bar"), said = r.querySelector(".ln-lbl");
    if (bar && said) {
      const b = bar.getBoundingClientRect(), t = said.getBoundingClientRect();
      if (t.height + 16 > b.height) bar.style.cssText = `top:${t.top - top - 8 + down}px;height:${t.height + 16}px`;
    }
    if (foot > h) r.style.height = Math.ceil(foot) + "px";
  }
}

// An arrow's words centre over it, as wide as it is and at least 220px, and stop short of the step numbers, of
// the board's edge and of the row's note: narrowed about the arrow's middle while that leaves them 160px, else slid aside.
function words(r, w) {
  const [lo, hi] = r._span, mid = (lo + hi) / 2, right = w - (r._nw ? NOTE_RIGHT + r._nw : EDGE);
  let lw = Math.min(Math.max(220, hi - lo + 40), w - BADGE - EDGE), lc = mid;
  const half = Math.min(lw / 2, mid - BADGE, right - mid);
  if (2 * half >= Math.min(lw, 160)) lw = 2 * half;
  else { lw = Math.min(lw, right - BADGE); lc = Math.min(Math.max(mid, lw / 2 + BADGE), right - lw / 2); }
  r.style.setProperty("--lw", lw + "px");
  r.style.setProperty("--lc", lc + "px");
}

// A note sits at the right of its row, and the step's words stop short of it; over an arrow that reaches under
// it, it rises above the line. Measured on the rows shown, as a hidden row has no width to measure.
function notes(box) {
  const st = box._lanes;
  for (const note of box.querySelectorAll(".ln-row[data-on] > .ln-note")) {
    const r = note.parentElement;
    if (!note.offsetWidth || !st.w) continue;
    r.classList.toggle("ln-up", !r.classList.contains("ln-self") && !r.classList.contains("ln-band")
      && r._span && r._span[1] + 6 > st.w - NOTE_RIGHT - note.offsetWidth);
    if (r._nw === note.offsetWidth + 10) continue;
    r._nw = note.offsetWidth + 10;
    r.style.setProperty("--nw", r._nw + "px");
    if (r._span) words(r, st.w);
  }
}

// After a frame: which rows are shown, which one is the current step, and where the board scrolls.
export function layoutLanes(box, scene, n = null) {
  const st = box._lanes;
  if (!st) return;
  const steps = st.spec.steps || [];
  const last = scene ? scene.frames.length - 1 : 0;
  const frame = scene ? scene.frames[Math.max(0, Math.min(n ?? last, last))] : null;
  const show = frame ? new Set(frame.show) : null;
  const shown = steps.filter((s) => !show || show.has("step:" + s.id));
  const said = scene && n != null ? beingSaid(scene, n) : [];
  const curKey = said.filter((k) => k.startsWith("step:")).pop();
  const cur = curKey ? steps.find((s) => "step:" + s.id === curKey) || null : null;
  const curId = cur ? cur.id : null;
  const lit = new Set(said.filter((k) => k.startsWith("actor:")).map((k) => k.slice(6)));
  const on = new Set(shown.map((s) => s.id));
  for (const r of box.querySelectorAll(".ln-row")) {
    r.toggleAttribute("data-on", on.has(r.dataset.step));
    r.classList.toggle("ln-cur", r.dataset.step === curId);
    r.classList.toggle("ln-mine", lit.has(r.dataset.from) || lit.has(r.dataset.to));
    // the arrow draws in and the dot travels only when a step becomes the current one
    if (r.dataset.step === curId && st.cur !== curId) { r.classList.remove("ln-enter"); void r.offsetWidth; r.classList.add("ln-enter"); }
    else if (r.dataset.step !== curId) r.classList.remove("ln-enter");
  }
  for (const p of box.querySelectorAll(".ln-phase")) p.toggleAttribute("data-on", on.has(p.dataset.at));
  notes(box);
  grow(box);
  const involved = lit.size ? lit : cur ? new Set([cur.from, cur.to]) : null;
  for (const c of box.querySelectorAll(".ln-chip")) {
    c.classList.toggle("ln-on", !!involved && involved.has(c.dataset.actor));
    c.classList.toggle("ln-off", !!involved && !involved.has(c.dataset.actor));
  }
  st.cur = curId;
  if (cur) requestAnimationFrame(() => follow(box));
}

// Keep the current step just above the bottom of the board, with
// the story so far stacked over it. Scrolls the pane's own scroller, never the page around it.
function follow(box) {
  const r = box.querySelector(".ln-row.ln-cur");
  const scroller = box.closest(".pbody");
  if (!r || !scroller || !r.isConnected) return;
  const room = +box.dataset.room || 24;
  const rb = r.getBoundingClientRect(), sb = scroller.getBoundingClientRect();
  const want = scroller.scrollTop + (rb.bottom - sb.bottom) + room;
  const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  scroller.scrollTo({ top: Math.max(0, want), behavior: smooth ? "smooth" : "auto" });
}
