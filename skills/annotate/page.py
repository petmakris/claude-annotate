"""annotate's HTML page shell.

This lived in `skills/_shared/web_companion/templates.py` and was moved here
once it was clear it is not a shared capability: it hard-codes markdown-it and
a non-deferred core.js, which only annotate wants. Deck opted out explicitly
and renders its own shell; walkthrough and interactive_review serve static
"runs in IntelliJ" notices with nothing interpolated at all, so neither will
ever need a shell. What IS shared — `html_escape` — stays in the engine, and
this module uses it.
"""
from __future__ import annotations

from skills._shared.web_companion.templates import html_escape


def render_page(title: str, head_assets: str, body_html: str,
                response_id: str = "", body_attrs: dict = None) -> str:
    """Standard page shell. Includes the core stylesheet and markdown-it.  The
    skill's body_html should already include any skill-specific scripts.
    head_assets is extra <link>/<script> tags. The palette is a single theme
    defined in core.css :root — no runtime accent switching.

    body_attrs carries the caller's own <body data-*> attributes — annotate's
    project name / repo root for its IDE-jump links — given as {name: value}.
    Kept generic rather than named fields, and safe: every name and value goes
    through html_escape here, same as every other value in this shell. Earlier this
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
