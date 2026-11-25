"""A map spec is bounded: a huge row, rows, cols, box count or arrow count is refused by name, at once."""
import time

import pytest

from skills._shared.visuals import map_svg


def spec(**box):
    b = {"id": "a", "name": "A", "col": 0, "row": 0}
    b.update(box)
    return {"columns": ["x", "y"], "boxes": [b, {"id": "b", "name": "B", "col": 1, "row": 0}]}


def refused(sp):
    t = time.monotonic()
    with pytest.raises(map_svg.ValidationError) as e:
        map_svg.validate(sp)
    assert time.monotonic() - t < 0.5
    return str(e.value)


def test_the_limits_are_these():
    assert (map_svg.MAX_COLS, map_svg.MAX_ROWS, map_svg.MAX_BOXES, map_svg.MAX_ARROWS) == (12, 40, 60, 120)


def test_a_huge_row_is_refused_by_name():
    assert refused(spec(row=10**9)) == "box 'a': row 1000000000 is past the last of 40 rows"


def test_a_huge_rows_span_is_refused_by_name():
    assert refused(spec(rows=10**9)) == "box 'a': rows is 1000000000; at most 40"


def test_rows_reaching_past_the_last_row_are_refused():
    assert refused(spec(row=39, rows=2)) == "box 'a': rows reach row 40, past the last of 40 rows"


def test_a_huge_cols_span_is_refused_by_name():
    assert refused(spec(cols=10**9)) == "box 'a': cols is 1000000000; at most 12"


def test_too_many_columns_are_refused():
    sp = spec()
    sp["columns"] = [str(i) for i in range(13)]
    assert refused(sp) == "map has 13 columns; at most 12"


def test_too_many_boxes_are_refused():
    sp = {"columns": ["x"], "boxes": [{"id": f"b{i}", "name": "B", "col": 0, "row": i % 40} for i in range(61)]}
    assert refused(sp) == "map has 61 boxes; at most 60"


def test_too_many_arrows_are_refused():
    sp = spec()
    sp["arrows"] = [{"from": "a", "to": "b"}] * 121
    assert refused(sp) == "map has 121 arrows; at most 120"


def test_the_last_row_and_the_most_arrows_are_still_drawn():
    sp = spec(row=39)
    sp["arrows"] = [{"from": "a", "to": "b"}] * 120
    map_svg.validate(sp)
