"""Bars: how much, how long, how many. Spec validator and server-side SVG renderer.

A bars board is one row per thing, each with a bar whose length is its value, on one scale. It is for a
magnitude the listener must feel (a cache miss costs a hundred times a hit, a packet loses 40 percent of a
window), where a table would only list the numbers. In the shared look of map_svg: Inter and JetBrains Mono,
the same tones, the same vz.css tokens, measured here in text_metrics.

    {"title": "A cache miss is a hundred times a hit", "unit": "ns", "scale": "log",
     "bars": [{"id": "l1", "label": "L1 cache", "value": 1, "note": "about 4 cycles"},
              {"id": "ram", "label": "Main memory", "value": 100, "tone": "red"}],
     "threshold": {"value": 10, "label": "budget"}}

- ``unit`` (text) is the one unit of every bar. A bar that names another unit is refused: mixed units
  cannot share a scale.
- ``scale`` is ``linear`` (default) or ``log``. A log board draws ticks at powers of ten and a visible
  "log scale" badge, and refuses a value of zero or less (the log of it is not a length). A linear board
  refuses a negative value; zero draws an empty bar.
- ``threshold`` is at most one dashed line with a ``label``; there are no series and no markers.
- Each bar's ``id`` is its key (``bar:<id>``): the stage lights it, reveals it and points at it. Its ``label``
  is the words you say. ``note`` is a second line under it for a number you speak.

Every drawn part of a bar carries ``data-key`` when ``keyed``. Pure functions, no I/O. Nothing the author
writes reaches the output except as escaped text.
"""
from __future__ import annotations

import math
import re
from html import escape
from typing import Any

from . import text_metrics as tm
from .map_svg import TONES, _attrs, _cls, _markers, _text, _width

W = 560               # the canvas: narrow, so text stays legible when a phone scales it down
PAD = 20
TITLE_Y = 34
TITLE_LINE = 28
SUB_GAP = 22
BAR_H = 22
CHIP_H = 26
CHIP_PAD = 9
TICK_H = 30
MIN_PITCH, MAX_PITCH = 54, 104
FILL_H = 520          # rows share about this much height, so a short board has tall rows and fills the pane
MAX_BARS = 24
MIN_BAR = 3.0         # a bar is never shorter, so a small value is still a bar
SCALES = ("linear", "log")


class ValidationError(ValueError):
    """Raised when a bars spec breaks a rule. The message names the bar by its id."""


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _text_field(obj: dict, key: str, where: str, required: bool = False) -> None:
    v = obj.get(key)
    if v is None and not required:
        return
    if not isinstance(v, str) or (required and not v.strip()):
        raise ValidationError(f"{where}: {key} must be text")


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None."""
    if not isinstance(spec, dict):
        raise ValidationError("a bars spec is an object")
    for k in ("title", "subtitle", "aria"):
        _text_field(spec, k, "bars")
    _text_field(spec, "unit", "bars", True)
    scale = spec.get("scale", "linear")
    if scale not in SCALES:
        raise ValidationError(f"bars: scale must be linear or log, got {scale!r}")
    bars = spec.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ValidationError("bars needs at least 1 bar: bars is a list of {id, label, value}")
    if len(bars) > MAX_BARS:
        raise ValidationError(f"bars has {len(bars)} bars, at most {MAX_BARS}: cut it to the ones that carry the argument")
    for stray in ("series", "markers"):
        if stray in spec:
            raise ValidationError(f"bars has no {stray}: one value per bar, one unit, one scale")
    seen: set[str] = set()
    for i, b in enumerate(bars):
        if not isinstance(b, dict):
            raise ValidationError(f"bar {i}: a bar is an object")
        bid = b.get("id")
        if not isinstance(bid, str) or not bid:
            raise ValidationError(f"bar {i}: id required")
        if bid in seen:
            raise ValidationError(f"duplicate bar id: {bid!r}")
        seen.add(bid)
        where = f"bar {bid!r}"
        _text_field(b, "label", where, True)
        _text_field(b, "note", where)
        if b.get("tone", "plain") not in TONES:
            raise ValidationError(f"{where}: unknown tone {b.get('tone')!r}; the tones are {', '.join(TONES)}")
        v = b.get("value")
        if not _num(v):
            raise ValidationError(f"{where}: value must be a number, got {v!r}; the unit is the board's unit "
                                  f"({spec['unit']}), written once")
        unit = b.get("unit")
        if unit is not None and unit != spec["unit"]:
            raise ValidationError(f"{where}: unit {unit!r} is not the board's unit {spec['unit']!r}; "
                                  "bars on one scale share one unit")
        if scale == "log" and v <= 0:
            raise ValidationError(f"{where}: value {v!r} is not above zero, which a log scale cannot draw; "
                                  "use scale linear or a value above zero")
        if v < 0:
            raise ValidationError(f"{where}: value {v!r} is below zero; a bar grows from zero")
    t = spec.get("threshold")
    if t is not None:
        if not isinstance(t, dict) or not _num(t.get("value")):
            raise ValidationError("threshold is one line: {value, label}, value a number")
        _text_field(t, "label", "threshold")
        if scale == "log" and t["value"] <= 0:
            raise ValidationError(f"threshold {t['value']!r} is not above zero, which a log scale cannot draw")
        if t["value"] < 0:
            raise ValidationError(f"threshold {t['value']!r} is below zero")


# ---------------------------------------------------------------- scale

def _fmt(v: float) -> str:
    """A number as a chip or a tick says it: no trailing zeros, thousands grouped, small values kept."""
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1000 and float(v).is_integer():
        return f"{int(v):,}"
    if a >= 100 or float(v).is_integer():
        return f"{v:,.0f}" if a >= 100 else f"{v:g}"
    return f"{v:.3g}"


def _tick_label(v: float) -> str:
    """A power of ten as a tick says it: 1, 10, 1k, 1M, 0.01."""
    for size, mark in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if v >= size:
            return f"{v / size:g}{mark}"
    return f"{v:g}"


def _chip_text(v: float, unit: str) -> str:
    text = _fmt(v)
    return text + unit if unit in ("%", "x") else f"{text} {unit}"


def _linear_ticks(top: float) -> list[float]:
    """Round ticks from zero up to a top at or above the largest value: 4 to 6 steps of 1, 2, 2.5 or 5 times a power of ten."""
    if top <= 0:
        return [0.0, 1.0]
    for step in (m * 10 ** e for e in range(-6, 15) for m in (1, 2, 2.5, 5)):
        if top / step <= 5:
            n = math.ceil(top / step - 1e-9)
            return [round(i * step, 10) for i in range(n + 1)]
    return [0.0, top]


def scale_of(spec: dict[str, Any]) -> tuple[list[float], Any]:
    """The ticks and the function that gives a value its length as a fraction of the axis, 0 to 1."""
    values = [b["value"] for b in spec["bars"]]
    if spec.get("threshold"):
        values.append(spec["threshold"]["value"])
    if spec.get("scale", "linear") == "log":
        lo = math.floor(math.log10(min(values)) + 1e-12)
        hi = math.ceil(math.log10(max(values)) - 1e-12)
        if hi == lo:
            hi = lo + 1
        ticks = [10.0 ** e if e >= 0 else float(f"1e{e}") for e in range(lo, hi + 1)]
        span = hi - lo
        return ticks, (lambda v: max(0.0, (math.log10(v) - lo) / span))
    ticks = _linear_ticks(max(values))
    top = ticks[-1] or 1.0
    return ticks, (lambda v: v / top)


# ---------------------------------------------------------------- drawing

def _wrap(text: str, style: str, width: float) -> list[str]:
    with tm.face("stage"):
        return tm.wrap(text, style, width)


def render(spec: dict[str, Any], uid: str, keyed: bool = False) -> str:
    """Validate and draw `spec` as one SVG string. `uid` prefixes every id. With `keyed`, each part of a bar carries
    ``data-key="bar:<id>"`` for the stage's frames."""
    validate(spec)
    if not re.fullmatch(r"[A-Za-z][\w-]{0,40}", uid or ""):
        raise ValidationError(f"uid {uid!r}: letters, digits, - and _, starting with a letter")
    unit = spec["unit"]
    log = spec.get("scale", "linear") == "log"
    bars = spec["bars"]
    ticks, frac = scale_of(spec)
    out: list[str] = []
    y = PAD
    if spec.get("title"):
        for line in _wrap(spec["title"], "vz-ttl", W - 2 * PAD):
            y += TITLE_LINE
            out.append(_text("ttl", PAD, y, line))
        y += 6
    if spec.get("subtitle"):
        y += SUB_GAP
        out.append(_text("sub", PAD, y, spec["subtitle"]))
    if log:  # the scale is said on the board, never only in the ticks
        label = "log scale"
        bw = _width(label, "vz-sb") + 18
        out.append(f'<rect class="lgb" x="{W - PAD - bw:.0f}" y="{y + 10:.0f}" width="{bw:.0f}" height="22" rx="11" data-badge="log"/>')
        out.append(_text("lgt", W - PAD - bw / 2, y + 25, label, anchor="middle"))
        y += 6
    top = y + 22
    notes = any(b.get("note") for b in bars)
    min_pitch = MIN_PITCH + (14 if notes else 0)
    pitch = max(min_pitch, min(MAX_PITCH, FILL_H / len(bars)))
    chips = [_chip_text(b["value"], unit) for b in bars]
    chip_w = [_width(c, "vz-nm") + 2 * CHIP_PAD for c in chips]
    x0, x1 = PAD, W - PAD - max(chip_w) - 8        # a bar's longest run, leaving room for its chip
    rows_bottom = top + pitch * len(bars)

    grid: list[str] = []
    for t in ticks:
        gx = x0 + frac(t) * (x1 - x0)
        grid.append(f'<line class="grd" x1="{gx:.0f}" y1="{top - 8:.0f}" x2="{gx:.0f}" y2="{rows_bottom:.0f}"/>')
        grid.append(_text("tk", gx, rows_bottom + 20, _tick_label(t), anchor="middle"))
    out.extend(grid)

    for i, b in enumerate(bars):
        key = f"bar:{b['id']}" if keyed else ""
        att = _attrs(key=key)
        ry = top + i * pitch
        tone = b.get("tone", "plain")
        with tm.face("stage"):
            label_lines = tm.wrap(b["label"], "vz-nm", W - 2 * PAD)
        by = ry + 18
        out.append(_text("nm", PAD, by, label_lines[0], att))
        line_y = by
        if b.get("note"):
            line_y += 18
            out.append(_text("sb", PAD, line_y, b["note"], att))
        bar_y = line_y + 10
        length = max(MIN_BAR, frac(b["value"]) * (x1 - x0))
        out.append(f'<rect class="trk" x="{x0}" y="{bar_y:.0f}" width="{x1 - x0:.0f}" height="{BAR_H}" rx="4"{att}/>')
        out.append(f'<rect class="{_cls("bar", tone)}" x="{x0}" y="{bar_y:.0f}" width="{length:.0f}" height="{BAR_H}" rx="4"{att}/>')
        cx = x0 + length + 8
        out.append(f'<rect class="{_cls("chp", tone)}" x="{cx:.0f}" y="{bar_y + (BAR_H - CHIP_H) / 2:.0f}" '
                   f'width="{chip_w[i]:.0f}" height="{CHIP_H}" rx="7"{att}/>')
        out.append(_text("bv", cx + chip_w[i] / 2, bar_y + BAR_H / 2 + 5.5, chips[i], att, "middle"))

    t = spec.get("threshold")
    if t:
        tx = x0 + frac(t["value"]) * (x1 - x0)
        out.append(f'<line class="thr" x1="{tx:.0f}" y1="{top - 8:.0f}" x2="{tx:.0f}" y2="{rows_bottom:.0f}"/>')
        text = (t.get("label") or "limit") + " " + _chip_text(t["value"], unit)
        out.append(_text("thl", min(max(tx, PAD + _width(text, "vz-sb") / 2), W - PAD - _width(text, "vz-sb") / 2), top - 14, text, anchor="middle"))

    height = rows_bottom + 20 + PAD
    aria = escape(spec.get("aria") or spec.get("title") or "Bars", quote=True)
    return (f'<svg class="vz vzb" viewBox="0 0 {W} {height:.0f}" role="img" aria-label="{aria}" data-vz="bars" '
            f'data-scale="{"log" if log else "linear"}">'
            + _markers(uid) + "".join(out) + "</svg>")


def bar_keys(spec: dict[str, Any]) -> list[str]:
    """Each bar's key, in spec order."""
    return [f"bar:{b['id']}" for b in spec.get("bars") or []]


__all__ = ["ValidationError", "validate", "render", "bar_keys", "scale_of"]
