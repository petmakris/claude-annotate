"""Every per-skill copy of a shared browser asset is byte-identical to its one
canonical source in skills/_shared/static/.

The daemon serves a session's page from exactly one directory — the skill's
own static/ — so a file two skills both need has to exist in both. That is
how markdown-it ended up in three places, the fonts in three and core.css in
three that had quietly drifted apart. The copies stay; what this test removes
is the drift: there is one file to edit, and a copy that differs from it fails
here with the command that fixes it.

Two kinds of difference are allowed, and both are listed below rather than
guessed at:

- a skill that ships its OWN file under a shared name, deliberately diverged
  (annotate's core.css lists its divergences in its own header) — that file is
  annotate's, not a copy, and is not compared;
- nothing else. A copy that needs a transform (deck's core.css used to carry
  different font URLs) is fixed at the source instead: the canonical file
  uses the relative URLs every copy needs.
"""
from __future__ import annotations

from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1]
CANONICAL = SKILLS / "_shared" / "static"

# Every static directory the daemon serves a page from.
STATIC_DIRS = sorted(p for p in SKILLS.glob("*/static") if p != CANONICAL) + \
    sorted(SKILLS.glob("*/webcompanion/static"))

# Which skill is expected to carry which canonical file. A copy that is
# deleted (or never made) fails as surely as one that drifts.
EXPECTED = {
    "core.css": ["deck"],
    "markdown-it.min.js": ["annotate", "dataflow"],
    "fonts/BricolageGrotesque-Variable.woff2": ["annotate", "deck"],
    "fonts/BRICOLAGE_LICENSE.txt": ["annotate", "deck"],
    "fonts/MonaspaceRadon-Regular.woff2": ["annotate", "deck"],
    "fonts/MONASPACE_LICENSE.txt": ["annotate", "deck"],
    "wc-threads.js": ["dataflow"],
    "wc-boot.js": ["annotate", "dataflow", "deck"],
    "wc-open.js": ["annotate", "dataflow", "specimen"],
}

# A skill's own file that shares a canonical name on purpose.
OWN = {
    ("annotate", "core.css"): "annotate's deliberately diverged core.css (see its header)",
}


def _skill_of(static_dir: Path) -> str:
    return static_dir.relative_to(SKILLS).parts[0]


def _canonical_files():
    return sorted(p.relative_to(CANONICAL).as_posix() for p in CANONICAL.rglob("*") if p.is_file())


def test_the_canonical_directory_holds_every_shared_asset():
    assert sorted(EXPECTED) == _canonical_files(), (
        "skills/_shared/static/ and this test's EXPECTED table disagree — a shared "
        "asset was added or removed without saying which skills carry it")


def test_every_expected_copy_exists():
    missing = []
    for rel, skills in EXPECTED.items():
        for skill in skills:
            dirs = [d for d in STATIC_DIRS if _skill_of(d) == skill]
            if not any((d / rel).is_file() for d in dirs):
                missing.append(f"{skill}: {rel}")
    assert not missing, "a shared asset is missing from a skill that uses it:\n  " + "\n  ".join(missing)


def test_every_copy_is_byte_identical_to_its_canonical_source():
    drifted = []
    for rel in _canonical_files():
        want = (CANONICAL / rel).read_bytes()
        for d in STATIC_DIRS:
            copy = d / rel
            if not copy.is_file() or (_skill_of(d), rel) in OWN:
                continue
            if copy.read_bytes() != want:
                drifted.append(f"cp skills/_shared/static/{rel} {copy.relative_to(SKILLS.parent)}")
    assert not drifted, (
        "a per-skill copy differs from its canonical source in skills/_shared/static/. "
        "Edit the canonical file, then copy it over:\n  " + "\n  ".join(drifted))


def test_the_retired_shared_static_directory_is_gone():
    old = SKILLS / "_shared" / "web_companion" / "static"
    assert not old.exists() or not any(old.iterdir()), (
        "skills/_shared/web_companion/static/ is back; shared assets live in skills/_shared/static/")
