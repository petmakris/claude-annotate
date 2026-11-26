# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""encode.py: turn a frame folder from rec.py into one animated WebP.

    uv run tools/promo/encode.py <frames dir> <out.webp> [--width 800] [--q 70]

Reads frames.json (file and delay of each frame), scales every frame down to
--width with Lanczos, merges frames that are the same as the one before (their
delays add up), and hands the list to img2webp with a delay per frame. Then it
strips EXIF and XMP with webpmux and prints size, frame count and duration.

Lossy -q 70 with -mixed is the default (the repo's shot-list rule). On a flat
background it can leave faint trails where the cursor was; look at the last
frames, and if they show, encode with --near-lossless 40 instead.

Needs img2webp and webpmux (Debian and Ubuntu: `apt-get install webp`; macOS:
`brew install webp`). ffmpeg is not used: many builds have no WebP encoder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        sys.exit(f"encode.py: {tool} is not installed (apt-get install webp, or brew install webp)")
    return path


def strip_meta(webpmux, src, dst):
    """Copy src to dst without EXIF, XMP or ICC chunks. webpmux -strip fails on
    a chunk that is not there, so only the chunks -info lists are stripped."""
    info = subprocess.run([webpmux, "-info", str(src)], capture_output=True, text=True).stdout
    feats = next((l for l in info.splitlines() if l.lower().startswith("features present")), "")
    cur = Path(src)
    for i, chunk in enumerate(k for k in ("EXIF", "XMP", "ICCP") if k in feats):
        nxt = Path(dst).with_suffix(".s%d.webp" % i)
        subprocess.run([webpmux, "-strip", chunk.lower(), str(cur), "-o", str(nxt)],
                       check=True, capture_output=True)
        cur = nxt
    shutil.copyfile(cur, dst)
    for f in Path(dst).parent.glob(Path(dst).stem + ".s*.webp"):
        f.unlink()


def encode(frames_dir, out, width=800, q=70, lossless=False, max_ms=None, near_lossless=None):
    from PIL import Image
    frames_dir = Path(frames_dir)
    meta = json.loads((frames_dir / "frames.json").read_text())
    frames = meta["frames"]
    if not frames:
        sys.exit("encode.py: no frames")
    img2webp, webpmux = need("img2webp"), need("webpmux")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="promo-enc-") as tmp:
        tmp = Path(tmp)
        merged: list[list] = []          # [path, ms, digest]
        for f in frames:
            im = Image.open(frames_dir / f["file"]).convert("RGB")
            if im.width != width:
                h = round(im.height * width / im.width)
                im = im.resize((width, h), Image.LANCZOS)
            digest = hashlib.sha1(im.tobytes()).hexdigest()
            if merged and merged[-1][2] == digest:
                merged[-1][1] += f["ms"]
                continue
            p = tmp / ("s%04d.png" % len(merged))
            im.save(p)
            merged.append([p, f["ms"], digest])
        # -mixed lets img2webp pick lossy or lossless per frame, so it is only
        # used for the lossy default; --lossless and --near-lossless stay exact.
        if near_lossless is not None:
            cmd = [img2webp, "-loop", "0", "-near_lossless", str(near_lossless), "-m", "6"]
        elif lossless:
            cmd = [img2webp, "-loop", "0", "-m", "6"]
        else:
            cmd = [img2webp, "-loop", "0", "-mixed"]
        for p, ms, _ in merged:
            ms = min(ms, max_ms) if max_ms else ms
            if near_lossless is not None:
                cmd += ["-d", str(ms), "-lossless", str(p)]
            elif lossless:
                cmd += ["-d", str(ms), "-lossless", str(p)]
            else:
                cmd += ["-d", str(ms), "-lossy", "-q", str(q), "-m", "6", str(p)]
        raw = tmp / "raw.webp"
        cmd += ["-o", str(raw)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        strip_meta(webpmux, raw, out)
    total = sum(m[1] for m in merged)
    info = {"file": str(out), "bytes": out.stat().st_size, "frames": len(merged),
            "duration_s": round(total / 1000, 2), "width": width}
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("frames_dir")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--q", type=int, default=70)
    ap.add_argument("--lossless", action="store_true")
    ap.add_argument("--near-lossless", type=int, default=None, metavar="N",
                    help="near-lossless at level N (0-100, 40 is a good start): no faint cursor "
                         "trails on flat backgrounds, which lossy -q 70 can leave, at about twice the size")
    ap.add_argument("--cap-kb", type=int, default=0, help="fail when the file is larger")
    a = ap.parse_args(argv)
    info = encode(a.frames_dir, a.out, a.width, a.q, a.lossless, near_lossless=a.near_lossless)
    print(json.dumps(info))
    if a.cap_kb and info["bytes"] > a.cap_kb * 1024:
        sys.exit(f"encode.py: {info['bytes'] // 1024} KB is over the cap of {a.cap_kb} KB")


if __name__ == "__main__":
    main()
