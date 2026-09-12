"""A stored SVG, rendered to a PNG that can be attached to a page.

The SVG annotate stores is deliberately style-free: `class="actor-box
tone-edge"`, and the colours live in the stylesheet. That is right for a page
that themes its diagrams, and fatal for one lifted out of it — so this module
rebuilds the missing half, inlining core.css (palette, type), diagram.css
(tone tokens) and the two woff2 faces as data URIs.

Chromium, not librsvg: diagram.css uses `color-mix()`, which librsvg does not
implement. `rsvg-convert` would not fail — it would draw the washes wrong and
say nothing.
"""
from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
FONTS = {
    "Monaspace Radon": STATIC / "fonts" / "MonaspaceRadon-Regular.woff2",
    "Bricolage Grotesque": STATIC / "fonts" / "BricolageGrotesque-Variable.woff2",
}
SCALE = 2

# The stylesheets declare their own @font-face rules pointing at a relative
# fonts/ directory that will not be sitting beside this standalone document.
# Those rules are stripped wholesale and replaced by the data-URI ones
# _font_faces() emits.
_FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*\}", re.S)

# The root <svg> carries its own intrinsic size as width/height attributes.
# diagram.css sets `.annotate-seq { width: auto; height: auto; }` so the
# diagram scales inside whatever container the real page puts it in; a
# standalone document has no such container, so without one "auto" resolves
# against the browser's default viewport instead of the diagram's own size.
# Wrapping it in a div pinned to its own attributes reproduces the container
# the live page provides.
_SVG_TAG_RE = re.compile(r"<svg\b[^>]*>", re.S)


class ChromiumMissing(RuntimeError):
    """Headless Chromium is not usable on this machine."""


def _font_faces() -> str:
    out = []
    for family, path in FONTS.items():
        blob = base64.b64encode(path.read_bytes()).decode("ascii")
        out.append("@font-face{font-family:'%s';src:url('data:font/woff2;"
                   "base64,%s') format('woff2');font-display:block;}"
                   % (family, blob))
    return "".join(out)


def _intrinsic_size(svg: str) -> tuple[str, str]:
    tag_match = _SVG_TAG_RE.search(svg)
    tag = tag_match.group(0) if tag_match else svg
    width = re.search(r'width="([\d.]+)"', tag)
    height = re.search(r'height="([\d.]+)"', tag)
    return (width.group(1) if width else "auto",
            height.group(1) if height else "auto")


def standalone_html(svg: str) -> str:
    """The SVG with everything it needs to look like it does on the page."""
    css = (STATIC / "core.css").read_text() + (STATIC / "diagram.css").read_text()
    css = _FONT_FACE_RE.sub("", css)
    width, height = _intrinsic_size(svg)
    wrapped = "<div style='width:%spx;height:%spx'>%s</div>" % (width, height, svg)
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>:root{color-scheme:light;}"
        "html,body{margin:0;padding:0;background:#fff;"
        "font-family:'Bricolage Grotesque',ui-sans-serif,system-ui,sans-serif;}"
        "%s\n%s</style><body>%s</body>" % (_font_faces(), css, wrapped))


_SCRIPT = """
const { chromium } = require('playwright');
(async () => {
  const [htmlPath, outPath, scale] = process.argv.slice(2);
  const fs = require('fs');
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: Number(scale) });
  await page.setContent(fs.readFileSync(htmlPath, 'utf8'),
                        { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  const svg = await page.$('svg');
  await svg.screenshot({ path: outPath, omitBackground: false });
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def _node_script(script_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the renderer under node, with the global module path available.

    playwright is installed globally rather than in this repo — there is no
    package.json here and adding one for a single screenshot would be a
    heavier dependency than the picture is worth.
    """
    root = subprocess.run(["npm", "root", "-g"], capture_output=True,
                          text=True).stdout.strip()
    return subprocess.run(["node", str(script_path), *args],
                          capture_output=True, text=True,
                          env={**__import__("os").environ, "NODE_PATH": root})


def render_png(svg: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    html_path = work / (out_path.stem + ".html")
    script_path = work / "_shot.cjs"
    html_path.write_text(standalone_html(svg))
    script_path.write_text(_SCRIPT)
    try:
        res = _node_script(script_path, str(html_path), str(out_path),
                           str(SCALE))
    finally:
        for p in (html_path, script_path):
            p.unlink(missing_ok=True)
    if res.returncode:
        detail = (res.stderr or res.stdout).strip()
        if "playwright" in detail or "chromium" in detail.lower():
            raise ChromiumMissing(
                "headless Chromium is not available, and a page published "
                "without its diagrams is not the document the author "
                "approved.\n  npm install -g playwright && npx playwright "
                "install chromium\n%s" % detail)
        raise RuntimeError("rendering %s failed: %s" % (out_path.name, detail))
    return out_path
