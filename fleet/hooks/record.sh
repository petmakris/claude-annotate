#!/bin/sh
# SessionStart, UserPromptSubmit, Stop, SessionEnd: note the session in the history (not on a prompt) and in the
# session index's journal. Reads the hook input once. Never fails a session: always exit 0.
[ -z "$FLEET_NO_RECORD" ] || exit 0
here="$(dirname "$0")/.."
input=$(cat)
case "$input" in
    *'"UserPromptSubmit"'*) ;;
    *) printf '%s' "$input" | python3 "$here/fleet.py" hook-record >/dev/null 2>&1 ;;
esac
printf '%s' "$input" | python3 "$here/fleet_index_hook.py" >/dev/null 2>&1
exit 0
