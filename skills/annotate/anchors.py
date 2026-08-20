"""Code anchors — resolving a block's {file, line, snippet} to real source.

A block may carry a `code` list; each entry names a file and a line in the
workspace's repo, and the server reads that file at render time. The block
never carries code text, which is what makes an anchor cheap enough to write
generously and impossible to leave stale relative to the working tree.

Two rules shape everything in here:

  * `file` is untrusted. Anchors are model-authored, so every path is
    resolved and then required to stay under the workspace root. Without that
    check a block could name ../../.ssh/id_rsa and the page would print it to
    anyone holding the read-only share link.

  * A failure is a marker, never an exception. One bad anchor must not blank
    the page — the same rule the sequence/flowchart/diagram branches of
    server._render_block_for_raw already follow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# Limits, from docs/superpowers/specs/2026-08-20-code-anchors-design.md.
MAX_ANCHORS = 3        # past three, the block is a tour — use /walkthrough
MAX_WINDOW = 40        # a pane you must scroll has stopped being a glance
CONTEXT_LINES = 2      # dimmed lines either side, so a line has a home
DRIFT_RADIUS = 40      # how far to hunt for a snippet that moved


def _is_int(v: Any) -> bool:
    """bool is an int subclass; True must not pass as line 1."""
    return isinstance(v, int) and not isinstance(v, bool)


def anchor_problem(a: Any) -> Optional[str]:
    """Return one human-readable problem with this anchor, or None."""
    if not isinstance(a, dict):
        return "must be an object"

    f = a.get("file")
    if not isinstance(f, str) or not f.strip():
        return "file must be a non-empty string"
    if Path(f).is_absolute():
        return "file must be relative to the repository root"

    line = a.get("line")
    if not _is_int(line) or line < 1:
        return "line must be a positive integer"

    end_line = a.get("end_line")
    if end_line is not None:
        if not _is_int(end_line) or end_line < 1:
            return "end_line must be a positive integer"
        if end_line < line:
            return "end_line must not precede line"

    snippet = a.get("snippet")
    if not isinstance(snippet, str) or not snippet.strip():
        return "snippet must be non-empty (it is what survives the file moving)"

    note = a.get("note")
    if note is not None and not isinstance(note, str):
        return "note must be a string"

    return None


def block_problems(blk: dict) -> list:
    """Return every problem with a block's `code` field; empty means valid."""
    code = blk.get("code")
    if code is None:
        return []
    if not isinstance(code, list):
        return ["code must be a list of anchors"]
    if not code:
        return []

    problems = []
    if (blk.get("kind") or "markdown") == "mockup":
        problems.append(
            "a mockup block takes no anchors — its sandboxed iframe has "
            "nowhere to put a pane"
        )
    if len(code) > MAX_ANCHORS:
        problems.append(
            "at most %d anchors per block (found %d) — past that the block "
            "is a tour, and the right answer is /walkthrough"
            % (MAX_ANCHORS, len(code))
        )
    for i, a in enumerate(code):
        p = anchor_problem(a)
        if p:
            problems.append("code[%d]: %s" % (i, p))
    return problems
