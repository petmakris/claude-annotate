"""The read-aloud controls after the restyle.

The toolbar shows Read and Explain side by side, each with its own icon. The
player card picks its mode with two tabs in its header, so the control row
holds only Play, Back, the progress bar and the speed. Play is the only solid
blue control.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
SPEECH = (STATIC / "speech.js").read_text()
SELECTION = (STATIC / "selection.js").read_text()
CSS = (STATIC / "style-read-aloud.css").read_text()


def _rule(css, selector):
    i = css.index(selector + " {")
    return css[i:css.index("}", i)]


def test_the_toolbar_shows_read_and_explain_with_no_chevron():
    assert "voice-more" not in SPEECH and "voice-more" not in SELECTION
    assert "ICON_MORE" not in SPEECH
    assert "menu.append(read, explain)" in SPEECH


def test_read_and_explain_have_their_own_icons():
    assert "const ICON_READ =" in SPEECH
    assert "const ICON_EXPLAIN =" in SPEECH
    assert 'make("read", ICON_READ' in SPEECH
    assert 'make("explain", ICON_EXPLAIN' in SPEECH
    # The toolbar draws icons as strokes; a fill would turn both into blobs.
    assert '.sel-menu [data-act="explain"] svg' not in CSS


def test_shift_r_clicks_read_directly():
    i = SELECTION.index('if (ev.key.toLowerCase() === "r")')
    body = SELECTION[i:SELECTION.index("return;\n      }", i)]
    assert 'live("read")?.click()' in body


def test_the_card_picks_its_mode_with_tabs_in_its_header():
    i = SPEECH.index("function buildCard(")
    card = SPEECH[i:SPEECH.index("\n  }\n", i)]
    assert 'class="sp-tabs"' in card
    assert 'data-mode="read"' in card and 'data-mode="explain"' in card
    i = SPEECH.index("function buildControls(")
    ctl = SPEECH[i:SPEECH.index("\n  }\n", i)]
    assert 'data-sp="mode"' not in ctl


def test_back_is_an_icon_button():
    assert "⟲" not in SPEECH
    assert 'class="sp-btn sp-icon" data-sp="back"' in SPEECH
    assert "width: 28px" in _rule(CSS, ".sp-icon")


def test_only_play_is_solid_blue():
    pressed = _rule(CSS, '.sp-seg button[aria-pressed="true"]')
    assert "background: var(--accent);" not in pressed
    assert "color-mix(in srgb, var(--accent)" in pressed
    assert "background: var(--accent)" in _rule(CSS, ".sp-btn.primary")


def test_the_card_starts_where_the_paragraph_text_does():
    assert "p + .sp-card, blockquote + .sp-card { margin-left: 6px; }" in CSS
