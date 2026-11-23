"""Fixture-repo tests for install_hooks.sh: three cases from the original
2026-09-01 design's own testing section (no existing hook, a foreign hook
that must survive ahead of ours, an already-installed repo where a second
run is a no-op), plus the core.hooksPath-outside-.git refusal the script
itself implements.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

INSTALLER = Path(__file__).resolve().parent.parent / "install_hooks.sh"
MARKER = "# claude-annotate: skills.ask_diff.sync"
HOOKS = ("post-commit", "post-rewrite", "post-checkout")


def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _install(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(INSTALLER), str(repo)],
                          capture_output=True, text=True, timeout=10)


def test_installs_all_three_hooks_when_none_exist(tmp_path):
    repo = _git_init(tmp_path / "repo1")
    result = _install(repo)
    assert result.returncode == 0

    for hook in HOOKS:
        hook_path = repo / ".git" / "hooks" / hook
        assert hook_path.exists()
        assert MARKER in hook_path.read_text()
        assert hook_path.stat().st_mode & 0o111  # executable


def test_foreign_hook_survives_ahead_of_the_marker(tmp_path):
    repo = _git_init(tmp_path / "repo2")
    hook_path = repo / ".git" / "hooks" / "post-commit"
    hook_path.write_text("#!/bin/sh\necho \"foreign hook ran\"\n")
    hook_path.chmod(0o755)

    result = _install(repo)
    assert result.returncode == 0

    content = hook_path.read_text()
    assert "foreign hook ran" in content
    assert MARKER in content
    assert content.index("foreign hook ran") < content.index(MARKER)


def test_second_run_is_idempotent(tmp_path):
    repo = _git_init(tmp_path / "repo3")
    _install(repo)
    hook_path = repo / ".git" / "hooks" / "post-commit"
    before = hook_path.read_text()

    _install(repo)
    after = hook_path.read_text()

    assert before == after
    assert after.count(MARKER) == 1


def test_refuses_a_core_hooks_path_outside_git_dir(tmp_path):
    repo = _git_init(tmp_path / "repo4")
    husky = repo / ".husky"
    husky.mkdir()
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".husky"],
                   check=True)

    result = _install(repo)

    assert not (husky / "post-commit").exists()
    assert "outside .git" in result.stderr


def test_invoked_command_uses_the_sync_module_with_no_arguments(tmp_path):
    repo = _git_init(tmp_path / "repo5")
    _install(repo)
    content = (repo / ".git" / "hooks" / "post-commit").read_text()
    assert "python3 -m skills.ask_diff.sync" in content
