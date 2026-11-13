"""Structural guard for the comment-card v2 redesign (commit 280cdd8):

  - The preview/edit-mode toggle is gone — no .editor-preview, no
    .preview-mode / .edit-mode class names remain in JS or CSS.

If a future change reintroduces it, this test fails immediately and
the diff explains why.

It also pinned .card-close in the card's right gutter. That test is gone:
the card has no × of its own any more. It opens in the comment window
(comment-window.js), whose title bar carries the one ×.
"""
import re
from pathlib import Path
from skills.annotate.tests.page_source import SCRIPT_JS

REPO = Path(__file__).resolve().parents[3]
# annotate's own core.css, the one its page loads. (It used to check the
# shared copy, which no page loaded.)
CORE_CSS = REPO / "skills" / "annotate" / "static" / "core.css"


def test_preview_mode_is_gone():
    """The preview/edit-mode toggle should leave no trace in JS or CSS."""
    js = SCRIPT_JS.read_text()
    css = CORE_CSS.read_text()
    for needle in (".preview-mode", ".edit-mode", "editor-preview"):
        assert needle not in js, f"JS still references {needle!r}"
        assert needle not in css, f"CSS still references {needle!r}"
