# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-11-specimen.py: a Java object with real-looking values, one explicit null, one question.

    uv run tools/promo/clips/ca-11-specimen.py [--port 19143] [--term-port 19155]

Everything the page shows is real tool output on invented data:
- fixtures/ca-11/src holds an invented shop (Order, Customer, OrderLine, Lombok
  @Data, discountCode @Nullable). It is copied into a scratch git repo and the
  real `claude-annotate specimen.extract_types Order` reads its shapes.
- fixtures/ca-11/shop-specimen.json is the populated instance (the part a
  session writes by hand), fixtures/ca-11/leaves.json an invented capture for
  the one leaf type (PaymentMethod), so one value is tagged `captured`.
- the real `specimen.push` puts it on a webcompanion daemon of the clip's own.
The recorder clicks the discountCode row's ✻, types the question and presses
Comment. A terminal inset then replays a real `webcompanion watch` run that
received that question, as the session's watcher would.

The specimen page draws no replies on its rows (a reply goes to the session's
thread), so the clip ends with the question landing in the session, not with
an answer on the page. The header, which names the scratch folder, is kept
out of frame.

Writes docs/img/ca-11.webp; frames stay in the scratch folder.
"""
import argparse
import json
import os
import shutil
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
FIX = HERE.parent / "fixtures" / "ca-11"
GIT_ID = ["-c", "user.name=Dana Example", "-c", "user.email=dana@example.com"]
ANCHOR = "com.acme.shop.Order#discountCode"
QUESTION = "why is this null for guests?"
VIEW = (960, 640)
TOP = 250          # the page is scrolled past its header to here


def make_repo(work: Path, env: dict):
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(FIX / "src", work / "src")
    e = dict(env, GIT_AUTHOR_DATE="2026-01-05T10:00:00+00:00",
             GIT_COMMITTER_DATE="2026-01-05T10:00:00+00:00")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", *GIT_ID, "add", "."],
                ["git", *GIT_ID, "commit", "-qm", "shop orders"]):
        subprocess.run(cmd, cwd=work, env=e, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19143)
    ap.add_argument("--term-port", type=int, default=19155)
    a = ap.parse_args()
    root = scratch_root()
    os.environ.setdefault("PROMO_XTERM_DIR", str(root / "xterm"))
    home = root / "home-ca-11"
    if home.exists():
        shutil.rmtree(home)
    work = root / "work" / "ca-11" / "shop-app"
    types = root / "work" / "ca-11" / "types.json"
    term_dir = root / "site" / "ca-11-term"
    out = frames_dir("ca-11")

    # daemon.py's free-port test fails while the last run's sockets sit in
    # TIME_WAIT (up to a minute); wait that out instead of failing.
    for _ in range(90):
        if port_free(a.port):
            break
        time.sleep(1)
    with Daemon(home, a.port) as d:
        env = d.env()
        make_repo(work, env)
        d.run(["claude-annotate", "specimen.extract_types", "Order",
               "--worktree", str(work), "--out", str(types)])
        sess = json.loads(d.run(["claude-annotate", "specimen.push", "--types", str(types),
                                 "--specimen", str(FIX / "shop-specimen.json"),
                                 "--cwd", str(work), "--leaves", str(FIX / "leaves.json")]).stdout)
        try:
            run(d, sess, env, term_dir, out, a.term_port)
        finally:
            d.run(["webcompanion", "forget", "--sid", sess["sid"], "--force"], check=False)

    # True lossless: lossy q70 leaves faint ghosts on this flat page.
    info = encode(out, REPO / "docs" / "img" / "ca-11.webp", width=800, near_lossless=100)
    print(json.dumps(info))


def run(d, sess, env, term_dir, out, term_port):
    with Recorder(out, viewport=VIEW, fps=12) as r:
        r.goto(d.url("/s/%s/" % sess["sid"]))
        r.page.wait_for_selector('[data-wc-anchor="%s"]' % ANCHOR)
        r.page.evaluate("y => window.scrollTo(0, y)", TOP)
        r.settle(0.3)
        row = r.page.locator('[data-wc-anchor="%s"]' % ANCHOR).first
        pay = r.page.locator('[data-wc-anchor="com.acme.shop.Order#payment"]').first
        r.pos = (VIEW[0] * 0.45, VIEW[1] * 0.55)
        r.shot()
        r.hold(0.7)
        # the captured tag, then the explicit null
        r.glide(pay.get_by_text("captured", exact=True), seconds=0.7)
        r.hold(0.5)
        r.glide(row.get_by_text("null", exact=True), seconds=0.6)
        r.hold(0.6)
        r.click(row.locator(".specimen-ask"), seconds=0.8)
        r.page.wait_for_selector("textarea.wc-composer-text")
        r.type(QUESTION, cps=36)
        r.hold(0.4)
        r.click(r.page.get_by_role("button", name="Comment"), seconds=0.6)
        r.hold(0.5)

        # The session's watcher receives the question: a real run, replayed.
        cast = term_dir.parent / "ca-11.cast"
        term_dir.mkdir(parents=True, exist_ok=True)
        shown = "webcompanion watch --kind specimen --sid %s" % sess["slug"]
        code = termcast.capture(cast, ["timeout", "2", "webcompanion", "watch", "--kind",
                                       "specimen", "--sid", sess["slug"]],
                                cols=74, rows=8, env=env, shown=shown)
        assert code == 124, code          # stopped by timeout after printing the event
        text = cast.read_text()
        assert QUESTION in text and ANCHOR in text, text
        termcast.page(cast, term_dir, title="Claude session", font=16, margin=0,
                      type_cps=48, after_prompt=False)
        with termcast.Serve(term_dir, term_port) as srv:
            r.page.evaluate("""url => {
              const f = document.createElement('iframe');
              f.id = '__inset'; f.src = url;
              f.style.cssText = 'position:fixed;left:50%;top:96px;transform:translateX(-50%);' +
                'width:744px;height:226px;border:0;border-radius:10px;z-index:99999;' +
                'box-shadow:0 14px 40px rgba(0,0,0,.35);background:#fbfbfa';
              document.body.appendChild(f);
            }""", srv.url("/index.html"))
            r.page.wait_for_timeout(800)
            tf = next(f for f in r.page.frames if f.url.startswith(srv.url("/")))
            tf.wait_for_function("!!window.cast")
            end = tf.evaluate("window.cast.end")
            r.hide_cursor()
            t = 0.0
            while t <= end + 1e-6:
                tf.evaluate("t => window.cast.seek(t)", t)
                r.shot()
                t += 1 / 12
            r.hold(2.2)


if __name__ == "__main__":
    main()
