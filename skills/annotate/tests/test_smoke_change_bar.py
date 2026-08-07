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


def _brace_block(src: str, start: int) -> str:
    """Text between the `{` at or after `start` and its matching `}`."""
    open_at = src.index("{", start)
    depth = 0
    for i in range(open_at, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_at + 1:i]
    raise AssertionError("unbalanced braces from offset %d" % start)


def test_one_failed_block_cannot_kill_the_rest_of_the_set():
    """Two guards, and only one of them is load-bearing.

    The outer `.catch` on the `applyChangeSet(...)` call site silences an
    unhandled rejection, but it fires AFTER the loop has already aborted —
    every block past the one that threw has lost its pane by then. What
    actually keeps the rest of the change set rendering is the per-block
    `try`/`catch` INSIDE the loop.

    So this asserts the per-block guard first and hardest: the loop body's
    real work — markChangedCard and renderDiffPane — must sit inside a try
    that has a catch. Asserting only the `.catch` was the earlier version
    of this test, and it stayed green when the per-block guard was deleted.
    """
    src = SCRIPT_JS.read_text()

    body = _brace_block(src, src.index("async function applyChangeSet("))
    loop = _brace_block(body, body.index("for (const c of changed)"))
    assert "try" in loop, "applyChangeSet's loop body has no per-block try"
    guarded = _brace_block(loop, loop.index("try"))
    for call in ("markChangedCard(", "renderDiffPane("):
        assert call in guarded, \
            f"{call} sits outside the per-block try — a throw there still " \
            "aborts the loop and every later block loses its pane"
    after_try = loop[loop.index(guarded) + len(guarded):]
    assert re.match(r"\s*\}\s*catch\b", after_try), \
        "the per-block try has no catch, so a throw still escapes the loop"

    # Secondary: the floating promise still needs a .catch, or the (now
    # rarer) escape becomes an unhandled rejection in the console.
    assert re.search(r"applyChangeSet\(changed, doc\)\s*\n?\s*\.catch\(", src), \
        "applyChangeSet's rejection is unhandled"


def test_the_hardcoded_why_label_is_gone():
    """The old renderDiffPane always prepended a literal "Why: " label and
    then appended the raw change_note verbatim. Since the contract's own
    change_note text starts with "Why:", that produced "Why: Why: ...".
    The fix must build the label from the note's own line, not a fixed
    string sitting outside the note's content."""
    src = SCRIPT_JS.read_text()
    body = _brace_block(src, src.index("function renderDiffPane("))
    assert '"Why: "' not in body, \
        "renderDiffPane still hardcodes a \"Why: \" label ahead of the note"


def test_the_change_note_renders_line_by_line():
    """A flat text node collapses the newline before a Lost: line (no
    white-space: pre-wrap in .diff-why), burying it mid-sentence. The note
    must be split into its own lines and rendered as separate elements."""
    src = SCRIPT_JS.read_text()
    body = _brace_block(src, src.index("function renderDiffPane("))
    assert 'split("\\n")' in body or "split('\\n')" in body, \
        "renderDiffPane does not split change_note into lines"
    assert "diff-why-line" in body, \
        "renderDiffPane does not give each note line its own element"


def test_the_lost_line_gets_its_own_class():
    """Lost: is the only place a user can ever learn what a compact
    irreversibly discarded. It must be distinguishable from the Why: line,
    not just more text in the same paragraph."""
    src = SCRIPT_JS.read_text()
    body = _brace_block(src, src.index("function renderDiffPane("))
    assert "diff-lost" in body, \
        "renderDiffPane never marks a Lost: line with its own class"
    css = STYLE_CSS.read_text()
    assert ".diff-lost" in css, "style.css does not style .diff-lost"


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


def test_the_busy_banner_has_no_empty_sub_label():
    """A `.bb-sub` node was created for a promised "3 of 5 marks applied"
    progress line. Nothing can write it: progress labels come from
    hooks/progress_publish.py, which maps tool names onto a fixed allowlist
    and knows nothing about mark counts. There is no `.bb-*` CSS either, so
    the node shipped as an empty flex child eating a `gap: 9px` slot.

    Recorded as a known spec deviation: the sub-label and step pips the spec
    promised are not reachable without a progress-contract change.
    """
    assert "bb-sub" not in SCRIPT_JS.read_text(), \
        "the busy banner still creates a sub-label nothing can fill"
