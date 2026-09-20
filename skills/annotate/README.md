# annotate

Render Claude responses as an interactive web page with per-block annotation.

## What it does

Long responses (multi-step plans, analyses, lists of findings) get pushed to a browser page where the user clicks any block to leave a comment. Claude updates that block in place when it responds — no page reload, no re-pushing the whole document.

### Capabilities

- **Granular review rounds** — hover any list item, paragraph, table row, or code block; give it one of four verdicts — comment, delete, keep as written, or compact — then submit the whole round as one event Claude applies in a single pass.

## How it works

**User workflow:**
1. User sees their response split into blocks on a web page.
2. Click any block, leave a comment, hit Submit.
3. Claude wakes up, rewrites that block, the page auto-refreshes it in place.
4. Repeat per block, in any order.
5. Click "Done" to finish the session.

**Technical flow:**
- `blocks.json` is a local, author-time file Claude writes to compose a push
  (the scratchpad is its natural home) — not a file the daemon reads or a
  session's canonical document. `push.py` renders it into items and PATCHes
  them onto the daemon, which owns storage from that point on.
- User comments trigger a per-block submit, not a whole-document submit.
- `webcompanion watch` (a daemon-shipped CLI, armed via the `Monitor` tool)
  wakes Claude with an event per submission; there is no per-skill watcher
  process or file-polling loop of annotate's own.
- Claude reads the event, rewrites the affected block, PATCHes it back, acks
  the event, and the page picks up the change over its SSE stream.

## Architecture

- **Server:** none of annotate's own. Every push and read goes to the
  **webcompanion daemon** — a separately-installed, always-on service shared
  by every migrated skill and the IDE plugin (`~/.claude/webcompanion/config.json`,
  a different repository at `github.com/petmakris/webcompanion`). The in-repo
  `skills/_shared/web_companion/` package still holds a server implementation,
  but it is retired and nothing launches it — see its own README for why it's
  kept anyway.
- **Client:** Static HTML/JS page (`static/`), served live off disk by the
  daemon's asset route and registered as the session's renderer at push time —
  not copied per session.
- **Session data:** owned entirely by the daemon (items, comment threads, the
  event queue) in its own session directories, not under the project being
  reviewed.
- **Watcher:** `webcompanion watch`, the daemon's own CLI — armed per session
  via the `Monitor` tool, not a process this skill starts or owns.

## Files

- `SKILL.md` — Full skill definition and implementation guide (API contracts, event flow, all edge cases), plus `references/` for the block-kind and lifecycle details kept out of the router file.
- `push.py` — Renders `blocks.json` into daemon items, creates or attaches to a session, registers `static/` as its renderer. The only thing that talks to the daemon.
- `blocks.py` — Block document model (the authoring/`blocks.json` shape) and validation.
- `render.py` — Renders one block model into the daemon item body `compat.js` expects.
- `anchors.py` / `check_anchors.py` — Code-anchor resolution and the pre-announce check that catches a wrong file/line before the URL goes out.
- `static/` — HTML/JS/CSS for the browser page.
- `diagrams/` — Server-side SVG renderers for the `flowchart` and `sequence` block kinds (`elk_layout.py` is the one renderer that shells out, to `node`, for geometry).
- `hooks/` — Claude Code hooks this plugin installs (progress publishing, etc.).
- `tests/` — Unit and integration tests.

## Diagram sizing

`diagrams/text_metrics.py` measures text with the **real advance widths of the
bundled fonts**, so nodes, pills and canvases are sized from their content
rather than from fixed constants. The widths live in the generated
`diagrams/font_metrics.py`; regenerate them after changing a bundled font:

    pip install fonttools brotli   # build-time only, never a runtime dependency
    python tools/gen_font_metrics.py \
      skills/_shared/web_companion/static/fonts \
      skills/annotate/diagrams/font_metrics.py

If a font size changes in `static/diagram.css`, mirror it in `STYLES` in
`text_metrics.py` — that table is the only place layout learns about type.

`tests/test_flowchart_geometry.py` and `tests/test_sequence_geometry.py` assert
geometry invariants on the rendered SVG (no overlapping nodes, no text escaping
its shape, no edge label on top of a node, nothing outside the viewBox) across
a fixed corpus plus 40 generated DAGs, so layout regressions fail a test
instead of only showing up in a screenshot.

## Trigger modes

- **Postmortem:** User types `/annotate` after a response — the explicit command is the only user trigger (the word "annotate" in prose is not); Claude re-composes the prior terminal answer through the same block-kind pipeline (substance preserved, presentation upgraded) and pushes it.
- **Forward:** While a session is live, Claude composes qualifying responses as blocks, writes `blocks.json`, announces the URL, arms the watcher.
- **Live session:** Typing `/annotate` makes the session live — from then on every substantive response routes to the browser and the terminal carries only status one-liners, until the user says "respond in terminal". The skill never self-invokes before that.
- **Event handling:** Watcher emits an event on submit/Done/cancel; Claude wakes up, applies the block-rewrite contract, updates `blocks.json`, acks the event.

See SKILL.md for full details.
