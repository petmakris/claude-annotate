# Stage — live, named views any skill can put in front of the user

Date: 2026-09-27. Status: approved design, not yet built.

## Why

The value of `/talk` is the visual feedback beside the voice, and its board is the weak
part. It can only show snapshots of code, Mermaid diagrams and tables, each one a new tab,
and it cannot show the thing the user is actually working on. A deck being edited during a
call had to be opened by hand in another tab and reloaded by hand after every edit.

The stage replaces that board with a general mechanism: a page of **named views**, each
kept live against its source, that Claude updates in place while the user watches. It is a
webcompanion session kind, so `/talk` embeds it, and so can any other skill or a session
with no voice at all.

This spec covers the first of three pieces. The other two get their own specs:

1. **The stage** (this spec): named live views, the daemon mount route, `/talk` embedding.
2. **Claude points:** jump to a slide, scroll to a section, highlight an element, zoom.
3. **The user points back:** clicks, selections and what is in view travel into the next
   voice turn or comment as "this".

Nothing in this spec may close off 2 or 3; see "Room left for pieces 2 and 3".

## Components

| Where | What | New or changed |
|---|---|---|
| webcompanion | mount routes: register a named directory, serve files from it | new, additive to contract 1 |
| claude-annotate `skills/stage/` | `stage.py` CLI, `watch` loop, `static/` renderer, `SKILL.md` | new |
| claude-annotate `skills/talk/` | embeds the stage; board tags become stage views; its own board is deleted | changed |

## webcompanion: mounts

A session may register named directories and have the daemon serve files from them
directly from disk. This exists because a real deck is an HTML file plus a sibling
`assets/` folder of tens of megabytes: the deck skill's copy-on-every-push approach copies
only the HTML file today, so relative asset references break, and copying the whole
folder on every save would be slow.

Routes, both added beside `/api/assets` in `server.py`'s flat routing chain:

| Method | Path | write | Behaviour |
|---|---|---|---|
| POST | `/s/{sid}/api/mounts` | write | Body `{name, root}`. `name` matches `^[a-z0-9][a-z0-9_-]{0,63}$`. `root` is resolved and must be an existing directory **inside the session's `cwd`** (`403` otherwise, the same containment rule `/api/open` uses). Stored in `mounts.json` in the session's workspace, so it survives daemon restarts. Re-registering a name replaces its root. Returns `200 {name, url}`. |
| GET | `/s/{sid}/mounts/<name>/<relpath>` | | Serves `root/relpath`, symlinks resolved, `403` if the result escapes `root`, `404` if not a file or the name is unknown. Sends `Cache-Control: no-store`, so a reload after a save always gets the new bytes. |

`docs/contract.md` gains both rows and a line that they are additive: contract stays 1.
The shell page and every existing route are untouched.

## claude-annotate: the stage skill

### Session

One stage per project directory: `kind: stage`, `cwd` the repo root. `stage.py` attaches to
the newest live stage for its `cwd` or creates one, so every call keeps the URL the user
already has open. `--slug` targets a specific stage.

### Items

| Anchor | Body |
|---|---|
| `view:<name>` | `{name, title, source, rev}` |
| `__layout__` | `{order: [name...], front: name}` |

`source` is one of:

| `type` | Fields | Rendered as |
|---|---|---|
| `file` | `path` (relative to `cwd`), `mount`, `fragment?` | iframe on `mounts/<mount>/<file>` |
| `url` | `url` | iframe on the URL |
| `session` | `sid` or `kind` + `slug` | iframe on that session's `/s/{sid}/` page |
| `inline` | `format: code \| diagram \| table`, plus `path`/`start`/`lines`/`highlight`/`lang` for code, `body` for the others | rendered on the page, as `/talk`'s board does today |

A `file` view mounts its file's **parent directory** under a mount name derived from that
directory, so the deck and its `assets/` resolve together; two files in one directory share
a mount. `rev` is the source's content revision (for files, the newest `st_mtime_ns` under
the mounted directory). The page reloads a view's frame only when `rev` changes.

### CLI

```
stage.py show <name> <source> [--title T] [--background] [--cwd DIR] [--slug S]
stage.py hide <name>
stage.py link            # print the stage URL, creating the stage if needed
stage.py watch           # the background revision loop, see below
```

`<source>` is parsed by shape: an existing path is `file` (a `#fragment` suffix is kept as
the frame's fragment), `http(s)://` is `url`, `session:<kind>/<slug>` is `session`, and
`code:<path>:<a>-<b>`, `diagram:-` / `table:-` (body on stdin) are `inline`. Showing an
existing name updates that view in place rather than adding one. `show` brings the view to
the front unless `--background`. `show` starts `watch` if none is running for this stage.

`show` is a plain command so Claude can call it in the same message as its first work call:
the visual reaches the user while the spoken answer is still being prepared.

### watch

Polls the mounted directories of every `file` view about twice a second, and on a change
writes that view's new `rev`. It rides out a briefly missing file (editors that save by
rename), and exits when the stage session is no longer live, checked every 30 seconds, as
the deck skill's `--watch` does. At most one `watch` runs per stage, guarded by a pid file
in the session's workspace directory.

### Renderer

`static/entry.js`, `stage.js`, `stage.css`, registered with `/api/assets`. A tab strip over
one pane per view, in `__layout__` order, `front` selected. It subscribes through
`/_wc/core.js`'s `init({onDelta})`:

- `view:<name>` changed: if only `rev` changed, reload that frame, keeping its scroll
  position (same-origin mount frames) and its `#fragment`; otherwise rebuild the pane.
- `view:<name>` deleted (version 0): remove its tab.
- `__layout__` changed: reorder tabs, select `front`.

Inline rendering (highlighted code with line numbers and highlights, Mermaid, sanitised
markdown tables) moves here from `talk.py`'s page, so there is one implementation.

The page follows the light and dark themes and works at phone width; the tab strip scrolls
horizontally rather than wrapping.

## /talk changes

- At launch, `talk.py` runs `stage.py link` for its `--code` directory and embeds the stage
  URL in an iframe where the board is now. The board's HTML, CSS and JS in `talk.py` are
  deleted.
- `[[show code|diagram|table ...]]` tags in a reply are turned into `stage.py show` calls
  (inline views, named from their titles), so existing answers keep working.
- `SKILL.md` gains a "Showing things" section: prefer `stage.py show` for anything the user
  is working on (a deck, a page, a running app); show it as early as possible in a turn,
  not only in the reply; reuse a name to update a view instead of adding one.
- `talk.py --doctor` checks the webcompanion daemon is reachable and prints the fix when it
  is not. The README's "talk is the exception" line changes: `/talk` now needs the daemon.
- For a user at another machine, the stage URL needs a route to the daemon's port, as the
  talk page already needs one to port 8766.

## Failure handling

| Situation | Behaviour |
|---|---|
| A `file` view's file is missing | The pane shows "waiting for `<path>`" and loads when it reappears. |
| The daemon is unreachable | `stage.py` exits non-zero with the daemon's name and the fix; `/talk` refuses to start and says so. |
| A path outside the project | `stage.py show` refuses before calling the daemon; the daemon refuses it too. |
| A `url` that will not frame | The pane shows the URL as a link to open in a new tab. |
| `watch` dies | The next `show` restarts it; stale views update on that `show`. |

## Room left for pieces 2 and 3

- Frames on `mounts/` are same-origin with the stage page, so piece 2 can drive them
  (`goTo`, scroll, highlight) and piece 3 can read clicks and selection from them, without
  the files having to cooperate. `url` and `session` frames will need a small injected
  bridge or `postMessage`; nothing here prevents that.
- `__layout__` is the natural place for a focus instruction (`{front, focus: {view, target}}`).
- The stage session's `submit` events are the natural channel for "the user pointed at X".

## Testing

- webcompanion: registering a mount inside and outside `cwd`; serving a file; symlink
  escape refused; unknown name `404`; `Cache-Control: no-store` present; `mounts.json`
  survives a daemon restart.
- stage: source parsing for every shape; `show` writes the expected item and layout against
  the fake daemon the client tests already use; `show` on an existing name updates in
  place; `hide` deletes; touching a file under a mount bumps `rev`; `watch` exits when the
  session ends.
- talk: board tags produce the expected `stage.py show` calls; the page embeds the stage URL.
- Browser (Playwright, skipped when absent): editing a mounted HTML file reloads only its
  frame and keeps its `#slide-N` fragment.
