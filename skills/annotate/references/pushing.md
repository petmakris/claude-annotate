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
5. Then follow the exact same flow as forward mode: confirm the daemon → write `blocks.json` → `python3 -m skills.annotate.push` → announce the URL → **start the watcher** (see "Arming the watcher" below) → end your turn.

## The live-session rule — the browser is the output channel

An annotate session is **live** from the first `/annotate` (or `/annotate resume`) of the conversation: a push makes it live, and so does an invocation with nothing usable to push (the empty-prior case in Mode B — reply once in terminal, one line: *"Annotate is armed for this session — responses from now on will route through the browser. Say 'respond in terminal' to disarm."*).

While the session is live:

1. **Every response that meets any Mode A trigger goes to the browser**, and the bar is lowered — when in doubt, route. The state persists across turns because Claude reads its own prior push or arming line in conversation context.
2. The terminal carries only: the URL announcement, one-line status notes, and answers genuinely too small to annotate (single facts, yes/no, brief acknowledgements). If a reply you are drafting in terminal grows past that, it belongs on the page — compose it as blocks and push.
3. Disarm when the user says "respond in terminal", "stop annotating", or anything semantically equivalent. Acknowledge briefly and stop routing for the rest of the session.

**Token-budget note:** postmortem mode does not produce a new response. The only outputs in your terminal turn are short status lines (creating session, writing files, announcing URL). Keep terminal text minimal.

## On every invocation: the daemon must be running

annotate no longer ships a server. Storage, comment threads, the event queue
and the page itself all belong to the **webcompanion daemon** — one always-on
service per machine, shared with every other skill and IDE plugin that talks
to it. It is installed and kept alive by launchd (macOS) or systemd (Linux),
so there is nothing to start per session and no port to negotiate.

Confirm it is up before composing anything:

```bash
webcompanion status
```

If that fails, stop and tell the user — do **not** try to start it yourself
(a client that auto-starts a service races every other client doing the same):

```
webcompanion doctor      # both interpreters, config, zipapp, launchd job, health
```

If `webcompanion` is not on PATH at all, the daemon has never been installed
on this machine:

```
pipx install webcompanion && webcompanion install-service
```

## Push the document

Write `blocks.json` (the authoring format described in "How to push a
response" below) to any path you like — your scratchpad is the natural home,
since it is no longer a file a server reads, only an input to the push:

```bash
cd "$PLUGIN_ROOT" && PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.annotate.push \
  --blocks <path/to/blocks.json> \
  --cwd "$PWD" \
  --title "<short title>" \
  --eval
```

`--eval` prints three lines to consume with `eval`:

```
WC_SID=<session id>       # what `webcompanion ack` and `webcompanion watch` take
WC_SLUG=<short name>      # what the URL is built from, and what `/annotate resume` takes
WC_URL=<localhost url>    # what you announce
```

**First push of a conversation**: omit `--slug`; a session is created and its
slug derived from the title. **Every push after that**: pass
`--slug "$WC_SLUG"` so the push lands on the page the user already has open
instead of minting a second URL beside it.

The push does four things in one step, all of which used to be yours to
orchestrate: it renders every diagram block to SVG (the daemon stores items
opaquely and renders nothing, so this happens once, here, at push time), it
replaces the stored document wholesale, it keeps a snapshot of what the
document said beforehand so the "what changed" pane has something to diff
against, and it registers annotate's own page as the session's renderer.

Code anchors are the deliberate exception: they are pushed **unresolved**,
because the daemon re-resolves them on every read. An anchor therefore keeps
tracking its line as the file changes underneath a page that stays open —
which is the whole reason the `snippet` field exists.

### The URLs

Three of them, and they are not interchangeable. Writes require either a
loopback connection or the capability token; reads never do.

| Field | Who it's for | Can it change the document? |
|-------|--------------|------------------------------|
| `localhost_url` (`WC_URL`) | the user, on this machine | yes — loopback is the owner |
| `url` | **shareable** — a colleague on the LAN/Tailnet | no, read-only |
| `owner_url` | the user, from another of their devices | yes — carries the token |

Announce `WC_URL` first (browser features needing a secure context, like voice
dictation, only work there). Offer `url` when the user wants to share, and say
plainly that it is read-only.

**Never print `owner_url` unless the user asked to work from another device.**
It carries the write token; treat it like a credential, not like a link.

## Verbosity mode — the composition contract

The mode (resolved by SKILL.md § Verbosity mode: argument > user's words >
default `compact`) decides how much of the response renders as blocks. It never
changes what you concluded — in compact mode the full findings stay in
conversation context, ready to be folded into a block when a comment asks.

### `compact` (default) — the page IS this shape

At most **5 blocks**, a ~2-minute read:

1. **Triage block** — titled like "The only N things that need you" (N ≤ 4):
   the decisions, blockers, and questions that require the reader's judgment,
   one short item each, every item a `data-annotate-id` sub-unit.
2. **Digest block** — everything else, **one line per item**, each line a
   commentable `data-annotate-id` row. A row is a claim plus its consequence,
   not a summary of a section.
3. **"What you do NOT need to re-check" block** (only when you verified work) —
   ≤ 4 bullets naming what was already confirmed, so the reader can skip it
   with confidence.
4. **A `choice` block** when the response ends in a decision the user makes.

Diagrams, per-finding code quotes, and long evidence are **not** rendered in
compact mode — they surface later, one block at a time, via the expand path
below. Glossary entries still apply.

**Expanding on demand:** a comment on a triage item or digest row is a request
for that item's full detail. Answer it by rewriting *that block* (or appending
one block for the item) with the full evidence — quoted code, failure scenario,
fix — per `references/handling-events.md`. Never re-render the whole page to
detailed because one row was asked about.

### `detailed` — full composition

The response renders block-per-point exactly as "How to push a response" below
describes: every finding its own block, diagrams where a kind claims them,
evidence and code quotes inline. Use only when the mode resolved to `detailed`.

## How to push a response

1. **Split, then capability-check every block.** (In `compact` mode the block list is the compact contract in § Verbosity mode above — the kind menu still applies to the blocks it produces.) Split the response into logical units (a paragraph, a heading + its prose, one bullet, one code block; aim for 3-15 lines — small enough to read one at a time, large enough to carry a self-contained thought). Then walk the kind menu (SKILL.md § Block-kind menu) over each unit and assign the first kind whose trigger matches — `sequence`, `flowchart`, `diagram`, `choice`, or `mockup` — with `kind: "markdown"` as the fallback for units no richer kind claims. Before writing the files, re-scan a block list that came out all-markdown against the menu once: a response about interacting systems, branching logic, or a decision the user must make typically mixes kinds. **Independent of kind, also decide each block's `code` anchors** — see `references/code-anchors.md`.
2. Write `blocks.json` anywhere convenient (your scratchpad). It is an input to
   the push, not a file a server reads, so its location no longer matters:
   ```json
   {"response_id": "resp-<unix-timestamp>",
    "title": "<short title>",
    "blocks": [
      {"id": "section-1", "title": "<short header>", "markdown": "<first block's markdown>"},
      {"id": "section-2", "title": "<short header>", "markdown": "<second block's markdown>"},
      ...
    ]}
   ```
   Block ids are sequential `section-1`, `section-2`, ... from 1. Each block also carries a **`title`** — a 2-5 word header shown on the block's collapsible card (e.g. `"What happens when you comment"`). Keep it a noun phrase, not a sentence. If you omit it, the client derives a header from the block's first heading or sentence, but an authored title is almost always cleaner. **When you author a `title`, do not also repeat it as a leading `#`/`##` heading inside that block's markdown** — the card already shows the title, so a duplicate heading reads twice. **Do not write a `version` field** — the daemon derives every item's version from its content hash, so a version you write is a second source of truth that will disagree.

   For non-markdown blocks (`kind: "sequence"|"flowchart"|"diagram"|"choice"|"mockup"`), read the exact spec shape in `references/block-kinds/<kind>.md`.

3. **Check the anchors** before pushing:

   ```bash
   cd "$PLUGIN_ROOT" && PYTHONPATH="$PLUGIN_ROOT" \
     python3 -m skills.annotate.check_anchors "<path/to/blocks.json>" "$PWD"
   ```

   Exit 0 means every anchor resolves. Non-zero prints one problem per line
   naming the block and the anchor — fix `blocks.json` and re-run. A broken
   anchor caught here costs a rewrite; the same anchor caught by the reader
   costs their trust in every other citation on the page.

4. **Push it** with the command in "Push the document" above, and capture
   `WC_SID` / `WC_SLUG` / `WC_URL`.

5. Tell the user, announcing **both** URLs (the loopback one first, since it's the one where voice dictation works):
   **"Response in browser → `<localhost_url>` (or `<url>` to open from another device).  Click any block to comment; the page updates that block in place when I respond."**
   If `localhost_url` and `url` are identical, announce just the one.
6. **Arm the watcher** (see "Arming the watcher").  The Monitor runs in the background; your turn ends immediately.  The user can chat in terminal while the page is open.
7. End your turn.

## Code anchors

A block that asserts something about specific code carries a `code` anchor
to it — see `references/code-anchors.md` for the field shape, the limits,
and the check (step 4b above).

## Code blocks

Fenced code blocks are syntax-highlighted (highlight.js, Tokyo Night theme) and rendered as a dark card. **Tag the opening fence with the language** (```` ```python ````, ```` ```ts ````, ```` ```bash ````) for accurate coloring; an untagged fence is auto-detected, which is usually right but not guaranteed. Inline `` `code` `` stays a light chip — don't fence single identifiers.

## Inline HTML inside markdown blocks

A markdown block can contain raw HTML when prose isn't enough — comparison tables, callout boxes, dense tabular data, anything you'd otherwise contort markdown into. The renderer (`markdown-it`) is configured with `html: true`; after render, a conservative client-side sanitizer strips `<script>`, `<iframe>`, `<style>`, `<form>`, `on*` event-handler attributes, and `javascript:` URLs. Everything else passes through.

Three guidelines:

0. **Write the HTML as one unbroken run: no blank lines inside it.** A blank line ends the HTML block and hands what follows back to markdown. This is the one failure that looks like the renderer is broken — the outer wrapper renders and the entire inside of your diagram appears on the page as its own source. Indentation used to compound it (4+ spaces meant a code block); the indented-code rule is now disabled for block markdown so that half can no longer bite, but **the blank-line rule is CommonMark and cannot be switched off.** For anything with nested structure, emit it flat — one long line per element, no blank lines between them — even though the source reads worse. Fenced code blocks are unaffected and remain the way to show code.

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

There is no watcher script any more — the daemon ships its own, and it emits
the same banners this skill has always read:

```bash
webcompanion watch --kind annotate --sid "$WC_SID"
```

Pass that as the `Monitor` tool's `command` with `persistent: true` and a
`description` like `"annotate-wait sid=$WC_SID"`.

Banners, unchanged:

- **`WEBCOMPANION_EVENT skill=annotate sid=<sid> event_id=<id>`** — one per
  submitted comment, followed by `---payload---`, the event JSON, `---end---`.
- **`WEBCOMPANION_FINISHED`** / **`WEBCOMPANION_CANCELLED`**.

**One obligation that is new and is not optional.** Every event you answer
must be acknowledged, or the daemon re-emits it — three times, thirty minutes
apart — and then drops it:

```bash
webcompanion ack --sid "$WC_SID" --event-id "<event_id>"
```

This replaces writing an `.ack` file into a consumed directory. Everywhere
`references/handling-events.md` says "write the `.ack`", run this instead; the
rule about *when* (after the rewrite, never before) is unchanged.

### The event payload

The daemon stores `{anchor, text, images}` and nothing else, so annotate's
richer vocabulary travels as JSON inside `text` — always JSON, never
sometimes-prose, so there is nothing to guess:

```json
{"type": "round", "reactions": [...], "text": ""}
{"type": "choice", "block_id": "section-5", "selected_options": ["o1"], "text": ""}
{"type": "comment", "block_id": "section-2", "step_id": "d-fields", "text": "…"}
```

`anchor` is the region the user was looking at — `<block-id>`, or
`<block-id>#<sub-unit>` for a comment on a row inside a block, or
`__general__` for the page-level composer. Parse `text` as JSON first; the
`type` inside decides which section of `handling-events.md` applies.

The registry persists across watchers within a single Claude Code session. It is *not* shared across sessions (keyed by `CLAUDE_CODE_SESSION_ID`).
