"""Guards for repository-level structure that no single skill owns.

These assert the things that break silently: a skill probing for a
marketplace name that no longer exists, a plugin manifest that stops
matching the skills on disk, a vendoring artifact left behind.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def _marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


# Each skill embeds a shell probe that resolves its own plugin root. The
# python inside it opens with this line.
PROBE_RE = re.compile(r'NAME, MARKER = "([^"]+)", "([^"]+)"')
# ...and reports failure with this one.
ECHO_RE = re.compile(r'echo "([^"]+): plugin root not found"')


def _skill_docs() -> list[Path]:
    return sorted(ROOT.glob("skills/**/*.md"))


def test_every_probe_asks_for_the_real_marketplace_name():
    # known_marketplaces.json is keyed by marketplace name. A skill that asks
    # for any other name cannot find itself once installed.
    expected = _marketplace()["name"]
    found = [
        (str(doc.relative_to(ROOT)), name)
        for doc in _skill_docs()
        for name, _ in PROBE_RE.findall(doc.read_text(encoding="utf-8"))
    ]
    assert found, "no plugin-root probe found — did the probe format change?"
    wrong = [(doc, name) for doc, name in found if name != expected]
    assert not wrong, f"probes must name the marketplace {expected!r}: {wrong}"


def test_every_probe_marker_file_exists():
    # The probe accepts a candidate root only if MARKER exists inside it, so a
    # stale marker path makes the skill unfindable even with the right name.
    missing = [
        (str(doc.relative_to(ROOT)), marker)
        for doc in _skill_docs()
        for _, marker in PROBE_RE.findall(doc.read_text(encoding="utf-8"))
        if not (ROOT / marker).is_file()
    ]
    assert not missing, f"probe markers do not exist: {missing}"


def test_probe_failure_messages_name_the_real_marketplace():
    expected = _marketplace()["name"]
    wrong = [
        (str(doc.relative_to(ROOT)), name)
        for doc in _skill_docs()
        for name in ECHO_RE.findall(doc.read_text(encoding="utf-8"))
        if name != expected
    ]
    assert not wrong, f"failure messages must say {expected!r}: {wrong}"


def test_marketplace_publishes_two_plugins_from_one_root():
    plugins = _marketplace()["plugins"]
    assert [p["name"] for p in plugins] == ["claude-annotate", "claude-ide-review"]
    for plugin in plugins:
        # One root, shared. The skills array is what separates the plugins;
        # a subdirectory source would force a second copy of _shared.
        assert plugin["source"] == "./", plugin["name"]
        assert plugin["strict"] is False, plugin["name"]
        assert plugin["skills"], plugin["name"]
        assert plugin["description"], plugin["name"]


# Skills deliberately claimed by BOTH plugins. The list is not a loophole —
# anything not named here is still a duplicate-claim bug.
#
# annotate-doctor: every guard block and both ensure_server.sh failure
# messages tell the user to run /annotate-doctor. Shipping it only with
# claude-annotate meant a claude-ide-review-only user was pointed at a command
# their install does not have. One diagnostic, both plugins.
SHARED_SKILLS = {"./skills/annotate-doctor"}


def test_plugin_skill_lists_cover_the_skills_tree():
    listed = [s for p in _marketplace()["plugins"] for s in p["skills"]]
    doubled = {s for s in listed if listed.count(s) > 1}
    unexpected = doubled - SHARED_SKILLS
    assert not unexpected, f"a skill is claimed twice: {sorted(unexpected)}"
    stale = SHARED_SKILLS - doubled
    assert not stale, (
        f"declared shared but claimed by one plugin only: {sorted(stale)} — "
        "either share it or drop it from SHARED_SKILLS"
    )
    # A skill directory is one with a SKILL.md; _shared and tests have none.
    on_disk = {
        f"./skills/{d.name}"
        for d in (ROOT / "skills").iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    }
    assert set(listed) == on_disk


def test_no_root_plugin_json():
    # Two plugins cannot share one plugin.json; their metadata lives in the
    # marketplace entries instead.
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()


BANNER = "GENERATED FILE"


def test_no_vendoring_artifacts():
    shared = ROOT / "skills" / "_shared"
    assert not (shared / "VENDOR.txt").exists()
    assert not (shared / "VENDOR.sha256").exists()


def test_engine_is_not_marked_generated():
    # The engine is edited here now. A "DO NOT EDIT" banner would send the
    # next reader looking for an upstream that no longer exists.
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "skills" / "_shared").rglob("*")
        if p.suffix in {".py", ".sh"} and BANNER in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"still marked generated: {offenders}"
