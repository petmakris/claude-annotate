"""Moving workspaces that were written inside a project into the central home.

Every one of these starts from the real pre-migration layout —
``<cwd>/.claude/<skill>/<sid>/`` — because the migration's whole job is to
recognise it. `_cwd` is the thing that must survive unchanged: it names the
project the anchors resolve against, and the move deliberately does not change
which project a workspace belongs to.
"""
import json
from pathlib import Path

from skills._shared.web_companion import paths
from skills._shared.web_companion.cleanup import migrate_workspaces


def _legacy_session(project: Path, sid: str, skill: str = "annotate") -> dict:
    base = project / ".claude" / skill / sid
    for sub in ("response", "annotations", "state", "state/events", "state/consumed"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (base / "response" / "blocks.json").write_text('{"blocks": []}')
    (base / "annotations" / "a.json").write_text('{"comment": "keep me"}')
    return {
        "response_dir": str(base / "response"),
        "annotations_dir": str(base / "annotations"),
        "state_dir": str(base / "state"),
        "events_dir": str(base / "state" / "events"),
        "consumed_dir": str(base / "state" / "consumed"),
        "_cwd": str(project),
    }


def _write_sessions(state_root: Path, sessions: dict) -> Path:
    state_root.mkdir(parents=True, exist_ok=True)
    f = state_root / "sessions.json"
    f.write_text(json.dumps(sessions))
    return f


def _read_sessions(state_root: Path) -> dict:
    return json.loads((state_root / "sessions.json").read_text())


def test_moves_the_tree_and_rewrites_every_path(tmp_path):
    state_root, ws_root = tmp_path / "state", tmp_path / "state" / "workspaces"
    project = tmp_path / "projects" / "wp" / "picon-473"
    sid = "260829-120000-aaaabbbbccccdddd"
    _write_sessions(state_root, {sid: _legacy_session(project, sid)})

    out = migrate_workspaces(state_root, ws_root, "annotate")

    assert out == {"moved": 1, "already_home": 0, "errors": 0}
    row = _read_sessions(state_root)[sid]
    assert Path(row["state_dir"]) == ws_root / sid / "state"
    assert Path(row["events_dir"]) == ws_root / sid / "state" / "events"
    assert Path(row["response_dir"]).is_dir()
    # Content came with it, not just the directories.
    assert (ws_root / sid / "annotations" / "a.json").read_text() == '{"comment": "keep me"}'
    # Nothing left behind inside the project.
    assert not (project / ".claude" / "annotate").exists()


def test_cwd_still_names_the_project(tmp_path):
    """The move changes where content lives, never which repo it describes."""
    state_root, ws_root = tmp_path / "state", tmp_path / "ws"
    project = tmp_path / "projects" / "wp" / "picon-473"
    sid = "260829-120000-aaaabbbbccccdddd"
    _write_sessions(state_root, {sid: _legacy_session(project, sid)})

    migrate_workspaces(state_root, ws_root, "annotate")

    assert _read_sessions(state_root)[sid]["_cwd"] == str(project)
    assert paths.read_marker(ws_root / sid) == {
        "sid": sid, "skill": "annotate", "cwd": str(project)}


def test_the_project_survives_when_it_holds_other_claude_state(tmp_path):
    """rmdir only removes an empty directory, so a project with its own
    .claude/settings.json keeps everything it had."""
    state_root, ws_root = tmp_path / "state", tmp_path / "ws"
    project = tmp_path / "proj"
    sid = "260829-120000-aaaabbbbccccdddd"
    _write_sessions(state_root, {sid: _legacy_session(project, sid)})
    (project / ".claude" / "settings.json").write_text("{}")
    (project / ".claude" / "annotate" / "notes.txt").write_text("mine")

    migrate_workspaces(state_root, ws_root, "annotate")

    assert (project / ".claude" / "settings.json").exists()
    assert (project / ".claude" / "annotate" / "notes.txt").read_text() == "mine"


def test_is_idempotent(tmp_path):
    state_root, ws_root = tmp_path / "state", tmp_path / "ws"
    sid = "260829-120000-aaaabbbbccccdddd"
    _write_sessions(state_root, {sid: _legacy_session(tmp_path / "proj", sid)})

    first = migrate_workspaces(state_root, ws_root, "annotate")
    before = _read_sessions(state_root)
    second = migrate_workspaces(state_root, ws_root, "annotate")

    assert first["moved"] == 1
    assert second == {"moved": 0, "already_home": 1, "errors": 0}
    assert _read_sessions(state_root) == before


def test_backfills_a_missing_marker_for_a_session_already_home(tmp_path):
    state_root, ws_root = tmp_path / "state", tmp_path / "ws"
    sid = "260829-120000-aaaabbbbccccdddd"
    _write_sessions(state_root, {sid: _legacy_session(tmp_path / "proj", sid)})
    migrate_workspaces(state_root, ws_root, "annotate")
    (ws_root / sid / "workspace.json").unlink()

    out = migrate_workspaces(state_root, ws_root, "annotate")

    assert out["already_home"] == 1
    assert paths.read_marker(ws_root / sid)["cwd"] == str(tmp_path / "proj")


def test_refuses_to_clobber_an_existing_destination(tmp_path):
    """Two trees claiming one sid means something is wrong; overwriting would
    destroy the evidence, so the row is left exactly where it is."""
    state_root, ws_root = tmp_path / "state", tmp_path / "ws"
    project = tmp_path / "proj"
    sid = "260829-120000-aaaabbbbccccdddd"
    row = _legacy_session(project, sid)
    _write_sessions(state_root, {sid: row})
    (ws_root / sid).mkdir(parents=True)
    (ws_root / sid / "squatter").write_text("do not lose me")

    out = migrate_workspaces(state_root, ws_root, "annotate")

    assert out == {"moved": 0, "already_home": 0, "errors": 1}
    assert _read_sessions(state_root)[sid] == row      # row untouched
    assert Path(row["response_dir"]).is_dir()          # tree untouched
    assert (ws_root / sid / "squatter").read_text() == "do not lose me"


def test_leaves_a_vanished_workspace_for_the_sweep_to_prune(tmp_path):
    state_root, ws_root = tmp_path / "state", tmp_path / "ws"
    sid = "260829-120000-aaaabbbbccccdddd"
    row = {"state_dir": str(tmp_path / "gone" / sid / "state"),
           "_cwd": str(tmp_path / "gone")}
    _write_sessions(state_root, {sid: row})

    out = migrate_workspaces(state_root, ws_root, "annotate")

    assert out == {"moved": 0, "already_home": 0, "errors": 0}
    assert _read_sessions(state_root) == {sid: row}


def test_migrates_only_this_skills_rows_into_this_skills_home(tmp_path):
    """Each skill has its own state_root and its own workspace_root, so a
    dataflow workspace can never land in annotate's home."""
    project = tmp_path / "proj"
    a_sid, d_sid = "260829-120000-" + "a" * 16, "260829-130000-" + "d" * 16
    a_root, d_root = tmp_path / "s-annotate", tmp_path / "s-dataflow"
    _write_sessions(a_root, {a_sid: _legacy_session(project, a_sid, "annotate")})
    _write_sessions(d_root, {d_sid: _legacy_session(project, d_sid, "dataflow")})

    migrate_workspaces(a_root, a_root / "workspaces", "annotate")
    migrate_workspaces(d_root, d_root / "workspaces", "dataflow")

    assert (a_root / "workspaces" / a_sid / "state").is_dir()
    assert (d_root / "workspaces" / d_sid / "state").is_dir()
    assert not (a_root / "workspaces" / d_sid).exists()
    assert paths.read_marker(d_root / "workspaces" / d_sid)["skill"] == "dataflow"


def test_survives_a_missing_or_unparseable_registry(tmp_path):
    empty = {"moved": 0, "already_home": 0, "errors": 0}
    assert migrate_workspaces(tmp_path / "nope", tmp_path / "ws", "annotate") == empty
    state_root = tmp_path / "state"
    _write_sessions(state_root, {})
    (state_root / "sessions.json").write_text("{ broken")
    assert migrate_workspaces(state_root, tmp_path / "ws", "annotate") == empty
    (state_root / "sessions.json").write_text('["a list"]')
    assert migrate_workspaces(state_root, tmp_path / "ws", "annotate") == empty


def test_leaves_an_unrecognizable_row_alone(tmp_path):
    state_root = tmp_path / "state"
    _write_sessions(state_root, {"sid-x": {"note": "no state_dir here"}})
    out = migrate_workspaces(state_root, tmp_path / "ws", "annotate")
    assert out == {"moved": 0, "already_home": 0, "errors": 0}
    assert _read_sessions(state_root) == {"sid-x": {"note": "no state_dir here"}}
