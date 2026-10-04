# show-diff — questions on a diff line

Read this when the script's output included a `WC_SID=` line (comments are
live for this diff in VS Code), and again whenever a task-notification's first
stdout line is a `WEBCOMPANION_*` banner for a `skill=show-diff` session. It
covers arming the watcher, answering a question on a line, and ending the
review. The rule in SKILL.md's "Never summarise the diff" still governs the
turn the diff opens; it does not reach an answer to a question the user asked.

## Arm the watcher

If the script's output included a `WC_SID=` line, comments are live for this
diff in VS Code. Arm a watcher immediately, in the same turn:

```bash
Monitor: command = "webcompanion watch --kind show-diff --sid <WC_SID>", persistent = true
description: "show-diff-review sid=<WC_SID>"
```

The watcher prints the same banners `ask_diff`'s watcher does:
`WEBCOMPANION_EVENT skill=show-diff sid=<sid> event_id=<id>` (followed by
`---payload---`, the event JSON, `---end---`), `WEBCOMPANION_FINISHED`,
`WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`. Each wakes you once; the
watcher stays alive across many questions until the session ends.

If the script's output had no `WC_SID=` line, `webcompanion` was
unreachable — the diff is open read-only and there is nothing to arm.

## Mode D — answering a question on a diff line

You wake here when a task-notification's first stdout line is one of the
`WEBCOMPANION_*` banners above, for a `skill=show-diff` session. A
`WEBCOMPANION_DROPPED` banner (see the banner list under "Arm the watcher")
means step 6 below never happened for an earlier event — the watcher gave up
re-emitting it — so tell the user plainly that a question went unanswered and
ask them to re-ask it on the line, rather than trying to reconstruct it.

1. **Parse the banner** for `sid` and `event_id`. Read the payload between
   `---payload---` and `---end---`: `{"anchor": "<path>:<side>:<line>",
   "text": "<question>", "images": [...]}`.
2. **Read the diff.** The script printed `WC_STATE_DIR=<dir>` beside
   `WC_SID=` and wrote the diff it opened to `<dir>/diff.patch`; that
   directory does not change for the life of the session, so `Read` the patch
   from there if you kept the value.
3. **Read the session's `__meta__` item** — `{"checkout": ..., "base": ...,
   "head": ...}`, where `head` is a sha or the string `worktree`. `webcompanion`
   has no "get one item" CLI, and the daemon's own package lives in its pipx
   environment where the system `python3` cannot import it, so read it through
   the plugin's own client:

   ```bash
   claude-annotate python -c '
   import json
   from skills._shared import webcompanion_client as wc
   print(json.dumps(wc.get_items("<sid>", kind="show-diff")["__meta__"]["body"]))
   '
   ```

   Use `checkout` to `Read`/`Grep` surrounding source for context beyond the
   diff hunk. If you no longer have `WC_STATE_DIR`, the same three values
   rebuild the patch the script wrote: `git -C <checkout> diff --no-color
   <base>..<head>`, or `git -C <checkout> diff --no-color <base>` when `head`
   is `worktree`.
4. **Compose a short, code-aware answer** in markdown, 2-4 sentences
   typically, fenced code blocks for snippet suggestions. If you spot a real
   bug, flag it and suggest a fix as a code block — never modify the
   checkout itself, this is a read-only review view exactly like
   `ask_diff`.
5. **Write the answer to a file, then post it** — never interpolate the
   answer into a shell command; it may contain backticks, quotes, or
   `$(...)`:

   ```bash
   webcompanion reply --sid <sid> --anchor "<anchor>" --text <path-to-answer-file>
   ```
6. **Ack the event.** `webcompanion watch` is blocked waiting for this event's
   ack file — up to 30 minutes — and re-emits the same `WEBCOMPANION_EVENT`
   (and wakes you again) up to twice more if it never sees one, so this step
   is not optional cleanup:

   ```bash
   webcompanion ack --sid <sid> --event-id <event_id>
   ```

   Do this only after step 5 succeeds — an ack written before the reply lands
   would mark the question answered when it is not.

## Ending the review

When the user indicates they're done reviewing this diff — "looks good,"
"thanks, that answers it," moving on to another diff or a different task —
end the session:

```bash
webcompanion end --sid <sid>
```

The watcher prints `WEBCOMPANION_FINISHED` and exits on its own.
