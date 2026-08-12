# Install and First-Use Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user whose machine cannot run this plugin learns that in one clear message naming the plugin and the fix, and a user who never invokes the plugin is never affected by it at all.

**Architecture:** Declare the requirement, verify it, explain the gap, never fill it. Three independent layers: a POSIX-sh gate on the `PostToolUse` hook so it is silent when unusable and free when unused; a preflight in the bootstrap and in `ensure_server.sh` that speaks once and stops; and `doctor.sh` written in POSIX sh so it runs on a machine where nothing works, wrapped by an `/annotate-doctor` skill.

**Tech Stack:** POSIX `sh`, `bash`, Python 3.9+ stdlib, `pytest`/`unittest`, GitHub Actions.

## Global Constraints

- **Never mutate the user's machine.** No installing, no symlinking, no `PATH` modification, no writing outside `~/.claude/<skill>/`. Every remedy is text the user runs themselves.
- **No interpreter probing.** Check for `python3` only. Never fall back to `python`, Homebrew paths, `uv`, or `$CLAUDE_ANNOTATE_PYTHON`.
- **Declared Python floor is `3.9`** — forced by `Path.is_relative_to` at `skills/_shared/web_companion/uploads.py:76`.
- **`doctor.sh` and the hook gate must contain no Python and no `jq`.** They run on machines where `python3` does not exist.
- **The hook never reports problems.** It fires hundreds of times per session and cannot speak once. It exits 0 silently or does its job.
- **Platforms:** macOS and Linux only.
- **Run tests from the repo root** with `python3 -m pytest`, never bare `pytest`.
- Baseline before any change: `python3 -m pytest skills -q`. Record the count in Task 1 and keep every later task green.

---

### Task 1: Sanitized-PATH fixture and the hook gate

The hook is what burned the reporting user. It publishes a cosmetic progress label and currently turns every tool call into a red line on a machine without `python3`.

Two facts constrain the gate. It receives the `PostToolUse` JSON on **stdin**, so it must not read stdin — doing so would consume the payload before `progress_publish.py` sees it. And `session_id` lives inside that JSON, so the gate cannot filter by session; it checks whether *any* pending round exists and lets Python do the precise per-session check it already does today.

**Files:**
- Create: `skills/tests/sanitized_env.py`
- Create: `skills/annotate/tests/test_hook_gate.py`
- Modify: `hooks/hooks.json:9`

**Interfaces:**
- Consumes: nothing.
- Produces: `skills/tests/sanitized_env.py` exposing `sanitized_path_dir(tmp: Path, *, with_python: bool = False, spy: bool = False) -> Path` (builds a directory of symlinks to real tools, optionally including a `python3` that is either real or a spy script) and `hook_command() -> str` (reads the shipped `hooks/hooks.json` and returns the single `PostToolUse` command string). Tasks 2, 3 and 5 import `sanitized_path_dir`.

- [ ] **Step 1: Record the baseline test count**

Run: `python3 -m pytest skills -q 2>&1 | tail -2`

Write the number down. Every task below must end green, and the count only ever grows.

- [ ] **Step 2: Write the shared fixture**

Create `skills/tests/sanitized_env.py`:

```python
"""Build a PATH that deliberately lacks python3.

The install-robustness work claims our shell entry points fail quietly when
no interpreter exists. That claim is only worth anything if a test watches
the failure, so these helpers construct a PATH containing the tools our
scripts genuinely need and nothing else.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Claude Code reports hook failures as coming from /usr/bin/bash, but that
# path does not exist on macOS (bash is /bin/bash there). Resolve it instead
# of hardcoding, or every test in this suite fails on a Mac for the wrong
# reason.
BASH = shutil.which("bash") or "/bin/bash"

# Tools our shell scripts legitimately call. python3 is deliberately absent.
# `dirname` matters: skills/annotate/ensure_server.sh:3 calls it before
# anything else, so omitting it would make the preflight test fail for the
# wrong reason.
_NEEDED = (
    "sh", "bash", "env", "cat", "sed", "grep", "mkdir", "rm", "rmdir",
    "date", "stat", "sleep", "seq", "ps", "curl", "uname", "tr",
    "dirname", "basename", "head", "cut", "nohup",
)


def sanitized_path_dir(tmp: Path, *, with_python: bool = False,
                       spy: bool = False) -> Path:
    """Create a bin directory to use as the whole PATH.

    with_python=False -> no python3 at all (the reported user's machine).
    with_python=True, spy=False -> the real python3, symlinked.
    with_python=True, spy=True -> a shell script named python3 that records
        that it ran, so a test can prove the gate never spawned it.
    """
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in _NEEDED:
        real = shutil.which(name)
        if real:
            link = bin_dir / name
            if not link.exists():
                link.symlink_to(real)
    if with_python:
        target = bin_dir / "python3"
        if spy:
            marker = tmp / "python3-was-spawned"
            target.write_text(
                "#!/bin/sh\n"
                f"echo spawned > '{marker}'\n"
                "exit 0\n"
            )
            target.chmod(0o755)
        else:
            real = shutil.which("python3")
            assert real, "the test host must have python3"
            target.symlink_to(real)
    return bin_dir


def spy_marker(tmp: Path) -> Path:
    """Path the spy python3 writes to when it is executed."""
    return tmp / "python3-was-spawned"


def hook_command() -> str:
    """The PostToolUse command exactly as shipped in hooks/hooks.json."""
    data = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = data["hooks"]["PostToolUse"]
    commands = [h["command"] for e in entries for h in e["hooks"]]
    assert len(commands) == 1, f"expected exactly one PostToolUse command, got {commands}"
    return commands[0]


def hook_env(home: Path, bin_dir: Path) -> dict:
    """Environment mimicking how Claude Code invokes a plugin hook."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(bin_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env
```

- [ ] **Step 3: Write the failing tests**

Create `skills/annotate/tests/test_hook_gate.py`:

```python
"""The progress hook must be invisible unless it can do useful work.

It fires on every PostToolUse. On a machine with no python3 it used to print
a bash error per tool call; for a user who installed only claude-ide-review
it spawned an interpreter per tool call for a feature they do not have.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import (
    BASH, hook_command, hook_env, sanitized_path_dir, spy_marker,
)

PAYLOAD = json.dumps({"tool_name": "Bash", "session_id": "sess-1"})


def _run(bin_dir: Path, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, "-c", hook_command()],
        input=PAYLOAD, capture_output=True, text=True, timeout=10,
        env=hook_env(home, bin_dir),
    )


class HookGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hookgate-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_silent_when_no_python3(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        (self.home / ".claude" / "annotate").mkdir(parents=True)
        (self.home / ".claude" / "annotate" / "pending-sess-1.json").write_text("[]")
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_does_not_spawn_python_when_no_pending_rounds(self):
        # The claude-ide-review-only user: python3 exists, annotate does not run.
        bin_dir = sanitized_path_dir(self.tmp, with_python=True, spy=True)
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse(
            spy_marker(self.tmp).exists(),
            "gate must not spawn an interpreter when no round is pending",
        )

    def test_spawns_python_when_a_round_is_pending(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=True, spy=True)
        (self.home / ".claude" / "annotate").mkdir(parents=True)
        (self.home / ".claude" / "annotate" / "pending-sess-1.json").write_text("[]")
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(
            spy_marker(self.tmp).exists(),
            "gate must hand off to the interpreter when work may exist",
        )

    def test_payload_reaches_the_interpreter_on_stdin(self):
        # The gate must not read stdin: progress_publish.py parses it.
        bin_dir = sanitized_path_dir(self.tmp, with_python=True, spy=False)
        d = self.home / ".claude" / "annotate"
        d.mkdir(parents=True)
        (d / "pending-sess-1.json").write_text("[]")
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 -m pytest skills/annotate/tests/test_hook_gate.py -v`

Expected: `test_silent_when_no_python3` FAILS — stderr contains `python3: command not found`. `test_does_not_spawn_python_when_no_pending_rounds` FAILS — the spy marker exists.

Watch both failures. If either passes before the change, the test is not testing what it claims.

- [ ] **Step 5: Add the gate**

Replace the `command` value at `hooks/hooks.json:9`. The whole string is what `/usr/bin/bash -c` receives, so no extra `sh -c` wrapper is needed:

```json
            "command": "command -v python3 >/dev/null 2>&1 || exit 0; set -- \"$HOME\"/.claude/annotate/pending-*.json; [ -e \"$1\" ] || exit 0; exec python3 \"${CLAUDE_PLUGIN_ROOT}/skills/annotate/hooks/progress_publish.py\""
```

Three things this does, in order: exits 0 if no interpreter exists; exits 0 if no session anywhere has a pending annotate round (the unmatched-glob idiom leaves the literal pattern in `$1`, which `-e` rejects); otherwise `exec`s Python with stdin untouched, so `progress_publish.py` still receives the payload and still does the precise per-session check it does today.

Also update the `description` field at `hooks/hooks.json:2` to state the gate, appending to the existing sentence:

```
Gated in POSIX sh: exits 0 without spawning an interpreter unless python3 resolves and this machine has a pending annotate round, so a machine without Python stays silent and an ide-review-only install pays nothing.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_hook_gate.py -v`
Expected: 4 passed.

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest skills -q`
Expected: baseline count + 4, all passing.

- [ ] **Step 8: Commit**

```bash
git add skills/tests/sanitized_env.py skills/annotate/tests/test_hook_gate.py hooks/hooks.json
git commit -m "fix(hooks): gate the progress hook in POSIX sh

It fired on every PostToolUse and printed a bash error per tool call on a
machine without python3. It now exits 0 silently unless an interpreter
resolves and a pending annotate round exists, so an ide-review-only install
stops spawning Python it has no use for. The gate never touches stdin, so
the PostToolUse payload still reaches progress_publish.py."
```

---

### Task 2: Preflight in `ensure_server.sh`

`ensure_server.sh` uses `python3` in three places (lines 30, 78, 137). Without an interpreter the server never starts, and the user sees whatever bash says rather than anything naming the plugin.

**Files:**
- Modify: `skills/_shared/web_companion/ensure_server.sh` (insert after line 24)
- Create: `skills/_shared/web_companion/tests/test_preflight.py`

**Interfaces:**
- Consumes: `sanitized_path_dir` from Task 1.
- Produces: a shell function `preflight()` in `ensure_server.sh`, called before any interpreter use. Task 3's `doctor.sh` reproduces the same checks independently; they share wording, not code, because `doctor.sh` must run standalone.

- [ ] **Step 1: Write the failing test**

Create `skills/_shared/web_companion/tests/test_preflight.py`:

```python
"""ensure_server.sh must name the plugin and the fix, not leak bash errors."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

SCRIPT = REPO_ROOT / "skills" / "annotate" / "ensure_server.sh"


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="preflight-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, bin_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(bin_dir / "bash"), str(SCRIPT)],
            capture_output=True, text=True, timeout=20,
            env={"HOME": str(self.home), "PATH": str(bin_dir)},
        )

    def test_reports_missing_python_and_stops(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=False))
        self.assertNotEqual(result.returncode, 0)
        err = result.stderr
        self.assertIn("claude-annotate", err)
        self.assertIn("python3", err)
        self.assertIn("3.9", err)
        # A remedy the user can act on, not just a complaint.
        self.assertIn("xcode-select --install", err)

    def test_message_is_one_block_not_a_bash_trace(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=False))
        self.assertNotIn("command not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/_shared/web_companion/tests/test_preflight.py -v`
Expected: both FAIL — stderr contains `python3: command not found` and none of the expected strings.

- [ ] **Step 3: Add the preflight**

Insert into `skills/_shared/web_companion/ensure_server.sh` immediately after `mkdir -p "$STATE_DIR"` (line 24). `set -euo pipefail` is active, so every probe is guarded by `if !` rather than left to fail the script:

```bash
preflight() {
  # Requirements are the user's to install; ours to state clearly. Never
  # probe for other interpreters and never install anything — see
  # docs/superpowers/specs/2026-08-12-install-robustness-design.md.
  if ! command -v python3 >/dev/null 2>&1; then
    cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.

This plugin needs Python 3.9 or newer (standard library only — there is
nothing to pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Then run /annotate-doctor to confirm the install is healthy.
EOF
    return 1
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    local found
    found="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown)"
    cat >&2 <<EOF
claude-annotate: python3 is version $found, but this plugin needs 3.9 or newer.

  macOS:  brew install python
  Linux:  install a newer python3 with your distribution's package manager

Then run /annotate-doctor to confirm the install is healthy.
EOF
    return 1
  fi
  if ! command -v curl >/dev/null 2>&1; then
    cat >&2 <<'EOF'
claude-annotate: curl was not found on PATH.

The launcher uses curl to check whether the local server is healthy.
Install curl with your system's package manager, then run /annotate-doctor.
EOF
    return 1
  fi
}

preflight || exit 1
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m pytest skills/_shared/web_companion/tests/test_preflight.py -v`
Expected: 2 passed.

- [ ] **Step 5: Confirm the healthy path still works**

The existing launcher tests are the guard against a preflight that rejects a good machine.

Run: `python3 -m pytest skills/annotate/tests/test_ensure_server.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the full suite and commit**

Run: `python3 -m pytest skills -q`
Expected: previous count + 2.

```bash
git add skills/_shared/web_companion/ensure_server.sh skills/_shared/web_companion/tests/test_preflight.py
git commit -m "feat(engine): preflight python3, version and curl before starting

Without an interpreter the launcher failed with a raw bash error naming
neither the plugin nor a fix. It now checks python3, the 3.9 floor and curl
up front and prints one block with the remedy for the platform."
```

---

### Task 3: `doctor.sh`

One constraint determines the implementation: it diagnoses the absence of Python, so it cannot be written in Python, and it cannot use `jq`.

**Files:**
- Create: `skills/_shared/web_companion/doctor.sh`
- Create: `skills/_shared/web_companion/tests/test_doctor.py`

**Interfaces:**
- Consumes: `sanitized_path_dir` from Task 1.
- Produces: `skills/_shared/web_companion/doctor.sh`, executable, no arguments. Prints one line per check prefixed `ok  ` or `FAIL`, exits 0 only when every required check passes. Task 4's skill invokes it by path.

- [ ] **Step 1: Write the failing test**

Create `skills/_shared/web_companion/tests/test_doctor.py`:

```python
"""The doctor must run on a machine where nothing else does."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

DOCTOR = REPO_ROOT / "skills" / "_shared" / "web_companion" / "doctor.sh"


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, bin_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(bin_dir / "sh"), str(DOCTOR)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.home), "PATH": str(bin_dir)},
        )

    def test_is_executable_and_posix_sh(self):
        self.assertTrue(DOCTOR.exists())
        self.assertTrue(DOCTOR.stat().st_mode & 0o111, "doctor.sh must be executable")
        self.assertEqual(DOCTOR.read_text().splitlines()[0], "#!/bin/sh")

    def test_contains_no_python_and_no_jq(self):
        # It diagnoses the absence of python3. It cannot depend on it.
        body = "\n".join(
            line for line in DOCTOR.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("jq ", body)
        self.assertNotIn("python3 -c", body)
        self.assertNotIn("python3 -m", body)

    def test_runs_and_reports_when_python_is_missing(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=False))
        self.assertNotEqual(result.returncode, 0, "must exit non-zero on a broken machine")
        out = result.stdout
        self.assertIn("FAIL", out)
        self.assertIn("python3", out)
        self.assertIn("xcode-select --install", out)

    def test_passes_python_check_on_a_healthy_machine(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=True))
        python_lines = [l for l in result.stdout.splitlines() if "python3" in l]
        self.assertTrue(python_lines, "doctor must report on python3")
        self.assertTrue(
            any(l.startswith("ok") for l in python_lines),
            f"python3 should pass on this host: {python_lines}",
        )

    def test_never_writes_outside_state_dir(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=True)
        before = sorted(p.name for p in self.home.iterdir())
        self._run(bin_dir)
        after = sorted(p.name for p in self.home.iterdir())
        self.assertEqual(before, after, "doctor must not create anything")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/_shared/web_companion/tests/test_doctor.py -v`
Expected: all FAIL — `doctor.sh` does not exist.

- [ ] **Step 3: Write the doctor**

Create `skills/_shared/web_companion/doctor.sh`:

```sh
#!/bin/sh
# Diagnose a claude-annotate / claude-ide-review install.
#
# POSIX sh on purpose: this script exists to report that python3 is missing,
# so it cannot be written in Python, and it must not need jq. It reports and
# prescribes; it never installs, symlinks, or edits PATH.
#
# Exit: 0 when every required check passes, 1 otherwise.

failures=0

ok()   { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
fix()  { printf '        %s\n' "$1"; }

printf 'claude-annotate doctor\n\n'

# --- interpreter -----------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  version="$(python3 --version 2>&1 | tr -d '\n')"
  where="$(command -v python3)"
  major="$(python3 --version 2>&1 | sed -n 's/[^0-9]*\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1/p')"
  minor="$(python3 --version 2>&1 | sed -n 's/[^0-9]*\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\2/p')"
  # An unparseable version must not make `[` error out under an empty operand.
  [ -n "$major" ] || major=0
  [ -n "$minor" ] || minor=0
  if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; }; then
    ok "python3 — $version ($where)"
  else
    fail "python3 — $version is older than the required 3.9 ($where)"
    fix "macOS:  brew install python"
    fix "Linux:  install a newer python3 with your package manager"
  fi
else
  fail "python3 — not found on PATH"
  fix "macOS:  xcode-select --install     (or: brew install python)"
  fix "Linux:  install python3 with your distribution's package manager"
  fix "Nothing needs pip: this plugin uses the standard library only."
fi

# --- the shim trap ---------------------------------------------------------
# Hooks run under a non-interactive shell. A pyenv/asdf/conda shim added by
# .zshrc is invisible there, so `python3 --version` can work when the user
# types it and fail inside a hook. No README can resolve that; detect it.
login_python="$(bash -lc 'command -v python3' 2>/dev/null)"
if [ -n "$login_python" ] && ! command -v python3 >/dev/null 2>&1; then
  fail "python3 — found by your login shell but NOT by a non-interactive shell"
  fix "Your shell finds it at: $login_python"
  fix "Hooks run under a non-interactive shell, which does not read your rc file."
  fix "Expose it to non-interactive shells, e.g. link it onto the default PATH:"
  fix "  sudo ln -s \"$login_python\" /usr/local/bin/python3"
fi

# --- other tools -----------------------------------------------------------
for tool in bash curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool — $(command -v "$tool")"
  else
    fail "$tool — not found on PATH"
    fix "Install $tool with your system's package manager."
  fi
done

# --- state directories -----------------------------------------------------
for skill in annotate walkthrough interactive-review; do
  dir="$HOME/.claude/$skill"
  if [ ! -d "$dir" ]; then
    ok "$skill — no state yet (never run on this machine)"
  elif [ -w "$dir" ]; then
    ok "$skill — state directory writable ($dir)"
  else
    fail "$skill — state directory is not writable ($dir)"
    fix "chmod u+w \"$dir\""
  fi
done

# --- server ----------------------------------------------------------------
for skill in annotate walkthrough interactive-review; do
  info="$HOME/.claude/$skill/server.json"
  [ -f "$info" ] || continue
  url="$(sed -n 's/.*"url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$info" | head -n 1)"
  if [ -z "$url" ]; then
    fail "$skill — server.json has no url"
    fix "rm \"$info\" and run the skill again to restart the server."
  elif command -v curl >/dev/null 2>&1 && curl -sf --max-time 2 "$url/health" >/dev/null 2>&1; then
    ok "$skill — server healthy at $url"
  else
    ok "$skill — server not running (it starts on next use)"
  fi
done

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'All checks passed.\n'
  exit 0
fi
printf '%s check(s) failed. Fix the lines marked FAIL above, then run this again.\n' "$failures"
printf 'This tool only reports — it never installs or changes anything.\n'
exit 1
```

- [ ] **Step 4: Make it executable**

```bash
chmod +x skills/_shared/web_companion/doctor.sh
```

- [ ] **Step 5: Run it to verify it passes**

Run: `python3 -m pytest skills/_shared/web_companion/tests/test_doctor.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run it by hand and read the output**

Run: `sh skills/_shared/web_companion/doctor.sh`
Expected: every line prefixed `ok`, exit 0. Read it as a stranger would — if any line does not say what to do about a failure, fix the wording now.

- [ ] **Step 7: Run the full suite and commit**

Run: `python3 -m pytest skills -q`
Expected: previous count + 5.

```bash
git add skills/_shared/web_companion/doctor.sh skills/_shared/web_companion/tests/test_doctor.py
git commit -m "feat(engine): add doctor.sh, a POSIX-sh install diagnostic

Checks python3 and the 3.9 floor, the non-interactive PATH gap that makes a
pyenv shim work in a terminal but fail in a hook, curl, bash, state
directory permissions and server health. Written in sh because it exists to
report that python3 is missing. Reports only — never installs."
```

---

### Task 4: The `/annotate-doctor` skill

`test_plugin_skill_lists_partition_the_skills_tree` asserts that no skill is claimed by two plugins and that the marketplace listing exactly equals the skill directories on disk. So this skill is listed under `claude-annotate` only. A `claude-ide-review`-only user still gets the diagnosis, because the Task 2 preflight message points at the script and the files ship from the same root.

**Files:**
- Create: `skills/annotate-doctor/SKILL.md`
- Modify: `.claude-plugin/marketplace.json`

**Interfaces:**
- Consumes: `skills/_shared/web_companion/doctor.sh` from Task 3.
- Produces: skill `annotate-doctor`, invoked as `/annotate-doctor`.

- [ ] **Step 1: Run the structure test to watch it fail**

Create the directory and a stub first, so the guard fires:

```bash
mkdir -p skills/annotate-doctor && printf -- '---\nname: annotate-doctor\ndescription: stub\n---\n' > skills/annotate-doctor/SKILL.md
python3 -m pytest skills/tests/test_repo_structure.py::test_plugin_skill_lists_partition_the_skills_tree -v
```

Expected: FAIL — the on-disk set now contains `./skills/annotate-doctor`, which the marketplace does not list. This is the guard doing its job.

- [ ] **Step 2: Write the skill**

Replace `skills/annotate-doctor/SKILL.md` with:

```markdown
---
name: annotate-doctor
description: Check that this machine can run claude-annotate and claude-ide-review — python3 and its version, curl, state directory permissions, and server health. Invoked only when the user types `/annotate-doctor`, or when a skill's preflight has just failed and the user asks why. Never self-triggers. Reports problems and prints the command the user should run; never installs anything.
allowed-tools:
  - Bash
  - Read
---

# /annotate-doctor — is this machine able to run the plugin?

Run the diagnostic and report what it says. It is POSIX `sh` and needs no
Python, which matters because the most common failure it diagnoses is Python
being absent.

## Run it

```bash
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$(command -v annotate-doctor 2>/dev/null || echo .)")" && pwd)}"
for candidate in "$CLAUDE_PLUGIN_ROOT" "$HOME/.claude/plugins/cache"/*/claude-annotate/*; do
  if [ -f "$candidate/skills/_shared/web_companion/doctor.sh" ]; then
    sh "$candidate/skills/_shared/web_companion/doctor.sh"
    exit $?
  fi
done
echo "claude-annotate: could not locate doctor.sh" >&2
exit 1
```

If `$CLAUDE_PLUGIN_ROOT` is set, the first candidate matches immediately.

## Report

Show the user the output verbatim — it is already written for a human, and
paraphrasing loses the exact commands. Then add one sentence naming the single
most important thing to fix, if anything failed.

Do **not** run any remedy yourself. The commands it prints install software or
change permissions on the user's machine; those are theirs to run. Offer to
explain a line if they want, and stop there.

If every check passes but the user still sees a problem, the useful next
questions are which skill they invoked, and what the terminal showed.
```

- [ ] **Step 3: List it in the marketplace**

In `.claude-plugin/marketplace.json`, change the `claude-annotate` entry's skills array:

```json
      "skills": [
        "./skills/annotate",
        "./skills/annotate-doctor"
      ]
```

Leave the `claude-ide-review` entry's skills array unchanged.

- [ ] **Step 4: Run the structure test to verify it passes**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run the full suite and commit**

Run: `python3 -m pytest skills -q`
Expected: same count as Task 3 (no new tests, one new skill).

```bash
git add skills/annotate-doctor/SKILL.md .claude-plugin/marketplace.json
git commit -m "feat(doctor): add the /annotate-doctor skill

A thin wrapper over doctor.sh so the diagnostic has a name a user can type.
Listed under claude-annotate only: the structure guard forbids one skill
being claimed by two plugins, and an ide-review-only user still reaches the
script through the preflight message."
```

---

### Task 5: Guard the bootstrap blocks

This is the failure the user actually meets first. Each skill flow opens by resolving `PLUGIN_ROOT` with `python3 -c`, *before* `ensure_server.sh` runs — so on a machine without an interpreter the Task 2 preflight never gets the chance to speak, and Claude sees a raw `command not found`.

**Files:**
- Modify: `skills/annotate/references/pushing.md:49`
- Modify: `skills/walkthrough/SKILL.md:46`
- Modify: `skills/interactive_review/SKILL.md:42`
- Create: `skills/tests/test_bootstrap_guard.py`

**Interfaces:**
- Consumes: `sanitized_path_dir` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `skills/tests/test_bootstrap_guard.py`. It extracts the shipped bash block from each doc and *runs* it, rather than asserting on the text — a doc that merely mentions a guard is not a guard:

```python
"""Every skill's bootstrap block must fail with a named message, not a trace.

The bootstrap resolves PLUGIN_ROOT with python3 and runs before
ensure_server.sh, so it is the first thing to break on a machine with no
interpreter. These tests execute the block exactly as shipped.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

DOCS = [
    "skills/annotate/references/pushing.md",
    "skills/walkthrough/SKILL.md",
    "skills/interactive_review/SKILL.md",
]

BLOCK_RE = re.compile(r"```bash\n(.*?PLUGIN_ROOT=.*?)```", re.DOTALL)


def bootstrap_block(rel: str) -> str:
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    match = BLOCK_RE.search(text)
    assert match, f"no bootstrap bash block found in {rel}"
    return match.group(1)


class BootstrapGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootstrap-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, script: str, bin_dir: Path) -> subprocess.CompletedProcess:
        path = self.tmp / "block.sh"
        path.write_text(script)
        return subprocess.run(
            [str(bin_dir / "bash"), str(path)],
            capture_output=True, text=True, timeout=20,
            env={"HOME": str(self.home), "PATH": str(bin_dir)},
        )

    def test_each_bootstrap_names_the_plugin_and_the_fix(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        for rel in DOCS:
            with self.subTest(doc=rel):
                result = self._run(bootstrap_block(rel), bin_dir)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("claude-annotate", result.stderr)
                self.assertIn("python3", result.stderr)
                self.assertIn("/annotate-doctor", result.stderr)

    def test_no_raw_command_not_found_reaches_the_user(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        for rel in DOCS:
            with self.subTest(doc=rel):
                result = self._run(bootstrap_block(rel), bin_dir)
                self.assertNotIn("command not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/tests/test_bootstrap_guard.py -v`
Expected: both FAIL for all three docs — stderr is `bash: line 1: python3: command not found`.

- [ ] **Step 3: Add the guard to all three docs**

In each of the three files, insert these lines immediately **before** the `PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '` line, inside the same ` ```bash ` block:

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
```

Leave everything after it unchanged.

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m pytest skills/tests/test_bootstrap_guard.py -v`
Expected: 2 passed.

- [ ] **Step 5: Confirm the docs still describe reality**

Run: `python3 -m pytest skills/tests/ skills/annotate/tests/test_skill_structure.py -v`
Expected: all passing. The structure guards parse these same blocks, so a malformed edit shows up here.

- [ ] **Step 6: Run the full suite and commit**

Run: `python3 -m pytest skills -q`
Expected: previous count + 2.

```bash
git add skills/annotate/references/pushing.md skills/walkthrough/SKILL.md skills/interactive_review/SKILL.md skills/tests/test_bootstrap_guard.py
git commit -m "fix(skills): guard the plugin-root bootstrap against a missing python3

The bootstrap runs before ensure_server.sh, so its raw 'command not found'
was the first thing a user without Python saw. It now stops with a message
naming the plugin, the requirement and the remedy. The test executes the
shipped block rather than asserting on its text."
```

---

### Task 6: State the requirement where people read it

The root cause: the word "Python" appears nowhere in the README or in either marketplace description, so a user cannot know before installing or diagnose after.

**Files:**
- Modify: `README.md` (insert a section before `## Install` at line 8)
- Modify: `.claude-plugin/marketplace.json` (both `description` fields)
- Create: `skills/tests/test_requirements_documented.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `skills/tests/test_requirements_documented.py`:

```python
"""The requirement must be stated before someone installs, not after.

A user with no python3 had no way to know the plugin needed it: the word
does not appear in the README or in either marketplace description.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_states_requirements_before_install():
    text = ROOT / "README.md"
    body = text.read_text(encoding="utf-8")
    assert "## Requirements" in body, "README needs a Requirements section"
    assert body.index("## Requirements") < body.index("## Install"), \
        "requirements must appear before install instructions"
    section = body[body.index("## Requirements"):body.index("## Install")]
    for token in ("python3", "3.9", "bash", "curl"):
        assert token in section, f"Requirements section must mention {token!r}"
    assert "pip install" in section, \
        "say there is nothing to pip install — it is the question everyone asks"


def test_both_plugin_descriptions_name_the_python_requirement():
    plugins = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )["plugins"]
    for plugin in plugins:
        assert "Python 3.9" in plugin["description"], \
            f"{plugin['name']} description must state the Python requirement"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest skills/tests/test_requirements_documented.py -v`
Expected: both FAIL — no Requirements section, no Python in descriptions.

- [ ] **Step 3: Add the README section**

Insert into `README.md` immediately before `## Install` (currently line 8):

```markdown
## Requirements

- **`python3` on your `PATH`, version 3.9 or newer.** Standard library only —
  there is nothing to `pip install`.
- **`bash` and `curl`** (both ship with macOS and every mainstream Linux).
- **macOS or Linux.** Windows is not supported.
- `claude-ide-review` additionally needs the IntelliJ plugin — see below.

On a fresh Mac without the Xcode Command Line Tools there is no `python3` at
all; `xcode-select --install` or `brew install python` provides one. If
anything misbehaves after installing, run `/annotate-doctor` for a check of
your machine.
```

- [ ] **Step 4: Update both marketplace descriptions**

In `.claude-plugin/marketplace.json`, append to each `description`:

For `claude-annotate`:
```
Read Claude's long answers in a browser and comment on any block; Claude rewrites that block in place. Requires Python 3.9+ on PATH (standard library only, nothing to install).
```

For `claude-ide-review`:
```
Ask Claude questions on a PR diff line or a code walkthrough step, inside IntelliJ. Requires Python 3.9+ on PATH (standard library only, nothing to install) and the companion IntelliJ plugin.
```

- [ ] **Step 5: Run it to verify it passes**

Run: `python3 -m pytest skills/tests/test_requirements_documented.py -v`
Expected: 2 passed.

- [ ] **Step 6: Run the full suite and commit**

Run: `python3 -m pytest skills -q`
Expected: previous count + 2.

```bash
git add README.md .claude-plugin/marketplace.json skills/tests/test_requirements_documented.py
git commit -m "docs: state the Python requirement before the install step

The word Python appeared nowhere in the README or either marketplace
description, so a user could not know the plugin needed it before installing
or diagnose it after. Both descriptions now say so at install time."
```

---

### Task 7: Verify the declared floor in CI

The plan declares 3.9 in four places. CI tests 3.12 only, so that number is currently a claim.

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Add 3.9 to the matrix**

Replace the `pytest` job in `.github/workflows/ci.yml`:

```yaml
jobs:
  pytest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        # 3.9 is the declared floor (Path.is_relative_to in uploads.py).
        # It is in the matrix so the number in the README stays true.
        python-version: ['3.9', '3.12']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install pytest
      - run: python3 -m pytest skills -q
```

- [ ] **Step 2: Check locally if a 3.9 is available**

Run: `command -v python3.9 && python3.9 -m pytest skills -q || echo "no local 3.9 — CI verifies this"`

If 3.9 exists locally and the suite fails, do not proceed to the commit: the failure tells us the declared floor is wrong. Raise the declared number to the lowest version that passes, and update it in all four places — `README.md`, both marketplace descriptions, `ensure_server.sh`'s preflight, and `doctor.sh`.

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: test the declared 3.9 floor, not just 3.12

The README, both marketplace descriptions, the launcher preflight and the
doctor all state 3.9. Nothing verified it."
git push
```

- [ ] **Step 4: Watch the CI run**

Run: `gh run watch` (or `gh run list --limit 3`)

Expected: both matrix legs green. If the 3.9 leg fails, that is the real answer about our floor — fix the declared version everywhere rather than dropping 3.9 from the matrix.

---

### Task 8: End-to-end check on a simulated broken machine

Every prior task tested its own layer. This one asks the question the reporting user actually asked: what does a person with no Python see?

**Files:**
- Create: `skills/tests/test_broken_machine_e2e.py`

**Interfaces:**
- Consumes: `sanitized_path_dir`, `hook_command`, `hook_env` from Task 1.
- Produces: nothing.

- [ ] **Step 1: Write the test**

Create `skills/tests/test_broken_machine_e2e.py`:

```python
"""What a machine with no python3 actually experiences, end to end.

One test per thing the reporting user hit, so a regression in any single
layer is legible without reading four other files.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import (
    BASH, REPO_ROOT, hook_command, hook_env, sanitized_path_dir,
)

PAYLOAD = json.dumps({"tool_name": "Bash", "session_id": "sess-1"})


class BrokenMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="broken-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = sanitized_path_dir(self.tmp, with_python=False)

    def test_a_hundred_tool_calls_produce_no_output_at_all(self):
        # The reported symptom: one red line per tool call, forever.
        env = hook_env(self.home, self.bin)
        for _ in range(100):
            result = subprocess.run(
                [BASH, "-c", hook_command()],
                input=PAYLOAD, capture_output=True, text=True, timeout=10, env=env,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout + result.stderr, "")

    def test_the_doctor_still_runs_and_explains(self):
        doctor = REPO_ROOT / "skills" / "_shared" / "web_companion" / "doctor.sh"
        result = subprocess.run(
            [str(self.bin / "sh"), str(doctor)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.home), "PATH": str(self.bin)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python3", result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("xcode-select --install", result.stdout)

    def test_launching_a_skill_names_the_plugin_once(self):
        script = REPO_ROOT / "skills" / "annotate" / "ensure_server.sh"
        result = subprocess.run(
            [str(self.bin / "bash"), str(script)],
            capture_output=True, text=True, timeout=20,
            env={"HOME": str(self.home), "PATH": str(self.bin)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.count("claude-annotate:"), 1,
                         "say it once, not once per layer")
        self.assertIn("/annotate-doctor", result.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest skills/tests/test_broken_machine_e2e.py -v`
Expected: 3 passed. If `test_launching_a_skill_names_the_plugin_once` fails on the count, two layers are both speaking — keep the message in `ensure_server.sh` and make the inner one silent.

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest skills -q`
Expected: previous count + 3, all passing.

- [ ] **Step 4: Verify on the committed tree**

A dirty working tree can hide an unstaged file that the suite depends on.

```bash
git add -A && git status --porcelain && python3 -m pytest skills -q
```

Expected: the status list contains only the files this task created, and the suite is green.

- [ ] **Step 5: Commit**

```bash
git commit -m "test: end-to-end behaviour on a machine with no python3

100 tool calls produce no output, the doctor still runs and explains, and
launching a skill names the plugin exactly once."
```

---

## Acceptance

| Claim | Verified by | Expected |
|---|---|---|
| The hook is silent without `python3` | Task 1 / Task 8 | exit 0, empty stdout and stderr, 100 times |
| The hook spawns nothing when unused | Task 1 spy interpreter | marker file absent |
| The hook still receives its stdin payload | Task 1 | `progress_publish.py` runs clean |
| The launcher names the plugin and the fix | Task 2 | stderr has `claude-annotate`, `python3`, `3.9`, a remedy |
| The doctor runs where nothing works | Task 3 / Task 8 | non-zero exit, report printed, remedy shown |
| The doctor contains no Python and no `jq` | Task 3 | source scan |
| The doctor changes nothing | Task 3 | `$HOME` contents identical before and after |
| The bootstrap speaks before Claude improvises | Task 5 | all three shipped blocks, executed |
| The requirement is stated before install | Task 6 | README section and both descriptions |
| The 3.9 floor is real | Task 7 | CI matrix leg green |
| Nothing else broke | every task | `python3 -m pytest skills -q` |

## Out of scope

- Windows and WSL support
- Probing for interpreters other than `python3`
- Any dependency installation or `PATH` modification
- IntelliJ-side diagnosis
- Reducing the Python dependency itself
