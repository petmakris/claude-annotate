"""The watcher signal, split in two.

The pill said "Watching" and had room for nothing else — not what watching
means, not how long ago the session was last seen, and not the command that
would attach one. The dot on the menu icon carries the state at a glance; the
status block at the top of the menu carries the sentence, and absorbs the
resume popover, which was the same subject behind a second button.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
ENTRY = (STATIC / "entry.js").read_text()
CSS = (STATIC / "style.css").read_text()


class TestTheBadgeIsGone(unittest.TestCase):
    def test_entry_no_longer_reaches_for_it(self):
        self.assertNotIn("watcher-badge", ENTRY)
        self.assertNotIn("makeWatcherBadgeClickable", ENTRY)


class TestTheDotCarriesTheState(unittest.TestCase):
    def test_it_paints_the_menu_button(self):
        self.assertIn('getElementById("menu-toggle")', ENTRY)
        self.assertIn("watcher-live", ENTRY)
        self.assertIn("watcher-stale", ENTRY)

    def test_the_dot_has_a_rule_for_each_state(self):
        self.assertIn(".menu-btn.watcher-live::after", CSS)
        self.assertIn(".menu-btn.watcher-stale::after", CSS)


class TestTheBlockCarriesTheSentence(unittest.TestCase):
    def test_it_writes_a_title_and_a_subtitle(self):
        self.assertIn('getElementById("menu-status-title")', ENTRY)
        self.assertIn('getElementById("menu-status-sub")', ENTRY)

    def test_the_staleness_threshold_did_not_move(self):
        # 180s is the daemon's own convention and the IntelliJ plugin's
        # REAP_AFTER_MS. This reads a fact everyone already agrees on.
        self.assertIn("WATCHER_STALE_MS = 180_000", ENTRY)


class TestTheResumeCommandCameWithIt(unittest.TestCase):
    def test_the_popover_and_its_toggle_are_gone(self):
        self.assertNotIn("resume-toggle", ENTRY)
        self.assertNotIn(".resume-pop {", CSS)

    def test_the_command_renders_in_the_status_block(self):
        self.assertIn('getElementById("menu-resume")', ENTRY)
        self.assertIn('getElementById("resume-cmd")', ENTRY)

    def test_it_is_shown_only_when_nothing_is_attached(self):
        # An attached session needs no instructions for attaching one.
        self.assertIn("resumeEl.hidden", ENTRY)
