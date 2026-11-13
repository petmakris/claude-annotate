# walkthrough edge cases and token budget

Moved out of SKILL.md. Read it when a tour hits a question that is too broad, no anchors, an empty diff, a validation failure, an unreachable daemon, a lost tour, a malformed event or a question with special characters.

## Edge cases

- **Question too broad** — would exceed 12 steps. Ask once for a narrower question;
  if refused, build the best 12-step spine and say what you dropped.
- **Zero anchors found** — nothing in the codebase matches. Do **not** write or
  push `.steps.draft.json` — there is nothing to cancel, since no session
  exists until `push.py` runs. In terminal, say what you searched for and what
  you found instead.
- **`--diff` with an empty diff** — say so; do not create a session.
- **Validation failure** — the validate step (or `push.py` itself) lists every
  problem. Fix the draft, re-run. Never skip validation by pushing an
  unvalidated document directly.
- **Daemon unreachable** — `push.py` raises `DaemonUnreachable`, printed to
  stderr with the fix. Do not try to start the daemon yourself; run
  `webcompanion status` / `webcompanion doctor` and tell the user what they
  reported.
- **Tour lost** — tours are ephemeral by design. If the session ends, say so
  plainly and offer to regenerate.
- **Malformed event payload** — no reply; run
  `webcompanion ack --sid "<sid>" --event-id "<event_id>"` directly so the
  event isn't re-emitted forever.
- **Question with special characters** — the question lives only inside
  `.steps.draft.json`, written with the `Write` tool and never interpolated
  into a shell command. Omitting `--title` on the push command (see "Validate
  and push the document") is what keeps it that way — `push.py` reads the
  question back out of the document itself instead of it being re-typed into
  a shell argument. Do not add a `--title "<question>"` argument — that
  reopens the exact quoting hazard this avoids.

## Token budget

Generation is the expensive part: read what you need to anchor steps honestly, and
stop. Each wake-up afterwards is one question on one step — answer that, 2–4
sentences, and end the turn.
