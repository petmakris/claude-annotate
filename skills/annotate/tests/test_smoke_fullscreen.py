"""Structural guards for the full-screen header control.

Android's Chrome and Firefox keep the address bar and system nav pinned to a
page that never asked otherwise, and offer no menu item that hides them —
unlike desktop, where F11 already does the job. #fullscreen-toggle wires the
standard Fullscreen API to a header button so a phone has the same escape.

What a source read can actually see is asserted here: that the button ships
in the shell, that its script is wired into entry.js, and that the same
`[hidden]` cascade trap other header controls already had to work around is
closed for it too. Whether the button actually toggles the browser's chrome
is not something a source check can see at all — that needs a real browser.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
FULLSCREEN_JS = STATIC / "fullscreen.js"
CORE_CSS = STATIC / "core.css"


def _hides_when_hidden(css, selector):
    pattern = re.escape(selector) + r"\[hidden\]\s*\{[^}]*display:\s*none"
    return re.search(pattern, css) is not None


def test_button_is_rendered_in_the_shell():
    from .shell_source import shell_html
    assert 'id="fullscreen-toggle"' in shell_html()


def test_served_after_shell_paints():
    """fullscreen.js only needs the header button shell.js already rendered
    (see entry.js boot()), so it just needs to appear in the script list —
    not necessarily last, only present."""
    entry = (STATIC / "entry.js").read_text()
    assert '"fullscreen.js"' in entry, "fullscreen.js is not wired into entry.js's JS list"


def test_feature_detects_before_touching_the_button():
    """No flash of a visible-then-hidden button on a browser without the
    Fullscreen API: the check has to run before anything else touches #btn."""
    code = FULLSCREEN_JS.read_text()
    assert "requestFullscreen" in code and "exitFullscreen" in code
    m = re.search(r"const btn = document\.getElementById\(.fullscreen-toggle.\);"
                  r".*?btn\.hidden = true", code, re.S)
    assert m, "the button is not hidden on an unsupported browser"


def test_icon_btn_hard_hides_when_hidden():
    """The exact cascade bug .general-composer[hidden] and .legend-pop[hidden]
    already had to work around in style.css, now closed for .icon-btn: a bare
    `hidden` attribute does nothing against .icon-btn's author `display:
    inline-flex` rule without an explicit [hidden] override."""
    css = CORE_CSS.read_text()
    assert _hides_when_hidden(css, ".icon-btn"), (
        "nothing makes .icon-btn display:none when hidden — an unsupported "
        "browser would still show a full-screen button that does nothing"
    )
