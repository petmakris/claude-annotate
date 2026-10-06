#!/bin/sh
# PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied, Stop, StopFailure: while a /talk call
# runs, show this session's tool calls on its call page, and which of them are still running.
# Exits at once when no talk server is running. Never fails the tool call.
# A server per port writes servers/<port>.json; the script beside this one posts to every one of them.
servers="${TALK_RUN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/talk/run}/servers"
set -- "$servers"/*.json
[ -f "$1" ] || exit 0
python3 "$(dirname "$0")/../talk_activity.py" >/dev/null 2>&1
exit 0
