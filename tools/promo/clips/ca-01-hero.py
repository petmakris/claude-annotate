# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-01 (hero): comment on one part, and only that part is rewritten.

    uv run tools/promo/clips/ca-01-hero.py [--port 19120]

Scripted: the Claude side of the round (ca-01_round.py). Everything the page
does is the real page.
"""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("round_", Path(__file__).with_name("ca-01_round.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

FX = R.KIT / "fixtures/ca-01"
COMMENT = "40M rows, not 2M - run this as an online job"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=R.PORT)
    a = ap.parse_args()
    with R.Stage("ca-01", a.port) as s:
        url = s.push(FX / "plan.v1.blocks.json", first=True)
        s.watch()
        with R.Recorder(R.frames_dir("ca-01"), viewport=(1040, 760), fps=12) as r:
            p = r.page
            r.goto(url)
            r.settle(1.2)
            p.evaluate("window.scrollTo(0, 268)")
            r.settle(0.5)
            r.pos = (760, 420)
            r.shot()
            r.hold(0.4)
            # select the wrong number, press c, type the correction
            R.select_words(r, p.locator("strong", has_text="2 million rows").first, seconds=0.6, drag_frames=5)
            r.hold(0.25)
            r.press("c", after=0.6)
            r.hold(0.2)
            r.type(COMMENT, cps=48)
            r.hold(0.3)
            r.click(p.get_by_role("button", name="Add to round"), seconds=0.45, ring_frames=3)
            r.hold(0.3)
            r.click(p.locator("button", has_text="Submit round").first, seconds=0.5, ring_frames=3)
            event = s.round_event()
            assert COMMENT in str(event), event
            s.claude_reads()
            r.run(0.4, every=0.2)
            r.glide((960, 700), 0.4)
            r.hold(0.25)
            # the scripted rewrite, through the same CLI call Claude makes
            s.push(FX / "plan.v2.blocks.json")
            r.settle(1.2)
            r.shot()
            r.hold(0.3)
            s.claude_done()
            R.wait_idle(r)
            r.settle(1.5)
            r.shot()
            r.hold(1.5)
    R.finish("ca-01", width=880, cap_kb=600, out_name="hero.webp", near_lossless=40)


if __name__ == "__main__":
    main()
