"""An empty draft must not outlive the SESSION that made it.

Opening a comment creates the draft immediately and persists it, so a click
with nothing typed used to leave a permanent engaged bar on the block AND, via
the one-draft-at-a-time rule, made every other block refuse to open a comment.

It said "the click that made it" until that turned out to be too literal.
The rule was enforced inside renderComments — which openAnnotation calls to
draw the card it has just created, while that card is still empty. So every
comment was deleted at the instant it was opened: one click wrote the draft
to localStorage and wrote "{}" back over it in the same tick, and the comment
icon did nothing at all, silently, on every block. Measured in a browser; see
test_smoke_comment_open.py.

The rule now lives in the two places that can tell an abandoned draft from a
live one: loadDrafts, on the way in, and openAnnotation, before it opens a
different target. Both are asserted below.

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
    # The one-draft guard still applies to drafts that DO carry content.
    # Asserted as the guard rather than as one spelling of it: this read
    # `...length > 0) return;` and broke when the refusal grew a body that
    # tells the reader where the open editor is — a change that left the rule
    # itself untouched.
    assert "Object.keys(annotations).length > 0)" in open_fn
    assert "return;" in open_fn.split("Object.keys(annotations).length > 0)", 1)[1]


def test_empty_drafts_are_pruned_on_load():
    """On LOAD, which is what this test was always named for.

    It used to assert against renderComments' orphan prune instead, and that
    is the line that made the comment icon dead — see the module docstring.
    """
    js = _js()
    load = js.split("function loadDrafts()", 1)[1].split("\n  }", 1)[0]
    assert "isEmptyDraft(a)" in load, \
        "an empty draft survives a reload again, with its engaged bar"
    assert "delete stored[id]" in load

    # And the render path must NOT do it, or opening a comment deletes it.
    prune = js.split("let pruned = false;", 1)[1].split("if (pruned)", 1)[0]
    prune = "\n".join(l for l in prune.splitlines() if not l.strip().startswith("//"))
    assert "isEmptyDraft" not in prune, \
        "renderComments prunes empty drafts again — that deletes every " \
        "comment at the moment it is opened"


def test_the_engaged_bar_is_still_driven_by_a_draft():
    """The bar itself is correct behaviour — it says which block you are
    commenting on. Only its lingering without a comment was the bug."""
    css = STYLE_CSS.read_text()
    assert '[data-engaged-type="comment"] .card-body' in css
    assert "isEmptyDraft" in _js()
