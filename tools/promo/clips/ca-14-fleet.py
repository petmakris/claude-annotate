# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-14-fleet.py: every session on two machines, a search by meaning, the backlog, Tools, the phone.

The page is the real fleet page (`fleet ui` from this checkout) on the invented two-machine world of
`fixtures/fleet/world.py`: `laptop` serves it, `build-box` answers through a fake ssh, every session, member,
to-do, skill and hook is made up, and nothing outside the scratch folder is read. "Search by meaning" asks the
world's stub `claude`, which answers from the invented sessions (scripted: no model runs).

The phone beat is the same page at a 390 px wide viewport; its frames are centred on a grey ground so every
frame of the clip has one size.

    uv run tools/promo/clips/ca-14-fleet.py [--port 19160]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from encode import encode  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "tools" / "promo" / "fixtures" / "fleet" / "world.py"
OUT = ROOT / "docs" / "img" / "ca-14.webp"
W, H = 1100, 720
PHONE = (390, 720)
TOKEN = "promo-token-0123456789abcdefghij"   # world.py's made-up token


def tab(r, name):
    r.click(f"#tabs >> text={name}", seconds=0.5)
    r.settle(1.2)


def pad_phone(out: Path, names):
    """Centre the phone frames on a grey ground of the desktop frame's size."""
    from PIL import Image
    meta = json.loads((out / "frames.json").read_text())
    first = Image.open(out / meta["frames"][0]["file"]).convert("RGB")
    big = first.size
    # A shade off the page's own ground: where a pixel equals the frame before, the encoder keeps it as see-through,
    # and lossy alpha then lets the desktop frame show through faintly. A ground that differs everywhere stops that.
    colour = tuple(max(0, c - 6) for c in first.getpixel((4, first.height - 4)))
    for n in names:
        im = Image.open(out / n).convert("RGB")
        ground = Image.new("RGB", big, colour)
        ground.paste(im, ((big[0] - im.width) // 2, 0))
        ground.save(out / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19160)
    a = ap.parse_args()
    scratch = scratch_root() / "ca-14"
    scratch.mkdir(parents=True, exist_ok=True)
    py = [sys.executable, str(WORLD), str(scratch)]
    subprocess.run(py + ["--port", str(a.port)], check=True, stdout=subprocess.DEVNULL)
    out = frames_dir("ca-14")
    phone = []
    try:
        with Recorder(out, viewport=(W, H), fps=12) as r:
            r.goto(f"http://127.0.0.1:{a.port}/login?t={TOKEN}")
            r.page.wait_for_selector("#s-rows .s-row, #s-rows [data-key], #s-rows > *", timeout=15000)
            r.settle(1.5)
            r.pos = (W * 0.55, H * 0.8)
            r.shot(); r.hold(1.0)
            # search by meaning
            r.page.focus("#s-q")
            r.type("the checkout retry work", cps=36)
            r.click("#s-meaning", seconds=0.4)
            r.page.wait_for_selector("#s-found:not([hidden])", timeout=15000)
            r.settle(0.6)
            r.shot(); r.hold(1.3)
            r.page.locator("#s-clear").click()  # off camera: the phone shows the whole list
            # members and the backlog
            tab(r, "Fleet")
            r.shot(); r.hold(0.4)
            r.glide((W * 0.5, H * 0.6), seconds=0.3)
            r.scroll(330, seconds=0.6)
            r.hold(1.0)
            # tools: the summary, then one finding opened
            tab(r, "Tools")
            r.shot(); r.hold(0.3)
            r.click("#tt-findings >> text=Same name from several providers", seconds=0.6)
            r.settle(0.5)
            r.shot(); r.hold(1.2)
            # the phone layout: Sessions as cards at 390 px
            r.hide_cursor()
            r.page.set_viewport_size({"width": PHONE[0], "height": PHONE[1]})
            r.page.locator("#tabs >> text=Sessions").click()
            r.page.evaluate("window.scrollTo(0, 0)")
            r.settle(1.2)
            phone.append(r.shot()); r.hold(1.6)
    finally:
        subprocess.run(py + ["--stop"], stdout=subprocess.DEVNULL)
    pad_phone(out, phone)
    info = encode(out, OUT, width=800)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
