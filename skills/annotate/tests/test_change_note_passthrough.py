"""`change_note` has to survive the trip from blocks.json to the client.

The contract (references/handling-events.md § "Explaining a change") invites
Claude to attach a `change_note` to a rewritten block, and the diff pane reads
`blk.change_note` to render it — including the `Lost:` line, which is the only
place a user can ever learn what a compact irreversibly discarded.

Between those two ends sits `_render_block_for_raw`, which builds the client
payload from a fixed set of keys. `change_note` was not one of them, so the
note was written by Claude, documented in the contract, read by the client —
and dropped in the middle. The pane's note rendering had never once run.

The smoke tests could not see this: they assert that renderDiffPane *contains*
the string "diff-lost", and it did. Nothing fed it.
"""
from skills.annotate.render import render_block


def _markdown_block(**extra):
    return dict({"id": "b-1", "kind": "markdown", "markdown": "Some prose."}, **extra)


def test_a_change_note_reaches_the_client():
    out = render_block(
        _markdown_block(change_note="Why: you marked it.\nLost: the rate limit."))
    assert out.get("change_note") == "Why: you marked it.\nLost: the rate limit."


def test_a_block_without_a_note_carries_no_empty_one():
    """The field is optional, and the pane branches on its presence.

    An always-present "" would be falsy today, but shipping a key that means
    nothing invites a later `if ("change_note" in blk)` that renders an empty
    bordered box above every diff.
    """
    assert "change_note" not in render_block(_markdown_block())


def test_an_empty_note_is_not_passed_through():
    assert "change_note" not in render_block(_markdown_block(change_note="   "))


def test_a_non_string_note_is_dropped():
    """blocks.json is model-authored, so the type is not guaranteed."""
    for junk in (5, ["Why: no"], {"why": "no"}, True):
        out = render_block(_markdown_block(change_note=junk))
        assert "change_note" not in out, f"{junk!r} reached the client"


def test_the_note_rides_along_with_a_diagram_block_too():
    """A compact can drop detail from a diagram's caption as easily as prose."""
    out = render_block(
        {
            "id": "b-2",
            "kind": "flowchart",
            "spec": {"nodes": [], "edges": []},
            "change_note": "Why: you marked it compact.",
        },
    )
    assert out.get("change_note") == "Why: you marked it compact."
