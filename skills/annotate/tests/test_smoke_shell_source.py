"""shell.js must stay readable, and must keep exporting the same markup.

The markup used to live on ONE source line as a JSON-encoded string: 8.6KB
unreadable in a diff, and unmergeable in practice. Two branches that each added
a single control to the header both edited "line 8" and conflicted on a 7KB
escaped string — measured, on exactly that pair, and resolved by re-running the
insertions rather than by editing the string.

It is now a line-continued template literal. Every source line ends with a
backslash, so no newline and no indentation enters the value: the string is
byte-identical to the old one, and the file is ~83 diffable lines.

Two things have to stay true, and neither is obvious from reading the file.
"""
import re
import unittest
from pathlib import Path

from .shell_source import SHELL_JS, shell_html


class TestShellSourceIsReadable(unittest.TestCase):
    def test_the_markup_is_not_on_one_line(self):
        src = SHELL_JS.read_text()
        literal = re.search(r"export const SHELL_HTML = `(.*?)`;", src, re.S)
        self.assertIsNotNone(
            literal, "SHELL_HTML is not a template literal any more — if it went "
                     "back to a one-line JSON string, every UI branch conflicts "
                     "on it again")
        self.assertGreater(len(literal.group(1).splitlines()), 40,
                           "the markup is back on a handful of lines")

    def test_every_source_line_is_continued(self):
        """The property the whole rewrite rests on.

        A line inside the literal that does not end in a backslash puts a real
        newline into the page's markup, and the indentation of the next line
        goes in with it — inside a <span> that is a visible change, and the
        page would still load, so nothing else here would catch it.

        Asserted on the SOURCE rather than by looking for stray whitespace in
        the value: the markup legitimately contains 8 runs of double space (the
        composer section came that way from the server that used to print it),
        so "no double spaces" is not a property this file can claim.
        """
        src = SHELL_JS.read_text()
        literal = re.search(r"export const SHELL_HTML = `(.*?)`;", src, re.S).group(1)
        lines = literal.split("\n")
        for i, line in enumerate(lines[:-1]):
            self.assertTrue(line.endswith("\\"),
                            f"line {i + 1} of the literal is not continued, so a "
                            f"newline and the next line's indentation land in "
                            f"the markup: {line[-60:]!r}")
        self.assertNotIn("\n", shell_html(), "a newline reached the markup")

    def test_the_shell_still_carries_every_control_the_page_needs(self):
        # A byte-for-byte snapshot would fail on every legitimate UI change, so
        # this asserts the inventory instead: the ids the page code reaches for.
        html = shell_html()
        for control in ("block-search", "settings-toggle", "settings-pop",
                        "settings-groups", "settings-reset", "palette-pop",
                        "review-progress", "highlighter-toggle", "highlighter-clear",
                        "fullscreen-toggle",
                        "composer-toggle", "legend-toggle", "legend-pop",
                        "general-composer", "general-input", "general-send",
                        "export-btn", "done-btn", "hdr-title", "hdr-respid"):
            self.assertIn(f'id="{control}"', html, f"the shell lost #{control}")
        self.assertIn('<main class="prose">', html)

    def test_one_decoder_not_eleven(self):
        # Eleven test modules each carried a copy of the regex that undoes the
        # encoding, so changing the encoding once meant eleven edits.
        tests = Path(__file__).resolve().parent
        needle = "SHELL_HTML" + " = ("      # split, or this file matches itself
        offenders = [f.name for f in tests.glob("test_*.py")
                     if f.name != Path(__file__).name and needle in f.read_text()]
        self.assertEqual(offenders, [],
                         f"these decode shell.js by hand instead of using "
                         f"shell_source.shell_html(): {offenders}")
