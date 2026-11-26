# `kind: "decisions"` block

Read this when the answer ends in questions only the reader can settle. This is
the one kind for questions, one question or many (`choice` is deprecated: new
questions use `decisions`). Each decision shows Claude's suggestion with what
it gives and costs, the other ways in one line each, and three buttons: go with
the suggestion, see another way, write your own.

The reader may be tired, on a phone, and not want technical decisions. Write for
that reader. The page does the layout; your job is the words.

## When to use

- One or more questions, each with 2–4 real options, a recommendation and a reason.
- The reader answers by pressing a button (or writing), and you carry the settled ones forward.

## When NOT to use

- Several answers to pick at once (multi-select). Not covered here: it stays on `choice` for now.
- A recommendation with no open question → a sentence in `markdown`.
- A list of things to do → `jobs`.

## Block shape

    {"id": "section-N", "kind": "decisions",
     "title": "Claude suggests an answer to each of seven questions, and two are hard to undo",
     "spec": {"decisions": [
       {"id": "D1", "question": "Where should each person's test data live?",
        "change": "hard",
        "change_note": "Jobs 1 to 4 build on this. Changing it later means redoing them in all three apps.",
        "options": [
          {"id": "a", "label": "One file for each person",
           "gain": "You and Alex never edit the same file.",
           "cost": "Each app gets four files, not one.",
           "detail": "One file per person per app, like apps/shop-app/dataset/alex01.yml."},
          {"id": "b", "label": "One big file for each app",
           "gain": "All the data is in one place to read.",
           "cost": "Two people's edits can clash in git."}],
        "recommended": "a",
        "why": "You said one big file by voice. Separate files stop your edits and Alex's from clashing.",
        "switch_if": "You want to read all four people's data in one place.",
        "next": "Jobs 1 to 4 build the data files the way you pick.",
        "status": "open"},
       {"id": "D3", "question": "How do the four files start?", "change": "easy",
        "options": [ ... ], "recommended": "a", "why": "...", "next": "...",
        "status": "answered", "chosen": "a",
        "outcome": "The plan now copies today's data into four files."}
     ]}}

Decision fields:
- `id` — `D1`, `D2`, … stable across rewrites; a new decision takes the next number, a removed one is never reused. Never reorder ids.
- `question`, `why` — the question; one line of reason about the reader's situation.
- `options` — 2 to 4, ids `a`–`d` unique and stable. Each has a `label` and either `trade` (one line) or both `gain` and `cost`. `detail` is optional technical text. A decision with only `trade` still renders (one line under the label).
- `recommended` — the id of one option. Do not pre-select anything.
- `change` — `easy` (default) or `hard`. `hard` needs `change_note`: what undoing it costs.
- `switch_if` (optional) — one fact that would make another way right: "Pick this way if: …".
- `next` (optional) — one true sentence on what you do after the send.
- `status` — `open` or `answered`. Answered has `chosen` (an option id), `answer` (the reader's own words), or both, and may have `outcome` (one sentence on what changed in the plan). Open has none of these.

`gain`, `cost`, `switch_if`, `next`, `change_note` and `outcome` are plain words on one
line, at most 200 characters, no HTML; `label` at most 80; `detail` at most 300.
`blocks.py` refuses any other shape at push time, naming the field. The word
limits below are writing rules, not checks.

## What the page does

- A strip at the top counts "N of M answered", with a numbered chip per question
  (grey not decided, amber picked, blue sent, green answered, red underline for hard).
  Hard decisions come first under "Read these first"; the rest follow. With one
  decision there is no strip and no groups.
- Each open card shows "Claude suggests" with what it gives and costs, one
  "Other way" line per alternative, and the buttons. "See other way" shows each
  alternative with its own "Pick this one instead".
- A pick or the reader's own words is a **pending comment** on that decision
  (`step_id` is the decision id); it goes out only with the page's **Submit round**.
  The card then says "Picked, not sent", then "Sent, Claude is updating" while the
  page is busy, then shows what you wrote when you answer it.
- Pressing a button is the only way a decision gets an answer. Submitting a
  round with untouched decisions leaves them `open`.

## The round rules

- **Silence is never a yes.** A decision stays `open` until the reader has said
  something that settles it. No comment, no change of status, and never answer
  because your recommendation seems obvious.
- **A `Choose x: …` comment on a decision** sets `status: "answered"` and
  `chosen: "x"`, also when the decision was already answered (they changed
  their mind). Leave `answer` out unless the comment adds words.
- **A free comment that settles it** ("go with a, but keep the old file as a
  backup", or the words from "Write my own") sets `status: "answered"` and puts
  the reader's words in `answer`, close to how they said them; set `chosen` too
  only if they named an option. A comment that only questions or pushes back
  leaves it `open`: change the options, the recommendation or the why as it asks.
- **Mark a decision answered only from the reader's own words.** Never write
  your recommendation into `chosen` or `answer`. After answering, set `outcome`
  from their pick or words only. Never praise.
- **A comment on a decision rewrites that decision only.** Leave every other
  decision, every decision id, every option id and the order as they are; a new
  option takes the next free letter.
- To rewrite, change `spec` with `update_spec_block` (`references/handling-events.md`).

## What Claude writes

Plain, short words. One thought per sentence. No path, tool name, class name or
abbreviation outside `detail`. Every label, gain, cost and why must be understood without opening `detail`.

- **Part title** (a sentence with a verb that states the claim and counts): "Claude suggests an answer to each of seven questions, and two are hard to undo". Not "Decisions for you".
- **Question**: one plain question, at most 10 words, about what he gets or sees. "Where should each person's test data live?" Not "Dataset layout?"
- **Option label**: at most 8 words, says what he gets. "One file for each person". Not "One file per person per app, like apps/shop-app/dataset/alex01.yml".
- **gain and cost**: one short sentence each, at most 14 words, one fact each. Every option has a real cost, the suggested one too. If no cost can be named, the options are not real alternatives: merge them. Costs are in time, risk or work; a number only when the source has one. "Each app gets four files, not one." Not "Atomic per-user YAML avoids merge conflicts." and not "None."
- **why**: one sentence, at most 20 words, about the reader's situation. If you are not sure, say what would change the answer. If the suggestion goes against something they said, the first words say so.
- **switch_if**: one fact the reader can judge. "You want to read all four people's data in one place." Not "If you prefer it."
- **change and change_note**: `hard` only when undoing it later means redoing real work already built on it, and you can name that work from the plan. If unsure, mark `hard` and say so; a wrong `easy` is worse than a wrong `hard`. List hard decisions first.
- **next**: one true sentence on what you build or change after the send. Job numbers only if the plan's own job list says so, checked in the same turn.
- **outcome**: one sentence, at most 20 words, written after an answer, saying what changed in the plan.
- **Limits**: 2 to 7 decisions per block (more: split by topic, each with its own claim title). 2 to 4 options (more exist: keep the best three; "Write my own" covers the rest). Never invent a number or a cost; ask instead.
