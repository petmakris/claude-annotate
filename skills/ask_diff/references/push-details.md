# ask_diff push: what it does, its output and its errors

Moved out of SKILL.md. Read it when the push prints an error, when the diff is large, or when you need the JSON it returns.

This fetches the PR diff via `gh pr diff`/`gh pr view`, then does two things
in one call: creates (or attaches to) the daemon session for `kind=
interactive-review` at this `cwd`, and writes the diff and its metadata as
that session's `__diff__`/`__meta__` items. When `gh pr diff` refuses (GitHub
will not serve a diff over 300 files), the diff is built locally instead —
`git diff <base>...<head>` against the PR's base branch (`origin/<base>` when
this clone has it), leaving out `*.json` unless
`INTERACTIVE_REVIEW_LOCAL_EXCLUDE` names other globs. The output is JSON:

```json
{
  "sid": "...",
  "slug": "...",
  "kind": "interactive-review",
  "cwd": "...",
  "title": "...",
  "url": "http://127.0.0.1:PORT/s/<sid>/",
  "warning": "...",
  "omitted_files": ["..."]
}
```

`warning` is present only for diffs over 1 MB (annotations may be slow).
`omitted_files` is present only when files were dropped: any file whose diff
carries a line over 2,000 characters — a minified bundle, a generated page
with content inlined — is left out of the review, and its path listed here
(and in the session's `__meta__` item). Name the omitted files in the "review
session ready" sentence below so the user knows they are not in the IDE. Save
`sid`, `url`, and `title` for the rest of this turn.

**One active review per `(cwd, kind)` — enforced by `supersede=True` on this
call.** Opening a new review for this repo ends any other live
`interactive-review` session at this same `cwd` first, in the same call — no
separate list-then-cancel step. This is coarser than the pre-daemon server's
own per-Claude-session supersede: two PR reviews opened concurrently in
*different* repos from the same Claude conversation no longer auto-cancel
each other. Accepted limitation — see the plan's Known Limitations.

**gh failure:** `push.py` prints `ask_diff push: gh pr fetch failed: <error>`
to stderr and exits 1. Surface this verbatim in terminal: *"Couldn't fetch PR
diff: `<error>`. Check `gh auth status` and try again."* Do not retry.

**Diff too large:** rejected when the diff, after dropping minified files and
measured as the JSON the daemon stores, is over 1,984 KB — just under the
daemon's 2 MB item limit. `push.py` prints `ask_diff push: diff is <N> KB,
over the … limit` and exits 1 before creating any session; surface it like a
gh failure and stop. Diffs over 1 MB succeed but carry `warning`; append it to
the "review session ready" sentence below.

**Daemon unreachable/not configured:** `push.py` prints the daemon client's
own error (which names the fix — `webcompanion status` or `pipx install
webcompanion && webcompanion install-service`) and exits 1. Do not try to
start the daemon yourself.
