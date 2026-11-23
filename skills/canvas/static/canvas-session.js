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
//   claude/status    {state, session, machine, since, at}   the attached session
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
    // The canvas is a notepad: Send keeps the batch in the comments, and only a Claude Code session the user
    // attached (/journey <canvas>) answers it. Attached means that session's watcher beats (the session's
    // `poll`, read here every 20 s, so a session that died shows at once); claude/status says who it is.
    // Not attached, the pill says a batch waits and since when, and opens a card with the command to copy.
    var claudeEl = document.getElementById('s-claude'), cardEl = document.getElementById('s-attach');
    var ATTACH = '/journey ' + (DATA.session.slug || '');
    var LISTENING_MS = 90000;
    var who = null, seenAt = null, stoppedAt = null, queued = { count: 0, oldest: null };
    function ago(iso) {
      var m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
      if (m < 1) return 'just now';
      if (m < 60) return m + ' min ago';
      var h = Math.round(m / 60);
      return h < 48 ? h + ' h ago' : Math.round(h / 24) + ' days ago';
    }
    function attached() {
      return !!seenAt && Date.now() - seenAt * 1000 < LISTENING_MS && !(stoppedAt && stoppedAt >= seenAt);
    }
    function showClaude() {
      if (!claudeEl) return;
      var on = attached(), narrow = innerWidth <= 600, n = queued.count, label, title;
      if (on) {
        label = narrow ? 'Attached' : 'Claude attached';
        title = 'Answered by session ' + (who && who.session || '?') + ' on ' + (who && who.machine || '?') + '. Send delivers a batch to it at once.';
      } else if (n) {
        label = narrow ? 'Waiting · ' + ago(queued.oldest).replace(' ago', '') : 'Waiting for a session · sent ' + ago(queued.oldest);
        title = n + (n === 1 ? ' comment waits' : ' comments wait') + ' for a Claude session. Attach one with ' + ATTACH;
      } else {
        label = narrow ? 'No session' : 'No session attached';
        title = 'Send keeps your comments until a Claude session attaches with ' + ATTACH;
      }
      claudeEl.className = 's-claude ' + (on ? 's-attached' : n ? 's-waiting' : 's-detached');
      claudeEl.textContent = label;
      claudeEl.title = title;
      claudeEl.setAttribute('aria-label', 'Claude: ' + title);
      if (cardEl && !cardEl.hidden) drawCard();
    }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function drawCard() {
      var on = attached(), n = queued.count, head, body;
      if (on) {
        head = 'Claude attached';
        body = '<p>Session <b>' + esc(who && who.session || '?') + '</b> on <b>' + esc(who && who.machine || '?') + '</b> answers this canvas' +
          (who && who.since ? ', since ' + esc(new Date(who.since).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })) : '') +
          '. Send delivers your comments to it as one batch.</p>' +
          (n ? '<p>' + n + (n === 1 ? ' comment' : ' comments') + ' sent ' + esc(ago(queued.oldest)) + ' still wait for its answer.</p>' : '');
      } else {
        head = n ? 'Waiting for a session' : 'No session attached';
        body = (n ? '<p><b>' + n + (n === 1 ? ' comment' : ' comments') + '</b> sent ' + esc(ago(queued.oldest)) + ' wait here. Nothing is lost.</p>'
                  : '<p>Send keeps your comments here until a session attaches.</p>') +
          '<p>Attach a Claude Code session, on any machine:</p>';
      }
      cardEl.innerHTML = '<div class="s-attach-head"><span>' + head + '</span><button type="button" class="s-attach-close" aria-label="Close">✕</button></div>' + body +
        '<div class="s-attach-cmd"><code id="s-attach-code">' + esc(ATTACH) + '</code><button type="button" id="s-attach-copy">Copy</button></div>';
    }
    // Under the pill, its right edge with the pill's, kept inside the window.
    function place() {
      var r = claudeEl.getBoundingClientRect(), w = cardEl.offsetWidth;
      cardEl.style.top = Math.round(r.bottom + 8) + 'px';
      cardEl.style.left = Math.round(Math.max(8, Math.min(innerWidth - w - 8, r.right - w))) + 'px';
    }
    addEventListener('resize', function () { if (!cardEl.hidden) place(); });
    function copy() {
      var done = function () { var b = document.getElementById('s-attach-copy'); if (b) { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 2000); } };
      if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(ATTACH).then(done, fallback); } else fallback();
      function fallback() {
        var code = document.getElementById('s-attach-code'), r = document.createRange();
        r.selectNodeContents(code);
        var sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
        try { if (document.execCommand('copy')) done(); } catch (e) { /* the text stays selected to copy by hand */ }
      }
    }
    if (claudeEl && cardEl) {
      claudeEl.addEventListener('click', function () {
        cardEl.hidden = !cardEl.hidden;
        claudeEl.setAttribute('aria-expanded', String(!cardEl.hidden));
        if (!cardEl.hidden) { drawCard(); place(); }
      });
      cardEl.addEventListener('click', function (e) {
        if (e.target.closest('.s-attach-close')) { cardEl.hidden = true; claudeEl.setAttribute('aria-expanded', 'false'); }
        else if (e.target.closest('#s-attach-copy')) copy();
      });
    }
    function poll() {
      return call('GET', 'poll').then(function (p) {
        seenAt = p && p.watcher_seen_at || null;
        stoppedAt = p && p.watcher_stopped_at || null;
        showClaude();
      }, function () { showClaude(); });
    }
    on('item', function (a, body) { if (a === 'claude/status') { who = body; poll(); } });
    setInterval(function () { if (document.visibilityState === 'visible') poll(); }, 20000);
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') poll(); });
    addEventListener('resize', showClaude);
    // canvas-comments.js says what waits: the comments sent and not answered, and the oldest send time.
    function setQueued(count, oldest) { queued = { count: count, oldest: oldest }; showClaude(); }
    showClaude();
    poll();

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
    on('item', function (a, body) { if (a.indexOf('run/') === 0 && a !== 'run/__journey__') showRun(a.slice(4), body); });

    // The whole run, beside the title, whoever started it (Re-run here, or `<app> journey` in a terminal):
    // run/__journey__ {state: running|passed|failed, done, failed, total, startedAt, at}.
    var runEl = document.getElementById('s-run'), runBody = null;
    function minutes(from, to) { var m = Math.max(0, Math.round((to - Date.parse(from)) / 60000)); return m + ' min'; }
    function showWhole() {
      var b = runBody;
      if (!runEl) return;
      if (!b || !b.state) { runEl.hidden = true; return; }
      var n = b.done + ' of ' + b.total + ' features';
      var bad = b.failed ? ' · ' + b.failed + ' failed' : '';
      var took = b.startedAt ? ' · ' + minutes(b.startedAt, b.state === 'running' ? Date.now() : Date.parse(b.at)) : '';
      runEl.hidden = false;
      runEl.className = 'run-chip run-' + (b.state === 'running' ? 'running' : b.failed ? 'failed' : 'passed');
      // A phone has room for the short form only: "Running 9/16".
      runEl.textContent = innerWidth <= 600
        ? (b.state === 'running' ? 'Running ' : b.failed ? 'Failed ' : 'Passed ') + b.done + '/' + b.total
        : (b.state === 'running' ? 'Running · ' + n : (b.failed ? 'Run failed · ' : 'Run passed · ') + n) + bad + took;
      runEl.title = b.state === 'running' ? 'A journey run is going on: each feature\'s chip shows its state' : 'The last journey run, ended ' + when(b.at);
    }
    on('item', function (a, body) { if (a === 'run/__journey__') { runBody = body; showWhole(); } });
    setInterval(function () { if (runBody && runBody.state === 'running') showWhole(); }, 30000);
    addEventListener('resize', showWhole);
    var lastError = '';
    // Re-run all also says `all`: the session then runs every feature the app
    // has now, new ones the canvas does not show yet included.
    function rerun(ids, every) {
      var at = new Date().toISOString();
      ids.forEach(function (id) { showRun(id, { state: 'queued', at: at }); });
      var ev = { type: 'rerun', features: ids, at: at };
      if (every) ev.all = true;
      return call('POST', 'api/submit', { anchor: '__general__', text: JSON.stringify(ev) })
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
        if (confirm('Run every feature again, new ones too, and publish the canvas?')) rerun(groupIds, true);
      });
    }

    stream();
    loadItems();
    return {
      base: BASE, call: call, enc: enc, on: on, items: function () { return items; }, rerun: rerun,
      setQueued: setQueued, attached: attached,
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
