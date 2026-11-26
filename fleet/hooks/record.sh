#!/bin/sh
# SessionStart, UserPromptSubmit, Stop, SessionEnd: note the session in the session index's journal (the one record
# of sessions, fleet/docs/session-index.md section 6). Never fails a session: always exit 0.
[ -z "$FLEET_NO_RECORD" ] || exit 0
python3 "$(dirname "$0")/../fleet_index_hook.py" >/dev/null 2>&1
exit 0
