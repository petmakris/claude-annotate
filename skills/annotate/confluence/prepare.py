"""Build the bundle a publish uploads.

Nothing here touches Confluence. It writes four things into a directory:

    body.template.html    the page, with placeholders where pictures go
    annotate-source.json  the manifest a future refresh regenerates from
    images/<id>.png       one per diagram
    report.json           every anchor's status, and whether to proceed

`proceed: false` means the publish stops and NO body is written. That is the
point of the split: a page that is missing a citation, that quietly dropped a
block the converter could not handle, or that quietly dropped a block missing
from disk entirely, is not the document the author approved, and the only
safe moment to notice is before anything is uploaded.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skills.annotate.confluence import body as body_mod
from skills.annotate.confluence import gitref, images, manifest, resolve
from skills.annotate.confluence.constants import (
    BODY_FINAL, BODY_TEMPLATE, REPORT_NAME)
from skills.annotate.confluence.markdown_html import UnsupportedMarkdown


def load_items(
        items_dir: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """The stored document: (__doc__ body, blocks in `order`, missing ids).

    Read from disk rather than from the daemon's API — a refresh may run long
    after the session was last open, and a scheduled job has no daemon at all.

    A block id named in `order` with no file on disk is not skipped silently:
    it is returned separately so the caller can refuse the publish over it,
    the same as any other way the stored document differs from the one the
    author approved.
    """
    items_dir = Path(items_dir)
    doc = json.loads((items_dir / "__doc__.json").read_text())
    doc = doc.get("body", doc)
    blocks = []
    missing = []
    for bid in doc.get("order") or []:
        path = items_dir / ("%s.json" % bid)
        if not path.exists():
            missing.append(bid)
            continue
        raw = json.loads(path.read_text())
        blocks.append(raw.get("body", raw))
    return doc, blocks, missing


def load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The stored document, read from a published page's own manifest.

    This is the refresh path, and it is the only path a refresh HAS: the
    machine that published the page may be gone, and `annotate-source.json`
    is the attachment that outlives it. `load_items` cannot serve it — it
    requires a `__doc__.json` no manifest contains, and an `order` a manifest
    expresses by the order of `blocks` itself. Every other field a refresh
    needs (title, slug, response_id, glossary) is already in there, so this
    reads them out rather than asking a caller to reconstruct a workspace.
    """
    man = manifest.parse(Path(path).read_text())
    doc = {
        "title": man.get("title", ""),
        "slug": man.get("slug", ""),
        "response_id": man.get("response_id", ""),
        "glossary": man.get("glossary") or [],
    }
    return doc, list(man.get("blocks") or [])


def clear(out_dir: Path) -> None:
    """Remove the previous run's bundle from `out_dir`.

    Nothing cleared it, so running successfully, editing the document and
    re-running into the same `--out` left `"proceed": false` in report.json
    beside the PREVIOUS run's body and this run's manifest — a complete,
    publishable, wrong bundle. The "no bundle at all" guarantee held only for
    a fresh directory, which is not how a second publish is run.
    """
    for name in (BODY_TEMPLATE, BODY_FINAL, REPORT_NAME,
                 manifest.MANIFEST_NAME):
        (Path(out_dir) / name).unlink(missing_ok=True)
    shutil.rmtree(Path(out_dir) / "images", ignore_errors=True)


def prepare(*, repo: str, out_dir: Path, items_dir: Path = None,
            manifest_path: Path = None, slug: str = "",
            ref: str = "origin/master", with_images: bool = True,
            resolved_at: str = None) -> dict:
    """Build the bundle, from a session's items directory or from a manifest.

    `resolved_at` exists so a caller can pin the clock; the round-trip test
    rebuilds a bundle from its own manifest and compares the two bodies byte
    for byte, which a live timestamp would make impossible to assert.
    """
    if (items_dir is None) == (manifest_path is None):
        raise ValueError(
            "prepare needs exactly one source: --items or --manifest")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clear(out_dir)
    if items_dir is not None:
        doc, blocks, missing_blocks = load_items(Path(items_dir))
    else:
        doc, blocks = load_manifest(Path(manifest_path))
        missing_blocks = []
    slug = slug or doc.get("slug", "")
    if not slug:
        raise ValueError(
            "no session slug: it names the annotate session in the page's "
            "provenance line, so pass --slug or use a manifest that carries "
            "one")

    commit = gitref.commit_of(repo, ref)
    web = gitref.web_url(gitref.remote_of(repo))
    repo_info = {
        "remote": gitref.remote_of(repo),
        "web": web,
        "ref": ref,
        "commit": commit,
        "resolved_at": resolved_at or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
    }

    man = manifest.build(
        response_id=doc.get("response_id", ""), title=doc.get("title", ""),
        slug=slug, glossary=doc.get("glossary") or [], blocks=blocks,
        repo=repo_info)
    (out_dir / manifest.MANIFEST_NAME).write_text(json.dumps(man, indent=2))

    rows = resolve.resolve_all(manifest.anchors_of(man), repo=repo, ref=ref,
                               commit=commit, web=web)
    blocked = resolve.blocking(rows)

    # Convert every markdown block up front, so a construct the converter
    # cannot handle is reported alongside the anchor problems rather than
    # raising halfway through writing a page.
    unconvertible = []
    unsupported_views = []
    for blk in blocks:
        if body_mod.has_picture(blk):
            views = body_mod.extra_views(blk)
            if views:
                unsupported_views.append(
                    {"block_id": blk["id"], "views": views})
            if not blk.get("svg"):
                unconvertible.append({
                    "block_id": blk["id"],
                    "problem": "a %s block with no stored drawing would "
                               "publish a picture placeholder that no upload "
                               "can fill" % blk.get("kind")})
            continue
        try:
            body_mod.render_block(blk, [])
        except UnsupportedMarkdown as e:
            unconvertible.append({"block_id": blk["id"], "problem": str(e)})

    report: dict[str, Any] = {
        "title": doc.get("title", ""),
        "repo": repo_info,
        "anchors": rows,
        "blocking": blocked,
        "unconvertible": unconvertible,
        "unsupported_views": unsupported_views,
        "missing_blocks": missing_blocks,
        "images": ["%s.png" % b["id"] for b in blocks
                   if body_mod.has_picture(b)],
        "proceed": not (blocked or unconvertible or unsupported_views
                        or missing_blocks),
    }
    (out_dir / REPORT_NAME).write_text(json.dumps(report, indent=2))
    if not report["proceed"]:
        return report

    (out_dir / BODY_TEMPLATE).write_text(body_mod.render_page(
        glossary=doc.get("glossary") or [], blocks=blocks, anchor_rows=rows, repo=repo_info, slug=slug))

    if with_images:
        img_dir = out_dir / "images"
        for blk in blocks:
            if body_mod.has_picture(blk):
                images.render_png(blk["svg"], img_dir / ("%s.png" % blk["id"]))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.confluence.prepare")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--items", help="the session's items dir")
    src.add_argument("--manifest",
                     help="annotate-source.json off a published page, for a "
                          "refresh with no workspace to read")
    ap.add_argument("--repo", required=True, help="checkout to resolve against")
    ap.add_argument("--out", required=True, help="bundle directory to write")
    ap.add_argument("--slug",
                    help="required with --items; --manifest carries its own")
    ap.add_argument("--ref", default="origin/master")
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args(argv)
    if a.items and not a.slug:
        ap.error("--slug is required with --items")
    report = prepare(items_dir=Path(a.items) if a.items else None,
                     manifest_path=Path(a.manifest) if a.manifest else None,
                     repo=a.repo, out_dir=Path(a.out), slug=a.slug or "",
                     ref=a.ref, with_images=not a.no_images)
    print(json.dumps({k: report[k] for k in
                      ("proceed", "blocking", "unconvertible",
                       "unsupported_views", "missing_blocks", "images")},
                     indent=2))
    return 0 if report["proceed"] else 2


if __name__ == "__main__":
    sys.exit(main())
