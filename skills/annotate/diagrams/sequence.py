"""Sequence-diagram spec validator + server-side SVG renderer.

Pure functions, no I/O. Called by server.py when rendering a block
with kind == "sequence".

Geometry follows a fixed-pitch grid rather than a fit-to-width one. The old
renderer sized actor columns from their labels and then scaled the whole SVG
down to the card (``width:100%``), so an eight-actor flow rendered at 0.655x
and its 11px labels landed at 7.2px — the more actors a diagram had, the less
readable it became. Here the column pitch is constant, long actor names wrap
onto two monospace lines instead of widening their column, and the canvas keeps
its pixel size inside a horizontally scrolling card. Type is the same size in
a two-actor diagram and a twelve-actor one.
"""
from __future__ import annotations

import re
from html import escape as _html_escape
from typing import Any

from .text_metrics import text_px

ARROW_TYPES = ("request", "event", "self", "band")

# Tone = what the author wants the reader to conclude from an edge, not the
# mechanism that carried it. `plain` is the default and needs no legend entry.
TONES = ("plain", "edge", "internal", "service", "cheap", "hot", "good", "dropped")


class ValidationError(ValueError):
    """Raised when a sequence spec violates a structural rule."""


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None."""
    actors = spec.get("actors") or []
    steps = spec.get("steps") or []
    phases = spec.get("phases") or []
    legend = spec.get("legend") or []

    if len(actors) < 2:
        raise ValidationError("sequence requires at least 2 actors")
    if len(steps) < 1:
        raise ValidationError("sequence requires at least 1 step")

    actor_ids: set[str] = set()
    for a in actors:
        aid = a.get("id")
        if not aid or aid in actor_ids:
            raise ValidationError(f"actor id missing or duplicate: {aid!r}")
        if not a.get("label"):
            raise ValidationError(f"actor {aid!r}: label required")
        tone = a.get("tone", "plain")
        if tone not in TONES:
            raise ValidationError(f"actor {aid!r}: unknown tone {tone!r}")
        actor_ids.add(aid)

    seen_step_ids: set[str] = set()
    step_order: list[str] = []
    for s in steps:
        sid = s.get("id")
        if not sid:
            raise ValidationError("step id required")
        if sid in seen_step_ids:
            raise ValidationError(f"duplicate step id: {sid!r}")
        seen_step_ids.add(sid)
        step_order.append(sid)

        if s.get("from") not in actor_ids:
            raise ValidationError(f"step {sid}: unknown from actor {s.get('from')!r}")
        if s.get("to") not in actor_ids:
            raise ValidationError(f"step {sid}: unknown to actor {s.get('to')!r}")

        arrow = s.get("arrow")
        if arrow not in ARROW_TYPES:
            raise ValidationError(f"step {sid}: unknown arrow type {arrow!r}")
        if arrow == "self" and s.get("from") != s.get("to"):
            raise ValidationError(f"step {sid}: arrow=self requires from == to")
        if arrow == "request" and s.get("from") == s.get("to"):
            raise ValidationError(f"step {sid}: cross-actor arrow with from == to; use arrow=self")
        if arrow == "event" and s.get("from") == s.get("to"):
            raise ValidationError(f"step {sid}: cross-actor arrow with from == to; use arrow=self")

        tone = s.get("tone", "plain")
        if tone not in TONES:
            raise ValidationError(f"step {sid}: unknown tone {tone!r}")

    for item in legend:
        if item.get("tone") not in TONES:
            raise ValidationError(f"legend: unknown tone {item.get('tone')!r}")
        if not item.get("label"):
            raise ValidationError(f"legend {item.get('tone')!r}: label required")

    last_step_idx = -1
    for p in phases:
        if not p.get("label"):
            raise ValidationError(f"phase {p.get('id')!r}: label required")
        start = p.get("start_at")
        if start not in seen_step_ids:
            raise ValidationError(f"phase {p.get('id')!r}: start_at refers to unknown step {start!r}")
        idx = step_order.index(start)
        if idx <= last_step_idx:
            raise ValidationError(f"phase {p.get('id')!r}: phase order violates step order")
        last_step_idx = idx


# ── layout constants ──────────────────────────────────────────────
# A fixed grid. Every number here was read off the reference diagram this
# renderer reproduces, so changing one changes the density on purpose rather
# than by accident. Keep in sync with the .annotate-seq rules in diagram.css
# and the seq-* entries in text_metrics.STYLES.
ACTOR_W_MIN = 112        # actor box width; grows only if a wrapped line needs it
ACTOR_PAD_X = 12         # total horizontal padding inside an actor box
ACTOR_GAP = 10           # gap between adjacent actor boxes
ACTOR_H2 = 46            # box height, two-line name
ACTOR_H1 = 33            # box height, one-line name
ACTOR_LINE_1 = 17        # first name baseline, relative to box top
ACTOR_LINE_2 = 30        # second name baseline, relative to box top
NAME_MAX_LINES = 2

PAD_LEFT = 52            # left margin: holds the row-number column
ROWNUM_X = 40            # row numbers are right-anchored here
GUTTER_GAP = 26          # last actor box edge → note column
GUTTER_MIN = 0           # no notes → no gutter
PAD_RIGHT = 16

LEGEND_H = 26            # 0 when the spec carries no legend
LEGEND_SWATCH_W = 22
LEGEND_ITEM_GAP = 24

ROW_H = 34               # row pitch
LABEL_DY = -6            # label baseline, relative to the arrow centreline
SUB_DY = 13              # sub-caption baseline, relative to the arrow centreline
ARROW_INSET = 6          # arrow endpoints stop this far short of the lifeline
HEAD_LEN = 7             # arrowhead triangle length
BAND_H = 22
BAND_PAD = 46            # band overhang past the outermost lifeline it spans
BAND_TEXT_X = 10
SELF_W = 22              # self-call bracket width
SELF_H = 14
SELF_LABEL_GAP = 8

PHASE_LABEL_H = ROW_H    # a phase label owns a whole row; nothing shares its y


def _name_lines(label: str, max_px: float) -> list[str]:
    """Wrap an actor label onto at most two monospace lines.

    An explicit newline in the label wins — that is how an author forces
    ``Kong`` / ``UOB gateway`` instead of one long line. Otherwise the label is
    split into tokens (words if it has spaces, CamelCase segments if it does
    not) and filled greedily. Greedy, not balanced: balanced wrapping turns
    ``PortfolioCheckupFactory`` into ``Portfolio`` / ``CheckupFactory``, where
    greedy gives ``PortfolioCheckup`` / ``Factory``, which is how a reader
    scanning a row of column heads expects to see it.
    """
    if "\n" in label:
        return [ln.strip() for ln in label.split("\n")][:NAME_MAX_LINES]
    if text_px(label, "seq-name") <= max_px:
        return [label]

    if " " in label:
        tokens, joiner = label.split(), " "
    else:
        # Zero-width split, never a findall: an extracting pattern keeps only
        # what it matches, so `auth-service` came back as "authservice" and
        # `<script>` as "script" — punctuation vanished from the label. Splitting
        # at boundaries instead means the tokens always rejoin to the original.
        tokens = re.split(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[-._/])",
                          label)
        joiner = ""
    if len(tokens) < 2:
        return [label]

    lines: list[str] = []
    cur = tokens[0]
    for tok in tokens[1:]:
        cand = joiner.join([cur, tok])
        if text_px(cand, "seq-name") <= max_px:
            cur = cand
        else:
            lines.append(cur)
            cur = tok
    lines.append(cur)
    if len(lines) <= NAME_MAX_LINES:
        return lines
    # More than two lines' worth: everything after the first is one long line.
    # It may overflow, and _actor_w below widens every column to hold it.
    return [lines[0], joiner.join(lines[1:])]


def _actor_layout(actors: list[dict[str, Any]]) -> tuple[list[list[str]], int]:
    """Wrapped name lines per actor, and the shared column width that holds them.

    Two passes: wrap at the default width, then — only if some line still
    overflows — widen every column by the same amount, so the grid stays
    uniform. A single long name costs a few px on every column rather than
    making one column twice the width of its neighbours.
    """
    budget = ACTOR_W_MIN - ACTOR_PAD_X
    lines = [_name_lines(a.get("label", ""), budget) for a in actors]
    widest = max((text_px(ln, "seq-name") for group in lines for ln in group), default=0.0)
    width = max(ACTOR_W_MIN, int(widest) + ACTOR_PAD_X + 1)
    if width > ACTOR_W_MIN:
        lines = [_name_lines(a.get("label", ""), width - ACTOR_PAD_X) for a in actors]
    return lines, width


def _tone_of(obj: dict[str, Any]) -> str:
    tone = obj.get("tone", "plain")
    return tone if tone in TONES else "plain"


def _cls(base: str, tone: str) -> str:
    """Class attribute for a toned element. `plain` adds nothing."""
    return base if tone == "plain" else f"{base} t-{tone}"


def render(spec: dict[str, Any], block_id: str) -> str:
    """Render a validated spec to an SVG string with hit-target IDs.

    Raises ValidationError if spec is malformed.
    """
    validate(spec)

    actors = spec["actors"]
    steps = spec["steps"]
    phases = spec.get("phases") or []
    legend = spec.get("legend") or []

    name_lines, actor_w = _actor_layout(actors)
    pitch = actor_w + ACTOR_GAP
    xs = [PAD_LEFT + actor_w // 2 + i * pitch for i in range(len(actors))]
    actor_x = {a["id"]: x for a, x in zip(actors, xs)}

    legend_h = LEGEND_H if legend else 0
    actor_top = legend_h + 8
    box_h = ACTOR_H2 if any(len(g) > 1 for g in name_lines) else ACTOR_H1
    lifeline_top = actor_top + box_h + 6

    # Row grid. A phase label owns a whole row of its own, so its text can never
    # land on the same baseline band as an arrow label — the collision the
    # previous renderer shipped, where PRE-PROCESSING sat under the first arrow.
    step_index = {s["id"]: i for i, s in enumerate(steps)}
    phase_offsets: dict[int, int] = {step_index[p["start_at"]]: PHASE_LABEL_H for p in phases}

    def row_y(i: int) -> int:
        return lifeline_top + 16 + i * ROW_H + sum(phase_offsets.get(k, 0) for k in range(i + 1))

    total_h = row_y(len(steps) - 1) + ROW_H // 2 + 14

    # Note gutter sits a fixed distance right of the last actor box, so a long
    # arrow label widening the canvas does not drag the notes with it.
    notes = [s for s in steps if s.get("note")]
    gutter_x = PAD_LEFT + actor_w + (len(actors) - 1) * pitch + GUTTER_GAP
    gutter_w = (
        max(text_px(str(s["note"]), "seq-note") for s in notes) if notes else GUTTER_MIN
    )
    total_w = int(gutter_x + gutter_w + PAD_RIGHT) if notes else int(
        PAD_LEFT + actor_w + (len(actors) - 1) * pitch + PAD_RIGHT
    )

    # Arrow labels float over neighbouring lifelines by design; they only get to
    # widen the canvas, never to spill outside it.
    label_right = _widest_label_right(steps, actor_x, actor_w)
    total_w = max(total_w, int(label_right) + PAD_RIGHT)

    parts: list[str] = []
    # No data-block-id on the SVG root: the host <section> already carries it,
    # and putting it here would let the catch-all `[data-block-id]:hover` rule
    # in style.css paint a background tint on the SVG element itself.
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" '
        f'width="{total_w}" height="{total_h}" class="annotate-seq">'
    )

    if legend:
        parts.append(_render_legend(legend))

    lifeline_bottom = total_h - 8
    for x in xs:
        parts.append(
            f'<line class="lane" x1="{x}" y1="{lifeline_top}" x2="{x}" y2="{lifeline_bottom}"/>'
        )

    for actor, x, lines in zip(actors, xs, name_lines):
        parts.append(_render_actor(actor, x, lines, actor_top, actor_w, box_h))

    if phases:
        parts.append(_render_phases(phases, steps, step_index, row_y, total_w))

    note_n = 0
    for i, step in enumerate(steps):
        y = row_y(i)
        num = None
        if step.get("note"):
            note_n += 1
            num = step.get("index") or f"#{note_n}"
        parts.append(_render_step(step, block_id, actor_x, actor_w, y, total_w, gutter_x, num))

    parts.append("</svg>")
    return "".join(parts)


def _widest_label_right(steps: list[dict[str, Any]], actor_x: dict[str, int],
                        actor_w: int) -> float:
    """Right-most pixel any arrow or band label reaches."""
    right = 0.0
    for s in steps:
        fx, tx = actor_x[s["from"]], actor_x[s["to"]]
        if s["arrow"] == "band":
            lo, hi = min(fx, tx), max(fx, tx)
            span = max(hi - lo + 2 * BAND_PAD,
                       text_px(s.get("label", ""), "seq-band") + 2 * BAND_TEXT_X)
            right = max(right, lo - BAND_PAD + span)
        elif s["arrow"] == "self":
            base = fx + SELF_W + SELF_LABEL_GAP
            right = max(right,
                        base + text_px(s.get("label", ""), "seq-label"),
                        base + text_px(s.get("sub", "") or "", "seq-tag"))
        else:
            mid = (fx + tx) / 2
            for txt, style in ((s.get("label", ""), "seq-label"),
                               (s.get("sub", "") or "", "seq-tag")):
                right = max(right, mid + text_px(txt, style) / 2)
    return right


def _render_actor(actor: dict[str, Any], x: int, lines: list[str], top: int,
                  w: int, h: int) -> str:
    tone = _tone_of(actor)
    parts = [
        f'<rect class="{_cls("actor-box", tone)}" x="{x - w // 2}" y="{top}" '
        f'width="{w}" height="{h}" rx="3"/>'
    ]
    if len(lines) == 1:
        ys = [top + h // 2 + 4]
    else:
        ys = [top + ACTOR_LINE_1, top + ACTOR_LINE_2]
    for text, y in zip(lines, ys):
        parts.append(
            f'<text class="actor-label" x="{x}" y="{y}" text-anchor="middle">'
            f'{_html_escape(text)}</text>'
        )
    return "".join(parts)


def _render_legend(legend: list[dict[str, Any]]) -> str:
    """Tone key across the top. Only tones the author declared appear."""
    parts = ['<g class="seq-legend">']
    cursor = float(PAD_LEFT)
    for item in legend:
        tone = _tone_of(item)
        label = str(item["label"])
        parts.append(
            f'<line class="{_cls("legend-swatch", tone)}" x1="{cursor:.0f}" y1="11" '
            f'x2="{cursor + LEGEND_SWATCH_W:.0f}" y2="11"/>'
        )
        tx = cursor + LEGEND_SWATCH_W + 7
        parts.append(
            f'<text class="legend-text" x="{tx:.0f}" y="15">{_html_escape(label)}</text>'
        )
        cursor = tx + text_px(label, "seq-legend") + LEGEND_ITEM_GAP
    parts.append("</g>")
    return "".join(parts)


def _head(x: float, y: float, facing: int, cls: str) -> str:
    """Filled triangle arrowhead at (x, y). facing=1 points right, -1 left."""
    return (f'<path class="{cls}" d="M {x:.0f} {y:.0f} l {-HEAD_LEN * facing:.0f} -4 '
            f'v 8 z"/>')


def _render_step(step: dict[str, Any], block_id: str, actor_x: dict[str, int],
                 actor_w: int, y: int, total_w: int, gutter_x: float,
                 num: str | None) -> str:
    """Emit one step row: the arrow (or band), its label, sub-caption, row
    number and gutter note. y is the arrow centreline."""
    sid = step["id"]
    arrow = step["arrow"]
    tone = _tone_of(step)
    fx = actor_x[step["from"]]
    tx = actor_x[step["to"]]
    label = _html_escape(step.get("label", ""))
    sub = step.get("sub")
    dash = ' stroke-dasharray="5 4"' if arrow in ("event", "dropped") or tone == "dropped" else ""

    parts = [
        f'<g class="step-row" data-block-id="{_html_escape(block_id, quote=True)}" '
        f'data-step-id="{_html_escape(sid, quote=True)}">',
        f'<rect class="row-bg" x="0" y="{y - ROW_H // 2}" width="{total_w}" height="{ROW_H}"/>',
    ]

    if num:
        parts.append(
            f'<text class="row-num" x="{ROWNUM_X}" y="{y}" text-anchor="end">'
            f'{_html_escape(str(num))}</text>'
        )
    if step.get("note"):
        parts.append(
            f'<text class="{_cls("row-note", tone)}" x="{gutter_x:.0f}" y="{y}">'
            f'{_html_escape(str(step["note"]))}</text>'
        )

    if arrow == "band":
        # A narrated aside laid across the actors it concerns — the device that
        # carries "pre-processing — auth, tenant resolution, JPA task lookup"
        # without spending an arrow on it.
        lo, hi = min(fx, tx), max(fx, tx)
        text_w = text_px(step.get("label", ""), "seq-band")
        span = max(hi - lo + 2 * BAND_PAD, text_w + 2 * BAND_TEXT_X)
        bx = lo - BAND_PAD
        parts.append(
            f'<rect class="{_cls("band", tone)}" x="{bx}" y="{y - BAND_H // 2}" '
            f'width="{span:.0f}" height="{BAND_H}" rx="3"/>'
        )
        parts.append(
            f'<text class="{_cls("band-text", tone)}" x="{bx + BAND_TEXT_X}" '
            f'y="{y + 4}">{label}</text>'
        )
    elif arrow == "self":
        # Square bracket hanging off the lifeline with the head pointing back at
        # it. Mirrored on the rightmost actor so the label stays on the canvas.
        max_x = max(actor_x.values())
        side = -1 if fx == max_x else 1
        anchor = ' text-anchor="end"' if side < 0 else ""
        far = fx + SELF_W * side
        lx = fx + (SELF_W + SELF_LABEL_GAP) * side
        parts.append(
            f'<path class="{_cls("arr", tone)}" fill="none" '
            f'd="M {fx} {y - SELF_H} H {far} V {y} H {fx}"{dash}/>'
        )
        parts.append(_head(fx, y, -side, _cls("arr-head", tone)))
        parts.append(f'<text class="{_cls("arrow-label", tone)}" x="{lx}" y="{y - 5}"{anchor}>{label}</text>')
        if sub:
            parts.append(
                f'<text class="{_cls("arrow-sub", tone)}" x="{lx}" y="{y + SUB_DY}"{anchor}>'
                f'{_html_escape(sub)}</text>'
            )
    else:
        sign = 1 if tx > fx else -1
        x1 = fx + ARROW_INSET * sign
        x2 = tx - (ARROW_INSET + 1) * sign
        parts.append(
            f'<line class="{_cls("arr", tone)}" x1="{x1}" y1="{y}" x2="{x2}" y2="{y}"{dash}/>'
        )
        parts.append(_head(tx - ARROW_INSET * sign, y, sign, _cls("arr-head", tone)))
        mid = (fx + tx) // 2
        for txt, style, cls, dy in (
            (step.get("label", ""), "seq-label", "arrow-label", LABEL_DY),
            (sub or "", "seq-tag", "arrow-sub", SUB_DY),
        ):
            if not txt:
                continue
            # Centre on the arrow, but never let a long label run into the note
            # gutter — slide it left instead.
            cx = mid
            half = text_px(txt, style) / 2
            if cx + half > gutter_x - 10:
                cx = gutter_x - 10 - half
            parts.append(
                f'<text class="{_cls(cls, tone)}" x="{cx:.0f}" y="{y + dy}" '
                f'text-anchor="middle">{_html_escape(txt)}</text>'
            )

    parts.append("</g>")
    return "".join(parts)


def _render_phases(
    phases: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    step_index: dict[str, int],
    row_y,
    total_w: int,
) -> str:
    """Phase separators: a hairline across the canvas with the phase name in the
    row above it. The label owns that row (PHASE_LABEL_H == ROW_H), so it cannot
    collide with an arrow label the way the previous full-width wash did."""
    parts: list[str] = []
    for phase in phases:
        idx = step_index[phase["start_at"]]
        y = row_y(idx) - ROW_H
        parts.append(f'<line class="phase-rule" x1="0" y1="{y + 5}" x2="{total_w}" y2="{y + 5}"/>')
        parts.append(
            f'<text class="phase-label" x="{PAD_LEFT}" y="{y + 1}">'
            f'{_html_escape(phase["label"])}</text>'
        )
    return "".join(parts)
