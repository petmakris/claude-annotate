# deck

Comment on a rendered presentation deck; Claude edits the `.html` on disk.
`/deck <path>` serves the file into the browser, renders every slide as itself,
and turns a click on any element into one queued instruction.

- Skill contract: `SKILL.md`
- Model: `model.py` — parses a deck into slides and addressable elements. Pure,
  read-only, and it never emits HTML: a real deck mixes HTML entities with their
  literal characters, so round-tripping it through a serialiser rewrites a fifth
  of the file. Callers get line ranges and read the source themselves.
- Server: `server.py` (handlers over `skills/_shared/web_companion`), port 3090,
  state root `~/.claude/deck/`.
- Client: `static/deck.js` + `static/deck.css`. Each slide loads the whole deck
  in a same-origin iframe with the other slides hidden, then the harness's
  zoom-to-fit, page-number injection and floating chrome are undone **in that
  frame's DOM only**. Speaker notes are `display:none` in most decks, so they
  render in a column beside the slide instead.
- Per-session state lives in `<project>/.claude/deck/<sid>/state/`: `meta.json`
  (which deck this workspace is attached to), `events/`, `consumed/`.

The deck file is written by exactly one thing: Claude's `Edit` tool. Not the
server, not the browser.

## Cost, and the limit of this design

One frame per slide means one copy of the deck document per mounted slide.
Frames mount lazily — only slides near the viewport hold one — which is what
keeps a 16MB deck (embedded images) from putting 25 copies in memory at once.

The `deck` route sends an `ETag` and answers `If-None-Match` with a 304, but
measured against Chrome the frames still refetch in full: the shared engine
speaks HTTP/1.0, and the browser declines to store the response. So a large
deck costs one full read per mounted slide. Rendering the whole deck in a
single frame, which removes the per-slide copy entirely, is the Phase 2 fix.

A sample deck to try it against lives in `demo/sample-deck.html`.

Run the tests from the repo root:

```bash
python3 -m pytest skills/deck/tests/ -v
```
