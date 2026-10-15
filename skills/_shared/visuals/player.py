"""Wrap a map or a lane sequence in the reveal player (static/vz-reveal.js), or in a whole HTML page.

``figure`` returns the fragment a page embeds next to vz.css and vz-reveal.js. ``standalone`` returns a
self-contained page with both inlined, for a file, an artifact or a deck. Captions come from the spec:
a map's ``captions.build`` and ``captions.route``, a sequence's ``captions`` (one per step number), each
a list of ``{"title", "text"}``. They travel as JSON in a ``<script type="application/json">``, with
``<`` escaped, and the page writes them only as text.

Pure functions, no I/O.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from . import map_svg, sequence_svg

STATIC = Path(__file__).resolve().parents[1] / "static"
FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800"
         "&family=JetBrains+Mono:wght@400;500;600&display=swap")


def _caps(items: Any) -> list[dict[str, str]]:
    out = []
    for c in items or []:
        if isinstance(c, dict) and isinstance(c.get("title"), str):
            out.append({"title": c["title"], "text": c.get("text", "") if isinstance(c.get("text"), str) else ""})
    return out


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def figure(svg: str, captions: dict[str, Any] | None = None, start: str = "") -> str:
    """The player fragment for an SVG already drawn by map_svg or sequence_svg."""
    data = {k: _caps(v) for k, v in (captions or {}).items() if k in ("build", "route")}
    st = f' data-vz-start="{escape(start, quote=True)}"' if start else ""
    return (f'<div class="vz-player" data-vz-player{st}><div class="vz-stage">{svg}</div>'
            f'<script type="application/json" class="vz-steps">{_json(data)}</script></div>')


def map_figure(spec: dict[str, Any], uid: str) -> str:
    caps = spec.get("captions") or {}
    return figure(map_svg.render(spec, uid), {"build": caps.get("build"), "route": caps.get("route")})


def sequence_figure(spec: dict[str, Any], uid: str) -> str:
    return figure(sequence_svg.render(spec, uid), {"route": spec.get("captions")})


def render_any(spec: dict[str, Any], uid: str) -> str:
    """A spec with ``actors`` is a sequence; one with ``columns`` and ``boxes`` is a map."""
    if "actors" in spec:
        return sequence_figure(spec, uid)
    return map_figure(spec, uid)


def standalone(fragments: list[str], title: str) -> str:
    """One self-contained HTML page holding the given player fragments."""
    css = (STATIC / "vz.css").read_text()
    js = (STATIC / "vz-reveal.js").read_text().replace("</", "<\\/")
    body = "".join(f'<section class="vz-sheet">{f}</section>' for f in fragments)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>
:root {{ --page: #f4f5f2; --ink: #161c1a }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --page: #0f1311; --ink: #e9edea; color-scheme: dark }} }}
:root[data-theme="dark"] {{ --page: #0f1311; --ink: #e9edea; color-scheme: dark }}
body {{ margin: 0; background: var(--page); color: var(--ink); font: 16px/1.5 Inter, system-ui, sans-serif;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 56px }}
.vz-sheet {{ max-width: 1240px; margin: 0 auto 32px; background: var(--vz-card, #fff); border: 1px solid var(--vz-line, #d6dbd5); border-radius: 14px; padding: 18px }}
{css}
</style></head><body>
{body}
<script>{js}</script>
</body></html>
"""
