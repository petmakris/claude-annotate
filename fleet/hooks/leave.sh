#!/bin/sh
# SessionEnd: mark a joined session left; exit at once when no store exists.
[ -f "${FLEET_HOME:-$HOME/.claude/fleet}/fleet.db" ] || exit 0
exec python3 "$(dirname "$0")/../fleet.py" hook-leave
