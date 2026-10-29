#!/usr/bin/env python3
"""Show a set of screenshots as one canvas that pans and zooms like Figma's (skills/canvas).

Run:  uv run --with pillow tools/canvas.py build MANIFEST.json --out DIR
      python3 tools/canvas.py check MANIFEST.json
      python3 tools/canvas.py template -o viewer.html

`build` writes DIR/index.html, the images it shows and their thumbnails (DIR may be the manifest's
own folder). `check` prints what is wrong with a manifest and exits 1, or prints "ok". `template`
writes the page with no data in it, for a project that fills it in itself.
The manifest's format is in skills/canvas/canvas.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills"))

from canvas import canvas  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="what", required=True)
    b = sub.add_parser("build", help="write the canvas folder")
    b.add_argument("manifest", type=Path)
    b.add_argument("--out", type=Path, help="the folder to write (default: the manifest's)")
    c = sub.add_parser("check", help="validate a manifest")
    c.add_argument("manifest", type=Path)
    t = sub.add_parser("template", help="write the page with no data in it")
    t.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args()
    if a.what == "template":
        a.out.write_text(canvas.template())
        print(a.out)
        return 0
    try:
        m = json.loads(a.manifest.read_text())
    except (OSError, ValueError) as e:
        print(f"{a.manifest}: {e}", file=sys.stderr)
        return 1
    errs = canvas.check(m, a.manifest.resolve().parent)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    if a.what == "check":
        print("ok")
        return 0
    print(canvas.build(a.manifest, a.out or a.manifest.resolve().parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
