"""Structural guards for the change summary bar and per-block diff.

The coherence sweep's whole job is changing blocks the user never marked.
Before this, the only signal that anything moved was a version pill in a
card corner — so the sweep edited unmarked sections invisibly and the user
had to take it on faith. These guard that the signal exists AND that it
distinguishes what the user asked for from what the sweep decided.

Source-string checks matching the repo's other smoke tests.
"""
import re
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


def test_the_bar_sticks_to_the_top_of_the_viewport():
    """The mockup's `top: 62px` cleared the mockup's own demo toolbar.

    Nothing ships in that space: the real .page-header sets no `position`
    and scrolls away. Any non-zero offset pins the bar as an opaque slab
    below the viewport top with prose scrolling above it — every round.
    """
    css = STYLE_CSS.read_text()
    rule = re.search(r"^\.change-bar\s*\{(.*?)\}", css, re.S | re.M)
    assert rule, "no .change-bar rule in style.css"
    body = rule.group(1)
    assert "position: sticky" in body, ".change-bar stopped being sticky"
    top = re.search(r"top:\s*([^;]+);", body)
    assert top, ".change-bar declares no top offset"
    assert top.group(1).strip() in ("0", "0px"), \
        f".change-bar top is {top.group(1).strip()!r}; nothing reserves space above it"


def test_the_word_diff_caps_its_table():
    """wordDiff allocates an (n+1)x(m+1) Uint32 table.

    Uncapped, a 2000-word block asks for ~61MB and a 4000-word one for
    ~244MB, and applyChangeSet runs it over every changed block so the
    peaks stack — a frozen tab, or a RangeError that kills the whole set.
    Past the cap it must still return a coarse whole-text replacement
    rather than nothing, so a huge block still shows a correct diff.
    """
    src = SCRIPT_JS.read_text()
    assert "DIFF_MAX_CELLS" in src, "wordDiff's table allocation is unbounded"
    guard = re.search(r"if \(n \* m > DIFF_MAX_CELLS\) return (.+);", src)
    assert guard, "no size guard ahead of the table allocation"
    assert '["-", a]' in guard.group(1) and '["+", b]' in guard.group(1), \
        "over the cap wordDiff must still return a whole-text replacement"
    # The guard has to come BEFORE the allocation or it saves nothing.
    assert src.index("DIFF_MAX_CELLS)") < src.index("new Uint32Array(m + 1)"), \
        "the cap is checked after the table is already allocated"


def test_one_failed_block_cannot_kill_the_rest_of_the_set():
    """applyChangeSet is a floating async call inside a .then.

    Without a .catch a throw is an unhandled rejection that silently drops
    the diff panes for every block after the one that failed.
    """
    src = SCRIPT_JS.read_text()
    assert re.search(r"applyChangeSet\(changed, doc\)\s*\n?\s*\.catch\(", src), \
        "applyChangeSet's rejection is unhandled"


def test_clearing_attribution_also_drops_the_unapplied_set():
    """The busy edge wipes the DOM; the /raw .then consumes the set later.

    If the ack poll's /raw fetch fails, the pending set outlives it — and
    round 2's busy edge clears the cards and then hands round 1's set to
    the next /raw. Chips and a pane appear mid-round, labelled with round-1
    versions but diffed against round 2's snapshot.
    """
    src = SCRIPT_JS.read_text()
    body = re.search(r"function clearChangeAttribution\(\) \{(.*?)\n  \}", src, re.S)
    assert body, "clearChangeAttribution is gone"
    assert "pendingChangeSet = null" in body.group(1), \
        "clearChangeAttribution leaves the un-applied change set behind"
