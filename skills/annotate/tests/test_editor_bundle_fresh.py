# skills/annotate/tests/test_editor_bundle_fresh.py
"""The committed editor bundle was built from the committed sources. The
bundle's first line carries the hash build.mjs computed; this recomputes it
the same way (sha256 over src/*.ts sorted by name, then package.json), so a
source edit without a rebuild fails here. Needs no node."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ANNOTATE = Path(__file__).resolve().parents[1]
EDITOR = ANNOTATE / "editor"
BUNDLE = ANNOTATE / "static" / "vendor" / "editor.min.js"


def _source_hash() -> str:
    h = hashlib.sha256()
    for f in sorted((EDITOR / "src").glob("*.ts"), key=lambda p: p.name):
        h.update(f.read_bytes())
    h.update((EDITOR / "package.json").read_bytes())
    return h.hexdigest()


def test_the_editor_bundle_matches_its_sources():
    assert BUNDLE.exists(), "editor bundle is stale: run node skills/annotate/editor/build.mjs"
    first = BUNDLE.read_bytes().split(b"\n", 1)[0].decode()
    m = re.fullmatch(r"/\* annotate-editor ([0-9a-f]{64}) \*/", first)
    assert m and m.group(1) == _source_hash(), "editor bundle is stale: run node skills/annotate/editor/build.mjs"


def test_the_editor_bundle_has_no_raw_nul_byte():
    assert b"\x00" not in BUNDLE.read_bytes()


def test_the_codemirror_license_ships_beside_the_bundle():
    lic = (BUNDLE.parent / "editor.LICENSE").read_text()
    assert "MIT License" in lic and "Marijn Haverbeke" in lic
