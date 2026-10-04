// annotate page code, part 3 of 9 (see script.js): the `explain` block — a
// code pane the explanation rides on — and its walk.

// ── kind: explain ─────────────────────────────────────────────────────
// A pane where the explanation rides on the code. Everything positional is
// measured in `ch` against columns resolved server-side (explain.py), which
// is exact because the pane is monospace.
//
// The marks are ABSOLUTE OVERLAYS, not wrappers around the text. Wrapping a
// span would mean splitting the highlighter's output at a character offset — and worse,
// an inline element inserted into a `white-space: pre` row shifts every
// glyph after it, so the underline would stop lining up with the thing it is
// underlining. Overlaying leaves the highlighted line untouched and costs
// nothing in layout, which is also why a badge here does not nudge the code
// sideways the way an inline badge would.
function explainRow(row, n, group, painted, ulines) {
  const div = document.createElement("div");
  div.className = "cp-row ex-row";
  if (row.blank) div.classList.add("is-blank");
  const text = document.createElement("span");
  text.className = "cp-line";
  if (painted != null) text.innerHTML = painted;
  else text.textContent = row.text;
  div.appendChild(text);

  (group ? group.marks : []).forEach((m) => {
    const u = document.createElement("i");
    u.className = "ex-uline";
    u.style.left = `calc(12px + ${m.col}ch)`;
    u.style.width = `${m.len}ch`;
    div.appendChild(u);
    // The walk lights one note's marks at a time and finds them by where
    // they are, which is the only thing a step and a mark both know.
    if (ulines) ulines.set(`${n}:${m.col}`, u);
    // An echo is a second place the same note is true of. It has no label
    // of its own, so a badge on it would number an entry that is not in the
    // list under the line — see explainNotes.
    const onSpanBadge = group.mode === "badge" && !m.echo;
    if (onSpanBadge) {
      const b = document.createElement("i");
      b.className = "ex-badge ex-badge--onspan";
      b.textContent = String(m.n);
      b.style.left = `calc(12px + ${m.col + m.len}ch)`;
      div.appendChild(b);
    }
    // The value chip: the concrete number this example carries at this
    // exact span, so a reader tracks the trace without leaving the code to
    // read a label. Independent of the walk and of echo status — two
    // occurrences of one claim can carry two different numbers.
    //
    // Split the same way `.ex-at`/`.ex-pin` are: the OFFSET-carrying node
    // (`ex-val`) inherits the row's code font untouched, because `ch` is a
    // metric of an element's own font and the column arithmetic above was
    // written in the code font's `ch`. A prose-sized chip styled directly
    // on that node would resolve a narrower `ch` and land back over the
    // span it is meant to follow. The pill's own look lives one level in,
    // on `ex-val-chip`, which carries no position of its own.
    //
    // Badge mode only, NOT on-span: three marks already sit close enough on
    // one line to need numbered badges instead of a ladder (see LADDER_MAX
    // in explain.py), and a value chip wide enough to read overlaps the
    // very next mark's span at that spacing. explainNotes prints it there
    // instead, next to the badge it belongs to, where there is a full row
    // of width to spend on it.
    if (m.valueHtml && group.mode !== "badge") {
      const v = document.createElement("i");
      v.className = "ex-val";
      v.style.left = `calc(12px + ${m.col + m.len}ch)`;
      v.appendChild(explainValueChip(m.valueHtml));
      div.appendChild(v);
    }
  });
  return div;
}

function explainLabel(html, extra) {
  const el = document.createElement("div");
  el.className = "ex-lbl" + (extra ? ` ${extra}` : "");
  // Restricted inline markdown, already escaped and rendered by explain.py's
  // label_html — bold and code and nothing else. Not model HTML.
  el.innerHTML = html || "";
  return el;
}

// The value chip's look with no positioning node around it — for a context
// that is already laid out (the notes list), unlike the on-span form in
// explainRow, which needs one to carry a `ch` offset in the code's font.
function explainValueChip(html) {
  const el = document.createElement("span");
  el.className = "ex-val-chip";
  el.innerHTML = html || "";
  return el;
}

// One or two marks: a ladder. Labels are emitted rightmost-first, the way a
// compiler stacks them, and every mark to the LEFT of the one being labelled
// carries a stem down through the row so its own elbow below still reads as
// coming from its column. Stems are 1px wide with -1px margin, so they draw
// at exactly their column and consume no width — which is what keeps the
// gaps expressible as whole `ch` counts with no pixel bookkeeping.
function explainLadder(group) {
  const lad = document.createElement("div");
  lad.className = "ex-lad";
  // Echoes are underlined on the line and stop there: they carry no label,
  // so a rung for one would be an elbow pointing at nothing.
  const marks = group.marks.filter((m) => !m.echo);
  for (let j = marks.length - 1; j >= 0; j--) {
    const row = document.createElement("div");
    row.className = "ex-lad-row";
    let prev = 0;
    for (let i = 0; i < j; i++) {
      row.appendChild(explainGap(marks[i].col - prev));
      const stem = document.createElement("i");
      stem.className = "ex-stem";
      row.appendChild(stem);
      prev = marks[i].col;
    }
    row.appendChild(explainGap(marks[j].col - prev));
    const elbow = document.createElement("i");
    elbow.className = "ex-elbow";
    row.appendChild(elbow);
    row.appendChild(explainLabel(marks[j].labelHtml));
    lad.appendChild(row);
  }
  return lad;
}

function explainGap(ch) {
  const gap = document.createElement("i");
  gap.className = "ex-gap";
  gap.style.width = `${Math.max(0, ch)}ch`;
  return gap;
}

// Three or more marks: the ladder becomes a knot, so the labels leave the
// columns and become a numbered list. The underlines stay on the line, so
// position is still stated — only the attachment changes.
function explainNotes(group) {
  const list = document.createElement("div");
  list.className = "ex-notes";
  group.marks.filter((m) => !m.echo).forEach((m) => {
    const item = document.createElement("div");
    item.className = "ex-note";
    const b = document.createElement("i");
    b.className = "ex-badge";
    b.textContent = String(m.n);
    item.appendChild(b);
    item.appendChild(explainLabel(m.labelHtml));
    if (m.valueHtml) item.appendChild(explainValueChip(m.valueHtml));
    list.appendChild(item);
  });
  return list;
}

// ── the walk ──────────────────────────────────────────────────────────
// One note at a time, in the order they were written, with the rest of the
// pane stepped back. The static pane is built FIRST and in full — every
// underline, every ladder, every bracket — and the walk is then a layer of
// state on top of it: `data-walk` on the pane, `.is-now` on the current
// note's marks, `.is-lit` on its rows. Nothing is built for one mode and
// missing from the other, which is what lets the export (no JS, no
// controls) recover the whole pane by deleting three nodes and one
// attribute rather than re-rendering anything.

// The pins: a step's number, parked past the end of its first line. They are
// the pane's table of contents — how many stops there are, where they are,
// and a way into any of them without walking the ones between.
function explainPins(step, onPick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "ex-pin";
  b.textContent = String(step.n);
  b.title = step.lead ? `step ${step.n} — ${step.lead}` : `step ${step.n}`;
  b.addEventListener("click", () => onPick(step.n - 1));
  return b;
}

// A tray that resizes as you step shoves the rest of the page down mid-read,
// so it is sized once to the longest note and never moves again. Measured
// AFTER the webfonts land: against the fallback face the reservation comes
// out a line short, and the pane grows on the first long note anyway —
// 326px then 344px, measured in Chromium. `border-box` is why the padding
// is added back in.
function reserveTray(tray, steps) {
  const settle = () => requestAnimationFrame(() => {
    const keep = [...tray.childNodes];
    let tallest = 0;
    steps.forEach((s) => {
      tray.replaceChildren(explainLabel(s.labelHtml));
      tallest = Math.max(tallest, tray.firstChild.getBoundingClientRect().height);
    });
    tray.replaceChildren(...keep);
    const cs = getComputedStyle(tray);
    tray.style.minHeight = Math.ceil(
      tallest + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)) + "px";
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(settle);
  else settle();
}

function explainWalk(wrap, body, view, rowEls, ulines) {
  const steps = view.walk || [];
  if (!steps.length) return;

  // `view.walk`'s own marks carry only position — `view.groups` is where a
  // mark's `valueHtml` lives (see explain.py). Cross-referenced by
  // `line:col`, the same key `ulines` already uses to find a mark again
  // after it is painted.
  const groupByLine = new Map((view.groups || []).map((g) => [g.line, g]));
  const valueByPos = new Map();
  (view.groups || []).forEach((g) => g.marks.forEach((m) => {
    if (m.valueHtml) valueByPos.set(`${g.line}:${m.col}`, m.valueHtml);
  }));

  const tray = document.createElement("div");
  tray.className = "ex-tray";

  const bar = document.createElement("div");
  bar.className = "ex-bar";
  const prev = document.createElement("button");
  prev.type = "button"; prev.className = "ex-step"; prev.textContent = "‹";
  prev.setAttribute("aria-label", "previous step");
  const next = document.createElement("button");
  next.type = "button"; next.className = "ex-step"; next.textContent = "›";
  next.setAttribute("aria-label", "next step");
  const count = document.createElement("span");
  count.className = "ex-count";
  const pips = document.createElement("span");
  pips.className = "ex-pips";
  steps.forEach(() => {
    const p = document.createElement("i");
    p.className = "ex-pip";
    pips.appendChild(p);
  });
  bar.append(prev, next, count, pips);

  let at = 0;
  const pins = [];

  function go(i) {
    at = Math.max(0, Math.min(steps.length - 1, i));
    const step = steps[at];

    rowEls.forEach((r) => r.classList.remove("is-lit"));
    ulines.forEach((u) => u.classList.remove("is-now"));

    const lines = step.kind === "range"
      ? Array.from({ length: step.to - step.from + 1 }, (_, k) => step.from + k)
      : (step.marks || []).map((m) => m.line);
    lines.forEach((n) => {
      const row = rowEls[n - 1];
      if (row) row.classList.add("is-lit");
    });
    (step.marks || []).forEach((m) => {
      const u = ulines.get(`${m.line}:${m.col}`);
      if (u) u.classList.add("is-now");
    });

    const trayKids = [explainLabel(step.labelHtml)];
    // Badge-mode values live in `.ex-notes`, which the walk hides (see
    // .codepane.ex[data-walk] .ex-notes) — without this they would be the
    // one thing on the pane a walking reader never sees. Ladder-mode values
    // stay on the span throughout the walk already, so repeating them here
    // would be the same number printed twice.
    if (step.kind === "span") {
      (step.marks || []).forEach((m) => {
        if ((groupByLine.get(m.line) || {}).mode !== "badge") return;
        const html = valueByPos.get(`${m.line}:${m.col}`);
        if (html) trayKids.push(explainValueChip(html));
      });
    }
    tray.replaceChildren(...trayKids);
    count.textContent = `step ${at + 1} of ${steps.length}` +
      (step.lead ? ` — ${step.lead}` : "");
    prev.disabled = at === 0;
    next.disabled = at === steps.length - 1;
    pins.forEach((p, k) => p.classList.toggle("is-now", k === at));
    pips.querySelectorAll(".ex-pip").forEach((p, k) => p.classList.toggle("on", k === at));

    // Only when the step is genuinely off screen: `block: "nearest"` would
    // still be a no-op most of the time, but a snippet long enough to walk
    // off the bottom is exactly the one this kind is for.
    const first = rowEls[lines[0] - 1];
    if (first) {
      const r = first.getBoundingClientRect();
      if (r.top < 0 || r.bottom > (window.innerHeight || 0)) {
        first.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  }

  // A pin per step, grouped by the line it sits on so two steps starting on
  // the same line stand side by side instead of on top of each other.
  const byLine = new Map();
  steps.forEach((s) => {
    const line = s.kind === "range" ? s.from : (s.marks[0] && s.marks[0].line);
    if (!line) return;
    if (!byLine.has(line)) byLine.set(line, []);
    byLine.get(line).push(s);
  });
  // A value chip is anchored to its span, which is sometimes the last thing
  // on the line — `priceInReferenceCurrency)` leaves one character before
  // the pin's own reservation. Widen that reservation by the chip's rough
  // width (plain-text length, tags stripped: a `valueHtml` is the same
  // restricted markdown as a label) rather than moving the chip, since the
  // chip's whole point is sitting exactly where the span ends. Badge-mode
  // lines never grow an on-span chip (see explainRow), so they need no
  // overhang here.
  function valueOverhang(line) {
    const group = groupByLine.get(line);
    const base = ((view.rows[line - 1] || {}).text || "").length;
    if (!group || group.mode === "badge") return 0;
    let end = base;
    group.marks.forEach((m) => {
      if (!m.valueHtml) return;
      const plain = m.valueHtml.replace(/<[^>]+>/g, "");
      end = Math.max(end, m.col + m.len + 2 + plain.length + 1);
    });
    return Math.max(0, end - base);
  }
  byLine.forEach((list, line) => {
    const row = rowEls[line - 1];
    if (!row) return;
    const at_ = document.createElement("i");
    at_.className = "ex-at";
    // Past the end of the line, never on top of it. The offset is in `ch`
    // and this element inherits the CODE font, which is the only font whose
    // `ch` the column arithmetic is written in — a pin styled in the prose
    // face resolves a narrower `ch` and lands back among the glyphs.
    at_.style.left = `calc(12px + ${(view.rows[line - 1] || {}).text.length + 2 + valueOverhang(line)}ch)`;
    list.forEach((s) => {
      const pin = explainPins(s, go);
      pins[s.n - 1] = pin;
      at_.appendChild(pin);
    });
    row.appendChild(at_);
  });

  prev.addEventListener("click", () => go(at - 1));
  next.addEventListener("click", () => go(at + 1));
  wrap.tabIndex = 0;
  wrap.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { go(at + 1); ev.preventDefault(); }
    else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { go(at - 1); ev.preventDefault(); }
  });

  wrap.append(tray, bar);
  // Opens already walking: a control nobody finds is a feature nobody has.
  wrap.dataset.walk = "1";
  go(0);
  reserveTray(tray, steps);
}

function renderExplain(content, blk) {
  const view = blk.view || {};
  const wrap = document.createElement("div");
  wrap.className = "codepane ex";

  if (view.error) {
    const err = document.createElement("div");
    err.className = "cp-status";
    err.dataset.status = "refused";
    err.textContent = `explain block: ${view.error}`;
    wrap.appendChild(err);
    content.appendChild(wrap);
    return;
  }

  const head = document.createElement("div");
  head.className = "cp-head";
  const path = document.createElement("span");
  path.className = "cp-path";
  if (view.project) {
    const pill = document.createElement("span");
    pill.className = "cp-proj";
    pill.textContent = view.project;
    pill.style.setProperty("--cp-pill-h", String(hueFromName(view.project)));
    path.appendChild(pill);
  }
  if (view.loc) {
    const loc = document.createElement("span");
    loc.className = "cp-loc";
    loc.textContent = view.loc;
    path.appendChild(loc);
  }
  head.appendChild(path);
  wrap.appendChild(head);

  const body = document.createElement("div");
  body.className = "cp-body ex-body";

  const rows = view.rows || [];
  const groups = new Map((view.groups || []).map((g) => [g.line, g]));
  const opens = new Map((view.ranges || []).map((r) => [r.from, r]));

  let sink = body;      // where the next row goes
  let open = null;      // the range being filled, if any
  // The walk needs to find a row and a mark again after they are painted;
  // rebuilding either from the spec would be a second renderer to keep in
  // step with this one.
  const rowEls = [];
  const ulines = new Map();
  // The whole snippet in one pass, cut into rows: see CodePaint.rows.
  const paintOpts = { lang: view.lang, file: (view.loc || "").replace(/:\d+$/, "") };
  const misses = codeMisses();
  const painted = window.CodePaint ? CodePaint.rows(rows.map((r) => r.text), paintOpts) : null;

  for (let n = 1; n <= rows.length; n++) {
    if (!open && opens.has(n)) {
      open = opens.get(n);
      const range = document.createElement("div");
      range.className = "ex-range";
      const side = document.createElement("div");
      side.className = "ex-range-code";
      range.appendChild(side);
      body.appendChild(range);
      open.el = range;
      sink = side;
    }
    const rowEl = explainRow(rows[n - 1], n, groups.get(n),
                             painted ? painted[n - 1] : null, ulines);
    rowEls[n - 1] = rowEl;
    sink.appendChild(rowEl);
    const g = groups.get(n);
    if (g) sink.appendChild(g.mode === "badge" ? explainNotes(g) : explainLadder(g));
    if (open && n === open.to) {
      const brk = document.createElement("i");
      brk.className = "ex-brk";
      open.el.appendChild(brk);
      open.el.appendChild(explainLabel(open.labelHtml, "ex-lbl--range"));
      open = null;
      sink = body;
    }
  }
  wrap.appendChild(body);
  if (!painted && codeMisses() > misses) {
    later(body, paintRowsLater(rowEls.map((r) => r.querySelector(".cp-line")),
                               rows.map((r) => r.text), paintOpts));
  }
  explainWalk(wrap, body, view, rowEls, ulines);
  content.appendChild(wrap);
}
