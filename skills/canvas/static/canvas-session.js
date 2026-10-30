// A canvas that lives in a webcompanion session (canvas.py `session`): the
// session's API, its live stream, the state of the Claude session that owns
// it, and, on a journey canvas (`reruns`), Re-run on every group and Re-run
// all in the toolbar.
//
// The page is the session's renderer, served at /s/<sid>/assets/index.html,
// so the session's routes are one folder up and same-origin: the daemon's
// owner check passes for a page on its own origin (contract.md, "Who may
// write"). Nothing typed on the page becomes a command: Re-run sends the
// group's id, which the Claude session checks against the journey's own
// feature list before it runs the one journey command it knows.
//
// Live state is items the journey tool writes (skills/journey):
//   run/<group id>   {state: queued|running|passed|failed, at, error?}
//   claude/status    {state, label, at}        who answers, and how
//   canvas/build     {built, features}         a publish: the page reloads
// and the threads, which canvas-comments.js folds into comments. The stream
// (GET stream) says when either changes; a poll every 60 s covers a stream
// that a proxy cut.
//
// This fragment runs inside the page's closure (canvas-page.js) and sets
// `session`, which canvas-comments.js uses.
var session = null;
if (DATA.session && /^\/s\/[^\/]+\/assets\//.test(location.pathname)) {
  session = (function () {
    var BASE = location.pathname.replace(/assets\/.*$/, '');
    var HEADERS = { 'X-WebCompanion-Contract': '1' };
    var listeners = { item: [], thread: [], online: [] };
    var items = {};
    function on(what, fn) { listeners[what].push(fn); }
    function emit(what, a, b) { listeners[what].forEach(function (fn) { fn(a, b); }); }

    function call(method, path, body) {
      var opts = { method: method, headers: {}, cache: 'no-store' };
      for (var k in HEADERS) opts.headers[k] = HEADERS[k];
      if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
      return fetch(BASE + path, opts).then(function (r) {
        if (!r.ok) {
          return r.text().then(function (t) { var e = new Error((t || '').trim() || 'HTTP ' + r.status); e.status = r.status; throw e; });
        }
        return r.status === 204 ? {} : r.json();
      });
    }
    function enc(anchor) { return encodeURIComponent(anchor); }

    // ── Items: run states, Claude's state, the build ──
    function gotItem(anchor, env) {
      var body = env && env.body;
      items[anchor] = body || null;
      emit('item', anchor, body || null);
    }
    function loadItems() {
      return call('GET', 'items').then(function (all) {
        Object.keys(all || {}).forEach(function (a) { gotItem(a, all[a]); });
        emit('online', true);
      }, function () { emit('online', false); });
    }
    function loadItem(anchor) {
      return call('GET', 'items/' + enc(anchor)).then(function (env) { gotItem(anchor, env); }, function (e) {
        if (e.status === 404) gotItem(anchor, null);
      });
    }

    // ── The stream ──
    var es = null;
    function stream() {
      if (!window.EventSource) return;
      es = new EventSource(BASE + 'stream');
      es.addEventListener('item-changed', function (e) {
        var d = JSON.parse(e.data || '{}');
        if (d.initial || !d.anchor) return;
        if (d.version === 0) gotItem(d.anchor, null); else loadItem(d.anchor);
      });
      es.addEventListener('thread-changed', function (e) {
        var d = JSON.parse(e.data || '{}');
        if (!d.initial && d.anchor) emit('thread', d.anchor);
      });
      es.addEventListener('thread-deleted', function (e) {
        var d = JSON.parse(e.data || '{}');
        if (d.anchor) emit('thread', d.anchor);
      });
      es.addEventListener('connected', function () { emit('online', true); });
      es.onerror = function () { emit('online', false); };
    }
    setInterval(function () { if (document.visibilityState === 'visible') { loadItems(); emit('thread', null); } }, 60000);
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') { loadItems(); emit('thread', null); } });

    // ── Claude's state, in the toolbar ──
    var claudeEl = document.getElementById('s-claude');
    function showClaude(st) {
      if (!claudeEl) return;
      var state = st && st.state || 'asleep';
      claudeEl.className = 's-claude s-' + state;
      claudeEl.textContent = 'Claude: ' + (st && st.label || 'asleep · Send wakes it');
    }
    on('item', function (a, body) { if (a === 'claude/status') showClaude(body); });
    showClaude(null);

    // ── A publish: new boards. Reload, unless a comment is being written. ──
    var reloadBtn = null;
    function busy() { return !!document.querySelector('.c-pop.open textarea'); }
    function newBoards(body) {
      if (!body || !body.built || !DATA.built || body.built <= DATA.built) return;
      if (!busy()) { location.reload(); return; }
      if (reloadBtn) return;
      var banner = document.getElementById('banner');
      banner.innerHTML = 'New boards were published. <button type="button" id="s-reload">Reload</button>';
      banner.hidden = false;
      reloadBtn = document.getElementById('s-reload');
      reloadBtn.addEventListener('click', function () { location.reload(); });
    }
    on('item', function (a, body) { if (a === 'canvas/build') newBoards(body); });

    // ── Re-run ──
    var RERUNS = !!DATA.session.reruns;
    var STATE_WORD = { queued: 'Queued', running: 'Running…', passed: 'Passed', failed: 'Failed' };
    function when(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }); }
    function showRun(id, body) {
      document.querySelectorAll('[data-run="' + id + '"]').forEach(function (chip) {
        var st = body && body.state;
        chip.hidden = !STATE_WORD[st];
        chip.className = 'run-chip run-' + (st || 'none');
        chip.textContent = STATE_WORD[st] ? STATE_WORD[st] + (body.at ? ' ' + when(body.at) : '') : '';
        chip.title = body && body.error ? body.error : '';
      });
      document.querySelectorAll('[data-rerun="' + id + '"]').forEach(function (b) {
        b.disabled = !!body && (body.state === 'queued' || body.state === 'running');
      });
    }
    on('item', function (a, body) { if (a.indexOf('run/') === 0) showRun(a.slice(4), body); });
    var lastError = '';
    function rerun(ids) {
      var at = new Date().toISOString();
      ids.forEach(function (id) { showRun(id, { state: 'queued', at: at }); });
      return call('POST', 'api/submit', { anchor: '__general__', text: JSON.stringify({ type: 'rerun', features: ids, at: at }) })
        .then(function () {
          return Promise.all(ids.map(function (id) { return call('PUT', 'items/' + enc('run/' + id), { state: 'queued', at: at }); }));
        })
        .catch(function (e) {
          lastError = 'Re-run not sent: ' + e.message;
          ids.forEach(function (id) { showRun(id, items['run/' + id] || null); });
          alert(lastError);
        });
    }
    var groupIds = DATA.groups.map(function (g) { return g.id; }).filter(Boolean);
    if (RERUNS) {
      var all = document.getElementById('s-rerun-all');
      if (all) all.addEventListener('click', function () {
        if (confirm('Run all ' + groupIds.length + ' features again and publish the canvas?')) rerun(groupIds);
      });
    }

    stream();
    loadItems();
    return {
      base: BASE, call: call, enc: enc, on: on, items: function () { return items; }, rerun: rerun,
      groupIds: groupIds, reruns: RERUNS
    };
  })();
  // Re-run on a group's title: the title row sits in the labels layer, above the surface.
  if (session.reruns) {
    layer.addEventListener('pointerdown', function (e) { if (e.target.closest('.rerun')) e.stopPropagation(); }, true);
    layer.addEventListener('click', function (e) {
      var b = e.target.closest('.rerun');
      if (!b || b.disabled) return;
      e.stopPropagation();
      session.rerun([b.getAttribute('data-rerun')]);
    });
  }
}
