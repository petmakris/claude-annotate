"""Rebuild blocks.json from what the daemon stores for a session.

The daemon holds the page; blocks.json is only the working copy a push is made
from. That copy lives in a scratchpad, so it does not survive the conversation
that wrote it, and `/annotate resume` from a new conversation used to leave no
working file at all — the next "save and re-push" then replaced the resumed
page with whatever Claude had in hand. This writes the working copy back from
the stored items, so a resumed page is edited, not overwritten.

The stored body of each block is its authoring format plus what push.py
rendered from it (svg, compiled views, a flowchart's derived nodes and edges).
Only the authored half comes back.

Usage:
    python3 -m skills.annotate.pull --sid <sid or slug> --out <blocks.json>
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from skills.annotate import blocks as blocks_model
from skills.annotate import session as session_mod
from skills.annotate.push import (DaemonError, KIND, DOC_ANCHOR, HOLDS_ANCHOR,
                                  _config, _request, held_blocks)

# What a stored body may carry that the author wrote (`mine` names the
# words the reader wrote in the editor). Everything else in it
# (svg, svgs, flavours, views, key, view, warnings) was rendered by push.py.
AUTHORED = ("id", "kind", "title", "markdown", "spec", "code", "change_note", "mine")


def block_from_body(body: dict, version=None) -> dict:
    blk = {k: body[k] for k in AUTHORED if k in body}
    if blk.get("kind") == "markdown":
        del blk["kind"]
    if isinstance(blk.get("markdown"), str) and isinstance(version, int):
        # The stored version this copy was built on. A push that sends it
        # back, while the item is still at that version, says Claude's text
        # includes the reader's edits, so push.py lets it replace them
        # (push.edited_since_push). Any later save bumps the version.
        blk["base"] = version
    spec = blk.get("spec")
    if blk.get("kind") == "flowchart" and isinstance(spec, dict) and spec.get("source"):
        # Compiled from `source` at push time; stale by definition once the
        # source is edited, so the working copy keeps only what drew them.
        blk["spec"] = {k: v for k, v in spec.items() if k not in ("nodes", "edges")}
    return blk


def pull(sid: str) -> tuple[blocks_model.BlocksDoc, dict, list]:
    cfg = _config()
    items = _request(cfg, "GET", "/s/%s/items?kind=%s" % (sid, KIND))
    doc_item = (items.get(DOC_ANCHOR) or {}).get("body") or {}
    blocks = []
    for bid in doc_item.get("order") or []:
        item = items.get(bid) or {}
        body = item.get("body")
        if isinstance(body, dict):
            blocks.append(block_from_body(body, item.get("version")))
    doc = blocks_model.BlocksDoc(
        response_id=doc_item.get("response_id", ""),
        title=doc_item.get("title", ""),
        blocks=blocks,
        glossary=list(doc_item.get("glossary") or []),
    )
    prev = {HOLDS_ANCHOR: (items.get(HOLDS_ANCHOR) or {}).get("body")}
    return doc, doc_item, sorted(held_blocks(prev, int(time.time())))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.pull")
    ap.add_argument("--sid", required=True, help="the session's sid or slug")
    ap.add_argument("--out", required=True, help="where to write blocks.json")
    a = ap.parse_args(argv)
    try:
        doc, doc_item, held = pull(a.sid)
    except DaemonError as e:
        print("annotate pull: %s" % e, file=sys.stderr)
        return 1
    if not doc.blocks:
        print("annotate pull: session %s holds no blocks; nothing written" % a.sid,
              file=sys.stderr)
        return 1
    out = Path(a.out)
    blocks_model.save_atomic(out, doc)
    # Point the conversation marker at the new working copy, so the next
    # push and every later event read this file.
    for e in session_mod.entries():
        if a.sid in (e.get("sid"), e.get("slug")):
            session_mod.record({**e, "blocks": str(out.resolve())})
    print("annotate pull: wrote %d blocks to %s" % (len(doc.blocks), out))
    if held:
        print("held by the reader: %s" % ", ".join(held))
    return 0


if __name__ == "__main__":
    sys.exit(main())
