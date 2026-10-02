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
    """Refuse a spec the layout cannot draw honestly, before anything is drawn.

    Nothing here places a card: columns, order and heights come from the wires (see
    engine.js). `slot` is still type-checked so that no spec that was refused before is
    accepted now, but it is never compared with the edges. engine.js repeats every check
    and throws, so a page that skipped this still fails loudly under --check."""
    if not spec.get("cards"):
        raise ValueError("the spec has no cards")
    cards = {c["id"]: c for c in spec["cards"]}
    if len(cards) != len(spec["cards"]):
        raise ValueError("two cards share an id")
    for c in spec["cards"]:
        slot = c.get("slot", 0)
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise ValueError(f"card {c['id']!r}: slot must be a whole number")
        if not c.get("fields"):
            raise ValueError(f"card {c['id']!r} has no fields")
        ids = [f["id"] for f in c["fields"]]
        if len(set(ids)) != len(ids):
            raise ValueError(f"card {c['id']!r}: two fields share an id")
        if c.get("rows", "real") not in ROW_MODES:
            raise ValueError(f"card {c['id']!r}: rows must be one of {ROW_MODES}")
    seen = set()
    feeds = {cid: set() for cid in cards}
    for e in spec.get("edges", []):
        for end in (e["from"], e["to"]):
            cid, fid = end.split(".", 1)
            if cid not in cards:
                raise KeyError(f"no card {cid!r}")
            if not any(f["id"] == fid for f in cards[cid]["fields"]):
                raise KeyError(f"{cid} has no field {fid!r}")
        a, b = e["from"].split(".")[0], e["to"].split(".")[0]
        if a == b:
            raise ValueError(f"edge {e['from']} → {e['to']} stays inside card {a!r}; a field cannot feed its own card")
        if (e["from"], e["to"]) in seen:
            raise ValueError(f"edge {e['from']} → {e['to']} appears twice")
        seen.add((e["from"], e["to"]))
        if "lane" in e and e["lane"] not in LANES:
            raise ValueError(f"edge {e['from']} → {e['to']}: lane must be one of {LANES}")
        feeds[a].add(b)
    loop = _find_loop(spec["cards"], feeds)
    if loop:
        raise ValueError(f"cards feed each other in a loop: {' → '.join(loop)}; "
                         "draw the later stage of one of them as its own card")


def _find_loop(cards: list, feeds: dict) -> list | None:
    """The first loop a three-colour DFS meets, as card ids ending where they start.

    It starts from each card in spec order and visits successors in id order, so the
    same spec always reports the same loop (engine.js walks the same way)."""
    colour = dict.fromkeys(feeds, 0)           # 0 unseen, 1 on the current path, 2 done
    for c in cards:
        if colour[c["id"]]:
            continue
        path, stack = [c["id"]], [iter(sorted(feeds[c["id"]]))]
        colour[c["id"]] = 1
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                colour[path.pop()] = 2
                stack.pop()
            elif colour[nxt] == 1:
                return path[path.index(nxt):] + [nxt]
            elif colour[nxt] == 0:
                colour[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(feeds[nxt])))
    return None


LEGACY_NOTE = 'note: "slot" and "gaps" are no longer read; columns and gap widths come from the wires'


def has_legacy_keys(spec: dict) -> bool:
    return "gaps" in spec or any("slot" in c for c in spec.get("cards", []))


def render(spec: dict) -> str:
    validate(spec)
    # `slot` and `gaps` place nothing any more. Dropping them after validating means a
    # spec that still carries them embeds, and so draws, byte for byte what it would
    # without them.
    spec = {k: v for k, v in spec.items() if k != "gaps"}
    spec["cards"] = [{k: v for k, v in c.items() if k != "slot"} for c in spec["cards"]]
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
        spec = json.load(fh)
    page = render(spec)
    if has_legacy_keys(spec):
        print(LEGACY_NOTE, file=sys.stderr)
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
