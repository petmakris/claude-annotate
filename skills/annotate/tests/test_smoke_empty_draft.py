"""An empty draft must not outlive the click that made it.

Opening a comment creates the draft immediately and persists it, so a click
with nothing typed used to leave a permanent engaged bar on the block AND, via
the one-draft-at-a-time rule, made every other block refuse to open a comment.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT_JS = REPO / "skills" / "annotate" / "static" / "script.js"
STYLE_CSS = REPO / "skills" / "annotate" / "static" / "style.css"


def _js():
    return SCRIPT_JS.read_text()


def test_emptiness_has_one_definition():
    js = _js()
    assert "function isEmptyDraft(a)" in js
    body = js.split("function isEmptyDraft(a)", 1)[1].split("}", 1)[0]
    # text, pasted images and the disagree stance are the three ways a draft
    # can carry content; selected_text is scope and must not count
    assert "comment" in body and "images" in body and "disagree" in body
    assert "selected_text" not in body


def test_opening_a_comment_clears_a_stale_empty_draft_first():
    js = _js()
    open_fn = js.split("if (!existingId) {", 1)[1].split(
        "const id = existingId", 1)[0]
    assert "isEmptyDraft(v)" in open_fn
    assert "delete annotations[k]" in open_fn
    # the one-draft guard still applies to drafts that DO carry content
    assert "Object.keys(annotations).length > 0) return;" in open_fn


def test_empty_drafts_are_pruned_on_load_with_the_orphans():
    js = _js()
    prune = js.split("let pruned = false;", 1)[1].split("if (pruned)", 1)[0]
    assert "isEmptyDraft(a)" in prune
    assert "delete annotations[id]" in prune


def test_the_engaged_bar_is_still_driven_by_a_draft():
    """The bar itself is correct behaviour — it says which block you are
    commenting on. Only its lingering without a comment was the bug."""
    css = STYLE_CSS.read_text()
    assert '[data-engaged-type="comment"] .card-body' in css
    assert "isEmptyDraft" in _js()
