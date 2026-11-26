# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow", "ocrmac; sys_platform == 'darwin'"]
# ///
"""scan.py: the privacy gate. Nothing is committed until it passes.

Three passes, each a hard stop:

1. source: every text file given (clip scripts, fixtures, captions, casts,
   built HTML, shot-list parts) is matched against deny.txt.
2. frames: every distinct frame of every .webp given is scaled up 2x and read
   by OCR (Apple Vision through ocrmac on macOS, tesseract elsewhere); the text
   is matched against the same list. OCR misses small text, so this is a
   backstop: no clip may use a real screen as its source in the first place.
3. file: `webpmux -info` must show no EXIF and no XMP (`--fix` strips them).

    uv run tools/promo/scan.py tools/promo/clips tools/promo/fixtures docs/img/ca-01.webp
    uv run tools/promo/scan.py --no-ocr <paths>        # passes 1 and 3 only
    uv run tools/promo/scan.py hash <word>...          # deny.txt lines for private words

deny.txt holds generic patterns in plain text (`re:` lines) and private words
(names of people, companies, hosts, ticket prefixes) only as salted SHA-256
hashes (`h:` lines), so the public repo never spells them out. A text is cut
into words and dotted or dashed compounds (`build-box`, `a&b`, `ab-12`), and
each one is hashed and looked up. Words that only one machine should know can
also go, in plain text, in a file outside the repo named by $PROMO_DENY_EXTRA.
Exit 0 when clean, 1 with one line per hit.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SALT = "promo-deny:"
TEXT_EXT = {".py", ".json", ".md", ".txt", ".html", ".htm", ".js", ".css", ".cast", ".sh",
            ".yaml", ".yml", ".svg", ".csv", ".java", ".ts", ".sql", ".toml", ".jsonl", ".xml"}
SKIP_NAMES = {"deny.txt"}
WORD_RE = re.compile(r"[a-z0-9]+(?:[-_.&][a-z0-9]+)*")


def h(word: str) -> str:
    return hashlib.sha256((SALT + word.lower()).encode()).hexdigest()[:20]


class Deny:
    def __init__(self, path=HERE / "deny.txt", extra=None):
        self.patterns: list[tuple[str, re.Pattern]] = []
        self.allow: list[re.Pattern] = []
        self.hashes: set[str] = set()
        self.plain: set[str] = set()
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, val = line.partition(":")
            val = val.strip()
            if kind == "re":
                self.patterns.append((val, re.compile(val, re.I)))
            elif kind == "allow":
                self.allow.append(re.compile(val, re.I))
            elif kind == "h":
                self.hashes.add(val.split()[0])
        extra = extra or os.environ.get("PROMO_DENY_EXTRA")
        if extra and Path(extra).exists():
            for line in Path(extra).read_text().splitlines():
                if line.strip() and not line.startswith("#"):
                    self.plain.add(line.strip().lower())

    def hits(self, text: str) -> list[str]:
        out = []
        clean = text
        for a in self.allow:
            clean = a.sub(" ", clean)
        for src, rx in self.patterns:
            for m in rx.finditer(clean):
                out.append(f"pattern {src!r} matched {m.group(0)!r}")
        low = clean.lower()
        seen = set()
        for m in WORD_RE.finditer(low):
            whole = m.group(0)
            parts = {whole, *re.split(r"[-_.&]", whole)}
            # also every run of 2+ pieces, so 'acme-box-one.lan' finds 'box-one'
            pieces = re.split(r"([-_.&])", whole)
            for i in range(0, len(pieces), 2):
                for j in range(i + 2, len(pieces), 2):
                    parts.add("".join(pieces[i:j + 1]))
            for w in parts:
                if not w or w in seen:
                    continue
                seen.add(w)
                if h(w) in self.hashes or w in self.plain:
                    out.append(f"private word {w!r}")
        return out


# ── pass 1: source ─────────────────────────────────────────────────────
def iter_text_files(paths):
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in TEXT_EXT and f.name not in SKIP_NAMES \
                        and "__pycache__" not in f.parts:
                    yield f
        elif p.is_file() and p.suffix.lower() in TEXT_EXT and p.name not in SKIP_NAMES:
            yield p


def scan_sources(paths, deny):
    bad = []
    for f in iter_text_files(paths):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for hit in deny.hits(line):
                bad.append(f"{f}:{n}: {hit}")
    return bad


# ── pass 2: frames ─────────────────────────────────────────────────────
def ocr(png: Path) -> str:
    if sys.platform == "darwin":
        from ocrmac import ocrmac
        return "\n".join(t for t, *_ in ocrmac.OCR(str(png)).recognize())
    tess = shutil.which("tesseract")
    if not tess:
        sys.exit("scan.py: no OCR: install tesseract (apt-get install tesseract-ocr), or run with --no-ocr")
    return subprocess.run([tess, str(png), "stdout", "--psm", "11"],
                          capture_output=True, text=True).stdout


def webp_frames(path: Path, tmp: Path):
    from PIL import Image, ImageSequence
    im = Image.open(path)
    seen = set()
    for i, fr in enumerate(ImageSequence.Iterator(im)):
        fr = fr.convert("RGB")
        d = hashlib.sha1(fr.tobytes()).hexdigest()
        if d in seen:
            continue
        seen.add(d)
        big = fr.resize((fr.width * 2, fr.height * 2), Image.LANCZOS)
        out = tmp / f"{path.stem}-{i:04d}.png"
        big.save(out)
        yield i, out


def scan_frames(paths, deny, every=1):
    bad = []
    webps = [p for p in map(Path, paths) if p.is_file() and p.suffix == ".webp"]
    webps += [f for p in map(Path, paths) if p.is_dir() for f in sorted(p.rglob("*.webp"))]
    with tempfile.TemporaryDirectory(prefix="promo-scan-") as tmp:
        for w in webps:
            for k, (i, png) in enumerate(webp_frames(w, Path(tmp))):
                if k % every:
                    continue
                for hit in deny.hits(ocr(png)):
                    bad.append(f"{w} frame {i}: {hit}")
    return bad, webps


# ── pass 3: file ───────────────────────────────────────────────────────
def scan_meta(webps, fix=False):
    mux = shutil.which("webpmux")
    if not mux:
        sys.exit("scan.py: webpmux is not installed (apt-get install webp, or brew install webp)")
    bad = []
    for w in webps:
        info = subprocess.run([mux, "-info", str(w)], capture_output=True, text=True).stdout
        feats = next((l for l in info.splitlines() if l.lower().startswith("features present")), "")
        found = [k for k in ("EXIF", "XMP", "ICCP") if k in feats]
        if found and fix:
            for k in found:
                subprocess.run([mux, "-strip", k.lower(), str(w), "-o", str(w)], check=True,
                               capture_output=True)
            found = []
        if found:
            bad.append(f"{w}: carries {', '.join(found)} (run with --fix)")
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hash"]:
        for w in argv[1:]:
            print(f"h: {h(w)}")
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--every", type=int, default=1, help="OCR every Nth distinct frame")
    ap.add_argument("--fix", action="store_true", help="strip EXIF and XMP in place")
    ap.add_argument("--deny", default=str(HERE / "deny.txt"))
    a = ap.parse_args(argv)
    deny = Deny(a.deny)
    bad = scan_sources(a.paths, deny)
    webps = []
    if not a.no_ocr:
        fb, webps = scan_frames(a.paths, deny, a.every)
        bad += fb
    else:
        webps = [p for p in map(Path, a.paths) if p.suffix == ".webp"]
        webps += [f for p in map(Path, a.paths) if p.is_dir() for f in sorted(p.rglob("*.webp"))]
    bad += scan_meta(webps, a.fix)
    for b in bad:
        print(b)
    print(f"scan.py: {'FAIL' if bad else 'clean'}: {len(bad)} hits, "
          f"{len(webps)} webp files, OCR {'off' if a.no_ocr else 'on'}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
