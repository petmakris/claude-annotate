# `kind: "choice"` block

Read this when you've decided (from the kind menu in SKILL.md) that a block
should be a choice/decision block, and you need the exact contract to emit or resolve it.

## When a choice block is the right block

Emit a choice block when the response reaches a **decision point** and the next step depends on the user's preference, with ALL of:

- 2–4 discrete, comparable options (or, for multi-select, a set the user picks a subset from).
- A mostly closed answer space — picking beats free-text. (The rendered block still lets the user add a note or answer in their own words, so near-misses are fine.)
- The choice genuinely drives what you do next.

Typical fits: "which migration strategy", "which datastores to provision", "scope this to A, B, or both".

**Do NOT use a choice block for:**

- Open-ended questions where the answer isn't one of a few options (use prose + let the user comment).
- A hard gate where you must block before doing anything else — annotate is async; use the terminal `AskUserQuestion` tool for that.
- More than ~4 options, or options needing paragraphs to explain (that's prose).

One question per choice block. Need several questions? Emit several blocks.

## Block shape

A choice block looks like this in `blocks.json`:

    {"id": "section-N", "kind": "choice", "spec": {
      "question": "<the decision, one line>",
      "multiSelect": false,
      "options": [
        {"id": "o1", "label": "<terse choice>", "description": "<optional sub-text>", "recommended": true},
        {"id": "o2", "label": "...", "description": "..."}
      ]
    }}

Block id is `section-N` (assigned by `next_block_id`). Option ids are `o1`, `o2`, … minted by hand, stable across rewrites. `multiSelect: false` allows exactly one pick; `true` allows several. `description` is optional. Use 2–4 options. Mark at most ONE option `"recommended": true` — it renders as a badge on the card; never write "(recommended)" inside `description` prose.

A choice block carries no block-level `markdown` (its options may carry their own; see below), and the question is shown in the card header — don't repeat it in the spec elsewhere. The user picks in the browser and may attach a free-text note; a **note-only** submission (no pick, non-empty note) means "none of these — here's my direction". You resolve or re-propose on the watcher event.

## Options that carry content

When the options ARE content, such as two versions of a file, two SQL queries or two table
layouts, put the content in the option, not in a separate block above the question:

    {"id": "o1", "label": "Original PR", "markdown": "```java\n...\n```"}

`markdown` renders under the label with the page's normal markdown and code highlighting.
Keep `label` short: it is the option's heading. Use `description` for a one-line gloss beside
the label, and `markdown` for anything longer. The reader can select and copy text inside an
option without picking it.

Questions never nest. When one part of an option needs its own decision, give that part its
own block with its own question.

## Many similar questions: groups

When a page asks the same kind of question many times (one per file, one per finding), give
each question its own choice block and the same `group`:

    "spec": {"question": "What should Asset.java carry?", "group": "Annotation decisions", ...}

Two or more ADJACENT choice blocks with an equal `group` render as one queue: one question
at a time, with progress, Prev and Next, and a "Show all" switch. Keep a group's blocks
together; a block of another kind between them splits the queue in two. Write `group` as a
heading, because it is the queue's title. It is at most 80 characters.

A single-select pick moves the queue to the next undecided question; a multi-select question waits for the reader to press Next. While a search is active the queue shows all its questions.

Each question is still its own block: answers arrive as ordinary `choice` reactions with the
question's own `block_id`, and you rewrite or resolve one question without touching the
others.

## Resolving a choice after the user picks

See `references/handling-events.md` § "`WEBCOMPANION_EVENT` with `type: \"choice\"`".
