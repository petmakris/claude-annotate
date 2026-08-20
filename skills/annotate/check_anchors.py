"""Push-time anchor check — fail where the author can still fix it.

A broken anchor renders a visible pill on the page, which tells the READER
something is wrong. By then the author has ended their turn. This runs after
blocks.json is written and before the URL is announced, so a bad citation
fails while it is still cheap.

Usage:
    python3 -m skills.annotate.check_anchors <blocks.json> <repo_root>

Exit 0 when every anchor is valid and resolves. Exit 1 otherwise, one
problem per line on stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from skills.annotate import anchors as anchors_module


def check(doc: dict, root) -> list:
    """Return every anchor problem in a blocks document; empty means clean.

    `moved` is not a problem. A line that drifted is still the right line —
    the pane says so and shows it. Only `stale`, `missing` and `refused`
    mean the citation no longer points at anything.
    """
    blocks = doc.get("blocks")
    if not isinstance(blocks, list):
        return ["blocks must be a list of blocks"]

    problems = []
    for idx, blk in enumerate(blocks):
        if not isinstance(blk, dict):
            problems.append("blocks[%d]: not an object" % idx)
            continue
        bid = blk.get("id") or "?"
        for p in anchors_module.block_problems(blk):
            problems.append("%s: %s" % (bid, p))
        code = blk.get("code")
        if not isinstance(code, list):
            continue
        for i, a in enumerate(code):
            if anchors_module.anchor_problem(a):
                continue  # already reported by block_problems
            out = anchors_module.resolve_anchor(a, root)
            if out["status"] in ("stale", "missing", "refused"):
                problems.append("%s: code[%d]: %s" % (bid, i, out["message"]))
    return problems


def main(argv: list) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python3 -m skills.annotate.check_anchors "
            "<blocks.json> <repo_root>\n")
        return 1
    blocks_path, root = Path(argv[1]), argv[2]
    try:
        doc = json.loads(blocks_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write("could not read %s: %s\n" % (blocks_path, e))
        return 1
    problems = check(doc, root)
    if not problems:
        return 0
    sys.stderr.write("claude-annotate: %d anchor problem(s)\n" % len(problems))
    for p in problems:
        sys.stderr.write("  %s\n" % p)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
