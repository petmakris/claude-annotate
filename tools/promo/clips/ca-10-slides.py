# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-10-slides.py: the slides layout audit names an overflow, the fix re-measures clean.

    uv run tools/promo/clips/ca-10-slides.py [--port 19164]

1. Builds an invented deck (fixtures/ca-10/deck-v1.html, a copy of the skill's
   skeleton) in a scratch decks folder: SLIDES_DECKS_DIR and HOME point into the
   scratch folder, and framework/inline.py pastes in the framework and the
   default theme. `decks init --use` is never run.
2. Runs fixtures/ca-10/audit.py for real in a pty (termcast.capture): it loads
   the deck in headless Chromium and evaluates the skill's
   references/layout-audit.js as it is. Slide 2 overflows the bottom.
3. The fix is the slide split in two (fixtures/ca-10/deck-v2.html, a prepared
   edit, as the skill says: split the slide, never shrink the type). The audit
   runs again for real: every slide `"overflow": []`.
4. Records: slide 2 in present mode with its last line cut off, the first run
   in a terminal inset, the deck switching to the fixed version and the second
   run, then present mode stepping two slides.

Writes docs/img/ca-10.webp. Raw frames and the built site stay in the scratch
folder (rec.scratch_root()).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
from rec import Recorder, frames_dir, scratch_root, ease  # noqa: E402
from termcast import Serve, capture, page as cast_page  # noqa: E402
from encode import encode  # noqa: E402

REPO = HERE.parents[3]
SLIDES = REPO / "skills" / "slides"
FIX = HERE.parents[1] / "fixtures" / "ca-10"
DECK = "2026.12.03-retries"
CMD_SHOWN = "python3 audit.py %s.html" % DECK
TYPE_CPS = 60

STAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#000;overflow:hidden}
#deck{position:fixed;left:0;top:0;width:1280px;height:800px;border:0}
#term{position:fixed;left:50%;top:18px;transform:translate(-50%,-500px)}
#cut{position:fixed;display:none;border:3px dashed #e5484d;background:rgba(229,72,77,.16);box-sizing:border-box}
#cut b{position:absolute;right:12px;top:50%;transform:translateY(-50%);font:600 19px system-ui,sans-serif;color:#fff;background:#e5484d;padding:3px 10px;border-radius:6px;white-space:nowrap}
#term iframe{border:0;display:block;border-radius:10px;background:transparent}
</style></head><body>
<iframe id="deck" src="_v1.html"></iframe>
<div id="cut"><b></b></div>
<div id="term"><iframe id="t" src="t1/index.html" width="1200" height="300"></iframe></div>
</body></html>"""


def build(root: Path, port: int):
    """The scratch decks folder, the two real audit runs, the replay pages."""
    if root.exists():
        shutil.rmtree(root)
    home = root / "home"
    decks = root / "decks"
    deck_dir = decks / DECK
    home.mkdir(parents=True)
    deck_dir.mkdir(parents=True)
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright"))
    env.update({"HOME": str(home), "SLIDES_DECKS_DIR": str(decks), "SLIDES_SKILL": str(SLIDES)})
    for k in ("SLIDES_THEME", "MB_DECKS_DIR", "XDG_CONFIG_HOME"):
        env.pop(k, None)

    def inline(path):
        subprocess.run([sys.executable, str(SLIDES / "framework" / "inline.py"), str(path),
                        "--theme", "default"], env=env, check=True, stdout=subprocess.DEVNULL)

    deck_file = deck_dir / (DECK + ".html")
    shutil.copy(FIX / "deck-v1.html", deck_file)
    inline(deck_file)
    shutil.copy(deck_file, deck_dir / "_v1.html")       # the before view the clip shows
    shutil.copy(FIX / "audit.py", deck_dir / "audit.py")
    (deck_dir / "stage.html").write_text(STAGE)
    casts = []
    with Serve(deck_dir, port):
        for n, src in ((1, "deck-v1.html"), (2, "deck-v2.html")):
            if n == 2:                                   # the fix: the slide split in two
                shutil.copy(FIX / src, deck_file)
                inline(deck_file)
            cast = root / ("audit%d.cast" % n)
            code = capture(cast, [sys.executable, "audit.py", deck_file.name, "--port", str(port)],
                           cols=96, rows=7, cwd=deck_dir, env=env, shown=CMD_SHOWN)
            print("audit run %d: exit %d" % (n, code))
            casts.append(cast)
    os.environ["PROMO_XTERM_DIR"] = str(scratch_root() / "xterm")
    for n, cast in enumerate(casts, 1):
        cast_page(cast, deck_dir / ("t%d" % n), title="decks/" + DECK, theme="dark",
                  font=18, type_cps=TYPE_CPS, margin=0, after_prompt=False)
    return deck_dir


def deck_frame(r):
    return r.page.query_selector("#deck").content_frame()


def show_slide2(r):
    """Scroll the deck's own scrolling view so slide 2 sits at the top, with room under it."""
    fr = deck_frame(r)
    fr.wait_for_function("document.querySelectorAll('.slide').length > 2")
    fr.evaluate("document.querySelectorAll('.slide')[1].scrollIntoView({block: 'start'}); window.scrollBy(0, -16)")
    r.settle(0.3)
    return fr


def fit_term(r):
    """Size the inset iframe to the terminal window inside it."""
    fr = r.page.frame(url=lambda u: "/t1/" in u or "/t2/" in u)
    fr.wait_for_function("window.cast !== undefined")
    w, h = fr.evaluate("(() => { const b = document.querySelector('.win').getBoundingClientRect();"
                       " return [Math.ceil(b.width), Math.ceil(b.height)]; })()")
    r.page.evaluate("([w,h]) => { const t = document.getElementById('t'); t.width = w; t.height = h; }", [w, h])
    return fr


def slide_term(r, down: bool, frames=6):
    for i in range(1, frames + 1):
        t = ease(i / frames)
        y = -(1 - t) * 500 if down else -t * 500
        r.page.evaluate("y => document.getElementById('term').style.transform = `translate(-50%, ${y}px)`", y)
        r.shot()


def play(r, fr, hold):
    """Type the command line, cut the wait for the browser, show the real output."""
    typed_end = 0.4 + len(CMD_SHOWN) / TYPE_CPS + 0.3
    t = 0.0
    while t < typed_end:
        fr.evaluate("t => window.cast.seek(t)", t)
        r.shot()
        t += 1 / r.fps
    fr.evaluate("t => window.cast.seek(t)", typed_end)
    r.shot(200)
    fr.evaluate("t => window.cast.seek(t)", fr.evaluate("window.cast.end") + 1)
    r.shot()
    r.hold(hold)


def mark_cut(r, fr, bottom_px):
    """Outline the part of the list that runs past the slide: the list's own box,
    measured in the page, from the slide's bottom edge to the list's bottom edge.
    `bottom_px` is the overshoot the audit printed; the label says it."""
    box = fr.evaluate("""() => {
      const s = document.querySelectorAll('.slide')[1].getBoundingClientRect();
      const u = document.querySelectorAll('.slide')[1].querySelector('ul.introb').getBoundingClientRect();
      return {sl: s.left, sw: s.width, sb: s.bottom, ub: u.bottom, ul: u.left, ur: u.right};
    }""")
    r.page.evaluate("""([b, px]) => {
      const c = document.getElementById('cut');
      c.style.left = (b.ul - 8) + 'px'; c.style.width = (b.ur - b.ul + 16) + 'px';
      c.style.top = b.sb + 'px'; c.style.height = Math.max(6, b.ub - b.sb) + 'px';
      c.querySelector('b').textContent = px + ' px below the slide, cut off';
      c.style.display = 'block';
    }""", [box, bottom_px])
    return box


def last_overflow(cast):
    """The bottom overshoot of slide 2 as the real audit run printed it."""
    import json
    _, events = __import__("termcast").read_cast(cast)
    text = "".join(e[2] for e in events if e[1] == "o")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and '"slide": 2' in line:
            ov = json.loads(line)["overflow"]
            return max(o["bottom"] for o in ov) if ov else 0
    raise SystemExit("ca-10: the audit printed no line for slide 2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19164)
    a = ap.parse_args()
    root = scratch_root() / "site" / "ca-10"
    deck_dir = build(root, a.port)
    px = last_overflow(root / "audit1.cast")
    out = frames_dir("ca-10")
    with Serve(deck_dir, a.port) as srv, Recorder(out, viewport=(1280, 800), fps=12) as r:
        r.hide_cursor()
        r.goto(srv.url("/stage.html"))
        fr_deck = show_slide2(r)
        fr = fit_term(r)
        r.settle(0.4)
        r.shot()
        r.hold(0.9)                                     # slide 2: the last point stops at the edge
        slide_term(r, True)
        play(r, fr, 0.4)                                # the audit names the overflow
        mark_cut(r, fr_deck, px)
        r.shot()
        r.hold(1.6)
        # the fix: the deck now holds the split slides; the audit runs again
        r.page.evaluate("document.getElementById('cut').style.display = 'none'")
        r.page.evaluate("document.getElementById('deck').src = '%s.html'" % DECK)
        r.page.evaluate("document.getElementById('t').src = 't2/index.html'")
        r.settle(1.0)
        fr_deck = show_slide2(r)
        fr = fit_term(r)
        r.settle(0.3)
        play(r, fr, 1.0)                                # clean
        slide_term(r, False)
        # present mode: F, then two slides on
        fr_deck.evaluate("window.focus()")
        r.page.keyboard.press("f")
        r.settle(0.5)
        r.shot()
        r.hold(0.5)
        for hold in (0.8, 1.2):
            r.page.keyboard.press("ArrowRight")
            r.settle(0.4)
            r.shot()
            r.hold(hold)
    info = encode(out, REPO / "docs" / "img" / "ca-10.webp", width=800)
    print(info)


if __name__ == "__main__":
    main()
