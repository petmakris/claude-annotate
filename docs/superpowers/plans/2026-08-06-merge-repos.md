# Repository Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `claude-ide-review` and `web-companion` into this repository so the shared Python server exists in exactly one place, edited in place.

**Architecture:** This repository becomes a marketplace publishing two plugins that share one root directory. `claude-annotate` exposes `./skills/annotate`; `claude-ide-review` exposes `./skills/interactive_review` and `./skills/walkthrough`. Because the plugin boundary is the `skills` array in `.claude-plugin/marketplace.json` rather than a directory, `skills/_shared/web_companion/` sits once in a tree that all three skills import from. The vendoring machinery that kept two copies in sync is deleted.

**Tech Stack:** Python 3.12 standard library only (no runtime dependencies), pytest for tests, GitHub Actions for CI, Gradle + JDK 25 for the IntelliJ plugin under `ide-plugin/`.

**Spec:** `docs/superpowers/specs/2026-08-05-merge-repos-design.md`

## Global Constraints

- Python 3 standard library only. Do not add a runtime dependency.
- All imports of the engine are written `skills._shared.web_companion.*`. Do not rewrite them; the merge is designed so no import changes.
- `skills/_shared/web_companion/` keeps **this** repository's copy (web-companion `7bc4988`). Never copy `skills/_shared/` from `claude-ide-review` — its copy is older.
- Source repositories are at `~/projects/claude-ide-review` and `~/projects/web-companion`. Read from them; do not modify them until Task 7.
- Test baseline before any change: `python3 -m pytest skills -q` reports **633 passed**. Each task below states its expected count; a mismatch means something was dropped and must be found before continuing.
- macOS `sed` requires an explicit empty backup suffix: `sed -i '' …`.
- Commit after every task.

---

### Task 1: Absorb the two skills and the IntelliJ plugin

Pure file movement, no edits. The absorbed skills are knowingly broken at the end of this task — Task 2 repairs them. The deliverable is that every test from both repositories runs green in one tree.

**Files:**
- Create: `skills/interactive_review/` (copied from `~/projects/claude-ide-review/skills/interactive_review/`)
- Create: `skills/walkthrough/` (copied from `~/projects/claude-ide-review/skills/walkthrough/`)
- Create: `ide-plugin/` (copied from `~/projects/claude-ide-review/ide-plugin/`)

**Interfaces:**
- Consumes: nothing.
- Produces: the directories `skills/interactive_review/`, `skills/walkthrough/`, `ide-plugin/`. Later tasks reference `skills/interactive_review/SKILL.md`, `skills/walkthrough/SKILL.md`, and `ide-plugin/build.gradle.kts`.

- [ ] **Step 1: Record the baseline**

Run: `python3 -m pytest skills -q`
Expected: `633 passed`

- [ ] **Step 2: Copy the two skill directories**

`--exclude` keeps compiled bytecode and pytest state out of the tree.

```bash
cd ~/projects/claude-annotate
rsync -a --exclude='__pycache__' --exclude='.pytest_cache' \
  ~/projects/claude-ide-review/skills/interactive_review/ skills/interactive_review/
rsync -a --exclude='__pycache__' --exclude='.pytest_cache' \
  ~/projects/claude-ide-review/skills/walkthrough/ skills/walkthrough/
```

- [ ] **Step 3: Copy the IntelliJ plugin**

`ide-plugin/` on disk holds ~21M of untracked Gradle and sandbox output. Only 676K is tracked, so copy the tracked files rather than the directory.

```bash
cd ~/projects/claude-ide-review
git ls-files -z ide-plugin | rsync -a --files-from=- --from0 . ~/projects/claude-annotate/
```

- [ ] **Step 4: Confirm the old engine copy did not come along**

Run:
```bash
cd ~/projects/claude-annotate
grep -c '76af9c0' skills/_shared/VENDOR.txt || echo "OK: still on this repo's engine copy"
```
Expected: `OK: still on this repo's engine copy`. If it prints `1`, the wrong `_shared` was copied — restore it with `git checkout -- skills/_shared` and redo Steps 2–3.

- [ ] **Step 5: Run the merged suite**

Run: `python3 -m pytest skills -q`
Expected: `729 passed`

633 from this repository plus 96 from the two absorbed skills. The other 80 tests in `claude-ide-review` were duplicate `_shared` tests and are correctly gone. Any other number means files were dropped or duplicated — stop and find out which before continuing.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/interactive_review skills/walkthrough ide-plugin
git commit -m "feat: absorb the interactive-review and walkthrough skills

Both drove the same local server this repository already ships, from a
second vendored copy that had drifted 192 lines behind in server.py.
They now import the one copy that lives here.

The skills are not yet installable: their plugin-root probe still looks
up the claude-ide-review marketplace. The next commit repairs that."
```

---

### Task 2: Point the absorbed skills at the merged marketplace

Each skill locates its own installed directory by looking its marketplace up in `~/.claude/plugins/known_marketplaces.json`. That file is keyed by **marketplace** name, and after the merge the only key is `claude-annotate`. The two absorbed skills still ask for `claude-ide-review`, so their probe falls through and they abort with "plugin root not found".

**Files:**
- Create: `skills/tests/__init__.py`
- Create: `skills/tests/test_repo_structure.py`
- Modify: `skills/interactive_review/SKILL.md:41` and its `echo` at line 61
- Modify: `skills/walkthrough/SKILL.md:45` and its `echo` at line 65

**Interfaces:**
- Consumes: `skills/interactive_review/SKILL.md`, `skills/walkthrough/SKILL.md` from Task 1.
- Produces: `skills/tests/test_repo_structure.py` with module constant `ROOT: Path` (the repository root) and helper `_marketplace() -> dict` returning the parsed `.claude-plugin/marketplace.json`. Tasks 3 and 4 add tests to this same file and reuse both.

- [ ] **Step 1: Create the test package**

```bash
cd ~/projects/claude-annotate
mkdir -p skills/tests
printf '' > skills/tests/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `skills/tests/test_repo_structure.py`:

```python
"""Guards for repository-level structure that no single skill owns.

These assert the things that break silently: a skill probing for a
marketplace name that no longer exists, a plugin manifest that stops
matching the skills on disk, a vendoring artifact left behind.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def _marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


# Each skill embeds a shell probe that resolves its own plugin root. The
# python inside it opens with this line.
PROBE_RE = re.compile(r'NAME, MARKER = "([^"]+)", "([^"]+)"')
# ...and reports failure with this one.
ECHO_RE = re.compile(r'echo "([^"]+): plugin root not found"')


def _skill_docs() -> list[Path]:
    return sorted(ROOT.glob("skills/**/*.md"))


def test_every_probe_asks_for_the_real_marketplace_name():
    # known_marketplaces.json is keyed by marketplace name. A skill that asks
    # for any other name cannot find itself once installed.
    expected = _marketplace()["name"]
    found = [
        (str(doc.relative_to(ROOT)), name)
        for doc in _skill_docs()
        for name, _ in PROBE_RE.findall(doc.read_text(encoding="utf-8"))
    ]
    assert found, "no plugin-root probe found — did the probe format change?"
    wrong = [(doc, name) for doc, name in found if name != expected]
    assert not wrong, f"probes must name the marketplace {expected!r}: {wrong}"


def test_every_probe_marker_file_exists():
    # The probe accepts a candidate root only if MARKER exists inside it, so a
    # stale marker path makes the skill unfindable even with the right name.
    missing = [
        (str(doc.relative_to(ROOT)), marker)
        for doc in _skill_docs()
        for _, marker in PROBE_RE.findall(doc.read_text(encoding="utf-8"))
        if not (ROOT / marker).is_file()
    ]
    assert not missing, f"probe markers do not exist: {missing}"


def test_probe_failure_messages_name_the_real_marketplace():
    expected = _marketplace()["name"]
    wrong = [
        (str(doc.relative_to(ROOT)), name)
        for doc in _skill_docs()
        for name in ECHO_RE.findall(doc.read_text(encoding="utf-8"))
        if name != expected
    ]
    assert not wrong, f"failure messages must say {expected!r}: {wrong}"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -q`
Expected: FAIL. `test_every_probe_asks_for_the_real_marketplace_name` and `test_probe_failure_messages_name_the_real_marketplace` both report `claude-ide-review` where `claude-annotate` was expected. `test_every_probe_marker_file_exists` passes already — the marker paths are correct.

- [ ] **Step 4: Repair the two probes**

In `skills/interactive_review/SKILL.md`, change:

```python
NAME, MARKER = "claude-ide-review", "skills/interactive_review/ensure_server.sh"
```

to:

```python
NAME, MARKER = "claude-annotate", "skills/interactive_review/ensure_server.sh"
```

and change:

```bash
[ -n "$PLUGIN_ROOT" ] || { echo "claude-ide-review: plugin root not found" >&2; exit 1; }
```

to:

```bash
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
```

In `skills/walkthrough/SKILL.md`, make the same two changes. Its probe line is:

```python
NAME, MARKER = "claude-ide-review", "skills/walkthrough/ensure_server.sh"
```

which becomes:

```python
NAME, MARKER = "claude-annotate", "skills/walkthrough/ensure_server.sh"
```

Leave the `MARKER` paths and the `~/.claude/{skill}/server.json` lookups alone. Those are per-skill state directories, not marketplace names, and they are still correct.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -q`
Expected: `3 passed`

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest skills -q`
Expected: `732 passed` (729 + 3 new)

- [ ] **Step 7: Commit**

```bash
git add skills/tests skills/interactive_review/SKILL.md skills/walkthrough/SKILL.md
git commit -m "fix: absorbed skills locate themselves under the merged marketplace

known_marketplaces.json is keyed by marketplace name. Both skills asked
for claude-ide-review, which no longer exists, so their plugin-root probe
fell through to 'plugin root not found'.

Guarded by a test that derives the expected name from marketplace.json,
so a future rename cannot break the probes silently."
```

---

### Task 3: Publish two plugins from one root

**Files:**
- Modify: `.claude-plugin/marketplace.json`
- Delete: `.claude-plugin/plugin.json`
- Modify: `skills/tests/test_repo_structure.py` (append tests)

**Interfaces:**
- Consumes: `ROOT`, `MARKETPLACE`, `_marketplace()` from Task 2.
- Produces: a `marketplace.json` whose `plugins` array has two entries. Task 6's README text quotes the two install commands this creates.

- [ ] **Step 1: Write the failing tests**

Append to `skills/tests/test_repo_structure.py`:

```python
def test_marketplace_publishes_two_plugins_from_one_root():
    plugins = _marketplace()["plugins"]
    assert [p["name"] for p in plugins] == ["claude-annotate", "claude-ide-review"]
    for plugin in plugins:
        # One root, shared. The skills array is what separates the plugins;
        # a subdirectory source would force a second copy of _shared.
        assert plugin["source"] == "./", plugin["name"]
        assert plugin["strict"] is False, plugin["name"]
        assert plugin["skills"], plugin["name"]
        assert plugin["description"], plugin["name"]


def test_plugin_skill_lists_partition_the_skills_tree():
    listed = [s for p in _marketplace()["plugins"] for s in p["skills"]]
    assert len(listed) == len(set(listed)), f"a skill is claimed twice: {listed}"
    # A skill directory is one with a SKILL.md; _shared and tests have none.
    on_disk = {
        f"./skills/{d.name}"
        for d in (ROOT / "skills").iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    }
    assert set(listed) == on_disk


def test_no_root_plugin_json():
    # Two plugins cannot share one plugin.json; their metadata lives in the
    # marketplace entries instead.
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -q`
Expected: FAIL. `test_marketplace_publishes_two_plugins_from_one_root` fails on the list comparison (one entry, `['claude-annotate']`); `test_plugin_skill_lists_partition_the_skills_tree` fails with a `KeyError: 'skills'`; `test_no_root_plugin_json` fails because the file exists.

- [ ] **Step 3: Rewrite the manifest**

Replace `.claude-plugin/marketplace.json` entirely with:

```json
{
  "name": "claude-annotate",
  "owner": {
    "name": "Petros Makris",
    "url": "https://github.com/petmakris"
  },
  "plugins": [
    {
      "name": "claude-annotate",
      "version": "0.1.0",
      "source": "./",
      "strict": false,
      "description": "Read Claude's long answers in a browser and comment on any block; Claude rewrites that block in place.",
      "skills": [
        "./skills/annotate"
      ]
    },
    {
      "name": "claude-ide-review",
      "version": "0.1.0",
      "source": "./",
      "strict": false,
      "description": "Ask Claude questions on a PR diff line or a code walkthrough step, inside IntelliJ. Requires the companion IDE plugin.",
      "skills": [
        "./skills/interactive_review",
        "./skills/walkthrough"
      ]
    }
  ]
}
```

- [ ] **Step 4: Delete the root plugin manifest**

```bash
git rm .claude-plugin/plugin.json
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -q`
Expected: `6 passed`

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest skills -q`
Expected: `735 passed` (732 + 3 new)

- [ ] **Step 7: Verify both plugins actually install**

No test can cover this — `strict: false` semantics were read off a working marketplace rather than off documentation, and this is the step that confirms the reading.

```bash
claude
```

Then, in the session:

```
/plugin marketplace add ~/projects/claude-annotate
/plugin install claude-annotate
/plugin install claude-ide-review
```

Expected: both install without error, and `/help` lists `/annotate`, `/interactive-review` and `/walkthrough`.

If `strict: false` turns out not to permit a missing `plugin.json`, the fallback is Pattern A — move each plugin into `plugins/<name>/` with its own `plugin.json`, and make `skills/_shared/` a symlink from each into a single top-level copy. Do not fall back without saying so; it changes the layout the rest of this plan assumes.

- [ ] **Step 8: Check what the hooks file does to the second plugin**

`hooks/hooks.json` sits at the repository root, and both plugins now claim that root. With only `claude-ide-review` installed, run any tool call and check whether `progress_publish.py` fires:

```bash
ls -la ~/.claude/annotate/ 2>/dev/null || echo "no annotate state — hook is inert"
```

Expected: the hook is inert. `progress_publish.py` returns immediately when the session has no pending annotate rounds, and always exits 0.

Record the result in the commit message. If the hook does fire for ide-review-only users it is still harmless, but it costs one `python3` spawn per tool call — worth an issue, not worth blocking this task.

- [ ] **Step 9: Commit**

```bash
git add .claude-plugin/marketplace.json skills/tests/test_repo_structure.py
git commit -m "feat: publish two plugins from one repository root

Both entries use source './' and are separated by their skills array,
which is what lets skills/_shared/web_companion/ exist once in a tree
that both plugins draw from. A subdirectory source would have required a
second copy — the thing this merge exists to delete.

plugin.json is gone; two plugins cannot share one, so their metadata
moved into the marketplace entries."
```

---

### Task 4: Remove the vendoring machinery

The point of the merge. Until the banners are gone, every file in the engine still tells the reader not to edit it.

**Files:**
- Delete: `skills/_shared/VENDOR.txt`, `skills/_shared/VENDOR.sha256`
- Modify: 33 files under `skills/_shared/` (30 `.py`, 3 `.sh`) — remove one banner line each
- Modify: `skills/tests/test_repo_structure.py` (append tests)

**Interfaces:**
- Consumes: `ROOT` from Task 2.
- Produces: an engine tree with no generated-file markers. Task 5 deletes the CI job that reads `VENDOR.sha256`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/tests/test_repo_structure.py`:

```python
BANNER = "GENERATED FILE"


def test_no_vendoring_artifacts():
    shared = ROOT / "skills" / "_shared"
    assert not (shared / "VENDOR.txt").exists()
    assert not (shared / "VENDOR.sha256").exists()


def test_engine_is_not_marked_generated():
    # The engine is edited here now. A "DO NOT EDIT" banner would send the
    # next reader looking for an upstream that no longer exists.
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "skills" / "_shared").rglob("*")
        if p.suffix in {".py", ".sh"} and BANNER in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"still marked generated: {offenders}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -q`
Expected: FAIL. `test_no_vendoring_artifacts` fails on `VENDOR.txt`; `test_engine_is_not_marked_generated` lists 33 files.

- [ ] **Step 3: Delete the vendoring artifacts**

```bash
cd ~/projects/claude-annotate
git rm skills/_shared/VENDOR.txt skills/_shared/VENDOR.sha256
```

- [ ] **Step 4: Strip the banners**

The banner is a whole line, first line in `.py` files and second (after the shebang) in `.sh` files. Deleting the matching line handles both.

```bash
find skills/_shared -type f \( -name '*.py' -o -name '*.sh' \) \
  -exec sed -i '' '/^# GENERATED FILE/d' {} +
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/tests/test_repo_structure.py -q`
Expected: `8 passed`

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest skills -q`
Expected: `737 passed` (735 + 2 new)

The engine's own 300-odd tests passing after 33 files were edited by `sed` is the check that the strip removed only what it should.

- [ ] **Step 7: Verify the shell entry point still runs**

`sed` touched `ensure_server.sh`, which is not covered by the Python suite.

Run: `bash skills/_shared/web_companion/tests/test_watcher.sh`
Expected: exits 0.

- [ ] **Step 8: Commit**

```bash
git add -A skills/_shared
git commit -m "refactor: the engine is source, not a vendored copy

Drops VENDOR.txt, VENDOR.sha256 and the 'GENERATED FILE — DO NOT EDIT'
banner from 33 files. Editing skills/_shared/web_companion/ in this
repository is now the correct and only way to change the server."
```

---

### Task 5: Merge the CI and release workflows

Both repositories' `ci.yml` are byte-identical apart from ide-review's extra `ide-plugin` job, so this is a union plus a deletion.

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/ide-plugin.yml`
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `ide-plugin/` from Task 1; the absence of `VENDOR.sha256` from Task 4.
- Produces: nothing later tasks read.

- [ ] **Step 1: Strip the vendor job from CI**

Replace `.github/workflows/ci.yml` entirely with:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install pytest
      - run: python3 -m pytest skills -q
```

The `vendor` job goes with the manifest it verified.

- [ ] **Step 2: Add the path-filtered IntelliJ build**

The spec calls for the Gradle build to be path-filtered so a skills-only change does not start a JetBrains build. GitHub's `paths:` key is workflow-level rather than job-level, so the filter needs its own file rather than a second job in `ci.yml`.

Create `.github/workflows/ide-plugin.yml`:

```yaml
name: ide-plugin
on:
  push:
    branches: [main]
    paths: ['ide-plugin/**', '.github/workflows/ide-plugin.yml']
  pull_request:
    paths: ['ide-plugin/**', '.github/workflows/ide-plugin.yml']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '25'
      - run: ./gradlew buildPlugin test
        working-directory: ide-plugin
```

The workflow file lists itself in `paths:` so a change to the build definition still triggers a build.

- [ ] **Step 3: Add the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: release
on:
  push:
    tags: ['ide-plugin-v*']

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        # build.gradle.kts derives the plugin version from the commit count,
        # so a shallow clone would produce the wrong version number.
        with:
          fetch-depth: 0
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '25'
      - run: ./gradlew buildPlugin
        working-directory: ide-plugin
      - uses: softprops/action-gh-release@v2
        with:
          files: ide-plugin/build/distributions/*.zip
          body: |
            Install in IntelliJ: **Settings → Plugins → ⚙ → Install Plugin from Disk…**
            and pick the `.zip` below.

            This is the IDE half. The Claude Code half installs separately:

                /plugin marketplace add petmakris/claude-annotate
                /plugin install claude-ide-review
```

Two changes from the original: the trigger is `ide-plugin-v*` so plain `v*` stays free for plugin releases, and the install instructions name this repository.

- [ ] **Step 4: Check the workflows parse**

Run:
```bash
python3 -c "
import sys
try:
    import yaml
except ImportError:
    sys.exit('skip: pyyaml not installed, rely on GitHub to validate')
for f in ('.github/workflows/ci.yml',
          '.github/workflows/ide-plugin.yml',
          '.github/workflows/release.yml'):
    yaml.safe_load(open(f))
    print('ok', f)
"
```
Expected: `ok` for all three, or the skip message. `pyyaml` is a dev convenience here — do not add it as a project dependency.

- [ ] **Step 5: Confirm nothing still references the deleted manifest**

Run: `grep -rn "VENDOR" .github/ || echo "OK: no vendor references left in CI"`
Expected: `OK: no vendor references left in CI`

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/
git commit -m "ci: one pipeline for both plugins and the IDE plugin

Drops the vendor-checksum job, which verified a manifest that no longer
exists. The Gradle build and the release workflow come from
claude-ide-review — the build in its own file, since GitHub filters paths
per workflow rather than per job, and the release retagged to
ide-plugin-v* so plain v* stays free for plugin releases."
```

Note for the first release after this lands: `ide-plugin/build.gradle.kts:37` sets `version = "0.1.$buildNumber"` from `git rev-list --count HEAD`. Against ide-review's 8 commits that produced 0.1.8; against this repository it will be roughly 0.1.20. The jump is forward, so IntelliJ accepts the upgrade.

---

### Task 6: Rewrite the README for a two-plugin repository

**Files:**
- Modify: `README.md`
- Modify: `skills/interactive_review/SKILL.md` (add the IntelliJ prerequisite note)
- Modify: `skills/walkthrough/SKILL.md` (add the IntelliJ prerequisite note)

**Interfaces:**
- Consumes: the install commands established in Task 3.
- Produces: nothing later tasks read.

- [ ] **Step 1: Read the current README**

Run: `cat README.md`

Note what it says about installation — line 11 currently reads `/plugin marketplace add petmakris/claude-annotate`, which stays correct. What changes is that adding the marketplace now offers two plugins rather than one.

- [ ] **Step 2: Rewrite the installation section**

The marketplace command is unchanged; the install step is now a choice. Use this text:

````markdown
## Install

    /plugin marketplace add petmakris/claude-annotate

That registers the marketplace, which publishes two plugins. Install either or both:

    /plugin install claude-annotate      # read long answers in a browser, comment on any block
    /plugin install claude-ide-review    # ask questions on a PR diff line or walkthrough step, in IntelliJ

`claude-ide-review` also needs the IntelliJ half, which is a separate download —
grab the `.zip` from [Releases](https://github.com/petmakris/claude-annotate/releases)
and install it via **Settings → Plugins → ⚙ → Install Plugin from Disk…**

Both plugins drive the same local server, which lives once in this repository at
`skills/_shared/web_companion/`.
````

- [ ] **Step 3: Note the IntelliJ prerequisite in both skills**

Someone can install `claude-ide-review` and invoke `/walkthrough` without the IDE half, and nothing will visibly happen. Add this line directly under the first heading of both `skills/interactive_review/SKILL.md` and `skills/walkthrough/SKILL.md`:

```markdown
> Requires the companion IntelliJ plugin. Without it this skill has nowhere to
> render — install the `.zip` from the repository's Releases page first.
```

- [ ] **Step 4: Confirm the skill-structure guard still passes**

`skills/annotate/tests/test_skill_structure.py` asserts `SKILL.md` stays under 120 lines and that every `references/…` link resolves. Editing the other two skills' `SKILL.md` files cannot affect it, but the run is cheap and the guard is exactly the kind that catches a careless paste.

Run: `python3 -m pytest skills -q`
Expected: `737 passed`

- [ ] **Step 5: Commit**

```bash
git add README.md skills/interactive_review/SKILL.md skills/walkthrough/SKILL.md
git commit -m "docs: the repository ships two plugins

Adding the marketplace now offers a choice rather than a single install.
Both IDE skills say up front that they need the IntelliJ half, since
without it they fail by doing nothing visible at all."
```

---

### Task 7: Retire the source repositories

Not code. Do this only after Task 3 Step 7 confirmed both plugins install from the merged repository — that is the evidence that the merge works, and until it exists there is something to go back to.

**Files:**
- Modify: `~/projects/web-companion/README.md`
- Delete: `~/projects/web-companion/sync-vendor.sh`, `~/projects/web-companion/check-vendor.sh`
- Modify: `~/projects/claude-ide-review/README.md`

**Interfaces:**
- Consumes: a verified, pushed merge.
- Produces: nothing.

- [ ] **Step 1: Push this repository first**

```bash
cd ~/projects/claude-annotate
git push origin main
```

Confirm CI is green before continuing. Archiving a source repository while the merged one is failing would be the one irreversible mistake available in this plan.

- [ ] **Step 2: Mark web-companion as superseded**

```bash
cd ~/projects/web-companion
git rm sync-vendor.sh check-vendor.sh
```

Add to the top of its `README.md`, immediately under the `# web-companion` heading:

```markdown
> **Superseded.** This engine now lives in
> [petmakris/claude-annotate](https://github.com/petmakris/claude-annotate)
> at `skills/_shared/web_companion/`, edited in place. This repository is
> kept read-only for its history; it is no longer vendored anywhere.
```

```bash
git add README.md
git commit -m "docs: superseded by claude-annotate

Both consumers merged into one repository, so there is nothing left to
vendor into. sync-vendor.sh and check-vendor.sh go with the practice."
git push origin main
```

- [ ] **Step 3: Mark claude-ide-review as superseded**

Add to the top of `~/projects/claude-ide-review/README.md`, under the heading:

```markdown
> **Moved.** This plugin now ships from
> [petmakris/claude-annotate](https://github.com/petmakris/claude-annotate):
>
>     /plugin marketplace add petmakris/claude-annotate
>     /plugin install claude-ide-review
>
> This repository is kept read-only for its history.
```

```bash
cd ~/projects/claude-ide-review
git add README.md
git commit -m "docs: moved to claude-annotate"
git push origin main
```

- [ ] **Step 4: Archive both on GitHub**

```bash
gh repo archive petmakris/web-companion --yes
gh repo archive petmakris/claude-ide-review --yes
```

Archiving is reversible from the repository settings page. Deleting is not — do not delete either repository.

- [ ] **Step 5: Confirm the old install path fails loudly**

Anyone with `claude-ide-review` already installed keeps working from their local copy; the concern is a fresh install from the archived repository.

```
/plugin marketplace add petmakris/claude-ide-review
```

Expected: it still resolves (archived repositories stay readable) and installs the old, now-frozen plugin. That is acceptable — the README says where to go. Note it in the final report rather than trying to break it.

---

## Verification

After Task 6, the whole merge is checkable in one command plus two manual confirmations:

| Check | Command | Expected |
|---|---|---|
| Full suite | `python3 -m pytest skills -q` | `737 passed` |
| Shell entry point | `bash skills/_shared/web_companion/tests/test_watcher.sh` | exit 0 |
| No engine copies left | `find . -name VENDOR.txt` | no output |
| Both plugins install | `/plugin install claude-annotate` then `claude-ide-review` | both succeed, `/help` lists all three commands |
| IDE path still works | `/interactive-review <PR>` against IntelliJ | diff-line questions reach Claude and answers land in the IDE |

The last one is the only check that exercises the write-gate reasoning from the spec on a real client rather than on a reading of `server.py:508`. Do not skip it.
