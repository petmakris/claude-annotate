"""Regression guard: inline HTML in a block must not render as source.

With `html: true`, Claude writes free-form HTML into markdown blocks —
comparison tables, callouts, side-by-side diagrams.  Readable HTML is
indented, and CommonMark turns any line indented four or more spaces into
a code block.  A blank line between elements compounds it: the blank line
closes the HTML block, so every indented line after it is parsed fresh and
becomes a listing.

The symptom is unmistakable and was hit in practice: the outer wrapper
renders, and the whole inside of the diagram appears on the page as its own
`<div style="...">` source.

The fix is to disable markdown-it's indented-code rule for block markdown.
Fenced code is a different rule and stays enabled, which is what every code
sample we emit uses.  These tests pin that so the line cannot be dropped in
a refactor.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT_JS = REPO / "skills" / "annotate" / "static" / "script.js"
PUSHING_MD = REPO / "skills" / "annotate" / "references" / "pushing.md"


def _src():
    return SCRIPT_JS.read_text()


def test_block_renderer_disables_indented_code():
    """blockMd must disable the `code` rule."""
    src = _src()
    assert re.search(r"blockMd\.disable\(\s*[\"']code[\"']\s*\)", src), (
        "blockMd no longer disables the indented-code rule — indented inline "
        "HTML will render as source again"
    )


def test_disable_is_guarded_against_a_missing_markdownit():
    """blockMd is null when markdown-it failed to load; disabling must not throw."""
    src = _src()
    m = re.search(r".*blockMd\.disable\(\s*[\"']code[\"']\s*\).*", src)
    line = m.group(0)
    assert "if (blockMd)" in line or "blockMd?." in line, (
        "blockMd.disable(...) must be guarded — blockMd is null when "
        f"markdown-it is unavailable. Got: {line.strip()}"
    )


def test_fenced_code_still_highlighted():
    """Disabling `code` must not disable fences — they carry every sample we emit."""
    src = _src()
    assert "highlight: highlightFence" in src, (
        "fenced-code highlighting disappeared; disabling the indented-code "
        "rule is only safe while fences still work"
    )
    assert not re.search(r"blockMd\.disable\(\s*[\"']fence[\"']", src), (
        "fences must stay enabled"
    )


def test_comment_renderer_untouched():
    """Only block markdown allows HTML. The comment renderer has html:false and
    is not part of this fix — pin that so the two do not get conflated."""
    src = _src()
    m = re.search(r"commentMd\s*=.*?markdownit\(\s*\{(.*?)\}", src, re.S)
    assert m, "commentMd construction not found"
    assert "html: false" in m.group(1), (
        "commentMd must keep html:false — user comment text is not trusted HTML"
    )


def test_authoring_constraint_is_documented():
    """The renderer fix removes the trap; the guidance must still tell Claude
    how to author HTML, because a blank line inside an HTML run also ends it."""
    doc = PUSHING_MD.read_text().lower()
    assert "blank line" in doc, (
        "references/pushing.md must warn that a blank line inside inline HTML "
        "ends the HTML block"
    )
