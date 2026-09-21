"""A magnifier that becomes the whole bar, and a filter that did not change.

The field is never removed from the DOM — it is collapsed to the width of its
own icon. That is the entire reason search.js needed four lines rather than a
rewrite: the index, the `/` shortcut, the Esc handler and the mutation
observer all still have the element they were written against.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "search.js").read_text()
CSS = (STATIC / "style.css").read_text()


class TestTheBarKnowsItIsSearching(unittest.TestCase):
    def test_focus_and_a_live_query_both_count(self):
        self.assertIn("syncTakeover", JS)
        self.assertIn("document.activeElement === input", JS)
        self.assertIn("input.value.trim().length", JS)

    def test_it_writes_the_attribute_the_stylesheet_reads(self):
        self.assertIn('dataset.searching', JS)
        self.assertIn('.page-header[data-searching="1"]', CSS)


class TestTheFieldCollapses(unittest.TestCase):
    def test_the_resting_width_is_one_icon(self):
        rule = CSS[CSS.index(".header-search {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("26px", rule)

    def test_it_takes_the_whole_bar_when_searching(self):
        self.assertIn('.page-header[data-searching="1"] .header-search', CSS)
        self.assertIn('.page-header[data-searching="1"] .header-title', CSS)

    def test_the_slash_hint_does_not_sit_on_the_magnifier(self):
        # At 26px the hint and the icon occupy the same box, and the hint
        # paints on top. It only ever meant "press / to open this", so it has
        # no job in the one state that has no room for it.
        self.assertIn('.page-header:not([data-searching="1"]) .search-kbd', CSS)


class TestTheFilterWasNotTouched(unittest.TestCase):
    """Four lines were added to init(). Nothing else in this file moved."""

    def test_the_slash_shortcut_still_exists(self):
        self.assertIn('e.key === "/" && !inField', JS)

    def test_escape_still_clears_and_blurs(self):
        self.assertIn('e.key === "Escape" && active === input', JS)
        self.assertIn("input.blur()", JS)

    def test_there_is_still_exactly_one_result_count(self):
        # search.js already renders "Showing N of M blocks" into main.prose.
        # A second count in the bar would be two answers to one question.
        self.assertIn('"Showing " + matched.size + " of "', JS)
        self.assertNotIn("search-count-bar", CSS)
