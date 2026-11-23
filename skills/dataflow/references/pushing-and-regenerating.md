# Pushing, superseding and regenerating a dataflow

Moved out of SKILL.md. Read it when a second `/dataflow` runs in one conversation, or when the diagram must be regenerated mid-session.

**A second `/dataflow` in one conversation no longer closes the first one.**
The old per-skill server set `supersede_by_claude_session = True` so a repeat
invocation replaced the earlier session rather than leaving two armed
watchers racing. `push.py` deliberately does not pass the daemon's own
`supersede` flag (see `webcompanion_client.create_or_attach`): that flag ends
every OTHER live session of the same kind in the same repo, regardless of
which Claude conversation started it — turning it on here would also end an
unrelated concurrent conversation's dataflow trace in the same repo, which
the old flag never did. The accepted tradeoff is old sessions accumulating as
extra browser tabs rather than risking silently ending someone else's work.

**Regenerating the diagram mid-session** (the answer to a question needed a
node that is not on the diagram): rewrite the draft with the new node added —
**keep every existing node id**, since an id that disappears takes its
thread's rendering with it — re-run the validation snippet above, then re-run
the same push command with `--slug "<slug>"` added, so it lands on the page
the user already has open instead of minting a second one. `push.py` sends
`PATCH .../items {replace: true}`, which overwrites the stored `__flow__`
item wholesale, and the page redraws itself over the daemon's own live-update
stream.
