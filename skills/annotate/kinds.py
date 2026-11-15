"""The block kinds, read from the one registry (static/block-kinds.json).

The page reads the same file (static/kinds.js), so a kind and its traits are
declared once. Nothing else may list kinds by hand: the guard in
tests/test_kinds_registry.py fails on a file that does.
"""
from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent / "static" / "block-kinds.json"

_data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

# {kind: {trait: value}}
KINDS: dict[str, dict] = _data["kinds"]
# {kind: {"message": str, ...}} — kinds that were removed; a spec naming one
# fails loudly instead of rendering as an empty card.
RETIRED: dict[str, dict] = _data["retired"]

# Every kind has the traits of `markdown`; `code_message` (with code: refused)
# `painter` (a kind the page paints from its spec, spec-parts.js) and
# `deprecated` (a note: new pages use another kind) are the optional ones.
TRAITS = frozenset(KINDS["markdown"])
OPTIONAL_TRAITS = frozenset({"code_message", "painter", "deprecated"})


def trait(kind: str, name: str):
    """A kind's trait; an unknown kind has none (None)."""
    return KINDS.get(kind, {}).get(name)


def with_trait(name: str) -> tuple[str, ...]:
    """Every kind whose trait `name` is true, in registry order."""
    return tuple(k for k, t in KINDS.items() if t.get(name))
