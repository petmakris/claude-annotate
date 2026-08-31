# claude-annotate

Claude writes you a long answer. You read it in a browser instead of a terminal,
click the one paragraph you disagree with, and type why. Claude rewrites *that
block* — not the whole answer, not a fresh reply appended below it.

![Comment on one block; Claude rewrites it in place](docs/img/hero.gif)

## Requirements

- **`python3` on your `PATH`, version 3.9 or newer.** Standard library only —
  there is nothing to `pip install`.
- **`bash` and `curl`** (both ship with macOS and every mainstream Linux).
- **macOS or Linux.** Windows is not supported.
- `claude-ide-review` additionally needs the IntelliJ plugin — see below.

On a fresh Mac without the Xcode Command Line Tools there is no `python3` at
all; `xcode-select --install` or `brew install python` provides one. If
anything misbehaves after installing, run `/annotate-doctor` for a check of
your machine.

## Install

    /plugin marketplace add petmakris/claude-annotate

That registers the marketplace, which publishes two plugins. Install either or both:

    /plugin install claude-annotate      # comment on a long answer, or on a rendered slide deck
    /plugin install claude-ide-review    # ask questions on a PR diff line or walkthrough step, in IntelliJ

`claude-ide-review` also needs the IntelliJ half, which is a separate download —
grab the `.zip` from [Releases](https://github.com/petmakris/claude-annotate/releases)
and install it via **Settings → Plugins → ⚙ → Install Plugin from Disk…**

`annotate`, `deck`, `dataflow`, `walkthrough` and `interactive_review` drive the same
local server engine, which lives once in this repository at `skills/_shared/web_companion/`.
`show_diff`'s per-line diff comments instead depend on
[webcompanion](https://github.com/petmakris/webcompanion), a standalone daemon
installed separately (see [Related](#related)) — `show_diff` still opens diffs without it,
only the comment feature is unavailable.

## Use

Ask for something long — a migration plan, a critique of a design, a list of
findings, then push it into the view:

    /annotate

Your browser opens. Every block is clickable. Comment on one, and Claude's reply
replaces it in place; the rest of the page does not move or reload.

That first `/annotate` also arms the session: from then on every substantive
answer goes to the browser instead of the terminal, until you say "respond in
terminal". Nothing routes there on its own before you ask.

![The comment flow up close: type a correction, submit the round, the block updates](docs/img/comment-flow.gif)

## Decks

`/deck <path to a deck .html>` opens a presentation the same way, except the
document is a file you already own. Every slide renders as itself, in order, at
the size it will be shown. Click any line — a title, a paragraph, a bullet, a
speaker note — say what should change, and Claude edits that line in the file.

The deck is never rewritten wholesale. A comment resolves to a line range, not
to a search string, so an edit is one line in `git diff` and the entities,
attribute case and formatting everywhere else survive untouched.

    /deck ~/decks/2026-quarterly-review

A folder resolves to the `.html` inside it with the same name.

## Not just prose

Claude splits each answer into blocks and picks a kind per block — a decision
becomes clickable cards, a protocol becomes a sequence diagram, a UI idea
becomes a working mock. Every kind below is commentable, and Claude rewrites
the one you flag.

### Sequence diagrams

Rendered by the plugin's own SVG layout engine — actors, phases, and three
arrow types. Click any line to comment on **the step it draws**, not the whole
diagram, and Claude redraws the flow.

![Sequence diagram block](docs/img/block-sequence.png)

### Flowcharts

Structured nodes with roles that drive shape and color — entry, decision,
success, error — plus `Class:line` references that jump to the source. Nodes
take comments individually. Claude can also emit the flow as restricted Python
(`spec.source`), so you get a *line* to comment on when you want the logic
changed.

![Flowchart block](docs/img/block-flowchart.png)

### Mermaid diagrams

Architecture, state machines, ER, class diagrams — raw Mermaid source,
rendered to SVG on the server and themed to the page.

![Mermaid diagram block](docs/img/block-mermaid.png)

### Choice cards

When Claude reaches a genuine fork it asks with cards instead of prose: pick
one, add a note to your pick — or answer note-only, which means "none of
these, here's my direction" and makes Claude re-propose.

![Choice block](docs/img/block-choice.png)

### Interactive mockups

Real HTML with working `<style>` and `<script>`, sandboxed in an iframe — the
toggles toggle. Tag regions with `data-annotate-id` and comments can target
the sidebar or one settings row instead of the whole mock.

![Interactive mockup block](docs/img/block-mockup.png)

### The reading machinery around them

- **Rounds** — comments batch into one explicit submit, so Claude wakes once
  per review pass, not once per thought.
- **Four verdicts per block** — comment, *delete*, *keep as written*, or
  *compact* (fold its point into what stays). A whole review, not just margin
  notes.
- **Versions and diffs** — every rewrite bumps the block's version chip;
  "what changed" shows the diff, and older versions stay a click away.
- **Voice dictation** — dictate comments straight into the comment box
  (works on `localhost`, where the browser grants a secure context).
- **Fuzzy search** — filter a long answer down to the blocks that mention
  the thing you're looking for.
- **Paste images** — screenshots paste into comments and travel to Claude
  with the round.
- **Persistent workspaces** — documents live on disk until you delete them;
  close the tab, come back next month, the comment history is still there.
  The server's landing page lists every workspace with a delete button, and
  `/annotate resume <slug>` reattaches Claude to one. (Set
  `WEBCOMPANION_RETENTION_DAYS=N` to opt back into N-day auto-expiry.)
  Workspaces are stored centrally, at `~/.claude/<skill>/workspaces/<sid>/`,
  never inside the project they were created from — so deleting a throwaway
  git worktree doesn't take its annotations with it. Set
  `WEBCOMPANION_WORKSPACE_ROOT=/abs/path` to keep them somewhere else (the
  skill name is appended, so all four skills can share one volume); the
  server moves workspaces written under the old per-project layout into the
  central home on its next start.

## How it works

A local HTTP server renders the response as addressable blocks, and the page
polls it for changes. Your comment becomes an event; Claude wakes, rewrites that
block, and the next poll picks it up. Sessions persist on disk, so you can close
the tab and come back to a document with its comment history intact.

The server binds to `127.0.0.1` on a port chosen at startup and records it in
`~/.claude/annotate/server.json`.

Voice dictation needs a secure browser context, so it works on `localhost` and
not over a LAN hostname.

## Related

Five of the six skills (`annotate`, `deck`, `dataflow`, `walkthrough`,
`interactive_review`) drive the same local server engine, which lives here in
`skills/_shared/web_companion/` and is edited in place.

`show_diff` is the exception: its per-line VS Code comments depend on
[webcompanion](https://github.com/petmakris/webcompanion), a standalone daemon
published from its own repository and installed separately
(`pipx install webcompanion`). Run `/annotate-doctor` to check whether it's installed
and running, or to have it install and start it for you.

The older, similarly-named repositories
[web-companion](https://github.com/petmakris/web-companion) (hyphenated) and
[claude-ide-review](https://github.com/petmakris/claude-ide-review) are superseded
by this repository and kept for their history only — they predate `webcompanion`
above and are unrelated to it.

## License

MIT
