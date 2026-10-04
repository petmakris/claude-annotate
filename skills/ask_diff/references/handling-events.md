# ask-diff — handling a watcher event

Read this when a task-notification arrives whose first stdout line is one of
the `WEBCOMPANION_*` banners for an `interactive-review` session — every
wake-up after the session is open lands here.

## `WEBCOMPANION_EVENT`

1. **Parse the banner:** extract `sid`, `event_id`.
2. **Read the payload** between `---payload---` and `---end---` — the daemon
   stores exactly `{anchor, text, images}` (there is no `type` field on the
   wire; the daemon's `_submit` handler keeps only these three keys from
   whatever was posted):
   - `anchor` — `<path>:<L|R>:<line>` or `<path>:<L|R>:<start>-<end>`, or
     `__general__` for a whole-PR comment.
   - `text` — a plain string, but it may itself be JSON encoding one of two
     structured envelopes. Check in this order, since a plain user comment
     can never legally match either:
     1. `json.loads(text)` succeeds, the result is a dict, and it has
        `"event_kind": "anchor_orphaned"` — this did **not** come from a
        user question. It is `sync.py`'s own notification that a git hook
        just ran and this anchor could not be kept live: `{"event_kind":
        "anchor_orphaned", "thread_title": "<...>", "old_anchor_text":
        "<...>", "reason": "stale" | "collision" | "cycle",
        "attempted_anchor": "<present when reason is "collision" or
        "cycle">"}`. Handle it per [orphaned-anchors.md](orphaned-anchors.md),
        not as a question.
     2. Otherwise, `json.loads(text)` succeeds, the result is a dict, and it
        has a `"v"` key — this is `ReviewSessionClient.postComment`'s
        anchor-text envelope: `{"v": 1, "anchor_text": "<line text at
        submit time, or "">", "comment": "<the user's actual question>"}`.
        Check `v == 1` (the only version this skill's parser knows); if
        `v` is anything else, don't guess at unfamiliar fields — fall back
        to treating the raw `text` string as the comment, with no
        `anchor_text`. On a recognized `v == 1`, the real question is
        `envelope["comment"]`, and `envelope["anchor_text"]` is the
        reviewed line's own text at the moment the user submitted (may be
        `""`).
     3. Otherwise (not JSON, or JSON without `event_kind`/`v`) — `text` is
        the comment verbatim, with no `anchor_text`.
   - `images` — `[{token, path}]`. `Read` each `path` before composing your
     answer if non-empty.

## Composing an answer (a real question)

1. Fetch the diff and PR metadata once per turn if you don't already have
   them cached:
   ```bash
   claude-annotate python -c "
   from skills._shared import webcompanion_client as wc
   items = wc.get_items('<sid>', kind='interactive-review')
   print(items['__diff__']['body'])
   "
   ```
   For specific-line anchors, narrow to the relevant hunk. For `__general__`,
   scan the whole diff.
2. **Read other open threads as background context.**
   `webcompanion_client.get_threads(sid, kind="interactive-review")` returns
   every anchor's thread. Skim them. A question the user asked on
   `Foo.java:42` may sharpen what you say about `Bar.java:113`, and vice
   versa. These threads are READ-ONLY input — they inform your synthesis on
   the active anchor; never write into another anchor's thread. The same
   call tells you whether the active anchor's thread already has a non-empty
   `anchor_text` (needed for the append step below).
3. Use `Read`, `Grep`, `Glob` to pull in surrounding source context if the
   diff alone isn't enough.
4. Write a short, code-aware answer in markdown: 2–4 sentences typically.
   Fenced code blocks for snippet suggestions. Shape it by
   [response-style.md](response-style.md) — the IDE renders a verdict quote,
   `####` labels and later quotes specially, and every reply carries a title.
5. If you spot a real bug, flag it and suggest a fix as a code block. **Do
   not modify the diff.**
6. Avoid hedging. If you genuinely need more context, say so concretely
   ("I'd need to see how `foo()` is called elsewhere") — don't ramble.

## Appending the reply and acknowledging

Write ONLY to the active anchor's thread (the one in the event payload).
Thread isolation is load-bearing: never mutate any other anchor's thread in
response to this event.

```bash
claude-annotate python -c "
from skills._shared import webcompanion_client as wc
wc.append_thread(
    '<sid>', '<anchor>', '''<your markdown answer>''',
    kind='interactive-review', role='agent',
    source_event_id='<event_id>', title='<short headline>',
    anchor_text=<'<envelope anchor_text>' if this is the thread's first reply else None>,
)
"
webcompanion ack --sid "<sid>" --event-id "<event_id>"
```

Only pass `anchor_text` when this is the thread's *first* Claude reply (the
`get_threads` read above came back with no `anchor_text` yet for this
anchor) — `set_anchor_text_if_absent` on the daemon's side is first-write-wins,
so sending it again on a follow-up is harmless but redundant; omit it there.
Never interpolate the answer or the anchor into a shell string — route
free-form content through Python's own triple-quoted literal (or, if it
contains `'''`, write it to a scratch file with `Write` and read it back in
the same `claude-annotate python -c`) rather than composing a shell command from it. Ack
only after the append succeeds — a crashed append means the event is
re-emitted and retried safely (see "Re-apply safety" below); acking first
would lose the question.

**End your turn. No terminal output.** The watcher stays armed.

## `WEBCOMPANION_FINISHED`

The session ended — normally because Claude called `webcompanion end` (see SKILL.md's
"Ending the review"); `ask_diff` has no IDE-side Done button. Ack in terminal: *"Review session for
`<title>` closed."*

## `WEBCOMPANION_CANCELLED`

The user cancelled (IDE, terminal `scrap it`, or superseded by a newer
review from this Claude session). Ack in terminal: *"Review session for
`<title>` cancelled."*

## `WEBCOMPANION_DROPPED`

An event went unanswered through every re-emit (an earlier wake-up was
interrupted or compacted away). Tell the user plainly: *"A review question
went unanswered and was dropped — please re-ask it on the line."*

## Re-apply safety

`append_thread`'s daemon-side handler dedups by `source_event_id`. If the
watcher restarts and re-emits an event you've already handled, the second
call is a no-op. Process the event normally each time — storage handles
dedup.
