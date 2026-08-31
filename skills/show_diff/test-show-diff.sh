#!/usr/bin/env bash
# Tests for show-diff.sh, run by hand: ./skills/show_diff/test-show-diff.sh
#
# The script's whole job is to reach VS Code and webcompanion, so every case here runs it
# against stubs for `code`, `open`, `osascript` and `webcompanion` placed ahead of the real
# ones on PATH. The stub `open` records the URI it was handed, which is the script's actual
# output — everything printed to the terminal is commentary on it.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/show-diff.sh"

PASS=0; FAIL=0
assert_eq() { # expected actual msg
  if [ "$1" = "$2" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $3"; echo "  expected [$1]"; echo "  got      [$2]"; fi
}
assert_contains() { # haystack needle msg
  case "$1" in *"$2"*) PASS=$((PASS+1));; *) FAIL=$((FAIL+1)); echo "FAIL: $3"; echo "  looked for [$2]"; echo "  in         [$1]";; esac
}

WORK="$(mktemp -d /tmp/show_diff_test.XXXXXX)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# --- the stubs -------------------------------------------------------------------------
# `code` must answer --list-extensions with the id the script insists on, or it refuses
# before reaching anything worth testing.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/code" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "--list-extensions" ]; then echo "petros-makris.petros-makris-vscode"; fi
exit 0
STUB
cat > "$BIN/open" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$1" >> "$SHOW_DIFF_TEST_URIS"
# Stand in for the real extension: it fires a "diff" verdict into PMDIFF_LOG the moment
# it handles the URI. Without this, verdict() polls a log line that never arrives and
# show-diff.sh burns all 3 retry attempts (~40s) before giving up on every single case.
repo="$(python3 -c 'import sys, urllib.parse as u; print(u.parse_qs(u.urlparse(sys.argv[1]).query).get("repo", [""])[0])' "$1")"
python3 -c 'import json, os, sys; print(json.dumps({"repo": sys.argv[1], "event": "diff"}))' "$repo" >> "$PMDIFF_LOG"
STUB
# The script polls the front window's title until it names the project. Answering with the
# project name immediately is what keeps the test fast; answering at all is what exercises
# the branch a machine with accessibility permission takes.
cat > "$BIN/osascript" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$SHOW_DIFF_TEST_WINDOW"
STUB
# Stands in for the real `webcompanion` CLI so this test never needs a live daemon — a
# fresh clone or CI box has neither. `push --eval` mints a session id and a real state
# dir (under $WC_TEST_STATE_DIR) and prints plain KEY=value lines, the same shape the
# real CLI's --eval produces, which is what makes `eval "$WC_OUT"` in show-diff.sh work
# against it unchanged.
cat > "$BIN/webcompanion" <<'STUB'
#!/usr/bin/env bash
case "${1:-}" in
  push)
    sid="stub-$$-$RANDOM"
    state_dir="$WC_TEST_STATE_DIR/$sid"
    mkdir -p "$state_dir"
    echo "WC_SID=$sid"
    echo "WC_URL=http://127.0.0.1:3080/s/$sid/"
    echo "WC_SLUG=stub-slug"
    echo "WC_STATE_DIR=$state_dir"
    ;;
  *)
    exit 0
    ;;
esac
STUB
chmod +x "$BIN/code" "$BIN/open" "$BIN/osascript" "$BIN/webcompanion"
export PATH="$BIN:$PATH"

# --- a server with a branch, and a clone that has never fetched it ----------------------
ORIGIN="$WORK/origin"
git init -q --bare "$ORIGIN"

SEED="$WORK/seed"
git init -q -b master "$SEED"
git -C "$SEED" config user.email t@t; git -C "$SEED" config user.name t
echo one > "$SEED/a.txt"; git -C "$SEED" add -A; git -C "$SEED" commit -qm one
git -C "$SEED" remote add origin "$ORIGIN"; git -C "$SEED" push -q origin master

# The base branch lives only on the server from here on.
git -C "$SEED" checkout -q -b the-base
echo two > "$SEED/b.txt"; git -C "$SEED" add -A; git -C "$SEED" commit -qm two
git -C "$SEED" push -q origin the-base

CLONE="$WORK/clone"
git clone -q --single-branch --branch master "$ORIGIN" "$CLONE"
git -C "$CLONE" config user.email t@t; git -C "$CLONE" config user.name t
echo three > "$CLONE/c.txt"; git -C "$CLONE" add -A; git -C "$CLONE" commit -qm three

export SHOW_DIFF_TEST_WINDOW="clone"
export SHOW_DIFF_TEST_URIS="$WORK/uris.txt"
export SHOW_DIFF_HISTORY="$WORK/reviews.jsonl"
export PMDIFF_LOG="$WORK/pmdiff.log"
export WC_TEST_STATE_DIR="$WORK/wc-state"
: > "$SHOW_DIFF_TEST_URIS"
: > "$PMDIFF_LOG"
mkdir -p "$WC_TEST_STATE_DIR"

have_ref() { git -C "$CLONE" rev-parse --verify --quiet "$1^{commit}" >/dev/null; }

# --- 1. the clone genuinely does not have the base yet ----------------------------------
if have_ref origin/the-base; then
  FAIL=$((FAIL+1)); echo "FAIL: precondition — the clone already has origin/the-base"
else
  PASS=$((PASS+1))
fi

# --- 2. a missing remote ref is fetched rather than refused -----------------------------
out="$("$SCRIPT" "$CLONE" origin/the-base HEAD 2>&1)"; rc=$?
assert_eq "0" "$rc" "a missing origin/ ref does not fail the run"
assert_contains "$out" "fetching" "the fetch is announced before it runs"
if have_ref origin/the-base; then PASS=$((PASS+1)); else
  FAIL=$((FAIL+1)); echo "FAIL: origin/the-base was not fetched into the clone"; fi

uri="$(tail -1 "$SHOW_DIFF_TEST_URIS")"
base_sha="$(git -C "$CLONE" rev-parse origin/the-base)"
assert_contains "$uri" "base=$base_sha" "the URI carries the sha the fetch produced"

# --- 3. a second run needs no fetch -----------------------------------------------------
out2="$("$SCRIPT" "$CLONE" origin/the-base HEAD 2>&1)"
case "$out2" in *fetching*) FAIL=$((FAIL+1)); echo "FAIL: fetched again for a ref already present";; *) PASS=$((PASS+1));; esac

# --- 4. a bare sha that does not exist still fails, with the old message -----------------
out3="$("$SCRIPT" "$CLONE" 0000000000000000000000000000000000000000 HEAD 2>&1)"; rc3=$?
assert_eq "2" "$rc3" "an unresolvable bare sha still refuses"
assert_contains "$out3" "cannot resolve" "the refusal still names what it could not resolve"
case "$out3" in *fetching*) FAIL=$((FAIL+1)); echo "FAIL: tried to fetch a bare sha";; *) PASS=$((PASS+1));; esac

# --- 5. a remote that does not exist is not fetched --------------------------------------
out4="$("$SCRIPT" "$CLONE" nosuchremote/whatever HEAD 2>&1)"; rc4=$?
assert_eq "2" "$rc4" "a rev naming an unknown remote still refuses"
case "$out4" in *fetching*) FAIL=$((FAIL+1)); echo "FAIL: tried to fetch from a remote that is not configured";; *) PASS=$((PASS+1));; esac

# --- 6. a branch the server does not have either -----------------------------------------
out5="$("$SCRIPT" "$CLONE" origin/never-existed HEAD 2>&1)"; rc5=$?
assert_eq "2" "$rc5" "a branch missing from the server still refuses"
assert_contains "$out5" "fetch was attempted" "the refusal says the fetch was already tried"

# --- 7. the first look at a branch says nothing about history ---------------------------
git -C "$CLONE" checkout -q -b under-review
echo four > "$CLONE/d.txt"; git -C "$CLONE" add -A; git -C "$CLONE" commit -qm four
first="$("$SCRIPT" "$CLONE" master under-review 2>&1)"
case "$first" in *"since you last"*) FAIL=$((FAIL+1)); echo "FAIL: reported history on a first look";; *) PASS=$((PASS+1));; esac
assert_contains "$first" "opened in VS Code" "the first look still opens"

# --- 8. reopening after new commits says how many, and which ----------------------------
echo five > "$CLONE/e.txt"; git -C "$CLONE" add -A; git -C "$CLONE" commit -qm "the fifth thing"
echo six > "$CLONE/f.txt"; git -C "$CLONE" add -A; git -C "$CLONE" commit -qm "the sixth thing"
again="$("$SCRIPT" "$CLONE" master under-review 2>&1)"
assert_contains "$again" "since you last opened" "reopening reports what moved"
assert_contains "$again" "2 new commits" "the count is the commits added since"
assert_contains "$again" "the sixth thing" "the new commit subjects are named"

# --- 9. reopening an unchanged branch says so -------------------------------------------
same="$("$SCRIPT" "$CLONE" master under-review 2>&1)"
assert_contains "$same" "unchanged since you last opened" "an unmoved branch is reported as unmoved"

# --- 10. a successful run also creates a webcompanion session ---------------------------
wc_out="$("$SCRIPT" "$CLONE" master under-review 2>&1)"
assert_contains "$wc_out" "WC_SID=" "a webcompanion session is created for the diff"
assert_contains "$wc_out" "WC_URL=" "the webcompanion URL is reported"
assert_contains "$wc_out" "WC_STATE_DIR=" "the webcompanion state dir is reported"
wc_state_dir="$(printf '%s\n' "$wc_out" | sed -n 's/^WC_STATE_DIR=//p' | tail -1)"
if [ -n "$wc_state_dir" ] && [ -s "$wc_state_dir/diff.patch" ]; then
  PASS=$((PASS+1))
else
  FAIL=$((FAIL+1)); echo "FAIL: diff.patch was not written into WC_STATE_DIR"
fi

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
