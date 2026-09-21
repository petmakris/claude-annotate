"""Narration has to be a step, not a suggestion.

The bug being fixed is silence. An instruction to "narrate as you go" is the
same instruction the page already effectively had, and it produced five-minute
gaps. So the contract is numbered steps in the event flow, with the same
standing as acknowledging the event.
"""
import re
import unittest
from pathlib import Path

REFS = Path(__file__).resolve().parents[1] / "references"
EVENTS = (REFS / "handling-events.md").read_text()
SKILL = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()

CMD = "skills.annotate.progress"


def _event_sections():
    """Every `### WEBCOMPANION_EVENT...` subsection, as (title, text).

    Scoped rather than searched whole-file: a substring check over the whole
    document passes on a contract that mandates narration twice per round and
    says nothing in between, which is exactly the silence being fixed.
    """
    heads = [m.start() for m in re.finditer(r"^### `WEBCOMPANION_EVENT", EVENTS, re.M)]
    assert len(heads) >= 3, "the event sections moved"
    bounds = heads + [len(EVENTS)]
    return [(EVENTS[start:bounds[i + 1]].splitlines()[0], EVENTS[start:bounds[i + 1]])
            for i, start in enumerate(heads)]


class TestEveryEventPathNarrates(unittest.TestCase):
    def test_the_command_is_documented_with_its_flags(self):
        self.assertIn(CMD, EVENTS)
        self.assertIn("--text", EVENTS)
        self.assertIn("--done", EVENTS)

    def test_every_documented_invocation_carries_its_pythonpath(self):
        # The command runs from whatever cwd the turn is in. Bare, it raises
        # ModuleNotFoundError — and because narration is contractually allowed
        # to fail without failing the turn, it fails SILENTLY and the reader
        # gets the spinner back. Every other `python3 -m skills.annotate.*`
        # invocation in the reference files carries the prefix; these must too.
        bare = [line for line in EVENTS.splitlines()
                if CMD in line and "--sid" in line
                and 'PYTHONPATH="$PLUGIN_ROOT"' not in line]
        self.assertEqual([], bare, "these narration commands cannot import themselves")

    def test_the_file_says_where_plugin_root_comes_from(self):
        # A reader of this file alone has to be able to run the command, the
        # way pushing.md and publishing.md already let one.
        self.assertIn("## Resolve the plugin root", EVENTS)
        self.assertIn('PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-', EVENTS)

    def test_each_event_subsection_carries_a_narration_step(self):
        # One per handled event type. A path that does not narrate is a path
        # that goes silent, which is the whole defect.
        for title, section in _event_sections():
            self.assertIn(CMD, section, f"{title} never narrates")

    def test_each_event_subsection_makes_before_each_work_a_numbered_step(self):
        # Decision 9: narration has the same standing as acknowledging the
        # event or re-pushing the document, "not an aside in prose". Only the
        # receipt line and the `--done` line shipped as numbered steps, which
        # yields one line, then silence, then a summary — the spec's own
        # stated failure mode. The obligation has to be IN the list.
        for title, section in _event_sections():
            numbered = [l for l in section.splitlines() if re.match(r"^\d+\. ", l)]
            self.assertTrue(numbered, f"{title} has no numbered steps at all")
            before = [l for l in numbered
                      if re.search(r"(?i)narrate before each", l)]
            self.assertTrue(
                before,
                f"{title} narrates on receipt and on done and nowhere between")

    def test_the_before_each_work_step_governs_the_work_that_follows_it(self):
        # A narration step placed after the rewrite governs nothing.
        for title, section in _event_sections():
            lines = section.splitlines()
            numbered = [(i, l) for i, l in enumerate(lines) if re.match(r"^\d+\. ", l)]
            at = next(i for i, l in numbered if re.search(r"(?i)narrate before each", l))
            after = [l for i, l in numbered if i > at]
            self.assertGreaterEqual(
                len(after), 3,
                f"{title} puts the narration step at the end, where it governs nothing")

    def test_each_event_subsection_still_narrates_on_receipt_and_on_done(self):
        for title, section in _event_sections():
            self.assertIn("--done", section, f"{title} never closes the trail")
            self.assertIn("--event-id", section, f"{title} never narrates the receipt")

    def test_narration_comes_before_the_work_not_after(self):
        # A line written after a ninety-second search arrives ninety seconds
        # too late — the silence it was meant to fill already happened.
        self.assertRegex(EVENTS, r"(?i)before (each|any|the) step")

    def test_a_step_is_defined_so_it_does_not_mean_every_tool_call(self):
        self.assertRegex(EVENTS, r"(?i)not an individual tool")


class TestTheSkillMentionsIt(unittest.TestCase):
    def test_the_skill_points_at_the_contract(self):
        self.assertIn("progress", SKILL.lower())
