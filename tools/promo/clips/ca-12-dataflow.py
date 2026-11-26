# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-12-dataflow.py: hover a field and its whole route lights across three records.

    uv run tools/promo/clips/ca-12-dataflow.py [--port 19165]

Renders the dataflow skill's own public example, skills/dataflow/fields/
example-order.json (Order -> OrderDto -> order.json), with
`python -m skills.dataflow.fields.render <spec> --check <out.html>`, which also
lays the page out in a browser and fails on a bad layout. The page is served on
its own port and recorded at 1100x690:

1. the three records at rest, a rename and a fan-out on the arrows;
2. hover totalCents: the three amounts that sum into it and total_cents light,
   the rest dims;
3. hover internalNotes, a field faded because nothing carries it on: only it
   lights;
4. zoom in with +, then F fits the drawing again; the minimap's frame follows.

Every hover and key is the page's own behaviour; nothing is drawn over it.
Writes docs/img/ca-12.webp; frames and the built page stay in the scratch
folder (rec.scratch_root()).
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from termcast import Serve  # noqa: E402
from encode import encode  # noqa: E402

REPO = HERE.parents[3]
SPEC = REPO / "skills" / "dataflow" / "fields" / "example-order.json"


def node(fid):
    return '.node[data-node="%s"]' % fid


def build(site: Path):
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    out = site / "index.html"
    res = subprocess.run([sys.executable, "-m", "skills.dataflow.fields.render", str(SPEC),
                          "--check", str(out)], cwd=REPO, capture_output=True, text=True)
    print(res.stdout.strip())
    if res.returncode != 0:
        raise SystemExit("ca-12: render --check failed:\n" + res.stdout + res.stderr)
    (site / "index.png").unlink(missing_ok=True)
    return site


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19165)
    a = ap.parse_args()
    site = build(scratch_root() / "site" / "ca-12")
    out = frames_dir("ca-12")
    with Serve(site, a.port) as srv, Recorder(out, viewport=(1100, 690), fps=12) as r:
        r.pos = (560, 600)
        r.goto(srv.url("/"))
        r.settle(0.6)
        r.shot()
        r.hold(1.6)                                  # at rest: rename, fan-out, three sums
        r.glide(node("dto.total"), seconds=0.8)      # hover totalCents
        r.settle(0.2)
        r.shot()
        r.hold(1.7)
        r.glide(node("entity.notes"), seconds=0.8)   # hover a dropped field
        r.settle(0.2)
        r.shot()
        r.hold(1.3)
        r.glide((700, 560), seconds=0.6)             # off the fields: nothing lit
        r.settle(0.2)
        r.shot()
        r.hold(0.3)
        for _ in range(2):                           # zoom in, the minimap frame shrinks
            r.page.keyboard.press("+")
            r.run(0.35)
        r.hold(0.6)
        r.page.keyboard.press("f")                   # F fits the drawing again
        r.run(0.4)
        r.hold(1.4)
    info = encode(out, REPO / "docs" / "img" / "ca-12.webp", width=800)
    print(info)


if __name__ == "__main__":
    main()
