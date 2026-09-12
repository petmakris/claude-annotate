"""Build the bundle a publish uploads.

Nothing here touches Confluence. It writes four things into a directory:

    body.template.html    the page, with placeholders where pictures go
    annotate-source.json  the manifest a future refresh regenerates from
    images/<id>.png       one per diagram
    report.json           every anchor's status, and whether to proceed

`proceed: false` means the publish stops and NO body is written. That is the
point of the split: a page that is missing a citation, or that quietly dropped
a block the converter could not handle, is not the document the author
approved, and the only safe moment to notice is before anything is uploaded.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skills.annotate.confluence import body as body_mod
from skills.annotate.confluence import gitref, images, manifest, resolve
from skills.annotate.confluence.markdown_html import UnsupportedMarkdown

REPORT_NAME = "report.json"
BODY_TEMPLATE = "body.template.html"


def load_items(items_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The stored document: (__doc__ body, blocks in `order`).

    Read from disk rather than from the daemon's API — a refresh may run long
    after the session was last open, and a scheduled job has no daemon at all.
    """
    items_dir = Path(items_dir)
    doc = json.loads((items_dir / "__doc__.json").read_text())
    doc = doc.get("body", doc)
    blocks = []
    for bid in doc.get("order") or []:
        path = items_dir / ("%s.json" % bid)
        if not path.exists():
            continue
        raw = json.loads(path.read_text())
        blocks.append(raw.get("body", raw))
    return doc, blocks


def prepare(*, items_dir: Path, repo: str, out_dir: Path, slug: str,
            ref: str = "origin/master", with_images: bool = True) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc, blocks = load_items(Path(items_dir))

    commit = gitref.commit_of(repo, ref)
    web = gitref.web_url(gitref.remote_of(repo))
    repo_info = {
        "remote": gitref.remote_of(repo),
        "web": web,
        "ref": ref,
        "commit": commit,
        "resolved_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
    }

    man = manifest.build(
        response_id=doc.get("response_id", ""), title=doc.get("title", ""),
        glossary=doc.get("glossary") or [], blocks=blocks, repo=repo_info)
    (out_dir / manifest.MANIFEST_NAME).write_text(json.dumps(man, indent=2))

    rows = resolve.resolve_all(manifest.anchors_of(man), repo=repo, ref=ref,
                               commit=commit, web=web)
    blocked = resolve.blocking(rows)

    # Convert every markdown block up front, so a construct the converter
    # cannot handle is reported alongside the anchor problems rather than
    # raising halfway through writing a page.
    unconvertible = []
    for blk in blocks:
        if (blk.get("kind") or "markdown") != "markdown":
            continue
        try:
            body_mod.render_block(blk, [])
        except UnsupportedMarkdown as e:
            unconvertible.append({"block_id": blk["id"], "problem": str(e)})

    report: dict[str, Any] = {
        "slug": slug,
        "title": doc.get("title", ""),
        "repo": repo_info,
        "anchors": rows,
        "blocking": blocked,
        "unconvertible": unconvertible,
        "images": ["%s.png" % b["id"] for b in blocks if b.get("svg")],
        "proceed": not blocked and not unconvertible,
    }
    (out_dir / REPORT_NAME).write_text(json.dumps(report, indent=2))
    if not report["proceed"]:
        return report

    (out_dir / BODY_TEMPLATE).write_text(body_mod.render_page(
        title=doc.get("title", ""), glossary=doc.get("glossary") or [],
        blocks=blocks, anchor_rows=rows, repo=repo_info, slug=slug))

    if with_images:
        img_dir = out_dir / "images"
        for blk in blocks:
            if blk.get("svg"):
                images.render_png(blk["svg"], img_dir / ("%s.png" % blk["id"]))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.confluence.prepare")
    ap.add_argument("--items", required=True, help="the session's items dir")
    ap.add_argument("--repo", required=True, help="checkout to resolve against")
    ap.add_argument("--out", required=True, help="bundle directory to write")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--ref", default="origin/master")
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args(argv)
    report = prepare(items_dir=Path(a.items), repo=a.repo, out_dir=Path(a.out),
                     slug=a.slug, ref=a.ref, with_images=not a.no_images)
    print(json.dumps({k: report[k] for k in
                      ("proceed", "blocking", "unconvertible", "images")},
                     indent=2))
    return 0 if report["proceed"] else 2


if __name__ == "__main__":
    sys.exit(main())
