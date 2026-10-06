#!/bin/sh
# PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied, Stop, StopFailure: while a /talk call
# runs, show this session's tool calls on its call page, and which of them are still running.
# Exits at once when no talk server is running. Never fails the tool call.
# A server per port writes servers/<port>.json; the script it names posts to every one of them.
servers="${TALK_RUN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/talk/run}/servers"
for state in "$servers"/*.json; do
  [ -f "$state" ] || exit 0
  python3 -c '
import json, runpy, sys
script = json.load(open(sys.argv[1])).get("activity_script")
if script:
    runpy.run_path(script, run_name="__main__")
' "$state" >/dev/null 2>&1
  exit 0
done
exit 0
