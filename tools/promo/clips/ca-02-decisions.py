# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-02: pick an option, change your mind, submit the round (decisions part).

    uv run tools/promo/clips/ca-02-decisions.py [--port 19120]

Scripted: the Claude side of the round (ca-01_round.py).
"""
import argparse
import importlib.util
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("round_", Path(__file__).with_name("ca-01_round.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

FX = R.KIT / "fixtures/ca-02"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=R.PORT)
    a = ap.parse_args()
    with R.Stage("ca-02", a.port) as s:
        url = s.push(FX / "v1.blocks.json", first=True)
        s.watch()
        with R.Recorder(R.frames_dir("ca-02"), viewport=(960, 820), fps=12) as r:
            p = r.page
            button = lambda name: p.get_by_role("button", name=re.compile(name)).first
            r.goto(url)
            r.settle(1.2)
            r.pos = (780, 740)
            r.shot()
            r.hold(0.9)
            r.click(button("See other ways"), seconds=0.5, ring_frames=3, after=0.4)
            r.hold(0.5)
            r.click(button("Pick this one instead"), seconds=0.55, ring_frames=3, after=0.7)
            r.hold(1.0)
            r.click(button("Change my mind"), seconds=0.5, ring_frames=3, after=0.7)
            r.hold(0.5)
            r.click(button("Go with Claude"), seconds=0.5, ring_frames=3, after=0.7)
            r.hold(0.8)
            r.click(p.locator("button", has_text="Submit round").first, seconds=0.55, ring_frames=3)
            event = s.round_event()
            assert "Online job after the release" in str(event) or "Choose a" in str(event), event
            s.claude_reads()
            r.run(0.4, every=0.2)
            r.glide((900, 750), 0.35)
            r.hold(0.3)
            s.push(FX / "v2.blocks.json")
            r.settle(1.2)
            s.claude_done()
            R.wait_idle(r)
            r.settle(1.5)
            r.shot()
            r.hold(1.8)
        print("EVENT", event)
    R.finish("ca-02", width=800, cap_kb=600, near_lossless=40)


if __name__ == "__main__":
    main()
