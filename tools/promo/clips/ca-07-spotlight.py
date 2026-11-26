# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-07-spotlight.py: Spotlight walks an invented Orders screen part by part.

    uv run tools/promo/clips/ca-07-spotlight.py [--port 19162]

Draws the invented shop-app screen (fixtures/ca-07/draw_screen.py), builds the
page with the real skills/spotlight/build.py from fixtures/ca-07/spotlight.json,
serves it on its own port and records: the opening part, Next (the first ring
and its dashed line), two Right-arrow presses (ring, line and progress bar move),
then the same page in a 560 px window, where it stacks. Near-lossless, so
no faint trails stay where the ring and the cursor were. Writes docs/img/ca-07.webp.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from termcast import Serve  # noqa: E402
from encode import encode  # noqa: E402

FIX = REPO / "tools/promo/fixtures/ca-07"
VIEW = (1040, 650)
NARROW = 560


def build(site):
    site.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(FIX / "draw_screen.py"), str(site)], check=True,
                   stdout=subprocess.DEVNULL)
    (site / "spotlight.json").write_text((FIX / "spotlight.json").read_text())
    subprocess.run([sys.executable, str(REPO / "skills/spotlight/build.py"), str(site / "spotlight.json")],
                   check=True, stdout=subprocess.DEVNULL)
    return "orders-spotlight.html"


def pad_narrow(out, first):
    """Frames from `first` on were taken in the narrow window: centre each on a
    full-width backdrop with a window edge, so every frame has the same size."""
    from PIL import Image, ImageDraw
    meta = json.loads((out / "frames.json").read_text())
    W, H = VIEW[0] * 2, VIEW[1] * 2
    for f in meta["frames"][first:]:
        p = out / f["file"]
        im = Image.open(p).convert("RGB")
        bg = Image.new("RGB", (W, H), "#d9dee6")
        x = (W - im.width) // 2
        bg.paste(im, (x, 0))
        d = ImageDraw.Draw(bg)
        d.rectangle([x - 4, 0, x - 1, H], fill="#b4bcc8")
        d.rectangle([x + im.width, 0, x + im.width + 3, H], fill="#b4bcc8")
        bg.save(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19162)
    a = ap.parse_args()
    site = scratch_root() / "site" / "ca-07"
    page = build(site)
    out = frames_dir("ca-07")
    with Serve(site, a.port) as srv, Recorder(out, viewport=VIEW, fps=12) as r:
        r.goto(srv.url("/" + page))
        r.page.wait_for_function("window.spotlightPage")
        r.settle(0.6)
        r.pos = (760, 470)
        r.shot()
        r.hold(1.1)
        r.click("#next", seconds=0.6)          # part 2: the first ring and the dashed line
        r.hold(1.4)
        r.hide_cursor()
        r.press("ArrowRight", after=0.5)       # part 3
        r.hold(1.3)
        r.press("ArrowRight", after=0.5)       # part 4: the progress bar is full
        r.hold(1.4)
        first_narrow = len(r.frames)
        r.page.set_viewport_size({"width": NARROW, "height": VIEW[1]})
        r.settle(0.6)
        r.shot()                               # stacked: the text sits under the screen
        r.hold(1.9)
    pad_narrow(out, first_narrow)
    info = encode(out, REPO / "docs/img/ca-07.webp", width=800, near_lossless=40)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
