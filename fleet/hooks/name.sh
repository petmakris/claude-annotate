#!/bin/sh
# UserPromptSubmit: keep the session's Claude name and its fleet name one name; ask an unnamed interactive
# session to name itself. Never fails a prompt: always exit 0.
[ -z "$FLEET_NO_NAME" ] || exit 0
python3 "$(dirname "$0")/../fleet.py" hook-name 2>/dev/null
exit 0
