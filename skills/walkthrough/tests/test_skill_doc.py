from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"
REFS = SKILL.parent / "references"


def _all_docs() -> str:
    """SKILL.md plus every reference it routes to — the skill's whole contract."""
    return "\n".join(p.read_text() for p in [SKILL, *sorted(REFS.glob("*.md"))])

REQUIRED_SECTIONS = [
    "## Invocation",
    "## On every invocation: the daemon must be running",
    "## Running the plugin's own code",
    "## Generate the steps",
    "## Validate and push the document",
    "## Arm the watcher",
    "## Handling a watcher event",
    "## Edge cases",
    "references/generation-contract.md",
    "references/handling-events.md",
]

REFERENCE_SECTIONS = {
    "generation-contract.md": ["# walkthrough — generation contract"],
    "handling-events.md": ["## `WEBCOMPANION_EVENT`", "## Response style guide"],
}


def test_frontmatter_declares_name_and_description():
    text = SKILL.read_text()
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert "name: walkthrough" in frontmatter
    assert "description:" in frontmatter


def test_required_sections_present():
    text = SKILL.read_text()
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert missing == [], f"SKILL.md missing sections: {missing}"


def test_reference_sections_present():
    for name, sections in REFERENCE_SECTIONS.items():
        text = (REFS / name).read_text()
        missing = [s for s in sections if s not in text]
        assert missing == [], f"references/{name} missing sections: {missing}"


def test_generation_contract_states_the_hard_rules():
    text = (REFS / "generation-contract.md").read_text()
    for rule in ["5–12 steps", "snippet", "execution order", "edit-site", "cross-block"]:
        assert rule.lower() in text.lower(), f"generation contract missing rule: {rule}"


def test_documents_step_anchor_form():
    assert "step:<id>" in _all_docs()
