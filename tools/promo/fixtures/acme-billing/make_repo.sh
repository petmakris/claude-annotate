#!/bin/sh
# make_repo.sh <dest>: build the invented acme-billing git repo the promo clips
# push their pages against. Fixed author and dates, so every run gives the same shas.
set -eu
dest=${1:?usage: make_repo.sh <dest>}
here=$(cd "$(dirname "$0")" && pwd)
rm -rf "$dest"; mkdir -p "$dest"
cp -R "$here/src/." "$dest/"
cd "$dest"
export GIT_AUTHOR_NAME="Dana Example" GIT_AUTHOR_EMAIL="dana@example.com"
export GIT_COMMITTER_NAME="Dana Example" GIT_COMMITTER_EMAIL="dana@example.com"
export GIT_AUTHOR_DATE="2026-03-02T10:00:00Z" GIT_COMMITTER_DATE="2026-03-02T10:00:00Z"
git init -q -b main
git add -A
git -c commit.gpgsign=false commit -q -m "invoices: store amounts in cents"
echo "$dest"
