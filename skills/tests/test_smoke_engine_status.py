"""Which half of skills/_shared/web_companion is live, asserted.

That package holds a shared library five skills import, and an HTTP server
nothing launches — every skill pushes to the webcompanion daemon instead. The
split is invisible from the file listing, which is how a probe-retry fix once
got carefully ported into the server's static/core.js: code that cannot run.

skills/_shared/web_companion/README.md is the decision. This is the guard on
it, and it fails in both directions on purpose: wire the server back up, or
stop importing one of the library modules, and it sends you to that file.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "skills" / "_shared" / "web_companion"

LIBRARY = {"atomic", "anchor_migrate", "paths", "templates", "threads"}
RETIRED = {"server", "handlers", "stream", "static_serve", "reply_cli"}


def _external_importers(module):
    """Files OUTSIDE the package that import this module."""
    hits = []
    for f in (REPO / "skills").rglob("*.py"):
        if PKG in f.parents or f.name == Path(__file__).name:
            continue
        src = f.read_text()
        if re.search(rf"web_companion\.{module}\b|web_companion import .*\b{module}\b", src):
            hits.append(f.relative_to(REPO).as_posix())
    return hits


class TestTheEngineSplit(unittest.TestCase):
    def test_the_decision_is_written_down(self):
        self.assertTrue((PKG / "README.md").is_file(),
                        "the live/retired split is undocumented again")

    def test_the_library_half_is_still_imported(self):
        for module in sorted(LIBRARY):
            self.assertTrue(_external_importers(module),
                            f"{module}.py has no importers left — it moved from "
                            f"library to dead code, and README.md now lies")

    def test_the_retired_half_is_still_retired(self):
        for module in sorted(RETIRED):
            importers = _external_importers(module)
            self.assertEqual(importers, [],
                             f"{module}.py is imported again by {importers}. The "
                             f"server in this package was retired; if it is back, "
                             f"update its README.md — and the advice there not to "
                             f"spend effort fixing bugs in it.")

    def test_nothing_launches_the_retired_server(self):
        launchers = []
        for f in list((REPO / "skills").rglob("*.py")) + list((REPO / "skills").rglob("*.sh")):
            # Production code only. A test that asserts something ABOUT the
            # retired server is not a thing that starts it, and three of them
            # exist — they are what keeps it honest while it sits there.
            if PKG in f.parents or "tests" in f.parts:
                continue
            if re.search(r"web_companion[./]server|ensure_server\.sh", f.read_text()):
                launchers.append(f.relative_to(REPO).as_posix())
        self.assertEqual(launchers, [],
                         f"{launchers} starts the retired server — every skill is "
                         f"supposed to push to the daemon")
