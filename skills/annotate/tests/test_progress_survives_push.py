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


def test_it_is_re_inserted_before_the_replacing_patch():
    # Order matters: after the PATCH there is nothing left to preserve.
    put_back = SRC.index("items[PROGRESS_ANCHOR]")
    patch = SRC.index('"PATCH"')
    assert put_back < patch, "the trail is restored after the replace wipes it"


def test_the_anchor_is_imported_rather_than_retyped():
    # One spelling. A second literal is a rename waiting to break silently.
    assert "from .progress import ANCHOR as PROGRESS_ANCHOR" in SRC \
        or "from skills.annotate.progress import ANCHOR as PROGRESS_ANCHOR" in SRC, \
        "push.py hardcodes the anchor instead of importing it"
