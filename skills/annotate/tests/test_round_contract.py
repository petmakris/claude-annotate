"""Guards on the round contract Claude executes.

Everything else in this feature is a control that queues an intent. This file
guards the half that acts on it. Two failure modes are worth a test each: the
contract describing compact as if it were delete, and the sweep drifting to
after the ack — which is when the user sees the page, so a sweep after it is
a sweep the user watches happen.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "skills" / "annotate" / "references" / "handling-events.md"


def test_compact_is_in_the_kind_table():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "`compact`" in doc, "the contract does not mention compact"


def test_compact_is_distinguished_from_delete():
    """The single most important line in the contract. If compact reads as a
    synonym for delete, Claude stops acting on content the user only wanted
    off the page."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still binds" in doc, \
        "the contract does not say a compacted idea still binds the plan"
    assert "out of scope" in doc, \
        "the contract lost the phrase that makes delete's meaning explicit"


def test_keep_beats_compact():
    """A user can protect one sentence and compact its neighbour in the same
    round. The absorb wants to rewrite the protected one."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "keep` beats compact" in doc or "keep beats compact" in doc, \
        "the contract does not resolve keep against a neighbouring compact"


def test_nothing_is_stored_off_page():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "no hidden store" in doc.lower() or "not retained" in doc.lower(), \
        "the contract does not forbid retaining compacted content"


def test_the_sweep_runs_before_the_ack():
    """Order is the whole point: the ack unlocks the page."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "sweep" in doc.lower(), "the contract has no coherence sweep"
    sweep = doc.lower().index("coherence sweep")
    section = doc[sweep:sweep + 2500].lower()
    assert "before" in section and "ack" in section, \
        "the sweep does not state its position relative to the ack"


def test_the_sweep_is_bounded():
    """An unbounded 'make it all coherent' pass churns the whole document
    every round and inflates versions on blocks the user never touched."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still reads true" in doc, \
        "the contract does not forbid rewriting blocks that are still true"
