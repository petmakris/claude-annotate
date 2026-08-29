"""Where a workspace's files live on disk.

Two different things used to share one directory layout:

- the **registry** — ``sessions.json``, ``sessions_meta.json``, ``server.json``
  — always under ``~/.claude/<skill>/``;
- a **workspace** — one session's rendered blocks, comments, replies, version
  history and event queue — which used to be written under
  ``<cwd>/.claude/<skill>/<sid>/``, i.e. inside whatever directory the skill
  happened to be invoked from.

The second location tied a workspace's survival to a directory users treat as
disposable. Deleting a git worktree took the annotations with it, and because
the startup sweep prunes registry rows whose dirs are gone, ``/annotate resume
<slug>`` then answered 404 with nothing left to say a workspace had ever
existed — indistinguishable from a normal expiry.

Workspaces now live in one place per skill, outside every project:
``~/.claude/<skill>/workspaces/<sid>/``, beside the registry that indexes them.
``WEBCOMPANION_WORKSPACE_ROOT`` moves that base elsewhere (a synced or
backed-up volume, say).

``_cwd`` is unchanged and still means the project root — it resolves file
anchors and "open in the editor". It is deliberately no longer where content
is stored, so ``workspace.json`` records it inside the workspace instead: a
workspace that no longer sits under its project has to carry the name of the
project it belongs to, or nothing on disk knows.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from skills._shared.web_companion.atomic import write_text_atomic

WORKSPACE_ROOT_ENV = "WEBCOMPANION_WORKSPACE_ROOT"

# Written at the top of every workspace tree. Named, not dotted, because the
# directory is ours end to end and a visible file is easier to find by hand.
MARKER_FILE = "workspace.json"

# The subdirectories every skill's session tree has, as {dirs-key: relative path}.
_SUBDIRS = {
    "response_dir": ("response",),
    "annotations_dir": ("annotations",),
    "state_dir": ("state",),
    "events_dir": ("state", "events"),
    "consumed_dir": ("state", "consumed"),
}


def state_root(skill_name: str) -> Path:
    """Where the registry lives. Deliberately NOT overridable: the shell
    launcher (`ensure_server.sh`) hardcodes the same path to find server.json,
    so a Python-only override would split the two halves of one directory."""
    return Path(os.path.expanduser(f"~/.claude/{skill_name}"))


def workspace_root(skill_name: str) -> Path:
    """Parent directory holding every ``<sid>`` workspace tree for this skill.

    ``WEBCOMPANION_WORKSPACE_ROOT`` overrides the base; the skill name is still
    appended to it, so pointing all four skills at one volume still gives each
    its own directory. A relative override is ignored in favour of the default:
    it would resolve against the server process's cwd, which is not the
    directory the user was thinking of, and quietly scattering workspaces is
    the exact failure this module exists to end.
    """
    override = os.environ.get(WORKSPACE_ROOT_ENV, "").strip()
    if override:
        base = Path(override).expanduser()
        if base.is_absolute():
            return base / skill_name
    return state_root(skill_name) / "workspaces"


def make_session_dirs(workspace_base: Path, sid: str) -> dict[str, Path]:
    """Create one session's directory tree under `workspace_base` and return
    the `dirs` mapping the registry stores."""
    base = Path(workspace_base) / sid
    dirs = {key: base.joinpath(*rel) for key, rel in _SUBDIRS.items()}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def base_of(dirs: dict) -> Path:
    """The workspace's top directory, from a registry `dirs` mapping."""
    return Path(dirs["state_dir"]).parent


def write_marker(base: Path, sid: str, skill_name: str, cwd: str) -> None:
    """Record which project this workspace belongs to, inside the workspace.

    Best-effort: a workspace that fails to describe itself is still a usable
    workspace, and refusing to create one over a marker write would be a worse
    outcome than a missing marker.
    """
    try:
        write_text_atomic(
            Path(base) / MARKER_FILE,
            json.dumps({"sid": sid, "skill": skill_name, "cwd": str(cwd)}, indent=2),
        )
    except OSError:
        pass


def read_marker(base: Path) -> dict:
    """The marker's contents, or {} if it is absent or unreadable."""
    try:
        data = json.loads((Path(base) / MARKER_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
