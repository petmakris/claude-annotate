#!/usr/bin/env bash
# pr-diff.sh <PR> — open a GitHub pull request's diff in IntelliJ, in the window of the
# checkout that has the PR's branch checked out.
#
# <PR> is a number, owner/repo#number, a pull-request URL, a Jira key (PMP-291) found in
# the PR title, or nothing for the PR of the current branch. Number and key forms use the
# repository of the current directory unless --repo owner/name is given.
#
# The checkout is looked for in $WP_WORKSPACE_ROOT/*/<repo> (default ~/projects/wp) and
# ~/projects/<repo>. With none on the branch, the IDE uses its last focused window of the
# repository.
set -euo pipefail

repo=""
ref=""
dry=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) ref="$1"; shift ;;
  esac
done

if [[ "$ref" =~ github\.com/([^/]+/[^/]+)/pull/([0-9]+) ]]; then
  repo="${BASH_REMATCH[1]}"; ref="${BASH_REMATCH[2]}"
elif [[ "$ref" =~ ^([^/#[:space:]]+/[^/#[:space:]]+)#([0-9]+)$ ]]; then
  repo="${BASH_REMATCH[1]}"; ref="${BASH_REMATCH[2]}"
fi
[ -n "$repo" ] || repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)

if [[ "$ref" =~ ^[A-Za-z][A-Za-z0-9]*-[0-9]+$ ]]; then
  key=$(printf %s "$ref" | tr '[:lower:]' '[:upper:]')
  ref=$(gh pr list --repo "$repo" --state all --search "$key in:title" --json number,title,state \
    --jq "[.[] | select(.title | ascii_upcase | test(\"(^|[^A-Z0-9])$key([^0-9]|$)\"))]
          | (map(select(.state == \"OPEN\")) + .) | .[0].number // empty")
  [ -n "$ref" ] || { echo "pr-diff: no PR in $repo has $key in its title" >&2; exit 1; }
fi

pr=$(gh pr view ${ref:+"$ref"} --repo "$repo" --json number,id,headRefName,title)
number=$(jq -r .number <<<"$pr")
branch=$(jq -r .headRefName <<<"$pr")

name=${repo#*/}
path=""
for d in "${WP_WORKSPACE_ROOT:-$HOME/projects/wp}"/*/"$name" "$HOME/projects/$name"; do
  [ -d "$d/.git" ] || continue
  git -C "$d" remote -v | grep -qiE "[/:]$repo(\.git)?[[:space:]]" || continue
  path=$(git -C "$d" worktree list --porcelain | awk -v b="refs/heads/$branch" '
    /^worktree /{wt=substr($0, 10)} $0 == "branch " b {print wt; exit}')
  [ -n "$path" ] && break
done

url=$(jq -r --arg repo "$repo" --arg path "$path" '
  "jetbrains://idea/ireview/pr-diff?" + ([
    "number=\(.number)", "id=\(.id | @uri)", "repo=\($repo | @uri)",
    "branch=\(.headRefName | @uri)"] + (if $path == "" then [] else ["path=\($path | @uri)"] end)
  | join("&"))' <<<"$pr")

echo "#$number $(jq -r .title <<<"$pr")"
echo "branch  $branch"
echo "window  ${path:-no checkout on $branch; the last focused $name window}"
[ -n "$dry" ] && { echo "$url"; exit 0; }
open "$url"
