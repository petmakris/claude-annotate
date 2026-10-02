"""Push a dataflow.json document to the webcompanion daemon.

Replaces the old flow — start a per-skill server on a fixed port, let it
serve dataflow.json off disk. There is no dataflow server any more: the
daemon owns storage, comment threads and the event queue, and this module is
the only thing that knows how a dataflow document maps onto it.

The mapping:

    __flow__    the full dataflow.json body, unchanged shape (see flow.py)

Usage:
    python3 -m skills.dataflow.push --flow <dataflow.json> --cwd <repo root>
                                    [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.dataflow import flow

KIND = "dataflow"
FLOW_ANCHOR = "__flow__"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"


def push(flow_path: Path, cwd: str, slug: str | None = None,
        title: str | None = None) -> dict:
    # push.py is handed an explicit file path Claude just wrote, not a
    # session's state_dir to search inside — read and parse it directly, the
    # same way annotate/push.py's `blocks_model.load` takes a direct path
    # rather than a directory.
    doc = json.loads(flow_path.read_text())

    # Nothing else validates this document before it reaches the page — the
    # old per-skill server's write path used to; refuse rather than push
    # something the board can't render.
    errors = flow.validate(doc)
    if errors:
        raise ValueError(
            "dataflow.json failed validation:\n" + "\n".join("  - " + e for e in errors))

    title = title or doc.get("seed") or "Dataflow"

    # `/api/open` only accepts an absolute path already inside a session's
    # workspace and does no resolution of its own — a node's `file` is
    # repository-relative, so the browser needs the repo root to build an
    # absolute path from it. Stashing it on the document is how it gets
    # there; `dataflow.js` reads it back as `FLOW.cwd`.
    doc["cwd"] = str(Path(cwd).resolve())

    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug)
    sid = res["sid"]

    wc.put_items(sid, {FLOW_ANCHOR: doc}, kind=KIND, replace=True)

    # Idempotent, re-sent on every push so a plugin that has moved on disk
    # since the session was created still resolves — same reasoning as
    # annotate/push.py's own asset registration.
    wc.register_assets(sid, str(STATIC_DIR), ENTRY, kind=KIND)

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.dataflow.push")
    ap.add_argument("--flow", required=True, help="path to dataflow.json")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.flow), a.cwd, a.slug, a.title)
    except ValueError as e:
        print("dataflow push: %s" % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("dataflow push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
