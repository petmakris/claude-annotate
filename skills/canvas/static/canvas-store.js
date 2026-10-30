// The comment store's one way to change: applyOp. The comments live in a
// webcompanion session as an op log: every create, edit, resolve, reply and
// delete is one message in the thread of the board it is about, carrying its
// op. `fold` puts every thread's ops in order and applies them, so every page
// and claude-annotate's journey tool (skills/journey/store.py, the same
// function in Python; skills/journey/tests run both on the same cases) see the
// same comments. The page also applies the ops not sent yet, so a comment
// made while the daemon is down shows at once and is sent once it is back.
//
// Who wrote what: a create, an edit of the text and a reply are Petros's
// (`by` absent or "petros") unless a reply says `by: "claude"`. A comment
// records when Petros last wrote on it (`askedAt`), when Claude last replied
// (`answeredAt`) and when the page last sent it to Claude (`sentAt`), so the
// page can count what waits for Claude and what was sent.
//
// A comment belongs to one canvas (`app`: "mealy", "billpod", "voice")
// and one shot of a board (`shot`: its label in lower case, "desktop",
// "phone"). The board is its number, or its id on a canvas whose boards have
// ids ("plan-setup/03-plan-setup-3-method"); `move` puts a comment on another
// board when the canvas renames or renumbers them. Ops are idempotent where a replay could repeat them: a create
// whose id is already there and a delete of what is gone change nothing.
var CanvasStore = (function () {
  var MAX_TEXT = 10000;
  var ID_OK = /^[A-Za-z0-9_-]{1,64}$/, BOARD_ID_OK = /^[A-Za-z0-9][A-Za-z0-9\/._-]{0,159}$/, APP_OK = /^[a-z0-9][a-z0-9-]{0,39}$/, SHOT_OK = /^[a-z0-9][a-z0-9-]{0,19}$/;

  function refuse(store, error, status) { return { store: store, error: error, status: status }; }
  function boardOk(b) { return (typeof b === 'number' && b >= 0 && Math.floor(b) === b) || (typeof b === 'string' && BOARD_ID_OK.test(b)); }
  function copy(o) { var r = {}; for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) r[k] = o[k]; return r; }

  // The store after op, or the same store and why not. now is an ISO time.
  function applyOp(store, op, now) {
    var o = op;
    if (!o || typeof o !== 'object') return refuse(store, 'An op must be an object.', 400);
    var at = typeof o.at === 'string' && !isNaN(Date.parse(o.at)) ? new Date(o.at).toISOString() : now;
    var list = store.comments, i = -1, k;
    if (typeof o.id === 'string') for (k = 0; k < list.length; k++) if (list[k].id === o.id) i = k;
    var audio;
    var rawAudio = o.kind === 'create' ? o.comment && o.comment.audio : o.kind === 'reply' ? o.reply && o.reply.audio : o.audio;
    if (rawAudio !== undefined) {
      if (!Array.isArray(rawAudio) || rawAudio.length > 20) return refuse(store, 'audio must be a list of file names.', 400);
      audio = [];
      for (k = 0; k < rawAudio.length; k++) {
        if (typeof rawAudio[k] !== 'string' || !/^[A-Za-z0-9_.-]{1,120}\.wav$/.test(rawAudio[k])) {
          return refuse(store, 'audio must be a list of .wav file names.', 400);
        }
        audio.push(rawAudio[k]);
      }
    }
    var text;
    var rawText = o.kind === 'create' ? o.comment && o.comment.text : o.kind === 'reply' ? o.reply && o.reply.text : o.text;
    if (rawText !== undefined) {
      if (typeof rawText !== 'string' || !rawText.trim()) return refuse(store, 'The text is empty.', 400);
      if (rawText.length > MAX_TEXT) return refuse(store, 'The text is longer than ' + MAX_TEXT + ' characters.', 400);
      text = rawText.trim();
    }

    if (o.kind === 'create') {
      var c = o.comment;
      if (!c || typeof c !== 'object') return refuse(store, 'create needs a comment.', 400);
      if (typeof c.id !== 'string' || !ID_OK.test(c.id)) return refuse(store, 'The comment id is not valid.', 400);
      for (k = 0; k < list.length; k++) if (list[k].id === c.id) return { store: store };
      if (typeof c.app !== 'string' || !APP_OK.test(c.app)) return refuse(store, 'app must be a canvas id (a-z, 0-9 and -).', 400);
      if (typeof c.shot !== 'string' || !SHOT_OK.test(c.shot)) return refuse(store, 'shot must be a shot label (a-z, 0-9 and -).', 400);
      if (!boardOk(c.board)) return refuse(store, 'board must be a board number or id.', 400);
      if (!(typeof c.fx === 'number' && c.fx >= 0 && c.fx <= 1 && typeof c.fy === 'number' && c.fy >= 0 && c.fy <= 1)) {
        return refuse(store, 'The point must be fractions of the shot, from 0 to 1.', 400);
      }
      if (text === undefined) return refuse(store, 'The text is empty.', 400);
      if (c.scope !== undefined && c.scope !== 'app' && c.scope !== 'both') return refuse(store, 'scope must be app or both.', 400);
      // A comment carried over from an earlier store keeps its number.
      var number = 1;
      for (k = 0; k < list.length; k++) if (list[k].app === c.app && list[k].number >= number) number = list[k].number + 1;
      if (typeof c.number === 'number' && c.number >= 1 && Math.floor(c.number) === c.number) number = c.number;
      var made = {
        id: c.id, number: number, app: c.app, board: c.board,
        boardTitle: String(c.boardTitle || '').slice(0, 300), chapter: String(c.chapter || '').slice(0, 300),
        shot: c.shot, fx: c.fx, fy: c.fy, text: text, scope: c.scope === 'both' ? 'both' : 'app',
        status: 'open', createdAt: at, askedAt: at, replies: []
      };
      if (audio && audio.length) made.audio = audio;
      return { store: { version: 1, comments: list.concat([made]) } };
    }

    if (o.kind === 'delete') {
      if (i < 0) return { store: store };
      return { store: { version: 1, comments: list.slice(0, i).concat(list.slice(i + 1)) } };
    }
    if (o.kind !== 'update' && o.kind !== 'move' && o.kind !== 'reply' && o.kind !== 'editReply' && o.kind !== 'deleteReply') {
      return refuse(store, 'Unknown op ' + JSON.stringify(o.kind) + '.', 400);
    }
    if (i < 0) {
      // Removing a reply from a comment already deleted changes nothing; an edit is refused.
      if (o.kind === 'deleteReply') return { store: store };
      return refuse(store, 'No comment ' + JSON.stringify(o.id) + '.', 404);
    }
    var was = list[i], next = copy(was);
    next.replies = was.replies.slice();

    if (o.kind === 'update') {
      if (o.scope !== undefined && o.scope !== 'app' && o.scope !== 'both') return refuse(store, 'scope must be app or both.', 400);
      if (o.status !== undefined && o.status !== 'open' && o.status !== 'resolved') return refuse(store, 'status must be open or resolved.', 400);
      if (o.sentAt !== undefined) {
        // Sent to Claude: not an edit, so it leaves updatedAt alone.
        if (typeof o.sentAt !== 'string' || isNaN(Date.parse(o.sentAt))) return refuse(store, 'sentAt must be a time.', 400);
        next.sentAt = new Date(o.sentAt).toISOString();
        if (text === undefined && o.scope === undefined && o.status === undefined && audio === undefined) {
          var sent = list.slice(); sent[i] = next;
          return { store: { version: 1, comments: sent } };
        }
      }
      if (text !== undefined) { next.text = text; next.askedAt = at; }
      if (o.scope !== undefined) next.scope = o.scope;
      if (audio !== undefined) {
        var all = (was.audio || []).slice();
        for (k = 0; k < audio.length; k++) if (all.indexOf(audio[k]) < 0) all.push(audio[k]);
        if (all.length) next.audio = all;
      }
      if (o.status !== undefined && o.status !== was.status) {
        next.status = o.status;
        if (o.status === 'resolved') next.resolvedAt = at; else delete next.resolvedAt;
      }
      next.updatedAt = at;
    } else if (o.kind === 'move') {
      if (!boardOk(o.board)) return refuse(store, 'board must be a board number or id.', 400);
      next.board = o.board;
      if (o.boardTitle !== undefined) next.boardTitle = String(o.boardTitle).slice(0, 300);
      if (o.chapter !== undefined) next.chapter = String(o.chapter).slice(0, 300);
    } else if (o.kind === 'reply') {
      var r = o.reply;
      if (!r || typeof r.id !== 'string' || !ID_OK.test(r.id)) return refuse(store, 'The reply id is not valid.', 400);
      for (k = 0; k < was.replies.length; k++) if (was.replies[k].id === r.id) return { store: store };
      if (text === undefined) return refuse(store, 'The text is empty.', 400);
      var reply = { id: r.id, text: text, createdAt: at };
      if (r.by === 'claude') { reply.by = 'claude'; next.answeredAt = at; } else next.askedAt = at;
      if (audio && audio.length) reply.audio = audio;
      next.replies.push(reply);
    } else {
      var j = -1;
      for (k = 0; k < was.replies.length; k++) if (was.replies[k].id === o.replyId) j = k;
      if (o.kind === 'deleteReply') {
        if (j < 0) return { store: store };
        next.replies.splice(j, 1);
      } else {
        if (j < 0) return refuse(store, 'No reply ' + JSON.stringify(o.replyId) + '.', 404);
        if (text === undefined) return refuse(store, 'The text is empty.', 400);
        var edited = copy(was.replies[j]);
        edited.text = text; edited.updatedAt = at;
        if (audio !== undefined && audio.length) edited.audio = (was.replies[j].audio || []).concat(audio);
        next.replies[j] = edited;
      }
    }
    var comments = list.slice();
    comments[i] = next;
    return { store: { version: 1, comments: comments } };
  }

  // Every op in a session's threads ({anchor: {messages}}, as GET /threads
  // answers), in the order they were made: by the op's own time (the page's
  // clock, kept through an offline queue), then the daemon's, then the order
  // in the thread. Ops another canvas wrote are skipped by `app` in the page.
  function opsOf(threads) {
    var all = [], n = 0;
    Object.keys(threads || {}).sort().forEach(function (anchor) {
      var msgs = (threads[anchor] && threads[anchor].messages) || [];
      msgs.forEach(function (m) {
        if (!m || !m.op || typeof m.op !== 'object') return;
        var t = typeof m.op.at === 'string' ? Date.parse(m.op.at) : NaN;
        all.push({ op: m.op, t: isNaN(t) ? (m.ts || 0) * 1000 : t, ts: m.ts || 0, n: n++ });
      });
    });
    all.sort(function (a, b) { return a.t - b.t || a.ts - b.ts || a.n - b.n; });
    return all.map(function (x) { return x.op; });
  }
  // The store every op in the threads makes, and the ops it refused.
  function fold(threads, now) {
    var s = { version: 1, comments: [] }, refused = [];
    opsOf(threads).forEach(function (op) {
      var r = applyOp(s, op, now || new Date().toISOString());
      if (r.error) refused.push({ op: op, error: r.error }); else s = r.store;
    });
    return { store: s, refused: refused };
  }
  // Open, and Petros wrote on it after Claude last answered.
  function waiting(c) { return c.status === 'open' && (!c.answeredAt || c.askedAt > c.answeredAt); }

  return { applyOp: applyOp, fold: fold, opsOf: opsOf, waiting: waiting, MAX_TEXT: MAX_TEXT };
})();
if (typeof module !== 'undefined') module.exports = CanvasStore;
