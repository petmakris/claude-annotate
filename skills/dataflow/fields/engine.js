// The field-view engine: lays out a field-mapping spec, draws it, and runs the canvas.
//
// Everything positional is computed here from the spec alone. Nothing measures the
// DOM, so a thumbnail, a print and a cold load draw the same picture, and the same
// spec always gives the same coordinates. The engine publishes what it computed on
// window.__layout and its own quality measures on window.__layoutReport, which is
// what the tests and `render.py --check` read.
(function () {
  "use strict";
  const SPEC = JSON.parse(document.getElementById("spec").textContent);

  // ── the grid ──
  const HEADER_H = 46, ROW_H = 26, PAD_X = 13, MIN_GAP = 120, MIN_CARD_W = 130, SLOT_VGAP = 40, MARGIN = 20;
  // Advance widths for the faces the page uses. Overestimating buys padding; underestimating clips.
  const MONO_11 = 6.65, MONO_13 = 7.9, SANS_95 = 5.3, SANS_9 = 5.1;
  const PORT = 10;              // a row grows this much per extra wire, and ports sit this far apart
  const DGAP = 16, DPAD = 24;   // bypass lanes: apart from each other, and clear of a card
  const COMPACT = 0.8;          // how hard a row is pulled toward its card neighbours
  const STEEP = 1.0, STEEP_CAP = 480, PER_WIRE = 8;   // gap width from the climb across it
  const SWEEPS = 14;

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const lerp = (a, b, t) => a + (b - a) * t;
  const tone = (t) => (["raw", "group", "accent", "muted"].includes(t) ? `var(--${t})` : "currentColor");
  const r2 = (v) => Math.round(v * 100) / 100;

  const cards = SPEC.cards.map((c, i) => ({
    id: c.id, name: c.name, sub: c.sub || "", stage: c.stage || "", tone: c.tone,
    follow: c.rows === "follow", slot: c.slot ?? i, fields: c.fields.slice(),
    w: Math.max(MIN_CARD_W, c.name.length * MONO_13 + 2 * PAD_X, (c.sub || "").length * SANS_95 + 2 * PAD_X,
      ...c.fields.map((f) => f.label.length * MONO_11 + 2 * PAD_X)),
    rowY: {}, rowH: {},
  }));
  const byId = Object.fromEntries(cards.map((c) => [c.id, c]));
  const edges = SPEC.edges || [];
  const slots = {};
  cards.forEach((c) => (slots[c.slot] = slots[c.slot] || []).push(c));
  const order = Object.keys(slots).map(Number).sort((a, b) => a - b);
  let routes = [];

  // ── layout ──
  // Rows sit at the height of what feeds them; a card may grow and show gaps. A wire
  // that skips columns gets a waypoint in each column it crosses, above or below that
  // column's cards, so it never passes behind one. Heights come from alternating
  // sweeps: each item moves toward the mean height of its neighbours, then an
  // order-preserving least-squares fit (pool-adjacent-violators) restores the spacing.
  function layout() {
    const colOf = Object.fromEntries(cards.map((c) => [c.id, order.indexOf(c.slot)]));

    // starting heights: each slot's cards stacked and centred on one axis
    const spans = {};
    order.forEach((si) => (spans[si] = slots[si].reduce((a, c) => a + HEADER_H + ROW_H * c.fields.length, 0) + SLOT_VGAP * (slots[si].length - 1)));
    const axis = Math.max(...Object.values(spans)) / 2;
    const items = {};
    order.forEach((si) => {
      let cur = axis - spans[si] / 2;
      slots[si].forEach((c) => {
        c.fields.forEach((f, i) => {
          const id = `${c.id}.${f.id}`;
          items[id] = { id, col: colOf[c.id], kind: "row", card: c, idx: i, y: cur + HEADER_H + ROW_H * i + ROW_H / 2 };
        });
        cur += HEADER_H + ROW_H * c.fields.length + SLOT_VGAP;
      });
    });

    const segs = [], chains = [];
    edges.forEach((e, ei) => {
      const a = items[e.from], b = items[e.to], chain = [a.id];
      for (let ci = a.col + 1; ci < b.col; ci++) {
        const d = { id: `~${ei}.${ci}`, col: ci, kind: "dummy", src: a, tgt: b, lane: e.lane,
          y: lerp(a.y, b.y, (ci - a.col) / (b.col - a.col)) };
        items[d.id] = d;
        chain.push(d.id);
      }
      chain.push(b.id);
      chains.push(chain);
      for (let i = 0; i + 1 < chain.length; i++) segs.push({ a: chain[i], b: chain[i + 1], e: ei, first: i === 0 });
    });
    const preds = {}, succs = {};
    segs.forEach((s) => { (succs[s.a] = succs[s.a] || []).push(s.b); (preds[s.b] = preds[s.b] || []).push(s.a); });
    // a row carrying several wires grows, so each wire gets its own port inside it
    Object.values(items).forEach((it) => {
      const n = Math.max((preds[it.id] || []).length, (succs[it.id] || []).length);
      it.h = it.kind === "row" ? ROW_H + Math.max(0, n - 1) * PORT : 0;
    });
    const colItems = order.map((_, ci) => Object.values(items).filter((it) => it.col === ci));
    const mean = (ids) => ids.reduce((a, id) => a + items[id].y, 0) / ids.length;

    function pav(z, w) {
      const bl = [];
      z.forEach((v, i) => {
        bl.push({ v, w: w[i], n: 1 });
        while (bl.length > 1 && bl[bl.length - 2].v > bl[bl.length - 1].v) {
          const b2 = bl.pop(), b1 = bl.pop();
          bl.push({ v: (b1.v * b1.w + b2.v * b2.w) / (b1.w + b2.w), w: b1.w + b2.w, n: b1.n + b2.n });
        }
      });
      return bl.flatMap((b) => Array(b.n).fill(b.v));
    }

    function place(ci, primary) {
      const its = colItems[ci];
      const want = new Map();
      its.forEach((it) => {
        // a bypass holds its source's height, so it bends once, at its target
        const p = it.kind === "dummy" ? preds[it.id] : (primary === "pred" ? preds : succs)[it.id];
        const q = it.kind === "dummy" ? null : (primary === "pred" ? succs : preds)[it.id];
        if (p && p.length) want.set(it, [mean(p), 1]);
        else if (q && q.length) want.set(it, [mean(q), 0.6]);
        else want.set(it, [it.y, 0.05]);
      });
      const raw = new Map([...want].map(([k, v]) => [k, v[0]]));   // ordering uses this, before compaction
      const rank = (a, b) => (a.card.follow ? raw.get(a) - raw.get(b) : 0) || a.idx - b.idx;
      // compaction: a row is also pulled toward its card neighbours, so a card only
      // opens a gap where a wire gains more than the gap costs
      its.forEach((it) => {
        if (it.kind !== "row") return;
        const sib = it.card.fields.map((f) => items[`${it.card.id}.${f.id}`]).sort(rank);
        const k = sib.indexOf(it), near = [];
        if (k > 0) near.push(sib[k - 1].y + (sib[k - 1].h + it.h) / 2);
        if (k + 1 < sib.length) near.push(sib[k + 1].y - (sib[k + 1].h + it.h) / 2);
        if (!near.length) return;
        const [v, w] = want.get(it), c = near.reduce((a, b) => a + b, 0) / near.length;
        want.set(it, [(v * w + c * COMPACT) / (w + COMPACT), w + COMPACT]);
      });
      const stack = slots[order[ci]];
      const rows = its.filter((it) => it.kind === "row").sort((a, b) => stack.indexOf(a.card) - stack.indexOf(b.card) || rank(a, b));
      const centre = rows.reduce((a, r) => a + want.get(r)[0], 0) / rows.length;
      const dums = its.filter((it) => it.kind === "dummy").sort((a, b) => want.get(a)[0] - want.get(b)[0]);
      // a bypass goes over or under by where it both starts and ends; the spec can force a side
      const over = (d) => (d.lane ? d.lane === "above" : (d.src.y + d.tgt.y) / 2 < centre);
      const seq = [...dums.filter(over), ...rows, ...dums.filter((d) => !over(d))];
      let off = 0;
      const offs = [];
      seq.forEach((it, i) => {
        if (i) {
          const p = seq[i - 1];
          if (p.kind === "dummy" && it.kind === "dummy") off += DGAP;
          else if (p.kind === "dummy") off += DPAD + 18 + HEADER_H + it.h / 2;
          else if (it.kind === "dummy") off += p.h / 2 + DPAD;
          else if (p.card === it.card) off += (p.h + it.h) / 2;
          else off += p.h / 2 + SLOT_VGAP + HEADER_H + it.h / 2;
        }
        offs.push(off);
      });
      const fit = pav(seq.map((it, i) => want.get(it)[0] - offs[i]), seq.map((it) => want.get(it)[1]));
      seq.forEach((it, i) => (it.y = fit[i] + offs[i]));
    }
    for (let sweep = 0; sweep < SWEEPS; sweep++) {
      for (let ci = 0; ci < order.length; ci++) place(ci, "pred");
      for (let ci = order.length - 1; ci >= 0; ci--) place(ci, "succ");
    }
    for (let ci = 0; ci < order.length; ci++) place(ci, "pred");   // settle left to right last

    // card boxes from their rows
    cards.forEach((c) => {
      if (c.follow) c.fields.sort((a, b) => items[`${c.id}.${a.id}`].y - items[`${c.id}.${b.id}`].y);
      c.fields.forEach((f) => { const it = items[`${c.id}.${f.id}`]; c.rowY[f.id] = it.y; c.rowH[f.id] = it.h; });
      const f0 = c.fields[0].id, fl = c.fields[c.fields.length - 1].id;
      c.y = c.rowY[f0] - c.rowH[f0] / 2 - HEADER_H;
      c.h = c.rowY[fl] + c.rowH[fl] / 2 - c.y;
    });
    const top = Math.min(...cards.map((c) => c.y - 30), ...Object.values(items).filter((i) => i.kind === "dummy").map((d) => d.y - 20));
    cards.forEach((c) => { c.y -= top; Object.keys(c.rowY).forEach((k) => (c.rowY[k] -= top)); });
    Object.values(items).forEach((it) => (it.y -= top));

    // gaps: wide enough for the longest label leaving the column, and wider still for
    // the steepest climb across it, so long climbs stay shallow
    const colW = order.map((si) => Math.max(...slots[si].map((c) => c.w)));
    const gapW = order.slice(0, -1).map((_, gi) => {
      let need = 0, climb = 0, n = 0;
      segs.forEach((s) => {
        if (items[s.a].col !== gi) return;
        if (s.first) need = Math.max(need, ...[edges[s.e].label, edges[s.e].note].map((t) => (t || "").length * SANS_9 + 46));
        climb = Math.max(climb, Math.abs(items[s.b].y - items[s.a].y));
        n++;
      });
      return Math.max(MIN_GAP, need, Math.min(STEEP_CAP, climb * STEEP + n * PER_WIRE), (SPEC.gaps || {})[order[gi]] || 0);
    });
    let x = MARGIN;
    const colX = [];
    order.forEach((si, ci) => {
      colX[ci] = x;
      slots[si].forEach((c) => { c.x = x; c.w = colW[ci]; });
      if (ci < gapW.length) x += colW[ci] + gapW[ci];
    });

    // ports: wires that share a row leave (or arrive) at their own height inside it,
    // ordered by where their other end sits, so a fan never collapses into one point
    const port = {};
    [["a", "b"], ["b", "a"]].forEach(([key, other]) => {
      const groups = {};
      segs.forEach((s) => (groups[s[key]] = groups[s[key]] || []).push(s));
      Object.entries(groups).forEach(([id, g]) => {
        g.sort((p, q) => items[p[other]].y - items[q[other]].y);
        g.forEach((s, i) => (port[`${key}|${s.e}|${id}`] = items[id].kind === "row" ? (i - (g.length - 1) / 2) * PORT : 0));
      });
    });

    // wires: a cubic per hop, flat at both ends; a bypass runs straight past the
    // cards of a column it skips
    routes = chains.map((chain, ei) => {
      let d = "", head = null, tail = null;
      const samples = [];
      for (let i = 0; i + 1 < chain.length; i++) {
        const a = items[chain[i]], b = items[chain[i + 1]];
        const x1 = colX[a.col] + colW[a.col], x2 = colX[b.col], g = x2 - x1;
        const y1 = a.y + port[`a|${ei}|${a.id}`], y2 = b.y + port[`b|${ei}|${b.id}`];
        if (i === 0) { d = `M ${x1} ${y1}`; head = [x1, y1]; }
        else {
          // the straight run past a skipped column's cards: sampled too, since that is
          // exactly where a wire would pass behind a card
          const [px, py] = samples[samples.length - 1];
          for (let k = 1; k <= 12; k++) samples.push([lerp(px, x1, k / 12), lerp(py, y1, k / 12)]);
          d += ` L ${x1} ${y1}`;
        }
        const c1 = [x1 + g * 0.55, y1], c2 = [x2 - g * 0.35, y2];
        d += ` C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${x2} ${y2}`;
        for (let k = 0; k <= 24; k++) {
          const t = k / 24, u = 1 - t;
          samples.push([u * u * u * x1 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * x2,
                        u * u * u * y1 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * y2]);
        }
        tail = [x2, y2];
      }
      return { d, head, tail, samples, texts: [] };
    });

    // labels and notes: each tries beside its start, then beside its arrowhead, above
    // then below, and takes the first spot that hits no card and no text already placed
    const boxes = cards.map((c) => ({ x: c.x - 2, y: c.y - 24, w: c.w + 4, h: c.h + 24 }));
    const overlap = (b) => boxes.reduce((a, o) => a + Math.max(0, Math.min(b.x + b.w, o.x + o.w) - Math.max(b.x, o.x)) *
      Math.max(0, Math.min(b.y + b.h, o.y + o.h) - Math.max(b.y, o.y)), 0);
    let labelOverlaps = 0;
    const texts = [];
    edges.forEach((e, ei) => {
      if (e.label) texts.push({ ei, kind: "label", text: e.label });
      if (e.note) texts.push({ ei, kind: "note", text: e.note });
    });
    texts.forEach((t) => {
      const R = routes[t.ei], w = t.text.length * 4.9 + 4, h = 11;
      const cands = [
        { x: R.head[0] + 10, y: R.head[1] - 6, anchor: "start" },
        { x: R.head[0] + 10, y: R.head[1] + 13, anchor: "start" },
        { x: R.tail[0] - 12, y: R.tail[1] - 6, anchor: "end" },
        { x: R.tail[0] - 12, y: R.tail[1] + 13, anchor: "end" },
      ].map((c) => ({ ...c, box: { x: c.anchor === "end" ? c.x - w : c.x, y: c.y - 9, w, h } }));
      let best = cands[0], bestHit = Infinity;
      for (const c of cands) {
        const v = overlap(c.box);
        if (v < bestHit) { best = c; bestHit = v; }
        if (!v) break;
      }
      if (bestHit > 0) labelOverlaps++;
      R.texts.push({ ...t, ...best });
      boxes.push(best.box);
    });

    report(segs, items, colX, colW, labelOverlaps);
  }

  // ── the report: what render.py --check prints ──
  function report(segs, items, colX, colW, labelOverlaps) {
    const endCards = (e) => [e.from.split(".")[0], e.to.split(".")[0]];
    let behind = 0;
    routes.forEach((R, ei) => {
      const own = endCards(edges[ei]);
      R.samples.forEach(([x, y]) => {
        cards.forEach((c) => {
          if (own.includes(c.id)) return;
          if (x > c.x + 1 && x < c.x + c.w - 1 && y > c.y + 1 && y < c.y + c.h - 1) behind++;
        });
      });
    });
    const cross = (p, q, r, s) => {
      const d = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
      return d(p, q, r) * d(p, q, s) < 0 && d(r, s, p) * d(r, s, q) < 0;
    };
    let crossings = 0;
    for (let i = 0; i < routes.length; i++) {
      for (let j = i + 1; j < routes.length; j++) {
        const a = edges[i], b = edges[j];
        if (a.from === b.from || a.to === b.to || a.from === b.to || a.to === b.from) continue;
        const A = routes[i].samples, B = routes[j].samples;
        let hit = false;
        for (let m = 1; m < A.length && !hit; m++)
          for (let n = 1; n < B.length && !hit; n++) hit = cross(A[m - 1], A[m], B[n - 1], B[n]);
        if (hit) crossings++;
      }
    }
    let steep = 0;
    segs.forEach((s) => {
      const a = items[s.a], b = items[s.b], g = colX[b.col] - (colX[a.col] + colW[a.col]);
      steep = Math.max(steep, Math.abs(b.y - a.y) / g);
    });
    let detour = 0;
    routes.forEach((R, ei) => {
      const a = items[edges[ei].from], b = items[edges[ei].to];
      if (b.col - a.col < 2) return;
      let len = 0;
      for (let k = 1; k < R.samples.length; k++)
        len += Math.hypot(R.samples[k][0] - R.samples[k - 1][0], R.samples[k][1] - R.samples[k - 1][1]);
      detour = Math.max(detour, len - Math.hypot(R.tail[0] - R.head[0], R.tail[1] - R.head[1]));
    });
    window.__layout = {
      cards: Object.fromEntries(cards.map((c) => [c.id, {
        x: r2(c.x), y: r2(c.y), w: r2(c.w), h: r2(c.h),
        rows: Object.fromEntries(c.fields.map((f) => [f.id, { y: r2(c.rowY[f.id]), h: r2(c.rowH[f.id]) }])),
      }])),
      wires: routes.map((R, ei) => ({
        from: edges[ei].from, to: edges[ei].to,
        start: R.head.map(r2), end: R.tail.map(r2), samples: R.samples.map((p) => p.map(r2)),
      })),
      labels: routes.flatMap((R, ei) => R.texts.map((t) => ({ edge: ei, kind: t.kind,
        ...Object.fromEntries(Object.entries(t.box).map(([k, v]) => [k, r2(v)])) }))),
    };
    window.__layoutReport = {
      behind_card: behind, label_overlaps: labelOverlaps, crossings,
      max_steepness: r2(steep), detour: r2(detour),
    };
  }

  // ── drawing ──
  const svg = $("#svg"), cam = $("#cam"), content = $("#content"), stage = $("#stage");
  $("#defs").innerHTML = ["n", "raw", "group", "accent", "muted"].map((tn) =>
    `<marker id="am-${tn}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">` +
    `<path d="M0 0L10 5L0 10z" fill="${tone(tn === "n" ? null : tn)}"/></marker>`).join("");

  function draw() {
    let out = "";
    // wires first, so a wire never crosses a field name
    edges.forEach((e, i) => {
      const R = routes[i];
      out += `<g class="edge" data-edge="${i}" data-from="${esc(e.from)}" data-to="${esc(e.to)}">` +
        `<path class="wire" d="${R.d}" stroke="${tone(e.tone)}" marker-end="url(#am-${e.tone || "n"})"/>` +
        `<path class="wirehit" d="${R.d}"/>` +
        R.texts.map((t) => `<text class="${t.kind === "note" ? "enote" : "elabel"}" x="${t.x}" y="${t.y}" text-anchor="${t.anchor}"` +
          (t.kind === "note" ? "" : ` fill="${tone(e.tone)}"`) + `>${esc(t.text)}</text>`).join("") +
        `</g>`;
    });
    cards.forEach((c) => {
      const stroke = tone(c.tone);
      if (c.stage) out += `<text class="stage" x="${c.x}" y="${c.y - 12}">${esc(c.stage)}</text>`;
      out += `<rect class="cardshadow" x="${c.x + 1}" y="${c.y + 3}" width="${c.w}" height="${c.h}" rx="7"/>`;
      out += `<rect class="card" x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}" rx="7" stroke="${stroke}"/>`;
      out += `<text class="cname" x="${c.x + PAD_X}" y="${c.y + 23}" fill="${stroke}">${esc(c.name)}</text>`;
      if (c.sub) out += `<text class="csub" x="${c.x + PAD_X}" y="${c.y + 38}">${esc(c.sub)}</text>`;
      out += `<line class="crule" x1="${c.x}" y1="${c.y + HEADER_H}" x2="${c.x + c.w}" y2="${c.y + HEADER_H}" stroke="${stroke}"/>`;
      c.fields.forEach((f, i) => {
        const rh = c.rowH[f.id], mid = c.rowY[f.id], top = mid - rh / 2, id = `${c.id}.${f.id}`;
        const prevBottom = i ? c.rowY[c.fields[i - 1].id] + c.rowH[c.fields[i - 1].id] / 2 : top;
        out += `<g class="node${f.muted ? " is-muted" : ""}" data-node="${esc(id)}" tabindex="0" role="button" aria-label="${esc(f.label)}">`;
        if (top - prevBottom > 0.5)
          out += `<rect class="rowgap" x="${c.x + 0.8}" y="${prevBottom}" width="${c.w - 1.6}" height="${top - prevBottom}"/>` +
            `<line class="rowrule" x1="${c.x}" y1="${prevBottom}" x2="${c.x + c.w}" y2="${prevBottom}" stroke="${stroke}"/>`;
        if (i) out += `<line class="rowrule" x1="${c.x}" y1="${top}" x2="${c.x + c.w}" y2="${top}" stroke="${stroke}"/>`;
        out += `<rect class="hit" x="${c.x + 1}" y="${top}" width="${c.w - 2}" height="${rh}"/>`;
        out += `<text class="fname" x="${c.x + PAD_X}" y="${mid + 4}" fill="${tone(f.tone)}"${f.strong ? ' font-weight="600"' : ""}>${esc(f.label)}</text>`;
        out += `</g>`;
      });
    });
    content.innerHTML = out;
    applySel();
  }

  // ── tracing: hover lights a field's lineage, a click pins it ──
  // Lineage is what the field flows into, followed forward only, plus what flows into
  // it, followed backward only. Walking both ways from every reached field would climb
  // back up through each fan-in and light fields with no relation to the one clicked.
  const flowsTo = {}, flowsFrom = {};
  edges.forEach((e, i) => { (flowsTo[e.from] = flowsTo[e.from] || []).push(i); (flowsFrom[e.to] = flowsFrom[e.to] || []).push(i); });
  function walk(start, along, end) {
    const nodes = { [start]: true }, wires = {}, stack = [start];
    while (stack.length) {
      (along[stack.pop()] || []).forEach((i) => {
        wires[i] = true;
        const m = edges[i][end];
        if (!nodes[m]) { nodes[m] = true; stack.push(m); }
      });
    }
    return { nodes, wires };
  }
  function reach(start) {
    const down = walk(start, flowsTo, "to"), up = walk(start, flowsFrom, "from");
    return { nodes: { ...down.nodes, ...up.nodes }, wires: { ...down.wires, ...up.wires } };
  }
  let sel = null, hover = null;
  function applySel() {
    const on = sel || hover;
    content.classList.toggle("has-sel", !!on);
    if (!on) return;
    const lit = reach(on);
    content.querySelectorAll(".node").forEach((el) => el.classList.toggle("on", !!lit.nodes[el.dataset.node]));
    content.querySelectorAll(".edge").forEach((el) => el.classList.toggle("on", !!lit.wires[el.dataset.edge]));
  }

  // ── camera ──
  let view = { x: 0, y: 0, k: 1 };
  function bounds() {
    const xs = cards.flatMap((c) => [c.x, c.x + c.w]), ys = cards.flatMap((c) => [c.y - 30, c.y + c.h]);
    routes.forEach((R) => R.samples.forEach(([, y]) => ys.push(y - 10, y + 10)));
    return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  }
  function apply() {
    cam.setAttribute("transform", `translate(${view.x} ${view.y}) scale(${view.k})`);
    const g = 22 * view.k;
    stage.style.backgroundSize = `${g}px ${g}px`;
    stage.style.backgroundPosition = `${view.x}px ${view.y}px`;
    $("#zpct").textContent = Math.round(view.k * 100) + "%";
    const b = bounds(), pad = 40, mini = $("#mini"), vp = $("#vp");
    mini.setAttribute("viewBox", `${b.x - pad} ${b.y - pad} ${b.w + 2 * pad} ${b.h + 2 * pad}`);
    vp.setAttribute("x", -view.x / view.k); vp.setAttribute("y", -view.y / view.k);
    vp.setAttribute("width", stage.clientWidth / view.k); vp.setAttribute("height", stage.clientHeight / view.k);
  }
  const clampK = (k) => Math.min(4, Math.max(0.12, k));
  function zoomAt(k, sx, sy) {
    k = clampK(k);
    view.x = sx - (sx - view.x) * (k / view.k);
    view.y = sy - (sy - view.y) * (k / view.k);
    view.k = k;
    apply();
  }
  let camAnim = null;
  function animateTo(nv) {
    cancelAnimationFrame(camAnim);
    const from = { ...view }, t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 280), e = 1 - Math.pow(1 - p, 3);
      view = { x: lerp(from.x, nv.x, e), y: lerp(from.y, nv.y, e), k: lerp(from.k, nv.k, e) };
      apply();
      if (p < 1) camAnim = requestAnimationFrame(step);
    };
    camAnim = requestAnimationFrame(step);
  }
  const animateZoomAt = (k, sx, sy) => {
    k = clampK(k);
    animateTo({ k, x: sx - (sx - view.x) * (k / view.k), y: sy - (sy - view.y) * (k / view.k) });
  };
  function fitRect(r, maxK = 1.6) {
    const W = stage.clientWidth, H = stage.clientHeight, chrome = document.body.classList.contains("shot");
    const padX = chrome ? 24 : 60, padTop = chrome ? 24 : 90, padBot = chrome ? 24 : 110;
    const k = clampK(Math.min((W - 2 * padX) / r.w, (H - padTop - padBot) / r.h, maxK));
    return { k, x: padX + (W - 2 * padX - r.w * k) / 2 - r.x * k, y: padTop + (H - padTop - padBot - r.h * k) / 2 - r.y * k };
  }
  const fit = (anim = true) => { const v = fitRect(bounds()); if (anim) animateTo(v); else { view = v; apply(); } };
  function fitSel() {
    if (!sel) return fit();
    const xs = [], ys = [];
    Object.keys(reach(sel).nodes).forEach((id) => {
      const dot = id.indexOf("."), c = byId[id.slice(0, dot)], fid = id.slice(dot + 1);   // field ids may hold dots
      xs.push(c.x, c.x + c.w);
      ys.push(c.rowY[fid] - c.rowH[fid] / 2, c.rowY[fid] + c.rowH[fid] / 2);
    });
    const r = { x: Math.min(...xs), y: Math.min(...ys) - 40, w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) + 40 };
    animateTo(fitRect(r, 1.4));
  }
  window.__fit = () => fit(false);   // render.py --check fits after hiding the chrome

  // ── input ──
  stage.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    if (ev.ctrlKey || ev.metaKey) zoomAt(view.k * Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.012 : 0.004)), ev.clientX, ev.clientY);
    else { view.x -= ev.deltaX; view.y -= ev.deltaY; apply(); }
  }, { passive: false });
  let drag = null;
  stage.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    drag = { sx: ev.clientX, sy: ev.clientY, vx: view.x, vy: view.y, moved: false, target: ev.target };
    stage.setPointerCapture(ev.pointerId);
  });
  stage.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.sx, dy = ev.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) > 4) { drag.moved = true; stage.classList.add("panning"); cancelAnimationFrame(camAnim); }
    if (drag.moved) { view.x = drag.vx + dx; view.y = drag.vy + dy; apply(); }
  });
  stage.addEventListener("pointerup", () => {
    if (!drag) return;
    stage.classList.remove("panning");
    if (!drag.moved) click(drag.target);
    drag = null;
  });
  stage.addEventListener("pointerover", (ev) => {
    if (drag && drag.moved) return;
    const n = ev.target.closest(".node"), h = n ? n.dataset.node : null;
    if (h !== hover) { hover = h; applySel(); }
  });
  stage.addEventListener("dblclick", (ev) => {
    if (ev.target.closest(".node,.edge")) return;
    animateZoomAt(view.k * 2, ev.clientX, ev.clientY);
  });
  function click(target) {
    const node = target.closest(".node"), edge = target.closest(".edge");
    sel = node ? node.dataset.node : edge ? edge.dataset.from : null;
    applySel();
  }
  document.addEventListener("keydown", (ev) => {
    const W = stage.clientWidth / 2, H = stage.clientHeight / 2;
    const node = ev.target.closest && ev.target.closest(".node");
    if (node && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); sel = node.dataset.node; applySel(); return; }
    if (ev.key === "Escape") { sel = null; applySel(); $("#about").classList.remove("open"); $("#aboutBtn").setAttribute("aria-pressed", "false"); }
    else if (ev.key === "f" || ev.key === "F") (sel ? fitSel() : fit());
    else if (ev.key === "0") fit();
    else if (ev.key === "1") animateZoomAt(1, W, H);
    else if (ev.key === "+" || ev.key === "=") animateZoomAt(view.k * 1.4, W, H);
    else if (ev.key === "-") animateZoomAt(view.k / 1.4, W, H);
  });
  const centre = () => [stage.clientWidth / 2, stage.clientHeight / 2];
  $("#zin").onclick = () => animateZoomAt(view.k * 1.4, ...centre());
  $("#zout").onclick = () => animateZoomAt(view.k / 1.4, ...centre());
  $("#zpct").onclick = () => animateZoomAt(1, ...centre());
  $("#zfit").onclick = () => (sel ? fitSel() : fit());
  const mini = $("#mini");
  function miniMove(ev) {
    const pt = mini.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    const p = pt.matrixTransform(mini.getScreenCTM().inverse());
    view.x = stage.clientWidth / 2 - p.x * view.k;
    view.y = stage.clientHeight / 2 - p.y * view.k;
    apply();
  }
  mini.addEventListener("pointerdown", (ev) => { mini.setPointerCapture(ev.pointerId); miniMove(ev); mini.onpointermove = miniMove; });
  mini.addEventListener("pointerup", () => (mini.onpointermove = null));
  window.addEventListener("resize", apply);

  // ── chrome ──
  $("#eyebrow").textContent = SPEC.eyebrow || "";
  $("#h1").textContent = SPEC.title;
  const src = SPEC.sources || { rows: [] };
  $("#about").innerHTML =
    (SPEC.lede ? `<h2>What this shows</h2><p>${SPEC.lede}</p>` : "") +
    (SPEC.caption ? `<h2>The shapes</h2><p>${SPEC.caption}</p>` : "") +
    ((src.rows || []).length ? `<h2>Sources</h2><table>` +
      (src.head ? `<tr>${src.head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` : "") +
      src.rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("") + `</table>` : "");
  $("#aboutBtn").onclick = () => {
    const open = $("#about").classList.toggle("open");
    $("#aboutBtn").setAttribute("aria-pressed", String(open));
  };
  $("#legend").innerHTML = (SPEC.legend || []).map((k) => `<span class="key"><i class="sw ${esc(k.tone || "")}"></i>${esc(k.text)}</span>`).join("");

  layout();
  draw();
  fit(false);
})();
