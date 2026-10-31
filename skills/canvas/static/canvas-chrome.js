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
  if (D.comments && D.session) {
    comments = '<button type="button" id="c-mode" class="c-toggle" aria-pressed="false" title="Comment on a screenshot (C)">Comment</button>' +
      '<button type="button" id="c-panel-btn" class="c-toggle" aria-pressed="false" title="Every comment on this canvas">Comments <span id="c-count"></span></button>' +
      '<button type="button" id="c-send" class="primary s-send" disabled title="Send the comments Claude has not answered to the Claude session of this canvas">Send to Claude</button>' +
      '<span class="c-status" id="c-status" role="status"></span>';
  }
  // A journey canvas: Claude's state, and Re-run all (each group has its own Re-run).
  var session = '';
  if (D.session) {
    session = '<span class="s-claude" id="s-claude" role="status" title="The Claude session that answers this canvas"></span>' +
      (D.session.reruns ? '<button type="button" id="s-rerun-all" title="Run every feature again and publish the canvas">Re-run all</button>' : '');
  }
  // What changed since an earlier capture: a count and the Changed only button.
  // A board with no `change` counts as unchanged; the failure board is no board.
  var changed = '';
  var CH = D.changes;
  if (CH) {
    var all = 0, moved = 0, fresh = 0;
    D.groups.forEach(function (g) {
      g.boards.forEach(function (b) {
        if (b.status === 'failure') return;
        all++;
        if (b.change === 'changed' || b.change === 'new') moved++;
        if (b.change === 'new') fresh++;
      });
    });
    var count = moved + ' of ' + all + ' board' + (all === 1 ? '' : 's') + ' changed' + (CH.since ? ' since ' + CH.since : '') +
      (fresh ? ' (' + fresh + ' new)' : '');
    changed = '<button type="button" id="chg-only" class="chg-only" aria-pressed="false" title="Show only the boards that changed">Changed only</button>' +
      '<span class="chg-count" id="chg-count">' + esc(count) + '</span>';
  }
  var status = D.status ? '<span class="chip chip-' + esc(D.status.kind) + '">' + esc(D.status.label) + '</span>' : '';
  // The page has no bar: the canvas takes the window, and the chrome floats on
  // it in three groups. Top left: the name, its status and the groups. Top
  // right: Changed only, Claude's state and the menu with everything else.
  // Bottom: zoom. Each id stays the same, so the scripts find what they did.
  var nav = D.groups.length > 1 ? '<nav aria-label="Groups">' + D.groups.map(function (g, i) {
    return '<a class="nav-link nav-' + esc(g.status || 'none') + '" href="#c-' + (i + 1) + '"><span class="num">' + (i + 1) + '</span> ' + esc(g.name) + '</a>';
  }).join('') + '</nav>' : '';
  var groupsBtn = nav ? '<span class="pop-host"><button type="button" class="pop-btn" aria-expanded="false" aria-haspopup="true" title="Go to a group">' +
    D.groups.length + ' ' + (D.groupNoun || (D.session ? 'features' : 'groups')) + ' ▾</button><div class="pop pop-left pop-groups" role="menu">' + nav + '</div></span>' : '';
  var removed = CH && (CH.removed || []).length ? '<div class="meta chg-removed"><span><strong>' + CH.removed.length + ' removed</strong>' +
    (CH.since ? ' since ' + esc(CH.since) : '') + ':</span>' + CH.removed.map(function (r) {
      return '<span>' + (r.number ? '<span class="num">' + esc(r.number) + '</span> ' : '') + esc(r.title) + (r.group ? ' <span class="muted">· ' + esc(r.group) + '</span>' : '') + '</span>';
    }).join('') + '</div>' : '';
  var capture = ((D.meta || []).length ? '<div class="meta">' + D.meta.map(function (m) { return '<span>' + esc(m) + '</span>'; }).join('') + '</div>' : '') +
    (changed ? '<div class="meta">' + changed.replace(/^<button[^]*?<\/button>/, '') + '</div>' : '') + removed;
  var claudeSec = session || comments ? '<div class="pop-sec"><div class="pop-h">Claude</div><div class="pop-row">' +
    comments.replace(/<span class="c-status"[^]*?<\/span>/, '') + '</div>' +
    (D.session && D.session.reruns ? '<div class="pop-row">' + session.replace(/<span class="s-claude"[^]*?<\/span>/, '') + '</div>' : '') + '</div>' : '';
  var menu = '<span class="pop-host"><button type="button" class="pop-btn menu-btn" aria-expanded="false" aria-haspopup="true" aria-label="Menu" title="Menu">☰</button>' +
    '<div class="pop pop-right" role="menu">' + claudeSec +
    (capture || D.subtitle ? '<div class="pop-sec"><div class="pop-h">Capture</div>' + (D.subtitle ? '<div class="meta">' + esc(D.subtitle) + '</div>' : '') + capture + '</div>' : '') +
    '<div class="pop-sec"><div class="pop-h">View</div><div class="pop-row">' + seg +
    '<button type="button" data-zoom="actual" title="Boards at their drawn size (Shift+0)">100%</button>' +
    '<button type="button" id="theme" title="Light or dark">◐ Theme</button></div></div></div></span>';
  document.getElementById('top').innerHTML =
    '<div class="float float-tl title"><h1 title="' + esc(D.title) + '">' + esc(D.title) + '</h1>' + status + groupsBtn + '</div>' +
    '<div class="float float-tr tools" role="toolbar" aria-label="Canvas">' +
    (CH ? changed.replace(/<span class="chg-count"[^]*?<\/span>/, '').replace('>Changed only</button>', '>Changed<span class="chg-only-word"> only</span> <span class="chg-n">' + moved + '</span></button>') : '') +
    (D.session ? '<span class="s-claude" id="s-claude" role="status" title="The Claude session that answers this canvas"></span>' : '') +
    (comments ? '<span class="c-status" id="c-status" role="status"></span>' : '') + menu + '</div>' +
    '<div class="float float-bc tools" role="toolbar" aria-label="Zoom">' +
    '<button type="button" data-zoom="out" aria-label="Zoom out" title="Zoom out (−)">−</button>' +
    '<span class="zoom-label" id="zoom-label">100%</span>' +
    '<button type="button" data-zoom="in" aria-label="Zoom in" title="Zoom in (+)">+</button>' +
    '<button type="button" data-zoom="fit" title="Every board in the window (Shift+1)">Fit all</button></div>';
  document.getElementById('top').appendChild(document.getElementById('banner'));
  // A menu opens on its button and closes on a second click, a click outside,
  // Escape, or a pick inside it (the view's own buttons keep it open).
  function closeAll(except) {
    document.querySelectorAll('.pop-host.open').forEach(function (h) {
      if (h === except) return;
      h.classList.remove('open');
      h.querySelector('.pop-btn').setAttribute('aria-expanded', 'false');
    });
  }
  document.querySelectorAll('.pop-host').forEach(function (h) {
    var b = h.querySelector('.pop-btn');
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      closeAll(h);
      var open = h.classList.toggle('open');
      b.setAttribute('aria-expanded', String(open));
    });
    h.querySelector('.pop').addEventListener('click', function (e) {
      var t = e.target.closest('a, button');
      if (t && !t.closest('.pop-row .seg') && !t.matches('[data-zoom], #theme')) closeAll(null);
    });
  });
  document.addEventListener('click', function (e) { if (!e.target.closest('.pop')) closeAll(null); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(null); });
  var banner = document.getElementById('banner');
  if (D.banner) {
    banner.innerHTML = esc(D.banner) + (D.groups.some(function (g) { return g.boards.some(function (b) { return b.status === 'failure'; }); })
      ? ' <a href="#failure">See where it stopped</a>.' : '');
    banner.hidden = false;
  }
  if (D.comments && D.session) {
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
