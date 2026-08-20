import http.client
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skills.annotate import server
from skills.annotate.tests.test_server import (
    _create_session, _http_get, _start_server, _write_blocks,
)


class TestRenderBlockAnchors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\nb = 2\nc = 3\n")
        self.addCleanup(self.tmp.cleanup)

    def test_block_without_anchors_has_no_code_key(self):
        out = server._render_block_for_raw(
            {"id": "section-1", "markdown": "hi"}, 1, self.root)
        self.assertNotIn("code", out)

    def test_resolved_anchor_carries_the_real_lines(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "mod.py", "line": 2, "snippet": "b = 2"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(len(out["code"]), 1)
        pane = out["code"][0]
        self.assertEqual(pane["status"], "ok")
        texts = [l["text"] for l in pane["lines"]]
        self.assertIn("b = 2", texts)

    def test_a_bad_anchor_is_a_status_not_an_exception(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "../escape.py", "line": 1, "snippet": "x"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(out["code"][0]["status"], "refused")
        # The block itself still rendered.
        self.assertEqual(out["markdown"], "hi")

    def test_anchors_on_a_flowchart_block_still_resolve(self):
        blk = {"id": "section-1", "kind": "flowchart",
               "spec": {"nodes": [], "edges": []},
               "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(out["code"][0]["status"], "ok")

    def test_no_repo_root_means_no_panes_rather_than_a_crash(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}
        out = server._render_block_for_raw(blk, 1, None)
        self.assertNotIn("code", out)


class TestRawRouteResolvesAnchors(unittest.TestCase):
    """HTTP-level coverage: proves the *route* wires dirs["_cwd"] through to
    _render_block_for_raw, not just that the function behaves when called
    directly. Finding 1 of Task 5's review — the function-level tests above
    do not exercise serve_data's two call sites or the real /raw response."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="annotate-anchor-test-"))
        (self.project / "mod.py").write_text("a = 1\nb = 2\nc = 3\n")
        self.fake_home = Path(tempfile.mkdtemp(prefix="annotate-anchor-home-"))
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

    def _write(self):
        response_dir = Path(self.sess["response_dir"])
        _write_blocks(response_dir, "resp-anchors", "T", [
            {"id": "good-block", "markdown": "hi",
             "code": [{"file": "mod.py", "line": 2, "snippet": "b = 2"}]},
            {"id": "bad-block", "markdown": "hi",
             "code": [{"file": "../escape.py", "line": 1, "snippet": "x"}]},
        ])

    def test_raw_all_blocks_resolves_good_and_bad_anchors(self):
        self._write()
        status, body = _http_get(
            "localhost", self.info["port"], self.base + "/raw")
        self.assertEqual(status, 200)
        data = json.loads(body)
        good = next(b for b in data["blocks"] if b["id"] == "good-block")
        bad = next(b for b in data["blocks"] if b["id"] == "bad-block")
        self.assertEqual(good["code"][0]["status"], "ok")
        texts = [l["text"] for l in good["code"][0]["lines"]]
        self.assertIn("b = 2", texts)
        self.assertEqual(bad["code"][0]["status"], "refused")
        self.assertNotIn("lines", bad["code"][0])

    def test_raw_single_block_query_also_resolves_anchors(self):
        # server.py:474 (the block= query) is a separate call site from the
        # all-blocks path at :481 -- both must pass dirs["_cwd"] through.
        self._write()
        status, body = _http_get(
            "localhost", self.info["port"], self.base + "/raw?block=bad-block")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["code"][0]["status"], "refused")
        self.assertNotIn("lines", data["code"][0])


if __name__ == "__main__":
    unittest.main()
