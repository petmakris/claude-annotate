"""The page reads as one document: no card, no section number, no chevron.

A block is still the unit Claude rewrites and a comment points at; the reader
just never sees it. These names were the card's, and none may come back.
"""
import re
from pathlib import Path

from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

STATIC = Path(__file__).resolve().parents[1] / "static"
GONE = ("card-head", "card-title", "card-chevron", "section-pill", "card-body", "block card")


def _all_static_text():
    for p in sorted(STATIC.glob("*.js")) + sorted(STATIC.glob("*.css")):
        if p.name.endswith(".min.js"):
            continue
        yield p.name, p.read_text()


def test_no_static_file_names_the_card():
    found = [(name, word) for name, text in _all_static_text() for word in GONE if word in text]
    assert found == [], f"the card is still named in: {found}"


def test_a_block_is_built_without_a_box():
    src = SCRIPT_JS.read_text()
    i = src.index("function createBlockSection(")
    body = src[i:src.index("\n}", i)]
    assert 'section.className = "block";' in body
    assert "blockLabel(blk)" in body
    assert 'body.className = "block-body"' in body
    assert "renderVersionBadge" not in src


def test_a_heading_is_only_an_authored_title():
    src = SCRIPT_JS.read_text()
    i = src.index("function blockLabel(")
    body = src[i:src.index("\n}", i)]
    assert "visibleTitle(blk)" in body
    assert '"h2"' in body


def test_the_page_ground_is_the_text_surface():
    css = STYLE_CSS.read_text()
    assert re.search(r"(?m)^body\s*\{[^}]*background:\s*var\(--surface\)", css), \
        "the page still sits on the grey card ground"


def test_a_label_of_the_same_shape_is_kept_on_re_render():
    src = SCRIPT_JS.read_text()
    i = src.index("function setBlockLabel(")
    body = src[i:src.index("\n}", i)]
    assert "sameShape" in body
    assert 'classList.contains("block-heading")' in body
    assert body.index("sameShape") < body.index("replaceWith"), \
        "the label is replaced before the shape is compared, dropping its chips"
    assert "textContent" in body


def test_a_part_has_no_hover_wash_or_engaged_tint():
    css = STYLE_CSS.read_text()
    assert "main.prose section.block:hover" in css
    assert "section.block[data-engaged-type]:not([data-kb-focus])::before { content: none; }" in css
