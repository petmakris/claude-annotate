"""Handler-level tests. No socket is opened; handlers are called directly."""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from skills.deck import server as deck_server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini-deck.html"


class FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler."""
    def __init__(self):
        self.status = None
        self.headers_sent = {}
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass

    def body(self):
        return self.wfile.getvalue().decode("utf-8")


@pytest.fixture
def dirs(tmp_path):
    state = tmp_path / "state"
    (state / "events").mkdir(parents=True)
    (state / "consumed").mkdir(parents=True)
    response = tmp_path / "response"
    response.mkdir()
    deck = tmp_path / "mini-deck.html"
    shutil.copy(FIXTURE, deck)
    d = {"state_dir": str(state), "response_dir": str(response)}
    deck_server.Handlers().create_session_extra({"deck": str(deck)}, d)
    return d


def test_create_session_requires_a_deck_path(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    with pytest.raises(ValueError, match="deck"):
        deck_server.Handlers().create_session_extra({}, {"state_dir": str(state)})


def test_create_session_rejects_a_missing_file(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    with pytest.raises(ValueError):
        deck_server.Handlers().create_session_extra(
            {"deck": str(tmp_path / "nope.html")}, {"state_dir": str(state)})


def test_create_session_records_the_deck_in_meta(dirs):
    meta = json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())
    assert meta["deck"].endswith("mini-deck.html")
    assert meta["title"] == "mini-deck"


def test_serve_deck_returns_the_file_byte_for_byte(dirs):
    h = FakeHandler()
    deck_server.Handlers().serve_data(h, dirs, "deck")
    assert h.status == 200
    assert h.body() == FIXTURE.read_text(encoding="utf-8")
    # the entity trap: the served bytes still carry the raw entity
    assert "&mdash;" in h.body()


def test_serve_model_returns_slides_and_elements(dirs):
    h = FakeHandler()
    deck_server.Handlers().serve_data(h, dirs, "model")
    payload = json.loads(h.body())
    assert [s["index"] for s in payload["slides"]] == [1, 2, 3]
    assert payload["deck"].endswith("mini-deck.html")


def test_submit_writes_one_event_and_returns_202(dirs):
    h = FakeHandler()
    deck_server.Handlers().handle_submit(h, dirs, {
        "slide": 3, "path": ".pro > p:nth-of-type(1)", "component": "pro",
        "line_start": 20, "line_end": 20, "text": "Every proposal…",
        "comment": "Open on the constraint.",
    })
    assert h.status == 202
    events = list((Path(dirs["state_dir"]) / "events").glob("*.json"))
    assert len(events) == 1
    body = json.loads(events[0].read_text())
    assert body["comment"] == "Open on the constraint."
    assert body["path"] == ".pro > p:nth-of-type(1)"
    assert body["slide"] == 3


def test_submit_rejects_an_empty_comment(dirs):
    h = FakeHandler()
    deck_server.Handlers().handle_submit(h, dirs, {
        "slide": 3, "path": ".kick", "comment": "   "})
    assert h.status == 400
    assert not list((Path(dirs["state_dir"]) / "events").glob("*.json"))


def test_submit_rejects_an_unknown_path(dirs):
    h = FakeHandler()
    deck_server.Handlers().handle_submit(h, dirs, {
        "slide": 3, "path": ".nonexistent", "comment": "hello"})
    assert h.status == 400


def test_poll_reports_busy_until_the_event_is_acked(dirs):
    handlers = deck_server.Handlers()
    sub = FakeHandler()
    handlers.handle_submit(sub, dirs, {
        "slide": 3, "path": ".kick", "comment": "shorter"})
    event_id = json.loads(sub.body())["event_id"]

    h = FakeHandler()
    handlers.serve_poll(h, dirs)
    assert json.loads(h.body())["busy"] is True

    (Path(dirs["state_dir"]) / "consumed" / f"{event_id}.ack").touch()
    h2 = FakeHandler()
    handlers.serve_poll(h2, dirs)
    poll = json.loads(h2.body())
    assert poll["busy"] is False
    assert event_id in poll["consumed_events"]


def test_poll_uses_the_blocks_key_core_js_expects(dirs):
    # core.js:110 reads data.blocks / data.threads and nothing else.
    h = FakeHandler()
    deck_server.Handlers().serve_poll(h, dirs)
    assert "blocks" in json.loads(h.body())


def test_poll_version_changes_when_the_deck_file_changes(dirs):
    handlers = deck_server.Handlers()
    h = FakeHandler()
    handlers.serve_poll(h, dirs)
    before = json.loads(h.body())["blocks"]

    deck = Path(json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())["deck"])
    deck.write_text(deck.read_text(encoding="utf-8").replace(
        "Mandatory documents", "Mandatory papers"), encoding="utf-8")

    h2 = FakeHandler()
    handlers.serve_poll(h2, dirs)
    assert json.loads(h2.body())["blocks"] != before


def test_comment_count_counts_events(dirs):
    handlers = deck_server.Handlers()
    assert handlers.comment_count(dirs) == 0
    handlers.handle_submit(FakeHandler(), dirs, {
        "slide": 3, "path": ".kick", "comment": "one"})
    assert handlers.comment_count(dirs) == 1


def test_model_reports_a_missing_deck_instead_of_raising(dirs):
    deck = Path(json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())["deck"])
    deck.unlink()
    h = FakeHandler()
    deck_server.Handlers().serve_data(h, dirs, "model")
    assert h.status == 404
    assert "unreadable" in h.body()


def test_submit_reports_a_missing_deck_instead_of_raising(dirs):
    deck = Path(json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())["deck"])
    deck.unlink()
    h = FakeHandler()
    deck_server.Handlers().handle_submit(h, dirs, {
        "slide": 3, "path": ".kick", "comment": "hello"})
    assert h.status == 404
    assert not list((Path(dirs["state_dir"]) / "events").glob("*.json"))


def test_a_file_with_no_slides_is_served_as_an_empty_model(tmp_path):
    state = tmp_path / "state"
    (state / "events").mkdir(parents=True)
    (state / "consumed").mkdir(parents=True)
    page = tmp_path / "panel.html"
    page.write_text("<html><body><div id='app'>not a deck</div></body></html>",
                    encoding="utf-8")
    d = {"state_dir": str(state)}
    deck_server.Handlers().create_session_extra({"deck": str(page)}, d)
    h = FakeHandler()
    deck_server.Handlers().serve_data(h, d, "model")
    assert h.status == 200
    assert json.loads(h.body())["slides"] == []
