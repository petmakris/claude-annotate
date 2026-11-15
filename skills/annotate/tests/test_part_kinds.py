"""The decisions, facts and jobs kinds: their specs are checked at load, and
each survives load, render, pull and save unchanged."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from skills.annotate import blocks, kinds
from skills.annotate.pull import block_from_body
from skills.annotate.render import render_block

ANNOTATE = Path(__file__).resolve().parents[1]
STATIC = ANNOTATE / "static"

DECISIONS = {"decisions": [
    {"id": "D1", "question": "How is the test data stored?",
     "options": [{"id": "a", "label": "One file per person per app", "trade": "Two people never edit the same file."},
                 {"id": "b", "label": "One big file per app", "trade": "One place to read; edits collide."}],
     "recommended": "a", "why": "Nothing else keeps two people apart.", "status": "open"},
    {"id": "D2", "question": "Behind a flag?",
     "options": [{"id": "a", "label": "Yes", "trade": "Off without a deploy."},
                 {"id": "b", "label": "No", "trade": "Less to remove later."},
                 {"id": "c", "label": "Later", "trade": "Decide after the pilot."}],
     "recommended": "a", "why": "Rollback is free.", "status": "answered", "chosen": "a"},
    {"id": "D3", "question": "Who reviews?",
     "options": [{"id": "a", "label": "Anna", "trade": "Knows the code."},
                 {"id": "b", "label": "Ben", "trade": "Fresh eyes."}],
     "recommended": "b", "why": "Fresh eyes.", "status": "answered",
     "answer": "Both, Anna first."}]}
FACTS = {"facts": [{"value": "3 files", "label": "change"},
                   {"value": "2 days", "label": "estimate"},
                   {"value": "low", "label": "risk"}]}
JOBS = {"jobs": [
    {"id": "J1", "title": "Registry", "does": "One list of kinds.", "after": [], "status": "done"},
    {"id": "J2", "title": "Tables", "does": "Rows comment.", "after": ["J1"], "status": "running"},
    {"id": "J3", "title": "Docs", "does": "Update rules.", "after": ["J1", "J2"], "status": "blocked"}]}
GOOD = {"decisions": DECISIONS, "facts": FACTS, "jobs": JOBS}


def _block(kind, spec):
    return {"id": "section-1", "kind": kind, "title": "T", "spec": spec}


def _load(tmp_path, blks):
    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"response_id": "r", "title": "t", "blocks": blks}))
    return blocks.load(p)


@pytest.mark.parametrize("kind", sorted(GOOD))
def test_the_kind_survives_load_render_pull_and_save(tmp_path, kind):
    blk = _block(kind, copy.deepcopy(GOOD[kind]))
    doc = _load(tmp_path, [blk])
    assert doc.blocks == [blk]
    stored = render_block(doc.blocks[0])
    assert stored["kind"] == kind and stored["spec"] == GOOD[kind]
    assert block_from_body(stored, 3) == blk
    out = tmp_path / "out" / "blocks.json"
    blocks.save_atomic(out, blocks.BlocksDoc(response_id="r", title="t", blocks=[block_from_body(stored, 3)]))
    assert blocks.load(out).blocks == [blk]


def test_re_pushing_a_pulled_copy_changes_nothing(tmp_path):
    blk = _block("jobs", copy.deepcopy(JOBS))
    first = render_block(_load(tmp_path, [blk]).blocks[0])
    again = render_block(_load(tmp_path, [block_from_body(first, 1)]).blocks[0])
    assert again == first


def _with(kind, mutate):
    spec = copy.deepcopy(GOOD[kind])
    mutate(spec)
    return _block(kind, spec)


BAD = [
    ("decisions", lambda s: s["decisions"][0].update(id="X1"), "D1, D2"),
    ("decisions", lambda s: s["decisions"][1].update(id="D1"), "used twice"),
    ("decisions", lambda s: s["decisions"][0].update(status="maybe"), "`status` must be one of open, answered"),
    ("decisions", lambda s: s["decisions"][1].pop("chosen"), "needs the reader's `chosen` option or their `answer`"),
    ("decisions", lambda s: s["decisions"][0].update(chosen="a"), "silence is not a yes"),
    ("decisions", lambda s: s["decisions"][0].update(answer="yes"), "silence is not a yes"),
    ("decisions", lambda s: s["decisions"][1].update(chosen="d"), "`chosen` must name one of the option ids"),
    ("decisions", lambda s: s["decisions"][0].update(why="a\nb"), "`why` must be a non-blank string on one line"),
    ("decisions", lambda s: s["decisions"][0].update(recommended="c"), "`recommended` must name one of the option ids"),
    ("decisions", lambda s: s["decisions"][0].pop("recommended"), "`recommended` must name one of the option ids"),
    ("decisions", lambda s: s["decisions"][0].update(recommendation="Drop it."), "`recommendation` is now `recommended`"),
    ("decisions", lambda s: s["decisions"][0].update(options=s["decisions"][0]["options"][:1]), "`options` must be a list of 2 to 4"),
    ("decisions", lambda s: s["decisions"][0]["options"].extend(
        [{"id": "c", "label": "x", "trade": "y"}, {"id": "d", "label": "x", "trade": "y"},
         {"id": "a", "label": "x", "trade": "y"}]), "`options` must be a list of 2 to 4"),
    ("decisions", lambda s: s["decisions"][0]["options"][1].update(id="a"), "option id 'a' is used twice"),
    ("decisions", lambda s: s["decisions"][0]["options"][1].update(id="e"), "must be one of a, b, c, d"),
    ("decisions", lambda s: s["decisions"][0]["options"][0].update(label="x\ny"), "`label` must be a non-blank one-line string"),
    ("decisions", lambda s: s["decisions"][0]["options"][0].pop("trade"), "`trade` must be a non-blank one-line string"),
    ("decisions", lambda s: s.update(decisions=[]), "non-empty list"),
    ("facts", lambda s: s.update(facts=s["facts"][:1]), "2 to 6 facts (found 1)"),
    ("facts", lambda s: s["facts"].extend([{"value": str(i), "label": "x"} for i in range(4)]), "(found 7)"),
    ("facts", lambda s: s["facts"][0].update(value="x" * 21), "over the 20 limit"),
    ("facts", lambda s: s["facts"][0].update(label=""), "`label` must be a non-blank"),
    ("jobs", lambda s: s["jobs"][1].update(after=["J9"]), "'J9', which is not a job here"),
    ("jobs", lambda s: s["jobs"][1].update(after=["J2"]), "waits on itself"),
    ("jobs", lambda s: s["jobs"][0].update(after=["J3"]), "in a circle"),
    ("jobs", lambda s: s["jobs"][0].update(status="paused"), "todo, running, done, blocked"),
    ("jobs", lambda s: s["jobs"][0].update(after="J1"), "`after` must be a list"),
]


@pytest.mark.parametrize("kind,mutate,message", BAD)
def test_a_bad_spec_is_refused_with_the_reason(tmp_path, kind, mutate, message):
    with pytest.raises(blocks.PartSpecError) as e:
        _load(tmp_path, [_with(kind, mutate)])
    assert message in str(e.value)


def test_a_spec_that_is_not_an_object_is_refused(tmp_path):
    with pytest.raises(blocks.PartSpecError, match="`spec` must be an object"):
        _load(tmp_path, [{"id": "section-1", "kind": "facts", "spec": []}])


def test_code_anchors_are_refused_on_these_kinds():
    from skills.annotate.anchors import block_problems
    for kind in GOOD:
        blk = {**_block(kind, GOOD[kind]), "code": [{"file": "a.py", "line": 1}]}
        assert any("takes no anchors" in p for p in block_problems(blk)), kind
        assert "code" not in render_block(blk)


def test_each_kind_has_a_reference_and_a_menu_line_and_a_painter():
    skill = (ANNOTATE / "SKILL.md").read_text(encoding="utf-8")
    spec_parts = (STATIC / "spec-parts.js").read_text(encoding="utf-8")
    for kind in GOOD:
        assert (ANNOTATE / "references" / "block-kinds" / f"{kind}.md").is_file()
        assert f"| `{kind}` |" in skill and f"references/block-kinds/{kind}.md" in skill
        assert kinds.trait(kind, "painter") == kind
        assert re.search(r"const painters = \{[^}]*\b%s\b" % kind, spec_parts)


def test_the_rules_say_silence_is_never_a_yes():
    ref = (ANNOTATE / "references" / "block-kinds" / "decisions.md").read_text(encoding="utf-8")
    assert "**Silence is never a yes.**" in ref
    assert "only from the reader's own words" in ref
    assert "**A comment on a decision rewrites that decision only.**" in ref
    assert "**A `Choose x: …` comment on a decision** sets `status: \"answered\"` and\n  `chosen: \"x\"`." in ref
    assert "A free comment that settles it" in ref
    events = (ANNOTATE / "references" / "handling-events.md").read_text(encoding="utf-8")
    assert "A comment whose text is `Choose x: <label>` is a pick" in events
    assert "Silence never answers" in events


def test_the_first_table_column_stays_in_view_when_the_table_scrolls():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    rule = css[css.index("main.prose tbody td:first-child, main.prose thead th:first-child {"):]
    rule = rule[:rule.index("}")]
    assert "position: sticky; left: 0" in rule
    assert "background-color: var(--surface)" in rule


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_parts_page_suite_passes():
    suite = Path(__file__).with_name("parts_page.test.mjs")
    proc = subprocess.run(["node", str(suite)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) == 6, proc.stdout


def test_confluence_lists_the_options_and_marks_recommended_and_chosen():
    from skills.annotate.confluence.body import render_block as confluence
    html = confluence(_block("decisions", DECISIONS), [])
    assert "<strong>a. One file per person per app</strong> (recommended): Two people never edit the same file." in html
    assert "<strong>b. One big file per app</strong>: One place to read; edits collide." in html
    assert "<strong>a. Yes</strong> (recommended, your choice): Off without a deploy." in html
    assert "Answered: Both, Anna first." in html
    assert "Open. Recommended a: Nothing else keeps two people apart." in html
