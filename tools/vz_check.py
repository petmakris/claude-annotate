# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright==1.55.0"]
# ///
"""Check a map or lane sequence (svg.vz) in Chromium, and export it as PNG.

Run:  uv run tools/vz_check.py check FILE.svg [FILE.svg ...] [--out DIR]
      uv run tools/vz_check.py frames FILE.svg --out DIR [--mode build|route]

`check` draws each SVG with skills/_shared/static/vz.css and the Inter and JetBrains Mono fonts, in
light and dark, and lists every fault: text off the canvas, text that leaves its box or touches its
edge, labels that overlap, an arrow through text or through a box, a filled arrow, text with no
visible colour, a missing title. For a map it also checks every build and route frame, since a part
can collide with another only while some parts are hidden. It writes light and dark PNGs.

`frames` writes one PNG per step, each adding to the last, for a deck or a document that cannot run
the reveal script.

The suite never drives a browser (see CLAUDE.md); this tool is run by hand and by the author.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "skills" / "_shared" / "static" / "vz.css"
FONTS = ROOT / "skills" / "_shared" / "static" / "fonts"

PROBE = r"""
(mode) => {
  const svg = document.querySelector('svg.vz');
  const vb = svg.viewBox.baseVal;
  const faults = [];
  const shown = (el) => getComputedStyle(el).display !== 'none' && +getComputedStyle(el).opacity > 0.5;
  const boxes = [...svg.querySelectorAll('rect.bx, rect.chip')].filter(shown).map(r => ({r, b: r.getBBox()}));
  const texts = [...svg.querySelectorAll('text:not(.n)')].filter(shown).map(t => ({t, b: t.getBBox(), s: t.textContent.trim()}));
  const inside = (p, b, pad = 0) => p.x >= b.x - pad && p.x <= b.x + b.width + pad && p.y >= b.y - pad && p.y <= b.y + b.height + pad;
  const area = (b) => b.width * b.height;
  for (const {b, s} of texts) {
    if (b.x < vb.x || b.y < vb.y || b.x + b.width > vb.x + vb.width || b.y + b.height > vb.y + vb.height)
      faults.push(`off canvas: "${s}"`);
    const start = {x: b.x + 1, y: b.y + b.height / 2};
    const own = boxes.filter(x => inside(start, x.b)).sort((p, q) => area(p.b) - area(q.b))[0];
    if (own) {
      const over = b.x + b.width - (own.b.x + own.b.width - 8);
      if (over > 0) faults.push(`leaves its box by ${Math.ceil(over)}px: "${s}"`);
      if (b.y < own.b.y + 2 || b.y + b.height > own.b.y + own.b.height - 2) faults.push(`touches its box's top or bottom: "${s}"`);
    }
  }
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
    const a = texts[i].b, c = texts[j].b;
    if (a.x < c.x + c.width - 1 && c.x < a.x + a.width - 1 && a.y < c.y + c.height - 2 && c.y < a.y + a.height - 2)
      faults.push(`labels overlap: "${texts[i].s}" and "${texts[j].s}"`);
  }
  for (const el of [...svg.querySelectorAll('.ar')].filter(shown)) {
    if (getComputedStyle(el).fill !== 'none') faults.push(`arrow is filled: ${el.getAttribute('d') || ''}`);
    const len = el.getTotalLength();
    const pts = [];
    for (let d = 10; d < len - 12; d += 3) pts.push(el.getPointAtLength(d));
    const id = el.getAttribute('d') || `${el.getAttribute('x1')},${el.getAttribute('y1')}`;
    for (const {b, s} of texts) if (pts.some(p => inside(p, b, 2))) faults.push(`arrow ${id} runs through text "${s}"`);
    for (const {b} of boxes) {
      const inner = {x: b.x + 4, y: b.y + 4, width: b.width - 8, height: b.height - 8};
      if (pts.filter(p => inside(p, inner)).length > 2) faults.push(`arrow ${id} runs through a box at ${Math.round(b.x)},${Math.round(b.y)}`);
    }
  }
  const ground = getComputedStyle(document.body).backgroundColor;
  for (const t of texts) {
    const c = getComputedStyle(t.t).fill;
    if (c === 'none' || c === ground) faults.push(`text has no visible colour: "${t.s}"`);
  }
  if (!svg.querySelector('text.ttl')) faults.push('no title');
  return faults;
}
"""

FRAME = r"""
([mode, n]) => {
  const svg = document.querySelector('svg.vz');
  svg.classList.remove('mode-build', 'mode-route');
  const key = mode === 'build' ? 'b' : 'r';
  let last = 0;
  for (const el of svg.querySelectorAll('[data-p]')) {
    el.classList.remove('fut', 'now');
    if (!mode) continue;
    const s = el.dataset[key];
    if (s === undefined) continue;
    last = Math.max(last, +s);
    if (+s > n) el.classList.add('fut');
    if (+s === n) el.classList.add('now');
  }
  if (mode) svg.classList.add('mode-' + mode);
  return last;
}
"""


def chromium() -> str | None:
    """The newest Chromium Playwright already downloaded, so no extra install is needed."""
    for cache in (Path.home() / "Library" / "Caches" / "ms-playwright", Path.home() / ".cache" / "ms-playwright"):
        shells = sorted(cache.glob("chromium_headless_shell-*/*/chrome-headless-shell"),
                        key=lambda x: int(x.parts[-3].rsplit("-", 1)[1]))
        if shells:
            return str(shells[-1])
    return None


def page(svg: str, theme: str) -> str:
    fonts = "".join(
        f'@font-face{{font-family:"{fam}";src:url("{(FONTS / f).as_uri()}") format("woff2");font-weight:100 900}}'
        for fam, f in (("Inter", "Inter-Variable.woff2"), ("JetBrains Mono", "JetBrainsMono-Variable.woff2")))
    ground = "#ffffff" if theme == "light" else "#1c2220"
    return (f'<!doctype html><html data-theme="{theme}"><head><meta charset="utf-8"><style>{fonts}</style>'
            f'<link rel="stylesheet" href="{CSS.as_uri()}"><style>body{{margin:0;padding:20px;background:{ground}}}'
            f' svg.vz{{width:auto;max-width:none}} svg.vz *{{transition:none!important}}</style></head><body>{svg}</body></html>')


def load(pg, svg: str, theme: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(page(svg, theme))
    pg.goto(Path(f.name).as_uri())
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(150)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("files", nargs="+")
    c.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "vz-check"))
    f = sub.add_parser("frames")
    f.add_argument("file")
    f.add_argument("--out", required=True)
    f.add_argument("--mode", choices=["build", "route"], default="route")
    f.add_argument("--theme", choices=["light", "dark"], default="light")
    a = ap.parse_args()

    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium())
        pg = browser.new_page(device_scale_factor=2, viewport={"width": 1600, "height": 1000})
        if a.cmd == "check":
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            for name in a.files:
                path = Path(name)
                svg = path.read_text()
                faults: list[str] = []
                for theme in ("light", "dark"):
                    load(pg, svg, theme)
                    if theme == "light":
                        faults += pg.evaluate(PROBE, "still")
                        for mode in ("build", "route"):
                            last = pg.evaluate(FRAME, [mode, 10 ** 6])
                            for n in range(1, last + 1):
                                pg.evaluate(FRAME, [mode, n])
                                faults += [f"{mode} {n}: {x}" for x in pg.evaluate(PROBE, mode)]
                            pg.evaluate(FRAME, [None, 0])
                    pg.locator("svg.vz").screenshot(path=str(out / f"{path.stem}-{theme}.png"))
                seen, uniq = set(), []
                for x in faults:
                    if x not in seen:
                        seen.add(x)
                        uniq.append(x)
                bad += len(uniq)
                print(f"{path.stem}: {len(uniq)} faults  {out / path.stem}-light.png")
                for x in uniq:
                    print("   ", x)
            print(f"{bad} faults")
        else:
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            path = Path(a.file)
            load(pg, path.read_text(), a.theme)
            last = pg.evaluate(FRAME, [a.mode, 10 ** 6])
            for n in range(0, last + 1):
                pg.evaluate(FRAME, [a.mode, n])
                pg.wait_for_timeout(50)
                pg.locator("svg.vz").screenshot(path=str(out / f"{path.stem}-{a.mode}-{n:02d}.png"))
            print(f"{last + 1} frames in {out}")
        browser.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
