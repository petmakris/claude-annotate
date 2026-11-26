# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-05-talk.py: Talk to the page. The word and the picture arrive together.

A real /talk call plays an invented answer about shop-app's checkout retry:
a sequence board, a before-and-after board with its verdict, and a code board
that points at three ranges of api/retry.py. tools/talk_render/render.py does
the playing (its own talk server, the silent stand-in voice, no microphone,
no Azure); this script only adds a shot at the start of each sentence, so the
lit word and the caption move along, and taps the Key points chip at the end.

    uv run tools/promo/clips/ca-05-talk.py [--daemon-port 19140] [--talk-port 19150]

Its own webcompanion daemon on a scratch HOME, its own talk-server port; both
stopped by PID. Writes docs/img/ca-05.webp.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
KIT = HERE.parents[1]
REPO = HERE.parents[3]
sys.path.insert(0, str(KIT))
from rec import frames_dir, scratch_root  # noqa: E402

FIX = KIT / "fixtures"
CLIP_W = 800
TOTAL_MS = 10000


def render_child(argv):
    """Runs inside the scratch HOME: render.py with two additions, then exits."""
    sys.path.insert(0, str(REPO / "tools" / "talk_render"))
    import render  # noqa: E402

    port = int(os.environ["CA05_TALK_PORT"])
    render.free_port = lambda: port

    orig_moments = render.moments_of

    def moments_of(view, entry):
        """render.py's moments (each board and point), plus two shots in every
        sentence (its first word and a word past its middle), so the lit word
        and the caption move along with the voice."""
        import re
        out = orig_moments(view, entry)
        text = entry.get("text", "")
        starts = [0] + [m.end() for m in re.finditer(r"[.!?][)\]\"']*\s+", text)] + [len(text)]
        extra = []
        for s0, s1 in zip(starts, starts[1:]):
            if s1 - s0 < 2:
                continue
            mid = text.find(" ", s0 + int((s1 - s0) * 0.55))
            for at in (s0, mid if 0 < mid < s1 else None):
                if at is None:
                    continue
                t = render.time_of(entry, at + (1 if at != s0 else 0)) + 0.05
                if any(abs(t - m["t"]) < 0.4 for m in out + extra):
                    continue
                extra.append({"t": t, "what": "say", "cue": None,
                              "caption": render.sentence_at(text, s0), "board": {}})
        out = sorted(out + extra, key=lambda m: m["t"])
        return out

    render.moments_of = moments_of

    orig_play = render.play_through

    def play_through(page, shooter, prefix, width, theme, *a, **kw):
        orig_play(page, shooter, prefix, width, theme, *a, **kw)
        if prefix != "d":
            return
        chip = page.locator("text=Key points").first
        chip.click()
        page.wait_for_timeout(1500)
        shooter.shot(page, prefix, "keys", 0.0, "(Key points)", {"title": "Key points", "kind": "keys"},
                     width, theme)

    render.play_through = play_through

    # desktop shots at device scale 2, so the text stays crisp once scaled to 800 px
    from playwright.sync_api._generated import Browser
    orig_ctx = Browser.new_context

    def new_context(self, **kw):
        if not kw.get("is_mobile"):
            kw.setdefault("device_scale_factor", 2)
        return orig_ctx(self, **kw)

    Browser.new_context = new_context
    sys.argv = ["render.py"] + argv
    sys.exit(render.main())


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        return render_child(sys.argv[2:])
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon-port", type=int, default=19140)
    ap.add_argument("--talk-port", type=int, default=19150)
    ap.add_argument("--keep-render", action="store_true", help="reuse the last render, only re-encode")
    a = ap.parse_args()
    from daemon import Daemon
    from encode import encode

    sc = scratch_root()
    home = sc.parent / "home-ca-05"
    code = sc / "work" / "ca-05" / "shop-app"
    rdir = sc / "render" / "ca-05"
    if not a.keep_render:
        code.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["sh", str(FIX / "shop-app" / "make_repo.sh"), str(code)], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(code), "checkout", "-q", "checkout-retry"], check=True)
        uv_cache = os.environ.get("UV_CACHE_DIR") or os.path.expanduser("~/.cache/uv")
        with Daemon(home, a.daemon_port) as d:
            env = d.env({"CA05_TALK_PORT": str(a.talk_port), "UV_CACHE_DIR": uv_cache})
            cmd = ["uv", "run", "--quiet", "--with", "playwright", "python", str(HERE), "--child",
                   "--repo", str(REPO), "--answer", str(FIX / "ca-05" / "answer.txt"),
                   "--code", str(code), "--out", str(rdir), "--topic", "shop-app checkout",
                   "--question", "What happens when a card charge times out?",
                   "--pace", "0.8", "--no-phone", "--no-dark"]
            p = subprocess.run(cmd, env=env)
            forget_all(d)
            if p.returncode:
                sys.exit("render failed; see %s" % rdir)
    assemble(rdir, frames_dir("ca-05"))
    info = encode(frames_dir("ca-05"), REPO / "docs" / "img" / "ca-05.webp", width=CLIP_W)
    print(json.dumps(info))


CROP = (0, 0, 1060, 900)    # CSS px: the stage and its caption bar, without the call panel


def forget_all(d):
    """Forget every session this clip's daemon holds (render.py has ended them)."""
    for ws in sorted((d.state / "workspaces").glob("*/*")):
        d.run(["webcompanion", "forget", "--sid", ws.name, "--force"], check=False)


def assemble(rdir: Path, out: Path):
    """render.py's desktop shots, in order, as rec.py frames with a delay each.

    Each shot is cropped to the stage and the caption bar under it (the call
    panel beside it is too small to read at 800 px). Delays follow the voice,
    a long sentence stays longer, squeezed into about TOTAL_MS. The first
    frames carry the one caption: the call reads the answer aloud, and an
    animated WebP has no sound."""
    import shutil
    from PIL import Image, ImageDraw, ImageFont
    shots = [f for f in json.loads((rdir / "frames.json").read_text()) if f["file"].startswith("d")]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ts = [s["t"] for s in shots[:-1]]
    spans = [ts[i + 1] - ts[i] if i + 1 < len(ts) else 1.5 for i in range(len(ts))] + [1.5]
    weight = [max(0.5, sp) ** 0.5 for sp in spans]
    scale = (TOTAL_MS - 2200) / sum(weight)
    font = None
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if Path(f).exists():
            font = ImageFont.truetype(f, 30)
            break
    frames = []
    for i, s in enumerate(shots):
        im = Image.open(rdir / s["file"]).convert("RGB")
        k = im.width / 1440
        im = im.crop(tuple(int(v * k) for v in CROP))
        if i < 6:
            dr = ImageDraw.Draw(im, "RGBA")
            text = "Read aloud on the call (this loop is silent)"
            w = dr.textlength(text, font=font) + 48
            x0, y0 = im.width - w - 36, im.height - 92
            dr.rounded_rectangle([x0, y0, x0 + w, y0 + 58], radius=29, fill=(17, 24, 39, 235))
            dr.text((x0 + 24, y0 + 12), text, font=font, fill=(255, 255, 255))
        name = "f%04d.png" % i
        im.save(out / name)
        ms = int(weight[i] * scale)
        if i == 0:
            ms += 700
        if i == len(shots) - 1:
            ms += 1500
        frames.append({"file": name, "ms": max(240, ms)})
    (out / "frames.json").write_text(json.dumps({"fps": 12, "scale": 2, "frames": frames}, indent=1))


if __name__ == "__main__":
    main()
