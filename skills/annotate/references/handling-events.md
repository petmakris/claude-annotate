# Handling a watcher event

Read this when a task-notification arrives whose first stdout line is one of the
`WEBCOMPANION_*` banners, OR when the user cancels in terminal while a watcher is
armed. These are **separate, later invocations** from the original push — you do
not need the pushing pipeline here.

All helpers below live in `skills/annotate/blocks.py`; the server and tests import
it aliased as `blocks_model`, but here it's always `blocks.`.

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
it?** There are exactly four answers, and they mean the same thing at every
scope:

| `kind` | Survives? | What you do |
|--------|-----------|-------------|
| `delete` | **No** | Remove it, re-thread what's left, never reintroduce it |
| `keep` | Yes, untouched | Nothing — explicitly do not rewrite this |
| `comment` | Yes, rewritten | Fold a response into the prose |
| `compact` | **Not on the page** | Remove it, but fold what it contributes into the prose that stays |

`delete` and `compact` both remove words; they differ in what happens to the
idea. A `delete` puts the idea **out of scope** — you stop acting on it. A
`compact` says only that the idea does not deserve page space: it **still
binds** the plan, and you keep acting on it. Delete the sentence about health
checks and you build no health check. Compact it and you still build one; the
plan just stops spending six lines saying so.

A `comment` may carry `disagree: true`. That does not change what survives —
it tells you the user is pushing back, so concede or defend with reasoning
rather than quietly folding the note in as if you agreed.

`scope` says what the reaction is anchored to: `"block"` (the whole block —
the user hovered the card header) or `"unit"` (one paragraph/bullet/row/fence
inside it, anchored by `selected_text`, or by `step_id` for diagram and
flowchart nodes).

Two event types are **not** content feedback and still arrive on their own:
`choice` (the user answered a question you asked) and a `comment` with
`block_id: null` (the general chat box). Legacy standalone `reject` and
`dismiss` events can only come from a browser tab opened before the round
rework; handle them as a `comment` with `disagree` and a `delete`
respectively.

### `WEBCOMPANION_EVENT` (per-comment submission)

1. Parse the banner: `skill`, `sid`, `event_id`.
2. Read the event payload between the `---payload---` and `---end---` markers in the notification body. **If `type == "choice"`, jump to the `choice` subsection below.** Otherwise, fields are:
   - `block_id` — the block to update, or `null` for a general comment.
   - `step_id` — which sub-unit of the block the comment targets, or `null` for the whole block. **Pictures no longer produce one.** A `sequence`, `flowchart` or `diagram` block is commented as a whole, from the card header, so its comments arrive with `step_id: null`; the reader cannot click a step row, a node, or a pflow source line to scope one. (The field is still live: `mockup` blocks produce it from a `data-annotate-id` region, and comments made before this rule changed still carry theirs. Keep handling it — see the rewrite contracts below.) Absent/null for markdown blocks.
   - `type` — `"round"` (all content feedback), `"choice"` (an answer), or `"comment"` with a null `block_id` (the general chat box). `"reject"` / `"dismiss"` are legacy — see the model paragraph above.
   - `selected_options` — for `type: "choice"`: the option id(s) the user picked (a list, possibly EMPTY when the user answered with a note instead). Absent otherwise.
   - `reactions` — for `type: "round"`: the batched reactions. Jump to the `round` subsection below.
   - `text` — the user's free-text feedback.
   - `selected_text` — the span they highlighted, or `null` if the comment is block-scoped.
   - `block_snippet` — optional: a short plain-text snapshot of the block as the user saw it when commenting (useful when the block has since been rewritten).
   - `prefix` / `suffix` — optional: surrounding context that pins down *which* occurrence of `selected_text` was highlighted when it appears more than once in the block.
   - For `type == "dismiss"`: `block_id` is the block to remove; `text` is empty and ignored. Jump to the `dismiss` subsection below.
   - `images` — array of `{token, path}` entries (or empty).  When non-empty, `Read` each `path` before composing your rewrite so you see the screenshots.
3. **Apply the block-rewrite contract** (see "Block-rewrite contract" below).
4. Save the updated `blocks.json` atomically (tmp → rename).
5. Acknowledge the event: `webcompanion ack --sid "$WC_SID" --event-id "<event_id>"`.
6. End your turn.  **No terminal output.**  The watcher remains armed.

### `WEBCOMPANION_EVENT` with `type: "choice"`

The user answered a choice block. `selected_options` holds the picked id(s) — map them to labels via the block's `spec.options` — and `text` may carry a free-text note riding along with the pick.

**Pick (with or without a note):**

1. Read your working `blocks.json`, find the block by `block_id`.
2. **Resolve the choice into a decision** — convert the block from `kind: "choice"` to a markdown block whose prose states the decision, folds in the reasoning, AND folds in the note when present (e.g. *"Decision: Koumbaras, lowercased per your note…"*). The options disappear; the answer is final. Use `blocks.convert_block_to_markdown(doc, block_id, markdown)` — it sets the markdown, drops `kind`/`spec`, and is content-hash-safe (a no-op rewrite doesn't bump the version).
3. **Continue the task** — the pick drives the next step. Append follow-up blocks to `blocks.json` and/or take the implied action, as the decision warrants.
4. Run the coherence sweep (see below — this path is the universal rule's highest-risk case, since it both resolves the block and appends new ones).
5. Re-push the document (`references/pushing.md` § Push the document, with `--slug "$WC_SLUG"`), then run `webcompanion ack --sid "$WC_SID" --event-id "<event_id>"`. End your turn. No terminal output; the watcher stays armed.

**Note-only (`selected_options` is `[]`, `text` non-empty):** the user rejected the slate and gave a direction instead. Do NOT resolve. Either rewrite the block's spec with re-proposed options that follow the direction (`blocks.update_spec_block` — the version bumps), or, when the note itself settles the question, resolve to a decision paragraph built from the note. Then continue as in steps 3–5 above.

Multi-select: the decision prose names all picked options. There is no `reject` on a choice — an empty pick always carries a note.

### `WEBCOMPANION_EVENT` with `type: "dismiss"` (legacy)

Only reachable from a browser tab opened before the round rework — the current client sends a `delete` reaction inside a round instead. The steps below are still the correct way to remove a block, and the round's block-scope `delete` refers back to them.

**Delete is not disagreement.** A disagreement means "I think this is wrong" — you soften, withdraw, or defend the claim, and the content stays. A delete means "this is *irrelevant*" — you remove it and stop carrying it forward; do not argue, defend, or re-add it.

1. Read your working `blocks.json`.
2. `blocks.remove_block(doc, block_id)` — deletes the block. It is a no-op if the block is already gone (watcher re-apply safety).
3. **Smart-drop:** scan the surviving blocks. Re-thread any that referenced the removed one — renumber steps, cut or rewrite dangling references — so the document still reads coherently without it. Use `blocks.update_block` / `blocks.update_spec_block` per touched block; touch only blocks that actually referenced the removed one.
4. `blocks.drop_unused_terms(doc)` — drop any glossary entry whose term was last used by the removed block.
5. Treat the removed content as **out of scope** for the rest of this turn and going forward: do not reintroduce it, and exclude it when acting on the plan.
6. Run the coherence sweep (see below — the same pre-ack rule as every other path; dismiss is legacy, not exempt).
7. Re-push the document with `--slug "$WC_SLUG"`, then run `webcompanion ack --sid "$WC_SID" --event-id "<event_id>"`. End the turn. No terminal output; the watcher stays armed.

A dismissed `choice` or `sequence` block is removed whole-block the same way — there is no step-level dismiss.

### `WEBCOMPANION_EVENT` with `type: "round"`

**This is how essentially all content feedback arrives.** The user swept the
document — marking whole blocks from the card header and individual sub-units
(list items, paragraphs, code blocks) in the body — and submitted the lot at
once. Tables and pictures have no sub-units: a comment on either is a
block-scope one from the card header. The payload carries the whole batch:

- `reactions` — a list of `{scope, kind, block_id, selected_text, text,
  images, step_id?, disagree?, prefix?, suffix?}`.
  - `kind` is `"delete"`, `"keep"`, `"comment"`, or `"compact"` (see the table
    at the top).
  - `scope` is `"block"` or `"unit"`.
  - `selected_text` is the sub-unit's plain text — **empty for `scope:
    "block"`**, which is anchored by `block_id` alone. `prefix`/`suffix` pin
    down which occurrence when it repeats inside the block (same convention as
    span comments).
  - `step_id`, when present, anchors a unit reaction to an authored
    `data-annotate-id` sub-unit instead of to text. Pictures no longer emit
    one (see the field note above); a `step_id` on a diagram or flowchart
    reaction is a pre-existing mark from before that rule and still resolves.
  - `disagree: true` on a comment means push-back — concede or defend, don't
    read it as agreement.

Apply the WHOLE round in one pass — this is the entire point of batching:

1. Read your working `blocks.json`. Group reactions by `block_id`.
2. **Apply `scope: "block"` reactions first**, since a block-level `delete`
   makes that block's unit reactions moot:
   - **`delete`** — `blocks.remove_block(doc, block_id)`, then smart-drop:
     re-thread surviving blocks that referenced it (renumber steps, cut or
     rewrite dangling references) so the document still reads coherently, and
     `blocks.drop_unused_terms(doc)` for any glossary entry it orphaned. Treat
     the content as **out of scope from now on** — do not reintroduce it, and
     exclude it when acting on the plan. Any unit reactions on that same block
     are then no-ops.
   - **`keep`** — no rewrite for this block at all. Never re-emit a block
     whose only reaction is a keep.
   - **`compact`** — the whole block leaves the page. Fold what it contributes
     into a neighbouring block, then `blocks.remove_block(doc, block_id)` and
     re-thread the survivors exactly as for a delete. The difference is what
     you carry forward: the block's content still binds the plan, so keep
     acting on it. Unit reactions on that block are absorbed rather than
     dropped — answer a `comment` inside it first, and let the answer be what
     travels into the neighbour.
   - **`comment`** — the block-rewrite contract for the whole block.
3. For each remaining touched block, compose ONE new markdown that applies all
   of its unit reactions together:
   - **`delete`** — cut that sub-unit (the bullet / paragraph / row / fence
     matching `selected_text`, or the node matching `step_id`) from the
     block's markdown, then re-thread the remainder (renumber, fix dangling
     references) so the block still reads coherently. Do not remove the whole
     block. Deleted content is out of scope going forward — do not
     reintroduce it (same rule as a block-scope delete).
   - **`comment`** — the block-rewrite contract scoped to that sub-unit: fold
     the answer or clarification into the sub-unit's prose. `Read` any
     `images` paths first.
   - **`keep`** — no rewrite for this sub-unit. Never re-emit a block whose
     only reactions are keeps.
   - **`compact`** — cut that sub-unit from the block's markdown, and fold
     what it contributes into the nearest surviving sub-unit that already
     covers that ground. The page gets shorter and denser. Do not leave a
     stub, a trailer, or a "compacted" note behind — there must be no residue.
     If no surviving sub-unit can carry it, the detail is dropped; that is
     expected, not an error.

Three rules govern compact, and all three matter:

- **`keep` beats compact.** If the only surviving sub-unit that could carry
  the absorbed material is marked `keep`, do not rewrite it — `keep` is an
  explicit "do not rewrite this" and that is the whole reason it exists.
  Carry the material somewhere else, or drop it. A user must be able to
  protect one sentence and compact its neighbour in the same round without
  the protection quietly failing.
- **There is no hidden store.** Compacted text is not retained — not in
  `blocks.json`, not in a side file, not carried in your head past this turn.
  Whatever survived the absorb is the document, and it is the whole of what
  you act on. If you find yourself about to use a detail that is no longer on
  the page, you have lost it: ask, or pick a sensible default and say so.
- **Compact is lossy, and that is accepted.** Do not compensate by writing
  longer surviving sentences than the material warrants, and do not refuse to
  compact because detail would be lost.
4. Persist each changed block via `blocks.update_block(doc, block_id,
   new_markdown)` (content-hash-safe), then `blocks.drop_unused_terms(doc)`.
5. **Run the coherence sweep** — see "The coherence sweep" below (it's the
   universal pre-ack rule, not a round-only step). This is not optional and it
   is not conditional on the round having deleted anything.
6. ONE `blocks.save_atomic`, then ONE re-push (`--slug "$WC_SLUG"`) — the daemon holds the document now, so a save that is not pushed changes nothing the user can see.
7. Run `webcompanion ack --sid "$WC_SID" --event-id "<event_id>"` ONCE. End your turn. No terminal
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
2. Remove this session's entry from `~/.claude/annotate/pending-${CLAUDE_CODE_SESSION_ID}.json`.

### `WEBCOMPANION_CANCELLED`

The user cancelled (clicked tab close, or wrote `scrap it` in terminal).

1. Ack briefly in terminal: *"Annotate session for `<title>` cancelled."*
2. Remove this session's entry from the pending registry.

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

**Fix exactly two things:**

1. **References that no longer resolve** — a pointer to a removed block, a
   step number that shifted, a count or total that stopped adding up, a
   glossary term whose referent is gone.
2. **Claims the change made false** — including claims that never name the
   block you changed. This is the case the smart-drop step cannot catch,
   because it looks for references rather than for meaning.

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
   - The `type` is `reject`: the user disagrees.  Either soften / withdraw the claim in the new prose, or hold the line with a reasoned explanation woven into the rewrite.  Don't pretend agreement; don't argue back in a side channel.  This mutates `blocks.json` and acks like any other path — the coherence sweep (see above) still applies before you write the `.ack`.
   - The user's `selected_text` no longer exists after a prior rewrite: treat it as historical context.  The current block content is what matters.
4. **Touch only the blocks you actually need to change.** Do not re-emit unchanged blocks "for completeness" — the server derives `version` from a content-hash chain, so re-writing identical content is a true no-op, but re-emitting the same prose with cosmetic differences (a swapped synonym, a re-flowed sentence) inflates the version of a block the user didn't ask you to touch. Block ids stay the same; versions take care of themselves.

Persist each changed markdown block via `blocks.update_block(doc, block_id, new_markdown)` (content-hash-safe — returns `False`, a true no-op, if identical), then `save_atomic` and re-push. (Use `blocks.update_spec_block` for `sequence`/`diagram` spec blocks instead — see "Diagram block-rewrite contract".)

When `block_id` is `null` (general comment):

1. Read the comment text.  It will be a directive that applies across blocks ("make this shorter", "more casual tone", "remove the second paragraph", etc.).
2. Update *only the blocks that actually need updating* to apply the directive. Don't re-emit untouched blocks.
3. Run the coherence sweep (see "The coherence sweep" above — a cross-document directive is exactly the kind of change that can orphan a reference elsewhere), then save and ack as above.

## Diagram block-rewrite contract

For `WEBCOMPANION_EVENT` payloads that target a `kind: "sequence"` block, the rewrite contract has three deltas from the markdown contract above:

1. **Whole-diagram by default (`step_id: null`)** — the usual case, and now the only one the UI produces. A picture is commented as a whole from the card header, so read the comment against the whole spec and apply it across steps as needed: restructure phases, reorder steps, add/remove actors, retitle. Analogous to general comments with `block_id: null` in the markdown contract. The user is pointing at the diagram; work out from the words which part they mean.

2. **Targeted when `step_id` IS present.** Comments made before the header-only rule still carry one, and a re-emitted event can bring one back. A comment on step `s4` ("does this fire once per click, or can it batch?") rewrites just that step's `label` and/or `sub`. Other steps untouched. Step ids stay stable across rewrites; new steps mint fresh ids via `next_step_id`.

3. **Reject on a step** — either soften/withdraw the claim by rewriting the step, or hold the line by rewriting the sub-caption with reasoning. Don't drop the step silently. Same "fold the answer into the prose" spirit; here the "prose" is the spec.

Persist updates via `blocks.update_spec_block(doc, block_id, new_spec)` — returns `True` only on real change (canonical-JSON content hash). Then `save_atomic` and re-push. Watcher re-emit safety is preserved: `webcompanion ack` is idempotent.

**Off-topic comments** (user comments on `s4` about something that really belongs in `s2`) follow the same "use judgment" rule as the markdown contract: rewrite the targeted step to be clearer about its actual topic, or rewrite the neighboring step, or both.

**`kind: "diagram"` (Mermaid) blocks** have no per-step targeting at all: a
comment always arrives with `step_id: null` and applies to the whole diagram.
Rewrite `spec.source` (and `spec.title` if warranted) to fold in the answer,
then persist with `blocks.update_spec_block(doc, block_id, new_spec)` — the same
content-hash-safe helper used for sequence specs — then `save_atomic` and re-push. To convert
a diagram to/from prose, treat it as a kind change (drop `kind`/`spec`, set
`markdown`) exactly as for other spec blocks.

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

If the user says "scrap it" / "respond in terminal" / "stop annotating" / equivalent *while a watcher is armed* (the pending registry has entries):

1. Read `~/.claude/annotate/pending-${CLAUDE_CODE_SESSION_ID}.json`.
2. For each entry, cancel the session: `webcompanion end --sid <sid> --cancel`
   ```bash
   printf '{"reason":"user-cancelled-terminal"}' > "$STATE_DIR/cancelled"
   ```
   The server's existing `_terminal_state` check only tests existence, so the body is optional but useful for debugging.
3. The watcher detects the marker on its next tick and emits `WEBCOMPANION_CANCELLED`. You'll get a task-notification for each.
4. Handle each cancellation per Mode D and clean up the registry as that step instructs.
5. Continue with whatever the user actually wanted.

## Edge cases

- **`selected_text: ""`** — comment refers to the entire block; treat the block as the anchor.
- **Daemon unreachable** — run `webcompanion status` (see `references/pushing.md`); do not start it yourself. It will restart the server. Retry the failed request.
- **Malformed event payload** — fall back to no-op; acknowledge it anyway so the event isn't re-emitted forever.
- **`finished` or `cancelled` marker present** — the user ended the session. The watcher emits `WEBCOMPANION_FINISHED` or `WEBCOMPANION_CANCELLED`; see Mode D.

## Page-wide single-flight lock

The browser page is single-flight: while a submitted event is in flight, the page is locked (block comment / reject / dismiss affordances disabled, a "Claude is updating…" banner shown), and only one comment editor can be open at a time. The lock is now **client-side**: the page locks itself on submit and unlocks when an item actually changes, because the daemon's `/poll` does not report whether an event is still unacked. Practical consequence for you is unchanged and slightly sharper: **re-push the document when you finish handling an event**, and acknowledge it, even on a no-op or malformed payload — a run that acks without changing anything leaves the banner up until the next change.

Two deliberate softenings of the lock:

- The **general composer stays usable while busy** — its submissions queue server-side and the watcher delivers them one at a time, so you may receive a second `WEBCOMPANION_EVENT` notification while (or right after) handling the first. Handle them in order; each gets its own ack.
- The client watches the watcher heartbeat (`watcher_age_s` in `/poll`). If the heartbeat goes stale (the Claude session died mid-event), the page **unlocks itself** and shows a "Claude's session is gone" warning instead of spinning forever. Events submitted in that state stay queued on disk; a freshly armed watcher for the same session directories will re-emit them.
