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

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const lerp = (a, b, t) => a + (b - a) * t;
  const tone = (t) => (["raw", "group", "accent", "muted"].includes(t) ? `var(--${t})` : "currentColor");
  const r2 = (v) => Math.round(v * 100) / 100;

  // ── validation ──
  // render.py refuses the same specs with the same messages; this copy makes a page
  // that skipped render.py throw at load, so `--check` exits 3 instead of drawing a lie.
  function validate(spec) {
    if (!spec.cards || !spec.cards.length) throw new Error("the spec has no cards");
    const byId = new Map(spec.cards.map((c) => [c.id, c]));
    if (byId.size !== spec.cards.length) throw new Error("two cards share an id");
    for (const c of spec.cards) {
      if ("slot" in c && !Number.isInteger(c.slot)) throw new Error(`card '${c.id}': slot must be a whole number`);
      if (!c.fields || !c.fields.length) throw new Error(`card '${c.id}' has no fields`);
      if (new Set(c.fields.map((f) => f.id)).size !== c.fields.length) throw new Error(`card '${c.id}': two fields share an id`);
      if (!["real", "follow"].includes(c.rows ?? "real")) throw new Error(`card '${c.id}': rows must be one of ('real', 'follow')`);
    }
    const seen = new Set(), feeds = new Map(spec.cards.map((c) => [c.id, new Set()]));
    for (const e of spec.edges || []) {
      for (const end of [e.from, e.to]) {
        const dot = end.indexOf("."), cid = end.slice(0, dot), fid = end.slice(dot + 1);
        if (!byId.has(cid)) throw new Error(`no card '${cid}'`);
        if (!byId.get(cid).fields.some((f) => f.id === fid)) throw new Error(`${cid} has no field '${fid}'`);
      }
      const a = e.from.split(".")[0], b = e.to.split(".")[0];
      if (a === b) throw new Error(`edge ${e.from} → ${e.to} stays inside card '${a}'; a field cannot feed its own card`);
      if (seen.has(e.from + "\n" + e.to)) throw new Error(`edge ${e.from} → ${e.to} appears twice`);
      seen.add(e.from + "\n" + e.to);
      if ("lane" in e && !["above", "below"].includes(e.lane)) throw new Error(`edge ${e.from} → ${e.to}: lane must be one of ('above', 'below')`);
      feeds.get(a).add(b);
    }
    // three-colour DFS from each card in spec order, successors in id order: the same
    // spec always reports the same loop
    const colour = new Map(), cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
    for (const c of spec.cards) {
      if (colour.get(c.id)) continue;
      const path = [c.id], stack = [[...feeds.get(c.id)].sort(cmp)[Symbol.iterator]()];
      colour.set(c.id, 1);
      while (stack.length) {
        const n = stack[stack.length - 1].next();
        if (n.done) { colour.set(path.pop(), 2); stack.pop(); continue; }
        const st = colour.get(n.value) || 0;
        if (st === 1) {
          const loop = [...path.slice(path.indexOf(n.value)), n.value];
          throw new Error(`cards feed each other in a loop: ${loop.join(" → ")}; draw the later stage of one of them as its own card`);
        }
        if (st === 0) { colour.set(n.value, 1); path.push(n.value); stack.push([...feeds.get(n.value)].sort(cmp)[Symbol.iterator]()); }
      }
    }
  }

  const cards = SPEC.cards.map((c) => ({
    id: c.id, name: c.name, sub: c.sub || "", stage: c.stage || "", tone: c.tone, fields: c.fields.slice(), rowY: {}, rowH: {},
  }));
  const byId = Object.fromEntries(cards.map((c) => [c.id, c]));
  const edges = SPEC.edges || [];
  let routes = [];

