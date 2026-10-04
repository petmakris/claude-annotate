# dataflow — handling a watcher event

Read this when a task-notification arrives whose first stdout line is one of
the `WEBCOMPANION_*` banners for a `dataflow` session — every question on a
node lands here.

## `WEBCOMPANION_EVENT` (a question on a node)

1. **Parse the banner** for `sid` and `event_id`.
2. **Read the payload** between `---payload---` and `---end---`: the daemon
   stores exactly `{anchor, text, images}` — `anchor` is always `node:<id>`,
   `text` is the question, `images` is `[{token, path}]` — `Read` each before
   answering.
3. **Compose the answer:**
   - Fetch the current document —
     `skills._shared.webcompanion_client.get_items(sid, kind="dataflow")["__flow__"]["body"]`
     — and find the node by id. Its `file`, `line`, `summary` and `note` are
     the subject.
   - `Read` the anchored file around that line. `Grep`/`Glob` for whatever the
     question pulls in beyond it.
   - Other nodes' threads —
     `skills._shared.webcompanion_client.get_threads(sid, kind="dataflow")`
     — are READ-ONLY background. Never write into another node's thread.
   - 2–4 sentences, naming actual methods, fields and line numbers, written to
     the style guide below. Do not modify code.
4. **Append to that node's thread, then acknowledge the event:**

   a. `Write` the answer (raw markdown) to your scratchpad as
      `dataflow-reply.md`.

   b. Run — appends the reply to the node's thread:
   ```bash
   claude-annotate python -c "
   import pathlib
   from skills._shared import webcompanion_client as wc
   text = pathlib.Path('<scratchpad>/dataflow-reply.md').read_text()
   wc.append_thread('<sid>', 'node:<id>', text, kind='dataflow', role='agent',
                    source_event_id='<event_id>', title='<short headline>')
   "
   ```

   c. Then, and only then, acknowledge the event — or the daemon re-emits it
      three times, thirty minutes apart, and finally drops it:
   ```bash
   webcompanion ack --sid "<sid>" --event-id "<event_id>"
   ```
5. **End your turn. No terminal output.** The watcher stays armed.

**When the answer needs a node that is not on the diagram**, you may
regenerate the document — see "Regenerating the diagram mid-session" under
"Write the document" in SKILL.md. Say in the reply what you added.

## `WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED`

Terminal: *"Dataflow for `<seed>` closed."* / *"…cancelled."*

## `WEBCOMPANION_DROPPED`

An event went unanswered through every re-emit. Say so plainly: *"A dataflow
question went unanswered and was dropped — please re-ask it on the node."*

## Response style guide

- **Self-contained synthesis.** Each reply answers *all* questions asked on
  that node so far; the page renders only your most recent reply.
- **Short.** 2–4 sentences in most cases.
- **Code-aware.** Name the actual variables, methods and lines.
- **Cite nodes by name** when the answer lives elsewhere on the diagram.
- **Honest uncertainty.** Name exactly what you would need to know.
- **Headline title.** The `title` passed to `append_thread`: plain text,
  ≤ 6 words.
