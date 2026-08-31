
 #!/usr/bin/env bash
# Open one diff in VS Code's multi-file diff editor.
#
#   show-diff.sh <checkout> <base-rev> <head-rev|--worktree> [title]
#
# `--worktree` as the head compares the files on disk to the base rev, untracked files
# included. That is the only way to review work that is not committed yet, and it is a
# different question from any pair of revs.
#
# The revs are resolved and reported here rather than inside the editor: a rev that this
# clone has never fetched is the common failure, and a shell line naming it is worth more
# than a toast in a window that may not even be in front.
#
# Two steps, in this order. The folder is opened first so the right-hand side of the diff
# can be the real file — navigable, editable — and so the diff lands in the window that
# holds the project it is about. One project, one window: `code <folder>` opens a new
# window for a folder nothing has open and focuses the existing one otherwise, so calling
# this once per project is what puts each project's diff in its own window. Then the URI
# fires, and the extension does the rest.

set -euo pipefail

REPO="${1:?usage: show-diff.sh <checkout> <base-rev> <head-rev|--worktree> [title]}"
BASE="${2:?missing base rev}"
HEAD_REV="${3:?missing head rev, or --worktree}"
TITLE="${4:-}"

WORKTREE=false
if [[ "$HEAD_REV" == "--worktree" || "$HEAD_REV" == "worktree" ]]; then
  WORKTREE=true
  HEAD_REV="worktree"
fi

EXTENSION_ID="petros-makris.petros-makris-vscode"

if [[ ! -d "$REPO/.git" ]]; then
  echo "not a checkout: $REPO" >&2
  exit 2
fi

resolve() {
  git -C "$REPO" rev-parse --verify --quiet "$1^{commit}" || true
}

# The base of a stacked branch is almost always an `origin/<branch>` that exists on the
# server and was never fetched into this clone — the branch below yours in the stack, which
# you have no reason to have checked out. Printing the fetch command and stopping made the
# reviewer run two commands to see one diff, so the script runs it.
#
# Only a rev that names a configured remote is fetched: the remote is the part before the
# first slash, and it has to be one this clone actually has. A bare sha, or a local branch
# name, carries no remote to ask, so there is nothing to try and the refusal stands.
#
# The refspec is written out in full rather than left to `git fetch <remote> <branch>`,
# which updates the remote-tracking ref only opportunistically, and only when the remote
# has the usual fetch refspec configured. Naming the destination means the ref this script
# is about to resolve is the ref the fetch just wrote.
FETCH_TRIED=false
fetch_missing() {
  local rev="$1" remote branch
  [[ "$rev" == */* ]] || return 1
  remote="${rev%%/*}"; branch="${rev#*/}"
  git -C "$REPO" remote get-url "$remote" >/dev/null 2>&1 || return 1
  echo "  fetching  $rev — this clone does not have it yet"
  FETCH_TRIED=true
  git -C "$REPO" fetch --quiet "$remote" \
    "+refs/heads/$branch:refs/remotes/$remote/$branch" 2>/dev/null || true
  return 0
}

# Sets RESOLVED rather than printing it. A `$(...)` capture runs the function in a
# subshell, where the fetch announcement would land in the captured sha and FETCH_TRIED
# would be forgotten the moment the subshell exited — so the caller reads a variable.
RESOLVED=""
resolve_or_fetch() {
  RESOLVED="$(resolve "$1")"
  if [[ -z "$RESOLVED" ]] && fetch_missing "$1"; then
    RESOLVED="$(resolve "$1")"
  fi
}

resolve_or_fetch "$BASE"; BASE_SHA="$RESOLVED"
CHECKS=("base:$BASE:$BASE_SHA")
if ! $WORKTREE; then
  resolve_or_fetch "$HEAD_REV"; HEAD_SHA="$RESOLVED"
  CHECKS+=("head:$HEAD_REV:$HEAD_SHA")
else
  HEAD_SHA="worktree"
fi
for pair in "${CHECKS[@]}"; do
  IFS=: read -r side rev sha <<<"$pair"
  if [[ -z "$sha" ]]; then
    echo "$(basename "$REPO"): cannot resolve $side '$rev' in this clone." >&2
    if $FETCH_TRIED; then
      echo "  a fetch was attempted and the ref still does not exist — check the name." >&2
    else
      echo "  fetch it:  git -C $REPO fetch origin ${rev#origin/}" >&2
    fi
    exit 2
  fi
done

if $WORKTREE; then
  # Untracked files are counted separately for the same reason the extension adds them
  # separately: `git diff` does not know about a file git has never been told about, and
  # a review of uncommitted work is the review most likely to be about new files.
  tracked=$(git -C "$REPO" diff --name-only "$BASE_SHA" | wc -l | tr -d ' ')
  new=$(git -C "$REPO" ls-files --others --exclude-standard | wc -l | tr -d ' ')
  FILES=$(( tracked + new ))
  RIGHT="working tree"
else
  FILES=$(git -C "$REPO" diff --name-only "$BASE_SHA..$HEAD_SHA" | wc -l | tr -d ' ')
  RIGHT="${HEAD_SHA:0:10}"
fi

if [[ "$FILES" == "0" ]]; then
  echo "$(basename "$REPO"): nothing differs from $RIGHT. Nothing opened."
  exit 0
fi

[[ -n "$TITLE" ]] || TITLE="$(basename "$REPO") · ${BASE_SHA:0:10}..$RIGHT · $FILES files"

# ---------------------------------------------------------------------------
# What moved since the last time this branch was opened.
#
# A review of a colleague's branch is rarely finished in one sitting: he pushes a fix, and
# the reader comes back to a diff he has already read most of, with no way to tell which
# part is new. So every run records what it opened, and a later run for the same branch
# says how far it has moved and names the commits that did it.
#
# The branch is derived from the head sha rather than taken from the caller, because the
# caller passes a sha — the skill resolves branch names through `wp diffable` and hands
# over the commit. At the moment a diff is opened the head sha is the branch's tip, so
# asking git which refs point at it recovers the name; both the recording run and the
# reading run do that for their own sha, and the two names match. A head that is not the
# tip of anything — a rev pair, a worktree diff — records nothing, which is right: there
# is no branch whose movement could be reported.
# ---------------------------------------------------------------------------

HISTORY="${SHOW_DIFF_HISTORY:-$HOME/.show-diff-reviews.jsonl}"

head_branch() {
  $WORKTREE && return 0
  git -C "$REPO" for-each-ref --format='%(refname:short)' \
    --points-at "$HEAD_SHA" refs/heads refs/remotes 2>/dev/null | head -1
}

BRANCH="$(head_branch)"
if [[ -n "$BRANCH" ]]; then
  PREV="$(REPO="$REPO" BRANCH="$BRANCH" HISTORY="$HISTORY" python3 -c '
import json, os
want = (os.environ["REPO"], os.environ["BRANCH"])
last = None
try:
    with open(os.environ["HISTORY"]) as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue                      # a truncated last line is not a reason to fail
            if (rec.get("repo"), rec.get("branch")) == want:
                last = rec
except FileNotFoundError:
    pass
print("%s %s" % (last["head"], last["at"]) if last else "")
')"
  if [[ -n "$PREV" ]]; then
    read -r prev_head prev_at <<<"$PREV"
    if [[ "$prev_head" == "$HEAD_SHA" ]]; then
      echo "  $BRANCH is unchanged since you last opened it on ${prev_at%T*}."
    else
      # `prev..head` and not the other way round: what is being reported is what arrived,
      # and a force-push that removed commits shows as zero rather than as a negative.
      n=$(git -C "$REPO" rev-list --count "$prev_head..$HEAD_SHA" 2>/dev/null || echo 0)
      echo "  $n new commit$([[ "$n" == 1 ]] || echo s) on $BRANCH since you last opened it on ${prev_at%T*}:"
      git -C "$REPO" log --format='    %h %s' --max-count=5 "$prev_head..$HEAD_SHA" 2>/dev/null || true
      [[ "$n" -gt 5 ]] && echo "    … and $(( n - 5 )) more"
    fi
  fi
fi

if ! command -v code >/dev/null 2>&1; then
  echo "the 'code' CLI is not on PATH — Cmd+Shift+P → 'Shell Command: Install code command in PATH'" >&2
  exit 2
fi
if ! code --list-extensions 2>/dev/null | grep -qx "$EXTENSION_ID"; then
  echo "$EXTENSION_ID is not installed — run: @vscode extension-install --build" >&2
  exit 2
fi

# A cold start has to load the window and activate the extension before a URI can be
# handled; a running one only has to raise a window. Firing too early is silent — the
# URI is dropped with no error anywhere — so the wait is generous when it has to be.
if pgrep -f "Visual Studio Code.app/Contents/MacOS" >/dev/null 2>&1; then
  settle=3
else
  settle=15
fi

# VS Code hands a URI to whichever of its windows is in front, and there is no way to
# address one. So the script raises this project's window and waits for it before firing.
# The title is read through System Events, which needs accessibility permission; it is
# also only the folder's basename, so two checkouts of the same repo — a ticket workspace
# and `main` — are indistinguishable by it, and the wait can end on the wrong one.
#
# The window itself knows better, and says so: the extension refuses a repo its window
# does not hold and writes `wrong-window` to ~/.pmdiff.log. That verdict, not the title,
# decides whether the diff opened. A refusal is retried, because by then `code "$REPO"`
# has created the right window and the next raise finds it.
front_window() {
  osascript -e 'tell application "System Events" to tell process "Code" to get name of front window' 2>/dev/null || true
}

WANT="$(basename "$REPO")"

raise_and_settle() {
  local wait_for="$1"
  code "$REPO"
  observed=false
  for _ in $(seq 1 "$(( wait_for * 2 ))"); do
    title="$(front_window)"
    [[ -z "$title" ]] && break
    observed=true
    [[ "$title" == *"$WANT"* ]] && break
    sleep 0.5
  done
  if ! $observed; then
    sleep "$wait_for"
  else
    sleep 1
  fi
}

URI=$(REPO="$REPO" BASE_SHA="$BASE_SHA" HEAD_SHA="$HEAD_SHA" TITLE="$TITLE" \
  EXTENSION_ID="$EXTENSION_ID" python3 -c '
import os, urllib.parse
q = urllib.parse.urlencode({
    "repo":  os.environ["REPO"],
    "base":  os.environ["BASE_SHA"],
    "head":  os.environ["HEAD_SHA"],
    "title": os.environ["TITLE"],
})
print("vscode://" + os.environ["EXTENSION_ID"] + "/diff?" + q)')

PMDIFF_LOG="${PMDIFF_LOG:-$HOME/.pmdiff.log}"

log_size() {
  if [[ -f "$PMDIFF_LOG" ]]; then wc -c <"$PMDIFF_LOG" | tr -d ' '; else echo 0; fi
}

verdict() {
  REPO="$REPO" PMDIFF_LOG="$PMDIFF_LOG" FROM="$1" python3 -c '
import json, os
repo, log = os.environ["REPO"], os.environ["PMDIFF_LOG"]
tail = ""
try:
    start = int(os.environ["FROM"])
    with open(log, "rb") as fh:
        # The extension truncates its own log at 256K; a mark past the end means it
        # rotated under us, and the whole of what is left is the honest place to look.
        fh.seek(start if start <= os.path.getsize(log) else 0)
        tail = fh.read().decode("utf-8", "replace")
except OSError:
    pass
seen = ""
for line in tail.splitlines():
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    if rec.get("repo") == repo and rec.get("event") in ("diff", "wrong-window"):
        seen = rec["event"]
print(seen)
'
}

ATTEMPTS=3
status=""
for attempt in $(seq 1 "$ATTEMPTS"); do
  mark="$(log_size)"
  raise_and_settle "$settle"
  open "$URI"
  for _ in $(seq 1 24); do
    sleep 0.5
    status="$(verdict "$mark")"
    [[ -n "$status" ]] && break
  done
  [[ "$status" == "diff" ]] && break
  if (( attempt < ATTEMPTS )); then
    if [[ "$status" == "wrong-window" ]]; then
      echo "  landed in another window holding a checkout named $WANT — raising this one and retrying"
    else
      echo "  no verdict from the extension yet — retrying"
    fi
  fi
  settle=$(( settle + 5 ))
done

if [[ "$status" != "diff" ]]; then
  echo "$WANT: the diff did not open." >&2
  if [[ "$status" == "wrong-window" ]]; then
    echo "  every attempt reached a window holding a different checkout of the same name." >&2
    echo "  bring the window for $REPO to the front, then run this again." >&2
  else
    echo "  the extension recorded nothing for this repo in $PMDIFF_LOG." >&2
    echo "  check that VS Code is running and $EXTENSION_ID is active." >&2
  fi
  exit 3
fi

# Recorded after the URI is fired, so a run that refused earlier leaves no trace claiming
# the branch was read. Appended rather than rewritten: the newest matching line wins on
# read, and an append cannot lose the file to a crash midway.
if [[ -n "$BRANCH" ]]; then
  REPO="$REPO" BRANCH="$BRANCH" HEAD_SHA="$HEAD_SHA" BASE_SHA="$BASE_SHA" \
    HISTORY="$HISTORY" python3 -c '
import json, os, datetime
rec = {
    "at":     datetime.datetime.now().isoformat(timespec="seconds"),
    "repo":   os.environ["REPO"],
    "branch": os.environ["BRANCH"],
    "head":   os.environ["HEAD_SHA"],
    "base":   os.environ["BASE_SHA"],
}
try:
    with open(os.environ["HISTORY"], "a") as fh:
        fh.write(json.dumps(rec) + "\n")
except OSError:
    pass                                      # a history that cannot be written is not a
                                              # reason to fail a diff that already opened
' || true
fi

echo "opened in VS Code: $TITLE"
echo "  checkout  $REPO"
echo "  window    ${title:-<title unreadable — accessibility permission not granted>}"
echo "  base      $BASE  (${BASE_SHA:0:10})"
if $WORKTREE; then
  echo "  head      working tree  ($tracked tracked, $new untracked)"
else
  echo "  head      $HEAD_REV  (${HEAD_SHA:0:10})"
fi
echo "  files     $FILES"
