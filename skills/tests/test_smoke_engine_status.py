"""What may live in skills/_shared, asserted.

The rule: a module stays in `_shared` only while at least two skills import it
from production code. One importer means it belongs to that skill; none means
it is dead. Tests never count — a test that imports a module keeps nothing
alive, which is how annotate's own HTTP server once sat here, retired, with
24 test files still passing against code no user could reach.

There is no server in this repo any more. Every skill pushes to the separately
installed webcompanion daemon through `webcompanion_client.py`; nothing here
may start one of its own.

skills/_shared/README.md says the same in prose.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"
SHARED = SKILLS / "_shared"

# Not modules: page assets another workstream owns, the package markers, the
# shared layer's own tests, its README, and third-party code a module loads.
_NOT_MODULES = {"static", "tests", "vendor", "__pycache__", ".pytest_cache"}


def _shared_files():
    """Every file in _shared that is code, as paths relative to the repo."""
    out = []
    for f in SHARED.rglob("*"):
        if not f.is_file() or _NOT_MODULES & set(f.relative_to(SHARED).parts):
            continue
        if f.name in ("__init__.py", "README.md"):
            continue
        out.append(f)
    return sorted(out)


def _production_files():
    """{skill name: [its non-test source files]} for every real skill."""
    out = {}
    for skill in sorted(SKILLS.iterdir()):
        if not (skill / "SKILL.md").is_file():
            continue          # _shared and tests are not skills
        out[skill.name] = [
            f for f in skill.rglob("*")
            if f.is_file() and f.suffix in (".py", ".sh", ".md")
            and "tests" not in f.relative_to(skill).parts
        ]
    return out


def _unit(f: Path) -> Path:
    """What counts importers: a top-level module, or the whole package a file belongs to."""
    top = SHARED / f.relative_to(SHARED).parts[0]
    return top if top.is_dir() else f


def _read_by_its_package(f: Path) -> bool:
    """A non-Python file a module of its own package runs or reads, named in that module."""
    unit = _unit(f)
    return unit.is_dir() and any(f.name in p.read_text(encoding="utf-8", errors="replace")
                                 for p in unit.rglob("*.py") if "tests" not in p.parts)


def _importing_skills(module: Path) -> set:
    """The skills whose production code imports `module`."""
    dotted = ".".join(module.relative_to(REPO).with_suffix("").parts)
    parent, name = dotted.rsplit(".", 1)
    pattern = re.compile(
        rf"\b{re.escape(dotted)}\b|from {re.escape(parent)} import [^\n]*\b{name}\b")
    return {skill for skill, files in _production_files().items()
            if any(pattern.search(f.read_text(encoding="utf-8", errors="replace"))
                   for f in files)}


class TestTheSharedLayer(unittest.TestCase):
    def test_the_rule_is_written_down(self):
        self.assertTrue((SHARED / "README.md").is_file())

    def test_only_python_modules_live_here(self):
        others = [f.relative_to(REPO).as_posix() for f in _shared_files()
                  if f.suffix != ".py" and not _read_by_its_package(f)]
        self.assertEqual(others, [], "a script in _shared belongs to the skill that runs it")

    def test_every_shared_module_has_two_skills_importing_it(self):
        lonely = {}
        for unit in sorted({_unit(f) for f in _shared_files() if f.suffix == ".py"}):
            users = _importing_skills(unit)
            if len(users) < 2:
                lonely[unit.relative_to(REPO).as_posix()] = sorted(users)
        self.assertEqual(lonely, {},
                         "move a module with one importer into that skill; "
                         "delete one with none")

    def test_tests_do_not_count_as_importers(self):
        # Every skill's tests import the shared client; were they counted,
        # this would include `tests` or a skill whose only import is a test.
        for skill, files in _production_files().items():
            self.assertFalse(any("tests" in f.relative_to(SKILLS / skill).parts
                                 for f in files), skill)
        self.assertNotIn("tests", _production_files())

    def test_nothing_starts_a_server_of_its_own(self):
        launchers = []
        for files in _production_files().values():
            for f in files:
                src = f.read_text(encoding="utf-8", errors="replace")
                if re.search(r"web_companion[./]server|ensure_server\.sh|"
                             r"\bserver\.run\(|watcher\.sh", src):
                    launchers.append(f.relative_to(REPO).as_posix())
        self.assertEqual(launchers, [],
                         "every skill pushes to the webcompanion daemon")


# The one skill that runs a server of its own: talk's call page is a long-lived speech server that
# launchd keeps up, one per machine, so it cannot be a push to the daemon. Every other skill pushes.
SERVER_SKILLS = {"talk"}

# Every way production code binds a port or serves HTTP: aiohttp, the standard library's servers,
# a raw socket, asyncio's and the usual third-party runners.
_SERVER_BIND = re.compile(
    r"\bweb\.(?:run_app|AppRunner|TCPSite|UnixSite|SockSite)\b|\b(?:TCPSite|UnixSite|SockSite)\(|"
    r"\bhttp\.server\b|\bsocketserver\b|\b\w*HTTPServer\b|\bserve_forever\b|"
    r"\basyncio\.(?:start_server|start_unix_server)\b|\.create_server\(|"
    r"\.bind\(\s*[(\"']|\.listen\(|\buvicorn\b|\bhypercorn\b|\bwaitress\b|\bgunicorn\b")


def _servers_found(skills_dir: Path) -> list:
    """Production .py and .sh files under `skills_dir` that bind a port, outside SERVER_SKILLS."""
    found = []
    for f in sorted(skills_dir.rglob("*")):
        rel = f.relative_to(skills_dir).parts
        if (not f.is_file() or f.suffix not in (".py", ".sh") or rel[0] in SERVER_SKILLS
                or "tests" in rel or "static" in rel or "vendor" in rel):
            continue
        if _SERVER_BIND.search(f.read_text(encoding="utf-8", errors="replace")):
            found.append("/".join(rel))
    return found


class TestOnlyTalkBindsAPort(unittest.TestCase):
    def test_no_skill_but_talk_binds_a_port_or_serves_http(self):
        self.assertEqual(_servers_found(SKILLS), [],
                         "every skill but talk pushes to the webcompanion daemon; none owns a port")

    def test_talk_is_still_the_one_that_does(self):
        # The allowlist must name a real server: were talk's gone, the exception would hide a new one.
        talk = (SKILLS / "talk" / "talk.py").read_text(encoding="utf-8")
        self.assertRegex(talk, r"web\.TCPSite\(")

    def test_the_check_sees_each_shape_of_bind_in_a_skill_that_is_not_talk(self):
        import tempfile
        shapes = {
            "aiohttp": "from aiohttp import web\nweb.run_app(app)\n",
            "tcpsite": "await web.TCPSite(runner, '127.0.0.1', 1).start()\n",
            "stdlib": "import http.server\nhttp.server.HTTPServer(('', 1), H).serve_forever()\n",
            "socketserver": "import socketserver\n",
            "socket": "s.bind(('127.0.0.1', 0))\n",
            "asyncio": "await asyncio.start_server(cb, '127.0.0.1', 1)\n",
        }
        for name, code in shapes.items():
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                (root / "other" / "tests").mkdir(parents=True)
                (root / "talk").mkdir()
                (root / "other" / "mod.py").write_text(code)
                (root / "talk" / "talk.py").write_text(code)
                (root / "other" / "tests" / "test_x.py").write_text(code)
                self.assertEqual(_servers_found(root), ["other/mod.py"], name)
