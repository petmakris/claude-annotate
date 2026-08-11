"""Explicit deletion is the only way a workspace disappears by default."""
from pathlib import Path

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
