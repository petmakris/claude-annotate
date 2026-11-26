# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""_smoke.py: prove the kit end to end in about 2 seconds of clip.

A small local page with one button, served on its own port; the cursor glides
to the button and clicks it, the button changes. Frames and the .webp stay in
the scratch folder (rec.scratch_root()); nothing here is committed output.

    uv run tools/promo/clips/_smoke.py [--port 19110]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from termcast import Serve  # noqa: E402
from encode import encode  # noqa: E402

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{font:20px system-ui,sans-serif;background:#fafaf8;margin:0;height:100vh;display:grid;place-items:center}
.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:36px 44px;box-shadow:0 4px 18px rgba(0,0,0,.06)}
h1{font-size:24px;margin:0 0 6px} p{color:#57606a;margin:0 0 22px}
button{font:inherit;padding:10px 22px;border-radius:8px;border:1px solid #0969da;background:#fff;color:#0969da}
button.done{background:#1a7f37;border-color:#1a7f37;color:#fff}
</style></head><body><div class="card"><h1>shop-app nightly build</h1><p>3 checks waiting</p>
<button id="go" onclick="this.className='done';this.textContent='Approved ✓'">Approve build</button></div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19110)
    a = ap.parse_args()
    site = scratch_root() / "site" / "_smoke"
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(PAGE)
    out = frames_dir("_smoke")
    with Serve(site, a.port) as srv, Recorder(out, viewport=(800, 450), fps=12) as r:
        r.pos = (640, 380)
        r.goto(srv.url("/"))
        r.shot()
        r.hold(0.3)
        r.click("#go", seconds=0.8)
        r.hold(0.6)
    info = encode(out, scratch_root() / "out" / "_smoke.webp", width=800)
    print(info)


if __name__ == "__main__":
    main()
