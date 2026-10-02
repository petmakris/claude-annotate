"""Geometry invariants for rendered sequence diagrams.

Same idea as the flowchart geometry suite: assert on the rendered SVG, so a
label that no longer fits its box fails a test instead of quietly overflowing
in the browser.

Two of these pin defects the fit-to-width renderer shipped:

- it scaled the SVG to the card, so an eight-actor diagram rendered at 0.655x
  and its 11px labels landed at 7.2px;
- it drew the phase name on the same baseline band as the first arrow label,
  and the two overlapped.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from skills.annotate.diagrams.sequence import (
    ACTOR_GAP, ACTOR_W_MIN, BADGE_R, ROW_H, render,
)
from skills.annotate.diagrams.text_metrics import text_px


def _spec(labels: list[str], **extra) -> dict:
    actors = [{"id": f"a{i}", "label": lb} for i, lb in enumerate(labels)]
    steps = [{"id": "s1", "from": "a0", "to": f"a{len(labels) - 1}",
              "arrow": "request", "label": "call", "sub": "with payload"}]
    return {"actors": actors, "steps": steps, **extra}


CASES = {
    "short": ["UI", "API"],
    "typical": ["Browser", "OrderService", "Repository"],
    "long_labels": ["OrderWorkflowActionsService", "WorkflowTaskRepository",
                    "NotificationDispatcher"],
    "many": [f"Actor{i}" for i in range(6)],
    "dozen": ["Browser", "Kong", "ProposalListController",
              "InternalProposalTaskService", "EnrichedProposalBatchService",
              "ProposedOrdersService", "PortfolioCheckupFactory",
              "EnrichedProposalService", "Integration Layer", "Morpheus",
              "BPS", "Rule Engine"],
}


def _parse(svg: str):
    root = ET.fromstring(svg)
    vw, vh = [float(v) for v in root.get("viewBox").split()][2:]
    boxes, labels = [], []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        cls = (el.get("class") or "").split()
        if tag == "rect" and "actor-box" in cls:
            x, w = float(el.get("x")), float(el.get("width"))
            boxes.append((x, x + w))
        elif tag == "text" and "actor-label" in cls:
            labels.append((el.text or "", float(el.get("x"))))
    return root, vw, vh, boxes, labels


@pytest.mark.parametrize("name,lbls", CASES.items(), ids=list(CASES))
def test_actor_label_fits_its_box(name, lbls):
    _, _, _, boxes, labels = _parse(render(_spec(lbls), "section-1"))
    assert boxes, f"{name}: no actor boxes rendered"
    for txt, cx in labels:
        w = text_px(txt, "seq-name")
        box = next(b for b in boxes if b[0] <= cx <= b[1])
        assert cx - w / 2 >= box[0] - 0.5 and cx + w / 2 <= box[1] + 0.5, \
            f"{name}: actor label {txt!r} overflows its box"


@pytest.mark.parametrize("name,lbls", CASES.items(), ids=list(CASES))
def test_actor_boxes_do_not_touch(name, lbls):
    _, _, _, boxes, _ = _parse(render(_spec(lbls), "section-1"))
    for (a0, a1), (b0, b1) in zip(boxes, boxes[1:]):
        assert b0 - a1 >= ACTOR_GAP - 0.5, \
            f"{name}: actor boxes {a1:.0f} / {b0:.0f} too close"


@pytest.mark.parametrize("name,lbls", CASES.items(), ids=list(CASES))
def test_boxes_inside_viewbox(name, lbls):
    _, vw, _, boxes, _ = _parse(render(_spec(lbls), "section-1"))
    for x0, x1 in boxes:
        assert x0 >= -0.5 and x1 <= vw + 0.5, f"{name}: box ({x0},{x1}) outside width {vw}"


@pytest.mark.parametrize("name,lbls", CASES.items(), ids=list(CASES))
def test_column_pitch_is_constant(name, lbls):
    """Every column is the same width, whatever the labels. A long actor name
    wraps onto a second line; it never widens its own column and squeezes the
    rest, which is what made wide diagrams shrink."""
    _, _, _, boxes, _ = _parse(render(_spec(lbls), "section-1"))
    widths = {round(x1 - x0) for x0, x1 in boxes}
    assert len(widths) == 1, f"{name}: columns differ in width: {sorted(widths)}"
    pitches = {round(b[0] - a[0]) for a, b in zip(boxes, boxes[1:])}
    assert len(pitches) <= 1, f"{name}: column pitch is not constant: {sorted(pitches)}"


def test_default_column_width_is_the_grid_minimum():
    """Names that wrap to fit stay on the 112px grid — the density guarantee."""
    _, _, _, boxes, _ = _parse(render(_spec(CASES["dozen"]), "section-1"))
    assert round(boxes[0][1] - boxes[0][0]) == ACTOR_W_MIN


@pytest.mark.parametrize("name,lbls", CASES.items(), ids=list(CASES))
def test_svg_carries_pixel_size_so_it_never_scales_down(name, lbls):
    """width/height must equal the viewBox. Without them the SVG is fluid and
    the card scales it — an eight-actor diagram used to render at 0.655x, which
    put 11px labels on screen at 7.2px."""
    root, vw, vh, _, _ = _parse(render(_spec(lbls), "section-1"))
    assert root.get("width") == str(int(vw))
    assert root.get("height") == str(int(vh))


def test_phase_label_clears_the_badges_on_both_neighbouring_rows():
    """A phase label owns a whole row, so it has to clear the badge above it
    and the badge below it. The old renderer drew the phase name on the same
    baseline band as the first arrow label and the two overlapped; the label
    text is gone now, but a badge is 8.5px tall either side of its centreline
    and the same collision is available if the row is not reserved."""
    spec = _spec(["A", "B"])
    spec["steps"] = [
        {"id": "s1", "from": "a0", "to": "a1", "arrow": "request", "label": "first"},
        {"id": "s2", "from": "a1", "to": "a0", "arrow": "request", "label": "second"},
    ]
    spec["phases"] = [{"id": "p1", "label": "SECOND PHASE", "start_at": "s2"}]
    root = ET.fromstring(render(spec, "section-1"))
    phase_y, badge_ys = None, []
    for el in root.iter():
        cls = (el.get("class") or "").split()
        if "phase-label" in cls:
            phase_y = float(el.get("y"))
        elif "step-badge" in cls:
            badge_ys.append(float(el.get("cy")))
    assert phase_y is not None and len(badge_ys) == 2
    above, below = sorted(badge_ys)
    assert phase_y - (above + BADGE_R) >= 8, \
        f"phase label at y={phase_y} crowds the badge above it at cy={above}"
    assert (below - BADGE_R) - phase_y >= 8, \
        f"phase label at y={phase_y} crowds the badge below it at cy={below}"


def test_no_text_but_a_band_can_widen_the_canvas():
    """The defect this replaces: an arrow label centred on a narrow span ran
    into the note gutter, and the renderer slid it left to compensate. There is
    no arrow label and no gutter now, so the canvas is a function of the actors
    alone — a band is the one exception, because a band keeps its text.

    Three specs, identical actors, wildly different text. Only the band moves
    the number."""
    def width(steps):
        spec = _spec(["Alpha", "Beta"])
        spec["steps"] = steps
        return float(ET.fromstring(render(spec, "section-1")).get("viewBox").split()[2])

    plain = width([{"id": "s1", "from": "a0", "to": "a1", "arrow": "request",
                    "label": "x"}])
    verbose = width([{"id": "s1", "from": "a0", "to": "a1", "arrow": "request",
                      "label": "an extremely long call label that would otherwise "
                               "sail past the gutter and scroll the card",
                      "sub": "and a sub-caption just as long, for good measure",
                      "note": "1,409 ms"}])
    banded = width([{"id": "s1", "from": "a0", "to": "a0", "arrow": "band",
                     "label": "a band whose narration is far wider than the two "
                              "actors it is laid across"}])
    assert plain == verbose, f"label and note still move the canvas: {plain} vs {verbose}"
    assert banded > plain, "a band wider than its actors must still widen the canvas"


def test_every_message_step_is_numbered_and_a_band_is_not():
    """Numbering used to count only the steps carrying a note, because a number
    was a gutter annotation. A number is now the handle that pairs an arrow to
    its key entry, so every step that has a key entry needs one — and a band,
    which has none, must not take an ordinal from the steps that do."""
    spec = _spec(["A", "B"])
    spec["steps"] = [
        {"id": "s1", "from": "a0", "to": "a1", "arrow": "request", "label": "x"},
        {"id": "s2", "from": "a0", "to": "a0", "arrow": "band", "label": "aside"},
        {"id": "s3", "from": "a1", "to": "a0", "arrow": "request", "label": "y", "note": "5 ms"},
    ]
    svg = render(spec, "section-1")
    nums = [el.text for el in ET.fromstring(svg).iter()
            if "badge-num" in (el.get("class") or "").split()]
    assert nums == ["1", "2"], nums


def test_actor_name_wrapping_is_lossless():
    """Tokenising must never drop a character: an extracting regex turned
    `auth-service` into `authservice` and `<script>` into `script`."""
    from skills.annotate.diagrams.sequence import _name_lines
    for label in ("EnrichedProposalBatchService", "auth-service-gateway",
                  "api.gateway.internal", "worker_pool_manager", "<script>x</script>"):
        assert "".join(_name_lines(label, 100)) == label, label
