# ask_diff edge cases and token budget

Moved out of SKILL.md. Read it when a review hits a failure, a remote PR change, an empty or very large PR, or a malformed event.

## Edge cases

- **gh failure** — session creation fails with a descriptive error. Surface verbatim; don't retry.
- **Empty PR (no diff)** — the diff snapshot is empty; the IDE shows no annotatable lines. General comments (`__general__` anchor) still work.
- **PR updated locally mid-session** — a commit, rebase, amend, or checkout on
  the reviewed branch fires the installed git hook, which resyncs the diff
  and migrates every thread's anchor automatically (see "Install the
  live-sync git hooks"). A line that moved too far to relocate, or one whose
  new position collides with another thread's, is reported via an
  `anchor_orphaned` event (see `references/orphaned-anchors.md`), not silently
  dropped. This only covers *local* changes to the branch — see "Remote-side
  PR changes" below.
- **Remote-side PR changes** — if someone else pushed to the PR, or you
  pushed from another machine, nothing here notices; there is no hook for
  that. The session's diff stays as of its last local sync. Recommend the
  user restart the session if they suspect this.
- **Very large PR** — soft warning above 1 MB of diff; hard reject above 1,984 KB (just under 2 MB); files with minified lines are dropped first and listed as `omitted_files`. The user can review a narrower PR instead.
- **Malformed event payload** — no reply; run `webcompanion ack --sid "<sid>" --event-id "<event_id>"` directly so the event isn't re-emitted forever.
- **Daemon unreachable** — do not try to start it yourself; run `webcompanion status` / `webcompanion doctor` and tell the user what they reported.

## Token budget

Each event wake-up is a single question on a single anchor. Answer specifically what was asked. 2-4 sentences is right for most questions; expand only when code context genuinely requires it. The user iterates by asking more questions — don't try to anticipate them.
