# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright", "pillow"]
# ///
"""ca-13-app-map.py: the app map of an invented shop, a part lit, then its detail map.

The map is real: `fixtures/ca-13/make_repo.py` builds an invented 13-module
Gradle repo, `app_map check` and `build` (with APP_MAP_HOME in the scratch
folder) turn `fixtures/ca-13/source.json` into `top.svg`, `orders.svg` and
`map.json`, and `tools/vz_check.py` finds 0 faults in both drawings.

The lighting is drawn by this script. The app map is shown by the IntelliJ
plugin (Cmd+Shift+M), which has no browser page; this page is a stand-in that
paints the plugin's file mode the way `AppMapCanvas.paint` does: the open
file's part in the accent, its arrows lit, everything else dimmed, team pills
from `map.json` owners, and a header row with file, place, module and owners.
A caption in the frame says so.

    uv run tools/promo/clips/ca-13-app-map.py [--port 19166] [--check]
"""
import argparse
import html
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rec import Recorder, frames_dir, scratch_root  # noqa: E402
from termcast import Serve  # noqa: E402
from encode import encode  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tools" / "promo" / "fixtures" / "ca-13"
STATIC = ROOT / "skills" / "_shared" / "static"
OUT = ROOT / "docs" / "img" / "ca-13.webp"
W, H = 1000, 880

# The plugin's light palette and team colours (ide-plugin AppMapCanvas.Palette.light, TEAM_COLOURS).
PAGE = """<!doctype html><html data-theme="light"><head><meta charset="utf-8"><style>
@font-face{font-family:"Inter";src:url("fonts/Inter-Variable.woff2") format("woff2");font-weight:100 900}
@font-face{font-family:"JetBrains Mono";src:url("fonts/JetBrainsMono-Variable.woff2") format("woff2");font-weight:100 900}
%(css)s
html,body{margin:0;background:#fff;font-family:Inter,sans-serif;color:#1F2328}
#hd{height:46px;display:flex;align-items:center;gap:14px;padding:0 24px;border-bottom:1px solid #d8dee4;font-size:14px;white-space:nowrap}
#hd b{font-weight:650} #hd .acc{color:#0A58CA} #hd .mut{color:#57606A} #hd code{font:12.5px "JetBrains Mono",monospace;color:#1F2328}
#hd .sp{flex:1} #hd .built{font-size:12px;color:#57606A}
#hd .btn{font-size:12.5px;border:1px solid #d0d7de;border-radius:6px;padding:3px 9px;color:#1F2328}
#stage{padding:8px 24px 0}
.map{display:none} .map.on{display:block}
svg.vz *{transition:none!important}
svg.vz [data-key]{transition:none}
svg.vz.dim [data-key]:not(.lit){opacity:.28}
svg.vz.dim text[data-key]:not(.lit){opacity:.38}
svg.vz rect.bx.lit.here{fill:#CFE2FF;stroke:#0A58CA;stroke-width:2}
svg.vz path.lit,svg.vz line.lit{stroke:#0A58CA!important;stroke-width:2.2}
#cap{position:fixed;left:0;right:0;bottom:0;height:34px;display:flex;align-items:center;justify-content:center;
 font-size:13px;color:#57606A;background:#f6f8fa;border-top:1px solid #d8dee4}
</style></head><body>
<div id="hd"><b id="file">App map</b><span id="place" class="acc"></span><span id="mod" class="mut"></span><span id="own" class="mut"></span>
<span class="sp"></span><span class="built">Map built 2 Mar</span><span id="back" class="btn" style="display:none">&#8592; Back</span><span class="btn">File</span><span class="btn">Branch</span><span class="btn">Tabs</span></div>
<div id="stage"><div class="map on" id="m-top">%(top)s</div><div class="map" id="m-orders">%(orders)s</div></div>
<div id="cap">Browser stand-in for the IntelliJ overlay (Cmd+Shift+M): the map is the real build, the lighting is drawn by the clip</div>
<script>
const MAP = %(mapjson)s;
const TEAM_COLOURS = ["#2F81F7","#E8590C","#2F9E44","#AE3EC9","#F08C00","#0C8599"];
const teams = [];
for (const id in MAP.owners) for (const o of MAP.owners[id]) if (o.team && !teams.includes(o.team)) teams.push(o.team);
teams.sort();
const colour = t => TEAM_COLOURS[teams.indexOf(t) %% TEAM_COLOURS.length];
const mix = (hex, toward, k) => { const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255];
  return `rgb(${c.map(v => Math.round(v + (toward - v) * k)).join(",")})`; };
function pills(svg) {
  const NS = "http://www.w3.org/2000/svg";
  for (const r of svg.querySelectorAll("rect.bx[data-key^='box:']")) {
    const id = r.dataset.key.slice(4), own = MAP.owners[id];
    if (!own) continue;
    const total = own.reduce((a, o) => a + o.files, 0);
    let tags = own.filter(o => o.team && o.files * 5 >= total).slice(0, 3)
      .map(o => ({text: MAP.teams[o.team] || o.team.split("/").pop().toUpperCase(), c: colour(o.team)}));
    if (!tags.length) tags = [{text: "No owner", c: "#8C959F"}];
    // The build ends each part's box with a blank line, and the pills go there, from its left; a box with no
    // such line (a slice, or a box holding slices) gets them right-aligned on its name's line (AppMapCanvas.paintTags).
    const texts = [...svg.querySelectorAll(`text[data-key="${r.dataset.key}"]`)];
    const last = texts[texts.length - 1];
    const blank = last && last.textContent.trim() === "" && last.getAttribute("y") > +r.getAttribute("y") + 40;
    const name = texts[0];
    let x = +r.getAttribute("x") + 18, y = blank ? +last.getAttribute("y") - 13 : +name.getAttribute("y") - 13;
    const right = !blank;
    const g = document.createElementNS(NS, "g"); g.setAttribute("data-key", r.dataset.key);
    svg.append(g);
    const made = [];
    for (const t of tags) {
      const tx = document.createElementNS(NS, "text"); tx.textContent = t.text;
      tx.setAttribute("style", `font:600 11px Inter;fill:${mix(t.c, 0, .45)}`);
      g.append(tx);
      const w = tx.getBBox().width + 14;
      const p = document.createElementNS(NS, "rect");
      Object.entries({width: w, height: 18, rx: 9, fill: mix(t.c, 255, .82), stroke: mix(t.c, 255, .35)})
        .forEach(([k, v]) => p.setAttribute(k, v));
      g.insertBefore(p, tx); made.push([p, tx, w]);
    }
    if (right) x = +r.getAttribute("x") + +r.getAttribute("width") - 14 - made.reduce((a, m) => a + m[2] + 6, -6);
    for (const [p, tx, w] of made) {
      p.setAttribute("x", x); p.setAttribute("y", y); tx.setAttribute("x", x + 7); tx.setAttribute("y", y + 13); x += w + 6;
    }
  }
}
function holders(svg, id) {
  const r = svg.querySelector(`rect.bx[data-key="box:${id}"]`); if (!r) return [];
  const b = r.getBBox(), out = [];
  for (const o of svg.querySelectorAll("rect.bx[data-key^='box:']")) {
    if (o === r) continue; const c = o.getBBox();
    if (c.x <= b.x && c.y <= b.y && c.x + c.width >= b.x + b.width && c.y + c.height >= b.y + b.height) out.push(o.dataset.key.slice(4));
  }
  return out;
}
window.light = function (mapId, id, head) {
  document.querySelectorAll(".map").forEach(m => m.classList.toggle("on", m.id === "m-" + mapId));
  const svg = document.querySelector(`#m-${mapId} svg`);
  svg.querySelectorAll(".lit,.here").forEach(e => e.classList.remove("lit", "here"));
  svg.querySelectorAll("path[data-head]").forEach(e => e.setAttribute("marker-end", e.dataset.head));
  svg.classList.toggle("dim", !!id);
  if (id) {
    const ends = [id, ...holders(svg, id)];
    for (const e of svg.querySelectorAll("[data-key]")) {
      const k = e.dataset.key;
      if (k.startsWith("box:") && ends.includes(k.slice(4))) { e.classList.add("lit"); if (k === "box:" + id) e.classList.add("here"); }
      if (k.startsWith("edge:")) { const [a, b] = k.slice(5).split("#")[0].split("->"); if (ends.includes(a) || ends.includes(b)) e.classList.add("lit"); }
    }
    for (const p of svg.querySelectorAll("path.lit")) if (p.getAttribute("marker-end")) p.dataset.head = p.dataset.head || p.getAttribute("marker-end"), p.setAttribute("marker-end", `url(#lit-head-${mapId})`);
  }
  const h = head || {};
  document.getElementById("file").textContent = h.file || "App map · shop";
  document.getElementById("place").textContent = h.place || "";
  document.getElementById("mod").innerHTML = h.module ? 'Module <code>' + h.module + '</code>' : "";
  document.getElementById("own").textContent = h.owners || "";
  document.getElementById("back").style.display = mapId === "top" ? "none" : "";
};
for (const svg of document.querySelectorAll("svg.vz")) {
  const id = svg.closest(".map").id.slice(2);
  svg.querySelector("defs").insertAdjacentHTML("beforeend",
    '<marker id="lit-head-' + id + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#0A58CA"/></marker>');
}
document.fonts.ready.then(() => {
  // each drawing fitted to the area under the header, at most twice its size (AppMapCanvas.layout, maxScale 2)
  const areaW = innerWidth - 48, areaH = innerHeight - 46 - 34 - 12;
  for (const m of document.querySelectorAll(".map")) {
    const was = m.classList.contains("on"); m.classList.add("on");
    const svg = m.querySelector("svg"), vb = svg.viewBox.baseVal;
    const k = Math.min(areaW / vb.width, areaH / vb.height, 2);
    svg.style.width = vb.width * k + "px";
    pills(svg); m.classList.toggle("on", was);
  }
  window.ready = true;
});
</script></body></html>"""


def build_map(scratch: Path, check: bool) -> Path:
    repo = scratch / "shop"
    subprocess.run([sys.executable, str(FIX / "make_repo.py"), str(repo)], check=True, stdout=subprocess.DEVNULL)
    home = scratch / "app-map"
    (home / "shop").mkdir(parents=True, exist_ok=True)
    (home / "shop" / "source.json").write_text((FIX / "source.json").read_text())
    env = dict(os.environ, APP_MAP_HOME=str(home))
    for cmd in ("check", "build"):
        r = subprocess.run([str(ROOT / "bin" / "claude-annotate"), "app_map.app_map", cmd, "shop", "--repo", str(repo)],
                           env=env, capture_output=True, text=True)
        rep = json.loads(r.stdout)
        if not rep["ok"]:
            sys.exit(f"app_map {cmd} failed: {rep['errors']}")
    out = home / "shop"
    if check:
        subprocess.run(["uv", "run", str(ROOT / "tools" / "vz_check.py"), "check", str(out / "top.svg"),
                        str(out / "orders.svg"), "--out", str(scratch / "vzcheck")], check=True)
    return out


def page(built: Path, site: Path):
    import shutil
    site.mkdir(parents=True, exist_ok=True)
    if not (site / "fonts").exists():
        shutil.copytree(STATIC / "fonts", site / "fonts")
    m = json.loads((built / "map.json").read_text())
    slim = {"owners": m["owners"], "teams": m["teams"]}
    (site / "index.html").write_text(PAGE % {
        "css": (STATIC / "vz.css").read_text(),
        "top": (built / "top.svg").read_text(), "orders": (built / "orders.svg").read_text(),
        "mapjson": json.dumps(slim)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19166)
    ap.add_argument("--check", action="store_true", help="also run tools/vz_check.py on the drawings")
    a = ap.parse_args()
    scratch = scratch_root() / "ca-13"
    built = build_map(scratch, a.check)
    site = scratch / "site"
    page(built, site)
    out = frames_dir("ca-13")
    with Serve(site, a.port) as srv, Recorder(out, viewport=(W, H), fps=12) as r:
        r.goto(srv.url("/"))
        r.page.wait_for_function("window.ready === true")
        r.hide_cursor()
        r.page.evaluate("light('top', null, null)")
        r.shot(); r.hold(1.6)
        # a file in the checkout module's retry slice is open in the editor
        r.page.evaluate("""light('top', 'checkout-retry', {file: 'RetryService.java', place: 'Checkout › Retry',
                           module: 'checkout', owners: '@acme/checkout'})""")
        r.shot(); r.hold(2.0)
        # another tab: a file of the orders module
        r.page.evaluate("""light('top', 'orders', {file: 'OrdersService.java', place: 'Orders',
                           module: 'orders', owners: '@acme/checkout'})""")
        r.shot(); r.hold(1.0)
        # click the lit box to open its detail map, as the overlay does
        r.show_cursor()
        r.pos = (W * 0.5, H * 0.92)
        r.glide("#m-top rect.bx[data-key='box:orders']", seconds=0.6)
        r.page.evaluate("""light('orders', 'orders-returns', {file: 'ReturnsService.java', place: 'Orders › Returns',
                           module: 'orders', owners: '@acme/checkout'})""")
        for i in range(4):
            r.shot(ring=i / 4)
        r.hide_cursor()
        r.shot(); r.hold(2.0)
    info = encode(out, OUT, width=800, near_lossless=40)  # lossy left ghosts of the top map on the detail map
    print(json.dumps(info))


if __name__ == "__main__":
    main()
