"""The Sessions tab's page code and its fixture: the row contract it is written against, and the rules it keeps."""
import json
import os
import re

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
ROW_KEYS = {"key", "id", "machine", "name", "named", "folder", "about", "kind", "where", "tmux", "state", "pid", "member",
            "held", "unanswered", "free", "started", "last_seen", "ended", "end_reason", "live_on", "copies", "stale", "as_of", "masked", "registry"}


def read(name):
    with open(os.path.join(UI, name)) as f:
        return f.read()


def test_the_fixture_rows_carry_the_whole_row_contract():
    doc = json.loads(read("fixtures/sessions.json"))
    assert doc["hub"] == "server" and set(doc["machines"]) == {"server", "laptop", "spare"}
    for row in doc["rows"]:
        assert ROW_KEYS <= set(row), sorted(ROW_KEYS - set(row))
        assert re.match(r"^[a-z0-9-]+:[0-9a-f-]{8,36}$", row["key"])


def test_sessions_is_the_first_tab_and_has_its_view():
    js = read("app.js")
    assert re.search(r"const VIEWS = \[\{ id: \"sessions\", label: \"Sessions\" \}, \{ id: \"fleet\"", js)
    assert 'id="view-sessions" data-view="sessions">' in read("index.html")


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
