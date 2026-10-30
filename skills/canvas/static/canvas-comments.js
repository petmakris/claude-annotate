// Comments pinned on the canvas's shots, like Figma's. Lifted from lomem's
// journey canvas (canvas-comments.ts, ADR-058).
//
// The Comment button (or C) turns comment mode on: a click or tap on any shot
// drops a numbered pin at that point and opens a box to type or speak in. Pins
// keep one size on screen at every zoom; hovering one shows its text, clicking
// it opens its thread (edit, resolve, delete, reply). The Comments panel lists
// this canvas's comments, filtered by status (and scope, on a canvas that
// shares its comments), and flies to a pin.
//
// The comments live in the canvas's webcompanion session (canvas-session.js):
// every change is one message in the thread of the board it is about, carrying
// its op, and the page folds every thread through canvas-store.js. An op made
// while the daemon cannot be reached waits in localStorage and is sent, in
// order, once it answers again; each carries its own id as source_event_id,
// so a resend is never stored twice. Send to Claude sends the comments Claude
// has not answered as one event to the Claude session that owns the canvas
// (claude-annotate's /journey), which answers in the same threads. A spoken
// comment is written down in the browser by Azure's speech SDK, with a
// ten-minute token from the daemon's /api/speech/token (no key in the page).
//
// This fragment runs inside the page's closure (canvas-page.js) and uses its
// view, box, shotEls, setView, animateTo, setShown, hooks and session. It runs
// only on a canvas whose data names comments and that is open in its session.
if (DATA.comments && session) {
  (function () {
    var CFG = DATA.comments, APP = CFG.canvas, SID = DATA.session.sid;
    var APP_NAME = CFG.name || DATA.title;
    // A canvas that shares its comments with others (Mealy's and Billpod's) has a scope choice.
    var SCOPES = CFG.scopes || null;
    var applyOp = CanvasStore.applyOp, fold = CanvasStore.fold, waiting = CanvasStore.waiting;
    var pointInBox = M.pointInBox, pinOnScreen = M.pinOnScreen, fitView = M.fitView;
    var QUEUE_KEY = 'canvas-queue:' + SID;
    var pinsEl = document.getElementById('pins'), pop = document.getElementById('c-pop'), hoverEl = document.getElementById('c-hover');
    var panel = document.getElementById('c-panel'), list = document.getElementById('c-list');
    var modeBtn = document.getElementById('c-mode'), panelBtn = document.getElementById('c-panel-btn');
    var statusEl = document.getElementById('c-status'), countEl = document.getElementById('c-count');
    var sendBtn = document.getElementById('c-send');

    function readJson(k, fallback) { try { var v = JSON.parse(load(k) || 'null'); return v === null ? fallback : v; } catch (e) { return fallback; } }
    // Every thread as the daemon last sent it, and the ops not sent yet ({anchor, op}).
    var threads = {};
    var queue = readJson(QUEUE_KEY, []);
    var online = null, flushing = false, lastError = '', loaded = false;
    var store = { version: 1, comments: [] }, mine = [];
    function uid(p) { return p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
    function escHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
    // Claude's answers link mockups and boards: links open, everything else stays text.
    function richText(s) {
      return escHtml(s).replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)\]'"]|#board-[A-Za-z0-9\/._-]+)/g, function (u) {
        var ext = u.charAt(0) !== '#';
        return '<a href="' + u + '"' + (ext ? ' target="_blank" rel="noopener"' : '') + '>' + u + '</a>';
      });
    }
    function when(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    // The thread a comment's ops go in: its board's.
    function anchorOf(board) { return typeof board === 'number' ? 'board-' + board : String(board); }

    // What sits where: each shot's image on the surface, by board and size.
    var shotBox = {};
    // A shot's box is its whole image (h tall); only its frame (frameH) is drawn.
    function measureShots() {
      shotBox = {};
      shotEls.forEach(function (s) {
        var b = s.box, o = b ? { el: s.el, x: b.x, y: b.y, w: b.w, h: b.h, frameH: b.frameH, shown: true } : { el: s.el, shown: false };
        shotBox[boardKey(s.board.data) + '|' + s.data.key] = o;
      });
    }

    // ── State: every thread's ops, plus the ops not sent yet ──
    function rebuild() {
      var s = fold(threads).store, unsent = {};
      for (var i = 0; i < queue.length; i++) {
        var q = queue[i].op;
        var r = applyOp(s, q, q.at || new Date().toISOString());
        s = r.store;
        var id = q.id || (q.comment && q.comment.id);
        if (id) unsent[id] = true;
      }
      store = s;
      mine = store.comments.filter(function (c) { return c.app === APP; }).sort(function (a, b) { return a.number - b.number; });
      mine.forEach(function (c) { c._unsent = !!unsent[c.id]; });
      var open = mine.filter(function (c) { return c.status === 'open'; }).length;
      countEl.textContent = open ? '(' + open + ')' : '';
      var toSend = unanswered();
      sendBtn.disabled = !toSend.length || online === false;
      sendBtn.textContent = 'Send to Claude' + (toSend.length ? ' (' + toSend.length + ')' : '');
      showStatus();
      drawPins();
      if (panel.classList.contains('open')) drawList();
      if (thread && !byId(thread)) closePop();
      else if (thread && !editing) drawThread();
    }
    function byId(id) { for (var i = 0; i < mine.length; i++) if (mine[i].id === id) return mine[i]; return null; }
    // Waiting for Claude and not sent since Petros last wrote on it.
    function unanswered() { return mine.filter(function (c) { return waiting(c) && !c._unsent && !(c.sentAt && c.sentAt >= c.askedAt); }); }
    function showStatus() {
      var n = queue.length, text = '';
      if (online === false) text = 'Cannot reach webcompanion' + (n ? ' · ' + n + ' unsent, kept here' : '');
      else if (n) text = n + ' unsent';
      if (lastError) text = (text ? text + ' · ' : '') + lastError;
      statusEl.textContent = text;
      statusEl.classList.toggle('on', !!text);
      statusEl.title = online === false ? 'Comments made now are kept in this browser and sent when the daemon answers again.' : '';
    }
    function saveQueue() { save(QUEUE_KEY, JSON.stringify(queue)); }
    // What a message says to anyone reading the thread without the canvas.
    function summary(op) {
      var c = byId(op.id || (op.comment && op.comment.id)), n = c ? '#' + c.number : 'a comment';
      if (op.kind === 'create') return op.comment.text;
      if (op.kind === 'reply') return op.reply.text;
      if (op.kind === 'editReply') return 'Edited a reply on ' + n + ': ' + op.text;
      if (op.kind === 'deleteReply') return 'Deleted a reply on ' + n;
      if (op.kind === 'delete') return 'Deleted ' + n;
      if (op.kind === 'move') return 'Moved ' + n + ' to ' + op.board;
      if (op.status === 'resolved') return 'Resolved ' + n;
      if (op.status === 'open') return 'Reopened ' + n;
      if (op.text) return 'Edited ' + n + ': ' + op.text;
      if (op.sentAt) return 'Sent ' + n + ' to Claude';
      return 'Changed ' + n;
    }
    function send(op, board) {
      op.at = new Date().toISOString();
      op.uid = uid('o');
      queue.push({ anchor: anchorOf(board), op: op, text: summary(op) });
      saveQueue();
      rebuild();
      flush();
    }
    function flush() {
      if (flushing || !queue.length) return;
      flushing = true;
      var q = queue[0];
      session.call('POST', 'threads/' + session.enc(q.anchor), { text: q.text || 'op', role: 'user', op: q.op, source_event_id: q.op.uid })
        .then(function () {
          online = true;
          lastError = '';
          return session.call('GET', 'threads/' + session.enc(q.anchor)).then(function (t) { threads[q.anchor] = t; });
        }, function (e) {
          if (!e.status || e.status >= 500) throw e;
          // Refused (4xx): it could never succeed, so it is dropped and said.
          lastError = 'Not saved: ' + e.message;
        })
        .then(function () {
          queue.shift();
          saveQueue();
          flushing = false;
          rebuild();
          if (queue.length) flush();
        })
        .catch(function () { online = false; flushing = false; rebuild(); });
    }
    function refresh(anchor) {
      var got = anchor
        ? session.call('GET', 'threads/' + session.enc(anchor)).then(function (t) {
          if (t && t.messages && t.messages.length) threads[anchor] = t; else delete threads[anchor];
        })
        : session.call('GET', 'threads').then(function (all) { threads = all || {}; });
      got.then(function () { online = true; loaded = true; rebuild(); flush(); }, function () { online = false; showStatus(); });
    }
    session.on('thread', function (anchor) { refresh(anchor); });
    session.on('online', function (up) { if (up && online === false) { online = true; flush(); rebuild(); } });
    window.addEventListener('online', function () { refresh(null); });

    // ── Send to Claude: the comments it has not answered, as one event ──
    sendBtn.addEventListener('click', function () {
      var ids = unanswered().map(function (c) { return c.id; });
      if (!ids.length) return;
      sendBtn.disabled = true;
      var at = new Date().toISOString();
      session.call('POST', 'api/submit', { anchor: '__general__', text: JSON.stringify({ type: 'comments', canvas: APP, ids: ids, at: at }) })
        .then(function () {
          lastError = '';
          ids.forEach(function (id) { var c = byId(id); if (c) send({ kind: 'update', id: id, sentAt: at }, c.board); });
        }, function (e) { lastError = 'Not sent to Claude: ' + e.message; rebuild(); });
    });

    // ── Pins ──
    var pinEls = {}, draft = null, thread = null, editing = false, filterStatus = 'open', filterScope = 'all';
    function pinShown(c) { return filterStatus === 'all' || c.status === filterStatus || c.id === thread; }
    function drawPins() {
      pinsEl.innerHTML = '';
      pinEls = {};
      mine.forEach(function (c) {
        if (!pinShown(c)) return;
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'pin' + (c.status === 'resolved' ? ' resolved' : '') + (c._unsent ? ' unsent' : '') + (c.id === thread ? ' active' : '');
        b.textContent = c.number;
        b.setAttribute('data-id', c.id);
        b.setAttribute('aria-label', 'Comment ' + c.number);
        pinsEl.appendChild(b);
        pinEls[c.id] = { el: b, c: c };
      });
      if (draft) {
        var d = document.createElement('button');
        d.type = 'button';
        d.className = 'pin draft';
        d.textContent = '+';
        pinsEl.appendChild(d);
        draft.el = d;
      }
      positionPins();
    }
    // The pin's tip (its bottom-left corner) sits on the point.
    function pinXY(c) {
      var o = shotBox[c.board + '|' + c.shot];
      // A point on the part of a full-page shot the frame crops away has no pin on the canvas.
      if (!o || !o.shown || c.fy * o.h > o.frameH + 0.5) return null;
      return pinOnScreen(view, o.x, o.y, o.w, o.h, c.fx, c.fy);
    }
    function positionPins() {
      var W = box.w, H = box.h;
      function put(el, c) {
        var p = pinXY(c);
        var on = !!p && p.x > -30 && p.x < W + 30 && p.y > -30 && p.y < H + 30;
        if (on) el.style.transform = 'translate(' + Math.round(p.x) + 'px,' + Math.round(p.y - 28) + 'px)';
        el.style.visibility = on ? 'visible' : 'hidden';
      }
      for (var id in pinEls) put(pinEls[id].el, pinEls[id].c);
      if (draft && draft.el) put(draft.el, draft);
      placePop();
    }

    // ── Comment mode ──
    var mode = false;
    function setMode(on) {
      mode = !!on;
      canvas.classList.toggle('commenting', mode);
      modeBtn.setAttribute('aria-pressed', String(mode));
    }
    modeBtn.addEventListener('click', function () { setMode(!mode); if (!mode) closePop(); });

    function placeDraft(e, shot) {
      var o = shotBox[shot.getAttribute('data-board') + '|' + shot.getAttribute('data-shot')];
      if (!o || !o.shown) return;
      var r = shot.getBoundingClientRect();
      var p = pointInBox(e.clientX, e.clientY, r.left, r.top, r.width, o.h * view.z);
      if (!p) return;
      closePop();
      draft = {
        id: uid('c'), board: shot.hasAttribute('data-board-num') ? parseInt(shot.getAttribute('data-board'), 10) : shot.getAttribute('data-board'), shot: shot.getAttribute('data-shot'),
        boardTitle: shot.getAttribute('data-title'), chapter: shot.getAttribute('data-chapter'), fx: p.fx, fy: p.fy,
        scope: 'app'
      };
      drawPins();
      openDraft();
    }

    // ── The box: a new comment ──
    function micButton() { return '<button type="button" class="c-mic" data-c="mic" title="Speak: press to record, press again to stop" aria-label="Speak">🎤</button>'; }
    function scopeSeg(scope) {
      if (!SCOPES) return '';
      return '<span class="c-seg" role="group" aria-label="Scope">' +
        '<button type="button" data-cscope-pick="app" aria-pressed="' + (scope !== 'both') + '">' + escHtml(SCOPES.app) + '</button>' +
        '<button type="button" data-cscope-pick="both" aria-pressed="' + (scope === 'both') + '">' + escHtml(SCOPES.both) + '</button></span>';
    }
    function scopeText(c) { return SCOPES ? '<span>' + escHtml(c.scope === 'both' ? SCOPES.both : SCOPES.app) + '</span>' : ''; }
    function whereText(c) {
      var where = typeof c.board === 'number' ? 'Board ' + c.board + ' ' + (c.boardTitle || '') : (c.boardTitle || c.board) + (c.chapter ? ' · ' + c.chapter : '');
      return where + (LABELS.length > 1 ? ' · ' + c.shot : '');
    }
    // Where the comment stands with Claude: sent and waiting, not sent yet, or answered.
    function claudeState(c) {
      if (c.status !== 'open') return '';
      if (!waiting(c)) return '<span class="c-answered">Claude answered</span>';
      if (c.sentAt && c.sentAt >= c.askedAt) return '<span class="c-waiting">Sent to Claude · waiting</span>';
      return '<span class="c-unsent-claude">Not sent to Claude</span>';
    }
    // A comment whose board this canvas no longer has (renamed, or its feature dropped it) stays listed, marked.
    function gone(c) { return !shotBox[c.board + '|' + c.shot]; }
    function openDraft() {
      thread = null;
      pop.innerHTML = '<div class="c-where">' + escHtml(whereText(draft)) + '</div>' +
        '<textarea id="c-text" placeholder="Add a comment" aria-label="Comment"></textarea>' +
        '<div class="c-row">' + scopeSeg('app') + '<span class="grow"></span>' + micButton() + '</div>' +
        '<div class="c-row"><span class="c-note" id="c-note"></span><span class="grow"></span>' +
        '<button type="button" data-c="cancel">Cancel</button><button type="button" class="primary" data-c="post">Post</button></div>';
      pop.classList.add('open');
      pop.setAttribute('data-kind', 'draft');
      placePop();
      var t = document.getElementById('c-text');
      setTimeout(function () { t.focus(); }, 0);
    }
    function post() {
      var t = document.getElementById('c-text'), text = t ? t.value.trim() : '';
      if (!draft || !text || recording) return;
      var c = draft;
      draft = null;
      closePop();
      send({ kind: 'create', comment: { id: c.id, app: APP, board: c.board, boardTitle: c.boardTitle, chapter: c.chapter, shot: c.shot,
        fx: c.fx, fy: c.fy, text: text, scope: c.scope } }, c.board);
    }

    // ── The thread: a comment and its replies ──
    function openThread(id) {
      var c = byId(id);
      if (!c) return;
      if (draft) { draft = null; }
      thread = id;
      editing = false;
      drawPins();
      drawThread();
      pop.classList.add('open');
      pop.setAttribute('data-kind', 'thread');
      placePop();
    }
    function drawThread(editTarget) {
      var c = byId(thread);
      if (!c) return;
      var keep = document.getElementById('c-reply'), kept = keep ? keep.value : '';
      var head = '<div class="c-head"><span class="c-num' + (c.status === 'resolved' ? ' resolved' : '') + '">' + c.number + '</span>' +
        '<span class="c-title">' + escHtml(whereText(c)) + '</span>' +
        '<button type="button" data-c="resolve" title="' + (c.status === 'open' ? 'Mark resolved' : 'Open again') + '">' + (c.status === 'open' ? '✓ Resolve' : 'Reopen') + '</button>' +
        '<button type="button" data-c="close" aria-label="Close">✕</button></div>';
      var meta = '<div class="c-meta"><span class="c-chip ' + c.status + '">' + c.status + '</span>' +
        scopeText(c) + '<span>' + escHtml(when(c.createdAt)) + '</span>' +
        (c.chapter ? '<span>' + escHtml(c.chapter) + '</span>' : '') + (c._unsent ? '<span>unsent</span>' : '') + claudeState(c) + '</div>';
      var body;
      if (editTarget === 'comment') {
        body = '<div class="c-msg">' + meta + '<textarea id="c-edit">' + escHtml(c.text) + '</textarea>' +
          '<div class="c-row">' + scopeSeg(c.scope) + '<span class="grow"></span>' + micButton() + '</div>' +
          '<div class="c-row"><span class="c-note" id="c-note"></span><span class="grow"></span><button type="button" data-c="edit-cancel">Cancel</button>' +
          '<button type="button" class="primary" data-c="edit-save">Save</button></div></div>';
      } else {
        body = '<div class="c-msg">' + meta + '<div class="c-text">' + escHtml(c.text) + '</div>' +
          '<div class="c-meta"><button type="button" data-c="edit">Edit</button><button type="button" data-c="delete">Delete</button></div></div>';
      }
      c.replies.forEach(function (r) {
        if (editTarget === r.id) {
          body += '<div class="c-msg" data-reply="' + escHtml(r.id) + '"><textarea id="c-edit">' + escHtml(r.text) + '</textarea>' +
            '<div class="c-row"><span class="c-note" id="c-note"></span><span class="grow"></span>' + micButton() +
            '<button type="button" data-c="edit-cancel">Cancel</button><button type="button" class="primary" data-c="reply-save">Save</button></div></div>';
        } else {
          var claude = r.by === 'claude';
          body += '<div class="c-msg' + (claude ? ' c-claude' : '') + '" data-reply="' + escHtml(r.id) + '"><div class="c-meta"><span>' + (claude ? '<b>Claude</b>' : 'Reply') + ' · ' + escHtml(when(r.createdAt)) + (r.updatedAt ? ' · edited' : '') + '</span></div>' +
            '<div class="c-text">' + richText(r.text) + '</div>' +
            (claude ? '' : '<div class="c-meta"><button type="button" data-c="reply-edit">Edit</button><button type="button" data-c="reply-delete">Delete</button></div>') + '</div>';
        }
      });
      var reply = editTarget ? '' : '<textarea id="c-reply" placeholder="Reply" aria-label="Reply"></textarea>' +
        '<div class="c-row"><span class="c-note" id="c-note"></span><span class="grow"></span>' + micButton() +
        '<button type="button" class="primary" data-c="reply">Reply</button></div>';
      pop.innerHTML = head + body + reply;
      editing = !!editTarget;
      editScope = c.scope;
      var r2 = document.getElementById('c-reply');
      if (r2 && kept) r2.value = kept;
      var ed = document.getElementById('c-edit');
      if (ed) setTimeout(function () { ed.focus(); }, 0);
    }
    var editScope = 'app';
    function closePop() {
      stopRecording(true);
      pop.classList.remove('open');
      pop.innerHTML = '';
      var had = draft || thread;
      draft = null; thread = null; editing = false;
      if (had) drawPins();
    }
    // Next to its pin, kept inside the window (a bottom sheet on a phone, in CSS).
    function placePop() {
      if (!pop.classList.contains('open')) return;
      var c = draft || byId(thread);
      var p = c && pinXY(c);
      var w = pop.offsetWidth, h = pop.offsetHeight;
      var x = p ? box.left + p.x + 36 : box.left + box.w - w - 12;
      var y = p ? box.top + p.y - 40 : box.top + 12;
      if (x + w > innerWidth - 8) x = p ? box.left + p.x - w - 12 : innerWidth - w - 8;
      x = Math.max(8, x);
      y = Math.max(8, Math.min(y, innerHeight - h - 8));
      pop.style.left = Math.round(x) + 'px';
      pop.style.top = Math.round(y) + 'px';
    }

    pop.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      var k = b.getAttribute('data-c'), pick = b.getAttribute('data-cscope-pick');
      var c = thread && byId(thread);
      if (pick) {
        if (draft) draft.scope = pick; else editScope = pick;
        b.parentNode.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
        return;
      }
      if (k === 'mic') return toggleRecording(b);
      if (k === 'cancel' || k === 'close') return closePop();
      if (k === 'post') return post();
      if (!c) return;
      var replyEl = b.closest('[data-reply]'), rid = replyEl && replyEl.getAttribute('data-reply');
      if (k === 'resolve') send({ kind: 'update', id: c.id, status: c.status === 'open' ? 'resolved' : 'open' }, c.board);
      else if (k === 'delete') { if (confirm('Delete comment ' + c.number + ' and its replies?')) { send({ kind: 'delete', id: c.id }, c.board); closePop(); } }
      else if (k === 'edit') { drawThread('comment'); }
      else if (k === 'edit-cancel') drawThread();
      else if (k === 'edit-save') {
        var t = document.getElementById('c-edit').value.trim();
        if (!t || recording) return;
        editing = false;
        send({ kind: 'update', id: c.id, text: t, scope: editScope }, c.board);
        drawThread();
      }
      else if (k === 'reply-edit') { drawThread(rid); }
      else if (k === 'reply-save') {
        var rt = document.getElementById('c-edit').value.trim();
        if (!rt || recording) return;
        editing = false;
        send({ kind: 'editReply', id: c.id, replyId: rid, text: rt }, c.board);
        drawThread();
      }
      else if (k === 'reply-delete') { if (confirm('Delete this reply?')) send({ kind: 'deleteReply', id: c.id, replyId: rid }, c.board); }
      else if (k === 'reply') {
        var input = document.getElementById('c-reply'), text = input.value.trim();
        if (!text || recording) return;
        input.value = '';
        send({ kind: 'reply', id: c.id, reply: { id: uid('r'), text: text } }, c.board);
      }
    });
    // Enter posts, Shift+Enter is a new line; Esc closes.
    pop.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePop(); return; }
      if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
      var id = e.target.id, k = id === 'c-text' ? 'post' : id === 'c-reply' ? 'reply' : id === 'c-edit' ? (pop.querySelector('[data-c="edit-save"]') ? 'edit-save' : 'reply-save') : '';
      if (!k) return;
      e.preventDefault();
      var b = pop.querySelector('[data-c="' + k + '"]');
      if (b) b.click();
    });

    // ── Speaking: Azure's browser SDK writes it down, English or Greek per phrase ──
    // The SDK (378 KB, vendor/ next to the page) loads the first time the mic is pressed.
    var recording = null, sdkP = null, tok = null, tokUntil = 0;
    function note(text, bad) {
      var n = document.getElementById('c-note');
      if (n) { n.textContent = text; n.classList.toggle('bad', !!bad); }
    }
    function target() { return document.getElementById('c-edit') || document.getElementById('c-text') || document.getElementById('c-reply'); }
    function loadSdk() {
      if (window.SpeechSDK) return Promise.resolve(window.SpeechSDK);
      if (!sdkP) {
        sdkP = new Promise(function (resolve, reject) {
          var sc = document.createElement('script');
          sc.src = 'vendor/speech-sdk.min.js';
          sc.onload = function () { if (window.SpeechSDK) resolve(window.SpeechSDK); else { sdkP = null; reject(new Error('the speech SDK did not load')); } };
          sc.onerror = function () { sdkP = null; sc.remove(); reject(new Error('the speech SDK is missing next to the page')); };
          document.head.appendChild(sc);
        });
      }
      return sdkP;
    }
    // A ten-minute token from the daemon (the key stays on main), kept until a minute before it ends.
    function token() {
      if (tok && Date.now() < tokUntil) return Promise.resolve(tok);
      return fetch('/api/speech/token', { method: 'POST', headers: { 'X-WebCompanion-Contract': '1' }, cache: 'no-store' })
        .then(function (r) {
          if (!r.ok) return r.text().then(function (t) { var e = new Error((t || '').trim() || 'HTTP ' + r.status); e.status = r.status; throw e; });
          return r.json();
        })
        .then(function (t) { tok = t; tokUntil = Date.now() + (t.expires_in || 540) * 1000; return t; });
    }
    function joined(base, parts) { var t = parts.filter(Boolean).join(' '); return base ? base.replace(/\s*$/, ' ') + t : t; }
    function toggleRecording(btn) {
      if (recording) return stopRecording(false);
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { note('This browser cannot record here.', true); return; }
      note('Starting the microphone…');
      btn.disabled = true;
      Promise.all([loadSdk(), token()]).then(function (x) {
        var SDK = x[0], t = x[1];
        var cfg = SDK.SpeechConfig.fromAuthorizationToken(t.token, t.region);
        cfg.setProperty(SDK.PropertyId.SpeechServiceConnection_LanguageIdMode, 'Continuous');
        var auto = SDK.AutoDetectSourceLanguageConfig.fromLanguages(['en-US', 'el-GR']);
        var rec = SDK.SpeechRecognizer.FromConfig(cfg, auto, SDK.AudioConfig.fromDefaultMicrophoneInput());
        var field = target(), base = field ? field.value : '', parts = [], heard = {};
        function put(extra) { if (field && document.body.contains(field)) field.value = joined(base, parts.concat(extra ? [extra] : [])); }
        rec.recognizing = function (_r, e) { put(e.result.text); };
        rec.recognized = function (_r, e) {
          if (e.result.reason !== SDK.ResultReason.RecognizedSpeech || !e.result.text) return;
          parts.push(e.result.text);
          var lang = '';
          try { lang = SDK.AutoDetectSourceLanguageResult.fromResult(e.result).language || ''; } catch (err) { lang = ''; }
          heard[lang] = (heard[lang] || 0) + e.result.text.length;
          put();
        };
        rec.canceled = function (_r, e) {
          if (e.reason === SDK.CancellationReason.Error) { tok = null; note('Speech failed: ' + (e.errorDetails || 'Azure refused'), true); }
          stopRecording(true);
        };
        recording = { rec: rec, btn: btn, heard: heard, field: field };
        rec.startContinuousRecognitionAsync(function () {
          btn.disabled = false;
          btn.classList.add('rec');
          btn.textContent = '■';
          btn.title = 'Stop';
          note('Listening… press ■ to stop');
        }, function (err) { btn.disabled = false; recording = null; note('No microphone: ' + err, true); });
      }).catch(function (e) {
        btn.disabled = false;
        note(e.status === 503 ? 'Speech is not set up on main (webcompanion speech.env). Type instead.' : 'Speech is off: ' + e.message, true);
      });
    }
    function stopRecording(discard) {
      var r = recording;
      if (!r) return;
      recording = null;
      var done = function () { try { r.rec.close(); } catch (e) {} };
      r.rec.stopContinuousRecognitionAsync(done, done);
      if (r.btn) { r.btn.disabled = false; r.btn.classList.remove('rec'); r.btn.textContent = '🎤'; r.btn.title = 'Speak: press to record, press again to stop'; }
      if (discard) return;
      var greek = (r.heard['el-GR'] || 0) > (r.heard['en-US'] || 0);
      if (r.field && document.body.contains(r.field)) { r.field.focus(); r.field.setSelectionRange(r.field.value.length, r.field.value.length); }
      note(greek ? 'Heard in Greek. Check it, then send.' : 'Check it, then send.');
    }

    // ── Hover ──
    pinsEl.addEventListener('pointerover', function (e) {
      var b = e.target.closest('.pin'), id = b && b.getAttribute('data-id'), c = id && byId(id);
      if (!c || e.pointerType === 'touch' || id === thread) return;
      hoverEl.innerHTML = '<b>' + c.number + ' · ' + escHtml(whereText(c)) + (c.replies.length ? ' · ' + c.replies.length + (c.replies.length === 1 ? ' reply' : ' replies') : '') + '</b>' + escHtml(c.text);
      var r = b.getBoundingClientRect();
      hoverEl.style.display = 'block';
      var x = Math.min(r.right + 6, innerWidth - hoverEl.offsetWidth - 8), y = Math.max(8, r.top - 4);
      hoverEl.style.left = x + 'px'; hoverEl.style.top = y + 'px';
    });
    pinsEl.addEventListener('pointerout', function () { hoverEl.style.display = 'none'; });

    // ── Panel ──
    function setPanel(open) {
      panel.classList.toggle('open', open);
      panelBtn.setAttribute('aria-pressed', String(open));
      if (open) drawList();
    }
    panelBtn.addEventListener('click', function () { setPanel(!panel.classList.contains('open')); });
    document.getElementById('c-panel-close').addEventListener('click', function () { setPanel(false); });
    panel.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      if (b.hasAttribute('data-cstatus')) {
        filterStatus = b.getAttribute('data-cstatus');
        panel.querySelectorAll('[data-cstatus]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
        drawList(); drawPins();
      } else if (b.hasAttribute('data-cscope')) {
        filterScope = b.getAttribute('data-cscope');
        panel.querySelectorAll('[data-cscope]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
        drawList();
      } else if (b.hasAttribute('data-goto')) {
        flyTo(b.getAttribute('data-goto'));
      }
    });
    // Panel clicks and scrolls stay in the panel: no pan, no zoom.
    ['pointerdown', 'wheel'].forEach(function (t) { panel.addEventListener(t, function (e) { e.stopPropagation(); }); });
    function drawList() {
      var shown = mine.filter(function (c) {
        return (filterStatus === 'all' || c.status === filterStatus) && (filterScope === 'all' || c.scope === filterScope);
      });
      if (!shown.length) {
        list.innerHTML = '<p class="c-empty">' + (mine.length ? 'No comments match.' : 'No comments on ' + APP_NAME + ' yet. Press Comment, then click a screenshot.') + '</p>';
        return;
      }
      list.innerHTML = shown.map(function (c) {
        return '<button type="button" class="c-item" data-goto="' + escHtml(c.id) + '">' +
          '<div class="c-meta"><span class="c-num' + (c.status === 'resolved' ? ' resolved' : '') + '">' + c.number + '</span>' +
          '<span>' + escHtml(whereText(c)) + '</span></div>' +
          '<div class="c-text">' + escHtml(c.text) + '</div>' +
          '<div class="c-meta">' + scopeText(c) + '<span>' + escHtml(when(c.createdAt)) + '</span>' +
          (c.replies.length ? '<span>' + c.replies.length + (c.replies.length === 1 ? ' reply' : ' replies') + '</span>' : '') +
          (c.status === 'resolved' ? '<span>resolved</span>' : '') + (c._unsent ? '<span>unsent</span>' : '') + claudeState(c) +
          (gone(c) ? '<span class="c-gone">board no longer on this canvas</span>' : '') + '</div></button>';
      }).join('');
    }
    // Fly the canvas to a pin: its shot fills the window (at most 100 %), the
    // pin at the shot's point, and its thread opens.
    function flyTo(id) {
      var c = byId(id);
      if (!c) return;
      var o = shotBox[c.board + '|' + c.shot];
      if (o && !o.shown) setShown('all');
      o = shotBox[c.board + '|' + c.shot];
      if (!o || !o.shown) return;
      var w = box.w - (panel.classList.contains('open') && box.w > 700 ? 360 : 0);
      var v = fitView(o.x, o.y, o.w, o.frameH, w, box.h, 48, 1);
      if (panel.classList.contains('open') && box.w <= 700) setPanel(false);
      animateTo(v);
      setTimeout(function () { openThread(id); }, 230);
    }

    // ── The page's hooks ──
    hooks.measured = measureShots;
    hooks.render = positionPins;
    hooks.click = function (e) {
      var pin = e.target.closest('.pin');
      if (pin) {
        var id = pin.getAttribute('data-id');
        if (id) { hoverEl.style.display = 'none'; if (thread === id) closePop(); else openThread(id); }
        return true;
      }
      var shot = mode && e.target.closest('.shot[data-board]');
      if (shot) { placeDraft(e, shot); return true; }
      return false;
    };
    hooks.key = function (e) {
      if (e.key === 'Escape') {
        if (pop.classList.contains('open')) { closePop(); return true; }
        if (mode) { setMode(false); return true; }
        if (panel.classList.contains('open')) { setPanel(false); return true; }
        return false;
      }
      if ((e.key === 'c' || e.key === 'C') && !e.metaKey && !e.ctrlKey && !e.altKey) { setMode(!mode); if (!mode) closePop(); return true; }
      return false;
    };
    // For the checks: the state and the pin layer, read-only.
    window.canvasComments = {
      state: function () { return { online: online, loaded: loaded, queue: queue.length, comments: mine.length, unanswered: unanswered().length }; },
      comments: function () { return JSON.parse(JSON.stringify(mine)); }, flyTo: flyTo, refresh: refresh, open: openThread
    };

    measureShots();
    rebuild();
    refresh(null);
  })();
}
