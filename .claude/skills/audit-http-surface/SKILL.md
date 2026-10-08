---
name: audit-http-surface
description: Audit the HTTP surface every client in this repository speaks to the webcompanion daemon — that each route the IntelliJ plugin, the VS Code extension and the Python client call exists in the daemon with that method, that FakeReviewServer matches the routes the Java client actually uses, that every client sends the contract version the daemon speaks, and that every mutating daemon route sits behind its owner write gate. Finds client-daemon route drift, a stale test double, a contract-number mismatch and unguarded writes. Reports in plain English. Use when the user says "/audit-http-surface", "check the route contract", or asks whether the IDE plugins and the daemon still agree.
user-invocable: true
---

# /audit-http-surface — the clients must agree with the daemon

This repository runs no server. Every route lives in the **webcompanion daemon**, a separate project installed on its own (pipx or `uv tool`), and four clients here speak to it: the IntelliJ plugin (`ide-plugin/`), the VS Code extension (`vscode-plugin/`), the Python client every skill imports (`skills/_shared/webcompanion_client.py`), and — as a test double for the first — `FakeReviewServer.java`. Nothing in this repository enforces that their route lists agree with the daemon's. The Python client tests run against a fake daemon (`test_webcompanion_client.py`), the Java client tests run only against `FakeReviewServer`, and the VS Code client tests run only against an ad-hoc `http.createServer` stub. When the fake drifts, the Java suite passes against something that does not match the daemon, and the suite becomes less trustworthy the longer it goes unnoticed.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `ide-plugin/src/test/java/com/petros/ireview/ReviewSessionClientTest.java` and `WalkthroughSessionClientTest.java` — the Java client tests, which run against `FakeReviewServer`. `ServerDiscoveryTest.java` covers config discovery.
- `vscode-plugin/test/webcompanionClient.test.js` and `webcompanionConfig.test.js` — the VS Code client against a local stub.
- `skills/_shared/tests/test_webcompanion_client.py` and `test_daemon_errors.py` — the Python client.
- In the daemon's own repository: `tests/test_gate.py` (the owner check itself) and the per-area `tests/test_server_*.py` files, several of which assert that a non-owner write is refused with `403` (for example `test_server_threads.py::test_reading_a_thread_is_not_owner_gated_but_writing_is`, `test_server_speech.py::test_every_speech_route_refuses_a_non_owner`). Read which routes they cover; report only gaps.

## Step 1 — load the sources of truth

1. **Find the daemon source.** Prefer the checkout at `~/projects/webcompanion/src/webcompanion/`. If it is absent, locate the installed package through the interpreter the `webcompanion` command runs under:

   ```sh
   "$(head -1 "$(command -v webcompanion)" | sed 's/^#!//')" -c 'import webcompanion, os; print(os.path.dirname(webcompanion.__file__))'
   ```

   If neither exists — no checkout and no `webcompanion` on PATH — **stop and say so**: report "daemon source not found; install webcompanion or clone it to ~/projects/webcompanion, then re-run". Do not fall back to the clients' own idea of the routes; with no source of truth there is nothing to check against, and a report built from the clients alone would be guesswork dressed as findings.
2. `<daemon>/server.py` — the route table is the `do_GET` / `do_POST` / `do_PUT` / `do_PATCH` / `do_DELETE` dispatch inside `_make_handler`: literal `path == "..."` comparisons for top-level routes and the module-level `_SID_*_RE` regexes (e.g. `_SID_POLL_RE = ^/s/([^/]+)/poll$`) for session-scoped ones. A route is a **(method, path)** pair: the same regex matched in two methods is two routes (`_SID_ITEM_RE` is GET, PUT and DELETE). The write gate is `_require_owner()`, which calls `gate.is_owner(...)` in `<daemon>/gate.py`; each mutating handler is expected to call it before it writes (Rule 4 checks that it does). Contract enforcement is `_contract_ok()` → `gate.check_contract`, against `CONTRACT` in `<daemon>/__init__.py`.
3. The daemon's own prose: `docs/contract.md` (repository checkout only) — its route table, the "Who may write" section, and the `kind` requirements. Where it and `server.py` disagree, `server.py` is the truth and the disagreement is a daemon-side finding to mention, not one to fix here.
4. The Java client: `ide-plugin/src/main/java/com/petros/ireview/WebCompanionHttp.java` (the route builders — `sessionsUri` for `GET /api/sessions?kind=&cwd=`, `sessionUri` for `/s/<sid>/<route>?kind=`, `CONTRACT_VERSION`, `withContract`), `DaemonSessionClient.java` (the shared base: `request(sid, route)` and every route string passed to it — `poll`, `threads`, `stream`, `api/submit`, `api/cancel`), and its subclasses `ReviewSessionClient.java` (`items`, `api/threads/delete`) and `WalkthroughSessionClient.java` (`items`). `ServerDiscovery.java` reads `~/.claude/webcompanion/config.json` only.
5. `ide-plugin/src/test/java/com/petros/ireview/FakeReviewServer.java` — the test double: its `createContext` registrations and the `path.endsWith(...)` branches inside `handleSession`.
6. The VS Code client: `vscode-plugin/src/webcompanionClient.js` (every `this._request(method, path)` and its `CONTRACT`) and `vscode-plugin/src/webcompanionConfig.js`.
7. The Python client: `skills/_shared/webcompanion_client.py` — every `request(method, path, ...)` call and its `CONTRACT`.
8. Every other place that states the contract number: `skills/annotate/static/daemon-http.js` (`CONTRACT`), `skills/annotate-doctor/doctor.sh` (`WC_REQUIRED_CONTRACT`), and `skills/show-diff/show-diff.sh` (`WC_REQUIRED_CONTRACT`, checked against `webcompanion --version`). `grep -rn "Contract\|CONTRACT" skills vscode-plugin/src ide-plugin/src/main` finds them.

## The rules

- **Rule 1 — every route a client calls exists in the daemon, with that method.** A (method, path) pair requested by the Java, VS Code or Python client that matches no branch of the daemon's dispatch is **Critical**: the feature fails at runtime with a 404, and for the Java and VS Code clients no test here catches it, because their tests run against stand-ins.
- **Rule 2 — the fake covers what the Java client uses.** A route `DaemonSessionClient` or a subclass calls that `FakeReviewServer` does not implement, or implements under a different method or response shape than the daemon, is **Critical**. A fake that diverges from its subject makes every Java test that touches it meaningless.
- **Rule 3 — every client speaks the daemon's contract.** Each client's contract number — `WebCompanionHttp.CONTRACT_VERSION`, `webcompanionClient.js`'s `CONTRACT`, `webcompanion_client.py`'s `CONTRACT`, `daemon-http.js`'s `CONTRACT`, `doctor.sh`'s `WC_REQUIRED_CONTRACT`, show-diff's check — must equal the daemon's `CONTRACT`. A mismatch is **Critical**: the daemon answers `426` on every request that carries the header, which presents as a dead poll.
- **Rule 4 — every mutating daemon route is gated.** Every handler a POST, PUT, PATCH or DELETE route dispatches to that writes — creates or forgets a session, finishes, cancels or unfinishes it, puts, patches or deletes an item, appends to or deletes a thread, registers assets or mounts, uploads, submits, opens a file in the editor, mints a speech token — must call `self._require_owner()` before mutating. An ungated write is **Critical**: the gate is the only thing between a non-owner client (anything not on loopback, without the token or an authorized Tailscale identity) and a write. The daemon's own comment above the `_SID_*_RE` block says the routing stays a flat if/elif chain precisely so this check stays a literal grep. This is a finding in the daemon repository; report it with that location and say the fix lands there, not here.
- **Rule 5 — a client's required query parameters are present.** Per-session routes are `kind`-scoped (`WebCompanionHttp.sessionUri` always sends `?kind=`, the Python client appends `_kind_qs(kind)`), and `GET /api/sessions` needs `cwd` unless `scope=all`. A client call that omits a parameter `server.py` treats as required is **Critical**; one that omits a parameter the contract calls optional but the client's own use depends on (e.g. listing sessions with no `kind` filter and then treating every row as its own kind) is **Medium**.
- **Rule 6 — no hand-maintained route list elsewhere.** A constant array of paths in a client, a switch in frontend JS, or a table in a doc in this repository that enumerates the daemon's routes is **Medium** — it is a second list that will drift. Describing the mechanism is fine; enumerating routes is a second list. The daemon's own `docs/contract.md` is its source, not a shadow list.
- **Rule 7 — a daemon route no client here calls.** **Decision**, not a Violation — the daemon serves other callers too (its own CLI, `webcompanion watch`, the browser pages). Surface only routes that look like they were added for one of this repository's clients and never wired up, and ask.

## Closed allowlist — never flag these

1. `GET /health` and `GET /api/whoami` — diagnostics, deliberately ungated reads.
2. `GET /_wc/core.js`, `GET /_wc/favicon.svg`, and `GET /s/<sid>/assets/...` / `GET /s/<sid>/mounts/...` — page assets served to the browser, not part of the IDE client contract.
3. `GET /api/sessions?scope=all` being an owner-gated read — `_list_sessions` gates only that scope, because it enumerates every project's sessions; `docs/contract.md` documents this. `GET /api/speech/status` being gated is likewise deliberate.
4. `GET /` and `GET /s/<sid>/` — the daemon's index and session shell pages, served to the browser.
5. The `/s/<sid>/` prefix — a routing prefix, not a route.
6. `FakeReviewServer` implementing routes by `path.endsWith(...)` instead of the daemon's anchored regexes — a simplification of the double, not drift, as long as each route the client calls resolves to the right branch.
7. The daemon's own tests naming routes on purpose, and this audit suite naming routes to describe them.
8. Browser page code under `skills/*/static/` calling daemon routes — it is served by the daemon and runs the daemon's own `core.js`; its route usage is the daemon's contract with itself.
9. Any line carrying `# route-exempt: <reason>`.

## Step 2 — scan

From `server.py`, build the set of (method, path-pattern) pairs: one per `path ==` literal and one per `_SID_*_RE` match inside each `do_<METHOD>`. Normalise client calls to the same form — `WebCompanionHttp.sessionUri(base, sid, "api/submit", kind)` is `POST /s/<sid>/api/submit`; the method comes from the `.GET()` / `.POST(...)` on the builder at the call site. Do the same for `FakeReviewServer`, `webcompanionClient.js` and every `request(...)` in `webcompanion_client.py`. Diff client sets against the daemon (Rule 1), the Java client against the fake (Rule 2). Collect every contract number and compare (Rule 3). For each mutating daemon handler, check that `_require_owner()` precedes the first write (Rule 4). Build this repository's file universe from `git ls-files`.

## Step 3 — severity

Critical for a route a client calls that the daemon or the fake lacks, a contract-number mismatch, a missing required parameter, and an ungated daemon write; Medium for a shadow route list or a dependent-but-optional parameter left out; Decision for an uncalled daemon route.

## Output template

```
HTTP surface audit — actionable items

Checked {N} daemon routes ({daemon source path}) against {M} client calls across the Java, VS Code and Python clients and the test double.
Verdict: {one sentence.}

**Critical — fix first**
1. {What drifted}. {Imperative fix}. — {area}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {Daemon route no client here calls — future API or dead weight?} — {area}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

## After delivering the report

Stop and wait, do not edit. "explain N" gives the route, the file:line on each side (daemon, client, fake), and the fix. "fix N" applies it — a route a client needs that the daemon lacks is fixed in the daemon repository first, then the fake; never by editing the client alone. A daemon-side gate gap is fixed in the daemon repository. False positive means fixing this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not propose a route registry as the fix for a single drift.
- Do not flag diagnostics, page assets or the browser pages' own calls.
- Do not demand ungated reads be gated.
- Do not report from the clients alone when the daemon source cannot be found.
- Do not start the daemon or run the Java, VS Code or Python suites.
