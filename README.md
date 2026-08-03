# claude-annotate

Claude writes you a long answer. You read it in a browser instead of a terminal,
click the one paragraph you disagree with, and type why. Claude rewrites *that
block* — not the whole answer, not a fresh reply appended below it.

<!-- SCREENSHOT: hero.gif — see docs/SHOTLIST.md -->

## Install

    /plugin marketplace add petmakris/claude-annotate

Python 3 standard library only. Nothing to `pip install`.

## Use

Ask for something long — a migration plan, a critique of a design, a list of
findings. Claude routes answers with several distinct parts through the view on
its own. To push an answer that has already landed:

    /annotate

Your browser opens. Every block is clickable. Comment on one, and Claude's reply
replaces it in place; the rest of the page does not move or reload.

<!-- SCREENSHOT: comment-flow.gif — see docs/SHOTLIST.md -->

## How it works

A local HTTP server renders the response as addressable blocks and holds an SSE
connection to the page. Your comment becomes an event; Claude wakes, rewrites
that block, and patches it over the wire. Sessions persist on disk, so you can
close the tab and come back to a document with its comment history intact.

The server binds to `127.0.0.1` on a port chosen at startup and records it in
`~/.claude/annotate/server.json`.

Voice dictation needs a secure browser context, so it works on `localhost` and
not over a LAN hostname.

## Related

The engine underneath lives in
[web-companion](https://github.com/petmakris/web-companion) and is vendored here
under `skills/_shared/`. Those files are generated — fix bugs upstream.
[claude-ide-review](https://github.com/petmakris/claude-ide-review) applies the
same idea to PR diffs and code walkthroughs inside IntelliJ.

## License

MIT
