---
name: audit-plugin-manifest
description: Audit `.claude-plugin/marketplace.json` — the registry of what ships — against the skills on disk and the root-shared hooks file. Finds a skill directory that never got its `SKILL.md`, thin install-time descriptions, a missing IntelliJ prerequisite note, and hooks that reach a plugin they were not written for. Reports in plain English. Use when the user says "/audit-plugin-manifest", "check what ships", or asks whether both plugins still install correctly.
user-invocable: true
---

# /audit-plugin-manifest — what ships, and whether it can find itself

Two plugins share one root and are separated only by their `skills` arrays, so `marketplace.json` is the sole statement of which skill belongs to which plugin. Both entries use `"source": "./"` rather than a subdirectory precisely so there is one copy of `skills/_shared/` to reach, not two — a subdirectory source would force a second copy and undo the merge, which is why `test_marketplace_publishes_two_plugins_from_one_root` checks it directly; this audit does not re-check it. A skill also has to locate its own installed directory at runtime, by resolving a marketplace name against `~/.claude/plugins/known_marketplaces.json` and then verifying a MARKER file exists under the candidate root. `test_every_probe_asks_for_the_real_marketplace_name` catches a probe whose `NAME` disagrees with this repo's `marketplace.json` — but nothing can catch the resolution failing on an installed copy: the marketplace registered under a different name, the registry entry missing from `known_marketplaces.json` altogether, or the MARKER file absent from the installed tree. Any of those and the skill simply aborts with "plugin root not found" for the user and nobody else.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/tests/test_repo_structure.py::test_marketplace_publishes_two_plugins_from_one_root`
- `skills/tests/test_repo_structure.py::test_plugin_skill_lists_partition_the_skills_tree`
- `skills/tests/test_repo_structure.py::test_no_root_plugin_json`
- `skills/tests/test_repo_structure.py::test_every_probe_asks_for_the_real_marketplace_name`
- `skills/tests/test_repo_structure.py::test_every_probe_marker_file_exists`
- `skills/tests/test_repo_structure.py::test_probe_failure_messages_name_the_real_marketplace`

These cover the mechanical checks thoroughly. Report only what they do not enforce, plus anywhere one has gone stale.

## Step 1 — load the sources of truth

1. `.claude-plugin/marketplace.json` — the two entries, their `description` and `skills` (their `source` and `strict` are context — see the intro — not a check this audit runs).
2. Each `skills/*/SKILL.md` — the embedded plugin-root probe.
3. `hooks/hooks.json` — the root-shared hook registration.
4. `skills/annotate/hooks/progress_publish.py` — the hook the root file registers.

## The rules

- **Rule 1 — a skill directory with no `SKILL.md` ships nothing, and no test notices.** `skills/_shared/` and `skills/tests/` are the two legitimate no-`SKILL.md` directories under `skills/`, allowlisted below. `test_plugin_skill_lists_partition_the_skills_tree` builds its on-disk set only from directories that already contain a `SKILL.md` — a directory without one never enters that comparison at all, so it is invisible by construction, not merely unlisted. A *third* such directory — one that reads like an abandoned or half-authored skill — is **Critical**.
- **Rule 2 — descriptions are the install-time prose.** An entry `description` that restates the plugin name and nothing more is **Medium**: it is what a user reads when choosing whether to install. The covering tests only require a description to be non-empty, not substantive.
- **Rule 3 — a root-shared surface reaches both plugins.** Anything at the repository root that Claude Code loads per-plugin — `hooks/`, and `commands/` or `agents/` if they ever appear — is claimed by both entries, and no covering test reads `hooks/hooks.json` at all. A hook there that is not inert for the plugin it was not written for is **Critical**. Today `hooks/hooks.json` registers `progress_publish.py`, which keys off a per-session registry at `~/.claude/annotate/pending-<session_id>.json` written only by the annotate skill; on a session that never used annotate the file does not exist, the lookup raises `FileNotFoundError`, and the hook returns before writing anything — so under `claude-ide-review` (interactive_review, walkthrough) it does nothing and always exits 0. A newly added hook without that property is a Violation.
- **Rule 4 — the IDE half is named honestly.** `claude-ide-review`'s description must state that it requires the companion IntelliJ plugin. Without the IDE half its commands fail by doing nothing visible, which reads as a broken skill. A description that omits it is **Medium**; the covering tests do not read description content.
- **Rule 5 — a skill that could belong to either plugin.** **Decision**, not a Violation. Ask which plugin should own it.

## Closed allowlist — never flag these

1. `skills/_shared/` and `skills/tests/` — no `SKILL.md`, deliberately not shipped.
2. `.claude/skills/` — this audit suite is local tooling, never shipped, and must not appear in any `skills` array.
3. The two plugins sharing the repository's `name` field with one of them — the marketplace and a plugin may legitimately share a name.
4. `docs/superpowers/` specs and plans describing manifest structure.
5. Any line carrying `# manifest-exempt: <reason>`.

## Step 2 — scan

Parse `marketplace.json` for both entries' `description` and `skills`; list every directory under `skills/` that has no `SKILL.md`, and check each against the allowlist so only a genuine third case gets reported; extract each probe's `NAME` and `MARKER` and resolve both; read `hooks/hooks.json` and the script it registers, checking the early-return property; check for `commands/` or `agents/` at the root; build the file universe from `git ls-files`.

## Step 3 — severity

Critical for a `skills/` directory with no `SKILL.md` beyond the two allowlisted cases, or a non-inert shared hook; Medium for a thin description or a missing IntelliJ prerequisite; Decision for ownership questions.

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
- Do not re-report the six covering tests.
- Do not install or uninstall a plugin.
