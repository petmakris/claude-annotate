"""push.py and blocks.py, run without a daemon: bad input is refused before
anything talks to the daemon, and the hold and anchor rules are pure functions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills._shared import webcompanion_client as wc
from skills.annotate import blocks as blocks_model
from skills.annotate import push as push_mod


def _write(path: Path, blocks, title="push behaviour", glossary=None) -> Path:
    doc = {"response_id": "resp-push-behaviour", "title": title, "blocks": blocks}
    if glossary:
        doc["glossary"] = glossary
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture(autouse=True)
def _marker_home(tmp_path, monkeypatch):
    """Every test gets its own marker directory and conversation id, so a run
    never writes into the real ~/.claude/annotate of the session running it."""
    monkeypatch.setenv("CLAUDE_ANNOTATE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-conversation")


# ── Hermetic: refused before the daemon is touched ──────────────────────────


@pytest.fixture
def no_daemon(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the push talked to the daemon before validating its input")
    monkeypatch.setattr(wc, "request", boom)
    monkeypatch.setattr(wc, "load_config", lambda: {"port": 1, "token": "t"})


def test_a_missing_blocks_file_is_an_error_not_an_empty_page(tmp_path, no_daemon, capsys):
    rc = push_mod.main(["--blocks", str(tmp_path / "nope.json"), "--cwd", str(tmp_path),
                        "--slug", "some-page"])
    assert rc != 0
    assert "nope.json" in capsys.readouterr().err


def test_invalid_json_is_an_error_not_an_empty_page(tmp_path, no_daemon, capsys):
    bad = tmp_path / "blocks.json"
    bad.write_text('{"blocks": [ {"id": "section-1", "markdown": "x"}, ]}')
    rc = push_mod.main(["--blocks", str(bad), "--cwd", str(tmp_path), "--slug", "some-page"])
    assert rc != 0
    assert "blocks.json" in capsys.readouterr().err


def test_a_document_with_no_blocks_is_refused(tmp_path, no_daemon, capsys):
    empty = _write(tmp_path / "blocks.json", [])
    rc = push_mod.main(["--blocks", str(empty), "--cwd", str(tmp_path), "--slug", "some-page"])
    assert rc != 0
    assert "no blocks" in capsys.readouterr().err


def test_an_empty_slug_is_refused_rather_than_read_as_create(tmp_path, no_daemon, capsys):
    ok = _write(tmp_path / "blocks.json", [{"id": "section-1", "markdown": "hello"}])
    rc = push_mod.main(["--blocks", str(ok), "--cwd", str(tmp_path), "--slug", ""])
    assert rc != 0
    assert "--slug" in capsys.readouterr().err


def test_load_raises_on_a_missing_file(tmp_path):
    with pytest.raises(blocks_model.BlocksFileError):
        blocks_model.load(tmp_path / "blocks.json")


def test_load_raises_on_invalid_json(tmp_path):
    p = tmp_path / "blocks.json"
    p.write_text("{not json")
    with pytest.raises(blocks_model.BlocksFileError):
        blocks_model.load(p)


# ── Holds: a section the reader has open is theirs until they close it ──────

def test_held_blocks_reads_only_fresh_well_formed_holds():
    now = 10_000
    prev = {"__holds__": {"a": {"heartbeat_at": now - 10}, "b": {"heartbeat_at": now - 1801},
                          "c": {"heartbeat_at": "junk"}, "d": "junk", "e": {}}}
    assert push_mod.held_blocks(prev, now) == {"a"}
    assert push_mod.held_blocks({"__holds__": ["a"]}, now) == set()
    assert push_mod.held_blocks({}, now) == set()


# ── `mine` rides a push Claude's working file knows nothing about ───────────

def test_rendered_plain_text_reads_as_the_page_does():
    text = push_mod.rendered_text(
        "# Title\n\nSome **bold** and `code` and [a link](http://x) a\\*b &amp; c\n\n"
        "| h1 | h2 |\n|---|---|\n| c1 | c2 |\n\n> quoted\n\n```\nfenced\n```\n<b>raw</b> html")
    squashed = "".join(text.split())
    for want in ("Title", "Someboldandcodeandalinka*b&c", "h1h2c1c2", "quoted", "fenced", "rawhtml"):
        assert want in squashed, (want, text)


def test_held_blocks_ignores_reserved_anchors():
    now = 10_000
    assert push_mod.held_blocks({"__holds__": {"__doc__": {"heartbeat_at": now},
                                               "section-1": {"heartbeat_at": now}}}, now) == {"section-1"}


@pytest.mark.parametrize("name,mine,new", [
    ("a whole-block anchor inside Claude's new sentence",
     {"selected_text": "Use Postgres.", "prefix": "", "suffix": ""},
     "We weighed it and decided: do not Use Postgres. Use MySQL."),
    ("an anchor at the start, after a sentence Claude prepended",
     {"selected_text": "Yes.", "prefix": "", "suffix": " The rest of the section is Clau"},
     "Claude asked: Yes. The rest of the section is Claude text here."),
    ("words joined by squashing whitespace",
     {"selected_text": "the rapist", "prefix": "", "suffix": ""},
     "Ask the therapist."),
    ("words joined by squashing whitespace, with full context",
     {"selected_text": "the rapist", "prefix": "a long enough lead-in, then ask ",
      "suffix": " about it, and a long enough end"},
     "Words first: a long enough lead-in, then ask therapist about it, and a long enough end of it."),
    ("an anchor at the end, before a sentence Claude appended",
     {"selected_text": "my end.", "prefix": "Claude's long opening sentence, ", "suffix": ""},
     "Claude's long opening sentence, my end. And Claude adds more."),
])
def test_context_cut_short_by_the_block_edge_pins_the_anchor_to_it(name, mine, new):
    assert push_mod._surviving([mine], new) == [], name


@pytest.mark.parametrize("mine,new", [
    ({"selected_text": "Use Postgres.", "prefix": "", "suffix": ""}, "Use Postgres."),
    ({"selected_text": "Yes.", "prefix": "", "suffix": " The rest of the section is Clau"},
     "Yes. The rest of the section is Claude text, rewritten."),
    ({"selected_text": "my end.", "prefix": "Claude's long opening sentence, ", "suffix": ""},
     "Claude's new start. Claude's long opening sentence, my end.\n"),
    ({"selected_text": "your words", "prefix": "Keep ", "suffix": " here."}, "Keep **your words** here."),
])
def test_an_anchor_at_the_block_edge_is_kept_where_it_still_is(mine, new):
    assert push_mod._surviving([mine], new) == [mine]
