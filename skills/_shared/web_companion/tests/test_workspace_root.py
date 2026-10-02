"""Where workspaces are written, and how WEBCOMPANION_WORKSPACE_ROOT moves it.

The bug this closes: a workspace created from a throwaway git worktree was
written inside that worktree, so removing the worktree destroyed the
annotations and the startup sweep then pruned the registry row too — a resume
answered 404 with nothing left to say anything had been lost.
"""
import json
from pathlib import Path

import pytest

from skills._shared.web_companion import paths

ENV = paths.WORKSPACE_ROOT_ENV


def test_default_is_beside_the_registry(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.workspace_root("annotate") == tmp_path / ".claude" / "annotate" / "workspaces"
    assert paths.state_root("annotate") == tmp_path / ".claude" / "annotate"


def test_default_is_never_inside_a_project(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "projects" / "wp" / "picon-473"
    project.mkdir(parents=True)
    root = paths.workspace_root("annotate")
    assert not root.is_relative_to(project)


def test_env_override_appends_the_skill_name(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, str(tmp_path / "vol"))
    # All four skills can share one volume without sharing a directory.
    assert paths.workspace_root("annotate") == tmp_path / "vol" / "annotate"
    assert paths.workspace_root("deck") == tmp_path / "vol" / "deck"


def test_env_override_expands_a_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(ENV, "~/synced/companion")
    assert paths.workspace_root("annotate") == tmp_path / "synced" / "companion" / "annotate"


@pytest.mark.parametrize("bad", ["", "   ", "relative/dir", "./here"])
def test_unusable_override_falls_back_to_the_default(monkeypatch, tmp_path, bad):
    """A relative override would resolve against the server process's cwd —
    which is not the directory the user meant, and scattering workspaces is
    the exact failure this module exists to end. Fall back, never guess."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(ENV, bad)
    assert paths.workspace_root("annotate") == tmp_path / ".claude" / "annotate" / "workspaces"


def test_make_session_dirs_creates_the_whole_tree(tmp_path):
    dirs = paths.make_session_dirs(tmp_path / "workspaces", "260829-120000-abc")
    assert set(dirs) == {"response_dir", "annotations_dir", "state_dir",
                         "events_dir", "consumed_dir"}
    for d in dirs.values():
        assert d.is_dir()
    assert paths.base_of({k: str(v) for k, v in dirs.items()}) == \
        tmp_path / "workspaces" / "260829-120000-abc"
    assert dirs["events_dir"] == dirs["state_dir"] / "events"


def test_marker_round_trips(tmp_path):
    paths.write_marker(tmp_path, "sid-1", "annotate", "/Users/x/projects/wp/picon-473")
    assert json.loads((tmp_path / "workspace.json").read_text()) == {
        "sid": "sid-1", "skill": "annotate", "cwd": "/Users/x/projects/wp/picon-473"}
    assert paths.read_marker(tmp_path)["cwd"] == "/Users/x/projects/wp/picon-473"


def test_read_marker_tolerates_absent_and_corrupt(tmp_path):
    assert paths.read_marker(tmp_path) == {}
    (tmp_path / "workspace.json").write_text("{not json")
    assert paths.read_marker(tmp_path) == {}
    (tmp_path / "workspace.json").write_text('["a list"]')
    assert paths.read_marker(tmp_path) == {}


def test_write_marker_never_raises_on_an_unwritable_base(tmp_path):
    paths.write_marker(tmp_path / "does" / "not" / "exist", "s", "annotate", "/x")
