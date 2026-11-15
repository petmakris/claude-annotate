# `kind: "jobs"` block

Read this when the answer is a plan: work to be done in order, where some steps
wait on others and the reader may want to change one.

## When to use

- Three or more pieces of work with an order, a dependency or a state.
- A plan the reader will comment on job by job.

## When NOT to use

- Steps of one request over time between named parties → `sequence`.
- A checklist with no dependencies and no states → a list in `markdown`.
- Questions to settle → `decisions`.

## Block shape

    {"id": "section-N", "kind": "jobs", "title": "The work, in order", "spec": {
      "jobs": [
        {"id": "J1", "title": "Registry", "does": "One list of block kinds.",
         "after": [], "status": "done"},
        {"id": "J2", "title": "Tables", "does": "Each row is a comment target.",
         "after": ["J1"], "status": "running"},
        {"id": "J3", "title": "Docs", "does": "Update the rules.",
         "after": ["J1", "J2"], "status": "todo"}
      ]
    }}

- `id` — `J1`, `J2`, … stable across rewrites; a new job takes the next number.
- `title` — a few words. `does` — what it does, one line.
- `after` — the ids this job waits on (`[]` or left out: it starts first). Each must be a job in the part, never itself, never a loop.
- `status` — `todo`, `running`, `done` or `blocked`.

`blocks.py` refuses any other shape. The page lists the jobs in order with the
status as a pill and, under each, what it waits on ("Waits on J1, J2" or "Starts
first"). Each job is its own comment target: `data-annotate-id` is its id, so a
comment on it, or on words inside it, arrives with that `step_id`; a small button
on each job comments without selecting words. The part takes no `code` anchors.

## Rewriting

A comment on a job rewrites that job only: its title, `does`, `after` or `status`.
Keep the other jobs and every id; if an `after` changes, check no job now waits on
one that does not exist or on itself. Rewrite `spec` with `update_spec_block`
(`references/handling-events.md`).
