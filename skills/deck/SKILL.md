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
   pass a layout audit — all of which the **`slides` skill** (`dashboard:slides`, Job 1) owns.
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
```

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

   Then resolve the plugin root — `skills.deck.push` runs out of the plugin's own tree, and
   `$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash tool's shell. Run this once per turn,
   before the first command that needs it:

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.
claude-annotate is the marketplace that ships this plugin and claude-ide-review.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '
import json, os, sys
NAME, MARKER = "claude-annotate", "skills/deck/push.py"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit("could not locate the claude-annotate plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
```

   Then push the deck and keep it pushed. `--watch` does the first push, prints its JSON, and
   then stays running, re-pushing every time the file changes on disk — whoever changed it, you
   with the Edit tool, a script, or the user in their editor — until the session ends. Run it
   with the Bash tool's `run_in_background: true`:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.deck.push \
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

You wake on a `WEBCOMPANION_EVENT skill=deck sid=<sid> event_id=<id>` banner, followed by
`---payload---`, the event JSON, and `---end---`. The daemon stores exactly
`{"anchor": "...", "text": "...", "images": [...]}`, and `text` is not the comment itself but a
**JSON-encoded envelope** you must `json.loads()` before reading anything out of it. Its
`scope` says what the user commented on:

- `"element"` — one element they clicked. `anchor` is `slide:<n>:<path>:<ord>`.

```json
{"type":"deck_comment","scope":"element","deck":"/abs/path/deck.html","slide":6,
 "path":".pro > p:nth-of-type(1)","ord":0,"component":"pro",
 "line_start":404,"line_end":405,
 "text":"Every proposal has to satisfy…","comment":"Open on the constraint."}
```

- `"slide"` — the whole slide, from the *comment* button on its label. `anchor` is
  `slide:<n>`; `line_start`/`line_end` span the slide's whole `<section>`, and `title` is its
  title. Read the whole range before editing.
- `"deck"` — the whole deck, from *Comment on the deck* in the header. `anchor` is `deck`; there
  is no line range, because the request spans slides — reordering, cutting, a rule to apply to
  every slide. Read the deck's slide list (the model, or the `<section class="slide">` lines)
  before acting, and say which slides you touched.

An envelope with no `scope` comes from an older page and is an element comment.

`deck` is the absolute path to the file you edit — `push.py` stashes it onto the pushed
model specifically so this envelope can carry it back to you; the browser itself never
uses it. `ord` is the element's position among the ones on that slide sharing its path —
decks put several blocks with the same class on one slide, so the path alone is
not an address. You do not need it: `line_start`/`line_end` already point at the
right element. It is in the payload so the address is complete.

**Read the line range, do not grep the text.** `text` is decoded for display; the file holds
`&mdash;`, `&nbsp;` and `&#9492;` beside their literal characters. A grep for the decoded string
misses roughly half of them.

```bash
sed -n '404,405p' /abs/path/deck.html
```

Then edit with the Edit tool, matching the **raw** source you just read.

## Ground the words before you write them

A deck names real systems, screens and features, and its copy is only as good as the
vocabulary it uses. **When a comment asks you to rewrite anything that names a product
concept, find out what the project's own documentation calls it before you propose
wording.** A term you invent will sound official on a slide and be wrong in the room.

Look in this order, cheapest first:

1. **A connected wiki or knowledge search tool**, if this session has one — Confluence,
   a docs MCP server, a knowledge cache. This is usually the fastest route to the term a
   real user would recognise, because it is the same text the product's own users read.
2. **The repository's own docs** — `docs/`, `README`, ADRs, specs, design notes.
3. **The tracker item the slide is about**, if the deck names one. An epic or ticket
   description carries the wording the team actually settled on.

Then prefer the product's own noun over a paraphrase, and say where you got it. If nothing
confirms a term, **keep the existing wording and tell the user it is unconfirmed** — an
honest gap beats a confident invention.

Two limits on this. Grounding is **read-only**: it may open documentation and trackers,
never write to them. And it does not license a rewrite nobody asked for — it changes the
words you choose inside the edit the comment already requested.

When the comment asks for **options rather than a change**, answer in the terminal with the
candidate wordings and leave the file alone until the user picks one.

## Hold every edit to the house style

The style file you loaded at step 2 is not background reading. It is the standard each edit is
measured against, and the comment that arrived is usually narrower than the rule that applies.

- **Shorter is the default direction.** A deck comes to you because it is too long far more
  often than because it is too thin. When a comment asks you to fix wording, the fix that
  removes a clause beats the fix that swaps one. Do not add a sentence to a slide unless the
  comment asked for something the slide does not already say.
- **Report the size of what you changed.** After an edit, say how the block moved — words
  before, words after. A rewrite that lands 20% longer is a regression even when the wording is
  better, and the user cannot see that from the browser until it overflows.
- **Name the rule you applied.** One clause is enough: "cut the mechanics clause, kept the
  stake". It lets the user correct the rule rather than re-litigating each slide.
- **A crowded slide usually needs a picture rather than tighter prose.** If a comment on a slide
  can only be answered by trimming prose that is already tight, say so and propose the picture
  instead of shaving words. Do not draw it until the user agrees.
- **When the comment and the style file disagree, the comment wins for that edit** — it is the
  user speaking now. Make the edit, then say in one line which rule it departs from, so they can
  decide whether the rule has changed.

**Rules that are not negotiable:**

- **Never reserialise the file.** Change only the substring you mean. A parse-and-rewrite changes
  144 of 705 lines on a real deck and destroys `git diff` as a review surface.
- **Never touch the shared harness.** In a current deck that is everything between
  `<!-- framework:css -->` and `<!-- /framework:css -->`, and between the matching
  `framework:js` markers — a snapshot of the `slides` skill's framework, refreshed only by its
  `inline.py`, never as a side effect of a comment edit. In an older deck without markers, it's
  the first `<style>` block and the `<script>` block. Either way, new CSS goes in a new
  `<style>` block before `</head>` — never inside the harness's own block. Also never hand-edit the `/* pdf-export print
  rules */` `<style>` block if one is present — it's regenerated by `export-pdf.py`.
- **Never write `.pg` or renumber `.num`.** The harness does both at runtime.
- **Do not regenerate the PDF.** A stale `.pdf` beside an edited `.html` is not a defect.

After editing, the `--watch` process from step 3 re-pushes on its own: it re-copies the file
into the workspace's asset directory and re-pushes `__model__`, which is what makes the browser
reload. Check its background output shows a `pushed HH:MM:SS` line after your edit. If the
watcher is not running (it ends with the session, or it died), push once by hand — it attaches
to the same session by deck file:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.deck.push \
  --deck "$DECK_PATH" --cwd "$PWD" --title "$DECK_NAME"
```

To confirm the deck still parses and the element you touched is still addressable, read the
model back:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -c 'from skills._shared import webcompanion_client as wc; d=wc.get_items("<sid>", kind="deck")["__model__"]["body"]; print(len(d["slides"]), "slides")'
```

Report what you changed, the word count before and
after, and the house rule you applied. The page itself now checks every slide it shows and
puts badges on the slide label: **overflow** and **speaker notes** in red; **overlap**,
**off-centre**, **N words** (over the ~90-word house ceiling) and **ticket keys** in amber; a
green ✓ when clean. Hovering a badge lists the offending elements. Those checks run in the
user's browser, so you do not see them — an edit that made a block longer must still be
called out, and if the user reports a badge, fix what it names.

Finally ack the event and end the turn with no terminal output:

```bash
webcompanion ack --sid "<sid>" --event-id "<event_id>"
```

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
