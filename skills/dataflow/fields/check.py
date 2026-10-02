"""Open a rendered field page in headless Chromium, screenshot it, and return the
layout report the engine computed (window.__layoutReport).

The screenshot is what Claude looks at before handing a diagram over; the report is
what tells it, in numbers, whether a wire passes behind a card or a label sits on
something. See SKILL.md, "Field mode".
"""

from __future__ import annotations

import math
from pathlib import Path

class PageError(RuntimeError):
    """The engine threw while laying the page out; the message is the browser's."""


class Unavailable(RuntimeError):
    """Playwright is installed but cannot start Chromium."""


MEASURES = ("behind_card", "label_overlaps", "crossings", "max_steepness", "detour")
TARGETS = ("behind_card", "label_overlaps")     # these must be 0; the rest are reported
WIDTH = 1800


def run(html_path: Path) -> dict:
    """Write html_path.with_suffix(".png") and return the report. Raises ImportError
    when Playwright is not installed."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    url = html_path.resolve().as_uri()
    # An engine error must surface at once, not as a 30-second wait for a report
    # that will never come.
    trap = "window.addEventListener('error', e => { window.__layoutError = String(e.message); });"
    ready = "() => window.__layoutReport || window.__layoutError"

    def load(page):
        page.add_init_script(trap)
        page.goto(url)
        page.wait_for_function(ready)
        err = page.evaluate("() => window.__layoutError || null")
        if err:
            raise PageError(err)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except PlaywrightError as e:
            raise Unavailable(f"check cannot start Chromium: run `playwright install chromium` ({str(e).splitlines()[0]})") from e
        try:
            probe = browser.new_page(viewport={"width": WIDTH, "height": 900})
            load(probe)
            box = probe.evaluate("""() => {
              const cs = Object.values(window.__layout.cards);
              const ys = cs.flatMap(c => [c.y - 30, c.y + c.h]);
              window.__layout.wires.forEach(w => w.samples.forEach(p => ys.push(p[1])));
              const xs = cs.flatMap(c => [c.x, c.x + c.w]);
              return { w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
            }""")
            report = probe.evaluate("() => window.__layoutReport")
            probe.close()

            height = math.ceil(WIDTH * box["h"] / box["w"]) + 160
            page = browser.new_page(viewport={"width": WIDTH, "height": height}, device_scale_factor=2)
            load(page)
            page.evaluate("() => { document.body.classList.add('shot'); window.__fit(); }")
            page.screenshot(path=str(html_path.with_suffix(".png")))
        finally:
            browser.close()
    return report


def passed(report: dict) -> bool:
    return all(report[m] == 0 for m in TARGETS)
