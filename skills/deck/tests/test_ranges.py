"""No line range may reach past the element it addresses.

Claude is handed a line range and replaces text inside it. A range one line
too long deletes whatever starts on that line — a sibling element, or a
closing tag. This is the one class of defect in this skill that destroys
content rather than merely misdirecting an edit, so it gets its own sweep over
randomly malformed documents rather than a handful of hand-written cases.

Every text run is a unique token, so "is this element's text inside its own
range" is an exact question with no chance of a repeated word answering it.
"""
from __future__ import annotations

import html as htmlmod
import itertools
import random
import re

from skills.deck import model

TAGS = ['<p>', '<p class="pro">', '<li>', '<div class="k">', '<span>',
        '<b></b>', '<em>e</em>', '<ul class="bul">', '</ul>', '</p>', '</div>',
        '</li>', '<div class="pro">', '<span></span>', '<br>', '<br/>',
        '<table class="t">', '<tr>', '<td>', '</table>',
        '<svg class="d"><line x1="0"></svg>']

TAG_RE = re.compile(r"<[^>]*>")
WORD_RE = re.compile(r"w\d+")


def _words(text: str) -> set[str]:
    return set(WORD_RE.findall(htmlmod.unescape(TAG_RE.sub(" ", text))))


def _document(rng: random.Random, counter) -> str:
    lines = ['<div class="deck">', '<section class="slide">']
    for _ in range(rng.randint(3, 14)):
        parts = []
        for _ in range(rng.randint(1, 3)):
            parts.append(rng.choice(TAGS))
            if rng.random() < 0.6:
                parts.append("w%d" % next(counter))
        lines.append("".join(parts))
    lines += ["</section>", "</div>"]
    return "\n".join(lines)


def test_no_range_reaches_past_its_element_across_malformed_documents():
    rng = random.Random(20260824)
    counter = itertools.count()
    checked = 0
    for _ in range(400):
        doc = _document(rng, counter)
        src = doc.splitlines()
        for slide in model.parse_deck(doc)["slides"]:
            for e in slide["elements"]:
                checked += 1
                a, b = e["line_start"], e["line_end"]
                assert a <= b <= len(src), (e, doc)
                mine = _words(e["text"])
                if not mine:
                    continue
                # every word of the element is inside its own range
                assert mine <= _words(" ".join(src[a - 1:b])), (e, doc)
                # and the last line earns its place: it carries either some of
                # that text or the element's closing tag
                if b > a and mine <= _words(" ".join(src[a - 1:b - 1])):
                    assert "</" in src[b - 1], (e, doc)
    assert checked > 200, f"the generator produced almost nothing ({checked})"
