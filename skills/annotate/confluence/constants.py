"""The names prepare, body and finalize have to spell identically.

`finalize` deliberately imports nothing that renders — it runs after the page
and its attachments exist, and pulling the diagram renderer into that step
would make a publish fail at its most expensive moment over a module the step
does not use. But the two halves still have to agree on a filename and on the
exact bytes of a media placeholder, and three separate spellings of the same
token is how a placeholder survives into a published page. So the agreement
lives here, in a module with no dependencies at all.
"""
from __future__ import annotations

import re
from html import escape

REPORT_NAME = "report.json"
BODY_TEMPLATE = "body.template.html"
BODY_FINAL = "body.html"

_MEDIA_ID = "__MEDIA_ID__%s__"
_MEDIA_COLLECTION = "__MEDIA_COLLECTION__%s__"


def media_token(block_id: str) -> tuple[str, str]:
    """The (id, collection) placeholder pair for one block's picture.

    The block id is escaped HERE rather than by the caller, because the token
    lands inside an HTML attribute in the body template and `finalize` has to
    rebuild the same bytes to substitute it back out. A block id is
    model-authored and nothing validates its characters, so an id carrying
    `&` or `<` would otherwise produce a template `body.py` wrote one way and
    `finalize` looked for another — an unfilled placeholder, published.
    """
    safe = escape(str(block_id))
    return (_MEDIA_ID % safe, _MEDIA_COLLECTION % safe)


# Non-greedy and character-class-free on purpose: the previous
# `[A-Za-z0-9_-]+` could not see a placeholder built from an id outside that
# charset, so the one guard standing between an unfilled placeholder and a
# broken tile on the published page let it through.
LEFTOVER = re.compile(r"__MEDIA_(?:ID|COLLECTION)__(.+?)__")
