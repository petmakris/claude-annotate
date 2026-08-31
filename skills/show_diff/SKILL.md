---
name: show-diff
description: Open code diffs in VS Code's multi-file diff editor, and never summarise them — branch against its base, a commit against the one before it, a branch against another workspace's branch, or uncommitted work including untracked files. Knows the Wealth Platform checkouts under ~/projects/wp/ through `wp diffable`, and works on any git checkout. Use when the user asks to see, show, open or review a diff, asks what a branch or a repo changed, or names things to compare. Not for reviewing a GitHub PR (that is mb-pr-review) and not for answering what the code does.
---

# show-diff

Show the user their diffs in VS Code — resolved from a phrase, or picked from the list of
everything reviewable when the user named nothing.

**One project, one window, always.** Each repository's diff goes in the VS Code window
holding that repository — never two projects' diffs in one window. This is not a
preference to weigh; it is the rule. Run the script once per project, and **wait for each
run to finish before starting the next**: VS Code hands a URI to whichever window is in
front, so overlapping runs put a diff in the wrong window. When the user names three
repositories, that is three sequential runs and three windows.

Within one project, one diff per run. If the user names two ref pairs for the same repo,
do the first and offer the second.

The two tools this skill exists to drive:

- `wp diffable [workspace] [--json]` — every checkout under `~/projects/wp/`, what branch
  it is on, what that branch is stacked on, and how many files each candidate base
  differs by. This is where the resolution comes from. Never re-derive it with raw git.
- `skills/show-diff/show-diff.sh <checkout> <base-rev> <head-rev|--worktree> [title]` —
  resolves the revs, fetching an `origin/<branch>` this clone has never seen, which is
  what the base of a stacked branch usually is. Then it opens the project's window, waits
  until that window is in front, and fires a URI the `petros-makris.petros-makris-vscode`
  extension turns into a multi-file diff editor. Every file in one scrollable view.
  `--worktree` as the head compares the files on disk to the base rev, untracked files
  included. When the head is a branch's tip it records the review in
  `~/.show-diff-reviews.jsonl`, so a later run for the same branch can say what moved.

## Procedure

1. **Read the inventory.** `wp diffable --json`, or `wp diffable <workspace> --json` when
   the user named a workspace. Scope it when you can; unscoped walks every clone.

2. **When the user named nothing, offer the inventory instead of guessing.** "show me a
   diff", "/show-diff" on its own, "what can I review" — there is no phrase to resolve, and
   the user should not have to supply one. Naming a base is the work this skill exists to
   remove.

   List one row per (checkout, base) pair, dropping every checkout whose only base is the
   trunk at distance zero — a branch standing on master has nothing to diff. Order by
   workspace, then repo, then ascending `distance`, so the closest base is the first thing
   read. Each row carries the workspace, the repo, the branch, the base `ref`, the
   distance, and the `files` count; where `wp diffable` did not compute one, say so rather
   than inventing it — it counts files for the nearest base and for the trunk, not for
   every rung between.

   Take one row, or several. Then go to step 3 for each, in sequence.

   **A workspace name on its own is a pick, not a question.** "/show-diff pmp-210" means
   every diffable checkout in that workspace, each against its own nearest base, opened in
   sequence — one window per repository. That is the natural unit of a review: a
   workspace holds one solution's work across every repo it touches, so `pmp-210` is the
   backend and the frontend halves of the same change. A ticket key is not that unit and
   must not be treated as one — PMP-281 has two solutions living in two workspaces, and
   their montblanc and benzene branches share no common name, so a ticket key alone cannot
   say which pair is meant. Ask which workspace.

   Where `wp diffable` is unavailable or reports nothing diffable, say which, and offer the
   uncommitted work in the current checkout — the other thing "show me a diff" means when
   there is no stack to pick from.

3. **Resolve the phrase to exactly one triple** — checkout path, base rev, head rev. The
   four shapes, and what each resolves to:

   - **"branch X against its base"**, "what does this branch change", "the diff for
     PMP-281 in montblanc" → the checkout whose `branch` matches, `head` = its `head`
     sha, `base` = the `sha` of its first `bases` entry (`kind: "ancestor"`). Pass the
     **`sha`**, never the `ref`.
   - **"against master"**, "everything this adds to master" → the `bases` entry with
     `kind: "trunk"`. Its `sha` is already the merge-base, so pass it as-is; passing
     `origin/master` would show master's own newer commits as deletions.
   - **"this commit against the previous one"** → `recent[0].sha` as head,
     `recent[1].sha` as base. Both are already in the inventory.
   - **"branch X in one workspace against branch Y in another"** → one checkout, two
     revs. Both revs must exist in *that* clone; `origin/<branch>` usually does, and where
     it does not the script fetches it and says so. Never fetch by hand first — the script
     already did, and a ref it could not fetch is one the server does not have.
   - **"Florian's CPT-475 branch"**, "review this PR's branch", "what is on
     origin/PICON-556" → a branch that belongs to somebody else and is in nobody's
     checkout. `wp diffable` has nothing to say about it: it reports the branches *you*
     have out. Resolve it with git instead, and read the two rules below before you do.

     Use the **`main` workspace's checkout** of the repo — `~/projects/wp/main/<repo>` —
     never one of your ticket workspaces. Every checkout of a repo shares the same origin,
     so any of them can resolve the ref, but the ticket workspaces hold work in flight and
     a review opened there puts a stranger's diff in the window where your own branch is.
     The `main` checkout is the neutral one and is the only one that should be borrowed.

     The base is `git merge-base origin/master <branch>`, passed as the **sha**. Naming
     `origin/master` instead would show master's own newer commits as deletions in
     somebody else's branch, which is the same trap the trunk rule exists for.

     Which repo, when the user did not say: ask git rather than guessing from the ticket
     prefix. `git -C ~/projects/wp/main/<repo> ls-remote --heads origin <branch>` answers
     for one repo, and the repo whose origin has the branch is the repo. Ask the user only
     when more than one does.

     Nothing is checked out and nothing is stashed. The reader's own branch stays exactly
     where it is, which is the point — a colleague's 109-file branch should cost nothing.

   - **"what I have not committed"**, "my uncommitted changes", "the diff for this repo
     before I commit" → `HEAD` as the base and `--worktree` as the head. Untracked files
     are in it, which matters: a change that adds files is exactly the change whose new
     files must be reviewed. This works in any git checkout, not only under
     `~/projects/wp/` — `wp diffable` has nothing to say about `~/projects/env`, and none
     is needed.

4. **Say what you resolved, in one line, before opening.** Checkout, base, head, file
   count. A wrong guess then costs the user one word instead of a re-explanation.

5. **Run the script, relay its output, and stop.** When the head is a branch's tip, the
   script records the review and a later run for the same branch reports what moved — "2
   new commits on X since you last opened it on 2026-08-30", with their subjects, or that
   it is unchanged. Relay those lines as they come; they are measurements, not a summary.

   It refuses rather than opening a useless window when nothing differs, when the extension
   is missing, or when a rev does not resolve even after it fetched — which means the name
   is wrong, not that the clone is behind. When it succeeds, the turn is over: see "Never
   summarise the diff" below, which is the rule this skill is most likely to break.

## Judgement calls

- **Two plausible bases.** When `bases` holds more than one `ancestor`, or the nearest
  ancestor and the trunk tell different stories, name both with their file counts and ask
  which. The PMP-281 freeze branch is the live example: stacked on
  `origin/PMP-210-CLIENT-INTERACTION-CHANNELS` it is 22 files, against `origin/master` it
  is 54, and the 32 extra files belong to the branch below it. Guessing here shows the
  user someone else's work as if it were theirs.

- **`staged`, `unstaged` or `untracked` is non-zero on a checkout being diffed by a rev
  pair.** Say so, and name the count. A diff of two commits cannot contain work that is
  only on disk, so the user is looking at less than they have. Offer the `--worktree` run
  as the follow-up.

- **`behind` is non-zero.** The local branch and its `origin/` copy disagree. Say which
  one you are diffing — the inventory's `head` is always the local commit.

- **A very large diff.** Open it anyway; the multi-file editor loads lazily. Mention the
  file count so the user knows what they are looking at.

## Arm the watcher

If the script's output included a `WC_SID=` line, comments are live for this
diff in VS Code. Arm a watcher immediately, in the same turn:

```bash
Monitor: command = "webcompanion watch --kind show-diff --sid <WC_SID>", persistent = true
description: "show-diff-review sid=<WC_SID>"
```

The watcher prints the same banners `interactive_review`'s watcher does:
`WEBCOMPANION_EVENT skill=show-diff sid=<sid> event_id=<id>` (followed by
`---payload---`, the event JSON, `---end---`), `WEBCOMPANION_FINISHED`,
`WEBCOMPANION_CANCELLED`, `WEBCOMPANION_DROPPED`. Each wakes you once; the
watcher stays alive across many questions until the session ends.

If the script's output had no `WC_SID=` line, `webcompanion` was
unreachable — the diff is open read-only and there is nothing to arm.

## Mode D — answering a question on a diff line

You wake here when a task-notification's first stdout line is one of the
`WEBCOMPANION_*` banners above, for a `skill=show-diff` session.

1. **Parse the banner** for `sid` and `event_id`. Read the payload between
   `---payload---` and `---end---`: `{"anchor": "<path>:<side>:<line>",
   "text": "<question>", "images": [...]}`.
2. **Find the session's state_dir.** You have it already if you created this
   session's watcher this turn (`WC_STATE_DIR` from Task 5's output). There is
   no documented way to re-derive it later — `webcompanion` has no "look up a
   session's state_dir by sid" command — so keep the `WC_STATE_DIR` value from
   when you armed the watcher; it does not change for the life of the
   session.
3. **Read `<state_dir>/diff.patch`** and the item at anchor `__meta__`
   (`webcompanion` has no "get one item" CLI, so read it via
   `python3 -c` importing `webcompanion.client`):

   ```bash
   python3 -c '
   from webcompanion.commands._common import client_from_config
   import json
   print(json.dumps(client_from_config().get_item("<sid>", "__meta__")["body"]))
   '
   ```

   This gives `{"checkout": ..., "base": ..., "head": ...}` — use `checkout`
   to `Read`/`Grep` surrounding source for context beyond the diff hunk.
4. **Compose a short, code-aware answer** in markdown, 2-4 sentences
   typically, fenced code blocks for snippet suggestions. If you spot a real
   bug, flag it and suggest a fix as a code block — never modify the
   checkout itself, this is a read-only review view exactly like
   `interactive_review`.
5. **Write the answer to a file, then post it** — never interpolate the
   answer into a shell command; it may contain backticks, quotes, or
   `$(...)`:

   ```bash
   webcompanion reply --sid <sid> --anchor "<anchor>" --text <path-to-answer-file>
   ```

## Never summarise the diff

**This skill opens a diff and stops.** After the script reports, say nothing about what the
change does, means, or is for. No overview, no "what you're looking at", no grouping of the
files into themes, no naming of the idea behind them, no note about which file is the
interesting one. Not as a courtesy, not as an opener, not in one line.

This governs the turn the diff opens, before anyone has asked anything. Mode D above answers
a question the user actually asked about one line — that is not a summary of the diff, and
this rule does not reach it.

The reason is not tone, it is truth. Everything available at this point is filenames and
counts, and a filename is not evidence: `InteractionChannelNames` reads like a second new
type beside `InteractionChannelName`, and it is a utility class holding two static
functions that nothing ever instantiates. A summary written from names is confidently wrong
in exactly the places the user cannot check without reading the code — which is what he
opened the diff to do. Handing him a wrong frame first means he reads the change looking
for what you told him was there.

What may be reported, because a tool measured it rather than a name suggested it:

- the resolution — checkout, base, head, and where the base came from
- the counts the script and `wp diffable` printed: total files, files per status, commit
  distance, `staged`/`unstaged`/`untracked`, `ahead`/`behind`
- the file paths themselves, listed, if the user asks for the list

Nothing else. A path is a path; the moment it becomes "the database change" or "the new
idea", it is a summary.

If the user wants to know what the change does, he will ask, and it is answered separately
and only from the code read at `file:line` — never from the diff's shape.
