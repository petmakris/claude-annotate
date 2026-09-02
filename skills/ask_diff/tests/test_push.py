import json
import subprocess
from unittest.mock import patch

import pytest

from skills.ask_diff import push


SAMPLE_META = {
    "title": "Fix the frobnicator",
    "headRefName": "feature/frob",
    "baseRefName": "master",
    "author": {"login": "alice"},
    "url": "https://github.com/acme/widget/pull/42",
    "headRefOid": "abc123",
}


def _fetch_ok(diff_text="diff --git a/x b/x\n"):
    return (diff_text, dict(SAMPLE_META))


def test_push_creates_session_and_pushes_both_items():
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok()) as mock_fetch, \
         patch("skills.ask_diff.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "s1", "kind": "interactive-review",
                            "url": "http://127.0.0.1:3080/s/s1/", "token": "tok"}) as mock_create, \
         patch("skills.ask_diff.push.wc.put_items") as mock_put, \
         patch("skills.ask_diff.push.wc.register_assets") as mock_assets, \
         patch("skills.ask_diff.push.time.time", return_value=1700000000):
        res = push.push("42", "/repo", "claude-session-abc")

    mock_fetch.assert_called_once_with("42", "/repo")
    mock_create.assert_called_once_with(
        "interactive-review", "/repo", title="Fix the frobnicator",
        slug=None, supersede=True)
    mock_put.assert_called_once_with(
        "s1",
        {
            "__diff__": "diff --git a/x b/x\n",
            "__meta__": {
                "pr_ref": "42",
                "title": "Fix the frobnicator",
                "head": "feature/frob",
                "base": "master",
                "author": "alice",
                "url": "https://github.com/acme/widget/pull/42",
                "head_oid": "abc123",
                "fetched_at": 1700000000,
            },
        },
        kind="interactive-review", replace=True)
    mock_assets.assert_not_called()
    assert res["sid"] == "s1"
    assert res["url"] == "http://127.0.0.1:3080/s/s1/"
    assert "warning" not in res


def test_push_never_scopes_supersede_by_claude_session():
    # Step 1's ruling: supersede is (kind, cwd)-scoped only -- the daemon has
    # no claude_session_id-aware supersede, so create_or_attach must never be
    # called with anything session-scoped, and claude_session_id must not
    # leak into the call at all.
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok()), \
         patch("skills.ask_diff.push.wc.create_or_attach",
              return_value={"sid": "s1"}) as mock_create, \
         patch("skills.ask_diff.push.wc.put_items"):
        push.push("42", "/repo", "claude-session-abc")

    _, kwargs = mock_create.call_args
    assert kwargs == {"title": "Fix the frobnicator", "slug": None, "supersede": True}
    assert "claude_session_id" not in kwargs


def test_push_attaches_by_slug():
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok()), \
         patch("skills.ask_diff.push.wc.create_or_attach",
              return_value={"sid": "s2", "slug": "my-slug"}) as mock_create, \
         patch("skills.ask_diff.push.wc.put_items"):
        push.push("42", "/repo", "claude-session-abc", slug="my-slug")

    mock_create.assert_called_once_with(
        "interactive-review", "/repo", title="Fix the frobnicator",
        slug="my-slug", supersede=True)


def test_push_refuses_diff_over_the_hard_limit():
    huge = "x" * (push.MAX_DIFF_BYTES + 1)
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok(huge)), \
         patch("skills.ask_diff.push.wc.create_or_attach") as mock_create, \
         patch("skills.ask_diff.push.wc.put_items") as mock_put:
        with pytest.raises(ValueError, match="MB limit"):
            push.push("42", "/repo", "claude-session-abc")

    mock_create.assert_not_called()
    mock_put.assert_not_called()


def test_push_warns_but_succeeds_over_the_soft_limit():
    large = "x" * (push.WARN_DIFF_BYTES + 1)
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok(large)), \
         patch("skills.ask_diff.push.wc.create_or_attach",
              return_value={"sid": "s1"}), \
         patch("skills.ask_diff.push.wc.put_items"):
        res = push.push("42", "/repo", "claude-session-abc")

    assert "warning" in res
    assert "large diff" in res["warning"]


def test_push_wraps_a_gh_failure_as_value_error_and_never_calls_the_daemon():
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              side_effect=subprocess.CalledProcessError(1, ["gh", "pr", "view"])), \
         patch("skills.ask_diff.push.wc.create_or_attach") as mock_create, \
         patch("skills.ask_diff.push.wc.put_items") as mock_put:
        with pytest.raises(ValueError, match="gh pr fetch failed"):
            push.push("42", "/repo", "claude-session-abc")

    mock_create.assert_not_called()
    mock_put.assert_not_called()


def test_push_never_registers_assets():
    # ask_diff has no browser page; register_assets must never be called.
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok()), \
         patch("skills.ask_diff.push.wc.create_or_attach",
              return_value={"sid": "s1"}), \
         patch("skills.ask_diff.push.wc.put_items"), \
         patch("skills.ask_diff.push.wc.register_assets") as mock_assets:
        push.push("42", "/repo", "claude-session-abc")

    mock_assets.assert_not_called()


def test_main_reports_gh_failure_and_exits_nonzero(capsys):
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              side_effect=subprocess.CalledProcessError(1, ["gh", "pr", "view"])):
        rc = push.main(["--pr", "42", "--cwd", "/repo",
                        "--claude-session-id", "cs-1"])

    assert rc == 1
    assert "gh pr fetch failed" in capsys.readouterr().err


def test_main_reports_daemon_unreachable_and_exits_nonzero(capsys):
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok()), \
         patch("skills.ask_diff.push.wc.create_or_attach",
              side_effect=push.wc.DaemonUnreachable("cannot reach the daemon")):
        rc = push.main(["--pr", "42", "--cwd", "/repo",
                        "--claude-session-id", "cs-1"])

    assert rc == 1
    assert "cannot reach the daemon" in capsys.readouterr().err


def test_main_prints_the_result_json_on_success(capsys):
    with patch("skills.ask_diff.push.diff_module.fetch_pr_diff",
              return_value=_fetch_ok()), \
         patch("skills.ask_diff.push.wc.create_or_attach",
              return_value={"sid": "s1", "url": "http://127.0.0.1:3080/s/s1/"}), \
         patch("skills.ask_diff.push.wc.put_items"):
        rc = push.main(["--pr", "42", "--cwd", "/repo",
                        "--claude-session-id", "cs-1"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["sid"] == "s1"
