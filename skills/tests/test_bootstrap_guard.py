"""Every skill doc that runs python3 must fail with a named message, not a trace.

The bootstrap resolves PLUGIN_ROOT with python3 and runs before
ensure_server.sh, so it is the first thing to break on a machine with no
interpreter. These tests execute the block exactly as shipped.

The list of docs is **derived, never hand-maintained**. It used to be three
literal paths, and that is precisely how `references/resuming.md` shipped
unguarded: `/annotate resume` is routed straight there by SKILL.md, so it
never touches `references/pushing.md` or `ensure_server.sh`, and no test
looked at it. Anything the scanner below finds is checked, so a new doc — or
a new first-block snippet in an existing doc — is covered the day it lands.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

# ---------------------------------------------------------------------------
# Deriving the docs to check
# ---------------------------------------------------------------------------

# Fenced shell blocks. Only ```bash / ```sh — an untagged fence is prose or a
# transcript, never something Claude is told to execute.
FENCE_RE = re.compile(r"^```(?:bash|sh)\n(.*?)^```", re.DOTALL | re.MULTILINE)

# Heredoc bodies are payload, not code: the guard's own message contains the
# words "python3" and "install python3 with ...". Strip them before deciding
# whether a block *invokes* the interpreter, so prose can never be mistaken
# for a call (or hide one).
HEREDOC_RE = re.compile(r"<<-?\s*'?(\w+)'?\n.*?^\1$", re.DOTALL | re.MULTILINE)

# python3 used as a command: `python3 -c`, `python3 -m`, `$(python3 -c`,
# `python3 - "$REG"`. The guard itself (`command -v python3 >/dev/null`) does
# not match, because `>` is not a flag or word character.
INVOKE_RE = re.compile(r"(?:^|[\s(`$])python3\s+[-\w]")

# The guard, and the exit that must follow it.
GUARD_RE = re.compile(r"command -v python3\b")
EXIT_RE = re.compile(r"^\s*exit 1\s*$", re.MULTILINE)

# Blocks that mention python3 but are NOT a skill's runtime path — a developer
# typing into their own terminal in a repo checkout. Claude never executes
# these during a skill invocation, so a guard there would be noise, and the
# person running them already has a checkout and a shell.
#
# Keyed by (doc, first line of the block) on purpose: adding a *different*
# block to one of these files does not inherit the exemption.
ALLOWED_BLOCKS = {
    # Running the walkthrough suite from a repo clone — a contributor
    # instruction in a README, not a step of /walkthrough.
    (
        "skills/walkthrough/README.md",
        "python3 -m pytest skills/walkthrough/tests/ -v",
    ),
    # Same case for the deck skill.
    (
        "skills/deck/README.md",
        "python3 -m pytest skills/deck/tests/ -v",
    ),
    # Same case for the dataflow skill.
    (
        "skills/dataflow/README.md",
        "python3 -m pytest skills/dataflow/tests/ -v",
    ),
}

# Scanner-health canary. Not the source of truth (the scan is), but if a fence
# convention changes and the regexes silently stop matching, this fails loudly
# instead of the suite going green over zero docs.
KNOWN_ENTRY_DOCS = {
    "skills/annotate/references/pushing.md",
    "skills/annotate/references/resuming.md",
    "skills/annotate/references/code-anchors.md",
    "skills/ask_diff/SKILL.md",
    "skills/walkthrough/SKILL.md",
}


def _code(block: str) -> str:
    """The block with heredoc payloads removed."""
    return HEREDOC_RE.sub("", block)


def invoking_blocks() -> list[tuple[str, str]]:
    """(doc, block) for every fenced shell block that runs python3."""
    found = []
    for path in sorted(REPO_ROOT.glob("skills/**/*.md")):
        rel = str(path.relative_to(REPO_ROOT))
        for block in FENCE_RE.findall(path.read_text(encoding="utf-8")):
            if not INVOKE_RE.search(_code(block)):
                continue
            first = block.strip().splitlines()[0].strip()
            if (rel, first) in ALLOWED_BLOCKS:
                continue
            found.append((rel, block))
    return found


def entry_blocks() -> list[tuple[str, str]]:
    """The first python3-invoking block of each doc — the one that must guard.

    Every later block in the same doc runs only after this one has succeeded:
    a doc's blocks are executed in order, and the guard's contract is that
    Claude surfaces the stderr and stops. So the doc's *entry* is where the
    check has to be, and where a missing check is a live bug.
    """
    first_per_doc: dict[str, str] = {}
    for rel, block in invoking_blocks():
        first_per_doc.setdefault(rel, block)
    return sorted(first_per_doc.items())


def is_guarded(block: str) -> bool:
    """A `command -v python3` check that exits before the first python3 call."""
    code = _code(block)
    guard = GUARD_RE.search(code)
    invoke = INVOKE_RE.search(code)
    if not guard or not invoke:
        return False
    if guard.start() >= invoke.start():
        return False
    exit_ = EXIT_RE.search(code, guard.end())
    return bool(exit_) and exit_.start() < invoke.start()


class ScannerHealthTests(unittest.TestCase):
    """The derived list must actually derive something."""

    def test_the_scan_finds_every_doc_we_know_runs_python(self):
        docs = {rel for rel, _ in entry_blocks()}
        missing = KNOWN_ENTRY_DOCS - docs
        self.assertFalse(
            missing,
            f"the block scanner stopped seeing known runtime docs: {missing}",
        )

    def test_the_allowlist_still_matches_something(self):
        # A stale exemption is worse than none: it reads as a considered
        # decision while silently covering nothing.
        for rel, first in ALLOWED_BLOCKS:
            with self.subTest(doc=rel):
                text = (REPO_ROOT / rel).read_text(encoding="utf-8")
                blocks = [b.strip().splitlines()[0].strip()
                          for b in FENCE_RE.findall(text)]
                self.assertIn(first, blocks,
                              f"allowlisted block no longer exists in {rel}")


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
            # LC_ALL/LANG pinned to C so bash's own diagnostics (e.g. "command
            # not found") are always English — otherwise this test's meaning
            # depends on the developer's locale instead of the guard.
            env={"HOME": str(self.home), "PATH": str(bin_dir),
                 "LC_ALL": "C", "LANG": "C"},
        )

    def test_every_entry_block_is_guarded(self):
        # Static: the check exists and precedes the first call. This is the
        # one that fails the day someone adds an unguarded snippet.
        for rel, block in entry_blocks():
            with self.subTest(doc=rel):
                self.assertTrue(
                    is_guarded(block),
                    f"{rel}: the first python3 block has no `command -v python3` "
                    f"guard that exits before the call",
                )

    def test_each_bootstrap_names_the_plugin_and_the_fix(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        for rel, block in entry_blocks():
            with self.subTest(doc=rel):
                result = self._run(block, bin_dir)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("claude-annotate", result.stderr)
                self.assertIn("python3", result.stderr)
                self.assertIn("/annotate-doctor", result.stderr)
                # The prefix is the marketplace, which ships two plugins. A
                # claude-ide-review user reading "claude-annotate:" otherwise
                # sees the name of something they never installed.
                self.assertIn("marketplace", result.stderr)
                self.assertIn("claude-ide-review", result.stderr)

    def test_no_raw_command_not_found_reaches_the_user(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        for rel, block in entry_blocks():
            with self.subTest(doc=rel):
                result = self._run(block, bin_dir)
                self.assertNotIn("command not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
