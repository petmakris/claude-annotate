"""Talk and stage share one design token block, pasted byte-identical into both pages, so the
two read as one page in light and dark. Same idea as tests/test-palette.bats."""
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
TALK = SKILLS / "talk" / "static" / "tokens.css"
STAGE_CSS = SKILLS / "stage" / "static" / "stage.css"


def tokens(text: str) -> str:
    m = re.search(r"/\* tokens:start \*/(.*?)/\* tokens:end \*/", text, re.S)
    assert m, "no tokens:start / tokens:end markers"
    return " ".join(m.group(1).split())


def test_talk_and_stage_carry_the_same_tokens():
    assert tokens(TALK.read_text()) == tokens(STAGE_CSS.read_text())


def test_a_token_changed_in_one_file_only_is_caught():
    stage = STAGE_CSS.read_text().replace("--acc:#0F6E74", "--acc:#0F6E75", 1)
    assert stage != STAGE_CSS.read_text()
    with pytest.raises(AssertionError):
        assert tokens(TALK.read_text()) == tokens(stage)


def test_the_tokens_cover_light_and_both_dark_guards():
    block = tokens(STAGE_CSS.read_text())
    assert "color-scheme:light dark" in block
    assert '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])' in block
    assert ':root[data-theme="dark"]' in block
    assert "--bg:#0F1318" in block
