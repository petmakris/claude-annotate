# /// script
# requires-python = ">=3.9"
# ///
"""termcast.py: capture a real terminal run once, then replay it in a browser page.

A terminal clip is never typed by hand. `capture` runs the real command once,
on made-up data, in a pseudo-terminal, and keeps every byte it printed with
the time it came (an asciicast v2 file). `rekey.py` may swap names in that
file afterwards; counts, times and exit codes stay as the run printed them.
`page` writes an HTML page that replays the file in xterm.js, and rec.py
records that page like any other, so terminal and browser clips share one
cursor, one codec and one look.

    uv run tools/promo/termcast.py capture out.cast --cols 92 --rows 22 -- sh -c 'git log --oneline'
    uv run tools/promo/termcast.py page out.cast .scratch/term/   # writes index.html + xterm files

The page shows the prompt `$ ` and types the command before its output (the
command line comes from the cast's `command`, typed at a steady pace, which is
the one scripted part and the shot list says so). In the page,
`window.cast.seek(t)` draws everything up to second t, and `window.cast.end`
is the length. xterm.js 5.5.0 is fetched once from jsDelivr into
`.scratch/xterm/` (or $PROMO_XTERM_DIR) and copied next to the page; nothing
is installed.

Works on Linux and macOS (the pty module is in Python's standard library).
"""
from __future__ import annotations

import argparse
import json
import os
import pty
import select
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

XTERM_VERSION = "5.5.0"
XTERM_FILES = {
    "xterm.js": f"https://cdn.jsdelivr.net/npm/@xterm/xterm@{XTERM_VERSION}/lib/xterm.js",
    "xterm.css": f"https://cdn.jsdelivr.net/npm/@xterm/xterm@{XTERM_VERSION}/css/xterm.css",
}


# ── capture ────────────────────────────────────────────────────────────
def capture(out, cmd, cols=92, rows=22, cwd=None, env=None, shown=None):
    """Run `cmd` in a pty and write an asciicast v2 file. Returns the exit code."""
    env = dict(env or os.environ)
    env.update({"TERM": "xterm-256color", "COLUMNS": str(cols), "LINES": str(rows),
                "PS1": "$ ", "CLICOLOR_FORCE": "1"})
    pid, fd = pty.fork()
    if pid == 0:
        if cwd:
            os.chdir(cwd)
        try:
            import fcntl, struct, termios
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass
        os.execvpe(cmd[0], cmd, env)
    events = []
    t0 = time.monotonic()
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 0.05)
        except InterruptedError:
            continue
        if fd in r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                data = b""
            if not data:
                break
            events.append([round(time.monotonic() - t0, 4), "o", data.decode("utf-8", "replace")])
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status >> 8
    header = {"version": 2, "width": cols, "height": rows,
              "command": shown or " ".join(shlex.quote(c) for c in cmd),
              "exit_code": code}
    with open(out, "w") as f:
        f.write(json.dumps(header) + "\n")
        for e in events:
            f.write(json.dumps(e) + "\n")
    return code


def read_cast(path):
    lines = Path(path).read_text().splitlines()
    return json.loads(lines[0]), [json.loads(l) for l in lines[1:] if l.strip()]


# ── page ───────────────────────────────────────────────────────────────
def xterm_dir() -> Path:
    env = os.environ.get("PROMO_XTERM_DIR")
    if env:
        base = Path(env)
    else:
        from rec import scratch_root  # never under the current folder: it may be the checkout
        base = scratch_root() / "xterm"
    d = base / XTERM_VERSION
    d.mkdir(parents=True, exist_ok=True)
    for name, url in XTERM_FILES.items():
        if not (d / name).exists():
            with urllib.request.urlopen(url, timeout=30) as r:
                (d / name).write_bytes(r.read())
    return d


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>terminal</title>
<link rel="stylesheet" href="xterm.css">
<style>
 html,body{margin:0;background:%(page_bg)s;}
 .win{margin:%(margin)spx;border-radius:10px;overflow:hidden;background:%(bg)s;
      box-shadow:0 10px 30px rgba(0,0,0,.25);display:inline-block}
 .bar{height:30px;background:%(bar)s;display:flex;align-items:center;padding:0 12px;gap:8px}
 .bar i{width:12px;height:12px;border-radius:50%%;display:inline-block}
 .bar span{flex:1;text-align:center;font:13px -apple-system,system-ui,sans-serif;color:%(title_fg)s;margin-right:52px}
 #t{padding:12px 14px}
</style></head><body>
<div class="win"><div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><span>%(title)s</span></div><div id="t"></div></div>
<script src="xterm.js"></script>
<script>
const CAST = %(cast)s;
const term = new Terminal({cols: CAST.width, rows: CAST.height, fontSize: %(font)s,
  fontFamily: %(family)s, cursorBlink: false, allowProposedApi: true,
  theme: %(theme)s});
term.open(document.getElementById('t'));
// The timeline: the prompt, the command typed, then the real output at its real times.
const TL = []; let t = 0;
TL.push([t, '$ ']); t += %(lead)s;
for (const ch of CAST.command) { TL.push([t, ch]); t += %(type_s)s; }
t += 0.25; TL.push([t, '\\r\\n']); t += 0.1;
const outStart = t;
for (const [et, kind, data] of CAST.events) if (kind === 'o') TL.push([outStart + et * %(speed)s, data]);
const last = TL.length ? TL[TL.length - 1][0] : 0;
TL.push([last + 0.2, %(after)s]);
let shown = 0;
window.cast = {
  end: last + 0.2,
  seek(time) {
    let buf = '';
    while (shown < TL.length && TL[shown][0] <= time) buf += TL[shown++][1];
    return new Promise(res => buf ? term.write(buf, res) : res());
  },
};
</script></body></html>
"""

THEMES = {
    "light": {"bg": "#fbfbfa", "bar": "#e8e8e6", "title_fg": "#555", "page_bg": "#ffffff",
              "theme": {"background": "#fbfbfa", "foreground": "#1f2328", "cursor": "#1f2328",
                        "black": "#24292f", "red": "#cf222e", "green": "#116329", "yellow": "#4d2d00",
                        "blue": "#0969da", "magenta": "#8250df", "cyan": "#1b7c83", "white": "#6e7781",
                        "brightBlack": "#57606a", "brightRed": "#a40e26", "brightGreen": "#1a7f37",
                        "brightYellow": "#633c01", "brightBlue": "#218bff", "brightMagenta": "#a475f9",
                        "brightCyan": "#3192aa", "brightWhite": "#8c959f"}},
    "dark": {"bg": "#0d1117", "bar": "#21262d", "title_fg": "#c9d1d9", "page_bg": "#ffffff",
             "theme": {"background": "#0d1117", "foreground": "#e6edf3", "cursor": "#e6edf3"}},
}


def page(cast_path, out_dir, title="Terminal", theme="light", font=15, speed=1.0,
         type_cps=22, margin=24, after_prompt=True):
    header, events = read_cast(cast_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in XTERM_FILES:
        shutil.copy(xterm_dir() / name, out / name)
    th = THEMES[theme]
    cast = {"width": header["width"], "height": header["height"],
            "command": header.get("command", ""), "events": events}
    html = PAGE % {
        "cast": json.dumps(cast), "title": title, "font": font,
        "family": json.dumps("'DejaVu Sans Mono', Menlo, 'SF Mono', Consolas, monospace"),
        "theme": json.dumps(th["theme"]), "bg": th["bg"], "bar": th["bar"],
        "title_fg": th["title_fg"], "page_bg": th["page_bg"], "margin": margin,
        "lead": 0.4, "type_s": round(1 / type_cps, 4), "speed": speed,
        "after": json.dumps("$ " if after_prompt else ""),
    }
    (out / "index.html").write_text(html)
    return out / "index.html"


class Serve:
    """A python http.server on `port` serving `root`, stopped by its PID."""

    def __init__(self, root, port):
        self.root, self.port = Path(root), int(port)

    def __enter__(self):
        self.p = subprocess.Popen([sys.executable, "-m", "http.server", str(self.port),
                                   "--bind", "127.0.0.1", "--directory", str(self.root)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import socket
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        return self

    def url(self, path="/"):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def __exit__(self, *exc):
        self.p.terminate()
        self.p.wait(5)
        return False


def record_cast(rec, fps=None, hold_end=1.5, start=0.0, stop=None):
    """Drive `window.cast` on rec's page one frame at a time (rec is a rec.Recorder)."""
    fps = fps or rec.fps
    end = rec.page.evaluate("window.cast.end") if stop is None else stop
    t = start
    rec.hide_cursor()
    while t <= end + 1e-6:
        rec.page.evaluate("t => window.cast.seek(t)", t)
        rec.shot(round(1000 / fps))
        t += 1 / fps
    rec.hold(hold_end)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="run a command in a pty and keep its output")
    c.add_argument("out")
    c.add_argument("--cols", type=int, default=92)
    c.add_argument("--rows", type=int, default=22)
    c.add_argument("--cwd")
    c.add_argument("--shown", help="the command line the replay types (default: the command)")
    # the command comes after `--`; main() splits it off before argparse sees it
    p = sub.add_parser("page", help="write the replay page for a cast")
    p.add_argument("cast")
    p.add_argument("out_dir")
    p.add_argument("--title", default="Terminal")
    p.add_argument("--theme", default="light", choices=sorted(THEMES))
    p.add_argument("--font", type=int, default=15)
    argv = sys.argv[1:] if argv is None else list(argv)
    cmd = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        if not cmd:
            ap.error("capture needs a command after --")
        code = capture(a.out, cmd, a.cols, a.rows, a.cwd, shown=a.shown)
        print(json.dumps({"cast": a.out, "exit_code": code}))
    else:
        print(page(a.cast, a.out_dir, a.title, a.theme, a.font))


if __name__ == "__main__":
    main()
