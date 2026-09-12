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
# A fixed grid, and a narrow one on purpose. The renderer this replaced painted
# every label and sub-caption on its arrow, centred on a span far narrower than
# the text: on a six-actor diagram the lane pitch was 122px while labels ran to
# 347px, so captions sat under lifelines they had nothing to do with and the
# outermost ones left the canvas entirely. Here the grid carries arrows and a
# numbered badge and nothing else; every word lives in `render_key` below. The
# canvas is therefore a function of the actors alone, which is what lets a
# twelve-actor flow render at full type size inside a card that does not scroll.
ACTOR_W_MIN = 112        # actor box width; grows only if a wrapped line needs it
ACTOR_PAD_X = 12         # total horizontal padding inside an actor box
ACTOR_GAP = 16           # gap between adjacent actor boxes
ACTOR_H2 = 46            # box height, two-line name
ACTOR_H1 = 33            # box height, one-line name
ACTOR_LINE_1 = 17        # first name baseline, relative to box top
ACTOR_LINE_2 = 30        # second name baseline, relative to box top
NAME_MAX_LINES = 2

PAD_LEFT = 24            # no row-number column any more: the numbers are badges
PAD_RIGHT = 24

LEGEND_TOP = 13          # first legend line's centre
LEGEND_LINE_H = 19       # a wrapped legend's line pitch
LEGEND_SWATCH_W = 22
LEGEND_TEXT_GAP = 7
LEGEND_ITEM_GAP = 26

ROW_H = 26               # row pitch — a badge row, not a two-line caption row
ARROW_INSET = 6          # arrow endpoints stop this far short of the lifeline
HEAD_LEN = 7             # arrowhead triangle length
BAND_H = 21
BAND_PAD = 30            # band overhang past the outermost lifeline it spans
BAND_TEXT_X = 10
SELF_W = 20              # self-call bracket width
SELF_H = 13
SELF_BADGE_GAP = 14      # bracket edge → badge centre

BADGE_R = 8.5            # the visible numbered circle
BADGE_HIT_R = 13         # the transparent disc that actually takes the click
BADGE_NUM_DY = 3.5       # number baseline, relative to the badge centre

PHASE_LABEL_H = 30       # a phase label owns a whole row; nothing shares its y


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


def _numbered(steps: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int | None]]:
    """Pair each step with its badge number, or None for a band.

    A band narrates across the actors it spans rather than carrying a message,
    so it has nothing for a key entry to say and no number to pair with. Every
    other step is numbered from 1, and that ordinal is what the badge shows and
    what the key repeats — but it is deliberately NOT what the two halves are
    paired on. They pair on `data-step-id`, which is stable when a step is
    inserted and is already what a comment anchors to.
    """
    out: list[tuple[dict[str, Any], int | None]] = []
    n = 0
    for step in steps:
        if step["arrow"] == "band":
            out.append((step, None))
            continue
        n += 1
        out.append((step, n))
    return out


def _legend_lines(legend: list[dict[str, Any]], max_w: float) -> list[list[tuple[dict, float]]]:
    """Greedily pack legend entries onto lines that fit `max_w`.

    The old legend ran on one line whatever its width: on the reference diagram
    its last entry reached x=1036 on an 890px canvas and was simply cut off.
    """
    lines: list[list[tuple[dict, float]]] = [[]]
    x = float(PAD_LEFT)
    for item in legend:
        w = LEGEND_SWATCH_W + LEGEND_TEXT_GAP + text_px(str(item["label"]), "seq-legend")
        if lines[-1] and x + w > max_w - PAD_RIGHT:
            lines.append([])
            x = float(PAD_LEFT)
        lines[-1].append((item, x))
        x += w + LEGEND_ITEM_GAP
    return lines


def _render_legend(lines: list[list[tuple[dict, float]]]) -> str:
    """Tone key across the top. Only tones the author declared appear."""
    parts = ['<g class="seq-legend">']
    for row, entries in enumerate(lines):
        y = LEGEND_TOP + row * LEGEND_LINE_H
        for item, x in entries:
            tone = _tone_of(item)
            label = str(item["label"])
            parts.append(
                f'<line class="{_cls("legend-swatch", tone)}" x1="{x:.0f}" y1="{y}" '
                f'x2="{x + LEGEND_SWATCH_W:.0f}" y2="{y}"/>'
            )
            parts.append(
                f'<text class="legend-text" x="{x + LEGEND_SWATCH_W + LEGEND_TEXT_GAP:.0f}" '
                f'y="{y + 4}">{_html_escape(label)}</text>'
            )
    parts.append("</g>")
    return "".join(parts)


def render(spec: dict[str, Any], block_id: str) -> str:
    """Render a validated spec to the grid: arrows, bands and numbered badges.

    The words that used to sit on these arrows are in `render_key(spec)`.
    Rendering one without the other leaves a diagram of unexplained numbers, so
    callers must paint both — see `render_block` in ../render.py, which puts
    them on the wire as `svg` and `key`.

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

    # Width is a function of the actors, and of a band's text when it is wider
    # than the actors it spans. Nothing else on this canvas is text, so nothing
    # else can drag the canvas past the card and make it scroll.
    grid_w = PAD_LEFT + actor_w + (len(actors) - 1) * pitch + PAD_RIGHT
    total_w = int(max(grid_w, _widest_band_right(steps, actor_x) + PAD_RIGHT))

    legend_lines = _legend_lines(legend, total_w) if legend else []
    legend_h = (LEGEND_TOP + (len(legend_lines) - 1) * LEGEND_LINE_H + 10) if legend else 0
    actor_top = legend_h + 8
    box_h = ACTOR_H2 if any(len(g) > 1 for g in name_lines) else ACTOR_H1
    lifeline_top = actor_top + box_h + 6

    # Row grid. A phase label owns a whole row of its own, so its text can never
    # land on the same baseline band as a badge.
    step_index = {s["id"]: i for i, s in enumerate(steps)}
    phase_offsets: dict[int, int] = {step_index[p["start_at"]]: PHASE_LABEL_H for p in phases}

    def row_y(i: int) -> int:
        return lifeline_top + 13 + i * ROW_H + sum(phase_offsets.get(k, 0) for k in range(i + 1))

    total_h = row_y(len(steps) - 1) + ROW_H // 2 + 12

    parts: list[str] = []
    # No data-block-id on the SVG root: the host <section> already carries it,
    # and putting it here would let the catch-all `[data-block-id]:hover` rule
    # in style.css paint a background tint on the SVG element itself.
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" '
        f'width="{total_w}" height="{total_h}" class="annotate-seq">'
    )

    if legend:
        parts.append(_render_legend(legend_lines))

    lifeline_bottom = total_h - 8
    for x in xs:
        parts.append(
            f'<line class="lane" x1="{x}" y1="{lifeline_top}" x2="{x}" y2="{lifeline_bottom}"/>'
        )

    for actor, x, lines in zip(actors, xs, name_lines):
        parts.append(_render_actor(actor, x, lines, actor_top, actor_w, box_h))

    if phases:
        parts.append(_render_phases(phases, step_index, row_y, total_w))

    for i, (step, num) in enumerate(_numbered(steps)):
        parts.append(_render_step(step, block_id, actor_x, row_y(i), total_w, num))

    parts.append("</svg>")
    return "".join(parts)


def render_key(spec: dict[str, Any], block_id: str) -> str:
    """The numbered key that reads alongside `render(spec)`'s grid.

    HTML, not SVG, and deliberately so: it is the half that has to reflow when
    the card narrows, and the half a reader selects text out of.

    Returns "" when the spec has no message steps — a diagram of nothing but
    bands has no numbers, and an empty key div would draw a rule under the grid
    for no reason.
    """
    validate(spec)
    steps = spec["steps"]
    phase_at = {p["start_at"]: str(p["label"]) for p in (spec.get("phases") or [])}
    bid = _html_escape(block_id, quote=True)

    rows: list[str] = []
    for step, num in _numbered(steps):
        if step["id"] in phase_at:
            rows.append(
                f'<div class="seq-key-phase"><span>'
                f'{_html_escape(phase_at[step["id"]])}</span></div>'
            )
        if num is None:
            continue
        tone = _tone_of(step)
        note = step.get("note")
        flag = (f'<span class="{_cls("seq-key-flag", tone)}">'
                f'{_html_escape(str(note))}</span>') if note else ""
        sub = step.get("sub")
        sub_html = (f'<div class="seq-key-sub">{_html_escape(str(sub))}</div>') if sub else ""
        rows.append(
            f'<div class="{_cls("seq-key-row", tone)}" data-block-id="{bid}" '
            f'data-step-id="{_html_escape(step["id"], quote=True)}" '
            f'role="button" tabindex="0">'
            f'<span class="{_cls("seq-key-n", tone)}">{num}</span>'
            f'<div class="seq-key-text">'
            f'<div class="seq-key-label">{_html_escape(step.get("label", ""))}{flag}</div>'
            f'{sub_html}</div></div>'
        )
    if not any(num is not None for _, num in _numbered(steps)):
        return ""
    return f'<div class="seq-key" data-block-id="{bid}">' + "".join(rows) + "</div>"


def _widest_band_right(steps: list[dict[str, Any]], actor_x: dict[str, int]) -> float:
    """Right-most pixel any band reaches. Bands are the only text left on the
    canvas, so they are the only thing that can still widen it."""
    right = 0.0
    for s in steps:
        if s["arrow"] != "band":
            continue
        fx, tx = actor_x[s["from"]], actor_x[s["to"]]
        lo, hi = min(fx, tx), max(fx, tx)
        span = max(hi - lo + 2 * BAND_PAD,
                   text_px(s.get("label", ""), "seq-band") + 2 * BAND_TEXT_X)
        right = max(right, lo - BAND_PAD + span)
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


def _head(x: float, y: float, facing: int, cls: str) -> str:
    """Filled triangle arrowhead at (x, y). facing=1 points right, -1 left."""
    return (f'<path class="{cls}" d="M {x:.0f} {y:.0f} l {-HEAD_LEN * facing:.0f} -4 '
            f'v 8 z"/>')


def _render_badge(step: dict[str, Any], block_id: str, cx: float, cy: float,
                  num: int) -> str:
    """The one clickable thing in a sequence diagram.

    `.annotate-seq .step-row` deliberately has no pointer cursor: a picture is
    commented as a whole, from the card header, and an affordance that promises
    a click nothing answers is worse than none. A badge is the exception
    because a badge's click HAS an answer — the key entry with the same
    `data-step-id` lights up. Shipping the badge without the key would put this
    straight back into the case that rule exists to prevent.
    """
    tone = _tone_of(step)
    label = step.get("label", "")
    return (
        f'<g class="badge-hit" data-block-id="{_html_escape(block_id, quote=True)}" '
        f'data-step-id="{_html_escape(step["id"], quote=True)}" role="button" '
        f'tabindex="0" aria-label="Step {num}: {_html_escape(label, quote=True)}">'
        f'<circle class="badge-halo" cx="{cx:.0f}" cy="{cy:.0f}" r="{BADGE_HIT_R}"/>'
        f'<circle class="{_cls("step-badge", tone)}" cx="{cx:.0f}" cy="{cy:.0f}" '
        f'r="{BADGE_R}"/>'
        f'<text class="{_cls("badge-num", tone)}" x="{cx:.0f}" y="{cy + BADGE_NUM_DY:.0f}" '
        f'text-anchor="middle">{num}</text>'
        f'<circle class="badge-target" cx="{cx:.0f}" cy="{cy:.0f}" r="{BADGE_HIT_R}"/>'
        f'</g>'
    )


def _render_step(step: dict[str, Any], block_id: str, actor_x: dict[str, int],
                 y: int, total_w: int, num: int | None) -> str:
    """Emit one step row: the arrow (or band) and its numbered badge.

    y is the arrow centreline. No label, no sub-caption and no note — those are
    the key's, and putting any of them back here reopens the collisions the
    split exists to close."""
    sid = step["id"]
    arrow = step["arrow"]
    tone = _tone_of(step)
    fx = actor_x[step["from"]]
    tx = actor_x[step["to"]]
    dash = ' stroke-dasharray="5 4"' if arrow in ("event", "dropped") or tone == "dropped" else ""

    parts = [
        f'<g class="step-row" data-block-id="{_html_escape(block_id, quote=True)}" '
        f'data-step-id="{_html_escape(sid, quote=True)}">',
        f'<rect class="row-bg" x="0" y="{y - ROW_H // 2}" width="{total_w}" height="{ROW_H}"/>',
    ]

    if arrow == "band":
        # A narrated aside laid across the actors it concerns — the device that
        # carries "pre-processing — auth, tenant resolution, JPA task lookup"
        # without spending an arrow on it. It keeps its text, because it is not
        # a message and has no key entry to move the text into.
        lo, hi = min(fx, tx), max(fx, tx)
        text_w = text_px(step.get("label", ""), "seq-band")
        span = max(hi - lo + 2 * BAND_PAD, text_w + 2 * BAND_TEXT_X)
        bx = lo - BAND_PAD
        parts.append(
            f'<rect class="{_cls("band", tone)}" x="{bx}" y="{y - BAND_H // 2}" '
            f'width="{span:.0f}" height="{BAND_H}" rx="3"/>'
        )
        parts.append(
            f'<text class="{_cls("band-text", tone)}" x="{bx + span / 2:.0f}" '
            f'y="{y + 4}" text-anchor="middle">{_html_escape(step.get("label", ""))}</text>'
        )
        parts.append("</g>")
        return "".join(parts)

    if arrow == "self":
        # Square bracket hanging off the lifeline with the head pointing back at
        # it. Mirrored on the rightmost actor so the badge stays on the canvas.
        max_x = max(actor_x.values())
        side = -1 if fx == max_x else 1
        far = fx + SELF_W * side
        parts.append(
            f'<path class="{_cls("arr", tone)}" fill="none" '
            f'd="M {fx} {y - SELF_H} H {far} V {y} H {fx}"{dash}/>'
        )
        parts.append(_head(fx, y, -side, _cls("arr-head", tone)))
        badge_x = fx + (SELF_W + SELF_BADGE_GAP) * side
    else:
        sign = 1 if tx > fx else -1
        x1 = fx + ARROW_INSET * sign
        x2 = tx - (ARROW_INSET + 1) * sign
        parts.append(
            f'<line class="{_cls("arr", tone)}" x1="{x1}" y1="{y}" x2="{x2}" y2="{y}"{dash}/>'
        )
        parts.append(_head(tx - ARROW_INSET * sign, y, sign, _cls("arr-head", tone)))
        badge_x = (fx + tx) / 2

    parts.append(_render_badge(step, block_id, badge_x, y, num))
    parts.append("</g>")
    return "".join(parts)


def _render_phases(
    phases: list[dict[str, Any]],
    step_index: dict[str, int],
    row_y,
    total_w: int,
) -> str:
    """Phase separators: the phase name on its own row with a hairline running
    off its right shoulder to the canvas edge."""
    parts: list[str] = []
    for phase in phases:
        y = row_y(step_index[phase["start_at"]]) - ROW_H
        label = str(phase["label"]).upper()
        lx = PAD_LEFT - 20 if PAD_LEFT >= 20 else 0
        parts.append(
            f'<text class="phase-label" x="{lx}" y="{y + 1}">'
            f'{_html_escape(label)}</text>'
        )
        rule_x = lx + text_px(label, "seq-legend") + 14
        parts.append(
            f'<line class="phase-rule" x1="{rule_x:.0f}" y1="{y - 3}" '
            f'x2="{total_w - 8}" y2="{y - 3}"/>'
        )
    return "".join(parts)
