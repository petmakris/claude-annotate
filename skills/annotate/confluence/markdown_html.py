"""Markdown → Confluence's HTML format (the ADF-mapped subset).

Written, not imported. The plugin's own error text promises "standard library
only — nothing to pip install", and a publish path is not a good enough reason
to break that for everyone who installs annotate.

The subset is small on purpose. Annotate's markdown is model-authored against
`references/pushing.md`, so what actually appears is headings, paragraphs,
lists (nested, and with lazy continuation lines), pipe tables, fenced code,
blockquotes, thematic breaks, and four inline marks. Anything else RAISES.
That is the whole safety argument: a converter that guesses produces a page
subtly unlike the one the author approved, and nobody re-reads a published
page closely enough to catch it.

"Raises" has to mean raises. Flattening a nested list, or splitting one list
in two around a continuation line, is not a smaller failure than refusing —
it is the same failure with nothing to notice it by, because the page still
looks plausible. So every construct the live page (markdown-it) renders is
either converted here or refused by name.
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
# The indent is captured because it is what decides nesting depth.
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_RULE = re.compile(r"^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
# A line of nothing but `=` or `-` under a paragraph is a setext heading. It
# is refused rather than converted: `---` is also a thematic break, and a
# converter that picks one reading silently is the thing this module is not.
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)\s*$")

_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


class UnsupportedMarkdown(ValueError):
    """A construct this converter will not guess at."""


def _inline(text: str) -> str:
    """Inline marks, with code spans and link targets taken out of the line.

    Both are stashed BEFORE `escape()` and put back after. Code spans, so
    `**x**` inside backticks stays literal — the one ordering bug that makes a
    converter silently corrupt a code sample. Link targets, because escaping
    an already-escaped href turns `?b=1&c=2` into `?b=1&amp;amp;c=2` and
    breaks every link that carries a query string.
    """
    spans: list[str] = []
    links: list[tuple[str, str]] = []

    def stash_code(m: "re.Match") -> str:
        spans.append(escape(m.group(1)))
        return "\x00%d\x00" % (len(spans) - 1)

    def stash_link(m: "re.Match") -> str:
        links.append((m.group(1), m.group(2)))
        return "\x01%d\x01" % (len(links) - 1)

    def marks(s: str) -> str:
        s = _BOLD.sub(lambda m: "<strong>%s</strong>" % m.group(1), s)
        return _ITALIC.sub(lambda m: "<em>%s</em>" % m.group(1), s)

    out = _CODE_SPAN.sub(stash_code, text)
    out = _LINK.sub(stash_link, out)
    out = marks(escape(out))

    def put_link(m: "re.Match") -> str:
        label, url = links[int(m.group(1))]
        return '<a href="%s">%s</a>' % (escape(url), marks(escape(label)))

    out = re.sub(r"\x01(\d+)\x01", put_link, out)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: "<code>%s</code>" % spans[int(m.group(1))], out)


def _split_row(body: str) -> list[str]:
    """Split a table row on its cell separators only.

    A `|` inside a code span is data, not a separator — `` `a|b` `` in a cell
    silently became two cells and shifted every column after it. A backslashed
    pipe is likewise a literal, and is unescaped here so the cell reads as the
    author wrote it.
    """
    out: list[str] = []
    buf: list[str] = []
    ticks = 0
    i = 0
    while i < len(body):
        ch = body[i]
        if not ticks and ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "`":
            run = 0
            while i + run < len(body) and body[i + run] == "`":
                run += 1
            if ticks == 0:
                ticks = run
            elif ticks == run:
                ticks = 0
            buf.append("`" * run)
            i += run
            continue
        if ch == "|" and not ticks:
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def _cells(row: str) -> list[str]:
    body = row.strip()
    parts = _split_row(body)
    if body.startswith("|") and parts and not parts[0].strip():
        parts = parts[1:]
    if body.endswith("|") and parts and not parts[-1].strip():
        parts = parts[:-1]
    return [c.strip() for c in parts]


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


def _starts_block(line: str) -> bool:
    """True when this line begins something other than paragraph text.

    Used in two places that must agree: where a paragraph stops, and where a
    list item's lazy continuation stops.
    """
    return bool(_FENCE.match(line) or _HEADING.match(line)
                or _BULLET.match(line) or _ORDERED.match(line)
                or _QUOTE.match(line) or _RULE.match(line)
                or _SETEXT.match(line) or line.lstrip().startswith("|"))


def _list_at(lines: list[str], i: int, indent: int) -> tuple[str, int]:
    """One list starting at `lines[i]`, nested lists included.

    `indent` is the column this list's own markers sit at; a marker further
    right opens a sub-list hanging off the item above it, and one further left
    belongs to an enclosing list and ends this one. ADF allows a `<ul>`/`<ol>`
    inside an `<li>`, so the nesting survives the publish rather than being
    flattened into one level.
    """
    ordered = _ORDERED.match(lines[i]) is not None
    start = _ORDERED.match(lines[i]).group(2) if ordered else ""
    items: list[dict] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            # A blank line inside a list is a loose list, not two lists — so
            # long as what follows is still an item of this list or deeper.
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            nxt = (_BULLET.match(lines[j]) or _ORDERED.match(lines[j])
                   if j < len(lines) else None)
            if nxt and len(nxt.group(1)) >= indent:
                i = j
                continue
            break
        bullet, order = _BULLET.match(line), _ORDERED.match(line)
        if bullet or order:
            at = len((bullet or order).group(1))
            if at > indent and items:
                sub, i = _list_at(lines, i, at)
                items[-1]["kids"].append(sub)
                continue
            if at < indent or (order is not None) != ordered:
                break
            items.append({"text": [bullet.group(2) if bullet
                                   else order.group(3)], "kids": []})
            i += 1
            continue
        if items and not _starts_block(line):
            # A lazy continuation: prose belonging to the item above it.
            items[-1]["text"].append(line.strip())
            i += 1
            continue
        break
    body = "".join("<li><p>%s</p>%s</li>"
                   % (_inline(" ".join(it["text"])), "".join(it["kids"]))
                   for it in items)
    if ordered:
        return '<ol start="%s">%s</ol>' % (escape(start), body), i
    return "<ul>%s</ul>" % body, i


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

        if _RULE.match(line):
            out.append("<hr />")
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

        marker = _BULLET.match(line) or _ORDERED.match(line)
        if marker:
            html, i = _list_at(lines, i, len(marker.group(1)))
            out.append(html)
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
        while (i < len(lines) and lines[i].strip()
               and not _starts_block(lines[i])):
            para.append(lines[i].strip())
            i += 1
        if para:
            if i < len(lines) and _SETEXT.match(lines[i]):
                raise UnsupportedMarkdown(
                    "a setext heading (a line of %s under %r) is ambiguous "
                    "against a horizontal rule, so it is refused rather than "
                    "guessed at — write it as '# %s' instead"
                    % (lines[i].strip()[0], para[-1], para[-1]))
            out.append("<p>%s</p>" % _inline(" ".join(para)))
        else:
            # No branch claimed this line and it is not paragraph text
            # either — a `|` row with no divider under it, say. Emit it as
            # prose and move on; spinning here would hang the publish.
            out.append("<p>%s</p>" % _inline(line.strip()))
            i += 1
    return "".join(out)
