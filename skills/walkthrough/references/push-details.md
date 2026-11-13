# walkthrough push: cwd, title and superseding

Moved out of SKILL.md. Read it when the push fails or you wonder why `--title` is left out.

Run this from the repository you are touring, so `$PWD` really is the repo
root — `claude-annotate` never changes directory. Deliberately **omit `--title`**: `push.py`
falls back to the document's own `question` field when no title is given, and
that field already reached the daemon safely through the `Write` tool inside
`.steps.draft.json` — passing `--title "<question>"` here would re-embed the
same free-form text into a shell argument and reopen the quoting hazard the
`Write`-tool routing exists to avoid. The output is JSON: `sid`, `slug`,
`kind`, `url`, `title`. Save `sid` — you need it to arm the watcher and to
answer questions.

**One active tour per project, atomically.** `push.py` passes `supersede=True`
to the daemon: creating a new walkthrough session for this cwd ends any other
live walkthrough session for this same cwd first, in the same call — there is
no separate list-then-cancel step to run, this is automatic.
