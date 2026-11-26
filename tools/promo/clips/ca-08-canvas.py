# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-08-canvas.py: 20 shop screens on one canvas, then only the three that changed.

    uv run tools/promo/clips/ca-08-canvas.py [--port 19163]

Draws the invented Northwind Goods screens (fixtures/ca-08/draw_screens.py: ten
screens, desktop and phone), builds the canvas with the real tools/canvas.py
from fixtures/ca-08/canvas.json (no session, no comments), serves it on its own
port and records: the first group, a wheel pan down, Ctrl + wheel zooming into
a phone shot, Fit all, then Changed only. Writes docs/img/ca-08.webp,
near-lossless 20: lossy q70 leaves faint trails here, near-lossless 40 is over
the 600 KB cap.

The before/now view is not in the clip: the viewer does not show a shot's
`previous` image today, so the manifest marks what changed and nothing more.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from termcast import Serve  # noqa: E402
from encode import encode  # noqa: E402

FIX = REPO / "tools/promo/fixtures/ca-08"
VIEW = (1200, 750)


def build(site):
    src = site / "src"
    src.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(FIX / "draw_screens.py"), str(src)], check=True,
                   stdout=subprocess.DEVNULL)
    (src / "canvas.json").write_text((FIX / "canvas.json").read_text())
    # CLAUDE_ANNOTATE_UPDATED stops tools/canvas.py from updating this checkout first.
    env = dict(os.environ, CLAUDE_ANNOTATE_UPDATED="1")
    subprocess.run([sys.executable, str(REPO / "tools/canvas.py"), "check", str(src / "canvas.json")],
                   check=True, env=env, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(REPO / "tools/canvas.py"), "build", str(src / "canvas.json"),
                    "--out", str(site / "out")], check=True, env=env, stdout=subprocess.DEVNULL)
    return site / "out"


def wheel(r, dy, steps, ctrl=False):
    """`steps` wheel events of `dy` each at the cursor, one frame after each."""
    if ctrl:
        r.page.keyboard.down("Control")
    for _ in range(steps):
        r.page.mouse.wheel(0, dy)
        r.settle(0.06)
        r.shot()
    if ctrl:
        r.page.keyboard.up("Control")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19163)
    a = ap.parse_args()
    site = scratch_root() / "site" / "ca-08"
    out_dir = build(site)
    out = frames_dir("ca-08")
    with Serve(out_dir, a.port) as srv, Recorder(out, viewport=VIEW, fps=12) as r:
        r.goto(srv.url("/index.html"))
        r.settle(0.8)
        r.pos = (700, 520)
        r.page.mouse.move(*r.pos)                # the wheel goes where the pointer is
        r.shot()
        r.hold(1.2)                              # the first group, desktop and phone
        wheel(r, 90, 8)                          # wheel pans down to Browse
        box = r.page.locator("button.shot").nth(5).bounding_box()   # board 3's phone shot
        r.glide((box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.3), seconds=0.5)
        wheel(r, -60, 3, ctrl=True)              # Ctrl + wheel zooms round the pointer
        r.hold(0.9)
        r.click("[data-zoom=fit]", seconds=0.6)  # Fit all: every board in the window
        r.run(0.3)
        r.hold(1.3)
        r.click("#chg-only", seconds=0.6)        # Changed only: three boards remain
        r.run(0.3)
        r.hold(2.2)
    info = encode(out, REPO / "docs/img/ca-08.webp", width=800, near_lossless=20)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
