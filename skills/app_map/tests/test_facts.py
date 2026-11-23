import tempfile
import unittest
from pathlib import Path

from skills.app_map import facts
from skills.app_map.tests import helpers as h


def edge(f, a, b, config=None):
    return [e for e in f["edges"] if e["from"] == a and e["to"] == b and (config is None or e["config"] == config)]


class Gradle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = h.gradle_repo(Path(self.tmp.name))
        h.write(self.repo, "untracked.txt")  # never added
        h.add_all(self.repo)
        h.write(self.repo, "later.txt")
        self.f = facts.gather(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_modules(self):
        self.assertEqual(self.f["build"], "gradle")
        mods = {m["name"]: m for m in self.f["modules"]}
        self.assertEqual(sorted(mods), ["core", "orders", "web"])
        self.assertEqual(mods["orders"]["dir"], "orders")
        self.assertEqual(mods["orders"]["files"], 3)  # build.gradle and two sources
        self.assertEqual(mods["web"]["files"], 2)

    def test_packages_group_under_the_common_prefix(self):
        mods = {m["name"]: m for m in self.f["modules"]}
        self.assertEqual(mods["orders"]["packages"], {"com/acme/orders": 2})

    def test_edges_run_from_provider_to_user(self):
        e = edge(self.f, "core", "orders")
        self.assertEqual([(x["config"], x["test"]) for x in e], [("implementation", False)])
        e = edge(self.f, "web", "orders")
        self.assertEqual([(x["config"], x["test"]) for x in e], [("testImplementation", True)])
        e = edge(self.f, "orders", "web")
        self.assertEqual([(x["config"], x["test"]) for x in e], [("implementation", False)])
        self.assertEqual(len(self.f["edges"]), 3)

    def test_no_codeowners(self):
        self.assertIsNone(self.f["codeowners"])


class Maven(unittest.TestCase):
    def test_modules_and_edges(self):
        with tempfile.TemporaryDirectory() as t:
            repo = h.maven_repo(Path(t))
            h.add_all(repo)
            f = facts.gather(repo)
        self.assertEqual(f["build"], "maven")
        mods = {m["name"]: m for m in f["modules"]}
        self.assertEqual(sorted(mods), ["shop-app", "shop-core"])
        self.assertEqual(mods["shop-app"]["dir"], "shop-app")
        self.assertEqual(mods["shop-app"]["files"], 3)
        got = sorted((e["from"], e["to"], e["config"], e["test"]) for e in f["edges"])
        self.assertEqual(got, [("shop-core", "shop-app", "compile", False), ("shop-core", "shop-app", "test", True)])


class Folders(unittest.TestCase):
    def test_top_level_folders_when_no_build_file(self):
        with tempfile.TemporaryDirectory() as t:
            repo = h.init(Path(t) / "plain")
            h.write(repo, "a/x.py")
            h.write(repo, "a/y.py")
            h.write(repo, "b/z.py")
            h.write(repo, "README.md")
            h.add_all(repo)
            f = facts.gather(repo)
        self.assertEqual(f["build"], "folders")
        self.assertEqual({m["name"]: m["files"] for m in f["modules"]}, {"a": 2, "b": 1})
        self.assertEqual(f["edges"], [])


class CodeOwners(unittest.TestCase):
    def test_rules_teams_and_skipped_sections(self):
        with tempfile.TemporaryDirectory() as t:
            repo = h.gradle_repo(Path(t))
            h.write(repo, ".github/CODEOWNERS",
                    "# owners\n\n/core/ @acme/core\n[Section]\n/orders/ @acme/orders @acme/lead\n*.md\n")
            h.add_all(repo)
            c = facts.gather(repo)["codeowners"]
        self.assertEqual(c["file"], ".github/CODEOWNERS")
        self.assertEqual(c["skipped_sections"], 1)
        self.assertEqual(c["rules"], [
            {"pattern": "/core/", "owners": ["@acme/core"]},
            {"pattern": "/orders/", "owners": ["@acme/orders", "@acme/lead"]},
            {"pattern": "*.md", "owners": []},
        ])
        self.assertEqual(c["teams"], ["@acme/core", "@acme/lead", "@acme/orders"])

    def test_first_location_wins(self):
        with tempfile.TemporaryDirectory() as t:
            repo = h.init(Path(t) / "r")
            h.write(repo, "CODEOWNERS", "/a/ @acme/root\n")
            h.write(repo, "docs/CODEOWNERS", "/a/ @acme/docs\n")
            h.add_all(repo)
            c = facts.gather(repo)["codeowners"]
        self.assertEqual(c["file"], "CODEOWNERS")
