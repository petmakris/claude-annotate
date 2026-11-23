"""Put the uploaded media ids into the page body.

A media id exists only after the file is uploaded, and the file can only be
uploaded to a page that already exists — so the body is written twice, and
this is the second pass. It refuses on an unfilled placeholder because the
failure it prevents is silent: Confluence renders a media node pointing at
nothing as a broken tile, with no error anywhere in the publish.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skills.annotate.confluence.constants import (
    BODY_FINAL, BODY_TEMPLATE, LEFTOVER, media_token)


class UnfilledPlaceholder(ValueError):
    """A picture in the body was never uploaded."""


def finalize(bundle: Path, media: dict[str, dict]) -> Path:
    """Substitute `{filename: {id, collection}}` into the body template."""
    bundle = Path(bundle)
    text = (bundle / BODY_TEMPLATE).read_text()
    for filename, ids in media.items():
        # Skip entries missing required keys (e.g., re-uploaded manifest, stale
        # image from a previous run). Only attempt substitution if both keys exist.
        if "id" not in ids or "collection" not in ids:
            continue
        mid, coll = media_token(Path(filename).stem)
        text = text.replace(mid, str(ids["id"]))
        text = text.replace(coll, str(ids["collection"]))
    left = sorted(set(LEFTOVER.findall(text)))
    if left:
        raise UnfilledPlaceholder(
            "no upload was recorded for %s — publishing this body would put a "
            "broken picture on the page" % ", ".join(left))
    out = bundle / BODY_FINAL
    out.write_text(text)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.confluence.finalize")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--media", required=True,
                    help='JSON: {"section-2.png": {"id": ..., "collection": ...}}')
    a = ap.parse_args(argv)
    try:
        out = finalize(Path(a.bundle), json.loads(a.media))
    except UnfilledPlaceholder as e:
        print("annotate publish: %s" % e, file=sys.stderr)
        return 2
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
