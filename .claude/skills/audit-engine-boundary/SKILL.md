---
name: audit-engine-boundary
description: Audit the shared-layer boundary — that `skills/_shared/webcompanion_client.py` is the one way any skill talks to the webcompanion daemon, reached by import rather than reimplemented; that `skills/_shared/` holds only what two or more skills import; that per-skill static copies match their canonical source; and that nothing in the repository starts a server or binds a port. Finds hand-rolled daemon HTTP calls, duplicate config readers, copied helpers, resurrected vendoring and in-repo servers. Reports in plain English. Use when the user says "/audit-engine-boundary", "check the shared layer", "check the engine boundary", or asks whether the daemon client is still the only one.
user-invocable: true
---

# /audit-engine-boundary — one daemon client, reached by import

The directory keeps its old name; the subject changed. This repository used to carry its own HTTP server in `skills/_shared/web_companion/`. That server is gone: every skill now pushes to the separately installed **webcompanion daemon**, and the shared layer is small — `skills/_shared/webcompanion_client.py` (the one Python daemon client: the `DaemonError` hierarchy, `request()`, `run_cli`), `skills/_shared/static/` (canonical page assets each skill copies into its own `static/`), and `skills/_shared/README.md` (the "two or more importers" rule). The way this boundary fails is quiet: a skill grows its own `urllib` call to the daemon, its own reader for `~/.claude/webcompanion/config.json`, its own copy of a helper another skill owns — and two clients start to drift on headers, timeouts and error handling. The output goes to someone who knows the architecture but is not in the code right now: plain English, no code snippets in the main report.

## The audit contract (read first)

- **Violation** — objectively wrong against a rule below, true **100% of the time**. If the user could reasonably wave it away, it is not a Violation. A false positive is a **bug in this skill** — fix the allowlist.
- **Decision** — a genuine either/or needing the user's judgment. Own bucket, never dressed as a Violation.

## Covering tests — read these first, do not duplicate them

- `skills/tests/test_smoke_engine_status.py` — the shared-layer rule, asserted: only Python modules live in `_shared` (no `.sh`), every shared module is imported by at least two skills' production code, tests never count as importers, and no production file names `web_companion/server`, `ensure_server.sh`, `server.run(` or `watcher.sh`.
- `skills/tests/test_shared_static_copies.py` — every canonical file in `skills/_shared/static/` is listed in its `EXPECTED` table, every expected per-skill copy exists, and every copy is byte-identical (except the `OWN` entries, e.g. annotate's deliberately diverged `core.css`); the retired `_shared/web_companion/static/` stays gone.
- `skills/tests/test_repo_structure.py::test_no_vendoring_artifacts` and `::test_engine_is_not_marked_generated` — no `VENDOR.txt`/`VENDOR.sha256` in `_shared`, no `GENERATED FILE` banner on any `.py`/`.sh` under it.

Report only what these do not enforce, plus anywhere one has gone stale (for example its regex no longer matching the shape of a server launch, or its `EXPECTED` table naming a skill that no longer exists).

## Step 1 — load the sources of truth

1. `skills/_shared/README.md` — the written rule and the history of what moved where.
2. `skills/_shared/webcompanion_client.py` — its public functions (`load_config`, `request`, `run_cli`, `create_or_attach`, `list_sessions`, `all_sessions`, `put_items`, `get_items`, `get_item`, `put_item`, `register_assets`, `get_threads`, `append_thread`, `delete_thread`, `submit_event`), its `CONTRACT`, its `_CONFIG_PATH`, the headers it sets (`X-WebCompanion-Contract`, `X-WebCompanion-Token`) and its `TIMEOUT_S`. This is what a skill must import rather than redo.
3. `skills/_shared/static/` — the canonical assets, and the `EXPECTED`/`OWN` tables in `skills/tests/test_shared_static_copies.py`.
4. Every skill's production code: `git ls-files 'skills/*'`, excluding `skills/tests/`, `skills/_shared/tests/` and each `skills/<skill>/tests/`. Nine skills today: annotate, annotate-doctor, ask_diff, dataflow, deck, show-diff, slides, specimen, walkthrough.

## The rules

- **Rule 1 — the daemon client is imported, never reimplemented.** Python production code outside `skills/_shared/webcompanion_client.py` that does any of the following is **Critical**: opens an HTTP connection to the daemon itself (`urllib.request`, `http.client`, a raw socket); reads or parses `~/.claude/webcompanion/config.json` (or derives the daemon's port or token any other way); sets an `X-WebCompanion-Contract` or `X-WebCompanion-Token` header; defines its own `DaemonError`-like hierarchy or its own copy of `run_cli`'s report-and-exit wrapper. This is how a second client comes back without anyone deciding to write one. The fix is always the same: import `skills._shared.webcompanion_client` and call it.
- **Rule 2 — the client is reached by one path.** Every import of the client reads `skills._shared.webcompanion_client` or `from skills._shared import webcompanion_client`, made importable by `bin/claude-annotate` putting the plugin root on `PYTHONPATH`. A `sys.path` manipulation that reaches `skills/_shared/`, a relative import climbing out of a skill, or a copied module file is **Critical**. So is production code importing the daemon's own package (`import webcompanion` / `from webcompanion ...`): the daemon is installed in its own isolated venv (pipx or `uv tool`), which the plain `python3` these skills run under cannot import — the client's module docstring states this.
- **Rule 3 — a helper one skill owns is not copied into another.** The README's history moved single-skill helpers into their one consumer: `atomic.py` into `skills/annotate/`, `anchor_migrate.py` into `skills/ask_diff/`, the workspace marker reader into `skills/annotate/check_anchors.py`. A second skill carrying its own copy of the logic in one of these — e.g. its own temp-file-then-`os.replace` atomic write that mirrors `skills/annotate/atomic.py` — is **Medium**: the rule says a helper with two importers belongs in `_shared`, so the fix is to move it there and import it from both, not to keep two. Calling a one-line standard-library function directly (`html.escape`, a bare `os.replace` with no temp-file dance around it) is not a copy of anything.
- **Rule 4 — the two-importer count is real.** `test_every_shared_module_has_two_skills_importing_it` counts a skill as an importer when the module's dotted name or a `from skills._shared import <name>` appears anywhere in its `.py`, `.sh` or `.md` production files. A skill whose only "import" is a mention in a comment, a docstring, or prose (not a runnable `claude-annotate python -c '...'` snippet, which is a real use) satisfies the test without using the module. If removing those mentions would drop a shared module below two importers, that is **Medium** — the test is passing on prose.
- **Rule 5 — nothing in this repository starts a server or binds a port.** Shipped code that starts an HTTP server or listens on a socket — `http.server`, `socketserver`, `HTTPServer`, `ThreadingHTTPServer`, `socket.bind`/`listen`, a `run()`/`serve_forever()` entry point, a `python3 -m http.server` in a skill doc, a Node `createServer`/`listen` in `vscode-plugin/src/`, a Java `HttpServer.create` under `ide-plugin/src/main/` — is **Critical**. The covering test's regex looks only for the retired server's names; this rule covers the shape. Every skill pushes to the daemon; no skill owns a port.
- **Rule 6 — vendoring stays dead.** Any resurrected `VENDOR*` file, `GENERATED FILE` banner, or sync/check script that re-derives part of the tree from elsewhere (including from `~/projects/webcompanion`) is **Critical**. The covering tests catch the two known filenames; this rule covers the rest of the shape, including a new script under `bin/` or a CI job in `.github/workflows/`.
- **Rule 7 — a per-skill static file that is a near-copy of a canonical asset under another name.** `test_shared_static_copies.py` compares files only by canonical name. A file in some `skills/<skill>/static/` that is substantially the same as a file in `skills/_shared/static/` but named differently has escaped the byte-identity check — **Medium**; rename it to the canonical name and add it to `EXPECTED`, or record why it diverged in `OWN`.
- **Rule 8 — a client function only one skill calls.** A public function in `webcompanion_client.py` called from exactly one skill's production code is a **Decision**, not a Violation. It may be a shared capability nobody else adopted yet, or skill-specific logic that leaked into the shared layer. Ask which.

## Closed allowlist — never flag these

1. `skills/_shared/webcompanion_client.py` itself — it is the one client.
2. The daemon's own CLI invoked as a subprocess or from a skill doc — `webcompanion push` and `webcompanion --version` in `skills/show-diff/show-diff.sh` and `skills/annotate-doctor/doctor.sh`, `webcompanion watch` in the skill docs that arm a watcher. The CLI is the daemon's own client, not a reimplementation of this one. (`doctor.sh` is POSIX `sh` by design — it must run when python3 is missing — so it cannot import the Python client.)
3. `urllib.parse` used only to build or encode a URL or query string, with no request sent — e.g. `skills/show-diff/show-diff.sh` building the `vscode://` URI.
4. Browser page code under `skills/*/static/` (and `skills/_shared/static/`) fetching routes from the daemon that served the page, including `skills/annotate/static/daemon-http.js`, which holds the page's one copy of the contract and token headers. The page runs in the browser; it cannot import Python.
5. The IDE clients — `ide-plugin/` (`DaemonSessionClient`, `WebCompanionHttp`, `ServerDiscovery`) and `vscode-plugin/src/` (`webcompanionClient.js`, `webcompanionConfig.js`) — are separate clients by necessity, in other languages. Their agreement with the daemon is `/audit-http-surface`'s job.
6. Every `tests/` directory, `skills/conftest.py` and `skills/tests/harness.py` — they start per-worker private daemons and fake servers on purpose; the rule is about shipped code.
7. Prose that names `~/.claude/webcompanion/config.json` or a header to describe it — `README.md`, skill READMEs, `SKILL.md` files and their `references/`. Describing the config is not reading it.
8. `skills/slides/bin/decks` inserting its own `skills/slides/framework` on `sys.path` — it reaches its own skill's code, not the shared layer.
9. `skills/slides/SKILL.md`'s `python3 -m http.server` deck-preview snippet. Slides does not use the daemon, and the user starts and kills that preview server themselves. If it is ever moved into code that runs unattended, Rule 5 applies.
10. This audit suite (`.claude/skills/audit*/`) and the spec and plan documents under `docs/superpowers/`, which describe the retired server and the vendoring that was removed.
11. Any line carrying `# engine-exempt: <reason>`, or, for a Rule 1 or Rule 3 finding, a justification attached to the duplicated code itself — its enclosing function's docstring, or a comment immediately preceding it — stating that the duplication is deliberate and why. A justification anywhere else in the file does not exempt the finding.

## Step 2 — scan

Build the file universe from `git ls-files`. List the public names `webcompanion_client.py` exports, then grep every skill's production files for imports of it (Rule 2) and for the behaviours in Rule 1 implemented locally — `urllib.request`, `http.client`, `webcompanion/config.json`, `X-WebCompanion-`. Grep for `os.replace` paired with a temp file, anchor-migration logic, and workspace-marker reads outside their owning skill (Rule 3). For Rule 4, take the importer set the covering test would compute and drop any match that sits in a comment, docstring or prose sentence. For Rule 5, grep shipped code (skills, `bin/`, `vscode-plugin/src/`, `ide-plugin/src/main/`) for the server shapes it lists. For Rule 7, compare per-skill static files against canonical ones by content, not only by name. Read the surrounding code before reporting any grep hit.

## Step 3 — severity

Critical for a second daemon client, a second path to the client, an in-repo server, or resurrected vendoring; Medium for a copied single-skill helper, a two-importer count propped up by prose, or a renamed static near-copy; Low for cosmetic drift; Decision for the Rule 8 case.

## Output template

```
Shared-layer boundary audit — actionable items

Checked {N} shared modules and assets against {M} skills.
Verdict: {one sentence.}

**Critical — fix first**
1. {What drifted}. {Imperative fix}. — {area}

**Medium — correctness & maintainability**
2. ...

**Low — hygiene & docs**
3. ...

**Decision — needs your call (not drift)**
4. {Client function used by one skill — shared capability or leaked specifics?} — {area}

Clean / tracked (no action): {one line}.

Want detail on any item? Say "explain N" and I'll show the file:line and the fix as concrete steps.
```

## After delivering the report

Stop and wait, do not edit. "explain N" gives the file:line on both sides and the fix as concrete steps. "fix N" applies it. When an item turns out to be a false positive, fix this skill's allowlist first.

## Anti-patterns (do not do these)

- Do not flag the IDE clients, the browser page code or the daemon CLI as second Python clients.
- Do not demand the shared client absorb one skill's payload shapes.
- Do not re-report what the covering tests already enforce.
- Do not start the daemon, a server, or the test suite.
