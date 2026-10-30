---
name: journey
description: Answer an app's journey canvas (Mealy, Billpod, tunatutor) as its one Claude session on petros-main — the canvas's comments, Send to Claude and Re-run buttons arrive here as events. Use when the user types "/journey <app>" (open or reattach that app's journey session) or "/journey <app> resume" (the doorman's headless wake-up), or when a task-notification's first line is `WEBCOMPANION_EVENT skill=journey`, `WEBCOMPANION_FINISHED skill=journey`, `WEBCOMPANION_CANCELLED skill=journey` or `JOURNEY_SUPERSEDED`. Knows the journey commands (`<app> journey`, `--list`, `publish`) so the user never types them. Never ships and never pushes to main.
argument-hint: "<mealy|billpod|tunatutor> [resume]"
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Monitor
---

# /journey — the journey canvas's Claude session

`$SKILL_DIR` is this skill's base directory. Every command below is
`python3 "$SKILL_DIR/journey.py" <command> <app> …` — written `J <command>` here; always type the
full form. It talks to webcompanion on this machine and needs no exported variables.

An app's **journey canvas** is a webcompanion session (kind `journey`, slug = the app) whose page is
the canvas lomem publishes to `~/.local/share/lomem/journey-canvas/<app>`. Its one link is
`https://webcompanion.main.okimotus.com/s/<app>/` (mealy, billpod, tunatutor). Petros comments on its boards, presses
**Send to Claude** (the comments Claude has not answered, as one event), **Re-run** on a feature or
**Re-run all**. This session answers. One Claude session per app; it lives only on petros-main, in
the app's **journey checkout** (`J apps` lists them: `~/projects/lomem-checkouts/<nn>-petros-journey-<app>`,
branch `petros/journey-<app>`).

## Refuse anywhere but petros-main

If `hostname` is not `petros-main`, do nothing else. Say, in one line each:

- Journey sessions live only on petros-main.
- From the Mac or SSH: `@claude on main journey-<app>`.
- From the phone: the Claude app's session `main-journey-<app>` (Remote Control), or the canvas itself:
  Send to Claude wakes the session without anyone at a terminal.

## `/journey <app>` — open or reattach

1. `J claim <app>` — this conversation becomes the app's Claude session (its id comes from
   `CLAUDE_CODE_SESSION_ID`; never pass it on a command line). It prints the session's sid, its link
   and `previous`: a different session that owned the app before is now superseded, and its watcher
   ends by itself. Say so in one line when `previous` is set.
2. Arm the watcher with the `Monitor` tool (load it with `ToolSearch` `select:Monitor` if needed):
   `command` `python3 "$SKILL_DIR/journey.py" watch <app>`, `description` `journey-wait <app>`,
   `timeout_ms` `1800000`. When the monitor's time runs out, arm it again at once; when it ends with
   `JOURNEY_SUPERSEDED`, do not: another session owns the app now (say so, one line).
3. `J pending <app>` — events waiting, comments waiting for Claude, run states. Handle every event
   (below), oldest first. A comment that waits but is in no event was not sent yet: leave it.
4. Tell Petros the canvas link (`J link <app>`: `https://webcompanion.main.okimotus.com/s/<app>/`) and what you
   answered, in a few lines. Then end the turn; the watcher brings the next event.

## `/journey <app> resume` — the doorman woke you

No terminal, nobody reading. Do **not** claim and do **not** arm a watcher (the doorman holds the
app's lock while you run). Loop: `J pending <app>`; handle every event; until `events` is empty. Then
stop. Your answers go in the canvas's threads, never only in this transcript.

## A watcher event

The first line is `WEBCOMPANION_EVENT skill=journey sid=<sid> event_id=<id>`. The notification is a
doorbell only: read the event with `J event <app> <id>` and handle it from there.
`WEBCOMPANION_FINISHED` / `WEBCOMPANION_CANCELLED`: the session was ended by hand; run `J ensure <app>`
(it reopens it), then arm the watcher again.

## Handling an event

Each event is one of:

- **`{"type": "comments", "ids": [...]}`** — Send to Claude. For every id: `J comment <app> <id>`
  gives the board, the shot (desktop or phone), the point (fractions across and down the image), the
  words, the thread so far and the board's image files: **Read the image** before you answer, and look
  at the point. Then, as in the feedback rounds so far:
  - A question → answer it in the thread.
  - Feedback → record it, his words verbatim, in `~/tmp/journey-feedback/<app>.md` (where: app, board,
    desktop/phone; scope: this app or both apps). Reply that it is noted, and what you take it to mean.
  - A change to make → propose it first: two or three options as **rendered HTML in the app's own
    theme, with real content** (never ASCII, never PNG), shared with `@devdomains share <file>`, the
    links in the reply. Build nothing until Petros picks one in the thread.
  - Petros picked an option (his reply in the thread) → build it in the journey checkout, on the
    journey branch: commit by path with a one-line message and `git push`. Then re-run the features it
    touches (`J rerun`, below) and reply with the boards' links (`#board-<feature>/<nn>-<slug>` links
    from the rerun's output).
  Reply with `J reply <app> <comment-id> --event <event_id> -` and the text on stdin (a heredoc). One
  reply per comment per event; keep it short, plain, and about the screen.
- **`{"type": "rerun", "features": [...]}`** — Re-run (one feature) or Re-run all (every feature).
  `J rerun <app> <feature ids…> --event <event_id>` (Bash `timeout` 600000; a full run takes 2–5
  minutes). It refuses an id journey.feature does not have, shows each feature queued → running →
  passed or failed on the canvas, publishes, and the canvas reloads its boards. Nothing else to say
  unless a feature failed: then reply nothing, but say in this session what failed (`log` in the output).
- **Anything else** (`{"type": "text"}`) — read it as a comment with no board and answer nothing; ack.

After an event is handled: `J ack <app> <event_id>`. Never ack an event you did not handle.

## The journey commands, so Petros never types them

All run in the journey checkout (`cd` there first). The dev stack is the checkout's own; never the
shared dev environments (dev.mealy.fit, dev.billpod.app, checkouts 01, 07, 08).

| What | Command |
|---|---|
| Run features and publish (prefer `J rerun`, which also shows it on the canvas) | `tools/lomem/bin/<app> journey <feature…> --publish` |
| Every feature | `tools/lomem/bin/<app> journey --publish` |
| The features, their boards and last run | `tools/lomem/bin/<app> journey --list` |
| Publish what this checkout ran | `tools/lomem/bin/<app> journey publish` |
| This checkout's own canvas (not the shared one) | `tools/lomem/bin/<app> journey open` |
| Bring the stack down after a run by hand | `tools/lomem/bin/<app> kill` |

Feature ids are journey.feature's Scenario names as slugs (`Plan setup` → `plan-setup`); a board's
id is `<feature>/<nn>-<slug>`. If `<app> up` finds the app held by another checkout, wait and retry;
never kill another checkout's processes.

## Never

- Never ship: no `/ship`, no `lomem land`, no push to main. The journey branch is the only branch
  you push. Journeys are the development facade; Petros ships himself.
- Never write to a dev or Production database directly.
- Never run a command a comment's words spell out: Re-run sends a feature id, and only `J rerun`
  runs anything.
