"""HTML escaping shared by every skill that interpolates into a page.

The page shell that used to live here moved to `skills/annotate/page.py`:
it hard-coded markdown-it and a non-deferred core.js that only annotate
wants, so it was skill-specific logic sitting in the shared layer, not a
capability the others had yet to adopt. Escaping is the part that is
genuinely shared — annotate and deck both build their own HTML and both
must escape the same way.
"""
from __future__ import annotations

import html as _html


def html_escape(s: str) -> str:
    return _html.escape(s, quote=True)
