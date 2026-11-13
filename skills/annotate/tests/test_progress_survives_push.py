"""A push must not delete the narration it just finished producing.

push.py replaces the whole item set (`PATCH … replace: true`), which is how
`__prev__` came to be re-inserted by hand at push.py:148. `__progress__` needs
the same treatment for a sharper reason: the push that lands Claude's answer is
the moment the reader turns to the page, and the trail explaining how the
answer was reached would vanish in the same instant.
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "push.py").read_text()


def test_push_preserves_the_progress_anchor():
    assert "PROGRESS_ANCHOR" in SRC, "push.py does not know about the trail"
    # Carried the same way __prev__ is: read the stored items, re-insert.
    assert re.search(r"items\[PROGRESS_ANCHOR\]\s*=", SRC), \
        "push.py reads the anchor but never puts it back"


def test_it_is_re_inserted_before_the_replacing_patch(tmp_path, monkeypatch):
    # Order matters: after the PATCH there is nothing left to preserve, so
    # the trail has to be in the very body the replace sends.
    import json
    from skills._shared import webcompanion_client as wc
    from skills.annotate import push as push_mod

    trail = {"id": "__progress__", "kind": "progress", "state": "done", "steps": []}
    stored = {"__progress__": {"body": trail, "version": 1}}
    sent = {}
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "")
    monkeypatch.setattr(wc, "load_config", lambda: {"port": 1, "token": "t"})
    monkeypatch.setattr(wc, "all_sessions",
                        lambda: [{"kind": "annotate", "slug": "pg", "sid": "s1"}])
    monkeypatch.setattr(wc, "request", lambda method, path, *a, **k: stored)
    monkeypatch.setattr(wc, "put_items", lambda sid, items, **k: sent.update(items))
    monkeypatch.setattr(wc, "register_assets", lambda *a, **k: None)
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps({"blocks": [{"id": "section-1", "markdown": "hi"}]}))
    push_mod.push(blocks, str(tmp_path), slug="pg")
    assert sent.get("__progress__") == trail, "the replace wiped the trail"


def test_the_anchor_is_imported_rather_than_retyped():
    # One spelling. A second literal is a rename waiting to break silently.
    assert "from .progress import ANCHOR as PROGRESS_ANCHOR" in SRC \
        or "from skills.annotate.progress import ANCHOR as PROGRESS_ANCHOR" in SRC, \
        "push.py hardcodes the anchor instead of importing it"
