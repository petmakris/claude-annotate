"""The view maths, ported from lomem's canvas-view.test.ts and comment-point tests, plus the layout."""
from __future__ import annotations

import math

from .helpers import js, needs_node

pytestmark = needs_node


def test_zoom_keeps_the_surface_point_under_the_pointer():
    r = js("var v = { x: -300, y: 120, z: 0.25 }, n = M.zoomAt(v, 500, 400, 1);"
           "return [n, n.x + 3200 * n.z, n.y + 1120 * n.z, M.zoomAt(n, 500, 400, 0.25)];")
    assert r == [{"x": -2700, "y": -720, "z": 1}, 500, 400, {"x": -300, "y": 120, "z": 0.25}]


def test_a_pinch_zooms_round_the_fingers_and_follows_them():
    r = js("var s = { x: 0, y: 0, z: 0.5 };"
           "var c = M.pinchView(s, 200, 300, 10, 200, 300, 1000, 0.02, 4);"
           "return [M.pinchView(s, 200, 300, 100, 200, 300, 300, 0.02, 4), M.pinchView(s, 200, 300, 100, 250, 300, 300, 0.02, 4), c.z, c.x + 400 * 4];")
    assert r == [{"x": -400, "y": -600, "z": 1.5}, {"x": -350, "y": -600, "z": 1.5}, 4, 200]


def test_zoom_is_clamped_and_fit_centres_a_box_under_the_cap():
    r = js("return [M.clampZoom(10, 0.02, 4), M.clampZoom(0.001, 0.02, 4), M.clampZoom(0.5, 0.02, 4),"
           "M.fitView(0, 0, 4000, 1000, 1000, 600, 50, 1), M.fitView(100, 200, 300, 200, 1000, 600, 50, 1)];")
    assert r == [4, 0.02, 0.5, {"x": 50, "y": 187.5, "z": 0.225}, {"x": 250, "y": 0, "z": 1}]


def test_the_wheel_pans_any_way_and_zooms_with_ctrl_capped_per_notch():
    r = js("return [M.wheelAction(30, -20, 0, false, false, 800), M.wheelAction(0, 100, 0, false, true, 800),"
           "M.wheelAction(0, 3, 1, false, false, 800), M.wheelAction(0, 1, 2, false, false, 800),"
           "M.wheelAction(0, -5, 0, true, false, 800).factor, M.wheelAction(0, 100, 0, true, false, 800).factor,"
           "M.wheelAction(0, -100, 0, true, false, 800).factor];")
    assert r[:4] == [{"dx": 30, "dy": -20, "factor": 1}, {"dx": 100, "dy": 0, "factor": 1},
                     {"dx": 0, "dy": 48, "factor": 1}, {"dx": 0, "dy": 800, "factor": 1}]
    assert r[4:] == [math.exp(0.05), math.exp(-0.4), math.exp(0.4)]


def test_a_press_is_a_click_until_it_moves_past_the_slop_more_for_a_finger():
    r = js("return [M.isDrag(0,0,'mouse'), M.isDrag(3,2,'mouse'), M.isDrag(4,0,'mouse'), M.isDrag(4,1,'mouse'),"
           "M.isDrag(6,6,'touch'), M.isDrag(6,6,'mouse'), M.isDrag(10,1,'touch')];")
    assert r == [False, False, False, True, False, True, True]


def test_a_pin_is_a_fraction_of_its_shot_and_lands_on_the_same_spot_at_every_zoom():
    r = js("var at = function (v) { return M.pinOnScreen(v, 3000, 2000, 1600, 1000, 0.25, 0.4); };"
           "return [M.pointInBox(150, 300, 100, 100, 200, 800), M.pointInBox(1, 1, 0, 0, 3, 7), M.pointInBox(99, 300, 100, 100, 200, 800),"
           "M.pointInBox(150, 300, 100, 100, 0, 800), at({x:0,y:0,z:1}), at({x:-100,y:50,z:0.5}), at({x:-6000,y:-4000,z:2})];")
    assert r == [{"fx": 0.25, "fy": 0.25}, {"fx": 0.3333, "fy": 0.1429}, None, None,
                 {"x": 3400, "y": 2400}, {"x": 1600, "y": 1250}, {"x": 800, "y": 800}]


# A journey: desktop 1600 × 1000 and phone 390 × 844 windows, full-page shots.
JOURNEY = """
function shot(label, w, h, vw, vh) { return { label: label, width: w, height: h, viewport: { width: vw, height: vh } }; }
function board(h, ph) { return { shots: [shot('Desktop', 1600, h, 1600, 1000), shot('Phone', 390, ph, 390, 844)] }; }
function group(n) { var b = []; for (var i = 0; i < n; i++) b.push(board(1000 + i * 300, 844 + i * 500)); return { boards: b }; }
var groups = [group(5), group(10), group(8), group(3), group(12), group(1), group(7), group(9)];
var all = function () { return true; };
"""


def test_every_board_is_drawn_at_one_size_whatever_its_shots_length():
    r = js(JOURNEY + "var l = M.layoutCanvas(groups, all, { height: 300 }); var b = l.groups[1].boards;"
           "return b.map(function (x) { return [x.w, x.h, x.shots.map(function (s) { return [Math.round(s.w * 10) / 10, s.h]; })]; });")
    desktop, phone = 480, round(300 * 390 / 844, 1)
    assert all(h == 300 and abs(w - (480 + 16 + 300 * 390 / 844)) < 1e-9 for w, h, _ in r)
    assert all(s == [[desktop, 300], [phone, 300]] for _, _, s in r)


def test_a_full_page_shot_keeps_its_whole_height_for_pins_but_draws_its_first_screen():
    r = js("var f = M.frameOf({ width: 390, height: 3808, viewport: { width: 390, height: 844 } }, 300);"
           "var g = M.frameOf({ width: 1220, height: 9000 }, 300); return [f, g];")
    assert r[0]["h"] == 300 and abs(r[0]["fullH"] - 300 * 3808 / 844) < 1e-9
    # No viewport: the shot's own aspect, never taller than 2.4 widths.
    assert abs(r[1]["w"] - 300 / 2.4) < 1e-9 and r[1]["h"] == 300


def test_boards_wrap_four_to_six_a_line_and_the_groups_make_the_surface_about_square():
    # Mealy's shape: 14 groups, 126 boards.
    r = js(JOURNEY + "groups = groups.concat(groups.slice(0, 6)); var l = M.layoutCanvas(groups, all, { height: 300 });"
           "var perLine = l.groups.map(function (g) { var ys = {}; g.boards.forEach(function (b) { ys[b.y] = (ys[b.y] || 0) + 1; });"
           "  return Math.max.apply(null, Object.keys(ys).map(function (k) { return ys[k]; })); });"
           "return { w: l.w, h: l.h, perLine: perLine, xs: l.groups.map(function (g) { return g.x; }) };")
    # The widest line of every group of 4 or more boards holds 4 to 6.
    assert all(4 <= n <= 6 for n, size in zip(r["perLine"], [5, 10, 8, 3, 12, 1, 7, 9, 5, 10, 8, 3, 12, 1]) if size >= 6)
    assert 0.7 < r["w"] / r["h"] < 1.4
    # Groups go down a column, then the next, in reading order.
    assert r["xs"] == sorted(r["xs"])
    assert len(set(r["xs"])) > 1


def test_the_shot_toggle_lays_the_grid_out_again_for_what_is_shown():
    r = js(JOURNEY + "var phone = function (l) { return l === 'Phone'; };"
           "var a = M.layoutCanvas(groups, all, { height: 300 }), p = M.layoutCanvas(groups, phone, { height: 300 });"
           "return [a.groups[0].boards[0].shots.length, p.groups[0].boards[0].shots.length, p.groups[0].boards[0].shots[0].i, p.w < a.w];")
    assert r == [2, 1, 1, True]


def test_a_board_with_one_shot_stays_when_the_toggle_picks_another_label():
    r = js("var g = [{ boards: [{ shots: [{ label: 'Desktop', width: 1600, height: 1000 }] }] }];"
           "var l = M.layoutCanvas(g, function (x) { return x === 'Phone'; }, { height: 300 }); return l.groups[0].boards.length;")
    assert r == 1


def test_changed_only_lays_out_the_kept_boards_alone_and_leaves_out_groups_with_none():
    # Group 0 keeps its 2nd and 4th boards, group 1 none, group 2 its first; group 3 is empty.
    r = js(JOURNEY + "var g = [group(5), group(3), group(2), { boards: [] }];"
           "g[0].boards[1].change = 'changed'; g[0].boards[3].change = 'new'; g[2].boards[0].change = 'changed';"
           "var keep = function (b) { return !!b.change; };"
           "var l = M.layoutCanvas(g, all, { height: 300, keep: keep }), a = M.layoutCanvas(g, all, { height: 300 });"
           "var none = M.layoutCanvas(g, all, { height: 300, keep: function () { return false; } });"
           "return { groups: l.groups.map(function (x) { return [x.i, x.boards.map(function (b) { return b.i; })]; }),"
           "  first: l.groups[0].boards.map(function (b) { return b.x; }), all: a.groups.length, none: none.groups.length };")
    assert r["groups"] == [[0, [1, 3]], [2, [0]]]
    # The kept boards close up: the second starts one board and one gap after the first.
    assert r["first"] == [0, 480 + 16 + 300 * 390 / 844 + 64]
    assert r["all"] == 4 and r["none"] == 0


def test_the_first_view_fits_the_first_group_but_a_phone_sees_its_first_board_whole():
    r = js(JOURNEY + "var l = M.layoutCanvas(groups, all, { height: 300 }), g = l.groups[0];"
           "var d = M.firstView(l, 1440, 800, 48, 44), p = M.firstView(l, 390, 700, 16, 44);"
           "return { gw: g.w, b0: g.boards[0].w, d: d, p: p };")
    assert abs(r["d"]["z"] - max((1440 - 96) / r["gw"], min(0.35, (1440 - 96) / r["b0"]))) < 1e-9
    assert r["d"]["x"] == 48 and abs(r["d"]["y"] - (44 + 72 * r["d"]["z"])) < 1e-9
    assert abs(r["p"]["z"] - (390 - 32) / r["b0"]) < 1e-9


def test_thumbnails_twice_the_size_only_when_the_zoom_needs_them():
    r = js("return [M.thumbTier(0.39, 1), M.thumbTier(1, 1), M.thumbTier(0.56, 3), M.thumbTier(0.3, 3), M.thumbTier(2, 1)];")
    assert r == [1, 1, 2, 1, 2]


def test_a_shot_is_loaded_when_it_is_in_view_or_half_a_window_from_it():
    r = js("var v = { x: -1000, y: 0, z: 0.5 };"
           "return [M.inView(v, 2000, 0, 400, 300, 1440, 900, 0.5), M.inView(v, 5000, 0, 400, 300, 1440, 900, 0.5),"
           "M.inView(v, 4800, 0, 400, 300, 1440, 900, 0.5), M.inView(v, 200, 0, 400, 300, 1440, 900, 0.5), M.inView(v, 200, 0, 400, 300, 1440, 900, 0)];")
    # Screen x: 0; 1500 (60 past the right edge, within half a window); 1400; -900 to -700 (within 720 of the left edge); the same with no margin.
    assert r == [True, True, True, True, False]
