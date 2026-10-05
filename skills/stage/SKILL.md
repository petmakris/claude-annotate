---
name: stage
description: Put something in front of the user on a live page and keep it current while you work — a deck or HTML page being edited, a running app or dashboard URL, another webcompanion session, a code range, a Mermaid diagram or a table. Each view has a name; showing the same name again updates it in place, and a file view reloads on every save. Use when the user says "/stage", "show me", "put it on the stage", or when seeing the thing would beat reading about it. /talk uses it for its board.
argument-hint: "[<name> <source>]"
allowed-tools:
  - Bash
---

# /stage — named live views

`$SKILL_DIR` is this skill's base directory. The stage is one webcompanion page per project;
calls below attach to it.

    python3 "$SKILL_DIR/stage.py" show <name> <source> [--title "..."] [--background]
    python3 "$SKILL_DIR/stage.py" hide <name>
    python3 "$SKILL_DIR/stage.py" link

`show` and `link` print the stage's URL; `hide` does not.

`<source>` is one of:

| Source | Shows |
|---|---|
| `path/to/file.html[#fragment]` | a project file, reloaded on every save of anything in its folder |
| `https://...` | any address |
| `session:<kind>/<slug>` | another webcompanion session's page (a deck, a dataflow, an annotate answer) |
| `code:<path>:<a>-<b> [highlight x-y]` | at most 60 lines of real code |
| `diagram:-` / `table:-` | Mermaid or a markdown table, body on stdin (heredoc) |

Rules:

- **Name views for what they are** (`deck`, `login-flow`, `pricing-table`) and reuse the name
  to update; a new name is a new tab.
- **Show early.** Call `show` in the same message as your first work call, not after the
  answer is written.
- **Files must be inside the project** (`--cwd`, default the git root); anything else is refused.
- Exit 2 means the name or source was refused (the message says why); exit 3 means the
  webcompanion daemon is not reachable or refused the request (the message says which):
  `webcompanion status`, then `webcompanion doctor`.
- Give the user the printed URL once per session; later views appear on the same page.
