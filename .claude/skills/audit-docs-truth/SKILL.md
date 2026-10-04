---
name: audit-docs-truth
description: Audit whether the repository's prose is true — README and skill-doc claims checked against the tree, plus progressive-disclosure structure across all nine skills. Finds directory names that no longer exist, install instructions that point at retired repositories, architecture claims that stopped being accurate (an in-repo server, per-skill ports, a vendored engine), contract numbers that disagree, broken in-skill links and orphaned reference files. Reports in plain English. Use when the user says "/audit-docs-truth", "check the docs", or asks whether the README still describes reality.
user-invocable: true
---

# /audit-docs-truth — is the prose still true?

This is the only audit whose subject is claims rather than code. It exists because of a measured failure: during the repository merge, four false statements shipped — a README asserting the engine was vendored two paragraphs below a section saying the opposite, two skill READMEs pointing at a directory that never existed here, and a claim that both plugins drove the same server when they ran separate processes on separate port ranges. Every one passed the full test suite. The architecture has since moved again — the in-repo server is deleted and every skill pushes to the separately installed webcompanion daemon — which is exactly the kind of change prose lags behind. The output goes to someone who knows the architecture but is not in the code right now.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/annotate/tests/test_skill_structure.py` — for `skills/annotate/` **only**: SKILL.md under 120 lines, every `references/…` and `docs/…` link in SKILL.md and its references resolving, no orphan reference file, the block-kind menu matching the files on disk.
- `skills/tests/test_repo_structure.py::test_every_reference_file_is_linked_from_its_skill` — for **every** skill: each `references/**/*.md` is named by its SKILL.md or a sibling reference. Orphans are covered tree-wide; do not re-report them.
- `skills/tests/test_repo_structure.py::test_every_runner_command_in_a_skill_doc_resolves`, `::test_every_path_under_the_plugin_root_exists` and `::test_every_shell_marker_file_exists` — runner commands, `$(claude-annotate root)/…` paths and annotate-doctor's `MARKER=` path in skill docs resolve.
- `skills/dataflow/tests/test_skill_doc.py` and `skills/walkthrough/tests/test_skill_doc.py` — required sections and specific stated rules in those two SKILL.md files (not link resolution).
- `skills/tests/test_requirements_documented.py` — the documented requirements.

## Step 1 — build the claim inventory

Read `README.md`, `CLAUDE.md`, `ide-plugin/README.md`, `ide-plugin/CLAUDE.md`, `vscode-plugin/README.md`, `skills/_shared/README.md`, each `skills/*/README.md`, each `skills/*/SKILL.md` and its `references/**/*.md`, and `docs/security/diagram-rendering.md`. Extract every checkable claim: directory and file paths, command names, port numbers, install instructions, repository names, contract numbers, cross-references between documents, test commands, and statements about how components relate.

The current architecture, as the tree states it (verify against the code before relying on it):

- **Nine skills:** annotate, annotate-doctor, ask_diff, dataflow, deck, show-diff, slides, specimen, walkthrough — the directories under `skills/` that have a `SKILL.md`.
- **No in-repo server.** `skills/_shared/` holds `webcompanion_client.py`, `static/` and `README.md`; `skills/_shared/web_companion/` is deleted. Every skill except `slides` pushes to the **webcompanion daemon**, a separate project (`github.com/petmakris/webcompanion`, installed with pipx or `uv tool`), whose address and write token live in `~/.claude/webcompanion/config.json`. The daemon has one port, chosen by its own config; no skill has a `PORT_RANGE`.
- **Contract version** is stated in `skills/_shared/webcompanion_client.py`, `vscode-plugin/src/webcompanionClient.js`, `ide-plugin/.../WebCompanionHttp.java`, `skills/annotate/static/daemon-http.js`, `skills/annotate-doctor/doctor.sh` and `skills/show-diff/show-diff.sh`.
- **Skills reach their code through `bin/claude-annotate`**; annotate-doctor alone uses a plain-`sh` `MARKER=` locator.
- **Tests run** with the command in `CLAUDE.md`; browser and daemon tests start a private daemon per worker (`skills/conftest.py`, `skills/tests/harness.py`).

## The rules

- **Rule 1 — a named path exists.** A directory or file named in prose that is not in `git ls-files` is a **Critical** Violation; it sends a reader somewhere that is not there. Likely instances after the server removal: anything under `skills/_shared/web_companion/`, a per-skill `server.py`, `ensure_server.sh`, `watcher.sh`, `cleanup.py`, `skills/specimen/webcompanion/`.
- **Rule 2 — an install instruction resolves.** A `/plugin marketplace add` or `/plugin install` line naming a marketplace or plugin that `.claude-plugin/marketplace.json` does not publish is **Critical**. So is a daemon install or upgrade command that names a package or tool other than `webcompanion`.
- **Rule 3 — an architectural claim matches the code.** A statement that this repository runs, starts, or ships a server; that a skill has its own port or `PORT_RANGE`; that the engine is vendored or shared by copy; that a skill other than `slides` works without the daemon (or that `slides` needs it); or any other claim about processes, shared components or data flow that the code contradicts — **Critical**. A stated skill count other than nine, or a list of skills that omits or invents one, is **Critical** when it is presented as the full set.
- **Rule 4 — stated numbers agree with their source.** A contract number in prose that differs from the code's `CONTRACT` values, a test count, line count or file count stated as current fact that the tree contradicts, or a test command that differs from the one in `CLAUDE.md` — **Medium**. Counts presented as history ("passed 737 tests at the time") are not claims about the present.
- **Rule 5 — a document does not contradict itself.** Two sections of one file making incompatible claims is **Critical**, regardless of which is true — a reader cannot tell which to believe.
- **Rule 6 — a retired repository is not named as live.** Prose pointing at `petmakris/web-companion` (hyphenated) or `petmakris/claude-ide-review` as somewhere to install from or file bugs against is **Critical**; both are superseded. Naming them as history is correct and must not be flagged. `petmakris/webcompanion` (no hyphen) is the live daemon and is never a finding.
- **Rule 7 — in-skill links resolve, everywhere.** Extend `test_skill_structure.py`'s link check — every relative Markdown link `[...](references/...)`, `[...](docs/...)` or `[...](../...)` in a SKILL.md or reference file resolving to a file — to the eight skills other than annotate. A broken link is **Medium**.
- **Rule 8 — SKILL.md length.** The 120-line cap is a written rule for `skills/annotate/` only, enforced by its own test. The other skills have `references/` directories (all but annotate-doctor) but no length rule; several SKILL.md files run to 250–400+ lines. Their length is a **Decision** — a long SKILL.md loads in full on every invocation, so moving detail into `references/` has a real token cost benefit, but nothing binds them today. Ask; never report it as a Violation, and measure with `wc -l` at audit time rather than quoting figures from here.

## Closed allowlist — never flag these

1. `docs/superpowers/specs/` and `docs/superpowers/plans/` — design documents describe a moment in time and may name things that no longer exist.
2. `docs/security/diagram-rendering.md` describing the D2 attempt it records as reverted — it is a dated decision record; only its claims about the present are in scope.
3. Superseded repositories, the deleted `skills/_shared/web_companion/`, and old per-skill servers named as history — e.g. the "History" section of `skills/_shared/README.md`, the README section naming the superseded repositories, annotate-doctor's note on leftover `server.json` files.
4. `docs/SHOTLIST.md` — a recording spec, not a claim about the tree.
5. Example paths inside fenced code blocks that are illustrative rather than repository paths.
6. `ide-plugin/README.md` and `vscode-plugin/README.md` naming IDE platform paths that live outside this repository, and any prose naming the daemon's own files (`~/projects/webcompanion/...`, `docs/contract.md`) — those live in the daemon's repository.
7. `skills/slides/SKILL.md`'s `python3 -m http.server 8777` deck preview — a port the user opens by hand for one preview, not a server this repository runs; it does not contradict Rule 3.
8. Any line carrying `# docs-exempt: <reason>`.

## Step 2 — scan

For each extracted claim, resolve it against the tree: paths against `git ls-files`, plugin and marketplace names against `marketplace.json`, the skill set against `skills/*/SKILL.md`, contract numbers against the `CONTRACT` constants listed above, test commands against `CLAUDE.md`, cross-document references against the files they name. Then run the link check over the eight skills `test_skill_structure.py` does not cover, and `wc -l` every SKILL.md for Rule 8.

## Step 3 — severity

Critical for a false claim a reader would act on; Medium for a disagreeing number, a stale test command or a broken in-skill link; Low for wording that is technically true but points the reader at the wrong thing; Decision for Rule 8.

## Output template

```
Docs truth audit — actionable items

Checked {N} claims across {M} documents.
Verdict: {one sentence.}

**Critical — fix first**
1. {The claim, and what is actually true}. {Imperative fix}. — {document}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {SKILL.md length without a progressive-disclosure rule — split it or leave it?} — {skill}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

## After delivering the report

Stop and wait. `explain N` quotes the claim, shows what the tree actually contains, and gives the fix. `fix N` applies it. False positive means fixing this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not flag design documents or history sections for describing superseded states.
- Do not treat the 120-line cap as binding on skills that never adopted it.
- Do not re-report orphaned reference files; the tree-wide test owns them.
- Do not rewrite prose for style, only for truth.
- Do not run anything beyond `git ls-files`, `grep` and `wc`.
