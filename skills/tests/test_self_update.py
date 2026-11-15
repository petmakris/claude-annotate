"""tools/self_update.py: a checkout fast-forwards to origin/main only when that is safe."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("self_update", ROOT / "tools" / "self_update.py")
su = importlib.util.module_from_spec(spec)
spec.loader.exec_module(su)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class World:
    """A bare origin, a clone that pushes (upstream) and the clone under test (here)."""

    def __init__(self, tmp: Path):
        self.origin = tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.up = tmp / "up"
        self.here = tmp / "here"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.up)], check=True)
        for repo in (self.up,):
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "t")
            git(repo, "checkout", "-q", "-b", "main")
        self.commit("README", "one")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.here)], check=True)
        git(self.here, "config", "user.email", "t@example.com")
        git(self.here, "config", "user.name", "t")

    def commit(self, path, text, repo=None):
        repo = repo or self.up
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        git(repo, "add", path)
        git(repo, "commit", "-q", "-m", path)
        if repo == self.up:
            git(repo, "push", "-q", "origin", "main")


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self._tmp.name))
        self.said = []
        self.restarts = []

    def tearDown(self):
        self._tmp.cleanup()

    def run_here(self):
        return su.here(self.w.here, say=self.said.append, force=True,
                       on_journey_change=lambda say: self.restarts.append(1))

    def test_a_clean_checkout_behind_origin_fast_forwards(self):
        self.w.commit("skills/canvas/x.txt", "new")
        self.assertTrue(self.run_here())
        self.assertEqual(git(self.w.here, "rev-parse", "HEAD"), git(self.w.up, "rev-parse", "HEAD"))
        self.assertEqual(self.restarts, [])

    def test_a_change_to_journey_py_restarts_the_doorman(self):
        self.w.commit("skills/journey/journey.py", "print(1)")
        self.assertTrue(self.run_here())
        self.assertEqual(self.restarts, [1])

    def test_uncommitted_changes_are_never_pulled_over(self):
        self.w.commit("skills/canvas/x.txt", "new")
        (self.w.here / "README").write_text("my edit")
        before = git(self.w.here, "rev-parse", "HEAD")
        self.assertFalse(self.run_here())
        self.assertEqual(git(self.w.here, "rev-parse", "HEAD"), before)
        self.assertEqual((self.w.here / "README").read_text(), "my edit")
        self.assertIn("uncommitted changes", self.said[-1])

    def test_local_commits_are_left_alone(self):
        self.w.commit("skills/canvas/x.txt", "new")
        self.w.commit("local.txt", "mine", repo=self.w.here)
        before = git(self.w.here, "rev-parse", "HEAD")
        self.assertFalse(self.run_here())
        self.assertEqual(git(self.w.here, "rev-parse", "HEAD"), before)
        self.assertIn("1 local commit(s)", self.said[-1])

    def test_another_branch_is_left_alone(self):
        git(self.w.here, "checkout", "-q", "-b", "work")
        self.assertFalse(self.run_here())
        self.assertIn("on branch work", self.said[-1])

    def test_no_network_says_so_and_never_raises(self):
        git(self.w.here, "remote", "set-url", "origin", str(Path(self._tmp.name) / "gone.git"))
        self.assertFalse(self.run_here())
        self.assertIn("could not reach origin", self.said[-1])

    def test_it_is_off_inside_pytest_unless_forced(self):
        self.w.commit("skills/canvas/x.txt", "new")
        before = git(self.w.here, "rev-parse", "HEAD")
        self.assertFalse(su.here(self.w.here, say=self.said.append))
        self.assertEqual(git(self.w.here, "rev-parse", "HEAD"), before)

    def test_fleet_machines_skips_this_machine(self):
        home = Path(self._tmp.name) / "fleet"
        home.mkdir()
        (home / "machines.json").write_text('{"self": "a", "a": {"ssh": "a"}, "b": {"ssh": "bee"}}')
        self.assertEqual(su.fleet_machines(home), [("b", "bee")])
        self.assertEqual(su.fleet_machines(Path(self._tmp.name) / "none"), [])


if __name__ == "__main__":
    unittest.main()
