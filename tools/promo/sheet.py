# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""sheet.py: one contact sheet page of every final clip, to look at them all at once.

    uv run tools/promo/sheet.py [--out .scratch/promo/sheet/index.html] [webp ...]

With no files it takes every docs/img/ca-*.webp and hero.webp (ca-01). Each
clip is shown at its real size with its name, size, frame count, length and the
hook from its section of docs/SHOTLIST.md, with its priority cap (P0 600 KB,
P1 450 KB, P2 300 KB) marked red when the clip is over it. Frame times come
from `webpmux -info`, because Pillow reads 0 ms for these files. The page and copies of the clips go into one folder, so it
can be shared as is. Built from the final files only, never from frames.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHOTLIST = REPO / "docs/SHOTLIST.md"
CAPS_KB = {"P0": 600, "P1": 450, "P2": 300}
ALIAS = {"hero": "ca-01"}


def clip_info(path: Path) -> dict:
    out = subprocess.run(["webpmux", "-info", str(path)], check=True,
                         capture_output=True, text=True).stdout
    w, h = map(int, re.search(r"Canvas size:\s*(\d+)\s*x\s*(\d+)", out).groups())
    durations = [int(m.group(1)) for m in re.finditer(r"^\s*\d+:\s+(?:\S+\s+){5}(\d+)", out, re.M)]
    return {"w": w, "h": h, "frames": len(durations), "s": sum(durations) / 1000,
            "kb": path.stat().st_size / 1024}


def section(clip_id: str) -> str:
    """The clip's section of docs/SHOTLIST.md: from `## <id>` to the next `## `."""
    if not SHOTLIST.exists():
        return ""
    m = re.search(r"^## %s\b.*?(?=^## |\Z)" % re.escape(clip_id), SHOTLIST.read_text(), re.M | re.S)
    return m.group(0) if m else ""


def caption(clip_id: str) -> str:
    m = re.search(r"^\W*hook:?\**:?\s*(.+)$", section(clip_id), re.M | re.I)
    return m.group(1).strip() if m else ""


def cap_kb(clip_id: str):
    sec = section(clip_id)
    m = re.search(r"priority\W*(P\d)", sec, re.I) or re.search(r"\b(P[0-2])\b", sec)
    return CAPS_KB.get(m.group(1).upper()) if m else None


CSS = """
body{font:15px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;margin:0;background:#f6f6f4;color:#1f2328}
header{padding:20px 28px;border-bottom:1px solid #ddd;background:#fff;display:flex;gap:24px;align-items:baseline}
header h1{font-size:20px;margin:0} header span{color:#57606a}
main{padding:24px 28px;display:grid;gap:28px}
figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px;max-width:900px}
figure img{display:block;max-width:100%;height:auto;border:1px solid #eee}
figcaption{margin-top:10px;display:grid;grid-template-columns:110px 1fr auto;gap:12px;align-items:baseline}
.id{font-weight:600} .num{color:#57606a;font-variant-numeric:tabular-nums;white-space:nowrap}
.over{color:#cf222e;font-weight:600}
"""


def build(files, out: Path, caps_kb=None):
    out.parent.mkdir(parents=True, exist_ok=True)
    rows, total = [], 0.0
    for f in files:
        f = Path(f)
        info = clip_info(f)
        total += info["kb"]
        shutil.copy(f, out.parent / f.name)
        cid = ALIAS.get(f.stem, f.stem)
        cap = (caps_kb or {}).get(cid) or cap_kb(cid)
        over = cap and info["kb"] > cap
        size = f'{info["kb"]:.0f} KB' + (f' (cap {cap})' if cap else "")
        rows.append(
            f'<figure><img src="{html.escape(f.name)}" width="{info["w"]}" height="{info["h"]}" alt="{html.escape(cid)}">'
            f'<figcaption><span class="id">{html.escape(cid)}</span><span>{html.escape(caption(cid))}</span>'
            f'<span class="num{" over" if over else ""}">{size} · {info["frames"]} frames · {info["s"]:.1f} s · {info["w"]}×{info["h"]}</span>'
            f'</figcaption></figure>')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Promo clips</title>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>'
            f'<header><h1>Promo clips</h1><span>{len(files)} clips · {total / 1024:.2f} MB</span></header>'
            f'<main>{"".join(rows)}</main></body></html>')
    out.write_text(page)
    return out, total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out", default=None, help="default: <scratch>/sheet/index.html, outside the checkout")
    a = ap.parse_args(argv)
    if a.out is None:
        from rec import scratch_root
        a.out = str(scratch_root() / "sheet" / "index.html")
    files = a.files or sorted({*REPO.glob("docs/img/ca-*.webp"), *REPO.glob("docs/img/hero.webp")},
                                key=lambda p: ALIAS.get(p.stem, p.stem))
    if not files:
        raise SystemExit("sheet.py: no clips found")
    out, total = build(files, Path(a.out))
    print(f"{out} ({len(files)} clips, {total / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
