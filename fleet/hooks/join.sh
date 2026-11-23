#!/bin/sh
# SessionStart: join the fleet when FLEET_JOIN_NAME is set; exit at once otherwise.
[ -n "$FLEET_JOIN_NAME" ] || exit 0
exec python3 "$(dirname "$0")/../fleet.py" hook-join
