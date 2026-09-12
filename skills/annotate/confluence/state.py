"""Which Confluence page a session publishes to.

Kept in the workspace so a second publish updates the page the author already
shared rather than minting a second one beside it — the same reason
`push.py` resolves a slug to a live session before creating one.

This is a convenience, not the source of truth: the page carries its own
manifest, so a refresh works even when this file is gone.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills._shared.web_companion.atomic import write_text_atomic

NAME = "confluence.json"


def _path(workspace: Path) -> Path:
    return Path(workspace) / NAME


def load(workspace: Path) -> dict[str, Any]:
    path = _path(workspace)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(workspace: Path, **fields: Any) -> dict[str, Any]:
    """Merge `fields` into the record. Merging, not replacing: a publish that
    only moves the commit forward must not drop the page id."""
    out = {**load(workspace), **{k: v for k, v in fields.items()
                                 if v is not None}}
    write_text_atomic(_path(workspace), json.dumps(out, indent=2))
    return out
