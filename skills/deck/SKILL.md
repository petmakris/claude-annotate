---
name: deck
description: Use when the user wants to review or change a single-file HTML presentation deck in a browser — "open the deck", "let me comment on these slides", "show me the deck and let me steer it". Renders every slide, lets any element be commented on, and edits the .html in place. When the deck does not exist yet — /deck with a new path, or with a topic instead of a path — it has the `slides` skill create it from the shared deck framework first, then opens it. Not for generic HTML editing. Triggered by /deck <path or topic>. Watcher events are WEBCOMPANION_EVENT / WEBCOMPANION_FINISHED / WEBCOMPANION_CANCELLED.
argument-hint: "<path to a deck .html, a folder containing one, or a topic for a new deck>"
allowed-tools:
  - Bash
  - Read
  - Edit
  - Grep
  - Monitor
---

# /deck — comment on a rendered deck

The deck's `.html` is the document. The browser renders it; the user clicks any element and
comments; **you** edit the file. Nothing else writes it.

## Opening a deck

0. **If there is no deck yet, create it first — never refuse.** People type `/deck` expecting a
   deck to appear, and a skill that answers "I only open existing decks" sends them away empty-
   handed. The deck is missing when the argument is a path that does not exist, or when it is a
   topic rather than a path (`/deck proposal for feedback tracking`).

   Creating is not this skill's job to do by hand: a deck must carry the shared framework
   (canvas, present mode, theme tokens), follow the decks folder's naming and house style, and
   pass a layout audit — all of which the **`slides` skill** in this plugin (Job 1) owns.
   Invoke it with the topic, or with the missing path's folder name as the slug, let it write and
   audit the deck, then come back here with the `.html` it created as the argument and carry on
   from step 1. Its house-style read counts as step 2's — say so rather than reading twice.

   If no `slides` skill is available in this session, say that in one line and stop. Do not
   hand-write a deck without the framework: it renders unstyled and cannot be exported.

1. Resolve the deck file from the argument, and set `DECK_PATH`/`DECK_NAME` — every later step in
   this skill uses both. A folder means the `.html` inside it with the same name as the folder.

```bash
ARG="<the argument exactly as given after /deck>"
if [ -d "$ARG" ]; then
  DECK_PATH="$(cd "$ARG" && pwd)/$(basename "$ARG").html"
else
  DECK_PATH="$(cd "$(dirname "$ARG")" && pwd)/$(basename "$ARG")"
fi
DECK_NAME="$(basename "$DECK_PATH" .html)"
echo "DECK_PATH=$DECK_PATH"; echo "DECK_NAME=$DECK_NAME"
```

   Shell variables do not survive between Bash tool calls. Every later block that uses
   `$DECK_PATH` or `$DECK_NAME` starts by setting them again from the two lines this one printed.

2. **Load the house style before anything else, and say out loud that you did.** A deck belongs
   to somebody who has already decided how their decks read — how long a slide may be, which
   words they refuse, what goes on a slide at all versus what they say over a live demo. Opening
   a deck without that is how you spend a session re-learning it one comment at a time.

   The decks folder is the deck's grandparent directory (`$DECKS/<deck-folder>/<deck>.html`).
   Read whichever of these exist, in this order — later files add to earlier ones, never replace
   them:

   ```bash
   DECKS="$(cd "$(dirname "$DECK_PATH")/.." && pwd)"
   for f in "$DECKS/PRESENTATION-STYLE.md" "$DECKS/README.md"; do
     [ -f "$f" ] && echo "=== $f ===" && cat "$f"
   done
   ls "$DECKS/playbooks" 2>/dev/null
   ```

   If `$DECKS/playbooks/` exists, it holds one folder per recurring meeting. Read the one whose
   slug matches this deck — a `2026.05.14-Board-Update` deck reads `playbooks/board-update/`. Read
   every file in it. The style file governs length, wording and density; the playbook governs
   structure and running order.

   If the deck's `theme:css snapshot of '<name>'` comment names a theme that has a
   `README.md` in `~/.config/slides/themes/<name>/`, read that too: it documents the
   components that theme adds.

   Then, in the same turn, tell the user in **two or three lines** what you loaded and the two or
   three constraints you will be holding to. Not a summary of the file — the specific limits that
   will bind the next edit, so they can correct you before you make one.

   If no style file exists, say so plainly in one line and carry on. Do not invent house rules,
   and do not go looking for them in other repositories.

3. **The daemon must be running.** deck no longer ships its own server — storage, the event
   queue and the page itself all belong to the **webcompanion daemon**, one always-on service
   per machine, shared with every other skill and IDE plugin that talks to it. Confirm it is up
   before doing anything else:

```bash
webcompanion status
```

   If that fails, stop and tell the user — do **not** try to start it yourself (a client that
   auto-starts a service races every other client doing the same):

```
webcompanion doctor      # both interpreters, config, zipapp, launchd job, health
```

   If `webcompanion` is not on PATH at all, the daemon has never been installed on this machine:

```
pipx install webcompanion && webcompanion install-service
```

   `skills.deck.push` runs out of the plugin's own tree, and `$CLAUDE_PLUGIN_ROOT` is **not**
   exported into the Bash tool's shell. Reach it through `claude-annotate`, the plugin's runner:
   Claude Code puts the plugin's `bin/` on `PATH`, the runner finds the plugin root from its own
   location, and on a machine with no python3 it prints a sentence naming the plugin and the fix
   instead of a traceback.

   Then push the deck and keep it pushed. `--watch` does the first push, prints its JSON, and
   then stays running, re-pushing every time the file changes on disk — whoever changed it, you
   with the Edit tool, a script, or the user in their editor — until the session ends. Run it
   with the Bash tool's `run_in_background: true`:

```bash
claude-annotate deck.push \
  --deck "$DECK_PATH" --cwd "$PWD" --title "$DECK_NAME" --watch
```

   Read the JSON from the background task's output: `sid`, `slug`, `kind`, `url`. Save `sid` —
   you need it to arm the event watcher and to ack.

   **One deck, one URL.** A push without `--slug` attaches to the live session already showing
   this deck file, so running it again (a new conversation, a restarted watcher) keeps the URL
   the user has open. Never pass the id out of the URL as a way to "stay on the same session" —
   there is no need, and before this was fixed it created a new session on every push.

4. Announce the `url`.
5. Arm the watcher with `Monitor` (`persistent: true`), using the `sid` from the push response:

```bash
webcompanion watch --kind deck --sid "<sid>"
```

   Pass that as the `Monitor` tool's `command`, with a `description` like `"deck-wait sid=<sid>"`.

6. End the turn.

## Handling a comment

When a task-notification's first stdout line is
`WEBCOMPANION_EVENT skill=deck sid=<sid> event_id=<id>`, **`Read`
`references/handling-comments.md` and follow it** before touching the file. It
covers the envelope's three scopes, reading the line range raw, grounding a
product term before rewording it, the house-style rules every edit is held to
(and the ones that are not negotiable: never reserialise the file, never touch
the shared harness), re-pushing, reporting the change and acking.

## One caution about sharing

Reads under `/s/<slug>/` are ungated by design — that is what makes a workspace
link shareable. For a deck that means anyone who can reach the daemon's port and knows the
slug can read the whole file. On loopback that is only you. If the daemon has been
bound beyond loopback, do not open a deck you would not hand over.

## What this skill does not do

- It does not create decks itself. A missing deck is created by the `slides` skill (step 0), then opened here.
- It does not edit in the browser; the user comments, you write.
- It does not publish anywhere.
- It does not fix what its badges report on its own; the user comments, you fix.

## What the page offers the user

- Two views, switched by the two icons in the header: **Scroll** (every slide in one column,
  each with its label row) and **Slide** (one slide at a time, filling everything between a 32px
  header and a 38px bottom strip; the strip carries ‹ numbered slide chips whose dots mirror each
  slide's check badges ›, and the current slide's badges, reveal steps, comment and ▶). ← → move;
  the URL's `#slide-N` keeps the place.
- A header with **Deck** (comment on the whole deck) and **Present** (the real deck, scripts
  running, in a sandboxed tab).
- On every slide label: the check badges, a **reveal** scrubber when the slide has `.frag`
  steps (0 … n, or all — purple numbers on the slide show each element's step), a **comment**
  button for the whole slide, and **▶** to present from that slide (decks on framework 2.1+).
