# Pushing a response to the annotation view

Read this when you are about to **push** a response to the browser — either
Forward mode (Mode A, a session is live and this response meets a routing
trigger in SKILL.md) or because the user typed `/annotate` (Mode B and the
live-session rule below).

The pipeline downstream of "ensure the server is running" is identical for all
modes — only the **content source** differs.

## Mode A — Forward (live-session routing)

An annotate session is live and this response meets a routing trigger (SKILL.md
routing decision). **Content source:**
compose the response as a list of blocks, each assigned a kind by the capability
check ("How to push a response" step 1 below), and write those to `blocks.json`.

## Mode B — Postmortem (user-invoked)

The user types `/annotate` after a response has already been delivered in
terminal. The explicit command is the only user-facing trigger — the word
"annotate" appearing in ordinary prose is not an invocation.

When invoked this way, treat the user's message as the trigger only — **do not** generate a fresh answer. Instead:

1. Take **your most recent prior assistant message from conversation context** as the content source. Do not consult transcript files; the conversation context is authoritative.
2. **Preserve the substance, re-compose the presentation.** Every claim, finding, number, name, and code block from the terminal answer appears on the page — add no new conclusions, drop nothing substantive. The terminal text was the draft rendering; the browser page is the finished one: run the same capability check as forward mode ("How to push a response" step 1), so a described interaction flow becomes a `sequence` block, branching logic a `flowchart`, a decision the user must make a `choice`, and prose no richer kind claims stays `markdown`.
3. Strip terminal-only artifacts: `assistant:` / system metadata wrappers if any, and any per-turn-hook trailer (e.g. a trailing absolute path a dump hook appended).
4. If your most recent prior assistant message is empty, trivial (a one-line acknowledgement), or contains only tool-call narration without standalone prose, do **not** push it. Instead, go live with nothing pushed (see "The live-session rule" below). Don't invent content; reply once in terminal so the user knows annotate is on.
5. Then follow the exact same flow as forward mode: `ensure_server.sh` → POST `/api/sessions` → write `meta.json` then `blocks.json` → announce the URL → **start the watcher** (see "Arming the watcher" below) → end your turn.

## The live-session rule — the browser is the output channel

An annotate session is **live** from the first `/annotate` (or `/annotate resume`) of the conversation: a push makes it live, and so does an invocation with nothing usable to push (the empty-prior case in Mode B — reply once in terminal, one line: *"Annotate is armed for this session — responses from now on will route through the browser. Say 'respond in terminal' to disarm."*).

While the session is live:

1. **Every response that meets any Mode A trigger goes to the browser**, and the bar is lowered — when in doubt, route. The state persists across turns because Claude reads its own prior push or arming line in conversation context.
2. The terminal carries only: the URL announcement, one-line status notes, and answers genuinely too small to annotate (single facts, yes/no, brief acknowledgements). If a reply you are drafting in terminal grows past that, it belongs on the page — compose it as blocks and push.
3. Disarm when the user says "respond in terminal", "stop annotating", or anything semantically equivalent. Acknowledge briefly and stop routing for the rest of the session.

**Token-budget note:** postmortem mode does not produce a new response. The only outputs in your terminal turn are short status lines (creating session, writing files, announcing URL). Keep terminal text minimal.

## On every invocation: ensure the server is running

The server is a long-lived singleton shared across all Claude Code sessions. Each turn, run this **once** before composing a response:

```bash
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '
import json, os, sys
NAME, MARKER = "claude-annotate", "skills/annotate/ensure_server.sh"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/annotate/server.json")))["plugin_root"]
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
sys.exit(f"could not locate the {NAME} plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
"$PLUGIN_ROOT/skills/annotate/ensure_server.sh"
```

`$CLAUDE_PLUGIN_ROOT` is **not** exported into the Bash tool's shell, so the root is resolved by probing, in order: every `bin/` directory on `PATH` (Claude Code adds `<plugin-root>/bin` for both `--plugin-dir` and marketplace installs, even when that directory does not exist), then a server this plugin already started, then the marketplace registry. Each candidate must actually contain `ensure_server.sh` — the check is a marker file, not a directory name, so it survives being cloned under any name. It's idempotent and fast (<100 ms when the server is already up). Internally it delegates to `skills/_shared/web_companion/ensure_server.sh` — no need to call that directly. Do **not** use `run_in_background: true` — wait for it to return. If it exits non-zero, surface the stderr to the user and stop.

## Create-or-attach a workspace for this conversation

Workspaces outlive a single push — they persist on disk for 7 days and survive
Claude exiting (see SKILL.md § Session lifecycle). So don't mint a fresh one on
every push: **create once per conversation, then attach on every push after
that**, so all of a conversation's pushes land in the same `blocks.json` at the
same URL.

After `ensure_server.sh` succeeds, read `$HOME/.claude/annotate/server.json` to get the server URL:

```bash
SERVER_URL=$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/annotate/server.json")))["url"])')
```

The workspace this conversation is using (if any) is tracked in the per-conversation
pending registry, `~/.claude/annotate/pending-${CLAUDE_CODE_SESSION_ID}.json` — the
same file "Arming the watcher" (below) appends a round entry to on every push. Each
entry carries a `workspace` key once one exists:

```bash
REG="$HOME/.claude/annotate/pending-${CLAUDE_CODE_SESSION_ID}.json"
WORKSPACE=$(python3 -c '
import json, sys
try:
    rounds = json.load(open(sys.argv[1]))
except (FileNotFoundError, json.JSONDecodeError):
    rounds = []
for r in reversed(rounds):
    w = r.get("workspace")
    if w:
        print(json.dumps(w))
        break
' "$REG")
```

### First push of this conversation (`$WORKSPACE` empty)

No prior push, and `/annotate resume` wasn't invoked (see `references/resuming.md`).
Create fresh — no `attach`:

```bash
curl -sf -X POST "$SERVER_URL/api/sessions" \
  -H 'Content-Type: application/json' \
  -d "$(printf '{"cwd": "%s", "title": "%s", "project": "%s"}' "$PWD" "$TITLE" "$(basename "$PWD")")"
```

`title` is this work's short title — the server slugifies it (deduping against
any live collision) into `slug`. Pass an explicit `"slug": "..."` too if you want
a specific short name instead of the auto-slugified title.

**Before creating**, check whether this project already has a live workspace and
offer to resume it instead of silently forking a second one — see
`references/resuming.md` § Auto-offer.

### Subsequent pushes in this conversation (`$WORKSPACE` non-empty)

Attach to the same workspace instead of creating a new one:

```bash
SLUG=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["slug"])' "$WORKSPACE")
curl -sf -X POST "$SERVER_URL/api/sessions" \
  -H 'Content-Type: application/json' \
  -d "$(printf '{"cwd": "%s", "title": "%s", "slug": "%s", "attach": true}' "$PWD" "$TITLE" "$SLUG")"
```

### Response shape (both calls)

```json
{"sid":"...","slug":"...","created":true,
 "url":"http://HOST:PORT/s/SLUG/",
 "localhost_url":"http://localhost:PORT/s/SLUG/",
 "owner_url":"http://HOST:PORT/s/SLUG/#k=TOKEN",
 "response_dir":"...","annotations_dir":"...","state_dir":"...",
 "events_dir":"...","consumed_dir":"..."}
```

The **create** call returns `created: true` with a fresh `sid`/`slug`/directories.
The **attach** call returns `created: false` with the **same** `sid` and
directories as the workspace's first push — `blocks.json` under that
`response_dir` is the same file every push in this conversation updates in
place, not a new one each time.

Save `sid`, `slug`, `url`, `localhost_url`, `response_dir`, `state_dir`,
`events_dir`, `consumed_dir` for the rest of this turn. Announce **the slug
URL** — the URLs are built from `slug`, not `sid` (`/s/<slug>/`), so that's
what the user should bookmark or type into `/annotate resume`. When two of
them are identical (no Tailscale host configured, `url` already on a loopback
host), announce just one. (`annotations_dir` is no longer used by the annotate
skill but is still returned by the server.)

**Three URLs, and they are not interchangeable.** Writes require either a
loopback connection or the capability token; reads never do.

| Field | Who it's for | Can it change the document? |
|-------|--------------|------------------------------|
| `localhost_url` | the user, on this machine | yes — loopback is the owner |
| `url` | **shareable** — a colleague on the LAN/Tailnet | no, read-only |
| `owner_url` | the user, from another of their devices | yes — carries the token |

Announce `localhost_url` first (browser features needing a secure context,
like voice dictation, only work there). Offer `url` when the user wants to
share, and say plainly that it is read-only.

**Never print `owner_url` unless the user asked to work from another device.**
It carries the write token; treat it like a credential, not like a link.

To resume a previously-closed conversation's workspace (`/annotate resume
<slug>`, or no arg to list candidates), see `references/resuming.md` — it sets
this same `workspace` marker so the push flow above attaches to it
automatically.

## How to push a response

1. **Split, then capability-check every block.** Split the response into logical units (a paragraph, a heading + its prose, one bullet, one code block; aim for 3-15 lines — small enough to read one at a time, large enough to carry a self-contained thought). Then walk the kind menu (SKILL.md § Block-kind menu) over each unit and assign the first kind whose trigger matches — `sequence`, `flowchart`, `diagram`, `choice`, or `mockup` — with `kind: "markdown"` as the fallback for units no richer kind claims. Before writing the files, re-scan a block list that came out all-markdown against the menu once: a response about interacting systems, branching logic, or a decision the user must make typically mixes kinds.
2. Write `meta.json` first (at `<response_dir>/meta.json`):
   ```json
   {"response_id": "resp-<unix-timestamp>",
    "title": "<short title>",
    "claude_session_id": "$CLAUDE_CODE_SESSION_ID"}
   ```
   Read `claude_session_id` from the `CLAUDE_CODE_SESSION_ID` env var (exposed to all Bash tool calls).
3. Then write `blocks.json` at `<response_dir>/blocks.json`:
   ```json
   {"response_id": "<same as meta>",
    "title": "<same as meta>",
    "blocks": [
      {"id": "section-1", "title": "<short header>", "markdown": "<first block's markdown>"},
      {"id": "section-2", "title": "<short header>", "markdown": "<second block's markdown>"},
      ...
    ]}
   ```
   Block ids are sequential `section-1`, `section-2`, `section-3`, ... starting from 1. Each block also carries a **`title`** — a 2-5 word header shown on the block's collapsible card (e.g. `"What happens when you comment"`). Keep it a noun phrase, not a sentence. If you omit it, the client derives a header from the block's first heading or sentence, but an authored title is almost always cleaner. **When you author a `title`, do not also repeat it as a leading `#`/`##` heading inside that block's markdown** — the card already shows the title, so a duplicate heading reads twice. **Do not write a `version` field** — the server derives per-block versions from a content-hash chain stored in a sibling `versions.json`. Any `version` field you write is stripped on save and ignored on read.

   For non-markdown blocks (`kind: "sequence"|"flowchart"|"diagram"|"choice"|"mockup"`), read the exact spec shape in `references/block-kinds/<kind>.md`.

4. Order matters: write `meta.json` before `blocks.json`, both atomically (write to `*.tmp` then `mv`).  The server reads both per request; an in-flight half-write falls back to the waiting page.
5. Tell the user, announcing **both** URLs (the loopback one first, since it's the one where voice dictation works):
   **"Response in browser → `<localhost_url>` (or `<url>` to open from another device).  Click any block to comment; the page updates that block in place when I respond."**
   If `localhost_url` and `url` are identical, announce just the one.
6. **Arm the watcher** (see "Arming the watcher").  The Monitor runs in the background; your turn ends immediately.  The user can chat in terminal while the page is open.
7. End your turn.

## Code blocks

Fenced code blocks are syntax-highlighted (highlight.js, Tokyo Night theme) and rendered as a dark card. **Tag the opening fence with the language** (```` ```python ````, ```` ```ts ````, ```` ```bash ````) for accurate coloring; an untagged fence is auto-detected, which is usually right but not guaranteed. Inline `` `code` `` stays a light chip — don't fence single identifiers.

## Inline HTML inside markdown blocks

A markdown block can contain raw HTML when prose isn't enough — comparison tables, callout boxes, dense tabular data, anything you'd otherwise contort markdown into. The renderer (`markdown-it`) is configured with `html: true`; after render, a conservative client-side sanitizer strips `<script>`, `<iframe>`, `<style>`, `<form>`, `on*` event-handler attributes, and `javascript:` URLs. Everything else passes through.

Two guidelines:

1. **Reuse the existing CSS variables.** `var(--accent)`, `var(--surface)`, `var(--surface-soft)`, `var(--border)`, `var(--text)`, `var(--text-strong)`, `var(--text-dim)`, `color-mix(...)` against them. Don't invent palettes — the page already has one. Inline `style="..."` is acceptable; a `<style>` block is not (the sanitizer strips it).

2. **Mark commentable sub-units with `data-annotate-id="<slug>"`.** The client uses this attribute to scope a click to a sub-unit of the block. Without it, clicks fall back to the whole block (`step_id: null`). Slugs are kebab-case, scoped within a single block — pick descriptive names (`verdict-row`, `auth-column`, `rate-limit-cell`), not positional indices. When you rewrite the block after a comment, **preserve `data-annotate-id` slugs on sub-units that still exist** so the rewrite contract round-trips cleanly.

Example:

```markdown
Three migration strategies considered:

<table class="weigh-up">
  <thead><tr><th></th>
    <th data-annotate-id="opt-bigbang">Big-bang</th>
    <th data-annotate-id="opt-incremental">Incremental</th>
  </tr></thead>
  <tbody>
    <tr><th>Risk</th>
      <td data-annotate-id="bigbang-risk">High — single window</td>
      <td data-annotate-id="incr-risk">Low</td>
    </tr>
  </tbody>
</table>
```

If the user clicks the `Incremental` header, the comment payload arrives with `step_id: "opt-incremental"`. Same rewrite contract as a diagram-step comment (`references/handling-events.md` § "Diagram block-rewrite contract"): fold the answer into the HTML — preserve surviving slugs, restructure freely otherwise.

For a **high-fidelity** mock that needs `<style>`/`<script>`/Tailwind, hover, or interaction, use `kind: "mockup"` instead — it renders in a sandboxed iframe with the sanitizer lifted. The `data-annotate-id` region convention above is unchanged. See `references/block-kinds/mockup.md`.

## Glossary (terminology surface)

`blocks.json` may include a sibling `glossary` array next to `blocks`:

```json
{
  "response_id": "...",
  "title": "...",
  "blocks": [...],
  "glossary": [
    {"term": "OnboardingOrchestrator",
     "definition": "Internal service coordinating new-user signup.",
     "role": "Upstream that emits the payload too early — the trigger of the bug."}
  ]
}
```

The client decorates matching terms in rendered block prose with a hover popover. Omit the field when no terms qualify.

### When to emit a glossary entry

While composing the blocks, ask yourself, for each project- or context-specific identifier that appears:

> If the reader didn't know this term, could they still follow this response?

Emit an entry **only when the answer is no**. Exclude any term that a competent engineer would resolve by Googling — `SQL`, `idempotent`, `mutex`, `hydration`, framework names, standard protocols, common patterns. Include identifiers that are unique to the user's project or that name a concept introduced by the current conversation.

Each entry has three fields:

- `term` — the exact string as it appears in the prose. Case-sensitive.
- `definition` — one line, generic (what this thing is).
- `role` — one line, contextual (what this thing does in *this specific response*).

The `role` field is what makes the glossary useful for debugging — it tells the reader why the term matters here, not just what it generically is.

(The glossary term-set diff applied **at rewrite time** lives in `references/handling-events.md` § "Glossary term-set diff at rewrite time".)

## Arming the watcher

After writing `meta.json` + `blocks.json` and announcing the URL, start a long-lived `Monitor` keyed to this session's directories.  Use `persistent: true` — the watcher lives for the whole session and emits one notification per submitted comment.

Invocation:

```bash
PLUGIN_ROOT=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.claude/annotate/server.json")))["plugin_root"])')
SKILL=annotate \
SID="<sid>" \
STATE_DIR="<state_dir>" \
EVENTS_DIR="<events_dir>" \
CONSUMED_DIR="<consumed_dir>" \
CLAUDE_SID="$CLAUDE_CODE_SESSION_ID" \
"$PLUGIN_ROOT/skills/_shared/web_companion/watcher.sh"
```

Substitute `<sid>`, `<state_dir>`, `<events_dir>`, `<consumed_dir>` from the session-create response (returned by `POST /api/sessions`). `CLAUDE_SID` is this Claude Code session's own id — read from the `CLAUDE_CODE_SESSION_ID` env var (exposed to all Bash tool calls, same one used for `meta.json`'s `claude_session_id` and the pending registry below). The watcher writes a per-session heartbeat file keyed by it (`state/watchers/<CLAUDE_SID>.hb`), which is how the server counts distinct live Claude sessions attached to one shared workspace. It's optional — an unset `CLAUDE_SID` doesn't break the watcher, it just isn't counted.

Pass this command as the `Monitor` tool's `command` with `persistent: true` and a short `description` like `"annotate-wait sid=<sid>"`.

The watcher emits these stdout banners:

- **`WEBCOMPANION_EVENT skill=annotate sid=<sid> event_id=<id>`** — one per submitted comment.  Followed by `---payload---`, the event JSON, and `---end---`.
- **`WEBCOMPANION_FINISHED skill=annotate sid=<sid>`** — when the user clicks Done.
- **`WEBCOMPANION_CANCELLED skill=annotate sid=<sid>`** — when the user cancels (terminal `scrap it`, etc.).

Each stdout line wakes you once.  The watcher stays alive across many events until the session terminates. When an event fires, follow `references/handling-events.md`.

After arming, also append a record to the pending registry so terminal-cancellation can find this session. This is also where the **workspace marker** used by "Create-or-attach a workspace" above gets written — pass the workspace's `sid` and `slug` (from the session-create/attach response) as `$SID`/`$SLUG`:

```bash
mkdir -p ~/.claude/annotate
REG="$HOME/.claude/annotate/pending-${CLAUDE_CODE_SESSION_ID}.json"
python3 - "$REG" "$SID" "$RID" "$TITLE" "$STATE_DIR" "$EVENTS_DIR" "$CONSUMED_DIR" "$SLUG" <<'PY'
import json, os, sys
path, sid, rid, title, state_dir, events_dir, consumed_dir, slug = sys.argv[1:]
try:
    data = json.load(open(path))
except FileNotFoundError:
    data = []
data.append({"sid": sid, "rid": rid, "title": title,
             "state_dir": state_dir, "events_dir": events_dir,
             "consumed_dir": consumed_dir,
             "workspace": {"sid": sid, "slug": slug}})
tmp = path + ".tmp"
json.dump(data, open(tmp, "w"), indent=2)
os.replace(tmp, path)
PY
```

`workspace` is a new key added to each round entry alongside the existing
`sid`/`rid`/`title`/`state_dir`/`events_dir`/`consumed_dir` fields — it doesn't
collide with them. `hooks/progress_publish.py` and `references/handling-events.md`
§ Terminal cancellation only ever read `state_dir`/`events_dir`/`consumed_dir`
off each entry, so the extra key is inert to both; "Create-or-attach a
workspace" above is the only reader of `workspace`, and it always looks at the
**last** entry with one set.

The registry persists across watchers within a single Claude Code session. It is *not* shared across sessions (keyed by `CLAUDE_CODE_SESSION_ID`).
