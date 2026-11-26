"""A .txt draft page keeps its line breaks and wraps long lines on a narrow stage."""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "static" / "stage.css"


def _rule(selector):
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", CSS.read_text())
    assert m, selector
    return m.group(1)


def test_the_text_page_pre_wraps_long_lines_and_keeps_line_breaks():
    assert _rule(".code>pre.filetext") == (
        "margin:0;padding:12px 18px;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit")


def test_the_code_boards_own_lines_stay_unwrapped():
    assert "white-space:pre;" in _rule(".code .ln")
    assert "white-space:pre;" in _rule(".ln-cl")
