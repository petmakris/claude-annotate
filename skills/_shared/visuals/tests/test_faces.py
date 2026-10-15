"""Diagrams measure their text in the face their page draws: annotate's fonts by default, Inter on the stage."""
import pytest

from skills._shared.visuals import flowchart, font_metrics, text_metrics

FLOW = {"nodes": [{"id": "a", "role": "entry", "label": "A start with several words"},
                  {"id": "b", "role": "code", "ref": "Service:42", "method": "handle(Request req)"}],
        "edges": [{"from": "a", "to": "b"}]}


def test_the_stage_face_measures_with_the_geist_tables():
    text = "Montblanc pins 2026-R1"
    default = text_metrics.text_px(text, "flow-ref")
    with text_metrics.face("stage"):
        stage = text_metrics.text_px(text, "flow-ref")
    assert stage != default
    assert stage == pytest.approx(sum(font_metrics.STAGE_MONO.get(c, font_metrics.STAGE_MONO_FALLBACK)
                                      for c in text) * 12.0)
    assert text_metrics.text_px(text, "flow-ref") == default


def test_an_unknown_face_is_refused():
    with pytest.raises(ValueError, match="no face"):
        with text_metrics.face("comic"):
            pass


def test_a_diagram_drawn_in_the_stage_face_is_laid_out_for_it():
    assert flowchart.render(FLOW, "b", face="stage") != flowchart.render(FLOW, "b")
    assert flowchart.render(FLOW, "b", face="annotate") == flowchart.render(FLOW, "b")
