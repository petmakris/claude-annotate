"""What a bars board says: one day, never "1 days" (QF-8), and the decimal mark a Greek board is read with (QF-9)."""
import re

import pytest

from skills._shared.visuals import bars_svg


def texts(spec):
    svg = bars_svg.render(spec, "t")
    return [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<text[^>]*>.*?</text>", svg)]


DAYS = {"title": "Trip", "unit": "days", "bars": [{"id": "a", "label": "Kyoto", "value": 1}, {"id": "b", "label": "Osaka", "value": 2}],
        "threshold": {"value": 1, "label": "limit"}}


def test_a_value_of_one_is_one_day_and_the_rest_are_days_in_the_chips_and_the_limit():
    got = texts(DAYS)
    assert [t for t in got if "day" in t] == ["1 day", "2 days", "limit 1 day"]


@pytest.mark.parametrize("value, unit, said", [
    (1, "days", "1 day"), (-1, "hours", "-1 hour"), (1, "person days", "1 person day"), (2, "days", "2 days"), (1.5, "days", "1.5 days"),
    (1, "kbps", "1 kbps"), (1, "ms", "1 ms"), (1, "class", "1 class"), (1, "%", "1%"), (1, "steps", "1 step")])
def test_the_unit_follows_the_value_but_never_loses_an_s_that_is_not_a_plural(value, unit, said):
    assert bars_svg._chip_text(value, unit) == said


GREEK = {"title": "Βάθος και πίεση", "unit": "εκ.", "bars": [{"id": "a", "label": "Πάνω", "value": 2.5}, {"id": "b", "label": "Κάτω", "value": 1234.5}]}


def test_a_board_in_greek_says_its_numbers_with_a_comma_and_spaces_its_thousands():
    got = texts(GREEK)
    assert "2,5 εκ." in got and "1 234 εκ." in got
    assert not [t for t in got if re.fullmatch(r"\d+\.\d+", t)]   # no tick with a point


def test_a_board_in_english_keeps_the_point_and_a_named_decimal_wins_either_way():
    english = {"unit": "m", "bars": [{"id": "a", "label": "A", "value": 2.5}, {"id": "b", "label": "B", "value": 1}]}
    assert "2.5 m" in texts(english)
    assert "2,5 m" in texts({**english, "decimal": ","})
    assert "2.5 εκ." in texts({**GREEK, "decimal": "."})
    with pytest.raises(bars_svg.ValidationError, match="decimal is"):
        bars_svg.validate({**english, "decimal": ";"})


def test_the_ticks_of_a_comma_board_use_the_comma_too():
    spec = {"unit": "s", "decimal": ",", "scale": "log", "bars": [{"id": "a", "label": "A", "value": 0.02}, {"id": "b", "label": "B", "value": 30}]}
    assert [t for t in texts(spec) if t[0].isdigit() and not t.endswith(" s")] == ["0,01", "0,1", "1", "10", "100"]
