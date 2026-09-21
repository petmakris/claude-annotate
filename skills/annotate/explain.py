"""Compile an `explain` block's spec into the view its renderer paints.

The point of this kind is that the explanation rides ON the code instead of
sitting in a prose column beside it, so the whole problem is tying a label to
an exact run of characters and keeping that tie true.

Two decisions are made here rather than by the author, and both exist because
the alternative was something an author gets silently wrong:

  1. **A span is quoted, not measured.** The spec says
     `{"line": 2, "span": "priceInReferenceCurrency"}` and this module finds
     the column. Asking for `{"col": 27, "len": 24}` was the obvious shape and
     is the wrong one: nothing at authoring time checks a column, so an
     off-by-three paints a confident underline under the wrong tokens and the
     page looks fine. A quote that does not occur is refused at push.

  2. **The presentation follows from the count.** One or two marks on a line
     get an underline and a label hanging under it; three or more get numbered
     badges and a list, because a ladder of three stems threaded past each
     other is unreadable. The author never picks, so a line that grows a third
     annotation re-lays itself out instead of degrading.

Columns are in characters, and the renderer turns them into `ch` units, which
is exact in a monospace pane. Tabs would break that — one tab is one character
but not one `ch` — so they are expanded here, once, before anything is
measured.
"""
from __future__ import annotations

import re
from typing import Any

TAB_WIDTH = 4

# Above this many marks on one line, the ladder stops being readable and the
# line switches to numbered badges. Two stems already cross; three is a knot.
LADDER_MAX = 2


class ExplainError(ValueError):
    """An `explain` spec names something that is not in its own code."""


# Inline markdown for labels, and deliberately only this much: bold for the
# lead-in, italic for emphasis mid-sentence, code for an identifier. A label is
# one or two sentences pinned to a line of code — it is not a place for
# headings, lists or links, and allowing them here would mean sanitizing model
# HTML on a path where escaping everything else is both safer and sufficient.
# Italic was not in the first cut and had to be added after a real push
# rendered `*several*` with its asterisks showing: prose being relocated onto
# a label is ordinary prose, and ordinary prose emphasises mid-sentence.
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
# `[^*]+` rather than a lazy `.+?`: bold has already been consumed by the time
# this runs, so any asterisk still standing is an italic delimiter — and
# refusing to cross one stops `**a** and *b*` being read as one italic run
# spanning the bold.
_ITAL = re.compile(r"\*([^*]+)\*")
_CODE = re.compile(r"`([^`]+)`")


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def label_html(text: str) -> str:
    """Render a label's restricted inline markdown, escaping everything else."""
    out = _escape(str(text or ""))
    out = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    # Bold BEFORE italic, always: `**x**` read by the italic rule first would
    # come out as `<em></em>x<em></em>`.
    out = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", out)
    out = _ITAL.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def _expand(line: str) -> str:
    return line.expandtabs(TAB_WIDTH)


# The bold lead-in the authoring guide already asks every label to open with.
# It is lifted here rather than authored a second time: a `lead` field would be
# one more thing to keep in sync with the sentence beside it, and a step
# counter that disagrees with the label under it is worse than no counter.
_LEAD = re.compile(r"^\s*\*\*(.+?)\*\*", re.S)


def lead_of(label: str) -> str:
    """The step's short name — the label's bold opening, or nothing."""
    m = _LEAD.match(str(label or ""))
    if not m:
        return ""
    return m.group(1).strip().rstrip(".:;,").strip()


def _resolve_span(rows: list[str], note: dict[str, Any], where: str) -> tuple[int, int]:
    """Find `span` on `line`, returning (col, len) in expanded characters."""
    lineno = note.get("line")
    if not isinstance(lineno, int) or not (1 <= lineno <= len(rows)):
        raise ExplainError(
            f"{where}: line {lineno!r} is outside the snippet, which has "
            f"{len(rows)} line(s).")
    text = rows[lineno - 1]
    span = note.get("span")
    if not isinstance(span, str) or not span:
        raise ExplainError(f"{where}: needs a `span` (a quote from line {lineno}).")
    span = _expand(span)

    hits = []
    start = text.find(span)
    while start != -1:
        hits.append(start)
        start = text.find(span, start + 1)
    if not hits:
        raise ExplainError(
            f"{where}: {span!r} does not occur on line {lineno}, which is "
            f"{text.strip()!r}. A span is quoted from the code, not described.")

    nth = note.get("nth", 1)
    if not isinstance(nth, int) or nth < 1:
        raise ExplainError(f"{where}: `nth` must be a positive integer, got {nth!r}.")
    if len(hits) > 1 and "nth" not in note:
        raise ExplainError(
            f"{where}: {span!r} occurs {len(hits)} times on line {lineno}. "
            f"Add \"nth\": 1..{len(hits)} to say which one, or quote more of "
            f"the line so the span is unique.")
    if nth > len(hits):
        raise ExplainError(
            f"{where}: asked for occurrence {nth} of {span!r} on line "
            f"{lineno}, which has {len(hits)}.")
    return hits[nth - 1], len(span)


def compile_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Turn an authored spec into the flat view the renderer walks.

    Raises ExplainError for anything the author could have got wrong; the
    caller turns that into a visible failure rather than a quietly mispainted
    pane.
    """
    spec = spec or {}
    code = spec.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ExplainError("an `explain` block needs `spec.code` — the snippet itself.")

    rows_text = [_expand(l) for l in code.replace("\r\n", "\n").split("\n")]
    # A trailing newline is an artifact of quoting, not a blank line worth a row.
    while rows_text and not rows_text[-1].strip():
        rows_text.pop()
    if not rows_text:
        raise ExplainError("an `explain` block needs `spec.code` — the snippet itself.")

    notes = spec.get("notes")
    if not isinstance(notes, list) or not notes:
        raise ExplainError(
            "an `explain` block needs at least one note — otherwise it is a "
            "fenced code block, and a markdown block already does that.")

    by_line: dict[int, list[dict[str, Any]]] = {}
    ranges: list[dict[str, Any]] = []
    # One step per note, in the order they were WRITTEN. That order is the
    # argument's, and it is routinely not the file's — an explanation often
    # starts at the second method and works back.
    walk: list[dict[str, Any]] = []

    for i, note in enumerate(notes):
        where = f"note {i + 1}"
        if not isinstance(note, dict):
            raise ExplainError(f"{where}: each note is an object.")
        label = note.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ExplainError(f"{where}: needs a `label`.")
        step = {
            "n": len(walk) + 1,
            "labelHtml": label_html(label),
            "lead": lead_of(label),
        }

        span_of = note.get("lines")
        if span_of is not None:
            if (not isinstance(span_of, list) or len(span_of) != 2
                    or not all(isinstance(n, int) for n in span_of)):
                raise ExplainError(f"{where}: `lines` is [from, to], 1-based.")
            lo, hi = span_of
            if not (1 <= lo <= hi <= len(rows_text)):
                raise ExplainError(
                    f"{where}: lines {lo}–{hi} are outside the snippet, which "
                    f"has {len(rows_text)} line(s).")
            ranges.append({"from": lo, "to": hi, "labelHtml": label_html(label)})
            step.update({"kind": "range", "from": lo, "to": hi, "marks": []})
            walk.append(step)
            continue

        # One note, one claim — but a claim can be true of more than one place.
        # The first mark carries the prose; the rest are ECHOES, underlined and
        # silent, because the same sentence printed under every twin is the
        # same sentence twice in one pane.
        many = note.get("spans")
        if many is not None:
            if "span" in note or "line" in note:
                raise ExplainError(
                    f"{where}: a note quotes either `span` (one place) or "
                    f"`spans` (several), not both.")
            if not isinstance(many, list) or not many:
                raise ExplainError(
                    f"{where}: `spans` is a list of {{line, span}} objects.")
            places = list(many)
        else:
            places = [note]

        marks = []
        for k, place in enumerate(places):
            if not isinstance(place, dict):
                raise ExplainError(f"{where}: each entry in `spans` is an object.")
            col, length = _resolve_span(rows_text, place, where)
            mark = {
                "col": col, "len": length, "echo": k > 0,
                "labelHtml": "" if k else label_html(label),
            }
            by_line.setdefault(place["line"], []).append(mark)
            marks.append({"line": place["line"], "col": col, "len": length})

        step.update({"kind": "span", "marks": marks})
        walk.append(step)

    # A range may not start or end inside another one: the renderer opens a
    # bracket at `from` and closes it at `to`, so overlapping ranges would
    # nest boxes that do not nest in meaning.
    ranges.sort(key=lambda r: (r["from"], r["to"]))
    for a, b in zip(ranges, ranges[1:]):
        if b["from"] <= a["to"]:
            raise ExplainError(
                f"ranges {a['from']}–{a['to']} and {b['from']}–{b['to']} "
                f"overlap; a line belongs to at most one range.")

    groups = []
    for lineno in sorted(by_line):
        marks = sorted(by_line[lineno], key=lambda m: m["col"])
        # Only a mark with a label of its own is one of the stacked labels the
        # ladder limit counts, and only those are numbered: an echo has nothing
        # to say, so a badge on it would point at an entry that is not there.
        spoken = [m for m in marks if not m["echo"]]
        for n, mark in enumerate(spoken, start=1):
            mark["n"] = n
        groups.append({
            "line": lineno,
            # See LADDER_MAX. Chosen here, never by the author.
            "mode": "drop" if len(spoken) <= LADDER_MAX else "badge",
            "marks": marks,
        })

    loc = str(spec.get("file") or "").strip()
    if loc and spec.get("line"):
        loc = f"{loc}:{spec['line']}"

    return {
        "project": str(spec.get("project") or "").strip(),
        "loc": loc,
        "lang": str(spec.get("lang") or "").strip(),
        "rows": [{"text": t, "blank": not t.strip()} for t in rows_text],
        "groups": groups,
        "ranges": ranges,
        "walk": walk,
    }
