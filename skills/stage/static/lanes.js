// Lanes: a sequence diagram that unfolds with the voice, drawn whole from the start. Each actor is a card in
// its own colour, kept on top while the rows scroll, over its lifeline. A call opens a bar on its receiver's
// lifeline until its reply (`reply_to`); calls inside it nest their bars. Replies are dashed and lighter.
// `alt`, `par`, `loop` and `opt` boxes (`groups`) are filled cards with their condition in a header, and
// cover the lifelines of the actors they do not involve. Phases head their steps. The steps not said yet
// are faint, so the shape of the flow shows before the voice reaches it; the step being said lies on a
// see-through accent band, its arrow drawn in, a dot travelling it.
//
// A click on a step opens its popup: who calls whom, the call, the source lines round its `ref` (the
// source's `refs`, read from the code folder), the step it answers or is answered by, and Play from here.
// A click on an actor card follows that actor; a box's kind or a phase's header folds it.
//
// The scene engine (scene.js) shows and lights keys as frames go by: `actor:<id>` on the cards, `step:<id>`
// on the rows. After each frame, layoutLanes draws the board again round the step the frame names as being
// said, and gives the keyed elements back the classes the frame set on them.

import { beingSaid } from "./scene.js";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const TONES = new Set(["plain", "edge", "internal", "service", "cheap", "hot", "good", "dropped"]);
const tone = (t) => (TONES.has(t) ? t : "plain");
const KINDS = ["request", "event", "self", "band"];
const EDGE = 6;          // nothing comes nearer the board's edge than this
const GAP = 10;          // between two cards on one line
const CARD = 92;         // narrower than this, the cards take two lines, every other one on the lower
const BAR = 10;          // an activation bar's width; a nested one stands NEST to the right
const NEST = 6;
const PHASE_H = 34, HEAD_H = 30, BRANCH_H = 30, CLOSE_H = 18, SUMMARY_H = 46;
// An actor's colour: its tone's, or the next of six in turn, so neighbours never share one.
const actorColour = (a, i) => (a.tone && TONES.has(a.tone) && a.tone !== "plain" ? `var(--t-${a.tone})` : `var(--a${(i % 6) + 1})`);
const ARROW = (d) => `<svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true"><path d="M1 5h14m-4-4 4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6"${d ? ' stroke-dasharray="3 2"' : ""}/></svg>`;
const CLOSE = `<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const PLAY = `<svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5z" fill="currentColor"/></svg>`;
const CODE = `<svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 4 1.5 8 5 12M11 4l3.5 4-3.5 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const CHECK = `<svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true"><path d="m2.5 6.2 2.4 2.4 4.6-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// `more`: the source's `refs` (step id -> {path, start, at, lines}) and `play(stepId, dry)`, which starts the
// voice at the sentence that says a step (with `dry`, only asks whether one does) and returns false when none does.
export function renderLanes(box, spec, embedded, more = {}) {
  const actors = spec.actors || [];
  const legend = (spec.legend || []).length
    ? `<div class="ln-legend">${spec.legend.map((l) => `<span class="t-${tone(l.tone)}"><i></i>${esc(l.label)}</span>`).join("")}</div>` : "";
  box.innerHTML = `<div class="ln-head"><div class="ln-actors">${actors.map((a, i) =>
      `<button type="button" class="ln-chip" style="--ac:${actorColour(a, i)}" data-key="actor:${esc(a.id)}" data-actor="${esc(a.id)}"
        title="Follow ${esc(String(a.label || a.id).replace(/\n/g, " "))}"><span>${esc(String(a.label || a.id).replace(/\n/g, " "))}</span>${a.sub ? `<small>${esc(a.sub)}</small>` : ""}</button>`).join("")}</div>${legend}</div>
    <div class="ln-body"></div>`;
  box._lanes = { spec, refs: more.refs || {}, play: embedded ? more.play : null, scene: null, n: null, cur: null, drawn: undefined,
                 focus: null, folded: new Set(), pop: null, popNew: false, model: model(spec) };
  box.classList.toggle("ln-subs", (spec.steps || []).some((s) => s.sub));
  if (!box._lanesObserved) {
    box._lanesObserved = true;
    new ResizeObserver(() => paint(box)).observe(box);
    document.fonts?.ready.then(() => paint(box));  // the cards are measured: again once the stage's fonts are in
    box.addEventListener("click", (e) => onClick(box, e));
    box.addEventListener("keydown", (e) => {
      const st = box._lanes;
      if (!st) return;
      if (e.key === "Escape" && st.pop != null) { st.pop = null; paint(box); return; }
      const row = (e.key === "Enter" || e.key === " ") && e.target.closest?.(".ln-row");
      if (row) { e.preventDefault(); row.click(); }
    });
  }
  layoutLanes(box, null);
}

// What the spec holds, worked out once: its phases' ranges, its groups, and the calls and their replies.
function model(spec) {
  const steps = spec.steps || [], at = new Map(steps.map((s, i) => [s.id, i]));
  const starts = (spec.phases || []).map((p) => ({ ...p, a: at.get(p.start_at) })).filter((p) => p.a != null);
  if (!starts.length || starts[0].a > 0) starts.unshift({ id: null, label: null, a: 0 });
  const phases = starts.map((p, i) => ({ ...p, b: i + 1 < starts.length ? starts[i + 1].a - 1 : steps.length - 1 }));
  const groups = new Map((spec.groups || []).map((g) => [g.id, g]));
  const reply = new Map(steps.filter((s) => s.reply_to).map((s) => [s.reply_to, s.id]));
  return { steps, at, phases, groups, reply, actors: spec.actors || [] };
}

// After a frame: which steps are shown, which one is being said, which actors the voice points at.
export function layoutLanes(box, scene, n = null) {
  const st = box._lanes;
  if (!st) return;
  st.scene = scene; st.n = n;
  paint(box);
}

function frameOf(st) {
  const { scene, n } = st;
  if (!scene) return { show: null, focus: new Set(), said: [] };
  const last = scene.frames.length - 1, f = scene.frames[Math.max(0, Math.min(n ?? last, last))];
  return { show: new Set(f.show), focus: new Set(f.focus || []), said: n != null ? beingSaid(scene, n) : [] };
}

function paint(box) {
  const st = box._lanes;
  if (!st) return;
  const { steps, actors, phases, groups } = st.model;
  const fr = frameOf(st);
  const curKey = fr.said.filter((k) => k.startsWith("step:")).pop();
  const cur = curKey ? st.model.at.get(curKey.slice(5)) ?? null : null;
  const lit = new Set(fr.said.filter((k) => k.startsWith("actor:")).map((k) => k.slice(6)));
  const shown = (i) => !fr.show || fr.show.has("step:" + steps[i].id);
  const w = st.w = box.clientWidth || 900, narrow = w < 600;
  const cols = columns(box, st, w, narrow);
  const { xs } = cols;

  // -- rows, top to bottom ------------------------------------------------------------------------------
  const rows = [];
  let y = 8;
  const phaseOn = (p) => shown(p.a);
  for (const p of phases) {
    const foldable = p.id != null, holdsCur = cur != null && cur >= p.a && cur <= p.b;
    if (foldable && st.folded.has("p:" + p.id) && !holdsCur) {
      rows.push({ type: "summary", p, y, h: SUMMARY_H }); y += SUMMARY_H + 10;
      continue;
    }
    if (p.label != null) { rows.push({ type: "phase", p, y, h: PHASE_H }); y += PHASE_H; }
    let box_ = null;
    for (let i = p.a; i <= p.b; i++) {
      const s = steps[i], g = s.group != null ? groups.get(s.group) : null;
      if (box_ && (!g || box_.g.id !== g.id)) { y = closeBox(box_, y); box_ = null; }
      if (g && !box_) {
        const holds = cur != null && steps[cur].group === g.id;
        box_ = { type: "box", g, y, first: i, last: i, branches: [], branch: Number(s.branch ?? 0),
                 folded: st.folded.has("g:" + g.id) && !holds };
        rows.push(box_); y += HEAD_H;
      } else if (g && Number(s.branch ?? 0) !== box_.branch) {
        box_.branch = Number(s.branch ?? 0);
        if (!box_.folded) { box_.branches.push({ y, guard: (g.branches || [])[box_.branch] || "" }); y += BRANCH_H; }
      }
      if (box_) box_.last = i;
      if (box_ && box_.folded) continue;
      const { h, ay } = rowSize(st, s, i === cur, narrow);
      rows.push({ type: "step", i, s, y, h, ay, extra: rowSize(st, s, i === cur, narrow).extra });
      y += h;
    }
    if (box_) y = closeBox(box_, y);
    y += 6;
  }
  const H = y + 24;

  // -- activation bars: a call's on its receiver until its reply; a call to itself a short one ------------
  const rowOf = new Map(rows.filter((r) => r.type === "step").map((r) => [r.i, r]));
  const bars = [];
  steps.forEach((s, i) => {
    const r = rowOf.get(i);
    if (!r) return;
    if (s.arrow === "request" && st.model.reply.has(s.id)) {
      const ri = st.model.at.get(st.model.reply.get(s.id)), rr = rowOf.get(ri);
      bars.push({ actor: s.to, y1: r.y + r.ay, y2: rr ? rr.y + rr.ay : r.y + r.ay + 26, i1: i, i2: ri });
    } else if (s.arrow === "self") bars.push({ actor: s.to, y1: r.y + r.ay - 4, y2: r.y + r.ay + 20, i1: i, i2: i, self: true });
  });
  for (const b of bars) b.depth = bars.filter((o) => o !== b && o.actor === b.actor && o.y1 <= b.y1 && o.y2 >= b.y2
    && !(o.y1 === b.y1 && o.y2 === b.y2)).length;
  const edge = (actor, at, dir) => {
    const open = bars.filter((b) => b.actor === actor && b.y1 <= at + 0.5 && b.y2 >= at - 0.5);
    if (!open.length) return xs.get(actor);
    const d = Math.max(...open.map((b) => b.depth));
    return xs.get(actor) + d * NEST + (dir > 0 ? BAR / 2 : -BAR / 2);
  };

  // -- who is in view: the voice's actors, or the one followed, or the step being said's two -----------------
  const involved = st.focus ? new Set([st.focus]) : lit.size ? lit : cur != null ? new Set([steps[cur].from, steps[cur].to]) : null;
  const touches = (s, set) => set.has(s.from) || set.has(s.to);

  // -- the drawing --------------------------------------------------------------------------------------
  const bg = [], top = [], html = [];
  const life = (a, y1, y2) => `<line class="ln-life${st.focus && st.focus !== a.id ? " ln-dim" : ""}" data-actor="${esc(a.id)}" x1="${xs.get(a.id)}" x2="${xs.get(a.id)}" y1="${y1}" y2="${y2}"/>`;
  for (const a of actors) bg.push(life(a, 0, H));
  const fills = [], frames = [], spans = [];
  for (const r of rows.filter((r) => r.type === "box")) boxDrawing(r, st, cols, w, narrow, shown, fills, frames, spans, html);
  bg.push(...fills);
  for (const f of spans) for (const a of actors) if (f.inv.has(a.id)) bg.push(life(a, f.y1, f.y2));
  bg.push(...frames);
  for (const b of bars) {
    const i = actors.findIndex((a) => a.id === b.actor), x = xs.get(b.actor) + b.depth * NEST - BAR / 2;
    const live = cur != null && b.i1 <= cur && b.i2 >= cur && !b.self;
    const cls = ["ln-actbar", shown(b.i1) ? "" : "ln-ghost", st.focus && st.focus !== b.actor ? "ln-dim" : "", live ? "ln-live" : ""].filter(Boolean).join(" ");
    top.push(`<rect class="${cls}" data-actor="${esc(b.actor)}" data-from="${steps[b.i1].id}" data-depth="${b.depth}" x="${x}" y="${b.y1 - 3}" width="${BAR}" height="${Math.max(BAR, b.y2 - b.y1 + 6)}" rx="2" style="--bc:${actorColour(actors[i], i)}"/>`);
  }
  for (const r of rows) {
    if (r.type === "phase") {
      const pos = cur == null ? "" : cur > r.p.b ? " ln-past" : cur >= r.p.a ? " ln-here" : "";
      html.push(`<button type="button" class="ln-phase${pos}${phaseOn(r.p) ? "" : " ln-ghost"}" data-at="${esc(r.p.start_at)}"${phaseOn(r.p) ? " data-on" : ""}
        data-fold="p:${esc(r.p.id)}" title="Fold this phase" style="top:${r.y}px;height:${r.h}px">${esc(r.p.label)}<em>steps ${r.p.a + 1}–${r.p.b + 1}</em></button>`);
    } else if (r.type === "summary") {
      const p = r.p, k = p.b - p.a + 1, done = cur != null ? cur > p.b : shown(p.b);
      const said = steps.slice(p.a, p.b + 1).map((s) => s.label);
      const gist = done && said.length > 1 ? `<b>${esc(said[0])}</b> → … → <b>${esc(said[said.length - 1])}</b>` : esc(said.join(" · "));
      html.push(`<button type="button" class="ln-summary${done ? "" : " ln-later"}" data-fold="p:${esc(p.id)}" title="Open this phase" style="top:${r.y}px;height:${r.h}px">
        <span class="ln-chk">${done ? CHECK : ""}</span><span class="ln-sph">${esc(p.label)}</span><span class="ln-gist">${gist}</span><span class="ln-n">${k} ${k === 1 ? "step" : "steps"}</span></button>`);
    } else if (r.type === "step") {
      html.push(stepRow(r, st, cols, w, narrow, edge, cur, lit, touches, shown));
    }
  }
  const body = box.querySelector(".ln-body");
  body.style.height = H + "px";
  body.innerHTML = `<svg class="ln-bg" width="${w}" height="${H}" viewBox="0 0 ${w} ${H}" aria-hidden="true">${bg.join("")}${top.join("")}</svg>${html.join("")}`;
  paintCards(box, st, cols, involved);
  // the keyed elements are new: they take back the classes the frame gave the old ones
  if (st.scene) {
    for (const el of box.querySelectorAll("[data-key]")) {
      el.classList.add("k-key");
      el.classList.toggle("k-focus", fr.focus.has(el.dataset.key));
      el.classList.toggle("k-hidden", !!fr.show && !fr.show.has(el.dataset.key));
    }
  }
  if (measure(box, st, rows)) return;  // drawn again, taller where words wrap
  if (st.pop != null) popup(box, st, rows, cols, w);
  const moved = cur != null && st.drawn !== cur;
  st.cur = cur != null ? steps[cur].id : null;
  st.drawn = cur;
  if (moved) requestAnimationFrame(() => follow(box));
}

// Columns spread over the board's width; the outer ones sit in far enough for the outer cards. A card is
// no wider than the room between two columns, wrapping its name inside it; when that leaves a card too
// narrow to read, every other card drops to a second line, so each has two columns' room.
function columns(box, st, w, narrow) {
  const actors = st.model.actors, n = actors.length;
  const notes = !narrow && st.model.steps.some((s) => s.note);
  const left = narrow ? 34 : 58, right = notes ? 112 : narrow ? 10 : 24;
  box.classList.remove("ln-tight");
  const chips = actors.map((a) => box.querySelector(`.ln-chip[data-actor="${CSS.escape(String(a.id))}"]`));
  for (const c of chips) if (c) c.style.maxWidth = "none";
  const natural = chips.map((c) => (c ? c.offsetWidth : 0));
  const fit = (k) => {
    let lo = left + 30, hi = w - right - 30;
    lo = Math.max(lo, Math.min(natural[0] || 0, w / 2) / 2 + EDGE);
    hi = Math.min(hi, w - Math.min(natural[n - 1] || 0, w / 2) / 2 - EDGE);
    const d = n > 1 ? (hi - lo) / (n - 1) : 0;
    return { lo, d, cap: Math.max(0, n > 1 ? k * d - GAP : w - 2 * EDGE) };
  };
  let k = 1, at = fit(1);
  if (n > 2 && at.cap < CARD) { k = 2; at = fit(2); }
  box.classList.toggle("ln-tight", natural.some((nw) => nw > at.cap));
  const xs = new Map(actors.map((a, i) => [a.id, Math.round(n === 1 ? w / 2 : at.lo + at.d * i)]));
  return { xs, pitch: at.d, k, cap: at.cap, chips, left, right, notes };
}

function paintCards(box, st, cols, involved) {
  const { chips, xs, k, cap } = cols;
  chips.forEach((c, i) => {
    if (!c) return;
    const id = c.dataset.actor;
    c.style.maxWidth = Math.floor(cap) + "px";
    c.style.left = xs.get(id) + "px";
    c.classList.toggle("ln-on", !!involved && involved.has(id));
    c.classList.toggle("ln-off", !!involved && !involved.has(id));
    c.classList.toggle("ln-followed", st.focus === id);
    c.setAttribute("aria-pressed", String(st.focus === id));
  });
  const tall = (odd) => Math.max(0, ...chips.filter((c, i) => c && i % 2 === odd).map((c) => c.offsetHeight));
  const second = k === 2 ? 2 + tall(0) + 6 : 2;
  chips.forEach((c, i) => { if (c) c.style.top = (i % 2 && k === 2 ? second : 2) + "px"; });
  const head = box.querySelector(".ln-actors");
  if (head) head.style.height = (k === 2 ? second + tall(1) : 2 + Math.max(tall(0), tall(1))) + 4 + "px";
}

// A row's height and where its arrow lies in it: room above the arrow for its sentence, under it for its
// call. The step being said is larger; once drawn, words that wrap make their row taller (measure).
function baseSize(s, isCur, narrow) {
  if (s.arrow === "band") return { h: isCur ? 70 : 54, ay: isCur ? 35 : 27 };
  if (s.arrow === "self" || s.from === s.to) return { h: isCur ? 76 : 56, ay: isCur ? 38 : 28 };
  const sub = s.sub ? 16 : 0;
  return { h: (isCur ? (narrow ? 76 : 72) : (narrow ? 54 : 48)) + sub, ay: isCur ? (narrow ? 48 : 44) : 32 };
}
const tallKey = (s, isCur) => s.id + (isCur ? ":cur" : "");
function rowSize(st, s, isCur, narrow) {
  const b = baseSize(s, isCur, narrow), x = st.tall?.get(tallKey(s, isCur)) || { a: 0, b: 0 };
  return { h: b.h + x.a + x.b, ay: b.ay + x.a, extra: x };
}

function closeBox(b, y) {
  if (b.folded) { b.foldY = y; y += 34; }
  b.y2 = y + 6;
  return y + CLOSE_H;
}

// A box's card: a fill under the lifelines of the actors it does not involve, and over it the lifelines of
// those it does, its frame, and its header with its kind and its whole condition.
function boxDrawing(r, st, cols, w, narrow, shown, fills, frames, spans, html) {
  const { steps } = st.model, { xs } = cols, g = r.g;
  const inv = new Set();
  for (let i = r.first; i <= r.last; i++) { inv.add(steps[i].from); inv.add(steps[i].to); }
  const xx = [...inv].map((a) => xs.get(a));
  const ghost = shown(r.first) ? "" : " ln-ghost";
  const label = g.kind === "alt" || g.kind === "par" ? (g.branches || [])[0] || "" : g.label || "";
  const tag = g.kind.length * 7.6 + 46;   // the kind's button, "▾ alt", and a gap
  const need = tag + label.length * 7.2 + 30;
  const x1 = Math.max(cols.left - 6, Math.min(...xx) - (narrow ? 26 : 46));
  let x2 = narrow ? w - EDGE : Math.max(...xx) + (inv.size === 1 ? 240 : 46);
  for (let i = r.first; i <= r.last; i++) {   // a call to itself keeps its words beside it, inside the box
    const s = steps[i];
    if (s.arrow === "self" && !r.folded) x2 = Math.max(x2, xs.get(s.from) + 60 + Math.max(s.label.length * 8.2, (s.sub || "").length * 7.2) + 16);
  }
  x2 = Math.min(w - EDGE, Math.max(x2, x1 + need));
  for (const lx of xs.values()) if (Math.abs(x2 - lx) < 18) x2 = lx > x2 && lx - 18 - x1 >= need ? lx - 18 : Math.min(w - EDGE, lx + 18);
  const y1 = r.y + 4, h = r.y2 - r.y - 4;
  spans.push({ inv, y1, y2: y1 + h });
  fills.push(`<rect class="ln-boxbg${ghost}" x="${x1}" y="${y1}" width="${x2 - x1}" height="${h}" rx="8"/>`);
  frames.push(`<path class="ln-boxhead${ghost}" d="M${x1} ${y1 + 26}V${y1 + 8}a8 8 0 0 1 8-8H${x2 - 8}a8 8 0 0 1 8 8V${y1 + 26}Z"/>`,
    `<line class="ln-boxline${ghost}" x1="${x1}" x2="${x2}" y1="${y1 + 26}" y2="${y1 + 26}"/>`,
    `<rect class="ln-boxframe${ghost}" x="${x1}" y="${y1}" width="${x2 - x1}" height="${h}" rx="8"/>`);
  for (const b of r.branches) frames.push(`<line class="ln-boxdiv${ghost}" x1="${x1}" x2="${x2}" y1="${b.y + 6}" y2="${b.y + 6}"/>`);
  html.push(`<button type="button" class="ln-kind ln-k-${esc(g.kind)}${ghost}" data-fold="g:${esc(g.id)}" data-group="${esc(g.id)}"
      title="${r.folded ? "Open" : "Fold"} this ${esc(g.kind)}" aria-expanded="${!r.folded}" style="left:${x1 + 7}px;top:${y1 + 5}px">${r.folded ? "▸" : "▾"} ${esc(g.kind)}</button>`,
    `<span class="ln-guard${ghost}" style="left:${x1 + tag}px;top:${y1 + 6}px;max-width:${x2 - x1 - tag - 10}px">${esc(label)}</span>`);
  for (const b of r.branches) {
    const plain = /^(else|otherwise)$/i.test(b.guard.trim());
    const word = g.kind === "par" ? "and" : plain ? "else" : "else if";
    html.push(`<span class="ln-guard ln-branch${ghost}" style="left:${x1 + 10}px;top:${b.y - 5}px;max-width:${x2 - x1 - 20}px"><em>${word}</em>${plain && g.kind !== "par" ? "" : " " + esc(b.guard)}</span>`);
  }
  if (r.folded) {
    const k = r.last - r.first + 1;
    html.push(`<button type="button" class="ln-guard ln-branch ln-folded" data-fold="g:${esc(g.id)}" style="left:${x1 + 12}px;top:${r.foldY + 2}px">${k} ${k === 1 ? "step" : "steps"} folded · open</button>`);
  }
}

// One step: a row the width of the board, keyed, with its arrow, its number, its sentence, its call and its note.
function stepRow(r, st, cols, w, narrow, edge, cur, lit, touches, shown) {
  const { s, i, y, h, ay } = r, { xs } = cols;
  const kind = KINDS.includes(s.arrow) ? s.arrow : "request";
  const isCur = i === cur, t = tone(s.tone);
  const cls = ["ln-row", "t-" + t, "ln-" + kind, isCur ? "ln-cur" : "", isCur && st.drawn !== cur ? "ln-enter" : "",
    lit.size && touches(s, lit) ? "ln-mine" : "", st.focus && !touches(s, new Set([st.focus])) && !isCur ? "ln-dim" : "",
    st.pop === i ? "ln-open" : ""].filter(Boolean);
  const fx = xs.get(s.from), tx = xs.get(s.to);
  const abs = y + ay;
  let svg = "", words = "";
  const note = s.note && !narrow ? `<span class="ln-note" style="top:${ay}px">${esc(s.note)}</span>` : "";
  if (kind === "band") {
    const lo = Math.max(EDGE, Math.min(fx, tx) - 44), hi = Math.min(w - EDGE, Math.max(fx, tx) + 44);
    const bh = (isCur ? 46 : 32) + r.extra.a + r.extra.b;
    svg = `<rect class="ln-bandbar" x="${lo}" y="${ay - bh / 2}" width="${hi - lo}" height="${bh}" rx="9"/>`;
    words = `<div class="ln-lbl ln-inband" style="left:${lo + 12}px;width:${hi - lo - 24}px;top:${ay}px"><b>${esc(s.label)}</b>${s.sub && isCur ? `<code>${esc(s.sub)}</code>` : ""}</div>`;
  } else if (kind === "self" || s.from === s.to) {
    const x0 = edge(s.from, abs + 6, 1);
    const flip = fx > w * 0.62 && fx - 300 > cols.left;
    const xr = flip ? xs.get(s.from) - 40 : xs.get(s.from) + 40;
    const sx = flip ? edge(s.from, abs - 10, -1) : edge(s.from, abs - 10, 1);
    const ex = flip ? edge(s.from, abs + 10, -1) : x0;
    svg = `<path class="ln-path" pathLength="1" d="M${sx} ${ay - 10}H${xr}V${ay + 10}H${ex + (flip ? -9 : 9)}"/>${head(ex, ay + 10, flip ? 1 : -1, false)}`;
    const room = flip ? xr - 12 - cols.left : w - (xr + 12) - (s.note && !narrow ? 120 : EDGE);
    words = `<div class="ln-lbl ln-beside${flip ? " ln-flip" : ""}" style="${flip ? `right:${w - xr + 12}px` : `left:${xr + 12}px`};top:${ay}px;width:${Math.max(140, room)}px">
      <b>${esc(s.label)}</b>${s.sub ? `<code>${esc(s.sub)}</code>` : ""}</div>`;
  } else {
    const dir = Math.sign(tx - fx), x1 = edge(s.from, abs, dir), x2 = edge(s.to, abs, -dir), ret = kind === "event";
    svg = `<line class="ln-path" pathLength="1" x1="${x1}" x2="${x2 - dir * 2}" y1="${ay}" y2="${ay}"/>${head(x2, ay, dir, ret)}`;
    if (isCur && st.drawn !== cur) svg += `<circle class="ln-dot" r="4.5" cx="${x1}" cy="${ay}"><animate attributeName="cx" from="${x1}" to="${x2}" dur=".6s" fill="freeze"/><animate attributeName="opacity" values="1;1;0" dur="1s" fill="freeze"/></circle>`;
    const mid = (x1 + x2) / 2, span = Math.abs(x2 - x1);
    // as wide as its words on one line (Inter's and JetBrains Mono's average widths), else as the board allows
    const need = Math.max(s.label.length * (isCur ? 8.9 : 7.5), (s.sub || "").length * (isCur ? 7.6 : 7)) + 12;
    let lw = Math.min(Math.max(span + 30, need, narrow ? 180 : 230), w - cols.left - EDGE);
    const right = w - (s.note && !narrow ? 120 : EDGE);
    const lc = Math.min(Math.max(mid, lw / 2 + cols.left - 6), right - lw / 2);
    words = `<div class="ln-lbl ln-over" style="left:${lc}px;width:${lw}px;top:${ay}px"><b>${esc(s.label)}</b></div>`
      + (s.sub ? `<div class="ln-call" style="left:${lc}px;width:${lw}px;top:${ay}px"><code>${esc(s.sub)}</code></div>` : "");
    if (dir < 0) cls.push("ln-back");
  }
  return `<div class="${cls.join(" ")}" role="button" tabindex="0" aria-label="Step ${i + 1}: ${esc(s.label)}" data-key="step:${esc(s.id)}"
      data-step="${esc(s.id)}" data-from="${esc(s.from)}" data-to="${esc(s.to)}"${shown(i) ? " data-on" : ""}
      style="top:${y}px;height:${h}px"><svg class="ln-svg" width="${w}" height="${h}" aria-hidden="true">${svg}</svg>
    <span class="ln-num" style="top:${ay}px">${i + 1}</span>${words}${note}</div>`;
}

function head(x, y, dir, open) {
  const d = `M${x - dir * 9} ${y - 5}L${x} ${y}L${x - dir * 9} ${y + 5}`;
  return open ? `<path class="ln-tip ln-open-tip" d="${d}"/>` : `<path class="ln-tip" d="${d}Z"/>`;
}

// A sentence that wraps, or a call that does, needs more room than its row gave it: the board is drawn
// again, each row as tall as its words. Returns whether it was. Unmeasured (no layout), nothing changes.
function measure(box, st, rows) {
  if (st.measuring) return false;
  const tall = new Map();
  for (const r of rows) {
    if (r.type !== "step") continue;
    const el = box.querySelector(`.ln-row[data-step="${CSS.escape(String(r.s.id))}"]`);
    const said = el?.querySelector(".ln-lbl"), call = el?.querySelector(".ln-call");
    const sh = said ? said.offsetHeight : 0, ch = call ? call.offsetHeight : 0;
    if (!sh) continue;
    const isCur = el.classList.contains("ln-cur"), b = baseSize(r.s, isCur, st.w < 600);
    const centred = r.s.arrow === "self" || r.s.arrow === "band" || r.s.from === r.s.to;
    const above = centred ? sh / 2 + 10 - b.ay : sh + 12 - b.ay;
    const below = centred ? sh / 2 + 10 - (b.h - b.ay) : (ch ? ch + 8 : 0) + 10 - (b.h - b.ay);
    if (above > 1 || below > 1) tall.set(tallKey(r.s, isCur), { a: Math.ceil(Math.max(0, above)), b: Math.ceil(Math.max(0, below)) });
  }
  const old = st.tall || new Map();
  const near = (x, y) => x && y && Math.abs(x.a - y.a) < 2 && Math.abs(x.b - y.b) < 2;
  if ([...tall].every(([k, v]) => near(old.get(k), v))) return false;
  st.tall = new Map([...old, ...tall]);
  st.measuring = true;
  try { paint(box); } finally { st.measuring = false; }
  return true;
}

// The popup of one step, under its row, or over it near the board's end.
function popup(box, st, rows, cols, w) {
  const r = rows.find((x) => x.type === "step" && x.i === st.pop);
  if (!r) { st.pop = null; return; }
  const { steps, actors, phases, groups, reply, at } = st.model;
  const s = r.s, p = phases.find((q) => r.i >= q.a && r.i <= q.b), src = st.refs[s.id];
  const ai = (id) => actors.findIndex((a) => a.id === id);
  const who = (id) => { const k = ai(id); return `<span class="ln-who" style="--c:${actorColour(actors[k], k)}"><i></i>${esc(String(actors[k].label).replace(/\n/g, " "))}</span>`; };
  const g = s.group != null ? groups.get(s.group) : null;
  const cond = g ? (g.kind === "alt" || g.kind === "par" ? (g.branches || [])[Number(s.branch ?? 0)] : g.label) : null;
  const answers = s.reply_to ? at.get(s.reply_to) : null, answered = reply.has(s.id) ? at.get(reply.get(s.id)) : null;
  const link = (k) => `<button type="button" class="ln-link" data-popgo="${k}">step ${k + 1}: ${esc(steps[k].label)}</button>`;
  const code = src ? src.lines.map((t, k) => `<div class="ln-cl${src.start + k === src.at ? " ln-at" : ""}"><i>${src.start + k}</i><span>${esc(t) || " "}</span></div>`).join("") : "";
  const kind = s.arrow === "event" ? "reply" : s.arrow === "self" ? "own call" : s.arrow === "band" ? "stretch" : "call";
  const pw = Math.min(580, w - 24);
  const mid = (cols.xs.get(s.from) + cols.xs.get(s.to)) / 2 + (s.from === s.to ? 60 : 0);
  const left = Math.max(12, Math.min(mid - pw / 2, w - pw - 12));
  const body = box.querySelector(".ln-body"), H = parseFloat(body.style.height) || 0;
  const below = r.y + r.h + 360 < H || r.y < 380;
  const el = document.createElement("div");
  el.className = "ln-pop" + (below ? "" : " ln-above");
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", `Step ${r.i + 1}: ${s.label}`);
  el.style.cssText = `left:${left}px;top:${below ? r.y + r.h - 2 : r.y + 6}px;width:${pw}px;--caret:${Math.max(18, Math.min(pw - 18, mid - left))}px`;
  el.innerHTML = `<div class="ln-pophead"><span class="ln-badge${r.i === (st.drawn ?? -1) ? " ln-said" : ""}">${r.i + 1}</span><span class="ln-popph">${esc(p?.label || "")}</span>
      <button type="button" class="ln-x" data-close title="Close" aria-label="Close">${CLOSE}</button></div>
    <h3>${esc(s.label.charAt(0).toUpperCase() + s.label.slice(1))}</h3>
    <div class="ln-whos">${who(s.from)}${s.from === s.to ? "<em>to itself</em>" : ARROW(s.arrow === "event") + who(s.to)}<span class="ln-kindtag">${kind}</span></div>
    ${s.sub ? `<div class="ln-popcall">${esc(s.sub)}</div>` : ""}
    ${src ? `<div class="ln-src"><div class="ln-srchead">${CODE}${esc(src.path)}:${src.at}</div><div class="ln-lines">${code}</div></div>` : s.ref ? `<div class="ln-srchead ln-nosrc">${CODE}${esc(s.ref)}</div>` : ""}
    ${cond || answers != null || answered != null || s.note ? `<div class="ln-meta">
      ${cond ? `<div><b>${esc(g.kind)}</b> · only when ${esc(cond)}</div>` : ""}
      ${answers != null ? `<div><b>Answers</b> ${link(answers)}</div>` : ""}
      ${answered != null ? `<div><b>Answered by</b> ${link(answered)}</div>` : ""}
      ${s.note ? `<div><b>Note</b> ${esc(s.note)}</div>` : ""}</div>` : ""}
    ${st.play && st.play(s.id, true) ? `<div class="ln-popact"><button type="button" class="ln-btn ln-pri" data-playfrom="${esc(s.id)}">${PLAY}Play from here</button></div>` : ""}`;
  body.appendChild(el);
  if (st.popNew) { st.popNew = false; requestAnimationFrame(() => el.scrollIntoView({ block: "nearest", behavior: "smooth" })); }
}

function onClick(box, e) {
  const st = box._lanes;
  if (!st) return;
  const t = e.target, at = (sel) => t.closest(sel);
  if (at("[data-close]")) { st.pop = null; paint(box); return; }
  const pf = at("[data-playfrom]");
  if (pf) {
    const ok = st.play && st.play(pf.dataset.playfrom);
    if (ok) { st.pop = null; paint(box); } else pf.textContent = "No answer says this step";
    return;
  }
  const pg = at("[data-popgo]");
  if (pg) { st.pop = +pg.dataset.popgo; st.popNew = true; paint(box); return; }
  if (at(".ln-pop")) return;
  const f = at("[data-fold]");
  if (f) { const k = f.dataset.fold; st.folded.has(k) ? st.folded.delete(k) : st.folded.add(k); st.pop = null; paint(box); return; }
  const c = at(".ln-chip");
  if (c) { st.focus = st.focus === c.dataset.actor ? null : c.dataset.actor; paint(box); return; }
  const row = at(".ln-row");
  if (row) { const i = st.model.at.get(row.dataset.step); st.pop = st.pop === i ? null : i; st.popNew = st.pop != null; paint(box); return; }
  if (st.pop != null) { st.pop = null; paint(box); }
}

// Keep the step being said a little above the middle of the rows in view, under the cards that stay on top.
// Scrolls the pane's own scroller, never the page around it.
function follow(box) {
  const r = box.querySelector(".ln-row.ln-cur");
  const scroller = box.closest(".pbody");
  if (!r || !scroller || !r.isConnected) return;
  const head = box.querySelector(".ln-head")?.offsetHeight || 0;
  const rb = r.getBoundingClientRect(), sb = scroller.getBoundingClientRect();
  const view = sb.height - head;
  const want = scroller.scrollTop + (rb.top - sb.top) - head - view * 0.4 + rb.height / 2;
  const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  scroller.scrollTo({ top: Math.max(0, want), behavior: smooth ? "smooth" : "auto" });
}
