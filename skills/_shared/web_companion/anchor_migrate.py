"""Server-side port of the IDE plugin's AnchorResolver.

`ide-plugin/src/main/java/com/petros/ireview/AnchorResolver.java` re-locates
an annotation anchor against the live document the IDE has open, when the
recorded line no longer holds the recorded text (code moved above it). This
module is the exact same algorithm, ported so the server can do the same
re-location during a resync — for the case nobody has that file open in an
editor at all.

Kept pure and dependency-free (no I/O — callers supply `lines`) so both
implementations can be tested against one shared fixture
(`tests/anchor_migration_fixtures.json`, also read by
`ide-plugin/.../AnchorResolverTest.java`) without either drifting from the
other. See docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    EXACT = "EXACT"
    MOVED = "MOVED"
    STALE = "STALE"


@dataclass(frozen=True)
class Resolution:
    kind: Kind
    line: int  # 1-based for EXACT/MOVED, -1 for STALE


def locate(lines: list[str], recorded_line: int, anchor_text: str, k: int = 25) -> Resolution:
    """Re-locate `anchor_text`, last seen at `recorded_line` (1-based), in `lines`.

    Mirrors `AnchorResolver.resolve` exactly: an exact match at the recorded
    line wins outright without even considering the window; otherwise a
    +/-k line window search around the (clamped) recorded line must find
    EXACTLY ONE match to count as MOVED — zero or more than one is STALE
    (an ambiguous match is treated the same as no match: guessing wrong here
    is worse than asking).
    """
    needle = (anchor_text or "").strip()
    if not needle:
        # Blank/unknown text isn't matchable — keep today's behavior: assume
        # the recorded line is still right rather than flagging every such
        # thread as orphaned.
        return Resolution(Kind.EXACT, recorded_line)

    idx = recorded_line - 1  # 1-based -> 0-based
    if 0 <= idx < len(lines) and lines[idx].strip() == needle:
        return Resolution(Kind.EXACT, recorded_line)

    search_idx = max(0, min(idx, len(lines) - 1))
    lo = max(0, search_idx - k)
    hi = min(len(lines) - 1, search_idx + k)
    match = -1
    for i in range(lo, hi + 1):
        if lines[i].strip() == needle:
            if match != -1:
                return Resolution(Kind.STALE, -1)  # ambiguous
            match = i
    if match == -1:
        return Resolution(Kind.STALE, -1)
    return Resolution(Kind.MOVED, match + 1)
