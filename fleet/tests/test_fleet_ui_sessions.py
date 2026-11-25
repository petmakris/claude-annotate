"""The Sessions tab's page code and its fixtures: the replies it is written against, and the rules it keeps."""
import json
import os
import re

import schema_check
from fleet_testkit import fleet

FLEET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(FLEET, "ui")


def read(name):
    with open(os.path.join(UI, name)) as f:
        return f.read()


def test_the_page_fixture_is_a_sessions_reply_of_the_contract():
    with open(os.path.join(FLEET, "docs", "session-index.schema.json")) as f:
        schema = json.load(f)
    assert schema_check.errors(schema, json.loads(read("fixtures/sessions.json")), "sessions_reply") == []


def test_the_plan_fixtures_hold_every_kind_with_head_and_take():
    plans = json.loads(read("fixtures/open-plans.json"))
    assert {p["kind"] for p in plans} == set(fleet.fs.PLAN_KINDS)
    for p in plans:
        assert set(p) == {"kind", "key", "id", "machine", "name", "tmux", "folder", "pid", "state", "member", "message",
                          "force", "run_on_owner", "head", "take"}
        assert (p["take"] is None) == (p["kind"] != "take-then-resume")


def test_sessions_is_the_first_tab_and_history_is_part_of_it():
    js, html = read("app.js"), read("index.html")
    assert re.search(r"const VIEWS = \[\{ id: \"sessions\", label: \"Sessions\" \}, \{ id: \"fleet\"", js)
    assert 'id="view-sessions" data-view="sessions">' in html
    assert "view-history" not in html and "/api/history" not in js
    for write in ("rename", "delete", "ask", "describe", "search", "open", "stop"):
        assert '"/api/sessions/%s"' % write in js, write


def test_profiles_is_named_as_one_machines():
    assert '"Profiles on " + d.self' in read("app.js")


def test_sessions_adds_no_timer():
    # The page already polls the members once; the Sessions list refreshes on focus and after an action only.
    js = read("app.js")
    assert js.count("setInterval(") == 1
    block = js[js.index("// ---- Sessions"):js.index("function renderNotices")]
    assert "setInterval(" not in block


def test_an_unreachable_machine_is_never_a_remembered_or_guessed_open_target():
    js = read("app.js")
    assert "t.id === saved && t.ok" in js and "t.id === g[0] && t.ok" in js


def test_open_sends_only_a_key_and_a_target():
    js = read("app.js")
    assert '"/api/sessions/open", { key: r.key, target: t }' in js


def test_a_link_off_the_page_opens_in_a_new_tab():
    js = read("app.js")
    assert 'href: t.ref, target: "_blank", rel: "noopener noreferrer"' in js


def test_the_page_never_reads_the_hubs_token():
    js = read("app.js")
    assert "/api/session/" not in js and "Authorization" not in js
