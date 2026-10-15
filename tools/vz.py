#!/usr/bin/env python3
"""Draw maps and lane sequences from their JSON specs (skills/_shared/visuals). Standard library only.

Run:  python3 tools/vz.py svg SPEC.json [--uid ID] [-o OUT.svg]
      python3 tools/vz.py html SPEC.json [SPEC.json ...] [--title T] -o OUT.html
      python3 tools/vz.py fragment SPEC.json [--uid ID] [-o OUT.html]

A spec with "actors" is a sequence, one with "columns" and "boxes" a map. `svg` writes the drawing
alone, `fragment` the player a page embeds next to vz.css and vz-reveal.js, `html` one page that holds
everything, for a file, an artifact or a deck. Check a drawing with tools/vz_check.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "_shared"))

from visuals import map_svg, player, sequence_svg  # noqa: E402


def uid_for(path: Path, given: str | None) -> str:
    if given:
        return given
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", path.stem).strip("-") or "vz"
    return stem if stem[0].isalpha() else "vz-" + stem


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["svg", "html", "fragment"])
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--uid")
    ap.add_argument("--title", default="Diagrams")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    outs = []
    for name in a.specs:
        path = Path(name)
        spec = json.loads(path.read_text())
        uid = uid_for(path, a.uid if len(a.specs) == 1 else None)
        try:
            if a.what == "svg":
                outs.append((sequence_svg if "actors" in spec else map_svg).render(spec, uid))
            else:
                outs.append(player.render_any(spec, uid))
        except ValueError as e:
            print(f"{name}: {e}", file=sys.stderr)
            return 1
    text = player.standalone(outs, a.title) if a.what == "html" else "\n".join(outs)
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
