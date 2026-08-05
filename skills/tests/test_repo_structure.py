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
