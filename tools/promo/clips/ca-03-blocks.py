# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-03: every block kind on one made-up page, on the real annotate page.

    uv run tools/promo/clips/ca-03-blocks.py [--port 19120]

Nothing is scripted but the page push: one push, then the reader looks at it.
The cuts between kinds are instant scrolls.
"""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("round_", Path(__file__).with_name("ca-01_round.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

FX = R.KIT / "fixtures/ca-03"

SCROLL_JS = """(i) => {
  const e = document.querySelector(`section[data-block-id="section-${i}"]`);
  window.scrollTo(0, e.getBoundingClientRect().top + scrollY - 14);
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=R.PORT)
    a = ap.parse_args()
    with R.Stage("ca-03", a.port) as s:
        url = s.push(FX / "v1.blocks.json", first=True)
        s.watch()
        with R.Recorder(R.frames_dir("ca-03"), viewport=(960, 640), fps=10) as r:
            p = r.page

            def part(i):
                return p.locator('section[data-block-id="section-%d"]' % i)

            def cut(i, hold):
                p.evaluate(SCROLL_JS, i)
                r.settle(0.6)
                r.shot()
                r.hold(hold)

            r.goto(url)
            r.settle(2.0)
            r.pos = (910, 560)
            # facts and explain: walk to the second note
            cut(1, 0.6)
            r.click(part(2).locator("button", has_text="›"), seconds=0.4, ring_frames=2, after=0.5)
            r.hold(0.8)
            # compare and map: follow the request two steps
            cut(3, 0.7)
            r.click(part(4).get_by_role("button", name="Follow the request"), seconds=0.4, ring_frames=2, after=0.4)
            nxt = part(4).get_by_role("button", name="Next")
            r.click(nxt, seconds=0.35, ring_frames=2, after=0.9)
            r.hold(0.2)
            r.click(nxt, seconds=0.15, ring_frames=2, after=0.9)
            r.hold(0.6)
            r.pos = (910, 560)
            cut(5, 1.1)   # sequence
            cut(6, 1.0)   # flowchart
            cut(7, 1.0)   # decisions
            cut(8, 1.0)   # jobs
            # a table: every row is its own comment target
            cut(9, 0.2)
            rows = p.locator('section[data-block-id="section-9"] tbody tr')
            for i in (0, 1):
                r.glide(rows.nth(i).locator("td").nth(1), 0.3)
                r.hold(0.1)
            r.click(rows.nth(1).locator(".row-comment"), seconds=0.4, ring_frames=2, after=0.6)
            r.hold(1.0)
    R.finish("ca-03", width=800, cap_kb=450, near_lossless=40)


if __name__ == "__main__":
    main()
