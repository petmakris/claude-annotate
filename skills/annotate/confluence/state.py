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

from skills.annotate.atomic import write_text_atomic

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


def main(argv=None) -> int:
    """`claude-annotate confluence.state --workspace <dir> key=value ...`

    publishing.md used to record the page with a `python3 -c` snippet that
    needed the plugin root on PYTHONPATH; this is that snippet as a command."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(prog="skills.annotate.confluence.state")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("fields", nargs="+", metavar="key=value")
    a = ap.parse_args(argv)
    bad = [f for f in a.fields if "=" not in f or not f.split("=", 1)[0]]
    if bad:
        print("confluence.state: expected key=value, got %s" % ", ".join(bad),
              file=sys.stderr)
        return 2
    save(Path(a.workspace), **dict(f.split("=", 1) for f in a.fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
