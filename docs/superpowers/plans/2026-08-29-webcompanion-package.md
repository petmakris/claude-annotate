# webcompanion package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `webcompanion` — a standalone, stdlib-only Python package and always-on loopback HTTP daemon that serves opaque addressable items, comment threads and an event queue for any client, published to PyPI from its own repository.

**Architecture:** One `ThreadingHTTPServer` process, installed as a launchd/systemd user service on a fixed loopback port, configured by one 0600 JSON file. Content arrives over HTTP as skill-defined JSON items addressed by anchor; the daemon hashes them into a per-anchor version chain, resolves declared `{file, line}` code anchors by reading the working tree at request time, and streams two generic SSE frames. It ships a 4.7KB interaction runtime (`core.js`) and serves each client's own renderer as per-session assets.

**Tech Stack:** Python 3.9+, standard library only (`http.server`, `threading`, `hashlib`, `fcntl`, `importlib.resources`, `zipapp`). pytest for tests. No runtime dependencies, ever.

**Spec:** `docs/superpowers/specs/2026-08-29-webcompanion-standalone-service-design.md`

**Scope:** This is plan 1 of 4. It builds the package only; nothing consumes it yet. Plans 2–4 (IntelliJ build with dual discovery, the five-skill cutover, IntelliJ fallback removal) are written after this ships to PyPI, per the spec's Rollout section.

## Global Constraints

- `requires-python = ">=3.9"`. `int | None` is permitted only under `from __future__ import annotations`.
- **Zero runtime dependencies.** Standard library only. A PR adding a dependency is rejected regardless of convenience.
- POSIX only — `fcntl` is imported by `threads.py`. The package README states macOS/Linux; Windows is unsupported.
- Every module begins `from __future__ import annotations`.
- Static assets are read via `importlib.resources.as_file`, never `Path(__file__).parent`. The zipapp build breaks the latter.
- Contract version is the integer `1` throughout. Every request carries `X-WebCompanion-Contract`; a mismatch is answered `426`.
- The daemon never self-restarts, never watches files for changes, and has no idle shutdown.
- All configuration is read from `~/.claude/webcompanion/config.json`. No `os.environ` reads for configuration anywhere in the package — under launchd the user's shell environment does not reach the process.
- Tests run `python3 -m pytest -q` from the repository root. Every task ends green.
- Commit messages: subject names its subject, no metaphor. See `~/.claude/CLAUDE.md`.

---

## File Structure

    webcompanion/
      pyproject.toml                 metadata, requires-python, [project.scripts]
      README.md                      install, service, contract, platform support
      LICENSE
      .github/workflows/ci.yml       pytest on 3.9 and 3.13
      src/webcompanion/
        __init__.py                  __version__, CONTRACT
        config.py                    read/write ~/.claude/webcompanion/config.json
        atomic.py                    write_text_atomic (ported verbatim)
        paths.py                     kind-namespaced workspace roots, markers
        registry.py                  Registry: sessions, kind, slugs, change counter
        versions.py                  generic per-anchor hash chain
        items.py                     item store on top of versions
        anchors.py                   request-time {file,line} resolution, cwd-bounded
        threads.py                   per-anchor append-only threads (ported)
        events.py                    event queue (ported)
        uploads.py                   paste-image upload (ported)
        stream.py                    SSE: item-changed, document-changed only
        cleanup.py                   retention, stray sweep, waiter GC, migration
        gate.py                      owner gate, contract negotiation
        server.py                    routes and the HTTP server
        static/core.js               the runtime
        static/shell.html            the session shell page
        service/launchd.plist        template
        service/systemd.service      template
        cli.py                       argument parsing and dispatch
        commands/                    one module per subcommand
          push.py update.py end.py watch.py serve.py
          install_service.py status.py doctor.py migrate.py
      tests/                         one test module per source module

Responsibility boundaries that matter: `registry.py` owns identity (sid, slug, kind) and knows nothing about content; `items.py` owns content and knows nothing about HTTP; `server.py` owns HTTP and knows nothing about what an item means; `gate.py` is the only module that decides whether a request may write.

---

### Task 1: Repository scaffold and version reporting

**Files:**
- Create: `pyproject.toml`, `README.md`, `LICENSE`, `.github/workflows/ci.yml`
- Create: `src/webcompanion/__init__.py`, `src/webcompanion/cli.py`
- Test: `tests/test_version.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `webcompanion.__version__: str`, `webcompanion.CONTRACT: int`, `webcompanion.cli.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Create the repository and write the failing test**

```bash
mkdir -p ~/projects/webcompanion/{src/webcompanion,tests}
cd ~/projects/webcompanion && git init -q
```

`tests/test_version.py`:

```python
from __future__ import annotations

import subprocess
import sys

import webcompanion
from webcompanion.cli import main


def test_package_reports_a_version_and_contract():
    assert isinstance(webcompanion.__version__, str)
    assert webcompanion.__version__.count(".") == 2
    assert webcompanion.CONTRACT == 1


def test_cli_version_flag_prints_version_and_contract(capsys):
    rc = main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert webcompanion.__version__ in out
    assert "contract 1" in out


def test_cli_unknown_subcommand_is_an_error():
    assert main(["nonesuch"]) == 2
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_version.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion'`

- [ ] **Step 3: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "webcompanion"
version = "0.1.0"
description = "A local always-on companion server: addressable items, comment threads, and an event queue."
readme = "README.md"
requires-python = ">=3.9"
license = {text = "MIT"}
authors = [{name = "Petros Makris"}]
dependencies = []
classifiers = [
  "Programming Language :: Python :: 3.9",
  "Operating System :: MacOS",
  "Operating System :: POSIX :: Linux",
]

[project.scripts]
webcompanion = "webcompanion.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
webcompanion = ["static/*", "service/*"]
```

- [ ] **Step 4: Write the package entry points**

`src/webcompanion/__init__.py`:

```python
"""webcompanion — a local always-on companion server.

The package is deliberately dependency-free. Everything it needs is in the
standard library, which is what lets the service ship as a zipapp run by the
system python instead of a virtualenv that dangles when that python is
replaced.
"""
from __future__ import annotations

__version__ = "0.1.0"

# The HTTP contract version. Bumped ONLY on a breaking change to routes or
# payload shapes. Clients send it in X-WebCompanion-Contract; a mismatch is
# answered 426 rather than being silently tolerated, because the four
# artifacts that speak this contract (this package, two Claude Code plugins,
# and a hand-downloaded IntelliJ zip) update on different schedules.
CONTRACT = 1
```

`src/webcompanion/cli.py`:

```python
from __future__ import annotations

import argparse
import sys

from webcompanion import CONTRACT, __version__

SUBCOMMANDS = (
    "serve", "push", "update", "end", "watch",
    "install-service", "status", "doctor", "migrate",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="webcompanion", add_help=True)
    p.add_argument("--version", action="store_true",
                   help="print the package version and contract, then exit")
    p.add_argument("command", nargs="?", choices=SUBCOMMANDS)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits 2 on an invalid choice; keep that as our return code
        # rather than letting it kill an embedding process.
        return 2
    if args.version or not args.command:
        print(f"webcompanion {__version__} (contract {CONTRACT})")
        return 0
    return _dispatch(args.command, args.rest)


def _dispatch(command: str, rest: list[str]) -> int:
    # Subcommand modules are imported lazily so `--version` and `--help` stay
    # fast and so a broken optional command cannot break the whole CLI.
    module_name = command.replace("-", "_")
    from importlib import import_module
    mod = import_module(f"webcompanion.commands.{module_name}")
    return int(mod.run(rest))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pip install -e . && python3 -m pytest tests/test_version.py -q`
Expected: 3 passed

- [ ] **Step 6: Write CI**

`.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.9", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install pytest
      - run: pip install -e .
      - run: python3 -m pytest -q
      - name: no runtime dependencies
        run: python3 -c "import tomllib,sys; d=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; sys.exit(0 if d==[] else 1)"
        if: matrix.python == '3.13'
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: package scaffold, version reporting, and CI"
```

---

### Task 2: Configuration file

**Files:**
- Create: `src/webcompanion/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Config` dataclass with fields `port: int`, `token: str`, `bind: str`, `retention_days: int | None`, `workspace_root: Path | None`, `public_host: str | None`; `config_path() -> Path`; `load(path: Path | None = None) -> Config`; `write(cfg: Config, path: Path | None = None) -> None`; `mint_token() -> str`; `DEFAULT_PORT = 3080`.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
from __future__ import annotations

import json
import stat

import pytest

from webcompanion import config as cfgmod


def test_defaults_when_no_file(tmp_path):
    cfg = cfgmod.load(tmp_path / "absent.json")
    assert cfg.port == 3080
    assert cfg.bind == "127.0.0.1"
    assert cfg.retention_days is None
    assert cfg.workspace_root is None
    assert cfg.token == ""


def test_write_then_load_roundtrips(tmp_path):
    p = tmp_path / "config.json"
    cfg = cfgmod.Config(port=3999, token="abc", bind="127.0.0.1",
                        retention_days=30, workspace_root=tmp_path / "ws",
                        public_host=None)
    cfgmod.write(cfg, p)
    back = cfgmod.load(p)
    assert back.port == 3999
    assert back.token == "abc"
    assert back.retention_days == 30
    assert back.workspace_root == tmp_path / "ws"


def test_written_file_is_owner_only(tmp_path):
    p = tmp_path / "config.json"
    cfgmod.write(cfgmod.Config(port=3080, token=cfgmod.mint_token()), p)
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"config holds the write token; got {oct(mode)}"


def test_corrupt_file_falls_back_to_defaults_without_raising(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json")
    cfg = cfgmod.load(p)
    assert cfg.port == 3080


def test_relative_workspace_root_is_rejected(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"workspace_root": "relative/path"}))
    assert cfgmod.load(p).workspace_root is None


def test_environment_is_never_consulted(tmp_path, monkeypatch):
    # Under launchd the daemon has a fixed environment; a setting that only
    # works when exported from an interactive shell is a setting that
    # silently stops working after install-service.
    monkeypatch.setenv("WEBCOMPANION_BIND", "0.0.0.0")
    monkeypatch.setenv("WEBCOMPANION_RETENTION_DAYS", "5")
    cfg = cfgmod.load(tmp_path / "absent.json")
    assert cfg.bind == "127.0.0.1"
    assert cfg.retention_days is None


def test_mint_token_is_unguessable_and_unique():
    a, b = cfgmod.mint_token(), cfgmod.mint_token()
    assert a != b
    assert len(a) >= 32
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.config'`

- [ ] **Step 3: Write the implementation**

`src/webcompanion/config.py`:

```python
"""The daemon's only configuration source.

Every setting lives in one 0600 JSON file at a fixed path. Nothing here reads
os.environ, and that is deliberate: the five per-skill servers this package
replaces were launched by a Claude session and inherited its shell
environment, so WEBCOMPANION_BIND and friends worked. A launchd or systemd
service has a fixed environment those variables never reach, and a setting
that quietly stops applying is worse than one that never existed.

The file also carries the write token, which is why it is owner-only. The
token must survive restarts: an always-on service that remints it on every
start invalidates the IntelliJ plugin's credential mid-session.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 3080
DEFAULT_BIND = "127.0.0.1"


@dataclass
class Config:
    port: int = DEFAULT_PORT
    token: str = ""
    bind: str = DEFAULT_BIND
    retention_days: int | None = None
    workspace_root: Path | None = None
    public_host: str | None = None


def config_path() -> Path:
    return Path(os.path.expanduser("~/.claude/webcompanion/config.json"))


def mint_token() -> str:
    return secrets.token_urlsafe(32)


def load(path: Path | None = None) -> Config:
    """The configuration, or defaults. Never raises."""
    path = Path(path) if path is not None else config_path()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return Config()
    if not isinstance(raw, dict):
        return Config()

    def _int(key: str, default):
        v = raw.get(key, default)
        return v if isinstance(v, int) and not isinstance(v, bool) else default

    def _str(key: str, default):
        v = raw.get(key, default)
        return v if isinstance(v, str) else default

    # A relative workspace_root would resolve against the daemon's cwd, which
    # is not the directory anyone was thinking of. Scattering workspaces
    # silently is the exact failure this package exists to end, so a relative
    # value is dropped in favour of the default.
    ws_raw = raw.get("workspace_root")
    ws: Path | None = None
    if isinstance(ws_raw, str) and ws_raw.strip():
        candidate = Path(ws_raw).expanduser()
        if candidate.is_absolute():
            ws = candidate

    return Config(
        port=_int("port", DEFAULT_PORT),
        token=_str("token", ""),
        bind=_str("bind", DEFAULT_BIND),
        retention_days=_int("retention_days", None) if raw.get("retention_days") is not None else None,
        workspace_root=ws,
        public_host=_str("public_host", None) or None,
    )


def write(cfg: Config, path: Path | None = None) -> None:
    """Write the config 0600, atomically.

    The mode is set on the temp file BEFORE the rename, so the token is never
    briefly world-readable at the destination path.
    """
    path = Path(path) if path is not None else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "port": cfg.port,
        "token": cfg.token,
        "bind": cfg.bind,
        "retention_days": cfg.retention_days,
        "workspace_root": str(cfg.workspace_root) if cfg.workspace_root else None,
        "public_host": cfg.public_host,
    }
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="config.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/config.py tests/test_config.py
git commit -m "feat: configuration file as the daemon's only settings source"
```

---

### Task 3: Atomic writes and kind-namespaced workspace paths

**Files:**
- Create: `src/webcompanion/atomic.py`, `src/webcompanion/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `webcompanion.config.Config`.
- Produces: `atomic.write_text_atomic(path: Path, text: str) -> None`; `paths.state_root() -> Path`; `paths.workspace_root(cfg: Config) -> Path`; `paths.kind_root(cfg: Config, kind: str) -> Path`; `paths.make_session_dirs(cfg: Config, kind: str, sid: str) -> dict[str, Path]`; `paths.base_of(dirs: dict) -> Path`; `paths.write_marker(base, sid, kind, cwd) -> None`; `paths.read_marker(base) -> dict`; `paths.VALID_KIND_RE`.

The `dirs` mapping keys are exactly: `state_dir`, `items_dir`, `threads_dir`, `events_dir`, `consumed_dir`, `assets_dir`. Later tasks index this mapping by those names; `_sid`, `_cwd` and `_kind` are added by the registry, not here.

- [ ] **Step 1: Write the failing test**

`tests/test_paths.py`:

```python
from __future__ import annotations

import pytest

from webcompanion import paths
from webcompanion.config import Config


def test_workspaces_are_namespaced_by_kind(tmp_path):
    cfg = Config(workspace_root=tmp_path)
    a = paths.make_session_dirs(cfg, "annotate", "s1")
    d = paths.make_session_dirs(cfg, "deck", "s1")
    assert paths.base_of(a) != paths.base_of(d)
    assert paths.base_of(a).parent.name == "annotate"
    assert paths.base_of(d).parent.name == "deck"


def test_every_expected_subdir_is_created(tmp_path):
    dirs = paths.make_session_dirs(Config(workspace_root=tmp_path), "annotate", "s1")
    assert set(dirs) == {"state_dir", "items_dir", "threads_dir",
                         "events_dir", "consumed_dir", "assets_dir"}
    for p in dirs.values():
        assert p.is_dir()


def test_marker_records_the_project_the_workspace_belongs_to(tmp_path):
    dirs = paths.make_session_dirs(Config(workspace_root=tmp_path), "deck", "s2")
    base = paths.base_of(dirs)
    paths.write_marker(base, "s2", "deck", "/home/x/proj")
    assert paths.read_marker(base) == {"sid": "s2", "kind": "deck", "cwd": "/home/x/proj"}


def test_missing_marker_reads_as_empty(tmp_path):
    dirs = paths.make_session_dirs(Config(workspace_root=tmp_path), "deck", "s3")
    assert paths.read_marker(paths.base_of(dirs)) == {}


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", ".", "Annotate!", "x" * 65])
def test_a_kind_that_could_escape_the_root_is_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        paths.make_session_dirs(Config(workspace_root=tmp_path), bad, "s1")


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "s id"])
def test_a_sid_that_could_escape_the_root_is_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        paths.make_session_dirs(Config(workspace_root=tmp_path), "annotate", bad)


def test_default_root_is_under_the_claude_directory():
    assert paths.workspace_root(Config()).parts[-2:] == (".claude", "webcompanion") + () \
        or paths.workspace_root(Config()).name == "workspaces"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_paths.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.paths'`

- [ ] **Step 3: Port atomic.py verbatim**

`src/webcompanion/atomic.py` — copy from `skills/_shared/web_companion/atomic.py` unchanged except the module docstring's reference to the old package. The unique-temp-name reasoning in that docstring is the whole point of the module; keep it.

```python
"""Atomic file writes — safe under concurrent writers.

The naive `tmp = path.with_suffix(".tmp"); tmp.write_text(...); tmp.replace(path)`
pattern uses a FIXED temp filename, so two writers racing on the same target
truncate/interleave the same tmp file and one promotes garbage (or the second
`replace` hits FileNotFoundError after the first already renamed it). Using a
unique temp name per writer makes the rename genuinely atomic and
last-writer-wins.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Write paths.py**

`src/webcompanion/paths.py`:

```python
"""Where a session's files live on disk.

One daemon now holds sessions that used to live under five separate roots.
Merging them naively would let two kinds collide: `register_with_slug` dedups
slugs globally, so /annotate and /deck could no longer both own `my-plan` —
one would silently become `my-plan-2`, changing a URL a user has memorised.
It would also widen garbage collection: the stray sweep removes any
sid-shaped directory no registry row points at, so a registry bug in one kind
could delete another kind's workspaces.

Namespacing by kind fixes both. A workspace is
`<workspace_root>/<kind>/<sid>/`, slugs are unique within a kind, and the
sweep for one kind can only ever reach that kind's directory.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from webcompanion.atomic import write_text_atomic
from webcompanion.config import Config

# A kind names a directory, so it must not be able to escape one.
VALID_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
VALID_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

MARKER_FILE = "workspace.json"

_SUBDIRS = {
    "state_dir": ("state",),
    "items_dir": ("items",),
    "threads_dir": ("threads",),
    "events_dir": ("state", "events"),
    "consumed_dir": ("state", "consumed"),
    "assets_dir": ("assets",),
}


def state_root() -> Path:
    """Where the registry and config live. Not overridable — the CLI and the
    IntelliJ plugin both hardcode this path to find the config file, so an
    override would split the two halves of one directory."""
    return Path("~/.claude/webcompanion").expanduser()


def workspace_root(cfg: Config) -> Path:
    if cfg.workspace_root is not None:
        return cfg.workspace_root
    return state_root() / "workspaces"


def kind_root(cfg: Config, kind: str) -> Path:
    if not VALID_KIND_RE.match(kind or ""):
        raise ValueError(f"invalid kind: {kind!r}")
    return workspace_root(cfg) / kind


def make_session_dirs(cfg: Config, kind: str, sid: str) -> dict[str, Path]:
    if not VALID_SID_RE.match(sid or ""):
        raise ValueError(f"invalid sid: {sid!r}")
    base = kind_root(cfg, kind) / sid
    dirs = {key: base.joinpath(*rel) for key, rel in _SUBDIRS.items()}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def base_of(dirs: dict) -> Path:
    """The workspace's top directory, from a `dirs` mapping."""
    return Path(dirs["items_dir"]).parent


def write_marker(base: Path, sid: str, kind: str, cwd: str) -> None:
    """Record which project this workspace belongs to, inside the workspace.

    Best-effort: a workspace that fails to describe itself is still usable,
    and refusing to create one over a marker write would be worse than a
    missing marker.
    """
    try:
        write_text_atomic(
            Path(base) / MARKER_FILE,
            json.dumps({"sid": sid, "kind": kind, "cwd": str(cwd)}, indent=2),
        )
    except OSError:
        pass


def read_marker(base: Path) -> dict:
    try:
        data = json.loads((Path(base) / MARKER_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_paths.py -q`
Expected: 13 passed (the two parametrized tests contribute 5 and 4)

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/atomic.py src/webcompanion/paths.py tests/test_paths.py
git commit -m "feat: kind-namespaced workspace paths and atomic writes"
```

---

### Task 4: Session registry with kind and a monotonic change counter

**Files:**
- Create: `src/webcompanion/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `atomic.write_text_atomic`, `paths`.
- Produces: `Registry(state_root: Path)` with `make_sid() -> str`; `create(kind, sid, dirs, meta_base, cwd, explicit_slug="") -> str` (returns slug; the caller mints `sid` because `make_session_dirs` needs it first); `lookup(sid) -> dict | None`; `resolve(key, kind=None) -> str | None`; `get_meta(sid) -> dict`; `unregister(sid) -> None`; `items() -> list[tuple[str, dict]]`; `find(cwd=None, kind=None) -> list[tuple[str, dict]]`; `list_all() -> list[tuple[str, dict]]`; `persist() -> None`; `rehydrate(cfg) -> None`; `version(sid) -> int`; `note_change(sid) -> int`; `wait_for_change(sid, since: int, timeout: float) -> int`.

`note_change` and `wait_for_change` replace the old `waiter()`/`Event` pair. The old `note_change` did `ev.set()` immediately followed by `ev.clear()` — an edge, with a genuine lost-wakeup window between the two calls. Today that is masked because the SSE loop re-reads on every 30-second timeout, so the worst case is 30 seconds of staleness. At merged scale it is hit far more often. A monotonic counter compared against the caller's last-seen value has no edge to miss.

- [ ] **Step 1: Write the failing test**

`tests/test_registry.py`:

```python
from __future__ import annotations

import threading
import time

from webcompanion import paths
from webcompanion.config import Config
from webcompanion.registry import Registry


def _mk(reg, cfg, kind, title, cwd="/proj", slug=""):
    sid = reg.make_sid()
    dirs = paths.make_session_dirs(cfg, kind, sid)
    return sid, reg.create(kind, sid, dirs, {"title": title}, cwd, slug)


def test_two_kinds_may_hold_the_same_slug(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    _, a = _mk(reg, cfg, "annotate", "My Plan")
    _, d = _mk(reg, cfg, "deck", "My Plan")
    assert a == "my-plan"
    assert d == "my-plan", "slugs are unique within a kind, not across kinds"


def test_same_slug_twice_in_one_kind_is_deduped(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    _, first = _mk(reg, cfg, "annotate", "My Plan")
    _, second = _mk(reg, cfg, "annotate", "My Plan")
    assert (first, second) == ("my-plan", "my-plan-2")


def test_resolve_requires_the_kind_to_disambiguate(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    sid_a, _ = _mk(reg, cfg, "annotate", "My Plan")
    sid_d, _ = _mk(reg, cfg, "deck", "My Plan")
    assert reg.resolve("my-plan", kind="annotate") == sid_a
    assert reg.resolve("my-plan", kind="deck") == sid_d
    assert reg.resolve(sid_a) == sid_a


def test_find_filters_by_cwd_and_kind(tmp_path):
    # Without the kind filter one daemon returns every kind for a cwd, and
    # the IntelliJ walkthrough panel latches an annotate session.
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    sid_w, _ = _mk(reg, cfg, "walkthrough", "W", cwd="/p")
    _mk(reg, cfg, "annotate", "A", cwd="/p")
    _mk(reg, cfg, "walkthrough", "W2", cwd="/other")
    found = reg.find(cwd="/p", kind="walkthrough")
    assert [sid for sid, _ in found] == [sid_w]


def test_meta_records_the_kind(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    sid, _ = _mk(reg, cfg, "deck", "D")
    assert reg.get_meta(sid)["kind"] == "deck"


def test_persist_and_rehydrate_survive_a_restart(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    sid, slug = _mk(reg, cfg, "annotate", "Keep Me")
    reg.persist()
    fresh = Registry(tmp_path / "state")
    fresh.rehydrate(cfg)
    assert fresh.resolve(slug, kind="annotate") == sid
    assert fresh.get_meta(sid)["kind"] == "annotate"


def test_rehydrate_drops_rows_whose_directories_are_gone(tmp_path):
    import shutil
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    sid, _ = _mk(reg, cfg, "annotate", "Doomed")
    reg.persist()
    shutil.rmtree(paths.base_of(reg.lookup(sid)))
    fresh = Registry(tmp_path / "state")
    fresh.rehydrate(cfg)
    assert fresh.lookup(sid) is None


def test_change_counter_is_monotonic_not_an_edge(tmp_path):
    reg = Registry(tmp_path / "state")
    assert reg.version("s") == 0
    assert reg.note_change("s") == 1
    assert reg.note_change("s") == 2
    assert reg.version("s") == 2


def test_a_change_between_read_and_wait_is_not_lost(tmp_path):
    # The old Event.set()/clear() pair could drop exactly this: the change
    # lands after the caller reads its snapshot but before it blocks.
    reg = Registry(tmp_path / "state")
    seen = reg.version("s")
    reg.note_change("s")
    assert reg.wait_for_change("s", since=seen, timeout=0.01) == 1


def test_wait_returns_the_same_version_on_timeout(tmp_path):
    reg = Registry(tmp_path / "state")
    started = time.monotonic()
    assert reg.wait_for_change("s", since=0, timeout=0.05) == 0
    assert time.monotonic() - started >= 0.04


def test_a_waiting_thread_wakes_on_change(tmp_path):
    reg = Registry(tmp_path / "state")
    out = []
    t = threading.Thread(target=lambda: out.append(reg.wait_for_change("s", 0, 5.0)))
    t.start()
    time.sleep(0.05)
    reg.note_change("s")
    t.join(timeout=2)
    assert out == [1]


def test_unregister_frees_the_slug_and_the_counter(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    sid, slug = _mk(reg, cfg, "annotate", "Gone")
    reg.note_change(sid)
    reg.unregister(sid)
    assert reg.resolve(slug, kind="annotate") is None
    assert sid not in reg._counters, "a never-restarting process must not leak per-session state"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.registry'`

- [ ] **Step 3: Write the implementation**

`src/webcompanion/registry.py`:

```python
"""Session identity: sid, slug, kind, and the per-session change counter.

The registry knows what sessions exist and where their directories are. It
knows nothing about their content — that is items.py's job — and nothing
about HTTP.

Two things differ from the per-skill registry this replaces. Slugs are unique
within a kind rather than globally, because one daemon must not make
/annotate and /deck fight over `my-plan`. And change notification is a
monotonic counter rather than a threading.Event that is set and immediately
cleared: the old shape had a real lost-wakeup window between set() and
clear(), survivable only because the SSE loop re-read on a 30s timeout.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path

from webcompanion.atomic import write_text_atomic
from webcompanion.paths import VALID_SID_RE


class Registry:
    def __init__(self, state_root: Path):
        self._state_root = Path(state_root)
        self._sessions: dict[str, dict] = {}
        self._meta: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._counters: dict[str, int] = {}

    # ── files ────────────────────────────────────────────────────────────
    @property
    def sessions_file(self) -> Path:
        return self._state_root / "sessions.json"

    @property
    def sessions_meta_file(self) -> Path:
        return self._state_root / "sessions_meta.json"

    # ── identity ─────────────────────────────────────────────────────────
    def make_sid(self) -> str:
        return f"{time.strftime('%y%m%d-%H%M%S')}-{secrets.token_hex(8)}"

    @staticmethod
    def _slugify(text: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
        return s[:40].strip("-")

    def create(self, kind: str, sid: str, dirs: dict, meta_base: dict,
               cwd: str, explicit_slug: str = "") -> str:
        """Pick a free slug within `kind` and register dirs + meta atomically.

        Pick-and-insert happens inside one lock acquisition. Splitting them
        is a check-then-act race: two concurrent creates with the same title
        both compute the same slug before either registers it.
        """
        base = (
            self._slugify(explicit_slug)
            or self._slugify(meta_base.get("title", ""))
            or self._slugify(Path(cwd).name)
            or "session"
        )
        with self._lock:
            taken = {
                m.get("slug") for m in self._meta.values()
                if m.get("kind") == kind and m.get("slug")
            }
            slug = base
            if slug in taken:
                n = 2
                while f"{base}-{n}" in taken:
                    n += 1
                slug = f"{base}-{n}"
            self._sessions[sid] = {**dirs, "_sid": sid, "_cwd": str(cwd), "_kind": kind}
            self._meta[sid] = {**meta_base, "slug": slug, "kind": kind,
                               "cwd": str(cwd), "created_at": int(time.time())}
        return slug

    def lookup(self, sid: str) -> dict | None:
        with self._lock:
            return self._sessions.get(sid)

    def resolve(self, key: str, kind: str | None = None) -> str | None:
        """A sid, or a slug within `kind`. A slug without a kind is ambiguous
        once two kinds can hold the same one, so it resolves only if exactly
        one session matches."""
        with self._lock:
            if key in self._sessions:
                return key
            matches = [
                sid for sid, m in self._meta.items()
                if m.get("slug") == key and sid in self._sessions
                and (kind is None or m.get("kind") == kind)
            ]
        return matches[0] if len(matches) == 1 else None

    def get_meta(self, sid: str) -> dict:
        with self._lock:
            return dict(self._meta.get(sid, {}))

    def unregister(self, sid: str) -> None:
        """Drop a dead session in memory, freeing its slug and its counter.

        Does NOT persist — persist() takes the lock itself, so calling it here
        would nest; the caller's next persist() snapshots the removal.
        """
        with self._lock:
            self._sessions.pop(sid, None)
            self._meta.pop(sid, None)
            self._counters.pop(sid, None)

    def items(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self._sessions.items())

    def find(self, cwd: str | None = None, kind: str | None = None) -> list[tuple[str, dict]]:
        """Sessions matching cwd and/or kind.

        The kind filter is why this exists. Both IntelliJ clients discover by
        cwd alone, which was unambiguous only while they hit different ports.
        """
        out = []
        for sid, dirs in self.items():
            if cwd is not None and str(dirs.get("_cwd", "")) != str(cwd):
                continue
            if kind is not None and str(dirs.get("_kind", "")) != kind:
                continue
            out.append((sid, dirs))
        return out

    def list_all(self) -> list[tuple[str, dict]]:
        out = self.items()
        out.sort(key=lambda kv: kv[0], reverse=True)
        return out

    # ── persistence ──────────────────────────────────────────────────────
    def persist(self) -> None:
        self._state_root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            snapshot = {
                sid: {k: str(v) for k, v in dirs.items()}
                for sid, dirs in self._sessions.items()
            }
            meta_snapshot = {sid: dict(m) for sid, m in self._meta.items()}
        write_text_atomic(self.sessions_file, json.dumps(snapshot, indent=2))
        write_text_atomic(self.sessions_meta_file, json.dumps(meta_snapshot, indent=2))

    def rehydrate(self, cfg=None) -> None:
        """Restore rows whose directories still exist. A row pointing at a
        deleted tree is dropped, not resurrected."""
        try:
            snapshot = json.loads(self.sessions_file.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(snapshot, dict):
            return
        restored: dict[str, dict] = {}
        for sid, dirs in snapshot.items():
            if not VALID_SID_RE.match(sid) or not isinstance(dirs, dict):
                continue
            paths_map = {k: (v if k.startswith("_") else Path(v)) for k, v in dirs.items()}
            real = [v for k, v in paths_map.items() if not k.startswith("_")]
            if not real or not all(isinstance(p, Path) and p.is_dir() for p in real):
                continue
            restored[sid] = paths_map
        with self._lock:
            self._sessions.update(restored)
        try:
            msnap = json.loads(self.sessions_meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            msnap = {}
        if isinstance(msnap, dict):
            with self._lock:
                live = set(self._sessions)
                self._meta.update({
                    sid: m for sid, m in msnap.items()
                    if sid in live and isinstance(m, dict)
                })

    # ── change notification ──────────────────────────────────────────────
    def version(self, sid: str) -> int:
        with self._lock:
            return self._counters.get(sid, 0)

    def note_change(self, sid: str) -> int:
        """Bump this session's counter and wake every waiter. Returns the new
        value."""
        with self._cond:
            v = self._counters.get(sid, 0) + 1
            self._counters[sid] = v
            self._cond.notify_all()
            return v

    def wait_for_change(self, sid: str, since: int, timeout: float) -> int:
        """Block until this session's counter exceeds `since`, or `timeout`.

        Returns the current counter either way. A change that lands between
        the caller reading its snapshot and calling this is NOT lost: the
        comparison is against a value, not an edge.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._counters.get(sid, 0) <= since:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(timeout=remaining)
            return self._counters.get(sid, 0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_registry.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/registry.py tests/test_registry.py
git commit -m "feat: session registry with per-kind slugs and a monotonic change counter"
```

---

### Task 5: Generic per-anchor version chain

**Files:**
- Create: `src/webcompanion/versions.py`
- Test: `tests/test_versions.py`

**Interfaces:**
- Consumes: `atomic.write_text_atomic`.
- Produces: `derive_versions(chain_path: Path, bodies: dict[str, dict]) -> dict[str, int]`; `body_hash(body: dict) -> str`.

This generalises `skills/annotate/versions.py`. That module hashes annotate's specific block shape — `kind`, `markdown`, `spec`, `code` — and normalises markdown for cosmetic noise. The daemon does not know what markdown is, so the hash is over the item body's canonical JSON, full stop. Cosmetic-noise normalisation moves client-side, where markdown is already understood. Everything else — the chain, the pruning rule, the convergence property under concurrent writers — carries over unchanged.

- [ ] **Step 1: Write the failing test**

`tests/test_versions.py`:

```python
from __future__ import annotations

import json

from webcompanion.versions import body_hash, derive_versions


def test_a_new_anchor_starts_at_version_one(tmp_path):
    v = derive_versions(tmp_path / "v.json", {"b-1": {"text": "hello"}})
    assert v == {"b-1": 1}


def test_unchanged_content_does_not_bump(tmp_path):
    p = tmp_path / "v.json"
    derive_versions(p, {"b-1": {"text": "hello"}})
    assert derive_versions(p, {"b-1": {"text": "hello"}}) == {"b-1": 1}


def test_changed_content_bumps_by_one(tmp_path):
    p = tmp_path / "v.json"
    derive_versions(p, {"b-1": {"text": "hello"}})
    assert derive_versions(p, {"b-1": {"text": "goodbye"}}) == {"b-1": 2}


def test_key_order_is_not_a_content_change(tmp_path):
    p = tmp_path / "v.json"
    derive_versions(p, {"b-1": {"a": 1, "b": 2}})
    assert derive_versions(p, {"b-1": {"b": 2, "a": 1}}) == {"b-1": 1}


def test_only_the_edited_anchor_bumps(tmp_path):
    p = tmp_path / "v.json"
    derive_versions(p, {"b-1": {"t": "a"}, "b-2": {"t": "b"}})
    out = derive_versions(p, {"b-1": {"t": "a"}, "b-2": {"t": "CHANGED"}})
    assert out == {"b-1": 1, "b-2": 2}


def test_a_removed_anchor_is_pruned_so_a_reused_id_starts_fresh(tmp_path):
    # Anchors can be reminted. If a deleted anchor's chain lingered, a new
    # item reusing that id would inherit a stale version — and if its content
    # happened to hash-match the old tail it would be reported unchanged.
    p = tmp_path / "v.json"
    derive_versions(p, {"b-1": {"t": "old"}})
    derive_versions(p, {"b-1": {"t": "old2"}})
    derive_versions(p, {})
    assert derive_versions(p, {"b-1": {"t": "brand new"}}) == {"b-1": 1}


def test_a_corrupt_chain_file_is_treated_as_absent(tmp_path):
    p = tmp_path / "v.json"
    p.write_text("{not json")
    assert derive_versions(p, {"b-1": {"t": "x"}}) == {"b-1": 1}


def test_concurrent_writers_converge(tmp_path):
    import threading
    p = tmp_path / "v.json"
    bodies = {"b-1": {"t": "same"}}
    threads = [threading.Thread(target=derive_versions, args=(p, bodies)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert derive_versions(p, bodies) == {"b-1": 1}
    assert len(json.loads(p.read_text())["b-1"]) == 1


def test_hash_is_stable_across_calls():
    assert body_hash({"a": 1}) == body_hash({"a": 1})
    assert body_hash({"a": 1}) != body_hash({"a": 2})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_versions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.versions'`

- [ ] **Step 3: Write the implementation**

`src/webcompanion/versions.py`:

```python
"""Server-derived per-anchor version chains.

An item's version is never something a client writes. It is computed by
hashing the item's canonical JSON body and comparing against a per-anchor
hash chain in a sidecar file; the reported version is the chain's length, a
value that can only grow when content actually changes.

This kills two failure modes at once: a client rewriting unrelated items
bumps their versions for no reason, and byte-churn that changes nothing
visible bumps versions anyway. The daemon cannot filter cosmetic noise the
way annotate's version of this module did — it does not know that a body
contains markdown, or HTML, or a diagram spec — so normalisation belongs in
whichever client understands the format. Canonical JSON is the part that is
genuinely generic: key order is not a content change.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from webcompanion.atomic import write_text_atomic


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def body_hash(body: dict) -> str:
    h = hashlib.sha1()
    h.update(_canonical_json(body).encode("utf-8"))
    return h.hexdigest()


def _load_chain(path: Path) -> dict[str, list[str]]:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: list(v) for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
    }


def derive_versions(chain_path: Path, bodies: dict[str, dict]) -> dict[str, int]:
    """Return {anchor: version} for `bodies`, growing the chain where content
    changed and pruning anchors no longer present.

    Concurrent calls converge: both read the same tail, both append the same
    hash, and last-writer-wins leaves identical state.
    """
    chain_path = Path(chain_path)
    chain = _load_chain(chain_path)
    changed = False

    for stale in [k for k in chain if k not in bodies]:
        del chain[stale]
        changed = True

    for anchor, body in bodies.items():
        if not isinstance(anchor, str):
            continue
        h = body_hash(body if isinstance(body, dict) else {"_": body})
        history = chain.setdefault(anchor, [])
        if not history or history[-1] != h:
            history.append(h)
            changed = True

    if changed:
        write_text_atomic(chain_path, json.dumps(chain, indent=2))

    return {a: len(chain.get(a, [])) or 1 for a in bodies if isinstance(a, str)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_versions.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/versions.py tests/test_versions.py
git commit -m "feat: generic per-anchor version chain over canonical JSON"
```

---

### Task 6: Item store

**Files:**
- Create: `src/webcompanion/items.py`
- Test: `tests/test_items.py`

**Interfaces:**
- Consumes: `atomic.write_text_atomic`, `versions.derive_versions`, `paths`.
- Produces: `put(items_dir, anchor, body) -> None`; `put_many(items_dir, bodies: dict) -> None`; `delete(items_dir, anchor) -> bool`; `load_all(items_dir) -> dict[str, dict]`; `load_one(items_dir, anchor) -> dict | None`; `snapshot(items_dir) -> dict[str, dict]` returning `{anchor: {"body": ..., "version": int}}`; `versions_of(items_dir) -> dict[str, int]`; `valid_anchor(anchor: str) -> bool`; `MAX_BODY_BYTES`.

Anchors are client-chosen and become filenames, so they are URL-quoted and length-capped exactly as `threads.py` already does for its own anchors — reuse that encoding so an item and its thread agree on the same on-disk name.

- [ ] **Step 1: Write the failing test**

`tests/test_items.py`:

```python
from __future__ import annotations

import pytest

from webcompanion import items


def test_put_then_load_roundtrips(tmp_path):
    items.put(tmp_path, "b-1", {"text": "hello"})
    assert items.load_one(tmp_path, "b-1") == {"text": "hello"}


def test_snapshot_reports_bodies_with_derived_versions(tmp_path):
    items.put(tmp_path, "b-1", {"text": "one"})
    items.put(tmp_path, "b-2", {"text": "two"})
    snap = items.snapshot(tmp_path)
    assert snap["b-1"] == {"body": {"text": "one"}, "version": 1}
    assert snap["b-2"]["version"] == 1


def test_rewriting_one_item_bumps_only_its_version(tmp_path):
    items.put_many(tmp_path, {"b-1": {"t": "a"}, "b-2": {"t": "b"}})
    items.snapshot(tmp_path)
    items.put(tmp_path, "b-2", {"t": "CHANGED"})
    snap = items.snapshot(tmp_path)
    assert (snap["b-1"]["version"], snap["b-2"]["version"]) == (1, 2)


def test_delete_removes_the_item_and_prunes_its_chain(tmp_path):
    items.put(tmp_path, "b-1", {"t": "a"})
    items.snapshot(tmp_path)
    assert items.delete(tmp_path, "b-1") is True
    assert items.load_one(tmp_path, "b-1") is None
    assert items.snapshot(tmp_path) == {}
    items.put(tmp_path, "b-1", {"t": "fresh"})
    assert items.snapshot(tmp_path)["b-1"]["version"] == 1


def test_deleting_an_absent_item_is_false_not_an_error(tmp_path):
    assert items.delete(tmp_path, "nope") is False


def test_put_many_replaces_the_whole_document(tmp_path):
    items.put_many(tmp_path, {"b-1": {"t": "a"}, "b-2": {"t": "b"}})
    items.put_many(tmp_path, {"b-1": {"t": "a"}}, replace=True)
    assert set(items.load_all(tmp_path)) == {"b-1"}


def test_put_many_without_replace_is_an_upsert(tmp_path):
    items.put_many(tmp_path, {"b-1": {"t": "a"}})
    items.put_many(tmp_path, {"b-2": {"t": "b"}})
    assert set(items.load_all(tmp_path)) == {"b-1", "b-2"}


@pytest.mark.parametrize("anchor", ["", "../escape", "a/../b", "\x00null"])
def test_an_anchor_that_could_escape_the_directory_is_rejected(tmp_path, anchor):
    assert items.valid_anchor(anchor) is False
    with pytest.raises(ValueError):
        items.put(tmp_path, anchor, {"t": "x"})


def test_a_long_anchor_is_hashed_rather_than_truncated(tmp_path):
    long_anchor = "src/" + "x" * 400 + ".java:L:12"
    items.put(tmp_path, long_anchor, {"t": "x"})
    assert items.load_one(tmp_path, long_anchor) == {"t": "x"}
    assert all(len(p.name) <= 210 for p in tmp_path.iterdir())


def test_an_oversized_body_is_rejected(tmp_path):
    huge = {"t": "x" * (items.MAX_BODY_BYTES + 1)}
    with pytest.raises(ValueError):
        items.put(tmp_path, "b-1", huge)


def test_a_corrupt_item_file_is_skipped_not_fatal(tmp_path):
    items.put(tmp_path, "b-1", {"t": "good"})
    (tmp_path / "corrupt.json").write_text("{not json")
    assert items.load_all(tmp_path) == {"b-1": {"t": "good"}}
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_items.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.items'`

- [ ] **Step 3: Write the implementation**

`src/webcompanion/items.py`:

```python
"""The item store — one JSON body per anchor, plus a derived version.

An item is opaque. The daemon stores the body verbatim, hashes it for
versioning, and hands it back. It never inspects the body's shape, because
the five clients that push items disagree completely about what one contains:
a markdown block, a slide, a diff hunk, a graph node, a walkthrough step.

Anchors are client-chosen and become filenames, so they are URL-quoted and
hashed past a length cap — the same encoding threads.py uses, so an item and
its comment thread land on matching on-disk names.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

from webcompanion.atomic import write_text_atomic
from webcompanion.versions import derive_versions

MAX_BODY_BYTES = 2 * 1024 * 1024
CHAIN_FILE = ".versions.json"
_MAX_NAME = 200


def valid_anchor(anchor: str) -> bool:
    if not isinstance(anchor, str) or not anchor:
        return False
    if "\x00" in anchor or "\n" in anchor:
        return False
    # Path traversal is defeated by quoting rather than by inspection, but an
    # anchor whose decoded form walks out of the directory is a client bug
    # worth rejecting loudly rather than silently storing under a mangled name.
    return ".." not in Path(anchor).parts


def _encode(anchor: str) -> str:
    enc = urllib.parse.quote(anchor, safe="")
    if len(enc) > _MAX_NAME:
        enc = "h_" + hashlib.sha256(anchor.encode("utf-8")).hexdigest()
    return enc


def _path_for(items_dir: Path, anchor: str) -> Path:
    return Path(items_dir) / f"{_encode(anchor)}.json"


def put(items_dir: Path, anchor: str, body: dict) -> None:
    if not valid_anchor(anchor):
        raise ValueError(f"invalid anchor: {anchor!r}")
    payload = json.dumps({"anchor": anchor, "body": body})
    if len(payload.encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError("item body too large")
    Path(items_dir).mkdir(parents=True, exist_ok=True)
    write_text_atomic(_path_for(items_dir, anchor), payload)


def put_many(items_dir: Path, bodies: dict, replace: bool = False) -> None:
    """Upsert every anchor in `bodies`. With replace=True, anchors absent from
    `bodies` are deleted — the shape a full document push wants."""
    for anchor, body in bodies.items():
        put(items_dir, anchor, body)
    if replace:
        for anchor in set(load_all(items_dir)) - set(bodies):
            delete(items_dir, anchor)


def delete(items_dir: Path, anchor: str) -> bool:
    try:
        _path_for(items_dir, anchor).unlink()
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False


def load_one(items_dir: Path, anchor: str) -> dict | None:
    try:
        raw = json.loads(_path_for(items_dir, anchor).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return raw.get("body") if isinstance(raw, dict) else None


def load_all(items_dir: Path) -> dict[str, dict]:
    items_dir = Path(items_dir)
    if not items_dir.is_dir():
        return {}
    out: dict[str, dict] = {}
    for p in sorted(items_dir.iterdir()):
        if p.suffix != ".json" or p.name == CHAIN_FILE:
            continue
        try:
            raw = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and isinstance(raw.get("anchor"), str):
            out[raw["anchor"]] = raw.get("body")
    return out


def versions_of(items_dir: Path) -> dict[str, int]:
    return derive_versions(Path(items_dir) / CHAIN_FILE, load_all(items_dir))


def snapshot(items_dir: Path) -> dict[str, dict]:
    bodies = load_all(items_dir)
    versions = derive_versions(Path(items_dir) / CHAIN_FILE, bodies)
    return {a: {"body": b, "version": versions.get(a, 1)} for a, b in bodies.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_items.py -q`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/items.py tests/test_items.py
git commit -m "feat: opaque item store with derived versions"
```

---

### Task 7: Request-time code anchor resolution

**Files:**
- Create: `src/webcompanion/anchors.py`
- Test: `tests/test_anchors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `anchor_problem(a: Any) -> str | None`; `resolve_anchor(a: dict, root: Path) -> dict`; `resolve_all(body: dict, root: Path) -> list[dict]`; constants `MAX_ANCHORS = 3`, `MAX_WINDOW = 40`, `CONTEXT_LINES = 2`, `DRIFT_RADIUS = 40`, `MAX_BYTES = 1_000_000`, `MAX_LINE_CHARS = 2000`.

This is the one capability the daemon owns that looks client-specific, and it is deliberate. An item may declare `code: [{file, line, end_line?, snippet}]`, and the daemon reads that file **when the item is requested**, never at push time. `skills/annotate/anchors.py:1-10` states the rule: the item never carries code text, which is what makes an anchor impossible to leave stale relative to the working tree. Claude edits the repository during a session, so an anchor snapshotted at push is a lie within one turn.

Port `skills/annotate/anchors.py` with two changes: the module takes a root explicitly rather than reading a workspace, and `block_problems` becomes `resolve_all` keyed off an item body. The containment rule, the drift search, the byte and line caps, and the marker-not-exception failure rule all carry over verbatim — each exists because of a specific failure.

- [ ] **Step 1: Write the failing test**

`tests/test_anchors.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from webcompanion import anchors


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 51)) + "\n"
    )
    return tmp_path


def test_an_anchor_resolves_to_the_current_file_contents(repo):
    out = anchors.resolve_anchor(
        {"file": "src/app.py", "line": 10, "snippet": "line 10"}, repo)
    assert out["status"] == "ok"
    assert any(l["text"] == "line 10" and l["focus"] for l in out["lines"])


def test_editing_the_file_changes_what_a_later_read_returns(repo):
    a = {"file": "src/app.py", "line": 10, "snippet": "line 10"}
    first = anchors.resolve_anchor(a, repo)
    (repo / "src" / "app.py").write_text(
        "\n".join(f"CHANGED {i}" for i in range(1, 51)) + "\n")
    second = anchors.resolve_anchor(a, repo)
    assert first["lines"] != second["lines"], (
        "resolution must happen per request; a push-time snapshot goes stale "
        "within one turn while Claude edits the repo")


def test_a_moved_snippet_is_found_within_the_drift_radius(repo):
    (repo / "src" / "app.py").write_text(
        "\n".join(["preamble"] * 5 + [f"line {i}" for i in range(1, 51)]) + "\n")
    out = anchors.resolve_anchor(
        {"file": "src/app.py", "line": 10, "snippet": "line 10"}, repo)
    assert out["status"] == "drifted"
    assert out["line"] == 15


def test_a_snippet_that_vanished_is_a_marker_not_an_exception(repo):
    out = anchors.resolve_anchor(
        {"file": "src/app.py", "line": 10, "snippet": "not in this file"}, repo)
    assert out["status"] == "missing"
    assert "message" in out


@pytest.mark.parametrize("bad_file", ["../../.ssh/id_rsa", "/etc/passwd"])
def test_an_anchor_may_not_escape_the_root(repo, bad_file):
    # Anchors are model-authored and the read-only share link makes this
    # reachable by anyone holding it.
    out = anchors.resolve_anchor(
        {"file": bad_file, "line": 1, "snippet": "x"}, repo)
    assert out["status"] == "error"
    assert "lines" not in out or out["lines"] == []


def test_a_symlink_pointing_outside_the_root_is_refused(repo, tmp_path):
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("password")
    (repo / "link.txt").symlink_to(secret)
    out = anchors.resolve_anchor(
        {"file": "link.txt", "line": 1, "snippet": "password"}, repo)
    assert out["status"] == "error"


def test_a_file_over_the_byte_cap_is_refused(repo):
    big = repo / "big.json"
    big.write_text("x" * (anchors.MAX_BYTES + 1))
    out = anchors.resolve_anchor(
        {"file": "big.json", "line": 1, "snippet": "x"}, repo)
    assert out["status"] == "error"


def test_a_very_long_line_is_truncated(repo):
    (repo / "min.js").write_text("a" * (anchors.MAX_LINE_CHARS + 500))
    out = anchors.resolve_anchor(
        {"file": "min.js", "line": 1, "snippet": "aaa"}, repo)
    assert max(len(l["text"]) for l in out["lines"]) <= anchors.MAX_LINE_CHARS + 1


def test_the_window_is_capped(repo):
    out = anchors.resolve_anchor(
        {"file": "src/app.py", "line": 1, "end_line": 50, "snippet": "line 1"}, repo)
    assert len(out["lines"]) <= anchors.MAX_WINDOW


def test_resolve_all_caps_the_number_of_anchors(repo):
    body = {"code": [{"file": "src/app.py", "line": i, "snippet": f"line {i}"}
                     for i in range(1, 8)]}
    assert len(anchors.resolve_all(body, repo)) == anchors.MAX_ANCHORS


def test_resolve_all_on_a_body_with_no_code_is_empty(repo):
    assert anchors.resolve_all({"text": "hello"}, repo) == []


@pytest.mark.parametrize("bad,expect", [
    ({}, "must be"),
    ({"file": "", "line": 1, "snippet": "x"}, "non-empty"),
    ({"file": "/abs", "line": 1, "snippet": "x"}, "relative"),
    ({"file": "a", "line": 0, "snippet": "x"}, "positive"),
    ({"file": "a", "line": True, "snippet": "x"}, "positive"),
    ({"file": "a", "line": 2, "end_line": 1, "snippet": "x"}, "precede"),
    ({"file": "a", "line": 1, "snippet": "  "}, "non-empty"),
])
def test_anchor_problem_names_the_problem(bad, expect):
    problem = anchors.anchor_problem(bad)
    assert problem and expect in problem
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_anchors.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.anchors'`

- [ ] **Step 3: Port the module**

Copy `skills/annotate/anchors.py` to `src/webcompanion/anchors.py` and apply exactly these edits:

1. Replace the module docstring's first paragraph with the daemon's framing, keeping both rules verbatim:

```python
"""Code anchors — resolving an item's {file, line, snippet} to real source.

An item may carry a `code` list; each entry names a file and a line in the
session's project, and the daemon reads that file when the item is REQUESTED.
The item never carries code text, which is what makes an anchor cheap enough
to write generously and impossible to leave stale relative to the working
tree. A client edits its repository while a session is open, so an anchor
snapshotted at push time is wrong within a turn.

This is the one thing the daemon knows that looks client-specific. It is here
because it cannot live anywhere else — resolution must happen inside the
request — and because it contains no client concepts: a file, a line, and a
snippet mean the same thing to every client that pushes items.

Two rules shape everything below:

  * `file` is untrusted. Anchors are model-authored, so every path is
    resolved and then required to stay under the session's root. Without that
    check an item could name ../../.ssh/id_rsa and the page would print it to
    anyone holding the read-only share link.

  * A failure is a marker, never an exception. One bad anchor must not blank
    the page.
"""
```

2. Keep `MAX_ANCHORS`, `MAX_WINDOW`, `CONTEXT_LINES`, `DRIFT_RADIUS`, `MAX_BYTES`, `MAX_LINE_CHARS`, `_is_int`, `anchor_problem`, `_fail`, `_read_lines`, `resolve_anchor`, `_build`, `_locate` unchanged. The `MAX_BYTES` comment explaining why — a 40-line window over a minified file is still a multi-megabyte body every tick, and the client refetches once a second per open tab — stays with it.

3. Replace `block_problems(blk)` with:

```python
def resolve_all(body: dict, root: Path) -> list[dict]:
    """Resolve up to MAX_ANCHORS code anchors declared by this item body.

    Past three anchors an item has stopped being a glance and become a tour;
    the cap is a product decision, not a performance one.
    """
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, list):
        return []
    return [resolve_anchor(a, root) for a in code[:MAX_ANCHORS]
            if isinstance(a, dict)]
```

4. In `resolve_anchor`, confirm containment is checked on the **resolved** path so a symlink out of the root is refused:

```python
    try:
        target = (Path(root) / f).resolve()
        root_resolved = Path(root).resolve()
    except (OSError, ValueError):
        return _fail(a, "error", "path could not be resolved")
    if not target.is_relative_to(root_resolved):
        return _fail(a, "error", "file is outside the session root")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_anchors.py -q`
Expected: 20 passed. If `test_a_symlink_pointing_outside_the_root_is_refused` fails, the ported code checked containment before `.resolve()` — fix it, do not weaken the test.

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/anchors.py tests/test_anchors.py
git commit -m "feat: request-time code anchor resolution bounded to the session root"
```

---

### Task 8: Threads, events and uploads

**Files:**
- Create: `src/webcompanion/threads.py`, `src/webcompanion/events.py`, `src/webcompanion/uploads.py`
- Test: `tests/test_threads.py`, `tests/test_events.py`, `tests/test_uploads.py`

**Interfaces:**
- Consumes: `atomic.write_text_atomic`.
- Produces: `threads.load/save_atomic/append_message/set_anchor_text_if_absent/delete/list_versions/valid_anchor/GENERAL_ANCHOR`; `events.append(events_dir, payload) -> str`; `uploads.handle(handler, dirs)`, `uploads.images_ok(images, state_dir) -> bool`, `uploads.UPLOAD_MAX_BYTES`.

These three port with import changes only. Their existing tests in `skills/_shared/web_companion/tests/` come with them — `test_events.py`, `test_uploads.py`, and the thread coverage inside `test_write_gate.py` — rewritten only where they import.

One behaviour change: `threads.valid_anchor` currently enforces the interactive-review anchor grammar (`path:L|R:line`). The daemon accepts any anchor `items.valid_anchor` accepts, because a slide and a graph node are not diff lines. Keep the encoding function; drop the grammar.

- [ ] **Step 1: Write the failing test for the widened anchor rule**

`tests/test_threads.py` (in addition to porting the existing coverage):

```python
from __future__ import annotations

import threading

from webcompanion import threads


def test_any_client_chosen_anchor_is_accepted(tmp_path):
    # The old grammar was interactive-review's: path:L|R:line. A slide id and
    # a graph node id are neither.
    for anchor in ["b-3", "slide-2/title", "node:UserService", "src/a.java:L:12",
                   threads.GENERAL_ANCHOR]:
        assert threads.valid_anchor(anchor), anchor


def test_an_anchor_that_could_escape_the_directory_is_rejected(tmp_path):
    for anchor in ["", "../escape", "a/../../b"]:
        assert not threads.valid_anchor(anchor)


def test_append_is_deduped_by_source_event_id(tmp_path):
    msg = {"role": "assistant", "text": "hi", "source_event_id": "e1"}
    assert threads.append_message(tmp_path, "b-1", msg) is True
    assert threads.append_message(tmp_path, "b-1", dict(msg)) is False
    assert len(threads.load(tmp_path, "b-1")["messages"]) == 1


def test_concurrent_appends_do_not_lose_messages(tmp_path):
    # The server worker handling /api/submit and the agent appending its reply
    # are genuinely concurrent; the flock is what makes this safe.
    def add(i):
        threads.append_message(tmp_path, "b-1",
                               {"role": "user", "text": str(i), "source_event_id": f"e{i}"})
    ts = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(threads.load(tmp_path, "b-1")["messages"]) == 20


def test_lock_files_do_not_pollute_the_threads_directory(tmp_path):
    threads.append_message(tmp_path, "b-1", {"role": "user", "text": "x"})
    assert all(p.suffix == ".json" for p in tmp_path.iterdir())
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_threads.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.threads'`

- [ ] **Step 3: Port the three modules**

Copy `threads.py`, `events.py` and `uploads.py` from `skills/_shared/web_companion/`. Change `from skills._shared.web_companion.atomic import write_text_atomic` to `from webcompanion.atomic import write_text_atomic` in each. In `threads.py`, replace `valid_anchor` and delete `_ANCHOR_RE`:

```python
def valid_anchor(anchor: str) -> bool:
    """Any anchor a client can address an item by.

    This used to enforce interactive-review's `path:L|R:line` grammar, which
    is meaningless to a client whose anchors are slide ids or graph nodes.
    The daemon's only requirement is that the anchor cannot walk out of the
    threads directory once encoded.
    """
    from webcompanion.items import valid_anchor as _valid
    return anchor == GENERAL_ANCHOR or _valid(anchor)
```

Keep everything else — the `.locks/` sibling directory (so consumers iterating `threads_dir` see only `.json` files), the flock, the dedup, `set_anchor_text_if_absent`.

- [ ] **Step 4: Port the existing tests**

Copy `skills/_shared/web_companion/tests/test_events.py` and `test_uploads.py` into `tests/`, rewriting imports from `skills._shared.web_companion.X` to `webcompanion.X`. Delete any test asserting the old anchor grammar.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_threads.py tests/test_events.py tests/test_uploads.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/threads.py src/webcompanion/events.py src/webcompanion/uploads.py tests/
git commit -m "feat: port threads, events and uploads; widen the anchor rule"
```

---

### Task 9: Write gate and contract negotiation

**Files:**
- Create: `src/webcompanion/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `webcompanion.CONTRACT`, `config.Config`.
- Produces: `is_owner(handler, token: str) -> bool`; `is_loopback(addr: str) -> bool`; `check_contract(handler) -> tuple[bool, str]`; `WRITE_TOKEN_HEADER = "X-WebCompanion-Token"`; `CONTRACT_HEADER = "X-WebCompanion-Contract"`.

`gate.py` is the only module that decides whether a request may write. Both halves of the existing gate carry over exactly, because both were written against real attacks:

- **Loopback is the owner by construction.** Nobody else can reach it.
- **`Sec-Fetch-Site` is checked anyway.** JavaScript on *any* website runs from loopback, so a page you merely visit could otherwise reach the daemon as owner. `Content-Type: text/plain` makes a POST a CORS "simple request" the browser sends with no preflight, and handlers `json.loads` the body without consulting Content-Type — a working delete-everything gadget for any site you open. The browser sets `Sec-Fetch-Site` and script cannot forge it. Non-browser callers send neither header and are unaffected, so requiring one would break the CLI.
- **The `Origin` fallback compares host only**, deliberately.
- **Token comparison uses `compare_digest`** so a wrong guess takes the same time as any other.

Contract negotiation is new. A missing header is tolerated (a `curl` by hand, a health probe); a header that disagrees is `426`.

- [ ] **Step 1: Write the failing test**

`tests/test_gate.py`:

```python
from __future__ import annotations

import pytest

from webcompanion import CONTRACT, gate


class FakeHandler:
    def __init__(self, addr="127.0.0.1", **headers):
        self.client_address = (addr, 5000)
        self.headers = {k.replace("_", "-"): v for k, v in headers.items()}


def test_loopback_is_the_owner_with_no_token():
    assert gate.is_owner(FakeHandler("127.0.0.1"), token="secret") is True
    assert gate.is_owner(FakeHandler("::1"), token="secret") is True


def test_a_remote_client_needs_the_token():
    assert gate.is_owner(FakeHandler("10.0.0.5"), token="secret") is False
    h = FakeHandler("10.0.0.5")
    h.headers[gate.WRITE_TOKEN_HEADER] = "secret"
    assert gate.is_owner(h, token="secret") is True


def test_a_wrong_token_is_refused():
    h = FakeHandler("10.0.0.5")
    h.headers[gate.WRITE_TOKEN_HEADER] = "wrong"
    assert gate.is_owner(h, token="secret") is False


def test_a_cross_site_browser_request_is_refused_even_from_loopback():
    # Script on any website runs from loopback. Without this, visiting a page
    # would let it drive the local daemon as the owner.
    h = FakeHandler("127.0.0.1")
    h.headers["Sec-Fetch-Site"] = "cross-site"
    assert gate.is_owner(h, token="secret") is False


def test_a_same_origin_browser_request_is_allowed():
    h = FakeHandler("127.0.0.1")
    h.headers["Sec-Fetch-Site"] = "same-origin"
    assert gate.is_owner(h, token="secret") is True


def test_a_foreign_origin_header_is_refused():
    h = FakeHandler("127.0.0.1")
    h.headers["Origin"] = "https://evil.example"
    h.headers["Host"] = "127.0.0.1:3080"
    assert gate.is_owner(h, token="secret") is False


def test_a_matching_origin_host_is_allowed_ignoring_scheme_and_port():
    h = FakeHandler("127.0.0.1")
    h.headers["Origin"] = "http://127.0.0.1:3080"
    h.headers["Host"] = "127.0.0.1:3080"
    assert gate.is_owner(h, token="secret") is True


def test_a_non_browser_caller_sending_neither_header_is_allowed():
    # The CLI and the IDE plugin send neither; requiring one would break them.
    assert gate.is_owner(FakeHandler("127.0.0.1"), token="secret") is True


def test_an_empty_configured_token_never_authorises_a_remote_client():
    h = FakeHandler("10.0.0.5")
    h.headers[gate.WRITE_TOKEN_HEADER] = ""
    assert gate.is_owner(h, token="") is False


def test_a_missing_contract_header_is_tolerated():
    ok, _ = gate.check_contract(FakeHandler())
    assert ok is True


def test_a_matching_contract_header_is_accepted():
    h = FakeHandler()
    h.headers[gate.CONTRACT_HEADER] = str(CONTRACT)
    assert gate.check_contract(h)[0] is True


@pytest.mark.parametrize("sent,who", [("0", "client"), ("99", "daemon")])
def test_a_mismatched_contract_names_which_side_is_old(sent, who):
    h = FakeHandler()
    h.headers[gate.CONTRACT_HEADER] = sent
    ok, message = gate.check_contract(h)
    assert ok is False
    assert who in message


def test_a_junk_contract_header_is_a_mismatch_not_a_crash():
    h = FakeHandler()
    h.headers[gate.CONTRACT_HEADER] = "banana"
    assert gate.check_contract(h)[0] is False
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_gate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.gate'`

- [ ] **Step 3: Write the implementation**

`src/webcompanion/gate.py`:

```python
"""Who may write, and whether the two sides agree on the contract.

This is the only module that answers either question. Everything else asks it.
"""
from __future__ import annotations

import ipaddress
import secrets
from urllib.parse import urlsplit

from webcompanion import CONTRACT

WRITE_TOKEN_HEADER = "X-WebCompanion-Token"
CONTRACT_HEADER = "X-WebCompanion-Contract"


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _header(handler, name: str) -> str:
    try:
        return (handler.headers.get(name) or "").strip()
    except AttributeError:
        return ""


def is_owner(handler, token: str) -> bool:
    """Two ways to be the owner, and no third.

    Loopback is the owner by construction — nobody else can reach it, so the
    CLI and the browser on this machine both pass without configuration.
    Everyone else needs the capability token, handed out only through the
    owner URL.

    But loopback alone is not enough, because JavaScript on ANY website runs
    from loopback: a page you merely visit could otherwise reach this daemon
    as the owner. `Content-Type: text/plain` makes a POST a CORS "simple
    request", which the browser sends with no preflight to stop it, and the
    handlers json.loads the body without consulting Content-Type. That is a
    working delete-everything gadget for any site you open.

    `Sec-Fetch-Site` is the reliable signal — the browser sets it and script
    cannot forge it. Non-browser callers send neither it nor Origin and are
    unaffected; requiring one would break them.
    """
    site = _header(handler, "Sec-Fetch-Site").lower()
    if site and site not in ("same-origin", "same-site", "none"):
        return False

    origin = _header(handler, "Origin")
    if origin:
        # HOST ONLY, deliberately: the owner may reach the daemon over either
        # scheme and through a port-forward, and neither changes who they are.
        if urlsplit(origin).hostname != (_header(handler, "Host").rsplit(":", 1)[0] or None):
            return False

    if is_loopback(handler.client_address[0]):
        return True

    presented = _header(handler, WRITE_TOKEN_HEADER)
    if not presented or not token:
        return False
    return secrets.compare_digest(presented, token)


def check_contract(handler) -> tuple[bool, str]:
    """(ok, message). A missing header is tolerated — a hand-run curl or a
    health probe is not a contract violation. A header that disagrees is not
    tolerated, because the four artifacts speaking this contract update on
    different schedules and a silent mismatch presents as a dead poll."""
    raw = _header(handler, CONTRACT_HEADER)
    if not raw:
        return True, ""
    try:
        sent = int(raw)
    except ValueError:
        return False, (f"unreadable {CONTRACT_HEADER}: {raw!r}; "
                       f"this daemon speaks contract {CONTRACT}")
    if sent == CONTRACT:
        return True, ""
    if sent < CONTRACT:
        return False, (f"the client speaks contract {sent}, this daemon speaks "
                       f"{CONTRACT}; update the client")
    return False, (f"the client speaks contract {sent}, this daemon speaks "
                   f"{CONTRACT}; update the daemon with "
                   f"`pipx upgrade webcompanion && webcompanion install-service`")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_gate.py -q`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/gate.py tests/test_gate.py
git commit -m "feat: write gate and contract negotiation"
```

---

### Task 10: HTTP server — health, session lifecycle, discovery

**Files:**
- Create: `src/webcompanion/server.py`
- Test: `tests/test_server_sessions.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: everything built so far.
- Produces: `Daemon(cfg: Config)` with `.registry`, `.url`, `.start()`, `.stop()`; `serve_forever(cfg: Config) -> int`; `make_server(cfg) -> Daemon`. Test fixture `daemon` in `conftest.py` yielding a started `Daemon` on an ephemeral port with a temp workspace root.

Routes in this task:

    GET    /health                          {banner, contract, version, uptime, sessions}
    POST   /api/sessions                    {kind, cwd, slug?, title?, supersede?}
    GET    /api/sessions?cwd=&kind=
    GET    /api/sessions?scope=all          owner-gated
    POST   /s/<sid>/api/finish
    POST   /s/<sid>/api/cancel
    GET    /api/whoami                      {writable}

Three properties this task must establish and later tasks must not break: the server is `ThreadingHTTPServer` with `daemon_threads`, it has **no idle shutdown**, and every mutating route passes through `gate.is_owner` before it acts.

- [ ] **Step 1: Write the shared fixture**

`tests/conftest.py`:

```python
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from webcompanion.config import Config, mint_token
from webcompanion.server import Daemon


@pytest.fixture
def daemon(tmp_path):
    cfg = Config(port=0, token=mint_token(), bind="127.0.0.1",
                 workspace_root=tmp_path / "ws")
    d = Daemon(cfg, state_root=tmp_path / "state")
    d.start()
    try:
        yield d
    finally:
        d.stop()


@pytest.fixture
def call(daemon):
    def _call(method, path, body=None, headers=None, expect=None):
        url = daemon.url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read().decode()
                parsed = json.loads(raw) if raw.strip().startswith(("{", "[")) else raw
                return r.status, parsed
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, raw
    return _call
```

- [ ] **Step 2: Write the failing test**

`tests/test_server_sessions.py`:

```python
from __future__ import annotations

import threading

from webcompanion import CONTRACT, __version__
from webcompanion.gate import CONTRACT_HEADER


def test_health_reports_contract_and_version(call):
    status, body = call("GET", "/health")
    assert status == 200
    assert body["contract"] == CONTRACT
    assert body["version"] == __version__
    assert "webcompanion" in body["banner"]


def test_create_returns_a_sid_slug_and_url(call):
    status, body = call("POST", "/api/sessions",
                        {"kind": "annotate", "cwd": "/proj", "title": "My Plan"})
    assert status == 201
    assert body["slug"] == "my-plan"
    assert body["sid"]
    assert body["url"].endswith("/s/" + body["sid"] + "/")


def test_create_without_a_kind_is_rejected(call):
    # One daemon holds every kind; a session that cannot say which it is makes
    # discovery ambiguous for both IntelliJ clients.
    status, _ = call("POST", "/api/sessions", {"cwd": "/proj", "title": "X"})
    assert status == 400


def test_create_with_an_unusable_kind_is_rejected(call):
    for kind in ["../escape", "A B", ""]:
        status, _ = call("POST", "/api/sessions",
                         {"kind": kind, "cwd": "/proj", "title": "X"})
        assert status == 400, kind


def test_discovery_filters_by_kind(call):
    call("POST", "/api/sessions", {"kind": "walkthrough", "cwd": "/p", "title": "W"})
    call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "A"})
    _, rows = call("GET", "/api/sessions?cwd=/p&kind=walkthrough")
    assert [r["kind"] for r in rows] == ["walkthrough"]


def test_discovery_rows_carry_the_kind(call):
    call("POST", "/api/sessions", {"kind": "deck", "cwd": "/p", "title": "D"})
    _, rows = call("GET", "/api/sessions?cwd=/p")
    assert rows and all("kind" in r for r in rows)


def test_discovery_without_a_cwd_is_a_400(call):
    status, _ = call("GET", "/api/sessions")
    assert status == 400


def test_two_kinds_may_share_a_slug(call):
    _, a = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "Plan"})
    _, d = call("POST", "/api/sessions", {"kind": "deck", "cwd": "/p", "title": "Plan"})
    assert a["slug"] == d["slug"] == "plan"


def test_finish_marks_the_session_and_is_visible_to_poll(call):
    _, s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})
    assert call("POST", f"/s/{s['sid']}/api/finish")[0] == 200
    _, poll = call("GET", f"/s/{s['sid']}/poll")
    assert poll["finished"] is True


def test_cancel_marks_the_session(call):
    _, s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})
    assert call("POST", f"/s/{s['sid']}/api/cancel")[0] == 200
    _, poll = call("GET", f"/s/{s['sid']}/poll")
    assert poll["cancelled"] is True


def test_an_unknown_session_is_a_404(call):
    assert call("GET", "/s/does-not-exist/poll")[0] == 404


def test_a_mismatched_contract_is_426_and_names_the_old_side(call):
    status, body = call("GET", "/health", headers={CONTRACT_HEADER: "99"})
    assert status == 426
    assert "daemon" in body


def test_a_matching_contract_passes(call):
    assert call("GET", "/health", headers={CONTRACT_HEADER: str(CONTRACT)})[0] == 200


def test_scope_all_lists_every_kind(call):
    call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/a", "title": "A"})
    call("POST", "/api/sessions", {"kind": "deck", "cwd": "/b", "title": "B"})
    _, rows = call("GET", "/api/sessions?scope=all")
    assert {r["kind"] for r in rows} == {"annotate", "deck"}


def test_whoami_reports_writable_on_loopback(call):
    _, body = call("GET", "/api/whoami")
    assert body["writable"] is True


def test_concurrent_creates_get_distinct_slugs(call):
    out = []
    def create():
        out.append(call("POST", "/api/sessions",
                        {"kind": "annotate", "cwd": "/p", "title": "Same"})[1]["slug"])
    ts = [threading.Thread(target=create) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(out)) == 6, f"slug collision under concurrency: {out}"


def test_the_server_is_threaded(daemon):
    from http.server import ThreadingHTTPServer
    assert isinstance(daemon._httpd, ThreadingHTTPServer)
    assert daemon._httpd.daemon_threads is True


def test_there_is_no_idle_shutdown(daemon):
    # Under KeepAlive an idle shutdown is a daily restart that drops every
    # open SSE stream, and core.js has no reconnect.
    import inspect
    import webcompanion.server as srv
    source = inspect.getsource(srv)
    assert "shutdown_after" not in source
    assert "idle" not in source.lower() or "no idle shutdown" in source.lower()
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_server_sessions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.server'`

- [ ] **Step 4: Write the server**

`src/webcompanion/server.py` — the structure below; fill the route bodies from the tests above.

```python
"""The daemon: one threaded HTTP server on loopback, running until stopped.

Deliberately absent, and each absence is load-bearing:

  * No idle shutdown. The five servers this replaces exited after 24 hours
    idle, which under a supervisor becomes a daily restart that drops every
    open SSE stream and every IntelliJ client — and the runtime has no
    reconnect logic.
  * No source fingerprinting and no self-restart. A running daemon cannot
    notice that its own package was upgraded underneath it, so it does not
    pretend to; /health reports its version and the CLI compares.
  * No environment reads. See config.py.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from webcompanion import CONTRACT, __version__
from webcompanion import anchors, events, gate, items, paths, threads, uploads
from webcompanion.config import Config
from webcompanion.registry import Registry

BANNER = f"webcompanion v{__version__}"


class Daemon:
    def __init__(self, cfg: Config, state_root: Path | None = None):
        self.cfg = cfg
        self.state_root = Path(state_root) if state_root else paths.state_root()
        self.registry = Registry(self.state_root)
        self.started_at = time.time()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.registry.rehydrate(self.cfg)
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self.cfg.bind, self.cfg.port), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
```

The handler factory closes over the daemon. Route dispatch is a flat table, and **every mutating route calls `_require_owner` first** — the audit that ships with `claude-annotate` checks exactly this, so keep the shape greppable:

```python
def _make_handler(daemon: Daemon):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = BANNER

        def log_message(self, fmt, *args):
            pass  # the service log is for failures, not an access log

        # ── plumbing ────────────────────────────────────────────────────
        def _json(self, status: int, obj) -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _text(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return {}
            if n <= 0:
                return {}
            try:
                parsed = json.loads(self.rfile.read(n))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def _require_owner(self) -> bool:
            if gate.is_owner(self, daemon.cfg.token):
                return True
            self._text(403, "forbidden")
            return False

        def _contract_ok(self) -> bool:
            ok, message = gate.check_contract(self)
            if not ok:
                self._text(426, message)
            return ok

        def _session(self, sid: str):
            resolved = daemon.registry.resolve(sid)
            if resolved is None:
                self._text(404, "no such session")
                return None, None
            return resolved, daemon.registry.lookup(resolved)

        # ── dispatch ────────────────────────────────────────────────────
        def do_GET(self):
            if not self._contract_ok():
                return
            ...

        def do_POST(self):
            if not self._contract_ok():
                return
            ...

    return Handler
```

Session creation, in full, because three details are easy to get wrong:

```python
        def _create_session(self) -> None:
            if not self._require_owner():
                return
            payload = self._body()
            kind = str(payload.get("kind") or "")
            cwd = str(payload.get("cwd") or "")
            if not paths.VALID_KIND_RE.match(kind):
                self._text(400, "kind is required and must match [a-z][a-z0-9_-]*")
                return
            if not cwd:
                self._text(400, "cwd is required")
                return
            sid = daemon.registry.make_sid()
            try:
                dirs = paths.make_session_dirs(daemon.cfg, kind, sid)
            except ValueError as e:
                self._text(400, str(e))
                return
            slug = daemon.registry.create(
                kind, sid, dirs,
                {"title": str(payload.get("title") or "")},
                cwd, str(payload.get("slug") or ""),
            )
            paths.write_marker(paths.base_of(dirs), sid, kind, cwd)
            # supersede replaces the per-skill class attribute the five
            # servers each set: annotate ends its older sessions for the same
            # Claude session, deck does not.
            if payload.get("supersede"):
                self._supersede_siblings(kind, cwd, sid)
            daemon.registry.persist()
            self._json(201, {
                "sid": sid, "slug": slug, "kind": kind,
                "url": f"{daemon.url}/s/{sid}/",
                "token": daemon.cfg.token,
            })
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_server_sessions.py -q`
Expected: 17 passed

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/server.py tests/conftest.py tests/test_server_sessions.py
git commit -m "feat: daemon with health, session lifecycle and kind-filtered discovery"
```

---

### Task 11: HTTP server — items, assets, uploads, open in editor

**Files:**
- Modify: `src/webcompanion/server.py`
- Test: `tests/test_server_items.py`, `tests/test_server_assets.py`

**Interfaces:**
- Consumes: `items`, `anchors`, `uploads`, `gate`.
- Produces: routes

      PUT    /s/<sid>/items/<anchor>
      PATCH  /s/<sid>/items              {items: {...}, replace?: bool}
      GET    /s/<sid>/items
      GET    /s/<sid>/items/<anchor>
      DELETE /s/<sid>/items/<anchor>
      POST   /s/<sid>/api/assets         {static_root}
      GET    /s/<sid>/assets/<path>
      POST   /s/<sid>/api/upload
      POST   /s/<sid>/api/submit
      GET    /s/<sid>/poll
      POST   /api/open                   {file, line}

- [ ] **Step 1: Write the failing test**

`tests/test_server_items.py`:

```python
from __future__ import annotations


def _session(call, kind="annotate", cwd="/p"):
    return call("POST", "/api/sessions", {"kind": kind, "cwd": cwd, "title": "T"})[1]


def test_put_then_get_one_item(call):
    s = _session(call)
    assert call("PUT", f"/s/{s['sid']}/items/b-1", {"text": "hello"})[0] == 200
    status, body = call("GET", f"/s/{s['sid']}/items/b-1")
    assert status == 200
    assert body["body"] == {"text": "hello"}
    assert body["version"] == 1


def test_patch_upserts_many_in_one_request(call):
    s = _session(call)
    call("PATCH", f"/s/{s['sid']}/items",
         {"items": {"b-1": {"t": "a"}, "b-2": {"t": "b"}}})
    _, all_items = call("GET", f"/s/{s['sid']}/items")
    assert set(all_items) == {"b-1", "b-2"}


def test_patch_with_replace_deletes_absent_anchors(call):
    s = _session(call)
    call("PATCH", f"/s/{s['sid']}/items", {"items": {"b-1": {}, "b-2": {}}})
    call("PATCH", f"/s/{s['sid']}/items", {"items": {"b-1": {}}, "replace": True})
    _, all_items = call("GET", f"/s/{s['sid']}/items")
    assert set(all_items) == {"b-1"}


def test_rewriting_one_item_bumps_only_its_version(call):
    s = _session(call)
    call("PATCH", f"/s/{s['sid']}/items", {"items": {"b-1": {"t": "a"}, "b-2": {"t": "b"}}})
    call("GET", f"/s/{s['sid']}/items")
    call("PUT", f"/s/{s['sid']}/items/b-2", {"t": "CHANGED"})
    _, all_items = call("GET", f"/s/{s['sid']}/items")
    assert all_items["b-1"]["version"] == 1
    assert all_items["b-2"]["version"] == 2


def test_delete_removes_an_item(call):
    s = _session(call)
    call("PUT", f"/s/{s['sid']}/items/b-1", {"t": "a"})
    assert call("DELETE", f"/s/{s['sid']}/items/b-1")[0] == 200
    assert call("GET", f"/s/{s['sid']}/items/b-1")[0] == 404


def test_an_item_declaring_a_code_anchor_gets_it_resolved_on_read(tmp_path, call):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("one\ntwo\nthree\n")
    s = _session(call, cwd=str(repo))
    call("PUT", f"/s/{s['sid']}/items/b-1",
         {"text": "see this", "code": [{"file": "src/a.py", "line": 2, "snippet": "two"}]})
    _, body = call("GET", f"/s/{s['sid']}/items/b-1")
    assert body["code"][0]["status"] == "ok"
    assert any(l["text"] == "two" for l in body["code"][0]["lines"])


def test_editing_the_file_changes_the_next_read(tmp_path, call):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("one\ntwo\nthree\n")
    s = _session(call, cwd=str(repo))
    call("PUT", f"/s/{s['sid']}/items/b-1",
         {"code": [{"file": "src/a.py", "line": 2, "snippet": "two"}]})
    first = call("GET", f"/s/{s['sid']}/items/b-1")[1]["code"][0]
    (repo / "src" / "a.py").write_text("one\nTWO EDITED\nthree\n")
    second = call("GET", f"/s/{s['sid']}/items/b-1")[1]["code"][0]
    assert first["lines"] != second["lines"]


def test_an_anchor_outside_the_session_cwd_is_refused(tmp_path, call):
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "secret.txt").write_text("password")
    s = _session(call, cwd=str(repo))
    call("PUT", f"/s/{s['sid']}/items/b-1",
         {"code": [{"file": "../secret.txt", "line": 1, "snippet": "password"}]})
    _, body = call("GET", f"/s/{s['sid']}/items/b-1")
    assert body["code"][0]["status"] == "error"


def test_submit_queues_an_event_and_returns_its_id(call):
    s = _session(call)
    call("PUT", f"/s/{s['sid']}/items/b-1", {"t": "a"})
    status, body = call("POST", f"/s/{s['sid']}/api/submit",
                        {"anchor": "b-1", "text": "please change this"})
    assert status == 202
    assert body["event_id"]


def test_submit_on_an_unknown_anchor_is_a_400(call):
    s = _session(call)
    assert call("POST", f"/s/{s['sid']}/api/submit",
                {"anchor": "../escape", "text": "x"})[0] == 400


def test_poll_reports_item_and_thread_versions(call):
    s = _session(call)
    call("PUT", f"/s/{s['sid']}/items/b-1", {"t": "a"})
    _, poll = call("GET", f"/s/{s['sid']}/poll")
    assert poll["items"]["b-1"] == 1
    assert "threads" in poll
    assert "watcher_seen_at" in poll


def test_open_in_editor_refuses_a_path_outside_every_session(tmp_path, call):
    repo = tmp_path / "repo"
    repo.mkdir()
    _session(call, cwd=str(repo))
    status, _ = call("POST", "/api/open",
                     {"file": str(tmp_path / "elsewhere.txt"), "line": 1})
    assert status == 403
```

`tests/test_server_assets.py`:

```python
from __future__ import annotations


def test_the_runtime_is_served_by_the_daemon(call):
    status, body = call("GET", "/_wc/core.js")
    assert status == 200
    assert "WebCompanion" in body


def test_a_client_registers_its_own_renderer_and_it_is_served(tmp_path, call):
    bundle = tmp_path / "bundle"
    (bundle / "sub").mkdir(parents=True)
    (bundle / "app.js").write_text("console.log('renderer')")
    (bundle / "sub" / "style.css").write_text("body{}")
    s = call("POST", "/api/sessions",
             {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    assert call("POST", f"/s/{s['sid']}/api/assets",
                {"static_root": str(bundle)})[0] == 200
    assert call("GET", f"/s/{s['sid']}/assets/app.js")[1] == "console.log('renderer')"
    assert call("GET", f"/s/{s['sid']}/assets/sub/style.css")[0] == 200


def test_assets_cannot_escape_the_registered_root(tmp_path, call):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (tmp_path / "secret.txt").write_text("password")
    s = call("POST", "/api/sessions",
             {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    call("POST", f"/s/{s['sid']}/api/assets", {"static_root": str(bundle)})
    assert call("GET", f"/s/{s['sid']}/assets/../secret.txt")[0] in (403, 404)


def test_the_shell_page_loads_the_runtime_and_the_registered_entry(tmp_path, call):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "app.js").write_text("//")
    s = call("POST", "/api/sessions",
             {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    call("POST", f"/s/{s['sid']}/api/assets",
         {"static_root": str(bundle), "entry": "app.js"})
    _, html = call("GET", f"/s/{s['sid']}/")
    assert "/_wc/core.js" in html
    assert "assets/app.js" in html


def test_a_session_with_no_registered_renderer_still_serves_a_shell(call):
    s = call("POST", "/api/sessions",
             {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    status, html = call("GET", f"/s/{s['sid']}/")
    assert status == 200
    assert "/_wc/core.js" in html
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python3 -m pytest tests/test_server_items.py tests/test_server_assets.py -q`
Expected: FAIL — the item and asset routes 404

- [ ] **Step 3: Add the item routes**

In `server.py`, the read path is where code anchors resolve. Note the two things it must do and the one it must not:

```python
        def _get_item(self, sid: str, dirs: dict, anchor: str) -> None:
            body = items.load_one(dirs["items_dir"], anchor)
            if body is None:
                self._text(404, "no such item")
                return
            versions = items.versions_of(dirs["items_dir"])
            out = {"body": body, "version": versions.get(anchor, 1)}
            # Resolved HERE, not at push time. The client edits its repository
            # while the session is open; an anchor captured at push is wrong
            # within a turn.
            resolved = anchors.resolve_all(body, Path(dirs["_cwd"]))
            if resolved:
                out["code"] = resolved
            self._json(200, out)
```

Writes go through the gate and then bump the session's change counter, which is what wakes the SSE loop in Task 12:

```python
        def _put_item(self, sid: str, dirs: dict, anchor: str) -> None:
            if not self._require_owner():
                return
            try:
                items.put(dirs["items_dir"], anchor, self._body())
            except ValueError as e:
                self._text(400, str(e))
                return
            daemon.registry.note_change(sid)
            self._json(200, {"ok": True})
```

- [ ] **Step 4: Add the asset routes**

`POST /s/<sid>/api/assets` records `{static_root, entry}` in the session meta after resolving `static_root` and confirming it is a directory. `GET /s/<sid>/assets/<path>` resolves the join and requires `is_relative_to` the registered root — a 403 otherwise, never a traversal. `GET /_wc/core.js` reads the package's own static through `importlib.resources.as_file`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_server_items.py tests/test_server_assets.py -q`
Expected: 17 passed

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/server.py tests/test_server_items.py tests/test_server_assets.py
git commit -m "feat: item, asset, upload and open-in-editor routes"
```

---

### Task 12: SSE stream with two generic frames and a connection cap

**Files:**
- Create: `src/webcompanion/stream.py`
- Modify: `src/webcompanion/server.py` (add `GET /s/<sid>/stream`)
- Test: `tests/test_stream.py`

**Interfaces:**
- Consumes: `registry.wait_for_change`, `items.versions_of`, `threads.list_versions`.
- Produces: `serve(handler, sid, dirs, registry, is_terminal) -> None`; `MAX_CONCURRENT_STREAMS = 200`; `open_stream_count() -> int`.

The frames are exactly: `connected`, `item-changed {anchor, version}`, `document-changed {version}`, `thread-changed {anchor, ...}`, `thread-deleted {anchor}`, `heartbeat`, `session-ended`. There is no `extra` hook. The old one took **a Python callable** so each skill could add its own frames on the shared loop — `steps-changed`, `flow-changed` — which a standalone daemon cannot call. Every one of those frames was really "X changed to version N", so they collapse into the two generic ones.

The connection cap is new and necessary: every browser tab and IDE client parks a thread for the life of its connection. That load used to be spread over five processes that each shut down when idle; it is now one process that never restarts.

- [ ] **Step 1: Write the failing test**

`tests/test_stream.py`:

```python
from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from webcompanion import stream


def _read_frames(url, count, timeout=5):
    """Read `count` SSE frames as (event, data) pairs."""
    frames, name = [], None
    with urllib.request.urlopen(url, timeout=timeout) as r:
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: ") and name:
                frames.append((name, json.loads(line[6:])))
                name = None
                if len(frames) >= count:
                    return frames
    return frames


def test_the_stream_opens_with_a_connected_frame(daemon, call):
    s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    frames = _read_frames(f"{daemon.url}/s/{s['sid']}/stream", 1)
    assert frames[0][0] == "connected"


def test_an_item_write_emits_item_changed_with_the_new_version(daemon, call):
    s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    call("PUT", f"/s/{s['sid']}/items/b-1", {"t": "a"})
    got = []
    t = threading.Thread(
        target=lambda: got.extend(_read_frames(f"{daemon.url}/s/{s['sid']}/stream", 3)))
    t.start()
    import time
    time.sleep(0.3)
    call("PUT", f"/s/{s['sid']}/items/b-1", {"t": "CHANGED"})
    t.join(timeout=5)
    changed = [f for f in got if f[0] == "item-changed"]
    assert changed, f"expected item-changed, got {[f[0] for f in got]}"
    assert changed[-1][1] == {"anchor": "b-1", "version": 2}


def test_there_is_no_skill_specific_frame_hook():
    import inspect
    src = inspect.getsource(stream)
    assert "extra" not in src, (
        "the old extra= hook took a Python callable so each skill could add "
        "its own frames; a standalone daemon cannot call into client code")


def test_only_the_documented_frames_are_emitted():
    import inspect
    src = inspect.getsource(stream)
    emitted = set(__import__("re").findall(r'emit\("([a-z-]+)"', src))
    assert emitted <= {"connected", "item-changed", "document-changed",
                       "thread-changed", "thread-deleted", "heartbeat",
                       "session-ended"}


def test_a_finished_session_ends_the_stream(daemon, call):
    s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    call("POST", f"/s/{s['sid']}/api/finish")
    frames = _read_frames(f"{daemon.url}/s/{s['sid']}/stream", 2)
    assert any(f[0] == "session-ended" for f in frames)


def test_the_stream_count_returns_to_zero_after_a_client_disconnects(daemon, call):
    s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    _read_frames(f"{daemon.url}/s/{s['sid']}/stream", 1)
    import time
    for _ in range(50):
        if stream.open_stream_count() == 0:
            break
        time.sleep(0.1)
    assert stream.open_stream_count() == 0


def test_the_cap_refuses_a_stream_rather_than_exhausting_threads(daemon, call, monkeypatch):
    monkeypatch.setattr(stream, "MAX_CONCURRENT_STREAMS", 0)
    s = call("POST", "/api/sessions", {"kind": "annotate", "cwd": "/p", "title": "T"})[1]
    assert call("GET", f"/s/{s['sid']}/stream")[0] == 503
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_stream.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.stream'`

- [ ] **Step 3: Write the implementation**

`src/webcompanion/stream.py`:

```python
"""The per-session SSE loop.

Two things differ from the version this replaces. There is no `extra` hook:
it took a Python callable so each skill could emit its own frames on the
shared loop, which a standalone daemon has no way to call. Every frame it
carried — walkthrough's steps-changed, dataflow's flow-changed — was really
"this changed to version N", so they collapse into item-changed and
document-changed.

And streams are counted and capped. Every connected browser tab and IDE
client parks a thread here for the life of the connection. That load used to
be spread over five processes that each shut down when idle; it is now one
process that never restarts, holding sessions from every project on the
machine.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

MAX_CONCURRENT_STREAMS = 200
HEARTBEAT_SECONDS = 30

_open = 0
_open_lock = threading.Lock()


def open_stream_count() -> int:
    with _open_lock:
        return _open


class _Slot:
    """Reserve a stream slot, or refuse. Released on exit either way."""

    def __init__(self):
        self.acquired = False

    def __enter__(self):
        global _open
        with _open_lock:
            if _open >= MAX_CONCURRENT_STREAMS:
                return self
            _open += 1
            self.acquired = True
        return self

    def __exit__(self, *exc):
        global _open
        if self.acquired:
            with _open_lock:
                _open -= 1
        return False


def serve(handler, sid: str, dirs: dict, *, registry, is_terminal) -> None:
    from webcompanion import items as items_mod
    from webcompanion import threads as threads_mod

    with _Slot() as slot:
        if not slot.acquired:
            body = b"too many open streams"
            handler.send_response(503)
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return

        state_dir = Path(dirs["state_dir"])
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

        def emit(name: str, obj: dict) -> bool:
            try:
                handler.wfile.write(f"event: {name}\ndata: {json.dumps(obj)}\n\n".encode())
                handler.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

        if not emit("connected", {}):
            return

        last_items = items_mod.versions_of(dirs["items_dir"])
        last_threads = threads_mod.list_versions(dirs["threads_dir"])
        for anchor, version in last_items.items():
            if not emit("item-changed", {"anchor": anchor, "version": version}):
                return
        for anchor, info in last_threads.items():
            if not emit("thread-changed", {"anchor": anchor, "version": info}):
                return

        # Compared against a VALUE, not an edge. A change landing between the
        # snapshot above and the wait below is not lost.
        seen = registry.version(sid)
        while True:
            now = registry.wait_for_change(sid, since=seen, timeout=HEARTBEAT_SECONDS)
            woke = now > seen
            seen = now

            if is_terminal(state_dir):
                # Otherwise this loop re-reads every file every 30s per
                # connected client, forever.
                emit("session-ended", {})
                return

            new_items = items_mod.versions_of(dirs["items_dir"])
            new_threads = threads_mod.list_versions(dirs["threads_dir"])

            for anchor in set(last_items) - set(new_items):
                if not emit("item-changed", {"anchor": anchor, "version": 0}):
                    return
            for anchor, version in new_items.items():
                if last_items.get(anchor) != version:
                    if not emit("item-changed", {"anchor": anchor, "version": version}):
                        return
            for anchor in set(last_threads) - set(new_threads):
                if not emit("thread-deleted", {"anchor": anchor}):
                    return
            for anchor, version in new_threads.items():
                if last_threads.get(anchor) != version:
                    if not emit("thread-changed", {"anchor": anchor, "version": version}):
                        return

            last_items, last_threads = new_items, new_threads
            if not woke and not emit("heartbeat", {}):
                return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_stream.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/stream.py src/webcompanion/server.py tests/test_stream.py
git commit -m "feat: SSE stream with generic frames and a connection cap"
```

---

### Task 13: The browser runtime and the shell page

**Files:**
- Create: `src/webcompanion/static/core.js`, `src/webcompanion/static/shell.html`
- Test: `tests/test_static_assets.py`

**Interfaces:**
- Consumes: the routes from Tasks 10–12.
- Produces: `window.WebCompanion` with `{api, writable, resolveWritable, init({onDelta})}`, plus the selection and composer behaviour the five clients no longer each implement.

The runtime owns *select → comment → submit → refetch* and **renders nothing**. A client marks commentable regions with `data-wc-anchor="<anchor>"`; the runtime binds selection and the composer to them and, on `item-changed`, calls the client's `onDelta` with the anchor and version. What replaces the element's contents is the client's decision, because the daemon does not know whether the body is markdown, a slide, or a graph node.

Port `skills/_shared/web_companion/static/core.js` (4.7KB) and add the selection and composer layer. Do **not** port anything from `skills/annotate/static/` — that ~480KB is annotate's renderer and stays with annotate.

- [ ] **Step 1: Write the failing test**

`tests/test_static_assets.py`:

```python
from __future__ import annotations

import re
from importlib.resources import as_file, files


def _read(name: str) -> str:
    with as_file(files("webcompanion").joinpath("static", name)) as p:
        return p.read_text()


def test_the_runtime_is_packaged_and_reachable_through_importlib():
    # Path(__file__).parent survives a wheel but not the zipapp the service
    # runs from; as_file works for both.
    assert "WebCompanion" in _read("core.js")


def test_the_runtime_stays_small():
    # It is the interaction, not a renderer. annotate's 480KB bundle is a
    # renderer and belongs to annotate.
    size = len(_read("core.js").encode())
    assert size < 20_000, f"core.js is {size} bytes; a renderer has leaked in"


def test_the_runtime_renders_nothing():
    src = _read("core.js")
    for forbidden in ["markdown", "markdownit", "hljs", "highlight", "innerHTML ="]:
        assert forbidden not in src, f"{forbidden} is a rendering concern"


def test_the_runtime_sends_the_contract_header():
    assert "X-WebCompanion-Contract" in _read("core.js")


def test_the_runtime_reads_the_token_from_the_fragment_not_the_query():
    src = _read("core.js")
    assert "location.hash" in src
    assert "sessionStorage" in src


def test_the_runtime_binds_to_the_anchor_attribute():
    assert "data-wc-anchor" in _read("core.js")


def test_the_shell_loads_the_runtime_and_leaves_a_mount_point():
    html = _read("shell.html")
    assert "/_wc/core.js" in html
    assert "{{ENTRY}}" in html and "{{TITLE}}" in html


def test_the_runtime_reconnects_a_dropped_stream():
    # There is no idle shutdown any more, but a laptop sleeping still drops
    # the connection, and a page that silently stops updating is worse than
    # one that reloads.
    assert re.search(r"onerror|reconnect", _read("core.js"))
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_static_assets.py -q`
Expected: FAIL — the static files do not exist

- [ ] **Step 3: Write `core.js`**

Start from `skills/_shared/web_companion/static/core.js` verbatim — keep the token-in-fragment reasoning comment, which explains why the credential travels in the hash (browsers never send it to the server and never write it to logs or `Referer`) and why it is held in `sessionStorage` rather than `localStorage` (a borrowed device forgets it when the tab closes). Then:

1. Add the contract header to every request:

```js
  const CONTRACT = 1;
  const CONTRACT_HEADER = "X-WebCompanion-Contract";

  function headers(extra) {
    const h = Object.assign({ [CONTRACT_HEADER]: String(CONTRACT) }, extra || {});
    if (token) h[TOKEN_HEADER] = token;
    return h;
  }
```

2. Replace the 1-second polling loop with an `EventSource` on `stream`, keeping `poll` as the fallback when `EventSource` errors twice in a row.

3. Add the selection and composer layer, which is the part the five clients stop each implementing:

```js
  // A client marks its commentable regions; the runtime owns what happens
  // when one is clicked. It never decides what the region CONTAINS — on
  // item-changed it hands the anchor back and the client re-renders.
  function bindSelection(root) {
    (root || document).addEventListener("click", (ev) => {
      const el = ev.target.closest("[data-wc-anchor]");
      if (!el || !writable) return;
      openComposer(el.getAttribute("data-wc-anchor"), el);
    });
  }
```

4. Expose `init({ onDelta })` where `onDelta({anchor, version})` fires per `item-changed`.

- [ ] **Step 4: Write `shell.html`**

A minimal document with `{{TITLE}}` and `{{ENTRY}}` placeholders, `/_wc/core.js` loaded before the entry, and a `<main data-wc-root>` mount point. No styling beyond what the composer needs — the client's stylesheet arrives through its registered assets.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_static_assets.py tests/test_server_assets.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/static tests/test_static_assets.py
git commit -m "feat: browser runtime and shell page"
```

---

### Task 14: Retention, stray sweep and startup self-heal

**Files:**
- Create: `src/webcompanion/cleanup.py`
- Modify: `src/webcompanion/server.py` (call the sweep once at startup)
- Test: `tests/test_cleanup.py`

**Interfaces:**
- Consumes: `registry.Registry`, `paths`, `config.Config`.
- Produces: `sweep(cfg, registry) -> dict[str, int]`; `expire(cfg, registry) -> int`; `sweep_strays(cfg, kind) -> int`; `prune_dead_rows(registry) -> int`.

Two rules the merged root changes:

- `sweep_strays` removes any sid-shaped directory no registry row points at. It now runs **per kind**, inside `<workspace_root>/<kind>/` only. Given one shared root and no kind namespacing, a registry bug in one client could delete another client's workspaces; scoping the sweep is what makes that impossible rather than unlikely.
- Retention comes from `cfg.retention_days`, defaulting to `None` — infinite. Users have workspaces going back to install day and `resume <slug>` is a shipped feature, so the daemon must not start deleting them because the configuration moved.

- [ ] **Step 1: Write the failing test**

`tests/test_cleanup.py`:

```python
from __future__ import annotations

import time

from webcompanion import cleanup, paths
from webcompanion.config import Config
from webcompanion.registry import Registry


def _session(reg, cfg, kind, sid):
    dirs = paths.make_session_dirs(cfg, kind, sid)
    reg.create(kind, sid, dirs, {"title": sid}, "/p")
    return dirs


def test_retention_defaults_to_infinite(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    dirs = _session(reg, cfg, "annotate", "old-one")
    ancient = time.time() - 86400 * 3650
    import os
    os.utime(paths.base_of(dirs), (ancient, ancient))
    assert cleanup.expire(cfg, reg) == 0
    assert paths.base_of(dirs).is_dir()


def test_retention_when_configured_removes_only_the_expired(tmp_path):
    import os
    cfg = Config(workspace_root=tmp_path / "ws", retention_days=30)
    reg = Registry(tmp_path / "state")
    old = _session(reg, cfg, "annotate", "old-one")
    new = _session(reg, cfg, "annotate", "new-one")
    ancient = time.time() - 86400 * 400
    os.utime(paths.base_of(old), (ancient, ancient))
    assert cleanup.expire(cfg, reg) == 1
    assert not paths.base_of(old).exists()
    assert paths.base_of(new).is_dir()


def test_the_stray_sweep_cannot_reach_another_kind(tmp_path):
    # One shared root means a registry bug in one client must not be able to
    # delete another client's workspaces.
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    kept = _session(reg, cfg, "deck", "deck-session")
    stray = paths.kind_root(cfg, "annotate") / "251231-000000-deadbeefdeadbeef"
    stray.mkdir(parents=True)
    assert cleanup.sweep_strays(cfg, "annotate") == 1
    assert not stray.exists()
    assert paths.base_of(kept).is_dir()


def test_the_stray_sweep_ignores_directories_that_are_not_sid_shaped(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    (paths.kind_root(cfg, "annotate") / "not-a-session").mkdir(parents=True)
    assert cleanup.sweep_strays(cfg, "annotate") == 0


def test_a_registered_workspace_is_never_a_stray(tmp_path):
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    dirs = _session(reg, cfg, "annotate", "251231-000000-abcdefabcdefabcd")
    reg.persist()
    cleanup.sweep(cfg, reg)
    assert paths.base_of(dirs).is_dir()


def test_rows_whose_directories_vanished_are_pruned(tmp_path):
    import shutil
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    dirs = _session(reg, cfg, "annotate", "doomed")
    sid = "doomed"
    shutil.rmtree(paths.base_of(dirs))
    assert cleanup.prune_dead_rows(reg) == 1
    assert reg.lookup(sid) is None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_cleanup.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.cleanup'`

- [ ] **Step 3: Write the implementation, then wire the startup sweep**

Port the structure of `skills/_shared/web_companion/cleanup.py`, scoping `sweep_strays` to one kind and reading retention from `cfg`. In `Daemon.start()`, call `cleanup.sweep(self.cfg, self.registry)` **after** `rehydrate` and before serving, then `self.registry.persist()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_cleanup.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/webcompanion/cleanup.py src/webcompanion/server.py tests/test_cleanup.py
git commit -m "feat: retention and a kind-scoped stray sweep"
```

---

### Task 15: Client CLI — push, update, end, watch

**Files:**
- Create: `src/webcompanion/commands/__init__.py`, `push.py`, `update.py`, `end.py`, `watch.py`, `src/webcompanion/client.py`
- Test: `tests/test_cli_client.py`

**Interfaces:**
- Consumes: `config.load`, the HTTP contract.
- Produces: `client.Client(base_url, token)` with `.create(kind, cwd, title, slug, supersede) -> dict`, `.put_items(sid, bodies, replace) -> None`, `.put_item(sid, anchor, body) -> None`, `.register_assets(sid, static_root, entry) -> None`, `.finish(sid)`, `.cancel(sid)`, `.health() -> dict`, `.events(sid)`; each command module exposes `run(argv: list[str]) -> int`.

The CLI is the only seam clients use. They never build JSON in bash and never learn a route, which is the whole reason the contract lives in one project. Two behaviours matter more than the argument shapes:

- **The daemon is never started.** Every command health-checks and, on failure, prints one of the three diagnostic messages and exits non-zero.
- **Limits that used to live server-side are enforced here.** `interactive_review` rejected a diff over 5MB inside `/api/sessions`; that check moved client-side with the `gh` call, so `push` enforces it or it evaporates.

- [ ] **Step 1: Write the failing test**

`tests/test_cli_client.py`:

```python
from __future__ import annotations

import json

import pytest

from webcompanion.commands import end, push, update


# NOTE: `wired` lives in tests/conftest.py, not here — Task 16's doctor tests
# need it too. Add it to conftest.py in this task:
#
#     @pytest.fixture
#     def wired(daemon, tmp_path, monkeypatch):
#         """Point the CLI at the test daemon, not the real config file."""
#         from webcompanion import config as cfgmod
#         p = tmp_path / "config.json"
#         cfgmod.write(cfgmod.Config(port=int(daemon.url.rsplit(":", 1)[1]),
#                                    token=daemon.cfg.token), p)
#         monkeypatch.setattr(cfgmod, "config_path", lambda: p)
#         return daemon


def test_push_creates_a_session_and_prints_the_url(wired, tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {"b-1": {"text": "hello"}}}))
    rc = push.run(["--kind", "annotate", "--cwd", str(tmp_path),
                   "--title", "My Plan", "--items", str(doc)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "/s/" in out


def test_push_prints_shell_evaluable_output(wired, tmp_path, capsys):
    # The reference docs used to parse curl output with hand-rolled
    # `python3 -c 'import json...'` one-liners. This is what removes them.
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {}}))
    push.run(["--kind", "annotate", "--cwd", str(tmp_path), "--title", "T",
              "--items", str(doc), "--eval"])
    out = capsys.readouterr().out
    assert "WC_SID=" in out and "WC_URL=" in out and "WC_SLUG=" in out


def test_update_replaces_one_item(wired, tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {"b-1": {"text": "before"}}}))
    push.run(["--kind", "annotate", "--cwd", str(tmp_path), "--title", "T",
              "--items", str(doc), "--eval"])
    sid = [l for l in capsys.readouterr().out.splitlines() if l.startswith("WC_SID=")][0][7:]
    body = tmp_path / "one.json"
    body.write_text(json.dumps({"text": "after"}))
    assert update.run(["--sid", sid, "--anchor", "b-1", "--body", str(body)]) == 0


def test_end_finishes_the_session(wired, tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {}}))
    push.run(["--kind", "annotate", "--cwd", str(tmp_path), "--title", "T",
              "--items", str(doc), "--eval"])
    sid = [l for l in capsys.readouterr().out.splitlines() if l.startswith("WC_SID=")][0][7:]
    assert end.run(["--sid", sid]) == 0


def test_a_payload_over_the_limit_is_refused_before_it_is_sent(wired, tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {"b-1": {"t": "x" * (6 * 1024 * 1024)}}}))
    rc = push.run(["--kind", "annotate", "--cwd", str(tmp_path), "--title", "T",
                   "--items", str(doc)])
    assert rc != 0
    assert "too large" in capsys.readouterr().err


def test_a_missing_daemon_prints_the_install_command_and_never_starts_one(
        tmp_path, monkeypatch, capsys):
    from webcompanion import config as cfgmod
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "config_path", lambda: p)
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {}}))
    rc = push.run(["--kind", "annotate", "--cwd", str(tmp_path), "--title", "T",
                   "--items", str(doc)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "webcompanion install-service" in err


def test_a_contract_mismatch_names_which_side_is_old(wired, tmp_path, monkeypatch, capsys):
    import webcompanion.client as clientmod
    monkeypatch.setattr(clientmod, "CONTRACT", 99)
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {}}))
    rc = push.run(["--kind", "annotate", "--cwd", str(tmp_path), "--title", "T",
                   "--items", str(doc)])
    assert rc != 0
    assert "daemon" in capsys.readouterr().err
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_cli_client.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.commands'`

- [ ] **Step 3: Write `client.py`, then the four commands**

`client.py` wraps `urllib.request`, sends `X-WebCompanion-Contract` and the token on every call, and raises `DaemonUnreachable`, `ContractMismatch` or `HttpError`. `commands/_common.py` turns those into the three diagnostic messages on stderr:

```python
def report(exc) -> int:
    """One message per distinguishable failure. Requirements are the user's to
    install; ours to state clearly. Never install anything."""
    if isinstance(exc, DaemonUnreachable) and not config_path().exists():
        print("webcompanion: the companion service is not installed.\n"
              "\n"
              "  pipx install webcompanion && webcompanion install-service\n",
              file=sys.stderr)
    elif isinstance(exc, DaemonUnreachable):
        print(f"webcompanion: the service is installed but not answering on "
              f"{exc.url}.\n"
              f"\n"
              f"  webcompanion status\n"
              f"  launchctl kickstart -k gui/$UID/dev.webcompanion   # macOS\n"
              f"  systemctl --user restart webcompanion              # Linux\n"
              f"\n"
              f"Log: {exc.log_path}\n", file=sys.stderr)
    elif isinstance(exc, ContractMismatch):
        print(f"webcompanion: {exc}\n", file=sys.stderr)
    else:
        print(f"webcompanion: {exc}\n", file=sys.stderr)
    return 1
```

`watch.py` is the successor to `watcher.sh`. It keeps that script's behaviour exactly, because each part of it was earned: heartbeats written by atomic rename (a truncate-then-fill wrote an empty file ~0.6% of reads, which `poll` read as a dead session and the IDE latched read-only on a live one); the ack wait that keeps beating while blocked; re-emission on ack timeout bounded to three attempts so one unanswered event cannot wedge the serially-processed queue; and `WEBCOMPANION_DROPPED` printed loudly when it gives up, so the user is told rather than watching a spinner vanish.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_cli_client.py -q`
Expected: 7 passed

- [ ] **Step 5: Port the watcher's own tests**

`skills/_shared/web_companion/tests/test_watcher.sh` and `test_watcher_heartbeat_atomic.sh` become `tests/test_watch.py`, asserting the same behaviours against `commands/watch.py`: one banner per event, the ack wait, three re-emissions then `WEBCOMPANION_DROPPED`, `WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED` on the terminal markers, and a heartbeat that is never observed empty.

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/client.py src/webcompanion/commands tests/test_cli_client.py tests/test_watch.py
git commit -m "feat: client CLI for push, update, end and watch"
```

---

### Task 16: serve, install-service, zipapp, status and doctor

**Files:**
- Create: `src/webcompanion/commands/serve.py`, `install_service.py`, `status.py`, `doctor.py`
- Create: `src/webcompanion/service/dev.webcompanion.plist`, `src/webcompanion/service/webcompanion.service`
- Test: `tests/test_install_service.py`, `tests/test_doctor.py`

**Interfaces:**
- Consumes: `config`, `server.Daemon`.
- Produces: `install_service.run(argv) -> int`; `install_service.render_plist(...) -> str`; `install_service.render_unit(...) -> str`; `install_service.build_zipapp(dest: Path) -> Path`; `status.run(argv) -> int`; `doctor.run(argv) -> int`.

The service runs the package as a **zipapp**, not from a virtualenv. A pipx venv is bound to the interpreter that created it; when Homebrew retires that Python the venv's interpreter dangles, the entry point fails to exec, and launchd respawn-loops the job forever at the default 10s throttle — `launchctl list` shows the job, every client sees connection refused, and nothing says why. The package is stdlib-only, so there is no reason to accept that failure mode.

`install-service` therefore: builds `~/.local/share/webcompanion/webcompanion.pyz` with `zipapp`, writes the config (minting the token only if absent — an existing token must survive), writes the plist or unit with `ThrottleInterval` and `StandardErrorPath` set, loads it, and **restarts the service as its final step** so an upgrade takes effect immediately.

- [ ] **Step 1: Write the failing test**

`tests/test_install_service.py`:

```python
from __future__ import annotations

import plistlib
import zipfile

from webcompanion import config as cfgmod
from webcompanion.commands import install_service as svc


def test_the_plist_runs_a_zipapp_with_the_system_python(tmp_path):
    xml = svc.render_plist(pyz=tmp_path / "webcompanion.pyz",
                           log_dir=tmp_path, label="dev.webcompanion")
    plist = plistlib.loads(xml.encode())
    args = plist["ProgramArguments"]
    assert args[0] == "/usr/bin/env"
    assert args[1] == "python3"
    assert args[2].endswith("webcompanion.pyz")
    assert args[3] == "serve"
    assert "site-packages" not in xml and "pipx" not in xml, (
        "a venv-bound interpreter dangles when its python is replaced")


def test_the_plist_sets_keepalive_a_throttle_and_a_log(tmp_path):
    plist = plistlib.loads(
        svc.render_plist(pyz=tmp_path / "w.pyz", log_dir=tmp_path,
                         label="dev.webcompanion").encode())
    assert plist["KeepAlive"] is True
    assert plist["ThrottleInterval"] >= 10
    assert plist["StandardErrorPath"].endswith(".log")


def test_the_systemd_unit_restarts_always(tmp_path):
    unit = svc.render_unit(pyz=tmp_path / "w.pyz")
    assert "Restart=always" in unit
    assert "RestartSec=" in unit


def test_the_zipapp_is_self_contained_and_executable(tmp_path):
    pyz = svc.build_zipapp(tmp_path / "webcompanion.pyz")
    assert pyz.is_file()
    with zipfile.ZipFile(pyz) as z:
        names = z.namelist()
    assert "__main__.py" in names
    assert any(n.endswith("webcompanion/server.py") for n in names)
    assert any(n.endswith("webcompanion/static/core.js") for n in names), (
        "static assets must be inside the zipapp; the daemon reads them "
        "through importlib.resources")


def test_install_mints_a_token_only_when_there_is_not_one(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "config_path", lambda: p)
    cfgmod.write(cfgmod.Config(port=3080, token="keep-me"), p)
    svc.ensure_config()
    assert cfgmod.load(p).token == "keep-me", (
        "reminting on every install invalidates the IDE plugin's credential")


def test_install_mints_a_token_when_there_is_none(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "config_path", lambda: p)
    svc.ensure_config()
    assert len(cfgmod.load(p).token) >= 32
```

`tests/test_doctor.py`:

```python
from __future__ import annotations

from webcompanion.commands import doctor


def test_doctor_reports_a_missing_service(tmp_path, monkeypatch, capsys):
    from webcompanion import config as cfgmod
    monkeypatch.setattr(cfgmod, "config_path", lambda: tmp_path / "absent.json")
    assert doctor.run([]) != 0
    assert "install-service" in capsys.readouterr().out


def test_doctor_detects_a_dangling_interpreter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "_service_interpreter",
                        lambda: tmp_path / "gone" / "python3")
    doctor.run([])
    out = capsys.readouterr().out
    assert "interpreter" in out.lower()


def test_doctor_detects_a_respawn_loop(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "_recent_restart_count", lambda: 40)
    doctor.run([])
    assert "restart" in capsys.readouterr().out.lower()


def test_doctor_reports_a_healthy_daemon(wired, capsys):
    assert doctor.run([]) == 0
    assert "ok" in capsys.readouterr().out.lower()


def test_doctor_names_the_port_holder_when_the_port_is_taken(monkeypatch, capsys):
    # "port 3080 held by node (pid 4821)" is the single most useful line the
    # old launcher printed, and a fixed port makes collisions more likely.
    monkeypatch.setattr(doctor, "_port_holder", lambda port: ("node", 4821))
    monkeypatch.setattr(doctor, "_health", lambda: None)
    doctor.run([])
    out = capsys.readouterr().out
    assert "node" in out and "4821" in out
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python3 -m pytest tests/test_install_service.py tests/test_doctor.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the service templates and commands**

`serve.py` loads the config, builds a `Daemon`, writes a pidfile, and runs until signalled. Before binding it performs a **startup self-check**: if the port is already held, it reports the holder and exits non-zero rather than binding with `SO_REUSEADDR` alongside a stale process — two processes on one port split requests at random, and a supervisor that restarts on crash makes that reachable.

`install_service.py` implements `build_zipapp` via `zipapp.create_archive` over a staged copy of the package, `render_plist`/`render_unit` from the templates, `ensure_config`, and the load-and-restart sequence.

`status.py` prints the service state, the configured port, the health response, and the number of live sessions. `doctor.py` succeeds `annotate-doctor`: python3 and its version, the config file and its mode, the zipapp's presence, the interpreter the service actually references, the port holder, the restart count, and the health response.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_install_service.py tests/test_doctor.py -q`
Expected: 11 passed

- [ ] **Step 5: Install it on this machine and verify end to end**

```bash
pipx install -e ~/projects/webcompanion
webcompanion install-service
webcompanion status
curl -s localhost:3080/health
```

Expected: `status` reports the service running; `/health` returns the banner, `"contract": 1`, and the installed version. Record the actual output in the commit message — a service that has never been watched starting is not a working service.

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/commands src/webcompanion/service tests/
git commit -m "feat: serve, install-service, zipapp packaging, status and doctor"
```

---

### Task 17: Migration from the five per-skill roots

**Files:**
- Create: `src/webcompanion/commands/migrate.py`
- Test: `tests/test_migrate.py`

**Interfaces:**
- Consumes: `paths`, `registry.Registry`, `client.Client`.
- Produces: `migrate.run(argv) -> int`; `plan(old_roots: list[Path]) -> list[dict]`; `apply(plan, cfg, registry) -> dict[str, int]`.

Existing workspaces are migrated, not discarded. Retention defaults to infinite and `resume <slug>` is shipped, so users have workspaces going back to install day; discarding them is choosing to break a feature to save a day's work. `cleanup.migrate_workspaces()` in the old tree already moves trees and re-roots `sessions.json` — it was written for exactly this shape of move, and `_reroot` is the part to reuse.

The one genuinely new piece: v1 changed the content channel, so a migrated workspace's `blocks.json` must be read once and written as items. Where that is not possible, the session is marked read-only rather than silently emptied.

- [ ] **Step 1: Write the failing test**

`tests/test_migrate.py`:

```python
from __future__ import annotations

import json

from webcompanion import items, paths
from webcompanion.commands import migrate
from webcompanion.config import Config
from webcompanion.registry import Registry


def _old_workspace(root, skill, sid, slug, blocks):
    ws = root / skill / "workspaces" / sid
    (ws / "response").mkdir(parents=True)
    (ws / "state").mkdir(parents=True)
    (ws / "response" / "blocks.json").write_text(json.dumps({"blocks": blocks}))
    (root / skill).mkdir(parents=True, exist_ok=True)
    (root / skill / "sessions.json").write_text(json.dumps({
        sid: {"response_dir": str(ws / "response"), "state_dir": str(ws / "state"),
              "_cwd": "/proj", "_sid": sid}}))
    (root / skill / "sessions_meta.json").write_text(json.dumps({
        sid: {"slug": slug, "title": slug}}))
    return ws


def test_a_workspace_moves_under_its_kind(tmp_path):
    old = tmp_path / "old"
    _old_workspace(old, "annotate", "s1", "my-plan", [{"id": "b-1", "markdown": "hi"}])
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    result = migrate.apply(migrate.plan([old / "annotate"]), cfg, reg)
    assert result["moved"] == 1
    assert (paths.kind_root(cfg, "annotate") / "s1").is_dir()


def test_blocks_become_items(tmp_path):
    old = tmp_path / "old"
    _old_workspace(old, "annotate", "s1", "my-plan",
                   [{"id": "b-1", "markdown": "hello"},
                    {"id": "b-2", "markdown": "world"}])
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    migrate.apply(migrate.plan([old / "annotate"]), cfg, reg)
    dirs = reg.lookup("s1")
    stored = items.load_all(dirs["items_dir"])
    assert set(stored) == {"b-1", "b-2"}
    assert stored["b-1"]["markdown"] == "hello"


def test_the_slug_and_the_kind_survive(tmp_path):
    old = tmp_path / "old"
    _old_workspace(old, "deck", "s1", "my-deck", [])
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    migrate.apply(migrate.plan([old / "deck"]), cfg, reg)
    assert reg.resolve("my-deck", kind="deck") == "s1"
    assert reg.get_meta("s1")["kind"] == "deck"


def test_a_slug_shared_by_two_kinds_is_no_longer_a_collision(tmp_path):
    old = tmp_path / "old"
    _old_workspace(old, "annotate", "s1", "plan", [])
    _old_workspace(old, "deck", "s2", "plan", [])
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    migrate.apply(migrate.plan([old / "annotate", old / "deck"]), cfg, reg)
    assert reg.resolve("plan", kind="annotate") == "s1"
    assert reg.resolve("plan", kind="deck") == "s2"


def test_a_workspace_whose_content_cannot_be_read_is_marked_read_only(tmp_path):
    old = tmp_path / "old"
    ws = _old_workspace(old, "annotate", "s1", "broken", [])
    (ws / "response" / "blocks.json").write_text("{not json")
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    result = migrate.apply(migrate.plan([old / "annotate"]), cfg, reg)
    assert result["read_only"] == 1
    assert reg.get_meta("s1").get("read_only") is True


def test_migration_is_idempotent(tmp_path):
    old = tmp_path / "old"
    _old_workspace(old, "annotate", "s1", "my-plan", [{"id": "b-1", "markdown": "hi"}])
    cfg = Config(workspace_root=tmp_path / "ws")
    reg = Registry(tmp_path / "state")
    p = migrate.plan([old / "annotate"])
    migrate.apply(p, cfg, reg)
    second = migrate.apply(migrate.plan([old / "annotate"]), cfg, reg)
    assert second["moved"] == 0


def test_plan_reports_what_it_will_do_without_touching_anything(tmp_path):
    old = tmp_path / "old"
    _old_workspace(old, "annotate", "s1", "my-plan", [])
    cfg = Config(workspace_root=tmp_path / "ws")
    p = migrate.plan([old / "annotate"])
    assert p and p[0]["sid"] == "s1" and p[0]["kind"] == "annotate"
    assert not paths.kind_root(cfg, "annotate").exists()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_migrate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.commands.migrate'`

- [ ] **Step 3: Write the implementation**

`plan()` reads each old root's `sessions.json` and `sessions_meta.json` and returns one row per session with `{sid, kind, slug, cwd, old_base, new_base, content_path}` — touching nothing. `apply()` moves each tree, converts `blocks.json` to items, registers the row with its kind, writes the marker, and persists. `run()` defaults to `--dry-run` printing the plan; `--apply` performs it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_migrate.py -q`
Expected: 7 passed

- [ ] **Step 5: Run the migration against this machine's real workspaces**

```bash
webcompanion migrate --dry-run
```

Expected: a row per existing session across the five old roots. Do not `--apply` until plan 3 (the skill cutover) is ready to ship — a migrated workspace is unreachable until the skills speak the new contract.

- [ ] **Step 6: Commit**

```bash
git add src/webcompanion/commands/migrate.py tests/test_migrate.py
git commit -m "feat: migrate the five per-skill workspace roots into one"
```

---

### Task 18: README, contract documentation, and the first PyPI release

**Files:**
- Create: `README.md` (replacing the scaffold's), `CHANGELOG.md`, `docs/contract.md`
- Modify: `.github/workflows/release.yml`
- Test: `tests/test_readme_claims.py`

**Interfaces:**
- Consumes: everything.
- Produces: `webcompanion` 1.0.0 on PyPI.

- [ ] **Step 1: Write the failing test**

`tests/test_readme_claims.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

import webcompanion

README = Path(__file__).resolve().parents[1] / "README.md"


def test_the_readme_states_the_platform_limit():
    # threads.py imports fcntl. The claude-annotate README says macOS/Linux;
    # this package's own README must say it too, for anyone who finds it on
    # PyPI without that context.
    text = README.read_text()
    assert "macOS" in text and "Linux" in text
    assert "Windows" in text


def test_the_readme_states_the_dependency_promise():
    assert "standard library" in README.read_text().lower()


def test_the_readme_documents_the_three_failure_messages():
    text = README.read_text()
    assert "webcompanion install-service" in text
    assert "webcompanion status" in text
    assert "426" in text


def test_every_route_in_the_contract_doc_exists_in_the_server():
    import webcompanion.server as srv
    import inspect
    source = inspect.getsource(srv)
    doc = (Path(__file__).resolve().parents[1] / "docs" / "contract.md").read_text()
    routes = set(re.findall(r"^\s*(?:GET|PUT|POST|PATCH|DELETE)\s+(/\S+)", doc, re.M))
    assert routes, "the contract doc lists no routes"
    for route in routes:
        stem = route.split("<")[0].rstrip("/").split("?")[0]
        assert stem.strip("/").split("/")[-1] in source or stem in source, route


def test_the_contract_number_matches_the_package():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "contract.md").read_text()
    assert f"contract {webcompanion.CONTRACT}" in doc
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m pytest tests/test_readme_claims.py -q`
Expected: FAIL — `docs/contract.md` does not exist

- [ ] **Step 3: Write the documentation**

`docs/contract.md` carries the full route table from the spec's "HTTP contract, version 1" section, the compatibility rule (426 on mismatch, missing header tolerated), and the SSE frame list. This is the document the other three artifacts are written against, so it must be complete on its own — a reader implementing an IntelliJ client should not need the spec.

`README.md` covers: what it is, install (`pipx install webcompanion && webcompanion install-service`), the zipapp and why, platform support, the three failure messages, and a pointer to `docs/contract.md`.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all pass. Then verify on a clean checkout, because a dirty working tree has hidden unstaged tests before:

```bash
git stash list && git status --porcelain
git clone . /tmp/wc-verify && cd /tmp/wc-verify && pip install -e . && python3 -m pytest -q
```

- [ ] **Step 5: Publish 1.0.0**

```bash
# set version = "1.0.0" in pyproject.toml and __init__.py first
python3 -m build
python3 -m twine upload dist/*
pipx install webcompanion && webcompanion --version
```

Expected: `webcompanion 1.0.0 (contract 1)` from the PyPI-installed copy, not the local checkout.

- [ ] **Step 6: Commit and tag**

```bash
git add -A
git commit -m "docs: README, contract reference, and 1.0.0"
git tag v1.0.0 && git push --tags
```

---

## Self-Review

**Spec coverage.** Walked each spec section against the tasks:

| Spec section | Task |
|---|---|
| What the daemon owns | 4–14 |
| Code anchors as a first-class capability | 7, 11 |
| `create_session_extra` moves client-side | 15 (push enforces the 5MB limit) |
| `/api/open` stays server-side, `_cwd`-contained | 11 |
| Session lifecycle routes, mandatory `kind` | 10 |
| Item routes and derived versions | 5, 6, 11 |
| Assets and the shell page | 11, 13 |
| Interaction, events, SSE frames | 12, 13, 15 |
| Package layout, zipapp, `importlib.resources` | 1, 13, 16 |
| Configuration file, durable token, no env reads | 2, 16 |
| Version compatibility, 426, no idle shutdown | 9, 10, 16 |
| Concurrency: stream cap, waiter GC, monotonic counter | 4, 12 |
| One state root, kind namespacing, GC blast radius | 3, 4, 14 |
| Migration | 17 |
| Security at merged scale | 9, 11, 14 |
| Failure messages | 15, 16 |
| Tests | every task |

Two spec items are deliberately **not** in this plan, because they belong to later plans: the IntelliJ plugin changes (plan 2) and the `progress_publish.py` hook, whose `webcompanion progress` command lands with the skill cutover (plan 3) since nothing calls it before then.

**Placeholder scan.** No "TBD", no "add appropriate error handling", no "similar to Task N". Tasks 10, 11 and 16 show structure plus the routes whose details are easy to get wrong rather than every line — the tests define the rest, which is the point of writing them first.

**Type consistency.** Checked the names that cross task boundaries: `dirs` keys (`state_dir`, `items_dir`, `threads_dir`, `events_dir`, `consumed_dir`, `assets_dir`) are defined in Task 3 and used identically in 10–14; `Registry.create(kind, sid, dirs, meta_base, cwd, explicit_slug)` is defined in Task 4 and called with that signature in Task 10; `derive_versions(chain_path, bodies)` in Task 5 matches its call in Task 6; `resolve_all(body, root)` in Task 7 matches Task 11; `stream.serve(handler, sid, dirs, registry=, is_terminal=)` in Task 12 matches the route added to `server.py`.

One inconsistency found and fixed while reviewing: Task 4's test referenced `reg.create(kind, sid, dirs, ...)` while the interface block originally listed `create(kind, dirs, meta_base, cwd, explicit_slug)` without `sid`. The signature with `sid` is correct — the caller mints it, because `make_session_dirs` needs it before the registry sees the row. The interfaces block above carries the corrected signature.
