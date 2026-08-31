# VS Code per-line interactive review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `show-diff`'s VS Code diff view the same per-line threaded Q&A `interactive_review` gives IntelliJ, built natively on the `webcompanion` v1 daemon, after consolidating `show-diff` and the `petros-makris-vscode` extension into `claude-annotate`.

**Architecture:** Three repos collapse to one. `show-diff` becomes a `claude-annotate` skill that creates a `webcompanion` session (`kind=show-diff`) carrying one `__meta__` item (checkout/base/head) and a snapshotted `diff.patch`, then arms `webcompanion watch`. The VS Code extension (moved into `claude-annotate/vscode-plugin/`) registers a `vscode.CommentController` scoped to the URIs it already opens for the diff, and talks to the daemon's v1 HTTP contract directly (no legacy per-skill `server.py`, no `gh`). Two small gaps in `webcompanion` itself — a way to post a thread reply from the CLI, and a way for `push` to report the session's `state_dir` — are closed first, since neither exists today and both are load-bearing for everything after them.

**Tech Stack:** Python 3.9+ (webcompanion, show_diff skill — stdlib only), plain CommonJS JavaScript (vscode-plugin, matching its existing style — no TypeScript, no bundler), bash (show-diff.sh), pytest (webcompanion tests).

**Spec:** `docs/superpowers/specs/2026-08-31-vscode-interactive-review-design.md`

## Global Constraints

- `webcompanion` changes: stdlib only, `requires-python = ">=3.9"`, every module starts `from __future__ import annotations`, tests run via `python3 -m pytest -q` from `~/projects/webcompanion`.
- No dependency on the legacy `skills/_shared/web_companion/` model anywhere in this plan — `show-diff` and the VS Code client speak `webcompanion` v1 only.
- `walkthrough` and the IntelliJ plugin are not touched by any task in this plan.
- Every `webcompanion` HTTP call sends `X-WebCompanion-Contract: 1`; on loopback no write token is required (`gate.is_owner`), so neither the skill's bash nor the VS Code extension needs to manage a token for its own calls.
- Anchors are `<path>:<side>:<line>` (side `L`=base, `R`=head), reused verbatim from `skills/interactive_review/diff.py` — this format already satisfies `webcompanion`'s `valid_anchor` check (no `..` path segments) and needs no encoding beyond standard URL-quoting of the anchor as a path segment.
- Commit messages: subject names its subject, no metaphor, per `~/.claude/CLAUDE.md`. No comments explaining "why" beyond what the surrounding files already do — match each file's existing comment density, don't invent a new house style.

---

## File Structure

    claude-annotate/
      skills/show_diff/                    # moved from dashboard, then extended
        SKILL.md
        show-diff.sh
        test-show-diff.sh
      vscode-plugin/                        # moved from env/apps/ide-themes/vscode
        package.json
        src/extension.js
        src/diff.js
        src/webcompanionClient.js           # NEW: HTTP client for the daemon
        src/reviewComments.js               # NEW: CommentController wiring
        themes/, dist/, build.sh, install.sh, uninstall.sh, .vscodeignore
        test/                               # NEW: extension tests

    webcompanion/
      src/webcompanion/
        client.py                           # gains get_item, list_items, get_thread, append_thread, list_sessions
        commands/push.py                    # gains WC_STATE_DIR in --eval output
        commands/reply.py                   # NEW
        cli.py                              # dispatches "reply"
      tests/
        test_cli_client.py                  # gains push/state_dir coverage
        test_reply.py                       # NEW

    env/apps/ide-themes/vscode/
      install.sh, build.sh                  # become one-line forwarders to claude-annotate/vscode-plugin

Responsibility boundaries: `webcompanion` owns the daemon and its CLI, and knows nothing about diffs or comments. `show_diff` owns turning a checkout/base/head into a session and answering questions about it, and knows nothing about VS Code. `vscode-plugin` owns rendering the diff and the comment UI, and knows nothing about how the answers get composed.

---

### Task 1: Move `show-diff` from `dashboard` into `claude-annotate`

**Files:**
- Create: `claude-annotate/skills/show_diff/SKILL.md`, `claude-annotate/skills/show_diff/show-diff.sh`, `claude-annotate/skills/show_diff/test-show-diff.sh` (verbatim copies of `dashboard/skills/show-diff/{SKILL.md,show-diff.sh,test-show-diff.sh}`)
- Modify: `claude-annotate/.claude-plugin/marketplace.json`
- Delete: `dashboard/skills/show-diff/` (all three files)

**Interfaces:**
- Consumes: nothing new.
- Produces: `claude-annotate/skills/show_diff/show-diff.sh <checkout> <base-rev> <head-rev|--worktree> [title]` — same signature as before, unchanged behavior. Later tasks extend this same script.

- [ ] **Step 1: Copy the three files verbatim**

```bash
mkdir -p ~/projects/claude-annotate/skills/show_diff
cp ~/projects/dashboard/skills/show-diff/SKILL.md ~/projects/claude-annotate/skills/show_diff/SKILL.md
cp ~/projects/dashboard/skills/show-diff/show-diff.sh ~/projects/claude-annotate/skills/show_diff/show-diff.sh
cp ~/projects/dashboard/skills/show-diff/test-show-diff.sh ~/projects/claude-annotate/skills/show_diff/test-show-diff.sh
chmod +x ~/projects/claude-annotate/skills/show_diff/show-diff.sh ~/projects/claude-annotate/skills/show_diff/test-show-diff.sh
```

Cross-repo history isn't preserved by this copy — `dashboard` and `claude-annotate` are unrelated git histories, so there is no move operation that would carry it. This is a plain copy-then-delete.

- [ ] **Step 2: Run the existing test script from its new home to confirm nothing broke in the move**

Run: `bash ~/projects/claude-annotate/skills/show_diff/test-show-diff.sh`
Expected: PASS, identical output to running it from `dashboard/skills/show-diff/` before the move.

- [ ] **Step 3: Add the skill to the `claude-ide-review` plugin's skill list**

In `claude-annotate/.claude-plugin/marketplace.json`, find the `claude-ide-review` plugin entry and add `"./skills/show_diff"` to its `skills` array, alongside `interactive_review` and `walkthrough`:

```json
    {
      "name": "claude-ide-review",
      "version": "0.1.0",
      "source": "./",
      "strict": false,
      "description": "Ask Claude questions on a PR diff line, a local diff line, or a code walkthrough step, inside IntelliJ or VS Code. Requires Python 3.9+ on PATH and either the companion IntelliJ plugin or the vscode-plugin extension.",
      "skills": [
        "./skills/interactive_review",
        "./skills/walkthrough",
        "./skills/show_diff",
        "./skills/annotate-doctor"
      ]
    }
```

(The description is updated now, ahead of the capability actually existing, so it doesn't need a second edit later — Task 6 is what makes the claim true.)

- [ ] **Step 4: Remove the old location and dashboard's now-unused reference**

```bash
rm -rf ~/projects/dashboard/skills/show-diff
```

`dashboard/.claude-plugin/marketplace.json` lists only one plugin entry with `"source": "./"` and no per-skill list, so nothing there needs editing — skills are discovered from the directory tree.

- [ ] **Step 5: Grep both repos for anything else pointing at the old path**

```bash
grep -rn "dashboard/skills/show-diff\|skills/show-diff" ~/projects/dashboard ~/projects/claude-annotate --include="*.md" --include="*.sh" --include="*.json" 2>/dev/null
```

Expected: no hits outside what was just deleted/created. If something else references it (a README, a cheatsheet), update it to `claude-annotate/skills/show_diff`.

- [ ] **Step 6: Commit in both repos**

```bash
cd ~/projects/dashboard
git add -A skills/show-diff
git commit -m "chore: remove show-diff, moved to claude-annotate

show-diff is becoming a claude-annotate skill so it can build directly on
the webcompanion daemon and the interactive-review machinery that already
lives there, instead of duplicating cross-repo server discovery."

cd ~/projects/claude-annotate
git add skills/show_diff .claude-plugin/marketplace.json
git commit -m "feat: add show-diff as a claude-annotate skill

Moved from dashboard, unchanged behavior. Groundwork for per-line
interactive review on VS Code diffs (see
docs/superpowers/specs/2026-08-31-vscode-interactive-review-design.md)."
```

---

### Task 2: Move `petros-makris-vscode` into `claude-annotate/vscode-plugin/`

**Files:**
- Create: `claude-annotate/vscode-plugin/{package.json,src/extension.js,src/diff.js,themes/Petros-Makris-color-theme.json,build.sh,install.sh,uninstall.sh,.vscodeignore,.gitignore,README.md}` (copies of the `env` originals)
- Modify: `claude-annotate/vscode-plugin/build.sh` (the one real content change — the markdown-preview CSS source path)
- Modify: `env/apps/ide-themes/vscode/install.sh`, `env/apps/ide-themes/vscode/build.sh` (become forwarders)
- Delete: everything else under `env/apps/ide-themes/vscode/` (`src/`, `themes/`, `dist/`, `package.json`, `.vscodeignore`, `README.md`, the committed `.vsix`)

**Interfaces:**
- Consumes: nothing new yet — this is a pure move, Tasks 7-9 add the review capability.
- Produces: the extension builds and installs from its new location with the same behavior as before, under the same `petros-makris.petros-makris-vscode` extension id.

- [ ] **Step 1: Copy everything**

```bash
mkdir -p ~/projects/claude-annotate/vscode-plugin
cp -R ~/projects/env/apps/ide-themes/vscode/. ~/projects/claude-annotate/vscode-plugin/
rm -rf ~/projects/claude-annotate/vscode-plugin/dist   # rebuilt by build.sh, not carried over stale
```

- [ ] **Step 2: Fix the one real coupling — `build.sh`'s markdown-preview CSS source**

`build.sh` reads `../markdown-preview/` today, which resolved (inside `env/apps/ide-themes/`) to a sibling directory holding the actual theme CSS. That directory is shared with the IntelliJ side (`markdown-preview/switch-intellij.sh`, `intellij-active.css`) and stays in `env` — it is not review tooling and does not move. The moved `build.sh` needs a path back to it.

In `claude-annotate/vscode-plugin/build.sh`, change:

```bash
CSS_SRC_DIR="$(cd ../markdown-preview && pwd)"
```

to:

```bash
# markdown-preview/ is a cross-IDE resource (IntelliJ's switch-intellij.sh
# reads it too) and stays in the env repo even though this extension moved
# out of it — hence the fixed path rather than a relative one.
CSS_SRC_DIR="$HOME/projects/env/apps/ide-themes/markdown-preview"
if [[ ! -d "$CSS_SRC_DIR" ]]; then
  echo "markdown-preview theme source not found at $CSS_SRC_DIR (is env checked out there?)" >&2
  exit 1
fi
```

- [ ] **Step 3: Verify the build still works from the new location**

```bash
cd ~/projects/claude-annotate/vscode-plugin
./build.sh
ls petros-makris-vscode.vsix
```

Expected: the `.vsix` builds successfully, same as it did in `env`.

- [ ] **Step 4: Turn the old `env` scripts into forwarders**

`env`'s bootstrap docs (`docs/cheatsheets/markdown-preview-themes.md`, `docs/linux-first-boot.md`, `docs/cheatsheets/editor-color-scheme.md`, the bootstrap-provisioning spec/plan) and its `@vscode` command dispatcher call `install.sh`/`build.sh` at this path. Rather than updating every doc and the dispatcher, leave thin forwarders so nothing else in `env` needs to change:

`env/apps/ide-themes/vscode/install.sh`:
```bash
#!/usr/bin/env bash
# desc: install the petros-makris-vscode extension into VS Code
# example: @vscode extension-install --build
# complete: words --build
# Moved to claude-annotate/vscode-plugin/ on 2026-08-31 — this forwards so
# env's docs and the @vscode dispatcher don't need to change.
set -euo pipefail
exec "$HOME/projects/claude-annotate/vscode-plugin/install.sh" "$@"
```

`env/apps/ide-themes/vscode/build.sh`:
```bash
#!/usr/bin/env bash
# Moved to claude-annotate/vscode-plugin/ on 2026-08-31 — this forwards so
# env's docs and the @vscode dispatcher don't need to change.
set -euo pipefail
exec "$HOME/projects/claude-annotate/vscode-plugin/build.sh" "$@"
```

```bash
chmod +x ~/projects/env/apps/ide-themes/vscode/install.sh ~/projects/env/apps/ide-themes/vscode/build.sh
```

- [ ] **Step 5: Delete everything else from the old location**

```bash
cd ~/projects/env/apps/ide-themes/vscode
rm -rf src themes dist package.json .vscodeignore README.md petros-makris-vscode.vsix .bootstrap-auto .gitignore
git status   # confirm only install.sh and build.sh remain, both forwarders
```

- [ ] **Step 6: Run the forwarder end to end**

```bash
~/projects/env/apps/ide-themes/vscode/install.sh --build
```

Expected: rebuilds via the new location's `build.sh` and installs the extension, with output identical in shape to before the move.

- [ ] **Step 7: Commit in both repos**

```bash
cd ~/projects/env
git add apps/ide-themes/vscode
git commit -m "chore: move petros-makris-vscode into claude-annotate

The diff-review half of this extension is about to grow a webcompanion
client; consolidating it with the skills it will talk to, the way
ide-plugin/ already sits alongside interactive_review. install.sh and
build.sh stay here as forwarders so nothing else in env needs to change."

cd ~/projects/claude-annotate
git add vscode-plugin
git commit -m "feat: add vscode-plugin, moved from env/apps/ide-themes/vscode

Unchanged behavior — markdown theme switching and the diff URI handler.
Groundwork for per-line interactive review on VS Code diffs."
```

---

### Task 3: `webcompanion` client and CLI gain the accessors show_diff needs

**Files:**
- Modify: `webcompanion/src/webcompanion/client.py`
- Modify: `webcompanion/src/webcompanion/commands/push.py`
- Test: `webcompanion/tests/test_cli_client.py`

**Interfaces:**
- Consumes: `Client._request(method, path, body)` (existing), `Registry(paths.state_root())` + `.rehydrate()` + `.lookup(sid)` (existing, same pattern `commands/watch.py:resolve_session_dirs` already uses).
- Produces: `Client.get_item(sid, anchor) -> dict`, `Client.list_items(sid) -> dict`, `Client.get_thread(sid, anchor) -> dict`, `Client.append_thread(sid, anchor, text, role="agent") -> dict`, `Client.list_sessions(cwd, kind=None) -> list[dict]`. `webcompanion push --eval` additionally prints `WC_STATE_DIR=`.

- [ ] **Step 1: Write the failing tests**

Append to `webcompanion/tests/test_cli_client.py`:

```python
def test_push_eval_output_includes_the_state_dir(wired, tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {}}))
    push.run(["--kind", "show-diff", "--cwd", str(tmp_path), "--title", "T",
              "--items", str(doc), "--eval"])
    out = capsys.readouterr().out
    lines = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in out.splitlines() if "=" in l}
    assert "WC_STATE_DIR" in lines
    from pathlib import Path
    assert Path(lines["WC_STATE_DIR"].strip("'\"")).is_dir()
```

Create `webcompanion/tests/test_client_thread_and_item_reads.py`:

```python
from __future__ import annotations

import json

from webcompanion.commands._common import client_from_config


def test_get_item_and_list_items_round_trip(wired, tmp_path):
    client = client_from_config()
    created = client.create("show-diff", str(tmp_path), title="T")
    client.put_items(created["sid"], {"a.py:R:1": {"checkout": str(tmp_path)}})

    items = client.list_items(created["sid"])
    assert items["a.py:R:1"]["body"] == {"checkout": str(tmp_path)}

    one = client.get_item(created["sid"], "a.py:R:1")
    assert one["body"] == {"checkout": str(tmp_path)}
    assert one["version"] == 1


def test_append_thread_then_get_thread_round_trip(wired, tmp_path):
    client = client_from_config()
    created = client.create("show-diff", str(tmp_path), title="T")

    appended = client.append_thread(created["sid"], "a.py:R:1", "why is this here?",
                                     role="user")
    assert appended["version"] == 1

    thread = client.get_thread(created["sid"], "a.py:R:1")
    assert thread["messages"][0]["text"] == "why is this here?"
    assert thread["messages"][0]["role"] == "user"


def test_list_sessions_filters_by_cwd_and_kind(wired, tmp_path):
    client = client_from_config()
    created = client.create("show-diff", str(tmp_path), title="T")

    rows = client.list_sessions(str(tmp_path), kind="show-diff")
    assert any(r["sid"] == created["sid"] for r in rows)

    other = client.list_sessions(str(tmp_path), kind="annotate")
    assert not any(r["sid"] == created["sid"] for r in other)
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `cd ~/projects/webcompanion && python3 -m pytest tests/test_client_thread_and_item_reads.py tests/test_cli_client.py::test_push_eval_output_includes_the_state_dir -v`
Expected: FAIL — `AttributeError: 'Client' object has no attribute 'get_item'` (and similar for the other new methods/output).

- [ ] **Step 3: Add the client methods**

In `webcompanion/src/webcompanion/client.py`, add alongside the existing `put_item`/`put_items`:

```python
    def get_item(self, sid: str, anchor: str) -> dict:
        quoted = urllib.parse.quote(anchor, safe="")
        _, body = self._request("GET", f"/s/{sid}/items/{quoted}")
        return body if isinstance(body, dict) else {}

    def list_items(self, sid: str) -> dict:
        _, body = self._request("GET", f"/s/{sid}/items")
        return body if isinstance(body, dict) else {}

    def get_thread(self, sid: str, anchor: str) -> dict:
        quoted = urllib.parse.quote(anchor, safe="")
        _, body = self._request("GET", f"/s/{sid}/threads/{quoted}")
        return body if isinstance(body, dict) else {"anchor": anchor, "version": 0, "messages": []}

    def append_thread(self, sid: str, anchor: str, text: str, role: str = "agent") -> dict:
        quoted = urllib.parse.quote(anchor, safe="")
        _, body = self._request("POST", f"/s/{sid}/threads/{quoted}",
                                 {"text": text, "role": role})
        return body if isinstance(body, dict) else {}

    def list_sessions(self, cwd: str, kind: str | None = None) -> list[dict]:
        query = f"?cwd={urllib.parse.quote(cwd, safe='')}"
        if kind:
            query += f"&kind={urllib.parse.quote(kind, safe='')}"
        _, body = self._request("GET", f"/api/sessions{query}")
        return body if isinstance(body, list) else []
```

- [ ] **Step 4: Make `push --eval` report the state dir**

In `webcompanion/src/webcompanion/commands/push.py`, import the existing resolver instead of duplicating it:

```python
from webcompanion.commands.watch import resolve_session_dirs, UnknownSession
```

Then in `run()`, right after `created = client.create(...)` succeeds and before the `if args.eval_:` block:

```python
    state_dir = ""
    try:
        state_dir = str(resolve_session_dirs(args.kind, created["sid"])["state_dir"])
    except UnknownSession:
        pass  # eval output just omits WC_STATE_DIR; every other line still prints
```

And inside the `if args.eval_:` block, alongside the existing three prints:

```python
        if state_dir:
            print(f"WC_STATE_DIR={shlex.quote(state_dir)}")
```

- [ ] **Step 5: Run the tests again to confirm they pass**

Run: `cd ~/projects/webcompanion && python3 -m pytest tests/test_client_thread_and_item_reads.py tests/test_cli_client.py -v`
Expected: PASS, all of them, including the pre-existing `test_cli_client.py` cases.

- [ ] **Step 6: Run the full webcompanion suite**

Run: `cd ~/projects/webcompanion && python3 -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
cd ~/projects/webcompanion
git add src/webcompanion/client.py src/webcompanion/commands/push.py \
        tests/test_cli_client.py tests/test_client_thread_and_item_reads.py
git commit -m "feat(client): add item/thread readers and list_sessions

show-diff's Mode-D step needs to read back the __meta__ item and post
thread replies; push --eval needs to report state_dir so a caller can
snapshot files into the session's own workspace, the way the legacy
per-skill model let interactive_review write diff.patch there directly."
```

---

### Task 4: `webcompanion reply` — post a thread message from the CLI

**Files:**
- Create: `webcompanion/src/webcompanion/commands/reply.py`
- Modify: `webcompanion/src/webcompanion/cli.py`
- Test: `webcompanion/tests/test_reply.py`

**Interfaces:**
- Consumes: `Client.append_thread` (Task 3).
- Produces: `webcompanion reply --sid <sid> --anchor <anchor> --text <path-to-file> [--role agent]`, exit code 0 on success. This is the CLI surface show_diff's `SKILL.md` (Task 6) instructs Claude to call — file-based, matching `update.py`'s existing pattern, so a markdown answer containing backticks or `$(...)` never touches shell interpolation.

- [ ] **Step 1: Write the failing test**

Create `webcompanion/tests/test_reply.py`:

```python
from __future__ import annotations

import json

from webcompanion.commands import push, reply
from webcompanion.commands._common import client_from_config


def test_reply_appends_to_the_thread(wired, tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"items": {}}))
    push.run(["--kind", "show-diff", "--cwd", str(tmp_path), "--title", "T",
              "--items", str(doc), "--eval"])
    sid = [l for l in capsys.readouterr().out.splitlines()
           if l.startswith("WC_SID=")][0][len("WC_SID="):]

    answer = tmp_path / "answer.md"
    answer.write_text("It's a guard clause for the empty-list case.")
    rc = reply.run(["--sid", sid, "--anchor", "a.py:R:1", "--text", str(answer)])
    assert rc == 0

    thread = client_from_config().get_thread(sid, "a.py:R:1")
    assert thread["messages"][-1]["text"] == "It's a guard clause for the empty-list case."
    assert thread["messages"][-1]["role"] == "agent"


def test_reply_reports_a_missing_file(tmp_path, capsys):
    rc = reply.run(["--sid", "whatever", "--anchor", "a.py:R:1",
                     "--text", str(tmp_path / "missing.md")])
    assert rc == 1
    assert "could not read" in capsys.readouterr().err
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd ~/projects/webcompanion && python3 -m pytest tests/test_reply.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webcompanion.commands.reply'`.

- [ ] **Step 3: Write `reply.py`, mirroring `update.py`'s file-based body pattern**

```python
"""`webcompanion reply` -- append one message to an anchor's thread.

Reads the message text from a file, never from an argv string: a Claude
answer routinely contains backticks, `$(...)`, and quotes, and interpolating
that into a shell command is exactly the injection risk interactive_review's
SKILL.md already routes around by writing files first. This command is that
same pattern, generalized off the legacy per-skill reply_cli.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from webcompanion.client import ContractMismatch, DaemonUnreachable, HttpError
from webcompanion.commands._common import client_from_config, preflight, report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="webcompanion reply")
    p.add_argument("--sid", required=True)
    p.add_argument("--anchor", required=True)
    p.add_argument("--text", required=True,
                   help="path to a file containing the reply's raw text")
    p.add_argument("--role", default="agent")
    return p


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    try:
        text = Path(args.text).read_text()
    except OSError as e:
        print(f"webcompanion: could not read {args.text}: {e}", file=sys.stderr)
        return 1

    client = client_from_config()
    rc = preflight(client)
    if rc is not None:
        return rc

    try:
        client.append_thread(args.sid, args.anchor, text, role=args.role)
    except (DaemonUnreachable, ContractMismatch, HttpError) as e:
        return report(e)
    return 0
```

- [ ] **Step 4: Wire it into the CLI dispatcher**

In `webcompanion/src/webcompanion/cli.py`, find where `push`/`update`/`watch`/`end` are dispatched by subcommand name and add `reply` the same way (import `from webcompanion.commands import reply` and add its case to the dispatch table/if-chain).

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `cd ~/projects/webcompanion && python3 -m pytest tests/test_reply.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `cd ~/projects/webcompanion && python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd ~/projects/webcompanion
git add src/webcompanion/commands/reply.py src/webcompanion/cli.py tests/test_reply.py
git commit -m "feat: add \`webcompanion reply\` to post a thread message from the CLI

No existing command lets a skill answer a question without either curling
the route by hand (and fighting shell-quoting on markdown replies) or
reaching into Client._request directly. This is the missing counterpart
to \`update\` for items."
```

---

### Task 5: `show-diff.sh` creates a `webcompanion` session and arms the watcher

**Files:**
- Modify: `claude-annotate/skills/show_diff/show-diff.sh`
- Test: `claude-annotate/skills/show_diff/test-show-diff.sh` (extended)

**Interfaces:**
- Consumes: `webcompanion push --kind show-diff --cwd <checkout> --items <file> --title <title> --eval` (existing CLI, Task 3's `WC_STATE_DIR` addition).
- Produces: after a successful diff open, `show-diff.sh` prints `WC_SID=`, `WC_URL=`, `WC_STATE_DIR=` lines (mirroring `webcompanion push --eval`'s own output shape) so the calling skill instructions (Task 6) can pick them up, and it writes `diff.patch` into the session's `state_dir`.

- [ ] **Step 1: Write the failing test**

`test-show-diff.sh` is a plain bash test script (no pytest here — this repo's shell scripts are tested with bash assertions in-file, matching the existing file's own style). Read `claude-annotate/skills/show_diff/test-show-diff.sh` first to match its existing assertion style, then add a case shaped like:

```bash
# --- new: a successful run also creates a webcompanion session ---
test_creates_webcompanion_session() {
  local out
  out="$(bash "$SHOW_DIFF_SH" "$FIXTURE_REPO" "$BASE_SHA" "$HEAD_SHA" 2>&1)"
  assert_contains "$out" "WC_SID="
  assert_contains "$out" "WC_URL="
}
run_test test_creates_webcompanion_session
```

(Match the fixture-setup and `assert_contains`/`run_test` helper names actually defined earlier in the file — read it first, this sketch names the shape, not the literal helper API.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `bash ~/projects/claude-annotate/skills/show_diff/test-show-diff.sh`
Expected: FAIL — no `WC_SID=` in the output, since `show-diff.sh` doesn't call `webcompanion` yet.

- [ ] **Step 3: Add the session-creation step to `show-diff.sh`**

After the existing `echo "opened in VS Code: $TITLE"` block and its trailing `echo` lines (the script's last lines today), add:

```bash
# ---------------------------------------------------------------------------
# Interactive review: create a webcompanion session for this diff so VS
# Code's comment UI (vscode-plugin) has something to talk to. A missing or
# unreachable webcompanion is not a reason to fail a diff that already
# opened -- it degrades to the old read-only behavior, silently.
# ---------------------------------------------------------------------------
if command -v webcompanion >/dev/null 2>&1; then
  ITEMS_JSON="$(mktemp)"
  trap 'rm -f "$ITEMS_JSON"' EXIT
  if $WORKTREE; then
    META_HEAD="worktree"
  else
    META_HEAD="$HEAD_SHA"
  fi
  REPO="$REPO" BASE_SHA="$BASE_SHA" META_HEAD="$META_HEAD" python3 -c '
import json, os
print(json.dumps({"items": {"__meta__": {
    "checkout": os.environ["REPO"],
    "base": os.environ["BASE_SHA"],
    "head": os.environ["META_HEAD"],
}}}))
' > "$ITEMS_JSON"

  WC_OUT="$(webcompanion push --kind show-diff --cwd "$REPO" \
    --title "$TITLE" --items "$ITEMS_JSON" --eval 2>&1)" && {
    eval "$WC_OUT"
    if [[ -n "${WC_STATE_DIR:-}" ]]; then
      if $WORKTREE; then
        git -C "$REPO" diff --no-color "$BASE_SHA" > "$WC_STATE_DIR/diff.patch" 2>/dev/null || true
      else
        git -C "$REPO" diff --no-color "$BASE_SHA..$HEAD_SHA" > "$WC_STATE_DIR/diff.patch" 2>/dev/null || true
      fi
    fi
    echo "$WC_OUT"
    echo "  comments: open in VS Code, click a line, ask a question"
  } || echo "  (webcompanion unreachable -- diff opened read-only: $WC_OUT)" >&2
fi
```

`eval "$WC_OUT"` is safe here the same way it already is in `webcompanion`'s own docs: `push --eval`'s own `shlex.quote` on every value is what makes this eval not an injection path, not the caller's care.

- [ ] **Step 4: Run the test again to confirm it passes**

Run: `bash ~/projects/claude-annotate/skills/show_diff/test-show-diff.sh`
Expected: PASS.

- [ ] **Step 5: Run it once by hand against a real repo to see the real output**

Run: `~/projects/claude-annotate/skills/show_diff/show-diff.sh ~/projects/claude-annotate HEAD~1 --worktree`
Expected: diff opens in VS Code as before, plus `WC_SID=...`, `WC_URL=...`, `WC_STATE_DIR=...`, and the comments line — confirm `$WC_STATE_DIR/diff.patch` exists and has real diff content.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/show_diff/show-diff.sh skills/show_diff/test-show-diff.sh
git commit -m "feat(show-diff): create a webcompanion session for every opened diff

Snapshots diff.patch into the session's state_dir (same convention
interactive_review already uses) and reports WC_SID/WC_URL/WC_STATE_DIR so
the calling skill can arm a watcher. Falls back to today's read-only
behavior if webcompanion isn't installed."
```

---

### Task 6: `show_diff/SKILL.md` documents session hand-off and Mode-D answering

**Files:**
- Modify: `claude-annotate/skills/show_diff/SKILL.md`

**Interfaces:**
- Consumes: `show-diff.sh`'s new `WC_SID=`/`WC_STATE_DIR=` output (Task 5), `webcompanion watch --kind show-diff --sid <sid>` (existing), `webcompanion reply --sid --anchor --text <file>` (Task 4).
- Produces: the documented Mode-D procedure a running Claude session follows when a `WEBCOMPANION_EVENT skill=show-diff ...` banner arrives.

- [ ] **Step 1: Add an "Arm the watcher" section after step 5 ("Run the script, relay its output, and stop")**

Insert into `SKILL.md`, right after the existing "Never summarise the diff" section title but before its body (so arming happens as part of the same turn the diff opens, not a separate ask):

```markdown
## Arm the watcher

If the script's output included a `WC_SID=` line, comments are live for this
diff in VS Code. Arm a watcher immediately, in the same turn:

```bash
Monitor: command = "webcompanion watch --kind show-diff --sid <WC_SID>", persistent = true
description: "show-diff-review sid=<WC_SID>"
```

The watcher prints the same banners `interactive_review`'s watcher does:
`WEBCOMPANION_EVENT skill=show-diff sid=<sid> event_id=<id>` (followed by
`---payload---`, the event JSON, `---end---`), `WEBCOMPANION_FINISHED`,
`WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`. Each wakes you once; the
watcher stays alive across many questions until the session ends.

If the script's output had no `WC_SID=` line, `webcompanion` was
unreachable — the diff is open read-only and there is nothing to arm.

## Mode D — answering a question on a diff line

You wake here when a task-notification's first stdout line is one of the
`WEBCOMPANION_*` banners above, for a `skill=show-diff` session.

1. **Parse the banner** for `sid` and `event_id`. Read the payload between
   `---payload---` and `---end---`: `{"anchor": "<path>:<side>:<line>",
   "text": "<question>", "images": [...]}`.
2. **Find the session's state_dir.** You have it already if you created this
   session's watcher this turn (`WC_STATE_DIR` from Task 5's output). There is
   no documented way to re-derive it later — `webcompanion` has no "look up a
   session's state_dir by sid" command — so keep the `WC_STATE_DIR` value from
   when you armed the watcher; it does not change for the life of the
   session.
3. **Read `<state_dir>/diff.patch`** and the item at anchor `__meta__`
   (`webcompanion` has no "get one item" CLI, so read it via
   `python3 -c` importing `webcompanion.client`):

   ```bash
   python3 -c '
   from webcompanion.commands._common import client_from_config
   import json
   print(json.dumps(client_from_config().get_item("<sid>", "__meta__")["body"]))
   '
   ```

   This gives `{"checkout": ..., "base": ..., "head": ...}` — use `checkout`
   to `Read`/`Grep` surrounding source for context beyond the diff hunk.
4. **Compose a short, code-aware answer** in markdown, 2-4 sentences
   typically, fenced code blocks for snippet suggestions. If you spot a real
   bug, flag it and suggest a fix as a code block — never modify the
   checkout itself, this is a read-only review view exactly like
   `interactive_review`.
5. **Write the answer to a file, then post it** — never interpolate the
   answer into a shell command; it may contain backticks, quotes, or
   `$(...)`:

   ```bash
   webcompanion reply --sid <sid> --anchor "<anchor>" --text <path-to-answer-file>
   ```
```

- [ ] **Step 2: Read the whole edited file back and confirm it flows as one document**

Read `claude-annotate/skills/show_diff/SKILL.md` top to bottom. Confirm the new sections sit between "Run the script..." (step 5) and "Judgement calls" without duplicating or contradicting "Never summarise the diff" (which still governs the *initial* turn's output — Mode D answering a specific question the user asked is not "summarising the diff" and is explicitly a different situation, worth one sentence distinguishing them if it reads ambiguously).

- [ ] **Step 3: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/show_diff/SKILL.md
git commit -m "docs(show-diff): document arming the watcher and answering questions

Mirrors interactive_review's Mode D, adapted to webcompanion's CLI (reply
instead of writing .reply.md/.reply.meta.json files for a legacy watcher
to pick up) and to a local checkout instead of a PR ref."
```

---

### Task 7: `webcompanionClient.js` — the VS Code extension's HTTP client

**Files:**
- Create: `claude-annotate/vscode-plugin/src/webcompanionClient.js`
- Test: `claude-annotate/vscode-plugin/test/webcompanionClient.test.js`
- Modify: `claude-annotate/vscode-plugin/package.json` (add `devDependencies`: `mocha`, and a `scripts.test` entry)

**Interfaces:**
- Consumes: Node's built-in `http` module (no dependency added — matches the rest of this extension's zero-dependency style) against a `webcompanion` daemon's base URL read from `~/.claude/webcompanion/config.json`.
- Produces: `listSessions(cwd, kind)`, `getPoll(sid)`, `getThread(sid, anchor)`, `submit(sid, anchor, text)`, each returning a `Promise`. Task 8 and 9 consume these by name.

- [ ] **Step 1: Write the failing test**

Create `claude-annotate/vscode-plugin/test/webcompanionClient.test.js`. It spins up a minimal HTTP server standing in for the daemon (same idea as `webcompanion`'s own `wired` fixture, done in plain Node since this file has no Python available to it):

```js
const assert = require('assert');
const http = require('http');
const { WebCompanionClient } = require('../src/webcompanionClient');

function fakeDaemon(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

describe('WebCompanionClient', () => {
  let server;
  afterEach(() => server && server.close());

  it('listSessions sends cwd and kind as query params', async () => {
    let seenUrl;
    server = await fakeDaemon((req, res) => {
      seenUrl = req.url;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify([{ sid: 's1', kind: 'show-diff' }]));
    });
    const client = new WebCompanionClient(`http://127.0.0.1:${server.address().port}`);
    const rows = await client.listSessions('/repo', 'show-diff');
    assert.strictEqual(rows[0].sid, 's1');
    assert.ok(seenUrl.includes('cwd=%2Frepo'));
    assert.ok(seenUrl.includes('kind=show-diff'));
  });

  it('submit posts anchor and text as JSON, returns event_id', async () => {
    let body = '';
    server = await fakeDaemon((req, res) => {
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        res.writeHead(202, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ event_id: 'e1' }));
      });
    });
    const client = new WebCompanionClient(`http://127.0.0.1:${server.address().port}`);
    const result = await client.submit('sid1', 'a.py:R:1', 'why?');
    assert.strictEqual(result.event_id, 'e1');
    assert.deepStrictEqual(JSON.parse(body), { anchor: 'a.py:R:1', text: 'why?' });
  });

  it('a 426 response rejects with a ContractMismatch-shaped error', async () => {
    server = await fakeDaemon((req, res) => {
      res.writeHead(426, { 'Content-Type': 'text/plain' });
      res.end('the client speaks contract 1, this daemon speaks 2');
    });
    const client = new WebCompanionClient(`http://127.0.0.1:${server.address().port}`);
    await assert.rejects(client.getPoll('sid1'), /contract/);
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd ~/projects/claude-annotate/vscode-plugin
npm install --save-dev mocha
npx mocha test/webcompanionClient.test.js
```
Expected: FAIL — `Cannot find module '../src/webcompanionClient'`.

- [ ] **Step 3: Write `webcompanionClient.js`**

```js
// HTTP client for the webcompanion daemon, used by the diff comment UI.
// Zero dependencies, matching the rest of this extension: plain `http`,
// same as diff.js's own git subprocess calls avoid pulling in a library.

const http = require('http');
const https = require('https');
const { URL } = require('url');

const CONTRACT = 1;

class WebCompanionClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  _request(method, path, body) {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const mod = url.protocol === 'https:' ? https : http;
      const data = body !== undefined ? JSON.stringify(body) : null;
      const headers = { 'X-WebCompanion-Contract': String(CONTRACT) };
      if (data) headers['Content-Type'] = 'application/json';
      const req = mod.request(url, { method, headers }, (res) => {
        let raw = '';
        res.on('data', (c) => (raw += c));
        res.on('end', () => {
          let parsed = raw;
          try { parsed = JSON.parse(raw); } catch { /* plain text error body */ }
          if (res.statusCode === 426) {
            reject(new Error(`webcompanion contract mismatch: ${raw}`));
            return;
          }
          if (res.statusCode >= 400) {
            reject(new Error(`webcompanion ${method} ${path} -> ${res.statusCode}: ${raw}`));
            return;
          }
          resolve(parsed);
        });
      });
      req.on('error', reject);
      if (data) req.write(data);
      req.end();
    });
  }

  listSessions(cwd, kind) {
    let path = `/api/sessions?cwd=${encodeURIComponent(cwd)}`;
    if (kind) path += `&kind=${encodeURIComponent(kind)}`;
    return this._request('GET', path);
  }

  getPoll(sid) {
    return this._request('GET', `/s/${sid}/poll`);
  }

  getThread(sid, anchor) {
    return this._request('GET', `/s/${sid}/threads/${encodeURIComponent(anchor)}`);
  }

  submit(sid, anchor, text) {
    return this._request('POST', `/s/${sid}/api/submit`, { anchor, text });
  }
}

module.exports = { WebCompanionClient };
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd ~/projects/claude-annotate/vscode-plugin && npx mocha test/webcompanionClient.test.js
```
Expected: PASS, all three.

- [ ] **Step 5: Add the test script to `package.json`**

```json
    "scripts": {
      "test": "mocha test/**/*.test.js"
    },
    "devDependencies": {
      "mocha": "^10.0.0"
    }
```

Run: `cd ~/projects/claude-annotate/vscode-plugin && npm test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/claude-annotate/vscode-plugin
git add src/webcompanionClient.js test/webcompanionClient.test.js package.json package-lock.json
git commit -m "feat: add webcompanionClient.js, this extension's first test suite

Zero-dependency HTTP client for the daemon's v1 contract. First automated
tests in this extension at all -- prior code (theme switching, the diff
URI handler) had none."
```

---

### Task 8: Wire a `CommentController` to the open diff

**Files:**
- Create: `claude-annotate/vscode-plugin/src/reviewComments.js`
- Modify: `claude-annotate/vscode-plugin/src/extension.js` (register the new module, mirroring how `diff.register(context)` is already called)
- Modify: `claude-annotate/vscode-plugin/src/diff.js` (export the info `reviewComments.js` needs about the currently-open diff)
- Test: `claude-annotate/vscode-plugin/test/reviewComments.test.js`

**Interfaces:**
- Consumes: `diff.js`'s per-file entries (`{name, originalUri, modifiedUri, status}` — the same shape already built for `DiffTree`, at the point `showFileList` is called), `WebCompanionClient` (Task 7).
- Produces: `reviewComments.setCurrentDiff({ repo, base, head, worktree, sid, files })` (called from `diff.js` once a diff opens and its webcompanion session is known) and `reviewComments.register(context)` (called once from `extension.js`, mirroring `diff.register(context)`).

- [ ] **Step 1: Write the failing test**

`vscode` itself is only resolvable inside a running extension host, so this module's pure logic — turning a clicked `(uri, range)` into a `path:side:line` anchor — is written to be testable without `vscode` at all: a small pure function, exported separately from the `vscode.CommentController` wiring that calls it.

Create `claude-annotate/vscode-plugin/test/reviewComments.test.js`:

```js
const assert = require('assert');
const { anchorFor } = require('../src/reviewComments');

describe('anchorFor', () => {
  const files = [
    { name: 'src/a.py', originalRef: 'base-sha', modifiedRef: 'head-sha' },
  ];

  it('builds an L-side anchor for the original document', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/a.py', ref: 'base-sha' }, 5),
      'src/a.py:L:6');
  });

  it('builds an R-side anchor for the modified document', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/a.py', ref: 'head-sha' }, 5),
      'src/a.py:R:6');
  });

  it('builds an R-side anchor for a live worktree file (no ref)', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/a.py', ref: '' }, 5, { worktree: true }),
      'src/a.py:R:6');
  });

  it('returns null for a file not part of the tracked diff', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/unrelated.py', ref: 'head-sha' }, 5),
      null);
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd ~/projects/claude-annotate/vscode-plugin && npx mocha test/reviewComments.test.js
```
Expected: FAIL — `Cannot find module '../src/reviewComments'`.

- [ ] **Step 3: Write the pure `anchorFor` function and the `vscode`-dependent wiring around it**

```js
// Turns a document + 0-based line into this session's <path>:<side>:<line>
// anchor, or null when the document isn't part of the diff currently open.
// Kept separate from the vscode.CommentController wiring below so it is
// testable without a running extension host.
function anchorFor(files, { gitPath, ref }, line, { worktree = false } = {}) {
  const file = files.find((f) => f.name === gitPath);
  if (!file) return null;
  let side;
  if (worktree && !ref) side = 'R';
  else if (ref === file.originalRef) side = 'L';
  else if (ref === file.modifiedRef) side = 'R';
  else return null;
  return `${gitPath}:${side}:${line + 1}`; // anchors are 1-based, VS Code ranges are 0-based
}

let vscode;
try { vscode = require('vscode'); } catch { /* loaded outside an extension host, e.g. under mocha */ }

const { WebCompanionClient } = require('./webcompanionClient');
const { loadConfig } = require('./webcompanionConfig');

let controller = null;
let current = null; // { repo, base, head, worktree, sid, files }

function commentingRangeProvider(document) {
  if (!current) return [];
  const decoded = decodeDocumentRef(document.uri);
  if (!decoded) return [];
  const anchor = anchorFor(current.files, decoded, 0, { worktree: current.worktree });
  if (anchor === null && !current.files.some((f) => f.name === decoded.gitPath)) return [];
  return [new vscode.Range(0, 0, document.lineCount - 1, 0)];
}

// pmdiff:// URIs carry {repo, ref, gitPath} base64-encoded in the query,
// exactly as diff.js's own decodeBlobUri does -- duplicated rather than
// imported, since diff.js does not export it and this module must not
// reach into diff.js's private encoding to stay independently testable.
function decodeDocumentRef(uri) {
  if (uri.scheme === 'pmdiff') {
    try {
      const { repo, ref, gitPath } = JSON.parse(Buffer.from(uri.query, 'base64').toString('utf8'));
      return { repo, ref, gitPath };
    } catch { return null; }
  }
  if (current && uri.scheme === 'file' && current.worktree) {
    const path = require('path');
    const rel = path.relative(current.repo, uri.fsPath).split(path.sep).join('/');
    if (current.files.some((f) => f.name === rel)) return { repo: current.repo, ref: '', gitPath: rel };
  }
  return null;
}

function setCurrentDiff(info) {
  current = info;
}

function register(context) {
  if (!vscode) return;
  controller = vscode.comments.createCommentController('petrosMakrisReview', 'Diff review');
  controller.commentingRangeProvider = { provideCommentingRanges: commentingRangeProvider };
  context.subscriptions.push(controller);

  context.subscriptions.push(
    vscode.commands.registerCommand('petrosMakris.submitReviewComment', async (reply) => {
      const decoded = decodeDocumentRef(reply.thread.uri);
      if (!current || !decoded) return;
      const line = reply.thread.range.start.line;
      const anchor = anchorFor(current.files, decoded, line, { worktree: current.worktree });
      if (!anchor) return;
      const cfg = await loadConfig();
      const client = new WebCompanionClient(`http://${cfg.bind}:${cfg.port}`);
      await client.submit(current.sid, anchor, reply.text);
      reply.thread.comments = [
        ...reply.thread.comments,
        { body: reply.text, mode: vscode.CommentMode.Preview,
          author: { name: 'You' } },
      ];
      reply.thread.contextValue = 'pending';
    }),
  );
}

module.exports = { anchorFor, setCurrentDiff, register };
```

`webcompanionConfig.js` doesn't exist yet — Task 9 needs the same "read `~/.claude/webcompanion/config.json`" logic for its poll loop, so it's factored out there rather than duplicated here; this task's `require('./webcompanionConfig')` is satisfied once Task 9's Step 1 creates it. (If executing tasks out of order, stub it minimally here first: `module.exports = { loadConfig: async () => ({ bind: '127.0.0.1', port: 3080 }) }`, then let Task 9 replace it with the real file-reading version — tests for both tasks still pass either way since neither test exercises `loadConfig` directly.)

- [ ] **Step 4: Create the `package.json` `comments` contribution**

VS Code requires a comment controller's ID declared in `package.json` for the reply command to show up as a submit button:

```json
    "commands": [
      ...,
      { "command": "petrosMakris.submitReviewComment", "title": "Ask Claude" }
    ]
```

- [ ] **Step 5: Register from `extension.js`**

Next to `diff.register(context);` in `activate()`:

```js
  const reviewComments = require('./reviewComments');
  reviewComments.register(context);
```

- [ ] **Step 6: Have `diff.js` report the open diff's files to `reviewComments`**

In `diff.js`, at the point `showFileList(repo, label, entries)` is called (after the diff successfully opens), also call:

```js
require('./reviewComments').setCurrentDiff({
  repo,
  worktree: /* the existing `live`/worktree boolean already in scope here */,
  files: entries.map((e) => ({
    name: e.name,
    originalRef: /* the base sha already in scope here */,
    modifiedRef: /* the head sha, or '' for worktree, already in scope here */,
  })),
  sid: /* not known yet at this point -- see Step 7 */,
});
```

(Read the surrounding function to use its actual local variable names for base/head/live — this plan names what must be passed, not what to call the existing locals.)

- [ ] **Step 7: Get the `sid` from `show-diff.sh` into the running extension**

The extension doesn't run the shell script and can't read its stdout. It needs another channel: after `webcompanion push` returns `WC_SID`, `show-diff.sh` fires the *same* diff URI a second time, now carrying `sid` too. The window is already open and already holds this exact repo/base/head, so the handler's existing file-list computation is idempotent — the only new effect is that `sid` is now present for `diff.js` to read.

Task 5's session-creation block already runs after the first `open "$URI"` call succeeds (it's appended after the existing "opened in VS Code" echo block). Add, at the end of that same block, once `WC_STATE_DIR` is known:

```bash
    SID_URI=$(REPO="$REPO" BASE_SHA="$BASE_SHA" HEAD_SHA="$HEAD_SHA" TITLE="$TITLE" \
      EXTENSION_ID="$EXTENSION_ID" WC_SID="$WC_SID" python3 -c '
import os, urllib.parse
q = urllib.parse.urlencode({
    "repo":  os.environ["REPO"],
    "base":  os.environ["BASE_SHA"],
    "head":  os.environ["HEAD_SHA"],
    "title": os.environ["TITLE"],
    "sid":   os.environ["WC_SID"],
})
print("vscode://" + os.environ["EXTENSION_ID"] + "/diff?" + q)')
    open "$SID_URI"
```

In `diff.js`'s URI handler, read `sid` from the query (empty string when absent, exactly like every other query param it already reads) and pass it through to `setCurrentDiff` alongside `repo`/`files`/`worktree`.

- [ ] **Step 8: Run the JS test suite**

```bash
cd ~/projects/claude-annotate/vscode-plugin && npm test
```
Expected: PASS (the `anchorFor` tests from Step 1; the `vscode`-dependent code isn't exercised by this test file at all, by design).

- [ ] **Step 9: Manual end-to-end check**

Run `show-diff.sh` against a real repo, click a changed line in VS Code, confirm a comment box appears (empty thread, since nothing's been submitted yet).

- [ ] **Step 10: Commit**

```bash
cd ~/projects/claude-annotate/vscode-plugin
git add src/reviewComments.js src/diff.js src/extension.js package.json test/reviewComments.test.js
git commit -m "feat: register a CommentController on the open diff

Every line of a diff show-diff opens becomes askable. anchorFor() is the
one piece of logic under test without a running extension host; the
vscode.CommentController wiring around it is exercised manually until
Task 9's @vscode/test-electron setup exists."
```

---

### Task 9: Poll for replies and update comment threads

**Files:**
- Create: `claude-annotate/vscode-plugin/src/webcompanionConfig.js`
- Modify: `claude-annotate/vscode-plugin/src/reviewComments.js`
- Test: `claude-annotate/vscode-plugin/test/webcompanionConfig.test.js`

**Interfaces:**
- Consumes: `WebCompanionClient.getPoll(sid)`, `WebCompanionClient.getThread(sid, anchor)` (Task 7).
- Produces: `loadConfig() -> Promise<{bind, port}>`; a running poll loop (started from `setCurrentDiff`) that keeps every open `CommentThread`'s `comments` array in sync with the daemon.

- [ ] **Step 1: Write the failing test for config loading**

Create `claude-annotate/vscode-plugin/test/webcompanionConfig.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadConfig } = require('../src/webcompanionConfig');

describe('loadConfig', () => {
  it('reads bind and port from the config file', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wc-'));
    const file = path.join(dir, 'config.json');
    fs.writeFileSync(file, JSON.stringify({ bind: '127.0.0.1', port: 4242, token: 'x' }));
    const cfg = await loadConfig(file);
    assert.strictEqual(cfg.port, 4242);
    assert.strictEqual(cfg.bind, '127.0.0.1');
  });

  it('rejects when the config file does not exist', async () => {
    await assert.rejects(loadConfig('/nonexistent/config.json'));
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd ~/projects/claude-annotate/vscode-plugin && npx mocha test/webcompanionConfig.test.js
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write `webcompanionConfig.js`**

```js
// Reads webcompanion's own config file -- the fixed, documented path every
// consumer (the CLI, and now this extension) reads, per the daemon's
// "one file, no discovery poll" design.

const fs = require('fs/promises');
const os = require('os');
const path = require('path');

const DEFAULT_PATH = path.join(os.homedir(), '.claude', 'webcompanion', 'config.json');

async function loadConfig(configPath = DEFAULT_PATH) {
  const raw = await fs.readFile(configPath, 'utf8');
  return JSON.parse(raw);
}

module.exports = { loadConfig, DEFAULT_PATH };
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd ~/projects/claude-annotate/vscode-plugin && npx mocha test/webcompanionConfig.test.js
```
Expected: PASS.

- [ ] **Step 5: Add the poll loop to `reviewComments.js`**

Replace the stub `require('./webcompanionConfig')` from Task 8 (now real) and extend `setCurrentDiff`:

```js
const POLL_MS = 2000;
let pollTimer = null;
const openThreads = new Map(); // anchor -> vscode.CommentThread

function setCurrentDiff(info) {
  current = info;
  openThreads.clear();
  if (pollTimer) clearInterval(pollTimer);
  if (!info.sid) return;
  pollTimer = setInterval(() => pollOnce().catch(() => {}), POLL_MS);
}

async function pollOnce() {
  if (!current || !current.sid) return;
  const cfg = await loadConfig();
  const client = new WebCompanionClient(`http://${cfg.bind}:${cfg.port}`);
  const status = await client.getPoll(current.sid);
  for (const [anchor, version] of Object.entries(status.threads || {})) {
    const known = openThreads.get(anchor);
    if (known && known.version === version) continue;
    const thread = await client.getThread(current.sid, anchor);
    renderThread(anchor, thread, version);
  }
}

function renderThread(anchor, thread, version) {
  const [gitPath, side, lineStr] = anchor.split(':');
  const line = parseInt(lineStr, 10) - 1;
  const file = current.files.find((f) => f.name === gitPath);
  if (!file) return;
  const uri = side === 'L'
    ? vscode.Uri.from({ scheme: 'pmdiff', path: gitPath,
        query: Buffer.from(JSON.stringify({ repo: current.repo, ref: file.originalRef, gitPath })).toString('base64') })
    : (current.worktree
        ? vscode.Uri.file(path.join(current.repo, gitPath))
        : vscode.Uri.from({ scheme: 'pmdiff', path: gitPath,
            query: Buffer.from(JSON.stringify({ repo: current.repo, ref: file.modifiedRef, gitPath })).toString('base64') }));
  const range = new vscode.Range(line, 0, line, 0);
  const comments = (thread.messages || []).map((m) => ({
    body: m.text,
    mode: vscode.CommentMode.Preview,
    author: { name: m.role === 'agent' ? 'Claude' : 'You' },
  }));
  let entry = openThreads.get(anchor);
  if (!entry) {
    const vsThread = controller.createCommentThread(uri, range, comments);
    entry = { vsThread, version };
    openThreads.set(anchor, entry);
  } else {
    entry.vsThread.comments = comments;
    entry.version = version;
  }
}
```

Add `path` and `vscode` requires already present at the top of the file (`path` needs adding alongside the existing `require('path')` used inside `decodeDocumentRef`'s worktree branch — hoist it to the top-level requires instead of importing it inline there).

- [ ] **Step 6: Run the full JS suite**

```bash
cd ~/projects/claude-annotate/vscode-plugin && npm test
```
Expected: PASS — `anchorFor` and `loadConfig` tests, unaffected by the poll loop (untested directly here; it composes two already-tested pieces and `vscode`-only APIs, exercised manually next).

- [ ] **Step 7: Manual end-to-end check**

Open a diff via `show-diff.sh`, click a line, type a question, submit. Have Claude's `show_diff` skill (Task 6) answer it via `webcompanion reply`. Confirm the comment appears in VS Code within ~2 seconds without reloading the window.

- [ ] **Step 8: Commit**

```bash
cd ~/projects/claude-annotate/vscode-plugin
git add src/webcompanionConfig.js src/reviewComments.js test/webcompanionConfig.test.js
git commit -m "feat: poll webcompanion for reply threads and render them as comments

2s polling, not SSE -- simpler to get right in an extension host with no
reconnect/backoff logic needed, and show-diff sessions are short-lived
enough that the latency difference doesn't matter."
```

---

