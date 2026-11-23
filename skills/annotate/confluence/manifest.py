"""`annotate-source.json` — what makes a published page regenerable.

This file is attached to the Confluence page, which is the point: a refresh
needs the document and its anchors, and nothing guarantees the machine that
published it still exists. Confluence content properties would be the natural
home, but no available MCP tool exposes them, so an attachment is the storage.

Blocks are stored VERBATIM, rendered SVG included. A refresh re-renders the
pictures from those bytes instead of re-running the layout engine, so a change
to the renderer cannot silently redraw a published page.
"""
from __future__ import annotations

import json
from typing import Any

MANIFEST_VERSION = 1
MANIFEST_NAME = "annotate-source.json"


class ManifestError(ValueError):
    """A manifest this code cannot safely read."""


def build(*, response_id: str, title: str, slug: str,
          glossary: list[dict[str, Any]], blocks: list[dict[str, Any]],
          repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "response_id": response_id,
        "title": title,
        # The slug names the annotate session in the page's provenance line.
        # Without it a refresh republishes the page attributing it to no
        # session at all -- and the manifest is the only thing a refresh has.
        "slug": slug,
        "glossary": list(glossary),
        "repo": dict(repo),
        "blocks": list(blocks),
    }


def parse(raw: str) -> dict[str, Any]:
    """Read a manifest, refusing one this version cannot honour.

    A future manifest is refused rather than read on a best-effort basis: a
    field this code does not know about is a field it would silently drop from
    the page it regenerates.
    """
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ManifestError("not valid JSON: %s" % e) from None
    if not isinstance(out, dict):
        raise ManifestError("expected an object at the top level")
    version = out.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ManifestError(
            "manifest_version %r cannot be read by this version (expected %d)"
            % (version, MANIFEST_VERSION))
    for key in ("title", "slug", "blocks", "repo"):
        if key not in out:
            raise ManifestError("manifest is missing %r" % key)
    return out


def anchors_of(manifest: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every anchor in the document, paired with the block that carries it."""
    pairs: list[tuple[str, dict[str, Any]]] = []
    for blk in manifest.get("blocks") or []:
        for a in (blk.get("code") or []):
            pairs.append((blk.get("id", ""), a))
    return pairs
