# `kind: "decisions"` block

Read this when the answer ends in questions only the reader can settle. Each
decision lists its options, marks the one you recommend and says why, so the
reader sees the choices and picks with one press. One decisions part replaces a
paragraph of "I would suggest…" and keeps every question separate.

## When to use

- Two or more open questions, each with 2–4 options, a recommendation and a reason.
- The reader will answer by pressing Choose or by commenting, and you will carry the settled ones forward.

## When NOT to use

- One question whose pick drives the next step on its own → `choice`.
- A recommendation with no open question → a sentence in `markdown`.
- A list of things to do → `jobs`.

## Block shape

    {"id": "section-N", "kind": "decisions", "title": "Decisions for you", "spec": {
      "decisions": [
        {"id": "D1", "question": "How is the test data stored?",
         "options": [
           {"id": "a", "label": "One file per person per app",
            "trade": "Two people never edit the same file."},
           {"id": "b", "label": "One big file per app",
            "trade": "One place to read; edits collide."}],
         "recommended": "a", "why": "Nothing else keeps two people from colliding.",
         "status": "open"},
        {"id": "D2", "question": "Ship behind a flag?",
         "options": [{"id": "a", "label": "Yes", "trade": "Off without a deploy."},
                     {"id": "b", "label": "No", "trade": "Less code to remove later."}],
         "recommended": "a", "why": "Rollback costs nothing.",
         "status": "answered", "chosen": "a"}
      ]
    }}

- `id` — `D1`, `D2`, … Stable across rewrites; a new decision takes the next number, a removed one is never reused.
- `question` — what is being decided.
- `options` — 2 to 4. Option `id` is `a`–`d`, unique in the decision and stable across rewrites; `label` and `trade` (what it costs or buys) are one line each.
- `recommended` — the id of one option. `why` — one line of reason.
- `status` — `open` or `answered`. An answered decision has `chosen` (an option id), `answer` (the reader's own words, for an answer in between the options), or both. An open one has neither.

`blocks.py` refuses any other shape at push time. The page shows every option as
its own card inside the decision, the recommended one marked "Recommended" with
the why under it; once answered, the chosen option says "Your choice" (and the
`answer` shows) and the others are dimmed. While a decision is open each option
has a **Choose this** button. Pressing it adds a pending comment on that
decision (`step_id` is the decision id) whose text is exactly
`Choose <option id>: <label>`; it goes out with the next Submit round, like any
comment. Each decision also keeps its small comment button for a free comment.
The part takes no `code` anchors.

## The rules

- **Silence is never a yes.** A decision stays `open` until the reader has said
  something that settles it. No comment, no change of status, and never answer
  because your recommendation seems obvious.
- **A `Choose x: …` comment on a decision** sets `status: "answered"` and
  `chosen: "x"`. Leave `answer` out unless the comment adds words.
- **A free comment that settles it** ("go with a, but keep the old file as a
  backup") sets `status: "answered"` and puts the reader's words in `answer`,
  close to how they said them; set `chosen` too only if they named an option.
  A comment that only questions or pushes back leaves it `open`: change the
  options, the recommendation or the why as it asks.
- **Mark a decision answered only from the reader's own words.** Never write
  your recommendation into `chosen` or `answer`.
- **A comment on a decision rewrites that decision only.** Leave every other
  decision, every decision id, every option id and the order as they are; a new
  option takes the next free letter.
- To rewrite, change `spec` with `update_spec_block` (`references/handling-events.md`).
