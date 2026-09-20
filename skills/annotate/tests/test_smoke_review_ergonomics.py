"""Working down a document without the mouse, and knowing where you are in it.

Four things that were missing, and are related more closely than they look:

  * every decision in this page began with a hover over a 26px band, so a
    twelve-block review was twelve hover-and-aim cycles;
  * the controls that band reveals are real <button>s, so Tab could always
    land on them — on something with opacity 0 and pointer-events none, which
    is a control you can focus, cannot see and cannot press;
  * the round dock said what was PENDING and nothing said what was LEFT;
  * and finishing a round was a one-way door in the page, though the daemon
    has always had POST /api/unfinish and the CLI has always exposed it.

Source-string checks matching the repo's other smoke tests. Behaviour was
verified in a browser against a live daemon on a scratch session served from
this checkout: j and k walk the blocks and scroll them into view, c opens a
comment on the block under the cursor and focuses its textarea, f folds only
that block, Escape drops the cursor, none of them fire while typing, the
cursor and Tab both reveal the control strip (opacity 1, pointer-events auto),
the counter went 0/8 → 1/8 → 2/8 as blocks were marked, its click moved the
cursor to the first untouched block, and Reopen round-tripped a really
finished session back to finished=false.
"""
import json
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "script.js").read_text()
CSS = (STATIC / "style.css").read_text()


def _shell_html():
    src = (STATIC / "shell.js").read_text()
    m = re.search(r'export const SHELL_HTML = ("(?:[^"\\]|\\.)*");', src, re.S)
    return json.loads(m.group(1)) if m else src


SHELL = _shell_html()


def _fn(name, src=JS):
    i = src.index(name)
    return src[i:src.index("\n  })();", i)]


class TestKeyboardReview(unittest.TestCase):
    def test_the_four_keys_are_bound(self):
        body = _fn("function initKeyboardReview()")
        for key in ('"j"', '"k"', '"c"', '"f"'):
            self.assertIn(key, body, f"{key} is no longer bound")

    def test_it_never_fires_while_you_are_typing(self):
        # Without this, `c` inside a comment box moves the document instead of
        # typing a letter.
        body = _fn("function initKeyboardReview()")
        self.assertIn("HTMLTextAreaElement", body)
        self.assertIn("isContentEditable", body)
        self.assertIn("if (typing) return;", body)

    def test_it_yields_to_the_chords_and_the_browser(self):
        # j/k/c/f are bare keys, so they must not swallow ⌘J, ⌘K or any
        # browser shortcut that happens to use the same letter.
        body = _fn("function initKeyboardReview()")
        self.assertIn("if (e.metaKey || e.ctrlKey || e.altKey) return;", body)

    def test_comment_goes_through_the_same_door_as_the_button(self):
        # Two entry points into one behaviour: the strip's Comment button and
        # `c`. If `c` opened its own editor the sub-unit scoping, the selection
        # capture and the one-editor-at-a-time rule would all have to be
        # reimplemented, and would drift.
        body = _fn("function initKeyboardReview()")
        self.assertIn('openAnnotation(el, "comment"', body)

    def test_the_cursor_is_one_attribute(self):
        body = _fn("function initKeyboardReview()")
        self.assertIn("kbFocus", body)
        self.assertIn("section.block[data-kb-focus]::before", CSS,
                      "the cursor paints nothing")


class TestTheControlsHaveANonHoverPath(unittest.TestCase):
    def test_focus_and_the_cursor_reveal_the_strip(self):
        reveal = CSS[CSS.index(".card-head:hover .hover-actions"):]
        reveal = reveal[:reveal.index("}")]
        self.assertIn(".card-head:focus-within .hover-actions", reveal,
                      "tabbing to a control still lands on an invisible button")
        self.assertIn("section.block[data-kb-focus] .hover-actions", reveal,
                      "the keyboard cursor no longer reveals its block's controls")

    def test_the_keys_are_documented_where_the_buttons_are(self):
        # A shortcut nobody can discover is a shortcut nobody has — and `/`,
        # `g` and the ⌘K chords were undiscoverable for far longer than these.
        self.assertIn("legend-keys", SHELL)
        for key in (">j<", ">k<", ">c<", ">f<", ">/<", ">g<"):
            self.assertIn(key, SHELL, f"the legend does not mention {key}")
        self.assertIn(".legend-keys kbd", CSS)

    def test_the_taller_legend_is_clamped(self):
        # The keyboard section took it from ~430px to 621px, measured.
        pop = CSS[CSS.index(".legend-pop {"):]
        pop = pop[:pop.index("}")]
        self.assertIn("max-height", pop)
        self.assertIn("overflow-y: auto", pop)


class TestReviewProgress(unittest.TestCase):
    def test_it_reads_state_off_the_dom_rather_than_keeping_its_own(self):
        # data-block-mark already carries every mark AND a pinned comment;
        # data-engaged-type carries a draft in progress. A second copy of that
        # truth would be one more thing to keep in step.
        body = _fn("function initReviewProgress()")
        self.assertIn("dataset.blockMark", body)
        self.assertIn("dataset.engagedType", body)

    def test_nothing_has_to_remember_to_refresh_it(self):
        body = _fn("function initReviewProgress()")
        self.assertIn("MutationObserver", body)
        self.assertIn('attributeFilter: ["data-block-mark", "data-engaged-type"]', body)

    def test_it_jumps_to_the_next_untouched_block(self):
        body = _fn("function initReviewProgress()")
        self.assertIn("focusBlock", body,
                      "the counter no longer takes you anywhere")
        self.assertIn("focusBlock:", JS,
                      "AnnotateKeyboard does not expose focusBlock for it")

    def test_the_pill_and_the_tick_are_rendered_and_styled(self):
        self.assertIn('id="review-progress"', SHELL)
        self.assertIn(".review-progress", CSS)
        # The tick is inline after the title, never absolute: the card sets
        # overflow:hidden and .card-head is position:static, so an absolute
        # one was clipped at the card edge — measured at x=1219 on a card
        # ending at 1206.
        self.assertIn('section.block[data-review-state="touched"] .card-title::after', CSS)
        self.assertNotIn('[data-review-state="touched"] .card-head::after', CSS)


class TestReopen(unittest.TestCase):
    def test_done_becomes_reopen_when_the_round_is_closed(self):
        body = _fn("function trackFinishedState()")
        self.assertIn('"Reopen"', body)
        self.assertIn("session-finished", body)

    def test_it_posts_to_the_route_the_daemon_already_had(self):
        handler = JS[JS.index('const doneBtn = document.getElementById("done-btn")'):]
        handler = handler[:handler.index("trackFinishedState")]
        self.assertIn('fetch("api/unfinish", { method: "POST" })', handler)

    def test_only_finishing_asks_first(self):
        # Finishing tells Claude to resume, so it confirms. Reopening only puts
        # the controls back, and the submitted round stays submitted.
        handler = JS[JS.index('const doneBtn = document.getElementById("done-btn")'):]
        handler = handler[:handler.index("trackFinishedState")]
        unfinish_at = handler.index("api/unfinish")
        confirm_at = handler.index("window.confirm")
        self.assertLess(unfinish_at, confirm_at,
                        "the reopen path now goes through the confirm dialog")
