"""Rearranging the field canvas in Chromium: a card dragged by its header, a row dragged
inside its card, and the arrangement each viewer keeps in localStorage.

Pages load from a file:// URL, not set_content, so localStorage has an origin to live
under; each test opens its own browser context, so stored arrangements never leak
between tests, exactly as render.py --check never sees a viewer's arrangement."""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from skills.dataflow.fields import render  # noqa: E402

FIELDS = Path(__file__).resolve().parents[1] / "fields"
LAYOUT = "() => window.__layout"


def _spec(name):
    return json.loads((FIELDS / name).read_text())


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def opened(browser, tmp_path):
    """opened(spec) -> page in a fresh context; every context opened is closed after."""
    ctxs = []

    def open_(spec, init=None):
        f = tmp_path / "canvas.html"
        f.write_text(render.render(spec))
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        if init:
            ctx.add_init_script(init)
        ctxs.append(ctx)
        pg = ctx.new_page()
        pg.goto(f.as_uri())
        pg.wait_for_function("() => window.__layoutReport")
        return pg

    yield open_
    for c in ctxs:
        c.close()


def _zoom(pg):
    return pg.evaluate("() => document.getElementById('cam').transform.baseVal.consolidate().matrix.a")


def _drag(pg, selector, dx, dy):
    b = pg.locator(selector).bounding_box()
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + dx / 2, y + dy / 2, steps=4)
    pg.mouse.move(x + dx, y + dy, steps=4)
    pg.mouse.up()


def _touches(w, cid):
    return w["from"].split(".")[0] == cid or w["to"].split(".")[0] == cid


def _row(L, end):
    cid, fid = end.split(".", 1)
    return L["cards"][cid], L["cards"][cid]["rows"][fid]


def test_card_drag_moves_the_card_and_its_wire_ends_only(opened):
    pg = opened(_spec("example-bypass.json"))
    before, k = pg.evaluate(LAYOUT), _zoom(pg)
    _drag(pg, '.grip[data-card="cmd"]', 0, 90)
    after = pg.evaluate(LAYOUT)
    dy = 90 / k
    c0, c1 = before["cards"]["cmd"], after["cards"]["cmd"]
    assert c1["y"] == pytest.approx(c0["y"] + dy, abs=0.05)
    assert (c1["x"], c1["h"], c1["rowOrder"]) == (c0["x"], c0["h"], c0["rowOrder"])
    for fid, r in c0["rows"].items():
        assert c1["rows"][fid]["y"] == pytest.approx(r["y"] + dy, abs=0.05)
    for cid in before["cards"]:
        if cid != "cmd":
            assert after["cards"][cid] == before["cards"][cid]
    moved = 0
    for w0, w1 in zip(before["wires"], after["wires"]):
        if not _touches(w0, "cmd"):
            assert w1 == w0
            continue
        moved += 1
        for end, at in (("from", "start"), ("to", "end")):
            shift = dy if w0[end].startswith("cmd.") else 0
            assert w1[at][0] == w0[at][0]
            assert w1[at][1] == pytest.approx(w0[at][1] + shift, abs=0.05)
    assert moved


def test_wires_stay_attached_to_their_ports(opened):
    pg = opened(_spec("example-bypass.json"))
    before = pg.evaluate(LAYOUT)
    _drag(pg, '.grip[data-card="env"]', 0, -70)
    _drag(pg, '.grip[data-card="cmd"]', 0, 120)
    after = pg.evaluate(LAYOUT)
    for w0, w1 in zip(before["wires"], after["wires"]):
        for end, at in (("from", "start"), ("to", "end")):
            (_, r0), (c1, r1) = _row(before, w0[end]), _row(after, w1[end])
            # the same offset from the row's centre: the fan of a busy row is kept
            assert w1[at][1] - r1["y"] == pytest.approx(w0[at][1] - r0["y"], abs=0.05)
            assert r1["y"] - r1["h"] / 2 <= w1[at][1] <= r1["y"] + r1["h"] / 2
        assert abs(w1["end"][0] - _row(after, w1["to"])[0]["x"]) < 0.5
    # the drawn path starts at the published start
    d = pg.evaluate("() => [...document.querySelectorAll('.edge .wire')].map(p => p.getAttribute('d'))")
    for w, path in zip(after["wires"], d):
        x, y = map(float, path.split()[1:3])
        assert (round(x, 2), round(y, 2)) == pytest.approx(tuple(w["start"]), abs=0.01)


def test_horizontal_drag_of_a_header_moves_nothing_sideways(opened):
    pg = opened(_spec("example-bypass.json"))
    before = pg.evaluate(LAYOUT)
    _drag(pg, '.grip[data-card="cmd"]', 200, 0)
    after = pg.evaluate(LAYOUT)
    assert after["cards"]["cmd"]["x"] == before["cards"]["cmd"]["x"]
    assert after["cards"]["cmd"]["y"] == pytest.approx(before["cards"]["cmd"]["y"], abs=0.05)


def test_row_drag_reorders_its_card(opened):
    pg = opened(_spec("example-order.json"))
    before, k = pg.evaluate(LAYOUT), _zoom(pg)
    c0 = before["cards"]["entity"]
    first = c0["rowOrder"][0]
    third = c0["rowOrder"][2]
    gap = c0["rows"][third]["y"] - c0["rows"][first]["y"]
    _drag(pg, f'[data-node="entity.{first}"] .hit', 0, gap * k)
    after = pg.evaluate(LAYOUT)
    c1 = after["cards"]["entity"]
    assert c1["rowOrder"] == c0["rowOrder"][1:3] + [first] + c0["rowOrder"][3:]
    # one rigid block: same place, same height, rows touching from the header down
    assert (c1["y"], c1["h"]) == (c0["y"], c0["h"])
    top = c1["y"] + 46
    for fid in c1["rowOrder"]:
        r = c1["rows"][fid]
        assert r["y"] - r["h"] / 2 == pytest.approx(top, abs=0.02)
        top += r["h"]
    assert top == pytest.approx(c1["y"] + c1["h"], abs=0.02)
    for w0, w1 in zip(before["wires"], after["wires"]):
        if w0["from"].startswith("entity."):
            r0, r1 = c0["rows"][w0["from"].split(".", 1)[1]], c1["rows"][w1["from"].split(".", 1)[1]]
            assert w1["start"][1] - r1["y"] == pytest.approx(w0["start"][1] - r0["y"], abs=0.05)
    moved = [w for w in after["wires"] if w["from"] == f"entity.{first}"]
    assert moved and all(w["start"][1] != w0["start"][1] for w, w0 in zip(moved, [x for x in before["wires"] if x["from"] == f"entity.{first}"]))


def test_a_click_without_movement_still_traces(opened):
    pg = opened(_spec("example-bypass.json"))
    before = pg.evaluate(LAYOUT)
    pg.locator('[data-node="form.email"] .hit').click()
    lit = pg.evaluate("() => [...document.querySelectorAll('.node.on')].map(e => e.dataset.node).sort()")
    assert lit == ["cmd.email", "env.body", "form.email", "req.body"]
    assert pg.evaluate(LAYOUT) == before
    # keyboard selection still works on a focused row
    pg.keyboard.press("Escape")
    pg.focus('[data-node="env.body"]')
    pg.keyboard.press("Enter")
    assert pg.evaluate("() => document.querySelectorAll('.node.on').length") == 9


def test_hover_still_lights_the_lineage(opened):
    pg = opened(_spec("example-bypass.json"))
    pg.locator('[data-node="form.email"] .hit').hover()
    assert pg.evaluate("() => document.getElementById('content').classList.contains('has-sel')")


def test_panning_the_empty_canvas_moves_the_camera_not_the_layout(opened):
    pg = opened(_spec("example-bypass.json"))
    before = pg.evaluate(LAYOUT)
    t0 = pg.get_attribute("#cam", "transform")
    pg.mouse.move(800, 860)
    pg.mouse.down()
    pg.mouse.move(700, 800, steps=4)
    pg.mouse.up()
    assert pg.get_attribute("#cam", "transform") != t0
    assert pg.evaluate(LAYOUT) == before


def test_reset_restores_the_computed_layout(opened):
    pg = opened(_spec("example-order.json"))
    before = pg.evaluate(LAYOUT)
    assert pg.is_disabled("#zreset")
    _drag(pg, '.grip[data-card="dto"]', 0, 80)
    first = before["cards"]["json"]["rowOrder"][0]
    _drag(pg, f'[data-node="json.{first}"] .hit', 0, 60)
    assert pg.evaluate(LAYOUT) != before
    pg.click("#zreset")
    assert pg.evaluate(LAYOUT) == before
    assert pg.is_disabled("#zreset")
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == before


def test_the_arrangement_persists_across_a_reload(opened):
    spec = _spec("example-order.json")
    pg = opened(spec)
    computed = pg.evaluate(LAYOUT)
    report = pg.evaluate("() => window.__layoutReport")
    _drag(pg, '.grip[data-card="dto"]', 0, -60)
    first = computed["cards"]["json"]["rowOrder"][0]
    _drag(pg, f'[data-node="json.{first}"] .hit', 0, 60)
    moved = pg.evaluate(LAYOUT)
    assert pg.evaluate("() => window.__layoutReport") == report
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == moved
    assert not pg.is_disabled("#zreset")
    # another browser context (what render.py --check opens) draws the computed layout
    assert opened(spec).evaluate(LAYOUT) == computed


def test_blocked_storage_still_renders_and_drags(opened):
    blocked = "Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });"
    pg = opened(_spec("example-order.json"), init=blocked)
    before = pg.evaluate(LAYOUT)
    _drag(pg, '.grip[data-card="dto"]', 0, 50)
    assert pg.evaluate(LAYOUT)["cards"]["dto"]["y"] > before["cards"]["dto"]["y"]


def test_a_stale_stored_order_is_ignored(opened):
    spec = _spec("example-order.json")
    pg = opened(spec)
    computed = pg.evaluate(LAYOUT)
    key = pg.evaluate("() => Object.keys(localStorage)")
    assert key == []
    _drag(pg, '.grip[data-card="dto"]', 0, 40)
    key = pg.evaluate("() => Object.keys(localStorage)")[0]
    pg.evaluate("k => localStorage.setItem(k, JSON.stringify({ dto: { dy: 0, order: ['id', 'nope'] } }))", key)
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == computed


# ── resizing a card and spacing its rows ──

def _edge(cid, side):
    return f'.rsz[data-card="{cid}"][data-side="{side}"] .rszhit'


def _tops(card):
    """each row's top as an offset from the card's top, in rowOrder"""
    return [card["rows"][f]["y"] - card["rows"][f]["h"] / 2 - card["y"] for f in card["rowOrder"]]


def _assert_rows_fit(card):
    top = card["y"] + 46
    for fid in card["rowOrder"]:
        r = card["rows"][fid]
        assert r["y"] - r["h"] / 2 >= top - 0.02, "rows overlap or sit over the header"
        top = r["y"] + r["h"] / 2
    assert top <= card["y"] + card["h"] + 0.02, "a row hangs out of its card"


def _assert_wires_on_rows(L):
    for w in L["wires"]:
        for end, at in (("from", "start"), ("to", "end")):
            _, r = _row(L, w[end])
            assert r["y"] - r["h"] / 2 <= w[at][1] <= r["y"] + r["h"] / 2


def test_resizing_the_bottom_edge_grows_the_card_and_keeps_rows_and_wires(opened):
    pg = opened(_spec("example-order.json"))
    before, k = pg.evaluate(LAYOUT), _zoom(pg)
    _drag(pg, _edge("dto", "bottom"), 0, 90)
    after = pg.evaluate(LAYOUT)
    c0, c1 = before["cards"]["dto"], after["cards"]["dto"]
    assert c1["h"] == pytest.approx(c0["h"] + round(90 / k), abs=1)
    assert (c1["y"], c1["rows"], c1["rowOrder"]) == (c0["y"], c0["rows"], c0["rowOrder"])
    # nothing on a row moved, so no wire did
    assert [(w["start"], w["end"]) for w in after["wires"]] == [(w["start"], w["end"]) for w in before["wires"]]
    assert pg.evaluate("() => window.__layoutReport") is not None
    # the opened space is drawn as a band
    assert pg.locator('.cardg[data-card="dto"] .rowgap').count() == 1
    assert not pg.is_disabled("#zreset")


def test_a_card_cannot_shrink_below_its_rows(opened):
    pg = opened(_spec("example-order.json"))
    before = pg.evaluate(LAYOUT)
    _drag(pg, _edge("dto", "bottom"), 0, -200)
    assert pg.evaluate(LAYOUT) == before
    _drag(pg, _edge("dto", "top"), 0, 200)
    assert pg.evaluate(LAYOUT) == before


def test_resizing_the_top_edge_keeps_the_bottom_and_the_rows(opened):
    pg = opened(_spec("example-order.json"))
    before = pg.evaluate(LAYOUT)
    _drag(pg, _edge("dto", "top"), 0, -60)
    c0, c1 = before["cards"]["dto"], pg.evaluate(LAYOUT)["cards"]["dto"]
    assert c1["y"] < c0["y"]
    assert c1["y"] + c1["h"] == pytest.approx(c0["y"] + c0["h"], abs=0.02)
    assert c1["rows"] == c0["rows"]


def test_shrinking_pushes_rows_only_as_far_as_needed(opened):
    pg = opened(_spec("example-order.json"))
    k = _zoom(pg)
    _drag(pg, _edge("dto", "bottom"), 0, 120 * k)
    last = pg.evaluate(LAYOUT)["cards"]["dto"]["rowOrder"][-1]
    _drag(pg, f'[data-node="dto.{last}"] .hit', 0, 100 * k)
    spread = pg.evaluate(LAYOUT)["cards"]["dto"]
    _drag(pg, _edge("dto", "bottom"), 0, -60 * k)
    c = pg.evaluate(LAYOUT)["cards"]["dto"]
    _assert_rows_fit(c)
    t0, t1 = _tops(spread), _tops(c)
    assert t1[:-1] == pytest.approx(t0[:-1], abs=0.02)        # the rows the edge never reached stay
    assert t1[-1] == pytest.approx(c["h"] - c["rows"][last]["h"], abs=0.02)   # the last one rides the edge


def test_a_row_moves_freely_inside_a_tall_card_and_its_wires_follow(opened):
    pg = opened(_spec("example-order.json"))
    k = _zoom(pg)
    _drag(pg, _edge("dto", "bottom"), 0, 120 * k)
    before = pg.evaluate(LAYOUT)
    c0 = before["cards"]["dto"]
    last = c0["rowOrder"][-1]
    _drag(pg, f'[data-node="dto.{last}"] .hit', 0, 50 * k)
    after = pg.evaluate(LAYOUT)
    c1 = after["cards"]["dto"]
    assert c1["rowOrder"] == c0["rowOrder"] and (c1["y"], c1["h"]) == (c0["y"], c0["h"])
    shift = c1["rows"][last]["y"] - c0["rows"][last]["y"]
    assert shift == pytest.approx(50, abs=1)
    assert float(_tops(c1)[-1]).is_integer()                   # snapped to whole pixels
    for fid in c0["rowOrder"][:-1]:
        assert c1["rows"][fid] == c0["rows"][fid]
    n = 0
    for w0, w1 in zip(before["wires"], after["wires"]):
        for end, at in (("from", "start"), ("to", "end")):
            if w0[end] == f"dto.{last}":
                n += 1
                assert w1[at][1] == pytest.approx(w0[at][1] + shift, abs=0.05)
    assert n
    _assert_wires_on_rows(after)


def test_reordering_inside_a_resized_card_swaps_and_lands_where_released(opened):
    pg = opened(_spec("example-order.json"))
    k = _zoom(pg)
    _drag(pg, _edge("dto", "bottom"), 0, 150 * k)
    before = pg.evaluate(LAYOUT)
    c0 = before["cards"]["dto"]
    first, second = c0["rowOrder"][:2]
    # past the second row's centre, into the free space below the last row
    target = c0["rows"][c0["rowOrder"][-1]]["y"] + c0["rows"][c0["rowOrder"][-1]]["h"] / 2 + 40 + c0["rows"][first]["h"] / 2
    _drag(pg, f'[data-node="dto.{first}"] .hit', 0, (target - c0["rows"][first]["y"]) * k)
    c1 = pg.evaluate(LAYOUT)["cards"]["dto"]
    assert c1["rowOrder"] == c0["rowOrder"][1:] + [first]
    assert c1["rows"][first]["y"] == pytest.approx(target, abs=1)
    _assert_rows_fit(c1)
    # with space between two rows, dragging one just past its neighbour's centre swaps them,
    # the dropped row lands where released, and the neighbour gives way only as it must
    pg2 = opened(_spec("example-order.json"))
    _drag(pg2, _edge("dto", "bottom"), 0, 150 * k)
    third, last = c0["rowOrder"][2], c0["rowOrder"][3]
    _drag(pg2, f'[data-node="dto.{last}"] .hit', 0, 100 * k)     # open space above the last row
    c0 = pg2.evaluate(LAYOUT)["cards"]["dto"]
    hop = c0["rows"][last]["y"] - c0["rows"][third]["y"] + 4
    _drag(pg2, f'[data-node="dto.{third}"] .hit', 0, hop * k)
    c1 = pg2.evaluate(LAYOUT)["cards"]["dto"]
    assert c1["rowOrder"] == c0["rowOrder"][:2] + [last, third]
    assert c1["rows"][third]["y"] == pytest.approx(c0["rows"][third]["y"] + hop, abs=1)
    _assert_rows_fit(c1)
    # and dragged back up past it, the two swap back
    _drag(pg2, f'[data-node="dto.{third}"] .hit', 0, -hop * k)
    assert pg2.evaluate(LAYOUT)["cards"]["dto"]["rowOrder"] == c0["rowOrder"]


def test_rows_never_overlap_however_far_a_row_is_dragged(opened):
    pg = opened(_spec("example-order.json"))
    k = _zoom(pg)
    _drag(pg, _edge("dto", "bottom"), 0, 40 * k)
    for fid, dy in (("id", 400), ("total", -400), ("cname", 25), ("cid", -13)):
        _drag(pg, f'[data-node="dto.{fid}"] .hit', 0, dy * k)
        L = pg.evaluate(LAYOUT)
        _assert_rows_fit(L["cards"]["dto"])
        _assert_wires_on_rows(L)


def test_a_packed_card_still_reorders_by_slot(opened):
    pg = opened(_spec("example-order.json"))
    before = pg.evaluate(LAYOUT)
    c0 = before["cards"]["dto"]
    _drag(pg, f'[data-node="dto.{c0["rowOrder"][0]}"] .hit', 0, 300)
    c1 = pg.evaluate(LAYOUT)["cards"]["dto"]
    assert c1["rowOrder"] == c0["rowOrder"][1:] + c0["rowOrder"][:1]
    assert (c1["y"], c1["h"]) == (c0["y"], c0["h"])
    assert _tops(c1) == pytest.approx([46 + sum(c1["rows"][f]["h"] for f in c1["rowOrder"][:i]) for i in range(4)], abs=0.02)


def test_size_and_spacing_persist_and_reset(opened):
    spec = _spec("example-order.json")
    pg = opened(spec)
    computed, report = pg.evaluate(LAYOUT), pg.evaluate("() => window.__layoutReport")
    k = _zoom(pg)
    _drag(pg, _edge("dto", "bottom"), 0, 100 * k)
    _drag(pg, '[data-node="dto.total"] .hit', 0, 70 * k)
    _drag(pg, _edge("json", "top"), 0, -50 * k)
    moved = pg.evaluate(LAYOUT)
    assert moved != computed
    assert pg.evaluate("() => window.__layoutReport") == report
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == moved
    pg.click("#zreset")
    assert pg.evaluate(LAYOUT) == computed
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == computed


@pytest.mark.parametrize("bad", [
    {"dto": {"dy": 0, "order": ["id", "cid", "cname", "total"], "h": 50}},                      # rows do not fit
    {"dto": {"dy": 0, "order": ["id", "cid", "cname", "total"], "h": 400, "tops": [46, 50, 120, 200]}},   # overlap
    {"dto": {"dy": 0, "order": ["id", "cid", "cname", "total"], "h": 200, "tops": [46, 80, 120, 190]}},   # out of the card
    {"dto": {"dy": 0, "order": ["id", "cid", "cname", "total"], "h": "tall"}},
])
def test_an_outdated_saved_card_is_ignored(opened, bad):
    pg = opened(_spec("example-order.json"))
    computed = pg.evaluate(LAYOUT)
    _drag(pg, '.grip[data-card="dto"]', 0, 40)
    key = pg.evaluate("() => Object.keys(localStorage)")[0]
    pg.evaluate("([k, v]) => localStorage.setItem(k, JSON.stringify(v))", [key, bad])
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == computed


# ── undo, redo, reset ──

UNDO, REDO = "Control+z", "Control+Shift+z"


def test_undo_and_redo_step_through_every_kind_of_change(opened):
    pg = opened(_spec("example-order.json"))
    k = _zoom(pg)
    states = [pg.evaluate(LAYOUT)]
    assert pg.is_disabled("#zundo") and pg.is_disabled("#zredo")
    _drag(pg, '.grip[data-card="dto"]', 0, 70)
    states.append(pg.evaluate(LAYOUT))
    _drag(pg, _edge("dto", "bottom"), 0, 120 * k)
    states.append(pg.evaluate(LAYOUT))
    _drag(pg, '[data-node="dto.total"] .hit', 0, 60 * k)
    states.append(pg.evaluate(LAYOUT))
    assert len({json.dumps(s, sort_keys=True) for s in states}) == 4
    for i in (2, 1, 0):
        pg.keyboard.press(UNDO)
        assert pg.evaluate(LAYOUT) == states[i]
    assert pg.is_disabled("#zundo") and pg.is_disabled("#zreset")
    for i in (1, 2, 3):
        pg.keyboard.press(REDO)
        assert pg.evaluate(LAYOUT) == states[i]
    assert pg.is_disabled("#zredo")
    pg.click("#zundo")
    assert pg.evaluate(LAYOUT) == states[2]
    pg.keyboard.press("Control+y")
    assert pg.evaluate(LAYOUT) == states[3]
    # what is stored follows the current step
    pg.keyboard.press(UNDO)
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert pg.evaluate(LAYOUT) == states[2]


def test_a_new_change_after_undo_drops_the_redo_branch(opened):
    pg = opened(_spec("example-order.json"))
    _drag(pg, '.grip[data-card="dto"]', 0, 70)
    pg.keyboard.press(UNDO)
    assert not pg.is_disabled("#zredo")
    _drag(pg, '.grip[data-card="json"]', 0, -40)
    assert pg.is_disabled("#zredo")


def test_r_and_the_button_reset_to_the_computed_layout_and_reset_is_undoable(opened):
    pg = opened(_spec("example-order.json"))
    computed = pg.evaluate(LAYOUT)
    assert pg.is_disabled("#zreset") and pg.get_attribute("#zreset", "class") == "btn"
    _drag(pg, '.grip[data-card="dto"]', 0, 70)
    _drag(pg, _edge("json", "bottom"), 0, 60)
    moved = pg.evaluate(LAYOUT)
    assert not pg.is_disabled("#zreset") and "dirty" in pg.get_attribute("#zreset", "class")
    assert pg.text_content("#zcount") == "2"
    pg.keyboard.press("r")
    assert json.dumps(pg.evaluate(LAYOUT)) == json.dumps(computed)
    assert pg.is_disabled("#zreset") and pg.text_content("#zcount") == ""
    pg.keyboard.press(UNDO)
    assert pg.evaluate(LAYOUT) == moved
    pg.click("#zreset")
    assert json.dumps(pg.evaluate(LAYOUT)) == json.dumps(computed)
    pg.reload()
    pg.wait_for_function("() => window.__layoutReport")
    assert json.dumps(pg.evaluate(LAYOUT)) == json.dumps(computed)


def test_reset_and_undo_are_findable(opened):
    pg = opened(_spec("example-order.json"))
    assert pg.is_visible("#title #zreset") and pg.text_content("#zreset").startswith("Reset layout")
    assert pg.is_visible("#zundo") and pg.is_visible("#zredo")
    help_ = pg.inner_text("#help")
    assert "R resets" in help_ and "undoes" in help_
    pg.set_viewport_size({"width": 800, "height": 700})
    assert pg.is_visible("#help") and "R resets" in pg.inner_text("#help")
