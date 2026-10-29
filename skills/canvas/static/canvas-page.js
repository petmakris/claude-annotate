// The canvas page: one surface that pans and zooms as a whole, as Figma's
// canvas does. Lifted from lomem's journey canvas (canvas.ts, ADR-058).
//
// Every board is drawn at one size, its shots side by side at one height, in
// a grid under its group's title. Two fingers or the wheel pan, a pinch or
// Ctrl/Cmd + wheel zooms round the pointer, a drag pans, and the toolbar zooms
// and fits all. A click opens a shot full size; a drag that starts on one does
// not. Titles and captions stay one size on screen. The view is remembered per
// canvas, and #board-36 centres that board. The canvas draws thumbnails made
// at build time, loaded for what is in view; the full image is only in the
// viewer a click opens.
//
// This fragment runs inside one closure with canvas-comments.js, which fills
// in `hooks`. CanvasMath (canvas-math.js) is loaded before it.
var M = CanvasMath;
var DATA = JSON.parse(document.getElementById('canvas-data').textContent);
var root = document.documentElement;
function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; }

var theme = load('canvas-theme');
if (theme === 'light' || theme === 'dark') root.setAttribute('data-theme', theme);
document.getElementById('theme').addEventListener('click', function () {
  var dark = root.getAttribute('data-theme') === 'dark' ||
    (!root.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
  var next = dark ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  save('canvas-theme', next);
});

// Filled in by the comments script, when the page has one.
var hooks = { measured: null, render: null, click: null, key: null };

var canvas = document.getElementById('canvas'), world = document.getElementById('world');
var layer = document.getElementById('labels'), zoomLabel = document.getElementById('zoom-label');
// Each canvas remembers its own view.
var VIEW_KEY = 'canvas-view:' + (DATA.id || location.pathname);
var view = { x: 0, y: 0, z: 1 };
var box = { w: 0, h: 0, left: 0, top: 0 };
var DPR = window.devicePixelRatio || 1;

// ── The surface's elements, made once; the layout only moves them ──
var LABELS = DATA.labels || [];
var shown = 'all';
function isShown(label) { return shown === 'all' || label === shown; }
var groupEls = [], boardEls = [], shotEls = [];
DATA.groups.forEach(function (g, gi) {
  var bg = el('div', 'group-bg');
  world.appendChild(bg);
  var head = '<h2><span class="num">' + (gi + 1) + '</span> ' + esc(g.name) + '</h2>' +
    (g.status ? '<span class="chip chip-' + esc(g.status) + '">' + esc(g.statusLabel || g.status) + '</span>' : '') +
    (g.note ? '<span class="muted">' + esc(g.note) + '</span>' : '') +
    '<span class="muted">' + g.boards.length + ' board' + (g.boards.length === 1 ? '' : 's') + '</span>' +
    (g.empty && !g.boards.length ? '<span class="muted">' + esc(g.empty) + '</span>' : '');
  var lbl = el('div', 'lbl lbl-row', head);
  layer.appendChild(lbl);
  groupEls.push({ g: g, bg: bg, lbl: lbl, id: 'c-' + (gi + 1) });
  g.boards.forEach(function (b, bi) {
    var fig = el('figure', 'board' + (b.status === 'failure' ? ' failure' : ''));
    fig.id = b.status === 'failure' ? 'failure' : 'b-' + b.number;
    var title = b.status === 'failure' ? '<strong>Failed here</strong>' : '<span class="num">' + esc(b.number) + '</span> ' + esc(b.title);
    var bo = { g: gi, b: bi, data: b, el: fig, shots: [],
      lbl: layer.appendChild(el('div', 'lbl lbl-board' + (b.status === 'failure' ? ' lbl-fail' : ''), title)),
      cap: b.caption || b.error ? layer.appendChild(el('div', 'lbl lbl-cap', esc(b.error || b.caption))) : null };
    b.shots.forEach(function (s, si) {
      var btn = el('button', 'shot');
      btn.type = 'button';
      var caption = b.number + ' · ' + b.title + (b.shots.length > 1 ? ' · ' + s.label : '');
      btn.setAttribute('data-file', s.file);
      btn.setAttribute('data-caption', caption);
      btn.setAttribute('data-board', b.number);
      btn.setAttribute('data-shot', s.key);
      btn.setAttribute('data-title', b.title);
      btn.setAttribute('data-chapter', g.name);
      btn.setAttribute('aria-label', caption);
      var img = el('img');
      img.alt = '';
      img.decoding = 'async';
      img.draggable = false;
      img.style.aspectRatio = s.thumbW + ' / ' + s.thumbH;
      btn.appendChild(img);
      if (s.cropped) btn.appendChild(el('span', 'more', '↓'));
      fig.appendChild(btn);
      var so = { board: bo, data: s, el: btn, img: img, tier: 0 };
      bo.shots.push(so);
      shotEls.push(so);
      if (si > 0) so.lbl = layer.appendChild(el('div', 'lbl lbl-variant', esc(s.label)));
    });
    world.appendChild(fig);
    boardEls.push(bo);
  });
});

// ── Layout: positions on the surface, made again when the shot toggle changes ──
var layout = null;
// Above a group's first line: its panel's edge and the boards' titles (canvas-math.js firstView).
var TITLE_ROOM = 72;
function relayout() {
  layout = M.layoutCanvas(DATA.groups, isShown, { height: DATA.height, captionH: DATA.captionH || 0 });
  var pad = 48;
  groupEls.forEach(function (ge) { ge.on = false; ge.lbl.style.visibility = 'hidden'; ge.box = null; ge.bg.style.display = 'none'; });
  boardEls.forEach(function (bo) { bo.box = null; bo.el.style.display = 'none'; });
  shotEls.forEach(function (so) { so.box = null; so.el.style.display = 'none'; });
  layout.groups.forEach(function (lg) {
    var ge = groupEls[lg.i];
    ge.box = lg;
    ge.bg.style.display = '';
    // Room above the first line for its board titles, as a Figma section has.
    ge.bg.style.cssText = 'left:' + (lg.x - pad) + 'px;top:' + (lg.y - pad - 24) + 'px;width:' + (lg.w + pad * 2) + 'px;height:' + (lg.h + pad * 2 + 24) + 'px';
    lg.boards.forEach(function (lb) {
      var bo = boardEls.filter(function (x) { return x.g === lg.i && x.b === lb.i; })[0];
      bo.box = { x: lb.x, y: lb.y, w: lb.w, h: lb.h };
      bo.el.style.cssText = 'display:block;left:' + lb.x + 'px;top:' + lb.y + 'px;width:' + lb.w + 'px;height:' + lb.h + 'px';
      lb.shots.forEach(function (ls) {
        var so = bo.shots[ls.i];
        // The shot's whole image on the surface (fullH tall), drawn in its frame (h tall).
        so.box = { x: lb.x + ls.x, y: lb.y, w: ls.w, h: ls.fullH, frameH: ls.h };
        so.el.style.cssText = 'display:block;left:' + ls.x + 'px;top:0;width:' + ls.w + 'px;height:' + ls.h + 'px';
      });
    });
  });
  world.style.width = layout.w + 'px';
  world.style.height = layout.h + 'px';
  labelsOff();
  if (hooks.measured) hooks.measured();
}
function labelsOff() {
  [groupEls, boardEls].forEach(function (list) { list.forEach(function (o) { o.on = false; o.lbl.style.visibility = 'hidden'; if (o.cap) { o.cap.style.visibility = 'hidden'; o.capOn = false; } }); });
  shotEls.forEach(function (so) { if (so.lbl) { so.lbl.style.visibility = 'hidden'; so.lblOn = false; } });
}
function measureBox() {
  var r = canvas.getBoundingClientRect();
  box = { w: r.width, h: r.height, left: r.left, top: r.top };
}

function fitAll() { return M.fitView(-48, -48, layout.w + 96, layout.h + 96, box.w, box.h, 16, 1); }
function minZoom() { return Math.min(M.MIN_ZOOM, fitAll().z); }

// ── Drawing a view ──
var frame = 0, idle = 0, lastPct = '';
function setView(v) {
  view = { x: v.x, y: v.y, z: v.z };
  if (!frame) frame = requestAnimationFrame(render);
}
function show(o, key, on) {
  if (on !== o[key + 'On']) { o[key].style.visibility = on ? 'visible' : 'hidden'; o[key + 'On'] = on; }
}
function render() {
  frame = 0;
  var x = view.x, y = view.y, z = view.z, W = box.w, H = box.h, i, o, sx, sy, sw, on;
  world.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + z + ')';
  if (!world.classList.contains('moving')) world.classList.add('moving');
  clearTimeout(idle);
  idle = setTimeout(rest, 180);
  var pct = Math.round(z * 100) + '%';
  if (pct !== lastPct) { zoomLabel.textContent = pct; lastPct = pct; }
  // Board titles above each board, captions under it, shot labels above a second shot.
  var titles = false;
  for (i = 0; i < boardEls.length; i++) {
    o = boardEls[i];
    if (!o.box) { show(o, 'lbl', false); if (o.cap) show(o, 'cap', false); continue; }
    sx = x + o.box.x * z; sy = y + o.box.y * z; sw = o.box.w * z;
    var near = sx < W && sx + sw > 0 && sy - 20 < H && sy + (o.box.h + (DATA.captionH || 0)) * z > 0;
    on = near && sw >= 64;
    if (on) {
      titles = true;
      o.lbl.style.transform = 'translate(' + sx + 'px,' + (sy - 20) + 'px)';
      // Never wider than its first shot (a second one has its own label), as Figma cuts a frame's name.
      var firstShot = o.shots.filter(function (so) { return !!so.box; })[0];
      o.lbl.style.maxWidth = (shown === 'all' && o.shots.length > 1 && firstShot ? firstShot.box.w * z - 6 : sw) + 'px';
    }
    show(o, 'lbl', on);
    if (o.cap) {
      var room = (DATA.captionH || 0) * z - 8;
      var capOn = near && sw >= 120 && room >= 16;
      if (capOn) {
        o.cap.style.transform = 'translate(' + sx + 'px,' + (sy + o.box.h * z + 6) + 'px)';
        o.cap.style.width = sw + 'px';
        o.cap.style.maxHeight = Math.floor(room / 16) * 16 + 'px';
      }
      show(o, 'cap', capOn);
    }
  }
  for (i = 0; i < shotEls.length; i++) {
    o = shotEls[i];
    if (!o.lbl) continue;
    on = !!o.box && o.box.w * z >= 40 && shown === 'all';
    if (on) {
      sx = x + o.box.x * z; sy = y + o.box.y * z;
      on = sx < W && sx + o.box.w * z > 0 && sy - 20 < H && sy > -o.box.frameH * z;
      if (on) o.lbl.style.transform = 'translate(' + sx + 'px,' + (sy - 18) + 'px)';
    }
    show(o, 'lbl', on);
  }
  // Group titles above their group; one that would overlap the one above is left out.
  var below = -Infinity;
  for (i = 0; i < groupEls.length; i++) {
    o = groupEls[i];
    if (!o.box) { show(o, 'lbl', false); continue; }
    // Above the group's panel (72 above its first line), never closer to the boards than their titles.
    sx = Math.max(x + (o.box.x - 48) * z, 8); sy = y + (o.box.y - 72) * z - 30;
    if (titles) sy = Math.min(sy, y + o.box.y * z - 48);
    on = sy < H && y + (o.box.y + o.box.h) * z > 0 && x + (o.box.x + o.box.w) * z > 0 && x + o.box.x * z < W && sy >= below;
    if (on) { below = sy + 26; o.lbl.style.transform = 'translate(' + sx + 'px,' + sy + 'px)'; }
    show(o, 'lbl', on);
  }
  loadInView();
  if (hooks.render) hooks.render();
}
// Thumbnails for every shot in view (or within half a window of it), at the
// tier the zoom needs; a shot keeps the sharper one once it has it.
function loadInView() {
  var tier = M.thumbTier(view.z, DPR);
  for (var i = 0; i < shotEls.length; i++) {
    var o = shotEls[i];
    if (!o.box || o.tier >= tier) continue;
    if (!M.inView(view, o.box.x, o.box.y, o.box.w, o.box.frameH, box.w, box.h, 0.5)) continue;
    o.tier = tier;
    o.img.src = o.data.thumbs[tier - 1] || o.data.thumbs[0];
  }
}
function rest() {
  world.classList.remove('moving');
  save(VIEW_KEY, JSON.stringify(view));
}

// Short eased moves for the buttons, the keys and links; the wheel, a drag and
// a pinch follow the hand directly.
var anim = 0;
function animateTo(t) {
  cancelAnimationFrame(anim);
  var s = view, t0 = performance.now();
  function step(now) {
    var k = Math.min(1, (now - t0) / 200), e = 1 - Math.pow(1 - k, 3);
    // Zoom moves in ratio, not in steps, so 2 % to 100 % does not leap.
    var z = s.z * Math.pow(t.z / s.z, e);
    var f = (s.z === t.z) ? e : (z - s.z) / (t.z - s.z);
    setView({ x: s.x + (t.x - s.x) * f, y: s.y + (t.y - s.y) * f, z: z });
    if (k < 1) anim = requestAnimationFrame(step);
  }
  anim = requestAnimationFrame(step);
}
function zoomCentre(z) {
  animateTo(M.zoomAt(view, box.w / 2, box.h / 2, M.clampZoom(z, minZoom(), M.MAX_ZOOM)));
}
function first() { return M.firstView(layout, box.w, box.h, box.w < 600 ? 16 : 48, 44); }
function actions(k) {
  if (k === 'in') zoomCentre(view.z * 2);
  else if (k === 'out') zoomCentre(view.z / 2);
  else if (k === 'actual') zoomCentre(1);
  else if (k === 'fit') animateTo(fitAll());
  else if (k === 'first') animateTo(first());
}
document.querySelectorAll('[data-zoom]').forEach(function (b) {
  b.addEventListener('click', function () { actions(b.getAttribute('data-zoom')); });
});

// All, or one shot label: which shots of a many-shot board are shown. The
// grid is laid out again for what is shown.
var SIZES_KEY = 'canvas-shots:' + (DATA.id || location.pathname);
function setShown(next) {
  if (LABELS.length < 2) return;
  shown = LABELS.indexOf(next) >= 0 ? next : 'all';
  root.setAttribute('data-shown', shown === 'all' ? 'all' : 'one');
  document.querySelectorAll('button[data-shown]').forEach(function (b) {
    b.setAttribute('aria-pressed', String(b.getAttribute('data-shown') === shown));
  });
  save(SIZES_KEY, shown);
  relayout();
  setView(view);
}
if (LABELS.length > 1) {
  shown = LABELS.indexOf(load(SIZES_KEY)) >= 0 ? load(SIZES_KEY) : 'all';
  root.setAttribute('data-shown', shown === 'all' ? 'all' : 'one');
  document.querySelectorAll('button[data-shown]').forEach(function (b) {
    b.setAttribute('aria-pressed', String(b.getAttribute('data-shown') === shown));
    b.addEventListener('click', function () { setShown(b.getAttribute('data-shown')); });
  });
}

// The wheel: two fingers on a trackpad pan any way, a mouse wheel pans down
// (Shift: sideways); a pinch or Ctrl/Cmd + wheel zooms round the pointer.
canvas.addEventListener('wheel', function (e) {
  e.preventDefault();
  cancelAnimationFrame(anim);
  var a = M.wheelAction(e.deltaX, e.deltaY, e.deltaMode, e.ctrlKey || e.metaKey, e.shiftKey, box.h);
  if (a.factor !== 1) {
    setView(M.zoomAt(view, e.clientX - box.left, e.clientY - box.top, M.clampZoom(view.z * a.factor, minZoom(), M.MAX_ZOOM)));
  } else {
    setView({ x: view.x - a.dx, y: view.y - a.dy, z: view.z });
  }
}, { passive: false });

// Pointers: a drag pans (on the background, or anywhere with Space or the
// middle button); two fingers pinch. A press that moves past a few pixels is a
// drag and never opens the shot it started on.
var pointers = {}, count = 0, press = null, pinch = null, dragged = false, space = false;
function pos(e) { return { x: e.clientX - box.left, y: e.clientY - box.top }; }
function startPinch() {
  var ids = Object.keys(pointers), a = pointers[ids[0]], b = pointers[ids[1]];
  pinch = { view: view, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) };
}
canvas.addEventListener('pointerdown', function (e) {
  if (e.target.closest('.c-panel')) return;
  if (e.pointerType === 'mouse' && e.button !== 0 && e.button !== 1) return;
  if (e.button === 1) e.preventDefault();
  cancelAnimationFrame(anim);
  if (count === 0) dragged = false;
  pointers[e.pointerId] = pos(e);
  count++;
  if (count === 1) {
    var p = pointers[e.pointerId];
    press = { id: e.pointerId, sx: p.x, sy: p.y, view: view, type: e.pointerType, panning: false };
    if (space || e.button === 1 || !e.target.closest('.shot, .pin')) canvas.classList.add('grabbing');
  } else if (count === 2) {
    dragged = true;
    press = null;
    startPinch();
    try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
  }
});
canvas.addEventListener('pointermove', function (e) {
  if (!(e.pointerId in pointers)) return;
  var p = pos(e);
  pointers[e.pointerId] = p;
  if (pinch && count >= 2) {
    var ids = Object.keys(pointers), a = pointers[ids[0]], b = pointers[ids[1]];
    setView(M.pinchView(pinch.view, pinch.mx, pinch.my, pinch.d, (a.x + b.x) / 2, (a.y + b.y) / 2,
      Math.hypot(a.x - b.x, a.y - b.y), minZoom(), M.MAX_ZOOM));
  } else if (press && press.id === e.pointerId) {
    if (!press.panning && M.isDrag(p.x - press.sx, p.y - press.sy, press.type)) {
      press.panning = true;
      dragged = true;
      canvas.classList.add('grabbing');
      try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
    }
    if (press.panning) setView({ x: press.view.x + p.x - press.sx, y: press.view.y + p.y - press.sy, z: press.view.z });
  }
});
function lift(e) {
  if (!(e.pointerId in pointers)) return;
  delete pointers[e.pointerId];
  count--;
  if (count === 1) {
    // One finger stays after a pinch: it pans on from where it is.
    var id = Object.keys(pointers)[0], p = pointers[id];
    pinch = null;
    press = { id: Number(id), sx: p.x, sy: p.y, view: view, type: 'touch', panning: true };
  } else if (count <= 0) {
    count = 0; pointers = {}; press = null; pinch = null;
    canvas.classList.remove('grabbing');
  }
}
canvas.addEventListener('pointerup', lift);
canvas.addEventListener('pointercancel', lift);
// A click that ends a drag, a pinch or a Space pan opens nothing. A click on a
// pin, or on a shot in comment mode, is the comments script's.
canvas.addEventListener('click', function (e) {
  if (e.target.closest('.c-panel')) return;
  if (dragged || space) { e.stopPropagation(); e.preventDefault(); dragged = false; return; }
  dragged = false;
  if (hooks.click && hooks.click(e)) { e.stopPropagation(); e.preventDefault(); }
}, true);
canvas.addEventListener('dragstart', function (e) { e.preventDefault(); });

// Group links, #board-36, #c-3 and #failure move the view there.
var hit = null;
function go(hash, instant) {
  var m = /^#(?:board-|b-)(\d+)$/.exec(hash), c = /^#c-(\d+)$/.exec(hash), t = null, v;
  if (m) t = boardEls.filter(function (o) { return o.box && String(o.data.number) === String(parseInt(m[1], 10)) && o.data.status !== 'failure'; })[0];
  else if (hash === '#failure') t = boardEls.filter(function (o) { return o.box && o.data.status === 'failure'; })[0];
  if (t) {
    v = M.fitView(t.box.x, t.box.y, t.box.w, t.box.h, box.w, box.h, 48, 1);
    if (hit) hit.classList.remove('hit');
    hit = t.el; hit.classList.add('hit');
  } else if (c && groupEls[parseInt(c[1], 10) - 1] && groupEls[parseInt(c[1], 10) - 1].box) {
    // A group: its width fills the window, from its first line.
    var g = groupEls[parseInt(c[1], 10) - 1].box, pad = box.w < 600 ? 16 : 48;
    var z = M.clampZoom(Math.min(1, (box.w - pad * 2) / Math.max(1, g.w)), minZoom(), M.MAX_ZOOM);
    if (g.boards[0]) z = Math.max(z, box.w < 600 ? (box.w - pad * 2) / g.boards[0].w : Math.min(0.35, (box.w - pad * 2) / g.boards[0].w));
    z = Math.min(1, z);
    v = { x: pad - g.x * z, y: 44 + (TITLE_ROOM - g.y) * z, z: z };
  } else return false;
  if (instant) setView(v); else animateTo(v);
  return true;
}
document.querySelectorAll('a[href^="#"]').forEach(function (a) {
  a.addEventListener('click', function (e) {
    e.preventDefault();
    var h = a.getAttribute('href');
    try { history.replaceState(null, '', h); } catch (err) {}
    go(h, false);
  });
});
window.addEventListener('hashchange', function () { go(location.hash, false); });

measureBox();
relayout();
if (!go(location.hash, true)) {
  var saved = null;
  try { saved = JSON.parse(load(VIEW_KEY) || 'null'); } catch (e) {}
  if (saved && isFinite(saved.x) && isFinite(saved.y) && saved.z > 0) setView(saved);
  else setView(first());
}
window.addEventListener('resize', function () { measureBox(); setView(view); });
// The toolbar can wrap again (the zoom label's width changes), which moves the
// canvas: zooming round a point needs where it is now.
if (window.ResizeObserver) new ResizeObserver(function () { measureBox(); }).observe(canvas);

// ── The viewer a click opens: the full image ──
function visibleShots() { return shotEls.filter(function (s) { return !!s.box; }); }
var lb = document.getElementById('lightbox'), lbImg = document.getElementById('lb-img');
var shots = [], cur = -1;
// 'width': the shot at 1.5x its CSS size (capped by the window), scrolling
// down a tall one. 'fit': the whole shot in the window. Either way only the
// width is set, so the image keeps its own aspect ratio.
var mode = load('canvas-lb-mode') === 'fit' ? 'fit' : 'width';
function size() {
  if (cur < 0) return;
  var s = shots[cur].data, scroll = document.getElementById('lb-scroll');
  var w = s.width, h = s.height;
  var availW = scroll.clientWidth - 32, availH = scroll.clientHeight - 40;
  var width = mode === 'fit' ? Math.min(w * 1.5, availW, (availH * w) / h) : Math.min(w * 1.5, availW);
  lbImg.style.width = Math.max(80, Math.floor(width)) + 'px';
  document.getElementById('lb-mode').textContent = mode === 'fit' ? 'Width' : 'Fit';
}
function open(i) {
  if (i < 0 || i >= shots.length) return;
  cur = i;
  var s = shots[i], b = s.board.data;
  lbImg.src = s.data.file;
  lbImg.alt = s.el.getAttribute('data-caption');
  document.getElementById('lb-cap').textContent = s.el.getAttribute('data-caption');
  var note = document.getElementById('lb-note');
  note.textContent = b.error || b.caption || '';
  note.style.display = note.textContent ? '' : 'none';
  document.getElementById('lb-open').href = s.data.file;
  lb.classList.add('open');
  size();
  document.getElementById('lb-scroll').scrollTop = 0;
}
function close() { lb.classList.remove('open'); cur = -1; }
function toggleMode() { mode = mode === 'fit' ? 'width' : 'fit'; save('canvas-lb-mode', mode); size(); }
window.addEventListener('resize', size);
shotEls.forEach(function (s) {
  s.el.addEventListener('click', function () { shots = visibleShots(); open(shots.indexOf(s)); });
});
lb.addEventListener('click', function (e) {
  var k = e.target.getAttribute && e.target.getAttribute('data-lb');
  if (k === 'close' || e.target === lb || e.target.id === 'lb-scroll') close();
  else if (k === 'prev') open(cur - 1);
  else if (k === 'next') open(cur + 1);
  else if (k === 'mode') toggleMode();
});
document.addEventListener('keydown', function (e) {
  // Typing in a comment: its keys are the text's.
  var t = e.target;
  if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable)) return;
  if (cur >= 0) {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') open(cur - 1);
    else if (e.key === 'ArrowRight') open(cur + 1);
    else if (e.key === 'f' || e.key === 'F') toggleMode();
    return;
  }
  if (hooks.key && hooks.key(e)) { e.preventDefault(); return; }
  // Figma's keys: Space held pans, Shift+1 fits all, Shift+0 is 100 %, + and − zoom.
  if (e.code === 'Space') {
    e.preventDefault();
    if (!space) { space = true; canvas.classList.add('hand'); }
  } else if (e.shiftKey && e.code === 'Digit1') { e.preventDefault(); actions('fit'); }
  else if (e.shiftKey && e.code === 'Digit0') { e.preventDefault(); actions('actual'); }
  else if (e.key === '+' || e.key === '=') { e.preventDefault(); actions('in'); }
  else if (e.key === '-' || e.key === '_') { e.preventDefault(); actions('out'); }
});
document.addEventListener('keyup', function (e) {
  if (e.code === 'Space') { e.preventDefault(); space = false; canvas.classList.remove('hand'); }
});
window.addEventListener('blur', function () { space = false; canvas.classList.remove('hand'); });

// For the checks: what is where, read-only.
window.canvasView = {
  view: function () { return { x: view.x, y: view.y, z: view.z }; },
  layout: function () { return { w: layout.w, h: layout.h, groups: layout.groups.length }; },
  shots: function () {
    return shotEls.filter(function (s) { return !!s.box; }).map(function (s) {
      return { board: s.data && s.board.data.number, key: s.data.key, box: s.box, tier: s.tier, src: s.img.getAttribute('src') || '' };
    });
  }
};
