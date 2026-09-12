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
PRIMARY = ("createConfluencePage", "updateConfluencePage",
           "getConfluenceSpaces", "getAccessibleAtlassianResources")
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


def test_allowed_tools_uses_an_attested_yaml_form():
    """The harness's frontmatter reader is not strict YAML -- this file's own
    unquoted `description` fails `yaml.safe_load` and the skill still works
    -- so a form counts as safe here only because it is already attested in
    production, not because a strict parser happens to accept it. Only two
    shapes are attested: a block list of `  - item` lines (used throughout
    this repo), or a single-line comma-separated scalar (the form Anthropic's
    own shipped `code-review` plugin uses). A bracketed flow sequence has no
    precedent anywhere and is rejected here even though it is valid strict
    YAML -- if the real parser is line-oriented rather than YAML-aware, that
    form can silently read as an empty list.
    """
    lines = SKILL_MD.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("allowed-tools:"))
    rest = lines[start][len("allowed-tools:"):].strip()

    if rest:
        # Single-line scalar form: not a flow sequence, and no continuation
        # line indented under it.
        assert not rest.startswith("["), (
            "allowed-tools is a bracketed flow sequence -- no precedent in "
            "this repo or in ~/.claude/plugins/cache; use a block list or a "
            "single-line comma-separated scalar instead")
        nxt = lines[start + 1]
        assert nxt.strip() == "---" or not nxt.startswith(" "), (
            "allowed-tools scalar spans multiple lines: %r" % nxt)
    else:
        # Block list form: every following line up to the closing `---`
        # must be `  - item`.
        i = start + 1
        items = []
        while lines[i].strip() != "---":
            assert re.match(r"^  - \S", lines[i]), (
                "allowed-tools block list line %r is not `  - item`" % lines[i])
            items.append(lines[i])
            i += 1
        assert items, "allowed-tools: with no items"


# This repo ships as a plugin marketplace. One organisation's Atlassian site
# and space ids in a reference every installer reads are that organisation's
# identifiers shipped to everyone else.
_CLOUD_ID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_SPACE_ID = re.compile(r'spaceId: "\d+"')


def test_no_customer_identifiers_are_shipped_in_the_reference():
    text = PUBLISHING.read_text()
    assert not _CLOUD_ID.search(text), (
        "references/publishing.md hardcodes an Atlassian cloudId; use a "
        "<cloudId> placeholder and say how to obtain it")
    assert not _SPACE_ID.search(text), (
        "references/publishing.md hardcodes a spaceId; use a <spaceId> "
        "placeholder and say how to obtain it")


def test_the_reference_says_how_to_obtain_them():
    text = PUBLISHING.read_text()
    assert "getAccessibleAtlassianResources" in text
    assert "getConfluenceSpaces" in text
    assert "<cloudId>" in text and "<spaceId>" in text


def test_the_reference_says_finalize_exits_2_on_an_unfilled_placeholder():
    # The model reads this file as its only contract for the publish, and
    # exit 2 there means the body was NOT written.
    text = PUBLISHING.read_text()
    step = text[text.index("## Step 4"):]
    assert "exits 2" in step or "exit 2" in step
