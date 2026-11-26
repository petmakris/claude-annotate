# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-09-deck.py: click one bullet of a deck, say "shorter", and one line changes.

    uv run tools/promo/clips/ca-09-deck.py [--port 19142] [--term-port 19154]

Stages an invented six-slide deck (fixtures/ca-09/checkout-retry.html) in a
scratch git repo, pushes it with the real `claude-annotate deck.push --watch`
to a webcompanion daemon of its own (scratch HOME, own port), and records the
real deck page in Slide view: a click on a bullet, the comment "shorter",
Send to Claude, the busy banner. The edit is scripted: the one-line change
Claude makes when it handles that comment (the deck skill's handling-comments
reference), written to the file on disk. The real `--watch` re-pushes it and
the real page repaints the slide. Then a real `git diff` in that repo,
captured in a pty, plays in a terminal inset.

Writes docs/img/ca-09.webp; frames stay in the scratch folder.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from daemon import Daemon, port_free  # noqa: E402
from encode import encode  # noqa: E402
import termcast  # noqa: E402

REPO = HERE.parents[2]
FIX = HERE.parent / "fixtures" / "ca-09" / "checkout-retry.html"
OLD = ("    <li>When the gateway times out, checkout waits two seconds and sends the same "
       "payment again, with the same idempotency key so the card is never charged twice.</li>")
NEW = "    <li>On a gateway timeout, retry once with the same idempotency key.</li>"
GIT_ID = ["-c", "user.name=Dana Example", "-c", "user.email=dana@example.com"]
VIEW = (1200, 750)


def make_repo(work: Path, env: dict) -> Path:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    deck = work / "checkout-retry.html"
    shutil.copy(FIX, deck)
    e = dict(env, GIT_AUTHOR_DATE="2026-01-05T10:00:00+00:00",
             GIT_COMMITTER_DATE="2026-01-05T10:00:00+00:00")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", *GIT_ID, "add", "."],
                ["git", *GIT_ID, "commit", "-qm", "checkout retry deck"]):
        subprocess.run(cmd, cwd=work, env=e, check=True)
    return deck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19142)
    ap.add_argument("--term-port", type=int, default=19154)
    a = ap.parse_args()
    root = scratch_root()
    os.environ.setdefault("PROMO_XTERM_DIR", str(root / "xterm"))
    home = root / "home-ca-09"
    if home.exists():
        shutil.rmtree(home)
    work = root / "work" / "ca-09" / "checkout-retry"
    term_dir = root / "site" / "ca-09-term"
    out = frames_dir("ca-09")

    # daemon.py's free-port test fails while the last run's sockets sit in
    # TIME_WAIT (up to a minute); wait that out instead of failing.
    for _ in range(90):
        if port_free(a.port):
            break
        time.sleep(1)
    with Daemon(home, a.port) as d:
        env = d.env()
        deck = make_repo(work, env)
        assert OLD in deck.read_text(), "fixture changed: the bullet to edit is gone"
        watch = subprocess.Popen(
            ["claude-annotate", "deck.push", "--deck", str(deck), "--cwd", str(work),
             "--title", "checkout-retry", "--watch"],
            env=env, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            buf = ""
            while not buf.rstrip().endswith("}"):
                line = watch.stdout.readline()
                if not line:
                    sys.exit("deck.push ended before printing its session")
                buf += line
            sess = json.loads(buf)
            run(d, sess, deck, work, env, term_dir, out, a.term_port)
        finally:
            watch.send_signal(signal.SIGTERM)
            watch.wait(5)
            d.run(["webcompanion", "forget", "--sid", sess["sid"], "--force"], check=False)

    info = encode(out, REPO / "docs" / "img" / "ca-09.webp", width=800, near_lossless=100)  # true lossless: lossy and --lossless (which keeps -mixed) leave ghosts of the popup
    print(json.dumps(info))


def run(d, sess, deck, work, env, term_dir, out, term_port):
    with Recorder(out, viewport=VIEW, fps=12) as r:
        r.context.add_init_script("try{localStorage.setItem('claude-deck-view','slide')}catch(e){}")
        r.goto(d.url("/s/%s/#slide-4" % sess["sid"]))
        r.settle(1.0)
        frame = next(f for f in r.page.frames if "content.html" in f.url and "slide-4" in f.url)
        li = frame.locator(".bullets li").first
        box = li.bounding_box()
        r.pos = (VIEW[0] * 0.72, VIEW[1] * 0.86)
        r.shot()
        r.hold(1.0)
        r.click((box["x"] + box["width"] * 0.35, box["y"] + 18), seconds=0.8)
        r.page.wait_for_selector("#deckpop textarea")
        r.hold(0.3)
        r.type("shorter", cps=14)
        r.hold(0.4)
        r.click("#deckpop button.send", seconds=0.6)
        r.hold(0.6)
        # Scripted: the one-line edit Claude makes for this comment.
        deck.write_text(deck.read_text().replace(OLD, NEW))
        # The real --watch re-pushes (it polls every 0.5 s) and the page repaints.
        t0 = time.monotonic()
        while r.page.locator("#deckbusy").count() and time.monotonic() - t0 < 10:
            r.page.wait_for_timeout(100)
        r.settle(0.6)
        r.shot()
        r.hold(1.6)

        # A real git diff, captured once in a pty, replayed in an inset.
        cast = term_dir.parent / "ca-09.cast"
        term_dir.mkdir(parents=True, exist_ok=True)
        tenv = dict(env, GIT_PAGER="cat", PAGER="cat")
        code = termcast.capture(cast, ["git", "-c", "color.ui=always", "diff", "-U0"],
                                cols=78, rows=11, cwd=str(work), env=tenv, shown="git diff -U0")
        assert code == 0
        termcast.page(cast, term_dir, title="checkout-retry", font=16, margin=0,
                      type_cps=16, after_prompt=False)
        with termcast.Serve(term_dir, term_port) as srv:
            r.page.evaluate("""url => {
              const f = document.createElement('iframe');
              f.id = '__inset'; f.src = url;
              f.style.cssText = 'position:fixed;left:50%;bottom:44px;transform:translateX(-50%);' +
                'width:812px;height:286px;border:0;border-radius:10px;z-index:99999;' +
                'box-shadow:0 14px 40px rgba(0,0,0,.35);background:#fbfbfa';
              document.body.appendChild(f);
            }""", srv.url("/index.html"))
            r.page.wait_for_timeout(800)
            tf = next(f for f in r.page.frames if f.url.startswith(srv.url("/")))
            tf.wait_for_function("window.cast && window.term !== undefined || window.cast")
            end = tf.evaluate("window.cast.end")
            r.hide_cursor()
            t = 0.0
            while t <= end + 1e-6:
                tf.evaluate("t => window.cast.seek(t)", t)
                r.shot()
                t += 1 / 12
            r.hold(2.6)


if __name__ == "__main__":
    main()
