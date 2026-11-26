# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-15-journey.py: pin comments on a journey canvas, press Send, the batch waits for a session.

Everything runs on a webcompanion daemon of the clip's own (scratch HOME, its own
port). The invented Corner Shop screens (fixtures/ca-15/screens.html) are shot
into a canvas folder, `tools/canvas.py build` makes the canvas with a journey
session, and `journey.py register` (JOURNEY_APPS = fixtures/ca-15/apps.json)
records it as a journey canvas under the scratch HOME. The recorder pins three
comments on three boards and presses Send for real; the page then says the
batch waits for a session. `journey.py batches` afterwards proves the batch is
in the session. No Claude session is attached and nothing goes to Lungo.

    uv run tools/promo/clips/ca-15-journey.py [--port 19144] [--http 19156]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from daemon import Daemon  # noqa: E402
from termcast import Serve  # noqa: E402
from encode import encode  # noqa: E402

FIX = REPO / "tools" / "promo" / "fixtures" / "ca-15"
KEY = "shop-checkout-dana"
SCREENS = [("cart", "Cart", "Three items, one total."),
           ("checkout", "Delivery", "Address and a delivery slot."),
           ("payment", "Payment", "Card, then Pay.")]
# (board index from 0, point as fractions of the shot, words)
COMMENTS = [(0, (0.62, 0.70), "Show the delivery fee here"),
            (1, (0.72, 0.80), "Make the slot a list"),
            (2, (0.30, 0.86), "Say the total on Pay")]
SHOT = (960, 600)


def build_canvas(d: Daemon, http_port: int) -> Path:
    """Shoot the screens and build the canvas with its journey session on the own daemon."""
    from playwright.sync_api import sync_playwright
    work = scratch_root() / "work" / "ca-15"
    if work.exists():
        shutil.rmtree(work)
    canvas = work / "canvas"
    canvas.mkdir(parents=True)
    site = work / "site"
    site.mkdir()
    shutil.copy(FIX / "screens.html", site / "index.html")
    with Serve(site, http_port) as srv, sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": SHOT[0], "height": SHOT[1]}, device_scale_factor=1)
        for i, (h, _, _) in enumerate(SCREENS, 1):
            pg.goto(srv.url("/index.html#" + h))
            pg.reload()
            pg.wait_for_timeout(150)
            pg.screenshot(path=str(canvas / ("%02d-%s.png" % (i, h))))
        b.close()
    boards = [{"number": i, "title": t, "caption": c, "id": "checkout/%02d-%s" % (i, h),
               "shots": [{"label": "Desktop", "file": "%02d-%s.png" % (i, h), "width": SHOT[0], "height": SHOT[1]}]}
              for i, (h, t, c) in enumerate(SCREENS, 1)]
    manifest = {
        "title": "Corner Shop journey", "subtitle": "checkout · dana", "id": KEY,
        "meta": ["Invented shop, made-up data"],
        "session": {"kind": "journey", "slug": KEY, "cwd": str(work), "title": "Corner Shop journey · checkout-dana"},
        "comments": {"canvas": "shop", "name": "Corner Shop"},
        "board_width": 520,
        "groups": [{"name": "Checkout", "id": "checkout", "boards": boards}],
    }
    (canvas / "canvas.json").write_text(json.dumps(manifest, indent=1))
    env = {"CLAUDE_ANNOTATE_UPDATED": "1", "JOURNEY_APPS": str(FIX / "apps.json")}
    d.run(["uv", "run", "--with", "pillow", str(REPO / "tools" / "canvas.py"), "build",
           str(canvas / "canvas.json"), "--out", str(canvas)], env=env)
    d.run(["python3", str(REPO / "skills" / "journey" / "journey.py"), "register", "shop",
           "--name", "checkout-dana", "--checkout", str(work), "--canvas", str(canvas)], env=env)
    return work


def wait_port(port: int, seconds=120):
    """daemon.py checks a port by binding it without SO_REUSEADDR, so a port a
    previous run left in TIME_WAIT reads as taken for up to a minute: wait it out."""
    import time
    from daemon import port_free
    for _ in range(seconds):
        if port_free(port):
            return
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19144)
    ap.add_argument("--http", type=int, default=19156)
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    home = scratch_root().parent / "home-ca-15"
    if home.exists():
        shutil.rmtree(home)
    out = frames_dir("ca-15")
    env = {"JOURNEY_APPS": str(FIX / "apps.json")}
    wait_port(a.port)
    with Daemon(home, a.port) as d:
        build_canvas(d, a.http)
        with Recorder(out, viewport=(1024, 500), fps=12) as r:
            p = r.page
            r.goto(d.url("/s/%s/" % KEY))
            p.wait_for_selector("#c-mode", timeout=15000)
            r.settle(1.5)
            if a.probe:
                p.screenshot(path=str(scratch_root() / "ca15-probe.png"))
                print(p.evaluate("()=>document.body.innerText.slice(0,600)"))
                print(p.evaluate("()=>[...document.querySelectorAll('[data-board],[id^=board]')].slice(0,8).map(e=>e.id+' '+JSON.stringify(e.getBoundingClientRect()))"))
                return
            run_clip(r)
        batches = d.run(["python3", str(REPO / "skills" / "journey" / "journey.py"), "--json", "batches", KEY],
                        env=env).stdout
        (scratch_root() / "work" / "ca-15" / "batches.json").write_text(batches)
        got = json.loads(batches)
        n = sum(len(b.get("comments", [])) for b in got)
        print("journey.py batches:", len(got), "batch(es),", n, "comment(s)")
        if n != len(COMMENTS):
            sys.exit("ca-15: the session does not hold the batch that was sent")
        f = d.run(["webcompanion", "forget", "--sid", KEY, "--kind", "journey", "--force"], check=False)
        print("webcompanion forget:", f.returncode, (f.stdout + f.stderr).strip()[:200])
    info = encode(out, REPO / "docs" / "img" / "ca-15.webp", width=800)
    print(json.dumps(info))


def run_clip(r):
    p = r.page
    r.pos = (760, 440)
    r.shot()
    r.hold(0.7)
    r.click("#c-mode", seconds=0.5, ring_frames=3)
    for i, (fx, fy), words in COMMENTS:
        b = p.locator('img[src*="%02d-%s"]' % (i + 1, SCREENS[i][0])).first.bounding_box()
        r.click((b["x"] + b["width"] * fx, b["y"] + b["height"] * fy), seconds=0.45, ring_frames=2, after=0.3)
        p.wait_for_selector("#c-text")
        r.type(words, chars_per_frame=4)
        r.hold(0.15)
        r.press("Enter", after=0.5)
        r.hold(0.2)
    r.click("#c-send", seconds=0.5, ring_frames=3, after=0.8)
    r.settle(0.6)
    r.shot()
    r.hold(0.8)
    r.click("#s-claude", seconds=0.45, ring_frames=2, after=0.4)
    r.shot()
    r.hold(2.2)


if __name__ == "__main__":
    main()
