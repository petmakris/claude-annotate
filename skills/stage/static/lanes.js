// Lanes: a sequence diagram that unfolds with the voice, drawn whole from the start, in the look of the lane
// sequence (sequence_svg, docs/vz.md): each actor is a box in its tone (blue the AI path, red the central
// mechanism, green a rule that holds, amber a cost; no tone is plain), with its role and file under its name,
// kept on top while the rows scroll, over its lifeline. A call carries what it sends in a chip on its arrow,
// a step's `checks` are ✓ / ✗ badges where the rule is applied, phases are bands behind their steps, and an
// `outcome` box closes the diagram. A call opens a bar on its receiver's
// lifeline until its reply (`reply_to`); calls inside it nest their bars. Replies are dashed and lighter.
// `alt`, `par`, `loop` and `opt` boxes (`groups`) are filled cards with their condition in a header, and
// cover the lifelines of the actors they do not involve. Phases head their steps. The steps not said yet
// are faint, so the shape of the flow shows before the voice reaches it; the step being said lies on a
// see-through accent band, its arrow drawn in, a dot travelling it.
//
// A compare spec (compare.py: its `steps` are rows, each holding the `before` and the `after` step) is two lane
// boards side by side, the before flow on the left and the after one on the right, each a whole flow with its
// own actors and numbers. A row has the same height on both sides, so a step in both flows sits level with
// itself, and a side with no step in a row shows a plain box that says "No step here" there. A gutter between them marks each row
// (= same, ~ changed, + new, − removed, ↕ moved), the words a changed step changed are bold in its colour, and
// an actor on one side only is red and "removed" or green and "new". The voice points at a side with
// `mode:before` or `mode:after` in a frame's focus, which dims the other (`mode:both` lifts it); on a board too
// narrow for two, one side shows at a time, with a Before / After toggle.
// A step that moved is two rows (its old place, its new one): a point on it lights both with a connector in the
// gutter, never an empty gap. At rest both sides are whole and undimmed. On a board narrow enough for one side
// the gap boxes are left out and the side on show is the one that has the step being said.
// A step's `note` stands in a margin right of the last lane, as wide as the longest note needs; on a phone it is
// a line under the arrow of the step being said. A spec the board cannot draw is a message on the stage, not a blank.
//
// A click on a step opens its popup: who calls whom, the call, the source lines round its `ref` (the
// source's `refs`, read from the code folder), the step it answers or is answered by, and Play from here.
// A click on an actor card follows that actor; a box's kind or a phase's header folds it.
//
// The scene engine (scene.js) shows and lights keys as frames go by: `actor:<id>` on the cards, `step:<id>`
// on the rows. After each frame, layoutLanes draws the board again round the step the frame names as being
// said, and gives the keyed elements back the classes the frame set on them.

import { beingSaid } from "./scene.js";
import { w as wd, wn as wdn } from "./words.js";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// the four tones of the lane sequence; the older tones map onto them as sequence_svg maps them
const TONE = { plain: "plain", blue: "blue", red: "red", green: "green", amber: "amber", edge: "blue", service: "blue",
               internal: "amber", hot: "red", good: "green", cheap: "plain", dropped: "dropped" };
const tone = (t) => TONE[t] || "plain";
const OUTCOME = "outcome:end";   // the scene key of the closing box (scene.py OUTCOME), plain and compared
const KINDS = ["request", "event", "self", "band"];
const EDGE = 6;          // nothing comes nearer the board's edge than this
const GAP = 10;          // between two cards on one line
const CARD = 92;         // narrower than this, the cards take two lines, every other one on the lower
const BAR = 10;          // an activation bar's width; a nested one stands NEST to the right
const NEST = 6;
const DENSE = 28;       // a numbered card on a phone with many actors
const SELF_LIFT = 8;     // a call to itself on a narrow board: its chip stands this much higher over the loop
const NUM_AT = (narrow) => (narrow ? 4 : 20);   // the step number's own gutter, the board's width deciding (not the window's)
const PHASE_H = 34, HEAD_H = 30, BRANCH_H = 30, CLOSE_H = 18, SUMMARY_H = 46;
// An actor's colour is its tone's: a colour carries a meaning, so an actor with none is plain.
const actorColour = (a) => `var(--t-${tone(a.tone) === "dropped" ? "plain" : tone(a.tone)})`;
const ARROW = (d) => `<svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true"><path d="M1 5h14m-4-4 4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6"${d ? ' stroke-dasharray="3 2"' : ""}/></svg>`;
const CLOSE = `<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const PLAY = `<svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5z" fill="currentColor"/></svg>`;
const CODE = `<svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 4 1.5 8 5 12M11 4l3.5 4-3.5 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const CHECK = `<svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true"><path d="m2.5 6.2 2.4 2.4 4.6-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// Short marks for the actors, so no actor is a digit (the rows' own numbers are the only numbers on a board): its first
// letter when no other actor has it, else its words' initials, else its first two or three letters, else a digit.
export function actorMarks(actors) {
  const used = new Set();
  return actors.map((a, i) => {
    const text = String(a.label || a.id).replace(/\n/g, " ").trim();
    const words = text.split(/[^\p{L}\p{N}]+/u).filter(Boolean), letters = words.join("");
    const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
    const tries = [cap(letters.slice(0, 1)), words.slice(0, 3).map((w) => w.charAt(0).toUpperCase()).join(""),
                   cap(letters.slice(0, 2)), cap(letters.slice(0, 3))];
    const m = tries.find((t) => t && !used.has(t)) ?? String(i + 1);
    used.add(m);
    return m;
  });
}

// The marks' look and the compact key of a phone board, put in once (the stage's own sheet keeps the rest).
const LANES_CSS = `.ln-kitem i,.ln-now i{width:auto;min-width:19px;padding:0 4px;border-radius:999px;box-sizing:border-box}
.ln-dense .ln-key{gap:2px 4px;padding:8px 10px 2px}
.ln-dense .ln-chip .ln-no{font-size:11px;letter-spacing:-.2px}
.ln-dense .ln-now{height:18px;padding-top:4px}
.ln-dense .ln-now:empty{display:none}`;
function styled() {
  try {
    if (document.getElementById("lanes-extra-css")) return;
    const el = document.createElement("style");
    el.id = "lanes-extra-css"; el.textContent = LANES_CSS;
    document.head.appendChild(el);
  } catch { /* a page with no head keeps the stage's own look */ }
}

// `more`: the source's `refs` (step id -> {path, start, at, lines}) and `play(stepId, dry)`, which starts the
// voice at the sentence that says a step (with `dry`, only asks whether one does) and returns false when none does.
export function renderLanes(box, spec, embedded, more = {}) {
  try { drawLanes(box, spec, embedded, more); } catch (e) { failed(box, e); }
}

// A spec the board cannot draw says so on the stage, where the reader looks, never a blank board.
function failed(box, e) {
  console.error("lanes:", e);
  box._lanes = null; box._cmp = null;
  box.innerHTML = `<div class="ln-fail" role="alert"><b>${esc(wd("lanes.fail"))}</b><span>${esc(e?.message || e)}</span></div>`;
}

function drawLanes(box, spec, embedded, more) {
  styled();
  if (spec.compare && typeof spec.compare.before === "object") return renderCompare(box, spec, embedded, more);
  if (spec.compare) spec = { ...spec, compare: undefined };  // a board saved as one merged diagram: drawn as its rows
  box._cmp = null;
  const actors = spec.actors || [];
  const legend = (spec.legend || []).length
    ? `<div class="ln-legend">${spec.legend.map((l) => `<span class="t-${tone(l.tone)}"><i></i>${esc(l.label)}</span>`).join("")}</div>` : "";
  const name = (a) => String(a.label || a.id).replace(/\n/g, " ");
  // on a phone with many actors the cards are numbers (`ln-dense`), named once in a key above the lifelines
  const marks = actorMarks(actors);
  const key = `<div class="ln-key" aria-label="${esc(wd("who.key"))}">${actors.map((a, i) =>
    `<button type="button" class="ln-kitem t-${tone(a.tone)}" style="--ac:${actorColour(a, i)}" data-actor="${esc(a.id)}"><i>${esc(marks[i])}</i>${esc(name(a))}</button>`).join("")}</div>`;
  box.innerHTML = `${key}<div class="ln-head"><div class="ln-actors">${actors.map((a, i) =>
      `<button type="button" class="ln-chip t-${tone(a.tone)}${a.mono ? " ln-mono" : ""}" style="--ac:${actorColour(a, i)}" data-key="actor:${esc(a.id)}" data-actor="${esc(a.id)}"
        title="${esc(wd("follow.actor", { name: name(a) }))}"><b class="ln-no">${esc(marks[i])}</b><span>${esc(name(a))}</span>${a.role ? `<em>${esc(a.role)}</em>` : ""}${a.sub ? `<small>${esc(a.sub)}</small>` : ""}${a.tag ? `<i class="ln-tag">${esc(a.tag)}</i>` : ""}</button>`).join("")}</div>
      <div class="ln-now" aria-live="off"></div>${legend}</div>
    <div class="ln-body"></div>`;
  box._lanes = { spec, refs: more.refs || {}, play: embedded ? more.play : null, scene: null, n: null, cur: null, drawn: undefined,
                 focus: null, folded: new Set(), pop: null, popNew: false, model: model(spec), onPaint: more.onPaint || null, managed: !!more.managed, aim: null, outSaid: false };
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
  // each step's number: its own `n` when the spec numbers its walkthrough (several arrows share one), else 1, 2, 3
  let last = null;
  let k = 0;
  const nums = steps.some((s) => s.n != null) ? steps.map((s) => (s.gap ? null : (last = s.n ?? last))) : steps.map((s) => (s.gap ? null : ++k));
  return { steps, at, phases, groups, reply, nums, marks: actorMarks(spec.actors || []), actors: spec.actors || [], outcome: spec.outcome || null };
}

// After a frame: which steps are shown, which one is being said, which actors the voice points at.
export function layoutLanes(box, scene, n = null) {
  try { layoutOf(box, scene, n); } catch (e) { failed(box, e); }
}
// The step popups of a board are taken down: on a board change, a new answer, and (layoutOf) a frame for another step.
export function closeLanesPop(box) {
  for (const b of box._cmp ? Object.values(box._cmp.panes) : [box]) {
    const st = b._lanes;
    if (st && st.pop != null) { st.pop = null; paint(b); }
  }
}
function layoutOf(box, scene, n) {
  if (box._cmp) return layoutCompare(box, scene, n);
  const st = box._lanes;
  if (!st) return;
  if (st.n !== n) st.pop = null;   // the voice moved to another frame: the popup of the step before goes
  st.scene = scene; st.n = n;
  paint(box);
}

// The outcome closes a diagram, plain or compared (one renderer, both boards): ghosted until the last step is
// shown, lit while the voice points at it (`[[point: outcome]]`), says the last step, or at rest.
const linesOf = (o) => (Array.isArray(o.lines) ? o.lines : o.lines ? [o.lines] : []);   // a saved board's one text is one line
const outcomeHeight = (o) => 30 + 22 * linesOf(o).length + 18;
function outcomeLit(st, fr, cur, last) {
  const atRest = !st.scene || st.n == null || st.n >= st.scene.rest;
  const shown = !fr.show || fr.show.has(OUTCOME) || (last >= 0 && fr.show.has("step:" + st.model.steps[last]?.id));
  const said = fr.said.includes(OUTCOME) || fr.focus.has(OUTCOME) || (cur != null && cur === last);
  return { ghost: !shown, lit: shown && (said || (atRest && cur == null)), said };
}
function outcomeHtml(o, { ghost, lit, said }, style) {
  return `<div class="ln-outcome t-${tone(o.tone)}${ghost ? " ln-ghost" : ""}${lit ? " ln-lit" : ""}${said ? " ln-said" : ""}" data-key="${OUTCOME}"${style ? ` style="${style}"` : ""}>
    <b>${esc(o.title)}</b>${linesOf(o).map((l) => `<span>${esc(l)}</span>`).join("")}</div>`;
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
  const fr = frameOf(st);
  const curKey = fr.said.filter((k) => k.startsWith("step:")).pop();
  if ([...fr.focus].length && [...fr.focus].every((k) => k.startsWith("mode:"))) box.closest(".k-dim")?.classList.remove("k-dim");  // a side lights no part
  const { steps, actors, phases, groups } = st.model;
  let cur = curKey ? st.model.at.get(curKey.slice(5)) ?? null : null;
  // a compare side with no step in the row said (a moved step's old place is the other row): the row holding its mate is the one said
  const mateOf = new Map(steps.filter((s) => s.mate).map((s) => ["step:" + s.mate, "step:" + s.id]));   // the row said -> the step here
  if (cur != null && steps[cur].gap && mateOf.has(curKey)) cur = st.model.at.get(mateOf.get(curKey).slice(5));
  const lit = new Set(fr.said.filter((k) => k.startsWith("actor:")).map((k) => k.slice(6)));
  const shown = (i) => !fr.show || fr.show.has("step:" + steps[i].id);
  const w = st.w = box.clientWidth || 900, narrow = w < 600;
  const cols = columns(box, st, w, narrow);
  const { xs } = cols;

  // -- rows, top to bottom ------------------------------------------------------------------------------
  const rows = [], natural = new Map();
  let y = 8;
  const phaseOn = (p) => shown(p.a);
  for (const p of phases) {
    const foldable = p.id != null, holdsCur = cur != null && cur >= p.a && cur <= p.b;
    if (foldable && st.folded.has("p:" + p.id) && !holdsCur) {
      rows.push({ type: "summary", p, y, h: SUMMARY_H }); y += SUMMARY_H + 10;
      continue;
    }
    const top = y;
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
      if (s.gap && st.dropGaps) continue;   // one side at a time (a phone): no empty filler to scroll past
      let { h, ay, extra } = rowSize(st, s, i === cur, narrow);
      natural.set(s.id, { h, ay });
      const pad = st.pad?.get(s.id);   // on a compare board, the row as tall as on the other side
      if (pad) { h = pad.h; ay = pad.ay; }
      rows.push({ type: "step", i, s, y, h, ay, extra });
      y += h;
    }
    if (box_) y = closeBox(box_, y);
    if (p.label != null) rows.push({ type: "band", p, y: top, h: y + 2 - top });
    y += 6;
  }
  // the outcome closes the diagram: its title and its lines, in its tone
  const out = st.model.outcome;
  if (out) { const h = outcomeHeight(out); rows.push({ type: "outcome", out, y: y + 8, h }); y += 8 + h + 10; }
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
  const involved = st.focus ? new Set([st.focus]) : lit.size ? lit : cur != null && !steps[cur].gap ? new Set([steps[cur].from, steps[cur].to]) : null;
  const touches = (s, set) => set.has(s.from) || set.has(s.to);

  // -- the drawing --------------------------------------------------------------------------------------
  const bg = [], top = [], html = [];
  const life = (a, y1, y2) => `<line class="ln-life${st.focus && st.focus !== a.id ? " ln-dim" : ""}" data-actor="${esc(a.id)}" x1="${xs.get(a.id)}" x2="${xs.get(a.id)}" y1="${y1}" y2="${y2}"/>`;
  for (const r of rows.filter((r) => r.type === "band")) {  // a phase is a band behind its steps
    const pos = cur == null ? "" : cur > r.p.b ? " ln-past" : cur >= r.p.a ? " ln-here" : "";
    bg.push(`<rect class="ln-band${phaseOn(r.p) ? "" : " ln-ghost"}${pos}" x="${EDGE}" y="${r.y}" width="${Math.max(0, w - 2 * EDGE)}" height="${r.h}" rx="10"/>`);
  }
  // a compare board's gap, a side with no step in this row: a plain box with its words, behind the lifelines so a bar that
  // runs through it stays whole (its words are drawn over them, with a halo, so no lifeline strikes them)
  const gaps = rows.filter((r) => r.type === "step" && r.s.gap);
  for (const r of gaps) {
    const gx = cols.left - 14, gw = Math.max(0, w - cols.left + 6);
    bg.push(`<rect class="ln-gapband" x="${gx}" y="${r.y + 5}" width="${gw}" height="${Math.max(0, r.h - 10)}" rx="8"/>`);
    top.push(`<text class="ln-gaptext" x="${gx + gw / 2}" y="${r.y + r.h / 2 + 5}" text-anchor="middle">${esc(wd("gap.none"))}</text>`);
  }
  const outRow = rows.find((r) => r.type === "outcome");
  for (const a of actors) bg.push(life(a, 0, outRow ? outRow.y - 6 : H));  // the lifelines end where the outcome closes the diagram
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
        data-fold="p:${esc(r.p.id)}" title="${esc(wd("phase.fold"))}" style="top:${r.y}px;height:${r.h}px"><span class="ln-pl">${esc(r.p.label)}</span><em>${esc(wd("phase.steps", { a: r.p.a + 1, b: r.p.b + 1 }))}</em></button>`);
    } else if (r.type === "summary") {
      const p = r.p, k = p.b - p.a + 1, done = cur != null ? cur > p.b : shown(p.b);
      const said = steps.slice(p.a, p.b + 1).map((s) => s.label);
      const gist = done && said.length > 1 ? `<b>${esc(said[0])}</b> → … → <b>${esc(said[said.length - 1])}</b>` : esc(said.join(" · "));
      html.push(`<button type="button" class="ln-summary${done ? "" : " ln-later"}" data-fold="p:${esc(p.id)}" title="${esc(wd("phase.open"))}" style="top:${r.y}px;height:${r.h}px">
        <span class="ln-chk">${done ? CHECK : ""}</span><span class="ln-sph">${esc(p.label)}</span><span class="ln-gist">${gist}</span><span class="ln-n">${esc(wdn("steps", k))}</span></button>`);
    } else if (r.type === "step") {
      html.push(stepRow(r, st, cols, w, narrow, edge, cur, lit, touches, shown));
    } else if (r.type === "outcome") {
      html.push(outcomeHtml(r.out, outcomeLit(st, fr, cur, steps.length - 1), `top:${r.y}px;height:${r.h}px`));
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
      const pointed = fr.focus.has(el.dataset.key) && !el.classList.contains("ln-gap")   // a gap is never lit
        || [...mateOf].some(([said, mine]) => mine === el.dataset.key && fr.focus.has(said));   // the old place of a moved step lights with the new one
      el.classList.toggle("k-focus", pointed);
      el.classList.toggle("k-hidden", !!fr.show && !fr.show.has(el.dataset.key));
    }
    const oel = box.querySelector(".ln-outcome");   // ghosted until said (k-hidden's .35), whole once the last step is shown
    if (oel && !outcomeLit(st, fr, cur, steps.length - 1).ghost) oel.classList.remove("k-hidden");
  }
  if (measure(box, st, rows)) return;  // drawn again, taller where words wrap
  if (st.pop != null) popup(box, st, rows, cols, w);
  // Where the view goes after this frame: to the step now said, to the outcome when it is said (a point at the outcome
  // leaves no step said, so it is tested before the rest), else to the top once the answer is over (a rest view left at
  // the last rows shows the end of a flow and none of its start).
  const moved = cur != null && st.drawn !== cur;
  const atRest = !!st.scene && st.n != null && st.n >= st.scene.rest;   // after a point at the outcome no step is said, so the rest is told by the frame
  const rested = cur == null && (st.drawn != null || (atRest && !st.wasRest));
  const outSaid = !!out && outcomeLit(st, fr, cur, steps.length - 1).said;
  const aim = moved ? "row" : outSaid && !st.outSaid ? "outcome" : rested ? "top" : null;
  st.cur = cur != null ? steps[cur].id : null;
  st.drawn = cur;
  st.outSaid = outSaid;
  st.wasRest = atRest;
  st.rowTops = rows.filter((r) => r.type === "step" || r.type === "phase" || r.type === "summary" || r.type === "box").map((r) => r.y).sort((a, b) => a - b);
  if (aim) { st.aim = aim; if (!st.managed) requestAnimationFrame(() => land(box)); }
  st.natural = natural;
  st.rowAt = new Map(rows.filter((r) => r.type === "step").map((r) => [r.s.id, r.y + r.ay]));
  st.onPaint?.();
}

// Columns spread over the board's width; the outer ones sit in far enough for the outer cards. A card is
// no wider than the room between two columns, wrapping its name inside it; when that leaves a card too
// narrow to read, every other card drops to a second line, so each has two columns' room.
function columns(box, st, w, narrow) {
  const actors = st.model.actors, n = actors.length;
  const notes = !narrow && st.model.steps.some((s) => s.note);
  // a step's note stands in the margin right of the last lane: as wide as the longest (13.5 px sans, 7.4 px a
  // character), up to a third of the board, the rest of a long one wrapping inside it; never over a lane or a bar
  const longest = notes ? Math.max(...st.model.steps.map((s) => String(s.note || "").length)) : 0;
  const noteW = notes ? Math.round(Math.min(Math.max(112, longest * 7.4 + 28), Math.max(112, w * 0.34))) : 0;
  const left = narrow ? 34 : 58, right = notes ? noteW : narrow ? 10 : 24;
  box.classList.remove("ln-tight", "ln-dense");
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
  // Five actors or more on a phone: names would pile up whatever their size, so each card is its number, one
  // small row, and the names stand once in the key above (ln-key); the actors of the step said are named under it.
  // on a compare board both sides are dense when either is (st.peers: the most actors of the two), so the two stand level
  const dense = narrow && Math.max(n, st.peers || 0) >= 5;
  if (dense) {
    const lo = left + 6, hi = w - right - 8, d = (hi - lo) / Math.max(1, n - 1);
    box.classList.add("ln-dense");
    const xs = new Map(actors.map((a, i) => [a.id, Math.round(lo + d * i)]));
    return { xs, pitch: d, k: 1, cap: DENSE, chips, left, right, notes, noteW, dense };
  }
  box.classList.toggle("ln-tight", natural.some((nw) => nw > at.cap));
  const xs = new Map(actors.map((a, i) => [a.id, Math.round(n === 1 ? w / 2 : at.lo + at.d * i)]));
  return { xs, pitch: at.d, k, cap: at.cap, chips, left, right, notes, noteW };
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
  for (const it of box.querySelectorAll(".ln-kitem")) {
    it.classList.toggle("ln-on", !!involved && involved.has(it.dataset.actor));
    it.classList.toggle("ln-followed", st.focus === it.dataset.actor);
  }
  // numbered cards: the actors of the step said are named under them, where the key has scrolled away
  const now = box.querySelector(".ln-now");
  if (now) {
    const named = involved ? st.model.actors.map((a, i) => [a, i]).filter(([a]) => involved.has(a.id)) : [];
    now.innerHTML = named.map(([a, i]) => `<span class="t-${tone(a.tone)}" style="--ac:${actorColour(a, i)}"><i>${esc(st.model.marks[i])}</i>${esc(String(a.label || a.id).replace(/\n/g, " "))}</span>`).join("");
  }
}

// A row's height and where its arrow lies in it: room above the arrow for its sentence, under it for its
// call. The step being said is larger; once drawn, words that wrap make their row taller (measure).
function baseSize(s, isCur, narrow) {
  if (s.gap) return { h: isCur ? 64 : 46, ay: isCur ? 32 : 23 };
  const checks = (s.checks || []).length ? 32 : 0;
  if (s.arrow === "band") return { h: isCur ? 70 : 54, ay: isCur ? 35 : 27 };
  if (centred(s, narrow)) return { h: (isCur ? 76 : 56) + checks, ay: isCur ? 38 : 28 };
  // a call's chip sits over its arrow, its label and then its sub; a reply's words over it, with no chip
  const chip = s.arrow === "event" ? 0 : 14, sub = s.sub ? 16 : 0;
  const ay = (isCur ? (narrow ? 48 : 44) : 32) + chip + sub + (selfRow(s) ? SELF_LIFT : 0);
  return { h: ay + (isCur ? 28 : 16) + checks, ay };
}
// A step whose words sit level with its arrow, in the lane's own row: a band's, and a call to itself on a board wide
// enough to put its chip beside the loop. On a narrow board a call to itself has its chip over the loop like any call.
const selfRow = (s) => s.arrow === "self" || s.from === s.to;
const centred = (s, narrow) => s.arrow === "band" || (selfRow(s) && !narrow);
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
    if (s.arrow === "self" && !r.folded) x2 = Math.max(x2, xs.get(s.from) + 60 + Math.max((s.label || "").length * 8.2, (s.sub || "").length * 7.2) + 16);
  }
  x2 = Math.min(w - EDGE, Math.max(x2, x1 + need));
  for (const lx of xs.values()) if (Math.abs(x2 - lx) < 18) x2 = lx > x2 && lx - 18 - x1 >= need ? lx - 18 : Math.min(w - EDGE, lx + 18);
  const y1 = r.y + 4, h = r.y2 - r.y - 4;
  spans.push({ inv, y1, y2: y1 + h });
  fills.push(`<rect class="ln-boxbg${ghost}" x="${x1}" y="${y1}" width="${Math.max(0, x2 - x1)}" height="${h}" rx="8"/>`);
  frames.push(`<path class="ln-boxhead${ghost}" d="M${x1} ${y1 + 26}V${y1 + 8}a8 8 0 0 1 8-8H${x2 - 8}a8 8 0 0 1 8 8V${y1 + 26}Z"/>`,
    `<line class="ln-boxline${ghost}" x1="${x1}" x2="${x2}" y1="${y1 + 26}" y2="${y1 + 26}"/>`,
    `<rect class="ln-boxframe${ghost}" x="${x1}" y="${y1}" width="${Math.max(0, x2 - x1)}" height="${h}" rx="8"/>`);
  for (const b of r.branches) frames.push(`<line class="ln-boxdiv${ghost}" x1="${x1}" x2="${x2}" y1="${b.y + 6}" y2="${b.y + 6}"/>`);
  html.push(`<button type="button" class="ln-kind ln-k-${esc(g.kind)}${ghost}" data-fold="g:${esc(g.id)}" data-group="${esc(g.id)}"
      title="${esc(wd(r.folded ? "group.open" : "group.fold", { kind: g.kind }))}" aria-expanded="${!r.folded}" style="left:${x1 + 7}px;top:${y1 + 5}px">${r.folded ? "▸" : "▾"} ${esc(g.kind)}</button>`,
    `<span class="ln-guard${ghost}" style="left:${x1 + tag}px;top:${y1 + 6}px;max-width:${x2 - x1 - tag - 10}px">${esc(label)}</span>`);
  for (const b of r.branches) {
    const plain = /^(else|otherwise)$/i.test(b.guard.trim());
    const word = g.kind === "par" ? "and" : plain ? "else" : "else if";
    html.push(`<span class="ln-guard ln-branch${ghost}" style="left:${x1 + 10}px;top:${b.y - 5}px;max-width:${x2 - x1 - 20}px"><em>${word}</em>${plain && g.kind !== "par" ? "" : " " + esc(b.guard)}</span>`);
  }
  if (r.folded) {
    const k = r.last - r.first + 1;
    html.push(`<button type="button" class="ln-guard ln-branch ln-folded" data-fold="g:${esc(g.id)}" style="left:${x1 + 12}px;top:${r.foldY + 2}px">${esc(wd("group.folded", { steps: wdn("steps", k) }))}</button>`);
  }
}

// One step: a row the width of the board, keyed, with its arrow, its number, its sentence, its call and its note.
// A step's name for a screen reader, the row's and its dialog's alike: its number as the board shows it, who sends to whom (the
// actors' names as the cards say them), and what is said. A call to itself, a reply (an event arrow) and a stretch say so.
export function stepName(model, i) {
  const s = model.steps[i], n = model.nums[i] ?? i + 1, label = String(s.label || s.sub || "").replace(/\s+/g, " ").trim();
  const actor = (id) => { const a = model.actors.find((x) => x.id === id); return String(a?.label || id).replace(/\s+/g, " ").trim(); };
  const from = actor(s.from), to = actor(s.to);
  if (s.arrow === "band") return wd("seq.band", { n, label });
  if (s.arrow === "self" || s.from === s.to) return wd("seq.self", { n, from, label });
  return wd(s.arrow === "event" ? "seq.reply" : "seq.call", { n, from, to, label });
}

function stepRow(r, st, cols, w, narrow, edge, cur, lit, touches, shown) {
  const { s, i, y, h, ay } = r, { xs } = cols;
  if (s.gap) {   // a compare board's side with no step in this row: a plain box the row's height, drawn in the background svg
    return `<div class="ln-row ln-gap${i === cur ? " ln-cur" : ""}" data-key="step:${esc(s.id)}" data-step="${esc(s.id)}"${shown(i) ? " data-on" : ""}
      style="top:${y}px;height:${h}px" aria-hidden="true"></div>`;
  }
  const kind = KINDS.includes(s.arrow) ? s.arrow : "request";
  const isCur = i === cur, t = tone(s.tone);
  const cls = ["ln-row", "t-" + t, "ln-" + kind, isCur ? "ln-cur" : "", isCur && st.drawn !== cur ? "ln-enter" : "",
    lit.size && touches(s, lit) ? "ln-mine" : "", st.focus && !touches(s, new Set([st.focus])) && !isCur ? "ln-dim" : "",
    st.pop === i ? "ln-open" : ""].filter(Boolean);
  const tag = "";
  const fx = xs.get(s.from), tx = xs.get(s.to);
  const abs = y + ay;
  let svg = "", words = "";
  let numLeft = NUM_AT(narrow), leadTo = null;   // the step's number: beside the start of a call's or a reply's arrow on a wide board, else in its own gutter with a faint line along the row to the arrow
  // wide: in the margin right of the last lane; narrow: a line under the arrow's chip (and its checks) of the step said
  const checkH = (s.checks || []).length ? 30 : 0;
  const bh = (isCur ? 46 : 32) + r.extra.a + r.extra.b;   // a band's height: its words are measured into extra
  const under = ay + (kind === "band" ? bh / 2 + 6 : 12 + checkH);   // a phone's note: under the arrow, or under the band
  const note = !s.note ? "" : !narrow ? `<span class="ln-note" style="top:${ay}px;max-width:${cols.noteW - 22}px">${esc(s.note)}</span>`
    : isCur ? `<span class="ln-note ln-under" style="top:${under}px;left:${cols.left}px;right:${EDGE}px">${esc(s.note)}</span>` : "";
  if (kind === "band") {
    const lo = Math.max(EDGE, Math.min(fx, tx) - 44), hi = Math.min(w - EDGE, Math.max(fx, tx) + 44);
    leadTo = lo - 2;
    svg = `<rect class="ln-bandbar" x="${lo}" y="${ay - bh / 2}" width="${Math.max(0, hi - lo)}" height="${bh}" rx="9"/>`;
    words = `<div class="ln-lbl ln-inband" style="left:${lo + 12}px;width:${hi - lo - 24}px;top:${ay}px">${tag}<b>${said(s, "label")}</b>${s.sub && isCur ? `<code>${said(s, "sub")}</code>` : ""}</div>`;
  } else if (kind === "self" || s.from === s.to) {
    leadTo = fx - BAR - 2;
    const x0 = edge(s.from, abs + 6, 1);
    const right = w - (fx + 52) - EDGE, left = fx - 52 - cols.left;  // a chip goes where it has room, left on a narrow board
    const flip = (fx > w * 0.62 && fx - 300 > cols.left) || (right < 170 && left > right);
    const xr = flip ? xs.get(s.from) - 40 : xs.get(s.from) + 40;
    const sx = flip ? edge(s.from, abs - 10, -1) : edge(s.from, abs - 10, 1);
    const ex = flip ? edge(s.from, abs + 10, -1) : x0;
    // one half-oval out of the lane to xr and back, as sequence_svg draws it
    svg = `<path class="ln-path" pathLength="1" d="M${sx} ${ay - 10}A${Math.abs(xr - sx)} 10 0 0 ${flip ? 0 : 1} ${ex + (flip ? -9 : 9)} ${ay + 10}"/>${head(ex, ay + 10, flip ? 1 : -1, false)}`;
    const room = flip ? xr - 12 - cols.left : w - (xr + 12) - (cols.notes && s.note ? cols.noteW + 6 : EDGE);
    if (narrow) {   // a phone: the chip over the loop, as wide as the board lets it be, its note under the loop (never over the chip)
      const need = Math.max((s.label || "").length * (isCur ? 8.9 : 7.5), (s.sub || "").length * (isCur ? 7.6 : 7)) + 12;
      const lw = Math.min(Math.max(need, 180), w - cols.left - EDGE), mid = (fx + xr) / 2;
      const lc = Math.min(Math.max(mid, lw / 2 + cols.left - 6), w - EDGE - lw / 2);
      words = `<div class="ln-lbl ln-over ln-chipped" style="left:${lc}px;max-width:${lw}px;top:${ay - SELF_LIFT}px">${tag}<b>${said(s, "label")}</b>${s.sub ? `<code>${said(s, "sub")}</code>` : ""}</div>`;
    } else words = `<div class="ln-lbl ln-beside ln-chipped${flip ? " ln-flip" : ""}" style="${flip ? `right:${w - xr + 12}px` : `left:${xr + 12}px`};top:${ay}px;max-width:${Math.max(100, room)}px">
      ${tag}<b>${said(s, "label")}</b>${s.sub ? `<code>${said(s, "sub")}</code>` : ""}</div>`;
  } else {
    const dir = Math.sign(tx - fx), x1 = edge(s.from, abs, dir), x2 = edge(s.to, abs, -dir), ret = kind === "event";
    if (narrow) leadTo = Math.min(x1, x2) - 4;
    else numLeft = Math.max(NUM_AT(false), Math.min(dir > 0 ? x1 - 34 : x1 + 10, w - EDGE - 26));
    svg = `<line class="ln-path" pathLength="1" x1="${x1}" x2="${x2 - dir * 2}" y1="${ay}" y2="${ay}"/>${head(x2, ay, dir, ret)}`;
    if (isCur && st.drawn !== cur) svg += `<circle class="ln-dot" r="4.5" cx="${x1}" cy="${ay}"><animate attributeName="cx" from="${x1}" to="${x2}" dur=".6s" fill="freeze"/><animate attributeName="opacity" values="1;1;0" dur="1s" fill="freeze"/></circle>`;
    const mid = (x1 + x2) / 2, span = Math.abs(x2 - x1);
    // as wide as its words on one line (Inter's and JetBrains Mono's average widths), else as the board allows
    const need = Math.max((s.label || "").length * (isCur ? 8.9 : 7.5), (s.sub || "").length * (isCur ? 7.6 : 7)) + 12;
    let lw = Math.min(Math.max(span + 30, need, narrow ? 180 : 230), w - cols.left - EDGE);
    const right = w - (cols.notes && s.note ? cols.noteW + 6 : EDGE);
    const lc = Math.min(Math.max(mid, lw / 2 + cols.left - 6), right - lw / 2);
    // what a call carries sits in a chip on its arrow: its label, then its sub in mono; a reply's words are bare
    const chip = kind === "event" ? "" : " ln-chipped";
    words = `<div class="ln-lbl ln-over${chip}" style="left:${lc}px;max-width:${lw}px;top:${ay}px">${tag}${s.label ? `<b>${said(s, "label")}</b>` : ""}${s.sub ? `<code>${said(s, "sub")}</code>` : ""}</div>`;
    if (dir < 0) cls.push("ln-back");
  }
  // a step's checks: ✓ / ✗ badges under its arrow, where the rule is applied
  if ((s.checks || []).length && kind !== "band") {
    const at = kind === "self" || s.from === s.to ? xs.get(s.from) + 40 : xs.get(s.to);
    const room = Math.max(160, w - EDGE - Math.max(cols.left, at - 150));
    words += `<div class="ln-checks" style="left:${Math.max(cols.left, at - 150)}px;top:${ay + (kind === "self" || s.from === s.to ? 22 : 10)}px;max-width:${room}px">${s.checks.map((c) =>
      `<span class="ln-ck ${c.ok === false ? "ln-no" : "ln-ok"}">${c.ok === false ? "✗" : "✓"} ${esc(c.label)}</span>`).join("")}</div>`;
  }
  const numText = i > 0 && st.model.nums[i - 1] === st.model.nums[i] ? "" : st.model.nums[i] ?? "";
  if (numText !== "" && leadTo != null && leadTo - (numLeft + 28) > 10) svg = `<line class="ln-lead" x1="${numLeft + 28}" x2="${leadTo}" y1="${ay}" y2="${ay}"/>` + svg;   // which arrow the number is of
  return `<div class="${cls.join(" ")}" role="button" tabindex="0" aria-label="${esc(stepName(st.model, i))}" data-key="step:${esc(s.id)}"
      data-step="${esc(s.id)}" data-from="${esc(s.from)}" data-to="${esc(s.to)}"${shown(i) ? " data-on" : ""}
      style="top:${y}px;height:${h}px"><svg class="ln-svg" width="${w}" height="${h}" aria-hidden="true">${svg}</svg>
    <span class="ln-num" style="top:${ay}px;left:${numLeft}px">${numText}</span>${words}${note}</div>`;
}

// A step's words, those a changed step changed marked (compare.py's `marks`: runs of [words, differs]).
const said = (s, f) => s.marks?.[f] ? s.marks[f].map(([t, m]) => (m ? `<mark class="ln-w">${esc(t)}</mark>` : esc(t))).join("") : esc(s[f]);

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
    const said = el?.querySelector(".ln-lbl");
    const sh = said ? said.offsetHeight : 0;
    let ch = 0;   // what hangs under the arrow (its checks, a narrow board's note): its lowest edge, from 10 px under the arrow
    const aty = el?.querySelector(".ln-num")?.offsetTop ?? 0;
    for (const x of el ? el.querySelectorAll(".ln-call, .ln-checks, .ln-under") : []) if (x.offsetHeight) ch = Math.max(ch, x.offsetTop + x.offsetHeight - aty - 10);
    if (!sh) continue;
    const isCur = el.classList.contains("ln-cur"), b = baseSize(r.s, isCur, st.w < 600);
    const mid = centred(r.s, st.w < 600);
    const above = mid ? sh / 2 + 10 - b.ay : sh + 12 + (selfRow(r.s) ? SELF_LIFT : 0) - b.ay;
    const below = mid ? sh / 2 + 10 - (b.h - b.ay) : (ch ? ch + 8 : 0) + 10 - (b.h - b.ay);
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
  const link = (k) => `<button type="button" class="ln-link" data-popgo="${k}">${esc(wd("pop.link", { n: st.model.nums[k] ?? k + 1, label: steps[k].label }))}</button>`;
  const code = src ? src.lines.map((t, k) => `<div class="ln-cl${src.start + k === src.at ? " ln-at" : ""}"><i>${src.start + k}</i><span>${esc(t) || " "}</span></div>`).join("") : "";
  const kind = wd(s.arrow === "event" ? "kind.reply" : s.arrow === "self" ? "kind.own" : s.arrow === "band" ? "kind.stretch" : "kind.call");
  const pw = Math.min(580, w - 24);
  const mid = (cols.xs.get(s.from) + cols.xs.get(s.to)) / 2 + (s.from === s.to ? 60 : 0);
  const left = Math.max(12, Math.min(mid - pw / 2, w - pw - 12));
  const body = box.querySelector(".ln-body"), H = parseFloat(body.style.height) || 0;
  const below = r.y + r.h + 360 < H || r.y < 380;
  const el = document.createElement("div");
  el.className = "ln-pop" + (below ? "" : " ln-above");
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", stepName(st.model, r.i));
  el.style.cssText = `left:${left}px;top:${below ? r.y + r.h - 2 : r.y + 6}px;width:${pw}px;--caret:${Math.max(18, Math.min(pw - 18, mid - left))}px`;
  el.innerHTML = `<div class="ln-pophead"><span class="ln-badge${r.i === (st.drawn ?? -1) ? " ln-said" : ""}">${st.model.nums[r.i] ?? r.i + 1}</span><span class="ln-popph">${esc(p?.label || "")}</span>
      <button type="button" class="ln-x" data-close title="${esc(wd("close"))}" aria-label="${esc(wd("close"))}">${CLOSE}</button></div>
    <h3>${esc(String(s.label || s.sub || "").charAt(0).toUpperCase() + String(s.label || s.sub || "").slice(1))}</h3>
    <div class="ln-whos">${who(s.from)}${s.from === s.to ? `<em>${esc(wd("pop.itself"))}</em>` : ARROW(s.arrow === "event") + who(s.to)}<span class="ln-kindtag">${kind}</span></div>
    ${s.sub ? `<div class="ln-popcall">${esc(s.sub)}</div>` : ""}
    ${src ? `<div class="ln-src"><div class="ln-srchead">${CODE}${esc(src.path)}:${src.at}</div><div class="ln-lines">${code}</div></div>` : s.ref ? `<div class="ln-srchead ln-nosrc">${CODE}${esc(s.ref)}</div>` : ""}
    ${cond || answers != null || answered != null || s.note ? `<div class="ln-meta">
      ${cond ? `<div><b>${esc(g.kind)}</b> · ${esc(wd("pop.only", { cond }))}</div>` : ""}
      ${answers != null ? `<div><b>${esc(wd("pop.answers"))}</b> ${link(answers)}</div>` : ""}
      ${answered != null ? `<div><b>${esc(wd("pop.answered"))}</b> ${link(answered)}</div>` : ""}
      ${s.note ? `<div><b>${esc(wd("pop.note"))}</b> ${esc(s.note)}</div>` : ""}</div>` : ""}
    ${st.play && st.play(s.id, true) ? `<div class="ln-popact"><button type="button" class="ln-btn ln-pri" data-playfrom="${esc(s.id)}">${PLAY}${esc(wd("play.here"))}</button></div>` : ""}`;
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
    if (ok) { st.pop = null; paint(box); } else pf.textContent = wd("play.none");
    return;
  }
  const pg = at("[data-popgo]");
  if (pg) { st.pop = +pg.dataset.popgo; st.popNew = true; paint(box); return; }
  if (at(".ln-pop")) return;
  const f = at("[data-fold]");
  if (f) { const k = f.dataset.fold; st.folded.has(k) ? st.folded.delete(k) : st.folded.add(k); st.pop = null; paint(box); return; }
  const c = at(".ln-chip, .ln-kitem");
  if (c) { st.focus = st.focus === c.dataset.actor ? null : c.dataset.actor; paint(box); return; }
  const row = at(".ln-row:not(.ln-gap)");
  if (row) { const i = st.model.at.get(row.dataset.step); st.pop = st.pop === i ? null : i; st.popNew = st.pop != null; paint(box); return; }
  if (st.pop != null) { st.pop = null; paint(box); }
}

// Where the view goes (st.aim, set by the frame): `land` does it once, on the pane's own scroller, never the page
// around it. A compare board's panes are `managed`: the board lands the one on show after both are drawn level.
function land(box) {
  const st = box._lanes, aim = st?.aim;
  if (!aim) return;
  st.aim = null;
  if (!box.isConnected || box.closest("[hidden]")) return;
  if (aim === "row") follow(box);
  else if (aim === "top") toTop(box);
  else toOutcome(box, box);
}

function viewOf(box, headBox = box) {
  const scroller = box.closest(".pbody");
  if (!scroller) return null;
  const head = headBox.querySelector(".ln-head");
  const sb = scroller.getBoundingClientRect();
  // the cards stay on top: they cover this much of the pane's top once they stick
  const stuck = head ? (parseFloat(getComputedStyle(head).top) || 0) + head.offsetHeight : 0;
  return { scroller, sb, stuck, smooth: !matchMedia("(prefers-reduced-motion: reduce)").matches };
}

// Keep the step being said a little above the middle of the rows in view, under the cards that stay on top, and
// the top of what shows on a row's own edge, so no row above is cut under the cards and none pokes out of them.
function follow(box) {
  const r = box.querySelector(".ln-row.ln-cur"), v = viewOf(box), st = box._lanes;
  if (!r || !v || !r.isConnected) return;
  const rb = r.getBoundingClientRect();
  const view = v.sb.height - v.stuck;
  let want = v.scroller.scrollTop + (rb.top - v.sb.top) - v.stuck - view * 0.4 + rb.height / 2;
  const body = box.querySelector(".ln-body"), tops = st?.rowTops || [];
  if (body && tops.length) {
    const bodyTop = body.getBoundingClientRect().top - v.sb.top + v.scroller.scrollTop;
    const seen = want + v.stuck - bodyTop;                  // the first y of the rows that show, as the view would be
    const edge = tops.filter((t) => t <= seen + 1).pop();   // the row edge at or above it
    want = edge == null ? 0 : edge - 8 + bodyTop - v.stuck;
  }
  v.scroller.scrollTo({ top: Math.max(0, want), behavior: v.smooth ? "smooth" : "auto" });
}

function toTop(box) {
  const v = viewOf(box);
  if (v) v.scroller.scrollTo({ top: 0, behavior: v.smooth ? "smooth" : "auto" });
}

// The outcome in view with the rows above it: its foot just over the pane's, when it is not whole in it.
function toOutcome(box, headBox) {
  const el = box.querySelector(".ln-outcome"), v = viewOf(box, headBox);
  if (!el || !v) return;
  const eb = el.getBoundingClientRect();
  if (eb.top >= v.sb.top + v.stuck && eb.bottom <= v.sb.bottom - 8) return;
  v.scroller.scrollTo({ top: Math.max(0, v.scroller.scrollTop + eb.bottom - v.sb.bottom + 18), behavior: v.smooth ? "smooth" : "auto" });
}

// -- a before/after board: two lane boards side by side, row for row ------------------------------------------

const SIDES = ["before", "after"];
const MARK = { same: "=", changed: "~", added: "+", removed: "−", moved: "↕" };
const MARK_SAY = { same: 1, changed: 1, added: 1, removed: 1, moved: 1 };   // the words of each are the stage's (words.js: mark.*)
const NARROW = 860;   // a board narrower than this shows one side at a time

// One side as a sequence of its own: its actors (one the other side lacks red and "removed", or green and "new"),
// and a step per row, its own where it has one, a gap where it has none, keyed by the row so a frame lights both.
function sideSpec(spec, side) {
  const actors = spec.compare[side].actors.map((a) => (a.change === "removed" ? { ...a, tone: "red", tag: "removed" }
    : a.change === "added" ? { ...a, tone: "green", tag: "new" } : a));
  const rowOf = new Map(spec.steps.filter((r) => r[side]).map((r) => [r[side].id, r.id]));
  const mates = new Map(spec.steps.filter((r) => r.replaces).map((r) => [r.replaces, r.id]));   // old row -> the row it moved to
  const steps = spec.steps.map((r) => {
    const s = r[side];
    if (!s) return { id: r.id, gap: true, from: actors[0].id, to: actors[0].id, arrow: "gap", label: "" };
    const { row: _row, ...own } = s;
    return { ...own, id: r.id, reply_to: s.reply_to != null ? rowOf.get(s.reply_to) : undefined,
             mate: side === "before" && !r.after ? mates.get(r.id) : undefined };
  });
  return { ...spec, compare: undefined, outcome: undefined, actors, steps };  // the outcome closes both sides at once (paintStrip)
}

// Each side's popup reads its own step's source lines: the after side's under the row's key, the before
// side's under before:<key> (or the row's key when the row has no after step).
function sideRefs(spec, refs, side) {
  const out = {};
  for (const r of spec.steps) {
    const ref = side === "after" ? (r.after ? refs[r.id] : null) : r.after ? refs["before:" + r.id] : refs[r.id];
    if (ref) out[r.id] = ref;
  }
  return out;
}

function renderCompare(box, spec, embedded, more) {
  const cmp = spec.compare;
  box.innerHTML = `<div class="ln-cmp"><div class="ln-sidebar" role="group" aria-label="${esc(wd("cmp.which"))}">${SIDES.map((sd) =>
      `<button type="button" class="ln-mode" data-side="${sd}" aria-pressed="false">${esc(cmp[sd].label)}</button>`).join("")}</div>
    <div class="ln-cgrid">${SIDES.map((sd, k) => `${k ? `<div class="ln-gutter" aria-hidden="true"></div>` : ""}<div class="ln-side ln-s-${sd}" data-side="${sd}">
      <div class="ln-stitle"><b>${esc(wd(sd === "before" ? "cmp.before" : "cmp.after"))}</b>${String(cmp[sd].label).toLowerCase() === sd ? "" : ` · ${esc(cmp[sd].label)}`}</div><div class="ln-pane"></div></div>`).join("")}</div>
    <div class="ln-cout"></div></div>`;
  box._lanes = null;
  const st = box._cmp = { spec, scene: null, n: null, mode: "both", pinned: false, pick: "after", panes: {} };
  for (const sd of SIDES) {
    const pane = box.querySelector(`.ln-s-${sd} .ln-pane`);
    renderLanes(pane, sideSpec(spec, sd), embedded, { refs: sideRefs(spec, more.refs || {}, sd), play: more.play, onPaint: () => syncSides(box), managed: true });
    st.panes[sd] = pane;
  }
  if (!box._cmpObserved) {
    box._cmpObserved = true;
    new ResizeObserver(() => box._cmp && layoutCompare(box, box._cmp.scene, box._cmp.n)).observe(box);
    box.addEventListener("click", (e) => {
      const b = e.target.closest?.(".ln-sidebar [data-side]"), c = box._cmp;
      if (!b || !c) return;
      c.pick = b.dataset.side; c.mode = b.dataset.side; c.pinned = true;
      layoutCompare(box, c.scene, c.n);
    });
    box.addEventListener("mouseover", (e) => {   // a row and its partner on the other side light together
      const r = e.target.closest?.(".ln-row"), id = r?.dataset.step ?? null;
      for (const x of box.querySelectorAll(".ln-row")) x.classList.toggle("ln-hov", id != null && x.dataset.step === id);
    });
    box.addEventListener("mouseleave", () => { for (const x of box.querySelectorAll(".ln-row.ln-hov")) x.classList.remove("ln-hov"); });
  }
  layoutCompare(box, null);
}

// The side the voice last pointed at (both, before or after), else the reader's own pick; then each side drawn.
function layoutCompare(box, scene, n = null) {
  const st = box._cmp;
  if (n !== st.n) st.pinned = false;   // the reader's own pick holds until the voice moves on
  st.scene = scene; st.n = n;
  let voice = null;
  if (scene && n != null) {
    for (let k = Math.min(n, scene.frames.length - 1); k >= 0 && !voice; k--) {
      const f = scene.frames[k].focus || [];
      voice = ["both", "before", "after"].find((m) => f.includes("mode:" + m)) || (f.includes("mode:merged") ? "both" : null);
    }
  }
  const atRest = !!scene && n != null && n >= scene.rest;   // the answer is over: both sides whole, nothing dimmed
  const mode = st.pinned ? st.mode : atRest ? "both" : voice || st.mode;
  const narrow = box.clientWidth > 0 && box.clientWidth < NARROW;
  let one = narrow ? (mode === "both" ? st.pick : mode) : null;
  if (one && mode === "both" && !st.pinned && scene && n != null) {   // the side on show follows the step being said
    const said = beingSaid(scene, n).filter((k) => k.startsWith("step:")).pop();
    const row = said && st.spec.steps.find((r) => "step:" + r.id === said);
    if (row && !row[one] && row[one === "before" ? "after" : "before"]) one = one === "before" ? "after" : "before";
  }
  box.classList.remove("ln-m-both", "ln-m-before", "ln-m-after");
  box.classList.add("ln-m-" + mode);
  box.classList.toggle("ln-narrow", narrow);
  for (const sd of SIDES) box.querySelector(`.ln-s-${sd}`).hidden = !!one && one !== sd;
  box.querySelector(".ln-gutter").hidden = narrow;
  for (const b of box.querySelectorAll(".ln-sidebar [data-side]")) b.setAttribute("aria-pressed", String(b.dataset.side === (one || mode)));
  const most = Math.max(...SIDES.map((sd) => st.panes[sd]._lanes?.model.actors.length || 0));
  for (const sd of SIDES) {
    const l = st.panes[sd]._lanes;
    if (l) { l.dropGaps = narrow; l.peers = most; }
    layoutLanes(st.panes[sd], scene, n);
  }
  syncSides(box);
  paintStrip(box);
  landCompare(box);
}

// The outcome, once across both sides under the last row, drawn as a sequence draws its own (outcomeHtml).
function paintStrip(box) {
  const c = box._cmp, o = c.spec.outcome, host = box.querySelector(".ln-cout");
  if (!o) { host.replaceChildren(); return; }
  const steps = c.spec.steps, scene = c.scene, n = c.n;
  const f = scene ? scene.frames[Math.max(0, Math.min(n ?? scene.frames.length - 1, scene.frames.length - 1))] : null;
  const fr = { show: f ? new Set(f.show) : null, focus: new Set(f?.focus || []), said: scene && n != null ? beingSaid(scene, n) : [] };
  const gone = new Set(steps.map((s) => s.replaces).filter(Boolean));
  let last = steps.length - 1;
  while (last > 0 && gone.has(steps[last].id)) last--;
  const curKey = fr.said.filter((k) => k.startsWith("step:")).pop();
  const cur = curKey ? steps.findIndex((s) => "step:" + s.id === curKey) : null;
  const state = outcomeLit({ scene, n, model: { steps } }, fr, cur >= 0 ? cur : null, last);
  const html = outcomeHtml(o, state, "");
  const old = host.firstElementChild;
  if (old && old.querySelector("b")?.textContent === o.title) {   // the same strip: its classes change, so it fades in or out
    const next = document.createElement("div"); next.innerHTML = html;
    old.className = next.firstElementChild.className;
  } else host.innerHTML = html;
  const was = !!c.outSaid; c.outSaid = state.said;
  if (state.said && !was) c.aimOut = true;
}

// After both sides are level: the view goes where the frame said, on the side on show (the after side when both are).
function landCompare(box) {
  const c = box._cmp;
  const shown = SIDES.map((sd) => c.panes[sd]).filter((p) => !p.closest(".ln-side")?.hidden);
  const aims = SIDES.map((sd) => c.panes[sd]._lanes?.aim).filter(Boolean);
  for (const sd of SIDES) if (c.panes[sd]._lanes) c.panes[sd]._lanes.aim = null;
  const pane = shown[shown.length - 1];
  // a side that came on show after the voice moved on (the pane was hidden when the step changed) is brought to it too
  const behind = pane?._lanes && pane._lanes.cur != null && pane._lanes.landed !== pane._lanes.cur;
  const aim = aims.includes("row") || behind ? "row" : c.aimOut ? "outcome" : aims.includes("top") ? "top" : null;
  c.aimOut = false;
  if (pane?._lanes && aim && pane.clientWidth > 0) pane._lanes.landed = aim === "row" ? pane._lanes.cur : null;
  if (!aim || !pane || !box.isConnected || box.clientWidth === 0) return;
  requestAnimationFrame(() => {
    pane._lanes.aim = null;
    if (aim === "row") follow(pane);
    else if (aim === "top") toTop(box);
    else toOutcome(box, pane);
  });
}

// Each row as tall as its taller side, its arrow at the lower of the two, and the heads as tall as each other;
// then the gutter's marks at the rows. A side drawn again with new sizes calls back here, and stops once both agree.
function syncSides(box) {
  const st = box._cmp;
  if (!st || st.syncing) return;
  const a = st.panes.before?._lanes, b = st.panes.after?._lanes;
  if (!a?.natural || !b?.natural) return;
  const pad = new Map();
  for (const [id, x] of a.natural) {
    const y = b.natural.get(id) || x, ay = Math.max(x.ay, y.ay);
    pad.set(id, { ay, h: ay + Math.max(x.h - x.ay, y.h - y.ay) });
  }
  const same = (p, q) => p && q && p.size === q.size && [...p].every(([k, v]) => q.get(k)?.h === v.h && q.get(k)?.ay === v.ay);
  st.syncing = true;
  try {
    for (const pane of [st.panes.before, st.panes.after]) {
      if (!same(pane._lanes.pad, pad)) { pane._lanes.pad = pad; paint(pane); }
    }
  } finally { st.syncing = false; }
  const heads = [st.panes.before, st.panes.after].map((p) => p.querySelector(".ln-actors"));
  for (const h of heads) h.style.minHeight = "";
  const tall = Math.max(...heads.map((h) => h.offsetHeight || 0));
  if (tall) for (const h of heads) h.style.minHeight = tall + "px";
  const keys = [st.panes.before, st.panes.after].map((p) => p.querySelector(".ln-key"));   // the key above the cards, as tall on both
  for (const k of keys) k.style.minHeight = "";
  const keyTall = Math.max(...keys.map((k) => k.offsetHeight || 0));
  if (keyTall) for (const k of keys) k.style.minHeight = keyTall + "px";
  const gutter = box.querySelector(".ln-gutter"), body = st.panes.after.querySelector(".ln-body");
  const top = body ? body.offsetTop : 0;   // both measured from the top of their side, which the gutter shares
  gutter.innerHTML = st.spec.steps.map((r) => `<i class="ln-gm ln-gm-${r.change}" data-row="${esc(r.id)}" title="${MARK_SAY[r.change] ? esc(wd("mark." + r.change)) : ""}"
    style="top:${top + (b.rowAt.get(r.id) ?? 0)}px">${MARK[r.change] || ""}</i>`).join("")
    + st.spec.steps.filter((r) => r.replaces && b.rowAt.has(r.id) && b.rowAt.has(r.replaces)).map((r) => {   // a moved step: its old place joined to its new
      const y1 = top + b.rowAt.get(r.replaces), y2 = top + b.rowAt.get(r.id);
      return `<i class="ln-gconn${b.cur === r.id ? " ln-lit" : ""}" data-row="${esc(r.id)}" style="top:${Math.min(y1, y2)}px;height:${Math.abs(y2 - y1)}px"></i>`;
    }).join("");
}
