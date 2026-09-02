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

## Resolve the plugin root

`skills.walkthrough.push` and `skills.walkthrough.steps` both run out of the
plugin's own tree, and `$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash
tool's shell. Run this once per turn, before the first command that needs it —
the guard is not ceremony: without it, a machine with no python3 gets a bare
traceback instead of a sentence naming the plugin and the fix.

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.
claude-annotate is the marketplace that ships this plugin and claude-ide-review.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '
import json, os, sys
NAME, MARKER = "claude-annotate", "skills/walkthrough/push.py"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit(f"could not locate the {NAME} plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
```

Two candidates, in order: every `bin/` directory on `PATH` (Claude Code adds
`<plugin-root>/bin` for both `--plugin-dir` and marketplace installs, even
when that directory does not exist), then the marketplace registry. Each
candidate must actually contain `skills/walkthrough/push.py`, so the check is
a marker file rather than a directory name and survives the plugin being
cloned under any name.

**There is no longer a step that creates an empty session before you
explore.** `push.py` mints the session and installs the steps document in the
same call, and it needs a real document to push — so the tour now appears
once you have explored the code and written the document, in "Validate and
push the document" below, not before.

## Generate the steps

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
PYTHONPATH="$PLUGIN_ROOT" python3 - <<'PY'
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
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.walkthrough.push \
  --steps <scratchpad>/.steps.draft.json --cwd "$PWD"
```

Run this from the repository you are touring — never from `$PLUGIN_ROOT` — so
`$PWD` really is the repo root. Deliberately **omit `--title`**: `push.py`
falls back to the document's own `question` field when no title is given, and
that field already reached the daemon safely through the `Write` tool inside
`.steps.draft.json` — passing `--title "<question>"` here would re-embed the
same free-form text into a shell argument and reopen the quoting hazard the
`Write`-tool routing exists to avoid. The output is JSON: `sid`, `slug`,
`kind`, `url`, `title`. Save `sid` — you need it to arm the watcher and to
answer questions.

**One active tour per project, atomically.** `push.py` passes `supersede=True`
to the daemon: creating a new walkthrough session for this cwd ends any other
live walkthrough session for this same cwd first, in the same call — there is
no separate list-then-cancel step to run, this is automatic.

## Generation contract

Hard rules. A tour that breaks one of these is a defect, not a style choice.

- **5–12 steps.** Fewer than 5 means the question deserved a paragraph in
  terminal — answer it there instead and do not create a tour. More than 12 means
  the question is too broad: ask the user to narrow it. If they decline, build the
  best 12-step spine and say what you left out.
- **Every step is a real anchor.** `file` + `line` + verbatim `snippet`. Never
  anchor to a file you did not `Read` in this turn. Never guess a line number.
- **Execution order, not file order.** Follow how control and data actually flow:
  entry point → gate → dispatch → implementation → data model → seam. Grouping
  steps by package is a failure mode.
- **Each step earns its place.** The markdown says *what happens here* and *why it
  matters for the question asked* — 2–5 sentences. It is not a file summary.
- **The last step answers the question.** For "how to add X", the final steps carry
  `role: "edit-site"` and name the exact file or directory for the new code, the
  registration point, and the test that would prove it. Concretely named — never
  "somewhere in the workflow package".
- **Link references inline.** `[evaluate](src/main/java/.../RuleRegistry.java:30)`
  for code, absolute URLs for tickets. The IDE renders these clickable.
- **Titles ≤ 6 words**, plain-text noun phrases — they are rail rows and HUD text.
- **Cross-block re-pass.** After drafting all steps, re-read them together and fix
  what only shows up in aggregate: a step repeating its neighbour, a jump with a
  missing bridge, a title that no longer matches its body, an ordering that only
  made sense while you were writing it. Do this **before** writing the document —
  steps are frozen once pushed.

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

## Mode D — handling a watcher event

### `WEBCOMPANION_EVENT` (a question on a step)

1. **Parse the banner** for `sid` and `event_id`.
2. **Read the payload** between `---payload---` and `---end---`: the daemon
   stores exactly `{anchor, text, images}` — `anchor` is always `step:<id>`,
   `text` is the question, `images` is `[{token, path}]` — `Read` each before
   answering.
3. **Compose the answer:**
   - Fetch the current steps document —
     `skills._shared.webcompanion_client.get_items(sid, kind="walkthrough")["__steps__"]["body"]`
     — and locate the step by id. Its `file`, `line`, and `markdown` are the
     subject of the question.
   - `Read` the anchored file around that line. Use `Grep`/`Glob` for anything
     the question pulls in beyond it.
   - Other steps' threads —
     `skills._shared.webcompanion_client.get_threads(sid, kind="walkthrough")`
     — are READ-ONLY background. Never write into another step's thread.
   - 2–4 sentences, code-aware, markdown links inline, fenced code blocks for
     suggested snippets. **Do not modify code.**
4. **Append to that step's thread, then acknowledge the event:**

   a. `Write` the answer (raw markdown) to your scratchpad as
      `walkthrough-reply.md`.

   b. Run — appends the reply to the step's thread:
   ```bash
   PYTHONPATH="$PLUGIN_ROOT" python3 -c "
   import pathlib
   from skills._shared import webcompanion_client as wc
   text = pathlib.Path('<scratchpad>/walkthrough-reply.md').read_text()
   wc.append_thread('<sid>', 'step:<id>', text, kind='walkthrough', role='agent',
                    source_event_id='<event_id>', title='<short headline>')
   "
   ```

   c. Then, and only then, acknowledge the event — or the daemon re-emits it
      three times, thirty minutes apart, and finally drops it:
   ```bash
   webcompanion ack --sid "<sid>" --event-id "<event_id>"
   ```
5. **End your turn. No terminal output.** The watcher stays armed.

**Never rewrite the steps document in response to an event.** Steps are
frozen. If the answer really needs a different path through the code, say so
in the reply and offer to run a new `/walkthrough`.

### `WEBCOMPANION_FINISHED`

Terminal: *"Walkthrough for `<question>` closed."*

### `WEBCOMPANION_CANCELLED`

Terminal: *"Walkthrough for `<question>` cancelled."*

### `WEBCOMPANION_DROPPED`

An event went unanswered through every re-emit (an earlier wake-up was
interrupted or compacted away). Tell the user plainly: *"A walkthrough
question went unanswered and was dropped — please re-ask it on the step."*

## Response style guide

- **Self-contained synthesis.** Each reply answers *all* questions asked on that
  step so far. The IDE renders only your most recent reply; older ones are stored
  for audit but not displayed.
- **Short.** 2–4 sentences in most cases.
- **Code-aware.** Name the actual variables, methods, and lines.
- **Cite steps by number** when the answer lives elsewhere in the tour ("that's
  step 6").
- **Suggest, don't ask.** If a fix is warranted, show it as a code block. The user
  applies it.
- **Honest uncertainty.** Name exactly what you would need to know. Don't hedge.
- **Headline title.** Pass a `title` to `append_thread`: plain text, ≤ 6 words,
  a noun phrase. Refresh it each answer.

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
`WEBCOMPANION_CANCELLED` and exits on its own — handle per Mode D.

## Edge cases

- **Question too broad** — would exceed 12 steps. Ask once for a narrower question;
  if refused, build the best 12-step spine and say what you dropped.
- **Zero anchors found** — nothing in the codebase matches. Do **not** write or
  push `.steps.draft.json` — there is nothing to cancel, since no session
  exists until `push.py` runs. In terminal, say what you searched for and what
  you found instead.
- **`--diff` with an empty diff** — say so; do not create a session.
- **Validation failure** — the validate step (or `push.py` itself) lists every
  problem. Fix the draft, re-run. Never skip validation by pushing an
  unvalidated document directly.
- **Daemon unreachable** — `push.py` raises `DaemonUnreachable`, printed to
  stderr with the fix. Do not try to start the daemon yourself; run
  `webcompanion status` / `webcompanion doctor` and tell the user what they
  reported.
- **Tour lost** — tours are ephemeral by design. If the session ends, say so
  plainly and offer to regenerate.
- **Malformed event payload** — no reply; run
  `webcompanion ack --sid "<sid>" --event-id "<event_id>"` directly so the
  event isn't re-emitted forever.
- **Question with special characters** — the question lives only inside
  `.steps.draft.json`, written with the `Write` tool and never interpolated
  into a shell command. Omitting `--title` on the push command (see "Validate
  and push the document") is what keeps it that way — `push.py` reads the
  question back out of the document itself instead of it being re-typed into
  a shell argument. Do not add a `--title "<question>"` argument — that
  reopens the exact quoting hazard this avoids.

## Token budget

Generation is the expensive part: read what you need to anchor steps honestly, and
stop. Each wake-up afterwards is one question on one step — answer that, 2–4
sentences, and end the turn.
