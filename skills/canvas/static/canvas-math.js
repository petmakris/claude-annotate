// The canvas viewer's maths: where the one surface sits, how far it is zoomed,
// where every board goes and which images to load. Pure functions, run by the
// page and by the tests under node (skills/canvas/tests/test_canvas_math.py).
// Lifted from lomem's journey canvas (canvas-view.ts, comment-point.ts), with
// the grid layout, the first view and the thumbnail choice added.
//
// A view is { x, y, z }: the surface's point (wx, wy) is drawn on screen at
// (x + wx * z, y + wy * z), relative to the canvas's top-left corner.
var CanvasMath = (function () {
  // Figma's range is 2 % to 400 %. Fit all may go lower when the surface needs it.
  var MIN_ZOOM = 0.02, MAX_ZOOM = 4;

  function clampZoom(z, min, max) {
    return Math.min(max, Math.max(min, z));
  }

  // The view at zoom z that keeps the surface point under (px, py) where it is.
  function zoomAt(view, px, py, z) {
    var wx = (px - view.x) / view.z, wy = (py - view.y) / view.z;
    return { x: px - wx * z, y: py - wy * z, z: z };
  }

  // Two fingers: the view that keeps the surface point first under their
  // midpoint (m0x, m0y) under their midpoint now, scaled by how far they spread.
  function pinchView(start, m0x, m0y, d0, mx, my, d, min, max) {
    var z = clampZoom(start.z * (d0 > 0 ? d / d0 : 1), min, max);
    var wx = (m0x - start.x) / start.z, wy = (m0y - start.y) / start.z;
    return { x: mx - wx * z, y: my - wy * z, z: z };
  }

  // One wheel event, as Chromium reports it, turned into a pan (dx, dy, in
  // screen pixels) or a zoom factor. A trackpad pinch arrives as a wheel with
  // ctrlKey; Ctrl or Cmd with a mouse wheel zooms too. Shift turns a mouse
  // wheel sideways. Lines and pages are scaled to pixels.
  function wheelAction(deltaX, deltaY, deltaMode, ctrl, shift, pageH) {
    var unit = deltaMode === 1 ? 16 : deltaMode === 2 ? pageH : 1;
    var dx = deltaX * unit, dy = deltaY * unit;
    if (ctrl) {
      // A pinch sends small deltas many times a second; a mouse notch sends
      // 100 at once. Capping one event keeps a notch to about 1.5x.
      var capped = Math.max(-40, Math.min(40, dy));
      return { dx: 0, dy: 0, factor: Math.exp(-capped * 0.01) };
    }
    if (shift && dx === 0) { dx = dy; dy = 0; }
    return { dx: dx, dy: dy, factor: 1 };
  }

  // Whether a press has moved far enough to be a drag. A drag never opens a
  // board; a finger is allowed more wobble than a mouse.
  function isDrag(dx, dy, pointerType) {
    var slop = pointerType === 'touch' ? 10 : 4;
    return dx * dx + dy * dy > slop * slop;
  }

  // The view that shows the box (bx, by, bw, bh) whole and centred in a
  // vw × vh canvas, with pad screen pixels round it, no larger than max zoom.
  function fitView(bx, by, bw, bh, vw, vh, pad, max) {
    var availW = Math.max(1, vw - pad * 2), availH = Math.max(1, vh - pad * 2);
    var z = Math.min(max, availW / Math.max(1, bw), availH / Math.max(1, bh));
    return { x: (vw - bw * z) / 2 - bx * z, y: (vh - bh * z) / 2 - by * z, z: z };
  }

  // The point (px, py) as a fraction of the box, each rounded to 1/10000;
  // null when it falls outside the box.
  function pointInBox(px, py, left, top, width, height) {
    if (!(width > 0) || !(height > 0)) return null;
    var fx = (px - left) / width, fy = (py - top) / height;
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null;
    return { fx: Math.round(fx * 10000) / 10000, fy: Math.round(fy * 10000) / 10000 };
  }

  // Where the fraction (fx, fy) of a shot lies on screen, for the shot's box
  // (bx, by, bw, bh) on the surface and the view.
  function pinOnScreen(view, bx, by, bw, bh, fx, fy) {
    return { x: view.x + (bx + fx * bw) * view.z, y: view.y + (by + fy * bh) * view.z };
  }

  // A shot's frame on the surface: drawn `height` tall at its viewport's
  // aspect (a full-page shot shows its first screen; the rest is cropped), or
  // at its own aspect when it has no viewport, never taller than 2.4 widths.
  function frameOf(shot, height) {
    var vw = shot.viewport ? shot.viewport.width : shot.width;
    var vh = shot.viewport ? shot.viewport.height : Math.min(shot.height, shot.width * 2.4);
    var w = height * vw / vh;
    // The whole shot drawn at the frame's scale: how far down it runs.
    return { w: w, h: height, fullH: w * shot.height / shot.width };
  }

  // Every board at one size, in a grid under its group's title: boards wrap
  // into lines `lineW` wide. `shown(label)` says which shots are on show.
  function layoutAt(groups, shown, o, lineW) {
    var out = [], y = 0, worldW = 0;
    for (var g = 0; g < groups.length; g++) {
      var grp = groups[g], gy = y, x = 0, lineTop = y, boards = [], lineH = 0, gw = 0;
      for (var b = 0; b < grp.boards.length; b++) {
        var bd = grp.boards[b], shots = [], sx = 0;
        for (var s = 0; s < bd.shots.length; s++) {
          if (!shown(bd.shots[s].label) && bd.shots.length > 1) continue;
          var f = frameOf(bd.shots[s], o.height);
          if (shots.length) sx += o.shotGap;
          shots.push({ i: s, x: sx, w: f.w, h: f.h, fullH: f.fullH });
          sx += f.w;
        }
        if (!shots.length) continue;
        var bw = sx, bh = o.height + o.captionH;
        if (x > 0 && x + bw > lineW) { x = 0; lineTop += lineH + o.rowGap; lineH = 0; }
        boards.push({ i: b, x: x, y: lineTop, w: bw, h: o.height, shots: shots });
        x += bw + o.boardGap;
        if (bh > lineH) lineH = bh;
        if (x - o.boardGap > gw) gw = x - o.boardGap;
      }
      var gh = boards.length ? lineTop + lineH - gy : o.emptyH;
      out.push({ i: g, x: 0, y: gy, w: Math.max(gw, o.emptyW), h: gh, boards: boards });
      if (gw > worldW) worldW = gw;
      y = gy + gh + o.groupGap;
    }
    return { groups: out, w: Math.max(worldW, o.emptyW), h: Math.max(0, y - o.groupGap) };
  }

  // The groups, stacked by layoutAt, put into k columns side by side in
  // reading order: down the first column, then the next, each about the same
  // height.
  function pack(l, k, o) {
    var total = 0, i;
    for (i = 0; i < l.groups.length; i++) total += l.groups[i].h + o.groupGap;
    var target = total / k, colW = l.w + o.groupGap * 1.5, col = 0, y = 0, h = 0, w = 0, groups = [];
    for (i = 0; i < l.groups.length; i++) {
      var g = l.groups[i];
      if (y > 0 && col < k - 1 && y + (g.h + o.groupGap) / 2 > target) { col++; y = 0; }
      var dx = col * colW - g.x, dy = y - g.y, boards = [];
      for (var b = 0; b < g.boards.length; b++) {
        var bd = g.boards[b];
        boards.push({ i: bd.i, x: bd.x + dx, y: bd.y + dy, w: bd.w, h: bd.h, shots: bd.shots });
      }
      groups.push({ i: g.i, x: g.x + dx, y: g.y + dy, w: g.w, h: g.h, boards: boards });
      y += g.h + o.groupGap;
      if (y - o.groupGap > h) h = y - o.groupGap;
      if (col * colW + g.w > w) w = col * colW + g.w;
    }
    return { groups: groups, w: w, h: h };
  }

  // The layout whose surface is closest to as wide as it is tall: lines of 4
  // to 6 typical boards (more makes each board a speck when a group fills the
  // window's width), the groups in 1 to 4 columns.
  function layoutCanvas(groups, shown, opts) {
    var o = {
      height: opts.height, shotGap: opts.shotGap || 16, boardGap: opts.boardGap || 64,
      rowGap: opts.rowGap || 72, groupGap: opts.groupGap || 200, captionH: opts.captionH || 0,
      emptyW: opts.emptyW || 600, emptyH: opts.emptyH || 120
    };
    var widths = [], g, b;
    for (g = 0; g < groups.length; g++) {
      for (b = 0; b < groups[g].boards.length; b++) {
        var bd = groups[g].boards[b], w = 0, n = 0;
        for (var s = 0; s < bd.shots.length; s++) {
          if (!shown(bd.shots[s].label) && bd.shots.length > 1) continue;
          w += frameOf(bd.shots[s], o.height).w + (n++ ? o.shotGap : 0);
        }
        if (n) widths.push(w);
      }
    }
    if (!widths.length) return layoutAt(groups, shown, o, o.emptyW);
    widths.sort(function (p, q) { return p - q; });
    var typical = widths[Math.floor(widths.length / 2)] + o.boardGap, widest = widths[widths.length - 1];
    var best = null, bestScore = Infinity;
    for (var cols = 4; cols <= 6; cols++) {
      var stacked = layoutAt(groups, shown, o, Math.max(widest, cols * typical - o.boardGap + 1));
      for (var k = 1; k <= Math.min(4, groups.length); k++) {
        var l = k === 1 ? stacked : pack(stacked, k, o);
        // Fewer boards per line first, then fewer columns, when as square.
        var score = Math.abs(Math.log((l.w || 1) / (l.h || 1))) + cols * 0.01 + k * 0.01;
        if (score < bestScore) { best = l; bestScore = score; }
      }
    }
    return best;
  }

  // The first view: the first group fills the window's width, but never so
  // small that a board is a speck. On a narrow window (a phone) its first
  // board fills the width instead. `top` screen pixels are left for the
  // group's title, above the 72 surface pixels of its panel's edge.
  function firstView(layout, vw, vh, pad, top) {
    var g = layout.groups[0];
    if (!g) return { x: pad, y: top, z: 1 };
    var avail = Math.max(1, vw - pad * 2);
    var z = avail / Math.max(1, g.w);
    var first = g.boards[0];
    if (first) z = Math.max(z, vw < 600 ? avail / first.w : Math.min(0.35, avail / first.w));
    z = clampZoom(z, MIN_ZOOM, 1);
    return { x: pad - g.x * z, y: top + (72 - g.y) * z, z: z };
  }

  // Which thumbnail to draw a frame `frameW` wide at zoom z on a screen of
  // pixel ratio dpr: 1 (drawn size) while it is enough, else 2 (twice).
  function thumbTier(z, dpr) {
    return z * (dpr || 1) <= 1.05 ? 1 : 2;
  }

  // Whether the surface box (bx, by, bw, bh) is on screen, or within `margin`
  // of a window's size of it, at the view.
  function inView(view, bx, by, bw, bh, vw, vh, margin) {
    var sx = view.x + bx * view.z, sy = view.y + by * view.z;
    var sw = bw * view.z, sh = bh * view.z, mx = vw * margin, my = vh * margin;
    return sx < vw + mx && sx + sw > -mx && sy < vh + my && sy + sh > -my;
  }

  return {
    MIN_ZOOM: MIN_ZOOM, MAX_ZOOM: MAX_ZOOM, clampZoom: clampZoom, zoomAt: zoomAt, pinchView: pinchView,
    wheelAction: wheelAction, isDrag: isDrag, fitView: fitView, pointInBox: pointInBox, pinOnScreen: pinOnScreen,
    frameOf: frameOf, layoutCanvas: layoutCanvas, firstView: firstView, thumbTier: thumbTier, inView: inView
  };
})();
if (typeof module !== 'undefined') module.exports = CanvasMath;
