# Answering a question asked on a field

After pushing, arm the watcher once in the background (run it inside `Monitor` so
each printed line becomes a notification, rather than invoking it fresh per event —
see "One watch, many events" below):

```bash
webcompanion watch --kind specimen --sid <sid>
```

`--max-emits N` (default 3) is the only other flag; it bounds how many times an
unacked event is re-printed before the watcher gives up on it.

It prints one of four banners, each confirmed by reading
`webcompanion/commands/watch.py`:
`WEBCOMPANION_EVENT skill=<kind> sid=<sid> event_id=<id>`,
`WEBCOMPANION_FINISHED skill=<kind> sid=<sid>`,
`WEBCOMPANION_CANCELLED skill=<kind> sid=<sid>`,
`WEBCOMPANION_DROPPED skill=<kind> sid=<sid> event_id=<id>` (an event that was
never acked within `--max-emits` tries; the watcher keeps running afterwards — this
does not end the loop).

## On `WEBCOMPANION_EVENT`

1. Parse the banner with `lib.answer.parse_banner` for `sid` and `event_id`.
2. Parse the block between `---payload---` and `---end---` with
   `lib.answer.parse_payload`. The block is one line of JSON with `anchor`, `text`
   (the question) and `images`; `parse_payload` returns `anchor` and `question`.
3. Call `lib.answer.context_for(types_payload, anchor)`, where `types_payload` is
   the `__specimen__` item's `types.json`-shaped body (`root`, `worktree`, `commit`,
   `types`).
   - `known` false means the anchor's type, or that type's field, is not in this
     specimen — `reason` says which. Say that. Do not answer about a field you
     cannot see.
   - `known` true gives `type`, `field`, `declared`, `nullability`, `source`,
     `line`, `shapeFrom` (`<basename>:<line>`), `siblings` (every other field on
     the same type, each with `name`/`declared`/`nullability`), `commit`,
     `worktree`.
4. Read the source at `source`:`line` before answering. The context grounds the
   answer; it does not replace reading the code.
5. Write the reply to a file and send it:

```bash
webcompanion reply --sid <sid> --anchor <anchor> --text <path-to-file>
webcompanion ack   --sid <sid> --event-id <event_id>
```

`reply --text` takes a path to a file holding the reply's raw text, not a literal
string — confirmed by `webcompanion reply --help` and by
`webcompanion/commands/reply.py`, which reads it with `Path(args.text).read_text()`.
`ack` also takes `--kind`, needed only if `--sid` is an ambiguous slug rather than a
real sid.

## One watch, many events

A single `webcompanion watch` invocation is not one-shot. Read from
`webcompanion/commands/watch.py`: after an event is acked it is archived and the
process loops back to wait for the next one, in the same run — it only exits on
`WEBCOMPANION_FINISHED` or `WEBCOMPANION_CANCELLED` (or if the session's workspace
is gone). Confirmed by running it live: `webcompanion watch` against a disposable
test session printed a `WEBCOMPANION_EVENT`, was replied to and acked, and then
printed a second `WEBCOMPANION_EVENT` for a second question submitted afterward —
same process, no restart. So there is nothing to "re-arm" between events; keep
reading the one running watcher's output and answer each `WEBCOMPANION_EVENT` as it
comes. Only start `webcompanion watch` again if the process actually ended
(`WEBCOMPANION_FINISHED`, `WEBCOMPANION_CANCELLED`, or it crashed).

## What a good answer does

Names the line it read. Compares the field to its siblings from `context_for`,
because "why is this null?" is usually answered by "because the one next to it is
`@NonNull` and this one is not". Says plainly when the honest answer is that the
page cannot tell — the page shows shape, not behaviour, and `context_for` never
reports anything beyond declared type, nullability, and source location.

`WEBCOMPANION_FINISHED` and `WEBCOMPANION_CANCELLED` end the loop; there is no
event to answer, and no further reply or ack to send.
