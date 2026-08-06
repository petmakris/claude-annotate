"""Structural guards for the local audit suite under .claude/skills/.

The suite is prose, not code, so its failure modes are structural: the
umbrella dispatching a sub-audit that does not exist, a sub-audit nobody
dispatches, or a SKILL.md missing the frontmatter that makes it invocable.
Each of those breaks the suite silently — /audit still runs, it just stops
covering something.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / ".claude" / "skills"

# Every sub-audit must carry these. They are the parts that make a report
# actionable rather than a wall of observations.
REQUIRED_SECTIONS = (
    "## The audit contract",
    "## Output template",
    "## After delivering the report",
    "## Anti-patterns",
)


def _audit_dirs() -> list[Path]:
    return sorted(p for p in SUITE.glob("audit*") if (p / "SKILL.md").is_file())


def _frontmatter(md: Path) -> dict[str, str]:
    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{md} has no frontmatter"
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def test_suite_exists():
    assert _audit_dirs(), "no audit skills found under .claude/skills/"


def test_every_audit_is_user_invocable():
    bad = [
        d.name
        for d in _audit_dirs()
        if _frontmatter(d / "SKILL.md").get("user-invocable") != "true"
    ]
    assert not bad, f"audits must be user-invocable: {bad}"


def test_frontmatter_name_matches_directory():
    bad = [
        (d.name, _frontmatter(d / "SKILL.md").get("name"))
        for d in _audit_dirs()
        if _frontmatter(d / "SKILL.md").get("name") != d.name
    ]
    assert not bad, f"frontmatter name must equal directory name: {bad}"


def test_umbrella_dispatch_table_matches_disk():
    # The umbrella's whole job is dispatch. A sub-audit it forgets is a
    # silent hole in the full sweep; one it names but that does not exist
    # is a broken run.
    #
    # Scoped to the `## Sub-audits` table in the body, not the whole file.
    # The frontmatter `description` also lists every sub-audit by
    # convention, but that convention has no enforcement of its own — if
    # this test scanned the whole file, a body that forgot every sub-audit
    # (dispatch table, Sub-audits section, Workflow, all of it) would still
    # pass as long as the frontmatter still named them, which defeats the
    # point of a sync test. Only the table counts.
    umbrella = SUITE / "audit" / "SKILL.md"
    text = umbrella.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{umbrella} has no frontmatter"
    body = text.split("---\n", 2)[2]
    assert "## Sub-audits" in body, f"{umbrella} has no ## Sub-audits section"
    table = body.split("## Sub-audits", 1)[1]
    if "## Workflow" in table:
        table = table.split("## Workflow", 1)[0]
    named = set(re.findall(r"`/(audit-[a-z-]+)`", table))
    on_disk = {d.name for d in _audit_dirs() if d.name != "audit"}
    assert named == on_disk, (
        f"umbrella dispatches {sorted(named)} but disk has {sorted(on_disk)}"
    )


def test_sub_audits_carry_the_required_sections():
    missing = []
    for d in _audit_dirs():
        if d.name == "audit":
            continue
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        missing += [f"{d.name} -> {s}" for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, f"sub-audits missing required sections: {missing}"
