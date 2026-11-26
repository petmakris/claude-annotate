# The annotate page today, read from the live page (spike CA-A2)

Rendered on 26 November 2026 from `origin/main` (ccb83ea), on a webcompanion
daemon with a scratch HOME, at 1440x900. These are the words the page showed,
in the order a round shows them. Clip beats follow this list, not the old loops.

| Step | What the page shows |
|---|---|
| Page open, watcher running | header pill `Watching` (without a watcher: `Unwatched`, in red) |
| Words selected | selection menu: `Comment (c)`, `Draw`, `Delete`, `Compact`, `Read`, `Explain`, `Edit` |
| Press `c` | floating window titled `Comment`, the quoted words above the box, buttons `Draw`, `Cancel`, mic, `Add to round` |
| Add to round | the comment shows as a chip under the words; dock `💬 1` with `Submit round (1)` |
| Submit round | dock `Applying round…`; the part greys with a pill `updating 0:03`; banner `Claude is applying your round… 0:06` under the toolbar |
| `claude-annotate progress --text` | bottom right pill `Claude is working 0:02` |
| push v2 | the part is replaced in place; nothing else moves |
| `progress --done` + `webcompanion ack` | pill `✓ Done in 4 s 1 step`; yellow bar `1 part changed — 1 you asked for` with `↑ prev`, `next ↓`, `dismiss`; the part's heading gets the chips `you asked` and `what changed` |

Not on the page any more: the "I disagree with this" checkbox (old loops) and a
v1 to v2 version chip. The old wording "1 section changed - you marked" is now
"1 part changed — 1 you asked for".

## The scripted Claude side of a round, in order

1. Ack every event left in `state/events/` before recording, else the watcher
   hands back an old round first and the page stays busy.
2. `webcompanion watch --kind annotate --sid <sid>` reads the round's `event_id`.
3. `claude-annotate progress --sid <sid> --text "Read your round of feedback" --event-id <id>`
4. `claude-annotate push --blocks plan.v2.blocks.json --cwd <repo> --slug <slug>`
5. `claude-annotate progress --sid <sid> --done`
6. `webcompanion ack --sid <sid> --event-id <id>`, then start the watcher again
   (the header pill goes back to `Watching`).

## Decisions and mockup parts (`decisions-mockup.blocks.json`)

| Step | What the page shows |
|---|---|
| Open card | chip `Easy to change later`; buttons `Go with Claude's suggestion`, `See other ways (2)`, `Write my own` |
| See other ways | `Hide the other way`, one `Pick this one instead` per other way |
| A pick | corner `Picked, not sent`; `Your pick: <label>`; `Not Claude's suggestion. Claude suggested "<label>".`; `Not sent yet. It goes to Claude when you press Submit round.`; button `Change my mind`; dock `Submit round (1)` |
| Mockup | its own title bar with a maximise icon; toggles and segment buttons inside the sandboxed iframe answer real clicks from the recorder (`page.frame_locator("iframe")`) |

With one decision, the part title and the question are the same words twice:
leave the part's `title` out or make it a different line.
