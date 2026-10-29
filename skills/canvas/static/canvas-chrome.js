// The page's chrome, built from the canvas data before canvas-page.js runs:
// the title bar and its toolbar, the group links, the banner, and the comment
// layers when the canvas takes comments. The template itself stays the same
// for every canvas, so a project can vendor it and only put its data in.
(function () {
  var D = JSON.parse(document.getElementById('canvas-data').textContent);
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  document.title = D.title;
  var labels = D.labels || [];
  var seg = '';
  if (labels.length > 1) {
    seg = '<span class="seg" role="group" aria-label="Shots">' +
      '<button type="button" data-shown="all" aria-pressed="true">' + (labels.length === 2 ? 'Both' : 'All') + '</button>' +
      labels.map(function (l) { return '<button type="button" data-shown="' + esc(l) + '" aria-pressed="false">' + esc(l) + '</button>'; }).join('') +
      '</span>';
  }
  var comments = '';
  if (D.comments) {
    comments = '<button type="button" id="c-mode" class="c-toggle" aria-pressed="false" title="Comment on a screenshot (C)">Comment</button>' +
      '<button type="button" id="c-panel-btn" class="c-toggle" aria-pressed="false" title="Every comment on this canvas">Comments <span id="c-count"></span></button>' +
      '<span class="c-status" id="c-status" role="status"></span>';
  }
  var status = D.status ? '<span class="chip chip-' + esc(D.status.kind) + '">' + esc(D.status.label) + '</span>' : '';
  var nav = D.groups.length > 1 ? '<nav aria-label="Groups">' + D.groups.map(function (g, i) {
    return '<a class="nav-link nav-' + esc(g.status || 'none') + '" href="#c-' + (i + 1) + '">' + (i + 1) + ' · ' + esc(g.name) + '</a>';
  }).join('') + '</nav>' : '';
  document.getElementById('top').innerHTML =
    '<div class="title"><h1>' + esc(D.title) + '</h1>' + status +
    (D.subtitle ? '<span class="muted">' + esc(D.subtitle) + '</span>' : '') +
    '<div class="tools" role="toolbar" aria-label="Zoom">' + seg +
    '<button type="button" data-zoom="out" aria-label="Zoom out" title="Zoom out (−)">−</button>' +
    '<span class="zoom-label" id="zoom-label">100%</span>' +
    '<button type="button" data-zoom="in" aria-label="Zoom in" title="Zoom in (+)">+</button>' +
    '<button type="button" data-zoom="fit" title="Every board in the window (Shift+1)">Fit all</button>' +
    '<button type="button" data-zoom="actual" title="Boards at their drawn size (Shift+0)">100%</button>' +
    '<button type="button" id="theme" title="Light or dark">◐</button>' + comments + '</div></div>' +
    ((D.meta || []).length ? '<div class="meta">' + D.meta.map(function (m) { return '<span>' + esc(m) + '</span>'; }).join('') + '</div>' : '') + nav;
  var banner = document.getElementById('banner');
  if (D.banner) {
    banner.innerHTML = esc(D.banner) + (D.groups.some(function (g) { return g.boards.some(function (b) { return b.status === 'failure'; }); })
      ? ' <a href="#failure">See where it stopped</a>.' : '');
    banner.hidden = false;
  }
  if (D.comments) {
    var scopes = D.comments.scopes;
    document.getElementById('canvas').insertAdjacentHTML('beforeend',
      '<div class="pins" id="pins"></div>' +
      '<aside class="c-panel" id="c-panel" aria-label="Comments">' +
      '<div class="c-panel-head"><div class="c-head"><span class="c-title">Comments</span><button type="button" id="c-panel-close" aria-label="Close the comments">✕</button></div>' +
      '<div class="c-row" style="margin:0"><span class="c-seg" role="group" aria-label="Status">' +
      '<button type="button" data-cstatus="open" aria-pressed="true">Open</button>' +
      '<button type="button" data-cstatus="resolved" aria-pressed="false">Resolved</button>' +
      '<button type="button" data-cstatus="all" aria-pressed="false">All</button></span>' +
      (scopes ? '<span class="c-seg" role="group" aria-label="Scope">' +
        '<button type="button" data-cscope="all" aria-pressed="true">Any scope</button>' +
        '<button type="button" data-cscope="app" aria-pressed="false">' + esc(scopes.app) + '</button>' +
        '<button type="button" data-cscope="both" aria-pressed="false">' + esc(scopes.both) + '</button></span>' : '') +
      '</div></div><div class="c-list" id="c-list"></div></aside>');
    document.body.insertAdjacentHTML('beforeend', '<div class="c-hover" id="c-hover"></div><div class="c-pop" id="c-pop" role="dialog" aria-label="Comment"></div>');
  }
})();
