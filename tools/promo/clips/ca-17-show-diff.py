# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-17: show-diff, every changed file of a branch in one scroll.

    uv run tools/promo/clips/ca-17-show-diff.py     # records docs/img/ca-17.webp

Linux only: needs VS Code (/usr/share/code), Xvfb, webcompanion, img2webp.
Everything the clip runs lives in /tmp/promo-ca17 (a fixed path, so that no
home folder shows in a frame) and is removed at the end: a scratch HOME, a
throwaway VS Code profile with only this repo's extension, the shop-app repo,
and a webcompanion daemon of its own. VS Code is driven through its remote
debugging port, so only its own window is captured, never a desktop.

show-diff.sh is the real script. It calls macOS `open` and `code`, so two
small wrappers on its PATH send both to the throwaway profile.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PROMO = Path(__file__).resolve().parents[1]
REPO_ROOT = PROMO.parents[1]
sys.path.insert(0, str(PROMO))
import rec as reclib            # noqa: E402
import termcast                 # noqa: E402
from daemon import Daemon, holder, port_free   # noqa: E402
from encode import encode       # noqa: E402

RUN = Path("/tmp/promo-ca17")
HOME = RUN / "home"
SHOP = RUN / "shop-app"
USER_DATA = RUN / "profile"
EXTENSIONS = RUN / "extensions"
BIN = RUN / "bin"
CODE = "/usr/share/code/code"
CODE_CLI = "/usr/share/code/bin/code"
DAEMON_PORT, DEBUG_PORT, TERM_PORT = (int(os.environ.get(k, d)) for k, d in
    (("CA17_DAEMON_PORT", 19180), ("CA17_DEBUG_PORT", 19181), ("CA17_TERM_PORT", 19182)))
VIEW = (960, 600)
HOP_1, HOP_2 = 470, 630    # wheel distance of the two scrolls
FIXTURES = PROMO / "fixtures"
OWN = FIXTURES / "ca-17"
TITLE = "shop-app · checkout-retry vs main"

SETTINGS = {
    "chat.disableAIFeatures": True, "workbench.startupEditor": "none",
    "workbench.secondarySideBar.defaultVisibility": "hidden", "update.mode": "none",
    "telemetry.telemetryLevel": "off", "workbench.tips.enabled": False,
    "window.commandCenter": False, "workbench.layoutControl.enabled": False,
    "extensions.ignoreRecommendations": True, "git.openRepositoryInParentFolders": "never",
    "security.workspace.trust.enabled": False, "editor.minimap.enabled": False,
    "workbench.colorTheme": "Default Dark Modern", "editor.fontSize": 14,
    "diffEditor.wordWrap": "on", "editor.wordWrap": "on", "diffEditor.renderSideBySide": False,
    "comments.openView": "never", "window.titleBarStyle": "custom",
    "workbench.editor.showTabs": "single", "breadcrumbs.enabled": False,
}

# VS Code refuses innerHTML (Trusted Types), so the kit's cursor is built here
# node by node under the same ids; the kit's script then finds it and only moves it.
CURSOR_NODES_JS = r"""
() => {
  if (document.getElementById('__promo_cursor')) return;
  const NS = 'http://www.w3.org/2000/svg';
  const c = document.createElement('div');
  c.id = '__promo_cursor';
  c.style.cssText = 'position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;pointer-events:none;display:none;';
  const s = document.createElementNS(NS, 'svg');
  s.setAttribute('width', '24'); s.setAttribute('height', '24'); s.setAttribute('viewBox', '0 0 24 24');
  const p = document.createElementNS(NS, 'path');
  p.setAttribute('d', 'M3 2 L3 19 L7.5 14.8 L10.6 21.6 L13.6 20.3 L10.6 13.6 L16.6 13.6 Z');
  p.setAttribute('fill', '#111'); p.setAttribute('stroke', '#fff'); p.setAttribute('stroke-width', '1.6');
  s.appendChild(p); c.appendChild(s);
  const r = document.createElement('div');
  r.id = '__promo_ring';
  r.style.cssText = 'position:fixed;left:0;top:0;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;border:3px solid #e8590c;z-index:2147483646;pointer-events:none;display:none;';
  document.body.append(r, c);
}
"""


class Stage:
    """Xvfb, the clip's daemon and a throwaway VS Code, each stopped by PID."""

    def __enter__(self):
        self.procs, self.daemon, self.pw = [], None, None
        try:
            self._up()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _spawn(self, cmd, log, **kw):
        p = subprocess.Popen(cmd, stdout=open(RUN / log, "ab"), stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True, **kw)
        self.procs.append(p)
        return p

    def _up(self):
        for port in (DAEMON_PORT, DEBUG_PORT, TERM_PORT):
            if not port_free(port):
                sys.exit("ca-17: port %d is taken: %s" % (port, holder(port)))
        if RUN.exists():
            sys.exit("ca-17: %s exists; another run, or a leftover to remove" % RUN)
        for d in (HOME, USER_DATA / "User", EXTENSIONS, BIN):
            d.mkdir(parents=True)
        self.owns_run = True
        (USER_DATA / "User" / "settings.json").write_text(json.dumps(SETTINGS, indent=1))
        pkg = json.loads((REPO_ROOT / "vscode-plugin" / "package.json").read_text())
        ext = EXTENSIONS / ("%s.%s-%s" % (pkg["publisher"], pkg["name"], pkg["version"]))
        for part in ("src", "themes"):
            shutil.copytree(REPO_ROOT / "vscode-plugin" / part, ext / part)
        shutil.copy(REPO_ROOT / "vscode-plugin" / "package.json", ext)
        (ext / "dist" / "markdown-themes").mkdir(parents=True)
        (ext / "dist" / "markdown-themes" / "active.css").write_text("")
        subprocess.run(["sh", str(FIXTURES / "shop-app" / "make_repo.sh"), str(SHOP)],
                       check=True, capture_output=True)

        r, w = os.pipe()
        self._spawn(["Xvfb", "-displayfd", str(w), "-screen", "0", "2400x1600x24", "-nolisten", "tcp"],
                    "xvfb.log", pass_fds=(w,))
        os.close(w)
        with os.fdopen(r) as f:
            display = ":" + f.readline().strip()

        self.daemon = Daemon(HOME, DAEMON_PORT).start()
        (BIN / "code").write_text('#!/bin/sh\nexec %s --user-data-dir=%s --extensions-dir=%s "$@"\n'
                                  % (CODE_CLI, USER_DATA, EXTENSIONS))
        (BIN / "open").write_text('#!/bin/sh\nexec %s/code --open-url "$1" >/dev/null 2>&1\n' % BIN)
        for f in BIN.iterdir():
            f.chmod(0o755)
        self.env = self.daemon.env({"DISPLAY": display})
        self.env["PATH"] = str(BIN) + os.pathsep + self.env["PATH"]
        for k in list(self.env):
            if k.startswith("VSCODE_") or k.startswith("CLAUDE_CODE"):
                self.env.pop(k)

        self._spawn([CODE, "--no-sandbox", "--user-data-dir=%s" % USER_DATA,
                     "--extensions-dir=%s" % EXTENSIONS, "--disable-workspace-trust",
                     "--skip-welcome", "--skip-release-notes", "--disable-telemetry",
                     "--disable-updates", "--disable-gpu", "--password-store=basic",
                     "--force-device-scale-factor=2", "--remote-debugging-port=%d" % DEBUG_PORT,
                     str(SHOP)], "code.log", env=self.env)
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        for _ in range(60):
            try:
                self.browser = self.pw.chromium.connect_over_cdp("http://127.0.0.1:%d" % DEBUG_PORT)
                pages = [p for c in self.browser.contexts for p in c.pages if "workbench" in p.url]
                if pages:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            sys.exit("ca-17: VS Code did not come up")
        self.page = pages[0]
        self.page.set_viewport_size({"width": VIEW[0], "height": VIEW[1]})
        self.page.wait_for_timeout(8000)

    def show_diff(self, out_cast=None):
        """Run the real show-diff.sh; answer VS Code's one-time URI question."""
        cmd = ["bash", str(REPO_ROOT / "skills" / "show-diff" / "show-diff.sh"),
               str(SHOP), "main", "checkout-retry", TITLE]
        log = RUN / "show-diff.out"
        if out_cast:
            code = ("import sys; sys.path.insert(0, %r); import termcast; "
                    "sys.exit(termcast.capture(%r, %r, cols=92, rows=24, env=%r, shown=%r))"
                    % (str(PROMO), str(out_cast), cmd, self.env,
                       "show-diff.sh shop-app main checkout-retry"))
            p = subprocess.Popen([sys.executable, "-c", code], stdout=open(log, "wb"), stderr=subprocess.STDOUT)
        else:
            p = subprocess.Popen(cmd, env=self.env, stdout=open(log, "wb"), stderr=subprocess.STDOUT)
        end = time.time() + 150
        while p.poll() is None:
            if time.time() > end:
                p.kill()
                sys.exit("ca-17: show-diff.sh did not finish")
            self.allow_uri()
            self.page.wait_for_timeout(500)
        self.allow_uri()
        if p.returncode:
            sys.exit("ca-17: show-diff.sh failed: " + log.read_text())
        return log.read_text()

    def allow_uri(self):
        """A fresh profile asks before an extension opens a URI. Tick and open."""
        btn = self.page.get_by_role("button", name="Open", exact=True)
        if btn.count():
            box = self.page.get_by_text("Do not ask me again for this extension")
            if box.count():
                box.first.click()
            btn.first.click()
            self.page.wait_for_timeout(500)

    def __exit__(self, *exc):
        if self.pw:
            try:
                self.browser.close()
            except Exception:
                pass
            self.pw.stop()
            self.pw = None
        for p in reversed(self.procs):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)    # the group this script started
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
        if self.daemon:
            self.daemon.stop()
        if getattr(self, "owns_run", False):
            logs = reclib.scratch_root() / "ca-17-logs"
            logs.mkdir(parents=True, exist_ok=True)
            for f in list(RUN.glob("*.log")) + list(RUN.glob("*.out")) + list(RUN.glob("*.cast")):
                shutil.copy(f, logs / f.name)
            time.sleep(1)
            shutil.rmtree(RUN, ignore_errors=True)
        return False


def comment_session(s, cast):
    text = "".join(e[2] for e in termcast.read_cast(cast)[1])
    return re.search(r"WC_SID=(\S+)", text).group(1)


def wait_event(s, sid):
    events = s.daemon.state / "workspaces" / "show-diff" / sid / "state" / "events"
    for _ in range(50):
        found = sorted(events.glob("*.json"))
        if found:
            return found[0].stem
        s.page.wait_for_timeout(200)
    sys.exit("ca-17: the question did not reach the daemon")


class TwoPageRecorder(reclib.Recorder):
    """The kit's recorder on pages this script owns: first a headless terminal
    replay, then VS Code's own window over its debugging port."""

    def __init__(self, out_dir, **kw):
        super().__init__(out_dir, viewport=VIEW, **kw)

    def __enter__(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.save()
        return False


def terminal_part(s, r, cast):
    """The real run, replayed: the command is typed, then its output. The wait
    while VS Code opens (about 16 s) is cut."""
    site = RUN / "term"
    os.environ.setdefault("PROMO_XTERM_DIR", str(reclib.scratch_root() / "xterm"))
    termcast.page(cast, site, title="Terminal", theme="dark", font=15, type_cps=48,
                  margin=24, after_prompt=True)
    browser = s.pw.chromium.launch()
    page = browser.new_page(viewport={"width": VIEW[0], "height": VIEW[1]}, device_scale_factor=2)
    with termcast.Serve(site, TERM_PORT) as web:
        page.goto(web.url("/index.html"), wait_until="networkidle")
        page.add_style_tag(content="html,body{background:#181818!important}"
                           ".win{display:block;width:fit-content;margin:24px auto}")
        r.page = page
        r.hide_cursor()
        typed = 0.4 + len("show-diff.sh shop-app main checkout-retry") / 48
        t = 0.0
        while t <= typed:
            page.evaluate("t => window.cast.seek(t)", t)
            r.shot(round(1000 / r.fps))
            t += 1 / r.fps
        page.evaluate("window.cast.seek(window.cast.end)")
        page.wait_for_timeout(300)
        r.shot()
        r.hold(0.9)
    browser.close()


def line_top(page, text):
    loc = page.locator(".view-line", has_text=text)
    box = loc.first.bounding_box() if loc.count() else None
    return box["y"] if box else None


def vscode_part(s, r, cast):
    page = s.page
    page.evaluate(CURSOR_NODES_JS)
    page.evaluate(reclib.CURSOR_JS)
    r.page = page
    page.mouse.move(700, 330)
    r.pos = (700, 330)
    r.show_cursor()
    r.shot()
    r.hold(0.9)
    # two hops down the one scroll: into payments.py, then to retry.py
    r.scroll(HOP_1, 0.6)
    r.hold(0.4)
    r.scroll(HOP_2, 0.7)
    page.wait_for_timeout(500)
    r.shot()
    r.hold(0.3)
    top = line_top(page, "except PaymentDeclined:")
    if top is None or not 150 < top < 420:
        sys.exit("ca-17: the line to ask about is not in view (top=%r); tune HOP_2" % top)
    # the gutter's comment marker on that line, found where VS Code drew it
    x = page.evaluate("""top => [...document.querySelectorAll('.comment-range-glyph')]
        .map(e => e.getBoundingClientRect())
        .filter(b => b.height > 0 && Math.abs(b.y - top) < 4).map(b => b.x + b.width / 2)[0]""", top)
    if x is None:
        sys.exit("ca-17: no comment marker beside the line")
    r.click((x + 1, top + 9.5), seconds=0.7, after=1.0)
    page.wait_for_timeout(600)
    r.shot()
    question = (OWN / "question.txt").read_text().strip()
    r.type(question, chars_per_frame=6)
    r.hold(0.3)
    r.click(page.get_by_role("button", name="Ask Claude"), seconds=0.4, after=1.2)
    r.shot()
    r.hold(0.5)
    sid = comment_session(s, cast)
    event = wait_event(s, sid)
    asked = json.loads(s.daemon.run(["webcompanion", "event", "--sid", sid, "--event-id", event]).stdout)
    if asked["anchor"] != "api/retry.py:R:11" or asked["text"] != question:
        sys.exit("ca-17: the daemon got %r" % asked)
    print("daemon got:", json.dumps(asked))
    # The one scripted part: Claude's answer, posted with the command Claude uses.
    s.daemon.run(["webcompanion", "reply", "--sid", sid, "--anchor", asked["anchor"],
                  "--text", str(OWN / "answer.md")])
    s.daemon.run(["webcompanion", "ack", "--sid", sid, "--event-id", event])
    page.get_by_text("Today the clause changes nothing").first.wait_for(timeout=10000)
    r.glide((880, 540), 0.5)
    page.wait_for_timeout(500)
    r.shot()
    r.hold(2.0)


def record():
    frames = reclib.frames_dir("ca-17")
    out = REPO_ROOT / "docs" / "img" / "ca-17.webp"
    with Stage() as s:
        cast = RUN / "show-diff.cast"
        s.show_diff(out_cast=cast)
        s.page.wait_for_timeout(3000)
        with TwoPageRecorder(frames, fps=10) as r:
            terminal_part(s, r, cast)
            vscode_part(s, r, cast)
    info = encode(frames, out, width=800)
    print(json.dumps(info))
    if info["bytes"] > 450 * 1024:
        sys.exit("ca-17: over the 450 KB cap")


if __name__ == "__main__":
    record()
