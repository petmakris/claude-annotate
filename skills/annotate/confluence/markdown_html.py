"""Markdown → Confluence's HTML format (the ADF-mapped subset).

Written, not imported. The plugin's own error text promises "standard library
only — nothing to pip install", and a publish path is not a good enough reason
to break that for everyone who installs annotate.

The subset is small on purpose. Annotate's markdown is model-authored against
`references/pushing.md`, so what actually appears is headings, paragraphs,
lists, pipe tables, fenced code, blockquotes, and four inline marks. Anything
else RAISES. That is the whole safety argument: a converter that guesses
produces a page subtly unlike the one the author approved, and nobody
re-reads a published page closely enough to catch it.
"""
from __future__ import annotations

import re
from html import escape

# Confluence's HTML format is not HTML — it is a fixed set of nodes that map to
# ADF. Raw HTML from a markdown block cannot be passed through: a <div> is
# dropped, a style attribute is dropped, and the reader sees a differently
# shaped page with no error anywhere.
_HTML_TAG = re.compile(
    r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?\s*/?\s*>")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

_FENCE = re.compile(r"^\s*```(\S*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")

_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


class UnsupportedMarkdown(ValueError):
    """A construct this converter will not guess at."""


def _inline(text: str) -> str:
    """Inline marks, with code spans taken out of the line first.

    Code spans are extracted before anything else and put back last, so
    `**x**` inside backticks stays literal — the one ordering bug that makes a
    converter silently corrupt a code sample.
    """
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(escape(m.group(1)))
        return "\x00%d\x00" % (len(spans) - 1)

    out = _CODE_SPAN.sub(stash, text)
    out = escape(out)
    out = _LINK.sub(
        lambda m: '<a href="%s">%s</a>' % (escape(m.group(2)), m.group(1)), out)
    out = _BOLD.sub(lambda m: "<strong>%s</strong>" % m.group(1), out)
    out = _ITALIC.sub(lambda m: "<em>%s</em>" % m.group(1), out)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: "<code>%s</code>" % spans[int(m.group(1))], out)


def _cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _guard(md: str) -> None:
    fenced = False
    for line in md.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        # Inline code spans are literal text, not markup — `<T>` is a code
        # sample, not raw HTML, so strip spans before scanning for either.
        checked = _CODE_SPAN.sub("", line)
        if _IMAGE.search(checked):
            raise UnsupportedMarkdown(
                "a markdown image cannot be published: pictures on a "
                "Confluence page are attachments — %s" % line.strip())
        if _HTML_TAG.search(checked):
            raise UnsupportedMarkdown(
                "raw HTML in a markdown block has no Confluence equivalent "
                "and would be silently dropped — %s" % line.strip())


def to_html(md: str) -> str:
    """Convert one block's markdown. Raises on anything outside the subset."""
    _guard(md)
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            lang, body, i = fence.group(1), [], i + 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence
            cls = ' class="language-%s"' % escape(lang) if lang else ""
            out.append("<pre><code%s>%s</code></pre>"
                       % (cls, escape("\n".join(body))))
            continue

        if not line.strip():
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append("<h%d>%s</h%d>"
                       % (level, _inline(heading.group(2).strip()), level))
            i += 1
            continue

        if (line.lstrip().startswith("|") and i + 1 < len(lines)
                and _TABLE_DIVIDER.match(lines[i + 1])):
            head = _cells(line)
            i += 2
            body_rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                body_rows.append(_cells(lines[i]))
                i += 1
            thead = "".join("<th><p>%s</p></th>" % _inline(c) for c in head)
            tbody = "".join(
                "<tr>%s</tr>" % "".join("<td><p>%s</p></td>" % _inline(c)
                                        for c in row)
                for row in body_rows)
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody>"
                       "</table>" % (thead, tbody))
            continue

        if _BULLET.match(line):
            items = []
            while i < len(lines) and _BULLET.match(lines[i]):
                items.append(_BULLET.match(lines[i]).group(1))
                i += 1
            out.append("<ul>%s</ul>" % "".join(
                "<li><p>%s</p></li>" % _inline(t) for t in items))
            continue

        if _ORDERED.match(line):
            start = _ORDERED.match(line).group(1)
            items = []
            while i < len(lines) and _ORDERED.match(lines[i]):
                items.append(_ORDERED.match(lines[i]).group(2))
                i += 1
            out.append('<ol start="%s">%s</ol>' % (escape(start), "".join(
                "<li><p>%s</p></li>" % _inline(t) for t in items)))
            continue

        if _QUOTE.match(line):
            quoted = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            out.append("<blockquote><p>%s</p></blockquote>"
                       % _inline(" ".join(quoted).strip()))
            continue

        para = []
        while i < len(lines) and lines[i].strip() and not (
                _FENCE.match(lines[i]) or _HEADING.match(lines[i])
                or _BULLET.match(lines[i]) or _ORDERED.match(lines[i])
                or _QUOTE.match(lines[i])
                or lines[i].lstrip().startswith("|")):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
    return "".join(out)
