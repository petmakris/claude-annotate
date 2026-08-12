# Install and first-use robustness

Date: 2026-08-12
Status: approved, ready for implementation planning

## Problem

A new user installed `claude-annotate` on a machine with no `python3` on
`PATH`. Every subsequent tool call in his session printed:

```
PostToolUse:Bash hook error
Failed with non-blocking status code: /usr/bin/bash: line 1: python3: command not found
```

The message names neither the plugin nor a fix, and repeats indefinitely. He
assumed his own setup was at fault and reported it as a probable local problem.

The hook is the loudest failure, not the only one. Every Python entry point in
the repository is spelled literally `python3`, in 29 runtime call sites across
six shipped files (a seventh mention is documentation):

| File | Sites | What breaks |
|---|---|---|
| `skills/walkthrough/SKILL.md` | 10 | Bootstrap, server URL, step writes, event ack |
| `skills/interactive_review/SKILL.md` | 8 | Same shape |
| `skills/annotate/references/pushing.md` | 6 | Plugin-root bootstrap, workspace lookup, watcher arming |
| `skills/_shared/web_companion/ensure_server.sh` | 3 | `expected_fp()` — server never starts |
| `skills/annotate/references/resuming.md` | 1 | Resume flow |
| `hooks/hooks.json` | 1 | A red line per tool call, forever |
| **Runtime total** | **29** | |
| `skills/walkthrough/README.md` | 1 | Documentation only — `python3 -m pytest`, not a runtime path |

The 25 markdown sites are the dangerous ones: Claude runs them as bash while
following a skill, so on a python-less machine every snippet in the flow fails
and Claude improvises around each one.

Three distinct defects sit underneath:

1. **The requirement is never stated.** The word "Python" appears nowhere in
   the README or in either marketplace description. There is no way for a user
   to know before installing, and no way to diagnose after.
2. **An optional feature has a critical feature's blast radius.** The hook
   publishes a cosmetic progress label. It fires on *every* `PostToolUse`,
   for *both* plugins — `hooks/hooks.json` is at the repository root and both
   marketplace entries ship from `source: "./"` — so a user who installed only
   `claude-ide-review` pays a `python3` spawn per tool call for a feature they
   do not have, and inherits its failure when the spawn fails.
3. **Failure teaches nothing.** No shipped message names the plugin, the
   requirement, or the remedy.

## Goal

A user whose machine cannot run this plugin learns that in one clear message,
at the moment it matters, and is told exactly what to install. A user who never
invokes the plugin is never affected by it at all.

Explicitly **not** a goal: making the plugin work on a machine that lacks its
dependencies. We state requirements and help users meet them. We do not supply
interpreters, install software, or modify `PATH`.

## Decisions

| Question | Decision |
|---|---|
| Supported platforms | macOS and Linux |
| Interpreter discovery | None. We check for `python3`; we do not probe for `python`, Homebrew paths, or `uv` |
| Shimming a `python3` | **Rejected.** Placing an executable named `python3` on `PATH` — even only when none exists — silently shadows an interpreter for every command run in the session. Unacceptable risk for a cosmetic feature |
| Interpreter override env var | **Rejected.** Honoring `$CLAUDE_ANNOTATE_PYTHON` would require rewriting all 29 runtime call sites, or it half-works silently. The PATH-visibility case it addresses is handled by diagnosis instead |
| Auto-install of Python | **Rejected.** The plugin never mutates the user's machine |
| Declared Python floor | **3.9** — established by execution, see below |
| Where the check runs | Both: automatic preflight at first use, and an on-demand `/annotate-doctor` |
| Doctor implementation | POSIX `sh`, no `python3`, no `jq` |
| Doctor name | `/annotate-doctor`. Imperfect for a user who installed only `claude-ide-review`; accepted for now, revisitable |
| IntelliJ-side checks | Out of scope for v1. Separate install, separate failure modes |

## The declared floor is 3.9, and it is measured

Parsing every shipped `.py` (35 files, excluding tests) with
`ast.parse(feature_version=...)` puts the *syntax* floor at 3.8. One stdlib
call raises it:

```
skills/_shared/web_companion/uploads.py:76   resolved.is_relative_to(images_root)   # Path.is_relative_to — 3.9+
```

`progress_publish.py:118` uses `Path.unlink(missing_ok=True)` (3.8+), and every
file using `str | None` or `list[...]` annotations carries
`from __future__ import annotations`, so annotations impose no floor.

Runtime dependencies are the interpreter alone. `fontTools` is imported only by
`tools/gen_font_metrics.py`, a development tool. There is nothing to
`pip install`.

CI currently tests 3.12 only. A declared 3.9 floor would therefore be an
unverified claim. See Acceptance.

## Design

### 1. Declared requirements

A `Requirements` section immediately above `Install` in `README.md`:

- `python3` on `PATH`, 3.9 or newer — stdlib only, nothing to `pip install`
- `bash` and `curl`
- macOS or Linux
- `claude-ide-review` additionally requires the IntelliJ plugin

The same sentence is folded into both `description` fields in
`.claude-plugin/marketplace.json`, because that text is what a user reads at
install time.

`bash` and `curl` are real dependencies, not speculative ones: every
`ensure_server.sh` is `#!/usr/bin/env bash` with `set -euo pipefail`, and
`is_healthy()` polls `/health` with `curl`. `flock` is *not* a dependency —
`ensure_server.sh:95` documents an atomic `mkdir` lock chosen for portability.
No shell script invokes `open` or `xdg-open`.

### 2. The hook becomes unable to cause harm

`hooks/hooks.json` gains a POSIX-sh gate ahead of the interpreter. It exits 0
unless **both** hold:

- this session has a pending annotate round on disk
- `python3` resolves

Consequences, in order of importance:

- A machine without `python3` sees nothing. Not a friendlier error — nothing.
- A user who installed only `claude-ide-review` no longer spawns a Python
  process per tool call.
- A user who has installed `claude-annotate` but is not currently annotating
  pays one `command -v` and one path test instead of an interpreter start.

The gate never reports a problem. A hook is the wrong messenger: it fires
hundreds of times per session and has no way to speak once. Reporting is
§3 and §4's job.

### 3. Preflight where the flow starts

No new mechanism. Each skill flow already opens with a `PLUGIN_ROOT` bootstrap
block and then calls `ensure_server.sh`, and the references already instruct:
"If it exits non-zero, surface the stderr to the user and stop."

The defect is ordering. On a python-less machine the *bootstrap* dies first —
it resolves the plugin root with `python3 -c` — so the user sees a raw
`command not found` before any of our own error handling runs.

Two changes:

- The bootstrap block in each skill gains a guard ahead of its `python3`.
- `ensure_server.sh` performs the same check before `expected_fp()`.

Both emit one message on stderr naming the plugin, the requirement, what was
found instead, and the remedy. On a fresh macOS install with no Command Line
Tools there is no `/usr/bin/python3` at all, and the remedy is
`xcode-select --install` or Homebrew.

Claude then stops, rather than improvising around a flow of failing snippets.

### 4. `/annotate-doctor`

One constraint determines its implementation: **it must run on a machine where
nothing works.** It diagnoses the absence of Python, so it cannot be written in
Python, and cannot depend on `jq`. POSIX `sh` only.

Checks:

| Check | Failure remedy shown |
|---|---|
| `python3` resolves | Install instructions for the platform |
| Version ≥ 3.9 | Upgrade instructions |
| `python3` visible to a **non-interactive** shell | The specific `PATH` remedy — see below |
| `curl` and `bash` present | Install instructions |
| State dirs under `~/.claude/` writable | Permission remedy |
| Server up and `/health` answering | How to restart |
| Hook wired in the installed plugin | Reinstall instructions |

The non-interactive check is the one that cannot be replaced by documentation.
Hooks run under `/usr/bin/bash -c`, which need not see a pyenv, asdf or conda
shim that the user's interactive shell sees. That user gets a working
`python3 --version` when they type it and a failing hook, and no README can
resolve the contradiction. The doctor detects the mismatch by testing the
interpreter the way the hook sees it, and prints the command for the user to
run. It does not run that command.

Nothing in the doctor mutates state.

The skill is a thin wrapper over the script, and the §3 preflight calls the same
script, so the two cannot drift apart.

## Acceptance

Every claim below is verified by running something, not by reading.

| Claim | Verified by | Expected |
|---|---|---|
| The hook is silent without `python3` | Run the hook with `PATH` sanitized to exclude every `python3`, feeding real `PostToolUse` JSON | exit 0, empty stdout, empty stderr |
| The hook is silent when not annotating | Run it with `python3` available and no pending registry | exit 0, no interpreter spawned |
| The doctor runs where nothing works | Run it under the same sanitized `PATH` | exit non-zero, report printed, `python3` line marked failed with remedy |
| Preflight speaks before Claude improvises | Run the bootstrap block under the sanitized `PATH` | one named message on stderr, non-zero exit |
| The 3.9 floor is real | Add 3.9 to the CI matrix | full suite green on 3.9 |
| Nothing else broke | `python3 -m pytest skills -q` | current count + new tests, all passing |

The sanitized-`PATH` fixture is the load-bearing piece: it constructs a
directory containing the tools the scripts need and no `python3`, then runs
against it. Without a watched failure, "it fails quietly now" is a claim rather
than a fact.

If the suite does not pass on 3.9, the declared floor is raised to the version
CI actually tests. We do not publish a number we have not run.

## Out of scope

- Windows and WSL support
- Any probing for interpreters other than `python3`
- Any form of dependency installation or `PATH` modification
- IntelliJ-side diagnosis
- Reducing the Python dependency itself
