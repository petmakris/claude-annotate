"""Getting a narration line from the daemon to the panel.

compat.js:207 strips `__`-prefixed anchors out of the version map before
script.js sees it — correct, and it means script.js never hears about a
progress write. So the panel needs its own signal, and compat.js already has
the pattern: it dispatches `annotate:busy` at :189, which subunits.js:836
consumes.

The second edit is the sharp one. compat.js clears the page lock on ANY item
change, as a fallback for a daemon too old to send `event-acked`. For the
progress anchor that rule is exactly backwards: Claude's first narration line
would unlock the page and dismiss the very ribbon the narration captions.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
COMPAT = (STATIC / "compat.js").read_text()

ANCHOR = "__progress__"


class TestTheUnlockRuleExemptsTheTrail(unittest.TestCase):
    def test_the_anchor_has_one_spelling(self):
        self.assertIn('const PROGRESS = "%s"' % ANCHOR, COMPAT,
                      "the anchor is retyped instead of named once")

    def test_the_guard_exists(self):
        self.assertIn("ev.anchor === PROGRESS", COMPAT,
                      "nothing distinguishes a progress write from a block write")

    def test_the_guard_comes_BEFORE_the_unlock(self):
        # Ordering is the whole property. A guard placed after the unlock line
        # would not prevent the unlock; it would just run afterwards.
        guard = COMPAT.index("ev.anchor === PROGRESS")
        unlock = COMPAT.index('ev.kind === "item" && busyLocal')
        self.assertLess(guard, unlock,
                        "a progress write still clears the page lock")

    def test_the_lock_is_still_cleared_by_an_ordinary_item(self):
        # The fallback this rule exists for must survive the exemption.
        self.assertIn('ev.kind === "item" && busyLocal', COMPAT)
        self.assertIn("setBusyLocal(false)", COMPAT)


class TestThePanelGetsItsOwnSignal(unittest.TestCase):
    def test_a_progress_delta_is_re_broadcast(self):
        self.assertIn("annotate:progress", COMPAT)

    def test_it_follows_the_event_the_page_already_uses(self):
        # annotate:busy is the precedent (compat.js:189, consumed by
        # subunits.js:836). One pattern, not two.
        self.assertIn('new CustomEvent("annotate:progress"', COMPAT)

    def test_the_signal_is_scoped_to_the_progress_anchor(self):
        # Dispatched from inside the guard, not for every item change.
        idx = COMPAT.index("annotate:progress")
        window = COMPAT[max(0, idx - 400):idx]
        self.assertIn("ev.anchor === PROGRESS", window,
                      "every item change dispatches a progress event")


SCRIPT = (STATIC / "script.js").read_text()
HOOKS = Path(__file__).resolve().parents[1] / "hooks"


class TestTheDeadCaptionPathIsGone(unittest.TestCase):
    """applyProgress captioned the ribbon from a map keyed by event id, fed by
    `data.progress`. compat.js has never carried that key, so it has been a
    no-op since the cutover. progress.js replaces it."""

    def test_the_function_is_deleted(self):
        self.assertNotIn("applyProgress", SCRIPT)

    def test_nothing_reads_the_key_that_never_existed(self):
        self.assertNotIn("data.progress", SCRIPT)

    def test_the_dormant_hook_is_gone(self):
        self.assertFalse((HOOKS / "progress_publish.py").exists(),
                         "a file documenting a feature nobody can reach")

    def test_the_block_caption_still_has_an_owner(self):
        # .updating-label is not being dropped — it moved to progress.js.
        progress_js = (STATIC / "progress.js").read_text()
        self.assertIn("updating-label", progress_js)
