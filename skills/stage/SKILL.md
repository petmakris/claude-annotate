---
name: stage
description: Put something in front of the user on a live page and keep it current while you work — a deck or HTML page being edited, a running app or dashboard URL, another webcompanion session, a code range, a sequence diagram, a flowchart, an architecture map or a table. Each view has a name; showing the same name again updates it in place, and a file view reloads on every save. Use when the user says "/stage", "show me", "put it on the stage", or when seeing the thing would beat reading about it. /talk uses it for its board.
argument-hint: "[<name> <source>]"
allowed-tools:
  - Bash
---

# /stage — named live views

`$SKILL_DIR` is this skill's base directory. The stage is one webcompanion page per project;
calls below attach to it.

    python3 "$SKILL_DIR/stage.py" show <name> <source> [--title "..."] [--background] [--slug S]
    python3 "$SKILL_DIR/stage.py" hide <name> [--slug S]
    python3 "$SKILL_DIR/stage.py" link [--slug S]

`show` and `link` print the stage's URL; `hide` does not. `--slug` picks one stage of the project
by slug or sid; /talk gives every call a stage of its own and names its sid, so pass it during a call.
Without `--slug` the newest stage of the project is used, never a talk call's (`talk-...`). A slug
that names an ended stage or a stage in another folder fails rather than making a second stage, and
`show` refuses a view name another writer (a talk call's board, or a hand-made view) already holds.

`<source>` is one of:

| Source | Shows |
|---|---|
| `path/to/file.html[#fragment]` | a project file, reloaded on every save of anything in its folder |
| `https://...` | any address |
| `session:<kind>/<slug>` | another webcompanion session's page (a deck, a dataflow, an annotate answer) |
| `code:<path>:<a>-<b> [highlight x-y]` | at most 60 lines of real code; a longer range is cut and `stage.py show` says so on stderr. Never a `.env`, a key, a `.git` path or a file git ignores |
| `change:<path> [since <rev>] [hunk N]` | what changed in a file, read from git (working tree against HEAD by default), in the file's own repository when the project holds a nested one; whole hunks up to 80 diff lines, then a note of how many changed lines are left out; `hunk N` or `hunks A-B` shows those hunks instead |
| `table:-` | markdown tables, body on stdin (heredoc). Cells hold text, `code`, **bold**, *em* and links; raw HTML is shown as typed (`List<T>`), only `<br>` breaks a line. A cell that starts with a check, a cross or a warning sign is coloured as allowed, blocked or caution. The grid is drawn once at its final size and never moves; a call lights a row, rows, a column or cells on it |
| `diagram:-` | Mermaid on stdin, which the stage does not draw itself: a graph, flowchart or state diagram becomes a flowchart (drawn as a map, as a talk call draws it) and a `sequenceDiagram` a sequence (drawn as lanes; `loop`, `alt`, `opt` and `par` become boxes, but not one inside another); any other kind, or a sequence line with no place on the lanes (`critical`, `break`, `rect`), exits 2 naming the JSON kinds to write instead. `mermaid:-`, `graph:-` and `flow:-` are the same |
| `sequence:-` / `flowchart:-` | a sequence diagram (drawn as lanes) or a flowchart (drawn as a map), drawn by the stage itself from a JSON spec in annotate's format on stdin (the spec is in `$SKILL_DIR/../annotate/references/block-kinds/`; give only the inner `spec` object, not annotate's block wrapper or its `source` form); a sequence also takes the lane sequence's `role`, `checks`, `n`, `outcome` and four tones (`$SKILL_DIR/../../docs/vz.md`); a refused spec exits 2 with the reason |
| `screen:<path/spotlight.json>` | a user interface explained part by part, from a spotlight spec (`$SKILL_DIR/../spotlight/SKILL.md`) in the project: one screen at a time, dimmed except the part in focus, which is ringed and joined by a dashed line to its count, title and text beside it. Its images are served from the spec's folder. On its own, Back and Next step through the parts; in a call the voice does (talk's `[[show screen: ...]]`). A refused spec exits 2 with the reason |
| `map:-` | an architecture map, from the map spec of `$SKILL_DIR/../../docs/vz.md` on stdin, drawn by `map_svg` in the same look as everywhere else; a refused spec exits 2 with the reason |

Rules:

- **Name views for what they are** (`deck`, `login-flow`, `pricing-table`) and reuse the name
  to update; a new name is a new board.
- **One board in front, the rest in a history.** The stage shows one board at a time under a 40px header:
  ‹ and › walk through the boards (so do the ← and → keys on a stage opened on its own; in a call they move the voice), “2 of 5” opens the list of every board (newest first, Key points last),
  and an orange dot there means a board changed while another was in front. Kind, size and update time
  show in a tooltip on the title.
- **Show early.** Call `show` in the same message as your first work call, not after the
  answer is written.
- **Files must be inside the project** (`--cwd`, default the git root); anything else is refused.
- Exit 2 means the name or source was refused (the message says why); exit 3 means the
  webcompanion daemon is not reachable or refused the request (the message says which):
  `webcompanion status`, then `webcompanion doctor`.
- Give the user the printed URL once per session; later views appear on the same page.
- A view's body may also carry the number of the answer that showed it (`answer`), with its
  `kind`; /talk sets these itself through `stage.show(..., extra=...)`, with no CLI flag.
- **A page you write for the stage follows the call's theme.** Give it both dark rules,
  `@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){...}}` and
  `:root[data-theme="dark"]{...}`. A file board gets `data-theme` on its `<html>` from the stage.
  A page on another address (`https://...`) cannot be reached that way: it gets
  `{type:'stage:theme', theme}` as a message instead, so it also needs
  `addEventListener("message", e => { if (e.data?.type === "stage:theme") document.documentElement.dataset.theme = e.data.theme; })`.
  Prefer a file in the project over an address.
- **Never put up a site that refuses to be framed; give its link instead.** The stage shows a page in a frame, and a
  site whose `Content-Security-Policy: frame-ancestors` or `X-Frame-Options` leaves the stage out draws as an empty
  board. Jira and Confluence (`*.atlassian.net`) are such sites, and so are GitHub and most sign-in pages. Check with
  `curl -sI <url>` when unsure; for those, say the link (or show a screenshot) and do not try the page.
- **During a talk call a page waits behind.** On a call's stage a file, address or session view put up with
  `stage.py show` opens as a background board and never takes the front; `stage.py` says so on stderr. To talk
  about it, bring it into the answer with talk's `[[show page: ... | title]]`, which fronts it with the voice and
  replaces the copy put up by hand.
- **Inside a talk call the stage follows the voice.** /talk embeds the stage and steers it over
  postMessage (the protocol is at the top of `static/stage.js`): it fronts each board as the
  spoken answer reaches it and lights up the lines, row or node a `[[point ...]]` tag names (on a change board a
  removed line too), keeping a range of lines or rows in view whole when it fits. The call
  page's gear has a **Stage follows the voice** switch for it. Picking a board by hand (its tab, its chip
  in the conversation, or Back and Next on its steps) turns it off, and the board stays in front whatever the
  reader plays. **Follow the voice**, a button beside the board counter while following is off, the gear's
  switch, Play on the board in front, or the next answer starting by itself turns it on again and puts the board
  back where the voice is. A board the voice reaches before it has come up
  is fronted when it arrives. When an answer has ended, after a short hold, each board it stepped shows
  whole, nothing dimmed. The call page also sets the stage's light or dark theme. The answer that showed a view is
  marked on its row in the list (`A3`). Every answer that steps a view keeps its own scene on it (`scenes`, by answer number), and
  the call page names the answer with each frame, so replaying an earlier answer steps the board as that answer did; an answer
  that showed the board with no steps of its own shows it whole. A stage opened on its own ignores all of this. Code, change, table, sequence, flowchart and map views
  can be pointed at from /talk only; /talk also keeps a pinned **Key points** board of the call's
  `[[key: ...]]` tags. Embedded in a call, the stage also shows the sentence being said (`stage:caption`) under a board.
  A tap on a part of a board opens its popup (Ask about this posts `stage:ask`; Play from here posts `stage:play`).

## What the stage keeps true

A board that steps with the voice keeps these, and the tests check them on the compiled frames
(`stage_rule_breaks` in `skills/talk/tests/helpers.py`):

1. The part drawn as being said is the part the voice is on: each frame names it (`cur`), and the page draws only that.
2. A part appears no earlier than the sentence that names it, and is visible when it is named. A part not said yet is faint or an outline with no words.
3. The pointed highlight and the being-said emphasis never disagree; nothing is emphasised and dimmed at once.
4. An arrow is lit only with both its ends; an arriving arrow animates once, on a forward step only.
5. Back, seek and replay give the same picture as playing straight through.
6. Updates, resizing and a theme change keep the current picture correct.
7. Text fits its box, and nothing overlaps. The sentence being said is one line under the board, and never covers a part.
8. Cues fire on the right word.
