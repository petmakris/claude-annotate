#!/usr/bin/env python3
"""Export every presentation in this folder to PDF, and to one PNG per page.

The `.html` is the master: it is what you edit and what you present from. Two
exports come out of it:

  `.pdf`      one file to hand to people, text still selectable.
  `png/`      one image per slide, for pasting into a wiki page or a chat,
              where an embedded PDF usually renders as a blurry preview.

    python3 export-pdf.py             # all decks in this folder
    python3 export-pdf.py 2026.07.31  # only folders whose name contains this

Each deck also gets a print stylesheet baked into it, so printing from the browser
produces the same PDF this script does. Re-running replaces that block rather than
stacking copies. Both exports are regenerated from the HTML, so keep them out of git.

Needs Google Chrome or Chromium, and poppler for the PNG step
(`brew install poppler`, or your distribution's poppler-utils).
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def find_chrome() -> str:
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac).exists():
        return mac
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    raise SystemExit("no Chrome or Chromium found — install one to export PDFs")


CHROME = None  # resolved on first export
MARKER = "/* pdf-export print rules */"
BAKED = re.compile(r"\n?<style>\s*" + re.escape(MARKER) + r".*?</style>\n?", re.S)

# A 1280x720 slide is 13.33in wide once Chrome writes it, so 192dpi lands on
# 2560px — exactly 2x. Wikis and chats downscale that to fit their column, and
# downscaling is the one resampling direction that never softens type.
PNG_DPI = 192

# A slide deck is <body><div class="deck"><section class="slide"> … 1280x720.
SLIDE_PRINT = f"""
<style>
{MARKER}
@media print{{
  @page{{size:1280px 720px;margin:0}}
  html,body{{background:#fff!important;margin:0!important;padding:0!important;
            -webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
  /* The body stack ends in system-ui, which on macOS resolves to San Francisco.
     Chrome cannot embed SF as a real font — it writes each glyph as an unhinted
     Type 3 procedure, which most PDF viewers render badly. Helvetica embeds
     properly as TrueType. Georgia (--head) and Menlo (--mono) already do. */
  :root{{--body:Helvetica,Arial,sans-serif!important}}
  body,.deck,.slide{{font-family:Helvetica,Arial,sans-serif}}
  /* every on-screen control is appended to <body>; only .deck is content */
  body>*:not(.deck){{display:none!important}}
  /* the deck JS sets an inline zoom to fit the browser window; undo it for print */
  .deck{{display:block!important;gap:0!important;zoom:1!important}}
  .slide{{box-shadow:none!important;margin:0!important;border-radius:0!important;
         break-inside:avoid;page-break-inside:avoid;
         break-after:page;page-break-after:always}}
  .slide:last-child{{break-after:auto;page-break-after:auto}}
}}
</style>
"""

# Long-form documents keep their own print CSS; they just need colour + paper.
DOC_PRINT = f"""
<style>
{MARKER}
@media print{{
  html,body{{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
  @page{{size:A4;margin:14mm}}
}}
</style>
"""


def decks(pattern: str | None):
    """Every <folder>/<folder>.html — the naming convention is the index."""
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        deck = d / f"{d.name}.html"
        if deck.is_file() and (not pattern or pattern in d.name):
            yield deck


def is_slide_deck(html: str) -> bool:
    return bool(re.search(r'<section[^>]*class="[^"]*\bslide\b', html))


def bake(deck: Path) -> str:
    html = deck.read_text(encoding="utf-8")
    kind = "slides" if is_slide_deck(html) else "document"
    block = SLIDE_PRINT if kind == "slides" else DOC_PRINT
    html = BAKED.sub("", html)
    if "</head>" not in html:
        raise SystemExit(f"{deck.name}: no </head> to bake print rules into")
    deck.write_text(html.replace("</head>", block + "</head>", 1), encoding="utf-8")
    return kind


def to_pdf(deck: Path) -> Path:
    out = deck.with_suffix(".pdf")
    subprocess.run(
        [CHROME or find_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
         "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
         "--virtual-time-budget=20000", f"--print-to-pdf={out}", deck.as_uri()],
        capture_output=True, text=True, timeout=300,
    )
    if not out.is_file():
        raise SystemExit(f"{deck.name}: Chrome produced no PDF")
    return out


def to_pngs(pdf: Path, kind: str) -> list[Path]:
    """One PNG per PDF page, numbered so a plain sort is presentation order."""
    out_dir = pdf.parent / "png"
    if out_dir.exists():
        shutil.rmtree(out_dir)  # a deck that lost slides must not keep the strays
    out_dir.mkdir()
    stem = "slide" if kind == "slides" else "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(PNG_DPI), pdf, out_dir / stem],
        check=True, capture_output=True, timeout=300,
    )
    # pdftoppm numbers by page count, so a 9-page deck gets -1 and a 10-page
    # deck gets -01. Renumber to a fixed width so the order is stable either way.
    pages = sorted(out_dir.glob(f"{stem}-*.png"),
                   key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    for n, page in enumerate(pages, 1):
        page.rename(out_dir / f"{stem}-{n:02d}.png")
    return sorted(out_dir.glob(f"{stem}-*.png"))


def main():
    if not shutil.which("pdftoppm"):
        raise SystemExit("pdftoppm not found — run: brew install poppler")
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    found = list(decks(pattern))
    if not found:
        raise SystemExit("no decks matched")
    for deck in found:
        kind = bake(deck)
        out = to_pdf(deck)
        pngs = to_pngs(out, kind)
        px = sum(p.stat().st_size for p in pngs) / 1024
        print(f"{deck.parent.name:32} {kind:9} -> {out.name}  "
              f"{out.stat().st_size/1024:,.0f} KB  + {len(pngs)} png ({px:,.0f} KB)")


if __name__ == "__main__":
    main()
