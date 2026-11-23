"""The transcript format is Claude Code's and undocumented. `fixtures/transcript_structure.jsonl` is the record
structure of a real transcript with every value replaced by a placeholder; when an update changes the format,
the parser must say so instead of quietly finding nothing."""
import io
import json
import os
import re

import pytest

from fleet_testkit import ROOT, fleet, world  # noqa: F401
import fleet_history as hist

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "transcript_structure.jsonl")
SAFE = [re.compile(p) for p in (
    r"^placeholder( prompt| reply| text)?$", r"^00000000-0000-4000-8000-\d{12}$", r"^2026-01-01T00:00:00\.000Z$",
    r"^[A-Za-z][A-Za-z0-9_-]{0,40}$")]


def records():
    return [json.loads(x) for x in open(FIXTURE)]


def strings(v):
    if isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)
    elif isinstance(v, str):
        yield v


def write(world, recs, name="t.jsonl"):
    path = os.path.join(world.base, name)
    with open(path, "w") as f:
        f.write("".join(json.dumps(r) + "\n" for r in recs))
    return path


def test_the_fixture_holds_structure_only_no_real_text():
    recs = records()
    assert len(recs) > 20 and {"user", "assistant", "system", "attachment"} <= {r["type"] for r in recs}
    for s in strings(recs):
        assert any(p.match(s) for p in SAFE), "not a placeholder: %r" % s[:40]
    raw = open(FIXTURE).read()
    assert "/Users" not in raw and "@" not in raw


def test_the_parser_reads_the_fixture():
    c = hist.conversation(FIXTURE)
    assert c["prompts"] == ["placeholder prompt"] and c["replies"] == ["placeholder reply"]
    assert hist.unreadable_reason(FIXTURE) is None
    assert hist.newest_names(records() + [{"type": "ai-title", "aiTitle": "A name"}]) == {"name_ai": "A name"}


def rename_key(recs, old, new):
    return [{(new if k == old else k): v for k, v in r.items()} for r in recs]


def test_a_renamed_type_key_is_reported(world):
    path = write(world, rename_key(records(), "type", "kind"))
    why = hist.unreadable_reason(path)
    assert why and "no line is a JSON record with a type" in why and "Has the transcript format changed?" in why


def test_a_renamed_message_key_is_reported(world):
    path = write(world, rename_key(records(), "message", "msg"))
    assert "2 user/assistant records but no prompt, reply or name" in hist.unreadable_reason(path)


def test_a_file_that_is_not_json_lines_is_reported_and_an_empty_or_tiny_one_is_not(world):
    path = os.path.join(world.base, "t.jsonl")
    open(path, "w").write("<html>" + "x" * 200 + "</html>\n")
    assert "no line is a JSON record" in hist.unreadable_reason(path)
    open(path, "w").write("")
    assert hist.unreadable_reason(path) is None
    open(path, "w").write(json.dumps({"type": "queue-operation", "operation": "enqueue"}) + "\n")
    assert hist.unreadable_reason(path) is None  # a session that has only just started
    assert hist.unreadable_reason(os.path.join(world.base, "gone.jsonl")) is None


def hook(world, monkeypatch, event, sid, path):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"hook_event_name": event, "session_id": sid, "cwd": "/work/x", "transcript_path": path})))
    world.capsys.readouterr()
    return fleet.main(["hook-record"])


def test_an_unreadable_transcript_is_logged_to_hooks_log_and_warned_about_in_history_ls(world, monkeypatch):
    path = write(world, rename_key(records(), "type", "kind"))
    assert hook(world, monkeypatch, "Stop", "sid-bad", path) == 0  # the hook never fails a session
    log = open(os.path.join(world.here.home, "hooks.log")).read()
    assert "hook-record: HistoryError: cannot read %s" % path in log and "Has the transcript format changed?" in log
    good = write(world, records(), "good.jsonl")
    assert hook(world, monkeypatch, "Stop", "sid-good", good) == 0
    world.capsys.readouterr()
    assert fleet.main(["history", "ls", "--json"]) == 0
    out = world.capsys.readouterr()
    assert len(json.loads(out.out)) == 2  # stdout stays clean JSON
    assert "warning: 1 transcript could not be read: has the transcript format changed?" in out.err
    assert fleet.db().execute("SELECT unreadable FROM conversations WHERE session_id='sid-bad'").fetchone()[0] == 1
    assert hist.unreadable_count(fleet.db()) == 1
    assert fleet.ui_history()["counts"]["unreadable"] == 1


def test_a_readable_transcript_raises_no_warning_and_a_later_good_read_clears_it(world, monkeypatch):
    path = write(world, records())
    assert hook(world, monkeypatch, "Stop", "sid-ok", path) == 0
    assert not os.path.exists(os.path.join(world.here.home, "hooks.log"))
    fleet.main(["history", "ls"])
    assert "could not be read" not in world.capsys.readouterr().err
    write(world, rename_key(records(), "type", "kind"))
    hook(world, monkeypatch, "Stop", "sid-ok", path)
    assert hist.unreadable_count(fleet.db()) == 1
    write(world, records())
    hook(world, monkeypatch, "Stop", "sid-ok", path)
    assert hist.unreadable_count(fleet.db()) == 0
