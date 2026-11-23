"""The narration CLI: the command Claude runs between steps so the reader
learns something during a long silence. These drive it the way the
documentation does, and never reach a daemon.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


# --- the CLI, exactly as the skill documents it -------------------------

def _cli(cwd, *args, env=None):
    import subprocess
    return subprocess.run(
        ["python3", "-m", "skills.annotate.progress", *args],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def test_a_missing_daemon_config_is_reported_not_raised(tmp_path):
    # main()'s DaemonError catch. Narration must never take down the turn it
    # is narrating, so this exits non-zero with a message rather than a
    # traceback — and the documented commands ignore the exit code.
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, PYTHONPATH=str(REPO), HOME=str(home))
    r = _cli(tmp_path, "--sid", "whatever", "--text", "x", env=env)
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "webcompanion is not configured" in r.stderr


def test_neither_text_nor_done_is_a_usage_error(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    r = _cli(tmp_path, "--sid", "whatever", env=env)
    assert r.returncode == 2
    assert "--text or --done" in r.stderr


# --- the commands exactly as the document ships them --------------------
#
# `--sid "$WC_SID"` once broke narration: a variable set in an earlier Bash
# call is empty in this one, and narration may fail without failing the turn.

CONTRACT = REPO / "skills" / "annotate" / "references" / "handling-events.md"
DOC_CMD = "claude-annotate progress"


def _documented_narration_commands():
    """Every runnable narration invocation the contract prints, verbatim."""
    import re
    found = []
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        if DOC_CMD not in line or "--sid" not in line:
            continue
        spans = [s for s in re.findall(r"`([^`]+)`", line)
                 if DOC_CMD in s and "--sid" in s]
        found.extend(spans or [line.strip()])
    assert found, "the contract prints no runnable narration command any more"
    return sorted(set(found))


def test_no_documented_narration_reads_a_shell_variable():
    # `$WC_SID` from an earlier call is empty in this one. Literal values only.
    bad = [c for c in _documented_narration_commands() if "$" in c]
    assert bad == [], bad
