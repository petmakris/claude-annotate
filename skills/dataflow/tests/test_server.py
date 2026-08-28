"""Handler behaviour for the dataflow server.

Exercised through the Handlers class directly with a recording stand-in for the
HTTP handler: the routing, gating and threading around these methods is the
shared engine's and is covered by its own suite.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

from skills.dataflow import flow as flow_module
from skills.dataflow import server as srv


class FakeH:
    """Records what a handler sent, standing in for BaseHTTPRequestHandler."""

    def __init__(self):
        self.status = None
        self.headers_sent = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass

    @property
    def body(self) -> str:
        return self.wfile.getvalue().decode()

    def json(self):
        return json.loads(self.body)


@pytest.fixture()
def dirs(tmp_path):
    state = tmp_path / "state"
    events = state / "events"
    (state / "threads").mkdir(parents=True)
    events.mkdir(parents=True)
    return {"state_dir": str(state), "events_dir": str(events), "_cwd": str(tmp_path)}


def _doc():
    return {
        "seed": "Order", "question": "how does an order reach the database",
        "generated_ts": int(time.time()),
        "slices": [{"id": "main", "title": "Placing an order", "nodes": [
            {"id": "ctl", "layer": "api", "role": "Controller", "name": "OrderController",
             "file": "src/Order.java", "line": 12},
            {"id": "tbl", "layer": "db", "role": "Table", "name": "orders",
             "file": "db/changelog-1.xml", "line": 7},
        ]}],
    }


def _install(dirs):
    flow_module.write_flow(Path(dirs["state_dir"]), _doc())


# ------------------------------------------------------------------ pages
def test_root_shows_the_splash_until_a_document_exists(dirs):
    h = FakeH()
    srv.Handlers().serve_root(h, dirs)
    assert h.status == 200
    assert "Mapping the dataflow" in h.body
    # No renderer is loaded yet — there is nothing for it to draw, and the
    # splash reloads itself instead.
    assert "dataflow.js" not in h.body


def test_root_serves_the_board_once_the_document_is_installed(dirs):
    _install(dirs)
    h = FakeH()
    srv.Handlers().serve_root(h, dirs)
    assert 'id="app"' in h.body
    assert "dataflow.js" in h.body
    assert "Dataflow — Order" in h.body


def test_root_is_closed_once_the_session_is_terminal(dirs):
    _install(dirs)
    (Path(dirs["state_dir"]) / "finished").write_text("")
    h = FakeH()
    srv.Handlers().serve_root(h, dirs)
    assert "closed" in h.body.lower()
    assert "dataflow.js" not in h.body


def test_a_seed_with_markup_cannot_break_out_of_the_title(dirs):
    doc = _doc()
    doc["seed"] = "<script>alert(1)</script>"
    flow_module.write_flow(Path(dirs["state_dir"]), doc)
    h = FakeH()
    srv.Handlers().serve_root(h, dirs)
    assert "<script>alert(1)</script>" not in h.body
    assert "&lt;script&gt;" in h.body


# ------------------------------------------------------------------- data
def test_serve_data_returns_the_document_and_an_empty_shape_without_one(dirs):
    h = FakeH()
    srv.Handlers().serve_data(h, dirs, "dataflow.json")
    assert h.json()["slices"] == []
    _install(dirs)
    h = FakeH()
    srv.Handlers().serve_data(h, dirs, "dataflow.json")
    assert h.json()["seed"] == "Order"


def test_serve_data_404s_an_unknown_query(dirs):
    h = FakeH()
    srv.Handlers().serve_data(h, dirs, "secrets")
    assert h.status == 404


def test_threads_bulk_omits_threads_with_no_answer_yet(dirs):
    threads = Path(dirs["state_dir"]) / "threads"
    (threads / "a.json").write_text(json.dumps({
        "anchor": "node:ctl", "version": 1,
        "messages": [{"role": "user", "ts": 1, "text": "why?"}]}))
    assert srv.Handlers().threads_bulk(dirs) == {}
    (threads / "a.json").write_text(json.dumps({
        "anchor": "node:ctl", "version": 2, "title": "Because",
        "messages": [{"role": "user", "ts": 1, "text": "why?"},
                     {"role": "claude", "ts": 2, "text": "Because of X."}]}))
    bulk = srv.Handlers().threads_bulk(dirs)
    assert bulk["node:ctl"]["latest_synthesis"] == "Because of X."
    assert bulk["node:ctl"]["question"] == "why?"


def test_threads_bulk_skips_a_foreign_or_corrupt_anchor(dirs):
    threads = Path(dirs["state_dir"]) / "threads"
    (threads / "b.json").write_text(json.dumps({
        "anchor": "step:1", "version": 1,
        "messages": [{"role": "claude", "ts": 2, "text": "hi"}]}))
    (threads / "c.json").write_text("{not json")
    assert srv.Handlers().threads_bulk(dirs) == {}


# ----------------------------------------------------------------- submit
def _submit(dirs, **payload):
    h = FakeH()
    srv.Handlers().handle_submit(h, dirs, payload)
    return h


def test_a_question_on_a_real_node_is_queued_and_threaded(dirs):
    _install(dirs)
    h = _submit(dirs, anchor="node:ctl", type="comment", text="why two calls?")
    assert h.status == 202
    assert h.json()["status"] == "queued"
    assert list(Path(dirs["events_dir"]).iterdir()), "no event was written"
    threads = list((Path(dirs["state_dir"]) / "threads").iterdir())
    assert len(threads) == 1
    t = json.loads(threads[0].read_text())
    assert t["anchor"] == "node:ctl"
    assert t["messages"][0]["text"] == "why two calls?"


def test_a_question_against_a_node_that_is_not_on_the_diagram_is_refused(dirs):
    # Claude could never render the answer back, so the event would be work
    # queued into a void.
    _install(dirs)
    h = _submit(dirs, anchor="node:ghost", type="comment", text="hello")
    assert h.status == 404
    assert not list(Path(dirs["events_dir"]).iterdir())


def test_a_malformed_anchor_is_refused_before_the_document_is_read(dirs):
    h = _submit(dirs, anchor="step:1", type="comment", text="hello")
    assert h.status == 400


@pytest.mark.parametrize("payload", [
    {"anchor": "node:ctl", "type": "shout", "text": "hi"},
    {"anchor": "node:ctl", "type": "comment", "text": "   "},
    {"anchor": "node:ctl", "type": "comment"},
])
def test_bad_submissions_are_refused(dirs, payload):
    _install(dirs)
    assert _submit(dirs, **payload).status == 400


def test_submitting_to_a_closed_session_is_refused(dirs):
    _install(dirs)
    (Path(dirs["state_dir"]) / "cancelled").write_text("{}")
    assert _submit(dirs, anchor="node:ctl", type="comment", text="hi").status == 409


# -------------------------------------------------------------- lifecycle
def test_create_session_requires_a_seed(dirs):
    with pytest.raises(ValueError) as exc:
        srv.Handlers().create_session_extra({}, dirs)
    assert "seed" in str(exc.value)


def test_create_session_records_the_seed_and_defaults_the_question(dirs):
    extra = srv.Handlers().create_session_extra({"seed": " Order "}, dirs)
    assert extra["title"] == "Order"
    meta = json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())
    assert meta["seed"] == "Order"
    assert meta["question"] == "Order"
    assert meta["cwd"] == dirs["_cwd"]


def test_poll_reports_the_document_timestamp_and_liveness(dirs):
    _install(dirs)
    h = FakeH()
    srv.Handlers().serve_poll(h, dirs)
    body = h.json()
    assert body["flow_generated_at"] > 0
    assert body["ended"] is False
    (Path(dirs["state_dir"]) / "cancelled").write_text("{}")
    h = FakeH()
    srv.Handlers().serve_poll(h, dirs)
    assert h.json()["ended_reason"] == "cancelled"


def test_comment_count_counts_node_threads(dirs):
    assert srv.Handlers().comment_count(dirs) == 0
    (Path(dirs["state_dir"]) / "threads" / "a.json").write_text("{}")
    assert srv.Handlers().comment_count(dirs) == 1


def test_one_live_dataflow_per_claude_session():
    # A second /dataflow in the same conversation must replace the first, not
    # leave two armed watchers racing to answer the same question.
    assert srv.Handlers.supersede_by_claude_session is True
