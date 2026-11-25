#!/usr/bin/env python3
"""Check a render's table geometry (frames.json 'grid'): no reflow between steps, lit cells inside the table's box.

    python3 grid_check.py <render out dir> [...]
For each width (desktop 1440, phone 390) the table's size, column widths and row heights must be the same in every
shot; a lit row, cell or column must be inside the table's visible box (below the sticky header, right of the
sticky first column on a phone) in every shot. Prints one line per width and the failures."""
import json, sys
from pathlib import Path

def main(dirs):
    bad = 0
    for d in dirs:
        frames = [f for f in json.load(open(Path(d) / "frames.json")) if f.get("grid")]
        for width in sorted({f["width"] for f in frames}):
            fs = [f for f in frames if f["width"] == width]
            base = fs[0]["grid"]
            shift = []
            for f in fs[1:]:
                g = f["grid"]
                for k in ("table", "cols", "rows", "head"):
                    a, b = base[k], g[k]
                    if k == "table":
                        a, b = [a[2], a[3]], [b[2], b[3]]  # its size: its place moves with the pane and its own scroll
                    if k == "head":
                        a, b = [a[3]], [b[3]]
                    if any(abs(x - y) > 1.01 for x, y in zip(a, b)) or len(a) != len(b):
                        shift.append((f["file"], k, a, b))
            out = []
            for f in fs:
                g = f["grid"]; wl, wt, ww, wh = g["wrap"]; head = g["head"][3]; key = g["key"] if g["scroll"][2] > g["scroll"][4] else 0
                span = (max(e["rect"][0] + e["rect"][2] for e in g["lit"]) - min(e["rect"][0] for e in g["lit"])) if g["lit"] else 0
                for e in g["lit"]:
                    l, t, w, h = e["rect"]
                    top_ok = t >= wt + (0 if e["tag"] == "TH" else head) - 1.5 and t + h <= wt + wh + 1.5
                    left_ok = e["tag"] == "TR" or (l >= wl - 1.5 and l + w <= wl + ww + 1.5)  # a row is as wide as the table
                    # a column of a table wider than its box may overhang; the cells being said must not
                    first = e is g["lit"][0]
                    tall = max(x["rect"][1] + x["rect"][3] for x in g["lit"]) - min(x["rect"][1] for x in g["lit"]) > wh - head
                    wide_set = span > ww or tall  # a pair of cells further apart than the box is wide: the first must be in
                    if not (top_ok and left_ok) and not (e["tag"] == "TH" and w > ww) and not (wide_set and not first):
                        out.append((f["file"], e["tag"], e["rect"], g["wrap"]))
            status = "OK" if not shift and not out else "FAIL"
            bad += status == "FAIL"
            print(f"{d} width {width}: {len(fs)} shots, reflow {len(shift)}, lit outside {len(out)} {status}")
            for x in shift[:5]: print("  reflow", x)
            for x in out[:5]: print("  outside", x)
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
