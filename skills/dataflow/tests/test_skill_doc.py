from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"
REFS = SKILL.parent / "references"
FIELD_MODE = REFS / "field-mode.md"

REQUIRED_SECTIONS = [
    "## Invocation",
    "## On every invocation: the daemon must be running",
    "## Running the plugin's own code",
    "## Trace the code",
    "## Write the document",
    "## Generation contract",
    "## Arm the watcher",
    "## Handling a watcher event",
    "references/handling-events.md",
    "references/field-mode.md",
]


def test_frontmatter_declares_name_and_description():
    text = SKILL.read_text()
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert "name: dataflow" in frontmatter
    assert "description:" in frontmatter


def test_required_sections_present():
    text = SKILL.read_text()
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert missing == [], f"SKILL.md missing sections: {missing}"


def test_generation_contract_states_the_hard_rules():
    text = SKILL.read_text().lower()
    # Each of these is a rule that, when dropped, produced a diagram the reader
    # could not act on: a trace that stopped at the repository, a missing
    # framework mapping, a guessed line number.
    for rule in ["6–14 nodes", "never guess a line number", "implicit",
                 "request order", "cross-node re-pass", "never end at a repository"]:
        assert rule in text, f"generation contract missing rule: {rule}"


def test_documents_node_anchor_form():
    assert "node:<id>" in (REFS / "handling-events.md").read_text()


def test_event_handling_carries_the_response_style():
    assert "## Response style guide" in (REFS / "handling-events.md").read_text()


def test_states_that_cwd_must_be_the_repository_root():
    # Every node path resolves against the session cwd; get this wrong and
    # /api/open refuses every node with "not a file inside this workspace".
    assert "must be the repository root" in SKILL.read_text()


def test_field_mode_requires_the_checked_render():
    field = FIELD_MODE.read_text()
    for must in ["--check", "behind_card", "label_overlaps", "source_slack", "improvable_swaps", "loose_sources",
                 '"lane"', '"rows": "follow"', "three rounds"]:
        assert must in field, must


def test_field_spec_format_places_nothing():
    # Columns and gap widths come from the wires: the format an author copies must not
    # offer the knobs that used to place cards.
    field = FIELD_MODE.read_text()
    block = field[field.index("## Spec format"):]
    block = block[block.index("```jsonc"):]
    block = block[:block.index("```", 3)]
    assert '"slot"' not in block and '"gaps"' not in block
    assert "left to right" not in field
