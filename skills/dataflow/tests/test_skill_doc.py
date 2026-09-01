from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"

REQUIRED_SECTIONS = [
    "## Invocation",
    "## On every invocation: the daemon must be running",
    "## Resolve the plugin root",
    "## Trace the code",
    "## Write the document",
    "## Generation contract",
    "## Arm the watcher",
    "## Handling a watcher event",
    "## Response style guide",
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
    assert "node:<id>" in SKILL.read_text()


def test_states_that_cwd_must_be_the_repository_root():
    # Every node path resolves against the session cwd; get this wrong and
    # /api/open refuses every node with "not a file inside this workspace".
    assert "must be the repository root" in SKILL.read_text()
