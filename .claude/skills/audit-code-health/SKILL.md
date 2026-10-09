---
name: audit-code-health
description: Audit generic code health across the Python skills, the Java IntelliJ plugin and the VS Code extension — dead code, copy-paste duplication, swallowed exceptions, missing timeouts on HTTP and subprocess calls, resource leaks, and risky modules with no test beside them. Reports in plain English. Use when the user says "/audit-code-health", "check code quality", "find duplication", or wants the non-structural slice of the full audit.
user-invocable: true
---

# /audit-code-health — the non-structural slice

Scope: `skills/**/*.py` and `skills/**/*.sh`, `bin/claude-annotate`,
`ide-plugin/src/main/**/*.java` plus the one Kotlin file
(`ide-plugin/src/main/kotlin/com/petros/ireview/GhPrDiffDriver.kt`), and
`vscode-plugin/src/*.js`. Browser page code under `skills/*/static/` is out
of scope. The other four audits own structure, contracts, manifests and
prose; this one owns everything left. It is the only audit with no single
source of truth — no shared layer, no route surface, no manifest to diff
against — so its bar for calling something a Violation is correspondingly
higher. When in doubt, it belongs in Decision.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of
  the time**. If the user could reasonably wave it away, it is not a
  Violation. A false positive is a **bug in this skill** — fix the
  allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own
  bucket, never dressed as a Violation.
- This audit has no registry to check findings against. Anything that rests
  on taste — naming, file length, how a function is broken up, whether a
  helper "should" exist — is a Decision by construction, not a Violation.

## Covering tests — read these first, do not duplicate them

No single test file covers this audit's territory — nothing asserts
"no swallowed exceptions" or "every subprocess call has a timeout" across
the whole tree the way the other four audits each have a structural test to
defer to. Tests live in five places; before reporting a module as untested
under Rule 6, check all of them for a covering file:

- `skills/*/tests/` — the per-skill Python suites.
- `skills/tests/` — repository-level and cross-skill tests (structure, the
  doctor, the bootstrap guard, the shared layer and its static copies).
- `skills/_shared/tests/` — the shared daemon client.
- `ide-plugin/src/test/java/` — the Java suite.
- `vscode-plugin/test/` — the VS Code extension's Node tests.

Search for the module or class name across every test file in all five
locations, not just the test directory next to it, since a test can
exercise a module it does not sit beside.
"No test beside it" means no test file exercises that module anywhere, not
that a specific function lacks a direct unit test.

## Step 1 — load the sources of truth

1. Every in-scope source file, enumerated with `git ls-files` — including
   `skills/_shared/webcompanion_client.py` (the one daemon client every skill
   imports).
2. `ide-plugin/src/main/**/*.java` and `GhPrDiffDriver.kt`.
3. `vscode-plugin/src/*.js`.
4. The five test locations above — read before calling anything untested.

## The rules

- **Rule 1 — no swallowed exceptions.** `except Exception: pass`, or a bare
  `except:` that neither logs nor re-raises, is **Critical** when it wraps a
  mutation and **Medium** when it wraps a read — unless the swallow is
  deliberate and says so, in which case it is not a Violation at all. The
  justification must be explicit that failure is absorbed on purpose (for
  example "best-effort," "never raises," "must never block the caller"), and
  it may live in any of three places: the enclosing function's own
  docstring, a comment immediately preceding the `try` block, or a comment
  anywhere inside the `catch`/`except` block. A justification that lives
  only in the module's docstring does not count: that position is not
  anchored to any specific swallow, so one module-level sentence would
  exempt every `try/except` in the file. Examples of each anchored form in
  the tree today: `skills/ask_diff/sync.py`'s `main()` documents its broad
  `except Exception: return 0` in its own docstring ("a git hook must never
  block or fail the git command that fired it"), which also covers the
  inner per-session `except Exception: continue` it describes;
  `ide-plugin/src/main/java/com/petros/ireview/BuildInfo.java`'s `load()`
  documents it inside the `catch` body ("never throw into the UI"). In Java
  and JavaScript, a `catch` block with an empty body is the same finding,
  exempted only under the same three-position rule.
- **Rule 2 — network and subprocess calls carry a timeout.** An
  `http.client`, `urllib`, or `subprocess` call with no timeout is
  **Critical**: it hangs the caller forever with no way out. This applies to
  the Python side, the Java `HttpClient` usage (a request or client with no
  `timeout(...)`/`connectTimeout(...)`, except the deliberately long-lived
  SSE stream in `SseClient`, which must instead have a reconnect or cancel
  path), and the Node `http.request` calls in `vscode-plugin/src/`.
  `skills/_shared/webcompanion_client.py`'s `TIMEOUT_S` is the Python
  client's default; a call site that overrides it with `None` is the
  finding.
- **Rule 3 — resources are closed.** A file, socket, or process opened
  outside a `with` (Python) or try-with-resources (Java) and not closed on
  every path is **Medium**.
- **Rule 4 — no dead code.** A module, function, or class nothing
  references is **Low**, unless it is an entry point (reached through
  `bin/claude-annotate <skill>.<module>`, `python -m`, a git hook, or a Java
  extension point in `plugin.xml`), a test fixture, or a public function of
  `skills/_shared/webcompanion_client.py`. Check `git ls-files` and grep the
  whole tree before calling anything dead — a name used only from a
  `SKILL.md` or `references/` shell snippet is still live.
- **Rule 5 — duplication that has diverged.** Two blocks of near-identical
  logic are **Medium** only when they have already drifted — identical
  copies are a Decision, drifted copies are a bug waiting to be found in one
  place and not the other. Quote both locations. A `user_msgs[0]` vs
  `user_msgs[-1]` choice diverging between two otherwise-identical
  thread-message-selection routines — both loading a thread's messages and
  picking a "question" to pair with the latest Claude reply — is the shape
  to look for: same scaffolding, different behavior on any thread with more
  than one exchange. Each copy's own tests pass; nothing catches the two
  disagreeing. Duplication of daemon-client behaviour across skills is
  `/audit-engine-boundary`'s, not this audit's.
- **Rule 6 — risky code with no test beside it.** A module that parses
  untrusted input, writes files, or spawns processes and has no test file
  anywhere in the five test locations is **Medium**. Name the specific risk,
  not the absence of coverage.
- **Rule 7 — anything stylistic.** Naming, structure, file length, and
  preference-driven refactors are **Decision**, never Violations.

## Closed allowlist — never flag these

1. Any swallow whose enclosing-function docstring, immediately-preceding
   comment, or comment inside the `catch`/`except` block states that the
   failure is absorbed on purpose — e.g. `skills/ask_diff/sync.py::main`
   (docstring) and
   `ide-plugin/src/main/java/com/petros/ireview/BuildInfo.java::load`
   (comment inside the `catch`). A justification that lives only in a
   module's docstring is not covered by this entry.
2. Generated or vendored third-party assets: every `*.min.js` (among them
   `skills/_shared/static/markdown-it.min.js` and its per-skill copies,
   `skills/annotate/static/vendor/`, `skills/annotate/static/shiki-langs/`,
   `ide-plugin/src/main/resources/web/highlight.min.js`),
   `skills/_shared/visuals/vendor/`, the fonts, and
   `ide-plugin/gradle/wrapper/gradle-wrapper.jar`.
3. `FakeReviewServer.java` — a test double; its simplifications are its
   purpose. Route drift there belongs to `/audit-http-surface`, not here.
4. Test files' own duplication — repetitive tests are usually clearer than
   abstracted ones.
5. Per-skill copies of `skills/_shared/static/` assets — duplicated on
   purpose because the daemon serves one folder per session, and held
   byte-identical by `skills/tests/test_shared_static_copies.py`. Any
   question about them is `/audit-engine-boundary`'s.
6. Any line carrying `# health-exempt: <reason>`.
7. A swallow during teardown of something already finished or already
   failing — `close()`/`shutdown()`-shaped calls in a cleanup path, or
   removing a temp file before re-raising — is not a Violation even with no
   comment, e.g.
   `ide-plugin/src/main/java/com/petros/ireview/SseClient.java`'s
   `catch (RuntimeException ignored) {}` around `Stream.close()`, and
   `skills/annotate/atomic.py`'s `except OSError: pass` around
   `os.unlink(tmp)` inside an `except BaseException: ... raise`. Keep this
   narrow: it covers teardown-only calls, not ordinary operations.

## Step 2 — scan

Build the file universe from `git ls-files`; walk the in-scope sources;
for each rule, grep for its shape and then read the surrounding function
before judging. Never report a finding from a grep hit alone.

## Step 3 — severity

Critical for a hang or a swallowed failure around a mutation; Medium for
leaks, drifted duplication, untested risk; Low for dead code; Decision for
anything stylistic or any identical-but-undrifted duplication.

## Output template

```
Code health audit — actionable items

Scanned {N} Python files, {M} Java/Kotlin files and {K} VS Code extension files.
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

## After delivering the report

Stop and wait. `explain N` gives the file:line and the fix as concrete
steps. `fix N` applies it. False positive means fixing this skill's
allowlist first.

## Anti-patterns (do not do these)

- Do not report style as drift.
- Do not call a name dead without grepping the whole tree, including
  `SKILL.md` and `references/` shell snippets.
- Do not flag the test double's simplifications.
- Do not report a finding from a grep hit without reading the function.
- Do not run the test suite, the Gradle build, the daemon, or a server.
