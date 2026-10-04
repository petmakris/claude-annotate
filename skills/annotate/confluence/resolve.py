"""Anchors resolved against a ref, with a permalink and an honesty check.

Two things separate this from the anchor resolution the live page does.

First, the byte source is `git show origin/master:<path>` — a published page
describes the code its readers have, not the branch it was written on.

Second, `ambiguous`. `anchors._locate` picks the match nearest the authored
line and reports it as `moved` with the same confidence as an exact hit. That
is right for a page the author is looking at while the file changes under
them; it is wrong for a page nobody re-reads for months, where a citation that
quietly slid onto the wrong line is worse than one that admits it is broken.
So when the snippet matches more than once in the drift window and the
authored line is not one of the matches, the guess is refused.
"""
from __future__ import annotations

from typing import Any

from skills.annotate import anchors
from skills.annotate.confluence import gitref

# Any of these stops a publish. `refused` is a malformed anchor, which is an
# authoring bug; the rest are citations that would mislead a reader.
BLOCKING = ("stale", "missing", "ambiguous", "refused")


def _matches_in_window(lines: list[str], snippet: str, authored: int) -> int:
    want = snippet.strip()
    lo = max(1, authored - anchors.DRIFT_RADIUS)
    hi = min(len(lines), authored + anchors.DRIFT_RADIUS)
    return sum(1 for n in range(lo, hi + 1) if lines[n - 1].strip() == want)


def _permalink(web: str, commit: str, path: str,
               start: int, end: int) -> str:
    span = "#L%d" % start if end <= start else "#L%d-L%d" % (start, end)
    return "%s/blob/%s/%s%s" % (web, commit, path, span)


def resolve_all(pairs: list[tuple[str, dict[str, Any]]], *, repo: str,
                ref: str, commit: str, web: str) -> list[dict[str, Any]]:
    """Resolve every (block_id, anchor) pair at `ref`."""
    out: list[dict[str, Any]] = []
    for block_id, a in pairs:
        row: dict[str, Any] = {
            "block_id": block_id,
            "file": a.get("file", ""),
            "line": a.get("line", 0),
            "end_line": a.get("end_line"),
            "snippet": a.get("snippet", ""),
        }
        lines = gitref.read_lines(repo, ref, str(a.get("file", "")))
        if lines is None:
            row.update(status="missing",
                       message="%s: not present at %s" % (a.get("file"), ref))
            out.append(row)
            continue

        resolved = anchors.resolve_anchor_in(a, lines)
        row.update({k: v for k, v in resolved.items() if k != "file"})

        if resolved["status"] == "moved":
            authored = a["line"]
            exact = (1 <= authored <= len(lines)
                     and lines[authored - 1].strip() == a["snippet"].strip())
            if not exact and _matches_in_window(
                    lines, a["snippet"], authored) > 1:
                row["status"] = "ambiguous"
                row["message"] = (
                    "%s: %r matches more than one line near line %d, so the "
                    "line this cites would be a guess"
                    % (a.get("file"), a["snippet"].strip(), authored))

        if row["status"] in ("ok", "moved"):
            start = resolved["actual_line"]
            end = start + ((a.get("end_line") or a["line"]) - a["line"])
            row["url"] = _permalink(web, commit, str(a["file"]), start, end)
        out.append(row)
    return out


def blocking(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The results that must stop a publish, in document order."""
    return [r for r in results if r.get("status") in BLOCKING]
