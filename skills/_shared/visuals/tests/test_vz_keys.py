"""Keys on the map and the lane sequence (`keyed=True`): every part a page reveals carries the key a scene names it
by, and without keys the drawing is exactly what it was."""
import re
from html import unescape

from skills._shared.visuals import map_svg, sequence_svg

# test_vz.py's two specs, copied so that a change there does not move these keys
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


def keys(svg: str) -> list[str]:
    """The keys as a browser reads them: an arrow's `->` is written `-&gt;` in the attribute."""
    return list(dict.fromkeys(unescape(k) for k in re.findall(r'data-key="([^"]*)"', svg)))


def test_a_map_without_keys_is_drawn_exactly_as_before_and_keys_only_add_the_attribute():
    plain, keyed = map_svg.render(MAP, "m1"), map_svg.render(MAP, "m1", keyed=True)
    assert "data-key" not in plain
    assert re.sub(r' data-key="[^"]*"', "", keyed) == plain


def test_every_drawn_part_of_a_keyed_map_carries_the_key_of_its_zone_box_or_arrow():
    svg = map_svg.render(MAP, "m1", keyed=True)
    # every part the player reveals is a part the stage reveals
    assert len(re.findall(r"data-p=", svg)) == len(re.findall(r'data-p="1" data-key=', svg))
    assert keys(svg) == ["zone:0", "box:u", "box:a", "box:rest", "box:mcp", "box:tok", "box:svc",
                         "edge:u->rest#0", "edge:a->mcp#0", "edge:rest->svc#0", "edge:mcp->svc#0",
                         "route:1", "route:2", "route:4"]
    # a box's words carry its key, and a child box keeps its own
    assert re.search(r'<text class="nm" [^>]*data-key="box:tok"[^>]*>token</text>', svg)
    assert re.search(r'<text class="sb" [^>]*data-key="box:tok"[^>]*>scopes</text>', svg)
    # a route arrow's badge and label are its step's
    assert re.search(r'<circle [^>]*data-key="route:2"', svg) and re.search(r'<text class="lb" [^>]*data-key="route:2"', svg)


def test_two_structure_arrows_between_the_same_boxes_are_counted_apart_and_a_route_arrow_with_no_step_is_step_1():
    spec = {"columns": ["a", "b"], "boxes": [{"id": "x", "col": 0, "row": 0, "name": "X"}, {"id": "y", "col": 1, "row": 0, "name": "Y"}],
            "arrows": [{"from": "x", "to": "y"}, {"from": "x", "to": "y", "offset": 10}, {"from": "y", "to": "x", "layer": "route"}]}
    assert map_svg.arrow_keys(spec) == ["edge:x->y#0", "edge:x->y#1", "route:1"]
    assert keys(map_svg.render(spec, "m2", keyed=True))[-3:] == ["edge:x->y#0", "edge:x->y#1", "route:1"]


def test_a_key_is_escaped_like_every_other_word_of_the_spec():
    spec = {"columns": ["a"], "boxes": [{"id": 'x"><script>', "col": 0, "row": 0, "name": "X"}]}
    svg = map_svg.render(spec, "m3", keyed=True)
    assert "<script>" not in svg and 'data-key="box:x&quot;&gt;&lt;script&gt;"' in svg


def test_a_sequence_without_keys_is_drawn_exactly_as_before_and_keyed_names_its_steps_and_actors():
    plain, keyed = sequence_svg.render(SEQ, "s1"), sequence_svg.render(SEQ, "s1", keyed=True)
    assert "data-key" not in plain
    assert re.sub(r' data-key="[^"]*"', "", keyed) == plain
    assert keys(keyed) == ["actor:p", "actor:s", "actor:c", "step:s1", "step:s2", "step:s3", "step:s4"]
    # an actor's head, its name, its role and its lifeline
    assert len(re.findall(r'data-key="actor:p"', keyed)) == 4
