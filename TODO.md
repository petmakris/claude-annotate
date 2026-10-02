# webcompanion — next steps

Written 2026-08-29. Everything below is verified working unless it says otherwise.

**Where things are**

- Package + daemon: `~/projects/webcompanion` — https://github.com/petmakris/webcompanion, tagged `v1.0.0`
- Consumer (this repo): `~/projects/claude-annotate` — still on the OLD per-skill servers, untouched
- Design: `docs/superpowers/specs/2026-08-29-webcompanion-standalone-service-design.md`
- Plan 1 (done): `docs/superpowers/plans/2026-08-29-webcompanion-package.md`
- Full build log, 42 rulings, and the incident write-up: `.superpowers/sdd/2026-08-29-webcompanion-package/progress.md`

**State right now**

- The service IS running on this machine: `dev.webcompanion` under launchd, port 3080, KeepAlive verified (killed with `kill -9`, came back in ~15s).
- 350 tests pass on a clean checkout. Zero runtime dependencies.
- Your 30 legacy workspaces are UNTOUCHED in `~/.claude/{annotate,deck,dataflow,interactive-review,walkthrough}/`.
- `dist/` holds `webcompanion-1.0.0-py3-none-any.whl` and `.tar.gz`, both `twine check` clean.
- **Not published to PyPI.** That is step 1.

---

## 1. Publish to PyPI  — 5 minutes, needs your token

The only blocker. Nothing on this machine has PyPI credentials.

```bash
# create a token at https://pypi.org/manage/account/token/
#   first publish needs scope "Entire account"; you can narrow it to the project afterwards
printf '[pypi]\n  username = __token__\n  password = pypi-YOUR-TOKEN-HERE\n' > ~/.pypirc
chmod 600 ~/.pypirc

cd ~/projects/webcompanion
.venv/bin/python -m twine upload dist/*
```

Then confirm it round-trips from PyPI rather than from your disk:

```bash
pipx uninstall webcompanion
pipx install webcompanion
webcompanion --version          # expect: webcompanion 1.0.0 (contract 1)
webcompanion doctor
```

`webcompanion` was free when checked. If someone has taken it since, the name lives in
`pyproject.toml:name` and three `[project.urls]` entries, plus the README links.

## 2. Do NOT migrate your workspaces yet

`webcompanion migrate` works and has been rehearsed against your real data
(30 sessions → 15 migrated, 14 needs-repush, 1 read-only, 96 comment threads preserved).
Do not run `--apply`.

Your five skills still read `~/.claude/<skill>/`. Migrating now moves your history out from
under the code that is currently using it. Migration belongs with the skill cutover (step 4).

To look without touching anything:

```bash
webcompanion migrate                       # dry run, the default
webcompanion migrate --into /tmp/rehearsal # full rehearsal, copies, sources untouched
```

**Never** try to isolate a migration test by copying the directories. Legacy `sessions.json`
holds absolute paths, so a copy still points at the originals — that is how I moved your live
workspaces during this build. Use `--into`, or point `HOME` somewhere disposable.

## 3. Plan 2 — IntelliJ plugin, dual discovery

The plugin currently reads `~/.claude/interactive-review/server.json` and
`~/.claude/walkthrough/server.json`, with hardcoded fallbacks to ports 54620 and 54660.
It must learn `~/.claude/webcompanion/config.json` and port 3080 **while keeping the old
discovery**, because the plugin ships as a hand-downloaded zip and updates late or never.

This has to propagate BEFORE the skills cut over, or both IDE views die silently for anyone
who has not updated. Roughly 20 lines in `ReviewSessionService.resolveServerUrl` and
`WalkthroughService.resolveServerUrl`. Also: `WalkthroughService` resolves its base URL once
at construction and never re-reads it — fix that too, or a daemon restart strands the panel
until IDE restart.

`docs/contract.md` in the webcompanion repo is written to be sufficient on its own for this.

## 4. Plan 3 — cut the five skills over

The big one. Delete all five `server.py`, all five `ensure_server.sh`, and
`skills/_shared/web_companion/`; rewrite each skill's push path against the HTTP contract;
run `webcompanion migrate --apply` as part of it (stop the service first — the command
refuses while `/health` answers).

Two things the daemon does not do yet, which the skills will need:
- non-annotate content (`steps.json`, `dataflow.json`, `diff.patch`) is not in the item
  format, so those sessions migrate as `needs_repush` and their skill must push them again
- pin the kind spelling: migration accepts both `interactive-review` and `interactive_review`,
  but a client must pick one. `docs/contract.md` says which.

## 5. Plan 4 — drop the plugin's old discovery

Once step 3 has shipped and settled.

---

## Known issues, deferred to 1.0.1

None block use. All are recorded with file:line in the final-review reports under
`.superpowers/sdd/2026-08-29-webcompanion-package/`.

- `Registry.persist()`'s merge can resurrect a row another process removed. Benign — the row
  points at directories that no longer exist and `prune_dead_rows` drops it on the next boot.
- `doctor._log_tail` reads the whole log into memory to show 20 lines; the machine most likely
  to need `doctor` is the one with the biggest log.
- `uploads`' 408 path leaves a keep-alive connection desynced.
- `Client.events(sid)` is public API with no caller and no test — delete it before anyone binds to it.
- `test_persist_serialises_concurrent_writers` uses threads, not processes.
- Two near-vacuous assertions among the newest tests (`test_doctor_reports_a_healthy_daemon`,
  `test_the_runtime_does_not_claim_the_token_is_reminted`).

## Worth knowing about this machine

Your shell's `python3` is Homebrew **3.14.7**. A launchd service gets a minimal PATH, so the
daemon actually runs on `/Library/Developer/CommandLineTools/usr/bin/python3` — **3.9.6**.

That makes `requires-python = ">=3.9"` load-bearing today, not future-proofing: any 3.10+
syntax passes every test you run locally and breaks only the installed service. `webcompanion
doctor` prints both interpreters so the divergence stays visible. If you ever remove the Xcode
Command Line Tools, the service loses its interpreter while your shell keeps working.

## Service commands

```bash
webcompanion doctor      # both interpreters, config, zipapp, launchd job, health, log tail
webcompanion status
webcompanion uninstall   # removes the service and zipapp; KEEPS config and workspaces
launchctl kickstart -k gui/$UID/dev.webcompanion
tail -f ~/.claude/webcompanion/dev.webcompanion.log
```
