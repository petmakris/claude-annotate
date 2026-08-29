"""A real server start migrates a legacy workspace and still serves it.

The unit tests prove `migrate_workspaces` moves files. This proves the thing
the user actually cares about: a workspace created back when content was
written inside the project is, after one server start, reachable by its slug
from a central home — and then survives the project directory being deleted,
which is the failure that motivated the move.
"""
import http.client
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skills.annotate.tests.test_server import _start_server, _http_get

SID = "260811-225744-f14fb462eff4665f"
SLUG = "picon-473-business-view"


def _legacy_workspace(home: Path, project: Path) -> None:
    """The exact pre-migration layout: tree inside the project, registry in HOME."""
    base = project / ".claude" / "annotate" / SID
    for sub in ("response", "annotations", "state", "state/events", "state/consumed"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (base / "response" / "blocks.json").write_text(json.dumps(
        {"response_id": "r1", "title": "PICON-473 business view",
         "blocks": [{"id": "section-1", "title": "A", "markdown": "alpha"}]}))
    (base / "annotations" / "keep.json").write_text('{"comment": "irreplaceable"}')

    state_root = home / ".claude" / "annotate"
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "sessions.json").write_text(json.dumps({SID: {
        "response_dir": str(base / "response"),
        "annotations_dir": str(base / "annotations"),
        "state_dir": str(base / "state"),
        "events_dir": str(base / "state" / "events"),
        "consumed_dir": str(base / "state" / "consumed"),
        "_cwd": str(project),
    }}))
    (state_root / "sessions_meta.json").write_text(json.dumps({SID: {
        "slug": SLUG, "title": "PICON-473 business view",
        "project": "montblanc", "created_at": 1_700_000_000}}))


class MigrateOnStartupTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="mig-proj-"))
        self.home = Path(tempfile.mkdtemp(prefix="mig-home-"))
        _legacy_workspace(self.home, self.project)
        self.proc, self.info = _start_server(self.home)
        self.new_base = self.home / ".claude" / "annotate" / "workspaces" / SID

    def tearDown(self):
        try:
            self.proc.terminate(); self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.project, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_content_moved_out_of_the_project(self):
        self.assertTrue(self.new_base.is_dir())
        self.assertEqual(
            (self.new_base / "annotations" / "keep.json").read_text(),
            '{"comment": "irreplaceable"}')
        self.assertFalse((self.project / ".claude" / "annotate").exists())

    def test_registry_points_at_the_new_home(self):
        rows = json.loads((self.home / ".claude" / "annotate" / "sessions.json").read_text())
        self.assertEqual(Path(rows[SID]["state_dir"]), self.new_base / "state")
        # The project root is preserved: it names the repo, not the storage.
        self.assertEqual(rows[SID]["_cwd"], str(self.project))

    def test_slug_still_resolves_after_the_move(self):
        status, body = _http_get("localhost", self.info["port"], f"/s/{SLUG}/")
        self.assertEqual(status, 200)
        self.assertIn("PICON-473 business view", body)

    def test_workspace_outlives_the_project_directory(self):
        """The whole point: delete the worktree, keep the annotations."""
        shutil.rmtree(self.project)
        status, body = _http_get("localhost", self.info["port"], f"/s/{SLUG}/")
        self.assertEqual(status, 200)
        self.assertIn("PICON-473 business view", body)
        self.assertTrue((self.new_base / "annotations" / "keep.json").exists())


if __name__ == "__main__":
    unittest.main()
