# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-04: a mockup whose toggles really toggle, with a comment on one row.

    uv run tools/promo/clips/ca-04-mockup.py [--port 19120]

Scripted: the Claude side of the round (ca-01_round.py).
"""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("round_", Path(__file__).with_name("ca-01_round.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

FX = R.KIT / "fixtures/ca-04"
COMMENT = "No pushes at night, please"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=R.PORT)
    a = ap.parse_args()
    with R.Stage("ca-04", a.port) as s:
        url = s.push(FX / "v1.blocks.json", first=True)
        s.watch()
        with R.Recorder(R.frames_dir("ca-04"), viewport=(960, 600), fps=11) as r:
            p = r.page
            r.goto(url)
            r.settle(1.5)
            r.pos = (800, 540)
            r.shot()
            r.hold(0.6)
            mock = p.frame_locator("iframe").first
            for target in (mock.locator("#email"), mock.locator("#push"),
                           mock.locator("button", has_text="Hourly")):
                r.click(target, seconds=0.45, ring_frames=3, after=0.35)
                r.hold(0.25)
            # a click on the row's label comments on that row only
            r.click(mock.locator("[data-annotate-id=push]"), seconds=0.6, ring_frames=3, after=0.6)
            r.hold(0.5)
            r.type(COMMENT, cps=33)
            r.hold(0.25)
            r.click(p.get_by_role("button", name="Add to round"), seconds=0.4, ring_frames=3)
            r.hold(0.5)
            r.click(p.locator("button", has_text="Submit round").first, seconds=0.45, ring_frames=3)
            event = s.round_event()
            assert event["reactions"][0]["step_id"] == "push", event
            s.claude_reads()
            r.run(0.4, every=0.2)
            r.glide((900, 530), 0.35)
            s.push(FX / "v2.blocks.json")
            r.settle(1.2)
            s.claude_done()
            R.wait_idle(r)
            r.settle(1.5)
            r.shot()
            r.hold(1.6)
        print("EVENT", event)
    R.finish("ca-04", width=800, cap_kb=300, near_lossless=40)


if __name__ == "__main__":
    main()
