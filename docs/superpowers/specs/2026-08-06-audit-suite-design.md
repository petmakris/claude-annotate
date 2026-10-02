# A local audit skill suite for claude-annotate

Date: 2026-08-06
Status: approved, ready for implementation planning

## Problem

This repository has 737 tests and no way to ask "what has drifted?".

Tests answer a question that is known in advance. They cannot see a claim in a
README that stopped being true, a test double that no longer resembles the
server it stands in for, or a skill that reimplemented something the shared
engine already provides. Those failures are silent: everything is green, and
the drift compounds until someone trips over it.

Two other repositories — `~/projects/dashboard` and `~/projects/lomem` — solve
this with a suite of local audit skills. This applies the same principle here,
grounded in this repository's own sources of truth.

Recent evidence that the gap is real, all from the repository merge completed
earlier today:

- `README.md` claimed the engine was vendored from an upstream repository, two
  paragraphs below a section stating the opposite.
- Two skill READMEs pointed at `intellij-plugin-spike/`, a directory that does
  not exist.
- `README.md` said both plugins "drive the same local server". They run three
  processes on three port ranges.
- Two tests were written, ran green in a dirty working tree, and were never
  committed. Three subsequent tasks and two reviewers all missed it.

Every one of those shipped. None was test-detectable.

## The pattern being applied

From dashboard and lomem, unchanged:

- An umbrella `/audit` that **owns no checks** — it dispatches the sub-audits
  and merges their reports.
- Sub-audits that each own exactly one source of truth and are independently
  invocable.
- A binding contract: every item is a Violation or a Decision, and a false
  positive is a bug in the sub-audit.
- Read-only. No audit starts a server, runs a test suite, or edits a file.

## Decisions

| Question | Decision |
|---|---|
| Location | `.claude/skills/audit*/SKILL.md` |
| Sub-audit count | Five, plus the umbrella |
| Java coverage | Yes — `audit-code-health` covers `ide-plugin/` as well as Python |
| Conventions rule-book | Out of scope. All five audits are code-vs-code |

### Location, and the gitignore change it requires

The audits go in `.claude/skills/`, not `skills/`.

`skills/` is shipped plugin content. `test_plugin_skill_lists_partition_the_skills_tree`
asserts that every directory there containing a `SKILL.md` appears in exactly
one plugin's `skills` array, so an audit skill placed there would either fail
that test or be published to users who did not ask for it.

`.gitignore` currently ignores `.claude/` wholesale, which would leave the suite
untracked — local-only, absent from a fresh clone, invisible to review. Both
reference repositories track their `.claude/skills/`. This one must too:

```
.claude/*
!.claude/skills/
```

An allowlist rather than lomem's deny-list of specific noisy subpaths. Nothing
else under `.claude/` is worth committing, and an allowlist cannot be defeated
by a new noisy subdirectory appearing later.

## The suite

| Skill | Owns | Source of truth |
|---|---|---|
| `/audit` | Nothing — dispatch and merge | — |
| `/audit-engine-boundary` | One engine, reached by import rather than reimplemented; no port or state-directory collisions between the three skills | `skills/_shared/web_companion/` |
| `/audit-http-surface` | The Python-to-Java contract, and the write gate | path dispatch in `server.py`; `ReviewSessionClient.java`; `WalkthroughSessionClient.java` |
| `/audit-plugin-manifest` | What ships, and whether each skill can find itself once installed | `.claude-plugin/marketplace.json` |
| `/audit-docs-truth` | Whether the prose is true | the tree itself |
| `/audit-code-health` | Generic health, Python and Java | — |

### audit-engine-boundary

The merge bought exactly one invariant: the engine exists once and is edited in
place. This audit defends it.

`test_repo_structure.py` already covers the artifacts — `VENDOR.txt`,
`VENDOR.sha256`, the `GENERATED FILE` banner. What it cannot see is a skill that
reimplements engine behaviour rather than importing it: its own atomic-write
helper, its own SSE framing, its own session-directory walk. That is the drift
that reintroduces two copies without reintroducing a single banner.

It also owns the collision surface between the three skills, which nothing
currently checks. Each skill calls the engine's `run()` with a `PORT_RANGE` and
a `skill_name`, and both are collision keys:

- The ranges must stay disjoint — `skills/annotate/server.py:43` (3080),
  `skills/interactive_review/server.py:27` (54620–54640),
  `skills/walkthrough/server.py:25` (54660–54680).
- `skill_name` determines `~/.claude/<skill_name>/server.json`, which carries
  the live port and the write token. Two skills passing the same name would
  overwrite each other's connection details, and each would intermittently
  drive the other's server.

### audit-http-surface

There is no route registry. The HTTP surface is a sequence of
`if self.path == "..."` comparisons spread across the engine and three per-skill
handler modules. Three lists must agree and nothing makes them:

1. what the server implements,
2. what the IntelliJ client calls,
3. what `FakeReviewServer.java` — the test double the Java suite runs against —
   implements.

A known instance: `ReviewSessionClient.java` calls `/api/threads/delete`, the
engine implements it at `skills/_shared/web_companion/server.py:708`, and
`FakeReviewServer.java` does not. The Java tests pass against a fake that does
not match the server. That is the failure mode this audit exists for — a test
double drifting from its subject makes the suite less trustworthy the longer it
goes unnoticed.

This audit also owns the write gate. Every mutating route must sit behind
`_is_owner` (`skills/_shared/web_companion/server.py:496`); a mutating route
that skips it is Critical, because the gate is the only thing standing between a
non-loopback client and a write.

### audit-plugin-manifest

`marketplace.json` decides what ships. Two plugins share one root, separated
only by their `skills` arrays, so the manifest is the sole statement of which
skill belongs to which plugin.

Beyond what `test_repo_structure.py` enforces, this audit owns the question of
whether each skill can locate itself once installed — the probe embedded in each
`SKILL.md` resolves a marketplace name against
`~/.claude/plugins/known_marketplaces.json` and then verifies a MARKER file. A
wrong name or a stale marker makes the skill silently unfindable at runtime, and
no test can catch it because the failure only exists on an installed copy.

It also owns the root-shared surface: `hooks/hooks.json` sits at the repository
root, which both plugins claim, so a hook added there reaches both. Today that
is one inert hook. A second one that is not inert would be a Violation.

### audit-docs-truth

`test_skill_structure.py` guards progressive disclosure for `skills/annotate/`
only. The other two skills have no equivalent. This audit extends that check to
all three, and then does the thing no test does: reads the prose and asks
whether it is true of the tree as it now stands.

Directory names, file paths, command names, port numbers, install instructions,
and cross-references are all checkable against the repository. Every stale claim
listed in the Problem section above falls in this audit's scope.

### audit-code-health

The generic sweep both reference repositories carry: dead code, duplication,
type-safety escapes, unhandled async, and risky code with no test beside it.

Scope is Python and Java. `ide-plugin/` is roughly fifty Java files and is
exercised only by its own JUnit suite, so it needs the same attention as the
Python side rather than an exemption for being unfamiliar.

## The contract, binding on every sub-audit

Carried over unchanged from dashboard and lomem, because its value is that it
does not bend:

- **Violation** — objectively wrong against a written rule, true **100% of the
  time**. If a knowledgeable reader could reasonably say "that's fine
  because…", it is not a Violation. A false positive is a **bug in the
  sub-audit**, fixed by hardening that skill's allowlist — never footnoted at
  delivery.
- **Decision** — a genuine either/or needing the user's judgment. Its own
  bucket, labelled as a question, never mixed into the Violation buckets.

Two corollaries:

1. Check against a source of truth, not a regex hunch.
2. Build the file universe from `git ls-files` so nothing is structurally
   invisible.

## The non-duplication rule

This repository differs from dashboard and lomem in one way that matters: it
already has 737 tests, several asserting audit-shaped invariants.
`test_repo_structure.py` covers vendoring artifacts, banners, probe names and
the skills partition. `test_skill_structure.py` covers annotate's progressive
disclosure.

Every sub-audit must therefore **read its covering tests first and report only
what they do not enforce, plus anywhere a test has itself gone stale.** Without
this rule the audits would spend most of their output restating green tests,
and the signal would be buried.

Each sub-audit's `SKILL.md` names its covering tests explicitly, so this stays a
concrete instruction rather than a principle.

## Output

Identical to dashboard's, because it is already tuned:

- Four buckets: **Critical**, **Medium**, **Low**, **Optional / Decision**.
- One line per finding — what is wrong, then the imperative fix.
- Master report labels each item `**{audit} {n}**` so "explain http-surface 2"
  and "fix http-surface 2" route to the owning sub-audit.
- No file paths or code in the master report; `explain N` produces those.
- No emoji.
- Cap a bucket at ten items, then `+ N more — say "show all"`.
- After delivering, stop and wait.

## Out of scope

- Writing a `CLAUDE.md` or any ADRs. All five audits check code against code,
  which is firmer ground than prose against code. A conventions layer is
  separate work if it is ever wanted.
- Any audit that would edit, run a server, or run a test suite.
- Extending the suite to the two archived repositories.
