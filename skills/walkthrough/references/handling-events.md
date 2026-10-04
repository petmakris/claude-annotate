# walkthrough — handling a watcher event

Read this when a task-notification arrives whose first stdout line is one of
the `WEBCOMPANION_*` banners for a `walkthrough` session — every question on a
step lands here.

## `WEBCOMPANION_EVENT` (a question on a step)

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
     suggested snippets, written to the style guide below. **Do not modify
     code.**
4. **Append to that step's thread, then acknowledge the event:**

   a. `Write` the answer (raw markdown) to your scratchpad as
      `walkthrough-reply.md`.

   b. Run — appends the reply to the step's thread:
   ```bash
   claude-annotate python -c "
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

## `WEBCOMPANION_FINISHED`

Terminal: *"Walkthrough for `<question>` closed."*

## `WEBCOMPANION_CANCELLED`

Terminal: *"Walkthrough for `<question>` cancelled."*

## `WEBCOMPANION_DROPPED`

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
