"""Tests for the ask_diff live-sync engine. Per the plan's own testing
strategy this is the phase's highest-value test file -- the mechanism has
no precedent to fall back on if it's wrong -- so scenarios go beyond the
happy path: a failed diff fetch that must touch nothing, an EXACT match
that migrates nothing, a MOVED match that must carry full history and
source_event_ids forward, a STALE match that must leave the thread alone,
and a genuine double-run idempotency check against a stateful fake daemon.
"""
from __future__ import annotations

import copy
import json
import subprocess
from unittest.mock import patch

import pytest

from skills._shared.web_companion import anchor_migrate
from skills.ask_diff import sync


SAMPLE_GH_META = {"headRefName": "feature/frob", "baseRefName": "master",
                  "headRefOid": "newoid"}


def _meta_items(pr_ref="42", head="feature/frob"):
    return {"__meta__": {"body": {"pr_ref": pr_ref, "title": "T", "head": head,
                                 "base": "master", "author": "alice",
                                 "url": "https://x", "head_oid": "oldoid",
                                 "fetched_at": 1}, "version": 1}}


def _thread(messages, title="A finding", anchor_text="foo()"):
    return {"anchor": "irrelevant-here", "version": len(messages),
           "messages": messages, "title": title, "anchor_text": anchor_text}


class _FakeDaemon:
    """Mirrors just enough of the real daemon's thread semantics (dedup by
    source_event_id, first-write-wins anchor_text, last-write-wins title --
    see ~/projects/webcompanion/src/webcompanion/threads.py) to make a
    genuine multi-call test possible against real surviving store contents,
    rather than asserting call counts/targets against independently-mocked
    calls -- the only way to actually distinguish a safe execution order
    from a destructive one when a fix's whole point is about ordering."""

    def __init__(self):
        self.items: dict = {}
        self.threads: dict = {}
        self.events: list[dict] = []  # every submit_event payload, anchor-keyed via "anchor"

    def get_items(self, sid, *, kind):
        return copy.deepcopy(self.items.get(sid, {}))

    def put_items(self, sid, items, *, kind, replace=False):
        cur = self.items.setdefault(sid, {})
        if replace:
            cur.clear()
        for k, v in items.items():
            cur[k] = {"body": v, "version": cur.get(k, {}).get("version", 0) + 1}
        return {"ok": True}

    def get_threads(self, sid, *, kind):
        return copy.deepcopy(self.threads.get(sid, {}))

    def append_thread(self, sid, anchor, text, *, kind, role="agent",
                      source_event_id=None, title=None, anchor_text=None):
        t = self.threads.setdefault(sid, {}).setdefault(
            anchor, {"anchor": anchor, "version": 0, "messages": []})
        if source_event_id is not None:
            for m in t["messages"]:
                if m.get("source_event_id") == source_event_id:
                    return {"appended": False, "version": t["version"]}
        msg = {"text": text, "role": role, "ts": 0}
        if source_event_id is not None:
            msg["source_event_id"] = source_event_id
        t["messages"].append(msg)
        t["version"] += 1
        if title:
            t["title"] = title
        if anchor_text and not t.get("anchor_text"):
            t["anchor_text"] = anchor_text
        return {"appended": True, "version": t["version"]}

    def delete_thread(self, sid, anchor, *, kind):
        return self.threads.get(sid, {}).pop(anchor, None) is not None

    def submit_event(self, sid, anchor, text, *, kind, images=None):
        payload = json.loads(text)
        payload["anchor"] = anchor
        self.events.append(payload)
        return "evt-fake"

    def patch_all(self, monkeypatch):
        """Wire every daemon call `sync.py` makes onto this fake in one line."""
        monkeypatch.setattr(sync.wc, "get_items", self.get_items)
        monkeypatch.setattr(sync.wc, "put_items", self.put_items)
        monkeypatch.setattr(sync.wc, "get_threads", self.get_threads)
        monkeypatch.setattr(sync.wc, "append_thread", self.append_thread)
        monkeypatch.setattr(sync.wc, "delete_thread", self.delete_thread)
        monkeypatch.setattr(sync.wc, "submit_event", self.submit_event)


# ---------------------------------------------------------------------------
# 1. A failing diff fetch must touch nothing else.
# ---------------------------------------------------------------------------

def test_resync_returns_early_and_touches_nothing_when_diff_fetch_fails(tmp_path):
    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              side_effect=RuntimeError("gh: network unreachable")) as mock_fetch, \
         patch("skills.ask_diff.sync.wc.get_threads") as mock_threads, \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items") as mock_put:
        result = sync.resync("s1", str(tmp_path))

    mock_fetch.assert_called_once_with("42", str(tmp_path))
    assert result["ok"] is False
    assert result["diff_fetch_failed"] is True
    assert "gh: network unreachable" in result["error"]
    assert result["migrated"] == []
    assert result["orphaned"] == []
    mock_threads.assert_not_called()
    mock_append.assert_not_called()
    mock_delete.assert_not_called()
    mock_submit.assert_not_called()
    mock_put.assert_not_called()


def test_resync_fails_cleanly_when_meta_has_no_pr_ref(tmp_path):
    with patch("skills.ask_diff.sync.wc.get_items",
              return_value={"__meta__": {"body": {}, "version": 1}}), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff") as mock_fetch, \
         patch("skills.ask_diff.sync.wc.put_items") as mock_put:
        result = sync.resync("s1", str(tmp_path))

    assert result["ok"] is False
    assert result["diff_fetch_failed"] is False
    mock_fetch.assert_not_called()
    mock_put.assert_not_called()


# ---------------------------------------------------------------------------
# 2. EXACT match: nothing to migrate.
# ---------------------------------------------------------------------------

def test_resync_exact_match_migrates_nothing_but_still_refreshes_the_snapshot(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("\n".join(f"line{i}" for i in range(1, 9))
                                          + "\nfoo()\n" + "line10\n")
    # "foo()" sits at line 9 (1-based) -- anchor already recorded there.
    anchor = "src/x.py:R:9"
    threads = {anchor: _thread([{"text": "a reply", "role": "agent", "ts": 1,
                                 "source_event_id": "e1"}])}

    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)), \
         patch("skills.ask_diff.sync.wc.get_threads", return_value=threads), \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items") as mock_put:
        result = sync.resync("s1", str(tmp_path))

    assert result["ok"] is True
    assert result["migrated"] == []
    assert result["orphaned"] == []
    mock_append.assert_not_called()
    mock_delete.assert_not_called()
    mock_submit.assert_not_called()
    mock_put.assert_called_once()
    put_args, put_kwargs = mock_put.call_args
    assert put_args[0] == "s1"
    assert put_args[1]["__diff__"] == "NEW DIFF"
    assert put_args[1]["__meta__"]["head"] == "feature/frob"
    assert put_kwargs == {"kind": "interactive-review", "replace": True}


# ---------------------------------------------------------------------------
# 3. MOVED match: full history replayed, old anchor deleted, ids survive.
# ---------------------------------------------------------------------------

def test_resync_moved_match_replays_full_history_and_deletes_old_anchor(tmp_path):
    (tmp_path / "src").mkdir()
    lines = [f"line{i}" for i in range(1, 15)]
    lines[14 - 1] = "foo()"  # now sits at line 14 (1-based), was recorded at 9
    (tmp_path / "src" / "x.py").write_text("\n".join(lines) + "\n")

    old_anchor = "src/x.py:R:9"
    messages = [
        {"text": "first reply", "role": "agent", "ts": 1, "source_event_id": "e1"},
        {"text": "a follow-up question", "role": "user", "ts": 2},
        {"text": "second reply", "role": "agent", "ts": 3, "source_event_id": "e2"},
    ]
    threads = {old_anchor: _thread(messages, title="Null check", anchor_text="foo()")}

    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)), \
         patch("skills.ask_diff.sync.wc.get_threads", return_value=threads), \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items"):
        result = sync.resync("s1", str(tmp_path))

    new_anchor = "src/x.py:R:14"
    assert result["migrated"] == [new_anchor]
    assert result["orphaned"] == []
    mock_submit.assert_not_called()

    assert mock_append.call_count == 3
    calls = mock_append.call_args_list

    # Original order preserved.
    assert [c.args[2] for c in calls] == ["first reply", "a follow-up question",
                                         "second reply"]
    # Every call targets the new anchor, not the old one.
    assert all(c.args[1] == new_anchor for c in calls)
    # Roles preserved verbatim -- not overwritten with a single decided role.
    assert [c.kwargs["role"] for c in calls] == ["agent", "user", "agent"]
    # source_event_ids survive (idempotency on a later re-run) -- absent
    # ones stay None rather than being invented.
    assert [c.kwargs["source_event_id"] for c in calls] == ["e1", None, "e2"]
    # anchor_text only rides the first replayed message (first-write-wins).
    assert calls[0].kwargs["anchor_text"] == "foo()"
    assert calls[1].kwargs["anchor_text"] is None
    assert calls[2].kwargs["anchor_text"] is None
    # title is thread-level/last-write-wins on the daemon's side, so sending
    # it on every call is redundant, not incorrect.
    assert all(c.kwargs["title"] == "Null check" for c in calls)
    assert all(c.kwargs["kind"] == "interactive-review" for c in calls)

    mock_delete.assert_called_once_with("s1", old_anchor, kind="interactive-review")


# ---------------------------------------------------------------------------
# 4. STALE match: orphaned event fires, thread itself untouched.
# ---------------------------------------------------------------------------

def test_resync_stale_match_emits_orphaned_event_and_leaves_thread_alone(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("\n".join(f"line{i}" for i in range(1, 30)) + "\n")
    # "foo()" (the recorded anchor_text) no longer appears anywhere nearby.
    anchor = "src/x.py:R:9"
    threads = {anchor: _thread(
        [{"text": "a reply", "role": "agent", "ts": 1, "source_event_id": "e1"}],
        title="Null check", anchor_text="foo()")}

    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)), \
         patch("skills.ask_diff.sync.wc.get_threads", return_value=threads), \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items"):
        result = sync.resync("s1", str(tmp_path))

    assert result["migrated"] == []
    assert result["orphaned"] == [anchor]
    mock_append.assert_not_called()
    mock_delete.assert_not_called()

    mock_submit.assert_called_once()
    args, kwargs = mock_submit.call_args
    assert args[0] == "s1"
    assert args[1] == anchor
    payload = json.loads(args[2])
    assert payload == {"event_kind": "anchor_orphaned", "thread_title": "Null check",
                       "old_anchor_text": "foo()", "reason": "stale"}
    assert kwargs == {"kind": "interactive-review"}


def test_resync_treats_a_deleted_file_the_same_as_stale(tmp_path):
    # The file the anchor points at is gone entirely (renamed or removed).
    anchor = "src/gone.py:R:9"
    threads = {anchor: _thread(
        [{"text": "a reply", "role": "agent", "ts": 1}],
        title="Dead file", anchor_text="foo()")}

    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)), \
         patch("skills.ask_diff.sync.wc.get_threads", return_value=threads), \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items"):
        result = sync.resync("s1", str(tmp_path))

    assert result["orphaned"] == [anchor]
    mock_append.assert_not_called()
    mock_delete.assert_not_called()
    mock_submit.assert_called_once()


# ---------------------------------------------------------------------------
# 4b. Collision: two DIFFERENT anchors resolving to the same target position
#     in one resync pass must never merge into one thread. Found live during
#     Task 4's own end-to-end smoke test against a real daemon, not
#     anticipated when this file was first written.
# ---------------------------------------------------------------------------

def test_resync_orphans_a_moved_thread_whose_target_is_already_occupied(tmp_path):
    """A STALE thread is orphaned in place (its own anchor, untouched, per
    the test above). A SEPARATE, unrelated thread's MOVED target happens to
    land exactly on that still-occupied anchor -- migrating into it would
    silently interleave two unrelated conversations into one thread file,
    since a thread is identified only by its anchor string, not a separate
    id. The MOVED thread must be orphaned too (never merged), tagged
    reason="collision" so Mode D can give an honest explanation, distinct
    from the STALE thread's own reason="stale" orphan event.
    """
    (tmp_path / "x.py").write_text("irrelevant -- locate() is mocked below\n")

    sid = "s1"
    stale_anchor = "x.py:R:7"    # orphaned in place, stays at R:7
    moved_anchor = "x.py:R:5"    # computes a target of x.py:R:7 -- collides
    threads = {
        stale_anchor: _thread(
            [{"text": "stale reply", "role": "agent", "ts": 1, "source_event_id": "eS"}],
            title="Stale finding", anchor_text="line E"),
        moved_anchor: _thread(
            [{"text": "moved reply", "role": "agent", "ts": 1, "source_event_id": "eM"}],
            title="Moved finding", anchor_text="line C"),
    }

    def fake_locate(lines, start, anchor_text, k):
        if anchor_text == "line E":
            return anchor_migrate.Resolution(kind=anchor_migrate.Kind.STALE, line=-1)
        return anchor_migrate.Resolution(kind=anchor_migrate.Kind.MOVED, line=7)

    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)), \
         patch("skills.ask_diff.sync.wc.get_threads", return_value=threads), \
         patch("skills.ask_diff.sync.anchor_migrate.locate", side_effect=fake_locate), \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items") as mock_put:
        result = sync.resync(sid, str(tmp_path))

    # Neither thread migrated -- the MOVED one collided and was orphaned too,
    # never merged into the STALE thread's still-occupied anchor.
    assert result["migrated"] == []
    assert sorted(result["orphaned"]) == sorted([stale_anchor, moved_anchor])
    assert result["collided"] == [moved_anchor]
    mock_append.assert_not_called()
    mock_delete.assert_not_called()

    # Two distinct orphan events, one per thread -- never one merged event.
    assert mock_submit.call_count == 2
    payloads = {c.args[1]: json.loads(c.args[2]) for c in mock_submit.call_args_list}
    assert payloads[stale_anchor]["reason"] == "stale"
    assert payloads[stale_anchor]["thread_title"] == "Stale finding"
    assert "attempted_anchor" not in payloads[stale_anchor]
    assert payloads[moved_anchor]["reason"] == "collision"
    assert payloads[moved_anchor]["thread_title"] == "Moved finding"
    assert payloads[moved_anchor]["attempted_anchor"] == stale_anchor

    # Nothing raised -- this is a deliberate choice, not a failure -- so the
    # refreshed diff/meta still gets pushed.
    assert result["ok"] is True
    mock_put.assert_called_once()


def test_resync_chained_shift_migrates_both_threads_without_losing_either(tmp_path, monkeypatch):
    """The exact false-positive a single-pass, seen-so-far "occupied" check
    used to raise (fix round 1): two comments in one file, both shifted down
    by the same amount (someone inserted lines near the top) so the LOWER
    comment's old line number becomes the UPPER comment's new one -- thread A
    vacates R:5 to land on R:8, thread B vacates R:8 to land on R:11. Fix
    round 1's collision *detection* correctly said "not a collision" here,
    but its *execution* ran migrations in whatever order the daemon returned
    threads, with no regard for the fact that A's target IS B's source --
    running A before B appended A's messages into the anchor B was about to
    delete, destroying A's content while `resync()` still reported
    `ok=True`. A bare-mock test asserting call TARGETS cannot see this: the
    destructive interleaving and the safe one produce the identical set of
    append/delete calls. This uses the stateful `_FakeDaemon` and asserts on
    the actual SURVIVING STORE CONTENTS after resync runs -- the only way to
    tell the two apart.
    """
    lines = [f"line{i}" for i in range(1, 5)]        # lines 1-4
    lines += ["inserted1", "inserted2", "inserted3"]  # lines 5-7 (the shift)
    lines += ["TARGET_X"]                             # line 8 -- was line 5
    lines += ["line9", "line10"]                      # lines 9-10
    lines += ["TARGET_Y"]                             # line 11 -- was line 8
    lines += ["line12"]                               # line 12
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")

    sid = "s1"
    anchor_a = "x.py:R:5"   # recorded at line 5, text "TARGET_X" -> now line 8
    anchor_b = "x.py:R:8"   # recorded at line 8, text "TARGET_Y" -> now line 11
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    # Ascending anchor order -- `threads.snapshot()`'s real sort order, and
    # exactly the order fix round 1 executed destructively (A before B).
    fake.threads[sid] = {
        anchor_a: {"anchor": anchor_a, "version": 1,
                  "messages": [{"text": "reply A", "role": "agent", "ts": 1,
                               "source_event_id": "eA"}],
                  "title": "Finding A", "anchor_text": "TARGET_X"},
        anchor_b: {"anchor": anchor_b, "version": 1,
                  "messages": [{"text": "reply B", "role": "agent", "ts": 1,
                               "source_event_id": "eB"}],
                  "title": "Finding B", "anchor_text": "TARGET_Y"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert sorted(result["migrated"]) == ["x.py:R:11", "x.py:R:8"]
    assert result["orphaned"] == []
    assert result["collided"] == []
    assert result["cycled"] == []
    assert result["ok"] is True

    # The load-bearing assertion: BOTH threads' own messages survive, each
    # at its own correct new anchor -- not merged, not lost. Note anchor_b
    # ("x.py:R:8") is itself A's new home, so checking "not in store" against
    # the old anchor strings would be checking the wrong thing here -- what
    # matters is which THREAD's content sits at each surviving key.
    store = fake.threads[sid]
    assert set(store.keys()) == {"x.py:R:8", "x.py:R:11"}
    assert [m["text"] for m in store["x.py:R:8"]["messages"]] == ["reply A"]
    assert store["x.py:R:8"]["title"] == "Finding A"
    assert [m["text"] for m in store["x.py:R:11"]["messages"]] == ["reply B"]
    assert store["x.py:R:11"]["title"] == "Finding B"


def test_resync_a_two_cycle_orphans_both_threads_without_destroying_either(tmp_path, monkeypatch):
    """Two commented lines that swapped places: A's target is B's source AND
    B's target is A's source, at the same time. No execution order can
    migrate either one first without appending into -- and then having the
    other thread's own delete call throw away -- content that hasn't been
    relocated yet. Both must be orphaned in place instead, `reason="cycle"`,
    with neither thread's content touched at all.
    """
    lines = ["line1", "line2", "line3", "line4",
            "TARGET_B",   # line 5 -- B's text, was recorded at line 8
            "line6", "line7",
            "TARGET_A"]   # line 8 -- A's text, was recorded at line 5
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")

    sid = "s1"
    anchor_a = "x.py:R:5"   # recorded text "TARGET_A" -> now at line 8
    anchor_b = "x.py:R:8"   # recorded text "TARGET_B" -> now at line 5
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        anchor_a: {"anchor": anchor_a, "version": 1,
                  "messages": [{"text": "reply A", "role": "agent", "ts": 1,
                               "source_event_id": "eA"}],
                  "title": "Finding A", "anchor_text": "TARGET_A"},
        anchor_b: {"anchor": anchor_b, "version": 1,
                  "messages": [{"text": "reply B", "role": "agent", "ts": 1,
                               "source_event_id": "eB"}],
                  "title": "Finding B", "anchor_text": "TARGET_B"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["migrated"] == []
    assert sorted(result["orphaned"]) == sorted([anchor_a, anchor_b])
    assert sorted(result["cycled"]) == sorted([anchor_a, anchor_b])
    assert result["collided"] == []  # a cycle is not a collision -- distinct reason
    assert result["ok"] is True

    # Neither thread was touched -- both still sit exactly where they always
    # were, full content intact, nothing merged or destroyed.
    store = fake.threads[sid]
    assert set(store.keys()) == {anchor_a, anchor_b}
    assert [m["text"] for m in store[anchor_a]["messages"]] == ["reply A"]
    assert [m["text"] for m in store[anchor_b]["messages"]] == ["reply B"]

    # Two distinct orphan events, one per thread, both correctly reasoned.
    assert len(fake.events) == 2
    events_by_anchor = {e["anchor"]: e for e in fake.events}
    assert events_by_anchor[anchor_a]["reason"] == "cycle"
    assert events_by_anchor[anchor_a]["attempted_anchor"] == "x.py:R:8"
    assert events_by_anchor[anchor_a]["thread_title"] == "Finding A"
    assert events_by_anchor[anchor_b]["reason"] == "cycle"
    assert events_by_anchor[anchor_b]["attempted_anchor"] == "x.py:R:5"
    assert events_by_anchor[anchor_b]["thread_title"] == "Finding B"


def test_resync_completes_a_stuck_migration_instead_of_orphaning_its_own_duplicate(
        tmp_path, monkeypatch):
    """A thread's migration got stuck last time: its messages were appended
    to the new anchor, but the old anchor's delete never landed (a daemon
    hiccup between the two calls) -- so the SAME thread's content now exists
    at both anchors. The old anchor still resolves MOVED to that same target
    on the next resync, `target_counts` sees two anchors converging on one
    position, and the naive collision check would orphan the original
    PERMANENTLY, every future firing, telling the user another comment is in
    the way when it is really its own stuck copy. `resync()` must recognize
    this via `source_event_id` overlap and finish the migration instead:
    delete the stale old anchor, no orphan event.
    """
    (tmp_path / "x.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 14)) + "\nfoo()\n")
    # "foo()" is on line 14 (1-based).

    sid = "s1"
    stuck_anchor = "x.py:R:9"    # never deleted after its own migration
    landed_anchor = "x.py:R:14"  # where the migration's content already is
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        stuck_anchor: {"anchor": stuck_anchor, "version": 1,
                      "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                   "source_event_id": "e1"}],
                      "title": "Null check", "anchor_text": "foo()"},
        landed_anchor: {"anchor": landed_anchor, "version": 1,
                       "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                    "source_event_id": "e1"}],
                       "title": "Null check", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    # Recognized as a resumable self-collision, not a genuine collision --
    # completed as a migration, never orphaned.
    assert result["migrated"] == [landed_anchor]
    assert result["orphaned"] == []
    assert result["collided"] == []
    assert result["ok"] is True

    store = fake.threads[sid]
    assert stuck_anchor not in store  # the stale duplicate is finally cleaned up
    assert landed_anchor in store
    # Still exactly one message -- the daemon's own dedup made the replay's
    # append a no-op, so nothing is duplicated by "finishing" the migration.
    assert len(store[landed_anchor]["messages"]) == 1
    assert store[landed_anchor]["messages"][0]["source_event_id"] == "e1"


def test_resync_blocks_a_mover_behind_a_thread_that_was_itself_collision_orphaned(
        tmp_path, monkeypatch):
    """The three-thread domino a one-shot occupancy census cannot see (fix
    round 3). A moves 5->8, B moves 8->20, D sits EXACT at 20.

    B's target is D's occupied anchor, so B is collision-orphaned and stays
    where it is -- at 8. But 8 is A's target, and at census time nothing
    ELSE's computed target was 8, so a single-pass check clears A as a "clean
    mover" and executes it straight into the anchor B never left: two
    unrelated conversations silently interleaved into one thread file, with
    `resync()` reporting `ok=True`. Verified against the pre-fix code, which
    ends this exact scenario with `["reply B", "reply A"]` in one thread.

    A thread's true resting anchor is therefore only known once collision
    resolution itself has run, so resolution must reach a FIXED POINT: B
    being pinned at 8 must feed back in and block A, whose own resting place
    then becomes its own anchor, 5. Nothing merges, nothing is lost -- all
    three threads keep their own content at their own anchor, and both
    blocked threads get an honest `reason="collision"` event naming where
    they wanted to go. Needs three threads to trigger, which is why every
    earlier two-thread regression test missed it.
    """
    lines = ["line1", "line2", "line3", "line4",
            "inserted1", "inserted2", "inserted3",
            "TARGET_A"]                                # line 8 -- A's text
    lines += [f"filler{i}" for i in range(9, 20)]       # lines 9-19
    lines += ["SHARED"]                                 # line 20 -- D's text
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")

    sid = "s1"
    anchor_a = "x.py:R:5"    # text "TARGET_A" -> MOVED to line 8
    anchor_b = "x.py:R:8"    # text "SHARED"   -> MOVED to line 20
    anchor_d = "x.py:R:20"   # text "SHARED"   -> EXACT, never moves
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        anchor_a: {"anchor": anchor_a, "version": 1,
                  "messages": [{"text": "reply A", "role": "agent", "ts": 1,
                               "source_event_id": "eA"}],
                  "title": "Finding A", "anchor_text": "TARGET_A"},
        anchor_b: {"anchor": anchor_b, "version": 1,
                  "messages": [{"text": "reply B", "role": "agent", "ts": 1,
                               "source_event_id": "eB"}],
                  "title": "Finding B", "anchor_text": "SHARED"},
        anchor_d: {"anchor": anchor_d, "version": 1,
                  "messages": [{"text": "reply D", "role": "agent", "ts": 1,
                               "source_event_id": "eD"}],
                  "title": "Finding D", "anchor_text": "SHARED"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["migrated"] == []
    assert sorted(result["collided"]) == sorted([anchor_a, anchor_b])
    assert sorted(result["orphaned"]) == sorted([anchor_a, anchor_b])
    assert result["cycled"] == []
    assert result["ok"] is True

    # The load-bearing assertion: three anchors in, three anchors out, each
    # still holding exactly its own one message. No merge anywhere.
    store = fake.threads[sid]
    assert set(store.keys()) == {anchor_a, anchor_b, anchor_d}
    assert [m["text"] for m in store[anchor_a]["messages"]] == ["reply A"]
    assert store[anchor_a]["title"] == "Finding A"
    assert [m["text"] for m in store[anchor_b]["messages"]] == ["reply B"]
    assert store[anchor_b]["title"] == "Finding B"
    # D is stationary and must not have been touched at all.
    assert [m["text"] for m in store[anchor_d]["messages"]] == ["reply D"]
    assert store[anchor_d]["title"] == "Finding D"

    # Both blocked threads say honestly where they wanted to go -- A names
    # B's anchor, B names D's, so the two events are not interchangeable.
    events_by_anchor = {e["anchor"]: e for e in fake.events}
    assert set(events_by_anchor) == {anchor_a, anchor_b}
    assert events_by_anchor[anchor_a]["reason"] == "collision"
    assert events_by_anchor[anchor_a]["attempted_anchor"] == anchor_b
    assert events_by_anchor[anchor_b]["reason"] == "collision"
    assert events_by_anchor[anchor_b]["attempted_anchor"] == anchor_d


@pytest.mark.parametrize("reverse_order", [False, True])
def test_resync_a_four_thread_chain_migrates_every_thread_in_either_order(
        tmp_path, monkeypatch, reverse_order):
    """A chain three links longer than the two-thread case fix round 2 was
    tested on: four comments in one file, all shifted down 3 lines, so EVERY
    mover's target is the next mover's still-occupied source (5->8, 8->11,
    11->14, 14->17). Only one execution order is safe -- strictly last-first
    -- and it must be found whichever order the daemon returns threads in, so
    this runs both. Asserts every thread's own message survives at its own
    correct new anchor, since a wrong order loses content silently rather
    than raising.
    """
    lines = ["line1", "line2", "line3", "line4",
            "inserted1", "inserted2", "inserted3",
            "T1",                       # line 8  -- was line 5
            "filler9", "filler10",
            "T2",                       # line 11 -- was line 8
            "filler12", "filler13",
            "T3",                       # line 14 -- was line 11
            "filler15", "filler16",
            "T4",                       # line 17 -- was line 14
            "filler18"]
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")

    sid = "s1"
    specs = [("x.py:R:5", "T1", "reply 1", "Finding 1"),
            ("x.py:R:8", "T2", "reply 2", "Finding 2"),
            ("x.py:R:11", "T3", "reply 3", "Finding 3"),
            ("x.py:R:14", "T4", "reply 4", "Finding 4")]
    if reverse_order:
        specs = list(reversed(specs))

    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        anchor: {"anchor": anchor, "version": 1,
                "messages": [{"text": text, "role": "agent", "ts": 1,
                             "source_event_id": text}],
                "title": title, "anchor_text": anchor_text}
        for anchor, anchor_text, text, title in specs
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert sorted(result["migrated"]) == sorted(
        ["x.py:R:8", "x.py:R:11", "x.py:R:14", "x.py:R:17"])
    assert result["orphaned"] == []
    assert result["collided"] == []
    assert result["cycled"] == []
    assert result["ok"] is True
    assert fake.events == []

    store = fake.threads[sid]
    assert set(store.keys()) == {"x.py:R:8", "x.py:R:11", "x.py:R:14", "x.py:R:17"}
    for new_anchor, text, title in [("x.py:R:8", "reply 1", "Finding 1"),
                                   ("x.py:R:11", "reply 2", "Finding 2"),
                                   ("x.py:R:14", "reply 3", "Finding 3"),
                                   ("x.py:R:17", "reply 4", "Finding 4")]:
        assert [m["text"] for m in store[new_anchor]["messages"]] == [text]
        assert store[new_anchor]["title"] == title


def test_resync_resumes_a_migration_whose_append_loop_failed_partway(
        tmp_path, monkeypatch):
    """The other half of the stuck-migration case (fix round 3). The test
    above it covers a migration that finished appending and then failed to
    delete, leaving the target with a SUPERSET of the source's message ids.
    This one fails EARLIER -- part-way through the append loop -- so the
    target ends up with a SUBSET instead: only the first of three messages
    made it over.

    Both are the same thread, duplicated by the same interrupted migration,
    and `source_event_id`s are globally unique per submitted event, so any
    overlap at all proves it. A containment check only sees whichever
    direction it was written for: `my_ids <= their_ids` is true for the
    delete-failure but false here, permanently misdiagnosing a half-copied
    thread as a genuine third-party collision and re-emitting the same wrong
    event on every future hook firing. The check must be symmetric overlap.
    """
    (tmp_path / "x.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 14)) + "\nfoo()\n")
    # "foo()" is on line 14 (1-based); the source anchor still records 9.

    sid = "s1"
    stuck_anchor = "x.py:R:9"
    landed_anchor = "x.py:R:14"
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        stuck_anchor: {"anchor": stuck_anchor, "version": 3,
                      "messages": [
                          {"text": "first reply", "role": "agent", "ts": 1,
                           "source_event_id": "e1"},
                          {"text": "a follow-up", "role": "user", "ts": 2,
                           "source_event_id": "e2"},
                          {"text": "second reply", "role": "agent", "ts": 3,
                           "source_event_id": "e3"}],
                      "title": "Null check", "anchor_text": "foo()"},
        # Only the FIRST message made it across before the append loop died.
        landed_anchor: {"anchor": landed_anchor, "version": 1,
                       "messages": [{"text": "first reply", "role": "agent",
                                    "ts": 1, "source_event_id": "e1"}],
                       "title": "Null check", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["migrated"] == [landed_anchor]
    assert result["orphaned"] == []
    assert result["collided"] == []
    assert result["ok"] is True
    assert fake.events == []  # never reported to the user as a collision

    store = fake.threads[sid]
    assert stuck_anchor not in store  # the half-copied source is cleaned up
    assert set(store.keys()) == {landed_anchor}
    # The migration is genuinely finished: all three messages, original
    # order, the already-present one deduped rather than doubled.
    assert [m["source_event_id"] for m in store[landed_anchor]["messages"]] == [
        "e1", "e2", "e3"]
    assert [m["text"] for m in store[landed_anchor]["messages"]] == [
        "first reply", "a follow-up", "second reply"]


@pytest.mark.parametrize("resumable_delete_fails", [False, True])
def test_resync_makes_a_mover_wait_for_a_resumable_self_migration_to_vacate(
        tmp_path, monkeypatch, resumable_delete_fails):
    """A resumable self-migration vacates its own old anchor, so it is a
    dependency for anything migrating INTO that anchor on exactly the same
    terms as any other mover -- it just never has to wait for anyone itself.
    Thread M moves 5->9, and 9 is the stuck anchor a resumable self-migration
    is about to clear.

    Both halves matter. When the self-migration succeeds, M must land at 9
    with its own content. When its delete FAILS, 9 never actually empties, so
    M must NOT execute into it -- the stuck thread's content is still sitting
    there, and appending into it is the interleaving the whole mechanism
    exists to prevent. M simply doesn't move this firing; `ok` is False and
    the next hook firing retries the lot.
    """
    lines = [f"line{i}" for i in range(1, 9)]      # lines 1-8
    lines += ["MTEXT"]                              # line 9  -- M's text
    lines += [f"line{i}" for i in range(10, 14)]    # lines 10-13
    lines += ["foo()"]                              # line 14 -- the landed copy
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")

    sid = "s1"
    mover_anchor = "x.py:R:5"     # text "MTEXT" -> MOVED to line 9
    stuck_anchor = "x.py:R:9"     # text "foo()" -> MOVED to line 14, resumable
    landed_anchor = "x.py:R:14"   # its own already-landed copy, EXACT
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        mover_anchor: {"anchor": mover_anchor, "version": 1,
                      "messages": [{"text": "reply M", "role": "agent", "ts": 1,
                                   "source_event_id": "eM"}],
                      "title": "Finding M", "anchor_text": "MTEXT"},
        stuck_anchor: {"anchor": stuck_anchor, "version": 1,
                      "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                   "source_event_id": "e1"}],
                      "title": "Null check", "anchor_text": "foo()"},
        landed_anchor: {"anchor": landed_anchor, "version": 1,
                       "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                    "source_event_id": "e1"}],
                       "title": "Null check", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    if resumable_delete_fails:
        real_delete = fake.delete_thread

        def flaky_delete(sid_, anchor, *, kind):
            if anchor == stuck_anchor:
                raise RuntimeError("daemon hiccup on delete")
            return real_delete(sid_, anchor, kind=kind)

        monkeypatch.setattr(sync.wc, "delete_thread", flaky_delete)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    store = fake.threads[sid]
    if not resumable_delete_fails:
        assert result["ok"] is True
        assert sorted(result["migrated"]) == sorted([landed_anchor, stuck_anchor])
        assert set(store.keys()) == {stuck_anchor, landed_anchor}
        # M landed in the anchor the self-migration vacated, alone.
        assert [m["text"] for m in store[stuck_anchor]["messages"]] == ["reply M"]
        assert store[stuck_anchor]["title"] == "Finding M"
        assert [m["text"] for m in store[landed_anchor]["messages"]] == ["the reply"]
    else:
        assert result["ok"] is False
        assert result["failed_threads"] == [stuck_anchor]
        assert result["cycled"] == []  # blocked by a failure, not a cycle
        # Nothing merged into the anchor that never emptied: the stuck
        # thread's own content is still the only thing there, and M is
        # untouched at its original anchor for the next firing to retry.
        assert set(store.keys()) == {mover_anchor, stuck_anchor, landed_anchor}
        assert [m["text"] for m in store[stuck_anchor]["messages"]] == ["the reply"]
        assert [m["text"] for m in store[mover_anchor]["messages"]] == ["reply M"]


def test_resync_resumable_self_migration_does_not_disturb_an_unrelated_collision(
        tmp_path, monkeypatch):
    """A resumable self-migration and a genuine collision in the same pass.
    The self-migration must complete (it is one thread finishing its own
    interrupted move) while the two unrelated threads converging on one
    target must BOTH be orphaned (they are two different conversations, and
    whichever executed second would silently interleave into the first).
    Neither resolution may leak into the other.

    `conv_a`/`conv_b` are also this file's only coverage of two movers
    converging on a target NEITHER of them occupies -- the shape that decides
    whether a contested position needs one other claimant or two before it
    counts as a collision. Loosening that threshold merges them here.
    """
    lines = [f"line{i}" for i in range(1, 14)]   # lines 1-13
    lines += ["foo()"]                            # line 14 -- the self-migration
    lines += [f"line{i}" for i in range(15, 50)]  # lines 15-49
    lines += ["DUP"]                              # line 50 -- both movers' target
    lines += [f"line{i}" for i in range(51, 61)]  # lines 51-60
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")

    sid = "s1"
    stuck_anchor = "x.py:R:9"     # its own content already landed at R:14
    landed_anchor = "x.py:R:14"
    conv_a = "x.py:R:40"          # unrelated -- MOVED to R:50
    conv_b = "x.py:R:45"          # unrelated -- MOVED to R:50 as well
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        stuck_anchor: {"anchor": stuck_anchor, "version": 1,
                      "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                   "source_event_id": "e1"}],
                      "title": "Null check", "anchor_text": "foo()"},
        landed_anchor: {"anchor": landed_anchor, "version": 1,
                       "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                    "source_event_id": "e1"}],
                       "title": "Null check", "anchor_text": "foo()"},
        conv_a: {"anchor": conv_a, "version": 1,
                "messages": [{"text": "reply A", "role": "agent", "ts": 1,
                             "source_event_id": "eA"}],
                "title": "Finding A", "anchor_text": "DUP"},
        conv_b: {"anchor": conv_b, "version": 1,
                "messages": [{"text": "reply B", "role": "agent", "ts": 1,
                             "source_event_id": "eB"}],
                "title": "Finding B", "anchor_text": "DUP"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["migrated"] == [landed_anchor]
    assert sorted(result["collided"]) == sorted([conv_a, conv_b])
    assert sorted(result["orphaned"]) == sorted([conv_a, conv_b])
    assert result["cycled"] == []
    assert result["ok"] is True

    store = fake.threads[sid]
    assert set(store.keys()) == {landed_anchor, conv_a, conv_b}
    # The self-migration finished: one anchor, one message, no duplicate.
    assert [m["source_event_id"] for m in store[landed_anchor]["messages"]] == ["e1"]
    # The two converging threads stayed put with their own content, and
    # nothing was written to the position they both wanted.
    assert [m["text"] for m in store[conv_a]["messages"]] == ["reply A"]
    assert [m["text"] for m in store[conv_b]["messages"]] == ["reply B"]
    assert "x.py:R:50" not in store

    events_by_anchor = {e["anchor"]: e for e in fake.events}
    assert set(events_by_anchor) == {conv_a, conv_b}
    assert events_by_anchor[conv_a]["reason"] == "collision"
    assert events_by_anchor[conv_a]["attempted_anchor"] == "x.py:R:50"
    assert events_by_anchor[conv_b]["reason"] == "collision"
    assert events_by_anchor[conv_b]["attempted_anchor"] == "x.py:R:50"


# ---------------------------------------------------------------------------
# 4c. Fragments of ONE thread, scattered by an interrupted migration and then
#     moved again, must be reunited rather than orphaned against each other.
#     Fix round 4: recognising only "my own duplicate is the thread currently
#     occupying my target" heals this on the very next hook firing and never
#     again -- one more commit moves the anchored line, both copies re-locate
#     to a third line neither occupies, and each looks like an ordinary mover
#     converging on a contested position.
# ---------------------------------------------------------------------------

def _stalled_pair_file(tmp_path):
    """`foo()` was on line 14 when the migration from R:9 stalled; the next
    commit moved it to line 17 -- so neither copy's recorded line is right
    any more, and both re-locate to the same third anchor."""
    (tmp_path / "x.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 17)) + "\nfoo()\n")


@pytest.mark.parametrize("shape", ["delete_failure", "append_failure"])
def test_resync_reunites_a_stuck_duplicate_after_both_copies_move_again(
        tmp_path, monkeypatch, shape):
    """Neither fragment is sitting on the other any more, so a check that
    asks "is my duplicate at my target" sees two unrelated movers converging
    and orphans both -- permanently, re-firing the same two bogus collision
    events on every future commit while the duplicate stays visible in the
    IDE at a line it is not about. Both shapes of the interruption end up
    here: a delete that failed after a complete append (the two copies hold
    the same messages) and an append loop that died part-way (the target
    holds a subset). Asserts one surviving anchor holding the UNION, deduped,
    and no collision event at all.
    """
    _stalled_pair_file(tmp_path)

    sid = "s1"
    stuck = "x.py:R:9"     # the source the failed migration never removed
    landed = "x.py:R:14"   # where that migration's messages went
    if shape == "delete_failure":
        stuck_msgs = [{"text": "the reply", "role": "agent", "ts": 1,
                      "source_event_id": "e1"}]
        landed_msgs = [{"text": "the reply", "role": "agent", "ts": 1,
                       "source_event_id": "e1"}]
        expected = [("the reply", "e1")]
    else:
        stuck_msgs = [{"text": "m1", "role": "agent", "ts": 1, "source_event_id": "e1"},
                     {"text": "m2", "role": "user", "ts": 2, "source_event_id": "e2"},
                     {"text": "m3", "role": "agent", "ts": 3, "source_event_id": "e3"}]
        landed_msgs = [{"text": "m1", "role": "agent", "ts": 1, "source_event_id": "e1"}]
        expected = [("m1", "e1"), ("m2", "e2"), ("m3", "e3")]

    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        stuck: {"anchor": stuck, "version": len(stuck_msgs), "messages": stuck_msgs,
               "title": "Null check", "anchor_text": "foo()"},
        landed: {"anchor": landed, "version": len(landed_msgs), "messages": landed_msgs,
                "title": "Null check", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["collided"] == []
    assert result["orphaned"] == []
    assert result["ok"] is True
    assert fake.events == []  # never reported to the user as a collision

    # One thread, at the line `foo()` actually sits on now, holding every
    # message either fragment carried -- exactly what one uninterrupted
    # migration would have produced.
    store = fake.threads[sid]
    assert set(store.keys()) == {"x.py:R:17"}
    assert [(m["text"], m["source_event_id"])
           for m in store["x.py:R:17"]["messages"]] == expected
    assert store["x.py:R:17"]["title"] == "Null check"


def test_resync_reunites_a_stuck_duplicate_on_the_first_firing(tmp_path, monkeypatch):
    """Not "eventually", and not "once more commits happen": the repair must
    land on the first hook firing after the move, and the two firings after
    it must be quiet no-ops rather than more events. Before fix round 4 this
    scenario produced two collision events per firing, forever.
    """
    _stalled_pair_file(tmp_path)

    sid = "s1"
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        "x.py:R:9": {"anchor": "x.py:R:9", "version": 1,
                    "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                 "source_event_id": "e1"}],
                    "title": "Null check", "anchor_text": "foo()"},
        "x.py:R:14": {"anchor": "x.py:R:14", "version": 1,
                     "messages": [{"text": "the reply", "role": "agent", "ts": 1,
                                  "source_event_id": "e1"}],
                     "title": "Null check", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        first = sync.resync(sid, str(tmp_path))
        assert set(fake.threads[sid].keys()) == {"x.py:R:17"}
        assert fake.events == []
        second = sync.resync(sid, str(tmp_path))
        third = sync.resync(sid, str(tmp_path))

    assert first["ok"] and second["ok"] and third["ok"]
    assert second["migrated"] == [] and third["migrated"] == []
    assert second["collided"] == [] and third["collided"] == []
    assert fake.events == []  # no event on ANY of the three firings

    store = fake.threads[sid]
    assert set(store.keys()) == {"x.py:R:17"}
    assert len(store["x.py:R:17"]["messages"]) == 1  # not re-appended per firing


def test_resync_reunites_a_fragment_pair_and_orphans_an_unrelated_third_party(
        tmp_path, monkeypatch):
    """A healing group and a genuine collision landing on the SAME position in
    the same pass. The two fragments must be reunited, and the stranger
    converging on that same line must be orphaned against the reunited thread
    -- neither folded into the repair, nor allowed to make the repair itself
    look contested.
    """
    _stalled_pair_file(tmp_path)

    sid = "s1"
    frag_a = "x.py:R:9"
    frag_b = "x.py:R:14"
    stranger = "x.py:R:20"
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        frag_a: {"anchor": frag_a, "version": 1,
                "messages": [{"text": "frag A", "role": "agent", "ts": 1,
                             "source_event_id": "e1"}],
                "title": "Null check", "anchor_text": "foo()"},
        # Shares e1 with frag_a (common origin) and carries e2 besides.
        frag_b: {"anchor": frag_b, "version": 2,
                "messages": [{"text": "frag B", "role": "agent", "ts": 1,
                             "source_event_id": "e2"},
                            {"text": "frag A", "role": "agent", "ts": 2,
                             "source_event_id": "e1"}],
                "title": "Null check", "anchor_text": "foo()"},
        # A different conversation entirely -- no id in common with either.
        stranger: {"anchor": stranger, "version": 1,
                  "messages": [{"text": "stranger", "role": "agent", "ts": 1,
                               "source_event_id": "eX"}],
                  "title": "Unrelated", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["collided"] == [stranger]
    assert result["orphaned"] == [stranger]
    assert result["cycled"] == []
    assert result["ok"] is True

    store = fake.threads[sid]
    assert set(store.keys()) == {"x.py:R:17", stranger}
    # The pair is reunited, with every message and no repeat of the shared one.
    assert [(m["text"], m["source_event_id"])
           for m in store["x.py:R:17"]["messages"]] == [("frag A", "e1"),
                                                       ("frag B", "e2")]
    assert store["x.py:R:17"]["title"] == "Null check"
    # The stranger kept its own content at its own anchor -- not merged in.
    assert [m["text"] for m in store[stranger]["messages"]] == ["stranger"]
    assert store[stranger]["title"] == "Unrelated"

    events_by_anchor = {e["anchor"]: e for e in fake.events}
    assert set(events_by_anchor) == {stranger}
    assert events_by_anchor[stranger]["reason"] == "collision"
    assert events_by_anchor[stranger]["attempted_anchor"] == "x.py:R:17"


def test_resync_still_orphans_a_five_way_convergence_with_no_shared_ids(
        tmp_path, monkeypatch):
    """The guard on fix round 4's loosening: five separate conversations all
    re-locating to one line share no `source_event_id` with each other, so no
    common-origin group exists and every one of them must still be orphaned.
    Nothing may be written to the contested position.
    """
    _stalled_pair_file(tmp_path)

    sid = "s1"
    anchors = ["x.py:R:5", "x.py:R:9", "x.py:R:12", "x.py:R:14", "x.py:R:20"]
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        a: {"anchor": a, "version": 1,
           "messages": [{"text": f"reply {i}", "role": "agent", "ts": 1,
                        "source_event_id": f"e{i}"}],
           "title": f"Finding {i}", "anchor_text": "foo()"}
        for i, a in enumerate(anchors)
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["migrated"] == []
    assert sorted(result["collided"]) == sorted(anchors)
    assert result["ok"] is True

    store = fake.threads[sid]
    assert set(store.keys()) == set(anchors)  # nothing moved, nothing created
    assert "x.py:R:17" not in store
    for i, a in enumerate(anchors):
        assert [m["text"] for m in store[a]["messages"]] == [f"reply {i}"]
    assert all(e["reason"] == "collision" and e["attempted_anchor"] == "x.py:R:17"
              for e in fake.events)


def test_resync_orphans_two_distinct_fragment_groups_converging_on_one_target(
        tmp_path, monkeypatch):
    """Two SEPARATE interrupted migrations whose fragments happen to re-locate
    to the same line. Each pair is internally common-origin, but the two pairs
    share nothing with each other, so whichever was reunited at the contested
    position would be an arbitrary winner and the other would be merged into
    it. Healing requires exactly one multi-member group; two means nobody
    heals and all four are orphaned in place.
    """
    _stalled_pair_file(tmp_path)

    sid = "s1"
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        "x.py:R:9": {"anchor": "x.py:R:9", "version": 1,
                    "messages": [{"text": "P1", "role": "agent", "ts": 1,
                                 "source_event_id": "p1"}],
                    "title": "P", "anchor_text": "foo()"},
        "x.py:R:14": {"anchor": "x.py:R:14", "version": 1,
                     "messages": [{"text": "P2", "role": "agent", "ts": 1,
                                  "source_event_id": "p1"}],
                     "title": "P", "anchor_text": "foo()"},
        "x.py:R:20": {"anchor": "x.py:R:20", "version": 1,
                     "messages": [{"text": "Q1", "role": "agent", "ts": 1,
                                  "source_event_id": "q1"}],
                     "title": "Q", "anchor_text": "foo()"},
        "x.py:R:22": {"anchor": "x.py:R:22", "version": 1,
                     "messages": [{"text": "Q2", "role": "agent", "ts": 1,
                                  "source_event_id": "q1"}],
                     "title": "Q", "anchor_text": "foo()"},
    }
    fake.patch_all(monkeypatch)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["migrated"] == []
    assert len(result["collided"]) == 4
    assert result["ok"] is True

    store = fake.threads[sid]
    assert set(store.keys()) == {"x.py:R:9", "x.py:R:14", "x.py:R:20", "x.py:R:22"}
    assert "x.py:R:17" not in store
    assert [m["text"] for m in store["x.py:R:9"]["messages"]] == ["P1"]
    assert [m["text"] for m in store["x.py:R:14"]["messages"]] == ["P2"]
    assert [m["text"] for m in store["x.py:R:20"]["messages"]] == ["Q1"]
    assert [m["text"] for m in store["x.py:R:22"]["messages"]] == ["Q2"]


def test_resync_leaves_a_non_locatable_anchor_alone(tmp_path):
    # __general__ (or any anchor that isn't path:side:line[-line]) is not
    # ours to migrate or orphan.
    threads = {"__general__": _thread([{"text": "hi", "role": "agent", "ts": 1}])}

    with patch("skills.ask_diff.sync.wc.get_items", return_value=_meta_items()), \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)), \
         patch("skills.ask_diff.sync.wc.get_threads", return_value=threads), \
         patch("skills.ask_diff.sync.wc.append_thread") as mock_append, \
         patch("skills.ask_diff.sync.wc.delete_thread") as mock_delete, \
         patch("skills.ask_diff.sync.wc.submit_event") as mock_submit, \
         patch("skills.ask_diff.sync.wc.put_items"):
        result = sync.resync("s1", str(tmp_path))

    assert result["migrated"] == []
    assert result["orphaned"] == []
    mock_append.assert_not_called()
    mock_delete.assert_not_called()
    mock_submit.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Idempotency: a repeat resync against an unchanged working tree must not
#    duplicate anything, against a real stateful fake of the daemon's own
#    dedup / first-write-wins / last-write-wins rules. (`_FakeDaemon` itself
#    is defined near the top of this file -- section 4b's ordering tests use
#    it too.)
# ---------------------------------------------------------------------------

def test_resync_run_twice_against_an_unchanged_tree_does_not_duplicate(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    lines = [f"line{i}" for i in range(1, 15)]
    lines[14 - 1] = "foo()"  # moved from recorded line 9 to real line 14
    (tmp_path / "src" / "x.py").write_text("\n".join(lines) + "\n")

    fake = _FakeDaemon()
    sid = "s1"
    fake.items[sid] = _meta_items()
    old_anchor = "src/x.py:R:9"
    fake.threads[sid] = {old_anchor: {
        "anchor": old_anchor, "version": 1,
        "messages": [{"text": "a reply", "role": "agent", "ts": 1,
                     "source_event_id": "e1"}],
        "title": "Null check", "anchor_text": "foo()",
    }}

    monkeypatch.setattr(sync.wc, "get_items", fake.get_items)
    monkeypatch.setattr(sync.wc, "put_items", fake.put_items)
    monkeypatch.setattr(sync.wc, "get_threads", fake.get_threads)
    monkeypatch.setattr(sync.wc, "append_thread", fake.append_thread)
    monkeypatch.setattr(sync.wc, "delete_thread", fake.delete_thread)
    monkeypatch.setattr(sync.wc, "submit_event", fake.submit_event)

    with patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("SAME DIFF", SAMPLE_GH_META)):
        first = sync.resync(sid, str(tmp_path))
        second = sync.resync(sid, str(tmp_path))

    new_anchor = "src/x.py:R:14"
    assert first["migrated"] == [new_anchor]
    assert first["orphaned"] == []
    # Second run: the anchor is already at line 14, matching the recorded
    # line -- locate() returns EXACT, so nothing migrates again.
    assert second["migrated"] == []
    assert second["orphaned"] == []

    assert old_anchor not in fake.threads[sid]
    assert new_anchor in fake.threads[sid]
    # Exactly one message, not duplicated by the second run.
    assert len(fake.threads[sid][new_anchor]["messages"]) == 1
    assert fake.threads[sid][new_anchor]["messages"][0]["source_event_id"] == "e1"


def test_resync_double_run_of_a_moved_replay_itself_is_deduped_by_source_event_id(tmp_path, monkeypatch):
    # A stronger idempotency case: simulate the SAME migration being
    # attempted twice back-to-back with no state persisted between calls
    # (e.g. two hook firings racing before the first migration's delete
    # lands) by replaying onto a thread that already has one of the two
    # messages recorded. Dedup must be by source_event_id, not by count.
    fake = _FakeDaemon()
    sid = "s1"
    new_anchor = "src/x.py:R:14"
    fake.threads[sid] = {new_anchor: {
        "anchor": new_anchor, "version": 1,
        "messages": [{"text": "first reply", "role": "agent", "ts": 1,
                     "source_event_id": "e1"}],
        "title": "Null check", "anchor_text": "foo()",
    }}
    monkeypatch.setattr(sync.wc, "append_thread", fake.append_thread)
    monkeypatch.setattr(sync.wc, "delete_thread", fake.delete_thread)

    old_thread = {
        "anchor": "src/x.py:R:9", "version": 2,
        "messages": [
            {"text": "first reply", "role": "agent", "ts": 1, "source_event_id": "e1"},
            {"text": "second reply", "role": "agent", "ts": 2, "source_event_id": "e2"},
        ],
        "title": "Null check", "anchor_text": "foo()",
    }
    sync._migrate_thread(sid, "src/x.py:R:9", new_anchor, old_thread, "foo()")

    messages = fake.threads[sid][new_anchor]["messages"]
    assert [m["source_event_id"] for m in messages] == ["e1", "e2"]
    assert len(messages) == 2  # "e1" deduped, not appended a second time


# ---------------------------------------------------------------------------
# 6. Failure isolation: one thread's daemon call raising must not abort the
#    rest of the session's threads, and must gate the final put_items push.
# ---------------------------------------------------------------------------

def test_resync_isolates_a_mid_loop_thread_failure_from_the_others(tmp_path, monkeypatch):
    current_lines = [f"line{i}" for i in range(1, 21)]
    current_lines[4] = "AAA"    # index 4 -> line 5 (1-based)
    current_lines[9] = "BBB"    # index 9 -> line 10
    current_lines[14] = "CCC"   # index 14 -> line 15
    (tmp_path / "x.py").write_text("\n".join(current_lines) + "\n")

    sid = "s1"
    fake = _FakeDaemon()
    fake.items[sid] = _meta_items()
    fake.threads[sid] = {
        "x.py:R:2": {"anchor": "x.py:R:2", "version": 1,
                    "messages": [{"text": "reply A", "role": "agent", "ts": 1,
                                 "source_event_id": "eA"}],
                    "title": "A", "anchor_text": "AAA"},
        "x.py:R:6": {"anchor": "x.py:R:6", "version": 1,
                    "messages": [{"text": "reply B", "role": "agent", "ts": 1,
                                 "source_event_id": "eB"}],
                    "title": "B", "anchor_text": "BBB"},
        "x.py:R:11": {"anchor": "x.py:R:11", "version": 1,
                     "messages": [{"text": "reply C", "role": "agent", "ts": 1,
                                  "source_event_id": "eC"}],
                     "title": "C", "anchor_text": "CCC"},
    }
    # A -> MOVED to x.py:R:5, B -> MOVED to x.py:R:10, C -> MOVED to x.py:R:15.
    # B's replay is the one that blows up mid-loop.
    real_append = fake.append_thread

    def flaky_append(sid_, anchor, text, **kwargs):
        if anchor == "x.py:R:10":
            raise RuntimeError("daemon hiccup mid-migration")
        return real_append(sid_, anchor, text, **kwargs)

    monkeypatch.setattr(sync.wc, "get_items", fake.get_items)
    monkeypatch.setattr(sync.wc, "get_threads", fake.get_threads)
    monkeypatch.setattr(sync.wc, "append_thread", flaky_append)
    monkeypatch.setattr(sync.wc, "delete_thread", fake.delete_thread)
    monkeypatch.setattr(sync.wc, "submit_event", fake.submit_event)

    with patch("skills.ask_diff.sync.wc.put_items") as mock_put, \
         patch("skills.ask_diff.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", SAMPLE_GH_META)):
        result = sync.resync(sid, str(tmp_path))

    assert result["ok"] is False
    assert sorted(result["migrated"]) == ["x.py:R:15", "x.py:R:5"]
    assert result["failed_threads"] == ["x.py:R:6"]
    # The refreshed diff/meta must NOT be pushed while one thread's
    # migration is incomplete -- same "stale-but-known-good beats
    # half-overwritten" reasoning as a failed diff fetch.
    mock_put.assert_not_called()

    # Thread A's migration genuinely landed in the fake store (not just a
    # recorded mock call) -- proving it isn't rolled back by B's failure.
    assert fake.threads[sid]["x.py:R:5"]["messages"][0]["text"] == "reply A"
    assert "x.py:R:2" not in fake.threads[sid]
    # Thread C was still attempted AFTER B's mid-loop failure, and landed.
    assert fake.threads[sid]["x.py:R:15"]["messages"][0]["text"] == "reply C"
    assert "x.py:R:11" not in fake.threads[sid]
    # B's old thread is left exactly as it was -- its message never
    # replayed, so nothing was deleted; a later hook firing retries safely.
    assert "x.py:R:6" in fake.threads[sid]
    assert len(fake.threads[sid]["x.py:R:6"]["messages"]) == 1


def test_main_isolates_one_sessions_resync_failure_from_the_next():
    with patch("skills.ask_diff.sync.subprocess.check_output",
              side_effect=["/repo\n", "feature/frob\n"]), \
         patch("skills.ask_diff.sync.find_matching_sessions",
              return_value=["s1", "s2"]), \
         patch("skills.ask_diff.sync.resync",
              side_effect=[RuntimeError("boom"), {"sid": "s2", "ok": True}]) as mock_resync:
        rc = sync.main([])

    assert rc == 0
    # Both sessions were attempted -- s1's total failure did not stop the
    # loop before it reached s2.
    assert mock_resync.call_args_list == [
        (("s1", "/repo"), {}), (("s2", "/repo"), {}),
    ]


# ---------------------------------------------------------------------------
# find_matching_sessions
# ---------------------------------------------------------------------------

def test_find_matching_sessions_matches_on_recorded_head(monkeypatch):
    rows = [{"sid": "s1", "cwd": "/repo", "kind": "interactive-review"},
           {"sid": "s2", "cwd": "/repo", "kind": "interactive-review"}]
    items_by_sid = {
        "s1": _meta_items(head="feature/frob"),
        "s2": _meta_items(head="other-branch"),
    }
    with patch("skills.ask_diff.sync.wc.list_sessions", return_value=rows) as mock_list, \
         patch("skills.ask_diff.sync.wc.get_items", side_effect=lambda sid, kind: items_by_sid[sid]):
        matches = sync.find_matching_sessions("/repo", "feature/frob")

    assert matches == ["s1"]
    # Goes through the public wrapper, not the shared client's private
    # `_request` helper -- a cross-module reach into a private symbol.
    mock_list.assert_called_once_with("/repo", "interactive-review")


def test_find_matching_sessions_returns_every_match(monkeypatch):
    rows = [{"sid": "s1"}, {"sid": "s2"}]
    items_by_sid = {
        "s1": _meta_items(head="feature/frob"),
        "s2": _meta_items(head="feature/frob"),
    }
    with patch("skills.ask_diff.sync.wc.list_sessions", return_value=rows), \
         patch("skills.ask_diff.sync.wc.get_items", side_effect=lambda sid, kind: items_by_sid[sid]):
        matches = sync.find_matching_sessions("/repo", "feature/frob")

    assert sorted(matches) == ["s1", "s2"]


def test_find_matching_sessions_skips_a_session_with_no_meta_yet(monkeypatch):
    rows = [{"sid": "s1"}, {"sid": "s2"}]

    def fake_get_items(sid, *, kind):
        if sid == "s1":
            return {}  # never successfully pushed
        return _meta_items(head="feature/frob")

    with patch("skills.ask_diff.sync.wc.list_sessions", return_value=rows), \
         patch("skills.ask_diff.sync.wc.get_items", side_effect=fake_get_items):
        matches = sync.find_matching_sessions("/repo", "feature/frob")

    assert matches == ["s2"]


def test_find_matching_sessions_skips_a_candidate_whose_items_fetch_fails(monkeypatch):
    rows = [{"sid": "s1"}, {"sid": "s2"}]

    def fake_get_items(sid, *, kind):
        if sid == "s1":
            raise RuntimeError("session ended")
        return _meta_items(head="feature/frob")

    with patch("skills.ask_diff.sync.wc.list_sessions", return_value=rows), \
         patch("skills.ask_diff.sync.wc.get_items", side_effect=fake_get_items):
        matches = sync.find_matching_sessions("/repo", "feature/frob")

    assert matches == ["s2"]


# ---------------------------------------------------------------------------
# main() -- the git-hook entry point
# ---------------------------------------------------------------------------

def test_main_never_raises_and_exits_zero_when_the_daemon_is_unreachable():
    with patch("skills.ask_diff.sync.subprocess.check_output",
              side_effect=["/repo\n", "feature/frob\n"]), \
         patch("skills.ask_diff.sync.find_matching_sessions",
              side_effect=RuntimeError("daemon unreachable")):
        assert sync.main([]) == 0


def test_main_resyncs_every_matching_session():
    with patch("skills.ask_diff.sync.subprocess.check_output",
              side_effect=["/repo\n", "feature/frob\n"]), \
         patch("skills.ask_diff.sync.find_matching_sessions",
              return_value=["s1", "s2"]) as mock_find, \
         patch("skills.ask_diff.sync.resync") as mock_resync:
        rc = sync.main([])

    assert rc == 0
    mock_find.assert_called_once_with("/repo", "feature/frob")
    assert mock_resync.call_args_list == [
        (("s1", "/repo"), {}), (("s2", "/repo"), {}),
    ]


def test_main_no_ops_when_not_on_a_branch(tmp_path):
    # git branch --show-current prints "" in detached HEAD -- nothing to
    # match against, and nothing should blow up.
    with patch("skills.ask_diff.sync.subprocess.check_output",
              side_effect=["/repo\n", "\n"]), \
         patch("skills.ask_diff.sync.find_matching_sessions") as mock_find:
        assert sync.main([]) == 0
    mock_find.assert_not_called()


def test_main_swallows_a_git_failure(tmp_path):
    with patch("skills.ask_diff.sync.subprocess.check_output",
              side_effect=subprocess.CalledProcessError(128, ["git"])):
        assert sync.main([]) == 0
