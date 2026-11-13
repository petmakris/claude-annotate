import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.dataflow import push


MINIMAL_FLOW = {
    "seed": "OrderService", "question": "how does an order get created",
    "generated_ts": 1700000000, "model": ["claim one"],
    "slices": [{"id": "main", "title": "Creating an order", "nodes": [
        {"id": "n1", "layer": "api", "role": "Controller", "name": "OrderController",
         "file": "OrderController.java", "line": 10, "summary": "s"},
        {"id": "n2", "layer": "db", "role": "Table", "name": "orders",
         "file": "db/changelog-1.xml", "line": 7},
    ]}],
}


def test_push_creates_session_and_pushes_flow_item(tmp_path):
    flow_path = tmp_path / "dataflow.json"
    flow_path.write_text(json.dumps(MINIMAL_FLOW))

    with patch("skills.dataflow.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "s1", "kind": "dataflow",
                            "url": "http://127.0.0.1:3080/s/s1/", "token": "tok"}) as mock_create, \
         patch("skills.dataflow.push.wc.put_items") as mock_put, \
         patch("skills.dataflow.push.wc.register_assets") as mock_assets, \
         patch("skills.dataflow.push.wc.load_config", return_value={"port": 3080, "token": "tok"}):
        res = push.push(flow_path, "/repo")

    mock_create.assert_called_once_with("dataflow", "/repo", title="OrderService", slug=None)
    expected_doc = {**MINIMAL_FLOW, "cwd": str(Path("/repo").resolve())}
    mock_put.assert_called_once_with("s1", {"__flow__": expected_doc}, kind="dataflow", replace=True)
    mock_assets.assert_called_once_with(
        "s1", str(push.STATIC_DIR), "entry.js", kind="dataflow")
    assert res["sid"] == "s1"
    assert res["url"] == "http://127.0.0.1:3080/s/s1/"


def test_push_attaches_by_slug(tmp_path):
    flow_path = tmp_path / "dataflow.json"
    flow_path.write_text(json.dumps(MINIMAL_FLOW))

    with patch("skills.dataflow.push.wc.create_or_attach",
              return_value={"sid": "s2", "slug": "my-slug", "kind": "dataflow",
                            "url": "http://127.0.0.1:3080/s/my-slug/", "token": "tok"}) as mock_create, \
         patch("skills.dataflow.push.wc.put_items"), \
         patch("skills.dataflow.push.wc.register_assets"), \
         patch("skills.dataflow.push.wc.load_config", return_value={"port": 3080, "token": "tok"}):
        push.push(flow_path, "/repo", slug="my-slug")

    mock_create.assert_called_once_with("dataflow", "/repo", title="OrderService", slug="my-slug")


def test_push_refuses_an_invalid_document(tmp_path):
    flow_path = tmp_path / "dataflow.json"
    flow_path.write_text(json.dumps({"seed": "X"}))  # missing question, slices, ...

    with patch("skills.dataflow.push.wc.create_or_attach") as mock_create, \
         patch("skills.dataflow.push.wc.put_items") as mock_put:
        with pytest.raises(ValueError, match="failed validation"):
            push.push(flow_path, "/repo")

    mock_create.assert_not_called()
    mock_put.assert_not_called()


def test_main_reports_validation_errors_and_exits_nonzero(tmp_path, capsys):
    flow_path = tmp_path / "dataflow.json"
    flow_path.write_text(json.dumps({"seed": "X"}))

    rc = push.main(["--flow", str(flow_path), "--cwd", "/repo"])

    assert rc == 1
    assert "failed validation" in capsys.readouterr().err
