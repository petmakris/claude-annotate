"""Lane sequence: the walkthrough look for a sequence spec, drawn on the server as one SVG.

Reads the same spec as sequence.py (actors, steps with request/event/self/band, phases, tones, sub,
note, reply_to) and draws it in the look chosen for every sequence diagram Claude makes:

- each lane is headed by a box with its name and an optional ``role`` line, coloured by its tone;
- what a step carries sits in a chip on its arrow (``label``, then ``sub`` in mono);
- a reply (an ``event``) is a dashed arrow with its words under it;
- ``checks`` put ✓ / ✗ badges under the arrow, where the rule is applied;
- phases are bands behind their rows, each with its label;
- numbered badges mark the walkthrough's steps (``n`` groups several arrows under one number);
- an ``outcome`` box closes the diagram.

Colours are the four vz tones (blue the AI or model path, red the central mechanism, green a rule that
holds, amber a warning or a cost); annotate's older tones map onto them. Every text is escaped and
measured in Inter and JetBrains Mono (text_metrics, stage face). Each step's parts carry ``data-r`` (its
number) and ``data-p``, so vz-reveal.js can play the sequence one step at a time.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

from . import text_metrics as tm
from .map_svg import _cls, _markers, _segments, _text, _width, MARK
from .sequence import ValidationError, validate as _validate_base

TONE_MAP = {"plain": "plain", "blue": "blue", "red": "red", "green": "green", "amber": "amber",
            "edge": "blue", "internal": "amber", "service": "blue", "cheap": "plain", "hot": "red",
            "good": "green", "dropped": "plain"}

PAD = 24
TITLE_Y = 38
SUB_GAP = 24
HEAD_H = 54
HEAD_MIN_W = 118
HEAD_PAD = 28
LANE_GAP = 22          # the narrowest room between two lane heads
CHIP_PAD_X = 10
CHIP_LINE = 19
CHIP_PAD_Y = 8
ROW_GAP = 16
BADGE_R = 10
CHECK_H = 24
CHECK_GAP = 8
BAND_HEAD = 34
TAG_H = 28           # a lane's name repeated at the top of a later band
SELF_IN = 16           # a self step's chip starts this far right of its lane
OUTCOME_GAP = 22
NOTE_GAP = 24


def _tone(t: Any) -> str:
    return TONE_MAP.get(t or "plain", "plain")


OLD_NAME = {"blue": "edge", "red": "hot", "green": "good", "amber": "internal"}


def _as_base(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec with the four vz tones named as sequence.py knows them, so its rules can run."""
    def tone(o: dict) -> dict:
        if o.get("tone") in OLD_NAME:
            o = dict(o, tone=OLD_NAME[o["tone"]])
        return o
    return dict(spec, actors=[tone(a) for a in spec.get("actors") or []],
                steps=[tone(s) for s in spec.get("steps") or []],
                legend=[tone(x) for x in spec.get("legend") or []])


def validate(spec: dict[str, Any]) -> None:
    """The base sequence rules, plus the fields only this renderer reads."""
    if not isinstance(spec, dict):
        raise ValidationError("a sequence spec is an object")
    _validate_base(_as_base(spec))
    for a in spec.get("actors") or []:
        if a.get("role") is not None and not isinstance(a["role"], str):
            raise ValidationError(f"actor {a.get('id')!r}: role must be text")
    for s in spec.get("steps") or []:
        for c in s.get("checks") or []:
            if not isinstance(c, dict) or not isinstance(c.get("label"), str) or not c["label"]:
                raise ValidationError(f"step {s.get('id')}: a check is {{label, ok}}")
        n = s.get("n")
        if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 1):
            raise ValidationError(f"step {s.get('id')}: n must be a whole number 1 or more")
    out = spec.get("outcome")
    if out is not None:
        if not isinstance(out, dict) or not isinstance(out.get("title"), str):
            raise ValidationError("outcome is {title, lines, tone}")
        if out.get("tone") is not None and out["tone"] not in TONE_MAP:
            raise ValidationError(f"outcome: unknown tone {out['tone']!r}")


def _chip_lines(step: dict) -> list[tuple[str, bool]]:
    """The lines of a step's chip: its label (split on newlines), then its sub in mono."""
    lines = [(ln, False) for ln in (step.get("label") or "").split("\n") if ln.strip()]
    lines += [(ln, True) for ln in (step.get("sub") or "").split("\n") if ln.strip()]
    return lines


def _lines_w(lines: list[tuple[str, bool]]) -> float:
    return max((_width(t, "vz-sb", m) for t, m in lines), default=0.0)


def _head_lines(actor: dict) -> list[str]:
    return [ln for ln in actor["label"].split("\n") if ln.strip()]


def _numbers(steps: list[dict]) -> list[int | None]:
    """Each step's badge number: its own ``n`` when the spec numbers steps, else 1, 2, 3 for every arrow."""
    if any(s.get("n") is not None for s in steps):
        out, last = [], 0
        for s in steps:
            if s.get("n") is not None:
                last = s["n"]
                out.append(s["n"])
            else:
                out.append(last or None)
        return out
    out, k = [], 0
    for s in steps:
        if s.get("arrow") == "band":
            out.append(None)
        else:
            k += 1
            out.append(k)
    return out


def render(spec: dict[str, Any], uid: str, keyed: bool = False) -> str:
    """Validate and draw `spec` as one SVG string. `uid` prefixes every id, so diagrams can share a page.

    Actors that are never in use at the same time share a column, the later one headed where it starts
    (``"share_lanes": false`` turns this off). Columns sit as close as their heads allow; a chip may lie
    over the lanes beside it, so a long payload never pushes the lanes apart.

    With `keyed`, each step's group also carries ``data-key="step:<id>"``, and an actor's head, its words and
    its lifeline ``data-key="actor:<id>"``, for a page that reveals and lights parts by key. Without it the
    output is exactly what it was before keys existed."""
    validate(spec)
    if not re.fullmatch(r"[A-Za-z][\w-]{0,40}", uid or ""):
        raise ValidationError(f"uid {uid!r}: letters, digits, - and _, starting with a letter")
    actors = spec["actors"]
    steps = spec["steps"]
    idx = {a["id"]: i for i, a in enumerate(actors)}
    nums = _numbers(steps)
    shown_badge = set()

    # ---- lanes: an actor's life runs from its first step to its last; actors whose lives never overlap
    # share a column (unless the spec says "share_lanes": false), and a later one gets its head where it
    # starts. Columns are as close as their heads allow: a chip may lie over the lanes beside it.
    life: dict[str, list[int]] = {}
    for i, s in enumerate(steps):
        for who in (s["from"], s["to"]):
            life.setdefault(who, [i, i])
            life[who][1] = i
    for a in actors:
        life.setdefault(a["id"], [0, 0])
    col_of: dict[str, int] = {}
    cols: list[list[str]] = []
    share = spec.get("share_lanes", True)
    for a in actors:
        aid = a["id"]
        placed = False
        if share:
            for c, members in enumerate(cols):
                if all(life[aid][0] > life[m][1] + 0 or life[aid][1] < life[m][0] for m in members):
                    members.append(aid)
                    col_of[aid] = c
                    placed = True
                    break
        if not placed:
            col_of[aid] = len(cols)
            cols.append([aid])
    first_in_col = {members[0] for members in cols}

    def head_width(a: dict) -> float:
        w = max([_width(ln, "vz-nm", bool(a.get("mono"))) for ln in _head_lines(a)] + [_width(a.get("role") or "", "vz-sb")])
        return max(HEAD_MIN_W, w + HEAD_PAD)

    by_id = {a["id"]: a for a in actors}
    col_w = [max(head_width(by_id[m]) for m in members) for members in cols]
    gaps = [col_w[i] / 2 + col_w[i + 1] / 2 + LANE_GAP for i in range(len(cols) - 1)]
    cx = [PAD + col_w[0] / 2]
    for g in gaps:
        cx.append(cx[-1] + g)
    xs = [cx[col_of[a["id"]]] for a in actors]
    head_w = [col_w[col_of[a["id"]]] for a in actors]
    canvas_r = cx[-1] + col_w[-1] / 2
    right_edge = canvas_r

    # ---- rows
    out_rows: list[str] = []
    bands: list[tuple[float, str, int | None, str]] = []   # (top y, label, first number, tone)
    phases = {p["start_at"]: p for p in spec.get("phases") or []}
    y = PAD
    title_parts: list[str] = []
    if spec.get("title"):
        title_parts.append(_text("ttl", PAD, TITLE_Y, spec["title"]))
        y = TITLE_Y + 16
        if spec.get("subtitle"):
            title_parts.append(_text("sub", PAD, TITLE_Y + SUB_GAP, spec["subtitle"]))
            y += SUB_GAP
    head_top = y
    y = head_top + HEAD_H + 18
    lane_bottom = y
    note_x = right_edge + NOTE_GAP
    notes_w = 0.0

    head_at: dict[str, float] = {}       # where each later actor's head is drawn
    tags: list[tuple[str, float]] = []   # (actor, y): a lane's name repeated at the top of a later band
    life_y: dict[str, list[float]] = {}  # top and bottom of each actor's lifeline
    for si, (s, n) in enumerate(zip(steps, nums)):
        late = [a["id"] for a in actors if a["id"] not in first_in_col and life[a["id"]][0] == si]
        if s["id"] in phases:
            bands.append((y, phases[s["id"]]["label"], n, _tone(phases[s["id"]].get("tone"))))
            y += BAND_HEAD
            if len(bands) > 1:
                # repeat the names of the lanes this band uses, so a reader who scrolled knows each line
                end = next((k for k in range(si + 1, len(steps)) if steps[k]["id"] in phases), len(steps)) - 1
                live = []
                for members in cols:
                    # one name per column: the lane in use as the band starts, else the column's first
                    # lane if it starts inside the band (a later lane there gets its own head)
                    at_start = [m for m in members if m not in late and life[m][0] <= si <= life[m][1]]
                    if at_start:
                        live.append(at_start[0])
                    elif members[0] not in late and si <= life[members[0]][0] <= end:
                        live.append(members[0])
                if live:
                    for aid in live:
                        tags.append((aid, y))
                    y += TAG_H + 14
        if late:
            for aid in late:
                head_at[aid] = y
            y += HEAD_H + 16
        att = f' data-p="1"' + (f' data-r="{n}"' if n else "")
        tone = _tone(s.get("tone"))
        g: list[str] = []
        fx, tx = xs[idx[s["from"]]], xs[idx[s["to"]]]
        badge_here = n is not None and n not in shown_badge
        if s["arrow"] == "band":
            lo, hi = sorted((fx, tx))
            lo -= 40
            hi += 40
            lines = _chip_lines(s)
            h = CHIP_LINE * max(1, len(lines)) + 2 * CHIP_PAD_Y
            g.append(f'<rect class="{_cls("chip", tone)}" x="{lo:.0f}" y="{y:.0f}" width="{hi - lo:.0f}" height="{h:.0f}" rx="6"/>')
            for k, (t, m) in enumerate(lines):
                g.append(_text(_cls("sb", "mono" if m else ""), lo + 12, y + CHIP_PAD_Y + 14 + CHIP_LINE * k, t))
            y += h + ROW_GAP
        elif s["arrow"] == "self":
            lines = _chip_lines(s)
            w = _lines_w(lines) + 2 * CHIP_PAD_X
            h = CHIP_LINE * max(1, len(lines)) + 2 * CHIP_PAD_Y
            cx = fx + SELF_IN + (BADGE_R + 6 if badge_here else 0)
            g.append(f'<path class="{_cls("ar", tone)}" d="M{fx:.0f},{y + 8:.0f} H{fx + SELF_IN - 4:.0f} V{y + h - 8:.0f} H{fx + 4:.0f}" marker-end="url(#{uid}-{MARK[tone]})"/>')
            g.append(f'<rect class="{_cls("chip", tone)}" x="{cx:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="6"/>')
            for k, (t, m) in enumerate(lines):
                g.append(_text(_cls("sb", "mono" if m else ""), cx + CHIP_PAD_X, y + CHIP_PAD_Y + 14 + CHIP_LINE * k, t))
            right_edge = max(right_edge, cx + w)
            if badge_here:
                g.append(f'<circle class="bd solid" cx="{fx:.0f}" cy="{y + h / 2:.0f}" r="{BADGE_R}"/>')
                g.append(f'<text class="n" x="{fx:.0f}" y="{y + h / 2 + 4.5:.1f}">{n}</text>')
                shown_badge.add(n)
            arrow_y = y + h / 2
            y += h + 8
            checks = s.get("checks") or []
            if checks:
                px = cx
                for c in checks:
                    ok = c.get("ok", True)
                    text = ("✓ " if ok else "✗ ") + c["label"]
                    col = "green" if ok else "red"
                    w2 = _width(text, "vz-sb") + 22
                    g.append(f'<rect class="chip {col}" x="{px:.0f}" y="{y:.0f}" width="{w2:.0f}" height="{CHECK_H}" rx="12"/>')
                    g.append(_text(f"sb {col}", px + w2 / 2, y + 16.5, text, "", "middle"))
                    right_edge = max(right_edge, px + w2)
                    px += w2 + CHECK_GAP
                y += CHECK_H + 8
            y += ROW_GAP - 8
        else:
            reply = s["arrow"] == "event"
            lines = _chip_lines(s)
            direction = 1 if tx > fx else -1
            start = fx + direction * (BADGE_R + 4 if badge_here else 2)
            end = tx - direction * 4
            mid = (start + end) / 2
            if reply:
                arrow_y = y + 8
                wl = _lines_w(lines)
                lm = min(max(mid, PAD + wl / 2), max(canvas_r, PAD + wl) - wl / 2)
                for k, (t, m) in enumerate(lines):
                    g.append(_text(_cls("lb", "mono" if m else "", tone), lm, arrow_y + 20 + CHIP_LINE * k, t, "", "middle"))
                below = 8 + CHIP_LINE * len(lines)
            else:
                if lines:
                    w = _lines_w(lines) + 2 * CHIP_PAD_X
                    h = CHIP_LINE * len(lines) + 2 * CHIP_PAD_Y
                    cm = min(max(mid, PAD + w / 2), max(canvas_r, PAD + w) - w / 2)
                    g.append(f'<rect class="{_cls("chip", tone)}" x="{cm - w / 2:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="6"/>')
                    for k, (t, m) in enumerate(lines):
                        g.append(_text(_cls("lb", "mono" if m else ""), cm, y + CHIP_PAD_Y + 14 + CHIP_LINE * k, t, "", "middle"))
                    arrow_y = y + h + 6
                else:
                    arrow_y = y + 8
                below = 0
            dash = " dash" if reply or s.get("tone") == "dropped" else ""
            g.append(f'<line class="{_cls("ar", tone)}{dash}" x1="{start:.0f}" y1="{arrow_y:.0f}" x2="{end:.0f}" y2="{arrow_y:.0f}" marker-end="url(#{uid}-{MARK[tone]})"/>')
            if badge_here:
                g.append(f'<circle class="bd solid" cx="{fx:.0f}" cy="{arrow_y:.0f}" r="{BADGE_R}"/>')
                g.append(f'<text class="n" x="{fx:.0f}" y="{arrow_y + 4.5:.1f}">{n}</text>')
                shown_badge.add(n)
            y = arrow_y + below + 10
            checks = s.get("checks") or []
            if checks:
                pills = []
                for c in checks:
                    ok = c.get("ok", True)
                    text = ("✓ " if ok else "✗ ") + c["label"]
                    pills.append((text, "green" if ok else "red", _width(text, "vz-sb") + 22))
                total = sum(p[2] for p in pills) + CHECK_GAP * (len(pills) - 1)
                px = min(max(tx - total / 2, PAD), max(canvas_r, PAD + total) - total)
                for text, col, w in pills:
                    g.append(f'<rect class="chip {col}" x="{px:.0f}" y="{y:.0f}" width="{w:.0f}" height="{CHECK_H}" rx="12"/>')
                    g.append(_text(f"sb {col}", px + w / 2, y + 16.5, text, "", "middle"))
                    right_edge = max(right_edge, px + w)
                    px += w + CHECK_GAP
                y += CHECK_H + 8
            y += ROW_GAP - 6
        if s.get("note"):
            g.append(_text("sb mono", note_x, arrow_y + 4, s["note"]))
            notes_w = max(notes_w, _width(s["note"], "vz-mono", True))
        for who in (s["from"], s["to"]):
            life_y.setdefault(who, [0.0, 0.0])
            life_y[who][1] = max(life_y[who][1], y - 4)
        key = f' data-key="step:{escape(s["id"], quote=True)}"' if keyed else ""
        out_rows.append(f'<g data-step="{escape(s["id"], quote=True)}"{key}{att}>' + "".join(g) + "</g>")

    lane_end = y
    outcome = spec.get("outcome")
    width = max(right_edge, note_x + notes_w if notes_w else right_edge) + PAD
    if spec.get("title"):
        width = max(width, PAD * 2 + _width(spec["title"], "vz-ttl"))
        if spec.get("subtitle"):
            width = max(width, PAD * 2 + _width(spec["subtitle"], "vz-sb"))
    if outcome:
        # The outcome box spans the canvas, its words 18px in from each side:
        # a line wider than the lanes widens the canvas, or it runs off it.
        words = [_width(outcome["title"], "vz-nm")] + [_width(ln, "vz-sb") for ln in outcome.get("lines") or []]
        width = max(width, PAD * 2 + 36 + max(words))
    parts: list[str] = []

    # bands behind everything
    for k, (top, label, n, tone) in enumerate(bands):
        bottom = (bands[k + 1][0] - 8) if k + 1 < len(bands) else lane_end
        att = ' data-p="1"' + (f' data-r="{n}"' if n else "")
        parts.append(f'<rect class="band" x="{PAD / 2:.0f}" y="{top - 6:.0f}" width="{width - PAD:.0f}" height="{bottom - top + 2:.0f}" rx="10"{att}/>')
        parts.append(_text(_cls("zl", tone), PAD, top + 16, label.upper(), att))

    # lifelines and heads
    def akey(a: dict) -> str:
        return f' data-key="actor:{escape(a["id"], quote=True)}"' if keyed else ""

    for i, a in enumerate(actors):
        aid = a["id"]
        top = (head_at[aid] + HEAD_H) if aid in head_at else head_top + HEAD_H
        members = cols[col_of[aid]]
        nxt = members[members.index(aid) + 1] if members.index(aid) + 1 < len(members) else None
        bottom = (head_at[nxt] - 8) if nxt else lane_end
        parts.append(f'<line class="life" x1="{xs[i]:.0f}" y1="{top:.0f}" x2="{xs[i]:.0f}" y2="{bottom:.0f}"{akey(a)}/>')
    for i, a in enumerate(actors):
        tone = _tone(a.get("tone"))
        w = head_width(a)
        x0 = xs[i] - w / 2
        ht = head_at.get(a["id"], head_top)
        lines = _head_lines(a)
        parts.append(f'<rect class="{_cls("bx", tone)}" x="{x0:.0f}" y="{ht:.0f}" width="{w:.0f}" height="{HEAD_H}" rx="8"{akey(a)}/>')
        if a.get("role") and len(lines) == 1:
            parts.append(_text(_cls("nm", "mono" if a.get("mono") else ""), xs[i], ht + 23, lines[0], akey(a), "middle"))
            parts.append(_text(_cls("sb", tone), xs[i], ht + 42, a["role"], akey(a), "middle"))
        else:
            base = ht + (33 if len(lines) == 1 else 23)
            for k, ln in enumerate(lines[:2]):
                parts.append(_text(_cls("nm", "mono" if a.get("mono") else ""), xs[i], base + 19 * k, ln, akey(a), "middle"))

    for aid, ty in tags:
        a = by_id[aid]
        i = idx[aid]
        tone = _tone(a.get("tone"))
        name = _head_lines(a)[0]
        w = _width(name, "vz-nm", bool(a.get("mono"))) + 24
        parts.append(f'<rect class="{_cls("bx", tone)}" x="{xs[i] - w / 2:.0f}" y="{ty:.0f}" width="{w:.0f}" height="{TAG_H}" rx="6"{akey(a)}/>')
        parts.append(_text(_cls("nm", "mono" if a.get("mono") else ""), xs[i], ty + 20, name, akey(a), "middle"))
    parts.extend(out_rows)
    y = lane_end
    if outcome:
        tone = _tone(outcome.get("tone"))
        lines = outcome.get("lines") or []
        h = 30 + 22 * len(lines) + 16
        last = max((n for n in nums if n), default=None)
        att = ' data-p="1"' + (f' data-r="{last}"' if last else "")
        y += OUTCOME_GAP - ROW_GAP
        parts.append(f'<rect class="{_cls("bx", tone)}" x="{PAD:.0f}" y="{y:.0f}" width="{width - 2 * PAD:.0f}" height="{h:.0f}" rx="8"{att}/>')
        parts.append(_text(_cls("nm", tone), PAD + 18, y + 28, outcome["title"], att))
        for k, ln in enumerate(lines):
            parts.append(_text("sb", PAD + 18, y + 52 + 22 * k, ln, att))
        y += h
    legend = spec.get("legend") or []
    if legend:
        y += 30
        x = PAD
        for item in legend:
            tone = _tone(item.get("tone"))
            parts.append(f'<line class="{_cls("ar", tone)}" x1="{x}" y1="{y - 4}" x2="{x + 34}" y2="{y - 4}" marker-end="url(#{uid}-{MARK[tone]})"/>')
            parts.append(_text("sb", x + 44, y, item["label"]))
            x += 44 + _width(item["label"], "vz-sb") + 30
            if x > width - 200:
                x, y = PAD, y + 28
    height = y + PAD
    aria = escape(spec.get("aria") or spec.get("title") or "Sequence diagram", quote=True)
    return (f'<svg class="vz" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{aria}" data-vz="sequence">'
            + _markers(uid) + "".join(title_parts) + "".join(parts) + "</svg>")


def step_count(spec: dict[str, Any]) -> int:
    return max((n for n in _numbers(spec.get("steps") or []) if n), default=0)
