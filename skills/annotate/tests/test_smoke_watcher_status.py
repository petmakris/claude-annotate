"""The watcher signal, split in two.

The pill after the title carries the state in one word, always in view. A
click opens its popover, which carries the sentence: what watching means, how
long ago the session was last seen, and the command that would attach one.
"""
import unittest
from pathlib import Path

from .shell_source import shell_html
from skills.annotate.tests.page_source import STYLE_CSS

STATIC = Path(__file__).resolve().parents[1] / "static"
ENTRY = (STATIC / "entry.js").read_text()
CSS = STYLE_CSS.read_text()
SHELL = shell_html()


class TestTheBadgeIsGone(unittest.TestCase):
    def test_entry_no_longer_reaches_for_it(self):
        self.assertNotIn("watcher-badge", ENTRY)
        self.assertNotIn("makeWatcherBadgeClickable", ENTRY)


class TestTheDotCarriesTheState(unittest.TestCase):
    def test_it_paints_the_status_pill(self):
        self.assertIn('getElementById("status-toggle")', ENTRY)
        self.assertIn('getElementById("status-word")', ENTRY)
        self.assertIn("watcher-live", ENTRY)
        self.assertIn("watcher-stale", ENTRY)

    def test_the_dot_has_a_rule_for_each_state(self):
        self.assertIn(".status-pill.watcher-live {", CSS)
        self.assertIn(".status-pill.watcher-stale {", CSS)

    def test_the_state_reaches_the_buttons_accessible_name(self):
        # A colour is not a signal for everyone, and the dot's only worded
        # sibling is inside the panel and aria-hidden. aria-label BEATS title
        # in the accessible-name computation, so writing only the title left
        # the button announcing the static "Menu" in every state. Measured in
        # test_browser_review.py; this is the deletion guard.
        self.assertIn('btn.setAttribute("aria-label", btn.title)', ENTRY)

    def test_a_change_of_state_is_announced(self):
        # On the word in the pill, which is always in view; the popover's
        # title is hidden until opened, and a hidden live region says nothing.
        self.assertIn('id="status-word" aria-live="polite"', SHELL)


class TestTheBlockCarriesTheSentence(unittest.TestCase):
    def test_it_writes_a_title_and_a_subtitle(self):
        self.assertIn('getElementById("status-title")', ENTRY)
        self.assertIn('getElementById("status-sub")', ENTRY)

    def test_the_staleness_threshold_did_not_move(self):
        # 180s is the daemon's own convention and the IntelliJ plugin's
        # REAP_AFTER_MS. This reads a fact everyone already agrees on.
        self.assertIn("WATCHER_STALE_MS = 180_000", ENTRY)


class TestAStoppedWatcherIsNotWatching(unittest.TestCase):
    # A stopped watch leaves its heartbeat in place (the IDE plugin reads a
    # missing one as "just armed"), so a fresh heartbeat alone kept the dot
    # on Watching for up to 180s after TaskStop. The daemon reports the stop
    # as `watcher_stopped_at`, and the page must read it.
    def test_the_poll_field_reaches_the_painter(self):
        self.assertIn("paintWatcherHealth(data.watcher_seen_at, data.watcher_stopped_at)", ENTRY)

    def test_a_stop_rules_out_live(self):
        self.assertIn("const live = lastStoppedAt == null && seenAt != null", ENTRY)


class TestTheResumeCommandCameWithIt(unittest.TestCase):
    def test_the_popover_and_its_toggle_are_gone(self):
        self.assertNotIn("resume-toggle", ENTRY)
        self.assertNotIn(".resume-pop {", CSS)

    def test_the_command_renders_in_the_status_block(self):
        self.assertIn('getElementById("status-resume")', ENTRY)
        self.assertIn('getElementById("resume-cmd")', ENTRY)

    def test_it_is_shown_only_when_nothing_is_attached(self):
        # An attached session needs no instructions for attaching one.
        self.assertIn("resumeEl.hidden", ENTRY)
