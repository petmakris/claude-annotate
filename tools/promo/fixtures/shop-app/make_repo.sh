#!/bin/sh
# make_repo.sh <dest>: build the invented shop-app git repo: `main` with the
# base files, and `checkout-retry` (one commit on top) with the feature files:
# 3 files changed, 1 added. Fixed author and dates, so the shas never change.
set -eu
dest=${1:?usage: make_repo.sh <dest>}
here=$(cd "$(dirname "$0")" && pwd)
rm -rf "$dest"; mkdir -p "$dest"
cd "$dest"
export GIT_AUTHOR_NAME="Dana Example" GIT_AUTHOR_EMAIL="dana@example.com"
export GIT_COMMITTER_NAME="Dana Example" GIT_COMMITTER_EMAIL="dana@example.com"
c() { GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git -c commit.gpgsign=false commit -q -m "$2"; }
git init -q -b main
cp -R "$here/base/." .
git add -A; c "2026-03-02T09:00:00Z" "shop-app: cart, checkout and sign-in"
git checkout -q -b checkout-retry
cp -R "$here/feature/." .
git add -A; c "2026-03-03T14:30:00Z" "checkout: retry a timed-out charge with an idempotency key"
git checkout -q main
echo "$dest"
