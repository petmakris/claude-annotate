---
name: draw
description: One drawing pad at a link that never changes, for sketching on a tablet while talking to this session. The user types "/draw" to make this session the pad's owner; each Update on the pad then arrives here as an event with the drawing. Also use when a task-notification's first line is `WEBCOMPANION_EVENT skill=draw` or `DRAW_SUPERSEDED`.
disable-model-invocation: true
allowed-tools:
  - Bash
  - Read
  - Monitor
---

# /draw: the drawing pad

`$SKILL_DIR` is this skill's base directory. Every command is
`python3 "$SKILL_DIR/draw.py" <command>`, written `D <command>` here; always type the full form.

The pad is one page at one link. It shows the drawing pad and nothing else: no answers, no
text. The user draws and taps **Update**, which sends the drawing as it is now to the Claude
session that last ran `/draw`. **Pictures** beside Update adds photos (the camera or the
library); they wait as thumbnails and go with the next Update only. The pad goes full screen
after the first line (no browser bars, no Android status bar or navigation buttons), and
**Full screen** beside it enters and leaves it. The pad saves the lines as they are drawn, so a reload or
another device opens the same drawing. **Answer in the terminal**; the pad never shows replies.

## /draw: take the pad

1. `D claim --session "$CLAUDE_CODE_SESSION_ID"`. It prints `{sid, url, previous, dropped_updates}`.
   Another session that held the pad loses it: its watch ends with `DRAW_SUPERSEDED`.
2. Arm the watch with the `Monitor` tool (load it with `ToolSearch` `select:Monitor` when it is
   deferred): command `python3 "$SKILL_DIR/draw.py" watch --session "$CLAUDE_CODE_SESSION_ID"`
   with the session id written out literally, description `draw-wait`, `timeout_ms` 1800000.
3. Tell the user, in one line: the pad is theirs at `<url>`.

When the monitor expires, arm it again, unless the user said they are done or it ended with
`DRAW_SUPERSEDED`.

## An Update arrives

The notification's first line is `WEBCOMPANION_EVENT skill=draw sid=<sid> event_id=<id>`.

1. `D event --event-id <id>` prints `{image, images, at}`. `Read` every path in `images`: the
   first is the drawing, the rest are pictures the user added to it, in the order added.
2. Answer in the terminal about the drawing, in the light of what the user is talking about.
   If several Updates arrived together, read only the newest: each one is the whole drawing.
3. Acknowledge every one: `webcompanion ack --sid <sid> --event-id <id>`. Without the ack the
   daemon sends the Update again every 30 minutes.

When the user asks about the drawing without having tapped Update ("what did I draw?"),
`D latest` gives the newest drawing sent. Say how old it is (`at`), and that a newer one needs
Update.

## DRAW_SUPERSEDED

Another Claude session ran `/draw` and has the pad now. Say so in one line and do not re-arm.
