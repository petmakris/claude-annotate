"""Structural guard: nothing optional may block the page from booting.

entry.js loads the page in a fixed order, and everything that makes the
document interactive — compat.js, script.js, subunits.js — is loaded at the
END of it. Anything awaited before that line is on the critical path of the
whole page, whether or not the page needs it.

The write probe is not something the page needs. It gates one optional
control ("open this in my editor"), and it used to be awaited. Every open
document holds an SSE stream, a browser allows six connections per origin,
and a request that cannot get one waits without ever failing — so on a busy
origin boot stopped at that await. The prose above it had already rendered,
so the document looked completely normal and simply ignored the pointer:
no hover controls, no way to comment, nothing to explain why.

Source-string checks matching the repo's other smoke tests; live behavior is
covered browser-side in the webcompanion repo's test_browser_runtime.py.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENTRY_JS = REPO / "skills" / "annotate" / "static" / "entry.js"


def test_the_write_probe_is_not_awaited_during_boot():
    src = ENTRY_JS.read_text()
    assert "whoami" in src, \
        "entry.js no longer probes for write access at all — retarget this test"
    assert not re.search(r"await\s+fetch\(\s*[\"']/api/whoami", src), \
        ("entry.js awaits the write probe again: a stalled probe now stops "
         "compat.js and script.js from ever loading, and the page renders "
         "the document with no controls on it")


def test_the_interactive_scripts_load_after_the_probe_is_fired():
    """The ordering the fix depends on: the probe is started, and the
    scripts that make the page interactive do not wait behind it."""
    src = ENTRY_JS.read_text()
    probe = src.find("/api/whoami")
    compat = src.find('addScript(asset("compat.js"))')
    assert probe != -1 and compat != -1, "entry.js boot sequence changed shape"
    assert probe < compat, \
        "the probe moved below the script loading it was meant to stop blocking"
