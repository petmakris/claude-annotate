---
name: walkthrough
description: Answer a codebase question as an ordered sequence of anchored steps walked in IntelliJ, not as terminal prose. Claude generates the steps, the IDE plugin walks the user through them, and the user can ask a question on any step which Claude answers in place. Triggered by /walkthrough <question>. Watcher events are WEBCOMPANION_EVENT / WEBCOMPANION_FINISHED / WEBCOMPANION_CANCELLED.
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Monitor
---

# /walkthrough — guided code tours in IntelliJ

> Requires the companion IntelliJ plugin. Without it this skill has nowhere to
> render — install the `.zip` from the repository's Releases page first.

Turn a question about a codebase into a path through it: 5–12 ordered steps, each
anchored to a real `file:line`, walked step-by-step in IntelliJ. The user steps
forward and backward, and can ask a question on any step; you answer into that
step in place.

Use this instead of answering in terminal prose whenever the honest answer is
"here is the path through the code". No code is modified — this is a tool for
*understanding*, and in v1 you never edit files as part of a tour.

## Invocation

```
/walkthrough <question>
/walkthrough --diff <question>
/walkthrough --diff <ref>..HEAD <question>
```

- Plain form: a tour over existing code. Works for both "how does X work" and
  "how would I add X" — the difference shows up in where the last steps land.
- `--diff` form: a tour over a change that already exists (uncommitted working
  copy by default, or the given ref range). You narrate the change; you do not
  make it.

## On every invocation: the daemon must be running

walkthrough no longer ships a server. Storage, comment threads and the event
queue all belong to the **webcompanion daemon** — one always-on service per
machine, shared with every other skill and IDE plugin that talks to it. It is
installed and kept alive by launchd (macOS) or systemd (Linux), so there is
nothing to start per session and no port to negotiate.

Confirm it is up before doing anything else:

```bash
webcompanion status
```

If that fails, stop and tell the user — do **not** try to start it yourself
(a client that auto-starts a service races every other client doing the same):

```
webcompanion doctor      # both interpreters, config, zipapp, launchd job, health
```

If `webcompanion` is not on PATH at all, the daemon has never been installed
on this machine:

```
pipx install webcompanion && webcompanion install-service
```

## Running the plugin's own code

`skills.walkthrough.push` and `skills.walkthrough.steps` both run out of the plugin's own tree, and `$CLAUDE_PLUGIN_ROOT` is
**not** exported into the Bash tool's shell. Reach them through
`claude-annotate`, the plugin's runner: Claude Code puts the plugin's `bin/` on
`PATH`, the runner finds the plugin root from its own location, and on a
machine with no python3 it prints a sentence naming the plugin and the fix
instead of a traceback. Each command below is self-contained — nothing has to
be resolved first or carried between Bash calls.

**There is no longer a step that creates an empty session before you
explore.** `push.py` mints the session and installs the steps document in the
same call, and it needs a real document to push — so the tour now appears
once you have explored the code and written the document, in "Validate and
push the document" below, not before.

## Generate the steps

**`Read` `references/generation-contract.md` before writing the document** —
its rules (5–12 steps, real anchors, execution order, the cross-step re-pass)
decide whether the tour is a defect.

Explore, then write the step list. For `--diff` tours, start from
`git diff` / `git diff <range>` and read the touched files around each hunk.

Write the document with the `Write` tool to your scratchpad as
`.steps.draft.json` — not into a session's state directory, since no session
exists yet:

```json
{
  "question": "<the user's question, verbatim>",
  "kind": "explain",
  "generated_ts": 0,
  "steps": [
    {"id": 1,
     "title": "Where sharing starts",
     "file": "src/main/java/com/acmeshop/api/OrderShareController.java",
     "line": 42,
     "snippet": "return shareService.share(id);",
     "role": "context",
     "markdown": "The REST entry point. Everything below hangs off this call."}
  ]
}
```

- `file` is **project-relative** (no leading `/`, no `..`).
- `snippet` is the **verbatim text of that line**, copied from the file you read.
  It is what re-anchors the step after the file shifts; a wrong snippet makes the
  step stale in the IDE.
- `role` is `context` (grey badge), `seam` (blue — where behaviour is extended),
  or `edit-site` (green — where new code goes).
- `id` values are positive integers, unique, in walking order.

## Validate and push the document

Never hand the document straight to `push.py` unvalidated — validation is
what keeps a malformed tour out of the IDE:

```bash
claude-annotate python - <<'PY'
import json, time
from pathlib import Path
from skills.walkthrough import steps as steps_module
p = Path("<scratchpad>/.steps.draft.json")
doc = json.loads(p.read_text())
doc["generated_ts"] = int(time.time())
errors = steps_module.validate(doc)
if errors:
    raise SystemExit("\n".join(errors))
p.write_text(json.dumps(doc, indent=2))
print(f"validated: {len(doc['steps'])} steps")
PY
```

A non-zero exit lists every problem at once. Fix the draft and re-run — do not
push an invalid document.

Then push it. This both mints the session and installs the document as the
`__steps__` item in one call:

```bash
claude-annotate walkthrough.push \
  --steps <scratchpad>/.steps.draft.json --cwd "$PWD"
```

Run this from the repository you are touring, so `$PWD` is the repo root. **Omit `--title`**: `push.py` takes the document's own `question`, so the free-form text never enters a shell argument. The output is JSON (`sid`, `slug`, `kind`, `url`, `title`); save `sid`. The push ends any other live walkthrough for this cwd. [`references/push-details.md`](references/push-details.md) says why.

## Tell the user where to walk

One sentence in terminal, then stop:

**"Walkthrough ready — <N> steps for `<question>`. Open the project in IntelliJ; step forward with the walkthrough shortcut and ask on any step."**

## Arm the watcher

There is no watcher script of walkthrough's own any more — the daemon ships
its own, and it emits the same banners this skill has always read. Arm it
**immediately** after telling the user, before any other work.

```bash
webcompanion watch --kind walkthrough --sid "<sid>"
```

Pass that as the `Monitor` tool's `command` with `persistent: true` and a
`description` like `"walkthrough-wait sid=<sid>"`.

Banners: `WEBCOMPANION_EVENT skill=walkthrough sid=<sid> event_id=<id>`,
`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`.
Each stdout line wakes you once; the watcher stays alive across many events.

**Never stop the monitor while the walkthrough is open**, however long it has
been quiet, and never to save turns. The IDE plugin treats a heartbeat older
than 180s as an ended session (`DaemonSessionClient.REAP_AFTER_MS`) and latches
it one-way for that sid; re-arming does not undo it — only a new session does.
Only `webcompanion end` ends a walkthrough.

## Handling a watcher event

When a task-notification's first stdout line is `WEBCOMPANION_EVENT`,
`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED` or `WEBCOMPANION_DROPPED`,
**`Read` `references/handling-events.md` and follow it** — it covers reading
the question, composing the answer, appending it to the step's thread, acking,
and the reply style.

## When the walkthrough is done

When the user reaches the last step with no more questions, or says they're
done with the tour, end the session:

```bash
webcompanion end --sid "<sid>"
```

The watcher prints `WEBCOMPANION_FINISHED` and exits on its own.

## Terminal cancellation

If the user says "scrap it" / "stop the walkthrough" while a watcher is armed,
run `webcompanion end --sid "<sid>" --cancel`; the watcher prints
`WEBCOMPANION_CANCELLED` and exits on its own — handle it per
`references/handling-events.md`.

The user can also end it from IntelliJ: the panel's Dismiss button (⌥X)
clears the tour from the panel and the editor and cancels the session, so the
same `WEBCOMPANION_CANCELLED` arrives. A dismissed tour never comes back in the
IDE; a new `/walkthrough` shows as usual.

## Edge cases

Read [`references/edge-cases.md`](references/edge-cases.md) for each failure and what to do. Rules that always hold: never push an unvalidated document, never start the daemon yourself, never pass `--title "<question>"`, and answer each event in 2-4 sentences.
