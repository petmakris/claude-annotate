"""The grid carries arrows and numbers; the key carries the words.

The fixed-pitch renderer put every label and sub-caption on its arrow, centred
on a span far narrower than the text. On the `the-pre-trade-id-chain` diagram
that put two captions outside the canvas — the legend's last entry reached
x=1036 on an 890px canvas, and a sub-caption started at x=-18.7 — and left the
rest running under lifelines they had nothing to do with.

Splitting the two is the fix: the grid answers *who talks to whom*, the key
answers *what is said*, and neither competes with the other for room. The two
halves are paired by `data-step-id`, which is what a comment already anchors
to, so one click can light both.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from skills.annotate.diagrams.sequence import render, render_key


def _spec(**extra) -> dict:
    return {
        "actors": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
        "steps": [
            {"id": "s1", "from": "a", "to": "b", "arrow": "request",
             "label": "first call", "sub": "with a payload"},
            {"id": "s2", "from": "a", "to": "a", "arrow": "band",
             "label": "a narrated aside"},
            {"id": "s3", "from": "b", "to": "a", "arrow": "event",
             "label": "the answer", "note": "unconfirmed", "tone": "hot"},
        ],
        **extra,
    }


def _step_ids(markup: str, pattern: str) -> list[str]:
    return re.findall(pattern, markup)


def _badge_ids(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    out = []
    for el in root.iter():
        if "badge-hit" in (el.get("class") or "").split():
            out.append(el.get("data-step-id"))
    return out


def test_every_message_step_gets_one_badge_and_one_key_row():
    spec = _spec()
    badges = _badge_ids(render(spec, "section-1"))
    rows = _step_ids(render_key(spec, "section-1"),
                     r'class="seq-key-row[^"]*"[^>]*data-step-id="([^"]+)"')
    assert badges == ["s1", "s3"], badges
    assert rows == ["s1", "s3"], rows


def test_a_band_gets_neither_a_badge_nor_a_key_row():
    """A band narrates across actors; it is not a message, so it has no number
    to pair with and stays whole inside the grid."""
    spec = _spec()
    assert "s2" not in _badge_ids(render(spec, "section-1"))
    assert 's2' not in render_key(spec, "section-1")


def test_badges_are_numbered_from_one_over_message_steps():
    spec = _spec()
    svg = render(spec, "section-1")
    nums = re.findall(r'class="badge-num[^"]*"[^>]*>(\d+)<', svg)
    assert nums == ["1", "2"], nums
    key_nums = re.findall(r'class="seq-key-n[^"]*"[^>]*>(\d+)<', render_key(spec, "section-1"))
    assert key_nums == ["1", "2"], key_nums


def _painted(svg: str) -> str:
    """Every string the grid actually draws. A badge still carries its step's
    label in `aria-label` — that is what a screen reader announces and is not
    ink on the canvas — so the check is against text nodes, not the markup."""
    return "\n".join(el.text or "" for el in ET.fromstring(svg).iter()
                     if el.tag.rsplit("}", 1)[-1] == "text")


def test_the_words_leave_the_grid_and_land_in_the_key():
    spec = _spec()
    painted = _painted(render(spec, "section-1"))
    key = render_key(spec, "section-1")
    for text in ("first call", "with a payload", "the answer", "unconfirmed"):
        assert text not in painted, f"{text!r} is still painted on the grid"
        assert text in key, f"{text!r} never reached the key"


def test_a_badge_still_announces_its_step_to_a_screen_reader():
    """The words leaving the canvas must not take the accessible name with
    them: a bare numbered circle announces nothing."""
    svg = render(_spec(), "section-1")
    assert 'aria-label="Step 1: first call"' in svg


def test_canvas_width_no_longer_follows_the_longest_label():
    """The whole point. Two specs that differ only in how long their label is
    must render the same canvas, because no label is on the canvas."""
    short = _spec()
    long = _spec()
    long["steps"] = [dict(short["steps"][0],
                          label="a call label so long it used to drag the canvas "
                                "hundreds of pixels to the right and scroll the card")]
    short["steps"] = [short["steps"][0]]
    w = lambda s: ET.fromstring(render(s, "x")).get("viewBox").split()[2]
    assert w(short) == w(long), f"{w(short)} vs {w(long)}"


def test_a_note_no_longer_reserves_a_gutter_on_the_canvas():
    spec = _spec()
    noted = _spec()
    spec["steps"] = [spec["steps"][0]]
    noted["steps"] = [dict(noted["steps"][0], note="1,409 ms")]
    w = lambda s: ET.fromstring(render(s, "x")).get("viewBox").split()[2]
    assert w(spec) == w(noted)


def test_phases_head_the_key_in_step_order():
    spec = _spec(phases=[{"id": "p1", "label": "Outbound", "start_at": "s1"},
                         {"id": "p2", "label": "The answer", "start_at": "s3"}])
    key = render_key(spec, "section-1")
    assert key.index("Outbound") < key.index("The answer")
    assert key.count("seq-key-phase") == 2


def test_the_key_escapes_its_text():
    spec = _spec()
    spec["steps"][0]["label"] = "<script>alert(1)</script>"
    spec["steps"][0]["sub"] = 'a & b "quoted"'
    key = render_key(spec, "section-1")
    assert "<script>" not in key
    assert "&lt;script&gt;" in key
    assert "&amp;" in key


def test_both_halves_carry_the_step_id_they_pair_on():
    """The pairing is by step id, and `data-step-id` is what a comment already
    anchors to — so lighting a step also lights whatever a comment marked."""
    spec = _spec()
    svg = render(spec, "section-9")
    key = render_key(spec, "section-9")
    assert 'data-step-id="s3"' in svg and 'data-step-id="s3"' in key
    assert 'data-block-id="section-9"' in svg


def test_the_key_carries_no_block_id():
    """`main.prose [data-block-id]:hover` in style.css is a catch-all that
    paints a hover tint. The renderer keeps the attribute off the SVG root for
    that reason; the first cut of the key put it on the key wrapper and on every
    row, and the whole key washed grey under the cursor — measured on the live
    page as rgb(236,239,244) on `.seq-key` itself. The host <section> carries
    the block id, which is where every reader of it looks."""
    key = render_key(_spec(), "section-9")
    assert "data-block-id" not in key


def test_key_rows_are_reachable_by_keyboard():
    key = render_key(_spec(), "section-1")
    assert key.count('tabindex="0"') == 2
    assert key.count('role="button"') == 2


def test_badges_are_reachable_by_keyboard_and_named():
    svg = render(_spec(), "section-1")
    assert svg.count('tabindex="0"') == 2
    assert 'aria-label="Step 1: first call"' in svg


def test_tone_reaches_the_key_row():
    key = render_key(_spec(), "section-1")
    assert 'seq-key-row t-hot' in key


def test_a_spec_with_no_message_steps_renders_an_empty_key():
    spec = _spec()
    spec["steps"] = [spec["steps"][1]]          # the band alone
    assert render_key(spec, "section-1") == ""


def test_render_block_puts_both_halves_on_the_wire():
    """The client paints what the push stored. A body carrying `svg` but no
    `key` renders a grid of numbered circles nothing explains."""
    from skills.annotate.render import render_block
    body = render_block({"id": "section-2", "kind": "sequence", "spec": _spec()})
    assert body["svg"].startswith("<svg")
    assert body["key"].startswith('<div class="seq-key"')
    assert 'data-step-id="s1"' in body["svg"] and 'data-step-id="s1"' in body["key"]


def test_a_malformed_spec_ships_the_error_pill_and_no_half_diagram():
    from skills.annotate.render import render_block
    body = render_block({"id": "section-2", "kind": "sequence",
                         "spec": {"actors": [], "steps": []}})
    assert "diagram render failed" in body["svg"]
    assert "key" not in body, "half a diagram reached the wire"
