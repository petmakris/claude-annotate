"""Publishing is only reachable if the skill can actually make the calls.

annotate's allowed-tools is Bash/Read/Write. Every Confluence call in
references/publishing.md is an MCP tool, so without them in the frontmatter
the procedure documents something the skill is not permitted to do."""
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
PUBLISHING = SKILL_DIR / "references" / "publishing.md"


def test_the_reference_exists_and_skill_md_points_at_it():
    assert PUBLISHING.exists()
    assert "references/publishing.md" in SKILL_MD.read_text()


def test_the_command_is_named_in_the_phase_map():
    assert "/annotate publish" in SKILL_MD.read_text()


# Two kinds of Confluence call, permitted two different ways. A primary tool
# is named in allowed-tools directly. An attachment operation is not a tool at
# all -- it is a name handed to executeWrite/executeRead -- so what has to be
# permitted is the carrier, not the operation.
PRIMARY = ("createConfluencePage", "updateConfluencePage", "getConfluenceSpaces")
VIA_EXECUTE = {
    "createConfluenceAttachment": "executeWrite",
    "listConfluenceAttachments": "executeRead",
    "downloadConfluenceAttachment": "executeRead",
}


def test_allowed_tools_covers_every_confluence_call_the_reference_makes():
    frontmatter = SKILL_MD.read_text().split("---", 2)[1]
    text = PUBLISHING.read_text()

    used = [t for t in PRIMARY if re.search(r"\b%s\b" % t, text)]
    assert used, "the reference names no primary Confluence tool"
    missing = [t for t in used if t not in frontmatter]
    assert not missing, (
        "references/publishing.md calls %s, which annotate's allowed-tools "
        "does not permit" % ", ".join(missing))

    for op, carrier in VIA_EXECUTE.items():
        if re.search(r"\b%s\b" % op, text):
            assert carrier in frontmatter, (
                "references/publishing.md runs %s, which is an operation name "
                "passed to %s -- and allowed-tools does not permit %s"
                % (op, carrier, carrier))


def test_the_procedure_stops_on_a_refusal_before_touching_confluence():
    text = PUBLISHING.read_text()
    assert "proceed" in text
    # The order on the page is the order of operations; resolving must come
    # before the first write.
    assert text.index("prepare") < text.index("createConfluencePage")


def test_the_procedure_finalizes_before_updating_the_body():
    text = PUBLISHING.read_text()
    assert text.index("finalize") < text.index("updateConfluencePage")
