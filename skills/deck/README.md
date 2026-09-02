# deck

Comment on a rendered presentation deck; Claude edits the `.html` on disk.
`/deck <path>` renders every slide as itself in the browser, and turns a click on any
element into one queued instruction.

- Skill contract: `SKILL.md`
- Model: `model.py` — parses a deck into slides and addressable elements. Pure,
  read-only, and it never emits HTML: a real deck mixes HTML entities with their
  literal characters, so round-tripping it through a serialiser rewrites a fifth
  of the file. Callers get line ranges and read the source themselves.
- No server of its own: `push.py` computes `model.py`'s parse of the deck and writes it
  to the **webcompanion daemon** — one always-on service shared by every migrated skill
  and IDE plugin — as the session's `__model__` item. Because the deck's own `.html` can
  run to tens of megabytes (well past the daemon's 2MB item cap), the file itself is
  never pushed as an item: `push.py` copies it, under a fixed name, into a directory it
  controls alongside its own `deck.js`/`deck.css`/`entry.js`, and registers that
  directory as the session's asset root. The copy is refreshed on every push — including
  after Claude edits the file — which is also the whole change-notification signal: the
  browser reacts to `__model__`'s version changing, not to polling the file on disk.
- Client: `static/deck.js` + `static/deck.css`, loaded by the daemon's own shell page via
  `static/entry.js`. Each slide loads the whole deck in a same-origin iframe with the
  other slides hidden, then the harness's zoom-to-fit, page-number injection and floating
  chrome are undone **in that frame's DOM only**. Speaker notes are `display:none` in most
  decks, so they render in a column beside the slide instead.
- Per-session state (the model, the event queue) lives in the daemon's own session
  directories, not under the project being reviewed.

The deck file is written by exactly one thing: Claude's `Edit` tool. Not the daemon, not
the browser.

## Cost, and the limit of this design

One frame per slide means one copy of the deck document per mounted slide. Frames mount
lazily — only slides near the viewport hold one — which is what keeps a 16MB deck
(embedded images) from putting 25 copies in memory at once.

The daemon's asset route sends no `ETag` and answers no conditional request at all — every
mounted frame's `GET` gets the whole file back, full price, every time. So a large deck
still costs one full read per mounted slide — the same cost the old per-skill server's own
`ETag`/`If-None-Match` handling never actually avoided in practice, since Chrome declined
to cache against that server's HTTP/1.0 response either way. Rendering the whole deck in a
single frame, which removes the per-slide copy entirely, remains the fix for this — it was
never about which server hosts the file. A sample deck to try it against lives in
`demo/sample-deck.html`.

Run the tests from the repo root:

```bash
python3 -m pytest skills/deck/tests/ -v
```
