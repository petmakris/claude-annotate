#!/usr/bin/env python3
"""Render a field-level object mapping as a standalone, interactive canvas page.

The output is one self-contained file: no webfonts, no CDN, no network of any kind. It
opens by double-click, survives being emailed or dropped on a share, and renders the same
offline as online. Keep it that way: anything added here must be inlined.

    python3 render.py spec.json > out.html

This module only validates the spec and assembles the page. The geometry is computed
in the page by engine.js, from the spec alone, so the same spec always draws the same
picture. See SKILL.md for the spec format.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

try:                       # imported as part of the package (tests)
    from . import check as _check
except ImportError:        # run as a script: render.py spec.json --check out.html
    import check as _check

HERE = Path(__file__).resolve().parent


LANES = ("above", "below")
ROW_MODES = ("real", "follow")


def validate(spec: dict) -> None:
    """Refuse a spec the layout cannot draw honestly, before anything is drawn."""
    if not spec.get("cards"):
        raise ValueError("the spec has no cards")
    cards = {c["id"]: c for c in spec["cards"]}
    if len(cards) != len(spec["cards"]):
        raise ValueError("two cards share an id")
    slot = {c["id"]: c.get("slot", i) for i, c in enumerate(spec["cards"])}
    for c in spec["cards"]:
        if not isinstance(slot[c["id"]], int) or isinstance(slot[c["id"]], bool):
            raise ValueError(f"card {c['id']!r}: slot must be a whole number")
        if not c.get("fields"):
            raise ValueError(f"card {c['id']!r} has no fields")
        ids = [f["id"] for f in c["fields"]]
        if len(set(ids)) != len(ids):
            raise ValueError(f"card {c['id']!r}: two fields share an id")
        if c.get("rows", "real") not in ROW_MODES:
            raise ValueError(f"card {c['id']!r}: rows must be one of {ROW_MODES}")
    for e in spec.get("edges", []):
        for end in (e["from"], e["to"]):
            cid, fid = end.split(".", 1)
            if cid not in cards:
                raise KeyError(f"no card {cid!r}")
            if not any(f["id"] == fid for f in cards[cid]["fields"]):
                raise KeyError(f"{cid} has no field {fid!r}")
        a, b = e["from"].split(".")[0], e["to"].split(".")[0]
        if slot[b] <= slot[a]:
            raise ValueError(f"edge {e['from']} → {e['to']} must run left to right")
        if "lane" in e and e["lane"] not in LANES:
            raise ValueError(f"edge {e['from']} → {e['to']}: lane must be one of {LANES}")


def render(spec: dict) -> str:
    validate(spec)
    page = (HERE / "canvas.html").read_text(encoding="utf-8")
    engine = (HERE / "engine.js").read_text(encoding="utf-8")
    # JSON inside a <script> element: "</script" would close it early and "<!--" can
    # switch the parser into a state where the engine never runs, so no "<" survives.
    data = json.dumps(spec, sort_keys=True, ensure_ascii=False).replace("<", "\\u003c")
    page = page.replace("{{title}}", html.escape(spec["title"]))
    page = page.replace("/*ENGINE*/", engine)
    return page.replace("/*SPEC*/", data)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a field-mapping spec as a canvas page.")
    ap.add_argument("spec", help="the spec JSON")
    ap.add_argument("--check", metavar="OUT.html", type=Path,
                    help="write the page here, screenshot it to OUT.png and print the layout report")
    args = ap.parse_args()
    with open(args.spec, encoding="utf-8") as fh:
        page = render(json.load(fh))
    if not args.check:
        sys.stdout.write(page)
        return 0

    args.check.write_text(page, encoding="utf-8")
    try:
        report = _check.run(args.check)
    except ImportError:
        print("check needs playwright: pip install playwright")
        return 2
    except _check.Unavailable as e:
        print(e)
        return 2
    except _check.PageError as e:
        print(f"the page failed to lay out: {e}")
        return 3
    for m in _check.MEASURES:
        print(f"{m}: {report[m]}")
    print(f"screenshot: {args.check.with_suffix('.png')}")
    return 0 if _check.passed(report) else 1


if __name__ == "__main__":
    sys.exit(main())
