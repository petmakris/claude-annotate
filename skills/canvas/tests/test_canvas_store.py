"""The page's copy of the comment store (canvas-store.js), ported from lomem's comment-store.test.ts.
lomem's suite checks that its applyOp and this one give the same stores (journey canvas vendor test)."""
from __future__ import annotations

import json

from .helpers import js, needs_node

pytestmark = needs_node

T0 = "2026-10-29T17:00:00.000Z"
PRELUDE = f"""
var T0 = {json.dumps(T0)};
function create(id, extra) {{
  var c = {{ id: id, app: 'mealy', board: 5, boardTitle: 'Sign in', chapter: 'Account', shot: 'desktop', fx: 0.25, fy: 0.5, text: 'The button is too small' }};
  for (var k in (extra || {{}})) c[k] = extra[k];
  return {{ kind: 'create', comment: c }};
}}
function run(ops, s) {{
  s = s || {{ version: 1, comments: [] }};
  ops.forEach(function (op) {{ var r = S.applyOp(s, op, T0); if (r.error) throw new Error(op.kind + ': ' + r.error); s = r.store; }});
  return s;
}}
"""


def test_a_comment_has_its_board_shot_point_scope_and_time_numbered_per_canvas():
    s = js(PRELUDE + "return run([create('a'), create('b', { app: 'billpod', shot: 'phone', scope: 'both' }), create('c'),"
           "create('v', { app: 'voice-states', shot: 'shot' })]);")
    assert s["comments"][0] == {"id": "a", "number": 1, "app": "mealy", "board": 5, "boardTitle": "Sign in", "chapter": "Account",
                                "shot": "desktop", "fx": 0.25, "fy": 0.5, "text": "The button is too small", "scope": "app",
                                "status": "open", "createdAt": T0, "replies": []}
    assert [[c["id"], c["app"], c["number"], c["shot"], c["scope"]] for c in s["comments"]] == [
        ["a", "mealy", 1, "desktop", "app"], ["b", "billpod", 1, "phone", "both"], ["c", "mealy", 2, "desktop", "app"],
        ["v", "voice-states", 1, "shot", "app"]]


def test_numbers_are_never_reused_and_a_replay_keeps_its_time():
    r = js(PRELUDE + "var s = run([create('a'), create('b'), { kind: 'delete', id: 'a' }, create('c')]);"
           "var t = run([Object.assign(create('x'), { at: '2026-10-29T16:12:00Z' })]);"
           "return [s.comments.map(function (c) { return [c.id, c.number]; }), t.comments[0].createdAt];")
    assert r == [[["b", 2], ["c", 3]], "2026-10-29T16:12:00.000Z"]


def test_edits_resolves_reopens_replies_and_deletes():
    r = js(PRELUDE + """
      var s = run([create('a'), { kind: 'update', id: 'a', text: '  Bigger button  ', scope: 'both' },
        { kind: 'update', id: 'a', status: 'resolved', at: '2026-10-29T18:00:00Z' }]);
      var resolved = [s.comments[0].text, s.comments[0].scope, s.comments[0].status, s.comments[0].resolvedAt];
      s = run([{ kind: 'update', id: 'a', status: 'open' }, { kind: 'reply', id: 'a', reply: { id: 'r1', text: 'Also on the phone' } },
        { kind: 'reply', id: 'a', reply: { id: 'r2', text: 'And the label' } },
        { kind: 'editReply', id: 'a', replyId: 'r1', text: 'Also on the phone shot' }, { kind: 'deleteReply', id: 'a', replyId: 'r2' }], s);
      var replies = s.comments[0].replies.map(function (x) { return [x.id, x.text, x.updatedAt || null]; });
      var reopened = [s.comments[0].status, s.comments[0].resolvedAt === undefined];
      return [resolved, reopened, replies, run([{ kind: 'delete', id: 'a' }], s).comments];""")
    assert r == [["Bigger button", "both", "resolved", "2026-10-29T18:00:00.000Z"], ["open", True],
                 [["r1", "Also on the phone shot", T0]], []]


def test_a_replayed_create_reply_or_delete_changes_nothing():
    r = js(PRELUDE + """
      var ops = [create('a'), { kind: 'reply', id: 'a', reply: { id: 'r', text: 'x' } }];
      var once = run(ops), twice = run(ops, once);
      var gone = run([{ kind: 'delete', id: 'gone' }, { kind: 'deleteReply', id: 'a', replyId: 'gone' }], once);
      return [JSON.stringify(once) === JSON.stringify(twice), JSON.stringify(once) === JSON.stringify(gone)];""")
    assert r == [True, True]


def test_refuses_what_is_not_a_comment_and_leaves_the_store_as_it_was():
    r = js(PRELUDE + """
      var s = run([create('a')]);
      var cases = [[create('b', { text: '   ' }), 400, 'empty'], [create('b', { app: 'Mealy app' }), 400, 'app'],
        [create('b', { app: '../mealy' }), 400, 'app'], [create('b', { shot: 'Phone' }), 400, 'shot'],
        [create('b', { fx: 1.2 }), 400, 'fractions'], [create('b', { scope: 'all' }), 400, 'scope'], [create('../x'), 400, 'id'],
        [create('b', { audio: ['../../etc/passwd'] }), 400, 'wav'], [{ kind: 'update', id: 'nope', text: 'x' }, 404, 'No comment'],
        [{ kind: 'update', id: 'a', status: 'done' }, 400, 'status'], [{ kind: 'editReply', id: 'a', replyId: 'nope', text: 'x' }, 404, 'No reply'],
        [{ kind: 'shout' }, 400, 'Unknown op']];
      return cases.map(function (c) { var x = S.applyOp(s, c[0], T0);
        return x.status === c[1] && (x.error || '').indexOf(c[2]) >= 0 && x.store === s; });""")
    assert r == [True] * 12
