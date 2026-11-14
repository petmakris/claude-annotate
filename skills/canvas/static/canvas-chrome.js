// The page's chrome, built from the canvas data before canvas-page.js runs:
// the title bar and its toolbar, the group links, the banner, and the comment
// layers when the canvas takes comments. The template itself stays the same
// for every canvas, so a project can vendor it and only put its data in.
(function () {
  var D = JSON.parse(document.getElementById('canvas-data').textContent);
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  document.title = D.title;
  // Lucide icons (ISC), drawn inline so the page needs nothing else.
  var ICONS = {
    both: '<path d="M18 8V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h8"/><path d="M10 19v-3.96 3.15"/><path d="M7 19h5"/><rect width="6" height="10" x="16" y="12" rx="2"/>',
    desktop: '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
    phone: '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
    collapse: '<path d="m7 20 5-5 5 5"/><path d="m7 4 5 5 5-5"/>',
    expand: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
    changed: '<path d="M12 3v14"/><path d="M5 10h14"/><path d="M5 21h14"/>',
    out: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><path d="M8 11h6"/>',
    in: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><path d="M11 8v6"/><path d="M8 11h6"/>',
    fit: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
    theme: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    comment: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M12 7v6"/><path d="M9 10h6"/>',
    comments: '<path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"/><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"/>',
    send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    rerun: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
  };
  function ic(name) {
    return '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>';
  }
  // An icon button: what it does is its tooltip and its accessible name.
  // A class in `attrs` replaces the plain "ib" (an element keeps only its first class attribute).
  function btn(attrs, icon, title, extra) {
    if (!/class="/.test(attrs)) attrs = 'class="ib" ' + attrs;
    return '<button type="button" ' + attrs + ' title="' + esc(title) + '" aria-label="' + esc(title) + '">' + ic(icon) + (extra || '') + '</button>';
  }
  var sep = '<span class="sep" aria-hidden="true"></span>';

  // The page has one strip along its top, every control a click away: no menus.
  // Left: the name, its status and the run. Then collapse and expand every section,
  // the view, and the zoom. Right: Claude and the comments.
  // Each id stays the same, so the scripts find what they did.
  var status = D.status ? '<span class="chip chip-' + esc(D.status.kind) + '">' + esc(D.status.label) + '</span>' : '';
  var noun = D.groupNoun || (D.session ? 'features' : 'groups');
  var nav = D.groups.length > 1 ? '<span class="sections">' +
    btn('id="fold-all"', 'collapse', 'Collapse every section') +
    btn('id="unfold-all"', 'expand', 'Expand every section') + '</span>' : '';

  var labels = D.labels || [];
  var seg = '';
  if (labels.length > 1) {
    var iconOf = function (l) { return /phone/i.test(l) ? 'phone' : /desk/i.test(l) ? 'desktop' : null; };
    seg = '<span class="seg" role="group" aria-label="Shots">' +
      btn('data-shown="all" aria-pressed="true"', 'both', labels.length === 2 ? 'Both: ' + labels.join(' and ') : 'All shots') +
      labels.map(function (l) {
        return iconOf(l) ? btn('data-shown="' + esc(l) + '" aria-pressed="false"', iconOf(l), l + ' only')
          : '<button type="button" class="tb" data-shown="' + esc(l) + '" aria-pressed="false">' + esc(l) + '</button>';
      }).join('') + '</span>';
  }

  // What changed since an earlier capture: the Changed only button, its count on it.
  // A board with no `change` counts as unchanged; the failure board is no board.
  var CH = D.changes, changed = '', count = '';
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
    count = moved + ' of ' + all + ' board' + (all === 1 ? '' : 's') + ' changed' + (CH.since ? ' since ' + CH.since : '') +
      (fresh ? ' (' + fresh + ' new)' : '');
    changed = btn('id="chg-only" class="ib chg-only" aria-pressed="false"', 'changed', 'Changed only: ' + count, '<span class="n chg-n">' + moved + '</span>');
  }

  // Everything about the capture, on the info button's tooltip.
  var info = [D.subtitle].concat(D.meta || []).concat(count ? [count] : []).filter(Boolean);
  if (CH && (CH.removed || []).length) {
    info.push(CH.removed.length + ' removed' + (CH.since ? ' since ' + CH.since : '') + ': ' +
      CH.removed.map(function (r) { return (r.number ? r.number + ' ' : '') + r.title + (r.group ? ' (' + r.group + ')' : ''); }).join(', '));
  }
  var infoBtn = info.length ? '<span class="ib info" tabindex="0" role="note" title="' + esc(info.join('\n')) + '" aria-label="' + esc(info.join('. ')) + '">' + ic('info') + '</span>' : '';

  var claude = '';
  if (D.session) {
    claude = '<span class="s-claude" id="s-claude" role="status" title="The Claude session that answers this canvas"></span>';
    if (D.comments) {
      claude += '<span class="c-status" id="c-status" role="status"></span>' +
        btn('id="c-mode" class="ib c-toggle" aria-pressed="false"', 'comment', 'Comment on a screenshot (C)') +
        btn('id="c-panel-btn" class="ib c-toggle" aria-pressed="false"', 'comments', 'Every comment on this canvas', '<span class="n" id="c-count"></span>') +
        btn('id="c-send" class="ib s-send" disabled', 'send', 'Send the comments Claude has not answered to the Claude session of this canvas', '<span class="n" id="c-send-n"></span>');
    }
    if (D.session.reruns) claude += btn('id="s-rerun-all"', 'rerun', 'Re-run all: run every feature again and publish the canvas');
  }

  document.getElementById('top').innerHTML =
    '<div class="strip" role="toolbar" aria-label="Canvas">' +
    '<h1 title="' + esc(D.title) + '">' + esc(D.title) + '</h1>' + status +
    (D.session && D.session.reruns ? '<span class="run-chip run-none" id="s-run" role="status" hidden></span>' : '') +
    (nav ? sep + nav : '') + sep + changed + seg +
    btn('class="ib zoom" data-zoom="out"', 'out', 'Zoom out (−)') +
    '<button type="button" class="tb zoom zoom-label" id="zoom-label" data-zoom="actual" title="Boards at their drawn size (Shift+0)">100%</button>' +
    btn('class="ib zoom" data-zoom="in"', 'in', 'Zoom in (+)') +
    btn('class="ib zoom" data-zoom="fit"', 'fit', 'Every board in the window (Shift+1)') +
    btn('id="theme"', 'theme', 'Light or dark') + infoBtn +
    '<span class="grow"></span>' + claude + '</div>';
  document.getElementById('top').appendChild(document.getElementById('banner'));
  var banner = document.getElementById('banner');
  if (D.brief && D.brief.length && !D.banner) {
    banner.className = 'banner brief';
    banner.innerHTML = D.brief.map(function (b) {
      return '<section><h2>' + esc(b.heading) + '</h2><p>' + esc(b.text) + '</p></section>';
    }).join('');
    banner.hidden = false;
  }
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
