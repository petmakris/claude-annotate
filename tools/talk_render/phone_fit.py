#!/usr/bin/env python3
"""390 px fit check for the graph, map and table boards (from bulldozer run bd1125).

    uv run --with playwright python tools/talk_render/phone_fit.py --repo <checkout> --answer <file> --code <folder> --out <dir>

Runs render.py's phone pass only (with --all-widths: every pass) (the desktop page just sends the answer) and, at every shot, probes the stage frame:
  - the board does not pan sideways (a short table whole: 16 cells or fewer),
  - the pointed part, every lane label and the lit arrow's two ends are inside the 390 px viewport,
  - no word of a table cell breaks across lines (mid-word),
  - the SVG text of a graph is not scaled under 11 px (a map is fitted whole; its smallest text is reported).
Prints one line per phone shot and the failures; exit 1 when any shot fails. The probe is stored in frames.json as 'fit'."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402

FLOOR = {"graph": 11, "map": 0}   # a map fits the width whole: its smallest text is reported, not floored

PROBE = r"""() => {
  const vw = window.innerWidth, R = (e) => e.getBoundingClientRect();
  const out = {vw, kind: null, issues: [], min_font: null, cells: 0};
  const inside = (r) => r.left >= -1 && r.right <= vw + 1;
  const broken = (root) => {
    const bad = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      for (const m of n.nodeValue.matchAll(/\S+/g)) {
        const r = document.createRange(); r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
        const tops = new Set([...r.getClientRects()].map((q) => Math.round(q.top / 4)));
        if (tops.size > 1) bad.push(m[0]);
      }
    }
    return bad;
  };
  const svgs = [...document.querySelectorAll('svg.vz')];
  const svg = svgs.find((s) => R(s).width > 0);
  const table = document.querySelector('.md.grid table');
  if (table) {
    out.kind = 'table';
    const wrap = table.closest('.tablewrap') || table.parentElement;
    out.cells = table.querySelectorAll('td, th').length;
    out.pans = wrap.scrollWidth > wrap.clientWidth + 1;
    if (out.cells <= 16 && out.pans) out.issues.push(`a table of ${out.cells} cells pans sideways (${wrap.scrollWidth} > ${wrap.clientWidth})`);
    const b = broken(table);
    if (b.length) out.issues.push('mid-word break: ' + [...new Set(b)].join(', '));
    const wr = R(wrap);
    for (const e of table.querySelectorAll('tr.g-cur, td.k-focus, th.g-col')) {
      const r = R(e);
      if (r.top < wr.top - 2 || r.bottom > wr.bottom + 2) out.issues.push('lit ' + e.tagName + ' outside the table box vertically');
      else if (!out.pans && !inside(r)) out.issues.push('lit ' + e.tagName + ' outside the viewport');
    }
  } else if (svg) {
    const kind = svg.dataset.vz === 'graph' ? 'graph' : 'map';
    out.kind = kind;
    const box = svg.closest('.visual, .vzmap, .vzgraph') || svg.parentElement;
    let pan = box;
    for (let e = svg.parentElement; e && e !== document.body; e = e.parentElement) if (e.scrollWidth > e.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(e).overflowX)) { pan = e; break; }
    out.pans = pan.scrollWidth > pan.clientWidth + 1;
    if (out.pans) out.issues.push(`the ${kind} pans sideways (${pan.scrollWidth} > ${pan.clientWidth})`);
    const sr = R(svg);
    let min = 1e9;
    const lit = [...svg.querySelectorAll('.now')];
    for (const t of svg.querySelectorAll('text')) {
      const ctm = t.getScreenCTM(); if (!ctm) continue;
      const fs = parseFloat(getComputedStyle(t).fontSize) * Math.hypot(ctm.a, ctm.b);
      if (fs < min) min = fs;
      const r = R(t);
      const seen = r.width > 0 && r.top >= sr.top - 1 && r.bottom <= sr.bottom + 1 && r.left >= sr.left - 1 && r.right <= sr.right + 1;
      if (seen && !inside(r)) out.issues.push('text outside the viewport: ' + t.textContent.trim().slice(0, 24));
    }
    out.min_font = Math.round(min * 10) / 10;
    if (min < __FLOOR__[kind]) out.issues.push(`text scaled to ${out.min_font}px, under the ${__FLOOR__[kind]}px floor`);
    for (const e of lit) {
      const r = R(e);
      if (!r.width && !r.height) continue;
      if (!inside(r)) out.issues.push('lit part outside the viewport: ' + (e.dataset.key || e.tagName));
      if (e.tagName === 'path' && e.getTotalLength) {
        const ctm = e.getScreenCTM(), L = e.getTotalLength();
        for (const d of [0, L]) { const p = e.getPointAtLength(d), x = p.x * ctm.a + p.y * ctm.c + ctm.e; if (x < -1 || x > vw + 1) out.issues.push('arrow end outside the viewport: ' + e.dataset.key); }
      }
    }
    out.lit = lit.length;
  } else {
    const map = document.querySelector('.map');
    if (map) {
      out.kind = 'map';
      out.pans = map.scrollWidth > map.clientWidth + 1;
      if (out.pans) out.issues.push('the map pans sideways');
      for (const e of map.querySelectorAll('.m-cur')) if (!inside(R(e))) out.issues.push('lit part outside the viewport');
    }
  }
  return out;
}""".replace("__FLOOR__", json.dumps(FLOOR))


def fit_probe(page):
    for fr in page.frames:
        try:
            got = fr.evaluate(PROBE)
        except Exception:
            continue
        if got and got.get("kind"):
            return got
    return None


_shot = render.Shooter.shot


def shot(self, page, prefix, label, t, caption, board, width, theme):
    _shot(self, page, prefix, label, t, caption, board, width, theme)
    self.frames[-1]["fit"] = fit_probe(page)


render.Shooter.shot = shot
ALL_WIDTHS = "--all-widths" in sys.argv
if ALL_WIDTHS:
    sys.argv.remove("--all-widths")   # also probe the desktop, TV and dark shots (tables: mid-word breaks)
_play = render.play_through


def play(page, shooter, prefix, *a, **kw):
    if prefix == "d" and not ALL_WIDTHS:
        return None   # the desktop page only sends the answer
    return _play(page, shooter, prefix, *a, **kw)


render.play_through = play


def report(out: Path) -> int:
    bad = 0
    for f in json.load(open(out / "frames.json")):
        fit = f.get("fit")
        if fit is None or (f["width"] > 480 and not ALL_WIDTHS):
            continue
        status = "OK" if not fit["issues"] else "FAIL"
        bad += status == "FAIL"
        print(f"{f['file']} w{f['width']} {f['theme']} {fit['kind']} cells={fit.get('cells')} min_font={fit.get('min_font')} pans={fit.get('pans')} {status}")
        for i in fit["issues"][:6]:
            print("   ", i)
    print("phone fit:", "FAIL" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    out = Path(argv[argv.index("--out") + 1])
    sys.argv = [sys.argv[0]] + argv + ([] if ALL_WIDTHS else ["--no-dark"])
    rc = render.main()
    sys.exit(report(out) or rc)
