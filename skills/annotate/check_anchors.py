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


def _derive_workspace_root(blocks_path: Path):
    """If `blocks_path` sits at <root>/.claude/annotate/<sid>/response/
    blocks.json, return <root>. Otherwise None.

    The server stamps a session's root (dirs["_cwd"]) once at create time
    and never refreshes it on the attach path -- so `/annotate resume` from
    a different directory can hand this check a root that names the wrong
    repo, while blocks.json's own location on disk still names the right
    one. A hand-made fixture (as this module's own tests use) won't match
    this shape, and the caller falls back to the passed root exactly as
    before.
    """
    parts = blocks_path.resolve().parts
    if len(parts) < 5:
        return None
    claude, annotate, _sid, response, name = parts[-5:]
    if (claude, annotate, response, name) != (".claude", "annotate", "response", "blocks.json"):
        return None
    return Path(*parts[:-5])


def main(argv: list) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python3 -m skills.annotate.check_anchors "
            "<blocks.json> <repo_root>\n")
        return 1
    blocks_path, root_arg = Path(argv[1]), argv[2]
    try:
        doc = json.loads(blocks_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write("could not read %s: %s\n" % (blocks_path, e))
        return 1

    root = root_arg
    derived = _derive_workspace_root(blocks_path)
    if derived is not None:
        try:
            passed_real = Path(root_arg).resolve()
        except (OSError, ValueError):
            passed_real = None
        if passed_real is None or derived != passed_real:
            # Refuse rather than guess which one is right -- validating
            # against either would silently check the wrong repo's files.
            sys.stderr.write(
                "claude-annotate: the workspace this session was created in "
                "does not match where this check is running from.\n"
                "  session's workspace root (from blocks.json's own path): %s\n"
                "  check was run against:                                  %s\n"
                % (derived, passed_real if passed_real is not None else root_arg)
            )
            return 1
        root = derived

    problems = check(doc, root)
    if not problems:
        return 0
    sys.stderr.write("claude-annotate: %d anchor problem(s)\n" % len(problems))
    for p in problems:
        sys.stderr.write("  %s\n" % p)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
