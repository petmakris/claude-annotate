# Code Anchors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an annotate block carry `{file, line, snippet}` anchors so the page renders the real source beside the prose that explains it.

**Architecture:** Blocks carry anchors, never code text. A new pure-Python module `skills/annotate/anchors.py` resolves each anchor against the workspace's stored repo root (`dirs["_cwd"]`), confines it inside that root, reads the window, and reports drift. `server._render_block_for_raw` calls it and inlines the resolved lines into the block payload the client already fetches, so screen, export and shared link all read from one path. The client paints the payload into a second column of the card.

**Tech Stack:** Python 3.9+ standard library only (no dependencies). Vanilla JS + CSS on the client. `unittest` via pytest. Playwright for `.cjs` end-to-end tests.

**Spec:** `docs/superpowers/specs/2026-08-20-code-anchors-design.md`

## Global Constraints

- **Python floor is 3.9.** CI matrix is `['3.9', '3.12']` (`.github/workflows/ci.yml`). `Path.is_relative_to` is 3.9+ and already used in `skills/_shared/web_companion/uploads.py:76` — it is allowed. `X | Y` type syntax at runtime is not; every new module starts with `from __future__ import annotations`.
- **Standard library only.** No new dependencies, ever. The README's install story is "nothing to pip install".
- **Test command:** `python3 -m pytest skills -q` from the repo root.
- **Branch:** `feat/code-anchors`. Do not merge to `main`; this is expected to iterate.
- **A malformed block must never blank the page.** Every anchor failure renders a visible marker and `/raw` still returns 200. This matches the existing `sequence`/`flowchart`/`diagram` branches at `skills/annotate/server.py:823-912`.
- **Limits, copied verbatim from the spec:** `MAX_ANCHORS = 3`, `MAX_WINDOW = 40` lines, `CONTEXT_LINES = 2` either side, `DRIFT_RADIUS = 40` lines.
- **Anchor statuses, exact strings:** `"ok"`, `"moved"`, `"stale"`, `"missing"`, `"refused"`.
- **Line roles, exact strings:** `"anchor"`, `"window"`, `"context"`.

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `skills/annotate/anchors.py` | The whole anchor model: validation (no I/O), path confinement, file reading, drift detection. One module because these change together and a caller wants all of it. |
| `skills/annotate/check_anchors.py` | `python -m` entry point for the push-time check. Separate from `anchors.py` because it is a CLI concern (argv, stderr, exit codes), not model logic. |
| `skills/annotate/references/code-anchors.md` | The authoring contract, loaded only when anchors are being written. |
| `skills/annotate/tests/test_anchors.py` | Validation, confinement, reading, drift. |
| `skills/annotate/tests/test_check_anchors.py` | The CLI's exit codes and messages. |
| `skills/annotate/tests/test_server_anchors.py` | `/raw` wiring, including that a bad anchor still returns 200. |
| `skills/annotate/tests/e2e/code-anchors.e2e.cjs` | Split card renders, `widen` promotes and persists, export carries the code. |

**Modify**

| File | Change |
|---|---|
| `skills/annotate/versions.py:63` | `_block_hash` folds in `code` — otherwise editing an anchor never bumps the version and the client never refetches. |
| `skills/annotate/server.py:473,479,801` | `_render_block_for_raw` gains a `repo_root` parameter; both callers pass `dirs.get("_cwd")`. |
| `skills/annotate/static/script.js` | Render code panes; promotion toggle and persistence. |
| `skills/annotate/static/style.css` | Split card, pane chrome, promotion, conditional column width. |
| `skills/annotate/SKILL.md` | The anchoring rule in the block-kind menu. |
| `skills/annotate/references/pushing.md` | Pointer to `references/code-anchors.md`. |

---

### Task 1: Anchor validation (no I/O)

Pure shape checking, so it can run in the push-time check without touching the filesystem.

**Files:**
- Create: `skills/annotate/anchors.py`
- Test: `skills/annotate/tests/test_anchors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MAX_ANCHORS: int = 3`, `MAX_WINDOW: int = 40`, `CONTEXT_LINES: int = 2`, `DRIFT_RADIUS: int = 40`
  - `anchor_problem(a: dict) -> str | None` — one anchor's shape problem, or None.
  - `block_problems(blk: dict) -> list[str]` — every problem with a block's `code` field, each prefixed `code[i]: ` where an index applies. Empty list means valid.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_anchors.py`:

```python
import unittest

from skills.annotate import anchors


def _ok(**over):
    a = {"file": "skills/annotate/server.py", "line": 801,
         "snippet": "def _render_block_for_raw(blk: dict, version: int) -> dict:"}
    a.update(over)
    return a


class TestAnchorProblem(unittest.TestCase):
    def test_valid_anchor_has_no_problem(self):
        self.assertIsNone(anchors.anchor_problem(_ok()))

    def test_valid_anchor_with_optionals(self):
        self.assertIsNone(anchors.anchor_problem(_ok(end_line=812, note="the dispatch point")))

    def test_not_a_dict(self):
        self.assertIn("object", anchors.anchor_problem("nope"))

    def test_missing_file(self):
        a = _ok()
        del a["file"]
        self.assertIn("file", anchors.anchor_problem(a))

    def test_absolute_file_is_refused(self):
        self.assertIn("relative", anchors.anchor_problem(_ok(file="/etc/passwd")))

    def test_line_must_be_positive_int(self):
        self.assertIn("line", anchors.anchor_problem(_ok(line=0)))
        self.assertIn("line", anchors.anchor_problem(_ok(line="801")))

    def test_bool_is_not_a_line_number(self):
        # bool is an int subclass; True must not sail through as line 1.
        self.assertIn("line", anchors.anchor_problem(_ok(line=True)))

    def test_end_line_must_not_precede_line(self):
        self.assertIn("end_line", anchors.anchor_problem(_ok(end_line=800)))

    def test_end_line_equal_to_line_is_fine(self):
        self.assertIsNone(anchors.anchor_problem(_ok(end_line=801)))

    def test_snippet_must_be_non_empty(self):
        self.assertIn("snippet", anchors.anchor_problem(_ok(snippet="   ")))


class TestBlockProblems(unittest.TestCase):
    def test_no_code_field_is_valid(self):
        self.assertEqual(anchors.block_problems({"id": "section-1"}), [])

    def test_empty_list_is_valid(self):
        self.assertEqual(anchors.block_problems({"id": "section-1", "code": []}), [])

    def test_code_must_be_a_list(self):
        problems = anchors.block_problems({"id": "section-1", "code": {}})
        self.assertEqual(len(problems), 1)
        self.assertIn("list", problems[0])

    def test_fourth_anchor_is_a_failure_not_a_silent_drop(self):
        blk = {"id": "section-1", "code": [_ok(), _ok(), _ok(), _ok()]}
        problems = anchors.block_problems(blk)
        self.assertTrue(any("at most 3" in p for p in problems))

    def test_mockup_takes_no_anchors(self):
        blk = {"id": "section-1", "kind": "mockup", "code": [_ok()]}
        problems = anchors.block_problems(blk)
        self.assertTrue(any("mockup" in p for p in problems))

    def test_problem_is_indexed(self):
        blk = {"id": "section-1", "code": [_ok(), _ok(line=0)]}
        problems = anchors.block_problems(blk)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("code[1]: "))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.anchors'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/annotate/anchors.py`:

```python
"""Code anchors — resolving a block's {file, line, snippet} to real source.

A block may carry a `code` list; each entry names a file and a line in the
workspace's repo, and the server reads that file at render time. The block
never carries code text, which is what makes an anchor cheap enough to write
generously and impossible to leave stale relative to the working tree.

Two rules shape everything in here:

  * `file` is untrusted. Anchors are model-authored, so every path is
    resolved and then required to stay under the workspace root. Without that
    check a block could name ../../.ssh/id_rsa and the page would print it to
    anyone holding the read-only share link.

  * A failure is a marker, never an exception. One bad anchor must not blank
    the page — the same rule the sequence/flowchart/diagram branches of
    server._render_block_for_raw already follow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# Limits, from docs/superpowers/specs/2026-08-20-code-anchors-design.md.
MAX_ANCHORS = 3        # past three, the block is a tour — use /walkthrough
MAX_WINDOW = 40        # a pane you must scroll has stopped being a glance
CONTEXT_LINES = 2      # dimmed lines either side, so a line has a home
DRIFT_RADIUS = 40      # how far to hunt for a snippet that moved


def _is_int(v: Any) -> bool:
    """bool is an int subclass; True must not pass as line 1."""
    return isinstance(v, int) and not isinstance(v, bool)


def anchor_problem(a: Any) -> Optional[str]:
    """Return one human-readable problem with this anchor, or None."""
    if not isinstance(a, dict):
        return "must be an object"

    f = a.get("file")
    if not isinstance(f, str) or not f.strip():
        return "file must be a non-empty string"
    if Path(f).is_absolute():
        return "file must be relative to the repository root"

    line = a.get("line")
    if not _is_int(line) or line < 1:
        return "line must be a positive integer"

    end_line = a.get("end_line")
    if end_line is not None:
        if not _is_int(end_line) or end_line < 1:
            return "end_line must be a positive integer"
        if end_line < line:
            return "end_line must not precede line"

    snippet = a.get("snippet")
    if not isinstance(snippet, str) or not snippet.strip():
        return "snippet must be non-empty (it is what survives the file moving)"

    note = a.get("note")
    if note is not None and not isinstance(note, str):
        return "note must be a string"

    return None


def block_problems(blk: dict) -> list:
    """Return every problem with a block's `code` field; empty means valid."""
    code = blk.get("code")
    if code is None:
        return []
    if not isinstance(code, list):
        return ["code must be a list of anchors"]
    if not code:
        return []

    problems = []
    if (blk.get("kind") or "markdown") == "mockup":
        problems.append(
            "a mockup block takes no anchors — its sandboxed iframe has "
            "nowhere to put a pane"
        )
    if len(code) > MAX_ANCHORS:
        problems.append(
            "at most %d anchors per block (found %d) — past that the block "
            "is a tour, and the right answer is /walkthrough"
            % (MAX_ANCHORS, len(code))
        )
    for i, a in enumerate(code):
        p = anchor_problem(a)
        if p:
            problems.append("code[%d]: %s" % (i, p))
    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q`
Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/anchors.py skills/annotate/tests/test_anchors.py
git commit -m "feat(anchors): validate a block's code anchors

Shape, the three-anchor cap, end_line ordering, and the rule that a
mockup block takes none. A fourth anchor is a failure rather than a
silent drop: a citation quietly discarded is one the reader never
learns was meant to be there."
```

---

### Task 2: Path confinement and reading the window

**Files:**
- Modify: `skills/annotate/anchors.py`
- Test: `skills/annotate/tests/test_anchors.py`

**Interfaces:**
- Consumes: Task 1's constants and `anchor_problem`.
- Produces: `resolve_anchor(a: dict, root) -> dict`. Returns a payload dict:

  ```python
  {"file": "skills/annotate/server.py",
   "line": 801,            # as authored
   "actual_line": 801,     # where the snippet really is
   "status": "ok",         # ok|moved|stale|missing|refused
   "note": "…",            # only when the anchor carried one
   "message": "…",         # only when status != "ok"
   "truncated": 12,        # only when the window was cut
   "lines": [{"n": 799, "text": "…", "role": "context"}, …]}
  ```

  `lines` is absent on a failing status. `role` is `"anchor"` for `actual_line`, `"window"` for the authored span, `"context"` for the dimmed padding.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_anchors.py`:

```python
import os
import tempfile
from pathlib import Path


class AnchorFixture(unittest.TestCase):
    """A throwaway repo with one known file, so line numbers are ours."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "mod.py").write_text(
            "\n".join([
                "import os",            # 1
                "",                     # 2
                "",                     # 3
                "def alpha():",         # 4
                "    return 1",         # 5
                "",                     # 6
                "",                     # 7
                "def beta():",          # 8
                "    return 2",         # 9
                "",                     # 10
            ]) + "\n"
        )
        self.addCleanup(self.tmp.cleanup)

    def anchor(self, **over):
        a = {"file": "pkg/mod.py", "line": 8, "snippet": "def beta():"}
        a.update(over)
        return a


class TestResolveConfinement(AnchorFixture):
    def test_escaping_the_root_is_refused(self):
        out = anchors.resolve_anchor(self.anchor(file="../outside.py"), self.root)
        self.assertEqual(out["status"], "refused")
        self.assertIn("outside the workspace", out["message"])
        self.assertNotIn("lines", out)

    def test_symlink_escaping_the_root_is_refused(self):
        outside = Path(self.tmp.name).parent / "escape-target.py"
        outside.write_text("SECRET\n")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        os.symlink(outside, self.root / "link.py")
        out = anchors.resolve_anchor(
            self.anchor(file="link.py", line=1, snippet="SECRET"), self.root)
        self.assertEqual(out["status"], "refused")

    def test_missing_file(self):
        out = anchors.resolve_anchor(self.anchor(file="pkg/gone.py"), self.root)
        self.assertEqual(out["status"], "missing")
        self.assertIn("pkg/gone.py", out["message"])


class TestResolveWindow(AnchorFixture):
    def test_single_line_anchor_carries_context_either_side(self):
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["actual_line"], 8)
        self.assertEqual([l["n"] for l in out["lines"]], [6, 7, 8, 9, 10])

    def test_the_anchor_line_is_marked(self):
        out = anchors.resolve_anchor(self.anchor(), self.root)
        roles = {l["n"]: l["role"] for l in out["lines"]}
        self.assertEqual(roles[8], "anchor")
        self.assertEqual(roles[6], "context")
        self.assertEqual(roles[10], "context")

    def test_end_line_widens_the_window(self):
        out = anchors.resolve_anchor(self.anchor(end_line=9), self.root)
        roles = {l["n"]: l["role"] for l in out["lines"]}
        self.assertEqual(roles[9], "window")

    def test_context_clamps_at_the_start_of_file(self):
        out = anchors.resolve_anchor(
            self.anchor(line=1, snippet="import os"), self.root)
        self.assertEqual(out["lines"][0]["n"], 1)

    def test_text_is_verbatim(self):
        out = anchors.resolve_anchor(self.anchor(line=9, snippet="return 2"), self.root)
        got = {l["n"]: l["text"] for l in out["lines"]}
        self.assertEqual(got[9], "    return 2")

    def test_note_is_passed_through(self):
        out = anchors.resolve_anchor(self.anchor(note="the second one"), self.root)
        self.assertEqual(out["note"], "the second one")

    def test_oversized_window_is_truncated_with_a_count(self):
        big = self.root / "big.py"
        big.write_text("\n".join("x = %d" % i for i in range(1, 101)) + "\n")
        out = anchors.resolve_anchor(
            {"file": "big.py", "line": 1, "end_line": 100, "snippet": "x = 1"},
            self.root)
        self.assertEqual(out["status"], "ok")
        window = [l for l in out["lines"] if l["role"] in ("anchor", "window")]
        self.assertEqual(len(window), anchors.MAX_WINDOW)
        self.assertEqual(out["truncated"], 100 - anchors.MAX_WINDOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q`
Expected: FAIL — `AttributeError: module 'skills.annotate.anchors' has no attribute 'resolve_anchor'`

- [ ] **Step 3: Write minimal implementation**

Append to `skills/annotate/anchors.py`:

```python
def _fail(a: dict, status: str, message: str) -> dict:
    """A failing anchor still names itself, so the pane can say what is lost."""
    out = {
        "file": a.get("file") if isinstance(a.get("file"), str) else "",
        "line": a.get("line") if _is_int(a.get("line")) else 0,
        "status": status,
        "message": message,
    }
    if isinstance(a.get("note"), str):
        out["note"] = a["note"]
    return out


def _read_lines(path: Path) -> list:
    """File as a list of lines, newline stripped. Undecodable bytes replaced
    rather than raising: a pane showing a mojibake line is still better than
    a block that failed to render."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    # A trailing newline yields a final empty element that is not a line.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def resolve_anchor(a: dict, root) -> dict:
    """Read the source an anchor names. Never raises; failures are statuses."""
    problem = anchor_problem(a)
    if problem:
        return _fail(a if isinstance(a, dict) else {}, "refused", problem)

    rel = a["file"]
    try:
        root_real = Path(root).resolve()
        target = (root_real / rel).resolve()
    except (OSError, ValueError) as e:
        return _fail(a, "refused", "%s: path could not be resolved (%s)" % (rel, e))

    # resolve() follows symlinks BEFORE this test, which is the point: a link
    # inside the repo pointing out of it must not smuggle a file through.
    if not target.is_relative_to(root_real):
        return _fail(a, "refused", "%s: resolves outside the workspace" % rel)
    if not target.is_file():
        return _fail(a, "missing", "%s: no such file in the workspace" % rel)

    try:
        lines = _read_lines(target)
    except OSError as e:
        return _fail(a, "missing", "%s: could not be read (%s)" % (rel, e))

    return _build(a, lines)


def _build(a: dict, lines: list) -> dict:
    """Locate the anchor in `lines` and lay out the window around it."""
    authored = a["line"]
    actual = _locate(lines, a["snippet"], authored)
    if actual is None:
        return _fail(
            a, "stale",
            "%s: the anchored line is no longer at or near line %d "
            "(looked for %r)" % (a["file"], authored, a["snippet"].strip()),
        )

    shift = actual - authored
    end = (a.get("end_line") or authored) + shift
    end = min(end, len(lines))

    truncated = 0
    span = end - actual + 1
    if span > MAX_WINDOW:
        truncated = span - MAX_WINDOW
        end = actual + MAX_WINDOW - 1

    first = max(1, actual - CONTEXT_LINES)
    last = min(len(lines), end + CONTEXT_LINES)

    out_lines = []
    for n in range(first, last + 1):
        if n == actual:
            role = "anchor"
        elif actual <= n <= end:
            role = "window"
        else:
            role = "context"
        out_lines.append({"n": n, "text": lines[n - 1], "role": role})

    out = {
        "file": a["file"],
        "line": authored,
        "actual_line": actual,
        "status": "moved" if shift else "ok",
        "lines": out_lines,
    }
    if shift:
        out["message"] = ("moved: authored at line %d, now at line %d"
                          % (authored, actual))
    if truncated:
        out["truncated"] = truncated
    if isinstance(a.get("note"), str):
        out["note"] = a["note"]
    return out


def _locate(lines: list, snippet: str, authored: int):
    """Line number where `snippet` really is, or None.

    Compared stripped, so re-indenting a line is not treated as drift — it is
    the same line. On several matches take the one nearest the authored line;
    on a tie, the earlier one.
    """
    want = snippet.strip()
    if 1 <= authored <= len(lines) and lines[authored - 1].strip() == want:
        return authored
    candidates = [
        n for n in range(1, len(lines) + 1)
        if abs(n - authored) <= DRIFT_RADIUS and lines[n - 1].strip() == want
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda n: (abs(n - authored), n))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q`
Expected: PASS, 26 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/anchors.py skills/annotate/tests/test_anchors.py
git commit -m "feat(anchors): confine to the workspace and read the window

realpath before the containment test, so a symlink inside the repo
pointing out of it cannot smuggle a file through. Anchors are
model-authored, and this is the check that stops one naming
../../.ssh/id_rsa on a page served over a share link."
```

---

### Task 3: Drift — moved and stale

Task 2 built `_locate`; this task proves the behaviour the whole `snippet` field exists for.

**Files:**
- Test: `skills/annotate/tests/test_anchors.py`

**Interfaces:**
- Consumes: `resolve_anchor` from Task 2.
- Produces: nothing new — this task is the guarantee, not new API.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_anchors.py`:

```python
class TestDrift(AnchorFixture):
    def _rewrite(self, body: str):
        (self.root / "pkg" / "mod.py").write_text(body)

    def test_indentation_change_is_not_drift(self):
        self._rewrite("\n".join([
            "import os", "", "", "def alpha():", "    return 1", "", "",
            "        def beta():",   # line 8, re-indented
            "    return 2", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["actual_line"], 8)

    def test_moved_line_is_found_and_reported(self):
        self._rewrite("\n".join([
            "import os", "", "", "# a new comment", "# and another",
            "def alpha():", "    return 1", "", "",
            "def beta():",   # was 8, now 10
            "    return 2", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "moved")
        self.assertEqual(out["line"], 8)
        self.assertEqual(out["actual_line"], 10)
        self.assertIn("now at line 10", out["message"])

    def test_moved_window_moves_with_it(self):
        self._rewrite("\n".join([
            "import os", "", "", "# a new comment", "# and another",
            "def alpha():", "    return 1", "", "",
            "def beta():", "    return 2", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(end_line=9), self.root)
        roles = {l["n"]: l["role"] for l in out["lines"]}
        # authored span was 8..9; shifted by +2 it is 10..11.
        self.assertEqual(roles[10], "anchor")
        self.assertEqual(roles[11], "window")

    def test_vanished_line_is_stale_and_shows_no_code(self):
        self._rewrite("\n".join([
            "import os", "", "", "def alpha():", "    return 1", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "stale")
        self.assertNotIn("lines", out)
        self.assertIn("def beta():", out["message"])

    def test_stale_rather_than_confidently_wrong(self):
        # The killer case: line 8 still exists and holds something else.
        # Rendering it would be a lie the reader cannot detect.
        self._rewrite("\n".join([
            "import os", "", "", "def alpha():", "    return 1", "", "",
            "def gamma():", "    return 3", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "stale")

    def test_nearest_match_wins_when_the_line_is_duplicated(self):
        body = ["import os", "", "", "def alpha():", "    return 1", "", ""]
        body += ["def beta():", "    return 2"]        # 8, 9
        body += ["x = 0"] * 5                          # 10..14
        body += ["def beta():", "    return 2"]        # 15, 16
        self._rewrite("\n".join(body) + "\n")
        out = anchors.resolve_anchor(self.anchor(line=14), self.root)
        # 15 is one away, 8 is six away.
        self.assertEqual(out["actual_line"], 15)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -k Drift -q`
Expected: PASS if Task 2 was implemented correctly. **If any test here fails, that is a real defect in Task 2's `_locate`/`_build` — fix `anchors.py`, not the test.** Confirm the tests are real by temporarily changing `_locate` to `return authored` and re-running: `test_moved_line_is_found_and_reported` and `test_stale_rather_than_confidently_wrong` must fail. Revert the sabotage before continuing.

- [ ] **Step 3: Run the whole anchors suite**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q`
Expected: PASS, 32 tests.

- [ ] **Step 4: Commit**

```bash
git add skills/annotate/tests/test_anchors.py
git commit -m "test(anchors): drift is found, or admitted — never guessed

The case that matters is a line number that still exists and now holds
something else. Rendering it would be a lie the reader has no way to
detect, so it resolves stale instead."
```

---

### Task 4: Anchors join the version hash

Without this, editing an anchor leaves the block's hash unchanged, the version chain never grows, and the client never refetches — the corrected pane simply does not appear.

**Files:**
- Modify: `skills/annotate/versions.py:63-72`
- Test: `skills/annotate/tests/test_versions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no new API — `_block_hash` behaviour changes.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_versions.py`:

```python
class TestCodeAnchorsAffectVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "versions.json"
        self.addCleanup(self.tmp.cleanup)

    def _blk(self, code=None):
        b = {"id": "section-1", "markdown": "unchanged prose"}
        if code is not None:
            b["code"] = code
        return b

    def test_editing_only_an_anchor_bumps_the_version(self):
        a1 = [{"file": "a.py", "line": 1, "snippet": "x = 1"}]
        a2 = [{"file": "a.py", "line": 2, "snippet": "x = 2"}]
        self.assertEqual(versions.derive_versions(self.path, [self._blk(a1)]),
                         {"section-1": 1})
        self.assertEqual(versions.derive_versions(self.path, [self._blk(a2)]),
                         {"section-1": 2})

    def test_adding_a_first_anchor_bumps_the_version(self):
        self.assertEqual(versions.derive_versions(self.path, [self._blk()]),
                         {"section-1": 1})
        a = [{"file": "a.py", "line": 1, "snippet": "x = 1"}]
        self.assertEqual(versions.derive_versions(self.path, [self._blk(a)]),
                         {"section-1": 2})

    def test_key_order_in_an_anchor_is_not_a_change(self):
        a1 = [{"file": "a.py", "line": 1, "snippet": "x = 1"}]
        a2 = [{"snippet": "x = 1", "line": 1, "file": "a.py"}]
        versions.derive_versions(self.path, [self._blk(a1)])
        self.assertEqual(versions.derive_versions(self.path, [self._blk(a2)]),
                         {"section-1": 1})

    def test_an_anchorless_block_hashes_exactly_as_before(self):
        # Existing workspaces must not have every block jump to v2 on the
        # first read after this change ships.
        self.assertEqual(
            versions._block_hash({"id": "section-1", "markdown": "hello"}),
            versions._block_hash({"id": "section-1", "markdown": "hello",
                                  "code": []}),
        )
```

Ensure `tempfile` and `Path` are imported at the top of the file; add them if the existing imports do not cover it.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_versions.py -k CodeAnchors -q`
Expected: FAIL — `test_editing_only_an_anchor_bumps_the_version` and `test_adding_a_first_anchor_bumps_the_version` both report version 1 where 2 is expected, because `_block_hash` ignores `code`.

- [ ] **Step 3: Write minimal implementation**

In `skills/annotate/versions.py`, replace `_block_hash` (currently at line 63):

```python
def _canonical_code(code: Any) -> str:
    """Stable JSON for a block's anchors — key order is not a content change."""
    return json.dumps(code, sort_keys=True, separators=(",", ":"))


def _block_hash(blk: dict[str, Any]) -> str:
    """SHA1 of (kind, normalized-content, anchors)."""
    kind = blk.get("kind") or "markdown"
    if kind in _SPEC_KINDS:
        body = _canonical_spec(blk.get("spec") or {})
    else:
        body = _normalize_markdown(blk.get("markdown") or "")
    h = hashlib.sha1()
    h.update(kind.encode("utf-8") + b"\x00" + body.encode("utf-8"))
    # Anchors are content: a block whose prose is unchanged but whose citation
    # moved IS a changed block, and without this the chain never grows, the
    # client never refetches, and the corrected pane never appears.
    #
    # Only mixed in when non-empty, so every block in every existing
    # workspace keeps the hash it already has and nothing jumps to v2 on the
    # first read after this ships.
    code = blk.get("code")
    if code:
        h.update(b"\x00" + _canonical_code(code).encode("utf-8"))
    return h.hexdigest()
```

Also update the module docstring's hash description if it names the inputs.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_versions.py -q`
Expected: PASS — the new tests plus every pre-existing versions test.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/versions.py skills/annotate/tests/test_versions.py
git commit -m "fix(versions): a block's anchors are part of its content

_block_hash keyed only on markdown/spec, so editing an anchor left the
hash unchanged, the chain flat, and the client never refetched — the
corrected pane simply would not appear. Mixed in only when non-empty so
existing workspaces keep the hashes they have."
```

---

### Task 5: Server wiring — resolved anchors on the wire

**Files:**
- Modify: `skills/annotate/server.py` (imports; `serve_data` at 473 and 479; `_render_block_for_raw` at 801)
- Test: `skills/annotate/tests/test_server_anchors.py`

**Interfaces:**
- Consumes: `anchors.resolve_anchor` (Task 2).
- Produces: `_render_block_for_raw(blk: dict, version: int, repo_root=None) -> dict`. When the block has anchors and `repo_root` is set, the returned dict carries `"code": [<resolved payload>, …]` using Task 2's shape. Absent otherwise.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_server_anchors.py`:

```python
import tempfile
import unittest
from pathlib import Path

from skills.annotate import server


class TestRenderBlockAnchors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\nb = 2\nc = 3\n")
        self.addCleanup(self.tmp.cleanup)

    def test_block_without_anchors_has_no_code_key(self):
        out = server._render_block_for_raw(
            {"id": "section-1", "markdown": "hi"}, 1, self.root)
        self.assertNotIn("code", out)

    def test_resolved_anchor_carries_the_real_lines(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "mod.py", "line": 2, "snippet": "b = 2"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(len(out["code"]), 1)
        pane = out["code"][0]
        self.assertEqual(pane["status"], "ok")
        texts = [l["text"] for l in pane["lines"]]
        self.assertIn("b = 2", texts)

    def test_a_bad_anchor_is_a_status_not_an_exception(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "../escape.py", "line": 1, "snippet": "x"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(out["code"][0]["status"], "refused")
        # The block itself still rendered.
        self.assertEqual(out["markdown"], "hi")

    def test_anchors_on_a_flowchart_block_still_resolve(self):
        blk = {"id": "section-1", "kind": "flowchart",
               "spec": {"nodes": [], "edges": []},
               "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(out["code"][0]["status"], "ok")

    def test_no_repo_root_means_no_panes_rather_than_a_crash(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}
        out = server._render_block_for_raw(blk, 1, None)
        self.assertNotIn("code", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_server_anchors.py -q`
Expected: FAIL — `_render_block_for_raw() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Write minimal implementation**

In `skills/annotate/server.py`, add to the existing imports:

```python
from skills.annotate import anchors as anchors_module
```

Change the signature and add the anchor block. `_render_block_for_raw` currently begins at line 801:

```python
def _render_block_for_raw(blk: dict, version: int, repo_root=None) -> dict:
```

Immediately before the closing `return base`, add:

```python
    # Code anchors, resolved server-side so the client, the export and the
    # read-only share link all read from one path. Any failure is a status on
    # the pane, never an exception — one bad anchor must not blank the page.
    code = blk.get("code")
    if repo_root and isinstance(code, list) and code:
        base["code"] = [
            anchors_module.resolve_anchor(a, repo_root) for a in code
        ]
```

Then update both callers in `serve_data`. Line 473:

```python
                _send_json(h, 200, _render_block_for_raw(
                    blk, versions.get(bid, 1), dirs.get("_cwd")))
```

Line 479:

```python
                    _render_block_for_raw(b, versions.get(b["id"], 1),
                                          dirs.get("_cwd"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_server_anchors.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full python suite for regressions**

Run: `python3 -m pytest skills -q`
Expected: PASS. `_render_block_for_raw`'s third parameter defaults to `None`, so any existing test calling it with two arguments still works.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/server.py skills/annotate/tests/test_server_anchors.py
git commit -m "feat(server): resolve code anchors into the /raw payload

The repo root comes from the workspace's own dirs['_cwd'], so no new
plumbing. Inlining the resolved lines rather than having the client
fetch them is what makes export and the read-only share link work for
free — export.js snapshots the live DOM."
```

---

### Task 6: The push-time check

A render-time pill tells the reader an anchor is broken; it does not tell the author, who has already ended their turn. This is what makes the rule fail where it can still be fixed.

**Files:**
- Create: `skills/annotate/check_anchors.py`
- Test: `skills/annotate/tests/test_check_anchors.py`

**Interfaces:**
- Consumes: `anchors.block_problems` (Task 1), `anchors.resolve_anchor` (Task 2).
- Produces: `python3 -m skills.annotate.check_anchors <blocks.json> <repo_root>` — exit 0 when every anchor is valid and resolves `ok` or `moved`; exit 1 otherwise, with one line per problem on stderr. Also `check(doc: dict, root) -> list[str]` for direct testing.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_check_anchors.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from skills.annotate import check_anchors

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\nb = 2\n")
        self.addCleanup(self.tmp.cleanup)

    def _doc(self, code):
        return {"response_id": "r", "title": "t",
                "blocks": [{"id": "section-1", "markdown": "hi", "code": code}]}

    def test_good_anchor_reports_nothing(self):
        doc = self._doc([{"file": "mod.py", "line": 1, "snippet": "a = 1"}])
        self.assertEqual(check_anchors.check(doc, self.root), [])

    def test_moved_anchor_is_not_a_failure(self):
        # Moving is handled at render time; it is information, not a defect.
        (self.root / "mod.py").write_text("# new\na = 1\nb = 2\n")
        doc = self._doc([{"file": "mod.py", "line": 1, "snippet": "a = 1"}])
        self.assertEqual(check_anchors.check(doc, self.root), [])

    def test_stale_anchor_is_reported_with_its_block(self):
        doc = self._doc([{"file": "mod.py", "line": 1, "snippet": "gone()"}])
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("section-1", problems[0])

    def test_shape_problem_is_reported(self):
        doc = self._doc([{"file": "mod.py", "line": 0, "snippet": "a = 1"}])
        problems = check_anchors.check(doc, self.root)
        self.assertTrue(any("line" in p for p in problems))

    def test_escape_is_reported(self):
        doc = self._doc([{"file": "../x.py", "line": 1, "snippet": "a"}])
        problems = check_anchors.check(doc, self.root)
        self.assertTrue(any("outside the workspace" in p for p in problems))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\n")
        self.blocks = self.root / "blocks.json"
        self.addCleanup(self.tmp.cleanup)

    def _run(self):
        return subprocess.run(
            [sys.executable, "-m", "skills.annotate.check_anchors",
             str(self.blocks), str(self.root)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )

    def test_exit_zero_when_clean(self):
        self.blocks.write_text(json.dumps({"blocks": [
            {"id": "section-1", "markdown": "hi",
             "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}]}))
        self.assertEqual(self._run().returncode, 0)

    def test_exit_one_and_names_the_block(self):
        self.blocks.write_text(json.dumps({"blocks": [
            {"id": "section-1", "markdown": "hi",
             "code": [{"file": "mod.py", "line": 1, "snippet": "gone()"}]}]}))
        res = self._run()
        self.assertEqual(res.returncode, 1)
        self.assertIn("section-1", res.stderr)

    def test_missing_blocks_file_is_an_error_not_a_pass(self):
        res = self._run()
        self.assertEqual(res.returncode, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_check_anchors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.check_anchors'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/annotate/check_anchors.py`:

```python
"""Push-time anchor check — fail where the author can still fix it.

A broken anchor renders a visible pill on the page, which tells the READER
something is wrong. By then the author has ended their turn. This runs after
blocks.json is written and before the URL is announced, so a bad citation
fails while it is still cheap.

Usage:
    python3 -m skills.annotate.check_anchors <blocks.json> <repo_root>

Exit 0 when every anchor is valid and resolves. Exit 1 otherwise, one
problem per line on stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from skills.annotate import anchors as anchors_module


def check(doc: dict, root) -> list:
    """Return every anchor problem in a blocks document; empty means clean.

    `moved` is not a problem. A line that drifted is still the right line —
    the pane says so and shows it. Only `stale`, `missing` and `refused`
    mean the citation no longer points at anything.
    """
    problems = []
    for blk in (doc.get("blocks") or []):
        if not isinstance(blk, dict):
            continue
        bid = blk.get("id") or "?"
        for p in anchors_module.block_problems(blk):
            problems.append("%s: %s" % (bid, p))
        code = blk.get("code")
        if not isinstance(code, list):
            continue
        for i, a in enumerate(code):
            if anchors_module.anchor_problem(a):
                continue  # already reported by block_problems
            out = anchors_module.resolve_anchor(a, root)
            if out["status"] in ("stale", "missing", "refused"):
                problems.append("%s: code[%d]: %s" % (bid, i, out["message"]))
    return problems


def main(argv: list) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python3 -m skills.annotate.check_anchors "
            "<blocks.json> <repo_root>\n")
        return 1
    blocks_path, root = Path(argv[1]), argv[2]
    try:
        doc = json.loads(blocks_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write("could not read %s: %s\n" % (blocks_path, e))
        return 1
    problems = check(doc, root)
    if not problems:
        return 0
    sys.stderr.write("claude-annotate: %d anchor problem(s)\n" % len(problems))
    for p in problems:
        sys.stderr.write("  %s\n" % p)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_check_anchors.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/check_anchors.py skills/annotate/tests/test_check_anchors.py
git commit -m "feat(anchors): push-time check, before the URL is announced

A render-time pill tells the reader an anchor is broken; by then the
author's turn is over. A drifted line is not a failure here — it still
points at the right code, and the pane says so."
```

---

### Task 7: Pane chrome (CSS)

**Files:**
- Modify: `skills/annotate/static/style.css`
- Test: `skills/annotate/tests/test_smoke_code_panes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the class contract Task 8's JS builds against —
  `.codepane`, `.cp-head`, `.cp-path`, `.cp-jump`, `.cp-body`, `.cp-row`,
  `.cp-num`, `.cp-line`, row modifiers `.cp-row.is-anchor` / `.is-context`,
  `.cp-truncated`, `.cp-status` (with `[data-status]`), `.code-col`,
  `.no-code-slot`, and `section.block.card[data-has-code="1"]`,
  `section.block.card .codepane.is-wide`.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_code_panes.py`. This is a source-presence smoke test in the same style as the repo's other `test_smoke_*.py` files — the pixel behaviour is Task 10's job.

```python
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()


class TestCodePaneCss(unittest.TestCase):
    def test_pane_classes_exist(self):
        for sel in [".codepane", ".cp-head", ".cp-body", ".cp-row",
                    ".cp-num", ".cp-line", ".cp-status"]:
            self.assertIn(sel, CSS, "%s missing from style.css" % sel)

    def test_split_is_gated_on_the_block_having_code(self):
        # An anchorless document must render exactly as annotate does today.
        self.assertIn('[data-has-code="1"]', CSS)

    def test_wide_column_is_gated_too(self):
        # 1180px must not apply to prose-only pages.
        self.assertIn('body[data-has-code="1"]', CSS)
        self.assertIn("1180px", CSS)

    def test_anchor_row_is_distinguished_from_context(self):
        self.assertIn(".cp-row.is-anchor", CSS)
        self.assertIn(".cp-row.is-context", CSS)

    def test_no_code_slot_exists(self):
        self.assertIn(".no-code-slot", CSS)

    def test_read_only_does_not_hide_the_panes(self):
        # Spec decision 3: the shared link serves panes too. A shared page
        # that dropped them would be the detached document this feature
        # exists to eliminate. body.read-only hides controls by CSS, so the
        # pane must not be swept up with them.
        for line in CSS.splitlines():
            if "body.read-only" in line:
                self.assertNotIn(".code-col", line)
                self.assertNotIn(".codepane", line)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_code_panes.py -q`
Expected: FAIL — every assertion, nothing is in `style.css` yet.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/annotate/static/style.css`:

```css
/* === Code anchors ====================================================
   A block that cites code splits its body in two: prose left, the real
   source right. The split is gated on data-has-code so a document with no
   anchors renders exactly as it did before this feature existed — nobody's
   prose-only page gets wider or two-columned because the field now exists.

   The pane is a READING AID. Nothing inside it is a click target, for the
   same reason the flowchart source pane gave that up: a code line painted
   like a jump-to-source link that opens a comment box instead is a lie
   about what a click does. Comments come from the card header. */

/* The wide column, only for documents that actually carry anchors. */
body[data-has-code="1"] { --content-max: 1180px; }

section.block.card[data-has-code="1"] .card-body {
  display: grid;
  grid-template-columns: minmax(0, 46fr) minmax(0, 54fr);
  padding: 0;
}
section.block.card[data-has-code="1"] .card-body > .block-content {
  padding: 2px 18px 16px 18px;
  min-width: 0;
}
.code-col {
  border-left: 1px solid var(--border);
  background: var(--surface-soft);
  padding: 14px 16px 16px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
/* A promoted pane takes the whole card: the grid collapses to one column and
   the prose sits above it. Promotion is per-block and persisted, because a
   widening you must redo on every reload is worse than not having one. */
section.block.card[data-has-code="1"][data-code-wide="1"] .card-body {
  grid-template-columns: minmax(0, 1fr);
}
section.block.card[data-has-code="1"][data-code-wide="1"] .code-col {
  border-left: none;
  border-top: 1px solid var(--border);
}

/* Tokyo Night, matching the fenced-code card the page already paints. */
.codepane {
  background: #1a1b26;
  border-radius: 8px;
  overflow: hidden;
  font-family: 'Monaspace Radon', ui-monospace, SFMono-Regular, Menlo, monospace;
}
.cp-head {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  background: #16171f;
  border-bottom: 1px solid #262838;
  font-size: 11px;
}
.cp-path {
  color: #7aa2f7;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.cp-spacer { flex: 1; }
.cp-jump {
  color: #565f89; font-size: 10.5px; letter-spacing: 0.06em;
  text-transform: uppercase; white-space: nowrap; text-decoration: none;
}
.cp-jump:hover { color: #7aa2f7; }
.cp-widen {
  background: none; border: 1px solid #2f3348; border-radius: 5px;
  color: #565f89; cursor: pointer; padding: 2px 7px;
  font-family: inherit; font-size: 10px;
  letter-spacing: 0.06em; text-transform: uppercase;
}
.cp-widen:hover { color: #7aa2f7; border-color: #7aa2f7; }
.cp-note {
  margin: 0; padding: 6px 12px;
  background: #14151d; border-bottom: 1px solid #262838;
  color: #7f89ad; font-size: 11.5px;
  font-family: 'Bricolage Grotesque', ui-sans-serif, system-ui, sans-serif;
}
.cp-body {
  padding: 9px 0; font-size: 12px; line-height: 1.62;
  overflow-x: auto; color: #9aa5ce;
}
.cp-row { display: flex; min-width: max-content; }
.cp-num {
  flex: none; width: 3.4em; padding-right: 12px;
  text-align: right; color: #3f4459; user-select: none;
}
.cp-line { flex: 1 1 auto; white-space: pre; padding-right: 16px; }
/* The anchored line is the one the prose is about; the padding around it is
   there so the line has a home, not to be read. */
.cp-row.is-anchor { background: rgba(122,162,247,.13); box-shadow: inset 3px 0 0 #7aa2f7; }
.cp-row.is-anchor .cp-num { color: #7aa2f7; }
.cp-row.is-context { opacity: 0.5; }
.cp-truncated {
  padding: 5px 12px 2px calc(3.4em + 12px);
  color: #565f89; font-size: 11px; font-style: italic;
}

/* A pane that could not resolve says so, and shows no code at all. A pane
   rendering whatever now sits at that line number would be a lie the reader
   has no way to detect. */
.cp-status {
  padding: 8px 12px;
  font-family: 'Bricolage Grotesque', ui-sans-serif, system-ui, sans-serif;
  font-size: 11.5px; line-height: 1.5;
}
.cp-status[data-status="moved"] { color: #e0af68; }
.cp-status[data-status="stale"],
.cp-status[data-status="missing"],
.cp-status[data-status="refused"] { color: #f7768e; }

/* The visible half of the authoring rule: in a document that cites code, a
   block that cites none says so where its pane would be. A missing citation
   is then something the reader can point at, not something they endure. */
.no-code-slot {
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  color: var(--text-dim);
  font-size: 12px;
  background: transparent;
}

@media (max-width: 1100px) {
  /* Two columns stop being two columns before they stop being readable. */
  section.block.card[data-has-code="1"] .card-body {
    grid-template-columns: minmax(0, 1fr);
  }
  .code-col { border-left: none; border-top: 1px solid var(--border); }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_code_panes.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/static/style.css skills/annotate/tests/test_smoke_code_panes.py
git commit -m "feat(annotate): code pane and split-card styling

Both the split and the 1180px column are gated on data-has-code, so a
document with no anchors renders exactly as it did before. Nothing in
the pane is a click target — same rule the flowchart source pane
adopted, and for the same reason."
```

---

### Task 8: Render the panes (JS)

**Files:**
- Modify: `skills/annotate/static/script.js`
- Test: `skills/annotate/tests/test_smoke_code_panes.py`

**Interfaces:**
- Consumes: the `code` payload from Task 5; the CSS contract from Task 7.
- Produces: `renderCodeColumn(blk)` returning an `HTMLElement` or `null`; called from `createBlockSection` and from the in-place update path so a rewrite cannot leave a card with stale panes.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_smoke_code_panes.py`:

```python
JS = (Path(__file__).resolve().parents[1] / "static" / "script.js").read_text()


class TestCodePaneJs(unittest.TestCase):
    def test_renderer_exists(self):
        self.assertIn("function renderCodeColumn", JS)

    def test_status_pane_shows_no_lines(self):
        # Guard the rule, not the wording: a failing pane must branch on
        # status before it ever touches `lines`.
        self.assertIn('pane.status !== "ok" && pane.status !== "moved"', JS)

    def test_promotion_is_persisted(self):
        self.assertIn("annotate.codewide:", JS)

    def test_body_flag_is_set_for_the_wide_column(self):
        self.assertIn('dataset.hasCode', JS)

    def test_export_strips_the_widen_control_but_not_the_code(self):
        exp = (Path(__file__).resolve().parents[1] / "static" / "export.js").read_text()
        self.assertIn('".cp-widen"', exp)
        self.assertNotIn('".cp-body"', exp)
        self.assertNotIn('".code-col"', exp)

    def test_update_path_repaints_panes(self):
        # A rewritten block must not keep the previous version's panes.
        self.assertIn("renderCodeColumn", JS.split("function updateBlockContent")[1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_code_panes.py -q`
Expected: FAIL on the `TestCodePaneJs` cases.

- [ ] **Step 3: Write minimal implementation**

In `skills/annotate/static/script.js`, add near `renderPflowSource` (around line 700):

```javascript
  // ── Code anchors ───────────────────────────────────────────────────────────
  // A block's anchors, resolved by the server into real lines. The pane is a
  // reading aid: it links into the IDE and nothing inside it is a click
  // target. Comments come from the card header, the same rule the flowchart
  // source pane adopted after a `ref` that only looked like a link kept
  // opening a comment box for people reaching for a file.

  function codeWideKey(blockId) {
    const rid = (document.body.dataset.responseId || "default");
    return `annotate.codewide:${rid}:${blockId}`;
  }

  function highlightCodeLine(text, file) {
    if (typeof window.hljs !== "object" || !window.hljs) return null;
    const m = /\.([A-Za-z0-9]+)$/.exec(file || "");
    const lang = m && hljs.getLanguage(m[1]) ? m[1] : null;
    try {
      return lang
        ? hljs.highlight(text, { language: lang, ignoreIllegals: true }).value
        : hljs.highlightAuto(text).value;
    } catch (e) {
      return null;
    }
  }

  function renderCodePane(pane, blockId) {
    const wrap = document.createElement("div");
    wrap.className = "codepane";

    const head = document.createElement("div");
    head.className = "cp-head";
    const path = document.createElement("span");
    path.className = "cp-path";
    const shown = pane.actual_line || pane.line;
    path.textContent = shown ? `${pane.file}:${shown}` : (pane.file || "");
    path.title = pane.file || "";
    const spacer = document.createElement("span");
    spacer.className = "cp-spacer";
    head.append(path, spacer);

    if (pane.status === "ok" || pane.status === "moved") {
      const widen = document.createElement("button");
      widen.type = "button";
      widen.className = "cp-widen";
      widen.textContent = "widen";
      widen.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const card = wrap.closest("section.block");
        if (!card) return;
        const next = card.dataset.codeWide === "1" ? "0" : "1";
        card.dataset.codeWide = next;
        widen.textContent = next === "1" ? "narrow" : "widen";
        try { localStorage.setItem(codeWideKey(blockId), next); } catch (_) {}
      });
      head.appendChild(widen);

      const project = document.body.dataset.projectName || "";
      const abs = document.body.dataset.repoRoot || "";
      if (abs) {
        const jump = document.createElement("a");
        jump.className = "cp-jump";
        jump.textContent = "open ↗";
        jump.href = "jetbrains://idea/navigate/reference?project="
          + encodeURIComponent(project)
          + "&path=" + encodeURIComponent(`${abs}/${pane.file}:${shown}`);
        head.appendChild(jump);
      }
    }
    wrap.appendChild(head);

    if (pane.note) {
      const note = document.createElement("p");
      note.className = "cp-note";
      note.textContent = pane.note;
      wrap.appendChild(note);
    }

    // A pane that could not resolve shows its reason and NO code. Rendering
    // whatever now sits at that line number would be a lie the reader has no
    // way to detect.
    if (pane.status !== "ok" && pane.status !== "moved") {
      const status = document.createElement("div");
      status.className = "cp-status";
      status.dataset.status = pane.status;
      status.textContent = pane.message || "this anchor could not be resolved";
      wrap.appendChild(status);
      return wrap;
    }

    if (pane.status === "moved") {
      const status = document.createElement("div");
      status.className = "cp-status";
      status.dataset.status = "moved";
      status.textContent = pane.message || "";
      wrap.appendChild(status);
    }

    const body = document.createElement("div");
    body.className = "cp-body hljs";
    (pane.lines || []).forEach((l) => {
      const row = document.createElement("div");
      row.className = "cp-row";
      if (l.role === "anchor") row.classList.add("is-anchor");
      if (l.role === "context") row.classList.add("is-context");
      const num = document.createElement("span");
      num.className = "cp-num";
      num.setAttribute("aria-hidden", "true");
      num.textContent = String(l.n);
      const text = document.createElement("span");
      text.className = "cp-line";
      const painted = highlightCodeLine(l.text, pane.file);
      if (painted !== null) text.innerHTML = painted;
      else text.textContent = l.text;
      row.append(num, text);
      body.appendChild(row);
    });
    wrap.appendChild(body);

    if (pane.truncated) {
      const cut = document.createElement("div");
      cut.className = "cp-truncated";
      cut.textContent = `… ${pane.truncated} more lines`;
      wrap.appendChild(cut);
    }
    return wrap;
  }

  // The whole right-hand column for one block, or null when the block cites
  // nothing and the document cites nothing either.
  function renderCodeColumn(blk) {
    const panes = Array.isArray(blk.code) ? blk.code : [];
    const docHasCode = document.body.dataset.hasCode === "1";
    if (!panes.length && !docHasCode) return null;

    const col = document.createElement("div");
    col.className = "code-col";
    if (!panes.length) {
      // The visible half of the authoring rule.
      const slot = document.createElement("div");
      slot.className = "no-code-slot";
      slot.textContent = "no code cited";
      col.appendChild(slot);
      return col;
    }
    panes.forEach((p) => col.appendChild(renderCodePane(p, blk.id)));
    return col;
  }

  // Whether ANY block in this document cites code. Drives the wide column and
  // the "no code cited" slots, so both are decisions about the document, not
  // about one block.
  function setDocumentCodeFlag(blocks) {
    const any = (blocks || []).some(
      (b) => Array.isArray(b.code) && b.code.length
    );
    document.body.dataset.hasCode = any ? "1" : "0";
  }
```

In `createBlockSection`, after `body.appendChild(content);` and before `section.appendChild(body);`:

```javascript
    const codeCol = renderCodeColumn(blk);
    if (codeCol) {
      section.dataset.hasCode = "1";
      body.appendChild(codeCol);
      let wide = "0";
      try { wide = localStorage.getItem(codeWideKey(blk.id)) || "0"; } catch (_) {}
      section.dataset.codeWide = wide;
      const widenBtn = codeCol.querySelector(".cp-widen");
      if (widenBtn && wide === "1") widenBtn.textContent = "narrow";
    }
```

Call `setDocumentCodeFlag(data.blocks)` in the render path that receives the `/raw` payload, **before** any `createBlockSection` call — `renderCodeColumn` reads the flag it sets.

In `updateBlockContent` (the in-place refresh path), after the content is replaced, drop any existing `.code-col` and re-append a fresh one:

```javascript
    const oldCol = section.querySelector(".code-col");
    if (oldCol) oldCol.remove();
    const freshCol = renderCodeColumn(blk);
    if (freshCol) {
      section.dataset.hasCode = "1";
      (section.querySelector(".card-body") || section).appendChild(freshCol);
      // The card keeps its data-code-wide across the rewrite, so the freshly
      // built button has to agree with it — otherwise a promoted pane comes
      // back from a rewrite still wide but offering to widen it again.
      const btn = freshCol.querySelector(".cp-widen");
      if (btn && section.dataset.codeWide === "1") btn.textContent = "narrow";
    } else {
      delete section.dataset.hasCode;
    }
```

In `skills/annotate/static/export.js`, add `".cp-widen"` to the `STRIP` list. Promotion is a live control; in an exported file its JS is gone, so the button would sit there inert. The pane's code itself must NOT be stripped — carrying it is the point.

Finally, in the server's page template, set `data-project-name` and `data-repo-root` on `<body>` from `dirs["_cwd"]` (basename and full path) so the `jetbrains://` link can be built. Find where `serve_root` writes `<body ...>` in `skills/annotate/server.py:353` and add both attributes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_smoke_code_panes.py -q`
Expected: PASS, 10 tests.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest skills -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/static/script.js skills/annotate/server.py skills/annotate/tests/test_smoke_code_panes.py
git commit -m "feat(annotate): paint code panes beside the prose

A failing pane branches on status before it touches lines, so it shows
its reason and no code — rendering whatever now sits at that line
number would be a lie the reader cannot detect. Promotion persists per
block; a widening you must redo on every reload is worse than none."
```

---

### Task 9: The authoring rule and its reference

**Files:**
- Create: `skills/annotate/references/code-anchors.md`
- Modify: `skills/annotate/SKILL.md`, `skills/annotate/references/pushing.md`
- Test: `skills/annotate/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: the field shape from Task 1, the CLI from Task 6.
- Produces: documentation only.

- [ ] **Step 1: Write the failing test**

Read `skills/annotate/tests/test_skill_structure.py` first to match its existing style, then append:

```python
class TestCodeAnchorDocs(unittest.TestCase):
    def test_reference_exists(self):
        p = SKILL_DIR / "references" / "code-anchors.md"
        self.assertTrue(p.is_file(), "references/code-anchors.md missing")

    def test_skill_md_states_the_rule(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        self.assertIn("code-anchors.md", text)

    def test_pushing_points_at_the_reference(self):
        text = (SKILL_DIR / "references" / "pushing.md").read_text()
        self.assertIn("code-anchors.md", text)

    def test_reference_documents_the_check(self):
        text = (SKILL_DIR / "references" / "code-anchors.md").read_text()
        self.assertIn("check_anchors", text)
```

`SKILL_DIR` is defined at the top of the existing file; reuse it rather than redefining.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_skill_structure.py -q`
Expected: FAIL — `references/code-anchors.md missing`.

- [ ] **Step 3: Write the reference**

Create `skills/annotate/references/code-anchors.md` containing, at minimum:

- **When to anchor** — the rule: a block that asserts something about specific code carries an anchor to that code. Prose naming a file, function, branch or line without one is the failure this field exists to fix.
- **When not to** — a block making a recommendation, framing a question, or summarising takes no anchor, and its empty slot is correct.
- **The field**, with the worked example from the spec (`{file, line, end_line, snippet, note}`), each field's meaning, and the limits: 3 anchors per block, `end_line >= line`, 40-line window, no anchors on `mockup`.
- **`snippet` is the point** — it is the verbatim text of `line`, and it is what lets an anchor survive the file changing underneath it. An anchor without an accurate snippet resolves stale.
- **The check** — run after writing `blocks.json`, before announcing the URL:

  ```bash
  python3 -m skills.annotate.check_anchors "<response_dir>/blocks.json" "$PWD"
  ```

  Non-zero means fix the anchors and rewrite `blocks.json` before announcing.
- **Rewrites** — when answering a comment on an anchored block, re-emit its anchors. Re-read the file if it may have changed; a snippet copied from memory is how a block goes stale.
- **What the reader sees** — `ok`, `moved` (drifted, shown at its new line), `stale`/`missing`/`refused` (a marker and no code).

- [ ] **Step 4: Add the rule to SKILL.md**

In `skills/annotate/SKILL.md`, immediately after the block-kind menu table, add:

```markdown
## Code anchors — for engineering answers

Independent of kind, **a block that asserts something about specific code
carries a `code` anchor to that code.** Prose describing a file, function,
branch or line with the code nowhere on screen is the failure this field
exists to fix — the reader has to take the claim on trust or go hunting.

The anchor names a file and line; the server reads the real source and paints
it beside the prose. It costs a few tokens, so anchor generously.

Before emitting anchors, **`Read` `references/code-anchors.md`** for the field
shape, the limits, and the check to run before announcing the URL.
```

And add a row to the phase map table pointing at `references/code-anchors.md` for "a block asserts something about specific code".

- [ ] **Step 5: Point `pushing.md` at it**

In `skills/annotate/references/pushing.md`, in the "How to push a response" numbered list, extend step 1 with a sentence and add a new step between the current steps 4 and 5:

```markdown
4b. **Check the anchors** before announcing anything:

    python3 -m skills.annotate.check_anchors "<response_dir>/blocks.json" "$PWD"

    Exit 0 means every anchor resolves. Non-zero prints one problem per line
    naming the block and the anchor — fix `blocks.json` and re-run. A broken
    anchor caught here costs a rewrite; the same anchor caught by the reader
    costs their trust in every other citation on the page.
```

Also add a short "Code anchors" section pointing at `references/code-anchors.md`.

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_skill_structure.py -q`
Expected: PASS.

- [ ] **Step 7: Run the docs-truth audit**

Run: `python3 -m pytest skills/tests/test_repo_structure.py skills/tests/test_requirements_documented.py -q`
Expected: PASS. If either asserts a file inventory, add the new modules.

- [ ] **Step 8: Commit**

```bash
git add skills/annotate/SKILL.md skills/annotate/references/ skills/annotate/tests/test_skill_structure.py
git commit -m "docs(annotate): the anchoring rule and its reference

The pane is only half the fix. The block menu never asked for code,
which is why explanations arrived without any — this is the half that
asks."
```

---

### Task 10: End-to-end — the layout, the promotion, the export

The source-presence tests in Tasks 7 and 8 cannot see pixels. This is the one that proves the thing works.

**Files:**
- Create: `skills/annotate/tests/e2e/code-anchors.e2e.cjs`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the test**

Model the file on `skills/annotate/tests/e2e/top-panels.e2e.cjs` — read it first for the server-spawn and teardown boilerplate, and copy that structure exactly. The assertions specific to this feature:

1. **Split is real, not just classed.** Create a workspace whose `blocks.json` has one anchored block. Measure `getBoundingClientRect()` of `.block-content` and `.code-col` in the same card and assert they overlap vertically but not horizontally — that is what "side by side" means, and no source check can see it.
2. **The anchor line is the emphasised one.** Assert exactly one `.cp-row.is-anchor` in the pane and that its `.cp-num` text equals the anchor's line number.
3. **Context lines are dimmed, not hidden.** Assert `.cp-row.is-context` elements exist and have a computed `opacity` strictly between 0 and 1.
4. **`widen` promotes.** Record `.code-col` width, click `.cp-widen`, assert the width grew and `section[data-code-wide="1"]`.
5. **Promotion survives reload.** Reload the page, assert the card is still `data-code-wide="1"` and the button reads `narrow`.
6. **An anchorless document is untouched.** Second workspace, no anchors anywhere: assert `document.body.dataset.hasCode !== "1"`, no `.code-col` in the DOM, and that the computed `--content-max` is `1040px`.
7. **Export carries the code.** Click the share/export control, capture the produced HTML, and assert it contains a line of the real source text. This is the claim that export is free — if the code were fetched client-side after render it would be absent.

- [ ] **Step 2: Run it**

Run: `NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/code-anchors.e2e.cjs`
Expected: all assertions pass. Requires the global `playwright` package and an installed chromium; this file is not part of the pytest CI run, same as the other `.cjs` tests.

- [ ] **Step 3: Prove assertion 7 can fail**

Temporarily change `renderCodePane` to append the lines in a `setTimeout(…, 0)`, re-run, and confirm the export assertion fails. Revert. A test that cannot fail guards nothing.

- [ ] **Step 4: Commit**

```bash
git add skills/annotate/tests/e2e/code-anchors.e2e.cjs
git commit -m "test(e2e): the split, the promotion, and the export

Side-by-side is a fact about pixels, so it is measured with
getBoundingClientRect rather than asserted from a class name. The
export assertion is the one that proves inlining server-side was the
right call."
```

---

### Task 11: Dogfood and full-suite gate

**Files:** none — this task is verification.

- [ ] **Step 1: Run the whole python suite**

Run: `python3 -m pytest skills -q`
Expected: PASS, no skips that were previously passing.

- [ ] **Step 2: Confirm the tree is clean and committed**

Run: `git status --porcelain`
Expected: empty. Anything unstaged here is work the suite above never saw.

- [ ] **Step 3: Dogfood it**

Start the server, push a real answer about this repo with anchors on at least three blocks, one of them deliberately stale, and open the page. Confirm by eye:
- panes sit beside their prose and the code is the real file's content;
- the stale one shows a marker and no code;
- `widen` works and survives a reload;
- a block with no anchor shows the "no code cited" slot.

- [ ] **Step 4: Record what iterating found**

Append a short "Field notes" section to the spec with anything the dogfood turned up that the design got wrong. This branch is expected to iterate before merging; the notes are what the next round argues from.

```bash
git add docs/superpowers/specs/2026-08-20-code-anchors-design.md
git commit -m "docs(spec): field notes from the first dogfood"
```
