"""End-to-end smoke: a choice block, a pick submit, and resolution to markdown."""
import http.client
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skills.annotate import blocks as blocks_model
from skills.annotate.tests.test_server import (
    _create_session, _http_get, _start_server, _write_blocks,
)


class ChoiceSmokeTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="annotate-choice-"))
        self.fake_home = Path(tempfile.mkdtemp(prefix="annotate-choice-home-"))
        self.proc, self.info = _start_server(self.fake_home)
        self.sess = _create_session(self.info["port"], self.project)
        self.base = f"/s/{self.sess['sid']}"

    def tearDown(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.project, ignore_errors=True)
        shutil.rmtree(self.fake_home, ignore_errors=True)

    def _post_json(self, path, payload):
        conn = http.client.HTTPConnection("localhost", self.info["port"], timeout=2)
        conn.request("POST", path, body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        status = resp.status
        conn.close()
        return status, body

    def test_e2e_choice_pick_then_resolve(self):
        response_dir = Path(self.sess["response_dir"])
        spec = {
            "question": "How should we cut over?",
            "multiSelect": False,
            "options": [
                {"id": "o1", "label": "Big-bang"},
                {"id": "o2", "label": "Incremental"},
            ],
        }
        _write_blocks(response_dir, "resp-choice", "choice-smoke", [
            {"id": "b-0", "kind": "choice", "spec": spec, "version": 1},
        ])

        # 1. /raw exposes the choice block with spec, no svg/markdown.
        status, body = _http_get("localhost", self.info["port"], self.base + "/raw")
        self.assertEqual(status, 200)
        blk = next(b for b in json.loads(body)["blocks"] if b["id"] == "b-0")
        self.assertEqual(blk["kind"], "choice")
        self.assertEqual(blk["spec"], spec)
        self.assertEqual(blk["version"], 1)

        # 2. POST the pick → 202, event stores selected_options.
        status, _ = self._post_json(self.base + "/api/submit", {
            "block_id": "b-0", "type": "choice", "selected_options": ["o2"],
        })
        self.assertEqual(status, 202)
        events_dir = Path(self.sess["events_dir"])
        evt = json.loads(list(events_dir.glob("*.json"))[0].read_text())
        self.assertEqual(evt["type"], "choice")
        self.assertEqual(evt["selected_options"], ["o2"])

        # 3. Simulate Claude resolving the choice into a markdown decision.
        blocks_path = response_dir / "blocks.json"
        doc = blocks_model.load(blocks_path)
        changed = blocks_model.convert_block_to_markdown(
            doc, "b-0", "Decision: incremental cutover.")
        self.assertTrue(changed)
        blocks_model.save_atomic(blocks_path, doc)

        # 4. /raw now shows a markdown block (kind flipped, version bumped).
        status, body = _http_get("localhost", self.info["port"], self.base + "/raw")
        self.assertEqual(status, 200)
        blk2 = next(b for b in json.loads(body)["blocks"] if b["id"] == "b-0")
        self.assertEqual(blk2["kind"], "markdown")
        self.assertEqual(blk2["markdown"], "Decision: incremental cutover.")
        self.assertNotIn("spec", blk2)
        self.assertEqual(blk2["version"], 2)

    def test_e2e_note_only_then_repropose(self):
        response_dir = Path(self.sess["response_dir"])
        spec = {
            "question": "New name for the bot?",
            "multiSelect": False,
            "options": [
                {"id": "o1", "label": "Koumbaras", "recommended": True},
                {"id": "o2", "label": "Ovolos"},
            ],
        }
        _write_blocks(response_dir, "resp-note", "note-smoke", [
            {"id": "b-0", "kind": "choice", "spec": spec, "version": 1},
        ])

        # 1. Note-only submit: no pick, a direction instead → 202.
        status, _ = self._post_json(self.base + "/api/submit", {
            "block_id": "b-0", "type": "choice", "selected_options": [],
            "text": "none of these — try nautical names",
        })
        self.assertEqual(status, 202)
        events_dir = Path(self.sess["events_dir"])
        evt = json.loads(list(events_dir.glob("*.json"))[0].read_text())
        self.assertEqual(evt["selected_options"], [])
        self.assertEqual(evt["text"], "none of these — try nautical names")

        # 1b. /raw initializes versions.json, confirms initial choice block.
        status, body = _http_get("localhost", self.info["port"], self.base + "/raw")
        self.assertEqual(status, 200)
        blk = next(b for b in json.loads(body)["blocks"] if b["id"] == "b-0")
        self.assertEqual(blk["kind"], "choice")
        self.assertEqual(blk["spec"], spec)
        self.assertEqual(blk["version"], 1)

        # 2. Simulate Claude re-proposing (spec update, NOT resolution).
        blocks_path = response_dir / "blocks.json"
        doc = blocks_model.load(blocks_path)
        new_spec = {
            "question": "New name for the bot?",
            "multiSelect": False,
            "options": [
                {"id": "o1", "label": "Trata"},
                {"id": "o2", "label": "Kaiki"},
            ],
        }
        self.assertTrue(blocks_model.update_spec_block(doc, "b-0", new_spec))
        blocks_model.save_atomic(blocks_path, doc)

        # 3. /raw still shows a choice block, new options, bumped version.
        status, body = _http_get("localhost", self.info["port"], self.base + "/raw")
        self.assertEqual(status, 200)
        blk = next(b for b in json.loads(body)["blocks"] if b["id"] == "b-0")
        self.assertEqual(blk["kind"], "choice")
        self.assertEqual(blk["spec"], new_spec)
        self.assertEqual(blk["version"], 2)


if __name__ == "__main__":
    unittest.main()
