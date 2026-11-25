"""The bars board (bars_svg): what a spec may say, the scale it draws on, and the keys the stage reveals and lights by."""
import copy
import re

import pytest

from skills._shared.visuals import bars_svg

CACHE = {
    "title": "A cache miss costs a hundred times a hit", "unit": "ns", "scale": "log",
    "bars": [{"id": "l1", "label": "L1 cache", "value": 1, "note": "about four cycles"},
             {"id": "l2", "label": "L2 cache", "value": 4}, {"id": "l3", "label": "L3 cache", "value": 15},
             {"id": "ram", "label": "Main memory", "value": 100, "tone": "red"}],
    "threshold": {"value": 10, "label": "loop budget"},
}


def broken(**change):
    spec = copy.deepcopy(CACHE)
    spec.update(change)
    return spec


@pytest.mark.parametrize("spec, why", [
    (broken(scale="log", bars=[{"id": "z", "label": "Zero", "value": 0}]), "bar 'z': value 0 is not above zero"),
    (broken(scale="log", bars=[{"id": "n", "label": "Minus", "value": -3}]), "bar 'n': value -3 is not above zero"),
    (broken(scale="linear", bars=[{"id": "n", "label": "Minus", "value": -3}]), "bar 'n': value -3 is below zero"),
    (broken(bars=[{"id": "s", "label": "Text", "value": "5 ms"}]), "bar 's': value must be a number, got '5 ms'"),
    (broken(bars=[{"id": "b", "label": "Bool", "value": True}]), "bar 'b': value must be a number, got True"),
    (broken(bars=[{"id": "m", "label": "Mixed", "value": 5, "unit": "ms"}]), "bar 'm': unit 'ms' is not the board's unit 'ns'"),
    (broken(bars=[{"id": "a", "label": "A", "value": 1}, {"id": "a", "label": "B", "value": 2}]), "duplicate bar id: 'a'"),
    (broken(scale="sqrt"), "scale must be linear or log, got 'sqrt'"),
    (broken(unit=""), "unit must be text"),
    (broken(bars=[]), "bars needs at least 1 bar"),
    (broken(series=[1, 2]), "bars has no series"),
    (broken(markers=[1]), "bars has no markers"),
    (broken(bars=[{"id": f"b{i}", "label": "x", "value": 1} for i in range(25)]), "bars has 25 bars, at most 24"),
    (broken(threshold={"value": 0, "label": "x"}), "threshold 0 is not above zero"),
    (broken(bars=[{"id": "w", "label": "x" * 49, "value": 1}]), "bar 'w': label is 49 characters, at most 48"),
    (broken(bars=[{"id": "w", "label": "x", "value": 1, "note": "y" * 91}]), "bar 'w': note is 91 characters, at most 90"),
])
def test_a_spec_the_board_cannot_draw_honestly_is_refused_naming_the_bar(spec, why):
    with pytest.raises(bars_svg.ValidationError) as err:
        bars_svg.validate(spec)
    assert why in str(err.value)


def test_a_log_board_draws_ticks_at_powers_of_ten_and_says_log_scale():
    svg = bars_svg.render(CACHE, "u1")
    assert re.findall(r'class="tk"[^>]*>([^<]*)<', svg) == ["1", "10", "100"]
    assert svg.count("log scale") == 1 and 'data-scale="log"' in svg
    big = bars_svg.render(broken(bars=[{"id": "a", "label": "A", "value": 3}, {"id": "b", "label": "B", "value": 4_500_000}],
                                 threshold=None), "u2")
    assert re.findall(r'class="tk"[^>]*>([^<]*)<', big) == ["1", "10", "100", "1k", "10k", "100k", "1M", "10M"]


def test_a_linear_board_has_round_ticks_and_no_log_badge():
    spec = broken(scale="linear", unit="ms", threshold=None, bars=[{"id": "a", "label": "A", "value": 12.5}, {"id": "b", "label": "B", "value": 87}])
    svg = bars_svg.render(spec, "u3")
    assert re.findall(r'class="tk"[^>]*>([^<]*)<', svg) == ["0", "20", "40", "60", "80", "100"]
    assert "log scale" not in svg and 'data-scale="linear"' in svg
    assert bars_svg._linear_ticks(1200) == [0.0, 250.0, 500.0, 750.0, 1000.0, 1250.0]
    assert bars_svg._linear_ticks(0.8) == [0.0, 0.2, 0.4, 0.6, 0.8]


def test_a_bar_is_as_long_as_its_value_on_the_scale():
    svg = bars_svg.render(CACHE, "u4", keyed=True)
    widths = dict(re.findall(r'<rect class="bar[^"]*" x="20" y="\d+" width="(\d+)" height="22" rx="4" data-p="1" data-key="bar:(\w+)"', svg)[i][::-1]
                  for i in range(4))
    # the track is 445 wide for 1 to 100 on a log axis: 4 is 30 percent of it, 15 is 59 percent, 100 all of it
    assert widths == {"l1": "3", "l2": "134", "l3": "262", "ram": "445"}  # 1 sits on the axis: the shortest bar there is


def test_every_part_of_a_bar_carries_its_key_and_only_bars_do():
    svg = bars_svg.render(CACHE, "u5", keyed=True)
    assert svg.count('data-key="bar:l1"') == 6    # label, note, track, bar, chip and value
    assert svg.count('data-key="bar:l2"') == 5    # the same with no note
    assert set(re.findall(r'data-key="([^"]*)"', svg)) == {"bar:l1", "bar:l2", "bar:l3", "bar:ram"}
    assert "data-key" not in bars_svg.render(CACHE, "u5")
    assert bars_svg.bar_keys(CACHE) == ["bar:l1", "bar:l2", "bar:l3", "bar:ram"]


def test_one_threshold_is_one_dashed_line_with_its_label_and_unit():
    svg = bars_svg.render(CACHE, "u6")
    assert svg.count('class="thr"') == 1 and "loop budget 10 ns" in svg
    assert 'class="thr"' not in bars_svg.render(broken(threshold=None), "u6")


def test_rows_fill_the_canvas_when_there_are_few_and_the_board_grows_when_there_are_many():
    few = bars_svg.render(broken(bars=CACHE["bars"][:2], threshold=None), "u7")
    many = bars_svg.render(broken(scale="linear", threshold=None, bars=[{"id": f"b{i}", "label": f"Row {i}", "value": i + 1} for i in range(12)]), "u7")
    height = lambda svg: int(re.search(r'viewBox="0 0 560 (\d+)"', svg)[1])  # noqa: E731
    assert (height(bars_svg.render(CACHE, "u7")), height(few), height(many)) == (538, 330, 764)


def test_a_title_a_label_and_a_unit_reach_the_page_only_as_text():
    spec = broken(title="<img src=x onerror=alert(1)>", unit="<b>ns</b>", threshold=None,
                  bars=[{"id": "a", "label": "<script>alert(1)</script>", "value": 2}])
    svg = bars_svg.render(spec, "u8")
    assert "<script" not in svg and "<img" not in svg and "<b>" not in svg
    assert "&lt;script&gt;" in svg
