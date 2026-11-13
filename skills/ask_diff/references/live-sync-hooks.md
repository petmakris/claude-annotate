# The live-sync git hooks

Moved out of SKILL.md. Read it when `install_hooks.sh` refuses or the user asks what the hooks do.

`install_hooks.sh` appends `post-commit`/`post-rewrite`/`post-checkout` hooks
that fire `python3 -m skills.ask_diff.sync` in the background — the mechanism
that keeps a session's diff and thread anchors from going stale after a local
commit, rebase, or amend on the reviewed branch. It never overwrites an
existing hook (appends behind its own marker) and is itself idempotent, but
checking the marker here first avoids re-running it — and re-`grep`ping every
hook file it touches — on every single invocation once it has already
succeeded once for this clone. If it refuses (a repo-tracked `core.hooksPath`
outside `.git`), it prints why and exits 0 — session creation still proceeds,
just without live sync for this repo; say so to the user in one sentence and
continue.
