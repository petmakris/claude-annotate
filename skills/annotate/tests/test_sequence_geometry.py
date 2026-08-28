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
    ACTOR_GAP, ACTOR_W_MIN, ROW_H, render,
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


def test_phase_label_clears_the_text_on_both_neighbouring_rows():
    """The old renderer put the phase name 7px above the first arrow label and
    horizontally on top of it. A phase label now owns a whole row, so it has to
    clear the sub-caption of the step above it AND the label of the step below —
    the row above is the tight one, because a sub-caption hangs 13px below its
    arrow while a label sits only 6px above one."""
    spec = _spec(["A", "B"])
    spec["steps"] = [
        {"id": "s1", "from": "a0", "to": "a1", "arrow": "request",
         "label": "first", "sub": "a sub-caption hanging below the first arrow"},
        {"id": "s2", "from": "a1", "to": "a0", "arrow": "request",
         "label": "a long second label that reaches well to the left"},
    ]
    spec["phases"] = [{"id": "p1", "label": "SECOND PHASE", "start_at": "s2"}]
    root = ET.fromstring(render(spec, "section-1"))
    phase_y = above_y = below_y = None
    for el in root.iter():
        cls = (el.get("class") or "").split()
        if "phase-label" in cls:
            phase_y = float(el.get("y"))
        elif "arrow-sub" in cls and above_y is None:
            above_y = float(el.get("y"))          # s1's sub-caption
        elif "arrow-label" in cls and el.text and el.text.startswith("a long"):
            below_y = float(el.get("y"))          # s2's label
    assert None not in (phase_y, above_y, below_y)
    assert phase_y - above_y >= 14, \
        f"phase label at y={phase_y} crowds the sub-caption above it at y={above_y}"
    assert below_y - phase_y >= 14, \
        f"phase label at y={phase_y} crowds the arrow label below it at y={below_y}"


def test_arrow_label_never_runs_into_the_note_gutter():
    spec = _spec(["Alpha", "Beta"])
    spec["steps"] = [{
        "id": "s1", "from": "a0", "to": "a1", "arrow": "request",
        "label": "an extremely long call label that would otherwise sail past the gutter",
        "note": "1,409 ms",
    }]
    root = ET.fromstring(render(spec, "section-1"))
    label_right = note_left = None
    for el in root.iter():
        cls = (el.get("class") or "").split()
        if "arrow-label" in cls:
            w = text_px(el.text or "", "seq-label")
            label_right = float(el.get("x")) + w / 2
        elif "row-note" in cls:
            note_left = float(el.get("x"))
    assert label_right is not None and note_left is not None
    assert label_right <= note_left, \
        f"arrow label reaches {label_right:.0f}, note column starts at {note_left:.0f}"


def test_row_numbers_count_only_noted_steps():
    spec = _spec(["A", "B"])
    spec["steps"] = [
        {"id": "s1", "from": "a0", "to": "a1", "arrow": "request", "label": "x"},
        {"id": "s2", "from": "a1", "to": "a0", "arrow": "request", "label": "y", "note": "5 ms"},
        {"id": "s3", "from": "a0", "to": "a1", "arrow": "request", "label": "z", "note": "9 ms"},
    ]
    svg = render(spec, "section-1")
    assert ">#1<" in svg and ">#2<" in svg and ">#3<" not in svg


def test_actor_name_wrapping_is_lossless():
    """Tokenising must never drop a character: an extracting regex turned
    `auth-service` into `authservice` and `<script>` into `script`."""
    from skills.annotate.diagrams.sequence import _name_lines
    for label in ("EnrichedProposalBatchService", "auth-service-gateway",
                  "api.gateway.internal", "worker_pool_manager", "<script>x</script>"):
        assert "".join(_name_lines(label, 100)) == label, label
