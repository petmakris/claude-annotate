"""The field canvas in Chromium: the engine's geometry, read back from the page.

The engine publishes what it computed on window.__layout and window.__layoutReport,
so these tests assert on the drawing's actual coordinates rather than on markup. Each
reading rule of the layout spec (docs/superpowers/specs/2026-10-02-dataflow-field-layout-
design.md, R1-R9) is pinned by at least one test here."""
import json
import random
import statistics
from pathlib import Path

import pytest

from skills.tests.harness import T, require_playwright  # noqa: E402

require_playwright()

from skills.dataflow.fields import render  # noqa: E402

FIELDS = Path(__file__).resolve().parents[1] / "fields"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TARGETS = ("behind_card", "label_overlaps", "source_slack", "improvable_swaps", "loose_sources")


def _spec(name):
    return json.loads((FIELDS / name).read_text())


def _card(cid, *fields, **kw):
    return {"id": cid, "name": kw.pop("name", cid), "fields": [{"id": f, "label": f} for f in fields], **kw}


def _edges(*pairs, **kw):
    return [{"from": a, "to": b, **kw} for a, b in (p.split(" > ") for p in pairs)]


# ── inline specs (all made up) ──
# S feeds T and U, which share a column; S.mid reaches D past both of them.
CORRIDOR = {"title": "Corridor", "cards": [
    _card("S", "t1", "t2", "mid", "u1", "u2"), _card("T", "t1", "t2"), _card("U", "u1", "u2"), _card("D", "t", "mid", "u")],
    "edges": _edges("S.t1 > T.t1", "S.t2 > T.t2", "S.u1 > U.u1", "S.u2 > U.u2", "T.t2 > D.t", "U.u1 > D.u", "S.mid > D.mid")}
# Two real-order cards wired crosswise: one crossing is forced, and its two hops meet
# exactly at their middle sample.
CROSSWISE = {"title": "Crosswise", "cards": [_card("A", "x", "y"), _card("B", "x", "y")],
             "edges": _edges("A.x > B.y", "A.y > B.x")}
NO_EDGES = {"title": "No wires", "cards": [_card("a", "x"), _card("b", "x", "y", "z"), _card("c", "x")], "edges": []}
# Two flows; the first sends a `lane: "below"` wire past a1, the second runs beside it.
TWO_FLOWS = {"title": "Two flows", "cards": [
    _card("a0", "x", "y"), _card("b0", "p"), _card("a1", "x", "y"), _card("b1", "p", "q"), _card("a2", "x", "y", "z"), _card("b2", "p")],
    "edges": _edges("a0.x > a1.x", "a0.y > a1.y", "a1.x > a2.x", "a1.y > a2.y", "b0.p > b1.p", "b1.p > b2.p", "b0.p > b2.p")
    + _edges("a0.x > a2.z", lane="below")}
# A follow card whose field ids are integer-like: a JavaScript object lists such keys in
# numeric order, so only rowOrder can say which row is drawn first.
FOLLOW_NUMERIC = {"title": "Numbered rows", "cards": [
    _card("src", "a", "b", "c"), _card("args", "0", "1", "2", "3", rows="follow"), _card("out", "p", "q", "r")],
    "edges": _edges("src.a > args.3", "src.b > args.2", "src.c > args.0", "args.3 > out.p", "args.2 > out.q", "args.0 > out.r")}
# Two cards without wires after the last wired card, listed against id order.
WIRELESS = {"title": "Loose cards", "cards": [_card("a", "x"), _card("b", "x"), _card("zeta", "n"), _card("alpha", "n")],
            "edges": _edges("a.x > b.x")}

EXAMPLES = {n: _spec(f"example-{n}.json") for n in ("order", "bypass", "sketch", "context")}
INLINE = {"corridor": CORRIDOR, "crosswise": CROSSWISE, "no-edges": NO_EDGES, "two-flows": TWO_FLOWS,
          "follow-numeric": FOLLOW_NUMERIC, "wireless": WIRELESS}
ALL = {**EXAMPLES, **INLINE}
ONE_FLOW = ["order", "bypass", "sketch", "context", "corridor", "crosswise", "follow-numeric"]


def _load(browser, spec):
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    pg.set_content(render.render(spec))
    pg.wait_for_function("() => window.__layoutReport")
    out = pg.evaluate("() => ({ L: window.__layout, R: window.__layoutReport })")
    pg.close()
    return out["L"], out["R"]


def _engine(browser, script, arg=None):
    """Run `script` (a JS function of one argument) against window.__fieldEngine."""
    pg = browser.new_page()
    pg.set_content(render.render(EXAMPLES["order"]))
    pg.wait_for_function("() => window.__fieldEngine")
    out = pg.evaluate(script, arg)
    pg.close()
    return out


def _col(L, cid):
    return L["cards"][cid]["col"]


def _items(L, k):
    return L["columns"][k]["items"]


def _sources(spec):
    """Cards that nothing feeds and that feed something; a card without wires is not one."""
    fed = {e["to"].split(".")[0] for e in spec["edges"]}
    feeds = {}
    for e in spec["edges"]:
        feeds.setdefault(e["from"].split(".")[0], set()).add(e["to"].split(".")[0])
    return {c: v for c, v in feeds.items() if c not in fed}


def _copies(spec):
    """Edges whose row sends one wire and whose target row receives one."""
    outs, ins = {}, {}
    for e in spec["edges"]:
        outs[e["from"]] = outs.get(e["from"], 0) + 1
        ins[e["to"]] = ins.get(e["to"], 0) + 1
    return [(e["from"], e["to"]) for e in spec["edges"] if outs[e["from"]] == 1 and ins[e["to"]] == 1]


def _wire(L, a, b):
    return next(w for w in L["wires"] if w["from"] == a and w["to"] == b)


# ── the targets and the reading rules ──

@pytest.mark.parametrize("name", list(ALL))
def test_targets_hold(browser, name):
    _, rep = _load(browser, ALL[name])
    assert {t: rep[t] for t in TARGETS} == dict.fromkeys(TARGETS, 0)


@pytest.mark.parametrize("name", list(ALL))
def test_sources_sit_one_column_before_their_consumer(browser, name):
    spec = ALL[name]
    L, _ = _load(browser, spec)
    for src, fed in _sources(spec).items():
        assert _col(L, src) == min(_col(L, c) for c in fed) - 1, src


def _canon(L, spec):
    """__layout with wires, labels and lanes keyed by their two ends instead of an index."""
    ends = [f'{e["from"]}>{e["to"]}' for e in spec["edges"]]
    return {
        "cards": L["cards"],
        "wires": {f'{w["from"]}>{w["to"]}': w for w in L["wires"]},
        "labels": sorted(json.dumps({**t, "edge": ends[t["edge"]]}, sort_keys=True) for t in L["labels"]),
        "columns": [{**c, "items": [i if "card" in i else {"lane": ends[i["lane"]]} for i in c["items"]]} for c in L["columns"]],
    }


def _variants(spec):
    rng = random.Random(7)
    out = {}
    for label, slots in (("zeroed", lambda i: 0), ("scrambled", lambda i: rng.randint(0, 9)), ("backwards", lambda i: 9 - i)):
        s = json.loads(json.dumps(spec))
        for i, c in enumerate(s["cards"]):
            c["slot"] = slots(i)
        out[label] = s
    s = json.loads(json.dumps(spec))
    s["cards"].reverse()
    out["cards reversed"] = s
    s = json.loads(json.dumps(spec))
    s["edges"].reverse()
    out["edges reversed"] = s
    return out


@pytest.mark.parametrize("name", ONE_FLOW)
def test_slot_and_card_order_place_nothing(browser, name):
    spec = ALL[name]
    L, rep = _load(browser, spec)
    want = _canon(L, spec)
    for label, variant in _variants(spec).items():
        L2, rep2 = _load(browser, variant)
        assert _canon(L2, variant) == want, label
        assert rep2 == rep, label


def test_separate_flows_stack_in_spec_order(browser):
    def first_flow_on_top(spec):
        L, _ = _load(browser, spec)
        return L["cards"]["a1"]["y"] < L["cards"]["b1"]["y"]
    assert first_flow_on_top(TWO_FLOWS)
    reversed_ = json.loads(json.dumps(TWO_FLOWS))
    reversed_["cards"].reverse()
    assert not first_flow_on_top(reversed_)


@pytest.mark.parametrize("slot", [None, 0])
def test_context_card_docks_level_on_top(browser, slot):
    # A context value feeds only the client's first parameter. With
    # "slot": 0, the mistake that sent its wire across the whole figure, nothing changes.
    spec = _spec("example-context.json")
    if slot is not None:
        next(c for c in spec["cards"] if c["id"] == "ctxTenant")["slot"] = slot
    L, _ = _load(browser, spec)
    k = _col(L, "client") - 1
    assert _col(L, "ctxTenant") == k
    assert _items(L, k)[0] == {"card": "ctxTenant"}
    w = _wire(L, "ctxTenant.tenant", "client.tenant")
    assert abs(w["start"][1] - w["end"][1]) < 0.5


def test_sketch_keeps_its_shape(browser):
    # Source A feeds the consumer's top row and sits above and left of it; source B feeds
    # the bottom row and sits below and left of it; the chain flows in between.
    spec = _spec("example-sketch.json")
    L, rep = _load(browser, spec)
    assert {c: _col(L, c) for c in ("opts", "entry", "A", "mid", "B", "C")} == \
        {"opts": 0, "entry": 0, "A": 1, "mid": 1, "B": 1, "C": 2}
    lane = spec["edges"].index(next(e for e in spec["edges"] if e["from"] == "entry.raw"))
    assert _items(L, 1) == [{"card": "A"}, {"card": "mid"}, {"lane": lane}, {"card": "B"}]
    assert rep["crossings"] == 0
    A, B, C = (L["cards"][c] for c in "ABC")
    assert A["y"] + A["h"] < C["y"]
    assert B["y"] > C["y"] + C["h"]
    for a, b in (("mid.mode", "C.mode"), ("mid.owner", "C.owner"), ("entry.raw", "C.file")):
        w = _wire(L, a, b)
        assert all(abs(p[1] - w["start"][1]) < 0.5 for p in w["samples"]), (a, b)


def test_long_wire_takes_the_corridor(browser):
    L, rep = _load(browser, CORRIDOR)
    k = _col(L, "T")
    assert _col(L, "U") == k and _col(L, "S") == k - 1 and _col(L, "D") == k + 1
    upper, lower = sorted((L["cards"]["T"], L["cards"]["U"]), key=lambda c: c["y"])
    w = _wire(L, "S.mid", "D.mid")
    col = L["columns"][k]
    over = [p[1] for p in w["samples"] if col["x"] <= p[0] <= col["x"] + col["w"]]
    assert over and max(over) - min(over) < 0.5
    assert upper["y"] + upper["h"] < over[0] < lower["y"]
    assert rep["behind_card"] == 0


def _hops_by_gap(L, spec):
    gaps = {}
    for w in L["wires"]:
        k0 = _col(L, w["from"].split(".")[0])
        for t, hop in enumerate(w["hops"]):
            gaps.setdefault(k0 + t, []).append((hop, w["samples"][37 * t: 37 * t + 25]))
    return gaps


@pytest.mark.parametrize("name", list(ALL))
def test_crossings_are_exact(browser, name):
    # Every hop in one gap shares x(t), so two hops cross exactly once when their end
    # orders are inverted and never otherwise. A segment-intersection test would miss the
    # crosswise spec, whose two hops meet exactly at the middle sample.
    spec = ALL[name]
    L, rep = _load(browser, spec)
    count = 0
    for hops in _hops_by_gap(L, spec).values():
        for i in range(len(hops)):
            for j in range(i + 1, len(hops)):
                (a, sa), (b, sb) = hops[i], hops[j]
                inverted = (a[1] - b[1]) * (a[3] - b[3]) < 0
                count += inverted
                assert len(sa) == len(sb) == 25 and all(abs(p[0] - q[0]) < 0.01 for p, q in zip(sa, sb))
                signs = [d > 0 for d in (p[1] - q[1] for p, q in zip(sa, sb)) if d != 0]
                changes = sum(x != y for x, y in zip(signs, signs[1:]))
                assert changes == (1 if inverted else 0), (a, b)
    assert rep["crossings"] == count
    if name == "crosswise":
        assert count == 1


# Optimal crossing counts, computed once by an offline ILP over every column order
# (pairwise order variables with transitivity).
OPTIMUM = {"order": 0, "bypass": 6, "sketch": 0, "context": 6}


@pytest.mark.parametrize("name", list(OPTIMUM))
def test_crossings_reach_the_optimum(browser, name):
    _, rep = _load(browser, EXAMPLES[name])
    assert rep["crossings"] == OPTIMUM[name]


@pytest.mark.parametrize("name", ["order", "sketch"])
def test_copies_are_straight(browser, name):
    spec = EXAMPLES[name]
    L, rep = _load(browser, spec)
    copies = _copies(spec)
    if name == "sketch":
        # A, B and opts are sources that the stacking cannot set level (mid and its header
        # hold that height), so their docks bend by construction, as the sketch draws them;
        # every other copy is straight.
        copies = [(a, b) for a, b in copies if a.split(".")[0] not in ("A", "B", "opts")]
        assert {a for a, _ in copies} == {"mid.mode", "mid.owner", "entry.user", "entry.raw"}
    assert copies
    for a, b in copies:
        w = _wire(L, a, b)
        assert abs(w["start"][1] - w["end"][1]) < 0.5, (a, b)
    assert rep["copy_bend"] == 0


def _row_band(L, end):
    cid, fid = end.split(".", 1)
    r = L["cards"][cid]["rows"][fid]
    return r["y"] - r["h"] / 2, r["y"] + r["h"] / 2


def _ports_inside(L):
    for w in L["wires"]:
        for end, (x, y) in ((w["from"], w["start"]), (w["to"], w["end"])):
            lo, hi = _row_band(L, end)
            assert lo + 8 - 1e-6 <= y <= hi - 8 + 1e-6, (end, y, lo, hi)
        c = L["cards"][w["to"].split(".")[0]]
        assert abs(w["end"][0] - c["x"]) < 0.5
        c = L["cards"][w["from"].split(".")[0]]
        assert abs(w["start"][0] - (c["x"] + c["w"])) < 0.5


@pytest.mark.parametrize("name", list(ALL))
def test_ports_stay_inside_their_rows(browser, name):
    L, _ = _load(browser, ALL[name])
    _ports_inside(L)


def _rows_touch(L):
    for cid, c in L["cards"].items():
        rows = [c["rows"][f] for f in c["rowOrder"]]
        assert abs(rows[0]["y"] - rows[0]["h"] / 2 - (c["y"] + 46)) < 0.02, cid
        for p, q in zip(rows, rows[1:]):
            assert abs(p["y"] + p["h"] / 2 - (q["y"] - q["h"] / 2)) < 0.02, cid
        assert abs(rows[-1]["y"] + rows[-1]["h"] / 2 - (c["y"] + c["h"])) < 0.02, cid


@pytest.mark.parametrize("name", list(ALL))
def test_rows_touch(browser, name):
    L, _ = _load(browser, ALL[name])
    _rows_touch(L)


def _real_order(L, spec):
    for c in spec["cards"]:
        if c.get("rows") != "follow":
            assert L["cards"][c["id"]]["rowOrder"] == [f["id"] for f in c["fields"]], c["id"]


@pytest.mark.parametrize("name", list(ALL))
def test_real_order_holds_without_follow(browser, name):
    spec = ALL[name]
    L, _ = _load(browser, spec)
    _real_order(L, spec)


def test_follow_rows(browser):
    L, _ = _load(browser, EXAMPLES["bypass"])
    # wired rows follow their wires; contentType, which has none, trails
    assert L["cards"]["env"]["rowOrder"] == ["body", "tenant", "attachment", "ctype"]
    L, _ = _load(browser, FOLLOW_NUMERIC)
    args = L["cards"]["args"]
    assert args["rowOrder"] == sorted(args["rows"], key=lambda f: args["rows"][f]["y"])
    assert args["rowOrder"] == ["3", "2", "0", "1"]


def test_cards_without_wires(browser):
    L, _ = _load(browser, EXAMPLES["bypass"])
    last = len(L["columns"]) - 1
    assert _items(L, last)[-1] == {"card": "audit"}
    # several of them in one column keep spec order, under everything else there
    L, _ = _load(browser, WIRELESS)
    k = _col(L, "b")
    assert _items(L, k) == [{"card": "b"}, {"card": "zeta"}, {"card": "alpha"}]
    # a spec without edges lays its cards out left to right, top-aligned
    L, rep = _load(browser, NO_EDGES)
    assert [_col(L, c["id"]) for c in NO_EDGES["cards"]] == [0, 1, 2]
    assert len({L["cards"][c["id"]]["y"] for c in NO_EDGES["cards"]}) == 1
    assert rep["hops"] == 0


def test_lane_stays_in_its_flow(browser):
    L, _ = _load(browser, TWO_FLOWS)
    w = _wire(L, "a0.x", "a2.z")
    assert len(w["hops"]) == 2
    k = _col(L, "a1")
    assert _items(L, k)[1] == {"lane": len(TWO_FLOWS["edges"]) - 1}
    y = w["hops"][0][3]
    assert L["cards"]["a1"]["y"] + L["cards"]["a1"]["h"] < y < L["cards"]["b1"]["y"]


def test_lane_override_goes_below(browser):
    spec = EXAMPLES["bypass"]
    e = next(e for e in spec["edges"] if e.get("lane") == "below")
    L, _ = _load(browser, spec)
    w = _wire(L, e["from"], e["to"])
    a, b = _col(L, e["from"].split(".")[0]), _col(L, e["to"].split(".")[0])
    skipped = [c for c in spec["cards"] if a < _col(L, c["id"]) < b]
    assert skipped
    for c in skipped:
        box = L["cards"][c["id"]]
        mid = box["x"] + box["w"] / 2
        y = min(w["samples"], key=lambda p: abs(p[0] - mid))[1]
        assert y > box["y"] + box["h"]


def test_wires_sharing_a_row_get_distinct_ordered_ports(browser):
    L, _ = _load(browser, EXAMPLES["bypass"])
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


def _measure(browser, spec, mutate):
    pg = browser.new_page()
    pg.set_content(render.render(spec))
    pg.wait_for_function("() => window.__layoutReport")
    L = pg.evaluate("() => window.__layout")
    mutate(L)
    out = pg.evaluate("(L) => window.__measure(L)", L)
    pg.close()
    return out


def test_measures_catch_the_tenant_context_regressions(browser):
    spec = EXAMPLES["context"]

    def to_column_0(L):                       # complaint 1: the source far from its consumer
        k = L["cards"]["ctxTenant"]["col"]
        L["columns"][k]["items"].remove({"card": "ctxTenant"})
        L["columns"][0]["items"].append({"card": "ctxTenant"})
        L["cards"]["ctxTenant"]["col"] = 0

    def under_the_lane(L):                    # complaint 2: on the wrong side of a wire
        items = L["columns"][L["cards"]["ctxTenant"]["col"]]["items"]
        assert items[0] == {"card": "ctxTenant"} and "lane" in items[1]
        items[0], items[1] = items[1], items[0]

    def up_30(L):                             # R4: left above the row it feeds
        c = L["cards"]["ctxTenant"]
        c["y"] -= 30
        for r in c["rows"].values():
            r["y"] -= 30
        for w in L["wires"]:
            if w["from"].startswith("ctxTenant."):
                w["start"][1] -= 30
                w["hops"][0][1] -= 30

    assert _measure(browser, spec, lambda L: None)["source_slack"] == 0
    assert _measure(browser, spec, to_column_0)["source_slack"] == 2
    assert _measure(browser, spec, under_the_lane)["improvable_swaps"] >= 1
    assert _measure(browser, spec, up_30)["loose_sources"] == 1


@pytest.mark.parametrize("bad, message", [
    ({"from": "json.total", "to": "entity.id"}, "cards feed each other in a loop: entity → dto → json → entity"),
    ({"from": "dto.id", "to": "dto.total"}, "stays inside card 'dto'"),
    ({"from": "entity.id", "to": "dto.id"}, "appears twice"),
])
def test_the_engine_refuses_what_render_refuses(browser, bad, message):
    # A page that skipped render.py must still fail loudly, so --check exits 3.
    spec = EXAMPLES["order"]
    page = render.render(spec)
    broken = json.loads(json.dumps(spec))
    broken["edges"].append(bad)
    page = page.replace(json.dumps(spec, sort_keys=True, ensure_ascii=False).replace("<", "\\u003c"),
                        json.dumps(broken, sort_keys=True, ensure_ascii=False).replace("<", "\\u003c"))
    errors = []
    pg = browser.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.set_content(page)
    pg.wait_for_timeout(100)
    report = pg.evaluate("() => window.__layoutReport || null")
    pg.close()
    assert report is None
    assert any(message in e for e in errors), errors


def test_no_nan_in_layout(browser):
    L, rep = _load(browser, EXAMPLES["bypass"])
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


# ── the solver and the column stage ──

NS_EXHAUSTIVE = """() => {
  const { networkSimplex } = window.__fieldEngine;
  let s = 20261002;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647, ri = (a, b) => a + Math.floor(rnd() * (b - a + 1));
  const bad = [];
  for (let t = 0; t < 200; t++) {
    const n = ri(2, 5), perm = [...Array(n).keys()];
    for (let i = n - 1; i > 0; i--) { const j = ri(0, i); [perm[i], perm[j]] = [perm[j], perm[i]]; }
    const E = [], edge = (i, j) => E.push({ v: perm[i], w: perm[j], minlen: ri(-3, 3), weight: ri(0, 5) });
    for (let i = 1; i < n; i++) edge(ri(0, i - 1), i);                 // connected
    for (let k = ri(0, 4); k > 0; k--) { const i = ri(0, n - 2); edge(i, ri(i + 1, n - 1)); }   // acyclic, parallels allowed
    const cost = (y) => E.reduce((a, e) => a + e.weight * (y[e.w] - y[e.v]), 0);
    const feasible = (y) => E.every((e) => y[e.w] - y[e.v] >= e.minlen);
    // an optimal vertex ties every node to node 0 by at most n - 1 tight edges of |minlen| <= 3
    const R = 3 * (n - 1), z = new Array(n).fill(0);
    let best = Infinity;
    const rec = (v) => {
      if (v === n) { if (feasible(z)) best = Math.min(best, cost(z)); return; }
      for (let x = -R; x <= R; x++) { z[v] = x; rec(v + 1); }
    };
    rec(1);
    const y = networkSimplex(n, E);
    if (!feasible(y) || cost(y) !== best) bad.push({ t, n, E, got: cost(y), best });
  }
  return bad;
}"""


def test_network_simplex_matches_exhaustive_search(browser):
    assert _engine(browser, NS_EXHAUSTIVE) == []


def _random_spec(rng, n_cards, n_edges=None, follow=0.0, labels=0.0, lanes=0.0, flows=1, loose=0.0):
    """A made-up acyclic spec: cards c0…, fields f0…, wires between cards in a hidden order."""
    ids = [f"c{i}" for i in range(n_cards)]
    cards = [_card(c, *[f"f{j}" for j in range(rng.randint(1, 5))], **({"rows": "follow"} if rng.random() < follow else {}))
             for c in ids]
    order = ids[:]
    rng.shuffle(order)
    wired = [c for c in order if rng.random() >= loose] or order[:2]
    groups = [wired[i::flows] for i in range(flows)]
    fields = {c["id"]: [f["id"] for f in c["fields"]] for c in cards}
    edges, seen = [], set()
    for g in groups:
        if len(g) < 2:
            continue
        want = n_edges if n_edges is not None else rng.randint(len(g) - 1, 3 * len(g))
        for _ in range(want * 4):
            if sum(1 for e in edges if e["from"].split(".")[0] in g) >= want:
                break
            i = rng.randrange(len(g) - 1)
            j = rng.randrange(i + 1, len(g))
            a, b = f"{g[i]}.{rng.choice(fields[g[i]])}", f"{g[j]}.{rng.choice(fields[g[j]])}"
            if (a, b) in seen:
                continue
            seen.add((a, b))
            e = {"from": a, "to": b}
            if rng.random() < labels:
                e["label"] = "l" * rng.randint(3, 18)
            if rng.random() < labels / 3:
                e["note"] = "n" * rng.randint(5, 30)
            if rng.random() < lanes:
                e["lane"] = rng.choice(["above", "below"])
            edges.append(e)
    rng.shuffle(cards)
    rng.shuffle(edges)
    return {"title": "Random", "cards": cards, "edges": edges}


LAYERING = """(specs) => specs.map((spec) => {
  const L = window.__fieldEngine.computeLayout(spec);
  const col = (end) => L.layout.cards[end.split(".")[0]].col;
  const got = spec.edges.reduce((a, e) => a + col(e.to) - col(e.from), 0);
  // brute force: every column in 0 … n-1 for every card, every wire running right
  const ids = spec.cards.map((c) => c.id), n = ids.length, at = new Map(ids.map((c, i) => [c, i]));
  const E = spec.edges.map((e) => [at.get(e.from.split(".")[0]), at.get(e.to.split(".")[0])]);
  const z = new Array(n).fill(0);
  let best = Infinity;
  const rec = (v) => {
    if (v === n) {
      let c = 0;
      for (const [a, b] of E) { if (z[b] <= z[a]) return; c += z[b] - z[a]; }
      best = Math.min(best, c); return;
    }
    for (let x = 0; x < n; x++) { z[v] = x; rec(v + 1); }
  };
  rec(0);
  return [got, best];
})"""


def test_layering_is_optimal(browser):
    rng = random.Random(1)
    specs = [_random_spec(rng, rng.randint(2, 6)) for _ in range(40)]
    for got, best in _engine(browser, LAYERING, specs):
        assert got == best


CERTIFIED = """([specs, check]) => specs.map((spec) => window.__fieldEngine.computeLayout(spec, { CHECK_CUTS: check }).T.solves)"""


def test_cut_values_stay_consistent(browser):
    # A sign slip in the incremental cut values gives a feasible, suboptimal layout and no
    # error; the debug flag recomputes every cut value after each pivot and throws on drift.
    specs = list(EXAMPLES.values()) + [s for n, s in INLINE.items()] + [_random_spec(random.Random(40), 40, n_edges=90)]
    for solves in _engine(browser, CERTIFIED, [specs, True]):
        assert solves


def test_solves_are_certified(browser):
    rng = random.Random(20)
    specs = list(ALL.values()) + [_random_spec(rng, rng.randint(4, 20), follow=0.2, flows=rng.randint(1, 2)) for _ in range(20)]
    for solves in _engine(browser, CERTIFIED, [specs, False]):
        assert solves and not any(s["capped"] for s in solves)


# ── property and budget tests ──

FUZZ = """(specs) => specs.map((spec) => {
  const { computeLayout } = window.__fieldEngine;
  try {
    const a = computeLayout(spec), b = computeLayout(spec);
    return { L: a.layout, R: a.report, same: JSON.stringify(a.layout) === JSON.stringify(b.layout) };
  } catch (e) { return { error: String(e) }; }
})"""


FUZZ_CASES, FUZZ_CHUNKS = 200, 8


def _fuzz_specs():
    rng = random.Random(943)
    return [_random_spec(rng, rng.randint(2, 25), follow=0.25, labels=0.3, lanes=0.05,
                         flows=rng.choice([1, 1, 2]), loose=0.08) for _ in range(FUZZ_CASES)]


# The same 200 seeded cases, in 8 slices of 25 so xdist can spread them: as one
# test it was the longest in the suite, about as long as the rest of CI.
@pytest.mark.slow
@pytest.mark.parametrize("chunk", range(FUZZ_CHUNKS))
def test_fuzz_invariants(browser, chunk):
    size = FUZZ_CASES // FUZZ_CHUNKS
    specs = _fuzz_specs()[chunk * size:(chunk + 1) * size]
    for spec, out in zip(specs, _engine(browser, FUZZ, specs)):
        assert "error" not in out, (out, spec)
        assert {t: out["R"][t] for t in TARGETS} == dict.fromkeys(TARGETS, 0), spec
        _ports_inside(out["L"])
        _rows_touch(out["L"])
        _real_order(out["L"], spec)
        assert out["same"]


def _perf_only(request):
    if "perf" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("timing test: run alone with -m perf -n 0")


def _cold_total(pw, spec):
    """The layout time of a cold page in a fresh Chromium, median of 3."""
    page = render.render(spec)
    times = []
    for _ in range(3):
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content(page)
        pg.wait_for_function("() => window.__layoutReport")
        times.append(pg.evaluate("() => window.__layoutTiming.total"))
        b.close()
    return statistics.median(times)


@pytest.mark.perf
@pytest.mark.parametrize("name", ["stress-60x300-423.json", "stress-60x300-662.json"])
def test_layout_budget(request, pw, name):
    _perf_only(request)
    assert _cold_total(pw, json.loads((FIXTURES / name).read_text())) < 100


@pytest.mark.perf
def test_layout_scales_with_lanes(request, pw):
    # 60 cards and 300 edges whose wires skip four columns on average: 1234 lane items,
    # past the ~900 where the 100 ms bound stops holding. Pinned so it cannot get worse unseen.
    _perf_only(request)
    assert _cold_total(pw, json.loads((FIXTURES / "stress-60x300-1234.json").read_text())) < 200


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("stress-*.json")))
def test_stress_specs_hold_their_targets(browser, name):
    spec = json.loads((FIXTURES / name).read_text())
    out = _engine(browser, FUZZ, [spec])[0]
    assert "error" not in out, out
    assert {t: out["R"][t] for t in TARGETS if t != "label_overlaps"} == dict.fromkeys(set(TARGETS) - {"label_overlaps"}, 0)


# ── the checked render ──

def _check(tmp_path, spec):
    import subprocess
    import sys
    src = tmp_path / "s.json"
    src.write_text(json.dumps(spec))
    out = tmp_path / "s.html"
    r = subprocess.run([sys.executable, str(FIELDS / "render.py"), str(src), "--check", str(out)],
                       capture_output=True, text=True, timeout=T(120))
    return r, out


def test_check_writes_png_and_reports(tmp_path):
    r, out = _check(tmp_path, _spec("example-bypass.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists() and out.with_suffix(".png").stat().st_size > 10_000
    for name in render._check.MEASURES:
        assert f"{name}:" in r.stdout
    assert render._check.TARGETS == TARGETS


def _main(monkeypatch, tmp_path, run):
    import sys
    src = tmp_path / "s.json"
    src.write_text((FIELDS / "example-order.json").read_text())
    monkeypatch.setattr(render._check, "run", run)
    monkeypatch.setattr(sys, "argv", ["render.py", str(src), "--check", str(tmp_path / "s.html")])
    return render.main()


@pytest.mark.parametrize("target", TARGETS)
def test_check_exits_1_when_a_target_is_missed(monkeypatch, tmp_path, capsys, target):
    report = dict.fromkeys(render._check.MEASURES, 0) | {target: 2}
    assert _main(monkeypatch, tmp_path, lambda p: report) == 1
    assert f"{target}: 2" in capsys.readouterr().out


def test_check_passes_when_only_judgment_measures_are_nonzero(monkeypatch, tmp_path):
    report = {m: (0 if m in TARGETS else 3) for m in render._check.MEASURES}
    assert _main(monkeypatch, tmp_path, lambda p: report) == 0


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
    pg.wait_for_function("() => window.__layoutReport", timeout=T(5000))
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
                       capture_output=True, text=True, timeout=T(120), env=env)
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
