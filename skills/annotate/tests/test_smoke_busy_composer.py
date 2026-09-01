"""Structural guards: the general composer must never silently swallow input.

Three invariants born from a real data-loss postmortem (2026-06-10/11):
  1. The busy lock must NOT make the general composer click-inert — sends
     queue server-side instead of being dropped on the floor.
  2. Sending while busy must say so ("queued"), not pretend nothing happened.
  3. Enter inserts a newline; only Cmd/Ctrl+Enter sends — same convention as
     the block comment cards, so a numbered answer can't fire prematurely.

Source-string checks matching the repo's other smoke tests.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STYLE_CSS = REPO / "skills" / "annotate" / "static" / "style.css"
SCRIPT_JS = REPO / "skills" / "annotate" / "static" / "script.js"
# The page shell and its asset list used to be printed by server.py; they now
# live in the renderer the daemon loads — shell.js for the markup, entry.js for
# which stylesheets and scripts are pulled in and in what order. These tests
# assert against the page's source either way, so they read both.
class _PageSource:
    """The page's markup and its asset list, as a single string to assert on.

    shell.js holds the markup as a JSON-encoded JS string literal, so reading
    the file raw would hand these tests `id=\\"block-search\\"` and every
    markup assertion would fail on the escaping rather than on the thing it
    is checking. The literal is decoded back to real HTML here, and entry.js
    (which lists the stylesheets and scripts, in load order) is appended.
    """

    def __init__(self, repo):
        static = repo / "skills" / "annotate" / "static"
        self._shell = static / "shell.js"
        self._entry = static / "entry.js"

    def read_text(self, *a, **k):
        import json
        src = self._shell.read_text(*a, **k)
        m = re.search(r"export const SHELL_HTML = (\".*\");", src, re.S)
        html = json.loads(m.group(1)) if m else src
        return html + "\n" + self._entry.read_text(*a, **k)


SERVER_PY = _PageSource(REPO)


def test_busy_lock_does_not_freeze_general_composer():
    css = STYLE_CSS.read_text()
    assert "body.is-busy .general-composer" not in css, (
        "style.css still pointer-locks the general composer while busy — "
        "Send clicks during a multi-minute update are silently swallowed"
    )


def test_general_send_reports_queued_while_busy():
    src = SCRIPT_JS.read_text()
    assert "queued" in src, (
        "script.js general send() has no queued-while-busy feedback"
    )


def test_general_composer_enter_is_newline_not_send():
    src = SCRIPT_JS.read_text()
    assert 'e.key === "Enter" && !e.shiftKey' not in src, (
        "general composer still submits on plain Enter — newline intent "
        "becomes a premature partial send"
    )
    # Cmd/Ctrl+Enter must be the send chord in the general composer too.
    assert src.count('ev.metaKey || ev.ctrlKey') + src.count('e.metaKey || e.ctrlKey') >= 2, (
        "expected both the card composer and the general composer to gate "
        "Enter-send behind meta/ctrl"
    )


def test_general_composer_shows_send_chord_hint():
    page = SERVER_PY.read_text()
    assert "general-hint" in page, (
        "serve_root HTML carries no send-chord hint for the general composer"
    )
