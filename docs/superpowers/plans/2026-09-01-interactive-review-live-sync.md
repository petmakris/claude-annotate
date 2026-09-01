# interactive-review Live Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an `/interactive-review` session notice, on its own, when the reviewed branch changes locally (commit, rebase, checkout) — refreshing its diff snapshot and re-locating every thread's anchor — and give threads an explicit resolve-by-delete lifecycle, so a session never again silently drifts from what a rebase or squash actually did.

**Architecture:** A git hook (installed once per reviewed repo, chaining behind any existing hook) calls a small Python CLI (`notify_change`) the instant the branch changes locally. It finds the matching live session(s) via the existing session registry and POSTs to a new `/resync` endpoint on the already-running server. That endpoint re-fetches the diff (reusing the exact fetch already used at session-open) and re-locates every thread's anchor by reading the real current file and running the same text-matching algorithm the IDE panel already uses client-side (`AnchorResolver`), now ported to Python. An anchor that cannot be re-located wakes Claude through the existing watcher/event mechanism to review it; nothing is ever auto-resolved. Resolving a thread reuses the existing delete primitive — there is no new "resolved" state to store.

**Tech Stack:** Python 3 stdlib (server, hooks glue — no new dependencies), POSIX `sh` (git hooks), Java 17 + JUnit 5 (existing IDE plugin, `AnchorResolverTest` gets a fixture-driven extension), pytest (existing Python test suite).

**Spec:** `docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md` — read it before starting; this plan implements its decisions verbatim and does not re-argue them.

## Global Constraints

- No new third-party dependencies (Python side stays stdlib-only, matching every existing `web_companion` module; Java side uses only Gson, already a dependency).
- A git hook must **never** fail or slow down the git command it's attached to: every failure mode in `notify_change`/`notify.sh` is silent (best-effort, swallow-and-continue), never a non-zero exit for anything except a genuine usage error.
- A resync must **never** partially overwrite `diff.patch`/`meta.json`: on any fetch failure, the session keeps its last-known-good snapshot untouched.
- `install_hooks.sh` must **never** overwrite an existing git hook — only append behind a marker comment, and never write into a `core.hooksPath` that lives outside `.git` (that may be a repo-tracked, shared hooks directory).
- A thread only closes on an explicit action (Claude via `resolve_cli.py`, or the user via the existing IDE delete button) — never inferred from anchor drift alone.
- Remote-side PR changes (someone else pushes, or you push from a different machine) are explicitly out of scope for this plan — no task adds polling or a remote hook.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `skills/_shared/web_companion/anchor_migrate.py` (new) | Pure text-matching re-location algorithm — Python port of `AnchorResolver.resolve()`. No I/O. |
| `skills/_shared/web_companion/tests/anchor_migration_fixtures.json` (new, canonical copy) | Shared test cases consumed by both the new Python test and the existing Java `AnchorResolverTest`. |
| `ide-plugin/src/test/resources/anchor_migration_fixtures.json` (new, copy kept in lockstep — see Task 1) | Java-side loadable copy of the same fixture. |
| `skills/_shared/web_companion/tests/test_anchor_migrate.py` (new) | Tests for `anchor_migrate.py`, including the shared fixture. |
| `ide-plugin/src/test/java/com/petros/ireview/AnchorResolverTest.java` (modify) | Gains one fixture-driven test method alongside its existing hand-written cases. |
| `skills/_shared/web_companion/threads.py` (modify) | Gains `migrate_anchor()` — moves a thread from one anchor to another, with a `migration_history` audit trail. |
| `skills/_shared/web_companion/tests/test_threads.py` (modify) | Tests for `migrate_anchor()`. |
| `skills/_shared/web_companion/resolve_cli.py` (new) | Thin CLI: delete a thread by anchor. Mirrors `reply_cli.py`'s shape. |
| `skills/_shared/web_companion/tests/test_resolve_cli.py` (new) | Tests for `resolve_cli.py`. |
| `skills/interactive_review/sync.py` (new) | Orchestrates one resync: re-fetch diff, migrate every thread, emit orphaned-anchor events. |
| `skills/interactive_review/tests/test_sync.py` (new) | Tests for `sync.py`. |
| `skills/interactive_review/server.py` (modify) | Gains `handle_resync`. |
| `skills/_shared/web_companion/server.py` (modify) | Gains the `/api/resync` route + `_handle_resync`, mirroring `/api/threads/delete`. |
| `skills/_shared/web_companion/tests/test_server.py` or equivalent (modify) | Route-level test for `/api/resync`. |
| `skills/_shared/web_companion/notify_change.py` (new) | CLI invoked by the git hook: finds matching sessions, POSTs `/resync`. |
| `skills/_shared/web_companion/tests/test_notify_change.py` (new) | Tests for `notify_change.py`. |
| `skills/interactive_review/hooks/notify.sh` (new) | Tiny script every installed hook calls; resolves its own plugin root and runs `notify_change`. |
| `skills/interactive_review/install_hooks.sh` (new) | Installs the three git hooks into a target repo, chaining behind any existing hook, idempotently. |
| `skills/interactive_review/tests/test_install_hooks.sh` (new) | Fixture-repo tests for the installer. |
| `skills/interactive_review/server.py` (modify, second edit) | `create_session_extra` best-effort calls `install_hooks.sh` once per session-create. |
| `skills/interactive_review/SKILL.md` (modify) | Documents the auto-install note, the new Mode-D `anchor_orphaned` branch, and `resolve_cli.py`. |

---

### Task 1: `anchor_migrate.py` — the ported resolution algorithm

**Files:**
- Create: `skills/_shared/web_companion/anchor_migrate.py`
- Create: `skills/_shared/web_companion/tests/anchor_migration_fixtures.json`
- Create: `ide-plugin/src/test/resources/anchor_migration_fixtures.json`
- Create: `skills/_shared/web_companion/tests/test_anchor_migrate.py`
- Modify: `ide-plugin/src/test/java/com/petros/ireview/AnchorResolverTest.java`

**Interfaces:**
- Produces: `anchor_migrate.Kind` (Enum: `EXACT`, `MOVED`, `STALE`), `anchor_migrate.Resolution` (frozen dataclass: `kind: Kind`, `line: int`), `anchor_migrate.locate(lines: list[str], recorded_line: int, anchor_text: str, k: int = 25) -> Resolution`. Task 4 (`sync.py`) is the consumer.

- [ ] **Step 1: Write the shared fixture** — the same seven cases `AnchorResolverTest.java` already hand-writes, so both implementations start from one source of truth.

```python
# scratch generator — run once to produce the JSON, then delete this script;
# it exists here only so the 100-line filler case isn't typed by hand twice.
import json

filler = [f"filler{i}" for i in range(100)]
filler[80] = "target();"

cases = [
    {
        "name": "exactWhenLineUnchanged",
        "lines": ["a", "  return foo();", "b"],
        "recorded_line": 2, "anchor_text": "return foo();", "k": 25,
        "expected_kind": "EXACT", "expected_line": 2,
    },
    {
        "name": "movedWhenUniqueNearby",
        "lines": ["new", "a", "  return foo();", "b"],
        "recorded_line": 2, "anchor_text": "return foo();", "k": 25,
        "expected_kind": "MOVED", "expected_line": 3,
    },
    {
        "name": "staleWhenGone",
        "lines": ["a", "b", "c"],
        "recorded_line": 2, "anchor_text": "return foo();", "k": 25,
        "expected_kind": "STALE", "expected_line": -1,
    },
    {
        "name": "staleWhenAmbiguous",
        "lines": ["x", "}", "y", "}", "z"],
        "recorded_line": 1, "anchor_text": "}", "k": 25,
        "expected_kind": "STALE", "expected_line": -1,
    },
    {
        "name": "exactWhenAnchorTextBlank",
        "lines": ["a", "b"],
        "recorded_line": 1, "anchor_text": "   ", "k": 25,
        "expected_kind": "EXACT", "expected_line": 1,
    },
    {
        "name": "staleWhenOutsideWindow",
        "lines": filler,
        "recorded_line": 1, "anchor_text": "target();", "k": 25,
        "expected_kind": "STALE", "expected_line": -1,
    },
    {
        "name": "recordedLinePastEndStillSearches",
        "lines": ["a", "  return foo();", "b"],
        "recorded_line": 999, "anchor_text": "return foo();", "k": 25,
        "expected_kind": "MOVED", "expected_line": 2,
    },
]
print(json.dumps(cases, indent=2))
```

Run it and save the output as both fixture files (they must be byte-identical):

```bash
cd /Users/petros.makris/projects/claude-annotate
python3 - <<'PYEOF' > skills/_shared/web_companion/tests/anchor_migration_fixtures.json
# paste the generator script above here
PYEOF
cp skills/_shared/web_companion/tests/anchor_migration_fixtures.json \
   ide-plugin/src/test/resources/anchor_migration_fixtures.json
```

- [ ] **Step 2: Write the failing Python test**

```python
# skills/_shared/web_companion/tests/test_anchor_migrate.py
import json
from pathlib import Path

import pytest

from skills._shared.web_companion.anchor_migrate import locate, Kind

FIXTURE = Path(__file__).parent / "anchor_migration_fixtures.json"
CASES = json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_fixture_cases(case):
    res = locate(case["lines"], case["recorded_line"], case["anchor_text"], case["k"])
    assert res.kind is Kind[case["expected_kind"]]
    assert res.line == case["expected_line"]


def test_empty_file_is_stale():
    res = locate([], 1, "anything", 25)
    assert res.kind is Kind.STALE
    assert res.line == -1
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_anchor_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._shared.web_companion.anchor_migrate'`

- [ ] **Step 4: Write `anchor_migrate.py`**

```python
"""Server-side port of the IDE plugin's AnchorResolver.

`ide-plugin/src/main/java/com/petros/ireview/AnchorResolver.java` re-locates
an annotation anchor against the live document the IDE has open, when the
recorded line no longer holds the recorded text (code moved above it). This
module is the exact same algorithm, ported so the server can do the same
re-location during a resync — for the case nobody has that file open in an
editor at all.

Kept pure and dependency-free (no I/O — callers supply `lines`) so both
implementations can be tested against one shared fixture
(`tests/anchor_migration_fixtures.json`, also read by
`ide-plugin/.../AnchorResolverTest.java`) without either drifting from the
other. See docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    EXACT = "EXACT"
    MOVED = "MOVED"
    STALE = "STALE"


@dataclass(frozen=True)
class Resolution:
    kind: Kind
    line: int  # 1-based for EXACT/MOVED, -1 for STALE


def locate(lines: list[str], recorded_line: int, anchor_text: str, k: int = 25) -> Resolution:
    """Re-locate `anchor_text`, last seen at `recorded_line` (1-based), in `lines`.

    Mirrors `AnchorResolver.resolve` exactly: an exact match at the recorded
    line wins outright without even considering the window; otherwise a
    +/-k line window search around the (clamped) recorded line must find
    EXACTLY ONE match to count as MOVED — zero or more than one is STALE
    (an ambiguous match is treated the same as no match: guessing wrong here
    is worse than asking).
    """
    needle = (anchor_text or "").strip()
    if not needle:
        # Blank/unknown text isn't matchable — keep today's behavior: assume
        # the recorded line is still right rather than flagging every such
        # thread as orphaned.
        return Resolution(Kind.EXACT, recorded_line)

    idx = recorded_line - 1  # 1-based -> 0-based
    if 0 <= idx < len(lines) and lines[idx].strip() == needle:
        return Resolution(Kind.EXACT, recorded_line)

    search_idx = max(0, min(idx, len(lines) - 1))
    lo = max(0, search_idx - k)
    hi = min(len(lines) - 1, search_idx + k)
    match = -1
    for i in range(lo, hi + 1):
        if lines[i].strip() == needle:
            if match != -1:
                return Resolution(Kind.STALE, -1)  # ambiguous
            match = i
    if match == -1:
        return Resolution(Kind.STALE, -1)
    return Resolution(Kind.MOVED, match + 1)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_anchor_migrate.py -v`
Expected: PASS (8 tests — 7 fixture cases + the empty-file case)

- [ ] **Step 6: Add the fixture-driven Java test**

Add this method to the existing `AnchorResolverTest.java` (keep every existing `@Test` method untouched — this is additive):

```java
    @Test void sharedFixtureCasesMatchPython() throws java.io.IOException {
        // Loads the same JSON both AnchorResolverTest.java and
        // test_anchor_migrate.py read, so a behavior change in one
        // implementation that isn't mirrored in the other fails here.
        try (var in = AnchorResolverTest.class.getResourceAsStream("/anchor_migration_fixtures.json")) {
            assertNotNull(in, "anchor_migration_fixtures.json missing from test resources");
            var json = new String(in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
            var cases = com.google.gson.JsonParser.parseString(json).getAsJsonArray();
            for (var el : cases) {
                var c = el.getAsJsonObject();
                java.util.List<String> lines = new java.util.ArrayList<>();
                for (var l : c.getAsJsonArray("lines")) lines.add(l.getAsString());
                var r = AnchorResolver.resolve(
                    lines, c.get("recorded_line").getAsInt(),
                    c.get("anchor_text").getAsString(), c.get("k").getAsInt());
                assertEquals(
                    AnchorResolver.Kind.valueOf(c.get("expected_kind").getAsString()), r.kind(),
                    "case: " + c.get("name").getAsString());
                assertEquals(c.get("expected_line").getAsInt(), r.line(),
                    "case: " + c.get("name").getAsString());
            }
        }
    }
```

- [ ] **Step 7: Run the Java test to verify it passes**

Run: `cd /Users/petros.makris/projects/claude-annotate/ide-plugin && ./gradlew test --tests "com.petros.ireview.AnchorResolverTest"`
Expected: BUILD SUCCESSFUL, all 8 methods pass (7 existing + the new fixture-driven one)

- [ ] **Step 8: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/_shared/web_companion/anchor_migrate.py \
        skills/_shared/web_companion/tests/anchor_migration_fixtures.json \
        skills/_shared/web_companion/tests/test_anchor_migrate.py \
        ide-plugin/src/test/resources/anchor_migration_fixtures.json \
        ide-plugin/src/test/java/com/petros/ireview/AnchorResolverTest.java
git commit -m "Add anchor_migrate.py, a Python port of AnchorResolver, with a shared cross-language test fixture"
```

---

### Task 2: `threads.migrate_anchor` — moving a thread when its code moved

**Files:**
- Modify: `skills/_shared/web_companion/threads.py`
- Modify: `skills/_shared/web_companion/tests/test_threads.py`

**Interfaces:**
- Consumes: `_anchor_lock`, `load`, `save_atomic`, `_path_for` — all already defined in `threads.py`.
- Produces: `migrate_anchor(threads_dir: Path, old_anchor: str, new_anchor: str, *, kind: str) -> bool`. Task 4 (`sync.py`) is the consumer.

- [ ] **Step 1: Write the failing test**

```python
# append to skills/_shared/web_companion/tests/test_threads.py
from skills._shared.web_companion.threads import migrate_anchor


def test_migrate_anchor_moves_thread_and_records_history(tmp_path):
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir()
    append_message(threads_dir, "src/x.py:R:42",
                   {"role": "claude", "ts": 100, "text": "hi", "source_event_id": "e1"})

    moved = migrate_anchor(threads_dir, "src/x.py:R:42", "src/x.py:R:45", kind="MOVED")

    assert moved is True
    old = load(threads_dir, "src/x.py:R:42")
    assert old["messages"] == []  # nothing left at the old anchor
    new = load(threads_dir, "src/x.py:R:45")
    assert new["anchor"] == "src/x.py:R:45"
    assert len(new["messages"]) == 1
    assert new["migration_history"] == [
        {"from": "src/x.py:R:42", "to": "src/x.py:R:45", "kind": "MOVED", "ts": new["migration_history"][0]["ts"]}
    ]


def test_migrate_anchor_missing_source_is_noop(tmp_path):
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir()
    assert migrate_anchor(threads_dir, "no/such.py:R:1", "no/such.py:R:2", kind="MOVED") is False


def test_migrate_anchor_same_anchor_is_noop(tmp_path):
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir()
    append_message(threads_dir, "a:R:1", {"role": "user", "ts": 1, "text": "x"})
    assert migrate_anchor(threads_dir, "a:R:1", "a:R:1", kind="EXACT") is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_threads.py -k migrate_anchor -v`
Expected: FAIL with `ImportError: cannot import name 'migrate_anchor'`

- [ ] **Step 3: Add `migrate_anchor` to `threads.py`**

Add this function after `delete()` (which it directly mirrors in shape — same locking discipline, same atomic-write reuse):

```python
def migrate_anchor(threads_dir: Path, old_anchor: str, new_anchor: str, *, kind: str) -> bool:
    """Move a thread from `old_anchor` to `new_anchor` after its code moved.

    Appends one `migration_history` entry ({from, to, kind, ts}) so a reader
    can see why a thread's anchor differs from where it was first created —
    `kind` is the resolution kind that produced this move (e.g. "MOVED" from
    anchor_migrate.locate). Returns False, doing nothing, if no thread exists
    at `old_anchor` or the two anchors are identical.

    Locks BOTH anchors, in a fixed lexicographic order regardless of which
    is "old" and which is "new" — so two migrations racing in opposite
    directions (a swap) cannot deadlock each other the way locking in call
    order could.
    """
    if old_anchor == new_anchor:
        return False
    first, second = sorted((old_anchor, new_anchor))
    with _anchor_lock(threads_dir, first), _anchor_lock(threads_dir, second):
        old_path = _path_for(threads_dir, old_anchor)
        if not old_path.exists():
            return False
        t = load(threads_dir, old_anchor)
        t["anchor"] = new_anchor
        t.setdefault("migration_history", []).append({
            "from": old_anchor, "to": new_anchor, "kind": kind,
            "ts": int(time.time()),
        })
        save_atomic(threads_dir, t)
        old_path.unlink()
        return True
```

Add `import time` to the top of `threads.py` if it is not already imported (check first — `threads.py` currently imports `hashlib`, `json`, `re`, `urllib.parse`; `time` is not among them).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_threads.py -v`
Expected: PASS (all existing `test_threads.py` tests plus the 3 new ones)

- [ ] **Step 5: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/_shared/web_companion/threads.py skills/_shared/web_companion/tests/test_threads.py
git commit -m "Add threads.migrate_anchor for moving a thread when its anchored code moves"
```

---

### Task 3: `resolve_cli.py` — the explicit-resolve primitive

**Files:**
- Create: `skills/_shared/web_companion/resolve_cli.py`
- Create: `skills/_shared/web_companion/tests/test_resolve_cli.py`

**Interfaces:**
- Consumes: `threads.delete`, `threads.valid_anchor` (both already defined).
- Produces: `resolve_cli.main(argv: list[str] | None = None) -> int`, invoked as `python3 -m skills._shared.web_companion.resolve_cli --anchor <anchor>` with `STATE_DIR` set. Documented for Claude's use in Task 8 (SKILL.md).

- [ ] **Step 1: Write the failing test**

```python
# skills/_shared/web_companion/tests/test_resolve_cli.py
from skills._shared.web_companion.resolve_cli import main
from skills._shared.web_companion import threads as threads_module


def test_resolve_deletes_thread(tmp_path):
    state = tmp_path / "state"
    (state / "threads").mkdir(parents=True)
    threads_module.append_message(state / "threads", "src/x.py:R:42",
                                  {"role": "claude", "ts": 1, "text": "found it"})

    rc = main(["--state-dir", str(state), "--anchor", "src/x.py:R:42"])

    assert rc == 0
    assert threads_module.load(state / "threads", "src/x.py:R:42")["messages"] == []


def test_resolve_missing_thread_returns_1(tmp_path):
    state = tmp_path / "state"
    (state / "threads").mkdir(parents=True)
    rc = main(["--state-dir", str(state), "--anchor", "no/such.py:R:1"])
    assert rc == 1


def test_resolve_bad_anchor_returns_2(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    rc = main(["--state-dir", str(state), "--anchor", "not-a-valid-anchor"])
    assert rc == 2


def test_resolve_missing_state_dir_returns_2(tmp_path):
    rc = main(["--state-dir", str(tmp_path / "nope"), "--anchor", "a:R:1"])
    assert rc == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_resolve_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._shared.web_companion.resolve_cli'`

- [ ] **Step 3: Write `resolve_cli.py`**

```python
"""One-command "this finding is resolved" for Claude and any other automation.

    PYTHONPATH="$PLUGIN_ROOT" STATE_DIR="$STATE_DIR" \
      python3 -m skills._shared.web_companion.resolve_cli --anchor "<anchor>"

This skill's resolve model is "resolved means gone" — the same one the IDE's
existing per-thread delete button already implements via `threads.delete`.
This CLI exists so Claude has the same "route through a documented command,
never import internals ad hoc" shape `reply_cli.py` already gives it for
replying.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from skills._shared.web_companion.threads import delete, valid_anchor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="resolve_cli", description=__doc__)
    parser.add_argument("--state-dir", default=os.environ.get("STATE_DIR"),
                        help="session state dir (default: $STATE_DIR)")
    parser.add_argument("--anchor", required=True,
                        help="the thread's anchor, e.g. src/x.py:R:42")
    args = parser.parse_args(argv)

    if not args.state_dir:
        print("resolve_cli: no state dir (pass --state-dir or set STATE_DIR)",
              file=sys.stderr)
        return 2
    state_dir = Path(args.state_dir)
    if not state_dir.is_dir():
        print(f"resolve_cli: state dir does not exist: {state_dir}", file=sys.stderr)
        return 2
    if not valid_anchor(args.anchor):
        print(f"resolve_cli: not a valid anchor: {args.anchor!r}", file=sys.stderr)
        return 2

    if not delete(state_dir / "threads", args.anchor):
        print(f"resolve_cli: no thread found for anchor {args.anchor!r} (already resolved?)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_resolve_cli.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/_shared/web_companion/resolve_cli.py skills/_shared/web_companion/tests/test_resolve_cli.py
git commit -m "Add resolve_cli.py — the explicit resolve-by-delete primitive for threads"
```

---

### Task 4: `sync.py` — the resync orchestrator

**Files:**
- Create: `skills/interactive_review/sync.py`
- Create: `skills/interactive_review/tests/test_sync.py`

**Interfaces:**
- Consumes: `anchor_migrate.locate`, `anchor_migrate.Kind` (Task 1); `threads.migrate_anchor` (Task 2); `events.append(events_dir: Path, payload: dict) -> str` (existing); `diff_module.fetch_pr_diff(pr_ref: str, cwd: str | None) -> tuple[str, dict]` (existing, `skills/interactive_review/diff.py`); `write_text_atomic` (existing).
- Produces: `sync.resync(dirs: dict) -> dict` returning `{"ok": bool, "error": str | None, "migrated": list[str], "orphaned": list[str]}`. Task 5 (`handle_resync`) is the consumer.

- [ ] **Step 1: Write the failing tests**

```python
# skills/interactive_review/tests/test_sync.py
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.interactive_review import sync
from skills._shared.web_companion import threads as threads_module
from skills._shared.web_companion import events as events_module


def make_dirs(tmp_path, cwd):
    state_dir = tmp_path / "state"
    (state_dir / "threads").mkdir(parents=True)
    (state_dir / "events").mkdir(parents=True)
    return {"state_dir": state_dir, "events_dir": state_dir / "events", "_cwd": str(cwd)}


def write_meta(dirs, **overrides):
    meta = {"pr_ref": "42", "head": "feature", "head_oid": "old", "title": "t"}
    meta.update(overrides)
    (Path(dirs["state_dir"]) / "meta.json").write_text(json.dumps(meta))


def test_resync_leaves_files_untouched_on_fetch_failure(tmp_path):
    dirs = make_dirs(tmp_path, tmp_path)
    write_meta(dirs)
    (Path(dirs["state_dir"]) / "diff.patch").write_text("ORIGINAL DIFF")

    with patch("skills.interactive_review.sync.diff_module.fetch_pr_diff",
              side_effect=RuntimeError("gh is down")):
        result = sync.resync(dirs)

    assert result["ok"] is False
    assert "gh is down" in result["error"]
    assert (Path(dirs["state_dir"]) / "diff.patch").read_text() == "ORIGINAL DIFF"


def test_resync_writes_new_diff_and_meta_on_success(tmp_path):
    dirs = make_dirs(tmp_path, tmp_path)
    write_meta(dirs)

    with patch("skills.interactive_review.sync.diff_module.fetch_pr_diff",
              return_value=("NEW DIFF", {"headRefName": "feature", "headRefOid": "new"})):
        result = sync.resync(dirs)

    assert result["ok"] is True
    assert (Path(dirs["state_dir"]) / "diff.patch").read_text() == "NEW DIFF"
    meta = json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())
    assert meta["head_oid"] == "new"
    assert meta["pr_ref"] == "42"  # preserved, not clobbered


def test_resync_migrates_a_moved_anchor(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("a\nb\ncall_it()\nc\n")
    dirs = make_dirs(tmp_path, repo)
    write_meta(dirs)
    threads_dir = Path(dirs["state_dir"]) / "threads"
    threads_module.append_message(threads_dir, "x.py:R:2",
                                  {"role": "claude", "ts": 1, "text": "hi"})
    threads_module.set_anchor_text_if_absent(threads_dir, "x.py:R:2", "call_it()")

    with patch("skills.interactive_review.sync.diff_module.fetch_pr_diff",
              return_value=("D", {"headRefName": "feature", "headRefOid": "new"})):
        result = sync.resync(dirs)

    assert result["migrated"] == ["x.py:R:3"]
    assert threads_module.load(threads_dir, "x.py:R:2")["messages"] == []
    moved = threads_module.load(threads_dir, "x.py:R:3")
    assert len(moved["messages"]) == 1


def test_resync_emits_event_for_orphaned_anchor(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("nothing matches here\n")
    dirs = make_dirs(tmp_path, repo)
    write_meta(dirs)
    threads_dir = Path(dirs["state_dir"]) / "threads"
    threads_module.append_message(threads_dir, "x.py:R:1",
                                  {"role": "claude", "ts": 1, "text": "hi"})
    threads_module.set_anchor_text_if_absent(threads_dir, "x.py:R:1", "call_it()")

    with patch("skills.interactive_review.sync.diff_module.fetch_pr_diff",
              return_value=("D", {"headRefName": "feature", "headRefOid": "new"})):
        result = sync.resync(dirs)

    assert result["orphaned"] == ["x.py:R:1"]
    events_dir = Path(dirs["events_dir"])
    event_files = list(events_dir.glob("*.json"))
    assert len(event_files) == 1
    payload = json.loads(event_files[0].read_text())
    assert payload["event_kind"] == "anchor_orphaned"
    assert payload["anchor"] == "x.py:R:1"


def test_resync_skips_general_and_textless_threads(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    dirs = make_dirs(tmp_path, repo)
    write_meta(dirs)
    threads_dir = Path(dirs["state_dir"]) / "threads"
    threads_module.append_message(threads_dir, "__general__", {"role": "user", "ts": 1, "text": "hi"})

    with patch("skills.interactive_review.sync.diff_module.fetch_pr_diff",
              return_value=("D", {"headRefName": "feature", "headRefOid": "new"})):
        result = sync.resync(dirs)

    assert result["migrated"] == []
    assert result["orphaned"] == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/interactive_review/tests/test_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.interactive_review.sync'`

- [ ] **Step 3: Write `sync.py`**

```python
"""Re-syncs an interactive-review session against the reviewed branch's
current local state: refreshes diff.patch/meta.json, and re-locates every
open thread's anchor in the real, current file — the same thing the IDE
panel's AnchorResolver already does against a live editor document, run here
for the case nobody has that file open at all.

Triggered by POST /resync (see skills/_shared/web_companion/server.py and
skills/interactive_review/server.py::handle_resync), itself fired by a git
hook via notify_change.py the instant the reviewed branch changes locally.
See docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from skills._shared.web_companion import anchor_migrate
from skills._shared.web_companion import events as events_module
from skills._shared.web_companion import threads as threads_module
from skills._shared.web_companion.atomic import write_text_atomic
from skills.interactive_review import diff as diff_module

_ANCHOR_RE = re.compile(r"^(.+):([LR]):(\d+)(?:-(\d+))?$")
_SEARCH_WINDOW = 25  # keep in lockstep with AnchorResolver.DEFAULT_K


def _parse_anchor(anchor: str) -> tuple[str, str, int, int] | None:
    """(path, side, start, end) for a locatable anchor, or None for
    `__general__` or anything else that isn't a `path:side:line[-line]` shape."""
    m = _ANCHOR_RE.match(anchor)
    if not m:
        return None
    path, side, start, end = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    return path, side, start, (int(end) if end else start)


def resync(dirs: dict) -> dict:
    """Re-fetch the diff and migrate every thread's anchor.

    Returns {"ok", "error", "migrated": [...], "orphaned": [...]} — the two
    lists are new anchors (for migrated) / old anchors (for orphaned), for
    logging and testing. Never partially overwrites diff.patch/meta.json: a
    failed fetch leaves the session exactly as it was, because a session
    with a stale-but-known-good snapshot is always preferable to a
    half-updated one.
    """
    state_dir = Path(dirs["state_dir"])
    meta_path = state_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"could not read meta.json: {e}", "migrated": [], "orphaned": []}
    pr_ref = meta.get("pr_ref")
    if not pr_ref:
        return {"ok": False, "error": "meta.json has no pr_ref", "migrated": [], "orphaned": []}

    try:
        diff_text, gh_meta = diff_module.fetch_pr_diff(pr_ref, dirs.get("_cwd"))
    except Exception as e:
        return {"ok": False, "error": f"gh fetch failed: {e}", "migrated": [], "orphaned": []}

    migrated, orphaned = _migrate_all_threads(dirs)

    write_text_atomic(state_dir / "diff.patch", diff_text)
    write_text_atomic(meta_path, json.dumps({
        **meta,
        "head": gh_meta.get("headRefName", meta.get("head", "")),
        "head_oid": gh_meta.get("headRefOid", ""),
        "fetched_at": int(time.time()),
    }, indent=2))

    return {"ok": True, "error": None, "migrated": migrated, "orphaned": orphaned}


def _migrate_all_threads(dirs: dict) -> tuple[list[str], list[str]]:
    """Re-locate every thread's anchor against the real current file.

    A thread is left alone (appears in neither returned list) when its
    anchor is `__general__`, or it has no recorded `anchor_text` to search
    for (created before that field existed) — there is nothing to compare
    against in either case.
    """
    threads_dir = Path(dirs["state_dir"]) / "threads"
    cwd = dirs.get("_cwd")
    migrated: list[str] = []
    orphaned: list[str] = []
    if not threads_dir.is_dir() or not cwd:
        return migrated, orphaned

    file_lines_cache: dict[str, list[str] | None] = {}

    def lines_for(path: str) -> list[str] | None:
        """Cached full-file read, mirroring what the IDE reads from its live
        editor document. None means the file no longer exists at this path."""
        if path not in file_lines_cache:
            try:
                file_lines_cache[path] = (Path(cwd) / path).read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                file_lines_cache[path] = None
        return file_lines_cache[path]

    for p in list(threads_dir.glob("*.json")):
        try:
            t = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        old_anchor = t.get("anchor")
        anchor_text = t.get("anchor_text")
        if not isinstance(old_anchor, str) or not anchor_text:
            continue

        parsed = _parse_anchor(old_anchor)
        if parsed is None:
            continue
        path, side, start, end = parsed

        lines = lines_for(path)
        if lines is None:
            orphaned.append(old_anchor)
            _emit_orphaned(dirs, old_anchor, t.get("title", ""), anchor_text)
            continue

        res = anchor_migrate.locate(lines, start, anchor_text, _SEARCH_WINDOW)
        if res.kind is anchor_migrate.Kind.STALE:
            orphaned.append(old_anchor)
            _emit_orphaned(dirs, old_anchor, t.get("title", ""), anchor_text)
            continue
        if res.line == start:
            continue  # EXACT at the same line — nothing to migrate

        new_end = end + (res.line - start)
        new_anchor = (f"{path}:{side}:{res.line}" if end == start
                      else f"{path}:{side}:{res.line}-{new_end}")
        if threads_module.migrate_anchor(threads_dir, old_anchor, new_anchor, kind=res.kind.value):
            migrated.append(new_anchor)

    return migrated, orphaned


def _emit_orphaned(dirs: dict, anchor: str, title: str, old_anchor_text: str) -> None:
    events_module.append(Path(dirs["events_dir"]), {
        "event_kind": "anchor_orphaned",
        "anchor": anchor,
        "thread_title": title,
        "old_anchor_text": old_anchor_text,
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/interactive_review/tests/test_sync.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/interactive_review/sync.py skills/interactive_review/tests/test_sync.py
git commit -m "Add sync.py: resync a session's diff and migrate every thread's anchor"
```

---

### Task 5: `/api/resync` endpoint

**Files:**
- Modify: `skills/interactive_review/server.py`
- Modify: `skills/_shared/web_companion/server.py`
- Create: `skills/interactive_review/tests/test_resync_route.py`

**Interfaces:**
- Consumes: `sync.resync(dirs: dict) -> dict` (Task 4).
- Produces: `Handlers.handle_resync(self, h, dirs, payload)` (optional-capability method, `hasattr`-dispatched exactly like `handle_thread_delete`); route `POST /s/<sid>/api/resync`. Task 6 (`notify_change.py`) is the consumer of the route.

- [ ] **Step 1: Write the failing test**

```python
# skills/interactive_review/tests/test_resync_route.py
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from skills.interactive_review.server import Handlers


def make_handler():
    h = MagicMock()
    h.rfile = BytesIO(b"")
    h.wfile = BytesIO()
    h.headers = {}
    return h


def make_dirs(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "threads").mkdir(parents=True)
    (state_dir / "events").mkdir(parents=True)
    (state_dir / "meta.json").write_text(json.dumps({"pr_ref": "42", "head": "feature"}))
    return {"state_dir": state_dir, "events_dir": state_dir / "events", "_cwd": str(tmp_path)}


def test_handle_resync_returns_sync_result(tmp_path):
    handlers = Handlers()
    handler = make_handler()
    with patch("skills.interactive_review.server.sync_module.resync",
              return_value={"ok": True, "error": None, "migrated": [], "orphaned": []}):
        handlers.handle_resync(handler, make_dirs(tmp_path), {})
    handler.send_response.assert_called_once_with(200)
    body = json.loads(handler.wfile.getvalue())
    assert body["ok"] is True


def test_handle_resync_returns_502_on_failure(tmp_path):
    handlers = Handlers()
    handler = make_handler()
    with patch("skills.interactive_review.server.sync_module.resync",
              return_value={"ok": False, "error": "gh down", "migrated": [], "orphaned": []}):
        handlers.handle_resync(handler, make_dirs(tmp_path), {})
    handler.send_response.assert_called_once_with(502)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/interactive_review/tests/test_resync_route.py -v`
Expected: FAIL with `AttributeError: 'Handlers' object has no attribute 'handle_resync'`

- [ ] **Step 3: Add `handle_resync` to `skills/interactive_review/server.py`**

Add the import near the top, alongside the other `skills.interactive_review` import:

```python
from skills.interactive_review import sync as sync_module
```

Add this method to `Handlers`, directly after `handle_thread_delete`:

```python
    def handle_resync(self, h: BaseHTTPRequestHandler, dirs: dict, payload: dict) -> None:
        """POST /s/<sid>/api/resync — re-fetch the diff and re-locate every
        thread's anchor against the reviewed branch's current local state.

        No request body is required; `payload` is accepted for symmetry with
        the other handlers and currently ignored.
        """
        result = sync_module.resync(dirs)
        _send_json(h, 200 if result["ok"] else 502, result)
```

- [ ] **Step 4: Add the shared route in `skills/_shared/web_companion/server.py`**

In `_dispatch_post`, immediately after the existing `/api/threads/delete` block (inside the `matched = self._match_session("/s/")` branch), add:

```python
                if rest == "/api/resync":
                    if _is_terminal(dirs):
                        self._send_text(409, "session closed")
                        return
                    self._handle_resync(sid, dirs)
                    return
```

Add the corresponding private method, directly after `_handle_thread_delete`:

```python
        def _handle_resync(self, sid, dirs):
            if not hasattr(handlers, "handle_resync"):
                self._send_text(404, "resync not supported by this skill")
                return
            handlers.handle_resync(self, dirs, {})
            registry.note_change(sid)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/interactive_review/tests/test_resync_route.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full existing suite to confirm nothing else broke**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all previously-passing tests still pass, plus the new ones from Tasks 1–5

- [ ] **Step 7: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/interactive_review/server.py skills/_shared/web_companion/server.py \
        skills/interactive_review/tests/test_resync_route.py
git commit -m "Add POST /api/resync, wired to sync.resync"
```

---

### Task 6: `notify_change.py` — the git-hook-invoked trigger

**Files:**
- Create: `skills/_shared/web_companion/notify_change.py`
- Create: `skills/_shared/web_companion/tests/test_notify_change.py`

**Interfaces:**
- Consumes: `sessions.Registry` (existing — `rehydrate()`, `find_by_cwd()`), `paths.state_root(skill_name: str) -> Path` (existing).
- Produces: `notify_change.notify(cwd: str, state_root: Path | None = None) -> int`, `notify_change.main(argv) -> int` (CLI entry: `python3 -m skills._shared.web_companion.notify_change <cwd>`). Task 7 (`notify.sh`) is the consumer.

- [ ] **Step 1: Write the failing tests**

```python
# skills/_shared/web_companion/tests/test_notify_change.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from skills._shared.web_companion.notify_change import notify
from skills._shared.web_companion.sessions import Registry


def _make_session(state_root: Path, sid: str, cwd: str, head: str) -> None:
    ws = state_root / "workspaces" / sid / "state"
    ws.mkdir(parents=True)
    (ws / "meta.json").write_text(json.dumps({"pr_ref": "1", "head": head}))
    registry = Registry(state_root)
    registry.register(sid, {"_cwd": cwd, "state_dir": ws})
    registry.register_meta(sid, {"slug": sid})
    registry.persist()


def test_notify_posts_to_matching_session(tmp_path):
    state_root = tmp_path / "sr"
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_session(state_root, "sid-1", str(repo), "feature")
    (state_root / "server.json").write_text(json.dumps({"url": "http://127.0.0.1:9999"}))

    with patch("skills._shared.web_companion.notify_change._current_repo_and_branch",
              return_value=(str(repo), "feature")), \
         patch("skills._shared.web_companion.notify_change.urllib.request.urlopen") as mock_open:
        rc = notify(str(repo), state_root=state_root)

    assert rc == 0
    mock_open.assert_called_once()
    called_url = mock_open.call_args[0][0].full_url
    assert called_url == "http://127.0.0.1:9999/s/sid-1/api/resync"


def test_notify_skips_session_on_different_branch(tmp_path):
    state_root = tmp_path / "sr"
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_session(state_root, "sid-1", str(repo), "other-branch")
    (state_root / "server.json").write_text(json.dumps({"url": "http://127.0.0.1:9999"}))

    with patch("skills._shared.web_companion.notify_change._current_repo_and_branch",
              return_value=(str(repo), "feature")), \
         patch("skills._shared.web_companion.notify_change.urllib.request.urlopen") as mock_open:
        rc = notify(str(repo), state_root=state_root)

    assert rc == 0
    mock_open.assert_not_called()


def test_notify_is_silent_when_server_not_running(tmp_path):
    state_root = tmp_path / "sr"
    state_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch("skills._shared.web_companion.notify_change._current_repo_and_branch",
              return_value=(str(repo), "feature")):
        rc = notify(str(repo), state_root=state_root)
    assert rc == 0  # no server.json at all — silent no-op


def test_notify_is_silent_on_detached_head(tmp_path):
    with patch("skills._shared.web_companion.notify_change._current_repo_and_branch",
              return_value=None):
        rc = notify(str(tmp_path), state_root=tmp_path)
    assert rc == 0


def test_notify_posts_to_every_matching_session(tmp_path):
    """Two sessions, same repo+branch (e.g. two review windows on one
    checkout) — both get resynced, not just the first found."""
    state_root = tmp_path / "sr"
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_session(state_root, "sid-1", str(repo), "feature")
    _make_session(state_root, "sid-2", str(repo), "feature")
    (state_root / "server.json").write_text(json.dumps({"url": "http://127.0.0.1:9999"}))

    with patch("skills._shared.web_companion.notify_change._current_repo_and_branch",
              return_value=(str(repo), "feature")), \
         patch("skills._shared.web_companion.notify_change.urllib.request.urlopen") as mock_open:
        rc = notify(str(repo), state_root=state_root)

    assert rc == 0
    assert mock_open.call_count == 2
    called_urls = {c[0][0].full_url for c in mock_open.call_args_list}
    assert called_urls == {
        "http://127.0.0.1:9999/s/sid-1/api/resync",
        "http://127.0.0.1:9999/s/sid-2/api/resync",
    }


def test_notify_swallows_network_errors(tmp_path):
    state_root = tmp_path / "sr"
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_session(state_root, "sid-1", str(repo), "feature")
    (state_root / "server.json").write_text(json.dumps({"url": "http://127.0.0.1:9999"}))

    with patch("skills._shared.web_companion.notify_change._current_repo_and_branch",
              return_value=(str(repo), "feature")), \
         patch("skills._shared.web_companion.notify_change.urllib.request.urlopen",
              side_effect=OSError("connection refused")):
        rc = notify(str(repo), state_root=state_root)

    assert rc == 0  # never propagates — a git hook must not fail
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_notify_change.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._shared.web_companion.notify_change'`

- [ ] **Step 3: Write `notify_change.py`**

```python
"""Notifies a running interactive-review server that the locally reviewed
branch just changed (commit, rebase, checkout), so it re-syncs its diff
snapshot and re-locates every thread's anchor before anyone notices they
drifted.

Invoked by a git hook installed via install_hooks.sh — see that file and
docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md.
Every function here is best-effort and silent on failure: a git hook must
not fail (or even visibly slow down) the git command that triggered it just
because the review server happens to be down, or no session matches.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from skills._shared.web_companion import paths
from skills._shared.web_companion.sessions import Registry

_GIT_TIMEOUT = 5
_HTTP_TIMEOUT = 10


def _current_repo_and_branch(cwd: str) -> tuple[str, str] | None:
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, cwd=cwd, timeout=_GIT_TIMEOUT,
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True, cwd=cwd, timeout=_GIT_TIMEOUT,
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    if not branch:
        return None  # detached HEAD — nothing named to match a session's `head`
    return root, branch


def _server_url(state_root: Path) -> str | None:
    try:
        info = json.loads((state_root / "server.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    url = info.get("url")
    return url if isinstance(url, str) and url else None


def _matching_sids(repo_root: str, branch: str, state_root: Path) -> list[str]:
    registry = Registry(state_root)
    registry.rehydrate()
    matches = []
    for sid, dirs in registry.find_by_cwd(repo_root):
        try:
            meta = json.loads((Path(dirs["state_dir"]) / "meta.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("head") == branch:
            matches.append(sid)
    return matches


def notify(cwd: str, state_root: Path | None = None) -> int:
    """Best-effort resync trigger. Always returns 0 — every failure mode
    (no repo, detached HEAD, no server, no match, network error) is silent."""
    state_root = state_root or paths.state_root("interactive-review")
    resolved = _current_repo_and_branch(cwd)
    if resolved is None:
        return 0
    repo_root, branch = resolved
    server_url = _server_url(state_root)
    if server_url is None:
        return 0  # server not running — nothing to notify
    for sid in _matching_sids(repo_root, branch, state_root):
        try:
            req = urllib.request.Request(
                f"{server_url}/s/{sid}/api/resync", data=b"{}", method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)
        except Exception:
            continue  # one session's failure must not block the others
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cwd = argv[0] if argv else os.getcwd()
    return notify(cwd)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills/_shared/web_companion/tests/test_notify_change.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/_shared/web_companion/notify_change.py skills/_shared/web_companion/tests/test_notify_change.py
git commit -m "Add notify_change.py — the git-hook-invoked resync trigger"
```

---

### Task 7: Git hook installer

**Files:**
- Create: `skills/interactive_review/hooks/notify.sh`
- Create: `skills/interactive_review/install_hooks.sh`
- Create: `skills/interactive_review/tests/test_install_hooks.sh`
- Modify: `skills/interactive_review/server.py` (wire into `create_session_extra`)

**Interfaces:**
- Consumes: `notify_change.main` (Task 6, invoked as `python3 -m skills._shared.web_companion.notify_change`).
- Produces: `install_hooks.sh <repo-root>` — installs the three hooks, idempotently, chaining behind any existing ones. `create_session_extra` calls it best-effort.

- [ ] **Step 1: Write `notify.sh`**

```sh
#!/bin/sh
# claude-annotate: notify_change runner. Installed hooks call this by its
# absolute path (see install_hooks.sh) — it resolves its own plugin root
# from its own location, so it works no matter what the caller's cwd is.
# The caller is responsible for backgrounding and silencing this: a git
# command must never be slowed down or failed by this script.
PLUGIN_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills._shared.web_companion.notify_change "$(pwd)"
```

```bash
chmod +x skills/interactive_review/hooks/notify.sh
```

- [ ] **Step 2: Write the failing installer test**

```sh
# skills/interactive_review/tests/test_install_hooks.sh
#!/bin/sh
# Fixture-repo tests for install_hooks.sh. Run directly: sh test_install_hooks.sh
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALLER="$SCRIPT_DIR/install_hooks.sh"
FAIL=0

assert_contains() {
    if ! grep -qF "$2" "$1"; then
        echo "FAIL: $1 does not contain: $2"
        FAIL=1
    fi
}

# Case 1: no existing hook
t1="$(mktemp -d)"
git init -q "$t1"
"$INSTALLER" "$t1"
for h in post-commit post-rewrite post-checkout; do
    assert_contains "$t1/.git/hooks/$h" "claude-annotate: notify_change"
done
[ -x "$t1/.git/hooks/post-commit" ] || { echo "FAIL: post-commit not executable"; FAIL=1; }

# Case 2: a foreign hook must survive, in order, ahead of ours
t2="$(mktemp -d)"
git init -q "$t2"
printf '#!/bin/sh\necho "foreign hook ran"\n' > "$t2/.git/hooks/post-commit"
chmod +x "$t2/.git/hooks/post-commit"
"$INSTALLER" "$t2"
assert_contains "$t2/.git/hooks/post-commit" "foreign hook ran"
assert_contains "$t2/.git/hooks/post-commit" "claude-annotate: notify_change"
foreign_line=$(grep -n "foreign hook ran" "$t2/.git/hooks/post-commit" | cut -d: -f1)
marker_line=$(grep -n "claude-annotate: notify_change" "$t2/.git/hooks/post-commit" | cut -d: -f1)
if [ "$foreign_line" -ge "$marker_line" ]; then
    echo "FAIL: foreign content was not preserved ahead of our marker"
    FAIL=1
fi

# Case 3: running twice is a no-op the second time
before="$(cat "$t1/.git/hooks/post-commit")"
"$INSTALLER" "$t1"
after="$(cat "$t1/.git/hooks/post-commit")"
if [ "$before" != "$after" ]; then
    echo "FAIL: second install run was not idempotent"
    FAIL=1
fi

# Case 4: core.hooksPath outside .git is refused, not written into
t4="$(mktemp -d)"
git init -q "$t4"
mkdir "$t4/.husky"
git -C "$t4" config core.hooksPath .husky
"$INSTALLER" "$t4" 2>/tmp/install_hooks_stderr || true
if [ -f "$t4/.husky/post-commit" ]; then
    echo "FAIL: wrote into a hooksPath outside .git"
    FAIL=1
fi
assert_contains /tmp/install_hooks_stderr "outside .git"

rm -rf "$t1" "$t2" "$t4"
if [ "$FAIL" -eq 0 ]; then
    echo "ALL PASS"
else
    exit 1
fi
```

```bash
chmod +x skills/interactive_review/tests/test_install_hooks.sh
```

- [ ] **Step 3: Run it to verify it fails**

Run: `sh /Users/petros.makris/projects/claude-annotate/skills/interactive_review/tests/test_install_hooks.sh`
Expected: FAIL (`install_hooks.sh: No such file or directory` or similar)

- [ ] **Step 4: Write `install_hooks.sh`**

```sh
#!/bin/sh
# Installs post-commit/post-rewrite/post-checkout hooks in the target repo so
# a running interactive-review session resyncs the instant the reviewed
# branch changes locally. Never overwrites an existing hook — appends behind
# a marker comment so a repo's own hooks (husky, lefthook, hand-written)
# keep working, and a second run is always a no-op. Refuses to write into a
# core.hooksPath outside .git, since that may be a repo-tracked, shared
# hooks directory rather than this machine's own untracked one.
#
# Usage: install_hooks.sh <repo-root>
set -eu

REPO_ROOT_ARG="${1:?usage: install_hooks.sh <repo-root>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY_SH="$SCRIPT_DIR/hooks/notify.sh"
MARKER="# claude-annotate: notify_change"

REPO_ROOT="$(cd "$REPO_ROOT_ARG" && git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "install_hooks.sh: $REPO_ROOT_ARG is not inside a git repository" >&2
    exit 1
}

GIT_DIR="$(cd "$REPO_ROOT" && git rev-parse --git-dir)"
case "$GIT_DIR" in
    /*) : ;;
    *) GIT_DIR="$REPO_ROOT/$GIT_DIR" ;;
esac

HOOKS_DIR="$(cd "$REPO_ROOT" && git rev-parse --git-path hooks)"
case "$HOOKS_DIR" in
    /*) : ;;
    *) HOOKS_DIR="$REPO_ROOT/$HOOKS_DIR" ;;
esac

case "$HOOKS_DIR" in
    "$GIT_DIR"/*|"$GIT_DIR")
        : # inside .git — untracked, always safe to write
        ;;
    *)
        echo "install_hooks.sh: core.hooksPath ($HOOKS_DIR) is outside .git — refusing to write a machine-specific hook into what may be a repo-tracked, shared hooks directory. Live sync will not work for this repo; install by hand if you want it, or unset core.hooksPath." >&2
        exit 0   # not fatal — session creation must still succeed
        ;;
esac

mkdir -p "$HOOKS_DIR"

for hook in post-commit post-rewrite post-checkout; do
    hook_path="$HOOKS_DIR/$hook"
    if [ -f "$hook_path" ] && grep -qF "$MARKER" "$hook_path" 2>/dev/null; then
        continue  # already installed — idempotent no-op
    fi
    if [ ! -f "$hook_path" ]; then
        printf '#!/bin/sh\n' > "$hook_path"
    fi
    {
        echo ""
        echo "$MARKER"
        echo "\"$NOTIFY_SH\" >/dev/null 2>&1 &"
    } >> "$hook_path"
    chmod +x "$hook_path"
done
```

```bash
chmod +x skills/interactive_review/install_hooks.sh
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `sh /Users/petros.makris/projects/claude-annotate/skills/interactive_review/tests/test_install_hooks.sh`
Expected: `ALL PASS`

- [ ] **Step 6: Wire installation into `create_session_extra`**

In `skills/interactive_review/server.py`, add `os` and `subprocess` to the imports at the top (alongside `json`, `sys`, `time`):

```python
import os
import subprocess
```

At the end of `create_session_extra` (right after the `write_text_atomic(state_dir / "meta.json", ...)` call, before building `result`), add:

```python
        # Best-effort: live sync is an enhancement, never a session-creation
        # requirement. A repo where hook installation fails (permissions, a
        # tracked core.hooksPath) still gets a working, one-shot review —
        # just without automatic resync on a later local change.
        plugin_root = os.environ.get("PLUGIN_ROOT", "")
        if plugin_root:
            try:
                subprocess.run(
                    [f"{plugin_root}/skills/interactive_review/install_hooks.sh",
                     str(dirs.get("_cwd", ""))],
                    check=False, capture_output=True, timeout=10,
                )
            except Exception:
                pass
```

- [ ] **Step 7: Run the full existing suite to confirm nothing else broke**

Run: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/interactive_review/hooks/notify.sh skills/interactive_review/install_hooks.sh \
        skills/interactive_review/tests/test_install_hooks.sh skills/interactive_review/server.py
git commit -m "Add the git hook installer and wire it into session creation"
```

---

### Task 8: SKILL.md documentation

**Files:**
- Modify: `skills/interactive_review/SKILL.md`

**Interfaces:**
- Consumes: `resolve_cli.py` (Task 3) usage pattern; the `anchor_orphaned` event shape emitted by `sync.py` (Task 4).
- Produces: updated agent-facing instructions — no new code interfaces.

- [ ] **Step 1: Add a note under "Create a session"**

Immediately after the "Tell the user where to review" section (before "Arm the watcher"), add:

```markdown
## Live sync (automatic — no action needed here)

Session creation also best-effort installs local git hooks
(`post-commit`/`post-rewrite`/`post-checkout`) in the reviewed repo, so if
the branch changes locally later (a follow-up commit, a rebase, a squash),
the session's diff and every thread's anchor resync on their own within
moments — see
`docs/superpowers/specs/2026-09-01-interactive-review-live-sync-design.md`.
This is silent and requires nothing from you. It does **not** cover a
remote-side change (someone else pushing to the PR, or you pushing from a
different machine) — if the user reports the panel looks stale in a way
that doesn't match a local change they just made, that gap is why; re-run
`/interactive-review` on the same PR to pick it up.
```

- [ ] **Step 2: Add the new Mode D branch for orphaned anchors**

In the "## Mode D — handling a watcher event" section, add a new subsection immediately after `### WEBCOMPANION_EVENT (per-question submission)` and before `### WEBCOMPANION_FINISHED`:

```markdown
### `WEBCOMPANION_EVENT` with `event_kind: "anchor_orphaned"`

A resync could no longer find a thread's anchored line anywhere near where
it used to be — the code moved further than a nearby-lines search allows, or
the file changed enough that the exact text is gone. This is a **question**,
not evidence the finding was fixed: never resolve a thread on this signal
alone.

1. **Parse the payload** (between `---payload---` and `---end---`): `anchor`
   (the anchor as it was before this event — the thread is still filed
   there), `thread_title`, `old_anchor_text` (the line text that could no
   longer be located).
2. **Look at what actually happened.** Read the thread's full history
   (`<state_dir>/threads/<encoded-anchor>.json`) to recall what the finding
   was about. Check the file's current state and recent history
   (`git log --oneline -5 -- <path>`, `git show HEAD:<path>`) to understand
   whether the code the finding was about still exists, was fixed, or was
   removed/refactored away entirely.
3. **Decide, and act:**
   - **The finding is now moot or was fixed** (the code the thread discusses
     is genuinely gone, or the fix it asked for is visibly in place) —
     resolve it:
     ```bash
     PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/interactive-review/server.json")))["plugin_root"])')
     PYTHONPATH="$PLUGIN_ROOT" STATE_DIR="$STATE_DIR" \
       python3 -m skills._shared.web_companion.resolve_cli --anchor "<the anchor from the payload>"
     ```
   - **The finding still applies, the code just moved further than the
     search window** — append a note explaining where it went, using the
     same `.reply.md`/`.reply.meta.json`/`reply_cli.py` flow as an ordinary
     answer (see Mode D above), with `anchor` set to the *old* anchor from
     the payload (the thread is still filed there — a resync only moves it
     automatically when the text can be found; append your note where it
     currently lives).
   - **Genuinely unclear** — append a note saying so and asking the user to
     confirm, same mechanism as above. Never resolve when unsure.
4. **End your turn. No terminal output.** Same as any other watcher event.
```

- [ ] **Step 3: Document `resolve_cli.py` for general use, not just orphaned anchors**

In the "## Response style guide" section, add a new bullet:

```markdown
- **Resolving a thread.** Whenever you fix and verify a finding a thread
  discusses (not just for `anchor_orphaned` events — this applies any time,
  including mid-review), resolve it explicitly rather than leaving it open
  with a "fixed" note in the body:
  ```bash
  PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/interactive-review/server.json")))["plugin_root"])')
  PYTHONPATH="$PLUGIN_ROOT" STATE_DIR="$STATE_DIR" \
    python3 -m skills._shared.web_companion.resolve_cli --anchor "<anchor>"
  ```
  This is a hard delete (this skill's resolve model is "resolved means
  gone") — only do this once you have actually verified the fix, not on the
  strength of a plan to fix it.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/interactive_review/SKILL.md
git commit -m "Document live sync, the anchor_orphaned event, and resolve_cli.py in SKILL.md"
```

---

## Final verification

- [ ] Run the complete Python suite: `cd /Users/petros.makris/projects/claude-annotate && python3 -m pytest skills -q` — expect all green, no regressions from the pre-existing baseline.
- [ ] Run the complete Java suite: `cd /Users/petros.makris/projects/claude-annotate/ide-plugin && ./gradlew test` — expect BUILD SUCCESSFUL.
- [ ] Run the hook installer test once more standalone: `sh skills/interactive_review/tests/test_install_hooks.sh` — expect `ALL PASS`.
- [ ] Manual end-to-end smoke test against a real fixture: open `/interactive-review` on any open PR in a scratch repo, confirm `.git/hooks/post-commit` etc. now exist and contain the marker, make a trivial commit on that branch, and confirm (via the panel, or `state_dir/meta.json`'s `fetched_at`) that a resync happened within a couple of seconds with no manual action.
