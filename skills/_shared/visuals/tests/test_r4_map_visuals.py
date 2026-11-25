"""The map's arrows, labels and width (map_svg), measured on the drawn geometry (`render(..., report=)`): no arrow
runs through a box it does not join or across a caption, no label sits on another arrow, caption, box or label, a
five-column map is tightened to fit its pane, and the words of a board are bounded by one shared check."""
import json
import re
from pathlib import Path

import pytest

from skills._shared.visuals import bars_svg, label_check, map_svg

HERE = Path(__file__).resolve().parent
DEMO = HERE.parents[2] / "talk" / "demo.md"
FIVE = json.loads((HERE / "data" / "map_five_columns.json").read_text())


def demo_map():
    text = DEMO.read_text()
    return json.loads(re.findall(r"\[\[show map[^\]]*\]\]\s*(\{.*?\})\s*\[\[/show\]\]", text, re.S)[0])


def segs(pts):
    return list(zip(pts, pts[1:]))


def hits(r, s, pad=0.0):
    x, y, w, h = r
    (a, b), (c, d) = s
    return min(a, c) < x + w - pad and max(a, c) > x + pad and min(b, d) < y + h - pad and max(b, d) > y + pad


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def problems(spec):
    rep: dict = {}
    svg = map_svg.render(spec, "t", False, rep)
    bad = []
    arrows, boxes = rep["arrows"], rep["boxes"]
    for i, (a, pts) in enumerate(arrows):
        for bid, r in boxes.items():
            if bid not in (a["from"], a["to"]) and any(hits(r, s, 2) for s in segs(pts)):
                bad.append(f"arrow {i} runs through box {bid}")
        for c in rep["captions"]:
            if any(hits(c, s, 3) for s in segs(pts)):
                bad.append(f"arrow {i} runs across a caption")
    for n, r in rep["labels"]:
        layer = arrows[n][0].get("layer", "base")
        for i, (a, pts) in enumerate(arrows):
            if i != n and a.get("layer", "base") == layer and any(hits(r, s) for s in segs(pts)):
                bad.append(f"label of arrow {n} lies on arrow {i}")
        bad += [f"label of arrow {n} lies on a caption" for c in rep["captions"] if overlap(r, c)]
        bad += [f"label of arrow {n} lies on box {b}" for b, br in boxes.items() if overlap(r, br)]
    for k, (n, r) in enumerate(rep["labels"]):
        for n2, r2 in rep["labels"][k + 1:]:
            if overlap(r, r2) and arrows[n][0].get("layer", "base") == arrows[n2][0].get("layer", "base"):
                bad.append(f"labels of arrows {n} and {n2} overlap")
    return bad, float(re.search(r'viewBox="0 0 (\d+)', svg).group(1)), rep


def test_no_arrow_of_the_demo_map_runs_through_a_box_or_a_caption_and_no_label_sits_on_another_arrow():
    bad, width, rep = problems(demo_map())
    assert bad == []
    never = next(pts for a, pts in rep["arrows"] if a.get("label") == "never")
    # the page-to-Azure arrow goes round under the Talk server, not through it
    assert [(round(x), round(y)) for x, y in never] == [(276, 154), (343, 154), (343, 316), (638, 316), (638, 266), (662, 266)]


def test_a_five_column_map_is_tightened_to_1165_px_and_its_labels_stay_on_their_own_arrows():
    bad, width, rep = problems(FIVE)
    assert bad == []
    assert width == 1165.0   # it was 1818, which the pane shrank to 7 px text


def test_a_wide_map_on_the_stage_carries_the_rule_that_scrolls_it_sideways_below_11px_text():
    svg = map_svg.render(FIVE, "vzm1", keyed=True, floor=True)
    assert '<style>@media (min-width:761px){svg.vz[data-uid="vzm1"]{min-width:1025px}}</style>' in svg
    assert 'data-uid="vzm1"' in svg
    assert "<style>" not in map_svg.render(FIVE, "vzm1", keyed=True)   # only the stage asks for it
    small = {"columns": ["a", "b"], "boxes": [{"id": "x", "name": "X", "col": 0, "row": 0}, {"id": "y", "name": "Y", "col": 1, "row": 0}]}
    assert "min-width" not in map_svg.render(small, "vzm2", keyed=True, floor=True)   # a narrow map fits as it is


def test_a_note_that_was_accepted_at_90_characters_and_cut_off_is_refused_by_its_measured_width():
    note = "Latency measured on the production fleet over the last full ninety days of traffic, p99 and up"[:90]
    assert len(note) == 90
    with pytest.raises(bars_svg.ValidationError) as e:
        bars_svg.validate({"unit": "ms", "bars": [{"id": "a", "label": "A", "value": 1, "note": note}]})
    assert str(e.value) == "bar 'a': note is 541 px wide on a canvas with 520 px of room: a note is one short line, the number you say"
    bars_svg.validate({"unit": "ms", "bars": [{"id": "a", "label": "A", "value": 1, "note": note[:60]}]})   # a short note still passes


def test_one_label_check_refuses_a_long_label_sub_and_spec_by_name_in_every_board():
    long_label, long_sub = "x" * 61, "y" * 121
    with pytest.raises(map_svg.ValidationError) as e:
        map_svg.validate({"columns": ["a"], "boxes": [{"id": "b", "name": long_label, "col": 0, "row": 0}]})
    assert str(e.value) == "box 'b': name is 61 characters, at most 60: a label is a few words, say it shorter"
    with pytest.raises(map_svg.ValidationError) as e:
        map_svg.validate({"columns": ["a"], "boxes": [{"id": "b", "name": "B", "lines": [long_sub], "col": 0, "row": 0}]})
    assert str(e.value) == "box 'b': line is 121 characters, at most 120: a sub is one short sentence, say it shorter"
    err = type("E", (ValueError,), {})
    with pytest.raises(err, match=r"^node 'n': label is 61 characters, at most 60"):
        label_check.check_flowchart({"nodes": [{"id": "n", "label": long_label}]}, err)
    with pytest.raises(err, match=r"^edge a->b: label is 61 characters"):
        label_check.check_flowchart({"nodes": [], "edges": [{"from": "a", "to": "b", "label": long_label}]}, err)
    with pytest.raises(err, match=r"^step s1: sub is 121 characters, at most 120"):
        label_check.check_sequence({"steps": [{"id": "s1", "label": "ok", "sub": long_sub}]}, err)
    with pytest.raises(err, match=r"^the spec is 80\d\d\d characters, at most 80000"):
        label_check.check_size({"nodes": ["z" * 80_000]}, err)
    label_check.check_flowchart({"nodes": [{"id": "n", "label": "x" * 60, "sub": "y" * 120}]}, err)   # the limits themselves pass
