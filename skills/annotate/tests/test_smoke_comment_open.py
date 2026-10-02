"""The comment icon must be able to open a comment.

It could not. openAnnotation creates the draft, saves it, and calls
renderComments() to draw its card — and renderComments() pruned every draft
that isEmptyDraft() matched. A draft that has just been opened has nothing
typed in it yet, so it matched, and the card was deleted before it was ever
built. Measured in a browser: one click on the comment icon wrote the draft
to localStorage and wrote "{}" back over it in the same tick, produced zero
DOM mutations beyond the hover strip's own data-visible, and raised nothing
in the console. The page did not flicker; the icon simply did nothing.

Empty drafts are still dropped. Only the two callers that can tell an
abandoned draft from a live one do it: openAnnotation, before it opens a
different target, and loadDrafts, on the way in.

Source-string checks matching the repo's other smoke tests; the behaviour
itself was verified in a real browser against a live daemon (card opens,
textarea focused, typed text survives, block paints its engaged bar).
"""
import re
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "static" / "script.js").read_text()


def _fn(name, src=SCRIPT):
    """The body of a top-level `function name(...)` in script.js."""
    i = src.index("function %s(" % name)
    return src[i:src.index("\n  }", i)]


def _code(text):
    """The same body with `//` comment lines removed.

    These functions carry long comments that name the very identifiers being
    asserted on — the fix for this bug added one that says isEmptyDraft "had
    to come out" — so a bare substring check finds the prose and reports the
    bug as still present. Caught by running this test against both trees.
    """
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


class TestOpeningAComment(unittest.TestCase):
    def test_rendering_a_comment_does_not_delete_the_one_being_opened(self):
        body = _code(_fn("renderComments"))
        prune = body[:body.index("if (pruned)")]
        self.assertNotIn("isEmptyDraft", prune,
                         "renderComments prunes empty drafts again — that "
                         "deletes every comment at the moment it is opened, "
                         "and the icon goes back to doing nothing")

    def test_an_orphan_draft_is_still_pruned(self):
        # The prune's real job: a draft whose block Claude has since removed
        # can never render a card, so it can never be closed either.
        prune = _code(_fn("renderComments"))
        self.assertIn("!a.block_id", prune)
        self.assertIn("section.block[data-block-id=", prune)

    def test_an_empty_draft_still_does_not_survive_a_reload(self):
        # The rule the prune was enforcing, moved somewhere that cannot
        # mistake a live draft for an abandoned one.
        self.assertIn("isEmptyDraft", _code(_fn("loadDrafts")),
                      "an empty draft now outlives the session that made it, "
                      "painting an engaged bar on a block nobody is commenting on")

    def test_opening_a_comment_still_saves_renders_and_focuses(self):
        body = _code(_fn("openAnnotation"))
        order = [body.find(s) for s in
                 ("annotations[id] = annot", "saveDrafts()", "renderComments()", "focusComment(id)")]
        self.assertTrue(all(i != -1 for i in order),
                        "openAnnotation lost one of its four closing steps")
        self.assertEqual(order, sorted(order),
                         "openAnnotation's closing steps are out of order")

    def test_only_one_editor_opens_at_a_time(self):
        # Deliberate, and unchanged by the fix: a second target is refused
        # while an unsaved draft is open. Verified in a browser — the second
        # block's icon leaves the first card standing and opens nothing.
        body = _code(_fn("openAnnotation"))
        # The GUARD, not one spelling of it: this asserted the single-line
        # `... .length > 0) return;` and broke the moment the refusal grew a
        # body telling the user where the open editor is — a change that kept
        # the rule exactly as it was.
        self.assertTrue(re.search(r"if \(Object\.keys\(annotations\)\.length > 0\)", body),
                        "the single-flight guard on the comment editor is gone")
        self.assertIn("return;", body[body.index("Object.keys(annotations).length > 0"):])


class TestARefusalIsVisible(unittest.TestCase):
    """One editor at a time is the rule; refusing in silence was the bug.

    A comment icon that does nothing when clicked is indistinguishable from a
    broken one — which is what it was mistaken for and reported as. The rule
    stands, but the refusal now scrolls the open card into view, pulses it and
    puts the caret in it, so the answer to "why did nothing happen" is the
    card itself.
    """

    def test_the_refusal_points_at_the_open_card(self):
        body = _code(_fn("openAnnotation"))
        self.assertIn("revealOpenDraft()", body,
                      "the single-flight guard returns silently again")
        reveal = _code(_fn("revealOpenDraft"))
        self.assertIn("scrollIntoView", reveal)
        self.assertIn("is-calling", reveal)
        self.assertIn("focus(", reveal)

    def test_the_pulse_can_fire_twice_in_a_row(self):
        # Re-adding a class an element already has animates nothing, so a
        # second refusal would be silent again — the exact bug, one layer down.
        reveal = _code(_fn("revealOpenDraft"))
        remove_at = reveal.index('classList.remove("is-calling")')
        reflow_at = reveal.index("offsetWidth")
        add_at = reveal.index('classList.add("is-calling")')
        self.assertTrue(remove_at < reflow_at < add_at,
                        "the animation is not restarted between refusals")

    def test_the_pulse_is_styled_and_respects_reduced_motion(self):
        css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()
        self.assertIn(".comment-card.is-calling", css)
        self.assertIn("@keyframes card-calling", css)
        reduced = css[css.index("prefers-reduced-motion"):]
        self.assertIn("is-calling", reduced[:400],
                      "the pulse ignores prefers-reduced-motion")
