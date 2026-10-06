# Talk and stage join annotate

Status: approved design, 2026-10-06. Project 1 of 3.

## Why

Annotate and talk both explain things to a reader with pictures. Annotate has the better pictures: `diagrams/sequence.py` and `diagrams/flowchart.py` lay out text with real font metrics. Talk has the better delivery: its stage reveals a picture frame by frame, in step with the voice. Today they live in two repos, so neither gets the other's strength.

The goal across three projects is one visual library that both skills use, with frames as a first-class idea in it.

| # | Project | Done when |
|---|---|---|
| 1 | Talk and stage move into claude-annotate, ready for the public plugin | `/talk` runs from claude-annotate; env's copies are gone |
| 2 | The generators move to `skills/_shared/visuals/` | annotate imports them from there and renders byte-identical output |
| 3 | Frames on `data-key` | talk shows and steps through a sequence diagram, and free HTML, in step with the voice |

This spec covers project 1. Projects 2 and 3 get their own specs.

### Target for projects 2 and 3 (agreed, not built here)

Every generator in the shared library marks the parts the eye can land on with a `data-key` attribute. One frame engine reads only `data-key`, so it never knows which generator drew the picture. Free HTML that the agent writes gets frames the same way. Annotate uses the same generators and shows the final frame, which is the whole picture.

Today the stage finds keys through one adapter per kind (`static/scene.js`: lines, rows, flowchart). Project 3 replaces those adapters with the `data-key` contract.

## History

Talk and stage lived in claude-annotate until 2026-10-05. Commit `d73ad8e` moved them to the env repo's personal plugin for two reasons:

1. Every session got talk. The `bare` and `evooq-hub` launch profiles do not load claude-annotate.
2. claude-annotate is public, and talk leaned on one machine's setup: `@devdomains` links, `@secrets` and the local VoiceStudio app.

This design answers both. The launch profiles add claude-annotate, and talk's machine-specific parts become optional settings.

## Design

### 1. Layout in claude-annotate

- `skills/talk/` and `skills/stage/` come over from `env/claude/skills/` unchanged, with their `tests/`, `static/` and `hooks/`.
- Stage drops its trimmed `webcompanion_client.py` and imports `skills/_shared/webcompanion_client.py`. The shared client gains the calls only the copy has today: `finish_session`, `register_mount`, `delete_item`, `slugify` and `_rows`. Where both define a function, the shared one is kept. Any difference in behaviour is resolved in the shared client, and stage's tests prove it.
- `.claude-plugin/marketplace.json` lists `./skills/talk` and `./skills/stage` under the `claude-annotate` plugin. The description says that `/stage` and `/talk` need the webcompanion daemon, and that `/talk` also needs `uv`, Python 3.11+ and a speech engine (an Azure key or the VoiceStudio app).
- The plugin's `hooks/hooks.json` registers `skills/talk/hooks/talk-activity.sh` for PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied, Stop and StopFailure. The script exits at once when no talk server runs. Today it is registered nowhere, so the call page never shows the session's tool calls. This fixes that.

### 2. Public plugin readiness

| Today | After |
|---|---|
| SKILL.md runs `@devdomains url talk` and `@devdomains url webcompanion` | SKILL.md passes `--url-base "$TALK_URL_BASE"` and `--stage-base "$TALK_STAGE_BASE"` when they are set. Without them talk prints its local link, and SKILL.md says the microphone needs https from another machine. |
| `speech.py` falls back to `@secrets read azure-speech` | `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`, else `TALK_AZURE_KEY_COMMAND`: a command whose output is the key, and `TALK_AZURE_REGION` for the region |
| VoiceStudio fallback | unchanged; `talk.py --doctor` names the missing engine when there is neither |

No text in `skills/talk` or `skills/stage` names `@devdomains`, `@secrets`, a machine name or an employer. A test greps for those words.

### 3. The env repo

- Delete `claude/skills/talk/` and `claude/skills/stage/`.
- Remove their entries from `claude/README.md` and their line from `tests/test-claude-skills.bats`.
- A profile `env.sh` exports `TALK_URL_BASE`, `TALK_STAGE_BASE` (built from this machine's name through `lib/machines.sh`) and `TALK_AZURE_KEY_COMMAND="@secrets read azure-speech token"`. The region is not a secret, so `TALK_AZURE_REGION` is a plain value.
- `claude/profiles/bare.args` adds `--plugin-dir ~/projects/claude-annotate`.
- `docs/history.md` records the move back and why.

In the evooq-env repo, `claude/profiles/evooq-hub.args` adds `--plugin-dir ~/projects/claude-annotate`, and its header comment drops "No annotate". This brings annotate's skills into dashboard sessions too. A separate plugin folder for talk would avoid that, and was judged not worth its cost.

### 4. Tests

- Talk's and stage's tests join claude-annotate's suite and run on its per-worker webcompanion harness (`skills/tests/harness.py`), not on the daemon in use.
- `requirements-test.txt` pins `aiohttp` with the marker `python_version >= "3.11"`, as it did before `d73ad8e`. Talk's suite skips below Python 3.11. Every file still compiles under 3.9, which the pre-push hook's 3.9 compile and collection step checks.
- Stage's browser tests and talk's browser tests run strict under the pre-push hook, like the rest of the suite.

## Order of work

1. Copy into claude-annotate. Merge the webcompanion client. Register the hook. Make talk's settings generic.
2. Both suites pass in claude-annotate under the pre-push hook's conditions.
3. A live `/talk` call runs from claude-annotate on this machine: a spoken turn, an answer with a diagram on the stage, and frames stepping with the voice.
4. Only then, delete from env and update env, its profiles and evooq-env. Run `@claude doctor` after the profile change.
5. Env and evooq-env are committed and pushed as usual. claude-annotate is public: ask before pushing it.

## Out of scope

- Moving the diagram generators (project 2).
- The `data-key` frame contract, the free HTML view and `[[show sequence]]` (project 3).
- Any change to how talk or stage look or behave, beyond the settings in section 2.
