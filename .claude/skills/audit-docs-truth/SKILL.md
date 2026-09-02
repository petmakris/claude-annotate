---
name: audit-docs-truth
description: Audit whether the repository's prose is true — README and skill-doc claims checked against the tree, plus progressive-disclosure structure across all three skills. Finds directory names that no longer exist, install instructions that point at retired repositories, port and architecture claims that stopped being accurate, broken in-skill links and orphaned reference files. Reports in plain English. Use when the user says "/audit-docs-truth", "check the docs", or asks whether the README still describes reality.
user-invocable: true
---

# /audit-docs-truth — is the prose still true?

This is the only audit whose subject is claims rather than code. It exists because of a measured failure: during the repository merge, four false statements shipped — a README asserting the engine was vendored two paragraphs below a section saying the opposite, two skill READMEs pointing at a directory that never existed here, and a claim that both plugins drive the same server when they run three processes on three port ranges. Every one passed 737 tests. The output goes to someone who knows the architecture but is not in the code right now.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/annotate/tests/test_skill_structure.py` — guards progressive disclosure for `skills/annotate/` **only**: SKILL.md under 120 lines, every `references/…` and `docs/…` link resolving, no orphaned reference file, the block-kind menu matching the files on disk. The other two skills have no equivalent.
- `skills/tests/test_repo_structure.py::test_every_probe_marker_file_exists` — already proves the probe MARKER paths in the docs resolve.

## Step 1 — build the claim inventory

Read `README.md`, `ide-plugin/README.md`, each `skills/*/README.md`, and each `skills/*/SKILL.md`. Extract every checkable claim: directory and file paths, command names, port numbers, install instructions, repository names, cross-references between documents, and statements about how components relate.

## The rules

- **Rule 1 — a named path exists.** A directory or file named in prose that is not in the tree is a **Critical** Violation. It sends a reader somewhere that is not there. Two shipped instances at the time of writing were `intellij-plugin-spike/`, which is `ide-plugin/`, and a design-doc link under `docs/superpowers/specs/` that never existed here.
- **Rule 2 — an install instruction resolves.** A `/plugin marketplace add` or `/plugin install` line naming a marketplace or plugin that `marketplace.json` does not publish is **Critical**.
- **Rule 3 — an architectural claim matches the code.** A statement about ports, processes, shared components, or data flow that the code contradicts is **Critical**. "Both plugins drive the same local server" was false: three processes, `PORT_RANGE` 3080 / 54620–54640 / 54660–54680. Only the engine library is shared.
- **Rule 4 — a document does not contradict itself.** Two sections of one file making incompatible claims is **Critical**, regardless of which is true — a reader cannot tell which to believe.
- **Rule 5 — a retired repository is not named as live.** Prose pointing at `petmakris/web-companion` or `petmakris/claude-ide-review` as somewhere to fix bugs or install from is **Critical**; both are archived. Naming them as history is correct and must not be flagged.
- **Rule 6 — in-skill links resolve, everywhere.** Extend `test_skill_structure.py`'s link and orphan checks to `skills/ask_diff/` and `skills/walkthrough/`. A broken link is **Medium**; an orphaned reference file is **Low**.
- **Rule 7 — SKILL.md length.** The 120-line cap is a written rule for `skills/annotate/` only, enforced by its own test. `skills/ask_diff/SKILL.md` (271 lines) and `skills/walkthrough/SKILL.md` (337 lines) have no `references/` directory and no such rule. Their length is a **Decision** — a monolithic SKILL.md loads in full on every invocation, so splitting it has a real token cost benefit, but nothing binds them today. Ask; never report it as a Violation.

## Closed allowlist — never flag these

1. `docs/superpowers/specs/` and `docs/superpowers/plans/` — design documents describe a moment in time and are allowed to name things that no longer exist.
2. Archived repositories named as history rather than as a live destination.
3. `docs/REMARKS.md` and `docs/SHOTLIST.md` — scratch notes, not claims about the tree.
4. Example paths inside fenced code blocks that are illustrative rather than repository paths.
5. `ide-plugin/README.md` naming IntelliJ platform paths that live outside this repository.
6. Any line carrying `# docs-exempt: <reason>`.

## Step 2 — scan

For each extracted claim, resolve it against the tree: paths against `git ls-files`, plugin and marketplace names against `marketplace.json`, ports against the three `PORT_RANGE` values, cross-document references against the files they name. Then run the link and orphan checks over all three skills.

## Step 3 — severity

Critical for a false claim a reader would act on; Medium for a broken in-skill link; Low for an orphaned reference file; Decision for Rule 7.

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

- Do not flag design documents for describing superseded states.
- Do not treat the 120-line cap as binding on skills that never adopted progressive disclosure.
- Do not rewrite prose for style, only for truth.
- Do not run anything.
