  // ── wiring the layout into the page ──
  // computeLayout numbers edges by their two ends; the page keeps spec order, so the
  // routes are put back in the order of SPEC.edges before anything draws them.
  const split = (end) => { const dot = end.indexOf("."); return [byId[end.slice(0, dot)], end.slice(dot + 1)]; };   // field ids may hold dots
  const ends = edges.map((e) => [split(e.from), split(e.to)]);
  let base = {}, computed = null;
  function layout() {
    const L = computeLayout(SPEC, { now: () => performance.now() });
    L.cards.forEach((lc) => {
      const c = byId[lc.id];
      c.x = lc.x; c.y = lc.y; c.w = lc.w; c.h = lc.h;
      c.fields = lc.item.ports.map((p) => p.f);          // drawn in the published row order
      lc.item.ports.forEach((p) => { c.rowY[p.f.id] = p.y; c.rowH[p.f.id] = p.h; });
    });
    const at = new Map(L.edges.map((E) => [E.e, E.i]));
    routes = edges.map((e) => L.routes[at.get(e)]);
    // where each wire meets its rows, as an offset from the row's centre: a row carrying
    // several wires fans them out, and a move must keep that fan, not collapse it
    routes.forEach((R, i) => {
      const [[ca, fa], [cb, fb]] = ends[i];
      R.pa = R.head[1] - ca.rowY[fa]; R.pb = R.tail[1] - cb.rowY[fb];
    });
    base = Object.fromEntries(cards.map((c) => [c.id, { y: c.y, h: c.h, order: c.fields.map((f) => f.id), tops: tops(c) }]));
    computed = L.layout;
    window.__layout = L.layout;
    // the report is the layout's own verdict; a viewer's moves never recompute it
    window.__layoutReport = L.report;
    window.__layoutTiming = L.T;
  }
  // The geometry on screen now, after a move, for the tests: the computed layout with each
  // card's y and rows, each wire's ends, hops and samples, and each label taken from what is
  // drawn. Columns, col and order stay the layout's: a move is up or down within a column.
  function publish() {
    const L = JSON.parse(JSON.stringify(computed));
    for (const c of cards) Object.assign(L.cards[c.id], { y: r2(c.y), h: r2(c.h),
      rowOrder: c.fields.map((f) => f.id),
      rows: Object.fromEntries(c.fields.map((f) => [f.id, { y: r2(c.rowY[f.id]), h: r2(c.rowH[f.id]) }])) });
    L.wires = routes.map((R, ei) => ({ from: edges[ei].from, to: edges[ei].to, start: R.head.map(r2), end: R.tail.map(r2),
      hops: R.hopGeo.map((g) => g.map(r2)), samples: R.samples.map((q) => q.map(r2)) }));
    L.labels = routes.flatMap((R, ei) => R.texts.map((t) => ({ edge: ei, kind: t.kind,
      ...Object.fromEntries(Object.entries(t.box).map(([k, v]) => [k, r2(v)])) })));
    window.__layout = L;
  }

  // ── rearranging ──
  // A viewer may move a card up or down and reorder the rows inside it. Nothing moves
  // sideways, so the columns, the lanes and every wire's x stay the layout's: only the two
  // ends of a wire touching a moved card change, and the wire is rebuilt from its hop list
  // by wireRoute, the same code that drew it.
  const touching = (c) => edges.map((_, i) => i).filter((i) => ends[i][0][0] === c || ends[i][1][0] === c);
  const fieldOf = Object.fromEntries(SPEC.cards.map((c) => [c.id, Object.fromEntries(c.fields.map((f) => [f.id, f]))]));
  // A card is its header and its rows in c.fields order, never overlapping. As laid out the
  // rows touch and the card is exactly as tall as they are; a viewer may make the card taller
  // and spread its rows inside it, so each row is kept as its top's offset from the card's.
  const packedH = (c) => c.fields.reduce((a, f) => a + c.rowH[f.id], K.HEADER_H);
  const tops = (c) => c.fields.map((f) => r2(c.rowY[f.id] - c.rowH[f.id] / 2 - c.y));
  function place(c, offs) { c.fields.forEach((f, i) => { c.rowY[f.id] = c.y + offs[i] + c.rowH[f.id] / 2; }); }
  // rows touch, in c.fields order, under the header
  function pack(c) {
    let y = K.HEADER_H;
    place(c, c.fields.map((f) => { const o = y; y += c.rowH[f.id]; return o; }));
  }
  // offsets that keep each row as close to want[i] as the card allows: no row above the
  // header, below the card's bottom, or over its neighbour; the row at fix stays at want[fix]
  // and the others give way, each by no more than it must
  function settleRows(c, want, fix = -1) {
    const hs = c.fields.map((f) => c.rowH[f.id]), n = hs.length, o = want.slice();
    const down = (from) => { for (let i = from; i < n; i++) o[i] = Math.max(o[i], i ? o[i - 1] + hs[i - 1] : K.HEADER_H); };
    const up = (from) => { for (let i = from; i >= 0; i--) o[i] = Math.min(o[i], i < n - 1 ? o[i + 1] - hs[i] : c.h - hs[i]); };
    if (fix < 0) { down(0); up(n - 1); }
    else { up(fix - 1); down(fix + 1); }
    return o;
  }
  let lift = null;   // the row in hand, { c, fid, y }: drawn and wired at y, its slot left empty
  const rowAt = (c, fid) => (lift && lift.c === c && lift.fid === fid ? lift.y : c.rowY[fid]);
  function reroute(i) {
    const R = routes[i], [[ca, fa], [cb, fb]] = ends[i], g = R.hopGeo.map((h) => h.slice());
    g[0][1] = rowAt(ca, fa) + R.pa;
    g[g.length - 1][3] = rowAt(cb, fb) + R.pb;
    Object.assign(R, wireRoute(g));
  }
  // labels of the wires in ids placed again, by the layout's own rule, around everything
  // that did not move; the other labels stay where the layout put them
  function relabel(ids) {
    const mine = new Set(ids), boxes = cardBoxes(cards), hits = wireGrid(routes);
    routes.forEach((R, i) => { if (!mine.has(i)) for (const t of R.texts) boxes.push(t.box); });
    for (const i of ids) {
      const R = routes[i];
      R.texts = R.texts.map((t) => {
        const { pick } = placeText(K, { ...t, ei: i }, R, R.hopGeo.length === 1, boxes, hits);
        boxes.push(pick.box);
        return { ...t, x: pick.x, y: pick.y, anchor: pick.anchor, box: pick.box };
      });
    }
  }
  function settle(cs) {
    const ids = [...new Set(cs.flatMap(touching))].sort((a, b) => a - b);
    ids.forEach(reroute);
    relabel(ids);
  }

  // The arrangement is the viewer's own: per card, how far it moved and its row order, kept
  // in this browser under a hash of the spec, so a changed spec starts from its new layout.
  // Storage can be blocked or absent (a private window, a file opened from a mail client);
  // the page then draws the computed layout and forgets moves on reload.
  const KEY = (() => {
    let h = 0x811c9dc5;
    for (const ch of document.getElementById("spec").textContent) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
    return "dataflow-fields:" + h.toString(16);
  })();
  let arr = {};
  function remember(c) {
    const b = base[c.id], order = c.fields.map((f) => f.id), dy = r2(c.y - b.y), h = r2(c.h), offs = tops(c);
    if (!dy && h === r2(b.h) && order.every((id, i) => id === b.order[i]) && offs.every((o, i) => o === b.tops[i])) delete arr[c.id];
    else arr[c.id] = { dy, order, h, tops: offs };
  }
  function save() {
    try { if (Object.keys(arr).length) localStorage.setItem(KEY, JSON.stringify(arr)); else localStorage.removeItem(KEY); } catch (e) { /* storage blocked */ }
    $("#zreset").disabled = !Object.keys(arr).length;
  }
  // a saved card that no longer fits this spec (other fields, rows over each other or out
  // of the card, a height its rows do not fit in) is ignored whole, not half-applied
  function restore() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { saved = {}; }
    const moved = [];
    const num = (v) => typeof v === "number" && Number.isFinite(v);
    for (const c of cards) {
      const a = saved[c.id], b = base[c.id];
      if (!a || typeof a !== "object") continue;
      const n = b.order.length;
      if (!Array.isArray(a.order) || a.order.length !== n || new Set(a.order).size !== n || !a.order.every((id) => id in fieldOf[c.id])) continue;
      if (!num(a.dy ?? 0) || ("h" in a && !num(a.h)) || ("tops" in a && !(Array.isArray(a.tops) && a.tops.length === n && a.tops.every(num)))) continue;
      const fields = a.order.map((id) => fieldOf[c.id][id]), hs = fields.map((f) => c.rowH[f.id]);
      const h = a.h ?? b.h, offs = a.tops || null;
      if (h < hs.reduce((x, y) => x + y, K.HEADER_H) - 0.01) continue;
      if (offs && !offs.every((o, i) => o >= (i ? offs[i - 1] + hs[i - 1] : K.HEADER_H) - 0.01) || offs && offs[n - 1] + hs[n - 1] > h + 0.01) continue;
      c.y = b.y + (a.dy ?? 0);
      c.h = h;
      c.fields = fields;
      if (offs) place(c, offs); else pack(c);
      remember(c);
      if (arr[c.id]) moved.push(c);
    }
    if (moved.length) { settle(moved); publish(); }
    save();
  }
  function resetLayout() {
    arr = {};
    save();
    layout();
    draw();
    apply();
  }
  window.__measure = (layout) => measure(SPEC, layout);
  window.__fieldEngine = { networkSimplex, computeLayout };

  // ── drawing ──
  const svg = $("#svg"), cam = $("#cam"), content = $("#content"), stage = $("#stage");
  $("#defs").innerHTML = ["n", "raw", "group", "accent", "muted"].map((tn) =>
    `<marker id="am-${tn}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">` +
    `<path d="M0 0L10 5L0 10z" fill="${tone(tn === "n" ? null : tn)}"/></marker>`).join("");

  function rowSVG(c, f, top, rh, rule, cls) {
    const id = `${c.id}.${f.id}`, stroke = tone(c.tone);
    let out = `<g class="node${f.muted ? " is-muted" : ""}${cls}" data-node="${esc(id)}" tabindex="0" role="button" aria-label="${esc(f.label)}">`;
    if (cls) out += `<rect class="lift" x="${c.x}" y="${top}" width="${c.w}" height="${rh}" stroke="${stroke}"/>`;
    else if (rule) out += `<line class="rowrule" x1="${c.x}" y1="${top}" x2="${c.x + c.w}" y2="${top}" stroke="${stroke}"/>`;
    out += `<rect class="hit" x="${c.x + 1}" y="${top}" width="${c.w - 2}" height="${rh}"/>`;
    out += `<text class="fname" x="${c.x + K.PAD_X}" y="${top + rh / 2 + 4}" fill="${tone(f.tone)}"${f.strong ? ' font-weight="600"' : ""}>${esc(f.label)}</text>`;
    return out + `</g>`;
  }
  // a card's inside; draw() wraps it in a <g class="cardg">, and a drag redraws just that
  function cardSVG(c) {
    const stroke = tone(c.tone);
    let out = "";
    if (c.stage) out += `<text class="stage" x="${c.x}" y="${c.y - 12}">${esc(c.stage)}</text>`;
    out += `<rect class="cardshadow" x="${c.x + 1}" y="${c.y + 3}" width="${c.w}" height="${c.h}" rx="7"/>`;
    out += `<rect class="card" x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}" rx="7" stroke="${stroke}"/>`;
    out += `<text class="cname" x="${c.x + K.PAD_X}" y="${c.y + 23}" fill="${stroke}">${esc(c.name)}</text>`;
    if (c.sub) out += `<text class="csub" x="${c.x + K.PAD_X}" y="${c.y + 38}">${esc(c.sub)}</text>`;
    out += `<rect class="grip" data-card="${esc(c.id)}" x="${c.x}" y="${c.y}" width="${c.w}" height="${K.HEADER_H}" rx="7"/>`;
    out += `<line class="crule" x1="${c.x}" y1="${c.y + K.HEADER_H}" x2="${c.x + c.w}" y2="${c.y + K.HEADER_H}" stroke="${stroke}"/>`;
    // the space a viewer opened between rows reads as space: a pale band edged by rules
    const band = (y0, y1, last) => {
      if (y1 - y0 <= 0.5) return "";
      let g = "";
      if (last) {
        const r = Math.min(6, y1 - y0);
        g += `<path class="rowgap" d="M ${c.x + 0.8} ${y0} H ${c.x + c.w - 0.8} V ${y1 - 0.8 - r} q 0 ${r} ${-r} ${r} H ${c.x + 0.8 + r} q ${-r} 0 ${-r} ${-r} Z"/>`;
      } else g += `<rect class="rowgap" x="${c.x + 0.8}" y="${y0}" width="${c.w - 1.6}" height="${y1 - y0}"/>`;
      if (y0 > c.y + K.HEADER_H + 0.5) g += `<line class="rowrule" x1="${c.x}" y1="${y0}" x2="${c.x + c.w}" y2="${y0}" stroke="${stroke}"/>`;
      return g;
    };
    let held = "", prev = c.y + K.HEADER_H;
    c.fields.forEach((f, i) => {
      const rh = c.rowH[f.id], top = c.rowY[f.id] - rh / 2, gap = top - prev > 0.5;
      out += band(prev, top, false);
      prev = top + rh;
      if (lift && lift.c === c && lift.fid === f.id) {
        // the slot it will drop into stays open; the row itself is drawn last, on top
        out += `<rect class="slot" x="${c.x + 0.8}" y="${top}" width="${c.w - 1.6}" height="${rh}"/>`;
        if (i || gap) out += `<line class="rowrule" x1="${c.x}" y1="${top}" x2="${c.x + c.w}" y2="${top}" stroke="${stroke}"/>`;
        held = rowSVG(c, f, lift.y - rh / 2, rh, false, " lifted");
      } else out += rowSVG(c, f, top, rh, i > 0 || gap, "");
    });
    out += band(prev, c.y + c.h, true);
    // either edge resizes the card; a short bar shows where while the card is hovered
    for (const side of ["top", "bottom"]) {
      const y = side === "top" ? c.y : c.y + c.h;
      out += `<g class="rsz" data-card="${esc(c.id)}" data-side="${side}">` +
        `<rect class="rszhit" x="${c.x + 8}" y="${y - 4}" width="${c.w - 16}" height="8"/>` +
        `<rect class="rszbar" x="${c.x + c.w / 2 - 14}" y="${y - 1.5}" width="28" height="3" rx="1.5" stroke="${stroke}"/></g>`;
    }
    return out + held;
  }

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
    cards.forEach((c) => { out += `<g class="cardg" data-card="${esc(c.id)}">${cardSVG(c)}</g>`; });
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
    // ctrlKey is also what a trackpad pinch reports; ⌘+scroll zooms the other way round
    if (ev.ctrlKey) zoomAt(view.k * Math.exp(-ev.deltaY * 0.012), ev.clientX, ev.clientY);
    else if (ev.metaKey) zoomAt(view.k * Math.exp(ev.deltaY * 0.004), ev.clientX, ev.clientY);
    else { view.x -= ev.deltaX; view.y -= ev.deltaY; apply(); }
  }, { passive: false });
  // One pointer gesture, decided by where it starts: a card's header moves the card, a row
  // reorders its card (once the pointer has gone more up or down than sideways; sideways it
  // pans, as it always did), anything else pans. A press that never moves 4px is a click.
  let drag = null, frame = 0;
  stage.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    const rsz = ev.target.closest(".rsz"), grip = !rsz && ev.target.closest(".grip"), node = !rsz && ev.target.closest(".node");
    drag = { sx: ev.clientX, sy: ev.clientY, vx: view.x, vy: view.y, moved: false, target: ev.target,
      mode: rsz ? "resize" : grip ? "card" : node ? "row?" : "pan", grip: grip || rsz, node, side: rsz && rsz.dataset.side };
    stage.setPointerCapture(ev.pointerId);
  });
  stage.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.sx, dy = ev.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) > 4) {
      drag.moved = true;
      cancelAnimationFrame(camAnim);
      if (drag.mode === "row?") drag.mode = Math.abs(dy) >= Math.abs(dx) ? "row" : "pan";
      if (drag.mode === "pan") stage.classList.add("panning");
      else pickUp(drag);
    }
    if (!drag.moved) return;
    if (drag.mode === "pan") { view.x = drag.vx + dx; view.y = drag.vy + dy; apply(); return; }
    drag.dy = dy / view.k;            // canvas units: the card stays under the pointer at any zoom
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; if (drag && drag.c) follow(drag); });
  });
  const release = (click_) => () => {
    if (!drag) return;
    stage.classList.remove("panning");
    if (drag.c) putDown(drag);
    else if (!drag.moved && click_) click(drag.target);
    drag = null;
  };
  stage.addEventListener("pointerup", release(true));
  stage.addEventListener("pointercancel", release(false));
  function pickUp(d) {
    stage.classList.add(d.mode === "resize" ? "resizing" : "moving");
    if (d.mode === "card" || d.mode === "resize") d.c = byId[d.grip.dataset.card];
    else {
      const [c, fid] = split(d.node.dataset.node);
      d.c = c; d.fid = fid; d.order0 = c.fields.filter((f) => f.id !== fid);
      lift = { c, fid, y: c.rowY[fid] };
    }
    const c = d.c;
    d.y0 = c.y; d.h0 = c.h; d.rows0 = { ...c.rowY };
    d.dy = 0;
    d.ids = touching(c);
    // where each wire's ends sat when the move began: a label rides along with its end
    d.ends0 = new Map(d.ids.map((i) => [i, [routes[i].head[1], routes[i].tail[1]]]));
  }
  // one animation frame of a move: the card (or the row in hand, or the edge in hand) to the
  // pointer, the other rows into place, and every wire touching the card rebuilt; labels
  // only translate until the drop places them again
  function follow(d) {
    const c = d.c, top0 = (id) => d.rows0[id] - c.rowH[id] / 2 - d.y0;   // a row's offset when the move began
    if (d.mode === "card") {
      c.y = d.y0 + d.dy;
      for (const id in d.rows0) c.rowY[id] = d.rows0[id] + d.dy;
    } else if (d.mode === "resize") {
      // the bottom edge: rows stay, and are pushed up only as the card closes on them; the
      // top edge: the bottom stays, rows stay where they are on the canvas, pushed down as needed
      const min = packedH(c);
      if (d.side === "bottom") c.h = Math.max(min, Math.round(d.h0 + d.dy));
      else { const h = Math.max(min, Math.round(d.h0 - d.dy)); c.y = d.y0 + d.h0 - h; c.h = h; }
      place(c, settleRows(c, c.fields.map((f) => d.rows0[f.id] - c.rowH[f.id] / 2 - c.y)));
    } else {
      // the row in hand goes where the pointer is, kept inside the card body. Its place in
      // the order is the one that lets it sit nearest the pointer (in a packed card, the
      // nearest slot); among those, the one its centre is on the right side of every other
      // row's centre for, so passing a neighbour swaps the two; the others give way around it
      const f = fieldOf[c.id][d.fid], h = c.rowH[d.fid], rest = d.order0;
      const at = Math.min(Math.max(d.rows0[d.fid] - h / 2 - c.y + d.dy, K.HEADER_H), c.h - h), mid = at + h / 2;
      let best = null;
      for (let k = 0; k <= rest.length; k++) {
        c.fields = [...rest.slice(0, k), f, ...rest.slice(k)];
        const hs = c.fields.map((g) => c.rowH[g.id]);
        const lo = hs.slice(0, k).reduce((x, y) => x + y, K.HEADER_H), hi = c.h - hs.slice(k).reduce((x, y) => x + y, 0);
        const near = Math.min(Math.max(at, lo), hi), mine = Math.round(near);   // whole pixels
        const want = c.fields.map((g) => (g === f ? mine : top0(g.id)));
        const offs = settleRows(c, want, k);
        const side = rest.reduce((x, g, j) => { const m = top0(g.id) + c.rowH[g.id] / 2; return x + ((j < k ? m > mid : m < mid) ? 1 : 0); }, 0);
        const cost = [Math.abs(near - at), side, offs.reduce((x, o, i) => x + Math.abs(o - want[i]), 0)];
        let better = !best;
        for (let q = 0; !better && q < 3; q++) {
          if (cost[q] < best.cost[q] - 1e-9) better = true;
          else if (cost[q] > best.cost[q] + 1e-9) break;
        }
        if (better) best = { k, offs, cost };
      }
      c.fields = [...rest.slice(0, best.k), f, ...rest.slice(best.k)];
      place(c, best.offs);
      lift.y = c.y + at + h / 2;
    }
    content.querySelector(`.cardg[data-card="${CSS.escape(c.id)}"]`).innerHTML = cardSVG(c);
    for (const i of d.ids) {
      reroute(i);
      const R = routes[i], g = content.querySelector(`.edge[data-edge="${i}"]`), [h0, t0] = d.ends0.get(i);
      g.querySelectorAll("path").forEach((p) => p.setAttribute("d", R.d));
      g.querySelectorAll("text").forEach((el, k) => {
        const a = R.texts[k].anchor, ty = a === "start" ? R.head[1] - h0 : a === "end" ? R.tail[1] - t0 : 0;
        el.setAttribute("transform", `translate(0 ${ty})`);
      });
    }
    applySel();
  }
  // the drop: the row settles in its slot, the labels are placed again, the arrangement is
  // stored, and the page is redrawn and republished with the minimap's bounds
  function putDown(d) {
    cancelAnimationFrame(frame); frame = 0;
    stage.classList.remove("moving", "resizing");
    if (d.moved) follow(d);
    lift = null;
    settle([d.c]);
    remember(d.c);
    save();
    draw();
    publish();
    apply();
  }
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
  $("#zreset").onclick = resetLayout;
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
  restore();
  draw();
  fit(false);
})();
