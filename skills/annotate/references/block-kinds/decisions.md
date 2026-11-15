# `kind: "decisions"` block

Read this when the answer ends in questions only the reader can settle, and
you have a recommendation for each. One decisions part replaces a paragraph of
"I would suggest…" and keeps every question separate, so the reader can settle
them one at a time.

## When to use

- Two or more open questions, each with your recommendation and a reason.
- The reader will answer by commenting, and you will carry the settled ones forward.

## When NOT to use

- One question with 2–4 discrete options whose pick drives the next step → `choice`.
- A recommendation with no open question → a sentence in `markdown`.
- A list of things to do → `jobs`.

## Block shape

    {"id": "section-N", "kind": "decisions", "title": "Decisions for you", "spec": {
      "decisions": [
        {"id": "D1", "question": "Keep the old export format?",
         "recommendation": "Drop it.", "why": "Nothing reads it since March.",
         "status": "open"},
        {"id": "D2", "question": "Ship behind a flag?",
         "recommendation": "Yes.", "why": "It can be turned off without a deploy.",
         "status": "answered", "answer": "Yes, flag it."}
      ]
    }}

- `id` — `D1`, `D2`, … Stable across rewrites; a new decision takes the next number, a removed one is never reused.
- `question` — what is being decided. `recommendation` and `why` — your answer and one line of reason, each on one line.
- `status` — `open` or `answered`. An answered decision carries `answer`; an open one must not.

`blocks.py` refuses any other shape at push time. The page shows open decisions
standing out (accent edge, "Open"), answered ones quieter, and makes each
decision its own comment target: `data-annotate-id` is its id, so a comment on
it, or on words inside it, arrives with that `step_id`. A small comment button
on each decision comments without selecting words. The part takes no `code`
anchors.

## The rules

- **Silence is never a yes.** A decision stays `open` until the reader has said
  something that settles it. No comment, no change of status.
- **Mark a decision `answered` only from the reader's own words.** Put what they
  said in `answer`, close to how they said it. Never fill `answer` with your
  recommendation, and never answer for them because the recommendation seems obvious.
- **A comment on a decision rewrites that decision only.** Change its question,
  recommendation, why, status or answer as the comment asks; leave every other
  decision, every id and the order as they are. If the comment settles it, set
  `answered`; if it pushes back, change the recommendation and keep it `open`.
- To rewrite, change `spec` with `update_spec_block` (`references/handling-events.md`).
