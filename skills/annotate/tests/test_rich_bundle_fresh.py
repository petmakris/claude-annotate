# skills/annotate/tests/test_rich_bundle_fresh.py
"""The committed rich bundle was built from the committed sources. The
bundle's first line carries the hash build.mjs computed; this recomputes it
the same way (sha256 over rich/src/*.js sorted by name, then
package-lock.json), so a source edit without a rebuild fails here. Needs no
node."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ANNOTATE = Path(__file__).resolve().parents[1]
RICH = ANNOTATE / "rich"
BUNDLE = ANNOTATE / "static" / "vendor" / "rich.min.js"
STALE = "rich bundle is stale: run node skills/annotate/rich/build.mjs"


def _source_hash() -> str:
    h = hashlib.sha256()
    for f in sorted((RICH / "src").glob("*.js"), key=lambda p: p.name):
        h.update(f.read_bytes())
    h.update((RICH / "package-lock.json").read_bytes())
    return h.hexdigest()


def test_the_rich_bundle_matches_its_sources():
    assert BUNDLE.exists(), STALE
    first = BUNDLE.read_bytes().split(b"\n", 1)[0].decode()
    m = re.fullmatch(r"/\* annotate-rich ([0-9a-f]{64}) \*/", first)
    assert m and m.group(1) == _source_hash(), STALE


def test_the_rich_bundle_has_no_raw_nul_byte():
    assert b"\x00" not in BUNDLE.read_bytes()

