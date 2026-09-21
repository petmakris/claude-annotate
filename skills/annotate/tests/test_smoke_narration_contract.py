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


class TestEveryEventPathNarrates(unittest.TestCase):
    def test_the_command_is_documented_with_its_flags(self):
        self.assertIn(CMD, EVENTS)
        self.assertIn("--text", EVENTS)
        self.assertIn("--done", EVENTS)

    def test_each_event_subsection_carries_a_narration_step(self):
        # One per handled event type. A path that does not narrate is a path
        # that goes silent, which is the whole defect.
        heads = [m.start() for m in re.finditer(r"^### `WEBCOMPANION_EVENT", EVENTS, re.M)]
        self.assertGreaterEqual(len(heads), 3, "the event sections moved")
        bounds = heads + [len(EVENTS)]
        for i, start in enumerate(heads):
            section = EVENTS[start:bounds[i + 1]]
            title = section.splitlines()[0]
            self.assertIn(CMD, section, f"{title} never narrates")

    def test_narration_comes_before_the_work_not_after(self):
        # A line written after a ninety-second search arrives ninety seconds
        # too late — the silence it was meant to fill already happened.
        self.assertRegex(EVENTS, r"(?i)before (each|any|the) step")

    def test_a_step_is_defined_so_it_does_not_mean_every_tool_call(self):
        self.assertRegex(EVENTS, r"(?i)not an individual tool")


class TestTheSkillMentionsIt(unittest.TestCase):
    def test_the_skill_points_at_the_contract(self):
        self.assertIn("progress", SKILL.lower())
