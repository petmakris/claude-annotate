# Audit Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give this repository a local audit suite that finds the drift its 737 tests cannot see.

**Architecture:** Six skills under `.claude/skills/`. One umbrella `/audit` that owns no checks and dispatches the rest, plus five sub-audits that each own exactly one source of truth. Each is a single `SKILL.md` — prose, not code. A structural test in `skills/tests/` keeps the umbrella's dispatch table and the sub-audits on disk from drifting apart.

**Tech Stack:** Markdown skills with YAML frontmatter, read by Claude Code. One pytest file for structural guards. No runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-06-audit-suite-design.md`

## Global Constraints

- Skills go in `.claude/skills/`, never `skills/`. `skills/` is shipped plugin content and `test_plugin_skill_lists_partition_the_skills_tree` asserts every directory there with a `SKILL.md` appears in a plugin's `skills` array.
- Every sub-audit is **read-only**: it never starts a server, runs a test suite, edits a file, or runs `gh`.
- Every sub-audit's frontmatter is exactly three keys: `name` (equal to its directory name), `description`, `user-invocable: true`.
- Every item a sub-audit reports is a **Violation** (objectively wrong against a written rule, true 100% of the time) or a **Decision** (a genuine either/or for the user). A false positive is a bug in the sub-audit, fixed by hardening its allowlist — never footnoted at delivery.
- Every sub-audit names its covering tests and reports only what those tests do not already enforce.
- No emoji anywhere in the suite. No file paths or code snippets in a main report; `explain N` produces those.
- Test baseline before any change: `python3 -m pytest skills -q` reports **737 passed**. Task 1 takes it to 742; Tasks 2–6 leave it at 742.
- Check the working tree is clean (`git status --porcelain` showing only untracked `docs/REMARKS.md`) before trusting any test count.

---

### Task 1: Scaffolding, the structural test, and the umbrella

Creates the suite's home, the guard that keeps it coherent, the umbrella, and the first sub-audit. The first sub-audit ships here rather than in its own task because the umbrella's dispatch table cannot be non-empty without it, and an empty table would make the sync test vacuous.

**Files:**
- Modify: `.gitignore:8`
- Create: `skills/tests/test_audit_suite.py`
- Create: `.claude/skills/audit/SKILL.md`
- Create: `.claude/skills/audit-engine-boundary/SKILL.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `skills/tests/test_audit_suite.py` with module constants `ROOT: Path` (repository root), `SUITE: Path` (`.claude/skills`), `REQUIRED_SECTIONS: tuple[str, ...]`, and helpers `_audit_dirs() -> list[Path]` and `_frontmatter(md: Path) -> dict[str, str]`. Later tasks add no tests; they rely on `test_umbrella_dispatch_table_matches_disk` and `test_sub_audits_carry_the_required_sections` to enforce their work.

- [ ] **Step 1: Un-ignore the suite**

`.gitignore` line 8 is currently `.claude/`, which would leave every audit untracked. Replace that single line with:

```
.claude/*
!.claude/skills/
```

Verify:
```bash
mkdir -p .claude/skills/audit
git check-ignore -v .claude/skills/audit/SKILL.md && echo "STILL IGNORED — wrong" || echo "OK: trackable"
```
Expected: `OK: trackable`

- [ ] **Step 2: Write the failing test**

Create `skills/tests/test_audit_suite.py`:

```python
"""Structural guards for the local audit suite under .claude/skills/.

The suite is prose, not code, so its failure modes are structural: the
umbrella dispatching a sub-audit that does not exist, a sub-audit nobody
dispatches, or a SKILL.md missing the frontmatter that makes it invocable.
Each of those breaks the suite silently — /audit still runs, it just stops
covering something.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / ".claude" / "skills"

# Every sub-audit must carry these. They are the parts that make a report
# actionable rather than a wall of observations.
REQUIRED_SECTIONS = (
    "## The audit contract",
    "## Output template",
    "## After delivering the report",
    "## Anti-patterns",
)


def _audit_dirs() -> list[Path]:
    return sorted(p for p in SUITE.glob("audit*") if (p / "SKILL.md").is_file())


def _frontmatter(md: Path) -> dict[str, str]:
    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{md} has no frontmatter"
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def test_suite_exists():
    assert _audit_dirs(), "no audit skills found under .claude/skills/"


def test_every_audit_is_user_invocable():
    bad = [
        d.name
        for d in _audit_dirs()
        if _frontmatter(d / "SKILL.md").get("user-invocable") != "true"
    ]
    assert not bad, f"audits must be user-invocable: {bad}"


def test_frontmatter_name_matches_directory():
    bad = [
        (d.name, _frontmatter(d / "SKILL.md").get("name"))
        for d in _audit_dirs()
        if _frontmatter(d / "SKILL.md").get("name") != d.name
    ]
    assert not bad, f"frontmatter name must equal directory name: {bad}"


def test_umbrella_dispatch_table_matches_disk():
    # The umbrella's whole job is dispatch. A sub-audit it forgets is a
    # silent hole in the full sweep; one it names but that does not exist
    # is a broken run.
    umbrella = SUITE / "audit" / "SKILL.md"
    named = set(re.findall(r"`/(audit-[a-z-]+)`", umbrella.read_text(encoding="utf-8")))
    on_disk = {d.name for d in _audit_dirs() if d.name != "audit"}
    assert named == on_disk, (
        f"umbrella dispatches {sorted(named)} but disk has {sorted(on_disk)}"
    )


def test_sub_audits_carry_the_required_sections():
    missing = []
    for d in _audit_dirs():
        if d.name == "audit":
            continue
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        missing += [f"{d.name} -> {s}" for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, f"sub-audits missing required sections: {missing}"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -q`
Expected: FAIL. `test_suite_exists` fails with "no audit skills found" — nothing has a `SKILL.md` yet. The others fail or error on the missing umbrella.

- [ ] **Step 4: Write the umbrella**

Create `.claude/skills/audit/SKILL.md`. Frontmatter exactly:

```yaml
---
name: audit
description: Master codebase audit for claude-annotate. Runs all focused sub-audits — `/audit-engine-boundary` — then presents one unified actionable report. Use when the user says "/audit", "audit the codebase", "run a full audit", "full sweep", or wants everything checked instead of one targeted sub-audit.
user-invocable: true
---
```

**The description names only the sub-audits that exist.** `test_umbrella_dispatch_table_matches_disk` scans the whole file, frontmatter included, so naming a sub-audit here before it is written fails the test. Each later task adds its own name to **both** the description and the dispatch table. That is deliberate rather than incidental: the description is what routes `/audit`, so it should never advertise a sweep wider than the one that runs.

By the end of Task 5 the description reads:

> Master codebase audit for claude-annotate. Runs all focused sub-audits — `/audit-engine-boundary`, `/audit-http-surface`, `/audit-plugin-manifest`, `/audit-docs-truth`, `/audit-code-health` — then presents one unified actionable report. Use when the user says "/audit", "audit the codebase", "run a full audit", "full sweep", or wants everything checked instead of one targeted sub-audit.

The body must contain, in this order:

1. **`# /audit — master orchestrator`** and a paragraph stating this skill owns no checks and exists for the "check everything" case; each sub-audit is independently invocable when the user already knows where the drift lives.

2. **`## The audit contract (binding on every sub-audit)`** — the Violation / Decision definitions from the Global Constraints above, stated in full, plus the two corollaries: check against a source of truth rather than a regex hunch, and build the file universe from `git ls-files` so nothing is structurally invisible. Include the closing instruction: if you feel the urge to write "this was flagged but it's actually fine", that item should have been filtered by the sub-audit — note it for a sub-audit fix instead of shipping it as a finding.

3. **`## Sub-audits`** — a table with one row per sub-audit. Each sub-audit name must appear as `` `/audit-name` `` so the sync test sees it. Rows, with the "Owns" text:

   | Sub-audit | Owns |
   |---|---|
   | `/audit-engine-boundary` | One engine, reached by import rather than reimplemented; port and state-directory collisions between the three skills. |
   | `/audit-http-surface` | The Python-to-Java route contract, the `FakeReviewServer` test double, and the `_is_owner` write gate. |
   | `/audit-plugin-manifest` | `.claude-plugin/marketplace.json` as the registry of what ships; each skill's ability to locate itself once installed; the root-shared `hooks/`. |
   | `/audit-docs-truth` | Whether the prose is true — progressive-disclosure structure across all three skills, and README and skill-doc claims against the tree. |
   | `/audit-code-health` | Generic health across Python and Java — dead code, duplication, unhandled async, risky code with no test beside it. |

   **In Task 1 this table contains only the `/audit-engine-boundary` row.** Each later task adds its own row. The sync test fails if a row names a sub-audit that does not exist yet.

4. **`## Workflow`** — three numbered steps: dispatch each sub-audit (one Explore agent each, in parallel, with the prompt `"Follow the instructions in .claude/skills/<sub-audit>/SKILL.md exactly and produce that skill's report. Do not deviate from the format defined there. When done, return your full report verbatim — no preamble, no summary, no commentary."`, falling back to inline sequential runs when subagents are unavailable, never skipping one silently); wait for every report before formatting anything; compose the master report.

5. **`## Output template`** — a fenced block matching this shape exactly:

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

   Follow it with the severity mapping table: Critical/High → **Critical**; Warning/Medium → **Medium**; Info/Low → **Low**; Decisions and promotion candidates → **Optional**.

6. **`## Hard rules`** — numbered: no own checks (a pattern to look for belongs in a sub-audit); run every sub-audit even when early ones find plenty; merge into the four buckets keeping each `{audit} N` label; one verdict line at the top; collapse the non-actionable into one closing line; no file paths in the master view; no emoji.

7. **`## After delivering the report`** — stop and wait; `explain {sub-audit} N` and `fix {sub-audit} N` route to the owning sub-audit.

8. **`## Anti-patterns (do not do these)`** — do not define checks here; do not re-judge sub-audit findings; do not editorialize across sub-reports; do not invent items the sub-audits did not return; do not start a server, run pytest, or run the Gradle build — every sub-audit is read-only and this master inherits it.

- [ ] **Step 5: Write audit-engine-boundary**

Create `.claude/skills/audit-engine-boundary/SKILL.md`. Frontmatter:

```yaml
---
name: audit-engine-boundary
description: Audit the shared server engine boundary — that `skills/_shared/web_companion/` is the one copy, reached by import rather than reimplemented, and that the three skills do not collide on ports or state directories. Finds hand-rolled reimplementations of engine behaviour, resurrected vendoring artifacts, overlapping PORT_RANGEs and duplicate skill_names. Reports in plain English. Use when the user says "/audit-engine-boundary", "check the engine boundary", or asks whether the shared server is still shared.
user-invocable: true
---
```

Body sections, in order:

**`# /audit-engine-boundary — one engine, reached by import`** — a paragraph explaining that three repositories became one so this engine would exist once; two copies previously drifted 192 lines apart in `server.py`, which is what the merge deleted. The output goes to someone who knows the architecture but is not in the code right now: plain English, no code snippets in the main report.

**`## The audit contract (read first)`** — Violation / Decision as in the Global Constraints.

**`## Covering tests — read these first, do not duplicate them`**

- `skills/tests/test_repo_structure.py::test_no_vendoring_artifacts` — asserts `VENDOR.txt` and `VENDOR.sha256` do not exist.
- `skills/tests/test_repo_structure.py::test_engine_is_not_marked_generated` — asserts no `.py` or `.sh` under `skills/_shared/` contains `GENERATED FILE`.

Report only what these do not enforce, plus anywhere either has gone stale.

**`## Step 1 — load the sources of truth`**

1. `skills/_shared/web_companion/` — every module, and what each provides.
2. `skills/annotate/server.py`, `skills/interactive_review/server.py`, `skills/walkthrough/server.py` — the three consumers.
3. `skills/_shared/web_companion/server.py` — the `run()` signature, which is how a skill declares `skill_name` and `port_range`.

**`## The rules`**

- **Rule 1 — the engine is imported, never reimplemented.** A skill that hand-rolls behaviour the engine already provides is a **Critical** Violation: its own atomic write instead of `atomic.py`, its own SSE framing instead of `events.py`, its own session-directory walk instead of `sessions.py`, its own thread store instead of `threads.py`. This is how two copies come back without a single banner reappearing. The fix is always the same: import it.
- **Rule 2 — no import reaches the engine by another path.** Every engine import must read `skills._shared.web_companion.*`. A `sys.path` manipulation, a relative import climbing out of a skill, or a duplicated module file is **Critical**.
- **Rule 3 — vendoring stays dead.** Any resurrected `VENDOR*` file, `GENERATED FILE` banner, or sync/check script anywhere in the tree is **Critical**. The covering tests above catch the two known filenames; this rule covers the rest of the shape, including a new script under `tools/` or a CI job that re-derives the tree.
- **Rule 4 — port ranges stay disjoint.** `PORT_RANGE` in the three skill servers must not overlap. Today: annotate 3080, interactive-review 54620–54640, walkthrough 54660–54680. An overlap is **Critical** — two skills race for a port and the loser reports a stale one.
- **Rule 5 — `skill_name` is unique per skill.** The value each skill passes to `run(skill_name=...)` determines `~/.claude/<skill_name>/server.json`, which carries the live port and the write token. Two skills sharing a name is **Critical**: each would overwrite the other's connection details and intermittently drive the other's server.
- **Rule 6 — engine changes that only one consumer uses.** A function in the engine called by exactly one skill is a **Decision**, not a Violation. It may be a shared capability nobody adopted yet, or skill-specific logic that leaked into the shared layer. Ask which.

**`## Closed allowlist — never flag these`**

1. The three per-skill `server.py` **handler** modules. They are meant to be distinct — the engine owns transport, the skill owns its routes' meaning.
2. The 8-line per-skill `ensure_server.sh` shims. They deliberately delegate to the 153-line one in `_shared`.
3. `skills/_shared/web_companion/tests/` naming engine internals — that is its job.
4. This audit suite (`.claude/skills/audit*/`) naming engine modules to describe them.
5. The spec and plan documents under `docs/superpowers/`, which describe the vendoring that was removed.
6. Any line carrying `# engine-exempt: <reason>`.

**`## Step 2 — scan`** — enumerate engine modules and the public names each exports; grep the three skill servers for those names to find who imports what; grep the same files for the behaviours in Rule 1 implemented locally; extract each `PORT_RANGE` and each `run(skill_name=...)` argument and diff them; build the file universe from `git ls-files`.

**`## Step 3 — severity`** — Critical for anything that reintroduces a second implementation or collides at runtime; Medium for a near-duplicate that has not fully diverged; Low for cosmetic drift; Decision for the Rule 6 case.

**`## Output template`**

```
Engine boundary audit — actionable items

Checked {N} engine modules against {M} consumers.
Verdict: {one sentence.}

**Critical — fix first**
1. {What drifted}. {Imperative fix}. — {area}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {Engine function used by one skill — shared capability or leaked specifics?} — {area}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

**`## After delivering the report`** — stop and wait, do not edit. `explain N` gives the file:line on both sides and the fix as concrete steps. `fix N` applies it. When an item turns out to be a false positive, fix this skill's allowlist first.

**`## Anti-patterns (do not do these)`** — do not flag the per-skill handler modules as duplication; do not demand the engine absorb skill-specific route meaning; do not re-report what the two covering tests already enforce; do not start a server or run the test suite.

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -q`
Expected: `5 passed`

- [ ] **Step 7: Run the full suite on a clean tree**

Run:
```bash
git add -A
git status --porcelain
python3 -m pytest skills -q
```
Expected: `742 passed` (737 + 5). The `git add -A` first is deliberate — a count measured against unstaged work is the exact failure this repository already hit once.

- [ ] **Step 8: Commit**

```bash
git commit -m "feat(audit): the suite's scaffolding, its guard, and the engine-boundary audit

737 tests answer questions known in advance. They cannot see a README
claim that stopped being true or a skill that reimplemented something the
engine already provides.

.gitignore blanket-ignored .claude/, which would have left the suite
untracked; it now allowlists .claude/skills/ the way dashboard and lomem
do.

The structural test guards what this pattern actually drifts on: the
umbrella naming a sub-audit that does not exist, or forgetting one that
does."
```

---

### Task 2: audit-http-surface

The Python-to-Java contract. There is no route registry — the HTTP surface is `if self.path == "..."` across the engine and three handler modules — so three lists must agree and nothing makes them.

**Files:**
- Create: `.claude/skills/audit-http-surface/SKILL.md`
- Modify: `.claude/skills/audit/SKILL.md` (add its dispatch-table row)

**Interfaces:**
- Consumes: the umbrella's `## Sub-audits` table from Task 1.
- Produces: nothing later tasks read.

- [ ] **Step 1: Confirm the test currently fails for the right reason**

Add the row to the umbrella's `## Sub-audits` table:

```markdown
| `/audit-http-surface` | The Python-to-Java route contract, the `FakeReviewServer` test double, and the `_is_owner` write gate. |
```

and add `` `/audit-http-surface` `` to the umbrella's frontmatter `description`, after `` `/audit-engine-boundary` ``.

Run: `python3 -m pytest skills/tests/test_audit_suite.py::test_umbrella_dispatch_table_matches_disk -q`
Expected: FAIL — the umbrella dispatches `audit-http-surface` but no such directory exists.

- [ ] **Step 2: Write the skill**

Create `.claude/skills/audit-http-surface/SKILL.md`. Frontmatter:

```yaml
---
name: audit-http-surface
description: Audit the HTTP surface the IntelliJ plugin talks to — that every route the Java client calls exists server-side, that FakeReviewServer matches the routes the client actually uses, and that every mutating route sits behind the _is_owner write gate. Finds client-server route drift, a stale test double, and unguarded writes. Reports in plain English. Use when the user says "/audit-http-surface", "check the route contract", or asks whether the IDE plugin and the server still agree.
user-invocable: true
---
```

Body sections, in order:

**`# /audit-http-surface — three lists that must agree`** — explain that there is no route registry. The surface is a sequence of `if self.path == "..."` comparisons in `skills/_shared/web_companion/server.py` and the three per-skill handler modules. Three lists must agree and nothing enforces it: what the server implements, what the IntelliJ client calls, and what `FakeReviewServer.java` implements. When the third drifts, the Java suite passes against a fake that does not match the server, and the suite becomes less trustworthy the longer it goes unnoticed.

**`## The audit contract (read first)`** — Violation / Decision as in the Global Constraints.

**`## Covering tests — read these first, do not duplicate them`**

- `skills/_shared/web_companion/tests/test_write_gate.py` — asserts specific routes reject non-owner writes. Read its route list; report only routes it omits.
- `skills/_shared/web_companion/tests/test_route_resolve.py` — asserts path resolution. Do not re-derive what it covers.
- `ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java` and `WalkthroughSessionClientTest.java` — the Java client tests, which run against `FakeReviewServer`.

**`## Step 1 — load the sources of truth`**

1. `skills/_shared/web_companion/server.py` — the shared path dispatch, `_match_session` (the session-scoped route matcher), and `_is_owner` at the write gate.
2. `skills/annotate/server.py`, `skills/interactive_review/server.py`, and `skills/walkthrough/server.py` — the three per-skill `Handlers` classes.
3. `ide-plugin/src/main/java/com/petros/ireview/ReviewSessionClient.java` and `WalkthroughSessionClient.java` — every path the client requests.
4. `ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java` — the test double.

**`## The rules`**

- **Rule 1 — every route the client calls exists.** A path requested by either Java client with no matching branch server-side is **Critical**: the feature fails at runtime and no test catches it, because the Java tests run against the fake.
- **Rule 2 — the fake covers what the client uses.** A path the client calls that `FakeReviewServer` does not implement is **Critical**. Known instance at the time of writing: `ReviewSessionClient.java` calls `/api/threads/delete`, the engine implements it at `skills/_shared/web_companion/server.py:708`, and the fake does not. A fake that diverges from its subject makes every Java test that touches it meaningless.
- **Rule 3 — every mutating route is gated.** Any branch that writes — creates a session, submits an event, deletes a thread, acknowledges, cancels — must call `_is_owner` before mutating. An ungated write is **Critical**: the gate is the only thing between a non-loopback client and a write. A gated read is correct, not a Violation, **when the read exposes data across sessions** — `GET /` and `/api/sessions` are the standing examples, each listing every workspace on the machine, and must never be flagged. A gated read that exposes only its own session's data is **Medium**, since it breaks sharing for no benefit.
- **Rule 4 — one route, one implementation.** The same path handled in both the engine and a per-skill handler is **Medium** — the resolution order decides which wins and the loser is dead code that reads as live.
- **Rule 5 — no hand-maintained route list elsewhere.** A constant array of paths in the Java client, a switch in the frontend JS, or a table in a doc that enumerates routes is **Medium**. Describing the mechanism is fine; enumerating the routes is a second list.
- **Rule 6 — a server route no client calls.** **Decision**, not a Violation — it may be a deliberate API for a future client or for `reply_cli.py`. Surface it and ask.

**`## Closed allowlist — never flag these`**

1. `/health` and `/api/whoami` — diagnostics, deliberately unauthenticated reads.
2. Static asset paths under `/static/` — served by `static_serve.py`, not part of the client contract.
3. `skills/_shared/web_companion/tests/test_write_gate.py` naming routes on purpose.
4. This audit suite naming routes to describe them.
5. The `/s/<session>/` prefix — a routing prefix, not a route.
6. `GET /` and `/api/sessions` being gated reads — the workspace index and the data behind it, deliberately owner-only because both list every session on the machine.
7. Any line carrying `# route-exempt: <reason>`.

**`## Step 2 — scan`** — routes come in two forms and both must be extracted: top-level `self.path ==` / `self.path.startswith(` literals in the engine and the three handler modules, and session-scoped `rest ==` literals inside the `_match_session("/s/")` branch (a session-scoped route's full path is `/s/<session>/<rest>`, so a client calling `/s/abc/api/threads/delete` is calling the route recorded as `rest == "/api/threads/delete"`). Extract every path string from both Java clients and from `FakeReviewServer`, normalizing session-scoped client calls the same way; diff the three sets pairwise; for each mutating branch, check whether `_is_owner` is called before the mutation; build the file universe from `git ls-files`.

**`## Step 3 — severity`** — Critical for a route the client calls that is missing server-side or from the fake, and for an ungated write; Medium for a double implementation, a gated read, or a shadow list; Decision for an uncalled server route.

**`## Output template`**

```
HTTP surface audit — actionable items

Checked {N} server routes against {M} client calls and the test double.
Verdict: {one sentence.}

**Critical — fix first**
1. {What drifted}. {Imperative fix}. — {area}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {Server route no client calls — future API or dead weight?} — {area}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

**`## After delivering the report`** — stop and wait, do not edit. `explain N` gives the path, the file:line on each of the three sides, and the fix. `fix N` applies it — adding a route means the server branch plus the fake, never the client alone. False positive means fixing this skill's allowlist first.

**`## Anti-patterns (do not do these)`** — do not propose a route registry as the fix for a single drift; do not flag diagnostics or static paths; do not gate reads; do not run the server or the Java suite.

- [ ] **Step 3: Run the sync test to verify it passes**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -q`
Expected: `5 passed`

- [ ] **Step 4: Run the full suite on a clean tree**

Run:
```bash
git add -A && git status --porcelain && python3 -m pytest skills -q
```
Expected: `742 passed` — unchanged. This task adds a skill, not a test.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(audit): the HTTP surface audit

Three lists must agree and nothing makes them: what the server
implements, what the IntelliJ client calls, and what FakeReviewServer
implements. The client already calls /api/threads/delete against a fake
that does not have it, so the Java tests touching delete prove nothing."
```

---

### Task 3: audit-plugin-manifest

**Files:**
- Create: `.claude/skills/audit-plugin-manifest/SKILL.md`
- Modify: `.claude/skills/audit/SKILL.md` (add its dispatch-table row)

**Interfaces:**
- Consumes: the umbrella's `## Sub-audits` table.
- Produces: nothing later tasks read.

- [ ] **Step 1: Add the row and confirm the sync test fails**

Add to the umbrella's `## Sub-audits` table:

```markdown
| `/audit-plugin-manifest` | `.claude-plugin/marketplace.json` as the registry of what ships; each skill's ability to locate itself once installed; the root-shared `hooks/`. |
```

and add `` `/audit-plugin-manifest` `` to the umbrella's frontmatter `description`.

Run: `python3 -m pytest skills/tests/test_audit_suite.py::test_umbrella_dispatch_table_matches_disk -q`
Expected: FAIL — dispatches `audit-plugin-manifest`, no such directory.

- [ ] **Step 2: Write the skill**

Create `.claude/skills/audit-plugin-manifest/SKILL.md`. Frontmatter:

```yaml
---
name: audit-plugin-manifest
description: Audit `.claude-plugin/marketplace.json` — the registry of what ships — against the skills on disk, each skill's plugin-root probe, and the root-shared hooks file. Finds skills claimed by two plugins or none, probes that name the wrong marketplace, stale MARKER paths, and hooks that reach a plugin they were not written for. Reports in plain English. Use when the user says "/audit-plugin-manifest", "check what ships", or asks whether both plugins still install correctly.
user-invocable: true
---
```

Body sections, in order:

**`# /audit-plugin-manifest — what ships, and whether it can find itself`** — explain that two plugins share one root and are separated only by their `skills` arrays, so `marketplace.json` is the sole statement of which skill belongs to which plugin. A skill also has to locate its own installed directory at runtime, by resolving a marketplace name against `~/.claude/plugins/known_marketplaces.json` and then verifying a MARKER file exists under the candidate root. `test_every_probe_asks_for_the_real_marketplace_name` catches a probe whose `NAME` disagrees with this repo's `marketplace.json` — but nothing can catch the resolution failing on an installed copy: the marketplace registered under a different name, the registry entry missing from `known_marketplaces.json` altogether, or the MARKER file absent from the installed tree. Any of those and the skill simply aborts with "plugin root not found" for the user and nobody else.

**`## The audit contract (read first)`** — Violation / Decision as in the Global Constraints.

**`## Covering tests — read these first, do not duplicate them`**

- `skills/tests/test_repo_structure.py::test_marketplace_publishes_two_plugins_from_one_root`
- `skills/tests/test_repo_structure.py::test_plugin_skill_lists_partition_the_skills_tree`
- `skills/tests/test_repo_structure.py::test_no_root_plugin_json`
- `skills/tests/test_repo_structure.py::test_every_probe_asks_for_the_real_marketplace_name`
- `skills/tests/test_repo_structure.py::test_every_probe_marker_file_exists`
- `skills/tests/test_repo_structure.py::test_probe_failure_messages_name_the_real_marketplace`

These cover the mechanical checks thoroughly. Report only what they do not enforce, plus anywhere one has gone stale.

**`## Step 1 — load the sources of truth`**

1. `.claude-plugin/marketplace.json` — the two entries, their `source`, `strict`, `description` and `skills`.
2. Each `skills/*/SKILL.md` — the embedded plugin-root probe.
3. `hooks/hooks.json` — the root-shared hook registration.
4. `skills/annotate/hooks/progress_publish.py` — the hook the root file registers.

**`## The rules`**

- **Rule 1 — both entries stay structurally identical, beyond what the tests already check.** `test_marketplace_publishes_two_plugins_from_one_root` already enforces `"source": "./"` and `"strict": false` on both entries, and `test_no_root_plugin_json` already enforces that no root `plugin.json` exists — a red pytest run reports those three conditions more precisely than this audit could, so do not re-report them. They matter because a subdirectory source would force a second copy of `skills/_shared/`, undoing the merge, and because metadata lives in the entry precisely because there is no root `plugin.json` left to hold it — but that reasoning is context, not something to flag here. What the tests do not see: a `source` value that is some third shape, neither `"./"` nor a subdirectory path (a URL, a git ref); a `strict` key missing from the entry entirely rather than present and `false`; or an entry missing `description` or `skills` outright. Any of these is **Critical**.
- **Rule 2 — every shipped skill is reachable, beyond what the partition test already checks.** `test_plugin_skill_lists_partition_the_skills_tree` already enforces that no skill directory with a `SKILL.md` goes unlisted or gets listed by both entries — do not re-report either case. What the partition test cannot see: a `skills` array entry naming a path that does not exist on disk at all, and a directory under `skills/` that has no `SKILL.md` — the partition test only ever considers directories that already have one, so a skill left without its `SKILL.md` never enters its comparison and could sit there unshipped indefinitely without anything noticing. Either is **Critical**.
- **Rule 3 — descriptions are the install-time prose.** An entry `description` that restates the plugin name and nothing more is **Medium**: it is what a user reads when choosing whether to install.
- **Rule 4 — a root-shared surface reaches both plugins.** Anything at the repository root that Claude Code loads per-plugin — `hooks/`, and `commands/` or `agents/` if they ever appear — is claimed by both entries. A hook there that is not inert for the plugin it was not written for is **Critical**. Today `hooks/hooks.json` registers `progress_publish.py`, which returns immediately when the session has no pending annotate rounds and always exits 0. A newly added hook without that property is a Violation.
- **Rule 5 — the IDE half is named honestly.** `claude-ide-review`'s description must state that it requires the companion IntelliJ plugin. Without the IDE half its commands fail by doing nothing visible, which reads as a broken skill. A description that omits it is **Medium**.
- **Rule 6 — a skill that could belong to either plugin.** **Decision**, not a Violation. Ask which plugin should own it.

**`## Closed allowlist — never flag these`**

1. `skills/_shared/` and `skills/tests/` — no `SKILL.md`, deliberately not shipped.
2. `.claude/skills/` — this audit suite is local tooling, never shipped, and must not appear in any `skills` array.
3. The two plugins sharing the repository's `name` field with one of them — the marketplace and a plugin may legitimately share a name.
4. `docs/superpowers/` specs and plans describing manifest structure.
5. Any line carrying `# manifest-exempt: <reason>`.

**`## Step 2 — scan`** — parse `marketplace.json`; list directories under `skills/` containing a `SKILL.md` and diff against the union of the `skills` arrays — this diff surfaces both a listed path absent from disk and an on-disk skill absent from every entry; separately, list directories under `skills/` that have no `SKILL.md` at all, since the first pass never considers them; extract each probe's `NAME` and `MARKER` and resolve both; read `hooks/hooks.json` and the script it registers, checking the early-return property; check for `commands/` or `agents/` at the root; build the file universe from `git ls-files`.

**`## Step 3 — severity`** — Critical for a `skills` array entry naming a path that does not exist, a skill directory with no `SKILL.md` that the partition test cannot see, a `source` that is neither `"./"` nor a subdirectory, a `strict` key missing entirely, an entry missing `description` or `skills`, or a non-inert shared hook; Medium for thin descriptions or a missing IntelliJ prerequisite; Decision for ownership questions.

**`## Output template`**

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

**`## After delivering the report`** — stop and wait. `explain N` gives the entry, the file:line, and the fix. `fix N` applies it. False positive means fixing this skill's allowlist first.

**`## Anti-patterns (do not do these)`** — do not propose moving plugins into subdirectories; do not flag `.claude/skills/` as an unshipped skill; do not re-report the six covering tests; do not install or uninstall a plugin.

- [ ] **Step 3: Run the sync test**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -q`
Expected: `5 passed`

- [ ] **Step 4: Run the full suite on a clean tree**

Run:
```bash
git add -A && git status --porcelain && python3 -m pytest skills -q
```
Expected: `742 passed`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(audit): the plugin manifest audit

Two plugins share one root and are separated only by their skills
arrays, so marketplace.json is the only statement of what ships. The
runtime half — whether a skill can find its own installed directory —
has no test, because it only fails on an installed copy."
```

---

### Task 4: audit-docs-truth

**Files:**
- Create: `.claude/skills/audit-docs-truth/SKILL.md`
- Modify: `.claude/skills/audit/SKILL.md` (add its dispatch-table row)

**Interfaces:**
- Consumes: the umbrella's `## Sub-audits` table.
- Produces: nothing later tasks read.

- [ ] **Step 1: Add the row and confirm the sync test fails**

Add to the umbrella's `## Sub-audits` table:

```markdown
| `/audit-docs-truth` | Whether the prose is true — progressive-disclosure structure across all three skills, and README and skill-doc claims against the tree. |
```

and add `` `/audit-docs-truth` `` to the umbrella's frontmatter `description`.

Run: `python3 -m pytest skills/tests/test_audit_suite.py::test_umbrella_dispatch_table_matches_disk -q`
Expected: FAIL — dispatches `audit-docs-truth`, no such directory.

- [ ] **Step 2: Write the skill**

Create `.claude/skills/audit-docs-truth/SKILL.md`. Frontmatter:

```yaml
---
name: audit-docs-truth
description: Audit whether the repository's prose is true — README and skill-doc claims checked against the tree, plus progressive-disclosure structure across all three skills. Finds directory names that no longer exist, install instructions that point at retired repositories, port and architecture claims that stopped being accurate, broken in-skill links and orphaned reference files. Reports in plain English. Use when the user says "/audit-docs-truth", "check the docs", or asks whether the README still describes reality.
user-invocable: true
---
```

Body sections, in order:

**`# /audit-docs-truth — is the prose still true?`** — explain that this is the only audit whose subject is claims rather than code. It exists because of a measured failure: during the repository merge, four false statements shipped — a README asserting the engine was vendored two paragraphs below a section saying the opposite, two skill READMEs pointing at a directory that never existed here, and a claim that both plugins drive the same server when they run three processes on three port ranges. Every one passed 737 tests. The output goes to someone who knows the architecture but is not in the code right now.

**`## The audit contract (read first)`** — Violation / Decision as in the Global Constraints.

**`## Covering tests — read these first, do not duplicate them`**

- `skills/annotate/tests/test_skill_structure.py` — guards progressive disclosure for `skills/annotate/` **only**: SKILL.md under 120 lines, every `references/…` and `docs/…` link resolving, no orphaned reference file, the block-kind menu matching the files on disk. The other two skills have no equivalent.
- `skills/tests/test_repo_structure.py::test_every_probe_marker_file_exists` — already proves the probe MARKER paths in the docs resolve.

**`## Step 1 — build the claim inventory`**

Read `README.md`, `ide-plugin/README.md`, each `skills/*/README.md`, and each `skills/*/SKILL.md`. Extract every checkable claim: directory and file paths, command names, port numbers, install instructions, repository names, cross-references between documents, and statements about how components relate.

**`## The rules`**

- **Rule 1 — a named path exists.** A directory or file named in prose that is not in the tree is a **Critical** Violation. It sends a reader somewhere that is not there. Two shipped instances at the time of writing were `intellij-plugin-spike/`, which is `ide-plugin/`, and a design-doc link under `docs/superpowers/specs/` that never existed here.
- **Rule 2 — an install instruction resolves.** A `/plugin marketplace add` or `/plugin install` line naming a marketplace or plugin that `marketplace.json` does not publish is **Critical**.
- **Rule 3 — an architectural claim matches the code.** A statement about ports, processes, shared components, or data flow that the code contradicts is **Critical**. "Both plugins drive the same local server" was false: three processes, `PORT_RANGE` 3080 / 54620–54640 / 54660–54680. Only the engine library is shared.
- **Rule 4 — a document does not contradict itself.** Two sections of one file making incompatible claims is **Critical**, regardless of which is true — a reader cannot tell which to believe.
- **Rule 5 — a retired repository is not named as live.** Prose pointing at `petmakris/web-companion` or `petmakris/claude-ide-review` as somewhere to fix bugs or install from is **Critical**; both are archived. Naming them as history is correct and must not be flagged.
- **Rule 6 — in-skill links resolve, everywhere.** Extend `test_skill_structure.py`'s link and orphan checks to `skills/interactive_review/` and `skills/walkthrough/`. A broken link is **Medium**; an orphaned reference file is **Low**.
- **Rule 7 — SKILL.md length.** The 120-line cap is a written rule for `skills/annotate/` only, enforced by its own test. `skills/interactive_review/SKILL.md` (271 lines) and `skills/walkthrough/SKILL.md` (337 lines) have no `references/` directory and no such rule. Their length is a **Decision** — a monolithic SKILL.md loads in full on every invocation, so splitting it has a real token cost benefit, but nothing binds them today. Ask; never report it as a Violation.

**`## Closed allowlist — never flag these`**

1. `docs/superpowers/specs/` and `docs/superpowers/plans/` — design documents describe a moment in time and are allowed to name things that no longer exist.
2. Archived repositories named as history rather than as a live destination.
3. `docs/REMARKS.md` and `docs/SHOTLIST.md` — scratch notes, not claims about the tree.
4. Example paths inside fenced code blocks that are illustrative rather than repository paths.
5. `ide-plugin/README.md` naming IntelliJ platform paths that live outside this repository.
6. Any line carrying `# docs-exempt: <reason>`.

**`## Step 2 — scan`** — for each extracted claim, resolve it against the tree: paths against `git ls-files`, plugin and marketplace names against `marketplace.json`, ports against the three `PORT_RANGE` values, cross-document references against the files they name. Then run the link and orphan checks over all three skills.

**`## Step 3 — severity`** — Critical for a false claim a reader would act on; Medium for a broken in-skill link; Low for an orphaned reference file; Decision for Rule 7.

**`## Output template`**

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

**`## After delivering the report`** — stop and wait. `explain N` quotes the claim, shows what the tree actually contains, and gives the fix. `fix N` applies it. False positive means fixing this skill's allowlist first.

**`## Anti-patterns (do not do these)`** — do not flag design documents for describing superseded states; do not treat the 120-line cap as binding on skills that never adopted progressive disclosure; do not rewrite prose for style, only for truth; do not run anything.

- [ ] **Step 3: Run the sync test**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -q`
Expected: `5 passed`

- [ ] **Step 4: Run the full suite on a clean tree**

Run:
```bash
git add -A && git status --porcelain && python3 -m pytest skills -q
```
Expected: `742 passed`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(audit): the docs truth audit

Four false statements shipped during the merge — a vendoring claim
contradicted two paragraphs above it, a directory that never existed
here, and three processes described as one server. All passed 737 tests,
because no test reads prose."
```

---

### Task 5: audit-code-health

**Files:**
- Create: `.claude/skills/audit-code-health/SKILL.md`
- Modify: `.claude/skills/audit/SKILL.md` (add its dispatch-table row)

**Interfaces:**
- Consumes: the umbrella's `## Sub-audits` table.
- Produces: nothing later tasks read.

- [ ] **Step 1: Add the row and confirm the sync test fails**

Add to the umbrella's `## Sub-audits` table:

```markdown
| `/audit-code-health` | Generic health across Python and Java — dead code, duplication, unhandled async, risky code with no test beside it. |
```

and add `` `/audit-code-health` `` to the umbrella's frontmatter `description`, completing the five-name list quoted in Task 1.

Run: `python3 -m pytest skills/tests/test_audit_suite.py::test_umbrella_dispatch_table_matches_disk -q`
Expected: FAIL — dispatches `audit-code-health`, no such directory.

- [ ] **Step 2: Write the skill**

Create `.claude/skills/audit-code-health/SKILL.md`. Frontmatter:

```yaml
---
name: audit-code-health
description: Audit generic code health across the Python skills and the Java IntelliJ plugin — dead code, copy-paste duplication, swallowed exceptions, unbounded reads and missing timeouts on HTTP and subprocess calls, resource leaks, and risky modules with no test beside them. Reports in plain English. Use when the user says "/audit-code-health", "check code quality", "find duplication", or wants the non-structural slice of the full audit.
user-invocable: true
---
```

Body sections, in order:

**`# /audit-code-health — the non-structural slice`** — state the scope: `skills/**/*.py` and `ide-plugin/src/**/*.java` plus the one Kotlin file. The other four audits own structure, contracts, manifests and prose; this one owns everything left. It is the only audit with no single source of truth, so its bar for calling something a Violation is correspondingly higher — when in doubt it belongs in Decision.

**`## The audit contract (read first)`** — Violation / Decision as in the Global Constraints, with the added note that this audit has no registry to check against, so any item that depends on taste is a Decision by definition.

**`## Covering tests — read these first, do not duplicate them`**

The repository has 742 tests. Before reporting a module as untested, check `skills/*/tests/` and `ide-plugin/src/test/java/` for a covering file. "No test beside it" means no test file exercises that module, not that a specific function lacks a direct test.

**`## The rules`**

- **Rule 1 — no swallowed exceptions.** `except Exception: pass`, or a bare `except:` that neither logs nor re-raises, is **Critical** when it wraps a mutation and **Medium** when it wraps a read. The exception is a diagnostic path that documents why failure is ignored — `_port_holder` in the engine deliberately never fails the startup path and says so in its docstring. In Java, a `catch` block with an empty body is the same finding.
- **Rule 2 — network and subprocess calls carry a timeout.** An `http.client`, `urllib`, or `subprocess` call with no timeout is **Critical**: it hangs the caller forever with no way out. This applies to both the Python side and the Java `HttpClient` usage.
- **Rule 3 — resources are closed.** A file, socket, or process opened outside a `with` (Python) or try-with-resources (Java) and not closed on every path is **Medium**.
- **Rule 4 — no dead code.** A module, function, or class nothing references is **Low**, unless it is an entry point, a test fixture, or a public helper the engine exposes for skills. Check `git ls-files` and grep the whole tree before calling anything dead — a name used only from a `SKILL.md` shell snippet is still live.
- **Rule 5 — duplication that has diverged.** Two blocks of near-identical logic are **Medium** only when they have already drifted — identical copies are a Decision, drifted copies are a bug waiting to be found in one place and not the other. Quote both locations.
- **Rule 6 — risky code with no test beside it.** A module that parses untrusted input, writes files, or spawns processes and has no test file is **Medium**. Name the specific risk, not the absence of coverage.
- **Rule 7 — anything stylistic.** Naming, structure, file length, and preference-driven refactors are **Decision**, never Violations.

**`## Closed allowlist — never flag these`**

1. `skills/_shared/web_companion/server.py::_port_holder` and any other function whose docstring states that failure is deliberately ignored.
2. Generated or vendored third-party assets: `skills/_shared/web_companion/static/markdown-it.min.js`, the fonts, `ide-plugin/gradle/wrapper/gradle-wrapper.jar`.
3. `FakeReviewServer.java` — a test double; its simplifications are its purpose. Route drift there belongs to `/audit-http-surface`, not here.
4. Test files' own duplication — repetitive tests are usually clearer than abstracted ones.
5. The three per-skill `server.py` handler modules being structurally similar — that is `/audit-engine-boundary`'s call, not this one's.
6. Any line carrying `# health-exempt: <reason>`.

**`## Step 2 — scan`** — build the file universe from `git ls-files`; walk Python and Java sources; for each rule, grep for its shape and then read the surrounding function before judging. Never report a finding from a grep hit alone.

**`## Step 3 — severity`** — Critical for a hang or a swallowed failure around a mutation; Medium for leaks, drifted duplication, untested risk; Low for dead code; Decision for anything stylistic or any identical-but-undrifted duplication.

**`## Output template`**

```
Code health audit — actionable items

Scanned {N} Python files and {M} Java files.
Verdict: {one sentence.}

**Critical — fix first**
1. {What is wrong}. {Imperative fix}. — {area}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {Identical duplication that has not drifted — extract or leave?} — {area}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

**`## After delivering the report`** — stop and wait. `explain N` gives the file:line and the fix as concrete steps. `fix N` applies it. False positive means fixing this skill's allowlist first.

**`## Anti-patterns (do not do these)`** — do not report style as drift; do not call a name dead without grepping the whole tree including `SKILL.md` shell snippets; do not flag the test double's simplifications; do not report a finding from a grep hit without reading the function; do not run the test suite or the Gradle build.

- [ ] **Step 3: Run the sync test**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -q`
Expected: `5 passed`

- [ ] **Step 4: Run the full suite on a clean tree**

Run:
```bash
git add -A && git status --porcelain && python3 -m pytest skills -q
```
Expected: `742 passed`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(audit): the code health audit

The slice the other four do not own, across Python and Java. It has no
registry to check against, so its bar for calling something a Violation
is higher — anything resting on taste is a Decision by construction."
```

---

### Task 6: Run the suite and harden it against its own first findings

An audit suite is only worth having if its first run produces findings a reader can act on without argument. This task runs it once for real and fixes whatever fires wrongly — which, per the contract, is a bug in the audit rather than a nuance to explain.

**Files:**
- Modify: any `.claude/skills/audit*/SKILL.md` whose allowlist proves too narrow.

**Interfaces:**
- Consumes: all six skills.
- Produces: nothing.

- [ ] **Step 1: Confirm the suite is coherent**

Run: `python3 -m pytest skills/tests/test_audit_suite.py -v`
Expected: `5 passed`, and `test_umbrella_dispatch_table_matches_disk` confirms the umbrella dispatches exactly the five sub-audits on disk.

- [ ] **Step 2: Run each sub-audit and record what it returns**

Invoke each of `/audit-engine-boundary`, `/audit-http-surface`, `/audit-plugin-manifest`, `/audit-docs-truth`, `/audit-code-health` in turn. Save each report.

Two findings are expected, because they were verified by hand while writing the spec — treat their absence as a bug in the audit that found nothing:

- `/audit-http-surface` must report that `FakeReviewServer.java` does not implement `/api/threads/delete`, which `ReviewSessionClient.java` calls.
- `/audit-docs-truth` must report the two absorbed skills' SKILL.md length as a **Decision**, never as a Violation.

- [ ] **Step 3: Judge every finding against the contract**

For each item returned, ask: could a knowledgeable reader reasonably say "that's fine because…"? If yes, it is not a Violation. Harden that sub-audit's closed allowlist so it never fires again, and note what you changed.

Do not fix the findings themselves in this task — the suite's job is to report, and acting on real findings is separate work the user directs.

- [ ] **Step 4: Run the umbrella**

Run `/audit`.
Expected: one merged report with every item labelled `**{audit} {n}**`, four buckets, no per-audit sections, no file paths, no emoji. If the umbrella restates sub-reports verbatim or adds analysis of its own, fix the umbrella — it merges and re-buckets, it does not think.

- [ ] **Step 5: Run the full suite on a clean tree**

Run:
```bash
git add -A && git status --porcelain && python3 -m pytest skills -q
```
Expected: `742 passed`

- [ ] **Step 6: Commit**

```bash
git commit -m "fix(audit): harden the allowlists against the suite's first run

Every false positive found on the first real run is a bug in the audit
that raised it, not a nuance to explain at delivery. The allowlists now
cover what the first sweep got wrong."
```

If the first run produced no false positives, skip this commit and say so — an empty hardening commit would be noise.

---

## Verification

| Check | Command | Expected |
|---|---|---|
| Suite coherent | `python3 -m pytest skills/tests/test_audit_suite.py -q` | `5 passed` |
| Nothing else broke | `python3 -m pytest skills -q` | `742 passed` |
| Suite is tracked | `git ls-files .claude/skills \| wc -l` | 6 |
| Nothing else in `.claude/` is tracked | `git ls-files .claude \| grep -v '^.claude/skills/'` | no output |
| Umbrella dispatches all five | `/audit` | one merged report, five sub-audits, no skips |
| Known finding surfaces | `/audit-http-surface` | reports the `FakeReviewServer` gap on `/api/threads/delete` |
