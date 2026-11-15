"""The block kinds are declared once, in static/block-kinds.json.

Python reads it through kinds.py and the page through static/kinds.js. Before
the registry, a kind was listed by hand in about eight files, and adding one
meant finding every list. These tests keep it to one.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from skills.annotate import blocks, kinds, render

ANNOTATE = Path(__file__).resolve().parents[1]
STATIC = ANNOTATE / "static"
QUOTED = re.compile(r"""["']([a-z]+)["']""")

TRAITS = {"renderer", "server_drawn", "framed", "whole_only", "not_text",
          "maximizable", "fit_to_width", "picture", "rebuild", "code"}


def _own_sources():
    """Python and page code of the annotate skill that is written by hand."""
    for p in sorted(ANNOTATE.rglob("*")):
        rel = p.relative_to(ANNOTATE).parts
        if p.suffix not in (".py", ".js") or p.name.endswith(".min.js"):
            continue
        if rel[0] in ("tests", "docs", "rich", "editor") or "vendor" in rel or "shiki-langs" in rel:
            continue
        if p.name == "kinds.py":
            continue
        yield p


def hand_lists(text: str, names: set[str]) -> list[int]:
    """Line numbers where three or more different kind names are quoted one
    after another, separated only by commas, space and comments: a list of
    kinds written out by hand. A chain of `kind === "x"` branches is a
    dispatch, not a list, and a dictionary has values between its keys."""
    code = re.sub(r"(?m)(#|//).*$", "", text)
    hits = []
    for m in re.finditer(r"""(?:["'][a-z]+["']\s*,\s*){2,}["'][a-z]+["']""", code):
        words = set(QUOTED.findall(m.group(0)))
        if len(words & names) >= 3:
            hits.append(code.count("\n", 0, m.start()) + 1)
    return hits


def test_no_file_lists_the_kinds_by_hand():
    names = set(kinds.KINDS) | set(kinds.RETIRED)
    found = {}
    for p in _own_sources():
        hits = hand_lists(p.read_text(encoding="utf-8"), names)
        if hits:
            found[str(p.relative_to(ANNOTATE))] = hits[:3]
    assert not found, (
        "a kind list written out by hand; read it from the registry "
        "(static/block-kinds.json) instead: %s" % found)


def test_the_guard_sees_a_hand_list():
    names = set(kinds.KINDS)
    assert hand_lists('const A = ["choice", "sequence",\n  "map"];', names)
    assert hand_lists('KINDS = {"choice", "sequence", "map"}', names)
    assert not hand_lists('if (k === "map" || k === "choice") {}', names)
    assert not hand_lists('a = "sequence"\nb = "map"\nc = "choice"', names)


def test_every_kind_has_exactly_the_known_traits():
    for name, t in kinds.KINDS.items():
        assert set(t) - {"code_message"} == TRAITS, name
        assert t["code"] in ("pane", "dropped", "refused"), name
        assert (t["code"] == "refused") == ("code_message" in t), name


def test_python_and_the_page_read_the_same_file():
    on_disk = json.loads((STATIC / "block-kinds.json").read_text(encoding="utf-8"))
    assert kinds.KINDS == on_disk["kinds"]
    assert kinds.RETIRED == on_disk["retired"]
    entry = (STATIC / "entry.js").read_text()
    assert 'asset("block-kinds.json")' in entry
    assert entry.index('"kinds.js"') < entry.index('"script.js"')


def test_block_kinds_validation_agrees_with_the_registry():
    assert blocks.BLOCK_KINDS == frozenset(kinds.KINDS)
    assert not set(blocks.RETIRED_KINDS) & set(blocks.BLOCK_KINDS)
    assert set(blocks.RETIRED_KINDS) == set(kinds.RETIRED)


def test_every_kind_has_a_renderer_and_nothing_else_is_rendered():
    assert set(render._RENDERERS) == set(kinds.KINDS)
    for name, t in kinds.KINDS.items():
        assert t["renderer"] in render._RENDERER_FUNCS, name
    assert set(render._RENDERER_FUNCS) == {t["renderer"] for t in kinds.KINDS.values()}


def test_the_traits_keep_each_kinds_behaviour():
    """The values the hand lists held before the registry."""
    assert set(kinds.with_trait("framed")) == {
        "sequence", "map", "flowchart", "mockup", "choice", "explain", "compare"}
    assert set(kinds.with_trait("whole_only")) == {"choice", "sequence", "map", "flowchart"}
    assert set(kinds.with_trait("not_text")) == {
        "choice", "sequence", "map", "flowchart", "mockup", "compare"}
    assert set(kinds.with_trait("maximizable")) == {
        "sequence", "map", "flowchart", "mockup", "compare"}
    assert set(kinds.with_trait("picture")) == {"sequence", "map", "flowchart"}
    assert set(kinds.with_trait("rebuild")) == {"choice", "mockup", "explain", "compare"}
    assert {k for k, t in kinds.KINDS.items() if t["code"] != "pane"} == {
        "mockup", "explain", "compare"}
    # `diagram` is retired but old pages still carry it.
    assert kinds.RETIRED["diagram"]["whole_only"] and kinds.RETIRED["diagram"]["not_text"]
