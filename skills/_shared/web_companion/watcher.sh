#!/usr/bin/env bash
# Persistent per-session watcher.  Emits one stdout banner per event in
# $EVENTS_DIR; exits when $STATE_DIR/finished or $STATE_DIR/cancelled exists.
#
# Required env:
#   SKILL, SID, STATE_DIR, EVENTS_DIR, CONSUMED_DIR
#
# Optional env:
#   CLAUDE_SID - the arming Claude Code session's id. When set, each
#     heartbeat also writes $STATE_DIR/watchers/$CLAUDE_SID.hb, so
#     the server can count distinct live Claude sessions attached to
#     one shared workspace (see attached_count in annotate/server.py).
#     Unset is fine — the watcher still works, it just won't be counted.

set -u

: "${SKILL:?}"; : "${SID:?}"; : "${STATE_DIR:?}"; : "${EVENTS_DIR:?}"; : "${CONSUMED_DIR:?}"

mkdir -p "$EVENTS_DIR" "$CONSUMED_DIR"

# Write one heartbeat, atomically.
#
# `date +%s > file` truncates the target FIRST and only fills it once the
# forked `date` has run — leaving the file empty for milliseconds on every
# beat (measured: ~0.6% of reads land in that window). A reader that catches
# it empty sees "no heartbeat ever written", which /poll reads as a dead
# session; the IDE then latches read-only on a session that is very much
# alive. Write to a private temp in the same directory and rename(2) over the
# target instead, so every reader sees either the old beat or the new one.
# The temp name carries $$ because several watchers may share one STATE_DIR.
beat() {
  _now=$(date +%s)
  _tmp="$STATE_DIR/.watcher_heartbeat.$$.tmp"
  if printf '%s\n' "$_now" > "$_tmp" 2>/dev/null; then
    mv -f "$_tmp" "$STATE_DIR/watcher_heartbeat" 2>/dev/null || rm -f "$_tmp"
  fi
  if [ -n "${CLAUDE_SID:-}" ]; then
    mkdir -p "$STATE_DIR/watchers"
    # Dot-prefixed and not *.hb, so an in-flight temp is never counted as an
    # attached session by attached_count()'s watchers/*.hb glob.
    _wtmp="$STATE_DIR/watchers/.hb.$$.tmp"
    if printf '%s\n' "$_now" > "$_wtmp" 2>/dev/null; then
      mv -f "$_wtmp" "$STATE_DIR/watchers/$CLAUDE_SID.hb" 2>/dev/null || rm -f "$_wtmp"
    fi
  fi
}

while [ ! -f "$STATE_DIR/finished" ] && [ ! -f "$STATE_DIR/cancelled" ]; do
  # Workspace reaped (GC/retention) -> nothing left to watch. Without this
  # the loop would spin forever writing heartbeats into a void.
  if [ ! -d "$STATE_DIR" ]; then
    printf 'WEBCOMPANION_CANCELLED skill=%s sid=%s\n' "$SKILL" "$SID"
    exit 0
  fi
  beat
  # Fixed-width event-id filenames sort chronologically (see events.append).
  evt=$(ls "$EVENTS_DIR"/*.json 2>/dev/null | sort | head -n1)
  if [ -n "$evt" ]; then
    id=$(basename "$evt" .json)
    if [ -f "$CONSUMED_DIR/$id.ack" ]; then
      # Already acked (e.g. a re-emitted event that has since been handled).
      rm -f "$CONSUMED_DIR/$id.attempts"
      mv -f "$evt" "$CONSUMED_DIR/$id.json"
    else
      printf 'WEBCOMPANION_EVENT skill=%s sid=%s event_id=%s\n' "$SKILL" "$SID" "$id"
      printf '%s\n' '---payload---'
      cat "$evt"
      printf '\n%s\n' '---end---'
      for _ in $(seq 1 1800); do
        if [ -f "$CONSUMED_DIR/$id.ack" ]; then break; fi
        if [ -f "$STATE_DIR/finished" ] || [ -f "$STATE_DIR/cancelled" ]; then break; fi
        # Keep the heartbeat fresh while blocked on the ack, otherwise
        # /poll's watcher_seen_at goes stale for up to 30 min and the page
        # would wrongly look like the watcher died.
        beat
        sleep 1
      done
      if [ -f "$CONSUMED_DIR/$id.ack" ]; then
        rm -f "$CONSUMED_DIR/$id.attempts"
        mv -f "$evt" "$CONSUMED_DIR/$id.json"
      elif [ ! -f "$STATE_DIR/finished" ] && [ ! -f "$STATE_DIR/cancelled" ]; then
        # Ack timed out. Re-emit on a later loop instead of silently dropping
        # the user's request — downstream dedups by source_event_id, so re-emit
        # is safe. Bound the attempts so one perpetually-unanswered event can't
        # wedge the (serially-processed) queue behind it forever.
        n=$(cat "$CONSUMED_DIR/$id.attempts" 2>/dev/null || echo 0)
        n=$((n + 1))
        if [ "$n" -ge "${WEBCOMPANION_MAX_EMITS:-3}" ]; then
          rm -f "$CONSUMED_DIR/$id.attempts"
          mv -f "$evt" "$CONSUMED_DIR/$id.json"
          # Giving up must be loud: this banner wakes Claude one final time
          # so the user can be told their question was dropped, instead of
          # a spinner that silently vanishes.
          printf 'WEBCOMPANION_DROPPED skill=%s sid=%s event_id=%s\n' "$SKILL" "$SID" "$id"
        else
          echo "$n" > "$CONSUMED_DIR/$id.attempts"
        fi
      fi
    fi
  else
    sleep 1
  fi
done

if [ -f "$STATE_DIR/cancelled" ]; then
  printf 'WEBCOMPANION_CANCELLED skill=%s sid=%s\n' "$SKILL" "$SID"
else
  printf 'WEBCOMPANION_FINISHED skill=%s sid=%s\n' "$SKILL" "$SID"
fi
