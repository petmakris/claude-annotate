"""Explicit deletion is the only way a workspace disappears by default."""
import json
import os
import stat
from pathlib import Path

import pytest

from skills._shared.web_companion.sessions import Registry
from skills._shared.web_companion.server import delete_session


def _session(reg, tmp_path, sid, slug):
    base = tmp_path / sid
    st = base / "state"
    (base / "response").mkdir(parents=True)
    st.mkdir(parents=True)
    reg.register(sid, {"state_dir": st, "_cwd": str(tmp_path)})
    reg.register_meta(sid, {"slug": slug, "title": slug, "created_at": 1})
    return base


def test_delete_by_slug_removes_dir_and_registry_row(tmp_path):
    r = Registry(tmp_path)
    base = _session(r, tmp_path, "260720-1-a", "one")
    assert delete_session(r, "one") is True
    assert not base.exists()
    assert r.lookup("260720-1-a") is None
    assert r.resolve("one") is None


def test_delete_by_sid_works_too(tmp_path):
    r = Registry(tmp_path)
    base = _session(r, tmp_path, "260720-2-b", "two")
    assert delete_session(r, "260720-2-b") is True
    assert not base.exists()


def test_delete_unknown_key_is_false_noop(tmp_path):
    r = Registry(tmp_path)
    _session(r, tmp_path, "260720-3-c", "three")
    assert delete_session(r, "nope") is False
    assert r.resolve("three") is not None


def test_delete_is_written_to_disk_not_just_memory(tmp_path):
    """The deletion has to survive a server restart.

    Dropping the row in memory alone looks identical through the running
    server — the index re-fetches and the workspace is absent either way — but
    the next process rehydrates from sessions.json and the workspace walks
    back in. Both files matter: sessions_meta.json holds the slug, so a stale
    meta row keeps that slug "taken" and forces the next workspace of the same
    name to dedup to `-2`.
    """
    r = Registry(tmp_path)
    _session(r, tmp_path, "260720-5-e", "five")
    _session(r, tmp_path, "260720-6-f", "six")
    r.persist()
    assert delete_session(r, "five") is True

    assert "260720-5-e" not in json.loads(r.sessions_file.read_text())
    assert "260720-5-e" not in json.loads(r.sessions_meta_file.read_text())
    assert "260720-6-f" in json.loads(r.sessions_file.read_text())

    # What the next server start would see.
    fresh = Registry(tmp_path)
    fresh.rehydrate()
    assert fresh.resolve("five") is None, "the deleted workspace came back on restart"
    assert fresh.resolve("six") is not None, "the surviving workspace was lost"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_failed_delete_keeps_the_workspace_reachable(tmp_path):
    """If the tree cannot be removed, the registration must SURVIVE.

    Dropping it anyway reported success, left the files on disk, and took away
    the only handle that could reach them: the key stopped resolving, so the
    "just delete it again" recovery 404s forever and `rehydrate` cannot help
    either — the row is gone from sessions.json. Silent, permanent garbage.

    Read+execute but not write on the workspace dir means its children cannot
    be unlinked, which is the cheapest honest way to make rmtree fail.
    """
    r = Registry(tmp_path)
    base = _session(r, tmp_path, "260720-4-d", "four")
    os.chmod(base, stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert delete_session(r, "four") is False, \
            "a delete that removed nothing reported success"
        assert base.exists(), "test setup is wrong — the tree was removable"
        assert r.resolve("four") == "260720-4-d", \
            "the workspace is on disk but no longer reachable by key"
    finally:
        os.chmod(base, stat.S_IRWXU)
    # And now that the obstruction is gone, the retry the docstring promises
    # actually works.
    assert delete_session(r, "four") is True
    assert not base.exists()
    assert r.resolve("four") is None
