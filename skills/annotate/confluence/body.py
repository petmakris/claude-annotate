"""The annotate document as a Confluence page body.

Confluence's HTML format maps to ADF, so the vocabulary is fixed: `<figure
data-type="media-single">` for a picture, `<div data-type="panel-*">` for a
callout, `<details>` for an expand, `<pre><code>` for source. Storage-format
markup (`<ac:…>`, `<ri:…>`) is NOT part of it and does not fail loudly — it
renders as raw text in the middle of the page. A test guards against it
because nothing else will.

Media ids only exist after a file is uploaded, and a file can only be uploaded
to a page that already exists. So pictures are written as placeholders here
and substituted by `finalize.py` once the uploads have happened.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

from skills.annotate.confluence.constants import media_token
from skills.annotate.confluence.markdown_html import to_html
from skills.annotate.diagrams.sequence import _numbered
from skills.annotate.diagrams.views import ALL_VIEW

# The kinds that publish a picture. `prepare` lists the PNGs to render from
# this and `render_block` emits the figures from it, because the two used to
# disagree -- prepare went by `svg`, body by `kind` -- and a block they
# disagreed about produced a placeholder no upload would ever fill. That
# failure surfaced in `finalize`, AFTER the page and its attachments existed,
# which is the worst moment available.
DIAGRAM_KINDS = ("sequence", "flowchart")


_SVG_W = re.compile(r'<svg[^>]*\bwidth="([\d.]+)"')
_SVG_H = re.compile(r'<svg[^>]*\bheight="([\d.]+)"')


def svg_size(svg: str):
    """The stored SVG's own pixel size, or None if it does not declare one.

    Taken from the SVG rather than the rendered PNG so the body is identical
    whether or not images were rendered this run — the manifest round-trip
    depends on that.
    """
    w, h = _SVG_W.search(svg or ""), _SVG_H.search(svg or "")
    if not (w and h):
        return None
    return (int(float(w.group(1))), int(float(h.group(1))))



def has_picture(blk: dict[str, Any]) -> bool:
    """Whether this block publishes a picture."""
    return (blk.get("kind") or "markdown") in DIAGRAM_KINDS


def extra_views(blk: dict[str, Any]) -> list[str]:
    """The views this block declares beyond the union drawing.

    A flowchart can carry a drawing per view. This module publishes only the
    union, so a block with extra views must REFUSE the publish rather than
    drop them: views-as-expands needs a PNG per view plumbed through prepare
    and images, no current document uses them, and dropping them silently is
    exactly the failure this path exists to prevent.
    """
    return [v for v in (blk.get("views") or []) if v != ALL_VIEW]


def figure(block_id: str, alt: str, caption: str = "",
           size: tuple[int, int] | None = None) -> str:
    """A picture, as a media node pointing at an attachment not yet uploaded.

    Two sizing facts, both learned by publishing rather than from the guide.

    The UNIT has to be stated: a bare `data-width="80"` is stored as
    `data-width-type="pixel"`, rendering a 2292px diagram 80px across.

    And the container matters more than the percentage: centred at 80% gave
    ~544px, and `wide` at 100% resolved to 680px — no wider than ordinary
    prose, for a 2292px sequence grid.

    So the layout follows the picture's shape. A landscape diagram takes the
    full page width, because it is the thing the reader came for. A portrait
    one does not: stretched to full width it is upscaled past its own
    resolution, and the reader scrolls through a soft, enormous picture. With
    no dimensions there is no judgement to make, so the safe container wins.
    """
    mid, coll = media_token(block_id)
    cap = "<figcaption>%s</figcaption>" % escape(caption) if caption else ""
    landscape = bool(size) and size[0] > size[1]
    layout = "full-width" if landscape else "wide"
    return ('<figure data-type="media-single" data-layout="%s" '
            'data-width="100" data-width-type="percentage"><div data-type="media" '
            'data-media-type="file" ' % layout +
            'data-id="%s" data-collection="%s" data-alt="%s"></div>%s</figure>'
            % (mid, coll, escape(alt), cap))


def sequence_key_table(spec: dict[str, Any]) -> str:
    """The numbered key as native text.

    `render_key()` already emits HTML rather than SVG because it is the half a
    reader selects text out of. On Confluence that pays off twice: the key
    stays searchable and reflows on a phone, while only the grid is a picture.
    Built from the spec rather than parsed out of that HTML — same source,
    same numbering helper, no HTML round-trip.
    """
    rows = []
    for step, num in _numbered(spec.get("steps") or []):
        if num is None:
            rows.append('<tr><td colspan="3"><p><strong>%s</strong></p>'
                        "</td></tr>" % escape(str(step.get("label", ""))))
            continue
        detail = str(step.get("sub") or "")
        note = str(step.get("note") or "")
        if note:
            detail = ("%s (%s)" % (detail, note)) if detail else note
        rows.append("<tr><td><p>%d</p></td><td><p>%s</p></td>"
                    "<td><p>%s</p></td></tr>"
                    % (num, escape(str(step.get("label", ""))), escape(detail)))
    if not rows:
        return ""
    return ("<table><thead><tr><th><p>#</p></th><th><p>Step</p></th>"
            "<th><p>Detail</p></th></tr></thead><tbody>%s</tbody></table>"
            % "".join(rows))


# Confluence highlights a code block from `class="language-*"`. Without one
# the block is undifferentiated grey text — which is how the first published
# page rendered every excerpt.
_LANGUAGES = {
    "java": "java", "kt": "kotlin", "py": "python", "js": "javascript",
    "ts": "typescript", "tsx": "typescript", "jsx": "javascript",
    "xml": "xml", "html": "html", "css": "css", "scss": "scss",
    "sql": "sql", "sh": "bash", "bash": "bash", "zsh": "bash",
    "yaml": "yaml", "yml": "yaml", "json": "json", "toml": "toml",
    "go": "go", "rs": "rust", "rb": "ruby", "php": "php", "cs": "csharp",
    "c": "c", "h": "c", "cpp": "cpp", "hpp": "cpp", "swift": "swift",
    "md": "markdown", "properties": "properties", "gradle": "groovy",
}


def _language_of(path: str) -> str:
    """The highlighter's name for this file's type, or "" if we don't know.

    Guessing wrong is worse than not guessing: a mislabelled block is
    highlighted as the wrong grammar, which reads as corrupted code.
    """
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _LANGUAGES.get(ext, "")


def _excerpt(row: dict[str, Any]) -> str:
    """One anchor: the cited source, then a link pinned to the commit.

    The source is emitted verbatim, with no gutter of our own. An earlier cut
    numbered every line and barred the cited window, which on the annotate
    page is right — but Confluence numbers a code block itself, from 1, so
    every line arrived carrying two different numbers side by side (`9  27 |`)
    and the gutter text defeated the syntax highlighter, since it is not
    source.

    So: Confluence's numbering is switched off, because a window over lines
    20-23 numbered 1-4 invites the reader to think the file starts there, and
    the caption carries the truth instead — which lines are cited, and which
    wider span is on screen.
    """
    rows = row.get("lines") or []
    text = "\n".join(l["text"] for l in rows)

    start = row.get("actual_line", row.get("line"))
    label = "%s:%s" % (row.get("file"), start)
    if row.get("end_line") and row["end_line"] != row.get("line"):
        label += "-%s" % (start + row["end_line"] - row["line"])

    shown = ""
    if rows:
        first, last = rows[0].get("n"), rows[-1].get("n")
        if (first, last) != (start, start) and str(first) not in label.rsplit(":", 1)[-1]:
            shown = " (lines %s-%s shown)" % (first, last)

    caption = escape(label) + escape(shown)
    link = ('<p><a href="%s">%s</a></p>' % (escape(row["url"]), caption)
            if row.get("url") else "<p>%s</p>" % caption)

    lang = _language_of(str(row.get("file", "")))
    open_tag = '<code class="language-%s">' % lang if lang else "<code>"
    return ('<pre data-hide-line-numbers="true">%s%s</code></pre>%s'
            % (open_tag, escape(text), link))


def _title_of(blk: dict[str, Any]) -> str:
    """The card's name, by the same priority the page uses (block-title.js):
    an authored title first, then the spec's own."""
    if blk.get("title"):
        return str(blk["title"])
    spec = blk.get("spec") or {}
    for key in ("title", "question"):
        if spec.get(key):
            return str(spec[key])
    return "Section"


def render_block(blk: dict[str, Any],
                 anchors_for_block: list[dict[str, Any]],
                 size: tuple[int, int] | None = None) -> str:
    kind = blk.get("kind") or "markdown"
    if size is None:
        size = svg_size(blk.get("svg") or "")
    out = ["<h2>%s</h2>" % escape(_title_of(blk))]

    if kind == "markdown":
        out.append(to_html(blk.get("markdown", "")))
    elif kind == "sequence":
        out.append(figure(blk["id"], _title_of(blk), size=size))
        out.append(sequence_key_table(blk.get("spec") or {}))
    elif kind == "flowchart":
        out.append(figure(blk["id"], _title_of(blk), size=size))
    elif kind == "choice":
        spec = blk.get("spec") or {}
        options = "".join("<li><p>%s</p></li>"
                          % escape(str(o.get("label", "")))
                          for o in (spec.get("options") or []))
        out.append('<div data-type="panel-warning"><p>This question was open '
                   "when the page was published: <strong>%s</strong></p>"
                   "<ul>%s</ul></div>"
                   % (escape(str(spec.get("question", ""))), options))
    elif kind == "mockup":
        out.append('<div data-type="panel-note"><p>This section is an '
                   "interactive mockup, which has no Confluence equivalent. "
                   "It is readable on the annotate page.</p></div>")

    for row in anchors_for_block:
        out.append(_excerpt(row))
    return "".join(out)


def _glossary(glossary: list[dict[str, Any]]) -> str:
    if not glossary:
        return ""
    rows = "".join("<tr><td><p><code>%s</code></p></td><td><p>%s</p></td></tr>"
                   % (escape(str(g.get("term", ""))),
                      escape(str(g.get("definition", ""))))
                   for g in glossary)
    return ("<table><thead><tr><th><p>Term</p></th>"
            "<th><p>Meaning</p></th></tr></thead><tbody>%s</tbody></table>"
            % rows)


def _provenance(repo: dict[str, Any], slug: str) -> str:
    """What the page is, and how old. A reader who does not know a page was
    generated cannot judge whether to trust its line numbers."""
    return ('<div data-type="panel-info"><p>Generated from the annotate '
            "session <code>%s</code>, resolved against <code>%s</code> at "
            "commit <a href=\"%s/commit/%s\">%s</a> on %s. Re-running the "
            "publish updates this page in place.</p></div>"
            % (escape(slug), escape(str(repo.get("ref", ""))),
               escape(str(repo.get("web", ""))),
               escape(str(repo.get("commit", ""))),
               escape(str(repo.get("commit", ""))[:7]),
               escape(str(repo.get("resolved_at", "")))))


def render_page(*, glossary: list[dict[str, Any]],
                blocks: list[dict[str, Any]], anchor_rows: list[dict[str, Any]],
                repo: dict[str, Any], slug: str,
                sizes: dict[str, tuple[int, int]] | None = None) -> str:
    """The whole page. The document's title is NOT rendered into the body —
    Confluence carries it as the page's own title, and a second copy at the
    top of the content reads as a duplicate heading."""
    by_block: dict[str, list[dict[str, Any]]] = {}
    for row in anchor_rows:
        by_block.setdefault(row["block_id"], []).append(row)
    parts = [_glossary(glossary)]
    for blk in blocks:
        parts.append(render_block(blk, by_block.get(blk["id"], []),
                                  size=(sizes or {}).get(blk["id"])))
    parts.append(_provenance(repo, slug))
    return "".join(p for p in parts if p)
