"""The map and the lane sequence (map_svg, sequence_svg) and their player: what a spec may say, what
the SVG carries for the reveal, and that an author's words reach the page only as text."""
import json
import re

import pytest

from skills._shared.visuals import map_svg, player, sequence_svg

MAP = {
    "title": "Two callers, one service",
    "columns": ["Who asks", "Entry", "Service"],
    "boxes": [
        {"id": "u", "col": 0, "row": 0, "name": "A person", "lines": ["taps Pay"], "b": 1, "r": 1},
        {"id": "a", "col": 0, "row": 1, "name": "An assistant", "tone": "blue", "b": 1, "r": 3},
        {"id": "rest", "col": 1, "row": 0, "name": "REST", "mono": True, "b": 2, "r": 1},
        {"id": "mcp", "col": 1, "row": 1, "name": "MCP", "tone": "blue", "b": 2, "r": 3,
         "children": [{"id": "tok", "name": "token", "lines": ["scopes"]}]},
        {"id": "svc", "col": 2, "row": 0, "rows": 2, "name": "bills.pay", "tone": "green", "b": 3, "r": 2,
         "lines": ["refuses a 2nd payment", {"text": "\"already paid\"", "tone": "red", "r": 4}]},
    ],
    "zones": [{"label": "entry points", "tone": "blue", "boxes": ["rest", "mcp"]}],
    "arrows": [
        {"from": "u", "to": "rest", "b": 2}, {"from": "a", "to": "mcp", "tone": "blue", "b": 2},
        {"from": "rest", "to": "svc", "label": "calls", "b": 3}, {"from": "mcp", "to": "svc", "b": 3},
        {"layer": "route", "from": "u", "to": "rest", "n": 1, "r": 1},
        {"layer": "route", "from": "rest", "to": "svc", "n": 2, "r": 2, "label": "`pay()`"},
        {"layer": "route", "from": "mcp", "to": "svc", "n": 3, "r": 4, "dash": True, "tone": "blue"},
    ],
    "legend": [{"label": "calls"}, {"tone": "blue", "label": "an AI call"}],
    "captions": {"build": [{"title": "Who", "text": "two"}], "route": [{"title": "Pay", "text": "`x`"}]},
}

SEQ = {
    "title": "Pay twice",
    "actors": [{"id": "p", "label": "Person", "role": "pays"}, {"id": "s", "label": "bills.pay", "mono": True, "tone": "green"},
               {"id": "c", "label": "Claude", "tone": "blue"}],
    "phases": [{"id": "one", "label": "First", "start_at": "s1"}, {"id": "two", "label": "Later", "start_at": "s3"}],
    "steps": [
        {"id": "s1", "from": "p", "to": "s", "arrow": "request", "sub": "pay(bill)", "n": 1, "checks": [{"label": "unpaid", "ok": True}]},
        {"id": "s2", "from": "s", "to": "p", "arrow": "event", "label": "paid", "tone": "good", "n": 1},
        {"id": "s3", "from": "c", "to": "s", "arrow": "request", "sub": "pay(bill)", "n": 2, "checks": [{"label": "already paid", "ok": False}]},
        {"id": "s4", "from": "c", "to": "c", "arrow": "self", "label": "decides itself", "tone": "amber", "n": 2},
    ],
    "outcome": {"tone": "red", "title": "Refused", "lines": ["the rule lives in the service"]},
    "captions": [{"title": "Pay", "text": "once"}, {"title": "Again", "text": "refused"}],
}


def attrs(svg, name):
    return [int(x) for x in re.findall(rf'data-{name}="(\d+)"', svg)]


def test_a_map_draws_as_one_svg_with_its_title_columns_and_every_box():
    svg = map_svg.render(MAP, "m1")
    assert svg.startswith('<svg class="vz"') and svg.endswith("</svg>")
    assert 'class="ttl"' in svg and "WHO ASKS" in svg and "SERVICE" in svg
    for name in ("A person", "An assistant", "REST", "MCP", "token", "bills.pay"):
        assert f">{name}<" in svg


def test_a_map_carries_build_and_route_steps_and_separates_route_arrows():
    svg = map_svg.render(MAP, "m1")
    assert max(attrs(svg, "b")) == 3 and max(attrs(svg, "r")) == 4
    route = re.findall(r'<path [^>]*data-route="1"', svg)
    base = re.findall(r'<path [^>]*data-base="1"', svg)
    assert len(route) == 3 and len(base) == 4


def test_a_child_box_takes_its_parents_steps():
    svg = map_svg.render(MAP, "m1")
    rect = re.search(r'<text class="nm" [^>]*data-b="(\d+)" data-r="(\d+)"[^>]*>token<', svg)
    assert rect and rect.groups() == ("2", "3")


def test_every_marker_id_is_prefixed_with_the_uid():
    svg = map_svg.render(MAP, "first")
    ids = re.findall(r' id="([^"]+)"', svg)
    assert ids and all(i.startswith("first-") for i in ids)
    assert all(u.startswith("#first-") for u in re.findall(r'url\((#[^)]+)\)', svg))


def test_code_spans_become_mono_tspans():
    svg = map_svg.render(MAP, "m1")
    assert '<tspan class="mono">pay()</tspan>' in svg


@pytest.mark.parametrize("field", ["name", "label", "title"])
def test_an_authors_words_reach_the_svg_only_as_text(field):
    spec = json.loads(json.dumps(MAP))
    evil = '<script>alert(1)</script><img src=x onerror=alert(1)>'
    if field == "name":
        spec["boxes"][0]["name"] = evil
    elif field == "label":
        spec["arrows"][2]["label"] = evil
    else:
        spec["title"] = evil
    svg = map_svg.render(spec, "m1")
    assert "<script" not in svg and "<img" not in svg
    assert "&lt;script&gt;" in svg


def test_a_bad_uid_is_refused():
    with pytest.raises(map_svg.ValidationError):
        map_svg.render(MAP, 'x" onload="')


@pytest.mark.parametrize("change, message", [
    (lambda s: s["boxes"][1].update(col=1, row=0), "overlaps"),
    (lambda s: s["boxes"][0].update(col=5), "reaches column"),
    (lambda s: s["boxes"][0].update(tone="purple"), "unknown tone"),
    (lambda s: s["arrows"][0].update(to="nowhere"), "unknown to box"),
    (lambda s: s["arrows"][0].update(path="zigzag"), "unknown path"),
    (lambda s: s["zones"][0].update(boxes=["tok"]), "not a box placed on the grid"),
    (lambda s: s["boxes"][0].update(b=-1), "whole number"),
    (lambda s: s["boxes"].append(dict(s["boxes"][0], col=2, row=3)), "duplicate box id"),
])
def test_a_malformed_map_is_refused_with_a_reason(change, message):
    spec = json.loads(json.dumps(MAP))
    change(spec)
    with pytest.raises(map_svg.ValidationError, match=message):
        map_svg.validate(spec)


def test_the_same_spec_draws_the_same_svg():
    assert map_svg.render(MAP, "m1") == map_svg.render(json.loads(json.dumps(MAP)), "m1")


def test_a_label_too_wide_for_its_gap_widens_the_gap():
    narrow = map_svg.render(MAP, "m1")
    spec = json.loads(json.dumps(MAP))
    spec["arrows"][0]["label"] = "a label far wider than the narrowest gap between two columns"
    wide = map_svg.render(spec, "m1")
    width = lambda s: float(re.search(r'viewBox="0 0 ([\d.]+)', s).group(1))
    assert width(wide) > width(narrow) + 100


def test_a_lane_sequence_draws_heads_chips_checks_bands_and_outcome():
    svg = sequence_svg.render(SEQ, "q1")
    assert svg.startswith('<svg class="vz"') and 'data-vz="sequence"' in svg
    assert ">Person<" in svg and ">pays<" in svg
    assert "✓ unpaid" in svg and "✗ already paid" in svg
    assert "FIRST" in svg and "LATER" in svg and ">Refused<" in svg
    assert max(attrs(svg, "r")) == 2


def test_each_step_of_a_lane_sequence_is_tagged_with_its_number():
    svg = sequence_svg.render(SEQ, "q1")
    groups = re.findall(r'<g data-step="(s\d)" data-p="1" data-r="(\d)">', svg)
    assert groups == [("s1", "1"), ("s2", "1"), ("s3", "2"), ("s4", "2")]


def test_a_lane_sequence_reads_annotates_older_tones():
    svg = sequence_svg.render(SEQ, "q1")
    assert 'class="lb green"' in svg  # "good" became green


def test_a_lane_sequence_numbers_every_arrow_when_the_spec_does_not():
    spec = json.loads(json.dumps(SEQ))
    for s in spec["steps"]:
        s.pop("n")
    assert max(attrs(sequence_svg.render(spec, "q1"), "r")) == 4


def test_a_lane_sequence_keeps_the_base_rules():
    spec = json.loads(json.dumps(SEQ))
    spec["steps"][0]["to"] = "nobody"
    with pytest.raises(sequence_svg.ValidationError, match="unknown to actor"):
        sequence_svg.render(spec, "q1")


def test_the_player_carries_captions_as_json_text_and_no_markup():
    spec = json.loads(json.dumps(MAP))
    spec["captions"]["route"][0]["title"] = "</script><script>alert(1)</script>"
    html = player.map_figure(spec, "m1")
    assert html.count("<script") == 1 and "alert(1)</script>" not in html
    data = json.loads(re.search(r'class="vz-steps">(.*?)</script>', html).group(1))
    assert data["route"][0]["title"].startswith("</script>")


def test_a_standalone_page_inlines_the_style_and_the_script():
    page = player.standalone([player.render_any(MAP, "m1"), player.render_any(SEQ, "q1")], "Two")
    assert "svg.vz" in page and "vzReveal" in page and page.split("<script>")[0].count('<div class="vz-player" data-vz-player') == 2
    script = page[page.rindex("<script>"):]
    assert script.count("</script>") == 1


def test_an_outcome_line_wider_than_the_lanes_widens_the_canvas():
    """The outcome box spans the canvas, so a long line in it used to run off
    the right edge whenever the title was short: the title alone set the
    width the outcome had to fit."""
    from skills._shared.visuals.map_svg import _width
    line = "The heal writes no archive row, so the next startup can heal again, and nothing says so."
    spec = {"title": "Short", "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "steps": [{"id": "s1", "from": "a", "to": "b", "arrow": "request", "label": "go"}],
            "outcome": {"tone": "green", "title": "Done", "lines": [line]}}
    svg = sequence_svg.render(spec, "u")
    width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
    x = float(re.search(r'<text class="sb" x="([\d.]+)" y="[\d.]+"[^>]*>' + re.escape(line), svg).group(1))
    box = re.search(r'<rect class="bx green" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg)
    right = float(box.group(1)) + float(box.group(2))
    assert x + _width(line, "vz-sb") <= right - 18 + 1
    assert right <= width
