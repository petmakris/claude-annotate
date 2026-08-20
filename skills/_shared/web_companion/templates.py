"""Shared HTML shell templates used by skill renderers."""
from __future__ import annotations

import html as _html


def html_escape(s: str) -> str:
    return _html.escape(s, quote=True)


def render_page(title: str, head_assets: str, body_html: str,
                response_id: str = "", body_attrs: dict = None) -> str:
    """Standard page shell. Includes the core stylesheet and markdown-it.  The
    skill's body_html should already include any skill-specific scripts.
    head_assets is extra <link>/<script> tags. The palette is a single theme
    defined in core.css :root — no runtime accent switching.

    body_attrs is a generic escape hatch for a caller's own <body data-*>
    attributes — e.g. annotate's project name / repo root for its IDE-jump
    links — given as {name: value}. This module is the shared engine
    (walkthrough and interactive_review render through it too), so it must
    not know what any one skill wants on <body>; it only knows how to splice
    attributes in, and does so safely: every name and value goes through
    html_escape here, same as every other value in this shell. Earlier this
    took a pre-built, pre-escaped HTML string instead — a raw-HTML splice
    guarded only by a docstring, and a footgun waiting for a caller that
    forgot to escape. Defaults to None (no extra attributes) so every
    existing caller is unaffected."""
    attrs = "".join(
        f' {html_escape(str(name))}="{html_escape(str(value))}"'
        for name, value in (body_attrs or {}).items()
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html_escape(title)}</title>
<link rel="stylesheet" href="/static/core.css">
{head_assets}
</head>
<body data-response-id="{html_escape(response_id)}"{attrs}>
{body_html}
<script src="/static/markdown-it.min.js"></script>
<script src="/static/core.js"></script>
</body>
</html>
"""
