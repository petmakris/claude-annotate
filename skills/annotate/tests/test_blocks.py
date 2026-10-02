import json
import pytest
from pathlib import Path

import pytest

from skills.annotate.blocks import (
    BlocksDoc, load, save_atomic, update_block, next_block_id,
    update_spec_block, next_step_id, drop_unused_terms, remove_block,
)


def test_load_missing_is_an_error(tmp_path):
    # It used to return an empty document, and a push of that emptied the page.
    from skills.annotate.blocks import BlocksFileError
    with pytest.raises(BlocksFileError):
        load(tmp_path / "blocks.json")


def test_load_drops_empty_markdown_blocks(tmp_path):
    # A real push once shipped a 0-char untitled block; the page rendered a
    # blank card. Empty markdown blocks are noise — load() filters them so
    # they never render and disappear on the next save (self-healing).
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps({
        "response_id": "r-e", "title": "t", "blocks": [
            {"id": "section-1", "title": "A", "markdown": "real content"},
            {"id": "section-2", "markdown": ""},
            {"id": "section-3", "title": "ghost", "markdown": "   \n  "},
        ],
    }))
    doc = load(path)
    assert [b["id"] for b in doc.blocks] == ["section-1"]


def test_load_keeps_spec_blocks_without_markdown(tmp_path):
    # kind blocks (sequence/diagram/choice) carry a spec, not markdown —
    # the empty-markdown filter must not eat them.
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps({
        "response_id": "r-s", "title": "t", "blocks": [
            {"id": "section-1", "kind": "sequence",
             "spec": {"actors": [], "steps": []}},
        ],
    }))
    doc = load(path)
    assert [b["id"] for b in doc.blocks] == ["section-1"]


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "blocks.json"
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[
        {"id": "b-0", "markdown": "hello"},
    ])
    save_atomic(path, doc)
    doc2 = load(path)
    assert doc2.response_id == "r-1"
    assert doc2.title == "t"
    assert doc2.blocks == doc.blocks


def test_save_atomic_strips_legacy_version_field(tmp_path):
    """Older sessions / habit-writers may still emit `version: N` on
    blocks. The on-disk format is canonical: it does not include version."""
    path = tmp_path / "blocks.json"
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[
        {"id": "b-0", "markdown": "hello", "version": 7},
        {"id": "b-1", "kind": "sequence", "spec": {"actors": [], "steps": []}, "version": 3},
    ])
    save_atomic(path, doc)
    raw = json.loads(path.read_text())
    for b in raw["blocks"]:
        assert "version" not in b


def test_update_block_returns_true_on_change(tmp_path):
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[
        {"id": "b-0", "markdown": "old"},
        {"id": "b-1", "markdown": "x"},
    ])
    changed = update_block(doc, "b-0", "new")
    assert changed is True
    assert doc.blocks[0]["markdown"] == "new"
    # No version field is mutated — versions live in versions.json now.


def test_update_block_no_op_when_unchanged(tmp_path):
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[
        {"id": "b-0", "markdown": "same"},
    ])
    changed = update_block(doc, "b-0", "same")
    assert changed is False


def test_update_block_unknown_id_raises():
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[])
    with pytest.raises(KeyError):
        update_block(doc, "b-99", "x")


def test_next_block_id_never_reuses():
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[
        {"id": "section-1", "markdown": "x", "version": 1},
        {"id": "section-5", "markdown": "y", "version": 1},
    ])
    # Next id is the smallest positive integer not in {1, 5}
    assert next_block_id(doc) == "section-2"


def test_next_block_id_empty_doc():
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[])
    assert next_block_id(doc) == "section-1"


def _seq_block(bid: str, spec: dict):
    return {"id": bid, "kind": "sequence", "spec": spec}


def test_update_spec_block_returns_true_on_change():
    spec_old = {"actors": [{"id": "a", "label": "A"}], "steps": []}
    spec_new = {"actors": [{"id": "a", "label": "A2"}], "steps": []}
    doc = BlocksDoc(response_id="r-1", title="t",
                    blocks=[_seq_block("b-0", spec_old)])
    changed = update_spec_block(doc, "b-0", spec_new)
    assert changed is True
    assert doc.blocks[0]["spec"] == spec_new


def test_update_spec_block_no_op_when_equivalent():
    spec = {"actors": [{"id": "a", "label": "A"}], "steps": []}
    doc = BlocksDoc(response_id="r-1", title="t",
                    blocks=[_seq_block("b-0", spec)])
    # Reordered keys must still hash equal — canonical JSON.
    equivalent = {"steps": [], "actors": [{"label": "A", "id": "a"}]}
    changed = update_spec_block(doc, "b-0", equivalent)
    assert changed is False


def test_update_spec_block_unknown_id_raises():
    doc = BlocksDoc(response_id="r-1", title="t", blocks=[])
    with pytest.raises(KeyError):
        update_spec_block(doc, "b-99", {})


def test_next_step_id_empty_spec():
    assert next_step_id({"steps": []}) == "s1"
    assert next_step_id({}) == "s1"


def test_next_step_id_never_reuses():
    spec = {"steps": [{"id": "s1"}, {"id": "s3"}, {"id": "s4"}]}
    assert next_step_id(spec) == "s2"


def test_next_step_id_handles_non_numeric():
    spec = {"steps": [{"id": "s1"}, {"id": "custom"}, {"id": "s2"}]}
    assert next_step_id(spec) == "s3"


def test_load_includes_glossary(tmp_path):
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps({
        "response_id": "r-1", "title": "t",
        "blocks": [{"id": "b-0", "markdown": "hi", "version": 1}],
        "glossary": [
            {"term": "OnboardingOrchestrator",
             "definition": "Internal service coordinating new-user signup.",
             "role": "Upstream that emits the payload too early."},
        ],
    }))
    doc = load(path)
    assert doc.glossary == [
        {"term": "OnboardingOrchestrator",
         "definition": "Internal service coordinating new-user signup.",
         "role": "Upstream that emits the payload too early."},
    ]


def test_load_missing_glossary_defaults_to_empty(tmp_path):
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps({"blocks": [{"id": "section-1", "markdown": "x"}]}))
    assert load(path).glossary == []


def test_save_round_trips_glossary(tmp_path):
    path = tmp_path / "blocks.json"
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[{"id": "b-0", "markdown": "hi", "version": 1}],
        glossary=[{"term": "Foo", "definition": "a foo", "role": "the bar"}],
    )
    save_atomic(path, doc)
    raw = json.loads(path.read_text())
    assert raw["glossary"] == [{"term": "Foo", "definition": "a foo", "role": "the bar"}]
    doc2 = load(path)
    assert doc2.glossary == doc.glossary


def test_save_omits_glossary_key_when_empty(tmp_path):
    path = tmp_path / "blocks.json"
    doc = BlocksDoc(response_id="r-1", title="t",
                    blocks=[{"id": "b-0", "markdown": "hi", "version": 1}])
    save_atomic(path, doc)
    raw = json.loads(path.read_text())
    assert "glossary" not in raw


def test_drop_unused_terms_removes_orphan_entries():
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[
            {"id": "b-0", "markdown": "Use OnboardingOrchestrator here.", "version": 1},
        ],
        glossary=[
            {"term": "OnboardingOrchestrator", "definition": "...", "role": "..."},
            {"term": "InsightsAggregator", "definition": "...", "role": "..."},  # orphan
        ],
    )
    changed = drop_unused_terms(doc)
    assert changed is True
    assert [g["term"] for g in doc.glossary] == ["OnboardingOrchestrator"]


def test_drop_unused_terms_no_op_when_all_referenced():
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[{"id": "b-0", "markdown": "Foo and Bar.", "version": 1}],
        glossary=[
            {"term": "Foo", "definition": "...", "role": "..."},
            {"term": "Bar", "definition": "...", "role": "..."},
        ],
    )
    changed = drop_unused_terms(doc)
    assert changed is False
    assert len(doc.glossary) == 2


def test_drop_unused_terms_case_sensitive():
    # "foo" lowercase should NOT match the entry for "Foo".
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[{"id": "b-0", "markdown": "the foo bar", "version": 1}],
        glossary=[{"term": "Foo", "definition": "...", "role": "..."}],
    )
    changed = drop_unused_terms(doc)
    assert changed is True
    assert doc.glossary == []


def test_drop_unused_terms_whole_word_only():
    # "Aggregator" should NOT match inside "Aggregators".
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[{"id": "b-0", "markdown": "We have many Aggregators here.", "version": 1}],
        glossary=[{"term": "Aggregator", "definition": "...", "role": "..."}],
    )
    changed = drop_unused_terms(doc)
    assert changed is True
    assert doc.glossary == []


def test_drop_unused_terms_scans_all_blocks():
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[
            {"id": "b-0", "markdown": "intro", "version": 1},
            {"id": "b-1", "markdown": "see Foo for details", "version": 1},
        ],
        glossary=[{"term": "Foo", "definition": "...", "role": "..."}],
    )
    changed = drop_unused_terms(doc)
    assert changed is False
    assert len(doc.glossary) == 1


def test_drop_unused_terms_with_no_blocks_drops_all_entries():
    # Mode D may invoke this before any blocks are populated. Confirm the
    # function returns True and clears the glossary instead of crashing.
    doc = BlocksDoc(
        response_id="r-1", title="t",
        blocks=[],
        glossary=[{"term": "Foo", "definition": "...", "role": "..."}],
    )
    changed = drop_unused_terms(doc)
    assert changed is True
    assert doc.glossary == []


from skills.annotate.blocks import (
    choice_option_ids, validate_choice_selection, convert_block_to_markdown,
)


def _choice_spec(multi=False):
    return {
        "question": "Pick one",
        "multiSelect": multi,
        "options": [
            {"id": "o1", "label": "A"},
            {"id": "o2", "label": "B"},
            {"id": "o3", "label": "C"},
        ],
    }


def test_choice_option_ids_lists_ids_in_order():
    assert choice_option_ids(_choice_spec()) == ["o1", "o2", "o3"]


def test_choice_option_ids_empty_for_no_options():
    assert choice_option_ids({}) == []


def test_validate_single_select_accepts_one_known_id():
    assert validate_choice_selection(_choice_spec(), ["o2"]) is None


def test_validate_single_select_rejects_empty():
    err = validate_choice_selection(_choice_spec(), [])
    assert err is not None and "empty" in err.lower()


def test_validate_single_select_rejects_two_picks():
    err = validate_choice_selection(_choice_spec(multi=False), ["o1", "o2"])
    assert err is not None and "one" in err.lower()


def test_validate_rejects_unknown_id():
    err = validate_choice_selection(_choice_spec(), ["o9"])
    assert err is not None and "option" in err.lower()


def test_validate_rejects_non_list():
    err = validate_choice_selection(_choice_spec(), "o1")
    assert err is not None


def test_validate_multi_select_accepts_several():
    assert validate_choice_selection(_choice_spec(multi=True), ["o1", "o3"]) is None


def test_validate_multi_select_rejects_empty():
    err = validate_choice_selection(_choice_spec(multi=True), [])
    assert err is not None and "empty" in err.lower()


def test_validate_choice_empty_selection_with_note_is_valid():
    assert validate_choice_selection(_choice_spec(), [], has_text=True) is None


def test_validate_choice_empty_selection_without_note_still_invalid():
    err = validate_choice_selection(_choice_spec(), [], has_text=False)
    assert err is not None


def test_validate_choice_note_does_not_excuse_unknown_ids():
    err = validate_choice_selection(_choice_spec(), ["o9"], has_text=True)
    assert "o9" in err


def test_validate_choice_note_does_not_excuse_two_picks_on_single_select():
    err = validate_choice_selection(_choice_spec(multi=False), ["o1", "o2"], has_text=True)
    assert err is not None


def test_convert_block_to_markdown_flips_kind_and_drops_spec():
    doc = BlocksDoc(blocks=[
        {"id": "section-1", "kind": "choice", "spec": _choice_spec()},
    ])
    changed = convert_block_to_markdown(doc, "section-1", "Decision: A.")
    assert changed is True
    blk = doc.blocks[0]
    assert blk.get("kind", "markdown") == "markdown"
    assert blk["markdown"] == "Decision: A."
    assert "spec" not in blk


def test_convert_block_to_markdown_is_noop_when_already_equal():
    doc = BlocksDoc(blocks=[
        {"id": "section-1", "markdown": "Decision: A."},
    ])
    assert convert_block_to_markdown(doc, "section-1", "Decision: A.") is False


def test_remove_block_removes_present_block():
    doc = BlocksDoc(blocks=[
        {"id": "section-1", "markdown": "a"},
        {"id": "section-2", "markdown": "b"},
        {"id": "section-3", "markdown": "c"},
    ])
    assert remove_block(doc, "section-2") is True
    assert [b["id"] for b in doc.blocks] == ["section-1", "section-3"]


def test_remove_block_absent_id_is_noop():
    doc = BlocksDoc(blocks=[{"id": "section-1", "markdown": "a"}])
    assert remove_block(doc, "section-9") is False
    assert [b["id"] for b in doc.blocks] == ["section-1"]


def test_remove_block_removes_non_markdown_block():
    doc = BlocksDoc(blocks=[
        {"id": "section-1", "markdown": "a"},
        {"id": "section-2", "kind": "choice", "spec": {"question": "q", "options": []}},
    ])
    assert remove_block(doc, "section-2") is True
    assert [b["id"] for b in doc.blocks] == ["section-1"]


def test_a_block_with_content_under_the_wrong_key_is_refused(tmp_path):
    """Prose in `text` instead of `markdown` rendered as nothing and the push
    reported success — two pages shipped with every paragraph missing."""
    import json

    from skills.annotate.blocks import BlockContentError, load

    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": "section-1", "text": "prose that would vanish"},
        {"id": "section-2", "kind": "flowchart", "spec": {"nodes": [], "edges": []}},
    ]}))
    with pytest.raises(BlockContentError) as e:
        load(p)
    assert "section-1" in str(e.value)
    assert "markdown" in str(e.value)


def test_a_genuinely_empty_block_is_still_dropped_quietly(tmp_path):
    import json

    from skills.annotate.blocks import load

    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": "section-1", "markdown": "   "},
        {"id": "section-2", "markdown": "real"},
    ]}))
    doc = load(p)
    assert [b["id"] for b in doc.blocks] == ["section-2"]


def test_a_retired_kind_is_refused_with_a_pointer(tmp_path):
    """`diagram` fell through to the markdown branch once mermaid.py was
    removed, so a Mermaid block rendered as an empty card and the push said
    nothing."""
    import json

    from skills.annotate.blocks import UnknownBlockKindError, load

    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": "section-1", "kind": "diagram",
         "spec": {"type": "state", "source": "stateDiagram-v2"}}]}))
    with pytest.raises(UnknownBlockKindError) as e:
        load(p)
    assert "diagram" in str(e.value) and "flowchart" in str(e.value)


def test_an_unknown_kind_is_refused(tmp_path):
    import json

    from skills.annotate.blocks import UnknownBlockKindError, load

    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": "section-1", "kind": "flowchrat", "spec": {}}]}))
    with pytest.raises(UnknownBlockKindError, match="flowchrat"):
        load(p)


def test_every_known_kind_loads(tmp_path):
    import json

    from skills.annotate.blocks import BLOCK_KINDS, load

    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": f"section-{i}", "kind": k, "spec": {}, "markdown": "x"}
        for i, k in enumerate(sorted(BLOCK_KINDS))]}))
    assert len(load(p).blocks) == len(BLOCK_KINDS)


def _choice_file(tmp_path, **spec):
    base = {"question": "Which?",
            "options": [{"id": "o1", "label": "A"}, {"id": "o2", "label": "B"}]}
    base.update(spec)
    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [
        {"id": "section-7", "kind": "choice", "spec": base}]}))
    return p


@pytest.mark.parametrize("group", [3, "", "   ", "x" * 81, None])
def test_a_malformed_choice_group_is_refused(tmp_path, group):
    from skills.annotate.blocks import ChoiceSpecError
    with pytest.raises(ChoiceSpecError) as e:
        load(_choice_file(tmp_path, group=group))
    assert "section-7" in str(e.value)
    assert "group" in str(e.value)


def test_a_group_of_exactly_80_characters_loads(tmp_path):
    doc = load(_choice_file(tmp_path, group="x" * 80))
    assert doc.blocks[0]["spec"]["group"] == "x" * 80


def test_option_markdown_that_is_not_a_string_is_refused(tmp_path):
    from skills.annotate.blocks import ChoiceSpecError
    opts = [{"id": "o1", "label": "A", "markdown": ["not", "a", "string"]},
            {"id": "o2", "label": "B"}]
    with pytest.raises(ChoiceSpecError) as e:
        load(_choice_file(tmp_path, options=opts))
    assert "section-7" in str(e.value)
    assert "o1" in str(e.value)


def test_rich_options_and_a_group_load(tmp_path):
    opts = [{"id": "o1", "label": "A", "markdown": "```java\nclass A {}\n```"},
            {"id": "o2", "label": "B", "markdown": ""}]
    doc = load(_choice_file(tmp_path, group="Decisions", options=opts))
    assert doc.blocks[0]["spec"]["options"][0]["markdown"].startswith("```java")


def test_a_choice_without_the_new_fields_loads_as_before(tmp_path):
    doc = load(_choice_file(tmp_path))
    assert "group" not in doc.blocks[0]["spec"]


# ── `mine`: the words the reader wrote, which Claude keeps verbatim ─────────

MINE = [{"selected_text": "short", "prefix": "Paragraph one of block 1, ",
         "suffix": " to scroll past."}]


def test_render_block_passes_mine_through():
    from skills.annotate.render import render_block
    out = render_block({"id": "section-1", "markdown": "a short text", "mine": MINE})
    assert out["mine"] == MINE


def test_render_block_leaves_out_an_empty_or_malformed_mine():
    from skills.annotate.render import render_block
    for junk in ([], None, "short", {"selected_text": "x"}):
        out = render_block({"id": "section-1", "markdown": "a short text", "mine": junk})
        assert "mine" not in out, f"{junk!r} reached the client"


def test_pull_keeps_mine():
    from skills.annotate.pull import AUTHORED, block_from_body
    assert "mine" in AUTHORED
    blk = block_from_body({"id": "section-1", "kind": "markdown", "markdown": "a short text",
                           "mine": MINE})
    assert blk["mine"] == MINE


def test_save_atomic_keeps_mine(tmp_path):
    path = tmp_path / "blocks.json"
    save_atomic(path, BlocksDoc(response_id="r", title="t", blocks=[
        {"id": "section-1", "markdown": "a short text", "mine": MINE}]))
    assert json.loads(path.read_text())["blocks"][0]["mine"] == MINE
    assert load(path).blocks[0]["mine"] == MINE
