"""audit.py: run the slides skill's layout audit on a deck and print each slide's overflow.

    python3 audit.py <deck.html> [--port 19164]

The deck is read over the clip's own http server on 127.0.0.1:<port>. The audit is
skills/slides/references/layout-audit.js, evaluated as it is in a headless Chromium
at 1280x720; this prints the `overflow` field of its report, one slide per line,
and exits 1 when any slide overflows. Needs playwright (the clip runs it under uv).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AUDIT = Path(os.environ["SLIDES_SKILL"]) / "references" / "layout-audit.js"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--port", type=int, default=19164)
    a = ap.parse_args()
    js = AUDIT.read_text()
    js = js[js.index("() => {"):]
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto("http://127.0.0.1:%d/%s" % (a.port, a.deck), wait_until="networkidle")
        report = json.loads(page.evaluate(js))
        b.close()
    bad = 0
    for s in report:
        print(json.dumps({"slide": s["slide"], "overflow": s["overflow"]}))
        bad += bool(s["overflow"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
