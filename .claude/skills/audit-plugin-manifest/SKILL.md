---
name: audit-plugin-manifest
description: Audit `.claude-plugin/marketplace.json` — the registry of what ships — against the skills on disk, the `bin/claude-annotate` runner every skill uses to find its installed code, and any other root-shared surface (`bin/`, `hooks/`, `commands/`, `agents/`). Finds a skill directory that never got its `SKILL.md`, runner invocations the structure tests cannot see, thin install-time descriptions, a missing IDE or daemon prerequisite note, and a root-shared file that reaches a plugin it was not written for. Reports in plain English. Use when the user says "/audit-plugin-manifest", "check what ships", or asks whether both plugins still install correctly.
user-invocable: true
---

# /audit-plugin-manifest — what ships, and whether it can find itself

Two plugins share one root and are separated only by their `skills` arrays, so `marketplace.json` is the sole statement of which skill belongs to which plugin. Both entries use `"source": "./"` rather than a subdirectory precisely so there is one copy of `skills/_shared/` to reach, not two — `test_marketplace_publishes_two_plugins_from_one_root` checks that directly; this audit does not re-check it.

Once installed, a skill reaches its own code through **`bin/claude-annotate`**, the runner. Claude Code puts `<plugin root>/bin` on PATH for `--plugin-dir` and marketplace installs alike, and the runner finds the root from its own location (`${0%/*}/..`), so a skill doc writes `claude-annotate push ...`, `claude-annotate <skill>.<module> ...`, `claude-annotate python -m skills.<...>` or `"$(claude-annotate root)/skills/<skill>/<file>"` and never probes for the root itself. The one exception is `skills/annotate-doctor/SKILL.md`: it diagnoses a missing `python3`, so it cannot rely on a runner that needs one, and locates `skills/annotate-doctor/doctor.sh` with a plain-`sh` loop over `MARKER="skills/annotate-doctor/doctor.sh"` — PATH entries ending in `/bin`, then `$CLAUDE_PLUGIN_ROOT`, then the plugin cache. The marketplace-name probes (`NAME, MARKER = ...` against `~/.claude/plugins/known_marketplaces.json`) that every SKILL.md used to paste are gone, and a test keeps them gone.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/tests/test_repo_structure.py::test_marketplace_publishes_two_plugins_from_one_root` — both entries, `source: "./"`, `strict: false`, non-empty `skills` and `description`.
- `skills/tests/test_repo_structure.py::test_plugin_skill_lists_cover_the_skills_tree` — every directory with a `SKILL.md` is listed, nothing is claimed twice except `SHARED_SKILLS` (`./skills/annotate-doctor`, deliberately in both).
- `skills/tests/test_repo_structure.py::test_no_root_plugin_json`
- `skills/tests/test_repo_structure.py::test_the_runner_is_used_and_executable` — `bin/claude-annotate` exists, is executable, and is referenced from each runner-using skill.
- `skills/tests/test_repo_structure.py::test_every_runner_command_in_a_skill_doc_resolves` — every `claude-annotate <cmd>` / `claude-annotate python -m <mod>` in a skill `.md` resolves to a module the runner would run.
- `skills/tests/test_repo_structure.py::test_every_path_under_the_plugin_root_exists` — every `$(claude-annotate root)/<path>`, and every path built from a variable assigned from it, exists.
- `skills/tests/test_repo_structure.py::test_no_skill_doc_pastes_its_own_root_probe` — no `NAME, MARKER = "` or `known_marketplaces.json` in any skill `.md`.
- `skills/tests/test_repo_structure.py::test_every_shell_marker_file_exists` — annotate-doctor's `MARKER=` is still seen and still exists.
- `skills/tests/test_repo_structure.py::test_every_hook_command_names_a_script_that_exists` — any `hooks.json` anywhere names scripts that exist.
- `skills/tests/test_doctor_skill_locator.py` — annotate-doctor's locator finds `doctor.sh` under a `--plugin-dir` layout and the marketplace-cache layout, and fails clearly otherwise.
- `skills/tests/test_bootstrap_guard.py` — every doc block that runs Python is guarded and names the plugin and the fix.

These cover the mechanical checks thoroughly. Report only what they do not enforce, plus anywhere one has gone stale.

## Step 1 — load the sources of truth

1. `.claude-plugin/marketplace.json` — the two entries, their `description` and `skills` (their `source` and `strict` are context, not a check this audit runs).
2. `bin/claude-annotate` — its header comment (the command forms it supports) and its resolution order: a bare name resolves in `skills/annotate/` first; a dotted name resolves under `skills/`; a dash becomes an underscore.
3. `skills/tests/test_repo_structure.py` — the exact regexes it uses to find runner invocations (`FENCE_RE` matches only ` ```bash ` and ` ```sh ` fences; `INLINE_RE` matches inline code spans; `RUNNER_CMD_RE` matches only command position), because Rule 2 is about what those regexes cannot see.
4. Each `skills/*/SKILL.md` and its `references/`, plus any shipped non-Markdown file that invokes the runner (`git ls-files skills | xargs grep -l "claude-annotate "`).
5. Any root-shared surface Claude Code loads per plugin: `bin/` (today: `claude-annotate` only), and `hooks/`, `commands/` or `agents/` at the repository root — **none of these three exists today**. If one has reappeared, read it and every script it registers.

## The rules

- **Rule 1 — a skill directory with no `SKILL.md` ships nothing, and no test notices.** `skills/_shared/` and `skills/tests/` are the two legitimate no-`SKILL.md` directories under `skills/`. `test_plugin_skill_lists_cover_the_skills_tree` builds its on-disk set only from directories that already contain a `SKILL.md`, so a directory without one is invisible to it by construction. A *third* such directory — one that reads like an abandoned or half-authored skill — is **Critical**.
- **Rule 2 — a runner invocation the structure tests cannot see.** The tests scan only `skills/**/*.md`, only ` ```bash `/` ```sh ` fences and inline spans, and only command position. A `claude-annotate <cmd>` or `$(claude-annotate root)/<path>` that sits in an unlabelled ` ``` ` fence, a ` ```console `/` ```zsh ` fence, or a shipped `.py`/`.sh` file, and that does not resolve by the runner's own rules (Step 1.2) or names a path that does not exist, is **Critical** — the skill cannot run once installed and nothing else would notice until a user hit it. A resolving invocation in such a place is not a finding.
- **Rule 3 — a skill resolves its root some other way.** A shipped skill file that finds the plugin root without the runner — reading `CLAUDE_PLUGIN_ROOT` as its only source, globbing `~/.claude/plugins/cache`, walking up from `__file__` in a doc snippet, or a reintroduced marketplace-name probe in a form `test_no_skill_doc_pastes_its_own_root_probe`'s regex misses — is **Critical**. annotate-doctor's `MARKER=` locator is the one allowlisted exception (see the allowlist).
- **Rule 4 — descriptions are the install-time prose.** An entry `description` that restates the plugin name and nothing more is **Medium**: it is what a user reads when choosing whether to install. The covering tests only require it to be non-empty.
- **Rule 5 — prerequisites are named honestly.** `claude-ide-review`'s description must state that it needs an IDE half — the companion IntelliJ plugin (`ide-plugin/`) for `/ask-diff` and `/walkthrough`, the VS Code extension (`vscode-plugin/`) for `/show-diff`. Each entry's description must also say which of its skills need the separately installed webcompanion daemon and which do not — every skill except `slides` pushes to it (`/show-diff` only for its per-line comments). A description that omits either is **Medium**: without the missing half the commands fail by doing nothing visible, which reads as a broken skill. The covering tests do not read description content.
- **Rule 6 — a root-shared surface reaches both plugins.** Anything at the repository root that Claude Code loads per plugin is claimed by both entries. `bin/claude-annotate` is shared on purpose and is correct as long as every command it serves works for a user who installed either plugin — it resolves inside the one shared root, so it does. A **new** executable under `bin/`, or any `hooks/`, `commands/` or `agents/` at the root, that assumes a skill only one plugin ships (e.g. fails, prints errors, or writes state when that skill was never used) is **Critical**. The bar is the one the deleted `progress_publish.py` hook met: it keyed off state written only by its own skill and returned before doing anything when that state was absent, so under the other plugin it did nothing and exited 0.
- **Rule 7 — a skill that could belong to either plugin.** **Decision**, not a Violation. Ask which plugin should own it, or whether it should join `SHARED_SKILLS`.

## Closed allowlist — never flag these

1. `skills/_shared/` and `skills/tests/` — no `SKILL.md`, deliberately not shipped as skills.
2. `.claude/skills/` — this audit suite is local tooling, never shipped, and must not appear in any `skills` array.
3. `skills/annotate-doctor/SKILL.md`'s plain-`sh` `MARKER=` locator — it cannot use the runner because it diagnoses a missing `python3`; `test_doctor_skill_locator.py` covers it.
4. `bin/claude-annotate` itself computing the root from `$0` — that is the one place root resolution is supposed to live.
5. Prose that names `$CLAUDE_PLUGIN_ROOT` to explain why the runner is used — e.g. the "`$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash tool's shell" notes in the ask_diff, dataflow, deck and walkthrough SKILL.md files. Rule 3 is about code that resolves the root, not sentences about it.
6. `./skills/annotate-doctor` appearing in both `skills` arrays — `SHARED_SKILLS` declares it.
7. The marketplace and a plugin sharing the name `claude-annotate`.
8. `skills/ask_diff/install_hooks.sh` — it installs **git** hooks into the user's repository, not Claude Code hooks; it is not a root-shared surface.
9. `ide-plugin/`, `vscode-plugin/`, `docs/`, `.github/`, `.githooks/` — present at the root but not loaded by Claude Code as plugin components.
10. `docs/superpowers/` specs and plans describing manifest structure or the retired probes.
11. Any line carrying `# manifest-exempt: <reason>`.

## Step 2 — scan

Parse `marketplace.json` for both entries' `description` and `skills`. List every directory under `skills/` that has no `SKILL.md`, and check each against the allowlist. Grep every shipped file under `skills/` (all extensions, all fence languages) for `claude-annotate ` and `claude-annotate root`; for each hit the covering regexes would not see, resolve it by the runner's rules and check the path exists. Grep shipped skill files for `CLAUDE_PLUGIN_ROOT`, `plugins/cache`, `known_marketplaces` and `__file__`-relative root walks. List `bin/` and check whether `hooks/`, `commands/` or `agents/` exists at the root; read any that do. Build the file universe from `git ls-files`.

## Step 3 — severity

Critical for a `skills/` directory with no `SKILL.md` beyond the two allowlisted cases, an unresolvable runner invocation the tests cannot see, a non-runner root lookup, or a root-shared file that misbehaves under the other plugin; Medium for a thin description or a missing IDE or daemon prerequisite; Decision for ownership questions.

## Output template

```
Plugin manifest audit — actionable items

Checked {N} manifest entries against {M} skills on disk.
Verdict: {one sentence.}

**Critical — fix first**
1. {What drifted}. {Imperative fix}. — {area}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {Skill that could belong to either plugin — which owns it?} — {area}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

## After delivering the report

Stop and wait. "explain N" gives the entry, the file:line, and the fix. "fix N" applies it. False positive means fixing this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not propose moving plugins into subdirectories.
- Do not flag `.claude/skills/` as an unshipped skill.
- Do not propose replacing the runner with per-skill root probes.
- Do not re-report what the covering tests enforce.
- Do not install or uninstall a plugin.
