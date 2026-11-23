"""The path matcher runs every case of match_cases.json, the file the Java matcher runs too."""
import json
import unittest
from pathlib import Path

from skills.app_map import paths

CASES = json.loads((Path(__file__).parent / "match_cases.json").read_text())


class MatchCases(unittest.TestCase):
    def test_every_pattern_case(self):
        for c in CASES["cases"]:
            with self.subTest(pattern=c["pattern"], path=c["path"]):
                self.assertEqual(paths.matches(c["pattern"], c["path"]), c["match"])

    def test_last_match_wins(self):
        for c in CASES["last_match_wins"]:
            with self.subTest(rules=c["rules"], path=c["path"]):
                self.assertEqual(paths.last_match(c["rules"], c["path"]), c["winner"])

    def test_the_file_has_cases(self):
        self.assertGreater(len(CASES["cases"]), 40)
        self.assertGreater(len(CASES["last_match_wins"]), 3)
