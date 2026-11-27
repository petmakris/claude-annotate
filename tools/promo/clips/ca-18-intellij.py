# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow", "pyobjc-framework-Quartz; sys_platform == 'darwin'"]
# ///
"""ca-18: the IntelliJ half. A walkthrough with a question, a question on a PR diff line,
the smart diff key walking one file back, and the app map over the editor.

    uv run tools/promo/clips/ca-18-intellij.py      # records docs/img/ca-18.webp

macOS or Linux. Needs IntelliJ IDEA (CA18_IDE: the .app on macOS, else ~/Applications or
/Applications; the unpacked tar's folder on Linux), webcompanion, img2webp, JDK 25 for the
two Gradle builds. On Linux also Xvfb and ImageMagick's import: the IDE runs on a virtual
display of its own at scale 2, with the macOS keymap the plugin's keys are bound in.

Everything runs in /tmp/promo-ca18 (a fixed path, so no home folder shows in a frame):
a scratch HOME, a clone of this repo the plugin is built from (commit first: the clone
holds only committed code), the invented shop repo (fixtures/ca-18), a webcompanion
daemon of its own, and a second IntelliJ with its own config, system and plugin folders,
so the IntelliJ a person uses is never touched. The IDE gets two plugins: this repo's
and ide-driver (tools/promo/ide-driver), a test-only plugin that runs actions and posts
clicks into the IDE's own event queue over HTTP on 127.0.0.1. On macOS the IDE stays a
background app the whole time: no OS mouse or keyboard input, so the person at the machine
can keep working. Each frame is the IDE window and its popups, captured window by window
(screencapture -l), never the screen. On Linux the virtual display holds only the IDE, so
a frame is that display cut to the IDE window.

What is staged and what is real is in docs/SHOTLIST.md, ca-18.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROMO = Path(__file__).resolve().parents[1]
REPO_ROOT = PROMO.parents[1]
sys.path.insert(0, str(PROMO))
from daemon import Daemon, holder, port_free   # noqa: E402
from encode import encode                       # noqa: E402

RUN = Path("/tmp/promo-ca18")
HOME = RUN / "home"
LINUX = sys.platform.startswith("linux")
# macOS reports /tmp as /private/tmp; the IDE and git must agree on the path.
SHOP = RUN / "shop" if LINUX else Path("/private/tmp/promo-ca18/shop")
IDE_DIR = RUN / "ide"
FRAMES = RUN / "frames"
FIX = PROMO / "fixtures" / "ca-18"
OUT = REPO_ROOT / "docs" / "img" / "ca-18.webp"
DAEMON_PORT = int(os.environ.get("CA18_DAEMON_PORT", 19190))
DRIVER_PORT = int(os.environ.get("CA18_DRIVER_PORT", 19191))
FRAME_BOUNDS = (80, 60, 960, 640)               # points; captured at 2x
PKG = "checkout/src/main/java/com/acme/shop/checkout"
DISPLAY = os.environ.get("CA18_DISPLAY", ":77")    # Linux: the virtual display
CA = str(REPO_ROOT / "bin" / "claude-annotate")

UNIFIED_BUTTON = (862, 88)      # the diff toolbar's one-column button, frame points at 960x640

STEPS_QUESTION = "How does checkout survive a card charge that times out?"
WT_QUESTION = "What if the first charge went through?"
WT_ANSWER = ("Then the retry is harmless. It sends the same key, so the gateway returns "
             "the first charge's result and charges nothing new.")
AD_QUESTION = "Why is the key made outside the loop?"
AD_ANSWER = ("So every attempt sends the **same** key. The gateway charges a key once, so if "
             "the first attempt reached it and only the answer timed out, the retry gets that "
             "first result back instead of charging the card twice.")


def badge_font():
    if not LINUX:
        return "/System/Library/Fonts/SFNS.ttf"
    # A sans font that has the key signs ⌘ ⌥ ⇧.
    return subprocess.run(["fc-match", "-f", "%{file}", "Inter:charset=2318 2325 21e7"],
                          capture_output=True, text=True, check=True).stdout


def ide_app() -> Path:
    if LINUX:
        p = os.environ.get("CA18_IDE")
        if p and (Path(p) / "bin" / "idea").is_file():
            return Path(p)
        sys.exit("ca-18: set CA18_IDE to the unpacked IntelliJ IDEA folder")
    for p in (os.environ.get("CA18_IDE"), "~/Applications/IntelliJ IDEA.app", "/Applications/IntelliJ IDEA.app"):
        if p and Path(p).expanduser().is_dir():
            return Path(p).expanduser()
    sys.exit("ca-18: no IntelliJ IDEA.app (set CA18_IDE)")


# The plugin's action ids, read from its plugin.xml (one prefix for all of them).
ACTION_PREFIX = re.search(r'<action id="([\w.]+)\.\w+"',
                          (REPO_ROOT / "ide-plugin/src/main/resources/META-INF/plugin.xml").read_text()).group(1)


def act(name):
    return f"{ACTION_PREFIX}.{name}"


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


# ── the driver ─────────────────────────────────────────────────────────
def drive(path, **q):
    url = f"http://127.0.0.1:{DRIVER_PORT}/{path}" + ("?" + urllib.parse.urlencode(q) if q else "")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"ca-18: driver {path} {q}: {e.read().decode()[:600]}")


def action(aid, **q):
    return drive("action", id=aid, **q)


# ── frames ─────────────────────────────────────────────────────────────
class Film:
    """One PNG per beat: the IDE window with its popups pasted in place, then a drawn
    pointer and a key badge on top. A hold is a longer delay, not more frames."""

    def __init__(self, pid):
        self.pid = pid
        self.font = badge_font()
        self.frames = []
        self.n = 0
        FRAMES.mkdir(parents=True, exist_ok=True)
        for f in FRAMES.glob("*.png"):
            f.unlink()

    def grab(self):
        return self.grab_linux() if LINUX else self.grab_mac()

    def grab_linux(self):
        from PIL import Image
        import io
        for _ in range(8):
            fr = next((l for l in drive("windows").splitlines() if l.startswith("com.intellij.openapi.wm.impl.IdeFrameImpl")), "")
            got = tuple(int(fr.split(k + "=")[1].split(",")[0].rstrip("]")) for k in ("x", "y", "width", "height")) if fr else None
            if got != FRAME_BOUNDS:
                x, y, w, h = FRAME_BOUNDS
                drive("frame", x=x, y=y, w=w, h=h)
                time.sleep(0.6)
                continue
            png = subprocess.run(["import", "-display", DISPLAY, "-window", "root", "png:-"],
                                 capture_output=True, check=True).stdout
            x, y, w, h = FRAME_BOUNDS
            return Image.open(io.BytesIO(png)).convert("RGBA").crop((x * 2, y * 2, (x + w) * 2, (y + h) * 2))
        sys.exit("ca-18: the IDE frame keeps another size: %s" % fr)

    def grab_mac(self):
        import Quartz
        from PIL import Image
        for _ in range(8):
            wins = [w for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly,
                                                                 Quartz.kCGNullWindowID)
                    if w["kCGWindowOwnerPID"] == self.pid and w["kCGWindowBounds"]["Height"] > 40]
            # The project frame is the window of FRAME_BOUNDS' size; some popups carry
            # the frame's title too, so the title alone picks the wrong one.
            frame = next((w for w in wins if (w["kCGWindowBounds"]["Width"], w["kCGWindowBounds"]["Height"])
                          == FRAME_BOUNDS[2:]), None)
            if frame is None:           # the IDE restored another size; set it again
                x, y, w, h = FRAME_BOUNDS
                drive("frame", x=x, y=y, w=w, h=h)
                time.sleep(0.6)
                continue
            fb = frame["kCGWindowBounds"]

            def shot(w):
                # None when the window closed between the listing and the capture.
                fd, f = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                r = subprocess.run(["screencapture", "-x", "-o", "-l", str(w["kCGWindowNumber"]), f],
                                   capture_output=True)
                try:
                    return Image.open(f).convert("RGBA") if r.returncode == 0 else None
                except OSError:
                    return None
                finally:
                    os.unlink(f)
            base = shot(frame)
            if base is None or base.width != fb["Width"] * 2:
                time.sleep(0.3)
                continue
            ok = True
            for w in reversed(wins):            # the list is front first
                if w is frame:
                    continue
                b = w["kCGWindowBounds"]
                im = shot(w)
                if im is None:
                    ok = False
                    break
                base.alpha_composite(im, (round((b["X"] - fb["X"]) * 2), round((b["Y"] - fb["Y"]) * 2)))
            if not ok:
                time.sleep(0.3)
                continue
            return base
        sys.exit("ca-18: could not capture the IDE window; its windows: %s" % [
            (w.get("kCGWindowName"), dict(w["kCGWindowBounds"])) for w in wins])

    def shot(self, ms, key=None, pointer=None, ring=False, settle=0.35):
        from PIL import ImageDraw, ImageFont
        time.sleep(settle)
        im = self.grab()
        d = ImageDraw.Draw(im)
        if pointer:
            x, y = pointer[0] * 2, pointer[1] * 2
            if ring:
                d.ellipse((x - 26, y - 26, x + 26, y + 26), outline=(255, 214, 10, 255), width=5)
            arrow = [(x, y), (x, y + 44), (x + 11, y + 33), (x + 20, y + 52), (x + 28, y + 48),
                     (x + 19, y + 30), (x + 33, y + 30)]
            d.polygon(arrow, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=3)
        if key:
            cap, label = key
            f1 = ImageFont.truetype(self.font, 44)
            f2 = ImageFont.truetype(self.font, 36)
            w1 = d.textlength(cap, font=f1)
            w2 = d.textlength(label, font=f2)
            W = w1 + w2 + 110
            x0 = (im.width - W) / 2
            y0 = im.height - 190
            d.rounded_rectangle((x0, y0, x0 + W, y0 + 92), 22, fill=(20, 22, 26, 235), outline=(255, 214, 10, 255), width=3)
            d.rounded_rectangle((x0 + 18, y0 + 14, x0 + 18 + w1 + 34, y0 + 78), 12, fill=(255, 214, 10, 255))
            d.text((x0 + 35, y0 + 46), cap, font=f1, fill=(20, 22, 26, 255), anchor="lm")
            d.text((x0 + 18 + w1 + 34 + 22, y0 + 46), label, font=f2, fill=(240, 240, 240, 255), anchor="lm")
        name = "f%03d.png" % self.n
        self.n += 1
        im.convert("RGB").save(FRAMES / name)
        self.frames.append({"file": name, "ms": ms})

    def save(self):
        (FRAMES / "frames.json").write_text(json.dumps({"frames": self.frames}))


# ── setup ──────────────────────────────────────────────────────────────
def build_plugins(app: Path):
    clone = RUN / "repo"
    if not clone.exists():
        sh(["git", "clone", "-q", str(REPO_ROOT), str(clone)])
    sh(["git", "-C", str(clone), "pull", "-q", "--ff-only"])
    sh(["./gradlew", "-q", "buildPlugin"], cwd=clone / "ide-plugin")
    sh(["./gradlew", "-q", "buildPlugin", f"-PlocalIdePath={app}"], cwd=PROMO / "ide-driver")
    # A fresh folder: unpacking over an older build leaves its jar beside the new
    # one, and the IDE may load the old classes.
    plugins = IDE_DIR / "plugins"
    shutil.rmtree(plugins, ignore_errors=True)
    plugins.mkdir(parents=True)
    newest = max((clone / "ide-plugin" / "build" / "distributions").glob("claude-ide-review-*.zip"),
                 key=lambda z: z.stat().st_mtime)
    for z in (newest, PROMO / "ide-driver" / "build" / "distributions" / "promo-ide-driver-0.1.zip"):
        sh(["unzip", "-q", "-o", str(z), "-d", str(plugins)])
    if LINUX:
        # IntelliJ on Linux ships no macOS keymap, and the plugin binds its keys only
        # there; JetBrains' own "macOS Keymap" plugin adds it.
        z = RUN / "macos-keymap.zip"
        if not z.exists():
            build = json.loads((app / "product-info.json").read_text())
            urllib.request.urlretrieve(
                "https://plugins.jetbrains.com/pluginManager?action=download&id=com.intellij.plugins.macoskeymap"
                f"&build={build['productCode']}-{build['buildNumber']}", z)
        sh(["unzip", "-q", "-o", str(z), "-d", str(plugins)])


def ide_config(app: Path):
    for d in ("config/options", "system", "plugins", "log"):
        (IDE_DIR / d).mkdir(parents=True, exist_ok=True)
    (IDE_DIR / "idea.properties").write_text("".join(
        f"idea.{k}.path={IDE_DIR / k}\n" for k in ("config", "system", "plugins", "log")))
    vm = (app / ("bin/idea64.vmoptions" if LINUX else "Contents/bin/idea.vmoptions")).read_text()
    # Linux: draw at scale 2 like a Retina Mac, so the frames are as sharp.
    hidpi = ("-Dsun.java2d.uiScale.enabled=true", "-Dsun.java2d.uiScale=2") if LINUX else ()
    vm += "".join(f"\n{o}" for o in (*hidpi,
        f"-Duser.home={HOME}", "-Didea.trust.all.projects=true", "-Djb.consents.confirmation.enabled=false",
        "-Djb.privacy.policy.text=<!--999.999-->", "-Didea.initially.ask.config=never",
        "-Dide.show.tips.on.startup.default.value=false")) + "\n"
    (IDE_DIR / "idea.vmoptions").write_text(vm)
    c = IDE_DIR / "config"
    # The AI chat, the feature trainer and full-line completion add panels and hints
    # that are not this plugin's; balloons and the update check add notices.
    (c / "disabled_plugins.txt").write_text(
        "com.intellij.air\ntraining\norg.jetbrains.completion.full.line\ncom.jetbrains.station\n")
    opts = {
        "notifications.xml": '<component name="NotificationConfiguration" showBalloons="false" systemNotifications="false" />',
        "editor-font.xml": '<component name="DefaultFont"><option name="FONT_SIZE" value="17" /><option name="FONT_SIZE_2D" value="17.0" /></component>',
        "updates.xml": '<component name="UpdatesConfigurable"><option name="CHECK_NEEDED" value="false" /></component>',
    }

    for name, comp in opts.items():
        f = c / "options" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"<application>{comp}</application>\n")


def app_map():
    am = HOME / ".config" / "claude-annotate" / "app-map"
    (am / "shop").mkdir(parents=True, exist_ok=True)
    shutil.copy(PROMO / "fixtures" / "ca-13" / "source.json", am / "shop" / "source.json")
    env = dict(os.environ, APP_MAP_HOME=str(am))
    for cmd in ("check", "build"):
        r = subprocess.run([CA, "app_map.app_map", cmd, "shop", "--repo", str(SHOP)], env=env,
                           capture_output=True, text=True)
        if not json.loads(r.stdout)["ok"]:
            sys.exit(f"ca-18: app_map {cmd} failed: {r.stdout}")


def start_ide(app: Path):
    env = {k: v for k, v in os.environ.items() if k != "APP_MAP_HOME"}
    env.update(PROMO_DRIVER_PORT=str(DRIVER_PORT), IDEA_PROPERTIES=str(IDE_DIR / "idea.properties"),
               IDEA_VM_OPTIONS=str(IDE_DIR / "idea.vmoptions"))
    log = open(RUN / "ide.log", "w")
    if LINUX:
        env["DISPLAY"] = DISPLAY
    exe = app / ("bin/idea" if LINUX else "Contents/MacOS/idea")
    p = subprocess.Popen([str(exe), str(SHOP)], env=env, stdout=log, stderr=log,
                         start_new_session=True)
    for _ in range(120):
        try:
            drive("windows")
            break
        except OSError:
            time.sleep(1)
    else:
        p.kill()
        sys.exit("ca-18: the IDE driver never answered")
    # Most of the plugin's actions wait for indexing, and the Gradle import starts a
    # second pass after the first ends: wait until it stays done for 8 s.
    calm = 0
    for _ in range(400):
        calm = calm + 1 if drive("smart") == "smart" else 0
        if calm >= 8:
            break
        time.sleep(1)
    else:
        p.kill()
        sys.exit("ca-18: the IDE never finished indexing")
    time.sleep(6)           # the first highlighting pass
    x, y, w, h = FRAME_BOUNDS
    drive("frame", x=x, y=y, w=w, h=h)
    action("HideAllWindows", frame=1)
    if LINUX:
        # With no window manager, X gives the keyboard to the window under the pointer;
        # without it IntelliJ closes each popup as soon as it opens. The spot is empty
        # toolbar, so the pointer hovers nothing. It is never in a frame: import leaves
        # the pointer out.
        sh(["xdotool", "mousemove", str((x + 440) * 2), str((y + 17) * 2)], env=dict(os.environ, DISPLAY=DISPLAY))
        # The plugin binds its keys in the macOS keymaps only (plugin.xml).
        drive("keymap", name="Mac OS X 10.5+")
    # Every key the clip shows as a badge must be bound to the action it runs.
    for aid in map(act, ("WalkthroughNext", "WalkthroughAsk", "DiffAgainstBase", "SmartDiff", "AppMapShow")):
        km = drive("shortcut", id=aid)
        print("ca-18 keymap:", aid, km, flush=True)
        if "Mac OS X" not in km or "[" not in km:
            p.kill()
            sys.exit(f"ca-18: {aid} has no key in the macOS keymap: {km}")
    return p


def start_display():
    """Linux: a virtual display of its own, so the IDE draws where no one works."""
    n = DISPLAY.lstrip(":")
    if Path(f"/tmp/.X11-unix/X{n}").exists():
        sys.exit(f"ca-18: display {DISPLAY} is in use (set CA18_DISPLAY)")
    x = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "2400x1600x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=open(RUN / "xvfb.log", "w"))
    for _ in range(50):
        if Path(f"/tmp/.X11-unix/X{n}").exists():
            return x
        time.sleep(0.1)
    x.kill()
    sys.exit("ca-18: Xvfb did not start; see xvfb.log")


def watch(d: Daemon, kind, sid):
    log = open(RUN / f"watch-{kind}.log", "w")
    return subprocess.Popen(["webcompanion", "watch", "--kind", kind, "--sid", sid], env=d.env(),
                            stdout=log, stderr=subprocess.STDOUT)


def wait_event(kind, timeout=20):
    log = RUN / f"watch-{kind}.log"
    end = time.time() + timeout
    while time.time() < end:
        for line in log.read_text().splitlines():
            if line.startswith("WEBCOMPANION_EVENT") and "event_id=" in line:
                eid = line.split("event_id=")[1].split()[0]
                payload = json.loads(log.read_text().split("---payload---")[1].split("---end---")[0])
                return eid, payload
        time.sleep(0.2)
    sys.exit(f"ca-18: no {kind} event")


def reply(d: Daemon, kind, sid, eid, anchor, text, title):
    code = ("import sys\nfrom skills._shared import webcompanion_client as wc\n"
            "wc.append_thread(sys.argv[1], sys.argv[2], sys.argv[3], kind=sys.argv[4], role='agent', "
            "source_event_id=sys.argv[5], title=sys.argv[6])\n")
    d.run([CA, "python", "-c", code, sid, anchor, text, kind, eid, title], capture_output=True)
    d.run(["webcompanion", "ack", "--sid", sid, "--event-id", eid], capture_output=True)


def push_json(d: Daemon, cmd):
    r = d.run(cmd, capture_output=True, text=True, cwd=str(SHOP))
    return json.loads(r.stdout)


def steps_doc():
    return {"question": STEPS_QUESTION, "kind": "explain", "generated_ts": 1790000000, "steps": [
        {"id": 1, "title": "The order is paid here", "file": f"{PKG}/flow/FlowService.java", "line": 17,
         "snippet": "    public ChargeResult pay(Order order) {", "role": "context",
         "markdown": "Checkout calls `pay` once the cart is confirmed. Everything about retrying lives inside this loop."},
        {"id": 2, "title": "One key for every attempt", "file": f"{PKG}/flow/FlowService.java", "line": 18,
         "snippet": '        String key = "order-" + order.id();', "role": "seam",
         "markdown": "The key is made once per order, before the loop, so every attempt sends the same one."},
        {"id": 3, "title": "The gateway charges a key once", "file": f"{PKG}/payment/PaymentClient.java", "line": 7,
         "snippet": "    ChargeResult charge(String orderId, long cents, String idempotencyKey);", "role": "seam",
         "markdown": "The gateway remembers the key. A second charge with it returns the first result instead of charging again."},
        {"id": 4, "title": "Only some errors are retried", "file": f"{PKG}/retry/RetryPolicy.java", "line": 15,
         "snippet": "        if (error == ChargeError.DECLINED) {", "role": "context",
         "markdown": "A declined card stops at once. A timeout or a gateway outage is tried again, up to three attempts."},
        {"id": 5, "title": "It waits longer each time", "file": f"{PKG}/retry/RetryPolicy.java", "line": 23,
         "snippet": "        return Duration.ofMillis(200L << (attempt - 1));", "role": "context",
         "markdown": "200 ms, then 400 ms, then 800 ms, so a struggling gateway gets room."},
    ]}


def refocus():
    """Linux: with no window manager, nothing gives the frame the focus back when a
    dialog closes, and IntelliJ then closes every popup at once."""
    if LINUX:
        time.sleep(0.3)
        print("ca-18 focus:", drive("focus", set=1), flush=True)


def find_icon(im, gx, gw, ly, last=True):
    """The ask icon the plugin draws in the gutter of the hovered line: the bluest
    pixels in that gutter row. Answers its centre in frame points."""
    px = im.load()
    # Linux: the gutter alone, or the blue text cursor beside it counts too.
    right = gx + gw if LINUX else max(gx + gw, 300)
    hits = [(x, y) for x in range(0, right * 2) for y in range(ly * 2 - 20, ly * 2 + 20)
            if (lambda p: p[2] > 170 and p[2] - p[0] > 90 and p[2] - p[1] > 30)(px[x, y])]
    if not hits and not last:
        return None
    if not hits:
        im.save(RUN / "calibrate.png")
        sys.exit(f"ca-18: no ask icon in the gutter at line y {ly}; see {RUN / 'calibrate.png'}")
    xs, ys = [h[0] for h in hits], [h[1] for h in hits]
    return (min(xs) + max(xs)) // 4, (min(ys) + max(ys)) // 4


def typed(film, text, key=None, pointer=None):
    """The question growing word by word (a background app gets no key events)."""
    words = text.split(" ")
    for i in (len(words) // 3, 2 * len(words) // 3, len(words)):
        drive("settext", text=" ".join(words[:i]))
        film.shot(110 if i < len(words) else 500, key=key, pointer=pointer, settle=0.15 if i < len(words) else 0.5)


# ── the clip ───────────────────────────────────────────────────────────
def record(film, d: Daemon, pid, procs):
    flow = f"{PKG}/flow/FlowService.java"
    retry = f"{PKG}/retry/RetryPolicy.java"

    # Warm-up, not filmed: the diff viewer remembers the unified view once chosen.
    drive("open", file=flow, line=18)
    action(act("DiffAgainstBase"))
    time.sleep(3)
    drive("click", x=UNIFIED_BUTTON[0], y=UNIFIED_BUTTON[1])
    time.sleep(1)
    action("CloseAllEditors", frame=1)
    time.sleep(1)

    # 1 · walkthrough
    steps = RUN / "steps.json"
    steps.write_text(json.dumps(steps_doc()))
    wt = push_json(d, [CA, "walkthrough.push", "--steps", str(steps), "--cwd", str(SHOP)])["sid"]
    procs.append(watch(d, "walkthrough", wt))
    time.sleep(5)
    film.shot(1500, key=("/walkthrough", "Claude's answer as steps in the code"))
    action(act("WalkthroughNext"))
    film.shot(1300, key=("⌥N", "next step"), settle=1.0)
    action(act("WalkthroughAsk"))
    film.shot(300, key=("⌥A", "ask about this step"), settle=0.8)
    typed(film, WT_QUESTION, key=("⌥A", "ask about this step"))
    drive("button", text="OK")
    refocus()
    film.shot(500, settle=0.6)
    eid, p = wait_event("walkthrough")
    reply(d, "walkthrough", wt, eid, p["anchor"], WT_ANSWER, "The same key charges once")
    film.shot(2600, settle=1.5)
    d.run(["webcompanion", "end", "--sid", wt], capture_output=True)
    time.sleep(2)
    # An ended walkthrough stays on screen until dismissed, and the app map would
    # open on its steps; dismiss it as a person would.
    action(act("WalkthroughDismiss"))
    time.sleep(1.5)
    if "Dialog" in drive("windows"):        # still live: the plugin asks first
        drive("button", text="Dismiss")
        time.sleep(1)
    refocus()

    # 2 · ask-diff on PR #42 (a gh stand-in; the diff is git's own)
    env = d.env({"PATH": f"{FIX / 'bin'}{os.pathsep}{d.env()['PATH']}"})
    r = subprocess.run([CA, "ask_diff.push", "--pr", "42", "--cwd", str(SHOP), "--claude-session-id", "demo-session"],
                       env=env, cwd=str(SHOP), capture_output=True, text=True, check=True)
    ad = json.loads(r.stdout)["sid"]
    procs.append(watch(d, "interactive-review", ad))
    action("CloseAllEditors", frame=1)
    drive("open", file=flow, line=18)
    time.sleep(4)
    film.shot(900, key=("/ask-diff 42", "the PR's diff, a question on any line"))
    action(act("DiffAgainstBase"))
    film.shot(900, key=("⌥B", "this file against the base branch"), settle=2.5)
    gx, gw, ly = (int(v) for v in drive("findline", text='String key = "order-"').split())
    time.sleep(0.5)
    gx, gw, ly = (int(v) for v in drive("findline", text='String key = "order-"').split())
    icon = None
    for i in range(8):                  # the hover can land before the scroll settles
        drive("move", x=gx + gw + 200 + i, y=ly)
        time.sleep(0.6)
        icon = find_icon(film.grab(), gx, gw, ly, last=i == 7)
        if icon:
            break
    refocus()
    drive("move", x=icon[0], y=icon[1])     # the gutter opens its popup for the hovered icon
    film.shot(700, pointer=(icon[0] + 6, icon[1] + 4), settle=0.4)
    drive("click", x=icon[0], y=icon[1])
    film.shot(300, pointer=(icon[0] + 6, icon[1] + 4), ring=True, settle=1.0)
    if "HeavyWeightWindow" not in drive("windows"):
        film.grab().save(RUN / "calibrate.png")
        sys.exit(f"ca-18: the ask popup did not open (icon at {icon}, {drive('focus')}); see {RUN / 'calibrate.png'}")
    typed(film, AD_QUESTION)
    drive("button", text="Ask")
    film.shot(500, settle=0.6)
    eid, p = wait_event("interactive-review")
    reply(d, "interactive-review", ad, eid, p["anchor"], AD_ANSWER, "One key, one charge")
    film.shot(3000, settle=1.5)
    drive("closepopups")
    d.run(["webcompanion", "end", "--sid", ad], capture_output=True)

    # 3 · the smart diff key walks one file back
    action("CloseAllEditors", frame=1)
    drive("open", file=retry, line=15)
    film.shot(700, settle=1.5)
    # RetryPolicy has two changes in the shop's history, so a third press would wrap.
    for label in ("this file's last change", "press again: one change further back"):
        refocus()                       # the press reads the focused tab: the diff after the first
        action(act("SmartDiff"), **({"focus": 1} if LINUX else {}))
        film.shot(1300, key=("⌥D", label), settle=1.5)

    # 4 · the app map, this file's part lit
    action("CloseAllEditors", frame=1)
    drive("open", file=retry, line=15)
    time.sleep(1)
    action(act("AppMapShow"))
    film.shot(3000, key=("⌘⇧M", "where this file sits in the app"), settle=2.0)


def main():
    app = ide_app()
    for port in (DAEMON_PORT, DRIVER_PORT):
        if not port_free(port):
            sys.exit(f"ca-18: port {port} is taken by {holder(port)}")
    RUN.mkdir(exist_ok=True)
    sh([sys.executable, str(FIX / "make_repo.py"), str(SHOP)], stdout=subprocess.DEVNULL)
    (SHOP / ".git" / "info").mkdir(exist_ok=True)     # some git installs make no info/
    with open(SHOP / ".git" / "info" / "exclude", "a") as f:
        f.write(".idea/\n.gradle/\ngradle/\ngradlew\ngradlew.bat\nbuild/\n")
    build_plugins(app)
    ide_config(app)
    procs = []
    # Sessions of an earlier run would show up as a paused review in the status bar.
    shutil.rmtree(HOME / ".claude" / "webcompanion" / "workspaces", ignore_errors=True)
    xvfb = start_display() if LINUX else None
    try:
        with Daemon(HOME, DAEMON_PORT) as d:
            app_map()
            ide = start_ide(app)
            try:
                film = Film(ide.pid)
                record(film, d, ide.pid, procs)
                film.save()
            finally:
                for p in procs:
                    p.terminate()
                ide.terminate()
                try:
                    ide.wait(30)
                except subprocess.TimeoutExpired:
                    ide.kill()
    finally:
        if xvfb:
            xvfb.terminate()
    encode(FRAMES, OUT, width=800)
    print(OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
