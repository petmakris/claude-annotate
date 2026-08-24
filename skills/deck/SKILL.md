---
name: deck
description: Use when the user wants to review or change a single-file HTML presentation deck in a browser — "open the deck", "let me comment on these slides", "show me the deck and let me steer it". Renders every slide, lets any element be commented on, and edits the .html in place. Not for building a deck from scratch and not for generic HTML editing.
argument-hint: "<path to a deck .html, or a folder containing one>"
allowed-tools:
  - Bash
  - Read
  - Edit
  - Grep
---

# /deck — comment on a rendered deck

The deck's `.html` is the document. The browser renders it; the user clicks any element and
comments; **you** edit the file. Nothing else writes it.

## Opening a deck

1. Resolve the deck file from the argument. A folder means the `.html` inside it with the same
   name as the folder.
2. Ensure the server is running, then create or attach a workspace. One block, because the
   guard has to run before the first `python3` call:

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
NAME, MARKER = "claude-annotate", "skills/deck/ensure_server.sh"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/deck/server.json")))["plugin_root"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit("could not locate the claude-annotate plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
"$PLUGIN_ROOT/skills/deck/ensure_server.sh"

SERVER_URL=$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/deck/server.json")))["url"])')
curl -sf -X POST "$SERVER_URL/api/sessions" -H 'Content-Type: application/json' \
  -d "$(printf '{"cwd": "%s", "title": "%s", "deck": "%s"}' "$PWD" "$DECK_NAME" "$DECK_PATH")"
```

3. Announce the `localhost_url`. **Do not append a query string to it** — the session router
   matches the path exactly and `?cb=1` returns 404.
4. Arm the watcher with `Monitor` (`persistent: true`), using the `sid`, `state_dir`,
   `events_dir` and `consumed_dir` from the response:

```bash
PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/deck/server.json")))["plugin_root"])')
SKILL=deck \
SID="<sid>" \
STATE_DIR="<state_dir>" \
EVENTS_DIR="<events_dir>" \
CONSUMED_DIR="<consumed_dir>" \
CLAUDE_SID="$CLAUDE_CODE_SESSION_ID" \
"$PLUGIN_ROOT/skills/_shared/web_companion/watcher.sh"
```

5. End the turn.

## Handling a comment

You wake on a `WEBCOMPANION_EVENT skill=deck` banner. The payload is one comment:

```json
{"type":"deck_comment","deck":"/abs/path/deck.html","slide":6,
 "path":".pro > p:nth-of-type(1)","ord":0,"component":"pro",
 "line_start":404,"line_end":405,
 "text":"Every proposal has to satisfy…","comment":"Open on the constraint."}
```

`ord` is the element's position among the ones on that slide sharing its path —
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

**Rules that are not negotiable:**

- **Never reserialise the file.** Change only the substring you mean. A parse-and-rewrite changes
  144 of 705 lines on a real deck and destroys `git diff` as a review surface.
- **Never touch the first `<style>` block or the `<script>` block.** They are the shared harness.
  New CSS goes in a new `<style>` block before `</head>`.
- **Never write `.pg` or renumber `.num`.** The harness does both at runtime.
- **Do not regenerate the PDF.** A stale `.pdf` beside an edited `.html` is not a defect.

After editing, confirm the deck still parses and the element you touched is still addressable:

```bash
curl -s "$SERVER_URL/s/<slug>/model" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["slides"]), "slides")'
```

The browser repaints on its own within a second of the file changing. Report what you changed.
Whether the new text still **fits** its slide is not checked in this phase — say so if an edit
made a block materially longer.

Finally write the ack and end the turn with no terminal output:

```bash
touch "<consumed_dir>/<event_id>.ack"
```

## One caution about sharing

Reads under `/s/<slug>/` are ungated by design — that is what makes a workspace
link shareable. For a deck that means anyone who can reach the port and knows the
slug can read the whole file. On loopback that is only you. If the server has been
bound beyond loopback, do not open a deck you would not hand over.

## What this skill does not do

- It does not create decks.
- It does not edit in the browser; the user comments, you write.
- It does not publish anywhere.
- It does not audit slide fit — that arrives with Phase 2.
