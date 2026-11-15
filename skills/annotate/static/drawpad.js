// A full-screen drawing pad, made for a pen on a tablet.
//
// Generic on purpose: it knows nothing about annotate. A page opens it with
//
//   DrawPad.open({ title, strokes, onDone(blob, strokes), onCancel() })
//
// and gets back a PNG of what was drawn (cropped to the drawing, on white)
// plus the strokes, which it can hand back as `strokes` to edit the drawing
// again. It needs drawpad.css and nothing else.
//
// Input, by what touches the screen:
//   pen     draws; its eraser end (or barrel button) erases
//   finger  draws until a pen has been seen, then only moves the paper, so a
//           palm resting on the screen never leaves a mark
//   two fingers  pinch to zoom, drag to pan; landing the second finger drops
//           a stroke the first one had started
//   mouse   left draws, middle or Space+drag pans, the wheel pans, Ctrl or
//           ⌘ + wheel (a trackpad pinch) zooms
(function () {
  "use strict";

  const COLORS = [
    { name: "Black", value: "#1d1d1f" },
    { name: "Blue", value: "#1f6feb" },
    { name: "Red", value: "#d1242f" },
    { name: "Green", value: "#1a7f37" },
    { name: "Orange", value: "#d4740c" },
  ];
  const SIZES = [
    { name: "Thin", value: 2 },
    { name: "Medium", value: 4 },
    { name: "Thick", value: 9 },
  ];
  const MIN_ZOOM = 0.2;
  const MAX_ZOOM = 8;
  const EXPORT_MAX_PX = 2400;
  const EXPORT_PAD = 24;

  const ICONS = {
    pen: '<path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14.5 6.5l3 3"/>',
    marker: '<path d="M6 19l-2 2"/><path d="M9.5 9.5l5 5"/><path d="M8 18l-3-3 9.5-9.5a2.1 2.1 0 0 1 3 0l0 0a2.1 2.1 0 0 1 0 3z"/>',
    eraser: '<path d="M7 20h13"/><path d="M4.6 15.4l9.8-9.8a2 2 0 0 1 2.8 0l2.2 2.2a2 2 0 0 1 0 2.8L12 18H8z"/>',
    undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    clear: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
    fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    zoomIn: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5M8 11h6M11 8v6"/>',
    zoomOut: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5M8 11h6"/>',
  };

  function icon(name) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
  }

  // ── Geometry, kept pure so it can be tested without a browser ─────────────

  // Width of a pen segment at a pressure. A mouse or finger reports 0.5 (or
  // 0 with no buttons), which lands on the chosen size; a pen spans about a
  // third of it to one and a third times it.
  function widthAt(size, pressure, tool) {
    if (tool === "marker") return size * 3;
    const p = pressure > 0 ? pressure : 0.5;
    return size * (0.35 + 1.0 * p);
  }

  function bounds(strokes) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const s of strokes) {
      const half = widthAt(s.size, 1, s.tool) / 2;
      for (const [x, y] of s.points) {
        if (x - half < x0) x0 = x - half;
        if (y - half < y0) y0 = y - half;
        if (x + half > x1) x1 = x + half;
        if (y + half > y1) y1 = y + half;
      }
    }
    if (x0 === Infinity) return null;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  // Distance from point p to segment ab, for the stroke eraser.
  function segDist(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay;
    const len = dx * dx + dy * dy;
    let t = len ? ((px - ax) * dx + (py - ay) * dy) / len : 0;
    t = Math.max(0, Math.min(1, t));
    const cx = ax + t * dx, cy = ay + t * dy;
    return Math.hypot(px - cx, py - cy);
  }

  function hits(stroke, x, y, radius) {
    const pts = stroke.points;
    const reach = radius + widthAt(stroke.size, 1, stroke.tool) / 2;
    if (pts.length === 1) return Math.hypot(x - pts[0][0], y - pts[0][1]) <= reach;
    for (let i = 1; i < pts.length; i++) {
      if (segDist(x, y, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]) <= reach) return true;
    }
    return false;
  }

  // Zoom about a screen point, so what is under the fingers stays there.
  function zoomAbout(view, sx, sy, factor) {
    const scale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.scale * factor));
    const k = scale / view.scale;
    return { scale, x: sx - (sx - view.x) * k, y: sy - (sy - view.y) * k };
  }

  // The view that shows box `b` whole in a w × h screen, never above 1:1.
  function fitView(b, w, h, margin) {
    if (!b) return { scale: 1, x: 0, y: 0 };
    const scale = Math.max(MIN_ZOOM, Math.min(1, (w - 2 * margin) / b.w, (h - 2 * margin) / b.h));
    return { scale, x: w / 2 - (b.x + b.w / 2) * scale, y: h / 2 - (b.y + b.h / 2) * scale };
  }

  // ── Painting ──────────────────────────────────────────────────────────────

  function paintStroke(ctx, s) {
    const pts = s.points;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = s.color;
    ctx.fillStyle = s.color;
    if (s.tool === "marker") {
      ctx.save();
      ctx.globalAlpha = 0.32;
      ctx.lineWidth = widthAt(s.size, 1, "marker");
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      if (pts.length === 1) ctx.lineTo(pts[0][0] + 0.01, pts[0][1]);
      ctx.stroke();
      ctx.restore();
      return;
    }
    // A pen line is filled as one shape: a disc at every point and a
    // four-sided piece between each pair, all in one path, all wound the same
    // way, filled once. Stroking each piece on its own put a darker tick
    // wherever two pieces' soft edges overlapped.
    ctx.beginPath();
    for (let i = 0; i < pts.length; i++) {
      addDisc(ctx, pts[i], widthAt(s.size, pts[i][2], s.tool) / 2);
      if (i > 0) addPiece(ctx, s, i);
    }
    ctx.fill("nonzero");
  }

  function addDisc(ctx, p, r) {
    ctx.moveTo(p[0] + r, p[1]);
    ctx.arc(p[0], p[1], r, 0, Math.PI * 2, false);
  }

  // The piece between point i-1 and point i, as wide as each end's pressure.
  // Its corners go round the same way as addDisc's circles (clockwise on the
  // screen), so where they overlap the nonzero fill keeps them solid.
  function addPiece(ctx, s, i) {
    const a = s.points[i - 1], b = s.points[i];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    if (!len) return;
    const nx = -dy / len, ny = dx / len;
    const ra = widthAt(s.size, a[2], s.tool) / 2;
    const rb = widthAt(s.size, b[2], s.tool) / 2;
    ctx.moveTo(a[0] - nx * ra, a[1] - ny * ra);
    ctx.lineTo(b[0] - nx * rb, b[1] - ny * rb);
    ctx.lineTo(b[0] + nx * rb, b[1] + ny * rb);
    ctx.lineTo(a[0] + nx * ra, a[1] + ny * ra);
    ctx.closePath();
  }

  // The newest piece of a line being drawn, painted at once so the pen feels
  // attached. Its soft edges may overlap the last piece's; the line is
  // painted again whole, without seams, when the pen lifts.
  function paintSegment(ctx, s, i) {
    ctx.fillStyle = s.color;
    ctx.beginPath();
    addDisc(ctx, s.points[i], widthAt(s.size, s.points[i][2], s.tool) / 2);
    addPiece(ctx, s, i);
    ctx.fill("nonzero");
  }

  function exportPng(strokes) {
    const b = bounds(strokes);
    if (!b) return Promise.resolve(null);
    const w = b.w + EXPORT_PAD * 2, h = b.h + EXPORT_PAD * 2;
    const k = Math.min(2, EXPORT_MAX_PX / Math.max(w, h));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w * k));
    c.height = Math.max(1, Math.round(h * k));
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.setTransform(k, 0, 0, k, (EXPORT_PAD - b.x) * k, (EXPORT_PAD - b.y) * k);
    for (const s of strokes) paintStroke(ctx, s);
    return new Promise((resolve) => c.toBlob(resolve, "image/png"));
  }

  // ── The pad ───────────────────────────────────────────────────────────────

  let current = null;

  function open(opts) {
    if (current) current.close(false);
    current = new Pad(opts || {});
    return current;
  }

  function Pad(opts) {
    const pad = this;
    const strokes = (opts.strokes || []).map((s) => ({ ...s, points: s.points.map((p) => p.slice()) }));
    const undoStack = [];
    const redoStack = [];
    let tool = "pen";
    let color = COLORS[0].value;
    let size = SIZES[1].value;
    let view = { scale: 1, x: 0, y: 0 };
    let penSeen = false;
    let spaceDown = false;
    const pointers = new Map(); // pointerId -> {x, y, type}
    let drawing = null;         // {id, stroke} while a stroke is being drawn
    let erasing = null;         // {id, before: the list when it began}
    let panning = null;         // {id, x, y} for a one-pointer pan
    let pinch = null;           // {dist, cx, cy} for a two-finger gesture

    const root = document.createElement("div");
    root.className = "drawpad";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", opts.title || "Drawing");
    root.innerHTML = `
      <div class="dp-bar">
        <div class="dp-group dp-tools" role="radiogroup" aria-label="Tool">
          <button type="button" class="dp-btn" data-tool="pen" role="radio" title="Pen" aria-label="Pen">${icon("pen")}</button>
          <button type="button" class="dp-btn" data-tool="marker" role="radio" title="Marker" aria-label="Marker">${icon("marker")}</button>
          <button type="button" class="dp-btn" data-tool="eraser" role="radio" title="Eraser: removes a whole line" aria-label="Eraser">${icon("eraser")}</button>
        </div>
        <div class="dp-group dp-colors" role="radiogroup" aria-label="Colour">
          ${COLORS.map((c) => `<button type="button" class="dp-swatch" role="radio" data-color="${c.value}" title="${c.name}" aria-label="${c.name}" style="--sw:${c.value}"></button>`).join("")}
        </div>
        <div class="dp-group dp-sizes" role="radiogroup" aria-label="Line width">
          ${SIZES.map((s) => `<button type="button" class="dp-btn dp-size" role="radio" data-size="${s.value}" title="${s.name}" aria-label="${s.name}"><span style="--d:${Math.max(3, s.value * 1.6)}px"></span></button>`).join("")}
        </div>
        <div class="dp-group">
          <button type="button" class="dp-btn" data-act="undo" title="Undo" aria-label="Undo">${icon("undo")}</button>
          <button type="button" class="dp-btn" data-act="redo" title="Redo" aria-label="Redo">${icon("redo")}</button>
          <button type="button" class="dp-btn" data-act="clear" title="Clear the page" aria-label="Clear the page">${icon("clear")}</button>
        </div>
        <div class="dp-group dp-zoom">
          <button type="button" class="dp-btn" data-act="zoom-out" title="Zoom out" aria-label="Zoom out">${icon("zoomOut")}</button>
          <button type="button" class="dp-btn dp-zoom-label" data-act="fit" title="Show the whole drawing" aria-label="Show the whole drawing"></button>
          <button type="button" class="dp-btn" data-act="zoom-in" title="Zoom in" aria-label="Zoom in">${icon("zoomIn")}</button>
        </div>
        <div class="dp-spacer"></div>
        <div class="dp-group dp-end">
          <button type="button" class="dp-text-btn" data-act="cancel">Cancel</button>
          <button type="button" class="dp-text-btn dp-primary" data-act="done">${opts.doneLabel || "Attach drawing"}</button>
        </div>
      </div>
      <div class="dp-stage">
        <canvas class="dp-base"></canvas>
        <canvas class="dp-live"></canvas>
        <div class="dp-hint">${opts.hint || "Draw with the pen. Two fingers move and zoom the page."}</div>
      </div>`;

    const stage = root.querySelector(".dp-stage");
    const base = root.querySelector(".dp-base");
    const live = root.querySelector(".dp-live");
    const hint = root.querySelector(".dp-hint");
    const bctx = base.getContext("2d");
    const lctx = live.getContext("2d");
    const zoomLabel = root.querySelector(".dp-zoom-label");
    const doneBtn = root.querySelector('[data-act="done"]');
    let dpr = 1, sw = 0, sh = 0;

    // ── layout and paint ──
    function resize() {
      const r = stage.getBoundingClientRect();
      dpr = window.devicePixelRatio || 1;
      sw = r.width; sh = r.height;
      for (const c of [base, live]) {
        c.width = Math.max(1, Math.round(sw * dpr));
        c.height = Math.max(1, Math.round(sh * dpr));
      }
      paintBase();
      paintLive();
    }

    function withView(ctx) {
      ctx.setTransform(dpr * view.scale, 0, 0, dpr * view.scale, dpr * view.x, dpr * view.y);
    }

    function paintGrid() {
      // Dots every 24 units, so the reader can feel the zoom; never exported.
      const step = 24 * view.scale;
      if (step < 8) return;
      bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      bctx.fillStyle = "rgba(29, 29, 31, 0.13)";
      const ox = ((view.x % step) + step) % step;
      const oy = ((view.y % step) + step) % step;
      const r = Math.min(1.4, 0.6 + view.scale * 0.4);
      for (let x = ox; x < sw; x += step) {
        for (let y = oy; y < sh; y += step) {
          bctx.beginPath();
          bctx.arc(x, y, r, 0, Math.PI * 2);
          bctx.fill();
        }
      }
    }

    function paintBase() {
      bctx.setTransform(1, 0, 0, 1, 0, 0);
      bctx.fillStyle = "#ffffff";
      bctx.fillRect(0, 0, base.width, base.height);
      paintGrid();
      withView(bctx);
      for (const s of strokes) paintStroke(bctx, s);
      sync();
    }

    function paintLive() {
      lctx.setTransform(1, 0, 0, 1, 0, 0);
      lctx.clearRect(0, 0, live.width, live.height);
      if (!drawing) return;
      withView(lctx);
      paintStroke(lctx, drawing.stroke);
    }

    let frame = 0;
    function schedule(fn) {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; fn(); });
    }

    function sync() {
      const empty = strokes.length === 0;
      doneBtn.disabled = empty;
      root.querySelector('[data-act="undo"]').disabled = undoStack.length === 0;
      root.querySelector('[data-act="redo"]').disabled = redoStack.length === 0;
      root.querySelector('[data-act="clear"]').disabled = empty;
      zoomLabel.textContent = Math.round(view.scale * 100) + "%";
      hint.hidden = !empty;
      for (const b of root.querySelectorAll("[data-tool]")) b.setAttribute("aria-checked", String(b.dataset.tool === tool));
      for (const b of root.querySelectorAll("[data-color]")) b.setAttribute("aria-checked", String(b.dataset.color === color));
      for (const b of root.querySelectorAll("[data-size]")) b.setAttribute("aria-checked", String(Number(b.dataset.size) === size));
      root.dataset.tool = tool;
    }

    function setView(v) {
      view = v;
      schedule(() => { paintBase(); paintLive(); });
    }

    function toWorld(sx, sy) {
      return [(sx - view.x) / view.scale, (sy - view.y) / view.scale];
    }

    function local(ev) {
      const r = stage.getBoundingClientRect();
      return [ev.clientX - r.left, ev.clientY - r.top];
    }

    // ── history ──
    function record(action) {
      undoStack.push(action);
      redoStack.length = 0;
    }

    // An erase or a clear swaps the whole list; undo puts the old one back,
    // so every line returns to the place it had in the drawing order.
    function apply(action, forward) {
      if (action.type === "add") {
        if (forward) strokes.push(action.stroke);
        else strokes.splice(strokes.lastIndexOf(action.stroke), 1);
      } else {
        strokes.splice(0, strokes.length, ...(forward ? action.after : action.before));
      }
    }

    function undo() {
      const a = undoStack.pop();
      if (!a) return;
      apply(a, false);
      redoStack.push(a);
      paintBase();
    }

    function redo() {
      const a = redoStack.pop();
      if (!a) return;
      apply(a, true);
      undoStack.push(a);
      paintBase();
    }

    function clearAll() {
      if (!strokes.length) return;
      record({ type: "replace", before: strokes.slice(), after: [] });
      strokes.length = 0;
      paintBase();
    }

    // ── strokes ──
    function startStroke(ev, sx, sy) {
      const [x, y] = toWorld(sx, sy);
      const useTool = (ev.buttons & 32) ? "eraser" : tool;
      if (useTool === "eraser") {
        erasing = { id: ev.pointerId, before: strokes.slice() };
        eraseAt(x, y);
        return;
      }
      drawing = {
        id: ev.pointerId,
        stroke: { tool: useTool, color, size, points: [[x, y, ev.pressure]] },
      };
      schedule(paintLive);
    }

    function extendStroke(ev) {
      const events = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [];
      const list = events.length ? events : [ev];
      const r = stage.getBoundingClientRect();
      for (const e of list) {
        const [x, y] = toWorld(e.clientX - r.left, e.clientY - r.top);
        if (erasing) { eraseAt(x, y); continue; }
        const pts = drawing.stroke.points;
        const last = pts[pts.length - 1];
        // Drop points closer than a third of a screen pixel: they add weight
        // and no shape.
        if (Math.hypot(x - last[0], y - last[1]) * view.scale < 0.35) continue;
        pts.push([x, y, e.pressure]);
        if (drawing.stroke.tool === "pen") {
          // Paint the new segment straight away; the pen should feel attached.
          withView(lctx);
          paintSegment(lctx, drawing.stroke, pts.length - 1);
        }
      }
      if (drawing && drawing.stroke.tool !== "pen") schedule(paintLive);
    }

    function endStroke(commit) {
      if (erasing) {
        if (strokes.length !== erasing.before.length) {
          record({ type: "replace", before: erasing.before, after: strokes.slice() });
        }
        erasing = null;
        sync();
        return;
      }
      if (!drawing) return;
      const s = drawing.stroke;
      drawing = null;
      if (commit) {
        strokes.push(s);
        record({ type: "add", stroke: s });
      }
      paintBase();
      paintLive();
    }

    function eraseAt(x, y) {
      const radius = 10 / view.scale;
      let changed = false;
      for (let i = strokes.length - 1; i >= 0; i--) {
        if (hits(strokes[i], x, y, radius)) { strokes.splice(i, 1); changed = true; }
      }
      if (changed) paintBase();
    }

    // ── pointers ──
    function onDown(ev) {
      if (ev.pointerType === "pen") penSeen = true;
      const [sx, sy] = local(ev);
      stage.setPointerCapture(ev.pointerId);
      pointers.set(ev.pointerId, { x: sx, y: sy, type: ev.pointerType });
      ev.preventDefault();

      if (ev.pointerType === "touch") {
        const touches = [...pointers.values()].filter((p) => p.type === "touch");
        if (touches.length >= 2) {
          // A second finger: any stroke a finger started was the start of a
          // gesture, not a line.
          if (drawing && pointers.get(drawing.id)?.type === "touch") { drawing = null; paintLive(); }
          if (erasing && pointers.get(erasing.id)?.type === "touch") endStroke(false);
          panning = null;
          pinch = pinchState(touches);
          return;
        }
        if (penSeen) { panning = { id: ev.pointerId, x: sx, y: sy }; return; }
      }
      if (ev.pointerType === "mouse" && (ev.button === 1 || spaceDown)) {
        panning = { id: ev.pointerId, x: sx, y: sy };
        return;
      }
      if (ev.pointerType === "mouse" && ev.button !== 0) return;
      if (drawing || erasing) return;
      startStroke(ev, sx, sy);
    }

    function pinchState(touches) {
      const [a, b] = touches;
      return {
        dist: Math.hypot(b.x - a.x, b.y - a.y) || 1,
        cx: (a.x + b.x) / 2,
        cy: (a.y + b.y) / 2,
      };
    }

    function onMove(ev) {
      const p = pointers.get(ev.pointerId);
      if (!p) return;
      const [sx, sy] = local(ev);
      p.x = sx; p.y = sy;
      if (pinch && p.type === "touch") {
        const touches = [...pointers.values()].filter((q) => q.type === "touch");
        if (touches.length < 2) return;
        const next = pinchState(touches);
        let v = { ...view, x: view.x + (next.cx - pinch.cx), y: view.y + (next.cy - pinch.cy) };
        v = zoomAbout(v, next.cx, next.cy, next.dist / pinch.dist);
        pinch = next;
        setView(v);
        return;
      }
      if (panning && panning.id === ev.pointerId) {
        setView({ ...view, x: view.x + (sx - panning.x), y: view.y + (sy - panning.y) });
        panning.x = sx; panning.y = sy;
        return;
      }
      if ((drawing && drawing.id === ev.pointerId) || (erasing && erasing.id === ev.pointerId)) extendStroke(ev);
    }

    function onUp(ev) {
      const p = pointers.get(ev.pointerId);
      pointers.delete(ev.pointerId);
      if (!p) return;
      if (p.type === "touch" && pinch) {
        const touches = [...pointers.values()].filter((q) => q.type === "touch");
        if (touches.length >= 2) pinch = pinchState(touches);
        else pinch = null;
        return;
      }
      if (panning && panning.id === ev.pointerId) { panning = null; return; }
      if ((drawing && drawing.id === ev.pointerId) || (erasing && erasing.id === ev.pointerId)) {
        endStroke(ev.type !== "pointercancel");
      }
    }

    function onWheel(ev) {
      ev.preventDefault();
      const [sx, sy] = local(ev);
      if (ev.ctrlKey || ev.metaKey) {
        setView(zoomAbout(view, sx, sy, Math.exp(-ev.deltaY * 0.01)));
      } else {
        setView({ ...view, x: view.x - ev.deltaX, y: view.y - ev.deltaY });
      }
    }

    function zoomStep(factor) {
      setView(zoomAbout(view, sw / 2, sh / 2, factor));
    }

    function fit() {
      const b = bounds(strokes);
      setView(b ? fitView(b, sw, sh, 32) : { scale: 1, x: 0, y: 0 });
    }

    // ── keys ──
    function onKey(ev) {
      if (ev.key === " " && ev.type === "keydown") {
        if (ev.target instanceof HTMLButtonElement) return;
        spaceDown = true; root.classList.add("dp-grab"); ev.preventDefault(); return;
      }
      if (ev.key === " " && ev.type === "keyup") { spaceDown = false; root.classList.remove("dp-grab"); return; }
      if (ev.type !== "keydown") return;
      const mod = ev.metaKey || ev.ctrlKey;
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopImmediatePropagation(); cancel(); return; }
      if (mod && ev.key.toLowerCase() === "z") {
        ev.preventDefault(); ev.stopImmediatePropagation();
        if (ev.shiftKey) redo(); else undo();
        return;
      }
      if (mod && ev.key.toLowerCase() === "y") { ev.preventDefault(); ev.stopImmediatePropagation(); redo(); return; }
      if (mod && ev.key === "Enter") { ev.preventDefault(); ev.stopImmediatePropagation(); done(); return; }
      // Everything else typed while the pad is up stays with the pad, so the
      // page's single-letter shortcuts do not fire behind it.
      ev.stopImmediatePropagation();
    }

    // ── closing ──
    let closed = false;
    function teardown() {
      closed = true;
      window.removeEventListener("resize", resize);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("keyup", onKey, true);
      root.remove();
      document.documentElement.classList.remove("drawpad-open");
      if (current === pad) current = null;
      if (opts.returnFocus && opts.returnFocus.isConnected) {
        try { opts.returnFocus.focus({ preventScroll: true }); } catch (_) {}
      }
    }

    function cancel() {
      if (closed) return;
      const dirty = undoStack.length > 0;
      if (dirty && !window.confirm("Throw this drawing away?")) return;
      teardown();
      if (opts.onCancel) opts.onCancel();
    }

    async function done() {
      if (closed || !strokes.length) return;
      doneBtn.disabled = true;
      const blob = await exportPng(strokes);
      const kept = strokes.map((s) => ({ ...s, points: s.points.map((p) => p.slice()) }));
      teardown();
      if (opts.onDone && blob) opts.onDone(blob, kept);
    }

    this.close = (notify) => { if (!closed) { teardown(); if (notify && opts.onCancel) opts.onCancel(); } };

    // ── wiring ──
    root.addEventListener("click", (ev) => {
      const b = ev.target instanceof Element ? ev.target.closest("button") : null;
      if (!b || b.disabled) return;
      if (b.dataset.tool) { tool = b.dataset.tool; sync(); return; }
      if (b.dataset.color) { color = b.dataset.color; if (tool === "eraser") tool = "pen"; sync(); return; }
      if (b.dataset.size) { size = Number(b.dataset.size); if (tool === "eraser") tool = "pen"; sync(); return; }
      switch (b.dataset.act) {
        case "undo": undo(); break;
        case "redo": redo(); break;
        case "clear": clearAll(); break;
        case "zoom-in": zoomStep(1.25); break;
        case "zoom-out": zoomStep(0.8); break;
        case "fit": fit(); break;
        case "cancel": cancel(); break;
        case "done": done(); break;
      }
    });
    // Nothing on the pad reaches the page underneath: a page that closes a
    // menu or a sheet on a press outside it would otherwise take it as one.
    for (const t of ["pointerdown", "mousedown", "touchstart", "contextmenu"]) {
      root.addEventListener(t, (ev) => { ev.stopPropagation(); if (t === "contextmenu") ev.preventDefault(); });
    }
    stage.addEventListener("pointerdown", onDown);
    stage.addEventListener("pointermove", onMove);
    stage.addEventListener("pointerup", onUp);
    stage.addEventListener("pointercancel", onUp);
    stage.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", resize);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("keyup", onKey, true);

    document.documentElement.classList.add("drawpad-open");
    document.body.appendChild(root);
    resize();
    if (strokes.length) fit();
    sync();
    // Focus goes to the pad itself, so its keys work and Tab reaches the
    // tools, without a focus ring on the pen button at first sight.
    root.tabIndex = -1;
    root.focus({ preventScroll: true });
  }

  window.DrawPad = {
    open,
    get isOpen() { return !!current; },
    // For tests: the pure parts.
    _geometry: { widthAt, bounds, hits, segDist, zoomAbout, fitView },
  };
})();
