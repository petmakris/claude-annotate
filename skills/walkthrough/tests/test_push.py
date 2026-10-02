import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.walkthrough import push


MINIMAL_STEPS = {
    "question": "how does an order get created", "kind": "explain",
    "generated_ts": 1700000000,
    "steps": [
        {"id": 1, "title": "Controller receives the request",
         "file": "OrderController.java", "line": 10,
         "snippet": "public Order createOrder(...)", "role": "seam",
         "markdown": "m"},
    ],
}


def test_push_creates_session_and_pushes_steps_item(tmp_path):
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(MINIMAL_STEPS))

    with patch("skills.walkthrough.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "s1", "kind": "walkthrough",
                            "url": "http://127.0.0.1:3080/s/s1/", "token": "tok"}) as mock_create, \
         patch("skills.walkthrough.push.wc.put_items") as mock_put, \
         patch("skills.walkthrough.push.wc.register_assets") as mock_assets:
        res = push.push(steps_path, "/repo")

    mock_create.assert_called_once_with(
        "walkthrough", "/repo", title="how does an order get created",
        slug=None, supersede=True)
    mock_put.assert_called_once_with(
        "s1", {"__steps__": MINIMAL_STEPS}, kind="walkthrough", replace=True)
    mock_assets.assert_not_called()
    assert res["sid"] == "s1"
    assert res["url"] == "http://127.0.0.1:3080/s/s1/"


def test_push_attaches_by_slug(tmp_path):
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(MINIMAL_STEPS))

    with patch("skills.walkthrough.push.wc.create_or_attach",
              return_value={"sid": "s2", "slug": "my-slug", "kind": "walkthrough",
                            "url": "http://127.0.0.1:3080/s/my-slug/", "token": "tok"}) as mock_create, \
         patch("skills.walkthrough.push.wc.put_items"), \
         patch("skills.walkthrough.push.wc.register_assets"):
        push.push(steps_path, "/repo", slug="my-slug")

    mock_create.assert_called_once_with(
        "walkthrough", "/repo", title="how does an order get created",
        slug="my-slug", supersede=True)


def test_push_uses_explicit_title_over_question(tmp_path):
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(MINIMAL_STEPS))

    with patch("skills.walkthrough.push.wc.create_or_attach",
              return_value={"sid": "s3"}) as mock_create, \
         patch("skills.walkthrough.push.wc.put_items"):
        push.push(steps_path, "/repo", title="Custom Title")

    mock_create.assert_called_once_with(
        "walkthrough", "/repo", title="Custom Title", slug=None, supersede=True)


def test_push_refuses_an_invalid_document(tmp_path):
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps({"question": ""}))  # missing kind, generated_ts, steps

    with patch("skills.walkthrough.push.wc.create_or_attach") as mock_create, \
         patch("skills.walkthrough.push.wc.put_items") as mock_put:
        with pytest.raises(ValueError, match="failed validation"):
            push.push(steps_path, "/repo")

    mock_create.assert_not_called()
    mock_put.assert_not_called()


def test_push_never_registers_assets(tmp_path):
    # walkthrough has no browser page; register_assets must never be called.
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(MINIMAL_STEPS))

    with patch("skills.walkthrough.push.wc.create_or_attach",
              return_value={"sid": "s1"}), \
         patch("skills.walkthrough.push.wc.put_items"), \
         patch("skills.walkthrough.push.wc.register_assets") as mock_assets:
        push.push(steps_path, "/repo")

    mock_assets.assert_not_called()


def test_main_reports_validation_errors_and_exits_nonzero(tmp_path, capsys):
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps({"question": ""}))

    rc = push.main(["--steps", str(steps_path), "--cwd", "/repo"])

    assert rc == 1
    assert "failed validation" in capsys.readouterr().err


def test_main_reports_daemon_unreachable_and_exits_nonzero(tmp_path, capsys):
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(MINIMAL_STEPS))

    with patch("skills.walkthrough.push.wc.create_or_attach",
              side_effect=push.wc.DaemonUnreachable("cannot reach the daemon")):
        rc = push.main(["--steps", str(steps_path), "--cwd", "/repo"])

    assert rc == 1
    assert "cannot reach the daemon" in capsys.readouterr().err
