# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright"]
# ///
"""rec.py: record a page step by step as crisp 2x PNG frames.

A clip script drives a real page with Playwright and takes one screenshot per
step. A glide is many small mouse moves with a screenshot after each one. A
hold is no extra frame, only a longer delay on the last frame. The frame list
with the delay of each frame goes to frames.json, which encode.py turns into
an animated WebP.

The page gets a drawn cursor (an arrow that follows the recorder, and a ring
when it clicks), because a headless browser draws no cursor. The recorder
sets the cursor's position and the ring's size itself before every shot, so
the frames are the same on every run, however slow the machine is.

    from rec import Recorder
    with Recorder(".scratch/frames/demo", viewport=(1440, 900)) as r:
        r.goto("http://127.0.0.1:19100/")
        r.hold(1.0)
        r.click("button#save")
        r.type("textarea", "40M rows, not 2M")
    # frames are in that folder, the list in frames.json

Works the same on Linux and macOS. Install the browser once with
`uv run --with playwright playwright install chromium`.
"""
from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

CURSOR_JS = r"""
(() => {
  if (window.__promoCursor) return;
  const make = () => {
    if (document.getElementById('__promo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__promo_cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;' +
      'pointer-events:none;transform:translate(-100px,-100px);display:none;';
    // Built node by node, not with innerHTML, so pages with Trusted Types
    // (VS Code's webviews) accept it.
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    for (const [k, v] of [['width', '24'], ['height', '24'], ['viewBox', '0 0 24 24'],
                          ['style', 'filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))']]) svg.setAttribute(k, v);
    const path = document.createElementNS(NS, 'path');
    for (const [k, v] of [['d', 'M3 2 L3 19 L7.5 14.8 L10.6 21.6 L13.6 20.3 L10.6 13.6 L16.6 13.6 Z'],
                          ['fill', '#111'], ['stroke', '#fff'], ['stroke-width', '1.6'],
                          ['stroke-linejoin', 'round']]) path.setAttribute(k, v);
    svg.append(path);
    c.append(svg);
    const r = document.createElement('div');
    r.id = '__promo_ring';
    r.style.cssText = 'position:fixed;left:0;top:0;width:40px;height:40px;margin:-20px 0 0 -20px;' +
      'border-radius:50%;border:3px solid #e8590c;z-index:2147483646;pointer-events:none;display:none;';
    (document.body || document.documentElement).append(r, c);
  };
  window.__promoCursor = {
    move(x, y) {
      make();
      const c = document.getElementById('__promo_cursor');
      c.style.display = 'block';
      c.style.transform = `translate(${x - 3}px, ${y - 2}px)`;
    },
    ring(x, y, t) {
      make();
      const r = document.getElementById('__promo_ring');
      if (t === null || t >= 1) { r.style.display = 'none'; return; }
      r.style.display = 'block';
      r.style.left = x + 'px'; r.style.top = y + 'px';
      r.style.transform = `scale(${0.3 + 0.9 * t})`;
      r.style.opacity = String(1 - t);
    },
    hide() {
      for (const id of ['__promo_cursor', '__promo_ring']) {
        const e = document.getElementById(id); if (e) e.style.display = 'none';
      }
    },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', make);
  else make();
})();
"""


def ease(t: float) -> float:
    """Ease in and out (cubic): slow start, fast middle, slow stop."""
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


class Recorder:
    """One recording: a browser page, a frame folder and a frame list."""

    def __init__(self, out_dir, *, viewport=(1440, 900), scale=2, fps=12,
                 clip=None, color_scheme="light", headless=True, browser_args=None,
                 context_args=None):
        self.out = Path(out_dir)
        self.viewport = viewport
        self.scale = scale
        self.fps = fps
        self.frame_ms = round(1000 / fps)
        self.clip = clip              # (x, y, w, h) in CSS px, or None for the viewport
        self.color_scheme = color_scheme
        self.headless = headless
        self.browser_args = browser_args or []
        self.context_args = context_args or {}
        self.frames: list[dict] = []
        self.pos = (viewport[0] * 0.6, viewport[1] * 0.75)
        self.cursor_on = True

    # ── lifecycle ──────────────────────────────────────────────────────
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless, args=self.browser_args)
        self.context = self.browser.new_context(
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            device_scale_factor=self.scale, color_scheme=self.color_scheme,
            **self.context_args)
        self.context.add_init_script(CURSOR_JS)
        self.page = self.context.new_page()
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.save()
        self.context.close()
        self.browser.close()
        self._pw.stop()
        return False

    def save(self):
        (self.out / "frames.json").write_text(json.dumps(
            {"fps": self.fps, "scale": self.scale, "frames": self.frames}, indent=1))

    # ── frames ─────────────────────────────────────────────────────────
    def _draw_cursor(self, ring=None):
        if not self.cursor_on:
            self.page.evaluate("window.__promoCursor && window.__promoCursor.hide()")
            return
        x, y = self.pos
        self.page.evaluate("([x,y,r]) => { const c = window.__promoCursor; if (!c) return;"
                           " c.move(x,y); c.ring(x,y,r); }", [x, y, ring])

    def shot(self, ms=None, ring=None):
        """Take one frame now and show it for `ms` (default: one frame at the fps)."""
        self._draw_cursor(ring)
        name = "f%04d.png" % len(self.frames)
        kw = {"path": str(self.out / name), "animations": "disabled", "caret": "initial"}
        if self.clip:
            x, y, w, h = self.clip
            kw["clip"] = {"x": x, "y": y, "width": w, "height": h}
        self.page.screenshot(**kw)
        self.frames.append({"file": name, "ms": int(ms or self.frame_ms)})
        return name

    def hold(self, seconds: float):
        """Keep the last frame on screen `seconds` longer. No new frame."""
        if not self.frames:
            self.shot()
        self.frames[-1]["ms"] += int(seconds * 1000)

    def settle(self, seconds=0.3):
        """Let the page finish what it is doing, without recording frames."""
        self.page.wait_for_timeout(int(seconds * 1000))

    def run(self, seconds: float, every: float | None = None):
        """Record the page as it changes by itself for `seconds` (real time)."""
        step = every or 1 / self.fps
        n = max(1, round(seconds / step))
        for _ in range(n):
            self.page.wait_for_timeout(int(step * 1000))
            self.shot(int(step * 1000))

    # ── navigation and pointer ─────────────────────────────────────────
    def goto(self, url: str, wait="networkidle"):
        self.page.goto(url, wait_until=wait)
        # Put the real mouse where the drawn cursor is, so a wheel or hover
        # before the first glide lands there and not at (0, 0).
        self.page.mouse.move(*self.pos)
        self.settle(0.4)

    def point_of(self, target):
        """(x, y) for a selector, a locator, or an (x, y) pair: the centre of the box."""
        if isinstance(target, (tuple, list)):
            return float(target[0]), float(target[1])
        loc = self.page.locator(target) if isinstance(target, str) else target
        loc = loc.first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box is None:
            raise RuntimeError("no box for %r" % (target,))
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def glide(self, target, seconds=0.7, record=True):
        """Move the cursor to `target` along an eased path, one frame per step."""
        x1, y1 = self.point_of(target)
        x0, y0 = self.pos
        n = max(2, round(seconds * self.fps))
        dist = math.hypot(x1 - x0, y1 - y0)
        bow = min(60.0, dist * 0.12)           # a slight arc, as a hand moves
        nx, ny = (-(y1 - y0) / dist, (x1 - x0) / dist) if dist else (0, 0)
        for i in range(1, n + 1):
            t = ease(i / n)
            arc = math.sin(math.pi * t) * bow
            x = x0 + (x1 - x0) * t + nx * arc
            y = y0 + (y1 - y0) * t + ny * arc
            self.page.mouse.move(x, y)
            self.pos = (x, y)
            if record:
                self.shot()
        return self.pos

    def click(self, target=None, seconds=0.7, ring_frames=4, after=0.25):
        """Glide to `target` (if given), click it for real, and draw the ring."""
        if target is not None:
            self.glide(target, seconds)
        x, y = self.pos
        self.page.mouse.click(x, y)
        self.settle(after)
        for i in range(ring_frames):
            self.shot(ring=i / ring_frames)
        self._draw_cursor(None)

    def type(self, text: str, target=None, cps=18, chars_per_frame=None):
        """Type `text` (after clicking `target` if given), a frame every few characters."""
        if target is not None:
            self.click(target)
        per = chars_per_frame or max(1, round(cps / self.fps))
        for i in range(0, len(text), per):
            self.page.keyboard.type(text[i:i + per])
            self.shot()

    def press(self, key: str, after=0.3, shot=True):
        self.page.keyboard.press(key)
        self.settle(after)
        if shot:
            self.shot()

    def scroll(self, dy: float, seconds=0.8):
        """Scroll the page by `dy` pixels with the wheel, eased, one frame per step."""
        n = max(2, round(seconds * self.fps))
        done = 0.0
        for i in range(1, n + 1):
            want = dy * ease(i / n)
            self.page.mouse.wheel(0, want - done)
            done = want
            self.settle(0.05)
            self.shot()

    def hide_cursor(self):
        self.cursor_on = False

    def show_cursor(self):
        self.cursor_on = True


def scratch_root() -> Path:
    """Where clips keep raw frames and servers keep their files: $PROMO_SCRATCH,
    else `.scratch/promo` beside the checkout (a job folder holds the clone in
    ./repo and its scratch in ./.scratch), else the system temp folder. Never
    inside the checkout, so nothing a clip makes can be committed by mistake."""
    env = os.environ.get("PROMO_SCRATCH")
    if env:
        return Path(env).resolve()
    beside = Path(__file__).resolve().parents[3] / ".scratch"
    if beside.is_dir():
        return beside / "promo"
    import tempfile
    return Path(tempfile.gettempdir()) / "promo-scratch"


def frames_dir(clip_id: str) -> Path:
    """The raw frame folder of one clip, under scratch_root()."""
    return scratch_root() / "frames" / clip_id
