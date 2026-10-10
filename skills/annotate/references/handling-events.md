# Handling a watcher event

Read this when a task-notification arrives whose first stdout line is one of the
`WEBCOMPANION_*` banners, OR when the user cancels in terminal while a watcher is
armed. These are **separate, later invocations** from the original push — you do
not need the pushing pipeline here.

All helpers below live in `skills/annotate/blocks.py`; the server and tests import
it aliased as `blocks_model`, but here it's always `blocks.`.

## Before anything: the values every command below needs

Every command in this file is run through `claude-annotate`, a script in the
plugin's `bin/` that Claude Code puts on PATH. It runs from any directory and
needs nothing exported first.

Nothing you set in one Bash call survives into the next, so this file never
uses shell variables like `$WC_SID`. Write the **literal values** into each
command instead:

- **`<sid>`** — from the banner itself: `WEBCOMPANION_EVENT skill=annotate sid=<sid> event_id=<event_id>`.
- **`<event_id>`** — from the same banner.
- **`<slug>`**, the repo root, and **the working `blocks.json`** — print them with
  `claude-annotate session show`. The push records every session this
  conversation owns there, as `{sid, slug, cwd, blocks, title}`.

If the `blocks` path it names no longer exists (a new conversation, or a
scratchpad that was cleaned), rebuild the working copy from the page first:
`claude-annotate pull --sid <sid> --out <scratchpad>/blocks.json`. Editing
from nothing and re-pushing would replace the whole page.

## The event payload is JSON inside JSON

What arrives between `---payload---` and `---end---` is the daemon's own
record, and it has exactly three keys:

```json
{"anchor": "section-2", "text": "{\"type\":\"round\",\"reactions\":[…]}", "images": []}
```

`text` is a **JSON string**. Parse it: the object inside is the envelope, and
every field this file names (`type`, `block_id`, `reactions`,
`selected_options`, the comment `text`) is a field of that envelope, not of
the outer record. `images` is the one field that stays on the outer record.

## Mode D — handling a watcher event

You wake here when a task-notification arrives whose first stdout line is one of the `WEBCOMPANION_*` banners.

**Universal rule, every path below:** whenever you have changed `blocks.json`
in response to an event, run the coherence sweep (see "The coherence sweep"
below) before acknowledging that event. The trigger is that condition —
you changed `blocks.json` and are about to ack — not a list of event types;
round, choice, general comment, and the legacy `reject` / `dismiss` types are
examples, not the complete set. The ack is what unlocks the page, not the
round specifically, so every path that mutates and then acks owes the same
check.

## The model in one paragraph

All content feedback arrives as **one `type: "round"` event**, carrying a list
of reactions the user batched up in the browser. Every reaction answers two
questions: **does the content survive**, and **if so, what should you do to
it?** There are exactly three answers, and they mean the same thing at every
scope:

| `kind` | Survives? | What you do |
|--------|-----------|-------------|
| `delete` | **No** | Remove it, re-thread what's left, never reintroduce it |
| `comment` | Yes, rewritten | Fold a response into the prose |
| `compact` | **Not on the page** | Remove it, but fold what it contributes into the prose that stays |

`delete` and `compact` both remove words; they differ in what happens to the
idea. A `delete` puts the idea **out of scope** — you stop acting on it. A
`compact` says only that the idea does not deserve page space: it **still
binds** the plan, and you keep acting on it. Delete the sentence about health
checks and you build no health check. Compact it and you still build one; the
plan just stops spending six lines saying so.

Weigh every `comment` on its merits. A comment is not an instruction to agree.
When the user is right, concede and rewrite. When the claim still holds, defend
it with the reason, in the rewritten prose. Never quietly fold a comment in as
if you agreed when you do not. (Rounds from older pages may still carry
`disagree: true`; it adds nothing to this rule.)

`scope` says what the reaction is anchored to: `"block"` (the whole section — the reader selected its title) or `"unit"` (exactly the words the reader selected, anchored by `selected_text` plus `prefix`/`suffix`, and by `step_id` when the words sit inside an authored `data-annotate-id` element).

Answers to `choice` blocks ride in the same round, as reactions with `kind:
"choice"`, so a page that asks three questions comes back as one event. They
are answers, not content feedback, and are handled as the `type: "choice"`
path below describes. A standalone `type: "choice"` event can still arrive
from a browser tab opened before answers joined the round. The general chat
box (a `comment` with `block_id: null`) is the one thing that still arrives
on its own. Legacy standalone `reject` and
`dismiss` events can only come from a browser tab opened before the round
rework; handle them as a `comment` and a `delete`
respectively.

## The reader's own words

The reader can edit a section's text in place. Their words are final.

- **An `edit` reaction is already applied.** The page holds the reader's
  version, and `before` / `after` are the section's markdown either side of
  their save. You must update the working `blocks.json` to `after` verbatim,
  `mine` included. Do not write the block back only because of the edit.
- **Pull first.** When a round carries any `edit` reaction, or a held section
  is in play, run `claude-annotate pull --sid <sid> --out <blocks>` before
  touching any block. That replaces your working copy with the page, edits
  included. If you have already edited blocks this round, a pull would lose
  those edits: copy `after` into that one block by hand instead of pulling.
  Pull writes `base` into each block, the stored version it was built from;
  leave it there. Any later save of the reader's moves the section past that
  version, even one that restores the same words. A push that would
  overwrite a section the reader saved since your last push with text not
  built on its current version (no matching `base`), or leave out such a
  section, keeps theirs where it was and prints
  `edited by the reader since your last push: <ids> — kept their version; pull first, then fold your change in`.
  When you see it, finish the round's other pushes, pull, and redo your
  change for those sections on the pulled text.
- **`mine` passages are final.** `mine` lists the words the reader wrote. When
  you rewrite that block for any other reaction, keep every one of them
  character for character. An anchor survives only if its words and the up to
  32 characters stored before and after them still read the same, so keep the
  text adjacent to the reader's words unchanged unless asked. Never compact,
  merge or reword them unless a reaction on those exact words asks. A push
  that loses one prints
  `your change dropped the reader's words in <id>: "<text>"`: put those words
  back as they were and push again.
- **Read the edit as information.** If it contradicts another section, fix that
  other section, or say so in your reply. Never revert the reader's text.
- **A held section.** While the reader has a section open for editing, a push
  keeps their version of it. If `claude-annotate push` prints
  `held by the reader: <ids>`, finish everything else and push it. Your working
  `blocks.json` still has your own stale text for the held section, so a later
  push from it would overwrite the reader's saved edit. Pull only after the
  round's last push, since a pull wipes any unpushed work. Before pulling,
  write down in your reply the change you meant for that section and say it is
  folded into the next round, once they release it. Then fold it into the
  pulled text. `pull` prints `held by the reader: <ids>` too, so reading the
  session tells you which sections are still held.

## Narrating while you work

The reader is looking at a page with a spinner on it. Between the moment they
comment and the moment you re-push, the only thing they can learn about what is
happening is what you tell them. Before the daemon cutover the page captioned
its spinner from a tool-name hook; that hook is gone and the caption was dead
for months. This is its replacement, and it is deliberately not automatic —
you write the lines, so they say something a tool name cannot.

Write a line with:

    claude-annotate progress --sid <sid> --text "Reading how anchors resolve"

and close the trail when the answer is pushed:

    claude-annotate progress --sid <sid> --done

Write the sid literally, as the banner gave it. A `$WC_SID` set in an earlier
Bash call is empty by now, and the line then goes nowhere.

A *step* is a distinct piece of work — a search, a pass of reading, a command
run, a rewrite — **not an individual tool call**. Three greps answering one
question are one step and get one line.

Narrate **before each step, not after it.** A line written after a ninety-second
search arrives ninety seconds too late: the silence it was supposed to fill has
already happened. This is the single rule that makes the feature work.

The line is prose the reader sees. Say what you are doing and, where it is not
obvious, why — "Looking for where the currency conversion actually happens"
beats "Searching".

**A narration line must never carry command output, file contents, secrets or
tokens.** This is a requirement, not tidiness, and it is the only thing
protecting any of it. The panel is hidden from a read-only viewer, but that
hide is client-side: the daemon's `GET /s/<sid>/items` is unauthenticated and
returns `__`-prefixed anchors to anyone holding the share link, and the page
fetches that route on every load, guest included. Anything you write here has
already been handed to every holder of the link, whether or not their browser
draws it. Name what you are doing; never quote what you found.

These commands are cheap and must never fail the turn: if one errors, carry on.

### `WEBCOMPANION_EVENT` (per-comment submission)

1. Parse the banner: `skill`, `sid`, `event_id`.
2. Read the event payload between the `---payload---` and `---end---` markers in the notification body, and parse its `text` as JSON (see "The event payload is JSON inside JSON" above). **If the envelope's `type == "choice"`, jump to the `choice` subsection below.** Otherwise, the envelope's fields are:
   - `block_id` — the block to update. **Absent** for a general comment from the page's chat box: treat a missing `block_id` the same as `null`.
   - `step_id` — which authored `data-annotate-id` element the selected words sit
     inside, or `null` for the whole block. **Pictures no longer produce one.**
     A `sequence`, `flowchart` or `diagram` block is commented as a whole, when
     the reader selected its title, so its comments arrive with `step_id: null`;
     the reader cannot click a step row, a node, or a pflow source line to scope
     one. (The field is still live: `mockup` blocks produce it from a
     `data-annotate-id` region, and comments made before this rule changed still
     carry theirs. Keep handling it — see the rewrite contracts below.) In a
     markdown block it is set when the selected words sit inside an authored
     `data-annotate-id` element.
   - `type` — `"round"` (all content feedback), `"choice"` (an answer), or `"comment"` with a null `block_id` (the general chat box). `"reject"` / `"dismiss"` are legacy — see the model paragraph above.
   - `selected_options` — for `type: "choice"` (and for a `kind: "choice"` reaction inside a round): the option id(s) the user picked (a list, possibly EMPTY when the user answered with a note instead). Absent otherwise.
   - `reactions` — for `type: "round"`: the batched reactions. Jump to the `round` subsection below.
   - `text` — the user's free-text feedback.
   - `selected_text` — the span they highlighted, or `null` or empty if the
     comment is block-scoped.
   - `block_snippet` — optional: a short plain-text snapshot of the block as the user saw it when commenting (useful when the block has since been rewritten).
   - `prefix` / `suffix` — sent with every span mark: the text just before and
     after `selected_text`. Use them to locate it; don't assume it is unique.
   - For `type == "dismiss"`: `block_id` is the block to remove; `text` is empty and ignored. Jump to the `dismiss` subsection below.
   - `images` — on the **outer** record, not the envelope: array of `{token, path}` entries (or empty).  When non-empty, `Read` each `path` before composing your rewrite so you see the screenshots.
3. Narrate that you have it: `claude-annotate progress --sid <sid> --text "Read your comment on <block_id>" --event-id "<event_id>"`.
4. **Narrate before each distinct piece of work below** — a search, a pass
   of reading, a command run, a rewrite — writing the line *before* you
   start it, never after:
   `claude-annotate progress --sid <sid> --text "<what you are about to do>"`.
   This step governs every step below it, not just the next one. An event
   that takes five minutes and produces one line is the silence this
   contract exists to end. See "Narrating while you work" above for what
   counts as one step and for the rule that the line comes first.
5. **Apply the block-rewrite contract** (see "Block-rewrite contract" below).
6. Save the updated `blocks.json` atomically (tmp → rename).
7. Re-push it: `claude-annotate push --blocks <blocks> --cwd <repo root> --slug <slug>`
   (the three values from `claude-annotate session show`). The daemon holds the
   page; a saved file that is not pushed changes nothing the reader sees. If it
   exits non-zero, see "When a push fails" below.
8. Close the trail: `claude-annotate progress --sid <sid> --done`.
9. Acknowledge the event: `webcompanion ack --sid <sid> --event-id "<event_id>"`.
10. End your turn.  **No terminal output.**  The watcher remains armed.

### `WEBCOMPANION_EVENT` with `type: "choice"`

The user answered a choice block. `selected_options` holds the picked id(s) — map them to labels via the block's `spec.options` — and `text` may carry a free-text note riding along with the pick.

**Pick (with or without a note):**

1. Read your working `blocks.json`, find the block by `block_id`. Check the
   answer against the block as it is now:
   `blocks.validate_choice_selection(block["spec"], selected_options, has_text=bool(text))`.
   The page can send an option id that no longer exists (the block was
   rewritten while the reader had it open). On an error, drop the unknown ids
   and continue with what is left; if nothing is left and there is no note,
   the answer says nothing, so re-pose the question and tell the reader why.
2. Narrate that you have it: `claude-annotate progress --sid <sid> --text "Read your choice answer" --event-id "<event_id>"`.
3. **Narrate before each distinct piece of work below** — a search, a pass
   of reading, a command run, a rewrite — writing the line *before* you
   start it, never after:
   `claude-annotate progress --sid <sid> --text "<what you are about to do>"`.
   This step governs every step below it, not just the next one. An event
   that takes five minutes and produces one line is the silence this
   contract exists to end. See "Narrating while you work" above for what
   counts as one step and for the rule that the line comes first.
4. **Resolve the choice into a decision** — convert the block from `kind: "choice"` to a markdown block whose prose states the decision, folds in the reasoning, AND folds in the note when present (e.g. *"Decision: Koumbaras, lowercased per your note…"*). The options disappear; the answer is final. Use `blocks.convert_block_to_markdown(doc, block_id, markdown)` — it sets the markdown, drops `kind`/`spec`, and is content-hash-safe (a no-op rewrite doesn't bump the version).
5. **Continue the task** — the pick drives the next step. Append follow-up blocks to `blocks.json` and/or take the implied action, as the decision warrants.
6. Run the coherence sweep (see below — this path is the universal rule's highest-risk case, since it both resolves the block and appends new ones).
7. Re-push the document: `claude-annotate push --blocks <blocks> --cwd <repo root> --slug <slug>`.
8. Close the trail: `claude-annotate progress --sid <sid> --done`.
9. Run `webcompanion ack --sid <sid> --event-id "<event_id>"`. End your turn. No terminal output; the watcher stays armed.

**Note-only (`selected_options` is `[]`, `text` non-empty):** the user rejected the slate and gave a direction instead. Do NOT resolve. Either rewrite the block's spec with re-proposed options that follow the direction (`blocks.update_spec_block` — the version bumps), or, when the note itself settles the question, resolve to a decision paragraph built from the note. Then continue as in steps 5–9 above.

Multi-select: the decision prose names all picked options. There is no `reject` on a choice — an empty pick always carries a note.

### `WEBCOMPANION_EVENT` with `type: "dismiss"` (legacy)

Only reachable from a browser tab opened before the round rework — the current client sends a `delete` reaction inside a round instead. The steps below are still the correct way to remove a block, and the round's block-scope `delete` refers back to them.

**Delete is not disagreement.** A disagreement means "I think this is wrong" — you soften, withdraw, or defend the claim, and the content stays. A delete means "this is *irrelevant*" — you remove it and stop carrying it forward; do not argue, defend, or re-add it.

1. Read your working `blocks.json`.
2. Narrate that you have it: `claude-annotate progress --sid <sid> --text "Read the dismiss request for <block_id>" --event-id "<event_id>"`.
3. **Narrate before each distinct piece of work below** — a search, a pass
   of reading, a command run, a rewrite — writing the line *before* you
   start it, never after:
   `claude-annotate progress --sid <sid> --text "<what you are about to do>"`.
   This step governs every step below it, not just the next one. An event
   that takes five minutes and produces one line is the silence this
   contract exists to end. See "Narrating while you work" above for what
   counts as one step and for the rule that the line comes first.
4. `blocks.remove_block(doc, block_id)` — deletes the block. It is a no-op if the block is already gone (watcher re-apply safety).
5. **Smart-drop:** scan the surviving blocks. Re-thread any that referenced the removed one — renumber steps, cut or rewrite dangling references — so the document still reads coherently without it. Use `blocks.update_block` / `blocks.update_spec_block` per touched block; touch only blocks that actually referenced the removed one.
6. `blocks.drop_unused_terms(doc)` — drop any glossary entry whose term was last used by the removed block.
7. Treat the removed content as **out of scope** for the rest of this turn and going forward: do not reintroduce it, and exclude it when acting on the plan.
8. Run the coherence sweep (see below — the same pre-ack rule as every other path; dismiss is legacy, not exempt).
9. Re-push the document: `claude-annotate push --blocks <blocks> --cwd <repo root> --slug <slug>`.
10. Close the trail: `claude-annotate progress --sid <sid> --done`.
11. Run `webcompanion ack --sid <sid> --event-id "<event_id>"`. End the turn. No terminal output; the watcher stays armed.

A dismissed `choice` or `sequence` block is removed whole-block the same way — there is no step-level dismiss.

### `WEBCOMPANION_EVENT` with `type: "round"`

**This is how essentially all content feedback arrives.** The reader selected words — any span, from two words to several paragraphs — and marked them, or selected a section's title and marked the whole section. Tables and pictures are marked whole, through their title. The payload carries the whole batch:

- `reactions` — a list of `{scope, kind, block_id, selected_text, text,
  images, step_id, prefix, suffix, before?, after?}`.
  - `kind` is `"delete"`, `"comment"`, or `"compact"` (see the table
    at the top), `"choice"` for an answer to a choice block, or `"edit"`
    for words the reader changed themselves (see "The reader's own words").
  - An `edit` reaction also carries `before` and `after`, and no `selected_text`.
  - A `choice` reaction is always `scope: "block"` and carries
    `selected_options` (the picked ids, possibly empty) and `text` (the note,
    possibly empty). At least one of the two is non-empty.
  - `scope` is `"block"` or `"unit"`.
  - `selected_text` is exactly the words the reader selected (a fragment, a
    sentence, or several paragraphs) — **empty for `scope: "block"`**, which is
    anchored by `block_id` alone. `prefix`/`suffix` are always sent with a unit
    reaction and locate the words in the block (same convention as span
    comments).
  - `step_id`, when present, names the authored `data-annotate-id` element the
    selected words sit inside. The words (`selected_text`) are still the target;
    cut or change only those words, not the whole element. Pictures no longer
    emit one (see the field note above); a `step_id` on a diagram or flowchart
    reaction is a pre-existing mark from before that rule and still resolves.
  - `spans`, present only when the reader's selection crossed a heading: a
    list of `{block_id, selected_text, prefix, suffix}`, one per block the
    words cover, in page order. `block_id` is the first of them and
    `selected_text` is all of them joined by a newline. The reaction belongs
    to every block in `spans`: group it under each, and rewrite each.

Apply the WHOLE round in one pass — this is the entire point of batching:

1. Read your working `blocks.json`. Group reactions by `block_id`, and a reaction with `spans` under every block it names.
2. Narrate that you have it: `claude-annotate progress --sid <sid> --text "Read your round of feedback" --event-id "<event_id>"`.
3. **Narrate before each distinct piece of work below** — a search, a pass
   of reading, a command run, a rewrite — writing the line *before* you
   start it, never after:
   `claude-annotate progress --sid <sid> --text "<what you are about to do>"`.
   This step governs every step below it, not just the next one. An event
   that takes five minutes and produces one line is the silence this
   contract exists to end. See "Narrating while you work" above for what
   counts as one step and for the rule that the line comes first.
4. **Apply `scope: "block"` reactions first**, since a block-level `delete`
   makes that block's unit reactions moot:
   - **`choice`** — the user answered that choice block. Resolve it exactly
     as the `type: "choice"` path below does, starting with its check of the
     answer against the current spec: a pick becomes a decision
     paragraph via `blocks.convert_block_to_markdown`, and a note-only answer
     either re-proposes options or resolves from the note. Several answers in
     one round are resolved in this one pass. Then carry each decision into
     the work, as that path's "continue the task" step says. When a `delete`
     on the same block sits beside the answer, the delete wins.
   - **`delete`** — `blocks.remove_block(doc, block_id)`, then smart-drop:
     re-thread surviving blocks that referenced it (renumber steps, cut or
     rewrite dangling references) so the document still reads coherently, and
     `blocks.drop_unused_terms(doc)` for any glossary entry it orphaned. Treat
     the content as **out of scope from now on** — do not reintroduce it, and
     exclude it when acting on the plan. Any unit reactions on that same block
     are then no-ops.
   - **`compact`** — the whole block leaves the page. Fold what it contributes
     into a neighbouring block, then `blocks.remove_block(doc, block_id)` and
     re-thread the survivors exactly as for a delete. The difference is what
     you carry forward: the block's content still binds the plan, so keep
     acting on it. Unit reactions on that block are absorbed rather than
     dropped — answer a `comment` inside it first, and let the answer be what
     travels into the neighbour.
   - **`comment`** — the block-rewrite contract for the whole block.
     **If the comment answers an open `choice` block anywhere on the page,
     that choice is answered** — resolve it in this same pass, exactly as the
     `type: "choice"` path would. A reader who types "let's do the second one"
     into a comment box has decided; only the transport differs, and leaving
     the card unresolved re-asks a question they consider closed. The reverse
     also holds: acting on the decision without resolving the card is the
     failure, not a missing extra step.
5. For each remaining touched block, compose ONE new markdown that applies all
   of its unit reactions together:
   - **`delete`** — cut exactly the words in `selected_text` from the block's
     markdown (a fragment, a sentence, or several paragraphs), then re-thread
     the remainder (renumber, fix dangling references) so the block still reads
     coherently. Do not remove the whole block. When the delete covers
     **part of a sentence**, cut exactly those words, then repair the sentence
     so it stays **grammatical**. Never delete the rest of the sentence to
     avoid the repair. Deleted content is out of scope going forward — do not
     reintroduce it (same rule as a block-scope delete).
   - **`comment`** — the block-rewrite contract scoped to the quoted words: fold
     the answer or clarification into the prose. A `comment` is about
     **exactly the quoted words**, not the whole paragraph they sit in. Answer
     that, and rewrite the paragraph only as far as the answer needs. `Read`
     any `images` paths first.
   - **`compact`** — cut the selected words from the block's markdown, and fold
     what they contribute into the **same sentence** where it can, otherwise
     the nearest surviving sentence or paragraph that covers that ground. The
     page gets shorter and denser. Do not leave a stub, a trailer, or a
     "compacted" note behind — there must be no residue. If no surviving
     sentence can carry it, the detail is dropped; that is expected, not an
     error.
   - **A span across paragraphs:** cut or fold the whole span, then re-join the
     surrounding paragraphs so they still read as one thought.
   - **Words inside a table cell:** change only that cell's text; keep the
     table's shape.

Two rules govern compact, and both matter:

- **There is no hidden store.** Compacted text is not retained — not in
  `blocks.json`, not in a side file, not carried in your head past this turn.
  Whatever survived the absorb is the document, and it is the whole of what
  you act on. If you find yourself about to use a detail that is no longer on
  the page, you have lost it: ask, or pick a sensible default and say so.
- **Compact is lossy, and that is accepted.** Do not compensate by writing
  longer surviving sentences than the material warrants, and do not refuse to
  compact because detail would be lost.
6. Persist each changed block via `blocks.update_block(doc, block_id,
   new_markdown)` (content-hash-safe), then `blocks.drop_unused_terms(doc)`.
7. **Run the coherence sweep** — see "The coherence sweep" below (it's the
   universal pre-ack rule, not a round-only step). This is not optional and it
   is not conditional on the round having deleted anything.
8. ONE `blocks.save_atomic`, then ONE re-push (`claude-annotate push --blocks <blocks> --cwd <repo root> --slug <slug>`) — the daemon holds the document now, so a save that is not pushed changes nothing the user can see.
9. Close the trail: `claude-annotate progress --sid <sid> --done`.
10. Run `webcompanion ack --sid <sid> --event-id "<event_id>"` ONCE. End your turn. No terminal
   output; the watcher stays armed.

Cross-item coherence is required: if a round deletes two bullets and
questions a third in the same block, the single rewrite resolves all three
together. A `selected_text` that no longer matches the current block content
(concurrent rewrite) is historical context — same rule as span comments. A
`block_id` absent from `blocks.json` at apply time is a no-op for that one
reaction — apply the rest of the round normally and ack as usual. A `step_id`
that no longer resolves is likewise a per-reaction no-op.
Re-apply safety is unchanged: re-processing the round is a content-hash
no-op.

### `WEBCOMPANION_FINISHED`

The user clicked Done.

1. Ack briefly in terminal: *"Annotate session for `<title>` closed."*
2. Remove this session from the conversation marker: `claude-annotate session forget --sid <sid>`.

### `WEBCOMPANION_CANCELLED`

The user cancelled (clicked tab close, or wrote `scrap it` in terminal).

1. Ack briefly in terminal: *"Annotate session for `<title>` cancelled."*
2. Remove this session from the conversation marker: `claude-annotate session forget --sid <sid>`.

## The coherence sweep

**This is a universal pre-ack rule, not a step scoped to `type: "round"`.**
The trigger is the condition — you changed `blocks.json` in response to an
event and are about to acknowledge it — not a fixed list of event
types; a round, a resolved choice, a general comment, and the legacy
`reject` / `dismiss` types are examples, not the complete set. Whenever that
condition holds, re-read every block and check it against the document you
just produced, and do it **before acknowledging the event**.

The order is the point. The page is locked behind "Claude is updating…" until
the ack lands — `/poll` reports `busy: true` until then — so the ack is the
moment the user sees your answer. Sweeping after it would be sweeping in front
of them. It costs no extra tool calls: `blocks.json` is already in hand from
whatever change you just made.

Steering block 4 while block 6 still describes what block 4 used to say is the
single most common way this document goes wrong, and nothing else catches it.
The block-rewrite contract's "touch only the blocks you actually need to
change" is a rule about *gratuitous* rewrites; it was never a licence to leave
a block saying something false.

**Fix exactly three things:**

1. **References that no longer resolve** — a pointer to a removed block, a
   step number that shifted, a count or total that stopped adding up, a
   glossary term whose referent is gone.
2. **Claims the change made false** — including claims that never name the
   block you changed. This is the case the smart-drop step cannot catch,
   because it looks for references rather than for meaning.
3. **Spec blocks the change made false** — a `choice` still offering an option
   you just carried out, a `flowchart` or `sequence` drawing a path the change
   removed. Read every `spec` on the page, not just every `markdown`.

Point 3 is the one that gets missed, and it fails loudly: a spec block's
staleness lives in `spec`, not in prose, so a sweep that re-reads only markdown
walks straight past it. A `choice` still offering finished work is the most
visible staleness a page can carry — the reader is being asked to decide
something you already did — and it is invisible to a grep for the block you
changed, because nothing in it mentions that block. Resolve it with
`blocks.convert_block_to_markdown` (state the decision and how it was reached),
or re-pose it with `blocks.update_spec_block` when a real question remains.

**Change nothing else.** Not wording, not tone, not ordering, not transitions,
not anything that **still reads true**. "Wordy but accurate" is left alone. A
block is rewritten only if leaving it would make the document lie.

Persist sweep fixes with `blocks.update_block`, which is content-hash-safe, so
a block that needed nothing costs no version bump. If a sweep fix itself makes
another block false, resolve that too in the same pass — the document settles
before the ack, not across turns.

This generalises the smart-drop step that block-scope `delete` and `compact`
already call for. Doing it there and again here is not wasted work: smart-drop
is scoped to what a removal broke, the sweep is scoped to the whole document.

## Explaining a change: `change_note`

The page can show a mechanical diff of any block you rewrite — it snapshots
the document when the event is queued. What it cannot derive is **why** you
changed something, and for a `compact` it cannot know **what you dropped**,
because that judgement existed only while you were applying the round.

So when you rewrite a block, you may set an optional `change_note` string on
it. Keep it to one or two sentences, in this shape:

    Why: you asked whether this holds when the consumer is idle. It doesn't, so the claim is now conditional.

For a block where a `compact` discarded detail that no surviving sentence
could carry, add a second line naming exactly what is gone:

    Lost: the flag key `ingest.v2.writes`.

**The `Lost:` line is the honest half of compact.** Compact is lossy and
irreversible once the round is submitted, and this note is the only place a
user could ever find out what it actually discarded. Write it whenever detail
was dropped; do not write it when nothing was.

`change_note` is **optional** and describes only the most recent rewrite.
Clear it on a block you rewrite without anything worth explaining, rather than
leaving a note that describes an older change. The diff renders with or
without it — never withhold a rewrite because you cannot phrase the note.

## Block-rewrite contract

When you receive a `WEBCOMPANION_EVENT` with a non-null `block_id`:

1. Read your working `blocks.json`.  Find the block by `id`.
2. **Generate rewritten markdown for the block that folds the answer or clarification into the prose.**  The document itself is the answer — do not echo the user's question back as Q-and-A.  No "Claude says:" panels, no chat threads.  After your rewrite, a reader who didn't see the user's comment should be able to read the new block and have no remaining question on the topic the comment raised.
3. **Edge cases:**
   - The comment is *off-topic* for the targeted block (the user's question references content that lives elsewhere): update the block to be clearer about its actual topic, or rewrite a *neighboring* block to address the question, or both.  Use judgement.
   - The `type` is `reject`: the user disagrees.  Either soften / withdraw the claim in the new prose, or hold the line with a reasoned explanation woven into the rewrite.  Don't pretend agreement; don't argue back in a side channel.  This mutates `blocks.json` and acks like any other path — the coherence sweep (see above) still applies before you ack.
   - The user's `selected_text` no longer exists after a prior rewrite: treat it as historical context.  The current block content is what matters.
4. **Touch only the blocks you actually need to change.** Do not re-emit unchanged blocks "for completeness" — the server derives `version` from a content-hash chain, so re-writing identical content is a true no-op, but re-emitting the same prose with cosmetic differences (a swapped synonym, a re-flowed sentence) inflates the version of a block the user didn't ask you to touch. Block ids stay the same; versions take care of themselves.

When you rewrite a section, keep its format. A markdown section stays markdown. An HTML section stays HTML unless the reader asks otherwise. Write new sections in markdown (`references/pushing.md` § Markdown first).

`step_id` still arrives for a section that carries `data-annotate-id` elements, so older pages and mockups keep reporting it. A section written as plain markdown has no such elements, and its reactions arrive with `step_id: null` and the selected words as the anchor.

Persist each changed markdown block via `blocks.update_block(doc, block_id, new_markdown)` (content-hash-safe — returns `False`, a true no-op, if identical), then `save_atomic` and re-push. (Use `blocks.update_spec_block` for `sequence`/`diagram` spec blocks instead — see "Diagram block-rewrite contract".)

When `block_id` is absent or `null` (a general comment from the page's chat box — the envelope has no `block_id` key at all, and the outer `anchor` is `__general__`):

1. Read the comment text.  It will be a directive that applies across blocks ("make this shorter", "more casual tone", "remove the second paragraph", etc.).
2. Update *only the blocks that actually need updating* to apply the directive. Don't re-emit untouched blocks.
3. Run the coherence sweep (see "The coherence sweep" above — a cross-document directive is exactly the kind of change that can orphan a reference elsewhere).
4. Save, re-push (`claude-annotate push --blocks <blocks> --cwd <repo root> --slug <slug>`), close the trail, and ack — steps 6 to 9 of the `WEBCOMPANION_EVENT` list above. A general comment that only asks a question and changes no block still gets the ack, and a one-line answer in the terminal.

## Diagram block-rewrite contract

For `WEBCOMPANION_EVENT` payloads that target a `kind: "sequence"` block, the rewrite contract has three deltas from the markdown contract above:

1. **Whole-diagram by default (`step_id: null`)** — the usual case, and now the only one the UI produces. A picture is commented as a whole when the reader selected its title, so read the comment against the whole spec and apply it across steps as needed: restructure phases, reorder steps, add/remove actors, retitle. Analogous to general comments with `block_id: null` in the markdown contract. The reader is pointing at the diagram; work out from the words which part they mean.

2. **Targeted when `step_id` IS present.** Comments made before pictures stopped
   taking step-level comments still carry one, and a re-emitted event can bring
   one back. A comment on step `s4` ("does this fire once per click, or can it batch?") rewrites just that step's `label` and/or `sub`. Other steps untouched. Step ids stay stable across rewrites; new steps mint fresh ids via `next_step_id`.

3. **Reject on a step** — either soften/withdraw the claim by rewriting the step, or hold the line by rewriting the sub-caption with reasoning. Don't drop the step silently. Same "fold the answer into the prose" spirit; here the "prose" is the spec.

Persist updates via `blocks.update_spec_block(doc, block_id, new_spec)` — returns `True` only on real change (canonical-JSON content hash). Then `save_atomic` and re-push. Watcher re-emit safety is preserved: `webcompanion ack` is idempotent.

**Off-topic comments** (user comments on `s4` about something that really belongs in `s2`) follow the same "use judgment" rule as the markdown contract: rewrite the targeted step to be clearer about its actual topic, or rewrite the neighboring step, or both.


### Flowchart block-rewrite contract

`kind: "flowchart"` blocks follow the sequence contract above, with node ids
where it says step ids. Neither the chart nor the pflow source pane is a click
target, so comments arrive whole-block.

1. **Whole-flowchart by default (`step_id: null`)** — the usual case, and now
   the only one the UI produces. Apply across the spec as needed: add/remove
   nodes, rewire edges, retitle, fix a `ref`. Analogous to general comments
   with `block_id: null` in the markdown contract. When the block was authored
   as `spec.source`, edit the source line the comment is about and let it
   recompile — the reader can see which line drew which shape, so they will
   often name it in words.
2. **Targeted when `step_id` IS present** (a pre-existing mark, or one a
   re-emitted event brought back). A comment on node `f` ("does this decision
   also fire on a partial save?") rewrites just that node's
   `label`/`sub`/`method`/`ref`/`href`, or the edges touching it if the branch
   structure itself needs to change. Other nodes untouched. Node ids are
   author-assigned and stay stable across rewrites — don't renumber a node
   just because you touched it. (The DOM carries the id as `data-node-id`, but
   it arrives on the wire in the `step_id` field — there is no separate
   `node_id` field.)
3. **Reject on a node** — either soften/withdraw the claim by rewriting the
   node, or hold the line by rewriting its `sub` with reasoning. Don't drop
   the node silently.

Persist updates via `blocks.update_spec_block(doc, block_id, new_spec)` — the
same content-hash-safe helper used for sequence and diagram specs — then
`save_atomic`. To convert a flowchart to/from prose, treat it as a kind
change (drop `kind`/`spec`, set `markdown`) exactly as for other spec blocks.

## Glossary term-set diff at rewrite time

When you handle a `WEBCOMPANION_EVENT` that targets a markdown block:

1. After composing the rewritten block markdown, apply the **drop rule**: any glossary entry whose `term` no longer appears (case-sensitive whole-word) in any block is dropped. Use `blocks.drop_unused_terms(doc)` — it does this in one call.
2. Apply the **add rule**: if the rewrite introduces a new project-specific identifier that wasn't already in the glossary and that meets the comprehension-blocker test (see `references/pushing.md` § "When to emit a glossary entry"), append a new entry.

Do not re-extract the whole glossary on every rewrite. The common case — a rewrite that doesn't touch the term set — produces no glossary mutation.

## Re-apply safety

If the watcher restarts mid-session, it may re-emit an event you've already processed.  This is safe because:

- For block rewrites, your new content will match the current block content — `blocks.py:update_block` is content-hash-aware and returns `False` on a no-op, so the chain in `versions.json` doesn't grow a duplicate entry.
- The event may already be acknowledged; that's fine — `webcompanion ack` is idempotent.  Run it again (idempotent).

Just process the event normally each time; the system handles dupe detection at the storage layer.

## Terminal cancellation

If the user says "scrap it" / "respond in terminal" / "stop annotating" / equivalent *while a watcher is armed* (`claude-annotate session show` lists sessions):

1. List this conversation's sessions: `claude-annotate session show`.
2. For each entry, cancel it: `webcompanion end --sid <sid> --cancel`. That is the whole step; there is no marker file to write by hand.
3. The watcher sees the cancellation on its next tick and emits `WEBCOMPANION_CANCELLED`. You'll get a task-notification for each.
4. Handle each one per `WEBCOMPANION_CANCELLED` above, which also removes it from the marker.
5. Continue with whatever the user actually wanted.

## Edge cases

- **`selected_text: null or ""`** — comment refers to the entire block; treat
  the block as the anchor.
- **Daemon unreachable** (any `claude-annotate` or `webcompanion` command says it cannot reach the daemon) — run `webcompanion status` once. If it is down, stop: do not start it yourself, do not ack, and tell the user in one terminal line, with the output of `webcompanion doctor`. The event stays queued on disk, and the watcher re-emits it once the daemon is back, so nothing is lost by stopping. If `status` says it is up, retry the failed command once.
- **The working `blocks.json` is missing** — rebuild it with `claude-annotate pull --sid <sid> --out <scratchpad>/blocks.json` before changing anything (see the top of this file).
- **Malformed event payload** — fall back to no-op; acknowledge it anyway so the event isn't re-emitted forever.
- **`finished` or `cancelled` marker present** — the user ended the session. The watcher emits `WEBCOMPANION_FINISHED` or `WEBCOMPANION_CANCELLED`; see Mode D.

## When a push fails

`claude-annotate push` exits non-zero and changes **nothing** on the page when
it refuses: a missing or unparseable `blocks.json`, a document with no blocks,
an unknown `--slug`, an unknown block kind, content under the wrong key. The
reason is on stderr. Fix the file (or the slug, from
`claude-annotate session show`) and push again. Do not ack while the answer
has not reached the page: the reader would be told you are done and see the
old page. If the cause is the daemon itself, follow "Daemon unreachable" above.

## When an anchor will not resolve

Run `claude-annotate check-anchors <blocks> <repo root>` after any rewrite that
added or moved a `code` anchor. If an anchor still fails after you have
corrected its `file`, `line` and `snippet` twice, remove that one anchor from
the block rather than ship a citation that shows no code, and say in the
block's `change_note` which reference you dropped and why. Never ack with the
check failing.

## Page-wide single-flight lock

The browser page is single-flight: while a submitted event is in flight, the
page is locked (the round's Submit disabled, a "Claude is updating…" banner
shown), and only one comment editor can be open at a time. The selection menu
stays usable: marks made while Claude works queue for the next round. The lock is now **client-side**: the page locks itself on submit and unlocks when an item actually changes, because the daemon's `/poll` does not report whether an event is still unacked. Practical consequence for you is unchanged and slightly sharper: **re-push the document when you finish handling an event**, and acknowledge it, even on a no-op or malformed payload — a run that acks without changing anything leaves the banner up until the next change.

Two deliberate softenings of the lock:

- The **general composer stays usable while busy** — its submissions queue server-side and the watcher delivers them one at a time, so you may receive a second `WEBCOMPANION_EVENT` notification while (or right after) handling the first. Handle them in order; each gets its own ack.
- The client watches the watcher heartbeat (`watcher_age_s` in `/poll`). If the heartbeat goes stale (the Claude session died mid-event), the page **unlocks itself** and shows a "Claude's session is gone" warning instead of spinning forever. Events submitted in that state stay queued on disk; a freshly armed watcher for the same session directories will re-emit them.
