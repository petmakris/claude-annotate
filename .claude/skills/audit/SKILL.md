---
name: audit
description: Master codebase audit for claude-annotate. Runs all focused sub-audits — `/audit-engine-boundary`, `/audit-http-surface`, `/audit-plugin-manifest`, `/audit-docs-truth`, `/audit-code-health` — then presents one unified actionable report. Use when the user says "/audit", "audit the codebase", "run a full audit", "full sweep", or wants everything checked instead of one targeted sub-audit.
user-invocable: true
---

# /audit — master orchestrator

The user runs this for the **full sweep**. This skill owns no checks itself. It dispatches the focused sub-audits and stitches their reports into one delivery. Each sub-audit is independently invocable — when the user already knows where the drift lives, run that sub-audit directly instead. This master exists for the "check everything" case.

## The audit contract (binding on every sub-audit)

An audit is only useful if its output is **actionable without hand-waving**. Every item any sub-audit returns must be **exactly one of two kinds**:

- **Violation** — objectively wrong against a written rule. A Violation must hold **100% of the time**: if a knowledgeable reader could reasonably say "that's fine because…", it is **not** a Violation and must not be reported as one. **A false positive is a bug in the sub-audit, not a nuance to explain at delivery.** When a reported item turns out to be fine, the fix is to **harden that sub-audit's SKILL.md** (add the case to its allowlist / tighten its check) so it never fires again — not to footnote it.
- **Decision** — a genuine either/or that needs the user's judgment. Still actionable — the user acts by deciding — but it lives in the **Optional / Decision** bucket, clearly labeled as a question, never mixed into the Violation buckets.

Two corollaries the sub-audits must honor:

1. **Check against a source of truth, not a regex hunch.**
2. **Build the file universe from `git ls-files`** so nothing is structurally invisible.

When delivering, if you feel the urge to write "this was flagged but it's actually fine," stop: that item should have been filtered by the sub-audit. Note it for a sub-audit fix instead of shipping it as a finding.

## Sub-audits

| Sub-audit | Owns |
|---|---|
| `/audit-engine-boundary` | One engine, reached by import rather than reimplemented; port and state-directory collisions between the three skills. |
| `/audit-http-surface` | The Python-to-Java route contract, the `FakeReviewServer` test double, and the `_is_owner` write gate. |
| `/audit-plugin-manifest` | `.claude-plugin/marketplace.json` as the registry of what ships; each skill's ability to locate itself once installed; the root-shared `hooks/`. |
| `/audit-docs-truth` | Whether the prose is true — progressive-disclosure structure across all three skills, and README and skill-doc claims against the tree. |
| `/audit-code-health` | Generic health across Python and Java — dead code, duplication, unhandled async, risky code with no test beside it. |

## Workflow

1. **Dispatch.** Run each sub-audit. If the user has approved subagent use, launch one Explore agent per sub-audit in parallel with this prompt:
   > "Follow the instructions in `.claude/skills/<sub-audit>/SKILL.md` exactly and produce that skill's report. Do not deviate from the format defined there. When done, return your full report verbatim — no preamble, no summary, no commentary."

   If subagents are not available or not approved, run the sub-audits inline, in sequence, following each SKILL.md exactly. **Never skip a sub-audit** to save time — say so explicitly if one could not be run.

2. **Wait.** Collect every sub-audit's report before formatting anything.

3. **Compose the master report.** Merge all items into one cross-audit actionable list: a top verdict line, then the priority buckets with every sub-audit's items pooled, each labeled `{audit} N` so it stays addressable.

## Output template

```
Audit — claude-annotate — actionable items

Scope: full sweep across {N} sub-audits. Scanned {M} tracked files.
Verdict: {one sentence — strongest finding across all sub-reports, or "nothing actionable across the board".}

**Critical — fix first**
1. **{audit} {n}** — {what is wrong, compressed}. {imperative fix}.

**Medium — correctness & maintainability**
...

**Low — hygiene & docs**
...

**Optional — improvements, not drift (only if you want them)**
...

Nothing actionable from: {audits that came back clean}.

Want detail on any item? Say "explain {sub-audit} N" (e.g. "explain http-surface 2") and I'll show the file:line and the fix as concrete steps.
```

**Severity → bucket mapping**: Critical/High → **Critical**; Warning/Medium → **Medium**; Info/Low → **Low**; Decisions and promotion candidates → **Optional**.

## Hard rules

1. **No own checks.** If you find yourself describing a pattern to look for, you have drifted — that pattern belongs in a sub-audit's SKILL.md.
2. **Run every sub-audit** even when early ones find plenty.
3. **Merge into the four priority buckets**, keeping each item's `{audit} N` label.
4. **One verdict line at the top.**
5. **Collapse the non-actionable into one closing line.**
6. **No file paths in the master view.**
7. **No emoji.**

## After delivering the report

Stop and wait. The user picks which finding to drill into.

"explain {sub-audit} N" and "fix {sub-audit} N" route to the owning sub-audit.

## Anti-patterns (do not do these)

- **Don't define checks here.** A new concern that fits no existing sub-audit means a **new** sub-audit, added to the dispatch table.
- **Don't re-judge sub-audit findings.** You merge and re-bucket; you do not second-guess whether a finding is real.
- **Don't editorialize across sub-reports.**
- **Don't invent items the sub-audits didn't return.**
- **Don't start a server, run pytest, or run the Gradle build.** Every sub-audit is read-only and this master inherits it.
