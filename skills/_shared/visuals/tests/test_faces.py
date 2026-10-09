"""Diagrams measure their text in the face their page draws: annotate's fonts by default, Inter on the stage."""
import pytest

from skills._shared.visuals import flowchart, font_metrics, sequence, text_metrics

SEQ = {"actors": [{"id": "p", "label": "EnrichedProposalBatchService"}, {"id": "s", "label": "Server"}],
       "steps": [{"id": "s1", "from": "p", "to": "s", "arrow": "band", "label": "a long band of narrated words"}]}
FLOW = {"nodes": [{"id": "a", "role": "entry", "label": "A start with several words"},
                  {"id": "b", "role": "code", "ref": "Service:42", "method": "handle(Request req)"}],
        "edges": [{"from": "a", "to": "b"}]}


def test_the_stage_face_measures_with_the_geist_tables():
    text = "Montblanc pins 2026-R1"
    default = text_metrics.text_px(text, "seq-band")
    with text_metrics.face("stage"):
        stage = text_metrics.text_px(text, "seq-band")
    assert stage != default
    assert stage == pytest.approx(sum(font_metrics.STAGE_MONO.get(c, font_metrics.STAGE_MONO_FALLBACK)
                                      for c in text) * 10.5)
    assert text_metrics.text_px(text, "seq-band") == default


def test_an_unknown_face_is_refused():
    with pytest.raises(ValueError, match="no face"):
        with text_metrics.face("comic"):
            pass


def test_a_diagram_drawn_in_the_stage_face_is_laid_out_for_it():
    assert sequence.render(SEQ, "b", face="stage") != sequence.render(SEQ, "b")
    assert flowchart.render(FLOW, "b", face="stage") != flowchart.render(FLOW, "b")
    assert sequence.render(SEQ, "b", face="annotate") == sequence.render(SEQ, "b")
