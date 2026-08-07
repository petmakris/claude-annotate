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
    """Order is the whole point: the ack unlocks the page. Anchored on the
    `## The coherence sweep` heading itself, not the first occurrence of the
    phrase anywhere in the doc — the Mode D universal-rule paragraph also
    says "coherence sweep" and sits thousands of characters away from this
    section, so anchoring on the phrase alone can miss the section entirely."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "## The coherence sweep" in doc, "the contract has no coherence sweep section"
    sweep = doc.index("## The coherence sweep")
    section = doc[sweep:sweep + 2500].lower()
    assert "before" in section and "ack" in section, \
        "the sweep does not state its position relative to the ack"


def test_reject_is_named_alongside_dismiss_in_the_universal_rule():
    """`reject` is a live legacy path — server.py accepts it alongside
    `dismiss` — not a hypothetical. Both places that illustrate the
    universal pre-ack rule's coverage must name it, or a reader can mistake
    the illustrative list for a closed set that excludes it."""
    doc = CONTRACT.read_text(encoding="utf-8")
    mode_d = doc.index("## Mode D")
    model_para = doc.index("## The model in one paragraph")
    universal_rule = doc[mode_d:model_para].lower()
    assert "reject" in universal_rule, \
        "the Mode D universal-rule paragraph does not name reject"

    sweep_heading = doc.index("## The coherence sweep")
    block_contract = doc.index("## Block-rewrite contract")
    sweep_section = doc[sweep_heading:block_contract].lower()
    assert "reject" in sweep_section, \
        "the coherence sweep section opening does not name reject"


def test_reject_edge_case_points_at_the_sweep():
    """The reject bullet in the block-rewrite contract mutates blocks.json
    via a non-null block_id and then acks — the same pre-ack condition as
    every other path — so it must point at the sweep the way the choice and
    general-comment paths do, rather than silently skipping it."""
    doc = CONTRACT.read_text(encoding="utf-8")
    reject_bullet = doc.index("The `type` is `reject`")
    next_bullet = doc.index("The user's `selected_text` no longer exists")
    section = doc[reject_bullet:next_bullet].lower()
    assert "coherence sweep" in section, \
        "the reject edge case does not point at the coherence sweep"


def test_the_sweep_is_bounded():
    """An unbounded 'make it all coherent' pass churns the whole document
    every round and inflates versions on blocks the user never touched."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still reads true" in doc, \
        "the contract does not forbid rewriting blocks that are still true"


def test_the_sweep_is_a_universal_pre_ack_rule():
    """The sweep must not read as round-only. It was written under the round
    subsection and a review found several other paths mutate blocks.json and
    ack with no sweep. The rule has to be stated once, generally, so every
    path inherits it instead of drifting out of sync with a per-path bullet."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "universal" in doc.lower(), \
        "the contract does not state the sweep as a universal rule"
    assert "not a step scoped to" in doc or "not a round-only step" in doc.lower(), \
        "the contract does not disclaim the sweep as round-only"


def test_the_choice_path_references_the_sweep():
    """Resolving a choice both converts the block and appends follow-ups —
    the highest-risk path of all, since nothing else checks the two against
    the rest of the document. Bounded to the choice subsection's own heading
    through the next subsection's heading, so this can't pass on a sweep
    mention that lives in a neighbouring section."""
    doc = CONTRACT.read_text(encoding="utf-8")
    choice = doc.index('### `WEBCOMPANION_EVENT` with `type: "choice"`')
    dismiss = doc.index('### `WEBCOMPANION_EVENT` with `type: "dismiss"`')
    section = doc[choice:dismiss].lower()
    assert "coherence sweep" in section, \
        "the choice path does not reference the coherence sweep"


def test_the_general_comment_path_references_the_sweep():
    """A cross-document directive ('make this shorter') can orphan a
    reference or glossary term elsewhere with nothing checking. Anchored on
    the block-rewrite contract's null-block_id subsection specifically, not
    just any mention of the phrase 'general comment' in the document."""
    doc = CONTRACT.read_text(encoding="utf-8")
    general = doc.index("`block_id` is `null` (general comment)")
    section = doc[general:general + 800].lower()
    assert "coherence sweep" in section, \
        "the general-comment path does not reference the coherence sweep"


def test_dismiss_is_covered_by_the_same_rule():
    """Dismiss is legacy but still mutates blocks.json and writes the ack —
    it does not get a special case. Bounded to the dismiss subsection's own
    heading through the next subsection's heading (round), so this can't
    pass on the round subsection's own sweep step instead."""
    doc = CONTRACT.read_text(encoding="utf-8")
    dismiss = doc.index('### `WEBCOMPANION_EVENT` with `type: "dismiss"`')
    round_ = doc.index('### `WEBCOMPANION_EVENT` with `type: "round"`')
    section = doc[dismiss:round_].lower()
    assert "coherence sweep" in section, \
        "the dismiss path does not reference the coherence sweep"


def test_the_contract_describes_the_change_note():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "change_note" in doc, "the contract does not mention change_note"


def test_a_compact_must_name_what_it_lost():
    """Compact is lossy and irreversible after submit. The change note is the
    only place the user could ever learn what it actually discarded."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "Lost:" in doc, \
        "the contract does not require a compact to name the dropped detail"


def test_the_change_note_is_optional():
    """A feature that breaks when Claude forgets a field is a broken feature.

    Scoped to the change_note section itself and to the specific claim, not
    a bare word search: "optional" already occurs elsewhere in the document
    (e.g. the coherence sweep is "not optional"), so an unscoped check for
    the substring alone stays green even if this whole section is deleted."""
    doc = CONTRACT.read_text(encoding="utf-8")
    start = doc.index("## Explaining a change: `change_note`")
    end = doc.index("## Block-rewrite contract")
    # Collapse whitespace: this document hand-wraps prose across source
    # lines within a paragraph (markdown treats a single newline as a
    # space), so a literal multi-word needle must not be sensitive to
    # exactly where the source happens to wrap.
    section = " ".join(doc[start:end].split())
    assert "`change_note` is **optional**" in section, \
        "the change_note section does not say change_note itself is optional"
    assert "diff renders with or without it" in section, \
        "the change_note section does not say the diff renders without it"
