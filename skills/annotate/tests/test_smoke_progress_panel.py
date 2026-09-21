"""The panel's shape, at the level source strings can see.

The behaviour that matters — lines arriving, the newest staying visible, the
collapse on done, and nothing at all for a guest — is browser-tested in
test_browser_review.py. These are the structural guarantees.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "progress.js").read_text() if (STATIC / "progress.js").exists() else ""
CSS = (STATIC / "style.css").read_text()
ENTRY = (STATIC / "entry.js").read_text()
CORE = (STATIC / "core.css").read_text()


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
        # the elapsed clock — which is local and reads nothing.
        import re as _re
        for m in _re.finditer(r"setInterval\((.{0,400}?)\}, \d+\)", JS, _re.S):
            self.assertNotIn("fetchJSON", m.group(1),
                             "the panel polls the daemon on a timer")


class TestTheGuestSeesNothing(unittest.TestCase):
    def test_the_panel_is_gated_on_writability(self):
        # The trail names file paths and repository structure. The document is
        # what the author chose to share; how it was produced is not.
        self.assertIn("writable", JS)

    def test_the_stylesheet_hides_it_too(self):
        # Belt and braces: a JS gate that regresses must not silently expose
        # the trail on a shared link.
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
