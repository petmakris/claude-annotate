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
// The comments live in the journey-comments service on main (lomem's
// `lomem journey comments serve`), reached from the phone and tablet too. The
// page runs the store's own applyOp (canvas-store.js) on what the service last
// sent plus the ops not sent yet, which wait in localStorage while the service
// is down and are sent, in order, once it answers again. A spoken comment is
// recorded as 16 kHz mono PCM and sent to the service, which turns it into text
// (no key in the page).
//
// This fragment runs inside the page's closure (canvas-page.js) and uses its
// view, box, shotEls, setView, animateTo, setShown and hooks. It runs only on
// a canvas whose manifest names a comments service.
if (DATA.comments) {
  (function () {
    var CFG = DATA.comments, APP = CFG.canvas, SERVICE = String(CFG.url).replace(/\/+$/, '');
    var APP_NAME = CFG.name || DATA.title;
    // A canvas that shares its comments with others (Mealy's and Billpod's) has a scope choice.
    var SCOPES = CFG.scopes || null;
    var applyOp = CanvasStore.applyOp, pointInBox = M.pointInBox, pinOnScreen = M.pinOnScreen, fitView = M.fitView;
    var QUEUE_KEY = 'journey-comments-queue', CACHE_KEY = 'journey-comments-cache';
    var pinsEl = document.getElementById('pins'), pop = document.getElementById('c-pop'), hoverEl = document.getElementById('c-hover');
    var panel = document.getElementById('c-panel'), list = document.getElementById('c-list');
    var modeBtn = document.getElementById('c-mode'), panelBtn = document.getElementById('c-panel-btn');
    var statusEl = document.getElementById('c-status'), countEl = document.getElementById('c-count');

    function readJson(k, fallback) { try { var v = JSON.parse(load(k) || 'null'); return v === null ? fallback : v; } catch (e) { return fallback; } }
    var server = readJson(CACHE_KEY, { version: 1, comments: [] });
    var queue = readJson(QUEUE_KEY, []);
    var online = null, flushing = false, lastError = '';
    var store = server, mine = [];
    function uid(p) { return p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
    function escHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
    function when(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }

    // What sits where: each shot's image on the surface, by board and size.
    var shotBox = {};
    // A shot's box is its whole image (h tall); only its frame (frameH) is drawn.
    function measureShots() {
      shotBox = {};
      shotEls.forEach(function (s) {
        var b = s.box, o = b ? { el: s.el, x: b.x, y: b.y, w: b.w, h: b.h, frameH: b.frameH, shown: true } : { el: s.el, shown: false };
        shotBox[s.board.data.number + '|' + s.data.key] = o;
      });
    }

    // ── State: what the service last sent, plus the ops not sent yet ──
    function rebuild() {
      var s = server, unsent = {};
      for (var i = 0; i < queue.length; i++) {
        var r = applyOp(s, queue[i], queue[i].at || new Date().toISOString());
        s = r.store;
        var id = queue[i].id || (queue[i].comment && queue[i].comment.id);
        if (id) unsent[id] = true;
      }
      store = s;
      mine = store.comments.filter(function (c) { return c.app === APP; }).sort(function (a, b) { return a.number - b.number; });
      mine.forEach(function (c) { c._unsent = !!unsent[c.id]; });
      var open = mine.filter(function (c) { return c.status === 'open'; }).length;
      countEl.textContent = open ? '(' + open + ')' : '';
      showStatus();
      drawPins();
      if (panel.classList.contains('open')) drawList();
      if (thread && !byId(thread)) closePop();
      else if (thread && !editing) drawThread();
    }
    function byId(id) { for (var i = 0; i < mine.length; i++) if (mine[i].id === id) return mine[i]; return null; }
    function showStatus() {
      var n = queue.length, text = '';
      if (online === false) text = 'Comments service down' + (n ? ' · ' + n + ' unsent, kept here' : '');
      else if (n) text = n + ' unsent';
      if (lastError) text = (text ? text + ' · ' : '') + lastError;
      statusEl.textContent = text;
      statusEl.classList.toggle('on', !!text);
      statusEl.title = online === false ? 'Cannot reach ' + SERVICE + '. Comments made now are kept in this browser and sent when it is back.' : '';
    }
    function saveQueue() { save(QUEUE_KEY, JSON.stringify(queue)); }
    function send(op) {
      op.at = new Date().toISOString();
      queue.push(op);
      saveQueue();
      rebuild();
      flush();
    }
    function got(s) {
      if (s && Array.isArray(s.comments)) { server = s; save(CACHE_KEY, JSON.stringify(s)); }
    }
    function flush() {
      if (flushing || !queue.length) return;
      flushing = true;
      var batch = queue.slice();
      fetch(SERVICE + '/ops', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ops: batch }) })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (body) {
          online = true;
          got(body.store);
          // Sent: drop them, also the refused ones, which could never succeed.
          queue = queue.slice(batch.length);
          saveQueue();
          var refused = (body.results || []).filter(function (x) { return x.error; });
          lastError = refused.length ? 'Not saved: ' + refused[0].error : '';
          flushing = false;
          rebuild();
          if (queue.length) flush();
        })
        .catch(function () { online = false; flushing = false; showStatus(); });
    }
    function refresh() {
      fetch(SERVICE + '/comments', { cache: 'no-store' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (s) { online = true; if (!queue.length) got(s); rebuild(); flush(); })
        .catch(function () { online = false; showStatus(); });
    }
    // Every 15 s while down, every 60 s while up, and whenever the tab comes back.
    setInterval(function () { if (online === false || document.visibilityState === 'visible') { if (queue.length) flush(); else refresh(); } }, 15000);
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') refresh(); });
    window.addEventListener('online', refresh);

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
        id: uid('c'), board: parseInt(shot.getAttribute('data-board'), 10), shot: shot.getAttribute('data-shot'),
        boardTitle: shot.getAttribute('data-title'), chapter: shot.getAttribute('data-chapter'), fx: p.fx, fy: p.fy,
        scope: 'app', audio: []
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
    function whereText(c) { return 'Board ' + c.board + ' ' + (c.boardTitle || '') + (LABELS.length > 1 ? ' · ' + c.shot : ''); }
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
        fx: c.fx, fy: c.fy, text: text, scope: c.scope, audio: c.audio.length ? c.audio : undefined } });
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
        (c.chapter ? '<span>' + escHtml(c.chapter) + '</span>' : '') + (c._unsent ? '<span>unsent</span>' : '') + '</div>';
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
          body += '<div class="c-msg" data-reply="' + escHtml(r.id) + '"><div class="c-meta"><span>Reply · ' + escHtml(when(r.createdAt)) + (r.updatedAt ? ' · edited' : '') + '</span></div>' +
            '<div class="c-text">' + escHtml(r.text) + '</div>' +
            '<div class="c-meta"><button type="button" data-c="reply-edit">Edit</button><button type="button" data-c="reply-delete">Delete</button></div></div>';
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
      if (k === 'resolve') send({ kind: 'update', id: c.id, status: c.status === 'open' ? 'resolved' : 'open' });
      else if (k === 'delete') { if (confirm('Delete comment ' + c.number + ' and its replies?')) { send({ kind: 'delete', id: c.id }); closePop(); } }
      else if (k === 'edit') { pendingAudio = []; drawThread('comment'); }
      else if (k === 'edit-cancel') drawThread();
      else if (k === 'edit-save') {
        var t = document.getElementById('c-edit').value.trim();
        if (!t || recording) return;
        editing = false;
        send({ kind: 'update', id: c.id, text: t, scope: editScope, audio: pendingAudio.length ? pendingAudio : undefined });
        pendingAudio = [];
        drawThread();
      }
      else if (k === 'reply-edit') { pendingAudio = []; drawThread(rid); }
      else if (k === 'reply-save') {
        var rt = document.getElementById('c-edit').value.trim();
        if (!rt || recording) return;
        editing = false;
        send({ kind: 'editReply', id: c.id, replyId: rid, text: rt, audio: pendingAudio.length ? pendingAudio : undefined });
        pendingAudio = [];
        drawThread();
      }
      else if (k === 'reply-delete') { if (confirm('Delete this reply?')) send({ kind: 'deleteReply', id: c.id, replyId: rid }); }
      else if (k === 'reply') {
        var input = document.getElementById('c-reply'), text = input.value.trim();
        if (!text || recording) return;
        input.value = '';
        send({ kind: 'reply', id: c.id, reply: { id: replyId || uid('r'), text: text, audio: pendingAudio.length ? pendingAudio : undefined } });
        pendingAudio = []; replyId = null;
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

    // ── Speaking: record 16 kHz mono PCM, the service turns it into text ──
    var recording = null, pendingAudio = [], replyId = null;
    function note(text, bad) {
      var n = document.getElementById('c-note');
      if (n) { n.textContent = text; n.classList.toggle('bad', !!bad); }
    }
    function target() { return document.getElementById('c-edit') || document.getElementById('c-text') || document.getElementById('c-reply'); }
    function toggleRecording(btn) {
      if (recording) return stopRecording(false);
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { note('This browser cannot record here.', true); return; }
      note('Starting the microphone…');
      navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }).then(function (stream) {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        var ctx = new Ctx();
        var src = ctx.createMediaStreamSource(stream);
        var proc = ctx.createScriptProcessor(4096, 1, 1);
        var chunks = [];
        proc.onaudioprocess = function (ev) { chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0))); };
        src.connect(proc);
        proc.connect(ctx.destination);
        recording = { stream: stream, ctx: ctx, proc: proc, src: src, chunks: chunks, btn: btn, started: Date.now() };
        btn.classList.add('rec');
        btn.textContent = '■';
        btn.title = 'Stop and write it down';
        note('Recording… press ■ to stop');
      }).catch(function (err) { note('No microphone: ' + (err && err.message || err), true); });
    }
    function stopRecording(discard) {
      var r = recording;
      if (!r) return;
      recording = null;
      try { r.proc.disconnect(); r.src.disconnect(); } catch (e) {}
      r.stream.getTracks().forEach(function (t) { t.stop(); });
      var rate = r.ctx.sampleRate;
      r.ctx.close();
      if (r.btn) { r.btn.classList.remove('rec'); r.btn.textContent = '🎤'; r.btn.title = 'Speak: press to record, press again to stop'; }
      if (discard) return;
      var wav = toWav(r.chunks, rate);
      if (!wav) { note('Nothing was recorded.', true); return; }
      var forId = draft ? draft.id : thread || uid('c');
      if (!draft && thread && !editing && !replyId) replyId = uid('r');
      var recId = forId + (replyId && !editing ? '-' + replyId : '') + '-' + Date.now().toString(36);
      var btn = r.btn, field = target();
      if (btn) btn.disabled = true;
      note('Writing it down…');
      fetch(SERVICE + '/transcribe?id=' + encodeURIComponent(recId), { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav })
        .then(function (res) { return res.json().then(function (j) { return { ok: res.ok, j: j }; }); })
        .then(function (x) {
          online = true;
          if (btn) btn.disabled = false;
          if (x.j.audio) { if (draft && draft.id === forId) draft.audio.push(x.j.audio); else pendingAudio.push(x.j.audio); }
          if (!x.ok) { note(x.j.error || 'Speech failed.', true); return; }
          if (!x.j.text) { note('No words heard.', true); return; }
          if (field && document.body.contains(field)) {
            field.value = field.value ? field.value.replace(/\s*$/, ' ') + x.j.text : x.j.text;
            field.focus();
            field.setSelectionRange(field.value.length, field.value.length);
          }
          note(x.j.language === 'el-GR' ? 'Heard in Greek. Check it, then send.' : 'Check it, then send.');
        })
        .catch(function () { if (btn) btn.disabled = false; online = false; showStatus(); note('The comments service is down, so speech is off. Type instead.', true); });
    }
    function toWav(chunks, rate) {
      var n = 0, i, j;
      for (i = 0; i < chunks.length; i++) n += chunks[i].length;
      if (n < rate * 0.2) return null;
      var ratio = rate / 16000, out = Math.floor(n / ratio);
      var all = new Float32Array(n), at = 0;
      for (i = 0; i < chunks.length; i++) { all.set(chunks[i], at); at += chunks[i].length; }
      var buf = new ArrayBuffer(44 + out * 2), v = new DataView(buf);
      function str(o, s) { for (var k = 0; k < s.length; k++) v.setUint8(o + k, s.charCodeAt(k)); }
      str(0, 'RIFF'); v.setUint32(4, 36 + out * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
      v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true);
      v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data'); v.setUint32(40, out * 2, true);
      // Each output sample is the mean of the input samples it covers.
      for (i = 0; i < out; i++) {
        var a = Math.floor(i * ratio), b = Math.min(n, Math.floor((i + 1) * ratio)), s = 0;
        for (j = a; j < b; j++) s += all[j];
        s = b > a ? s / (b - a) : all[a];
        s = Math.max(-1, Math.min(1, s));
        v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      return new Blob([buf], { type: 'audio/wav' });
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
          (c.status === 'resolved' ? '<span>resolved</span>' : '') + (c._unsent ? '<span>unsent</span>' : '') + '</div></button>';
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
    window.canvasComments = { state: function () { return { online: online, queue: queue.length, comments: mine.length }; }, flyTo: flyTo, refresh: refresh };

    measureShots();
    rebuild();
    refresh();
  })();
}
