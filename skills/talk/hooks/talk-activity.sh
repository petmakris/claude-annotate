#!/bin/sh
# PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied, Stop, StopFailure: while a /talk call
# runs, show this session's tool calls on its call page, and which of them are still running.
# Exits at once, in sh, when no talk server is running or no call file exists: python is never started
# for a tool call of a session when nothing could be listening. Never fails the tool call.
# A server per port writes servers/<port>.json and each call calls/<id>.json; the script beside this one
# posts to every server.
run="${TALK_RUN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/talk/run}"
set -- "$run"/servers/*.json
[ -f "$1" ] || exit 0
set -- "$run"/calls/*.json
[ -f "$1" ] || exit 0
python3 "$(dirname "$0")/../talk_activity.py" >/dev/null 2>&1
exit 0
