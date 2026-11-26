# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-03: the still docs/img/block-sequence.png, shot again from today's page.

    uv run tools/promo/clips/ca-03-sequence-still.py [--port 19120]
"""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("round_", Path(__file__).with_name("ca-01_round.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

OUT = R.REPO / "docs/img/block-sequence.png"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=R.PORT)
    a = ap.parse_args()
    with R.Stage("ca-03-still", a.port) as s:
        url = s.push(R.KIT / "fixtures/ca-03/sequence-still.blocks.json", first=True)
        s.watch()
        with R.Recorder(R.frames_dir("ca-03-still"), viewport=(1000, 900), fps=10) as r:
            r.goto(url)
            r.settle(2.0)
            r.page.locator('section[data-block-id="section-1"]').screenshot(path=str(OUT), animations="disabled")
            r.shot()
    from PIL import Image
    im = Image.open(OUT).convert("RGB")
    # flat colours: 256 of them keep the text crisp at a third of the size
    im.quantize(256, dither=Image.Dither.NONE).save(OUT, optimize=True)
    print(OUT, im.size, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
