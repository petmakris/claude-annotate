#!/usr/bin/env bash
# The heartbeat must never be observable empty.
#
# Regression: watcher.sh wrote it with `date +%s > file`, which truncates the
# target and only fills it after forking `date` — leaving it empty for
# milliseconds on every beat. ask_diff's /poll read an empty file as
# "watcher never armed", fell back to the session's creation age, and declared
# a live session dead; the IDE latched that read-only and never recovered.
set -euo pipefail

ROOT="$(mktemp -d)"
trap "rm -rf $ROOT" EXIT
STATE="$ROOT/state"
EVENTS="$STATE/events"
CONSUMED="$STATE/consumed"
mkdir -p "$EVENTS" "$CONSUMED"

WATCHER="$(cd "$(dirname "$0")/.." && pwd)/watcher.sh"

(
  SKILL=test SID=sid-1 CLAUDE_SID=claude-1 \
    STATE_DIR="$STATE" EVENTS_DIR="$EVENTS" CONSUMED_DIR="$CONSUMED" \
    "$WATCHER" > /dev/null 2>&1
) &
WATCHER_PID=$!

# Wait for the first beat.
for _ in $(seq 1 40); do
  [ -s "$STATE/watcher_heartbeat" ] && break
  sleep 0.25
done

BAD=$(HB="$STATE/watcher_heartbeat" python3 - <<'PY'
import os, time
from pathlib import Path
p = Path(os.environ["HB"])
bad = total = 0
end = time.time() + 4
while time.time() < end:
    total += 1
    try:
        int(p.read_text().strip())
    except (ValueError, FileNotFoundError, OSError):
        bad += 1
print(bad)
PY
)

touch "$STATE/finished"
for _ in $(seq 1 20); do
  kill -0 $WATCHER_PID 2>/dev/null || break
  sleep 0.25
done
wait $WATCHER_PID 2>/dev/null || true

if [ "$BAD" -ne 0 ]; then
  echo "FAIL: heartbeat read empty/unparsable $BAD times — the write is not atomic"
  exit 1
fi

# The rename temps must never be left behind, and must never look like an
# attached-session heartbeat (attached_count globs watchers/*.hb).
if ls "$STATE"/.watcher_heartbeat.*.tmp >/dev/null 2>&1; then
  echo "FAIL: heartbeat temp file left behind"; exit 1
fi
if ls "$STATE"/watchers/*.tmp >/dev/null 2>&1; then
  echo "FAIL: per-session heartbeat temp left behind"; exit 1
fi
test -s "$STATE/watchers/claude-1.hb" || { echo "FAIL: per-session heartbeat missing"; exit 1; }

echo "watcher.sh heartbeat atomicity OK"
