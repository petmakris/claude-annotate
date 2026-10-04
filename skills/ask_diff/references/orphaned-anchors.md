# ask-diff — `anchor_orphaned` events

Read this when a `WEBCOMPANION_EVENT` payload's `text` decodes to a dict with
`"event_kind": "anchor_orphaned"` (step 2 of
[handling-events.md](handling-events.md)): a git hook ran `sync.py` and a
thread could not be kept live.

The payload's `thread_title` and `old_anchor_text` name the thread and the
line it used to sit on. There is no reply to write into that thread — the
thread itself is untouched and still holds its full history for audit, just
no longer reachable by clicking a line in the IDE. Three distinct root causes
share this event, told apart by `reason`, and they are not interchangeable —
saying "moved too far to track" about a line that was located exactly is
simply false:

- **`reason` is `"stale"`** (or absent, for an older `sync.py`): the
  reviewed line's content drifted too far for `sync.py` to relocate it
  automatically — there is nowhere left to point the thread at. Tell the
  user in terminal, one sentence: **"A reviewed line moved too far for me to
  re-anchor automatically — the thread on `<thread_title>`
  (`<old_anchor_text>`) is still there if you want to revisit it, but you'll
  need to re-ask on the new line."**
- **`reason` is `"collision"`**: `sync.py` DID find exactly where this line
  went — `attempted_anchor` names it — but that position isn't free. Either
  another thread is sitting there and is not itself moving (possibly because
  it, too, was blocked and had to stay put), or a second thread is
  converging on the very same line; merging any of them would silently mix
  two unrelated conversations into one. Tell the user in terminal, one
  sentence: **"A reviewed line now sits exactly where another comment does
  (`<attempted_anchor>`), so I couldn't move `<thread_title>` there
  automatically — it's still tracking `<old_anchor_text>`'s old position."**
- **`reason` is `"cycle"`**: this line swapped places with another commented
  line (`attempted_anchor` names where it went), so migrating either one
  first would overwrite the other before it could move — neither is
  touched. Tell the user in terminal, one sentence: **"A reviewed line
  swapped places with another commented line, so I couldn't safely move
  either one automatically — `<thread_title>` is still tracking
  `<old_anchor_text>`'s old position."**

Either way, then acknowledge the event (the same
`webcompanion ack --sid "<sid>" --event-id "<event_id>"` call as any other
event — there is nothing else to do). Do not treat this as a question
and do not `append_thread`.
