"""The field canvas in Chromium: the engine's geometry, read back from the page.

The engine publishes what it computed on window.__layout and window.__layoutReport,
so these tests assert on the drawing's actual coordinates rather than on markup."""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from skills.dataflow.fields import render  # noqa: E402

FIELDS = Path(__file__).resolve().parents[1] / "fields"


def _spec(name):
    return json.loads((FIELDS / name).read_text())


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _load(browser, spec):
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    pg.set_content(render.render(spec))
    pg.wait_for_function("() => window.__layoutReport")
    out = pg.evaluate("() => ({ L: window.__layout, R: window.__layoutReport })")
    pg.close()
    return out["L"], out["R"]


def _slot(spec, end):
    return next(c["slot"] for c in spec["cards"] if c["id"] == end.split(".")[0])


@pytest.mark.parametrize("name", ["example-order.json", "example-bypass.json"])
def test_no_wire_behind_a_card(browser, name):
    _, rep = _load(browser, _spec(name))
    assert rep["behind_card"] == 0


@pytest.mark.parametrize("name", ["example-order.json", "example-bypass.json"])
def test_arrowheads_land_on_their_rows(browser, name):
    L, _ = _load(browser, _spec(name))
    for w in L["wires"]:
        cid, fid = w["to"].split(".", 1)
        row, card = L["cards"][cid]["rows"][fid], L["cards"][cid]
        assert abs(w["end"][0] - card["x"]) < 0.5
        assert row["y"] - row["h"] / 2 <= w["end"][1] <= row["y"] + row["h"] / 2


def test_wires_sharing_a_row_get_distinct_ordered_ports(browser):
    L, _ = _load(browser, _spec("example-bypass.json"))
    by_target = {}
    for w in L["wires"]:
        by_target.setdefault(w["to"], []).append(w)
    busy = [ws for ws in by_target.values() if len(ws) >= 3]
    assert busy
    for ws in busy:
        ends = [w["end"][1] for w in ws]
        assert len({round(y, 1) for y in ends}) == len(ends)
        starts = [w["start"][1] for w in sorted(ws, key=lambda w: w["end"][1])]
        assert starts == sorted(starts)


def test_real_order_holds_without_follow(browser):
    spec = _spec("example-bypass.json")
    L, _ = _load(browser, spec)
    for c in spec["cards"]:
        if c.get("rows") == "follow":
            continue
        ys = [L["cards"][c["id"]]["rows"][f["id"]]["y"] for f in c["fields"]]
        assert ys == sorted(ys)


def test_lane_override_goes_below(browser):
    spec = _spec("example-bypass.json")
    e = next(e for e in spec["edges"] if e.get("lane") == "below")
    L, _ = _load(browser, spec)
    w = next(w for w in L["wires"] if w["from"] == e["from"] and w["to"] == e["to"])
    skipped = [c for c in spec["cards"] if _slot(spec, e["from"]) < c["slot"] < _slot(spec, e["to"])]
    assert skipped
    for c in skipped:
        box = L["cards"][c["id"]]
        mid = box["x"] + box["w"] / 2
        y = min(w["samples"], key=lambda p: abs(p[0] - mid))[1]
        assert y > box["y"] + box["h"]


def test_no_nan_in_layout(browser):
    L, rep = _load(browser, _spec("example-bypass.json"))
    assert "NaN" not in json.dumps(L) and "null" not in json.dumps(rep)


def test_gap_holds_longest_label(browser):
    spec = _spec("example-order.json")
    spec["edges"][0]["label"] = "x" * 90
    _, rep = _load(browser, spec)
    assert rep["label_overlaps"] == 0


def test_layout_is_deterministic(browser):
    spec = _spec("example-bypass.json")
    assert render.render(spec) == render.render(spec)
    assert _load(browser, spec) == _load(browser, spec)


def _check(tmp_path, spec):
    import subprocess
    import sys
    src = tmp_path / "s.json"
    src.write_text(json.dumps(spec))
    out = tmp_path / "s.html"
    r = subprocess.run([sys.executable, str(FIELDS / "render.py"), str(src), "--check", str(out)],
                       capture_output=True, text=True, timeout=120)
    return r, out


def test_check_writes_png_and_reports(tmp_path):
    r, out = _check(tmp_path, _spec("example-bypass.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists() and out.with_suffix(".png").stat().st_size > 10_000
    for name in ("behind_card", "label_overlaps", "crossings", "max_steepness", "detour"):
        assert f"{name}:" in r.stdout


def _main(monkeypatch, tmp_path, run):
    import sys
    src = tmp_path / "s.json"
    src.write_text((FIELDS / "example-order.json").read_text())
    monkeypatch.setattr(render._check, "run", run)
    monkeypatch.setattr(sys, "argv", ["render.py", str(src), "--check", str(tmp_path / "s.html")])
    return render.main()


def test_check_exits_1_when_a_target_is_missed(monkeypatch, tmp_path, capsys):
    report = dict.fromkeys(render._check.MEASURES, 0) | {"label_overlaps": 2}
    assert _main(monkeypatch, tmp_path, lambda p: report) == 1
    assert "label_overlaps: 2" in capsys.readouterr().out


def test_check_exits_2_without_playwright(monkeypatch, tmp_path, capsys):
    def missing(p):
        raise ImportError("No module named 'playwright'")
    assert _main(monkeypatch, tmp_path, missing) == 2
    assert "pip install playwright" in capsys.readouterr().out


def test_a_wire_note_is_drawn_and_placed(browser):
    spec = _spec("example-order.json")
    spec["edges"][0]["note"] = "only on create"
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    pg.set_content(render.render(spec))
    pg.wait_for_function("() => window.__layoutReport")
    notes = pg.evaluate("() => [...document.querySelectorAll('.enote')].map(t => t.textContent)")
    rep = pg.evaluate("() => window.__layoutReport")
    pg.close()
    assert notes == ["only on create"]
    assert rep["label_overlaps"] == 0


def _page(browser, spec):
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    pg.set_content(render.render(spec))
    pg.wait_for_function("() => window.__layoutReport", timeout=5000)
    return pg


def test_dotted_field_id_fits_the_lit_path(browser):
    spec = _spec("example-order.json")
    spec["cards"][1]["fields"].append({"id": "addr.city", "label": "address.city"})
    spec["edges"].append({"from": "entity.customer", "to": "dto.addr.city"})
    pg = _page(browser, spec)
    pg.focus('[data-node="dto.addr.city"]')
    pg.keyboard.press("Enter")
    pg.keyboard.press("f")
    pg.wait_for_timeout(450)
    t = pg.get_attribute("#cam", "transform")
    pg.close()
    assert "NaN" not in t


def test_script_like_text_in_the_spec_still_renders(browser):
    spec = _spec("example-order.json")
    spec["lede"] = "a comment opener <!--<script> in prose"
    _page(browser, spec).close()


def test_shot_mode_hides_all_chrome(browser):
    pg = _page(browser, _spec("example-order.json"))
    pg.evaluate("() => document.body.classList.add('shot')")
    shown = pg.evaluate("""() => ['#title', '#legend', '#nav', '#help', '#about']
      .filter(s => getComputedStyle(document.querySelector(s)).display !== 'none')""")
    pg.close()
    assert shown == []


def test_a_long_note_widens_its_gap(browser):
    spec = _spec("example-order.json")
    spec["edges"][0]["note"] = "n" * 120
    _, rep = _load(browser, spec)
    assert rep["label_overlaps"] == 0


def test_check_fails_fast_on_an_engine_error(tmp_path):
    import time
    from skills.dataflow.fields import check
    page = render.render(_spec("example-order.json")).replace('"use strict";', '"use strict"; throw new Error("boom");', 1)
    html = tmp_path / "broken.html"
    html.write_text(page)
    # check.run starts its own sync Playwright; the module's browser fixture already
    # holds one on this thread, so run it on another.
    import threading
    caught = []
    t0 = time.monotonic()
    th = threading.Thread(target=lambda: _catch(caught, check.run, html))
    th.start()
    th.join(60)
    assert caught and isinstance(caught[0], check.PageError) and "boom" in str(caught[0]), caught
    assert time.monotonic() - t0 < 15


def _catch(into, fn, *a):
    try:
        fn(*a)
    except Exception as e:  # noqa: BLE001 - the test inspects whatever was raised
        into.append(e)


def test_check_exits_2_without_chromium(tmp_path):
    import os
    import subprocess
    import sys
    src = tmp_path / "s.json"
    src.write_text((FIELDS / "example-order.json").read_text())
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(tmp_path / "no-browsers"))
    r = subprocess.run([sys.executable, str(FIELDS / "render.py"), str(src), "--check", str(tmp_path / "s.html")],
                       capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "playwright install chromium" in r.stdout


def _lit_after_click(browser, spec, node):
    pg = _page(browser, spec)
    pg.focus(f'[data-node="{node}"]')
    pg.keyboard.press("Enter")
    lit = pg.evaluate("""() => ({
      nodes: [...document.querySelectorAll('.node.on')].map(e => e.dataset.node).sort(),
      edges: [...document.querySelectorAll('.edge.on')].map(e => e.dataset.from + '>' + e.dataset.to).sort() })""")
    pg.close()
    return lit


def test_a_trace_follows_wires_one_way_from_the_field(browser):
    # form.email feeds cmd.email, which joins two other fields in env.body. The trace
    # must go on downstream from env.body, never back up into its other sources.
    lit = _lit_after_click(browser, _spec("example-bypass.json"), "form.email")
    assert lit["nodes"] == ["cmd.email", "env.body", "form.email", "req.body"]
    assert lit["edges"] == ["cmd.email>env.body", "env.body>req.body", "form.email>cmd.email"]


def test_a_trace_from_a_fan_in_lights_every_source_upstream(browser):
    lit = _lit_after_click(browser, _spec("example-bypass.json"), "env.body")
    assert lit["nodes"] == ["cmd.consent", "cmd.email", "cmd.profile", "ctx.locale", "env.body",
                            "form.displayName", "form.email", "form.optIn", "req.body"]
