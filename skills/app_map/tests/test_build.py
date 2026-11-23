import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from skills.app_map import app_map
from skills.app_map.tests import helpers as h

SAMPLE = json.loads((Path(__file__).parent / "sample_map.json").read_text())


def box(bid, col, row, name, **kw):
    return dict({"id": bid, "col": col, "row": row, "name": name}, **kw)


def source(remote="github.com/acme/shop"):
    return {
        "name": "shop",
        "match": {"remotes": [remote], "folders": []},
        "map": {"title": "Orders flow from the web through the service", "columns": ["Entry", "Service"],
                "boxes": [box("web", 0, 0, "Web"), box("svc", 1, 0, "Service"), box("orders", 1, 1, "Orders", tone="blue")],
                "arrows": [{"from": "svc", "to": "web", "label": "REST", "n": 1}],
                "legend": [{"label": "provider to user"}]},
        "parts": [
            {"id": "svc", "paths": ["/svc/"]},
            {"id": "orders", "paths": ["/svc/src/**/java/com/acme/svc/orders/**", "/orders/"]},
            {"id": "web", "paths": ["/web/"]},
        ],
        "details": {"svc": {
            "map": {"title": "The service splits into an API and a database layer", "columns": ["Layer"],
                    "boxes": [box("svc-api", 0, 0, "API"), box("svc-db", 0, 1, "DB")]},
            "parts": [{"id": "svc-api", "paths": ["/svc/src/**/java/com/acme/svc/api/**"]},
                      {"id": "svc-db", "paths": ["/svc/src/**/java/com/acme/svc/db/**"]}]}},
    }


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = app_map.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.old = os.environ.get("APP_MAP_HOME")
        os.environ["APP_MAP_HOME"] = str(self.home)
        self.addCleanup(self._restore)
        self.repo = h.init(root / "shop")
        for rel in ["svc/src/main/java/com/acme/svc/orders/A.java", "svc/src/main/java/com/acme/svc/orders/B.java",
                    "svc/src/main/java/com/acme/svc/api/Api.java", "svc/src/main/java/com/acme/svc/db/Db.java",
                    "svc/src/main/java/com/acme/svc/util/U.java", "web/Page.js", "web/Other.js", "docs/readme.md"]:
            h.write(self.repo, rel)
        h.write(self.repo, ".github/CODEOWNERS",
                "/svc/ @acme/core\n/svc/src/**/java/com/acme/svc/orders/** @acme/orders @acme/lead\n/web/ @acme/web\n")
        h.add_all(self.repo, commit=True)
        h.write(self.repo, "svc/untracked.java")
        h.write(self.repo, ".gitignore", "ignored.log\n")
        h.write(self.repo, "ignored.log")

    def _restore(self):
        if self.old is None:
            os.environ.pop("APP_MAP_HOME", None)
        else:
            os.environ["APP_MAP_HOME"] = self.old

    def put(self, src, name="shop"):
        d = self.home / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "source.json").write_text(json.dumps(src))
        return d

    def ready(self, src=None):
        src = src or source()
        src["match"]["folders"] = [str(self.repo)]
        return self.put(src)


class Check(Base):
    def test_reports_unmapped_files_and_ignores_untracked_ones(self):
        self.ready()
        code, out, _ = run("check", "shop")
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(r["total"], 9)  # 8 sources + CODEOWNERS; not the untracked or the ignored file
        self.assertEqual(r["unmapped"]["count"], 2)  # docs/readme.md and .github/CODEOWNERS
        folders = {f["folder"]: f["files"] for f in r["unmapped"]["folders"]}
        self.assertEqual(folders, {"docs": 1, ".github": 1})
        self.assertEqual(r["parts"], {"svc": 3, "orders": 2, "web": 2})
        self.assertEqual(r["details"]["svc"], {"svc-api": 1, "svc-db": 1})

    def test_the_last_match_wins_so_orders_files_leave_svc(self):
        self.ready()
        r = json.loads(run("check", "shop")[1])
        self.assertEqual(r["parts"]["svc"], 3)  # 5 tracked files under /svc/ minus the 2 carved out
        self.assertEqual(r["empty_parts"], [])

    def test_empty_parts_and_boxes_without_a_part(self):
        src = source()
        src["parts"].append({"id": "ghost", "paths": ["/nowhere/"]})
        src["map"]["boxes"].append(box("ghost", 0, 1, "Ghost"))
        src["map"]["boxes"].append(box("label", 0, 2, "An outside system"))
        self.ready(src)
        code, out, _ = run("check", "shop")
        r = json.loads(out)
        self.assertEqual(r["empty_parts"], ["ghost"])
        self.assertEqual(r["boxes_without_part"], ["label"])
        self.assertEqual(code, 0)

    def test_a_part_with_no_box_is_an_error(self):
        src = source()
        src["parts"].append({"id": "nobox", "paths": ["/docs/"]})
        self.ready(src)
        code, out, _ = run("check", "shop")
        r = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(r["parts_without_box"], ["nobox"])
        self.assertFalse(r["ok"])

    def test_a_duplicate_part_id_across_maps_is_an_error(self):
        src = source()
        src["details"]["svc"]["parts"].append({"id": "web", "paths": ["/svc/x/"]})
        src["details"]["svc"]["map"]["boxes"].append(box("web", 0, 2, "Web again"))
        self.ready(src)
        code, out, _ = run("check", "shop")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["duplicate_part_ids"], ["web"])

    def test_a_detail_for_an_unknown_part_is_an_error(self):
        src = source()
        src["details"]["nothing"] = src["details"].pop("svc")
        self.ready(src)
        code, out, _ = run("check", "shop")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["details_without_part"], ["nothing"])

    def test_the_repo_flag_beats_the_match_folders(self):
        src = source()
        src["match"]["folders"] = ["/no/such/folder"]
        self.put(src)
        self.assertEqual(run("check", "shop", "--repo", str(self.repo))[0], 0)

    def test_no_repo_is_one_line_and_exit_2(self):
        src = source()
        src["match"]["folders"] = ["/no/such/folder"]
        self.put(src)
        code, out, err = run("check", "shop")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_a_missing_source_is_one_line(self):
        code, _, err = run("check", "nothing")
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_a_name_that_climbs_out_is_refused(self):
        code, _, err = run("check", "../x")
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1)


class Build(Base):
    def test_refuses_a_part_id_with_no_box_and_writes_nothing(self):
        src = source()
        src["parts"].append({"id": "nobox", "paths": ["/docs/"]})
        d = self.ready(src)
        self.assertEqual(run("build", "shop")[0], 1)
        self.assertFalse((d / "map.json").exists())

    def test_refuses_a_duplicate_part_id(self):
        src = source()
        src["details"]["svc"]["parts"].append({"id": "orders", "paths": ["/svc/x/"]})
        src["details"]["svc"]["map"]["boxes"].append(box("orders", 0, 2, "Orders again"))
        d = self.ready(src)
        self.assertEqual(run("build", "shop")[0], 1)
        self.assertFalse((d / "map.json").exists())

    def test_a_good_build_writes_the_map(self):
        d = self.ready()
        code, out, _ = run("build", "shop")
        self.assertEqual(code, 0, out)
        report = json.loads(out)
        self.assertTrue(report["ok"])
        self.assertEqual(sorted(report["written"]), ["map.json", "svc.svg", "top.svg"])
        m = json.loads((d / "map.json").read_text())
        self.assertEqual(m["version"], 1)
        self.assertEqual(m["name"], "shop")
        self.assertEqual(m["match"], {"remotes": ["github.com/acme/shop"], "folders": [str(self.repo)]})
        self.assertEqual([p["id"] for p in m["parts"]], ["svc", "orders", "web"])
        self.assertEqual(m["details"], {"svc": {"parts": source()["details"]["svc"]["parts"]}})
        self.assertRegex(m["built"]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertRegex(m["built"]["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(sorted(m["drawings"]), ["svc", "top"])
        self.assertTrue((d / "top.svg").read_text().startswith("<svg"))
        self.assertIn('data-vz="map"', (d / "svc.svg").read_text())

    def test_every_part_box_ends_with_a_blank_row_for_its_pills(self):
        d = self.ready()
        run("build", "shop")
        shapes = json.loads((d / "map.json").read_text())["drawings"]["top"]["shapes"]
        texts = [s for s in shapes if s["kind"] == "text" and s["key"] == "box:web"]
        self.assertEqual(texts[-1]["runs"], [{"text": "\u00a0", "mono": False}])
        # The source itself is not changed.
        self.assertNotIn("\u00a0", (d / "source.json").read_text())

    def test_the_map_lists_each_build_module_with_its_folder(self):
        d = self.ready()
        run("build", "shop")
        mods = json.loads((d / "map.json").read_text())["modules"]
        self.assertTrue(mods)
        self.assertTrue(all(set(m) == {"name", "dir", "repo"} and m["repo"] is None for m in mods))

    def test_team_labels_are_carried_into_the_map(self):
        d = self.ready()
        src = json.loads((d / "source.json").read_text())
        src["teams"] = {"@acme/core": "CORE"}
        (d / "source.json").write_text(json.dumps(src))
        run("build", "shop")
        self.assertEqual(json.loads((d / "map.json").read_text())["teams"], {"@acme/core": "CORE"})

    def test_a_team_label_must_be_text(self):
        d = self.ready()
        src = json.loads((d / "source.json").read_text())
        src["teams"] = {"@acme/core": 3}
        (d / "source.json").write_text(json.dumps(src))
        self.assertNotEqual(run("build", "shop")[0], 0)

    def test_owners_count_files_by_first_owner(self):
        d = self.ready()
        run("build", "shop")
        o = json.loads((d / "map.json").read_text())["owners"]
        self.assertEqual(o["svc"], [{"team": "@acme/core", "files": 3}])
        self.assertEqual(o["orders"], [{"team": "@acme/orders", "files": 2}])
        self.assertEqual(o["web"], [{"team": "@acme/web", "files": 2}])
        self.assertEqual(o["svc-api"], [{"team": "@acme/core", "files": 1}])
        self.assertEqual(o["svc-db"], [{"team": "@acme/core", "files": 1}])

    def test_without_a_codeowners_file_every_file_is_uncovered(self):
        d = self.ready()
        h.git(self.repo, "rm", "-q", ".github/CODEOWNERS")
        run("build", "shop")
        o = json.loads((d / "map.json").read_text())["owners"]
        self.assertEqual(o["web"], [{"team": None, "files": 2}])

    def test_drawing_shapes_have_exactly_the_samples_kinds_and_fields(self):
        d = self.ready()
        run("build", "shop")
        m = json.loads((d / "map.json").read_text())
        want = {}
        for dr in SAMPLE["drawings"].values():
            for s in dr["shapes"]:
                want.setdefault(s["kind"], set(s))
        top = m["drawings"]["top"]
        self.assertEqual(set(top), {"width", "height", "shapes"})
        kinds = set()
        for dr in m["drawings"].values():
            for s in dr["shapes"]:
                kinds.add(s["kind"])
                self.assertEqual(set(s), want[s["kind"]], s)
        self.assertEqual(kinds, {"rect", "text", "path", "circle"})
        keys = {s["key"] for s in top["shapes"]}
        self.assertTrue({"box:web", "box:svc", "box:orders", "edge:svc->web#0"} <= keys)

    def test_top_level_keys_match_the_sample(self):
        d = self.ready()
        run("build", "shop")
        self.assertEqual(set(json.loads((d / "map.json").read_text())), set(SAMPLE))

    def test_a_rebuild_succeeds(self):
        self.ready()
        run("build", "shop")
        self.assertEqual(run("build", "shop")[0], 0)

    def test_facts_prints_json(self):
        code, out, _ = run("facts", str(self.repo))
        self.assertEqual(code, 0)
        f = json.loads(out)
        self.assertEqual(f["build"], "folders")
        self.assertEqual(f["codeowners"]["file"], ".github/CODEOWNERS")


class TwoRepos(Base):
    """A map that spans a second checkout: its parts are counted, owned and matched in that repo only."""

    def setUp(self):
        super().setUp()
        self.other = h.init(Path(self.tmp.name) / "contract")
        for rel in ["svc/Shared.java", "svc/More.java", "api/Dto.java"]:
            h.write(self.other, rel)
        h.write(self.other, ".github/CODEOWNERS", "/svc/ @acme/contract\n")
        h.add_all(self.other, commit=True)

    def two(self):
        src = source()
        src["repos"] = [{"name": "contract", "remote": "github.com/acme/contract", "folders": [str(self.other)]}]
        src["map"]["boxes"].append(box("shared", 0, 1, "Shared"))
        # The same folder name as the main repo's svc part: only the contract's files may land here.
        src["parts"].append({"id": "shared", "repo": "contract", "paths": ["/svc/"]})
        return self.ready(src)

    def test_each_repos_files_land_only_on_its_own_parts(self):
        self.two()
        code, out, _ = run("check", "shop")
        r = json.loads(out)
        self.assertEqual(code, 0, r["errors"])
        self.assertEqual(r["parts"]["svc"], 3)
        self.assertEqual(r["parts"]["shared"], 2)
        folders = {f["folder"]: f["files"] for f in r["unmapped"]["folders"]}
        self.assertEqual(folders.get("contract:api"), 1)

    def test_owners_come_from_each_repos_own_codeowners(self):
        d = self.two()
        run("build", "shop")
        m = json.loads((d / "map.json").read_text())
        self.assertEqual(m["owners"]["shared"], [{"team": "@acme/contract", "files": 2}])
        self.assertEqual(m["owners"]["svc"], [{"team": "@acme/core", "files": 3}])

    def test_the_map_names_the_repos_and_matches_both(self):
        d = self.two()
        run("build", "shop")
        m = json.loads((d / "map.json").read_text())
        self.assertEqual(m["repos"], {"contract": "github.com/acme/contract"})
        self.assertIn("github.com/acme/contract", m["match"]["remotes"])
        self.assertIn(str(self.other), m["match"]["folders"])
        self.assertEqual([p.get("repo") for p in m["parts"] if p["id"] == "shared"], ["contract"])
        self.assertNotIn("repo", [p for p in m["parts"] if p["id"] == "svc"][0])

    def test_a_part_naming_an_unknown_repo_is_refused(self):
        src = source()
        src["map"]["boxes"].append(box("shared", 0, 1, "Shared"))
        src["parts"].append({"id": "shared", "repo": "nowhere", "paths": ["/svc/"]})
        self.ready(src)
        code, out, _ = run("check", "shop")
        self.assertNotEqual(code, 0)
        self.assertTrue(any("nowhere" in e for e in json.loads(out)["errors"]))

    def test_a_repo_with_no_folder_here_is_refused(self):
        src = source()
        src["repos"] = [{"name": "contract", "remote": "github.com/acme/contract", "folders": ["/no/such/folder"]}]
        self.ready(src)
        code, out, _ = run("check", "shop")
        self.assertNotEqual(code, 0)
        self.assertTrue(any("contract" in e for e in json.loads(out)["errors"]))

