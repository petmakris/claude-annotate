"""`type: "round"` submit — one event carrying every piece of content feedback.

A round is the ONLY path for content feedback: the client accumulates
delete/keep/comment marks locally, at block scope (card header) and unit
scope (a paragraph/bullet/row in the body), and submits them all at once.
The server validates shape + block existence and queues ONE event.
"""
import json
import shutil
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path

from skills.annotate.tests.test_server import (  # noqa: E402
    _start_server, _create_session, _write_blocks,
)


def _reaction(kind="keep", block_id="section-1", **kw):
    r = {"kind": kind, "block_id": block_id, "selected_text": "alpha one"}
    r.update(kw)
    return r


class SubmitRoundTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="rd-proj-"))
        self.home = Path(tempfile.mkdtemp(prefix="rd-home-"))
        self.proc, self.info = _start_server(self.home)
        self.sess = _create_session(self.info["port"], self.project)
        _write_blocks(Path(self.sess["response_dir"]), "resp-rd", "T", [
            {"id": "section-1", "title": "A",
             "markdown": "- alpha one\n- alpha two\n- alpha one"},
            {"id": "section-2", "title": "B", "markdown": "beta"},
        ])

    def tearDown(self):
        try:
            self.proc.terminate(); self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.project, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _submit(self, payload: dict):
        conn = HTTPConnection("localhost", self.info["port"], timeout=2)
        conn.request("POST", f"/s/{self.sess['sid']}/api/submit",
                     body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read().decode()

    def _event(self, event_id: str) -> dict:
        path = Path(self.sess["events_dir"]) / f"{event_id}.json"
        return json.loads(path.read_text())

    def test_round_queues_single_event_with_reactions(self):
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("keep"),
            _reaction("delete", selected_text="alpha two"),
            _reaction("comment", block_id="section-2", selected_text="beta",
                      text="why beta?"),
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual(evt["type"], "round")
        self.assertEqual(len(evt["reactions"]), 3)
        self.assertEqual(evt["reactions"][2]["text"], "why beta?")

    def test_round_passes_prefix_suffix_through(self):
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("delete", prefix="", suffix=" alpha two"),
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual(evt["reactions"][0]["suffix"], " alpha two")

    def test_block_scope_needs_no_selected_text(self):
        """A block-scope reaction is anchored by block_id alone — requiring
        selected_text there would make the card-header controls unusable."""
        status, body = self._submit({"type": "round", "reactions": [
            {"scope": "block", "kind": "delete", "block_id": "section-1"},
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual(evt["reactions"][0]["scope"], "block")
        self.assertEqual(evt["reactions"][0]["kind"], "delete")

    def test_step_scope_needs_no_selected_text(self):
        """Diagram/flowchart nodes anchor by step_id rather than by text."""
        status, body = self._submit({"type": "round", "reactions": [
            {"scope": "unit", "kind": "comment", "block_id": "section-1",
             "step_id": "node-3", "text": "why this branch?"},
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual(evt["reactions"][0]["step_id"], "node-3")

    def test_disagree_flag_survives(self):
        """Disagreement rides as a flag on a comment, not a fourth kind."""
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("comment", text="wrong, because…", disagree=True),
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertIs(evt["reactions"][0]["disagree"], True)

    def test_scope_defaults_to_unit(self):
        status, body = self._submit(
            {"type": "round", "reactions": [_reaction("keep")]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual(evt["reactions"][0]["scope"], "unit")

    def test_round_rejects_bad_scope(self):
        status, _ = self._submit({"type": "round", "reactions": [
            _reaction("keep", scope="page"),
        ]})
        self.assertEqual(status, 422)

    def test_legacy_kinds_are_translated_not_rejected(self):
        """A tab opened before the rename still submits agree/dismiss. Reject
        it and that page is wedged with no recovery, so translate instead."""
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("agree"),
            _reaction("dismiss", selected_text="alpha two"),
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual([r["kind"] for r in evt["reactions"]],
                         ["keep", "delete"])

    def test_round_rejects_empty_reactions(self):
        status, _ = self._submit({"type": "round", "reactions": []})
        self.assertEqual(status, 422)

    def test_round_rejects_missing_reactions(self):
        status, _ = self._submit({"type": "round"})
        self.assertEqual(status, 422)

    def test_round_rejects_bad_kind(self):
        status, _ = self._submit(
            {"type": "round", "reactions": [_reaction("shrug")]})
        self.assertEqual(status, 422)

    def test_round_rejects_unknown_block(self):
        status, _ = self._submit(
            {"type": "round", "reactions": [_reaction(block_id="section-99")]})
        self.assertEqual(status, 422)

    def test_round_rejects_comment_without_text(self):
        status, _ = self._submit(
            {"type": "round", "reactions": [_reaction("comment")]})
        self.assertEqual(status, 422)

    def test_round_rejects_empty_selected_text(self):
        status, _ = self._submit(
            {"type": "round", "reactions": [_reaction(selected_text="")]})
        self.assertEqual(status, 422)

    def test_compact_is_a_round_kind_at_both_scopes(self):
        """Compact rides the round like the other three kinds.

        Unit scope anchors by selected_text; block scope by block_id alone.
        """
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("compact"),
            {"kind": "compact", "scope": "block", "block_id": "section-2",
             "selected_text": ""},
        ]})
        self.assertEqual(status, 202, body)
        evt = self._event(json.loads(body)["event_id"])
        self.assertEqual([r["kind"] for r in evt["reactions"]],
                         ["compact", "compact"])
        self.assertEqual(evt["reactions"][0]["scope"], "unit")
        self.assertEqual(evt["reactions"][1]["scope"], "block")

    def test_compact_carries_no_text(self):
        """Only `comment` requires non-empty text. Compact says nothing —
        it is a request to remove, not a message."""
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("compact", text=""),
        ]})
        self.assertEqual(status, 202, body)

    def test_unknown_kind_is_still_refused(self):
        """Guard the allowlist itself: widening it for compact must not
        turn it into a pass-through."""
        status, body = self._submit({"type": "round", "reactions": [
            _reaction("squash"),
        ]})
        self.assertEqual(status, 422, body)
        self.assertIn("bad kind", body)


if __name__ == "__main__":
    unittest.main()
