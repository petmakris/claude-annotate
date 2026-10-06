"""push.py, pull.py and the conversation marker, run for real.

Everything else about the push was guarded by grepping push.py's source, and
four realistic breakages survived that: a re-push that never found its session,
a lost `__prev__`, a `__prev__` that nested itself on every push, and a sorted
block order. These run the code instead.

The first group is hermetic: bad input must be refused before anything talks
to the daemon. The second runs against a real webcompanion daemon — the xdist
worker's private one (skills/conftest.py), never the one on this machine —
creates its sessions under a throwaway cwd, and deletes every one of them
afterwards. Its own reads and writes go over plain HTTP, not through push.py's
client, so they check what the daemon stored rather than what push.py thinks.
"""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from skills._shared import webcompanion_client as wc
from skills.annotate import blocks as blocks_model
from skills.annotate import pull as pull_mod
from skills.annotate import push as push_mod
from skills.annotate import session as session_mod


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


# ── Live daemon ──────────────────────────────────────────────────────────────


def _call(cfg, method, path, body=None):
    return cfg["_daemon"].call(method, path, body)


def _items(cfg, sid):
    return _call(cfg, "GET", "/s/%s/items?kind=annotate" % sid)


@pytest.fixture
def daemon(tmp_path, wc_config):
    cfg = dict(wc_config.cfg, _daemon=wc_config)
    yield cfg
    # Delete every session any test created under this throwaway cwd — both
    # cwds a test may push from live under tmp_path.
    rows = _call(cfg, "GET", "/api/sessions?scope=all")
    for row in rows:
        if row.get("cwd", "").startswith(str(tmp_path)):
            try:
                _call(cfg, "DELETE", "/s/%s/?force=1" % row["sid"])
            except urllib.error.URLError as e:         # noqa: PERF203
                import warnings
                warnings.warn("push behaviour suite leaked session %s: %s" % (row["sid"], e))


def _push(tmp_path, blocks, *extra, cwd=None, capsys=None, glossary=None):
    path = _write(tmp_path / "blocks.json", blocks, glossary=glossary)
    rc = push_mod.main(["--blocks", str(path), "--cwd", str(cwd or tmp_path / "repo"),
                        *extra, "--json"])
    assert rc == 0, capsys.readouterr().err if capsys else rc
    return json.loads(capsys.readouterr().out)


FIRST = [{"id": "section-3", "title": "Third", "markdown": "three"},
         {"id": "section-1", "title": "First", "markdown": "one"},
         {"id": "section-2", "kind": "choice",
          "spec": {"question": "Which?", "options": [{"id": "o1", "label": "A"},
                                                     {"id": "o2", "label": "B"}]}}]
SECOND = [{"id": "section-1", "title": "First", "markdown": "one, revised"},
          {"id": "section-4", "markdown": "four"}]


def test_a_second_push_by_slug_lands_on_the_same_session(tmp_path, daemon, capsys):
    first = _push(tmp_path, FIRST, capsys=capsys)
    # From a different directory on purpose: resolving the slug must not
    # depend on the cwd the session was created from.
    second = _push(tmp_path, SECOND, "--slug", first["slug"],
                   cwd=tmp_path / "elsewhere", capsys=capsys)
    assert second["sid"] == first["sid"]
    assert second["created"] is False


def test_the_authored_order_is_kept(tmp_path, daemon, capsys):
    first = _push(tmp_path, FIRST, capsys=capsys)
    doc = _items(daemon, first["sid"])["__doc__"]["body"]
    assert doc["order"] == ["section-3", "section-1", "section-2"]


def test_prev_is_the_first_push_and_never_nests(tmp_path, daemon, capsys):
    first = _push(tmp_path, FIRST, capsys=capsys)
    stored_first = {a: v["body"] for a, v in _items(daemon, first["sid"]).items()
                    if not a.startswith("__")}
    _push(tmp_path, SECOND, "--slug", first["slug"], capsys=capsys)
    _push(tmp_path, SECOND, "--slug", first["slug"], capsys=capsys)
    prev = _items(daemon, first["sid"])["__prev__"]["body"]
    assert "__prev__" not in prev, "each push nested the previous __prev__ inside itself"
    second_blocks = {a: v for a, v in prev.items() if not a.startswith("__")}
    assert set(second_blocks) == {"section-1", "section-4"}
    # And after exactly one re-push, __prev__ is what the first push stored.
    fresh = _push(tmp_path, FIRST, capsys=capsys)
    _push(tmp_path, SECOND, "--slug", fresh["slug"], capsys=capsys)
    prev = _items(daemon, fresh["sid"])["__prev__"]["body"]
    assert {a: v for a, v in prev.items() if not a.startswith("__")} == stored_first


def test_an_unknown_slug_is_an_error_and_creates_nothing(tmp_path, daemon, capsys):
    path = _write(tmp_path / "blocks.json", SECOND)
    rc = push_mod.main(["--blocks", str(path), "--cwd", str(tmp_path / "repo"),
                        "--slug", "no-such-page-for-push-behaviour"])
    assert rc != 0
    assert "no-such-page-for-push-behaviour" in capsys.readouterr().err
    rows = _call(daemon, "GET", "/api/sessions?scope=all")
    assert not [r for r in rows if r.get("cwd", "").startswith(str(tmp_path))]


def test_a_push_by_slug_to_a_finished_session_is_refused(tmp_path, daemon, capsys):
    """A push used to land on a page the reader had clicked Done on. The page
    changed, and the watcher armed after it reported FINISHED at once."""
    first = _push(tmp_path, FIRST, capsys=capsys)
    _call(daemon, "POST", "/s/%s/api/finish" % first["sid"])
    before = _items(daemon, first["sid"])
    path = _write(tmp_path / "blocks.json", SECOND)
    rc = push_mod.main(["--blocks", str(path), "--cwd", str(tmp_path / "repo"),
                        "--slug", first["slug"]])
    assert rc != 0
    err = capsys.readouterr().err
    assert "finished" in err
    assert "webcompanion unfinish --sid %s" % first["sid"] in err
    assert _items(daemon, first["sid"]) == before


def test_a_push_records_the_session_in_the_conversation_marker(tmp_path, daemon, capsys):
    first = _push(tmp_path, FIRST, capsys=capsys)
    entries = session_mod.entries()
    assert [e["sid"] for e in entries] == [first["sid"]]
    e = entries[0]
    assert e["slug"] == first["slug"]
    assert e["cwd"] == str(tmp_path / "repo")
    assert e["blocks"] == str(tmp_path / "blocks.json")
    # A second push updates the one entry rather than adding another.
    _push(tmp_path, SECOND, "--slug", first["slug"], capsys=capsys)
    assert len(session_mod.entries()) == 1


def test_lookup_finds_a_session_by_slug_or_by_exact_cwd(tmp_path, daemon, capsys):
    """/annotate resume used to set $SERVER_URL in one Bash call and read it in
    the next, where it was empty. The lookup is a command now."""
    first = _push(tmp_path, FIRST, capsys=capsys)
    assert session_mod.main(["lookup", "--slug", first["slug"]]) == 0
    got = json.loads(capsys.readouterr().out)
    assert [r["sid"] for r in got["sessions"]] == [first["sid"]]
    assert got["sessions"][0]["state"] == "live"
    assert got["index"].startswith("http://localhost:")
    assert session_mod.main(["lookup", "--cwd", str(tmp_path / "repo")]) == 0
    assert [r["sid"] for r in json.loads(capsys.readouterr().out)["sessions"]] \
        == [first["sid"]]
    assert session_mod.main(["lookup", "--slug", "no-such-slug-anywhere"]) == 0
    assert json.loads(capsys.readouterr().out)["sessions"] == []


def test_pull_rebuilds_blocks_json_from_the_stored_page(tmp_path, daemon, capsys):
    glossary = [{"term": "Koumbaras", "definition": "a thing", "role": "the thing"}]
    first = _push(tmp_path, FIRST, capsys=capsys, glossary=glossary)
    out = tmp_path / "pulled.json"
    assert pull_mod.main(["--sid", first["slug"], "--out", str(out)]) == 0
    doc = blocks_model.load(out)
    assert [b["id"] for b in doc.blocks] == ["section-3", "section-1", "section-2"]
    assert doc.title == "push behaviour"
    assert doc.response_id == "resp-push-behaviour"
    assert doc.glossary == glossary
    by_id = {b["id"]: b for b in doc.blocks}
    assert by_id["section-1"]["markdown"] == "one"
    assert by_id["section-1"]["title"] == "First"
    assert by_id["section-2"]["kind"] == "choice"
    assert by_id["section-2"]["spec"]["options"][1]["id"] == "o2"
    # What pull wrote pushes back to the same page unchanged.
    rc = push_mod.main(["--blocks", str(out), "--cwd", str(tmp_path / "repo"),
                        "--slug", first["slug"]])
    assert rc == 0


def test_eval_prints_a_share_url_only_when_the_daemon_is_reachable_off_box(
        tmp_path, daemon, capsys):
    path = _write(tmp_path / "blocks.json", FIRST)
    assert push_mod.main(["--blocks", str(path), "--cwd", str(tmp_path / "repo"),
                          "--eval"]) == 0
    lines = dict(l.split("=", 1) for l in capsys.readouterr().out.strip().splitlines())
    assert lines["WC_URL"].startswith("http://localhost:")
    if daemon.get("bind", "127.0.0.1") in ("127.0.0.1", "localhost", "::1"):
        assert "WC_SHARE_URL" not in lines
    else:
        assert "WC_SHARE_URL" in lines
        assert "127.0.0.1" not in lines["WC_SHARE_URL"]
        assert "localhost" not in lines["WC_SHARE_URL"]


def test_mine_survives_a_push_and_a_pull(tmp_path, daemon, capsys):
    mine = [{"selected_text": "my words", "prefix": "one, ", "suffix": ""}]
    blocks = [{"id": "section-1", "title": "First", "markdown": "one, my words", "mine": mine}]
    first = _push(tmp_path, blocks, capsys=capsys)
    stored = _items(daemon, first["sid"])["section-1"]["body"]
    assert stored["mine"] == mine
    out = tmp_path / "pulled.json"
    assert pull_mod.main(["--sid", first["slug"], "--out", str(out)]) == 0
    assert blocks_model.load(out).blocks[0]["mine"] == mine


# ── Holds: a section the reader has open is theirs until they close it ──────

import time  # noqa: E402

TWO = [{"id": "section-1", "title": "First", "markdown": "one"},
       {"id": "section-2", "title": "Second", "markdown": "two"}]
TWO_REVISED = [{"id": "section-1", "title": "First", "markdown": "one, revised"},
               {"id": "section-2", "title": "Second", "markdown": "two, revised by Claude"}]


def _hold(daemon, sid, block_id, age_s=0):
    now = int(time.time())
    _call(daemon, "PUT", "/s/%s/items/__holds__" % sid, {
        block_id: {"opened_at": now - age_s, "heartbeat_at": now - age_s, "tab": "tab-x"}})


def _push_rc(tmp_path, blocks, slug, capsys):
    path = _write(tmp_path / "blocks.json", blocks)
    rc = push_mod.main(["--blocks", str(path), "--cwd", str(tmp_path / "repo"),
                        "--slug", slug, "--json"])
    return rc, capsys.readouterr()


def test_a_held_section_keeps_the_readers_version(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    _hold(daemon, first["sid"], "section-2")
    rc, out = _push_rc(tmp_path, TWO_REVISED, first["slug"], capsys)
    assert rc == 0, out.err
    stored = _items(daemon, first["sid"])
    assert stored["section-1"]["body"]["markdown"] == "one, revised"
    assert stored["section-2"]["body"]["markdown"] == "two"
    assert "section-2" in stored["__holds__"]["body"], "the hold did not survive the replace"
    assert ("held by the reader: section-2 — kept their version; "
            "fold your change into the next round") in out.err
    # The hold is not a block of the page Claude pushed over.
    assert "__holds__" not in stored["__prev__"]["body"]


def test_a_stale_hold_is_ignored(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    _hold(daemon, first["sid"], "section-2", age_s=31 * 60)
    rc, out = _push_rc(tmp_path, TWO_REVISED, first["slug"], capsys)
    assert rc == 0, out.err
    stored = _items(daemon, first["sid"])
    assert stored["section-2"]["body"]["markdown"] == "two, revised by Claude"
    assert "held by the reader" not in out.err


def test_held_blocks_reads_only_fresh_well_formed_holds():
    now = 10_000
    prev = {"__holds__": {"a": {"heartbeat_at": now - 10}, "b": {"heartbeat_at": now - 1801},
                          "c": {"heartbeat_at": "junk"}, "d": "junk", "e": {}}}
    assert push_mod.held_blocks(prev, now) == {"a"}
    assert push_mod.held_blocks({"__holds__": ["a"]}, now) == set()
    assert push_mod.held_blocks({}, now) == set()


# ── `mine` rides a push Claude's working file knows nothing about ───────────

def _stored_mine(daemon, sid, anchor="section-1"):
    return _items(daemon, sid)[anchor]["body"].get("mine")


def _seed_mine(daemon, sid, markdown, mine, anchor="section-1"):
    """What edit.js's save leaves in the store."""
    _call(daemon, "PUT", "/s/%s/items/%s" % (sid, anchor),
                      {"id": anchor, "kind": "markdown", "title": "First",
                       "markdown": markdown, "mine": mine})


def test_a_push_without_mine_carries_the_stored_anchors_forward(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    md = "Intro text. Then **your exact words** stay here.\n\n- a list item\n- another item"
    # As the page reads it: markdown-it's newlines between blocks, the
    # suffix cut at 32 characters.
    mine = [{"selected_text": "your exact words", "prefix": "Intro text. Then ",
             "suffix": " stay here.\n\na list item\nanother"}]
    _seed_mine(daemon, first["sid"], md, mine)
    # Claude's working file never had `mine`; it changes only section-2.
    _push(tmp_path, [{"id": "section-1", "title": "First", "markdown": md},
                     {"id": "section-2", "markdown": "two, revised"}],
          "--slug", first["slug"], capsys=capsys)
    assert _stored_mine(daemon, first["sid"]) == mine


def test_an_anchor_whose_context_claude_rewrote_is_dropped(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    mine = [{"selected_text": "your words", "prefix": "Keep ", "suffix": " here."}]
    _seed_mine(daemon, first["sid"], "Keep your words here.", mine)
    # Claude rewrote the sentence around them and wrote its own copy of the
    # same words elsewhere: the anchor must not land on that copy.
    # Built on the reader's stored version (`base`, as pull writes it).
    _push(tmp_path, [{"id": "section-1", "markdown": "Claude says your words there. Keep it.",
                      "base": _items(daemon, first["sid"])["section-1"]["version"]},
                     {"id": "section-2", "markdown": "two"}],
          "--slug", first["slug"], capsys=capsys)
    assert _stored_mine(daemon, first["sid"]) is None


def test_mine_claude_sends_is_filtered_the_same_way(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    good = {"selected_text": "kept", "prefix": "words ", "suffix": " here, and nothing else"}
    gone = {"selected_text": "vanished", "prefix": "and ", "suffix": " too"}
    _push(tmp_path, [{"id": "section-1", "markdown": "words kept here, and nothing else",
                      "mine": [good, gone]},
                     {"id": "section-2", "markdown": "two"}],
          "--slug", first["slug"], capsys=capsys)
    assert _stored_mine(daemon, first["sid"]) == [good]


def test_rendered_plain_text_reads_as_the_page_does():
    text = push_mod.rendered_text(
        "# Title\n\nSome **bold** and `code` and [a link](http://x) a\\*b &amp; c\n\n"
        "| h1 | h2 |\n|---|---|\n| c1 | c2 |\n\n> quoted\n\n```\nfenced\n```\n<b>raw</b> html")
    squashed = "".join(text.split())
    for want in ("Title", "Someboldandcodeandalinka*b&c", "h1h2c1c2", "quoted", "fenced", "rawhtml"):
        assert want in squashed, (want, text)


def test_a_held_section_claude_dropped_stays_where_it_was(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO + [{"id": "section-3", "markdown": "three"}], capsys=capsys)
    _hold(daemon, first["sid"], "section-2")
    rc, out = _push_rc(tmp_path, [{"id": "section-1", "markdown": "one"},
                                  {"id": "section-3", "markdown": "three"}], first["slug"], capsys)
    assert rc == 0, out.err
    stored = _items(daemon, first["sid"])
    assert stored["section-2"]["body"]["markdown"] == "two"
    assert stored["__doc__"]["body"]["order"] == ["section-1", "section-2", "section-3"]
    assert "held by the reader: section-2" in out.err



def test_the_readers_save_and_release_during_a_push_are_not_reverted(tmp_path, daemon, capsys,
                                                                     monkeypatch):
    """The page saves and closes between push's read and its PATCH: the
    PATCH, carrying the copies it read, must not put them back."""
    first = _push(tmp_path, TWO, capsys=capsys)
    sid = first["sid"]
    _hold(daemon, sid, "section-2")
    real = push_mod._existing_items

    def read_then_the_page_writes(cfg, s):
        out = real(cfg, s)
        cur = _items(daemon, sid)["section-2"]
        _call(daemon, "PUT", "/s/%s/items/section-2" % sid,
                          dict(cur["body"], markdown="READER SAVED WORDS"))
        _call(daemon, "PUT", "/s/%s/items/__holds__" % sid, {})   # released
        return out
    monkeypatch.setattr(push_mod, "_existing_items", read_then_the_page_writes)
    rc, out = _push_rc(tmp_path, TWO_REVISED, first["slug"], capsys)
    assert rc == 0, out.err
    stored = _items(daemon, sid)
    assert stored["section-2"]["body"]["markdown"] == "READER SAVED WORDS"
    assert stored["__holds__"]["body"] == {}
    assert stored["section-1"]["body"]["markdown"] == "one, revised"


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


def test_a_hold_taken_during_a_push_is_not_deleted(tmp_path, daemon, capsys, monkeypatch):
    first = _push(tmp_path, TWO, capsys=capsys)
    sid = first["sid"]
    real = push_mod._existing_items

    def read_then_a_tab_opens(cfg, s):
        out = real(cfg, s)
        _hold(daemon, sid, "section-2")
        return out
    monkeypatch.setattr(push_mod, "_existing_items", read_then_a_tab_opens)
    rc, out = _push_rc(tmp_path, TWO_REVISED, first["slug"], capsys)
    assert rc == 0, out.err
    assert "section-2" in _items(daemon, sid)["__holds__"]["body"]


def test_pull_lists_the_held_sections(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    out = tmp_path / "pulled.json"
    assert pull_mod.main(["--sid", first["slug"], "--out", str(out)]) == 0
    assert "held by the reader" not in capsys.readouterr().out
    now = int(time.time())
    _call(daemon, "PUT", "/s/%s/items/__holds__" % first["sid"], {
        "section-2": {"opened_at": now, "heartbeat_at": now, "tab": "t"},
        "section-1": {"opened_at": now - 7200, "heartbeat_at": now - 7200,
                      "tab": "t"}})                      # stale: not held
    assert pull_mod.main(["--sid", first["slug"], "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "held by the reader: section-2\n" in printed
    assert "section-1" not in printed.split("held by the reader:")[1]


# ── A saved edit no round has carried yet: Claude's stale copy must not revert it ──

import hashlib  # noqa: E402

EDITED = "Claude wrote this sentence about my own careful words."
EDITED_MINE = [{"selected_text": "my own careful words",
                "prefix": "Claude wrote this sentence about ", "suffix": "."}]
STALE = [{"id": "section-1", "title": "First", "markdown": "one, tightened"},
         {"id": "section-2", "title": "Second",
          "markdown": "Claude wrote this sentence about retries."}]
GUARD_MSG = ("edited by the reader since your last push: section-2 — kept their version; "
             "pull first, then fold your change in")


def _sha(md):
    return hashlib.sha256(md.encode("utf-8")).hexdigest()


def _reader_saves(daemon, sid, markdown=EDITED, mine=EDITED_MINE, anchor="section-2"):
    """edit.js's save after the hold was released: no hold left behind."""
    cur = _items(daemon, sid)[anchor]["body"]
    _call(daemon, "PUT", "/s/%s/items/%s" % (sid, anchor),
                      dict(cur, markdown=markdown, mine=mine))


def test_a_saved_edit_is_not_reverted_by_claudes_stale_push(tmp_path, daemon, capsys):
    first = _push(tmp_path, [STALE[0] | {"markdown": "one"}, STALE[1]], capsys=capsys)
    _reader_saves(daemon, first["sid"])
    rc, out = _push_rc(tmp_path, STALE, first["slug"], capsys)
    assert rc == 0, out.err
    stored = _items(daemon, first["sid"])
    assert stored["section-2"]["body"]["markdown"] == EDITED
    assert stored["section-2"]["body"]["mine"] == EDITED_MINE
    assert stored["section-1"]["body"]["markdown"] == "one, tightened"
    assert GUARD_MSG in out.err
    # A second stale push is refused the same way: keeping their version
    # is not Claude writing it.
    rc, out = _push_rc(tmp_path, STALE, first["slug"], capsys)
    assert _items(daemon, first["sid"])["section-2"]["body"]["markdown"] == EDITED
    assert GUARD_MSG in out.err


def test_the_push_records_the_hash_of_what_it_wrote(tmp_path, daemon, capsys):
    first = _push(tmp_path, STALE, capsys=capsys)
    doc = _items(daemon, first["sid"])["__doc__"]["body"]
    assert doc["pushed"] == {"section-1": _sha("one, tightened"),
                             "section-2": _sha(STALE[1]["markdown"])}


def test_a_push_built_on_the_pulled_version_lands(tmp_path, daemon, capsys):
    first = _push(tmp_path, [STALE[0] | {"markdown": "one"}, STALE[1]], capsys=capsys)
    _reader_saves(daemon, first["sid"])
    out = tmp_path / "pulled.json"
    assert pull_mod.main(["--sid", first["slug"], "--out", str(out)]) == 0
    capsys.readouterr()
    pulled = json.loads(out.read_text())["blocks"]
    by_id = {b["id"]: b for b in pulled}
    assert by_id["section-2"]["base"] == _items(daemon, first["sid"])["section-2"]["version"]
    by_id["section-2"]["markdown"] = "Claude adds a sentence. " + EDITED
    rc, res = _push_rc(tmp_path, pulled, first["slug"], capsys)
    assert rc == 0, res.err
    body = _items(daemon, first["sid"])["section-2"]["body"]
    assert body["markdown"] == "Claude adds a sentence. " + EDITED
    assert "base" not in body, "base reached the store"
    assert body["mine"] == EDITED_MINE
    assert "edited by the reader" not in res.err


def test_claude_sending_the_readers_text_back_is_not_flagged(tmp_path, daemon, capsys):
    first = _push(tmp_path, STALE, capsys=capsys)
    _reader_saves(daemon, first["sid"])
    rc, out = _push_rc(tmp_path, [STALE[0], STALE[1] | {"markdown": EDITED}], first["slug"], capsys)
    assert rc == 0 and "edited by the reader" not in out.err
    assert _items(daemon, first["sid"])["section-2"]["body"]["markdown"] == EDITED


def test_a_block_with_no_recorded_push_is_not_guarded(tmp_path, daemon, capsys):
    """A session pushed before the guard existed has no `pushed` map."""
    first = _push(tmp_path, STALE, capsys=capsys)
    doc = _items(daemon, first["sid"])["__doc__"]["body"]
    doc.pop("pushed")
    _call(daemon, "PUT", "/s/%s/items/__doc__" % first["sid"], doc)
    _reader_saves(daemon, first["sid"])
    rc, out = _push_rc(tmp_path, [STALE[0], STALE[1] | {"markdown": "Claude's newer text."}],
                       first["slug"], capsys)
    assert rc == 0 and "edited by the reader" not in out.err
    assert _items(daemon, first["sid"])["section-2"]["body"]["markdown"] == "Claude's newer text."


def test_a_dropped_anchor_is_named_on_stderr(tmp_path, daemon, capsys):
    first = _push(tmp_path, TWO, capsys=capsys)
    mine = [{"selected_text": "your words", "prefix": "Keep ", "suffix": " here."}]
    _seed_mine(daemon, first["sid"], "Keep your words here.", mine)
    rc, out = _push_rc(tmp_path, [{"id": "section-1", "markdown": "Claude rewrote it all.",
                                   "base": _items(daemon, first["sid"])["section-1"]["version"]},
                                  {"id": "section-2", "markdown": "two"}], first["slug"], capsys)
    assert rc == 0, out.err
    assert 'your change dropped the reader\'s words in section-1: "your words"' in out.err


def test_a_base_is_spent_once_the_reader_saves_again(tmp_path, daemon, capsys):
    """Claude pulls and pushes a rewrite; the reader saves the pulled text
    back; a push from the same working copy must not restore the rewrite.
    The text matches what was pulled, but the save is newer than the pull."""
    first = _push(tmp_path, [STALE[0] | {"markdown": "one"}, STALE[1]], capsys=capsys)
    sid = first["sid"]
    _reader_saves(daemon, sid)
    out = tmp_path / "pulled.json"
    assert pull_mod.main(["--sid", first["slug"], "--out", str(out)]) == 0
    capsys.readouterr()
    pulled = json.loads(out.read_text())["blocks"]
    assert pulled[1]["base"] == _items(daemon, sid)["section-2"]["version"]
    pulled[1]["markdown"] = "Claude's added opening. " + EDITED
    rc, res = _push_rc(tmp_path, pulled, first["slug"], capsys)
    assert rc == 0 and "edited by the reader" not in res.err
    _reader_saves(daemon, sid)                      # back to exactly the pulled text
    pulled[0]["markdown"] = "one, next round"
    rc, res = _push_rc(tmp_path, pulled, first["slug"], capsys)
    assert rc == 0, res.err
    assert _items(daemon, sid)["section-2"]["body"]["markdown"] == EDITED
    assert GUARD_MSG in res.err


def test_a_section_the_reader_edited_is_not_deleted_by_a_push_that_omits_it(tmp_path, daemon, capsys):
    first = _push(tmp_path, [STALE[0] | {"markdown": "one"}, STALE[1],
                             {"id": "section-3", "markdown": "three"}], capsys=capsys)
    sid = first["sid"]
    _reader_saves(daemon, sid)
    rc, out = _push_rc(tmp_path, [STALE[0], {"id": "section-3", "markdown": "three"}],
                       first["slug"], capsys)
    assert rc == 0, out.err
    stored = _items(daemon, sid)
    assert stored["section-2"]["body"]["markdown"] == EDITED
    assert stored["section-2"]["body"]["mine"] == EDITED_MINE
    assert stored["__doc__"]["body"]["order"] == ["section-1", "section-2", "section-3"]
    assert GUARD_MSG in out.err
    # A section the reader did not touch still goes when Claude drops it.
    rc, out = _push_rc(tmp_path, [STALE[0], STALE[1] | {"markdown": EDITED}], first["slug"], capsys)
    assert "section-3" not in _items(daemon, sid)
