"""A stylesheet whose braces do not balance drops every rule after the slip without a word in the browser:
one extra `}` after the dark tones once took `.visual` and the forced dark theme with it."""
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
SHEETS = [SKILLS / "stage" / "static" / "stage.css", SKILLS / "talk" / "static" / "call.css", SKILLS / "talk" / "static" / "tokens.css"]


def depth_slips(css: str) -> list[int]:
    """The lines where the brace depth goes below zero, and the depth left over at the end (as line -1).
    Comments are blanked first, keeping their line breaks: an apostrophe in one is not a quote."""
    css = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), css, flags=re.S)
    depth, slips, line, quote = 0, [], 1, ""
    for i, ch in enumerate(css):
        if ch == "\n":
            line += 1
        if quote:
            quote = "" if ch == quote and css[i - 1] != "\\" else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                slips.append(line)
                depth = 0
    return slips + ([-1] if depth else [])


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_every_rule_of_the_page_stylesheets_closes(sheet):
    assert depth_slips(sheet.read_text()) == []


def test_an_extra_brace_is_found_on_its_line():
    assert depth_slips(":root{--a:1}}\n.visual{x:1}") == [1]
    assert depth_slips("@media x{:root{--a:1}\n") == [-1]
    assert depth_slips("/* the page's own */\n:root{--a:1}}") == [2]
