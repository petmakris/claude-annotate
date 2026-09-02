---
name: audit-code-health
description: Audit generic code health across the Python skills and the Java IntelliJ plugin — dead code, copy-paste duplication, swallowed exceptions, missing timeouts on HTTP and subprocess calls, resource leaks, and risky modules with no test beside them. Reports in plain English. Use when the user says "/audit-code-health", "check code quality", "find duplication", or wants the non-structural slice of the full audit.
user-invocable: true
---

# /audit-code-health — the non-structural slice

Scope: `skills/**/*.py` and `ide-plugin/src/**/*.java`, plus the one Kotlin
file (`ide-plugin/src/main/kotlin/com/petros/ireview/GhPrDiffDriver.kt`). The
other four audits own structure, contracts, manifests and prose; this one
owns everything left. It is the only audit with no single source of truth —
no engine, no route surface, no manifest to diff against — so its bar for
calling something a Violation is correspondingly higher. When in doubt, it
belongs in Decision.

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
defer to. The repository has 742 tests spread across two locations; before
reporting a module as untested under Rule 6, check both for a covering
file:

- `skills/*/tests/` — the per-skill Python test suites.
- `ide-plugin/src/test/java/` — the Java test suite.

Search for the module or class name across every test file in both
locations, not just the test directory next to it, since a test can
exercise a module it does not sit beside. "No test beside it" means no test
file exercises that module anywhere in either location, not that a specific
function lacks a direct unit test.

## Step 1 — load the sources of truth

1. `skills/**/*.py` — every Python module under `skills/`, including
   `skills/_shared/web_companion/` (the engine) and each skill's `hooks/`.
2. `ide-plugin/src/**/*.java`, plus the one Kotlin file,
   `ide-plugin/src/main/kotlin/com/petros/ireview/GhPrDiffDriver.kt`.
3. `skills/*/tests/` and `ide-plugin/src/test/java/` — read before calling
   anything untested; see Covering tests above.

## The rules

- **Rule 1 — no swallowed exceptions.** `except Exception: pass`, or a bare
  `except:` that neither logs nor re-raises, is **Critical** when it wraps a
  mutation and **Medium** when it wraps a read — unless the swallow is
  deliberate and says so, in which case it is not a Violation at all. The
  justification must be explicit that failure is absorbed on purpose (for
  example "best-effort," "never raises," "must never stop the caller"), and
  it may live in any of three places: the enclosing function's own
  docstring, a comment immediately preceding the `try` block, or a comment
  anywhere inside the `catch`/`except` block — an ordinary undocumented
  `except: pass` gets none of these exemptions, and neither does a
  justification that lives only in the module's own docstring: that
  position is not anchored to any specific swallow, so one module-level
  sentence would exempt every `try/except` in the file regardless of how
  many there are or whether any of them actually says so.
  `_port_holder` in the engine (`skills/_shared/web_companion/server.py`)
  documents it in its own docstring ("best-effort description... never let
  the diagnostic itself fail the startup path"). The `cleanup.sweep_state(...)`
  call inside `run()` in the same file documents it a second way — a
  comment immediately above the `try` ("Best-effort: a sweep failure must
  never stop the server from starting") rather than in `run()`'s own
  docstring, which is about being the server entrypoint and says nothing
  about this swallow. `BuildInfo.java:40` documents it a third way — a
  comment inside the `catch` body itself ("never throw into the UI").
  `skills/annotate/hooks/progress_publish.py:134` documents it the same
  third way — `except Exception:` followed by a comment inside the block
  itself ("Never let a progress hook disrupt the user's tool flow"). All
  three positions are allowlisted; a swallow with no comment and no
  docstring statement in any of them is still Critical or Medium as above.
  In Java, a `catch` block with an empty body is the same finding, exempted
  only under the same three-form rule.
- **Rule 2 — network and subprocess calls carry a timeout.** An
  `http.client`, `urllib`, or `subprocess` call with no timeout is
  **Critical**: it hangs the caller forever with no way out. This applies to
  both the Python side and the Java `HttpClient` usage.
- **Rule 3 — resources are closed.** A file, socket, or process opened
  outside a `with` (Python) or try-with-resources (Java) and not closed on
  every path is **Medium**.
- **Rule 4 — no dead code.** A module, function, or class nothing
  references is **Low**, unless it is an entry point, a test fixture, or a
  public helper the engine exposes for skills. Check `git ls-files` and grep
  the whole tree before calling anything dead — a name used only from a
  `SKILL.md` shell snippet is still live.
- **Rule 5 — duplication that has diverged.** Two blocks of near-identical
  logic are **Medium** only when they have already drifted — identical
  copies are a Decision, drifted copies are a bug waiting to be found in one
  place and not the other. Quote both locations. `threads_bulk()` in
  `skills/ask_diff/server.py` and `skills/walkthrough/server.py`
  is the shape to look for: both load a thread's messages and pick a
  "question" to pair with the latest Claude reply, but one takes
  `user_msgs[0]` and the other `user_msgs[-1]` — same scaffolding, different
  behavior on any thread with more than one exchange. Each copy's own tests
  pass; nothing catches the two disagreeing.
- **Rule 6 — risky code with no test beside it.** A module that parses
  untrusted input, writes files, or spawns processes and has no test file
  anywhere in the tree is **Medium**. Name the specific risk, not the
  absence of coverage.
- **Rule 7 — anything stylistic.** Naming, structure, file length, and
  preference-driven refactors are **Decision**, never Violations.

## Closed allowlist — never flag these

1. `skills/_shared/web_companion/server.py::_port_holder`,
   `skills/_shared/web_companion/cleanup.py::sweep_state`, and
   `skills/_shared/web_companion/server.py::_safe_500` — each carries a
   docstring on the function itself stating its failure is deliberately
   absorbed (best-effort, never raises, must not mask or block the caller).
   The `cleanup.sweep_state(...)` call wrapped in `try/except Exception:
   pass` inside `run()` (`server.py:435-443`) is the same kind of
   deliberate swallow, justified the other way: a comment immediately above
   the `try` ("Best-effort: a sweep failure must never stop the server from
   starting"), not `run()`'s own docstring. Any other function or call site
   whose enclosing-function docstring, immediately-preceding comment, or
   comment anywhere inside the `catch`/`except` block makes the same claim
   is covered by this same allowlist entry — for example
   `ide-plugin/src/main/java/com/petros/ireview/BuildInfo.java:40` (comment
   inside the `catch` body: "never throw into the UI") and
   `skills/annotate/hooks/progress_publish.py:134` (comment inside the
   `except Exception:` body: "Never let a progress hook disrupt the user's
   tool flow") — not just the three named at the top of this entry. A
   justification that lives only in a module's docstring, with nothing
   anchored to the specific swallow, is not covered by this entry.
2. Generated or vendored third-party assets:
   `skills/_shared/web_companion/static/markdown-it.min.js`, the fonts,
   `ide-plugin/gradle/wrapper/gradle-wrapper.jar`.
3. `FakeReviewServer.java` — a test double; its simplifications are its
   purpose. Route drift there belongs to `/audit-http-surface`, not here.
4. Test files' own duplication — repetitive tests are usually clearer than
   abstracted ones.
5. The three per-skill `server.py` handler modules' **structural** shape —
   the `Handlers` class outline and its `serve_data`/`create_session_extra`
   method set, plus byte-identical small helpers such as `_send_text`,
   `_send_html`, `_send_json`, and `_is_terminal` repeated across
   `skills/annotate/server.py`, `skills/ask_diff/server.py`, and
   `skills/walkthrough/server.py` — that is `/audit-engine-boundary`'s call,
   not this one's, and identical (undrifted) copies are a Decision under
   Rule 5 regardless. This does **not** reach duplicated **implementation
   bodies** between the three modules — for example the two `_serve_stream`
   loops — which this audit owns under Rule 5: there is no engine module
   either could import instead, so it is duplication between skills, not a
   boundary violation, and it is reportable here the same as any other
   drifted copy.
6. Any line carrying `# health-exempt: <reason>`.
7. A swallow around closing or releasing a resource during teardown —
   `close()`/`shutdown()`-shaped calls in a cleanup path, where the
   operation being abandoned is already finished or already failing — is
   not a Violation even with no comment, e.g.
   `ide-plugin/src/main/java/com/petros/ireview/SseClient.java:81,115`'s
   `catch (RuntimeException ignored) {}` around `Stream.close()`. Keep this
   narrow: it covers teardown-only close/shutdown calls, not ordinary
   operations.

## Step 2 — scan

Build the file universe from `git ls-files`; walk Python and Java sources;
for each rule, grep for its shape and then read the surrounding function
before judging. Never report a finding from a grep hit alone.

## Step 3 — severity

Critical for a hang or a swallowed failure around a mutation; Medium for
leaks, drifted duplication, untested risk; Low for dead code; Decision for
anything stylistic or any identical-but-undrifted duplication.

## Output template

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

## After delivering the report

Stop and wait. `explain N` gives the file:line and the fix as concrete
steps. `fix N` applies it. False positive means fixing this skill's
allowlist first.

## Anti-patterns (do not do these)

- Do not report style as drift.
- Do not call a name dead without grepping the whole tree, including
  `SKILL.md` shell snippets.
- Do not flag the test double's simplifications.
- Do not report a finding from a grep hit without reading the function.
- Do not run the test suite, the Gradle build, or a server.
