"""The panel's shape, at the level source strings can see.

The behaviour that matters — lines arriving, the newest staying visible, the
collapse on done, and nothing at all for a guest — is browser-tested in
test_browser_review.py. These are the structural guarantees.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "progress.js").read_text() if (STATIC / "progress.js").exists() else ""
CSS = (STATIC / "style.css").read_text()
ENTRY = (STATIC / "entry.js").read_text()
CORE = (STATIC / "core.css").read_text()


def _brace_body(src, open_idx):
    """The text strictly between the '{' at `open_idx` and its matching '}'."""
    assert src[open_idx] == "{"
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx + 1:i]
    raise AssertionError("unbalanced braces in " + src[open_idx:open_idx + 80])


def _interval_bodies(js):
    """The body of every function a `setInterval(...)` call in `js` runs.

    The callback can be written two ways, and a caller regex that only
    matches one of them proves nothing about the other:

      setInterval(() => { ... }, 1000)   -- inline, the body is right there
      setInterval(tick, 1000)            -- a bare reference to a function
                                             declared elsewhere in the file

    progress.js uses the second form (`ticking = setInterval(tick, 1000)`),
    so a check that only reads the call site sees an identifier and nothing
    of what it does -- exactly the gap that let a `fetchJSON` inside `tick`
    stay invisible to the original version of this test.
    """
    bodies = []

    # Bare identifier: resolve it to a `function <name>(...) { ... }`
    # declaration elsewhere in the file and take that function's body.
    for m in re.finditer(r"setInterval\(\s*([A-Za-z_$][\w$]*)\s*,\s*[^)]+\)", js):
        name = m.group(1)
        decl = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", js)
        if decl:
            bodies.append(_brace_body(js, decl.end() - 1))

    # Inline function expression or arrow function passed directly.
    for m in re.finditer(
            r"setInterval\(\s*(?:function\b[^{]*|\([^)]*\)\s*=>\s*)\{", js):
        bodies.append(_brace_body(js, m.end() - 1))

    return bodies


class TestItIsLoaded(unittest.TestCase):
    def test_progress_js_is_in_the_entry_list(self):
        self.assertIn('"progress.js"', ENTRY)

    def test_it_loads_after_script_js(self):
        # It mounts relative to .page-header, which the shell paints, and it
        # reads window.WebCompanion, which compat.js installs.
        self.assertLess(ENTRY.index('"script.js"'), ENTRY.index('"progress.js"'))


class TestItListensRatherThanPolls(unittest.TestCase):
    def test_it_consumes_the_broadcast(self):
        self.assertIn('addEventListener("annotate:progress"', JS)

    def test_it_reads_the_item_through_the_route_compat_already_serves(self):
        self.assertIn('raw?block=__progress__', JS)

    def test_it_never_polls_the_daemon(self):
        # A poll would work and would also be a second source of truth for
        # something the stream already pushes. The panel does own ONE timer —
        # the elapsed clock — which is local and reads nothing. Resolve every
        # setInterval callback to its actual function body (named references
        # included — see _interval_bodies) before checking it, rather than
        # pattern-matching the call site, which for `setInterval(tick, 1000)`
        # sees only the identifier and nothing of what `tick` does.
        bodies = _interval_bodies(JS)
        self.assertTrue(bodies, "no setInterval callback body could be resolved")
        for body in bodies:
            self.assertNotIn("fetchJSON", body,
                             "the panel polls the daemon on a timer")


class TestTheGuestIsNotSHOWNTheTrail(unittest.TestCase):
    """Not shown, not protected.

    The trail names file paths and repository structure, and the document is
    what the author chose to share while how it was produced is not — but both
    checks below are about RENDERING. The daemon's `GET /s/<sid>/items` is
    unauthenticated and returns `__`-prefixed anchors to anyone holding the
    link, and compat.js fetches it on every page load, so a guest's browser
    already has the trail. Making the daemon withhold it is a `webcompanion`
    change (spec decision 7, amended); what keeps a secret out of a guest's
    hands here is the contract rule that narration never carries output,
    secrets or tokens.
    """

    def test_the_panel_is_gated_on_writability(self):
        # progress.js must consult the write-capability verdict, not merely
        # mention the word: `resolveWritable` alone satisfies a bare substring
        # search while gating nothing.
        self.assertRegex(JS, r"function writable\(\)")
        self.assertRegex(JS, r"wc\.writable")
        for fn in ("function paint(", "async function refresh("):
            body = JS[JS.index(fn):]
            body = body[:body.index("\n  }\n")]
            self.assertIn("writable()", body,
                          f"{fn.strip()} paints without asking whether this reader may see it")

    def test_the_stylesheet_hides_it_too(self):
        # Belt and braces for the RENDER, not a second line of defence for the
        # data: a JS gate that regresses must not leave the panel drawn on a
        # shared link.
        self.assertIn("body.read-only #progress-panel", CSS)


class TestTheFeedPinsToTheNewestLine(unittest.TestCase):
    def test_it_scrolls_the_feed(self):
        # Measured in the mockup: with a max-height and no scroll management
        # the current line is the one clipped off the bottom.
        self.assertIn("scrollTop", JS)
        self.assertIn("scrollHeight", JS)

    def test_the_feed_has_a_bounded_height_to_scroll_within(self):
        rule = CSS[CSS.index("#progress-feed"):]
        rule = rule[:rule.index("}")]
        self.assertIn("max-height", rule)
        self.assertIn("overflow-y: auto", rule)


class TestItIsQuietButStillReadsAsALock(unittest.TestCase):
    def test_the_panel_keeps_an_accent_edge(self):
        # The accent ribbon was the only thing saying "you cannot submit
        # another round". The panel is quiet; the edge keeps the lock legible.
        rule = CSS[CSS.index("#progress-panel {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("border-left", rule)
        self.assertIn("var(--accent)", rule)

    def test_nothing_was_added_to_the_shared_core_stylesheet(self):
        self.assertNotIn("#progress-panel", CORE)
