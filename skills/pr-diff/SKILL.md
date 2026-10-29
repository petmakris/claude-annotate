---
name: pr-diff
description: Open a GitHub pull request's diff in IntelliJ, in the window of the checkout that has the PR's branch checked out. Use when the user asks to open, show or see a PR's diff in IntelliJ or the IDE, or types /pr-diff with a PR number, a PR URL, owner/repo#number or a Jira key. Not for VS Code diffs of local branches (that is show-diff) and not for reviewing a PR in text (that is wp-pr-review).
---

# pr-diff

Run the script with whatever the user named, from the session's checkout:

    "$(claude-annotate root)/skills/pr-diff/pr-diff.sh" <PR>

`<PR>` is a number, `owner/repo#number`, a pull-request URL, a Jira key (`PMP-291`, matched
in the PR title, an open PR first), or nothing for the current branch's PR. Add
`--repo owner/name` when the user names a number of another repository.

The script prints three lines: the PR, its branch, and the window it goes to. Pass them
on as they are. The IntelliJ plugin (`claude-ide-review`, `ide-plugin/`) then:

- uses the window whose checkout is on the PR's branch, opening that checkout in a new
  window when IntelliJ has not opened it yet;
- otherwise uses the last focused window of the same repository;
- opens the GitHub plugin's "Diff for Pull Request #N" tab there at the first changed file.

When the third line says no checkout is on the branch, say so in one line: the diff
still opens, in the last focused window, but that window's files are not the PR's.

Nothing happens in the IDE when the plugin is older than this skill: rebuild it with
`cd ide-plugin && ./reload` and restart IntelliJ.
