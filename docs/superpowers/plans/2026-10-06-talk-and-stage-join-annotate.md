# Talk and stage join annotate: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `/talk` and `/stage` from the env repo's personal plugin into claude-annotate, ready for the public plugin.

**Architecture:** The two skill folders move as they are. Stage switches to the shared webcompanion client, which takes stage's stricter session lookup. Talk's machine-specific settings become environment variables that env sets.

**Tech Stack:** Python 3.9+ (talk 3.11+, run with `uv run --script`), aiohttp, pytest with xdist and playwright, the webcompanion daemon.

**Spec:** `docs/superpowers/specs/2026-10-06-talk-and-stage-join-annotate-design.md`

## Global Constraints

- Every file compiles under Python 3.9. Talk's suite skips below 3.11.
- `aiohttp==3.14.3; python_version >= "3.11"` in `requirements-test.txt`.
- No text under `skills/talk` or `skills/stage` names `@devdomains`, `@secrets`, `petros-`, `evooq` or `wealth`.
- Commit messages are one line, with no attribution.
- claude-annotate is public: never push without asking.
- Env: commit and push own work. evooq-env: commit and push own work.

## Review Focus

1. A stage slug that names an ended session: `create_or_attach` raises `SlugMismatch` naming `webcompanion unfinish`, for annotate as well as stage.
2. `all_sessions` on a daemon that refuses `scope=all`: stage still opens or attaches its session, as it does today.
3. `TALK_URL_BASE` unset: `/talk` prints its local link, and SKILL.md tells the user that the microphone needs https from another machine.
4. `TALK_AZURE_KEY_COMMAND` set but failing: talk falls back to VoiceStudio, and `--doctor` says why.
5. A session started with the `bare` profile gets `/talk` (run `@claude doctor`).

---

### Task 1: Move the folders and share one client

**Files:**
- Create: `skills/talk/**`, `skills/stage/**` (copied from `~/projects/env/claude/skills/`)
- Delete: `skills/stage/webcompanion_client.py`
- Modify: `skills/_shared/webcompanion_client.py`, `skills/stage/stage.py`, `skills/talk/talk.py`, `requirements-test.txt`, `.claude-plugin/marketplace.json`, `hooks/hooks.json` (create)

**Interfaces:**
- Produces in `skills._shared.webcompanion_client`: `SlugMismatch(DaemonError)`, `SID_RE`, `slugify(text) -> str`, `all_sessions(kind=None) -> list[dict]` (raises `DaemonHTTPError` as today), `finish_session(sid)`, `register_mount(sid, name, root, *, kind) -> dict`, `delete_item(sid, anchor, *, kind)`, and stage's strict `create_or_attach`.

- [ ] Step 1: `cp -R` both folders, excluding `__pycache__`.
- [ ] Step 2: Port the stage-only functions into the shared client. `create_or_attach` takes stage's body. Its `all_sessions` call catches `DaemonHTTPError` and treats it as no rows.
- [ ] Step 3: Point stage and talk at `skills._shared.webcompanion_client`. Delete stage's copy. In `stage.py`, the `all_sessions(kind)` call catches `DaemonHTTPError` and uses `[]`.
- [ ] Step 4: Add the `aiohttp` line to `requirements-test.txt`. Add `talk` and `stage` to `marketplace.json` with the spec's wording. Register `talk-activity.sh` in `hooks/hooks.json` under `${CLAUDE_PLUGIN_ROOT}`.
- [ ] Step 5: Run the full suite: `uv run -q --with-requirements requirements-test.txt python -m pytest skills -q -n 4`. Expected: all pass, the moved suites included.
- [ ] Step 6: Commit.

### Task 2: Generic settings, and a test that keeps them generic

**Files:**
- Modify: `skills/talk/SKILL.md`, `skills/talk/speech.py`, `skills/talk/azure_speech.py`, `skills/talk/talk.py` (doctor), `skills/stage/SKILL.md`
- Test: `skills/talk/tests/test_speech.py`, `skills/talk/tests/test_public.py` (create)

- [ ] Step 1: Write failing tests. `TALK_AZURE_KEY_COMMAND` supplies the key when `AZURE_SPEECH_KEY` is unset, and `TALK_AZURE_REGION` supplies the region. A failing command means there is no key. `test_public.py` greps every file under `skills/talk` and `skills/stage` (except `static/vendor`) for the forbidden words.
- [ ] Step 2: Run them and see them fail.
- [ ] Step 3: Replace the `@secrets` call in `speech.py` with the command. Rewrite the SKILL.md launch line to use `TALK_URL_BASE` and `TALK_STAGE_BASE` when set.
- [ ] Step 4: Run the full suite. Expected: all pass.
- [ ] Step 5: Commit.

### Task 3: The env side

**Files (env):**
- Delete: `claude/skills/talk/`, `claude/skills/stage/`
- Modify: `claude/README.md`, `tests/test-claude-skills.bats`, `claude/profiles/bare.args`, `docs/history.md`, `profiles/toolkit/env.sh` (or the profile that sets other `ENV_*` hooks)

**Files (evooq-env):** `claude/profiles/evooq-hub.args`

- [ ] Step 1: Export `TALK_URL_BASE`, `TALK_STAGE_BASE` (from the machine name), `TALK_AZURE_KEY_COMMAND` and `TALK_AZURE_REGION`.
- [ ] Step 2: Add `--plugin-dir ~/projects/claude-annotate` to both profiles. Delete the folders. Update the README, the bats file and the history.
- [ ] Step 3: Run `@lint`, `@claude doctor --quick` and `@test tests/test-claude-skills.bats`. Expected: clean.
- [ ] Step 4: Commit and push env and evooq-env.

### Task 4: A live call

- [ ] Step 1: Start `/talk` from a fresh `@claude` session in env, which loads claude-annotate.
- [ ] Step 2: Check that the link is the https one, that a typed turn arrives, and that an answer with a diagram reaches the stage and steps through its frames.
- [ ] Step 3: Ask the user before pushing claude-annotate.
