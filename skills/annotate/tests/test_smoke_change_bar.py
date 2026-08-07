"""Structural guards for the change summary bar and per-block diff.

The coherence sweep's whole job is changing blocks the user never marked.
Before this, the only signal that anything moved was a version pill in a
card corner — so the sweep edited unmarked sections invisibly and the user
had to take it on faith. These guard that the signal exists AND that it
distinguishes what the user asked for from what the sweep decided.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"


def test_a_change_bar_is_rendered():
    src = SCRIPT_JS.read_text()
    assert "change-bar" in src, "no change summary bar"
    assert "sections changed" in src, "the bar does not say how many moved"


def test_the_bar_splits_asked_from_swept():
    """The entire reason the bar earns its space."""
    src = SCRIPT_JS.read_text()
    assert "coherence sweep" in src, \
        "the bar does not attribute changes to the sweep"
    assert "submittedBlockIds" in src, \
        "attribution is not derived from what the user actually submitted"


def test_changed_blocks_carry_an_attribution_chip():
    src = SCRIPT_JS.read_text()
    assert "attr-chip" in src, "changed blocks carry no attribution chip"


def test_the_diff_reads_the_snapshot():
    src = SCRIPT_JS.read_text()
    assert "/prev" in src, "the client never fetches the pre-round snapshot"


def test_the_diff_is_styled():
    css = STYLE_CSS.read_text()
    for needle in (".change-bar", ".attr-chip", ".diff-pane", ".card-diff-toggle"):
        assert needle in css, f"style.css missing {needle}"
