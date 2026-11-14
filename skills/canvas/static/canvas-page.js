// The canvas page: one surface that pans and zooms as a whole, as Figma's
// canvas does. Lifted from a journey canvas (canvas.ts, ADR-058).
//
// Every board is drawn at one size, its shots side by side at one height, in
// a grid under its group's title. Two fingers or the wheel pan, a pinch or
// Ctrl/Cmd + wheel zooms round the pointer, a drag pans, and the toolbar zooms
// and fits all. A click on a shot opens nothing: the page only pans and zooms.
// Titles and captions stay one size on screen. The view is remembered per
// canvas, and #board-36 centres that board. The canvas draws thumbnails made
// at build time, loaded for what is in view; a tall shot shows its first
// screen, marked with an arrow.
//
// A canvas whose data has `changes` (canvas.py) marks the boards that changed
// or are new since an earlier capture with an outline and a word, and has a
// Changed only button that lays out those boards alone.
//
// This fragment runs inside one closure with canvas-comments.js, which fills
// in `hooks`. CanvasMath (canvas-math.js) is loaded before it.
var M = CanvasMath;
var DATA = JSON.parse(document.getElementById('canvas-data').textContent);
var root = document.documentElement;
function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
// A board's lasting name: its id when the canvas gives boards ids, else its number.
function boardKey(b) { return b.id != null ? b.id : b.number; }
function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
// 'changed' or 'new' for a board marked so, else ''.
function changeOf(b) { return b.status !== 'failure' && (b.change === 'changed' || b.change === 'new') ? b.change : ''; }
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
var CHEVRON = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
DATA.groups.forEach(function (g, gi) {
  var bg = el('div', 'group-bg');
  world.appendChild(bg);
  var head = '<button type="button" class="fold" data-fold="' + gi + '" aria-expanded="true" title="Collapse this section">' + CHEVRON + '</button><h2><span class="num">' + (gi + 1) + '</span> ' + esc(g.name) + '</h2>' +
    (g.status ? '<span class="chip chip-' + esc(g.status) + '">' + esc(g.statusLabel || g.status) + '</span>' : '') +
    (g.note ? '<span class="muted">' + esc(g.note) + '</span>' : '') +
    '<span class="muted">' + g.boards.length + ' board' + (g.boards.length === 1 ? '' : 's') + '</span>' +
    (g.empty && !g.boards.length ? '<span class="muted">' + esc(g.empty) + '</span>' : '') +
    (DATA.session && DATA.session.reruns && g.id ? '<span class="run-chip" data-run="' + esc(g.id) + '" hidden></span>' +
      '<button type="button" class="rerun" data-rerun="' + esc(g.id) + '" title="Run this feature again and publish its boards">Re-run</button>' : '');
  var lbl = el('div', 'lbl lbl-row', head);
  layer.appendChild(lbl);
  groupEls.push({ g: g, bg: bg, lbl: lbl, id: 'c-' + (gi + 1) });
  g.boards.forEach(function (b, bi) {
    var chg = changeOf(b);
    var fig = el('figure', 'board' + (b.status === 'failure' ? ' failure' : '') + (chg ? ' chg chg-' + chg : ''));
    fig.id = b.status === 'failure' ? 'failure' : 'b-' + boardKey(b);
    var title = b.status === 'failure' ? '<strong>Failed here</strong>' :
      (chg ? '<span class="chg-tag chg-tag-' + chg + '">' + esc(b.changeLabel || chg) + '</span> ' : '') +
      '<span class="num">' + esc(b.number) + '</span> ' + esc(b.title);
    var bo = { g: gi, b: bi, data: b, el: fig, shots: [],
      lbl: layer.appendChild(el('div', 'lbl lbl-board' + (b.status === 'failure' ? ' lbl-fail' : ''), title)),
      cap: b.caption || b.error ? layer.appendChild(el('div', 'lbl lbl-cap', esc(b.error || b.caption))) : null };
    b.shots.forEach(function (s, si) {
      // A changed board outlines the shots that changed; one that does not say, all of them.
      var btn = el('button', 'shot' + (chg && (!s.change || s.change !== 'unchanged') ? ' chg-shot' : ''));
      btn.type = 'button';
      var caption = b.number + ' · ' + b.title + (b.shots.length > 1 ? ' · ' + s.label : '');
      btn.setAttribute('data-caption', caption);
      btn.setAttribute('data-board', boardKey(b));
      if (b.id == null) btn.setAttribute('data-board-num', '');
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
var CHANGES = DATA.changes || null;
var CHANGED_KEY = 'canvas-changed-only:' + (DATA.id || location.pathname);
var changedOnly = !!CHANGES && load(CHANGED_KEY) === '1';
// Changed only keeps the failure board too: it says where the run stopped.
function keepChanged(b) { return b.status === 'failure' || !!changeOf(b); }
// Above a group's first line: its panel's edge and the boards' titles (canvas-math.js firstView).
var TITLE_ROOM = 72;
// Collapsed groups: their title stays, their boards go, the groups below close up.
var FOLD_KEY = 'canvas-folded:' + (DATA.id || location.pathname);
function groupKey(gi) { var g = DATA.groups[gi]; return String(g.id != null ? g.id : g.name); }
var folded = {};
try { (JSON.parse(load(FOLD_KEY) || '[]') || []).forEach(function (k) { folded[k] = true; }); } catch (e) {}
function isFolded(gi) { return !!folded[groupKey(gi)]; }
function relayout() {
  layout = M.layoutCanvas(DATA.groups, isShown, { height: DATA.height, captionH: DATA.captionH || 0, keep: changedOnly ? keepChanged : null,
    folded: isFolded, foldH: 0 });
  if (emptyNote) emptyNote.hidden = !(changedOnly && !layout.groups.length);
  var pad = 48;
  groupEls.forEach(function (ge) { ge.lblOn = false; ge.lbl.style.visibility = 'hidden'; ge.box = null; ge.bg.style.display = 'none'; });
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
  groupEls.forEach(function (ge, gi) {
    var f = isFolded(gi), b = ge.lbl.querySelector('.fold');
    ge.lbl.classList.toggle('folded', f);
    ge.bg.classList.toggle('folded', f);
    b.setAttribute('aria-expanded', String(!f));
    b.title = f ? 'Expand this section' : 'Collapse this section';
  });
  var nFolded = DATA.groups.filter(function (g, gi) { return isFolded(gi); }).length;
  var ua = document.getElementById('unfold-all'), fa = document.getElementById('fold-all');
  if (ua) ua.disabled = !nFolded;
  if (fa) fa.disabled = nFolded === DATA.groups.length;
  // A group title's width, for coversGroup: measured once, while hidden but laid out.
  groupEls.forEach(function (ge) {
    if (ge.lblW) return;
    ge.lblW = ge.lbl.offsetWidth;
    // Its width in the left margin, where it goes when there is no room above (zoomed out): name and status only.
    ge.lbl.classList.add('lbl-side');
    ge.sideW = ge.lbl.offsetWidth;
    ge.lbl.classList.remove('lbl-side');
  });
  world.style.width = layout.w + 'px';
  world.style.height = layout.h + 'px';
  labelsOff();
  if (hooks.measured) hooks.measured();
}
function labelsOff() {
  [groupEls, boardEls].forEach(function (list) { list.forEach(function (o) { o.lblOn = false; o.lbl.style.visibility = 'hidden'; if (o.cap) { o.cap.style.visibility = 'hidden'; o.capOn = false; } }); });
  shotEls.forEach(function (so) { if (so.lbl) { so.lbl.style.visibility = 'hidden'; so.lblOn = false; } });
}
function measureBox() {
  var r = canvas.getBoundingClientRect();
  box = { w: r.width, h: r.height, left: r.left, top: r.top };
}

// The chrome floats on the canvas: the screen pixels its top groups (and a
// banner) cover, and the zoom group's at the bottom, which a view keeps clear.
function topRoom() {
  var r = 0;
  document.querySelectorAll('.banner:not([hidden])').forEach(function (e) {
    r = Math.max(r, e.getBoundingClientRect().bottom - box.top);
  });
  return Math.max(0, r);
}
function bottomRoom() {
  return 0;
}
// fitView in the part of the window the chrome leaves free.
function fitFree(bx, by, bw, bh, pad) {
  var t = topRoom(), v = M.fitView(bx, by, bw, bh, box.w, Math.max(1, box.h - t - bottomRoom()), pad, 1);
  return { x: v.x, y: v.y + t, z: v.z };
}
function fitAll() { return fitFree(-48, -48, layout.w + 96, layout.h + 96, 16); }
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
  // The change outlines keep one width on screen at any zoom (canvas.css).
  if (CHANGES) world.style.setProperty('--z', String(z));
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
  // Group titles above their group. One that would overlap the one above, or
  // another group's boards (short groups, zoomed far out), moves into the left
  // margin beside its group's top, name and status only; with no room there
  // either it is left out. Each column of groups keeps its own: a title never
  // hides one in the next column.
  var below = {}, side = -Infinity;
  for (i = 0; i < groupEls.length; i++) {
    o = groupEls[i];
    if (!o.box) { show(o, 'lbl', false); continue; }
    // Above the group's panel (72 above its first line), never closer to the boards than their titles.
    sx = Math.max(x + (o.box.x - 48) * z, 8); sy = y + (o.box.y - 72) * z - 30;
    if (titles) sy = Math.min(sy, y + o.box.y * z - 48);
    on = sy < H && y + (o.box.y + o.box.h) * z > 0 && x + (o.box.x + o.box.w) * z > 0 && x + o.box.x * z < W && sy >= (o.box.x in below ? below[o.box.x] : -Infinity) &&
      !coversGroup(i, sx, sy, sx + (o.lblW || 0), sy + 26, x, y, z);
    var inView = y + (o.box.y + o.box.h) * z > 0 && y + o.box.y * z < H;
    var atSide = false;
    if (on) below[o.box.x] = sy + 26;
    else if (inView && o.sideW) {
      sx = x + o.box.x * z - o.sideW - 12; sy = y + o.box.y * z;
      atSide = on = sx >= 8 && sy >= side;
      if (on) side = sy + 26;
    }
    if (on) o.lbl.style.transform = 'translate(' + sx + 'px,' + sy + 'px)';
    o.lbl.classList.toggle('lbl-side', atSide);
    show(o, 'lbl', on);
  }
  loadInView();
  if (hooks.render) hooks.render();
}
// Whether the screen box (l, t)-(r, b) overlaps the boards of any group but `skip`.
function coversGroup(skip, l, t, r, b, x, y, z) {
  for (var k = 0; k < groupEls.length; k++) {
    var g = groupEls[k].box;
    if (k === skip || !g) continue;
    if (l < x + (g.x + g.w) * z && r > x + g.x * z && t < y + (g.y + g.h) * z && b > y + g.y * z) return true;
  }
  return false;
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
function first() { return M.firstView(layout, box.w, box.h, box.w < 600 ? 16 : 48, topRoom() + 44); }
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

// A section's fold button: the section's title stays where it is on screen.
function setFolded(gi, on) {
  var before = groupEls[gi].box;
  if (on) folded[groupKey(gi)] = true; else delete folded[groupKey(gi)];
  save(FOLD_KEY, JSON.stringify(Object.keys(folded)));
  relayout();
  var after = groupEls[gi].box;
  if (before && after) setView({ x: view.x + (before.x - after.x) * view.z, y: view.y + (before.y - after.y) * view.z, z: view.z });
  else setView(view);
}
// Opening a board in a collapsed section (a link, a comment) expands it first.
function unfoldBoard(key) {
  var bo = boardEls.filter(function (o) { return String(boardKey(o.data)) === String(key); })[0];
  if (bo && isFolded(bo.g)) { delete folded[groupKey(bo.g)]; save(FOLD_KEY, JSON.stringify(Object.keys(folded))); relayout(); }
}
layer.addEventListener('click', function (e) {
  var b = e.target.closest('.fold');
  if (!b) return;
  var gi = parseInt(b.getAttribute('data-fold'), 10);
  setFolded(gi, !isFolded(gi));
});
// Collapse every section, or expand every one: then the view starts again at the top.
function foldAll(on) {
  folded = {};
  if (on) DATA.groups.forEach(function (g, gi) { folded[groupKey(gi)] = true; });
  save(FOLD_KEY, JSON.stringify(Object.keys(folded)));
  relayout();
  animateTo(first());
}
var ua = document.getElementById('unfold-all'), fa = document.getElementById('fold-all');
if (ua) ua.addEventListener('click', function () { foldAll(false); });
if (fa) fa.addEventListener('click', function () { foldAll(true); });

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

// Changed only: the boards that changed or are new, laid out alone, in view.
var emptyNote = null, changedBtn = document.getElementById('chg-only');
if (CHANGES) {
  emptyNote = canvas.appendChild(el('div', 'chg-empty', 'No board changed' + (CHANGES.since ? ' since ' + esc(CHANGES.since) : '') + '.'));
  emptyNote.hidden = true;
}
function setChangedOnly(on) {
  changedOnly = !!on && !!CHANGES;
  save(CHANGED_KEY, changedOnly ? '1' : '0');
  if (changedBtn) changedBtn.setAttribute('aria-pressed', String(changedOnly));
  root.setAttribute('data-changed-only', changedOnly ? '1' : '0');
  relayout();
  animateTo(changedOnly ? fitAll() : first());
}
if (changedBtn) {
  changedBtn.setAttribute('aria-pressed', String(changedOnly));
  changedBtn.addEventListener('click', function () { setChangedOnly(!changedOnly); });
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
// A click that ends a drag, a pinch or a Space pan does nothing. A click on a
// pin, or on a shot in comment mode, is the comments script's.
canvas.addEventListener('click', function (e) {
  if (e.target.closest('.c-panel')) return;
  if (dragged || space) { e.stopPropagation(); e.preventDefault(); dragged = false; return; }
  dragged = false;
  if (hooks.click && hooks.click(e)) { e.stopPropagation(); e.preventDefault(); }
}, true);
canvas.addEventListener('dragstart', function (e) { e.preventDefault(); });

// Group links, #board-36 (or #36), #c-3 and #failure move the view there.
var hit = null;
function go(hash, instant) {
  var m = /^#(?:board-|b-)(.+)$/.exec(hash) || /^#(\d+)$/.exec(hash), c = /^#c-(\d+)$/.exec(hash), t = null, v;
  if (m) {
    var want = decodeURIComponent(m[1]);
    unfoldBoard(want);
    t = boardEls.filter(function (o) { return o.box && o.data.status !== 'failure' && String(boardKey(o.data)) === want; })[0];
  }
  else if (hash === '#failure') t = boardEls.filter(function (o) { return o.box && o.data.status === 'failure'; })[0];
  if (t) {
    v = fitFree(t.box.x, t.box.y, t.box.w, t.box.h, 48);
    if (hit) hit.classList.remove('hit');
    hit = t.el; hit.classList.add('hit');
  } else if (c && groupEls[parseInt(c[1], 10) - 1] && groupEls[parseInt(c[1], 10) - 1].box) {
    // A group: its width fills the window, from its first line.
    var g = groupEls[parseInt(c[1], 10) - 1].box, pad = box.w < 600 ? 16 : 48;
    var z = M.clampZoom(Math.min(1, (box.w - pad * 2) / Math.max(1, g.w)), minZoom(), M.MAX_ZOOM);
    if (g.boards[0]) z = Math.max(z, box.w < 600 ? (box.w - pad * 2) / g.boards[0].w : Math.min(0.35, (box.w - pad * 2) / g.boards[0].w));
    z = Math.min(1, z);
    v = { x: pad - g.x * z, y: topRoom() + 44 + (TITLE_ROOM - g.y) * z, z: z };
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
// The banner or a phone's rotation can move the canvas: zooming round a point
// needs where it is now.
if (window.ResizeObserver) new ResizeObserver(function () { measureBox(); }).observe(canvas);

document.addEventListener('keydown', function (e) {
  // Typing in a comment: its keys are the text's.
  var t = e.target;
  if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable)) return;
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
  layout: function () { return { w: layout.w, h: layout.h, groups: layout.groups.length, folded: layout.groups.filter(function (g) { return g.folded; }).length }; },
  shots: function () {
    return shotEls.filter(function (s) { return !!s.box; }).map(function (s) {
      return { board: s.data && boardKey(s.board.data), key: s.data.key, box: s.box, tier: s.tier, src: s.img.getAttribute('src') || '' };
    });
  }
};
