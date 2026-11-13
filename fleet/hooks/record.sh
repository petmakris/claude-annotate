#!/bin/sh
# SessionStart, Stop, SessionEnd: note the session in the history. Never fails a session: always exit 0.
[ -z "$FLEET_NO_RECORD" ] || exit 0
python3 "$(dirname "$0")/../fleet.py" hook-record >/dev/null 2>&1
exit 0
