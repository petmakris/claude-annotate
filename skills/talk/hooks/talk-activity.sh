#!/bin/sh
# PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied, Stop, StopFailure: while a /talk call
# runs, show this session's tool calls on the call page, and which of them are still running.
# Exits at once when no call is running. Never fails the tool call.
state="${TALK_STATE:-${TMPDIR:-/tmp}/talk/session.json}"
[ -f "$state" ] || exit 0
python3 -c '
import json, runpy, sys
script = json.load(open(sys.argv[1])).get("activity_script")
if script:
    runpy.run_path(script, run_name="__main__")
' "$state" >/dev/null 2>&1
exit 0
