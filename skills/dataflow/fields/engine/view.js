  // ── wiring the layout into the page ──
  // computeLayout numbers edges by their two ends; the page keeps spec order, so the
  // routes are put back in the order of SPEC.edges before anything draws them.
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
    window.__layout = L.layout;
    window.__layoutReport = L.report;
    window.__layoutTiming = L.T;
  }
  window.__measure = (layout) => measure(SPEC, layout);
  window.__fieldEngine = { networkSimplex, computeLayout };

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
      out += `<text class="cname" x="${c.x + K.PAD_X}" y="${c.y + 23}" fill="${stroke}">${esc(c.name)}</text>`;
      if (c.sub) out += `<text class="csub" x="${c.x + K.PAD_X}" y="${c.y + 38}">${esc(c.sub)}</text>`;
      out += `<line class="crule" x1="${c.x}" y1="${c.y + K.HEADER_H}" x2="${c.x + c.w}" y2="${c.y + K.HEADER_H}" stroke="${stroke}"/>`;
      c.fields.forEach((f, i) => {
        const rh = c.rowH[f.id], mid = c.rowY[f.id], top = mid - rh / 2, id = `${c.id}.${f.id}`;
        out += `<g class="node${f.muted ? " is-muted" : ""}" data-node="${esc(id)}" tabindex="0" role="button" aria-label="${esc(f.label)}">`;
        if (i) out += `<line class="rowrule" x1="${c.x}" y1="${top}" x2="${c.x + c.w}" y2="${top}" stroke="${stroke}"/>`;
        out += `<rect class="hit" x="${c.x + 1}" y="${top}" width="${c.w - 2}" height="${rh}"/>`;
        out += `<text class="fname" x="${c.x + K.PAD_X}" y="${mid + 4}" fill="${tone(f.tone)}"${f.strong ? ' font-weight="600"' : ""}>${esc(f.label)}</text>`;
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
    // ctrlKey is also what a trackpad pinch reports; ⌘+scroll zooms the other way round
    if (ev.ctrlKey) zoomAt(view.k * Math.exp(-ev.deltaY * 0.012), ev.clientX, ev.clientY);
    else if (ev.metaKey) zoomAt(view.k * Math.exp(ev.deltaY * 0.004), ev.clientX, ev.clientY);
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
