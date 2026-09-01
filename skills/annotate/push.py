"""Push an annotate document to the webcompanion daemon.

Replaces the old flow — start a per-skill server, create a workspace, write
blocks.json into a directory the server happens to watch. There is no
annotate server any more: the daemon owns storage, comment threads and the
event queue, and this module is the only thing that knows how an annotate
document maps onto it.

The mapping, which is the whole contract between this file and the page's
compat.js:

    __doc__          {response_id, title, glossary, order: [block ids]}
    <block id>       one rendered block body (see render.render_block)
    __prev__         the previous __doc__ + blocks, for the "what changed" pane

Usage:
    python3 -m skills.annotate.push --blocks <blocks.json> --cwd <repo root>
                                    [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from skills.annotate import blocks as blocks_model
from skills.annotate.render import render_block

CONTRACT = 1
KIND = "annotate"
DOC_ANCHOR = "__doc__"
PREV_ANCHOR = "__prev__"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"


class DaemonError(RuntimeError):
    pass


def _config() -> dict:
    path = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))
    if not path.exists():
        raise DaemonError(
            "webcompanion is not configured on this machine "
            "(~/.claude/webcompanion/config.json is missing).\n"
            "  pipx install webcompanion && webcompanion install-service")
    return json.loads(path.read_text())


def _request(cfg: dict, method: str, path: str, body=None) -> dict:
    url = "http://127.0.0.1:%d%s" % (int(cfg["port"]), path)
    data = None
    headers = {"X-WebCompanion-Contract": str(CONTRACT)}
    if cfg.get("token"):
        headers["X-WebCompanion-Token"] = cfg["token"]
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        if e.code == 426:
            raise DaemonError("contract mismatch: %s" % detail) from None
        raise DaemonError("%s %s -> %d %s" % (method, path, e.code, detail)) from None
    except urllib.error.URLError as e:
        raise DaemonError(
            "cannot reach the webcompanion daemon on port %s (%s).\n"
            "  webcompanion status   # is the service running?\n"
            "  webcompanion doctor   # full check"
            % (cfg["port"], e.reason)) from None
    return json.loads(raw) if raw.strip() else {}


def items_for(doc: blocks_model.BlocksDoc, cwd: str) -> dict:
    """The full item set for a document — the exact body of a `replace` push."""
    items = {
        DOC_ANCHOR: {
            "response_id": doc.response_id,
            "title": doc.title,
            "glossary": list(doc.glossary),
            "order": [b["id"] for b in doc.blocks],
            # The repo root, so the page can offer "open this in my editor"
            # for a code anchor. The page shows the control to an owner only.
            "cwd": cwd,
        }
    }
    for blk in doc.blocks:
        items[blk["id"]] = render_block(blk)
    return items


def _existing_items(cfg: dict, sid: str) -> dict:
    try:
        snap = _request(cfg, "GET", "/s/%s/items?kind=%s" % (sid, KIND))
    except DaemonError:
        return {}
    return {a: v.get("body") for a, v in snap.items() if isinstance(v, dict)}


def push(blocks_path: Path, cwd: str, slug: str | None = None,
         title: str | None = None) -> dict:
    cfg = _config()
    doc = blocks_model.load(blocks_path)
    title = title or doc.title or "Response"

    sid = None
    if slug:
        # Attaching: resolve the slug to a live session before creating one,
        # so a second push in a conversation updates the page the user already
        # has open instead of minting a second URL beside it. Resolve it to the
        # real sid rather than passing the slug on — a slug is unique only
        # within a kind, and the caller gets this value back to hand to
        # `webcompanion ack`, where an ambiguous one would be a 409 at the
        # worst possible moment.
        try:
            rows = _request(cfg, "GET", "/api/sessions?cwd=%s&kind=%s"
                            % (urllib.parse.quote(cwd), KIND))
            for row in (rows if isinstance(rows, list) else rows.get("sessions", [])):
                if row.get("slug") == slug:
                    sid = row.get("sid")
                    break
        except DaemonError:
            sid = None

    created = False
    if sid is None:
        body = {"kind": KIND, "cwd": cwd, "title": title}
        if slug:
            body["slug"] = slug
        res = _request(cfg, "POST", "/api/sessions", body)
        sid, slug, created = res["sid"], res["slug"], True

    items = items_for(doc, cwd)

    # The pre-round snapshot the diff pane reads. Written from what is
    # currently stored, BEFORE the replace lands — the old server kept this
    # by copying blocks.json on every mutating event, and losing it would
    # silently kill the "what changed since you commented" marks.
    prev = _existing_items(cfg, sid)
    prev.pop(PREV_ANCHOR, None)
    if prev:
        items[PREV_ANCHOR] = prev

    _request(cfg, "PATCH", "/s/%s/items?kind=%s" % (sid, KIND),
             {"items": items, "replace": True})

    # Register the page. Idempotent, and re-sent on every push so a plugin
    # that has moved on disk since the session was created still resolves.
    _request(cfg, "POST", "/s/%s/api/assets?kind=%s" % (sid, KIND),
             {"static_root": str(STATIC_DIR), "entry": ENTRY})

    base = "http://127.0.0.1:%d/s/%s/" % (int(cfg["port"]), slug)
    return {
        "sid": sid,
        "slug": slug,
        "created": created,
        "kind": KIND,
        "url": base,
        "localhost_url": "http://localhost:%d/s/%s/" % (int(cfg["port"]), slug),
        "owner_url": base + "#k=" + cfg.get("token", ""),
        "blocks": len(doc.blocks),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.push")
    ap.add_argument("--blocks", required=True, help="path to blocks.json")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    ap.add_argument("--eval", action="store_true",
                    help="print WC_SID=/WC_SLUG=/WC_URL= for `eval`")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.blocks), a.cwd, a.slug, a.title)
    except DaemonError as e:
        print("annotate push: %s" % e, file=sys.stderr)
        return 1
    if a.eval:
        print("WC_SID=%s" % res["sid"])
        print("WC_SLUG=%s" % res["slug"])
        print("WC_URL=%s" % res["localhost_url"])
    else:
        print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
