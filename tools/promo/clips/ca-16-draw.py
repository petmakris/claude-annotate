# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-16-draw.py: sketch a login screen on the drawing pad, tap Update, the session hears it.

Everything runs on a webcompanion daemon of the clip's own (scratch HOME, its
own port); the pad is never claimed on a daemon anyone uses. `draw.py claim`
takes the pad for a made-up session id and `draw.py watch` waits for Update,
as /draw does. The recorder draws a login wireframe at a tablet viewport with
hand-like strokes (eased curves with a small seeded wobble) and taps Update
for real. The terminal inset then shows the line `draw.py watch` really
printed, with its ids swapped for short made-up ones (they are random per run
and too long for the inset), and a reply that is SCRIPTED (no model runs), as
its title bar says.

    uv run tools/promo/clips/ca-16-draw.py [--port 19145]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from daemon import Daemon, port_free  # noqa: E402
from encode import encode  # noqa: E402

DX = 310   # the sketch sits left of centre, so the terminal inset leaves it whole
SESSION = "00000000-0000-4000-8000-0000000000d1"   # a made-up Claude session id
DRAW = REPO / "skills" / "draw" / "draw.py"
REPLY = ("A sign-in screen: a title, email, password and one button.",
         "Want the button full width, and a 'Forgot password' link?")

INSET_JS = r"""
([lines]) => {
  let box = document.getElementById('__inset');
  if (!box) {
    box = document.createElement('div');
    box.id = '__inset';
    box.style.cssText = 'position:fixed;right:22px;bottom:22px;width:700px;z-index:2147483600;' +
      'border-radius:10px;overflow:hidden;box-shadow:0 10px 34px rgba(0,0,0,.35);' +
      'font:18px/1.45 "DejaVu Sans Mono",Menlo,monospace;background:#1d2128;color:#e6e6e6';
    box.innerHTML = '<div style="background:#2c313a;color:#aab1bd;font:15px system-ui,sans-serif;padding:7px 12px;' +
      'display:flex;gap:8px;align-items:center"><span style="width:11px;height:11px;border-radius:50%;background:#ef6a5e"></span>' +
      '<span style="width:11px;height:11px;border-radius:50%;background:#f5bf4f"></span>' +
      '<span style="width:11px;height:11px;border-radius:50%;background:#61c454"></span>' +
      '<span style="margin-left:8px">terminal · the session that ran /draw</span>' +
      '<span style="margin-left:auto;background:#5b4a1f;color:#ffd77a;border-radius:4px;padding:1px 7px">reply scripted</span></div>' +
      '<div id="__inset_body" style="padding:12px 16px 14px;white-space:pre-wrap"></div>';
    document.body.append(box);
  }
  document.getElementById('__inset_body').innerHTML = lines;
}
"""


def bezier_stroke(pts, rng, wobble=2.2, per=14):
    """A hand-like path through `pts`: each leg a cubic curve with slightly
    off-line control points, sampled with eased spacing, plus a small wobble."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        n = (-dy, dx)
        ln = math.hypot(*n) or 1
        n = (n[0] / ln, n[1] / ln)
        bend = rng.uniform(-0.035, 0.035) * ln
        c1 = (x0 + dx / 3 + n[0] * bend, y0 + dy / 3 + n[1] * bend)
        c2 = (x0 + 2 * dx / 3 + n[0] * bend * 0.6, y0 + 2 * dy / 3 + n[1] * bend * 0.6)
        for i in range(1, per + 1):
            t = i / per
            t = t * t * (3 - 2 * t)
            x = (1 - t) ** 3 * x0 + 3 * (1 - t) ** 2 * t * c1[0] + 3 * (1 - t) * t * t * c2[0] + t ** 3 * x1
            y = (1 - t) ** 3 * y0 + 3 * (1 - t) ** 2 * t * c1[1] + 3 * (1 - t) * t * t * c2[1] + t ** 3 * y1
            out.append((x + rng.uniform(-wobble, wobble) * 0.08, y + rng.uniform(-wobble, wobble) * 0.08))
    return out


def stroke(r, pts, rng, every=5, glide=0.2, per=14):
    pts = [(x - DX, y) for x, y in pts]
    p = r.page
    path = bezier_stroke(pts, rng, per=per)
    r.glide(pts[0], glide)
    p.mouse.move(*pts[0])
    p.mouse.down()
    for i, (x, y) in enumerate(path, 1):
        p.mouse.move(x, y)
        r.pos = (x, y)
        if i % every == 0:
            r.shot()
    p.mouse.up()
    r.shot()


def wiggle(cx, cy, w, rng, amp=6, n=7):
    """A scribbled word: a short wavy line."""
    return [(cx + w * i / n, cy + (amp if i % 2 else -amp) * rng.uniform(0.6, 1.0)) for i in range(n + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19145)
    a = ap.parse_args()
    for _ in range(120):            # daemon.py binds without SO_REUSEADDR: wait out TIME_WAIT
        if port_free(a.port):
            break
        time.sleep(1)
    home = scratch_root().parent / "home-ca-16"
    if home.exists():
        shutil.rmtree(home)
    out = frames_dir("ca-16")
    rng = random.Random(16)
    with Daemon(home, a.port) as d:
        claim = json.loads(d.run(["python3", str(DRAW), "claim", "--session", SESSION]).stdout)
        sid = claim["sid"]
        watch = subprocess.Popen(["python3", str(DRAW), "watch", "--session", SESSION], env=d.env(),
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 start_new_session=True)
        heard: list[str] = []
        threading.Thread(target=lambda: [heard.append(l.rstrip()) for l in watch.stdout], daemon=True).start()
        try:
            with Recorder(out, viewport=(1180, 820), fps=12, context_args={"has_touch": True}) as r:
                p = r.page
                r.pos = (900, 700)
                r.goto(d.url("/s/draw/"))
                r.settle(1.0)
                r.shot()
                r.hold(0.4)
                # the phone frame of a login screen, then a logo, a title, two fields, a button
                stroke(r, [(430, 150), (750, 146), (754, 690), (428, 694), (430, 150)], rng, every=12)
                circ = [(590 + 34 * math.cos(t / 24 * 2 * math.pi), 230 + 34 * math.sin(t / 24 * 2 * math.pi))
                        for t in range(25)]
                stroke(r, circ, rng, every=12, per=4)
                stroke(r, wiggle(520, 315, 140, rng), rng, every=12)
                stroke(r, [(470, 370), (712, 368), (713, 418), (469, 420), (470, 370)], rng, every=12)
                stroke(r, [(470, 450), (712, 449), (713, 499), (469, 501), (470, 450)], rng, every=12)
                stroke(r, [(500, 560), (682, 558), (684, 616), (498, 618), (500, 560)], rng, every=12)
                stroke(r, wiggle(548, 588, 90, rng, amp=4, n=5), rng, every=12)
                r.hold(0.3)
                upd = p.get_by_role("button", name=re.compile("Update"))
                r.click(upd.first, seconds=0.6, ring_frames=3, after=0.4)
                for _ in range(60):
                    if any("event_id" in l for l in heard):
                        break
                    time.sleep(0.1)
                line = next((l for l in heard if "event_id" in l), None)
                if line is None:
                    sys.exit("ca-16: the Update never reached the session's watch")
                real = line
                (scratch_root() / "ca-16-watch.txt").write_text(real + "\n")
                # the ids are random per run; shorten them for the inset (names only, as rekey.py does)
                shown = re.sub(r"sid=\S+", "sid=d1", re.sub(r"event_id=\S+", "event_id=e1", real))
                esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
                head = '<span style="color:#8fd18f">$</span> draw.py watch\n<span style="color:#9ecbff">%s</span>\n' % esc(shown)
                p.evaluate(INSET_JS, [head])
                r.shot()
                r.hold(0.4)
                text = "\n".join(REPLY)
                for i in range(0, len(text) + 1, 14):
                    p.evaluate(INSET_JS, [head + '\n<span style="color:#e0b0ff">⏺</span> ' + esc(text[:i])])
                    r.shot()
                p.evaluate(INSET_JS, [head + '\n<span style="color:#e0b0ff">⏺</span> ' + esc(text)])
                r.shot()
                r.hold(2.4)
        finally:
            watch.terminate()
            try:
                watch.wait(5)
            except subprocess.TimeoutExpired:
                watch.kill()
            ev = re.search(r"event_id=(\S+)", next((l for l in heard if "event_id" in l), "") or "")
            if ev:
                d.run(["webcompanion", "ack", "--sid", sid, "--event-id", ev.group(1)], check=False)
            f = d.run(["webcompanion", "forget", "--sid", sid, "--force"], check=False)
            print("webcompanion forget:", f.returncode, (f.stdout + f.stderr).strip()[:160])
    info = encode(out, REPO / "docs" / "img" / "ca-16.webp", width=800)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
