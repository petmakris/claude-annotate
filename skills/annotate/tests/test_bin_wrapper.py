"""bin/claude-annotate: the one command every annotate reference calls.

Claude Code puts `<plugin root>/bin` on PATH (for --plugin-dir and marketplace
installs alike), so a script there is callable by name from any directory.
It replaced a 431-byte root-finding one-liner that handling-events.md spelled
out fourteen times, which every event turn paid to read.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BIN = REPO / "bin" / "claude-annotate"


def _run(*args, cwd, env=None):
    base = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([str(BIN), *args], cwd=cwd, env={**base, **(env or {})},
                          capture_output=True, text=True, timeout=60)


def test_it_is_executable():
    assert BIN.is_file() and os.access(BIN, os.X_OK)


def test_it_runs_a_module_from_any_directory(tmp_path):
    r = _run("progress", "--help", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "--sid" in r.stdout


def test_dashes_map_to_module_names(tmp_path):
    # check_anchors has no --help; its own usage line proves it was reached.
    r = _run("check-anchors", cwd=tmp_path)
    assert "skills.annotate.check_anchors" in r.stderr, r.stderr


def test_nested_modules_are_reachable(tmp_path):
    r = _run("confluence.prepare", "--help", cwd=tmp_path)
    assert r.returncode == 0, r.stderr


def test_the_callers_directory_is_kept(tmp_path):
    """The old commands `cd`-ed into the plugin root and then passed "$PWD" as
    the repo root, which by then was the plugin root. The wrapper never moves."""
    r = _run("session", "--help", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    probe = subprocess.run(
        ["sh", "-c", 'grep -n "^ *cd " "$0" || true', str(BIN)],
        capture_output=True, text=True)
    assert probe.stdout == "", "the wrapper changes directory: " + probe.stdout


def test_an_unknown_command_names_the_real_ones(tmp_path):
    r = _run("nope", cwd=tmp_path)
    assert r.returncode != 0
    assert "push" in r.stderr and "progress" in r.stderr


def test_no_python_is_a_sentence_not_a_traceback(tmp_path):
    r = _run("progress", "--help", cwd=tmp_path, env={"PATH": "/nonexistent"})
    assert r.returncode != 0
    assert "python3 was not found" in r.stderr


def test_root_prints_the_plugin_root(tmp_path):
    r = _run("root", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()).resolve() == REPO.resolve()


def test_python_runs_with_the_plugin_root_importable(tmp_path):
    r = _run("python", "-c", "import skills.ask_diff.push, os; print(os.getcwd())",
             cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()).resolve() == tmp_path.resolve()


def test_other_skills_modules_are_reachable_as_skill_dot_module(tmp_path):
    for cmd in ("ask_diff.push", "walkthrough.push", "deck.push", "dataflow.push"):
        r = _run(cmd, "--help", cwd=tmp_path)
        assert r.returncode == 0, (cmd, r.stderr)
        assert "--cwd" in r.stdout, cmd


def test_a_bare_name_outside_annotate_is_not_a_command(tmp_path):
    # `diff` exists only as skills/ask_diff/diff.py; without the skill prefix
    # it must not resolve to some other skill's module by accident.
    r = _run("diff", cwd=tmp_path)
    assert r.returncode == 2
    assert "not a command" in r.stderr


def test_dot_dot_cannot_walk_out_of_skills(tmp_path):
    r = _run("..bin.claude-annotate", cwd=tmp_path)
    assert r.returncode == 2
