"""A box's long line is wrapped, so one sentence never sets the width of a whole map (the stage draws it at the
width of its pane, and a map 2,800 px wide came out at 5 px type)."""
from __future__ import annotations

import re

from skills._shared.visuals import map_svg

LONG = "`web.service` handles requests and long lines of explanation text here, so that it runs well past the box"


def spec(line=LONG):
    cols = ["One", "Two", "Three"]
    boxes = [{"id": f"b{c}", "col": c, "row": 0, "name": f"Part {c}", "lines": [line, "short"]} for c in range(3)]
    return {"title": "T", "columns": cols, "boxes": boxes, "arrows": [{"from": "b0", "to": "b1"}, {"from": "b1", "to": "b2"}]}


def width(svg):
    return int(re.match(r'<svg class="vz" viewBox="0 0 (\d+) ', svg).group(1))


def test_a_long_line_wraps_at_the_line_limit_keeping_its_code_span_whole():
    lines = map_svg.fold_lines(spec())["boxes"][0]["lines"]
    assert lines == [{"text": "`web.service` handles requests"}, {"text": "and long lines of explanation"},
                     {"text": "text here, so that it runs well"}, {"text": "past the box"}, "short"]


def test_a_map_of_long_lines_is_no_wider_than_its_wrapped_lines_need():
    assert map_svg.LINE_MAX == 200.0
    assert width(map_svg.render(spec(), "vzx")) == 875      # unwrapped it is 2,186
    assert width(map_svg.render(spec("short line"), "vzy")) == 716


def test_a_line_that_fits_is_left_exactly_as_the_author_wrote_it():
    one = spec("fits")
    assert map_svg.fold_lines(one)["boxes"] == one["boxes"]
