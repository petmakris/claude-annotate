"""A picture is commented as a whole, from the card header — never per node.

Why the rule exists: `.annotate-flow .flow-ref` paints a node's file reference
accent-coloured and underlined whether or not the spec gave it an `href`. A ref
without one therefore reads as a jump-to-source link while behaving as a comment
target — the click misses the absent anchor and lands on the node handler, and
the reader who wanted a file gets an editor. The granular scope was withdrawn
from sequence, flowchart and pflow-source rather than tuned.

These are structural guards. The behavioural proof — that a click on a node, a
ref line, a source row or a step row opens nothing, while the header still opens
a whole-block comment and a real anchor still navigates — lives in
`tests/e2e/no-granular-diagram.e2e.cjs`, which drives a real browser:

    NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/no-granular-diagram.e2e.cjs
"""
# NOTE: the browser-driven proof this file used to point at is gone. The 19
# e2e suites spawned annotate's own server, which was deleted when annotate
# moved onto the webcompanion daemon. They are recoverable from git history
# and are repointable — the page they drove is unchanged, only the way it is
# served — but until they are, what remains below is static assertion only.
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
DIAGRAM_CSS = STATIC / "diagram.css"
STYLE_CSS = STATIC / "style.css"


def _strip_comments(js: str) -> str:
    """Drop // and /* */ comments so a guard cannot be satisfied by prose.

    The comments in these branches explain the removed handler by name, so a
    plain substring search over the source would keep passing after the
    handler itself came back."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in js.splitlines())


def _picture_branches() -> str:
    """The sequence/diagram/flowchart arms of createBlockSection, code only."""
    src = SCRIPT_JS.read_text()
    region = src.split('if (kind === "sequence") {', 1)[1]
    region = region.split('} else if (kind === "choice") {', 1)[0]
    return _strip_comments(region)


def test_no_picture_kind_opens_a_comment_on_click():
    code = _picture_branches()
    assert "onHoverAction" not in code, (
        "a sequence/diagram/flowchart branch opens a comment from a body "
        "click again — pictures are header-scope only"
    )


def test_flowchart_still_follows_its_anchors():
    """Killing the node handler must not kill navigation: an in-page
    href="#<block-id>" still has to scroll to that block, and any other anchor
    (a jetbrains:// code ref) still has to be left alone to navigate."""
    code = _picture_branches()
    assert "scrollIntoView" in code, "the in-page cross-block anchor stopped scrolling"
    assert 'closest("a[href]")' in code, "the flowchart anchor path is gone"


def test_pflow_rows_are_not_comment_targets():
    """The source pane pairs a line to the shape it drew. It stopped being a
    second way into the composer, so it must not advertise one."""
    src = SCRIPT_JS.read_text()
    assert "click a line to comment" not in src, \
        "the pflow pane still invites a click that opens nothing"
    assert ".pflow-row.is-live { cursor: pointer; }" not in STYLE_CSS.read_text(), \
        "a pflow source row still shows a pointer cursor it cannot honour"


def test_pictures_do_not_advertise_a_click_they_no_longer_answer():
    css = DIAGRAM_CSS.read_text()
    for rule in (".annotate-seq .step-row { cursor: pointer; }",
                 ".annotate-flow .node { cursor: pointer; }"):
        assert rule not in css, f"{rule} promises a click nothing answers"
    # The one genuinely clickable thing inside a picture keeps its cursor.
    assert ".annotate-flow a { cursor: pointer; }" in css, \
        "real anchors inside a flowchart lost their pointer cursor"


def test_engaged_and_focus_state_survives():
    """Comments made before the rule changed still anchor by step id, and the
    row/node they point at still has to light up when their card is focused —
    otherwise an existing session's cards lose their target."""
    css = DIAGRAM_CSS.read_text()
    assert '.annotate-seq .step-row[data-card-focus]' in css
    assert '.annotate-flow .node[data-card-focus]' in css
    assert '.annotate-seq .step-row[data-engaged-type="comment"]' in css




def test_the_badge_is_the_one_licensed_click_and_its_answer_ships_with_it():
    """The rule this file guards is not "nothing in a picture is clickable" —
    it is "nothing promises a click that leads nowhere". A badge points at its
    key entry, so it earns a cursor; a step row still points at nothing, so it
    must not have one. The licence is conditional: if the key ever stops being
    painted alongside the grid, the badge becomes exactly the dead affordance
    the rest of this file exists to prevent."""
    css = DIAGRAM_CSS.read_text()
    assert ".annotate-seq .badge-hit    { cursor: pointer; outline: none; }" in css, \
        "the badge lost the pointer cursor for the click it does answer"
    assert ".annotate-seq .step-row { cursor: pointer; }" not in css, \
        "a step row promises a click nothing answers"
    assert ".seq-key-row" in css, "the badge's cursor is unlicensed: no key is styled"

    js = _strip_comments(SCRIPT_JS.read_text())
    assert "blk.key" in js, "the key half never reaches the page"
    # Both paint sites must go through the one function, or a repaint can drop
    # the key and leave a grid of unexplained circles.
    # The trailing `;` is what separates the two call sites from the one
    # definition, which the same substring otherwise matches.
    assert js.count("paintSequence(content, blk);") == 2, \
        "a sequence paint site bypasses paintSequence"
    assert 'content.innerHTML = blk.svg' not in js, \
        "a paint site paints the grid without its key"


def test_the_pairing_is_not_a_second_way_into_the_composer():
    """linkSequenceKey exists to light a row, nothing more."""
    src = SCRIPT_JS.read_text()
    region = src.split("function linkSequenceKey(content) {", 1)[1]
    region = _strip_comments(region.split("\n  }\n", 1)[0])
    for forbidden in ("onHoverAction", "openComposer", "composer"):
        assert forbidden not in region, \
            f"the badge/key pairing reaches {forbidden} — it must only toggle a class"


def test_the_key_cannot_widen_the_card_it_sits_in():
    """`.block-content` is a horizontal scroll container for a sequence block.
    A key row that bleeds past it does not bleed, it scrolls: the first cut
    carried `margin: 0 -10px` and put a 1111px row inside a 1091px card, giving
    every sequence card 10px of horizontal scroll for nothing."""
    css = DIAGRAM_CSS.read_text()
    block = css.split(".seq-key-row {", 1)[1].split("}", 1)[0]
    assert "margin" not in block, \
        f"a margin on .seq-key-row can push it past the scroll container: {block.strip()!r}"
