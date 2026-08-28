---
name: audit-engine-boundary
description: Audit the shared server engine boundary — that `skills/_shared/web_companion/` is the one copy, reached by import rather than reimplemented, and that the four skills do not collide on ports or state directories. Finds hand-rolled reimplementations of engine behaviour, resurrected vendoring artifacts, overlapping PORT_RANGEs and duplicate skill_names. Reports in plain English. Use when the user says "/audit-engine-boundary", "check the engine boundary", or asks whether the shared server is still shared.
user-invocable: true
---

# /audit-engine-boundary — one engine, reached by import

Three repositories became one so this engine would exist once. Two copies previously drifted 192 lines apart in `server.py`, which is what the merge deleted. The output goes to someone who knows the architecture but is not in the code right now: plain English, no code snippets in the main report.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/tests/test_repo_structure.py::test_no_vendoring_artifacts` — asserts `VENDOR.txt` and `VENDOR.sha256` do not exist.
- `skills/tests/test_repo_structure.py::test_engine_is_not_marked_generated` — asserts no `.py` or `.sh` under `skills/_shared/` contains `GENERATED FILE`.

Report only what these do not enforce, plus anywhere either has gone stale.

## Step 1 — load the sources of truth

1. `skills/_shared/web_companion/` — every module, and what each provides.
2. `skills/annotate/server.py`, `skills/deck/server.py`, `skills/interactive_review/server.py`, `skills/walkthrough/server.py` — the four consumers. Deck is easy to miss because no Java client talks to it.
3. `skills/_shared/web_companion/server.py` — the `run()` signature, which is how a skill declares `skill_name` and `port_range`.

## The rules

- **Rule 1 — the engine is imported, never reimplemented.** A skill that hand-rolls behaviour the engine already provides is a **Critical** Violation: its own atomic write instead of `atomic.py`, its own on-disk event queue instead of `events.py` (the queue the watcher reads to wake Claude — not a browser-facing SSE transport), its own session-directory walk instead of `sessions.py`, its own thread store instead of `threads.py`. This is how two copies come back without a single banner reappearing. The fix is always the same: import it.
- **Rule 2 — no import reaches the engine by another path.** Every engine import must read `skills._shared.web_companion.*`. A `sys.path` manipulation, a relative import climbing out of a skill, or a duplicated module file is **Critical**.
- **Rule 3 — vendoring stays dead.** Any resurrected `VENDOR*` file, `GENERATED FILE` banner, or sync/check script anywhere in the tree is **Critical**. The covering tests above catch the two known filenames; this rule covers the rest of the shape, including a new script under `tools/` or a CI job that re-derives the tree.
- **Rule 4 — port ranges stay disjoint.** `PORT_RANGE` in the four skill servers must not overlap. Today: annotate 3080, deck 3090, interactive-review 54620–54640, walkthrough 54660–54680. An overlap is **Critical** — two skills race for a port and the loser reports a stale one.
- **Rule 5 — `skill_name` is unique per skill.** The value each skill passes to `run(skill_name=...)` determines `~/.claude/<skill_name>/server.json`, which carries the live port and the write token. Two skills sharing a name is **Critical**: each would overwrite the other's connection details and intermittently drive the other's server.
- **Rule 6 — engine changes that only one consumer uses.** A function in the engine called by exactly one skill is a **Decision**, not a Violation. It may be a shared capability nobody adopted yet, or skill-specific logic that leaked into the shared layer. Ask which.

## Closed allowlist — never flag these

1. The four per-skill `server.py` **handler** modules. They are meant to be distinct — the engine owns transport, the skill owns its routes' meaning.
2. The 8-line per-skill `ensure_server.sh` shims. They deliberately delegate to the 153-line one in `_shared`.
3. `skills/_shared/web_companion/tests/` naming engine internals — that is its job.
4. This audit suite (`.claude/skills/audit*/`) naming engine modules to describe them.
5. The spec and plan documents under `docs/superpowers/`, which describe the vendoring that was removed.
6. Each skill's `_serve_stream` HTTP transport framing — the browser-facing SSE loop in `skills/interactive_review/server.py` and `skills/walkthrough/server.py`. The engine has no SSE-serving module for either to reimplement, so this is skill-owned, not a Rule 1 Violation. Duplication between the two belongs to `/audit-code-health`'s Rule 5, not to this audit.
7. Importing through a same-repo compatibility shim that is documented as a deliberate, migratable re-export — for example `skills/interactive_review/threads.py`, whose docstring says "Import sites can migrate at leisure; this alias keeps both old module paths working" — is a **Decision** (migrate now or later), not a Rule 2 Violation. Rule 2 still applies in full to `sys.path` manipulation, a relative import climbing out of a skill, and a duplicated module file, all of which stay Critical.
8. Any line carrying `# engine-exempt: <reason>`, or, for a Rule 1 finding, a justification attached to the duplicated code itself — its enclosing function's docstring, or a comment immediately preceding it — stating that the duplication is deliberate and why. The marker is preferred because it is greppable. A justification anywhere else in the file (a general file-level comment, a docstring on an unrelated function, a note in the module docstring) does not exempt the finding — it must sit on the code being flagged, not merely share a file with it.

## Step 2 — scan

Enumerate engine modules and the public names each exports. Grep the four skill servers for those names to find who imports what. Grep the same files for the behaviours in Rule 1 implemented locally. Extract each `PORT_RANGE` and each `run(skill_name=...)` argument and diff them. Build the file universe from `git ls-files`.

## Step 3 — severity

Critical for anything that reintroduces a second implementation or collides at runtime; Medium for a near-duplicate that has not fully diverged; Low for cosmetic drift; Decision for the Rule 6 case.

## Output template

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

## After delivering the report

Stop and wait, do not edit. "explain N" gives the file:line on both sides and the fix as concrete steps. "fix N" applies it. When an item turns out to be a false positive, fix this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not flag the per-skill handler modules as duplication.
- Do not demand the engine absorb skill-specific route meaning.
- Do not re-report what the two covering tests already enforce.
- Do not start a server or run the test suite.
