---
name: audit-http-surface
description: Audit the HTTP surface the IntelliJ plugin talks to — that every route the Java client calls exists server-side, that FakeReviewServer matches the routes the client actually uses, and that every mutating route sits behind the _is_owner write gate. Finds client-server route drift, a stale test double, and unguarded writes. Reports in plain English. Use when the user says "/audit-http-surface", "check the route contract", or asks whether the IDE plugin and the server still agree.
user-invocable: true
---

# /audit-http-surface — three lists that must agree

There is no route registry. The HTTP surface is a sequence of `if self.path == "..."` and `if self.path.startswith("...")` comparisons in `skills/_shared/web_companion/server.py` and the three per-skill handler modules. Three lists must agree and nothing enforces it: what the server implements, what the IntelliJ client calls, and what `FakeReviewServer.java` implements. When the third drifts, the Java suite passes against a fake that does not match the server, and the suite becomes less trustworthy the longer it goes unnoticed.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/_shared/web_companion/tests/test_write_gate.py` — asserts specific routes reject non-owner writes. Read its route list; report only routes it omits.
- `skills/_shared/web_companion/tests/test_route_resolve.py` — asserts path resolution. Do not re-derive what it covers.
- `ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java` and `WalkthroughSessionClientTest.java` — the Java client tests, which run against `FakeReviewServer`.

## Step 1 — load the sources of truth

1. `skills/_shared/web_companion/server.py` — the shared path dispatch, `_match_session` (the session-scoped route matcher), and `_is_owner` at the write gate.
2. `skills/annotate/server.py`, `skills/interactive_review/server.py`, and `skills/walkthrough/server.py` — the three per-skill `Handlers` classes.
3. `ide-plugin/src/main/java/com/petros/ireview/ReviewSessionClient.java` and `WalkthroughSessionClient.java` — every path the client requests.
4. `ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java` — the test double.

## The rules

- **Rule 1 — every route the client calls exists.** A path requested by either Java client with no matching branch server-side is **Critical**: the feature fails at runtime and no test catches it, because the Java tests run against the fake.
- **Rule 2 — the fake covers what the client uses.** A path the client calls that `FakeReviewServer` does not implement is **Critical**. Known instance at the time of writing: `ReviewSessionClient.java` calls `/api/threads/delete`, the engine implements it at `skills/_shared/web_companion/server.py:708`, and the fake does not. A fake that diverges from its subject makes every Java test that touches it meaningless.
- **Rule 3 — every mutating route is gated.** Any branch that writes — creates a session, submits an event, deletes a thread, acknowledges, cancels — must call `_is_owner` before mutating. An ungated write is **Critical**: the gate is the only thing between a non-loopback client and a write. A gated read is correct, not a Violation, **when the read exposes data across sessions** — `GET /` and `/api/sessions` are the standing examples, each listing every workspace on the machine, and must never be flagged. A gated read that exposes only its own session's data is **Medium**, since it breaks sharing for no benefit.
- **Rule 4 — one route, one implementation.** The same path handled in both the engine and a per-skill handler is **Medium** — the resolution order decides which wins and the loser is dead code that reads as live.
- **Rule 5 — no hand-maintained route list elsewhere.** A constant array of paths in the Java client, a switch in the frontend JS, or a table in a doc that enumerates routes is **Medium**. Describing the mechanism is fine; enumerating the routes is a second list.
- **Rule 6 — a server route no client calls.** **Decision**, not a Violation — it may be a deliberate API for a future client or for `reply_cli.py`. Surface it and ask.

## Closed allowlist — never flag these

1. `/health` and `/api/whoami` — diagnostics, deliberately unauthenticated reads.
2. Static asset paths under `/static/` — served by `static_serve.py`, not part of the client contract.
3. `skills/_shared/web_companion/tests/test_write_gate.py` naming routes on purpose.
4. This audit suite naming routes to describe them.
5. The `/s/<session>/` prefix — a routing prefix, not a route.
6. `GET /` and `/api/sessions` being gated reads — the workspace index and the data behind it, deliberately owner-only because both list every session on the machine.
7. Any line carrying `# route-exempt: <reason>`.

## Step 2 — scan

Routes come in two forms and both must be extracted:

- **Top-level routes** — `self.path ==` and `self.path.startswith(` literals in the engine and the three handler modules.
- **Session-scoped routes** — inside the `_match_session("/s/")` branch, the code matches on `rest ==` (the remainder after the session id is stripped), e.g. `if rest == "/api/threads/delete":`. A session-scoped route's full path is `/s/<session>/<rest>`, so a client calling `/s/abc/api/threads/delete` is calling the route recorded as `rest == "/api/threads/delete"`. Map every `rest ==` literal to its `/s/<session>/...` form before comparing against client calls — otherwise the two cannot be diffed at all.

Extract every path string from both Java clients and from `FakeReviewServer`, normalizing session-scoped client calls the same way; diff the three sets pairwise; for each mutating branch, check whether `_is_owner` is called before the mutation; build the file universe from `git ls-files`.

## Step 3 — severity

Critical for a route the client calls that is missing server-side or from the fake, and for an ungated write; Medium for a double implementation, a gated read, or a shadow list; Decision for an uncalled server route.

## Output template

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

## After delivering the report

Stop and wait, do not edit. "explain N" gives the path, the file:line on each of the three sides, and the fix. "fix N" applies it — adding a route means the server branch plus the fake, never the client alone. False positive means fixing this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not propose a route registry as the fix for a single drift.
- Do not flag diagnostics or static paths.
- Do not gate reads.
- Do not run the server or the Java suite.
