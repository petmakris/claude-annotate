"""Atomic file writes: safe under concurrent writers, the one copy every skill uses.

The naive `tmp = path.with_suffix(".tmp"); tmp.write_text(...); tmp.replace(path)`
pattern uses a FIXED temp filename, so two writers racing on the same target
truncate/interleave the same tmp file and one promotes garbage (or the second
`replace` hits FileNotFoundError after the first already renamed it). Using a
unique temp name per writer makes the rename genuinely atomic and last-writer-wins.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str, *, mode: int = 0o600, encoding: str = "utf-8") -> None:
    """Write `path` whole or not at all, under a temp name of its own in the same folder.

    The file ends up with permissions `mode`: owner-only by default (what `tempfile.mkstemp`
    makes), `0o644` for a file other users may read."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
