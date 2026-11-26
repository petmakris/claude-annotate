# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-06-stage.py: Stage. One page of boards that fills as you work.

The real stage page (the clip's own webcompanion daemon) above a terminal.
Each command is typed into the terminal, then run for real in a pty (its
output is what it printed), and the stage changes because of it: an empty
stage, a code board, a deck file, a table, a sequence. Then the deck file is
saved from the terminal while another board is in front, and the stage's
‹ arrow steps back to the deck to show it reloaded.

    uv run tools/promo/clips/ca-06-stage.py [--daemon-port 19141] [--page-port 19152]

Writes docs/img/ca-06.webp. The daemon and the page server are stopped by
PID; every session the daemon holds is forgotten at the end.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
KIT = HERE.parents[1]
REPO = HERE.parents[3]
sys.path.insert(0, str(KIT))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from termcast import Serve, capture, read_cast, xterm_dir  # noqa: E402
from daemon import Daemon  # noqa: E402
from encode import encode  # noqa: E402
from rekey import load_map, rekey_text  # noqa: E402

FIX = KIT / "fixtures"
VIEW = (1100, 720)
STAGE_H = 500

COMMANDS = [
    "stage link",
    'stage show login "code:web/login.ts:1-8 highlight 2-6"',
    "stage show deck slides/deck.html",
    "stage show ports table:- < notes/ports.md",
    "stage show checkout sequence:- < notes/checkout.json",
    "sed -i s/Monday/Thursday/ slides/deck.html",
]

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>stage</title>
<link rel="stylesheet" href="xterm.css">
<style>
 html,body{margin:0;background:#f3f4f6;height:100%%;overflow:hidden}
 #stage{display:block;width:100%%;height:%(stage_h)spx;border:0;background:#e9eaee}
 .empty{height:%(stage_h)spx;display:grid;place-items:center;color:#8c959f;font:15px system-ui,sans-serif;background:#e9eaee}
 .term{position:absolute;left:0;right:0;top:%(stage_h)spx;bottom:0;background:#fbfbfa;border-top:1px solid #d0d7de;
       padding:10px 16px;box-sizing:border-box}
</style></head><body>
<div id="holder"><div class="empty">no stage yet</div></div>
<div class="term"><div id="t"></div></div>
<script src="xterm.js"></script>
<script>
const term = new Terminal({cols: 104, rows: 10, fontSize: 15, cursorBlink: false,
  fontFamily: "'DejaVu Sans Mono', Menlo, monospace",
  theme: {background: '#fbfbfa', foreground: '#1f2328', cursor: '#1f2328'}});
term.open(document.getElementById('t'));
window.feed = (s) => new Promise(r => term.write(s, r));
window.openStage = (url) => new Promise(r => {
  const f = document.createElement('iframe'); f.id = 'stage'; f.src = url; f.onload = () => r();
  const h = document.getElementById('holder'); h.innerHTML = ''; h.append(f);
});
</script></body></html>"""


def build_project(root: Path) -> Path:
    proj = root / "shop-app"
    subprocess.run(["sh", str(FIX / "shop-app" / "make_repo.sh"), str(proj)], check=True,
                   stdout=subprocess.DEVNULL)
    (proj / "slides").mkdir()
    (proj / "notes").mkdir()
    shutil.copy(FIX / "ca-06" / "deck.html", proj / "slides" / "deck.html")
    shutil.copy(FIX / "ca-06" / "ports.md", proj / "notes" / "ports.md")
    shutil.copy(FIX / "ca-06" / "checkout.json", proj / "notes" / "checkout.json")
    # `stage` on the PATH is the skill's own CLI, so the typed line is what ran
    bindir = root / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "stage").write_text('#!/bin/sh\nexec python3 "%s" "$@"\n' % (REPO / "skills" / "stage" / "stage.py"))
    os.chmod(bindir / "stage", 0o755)
    return proj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon-port", type=int, default=19141)
    ap.add_argument("--page-port", type=int, default=19152)
    a = ap.parse_args()
    sc = scratch_root()
    # termcast.xterm_dir() defaults to a .scratch folder under the current folder (the checkout)
    os.environ.setdefault("PROMO_XTERM_DIR", str(sc / "xterm"))
    work = sc / "work" / "ca-06"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    proj = build_project(work)
    home = sc.parent / "home-ca-06"
    site = sc / "site" / "ca-06"
    site.mkdir(parents=True, exist_ok=True)
    for name in ("xterm.js", "xterm.css"):
        shutil.copy(xterm_dir() / name, site / name)
    (site / "index.html").write_text(PAGE % {"stage_h": STAGE_H})
    casts = sc / "casts" / "ca-06"
    casts.mkdir(parents=True, exist_ok=True)
    out = frames_dir("ca-06")
    swaps = load_map(FIX / "ca-06" / "rekey.txt")

    with Daemon(home, a.daemon_port) as d, Serve(site, a.page_port) as srv, \
            Recorder(out, viewport=VIEW, fps=12) as r:
        env = d.env()
        env["PATH"] = str(work / "bin") + os.pathsep + env["PATH"]
        env["PS1"] = "$ "
        r.pos = (VIEW[0] * 0.55, STAGE_H * 0.6)
        r.hide_cursor()
        r.goto(srv.url("/"))
        r.shot()
        r.hold(0.3)
        for i, cmd in enumerate(COMMANDS):
            r.page.evaluate("s => feed(s)", "$ ")
            for k in range(0, len(cmd), 10):
                r.page.evaluate("s => feed(s)", cmd[k:k + 10])
                r.shot()
            cast = casts / ("%d.cast" % i)
            code = capture(cast, ["sh", "-c", cmd], cols=104, rows=10, cwd=str(proj), env=env, shown=cmd)
            if code:
                sys.exit("ca-06: `%s` failed (%d); see %s" % (cmd, code, cast))
            _, events = read_cast(cast)
            output = "".join(e[2] for e in events if e[1] == "o")
            # the terminal names the host (localhost), not its loopback number
            r.page.evaluate("s => feed(s)", "\r\n" + rekey_text(output, swaps))
            if i == 0:
                url = output.strip().splitlines()[-1].strip()
                r.page.evaluate("u => openStage(u)", url)
            r.settle(1.2)
            r.shot()
            r.hold(0.35 if i else 0.7)
        r.page.evaluate("s => feed(s)", "$ ")
        r.shot()
        r.hold(0.9)                       # the orange dot on "Board 4 of 4"
        r.show_cursor()
        back = (22, 20)                   # the stage's ‹ in its 40 px header
        r.glide(back, 0.6)
        r.click(None, ring_frames=3, after=0.5)
        r.hold(0.3)
        r.click(None, ring_frames=3, after=0.7)
        r.hold(1.6)                       # the deck, reloaded: "on Thursday"
        for ws in sorted((d.state / "workspaces").glob("*/*")):
            d.run(["webcompanion", "forget", "--sid", ws.name, "--force"], check=False)
    info = encode(out, REPO / "docs" / "img" / "ca-06.webp", width=800)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
