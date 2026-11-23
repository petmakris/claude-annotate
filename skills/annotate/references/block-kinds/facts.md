# `kind: "facts"` block

Read this when the answer has two to six numbers or short facts the reader should
see before anything else: a key-facts strip at the top of the page.

## When to use

- The answer's headline in figures: "3 files", "2 days", "low risk".
- A strip under the title that the reader scans in a second.

## When NOT to use

- Facts that need a sentence each → bullets in `markdown`.
- Many rows of the same attributes → a table in `markdown`.
- More than six; pick the six that matter.

## Block shape

    {"id": "section-N", "kind": "facts", "title": "At a glance", "spec": {
      "facts": [
        {"value": "3 files", "label": "change"},
        {"value": "2 days", "label": "estimate"},
        {"value": "low", "label": "risk"}
      ]
    }}

- `facts` — 2 to 6 entries. `value` is short (at most 20 characters), `label` names it (at most 40). Both on one line.

`blocks.py` refuses any other shape. The strip is a row of cards that wraps on a
phone. It is commented **whole**, from its title, like a picture: the reader
cannot select words in it, and a comment arrives with `step_id: null`. The part
takes no `code` anchors.

## Rewriting

A comment on the strip changes the facts it names and leaves the rest. Keep
the order unless the comment asks otherwise. Rewrite `spec` with `update_spec_block`.
