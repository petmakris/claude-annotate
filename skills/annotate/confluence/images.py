"""A stored SVG, rendered to a PNG that can be attached to a page.

The SVG annotate stores is deliberately style-free: `class="actor-box
tone-edge"`, and the colours live in the stylesheet. That is right for a page
that themes its diagrams, and fatal for one lifted out of it — so this module
rebuilds the missing half, inlining core.css (palette, type), visuals.css
(the drawing), diagram.css (tone tokens) and the two woff2 faces as data URIs.

Chromium, not librsvg: diagram.css uses `color-mix()`, which librsvg does not
implement. `rsvg-convert` would not fail — it would draw the washes wrong and
say nothing.
"""
from __future__ import annotations

import base64
import functools
import json
import os
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


@functools.lru_cache(maxsize=None)
def _font_faces() -> str:
    """The two faces as data URIs — ~630 KB of base64, encoded once."""
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
    css = "".join((STATIC / name).read_text() for name in ("core.css", "visuals.css", "diagram.css"))
    css = _FONT_FACE_RE.sub("", css)
    width, height = _intrinsic_size(svg)
    wrapped = "<div style='width:%spx;height:%spx'>%s</div>" % (width, height, svg)
    # The diagram's SVG paints no background of its own. On the live page it
    # now sits in a frame (.block-frame) on --diagram-ground (#ffffff); this
    # image keeps the old card's --surface (#f8f9fb), which Confluence
    # publishing has not been moved off. Either way it is not the page
    # body's --bg (#e4e7ed). core.css carries its own
    # `body { background: var(--bg) }` at the same specificity as a plain
    # `body` rule of ours, so whichever comes LAST in source order wins the
    # cascade. This override is therefore placed AFTER core.css/diagram.css
    # on purpose — move it earlier and core.css's rule silently wins again.
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>:root{color-scheme:light;}"
        "html,body{margin:0;padding:0;"
        "font-family:'Bricolage Grotesque',ui-sans-serif,system-ui,sans-serif;}"
        "%s\n%s\nbody{background:#f8f9fb;}"
        "</style><body>%s</body>" % (_font_faces(), css, wrapped))


_SCRIPT = """
const { chromium } = require('playwright');
(async () => {
  const fs = require('fs');
  const [jobsPath] = process.argv.slice(2);
  const { scale, jobs } = JSON.parse(fs.readFileSync(jobsPath, 'utf8'));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ deviceScaleFactor: Number(scale) });
    for (const job of jobs) {
      await page.setContent(fs.readFileSync(job.html, 'utf8'),
                            { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      const svg = await page.$('svg');
      await svg.screenshot({ path: job.out, omitBackground: false });
    }
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e.message); process.exit(1); });
"""

# `npm root -g` answers from local config; Chromium launches in a second or
# two and each screenshot takes well under one. The ceilings sit an order of
# magnitude above that: they exist so a wedged npm or browser fails the
# publish instead of hanging it.
NPM_TIMEOUT = 15
RENDER_TIMEOUT = 120
RENDER_TIMEOUT_PER_IMAGE = 10

# The global module path, asked of npm once per process.
_npm_root_cache: str | None = None


def _failed(cmd: list[str], message: str) -> subprocess.CompletedProcess:
    """A timeout, reported the way render_pngs already reads a failed run."""
    return subprocess.CompletedProcess(cmd, 124, "", message)


def _node_script(script_path: Path, *args: str,
                 timeout: float = RENDER_TIMEOUT) -> subprocess.CompletedProcess:
    """Run the renderer under node, with the global module path available.

    playwright is installed globally rather than in this repo — there is no
    package.json here and adding one for a single screenshot would be a
    heavier dependency than the picture is worth.
    """
    global _npm_root_cache
    if _npm_root_cache is None:
        npm = ["npm", "root", "-g"]
        try:
            _npm_root_cache = subprocess.run(
                npm, capture_output=True, text=True,
                timeout=NPM_TIMEOUT).stdout.strip()
        except subprocess.TimeoutExpired:
            return _failed(npm, "`npm root -g` did not finish within %ds"
                           % NPM_TIMEOUT)
    cmd = ["node", str(script_path), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout,
                              env={**os.environ, "NODE_PATH": _npm_root_cache})
    except subprocess.TimeoutExpired:
        return _failed(cmd, "the diagram renderer did not finish within %ds"
                       % timeout)


def render_png(svg: str, out_path: Path) -> Path:
    return render_pngs([(svg, out_path)])[0]


def render_pngs(items: list[tuple[str, Path]]) -> list[Path]:
    """Every (svg, out_path) pair drawn in one headless Chromium session.

    Launching the browser costs more than a screenshot does, so a page with
    several diagrams pays for it once.
    """
    outs = [Path(out) for _, out in items]
    if not outs:
        return outs
    for out in outs:
        out.parent.mkdir(parents=True, exist_ok=True)
    work = outs[0].parent
    script_path = work / "_shot.cjs"
    jobs_path = work / "_shot.json"
    html_paths = [out.parent / (out.stem + ".html") for out in outs]
    for (svg, _), html_path in zip(items, html_paths):
        html_path.write_text(standalone_html(svg))
    jobs_path.write_text(json.dumps({
        "scale": SCALE,
        "jobs": [{"html": str(h), "out": str(o)}
                 for h, o in zip(html_paths, outs)]}))
    script_path.write_text(_SCRIPT)
    try:
        res = _node_script(script_path, str(jobs_path),
                           timeout=RENDER_TIMEOUT
                           + RENDER_TIMEOUT_PER_IMAGE * len(outs))
    finally:
        for p in (*html_paths, script_path, jobs_path):
            p.unlink(missing_ok=True)
    if res.returncode:
        detail = (res.stderr or res.stdout).strip()
        # Two different missing pieces, with different fixes. Naming the
        # browser when it is the Node package that is absent sent people to
        # install a Chromium they already had.
        if "Cannot find module 'playwright'" in detail:
            raise ChromiumMissing(
                "the Node `playwright` module is not installed, so diagrams "
                "cannot be rendered, and a page published without its "
                "diagrams is not the document the author approved.\n"
                "  npm install -g playwright && npx playwright install chromium"
                "\n%s" % detail)
        if "playwright" in detail or "chromium" in detail.lower():
            raise ChromiumMissing(
                "headless Chromium is not available, and a page published "
                "without its diagrams is not the document the author "
                "approved.\n  npm install -g playwright && npx playwright "
                "install chromium\n%s" % detail)
        raise RuntimeError("rendering %s failed: %s"
                           % (", ".join(o.name for o in outs), detail))
    return outs
