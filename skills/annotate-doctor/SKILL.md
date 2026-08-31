---
name: annotate-doctor
description: Check that this machine can run claude-annotate and claude-ide-review — python3 and its version, curl, state directory permissions, server health, and the separately-installed webcompanion daemon show-diff depends on. Invoked only when the user types `/annotate-doctor`, or when a skill's preflight has just failed and the user asks why. Never self-triggers. Reports problems and prints the command the user should run; for webcompanion specifically, offers to run that command itself once the user confirms — every other remedy stays report-only.
allowed-tools:
  - Bash
  - Read
---

# /annotate-doctor — is this machine able to run the plugin?

Run the diagnostic and report what it says. It is POSIX `sh` and needs no
Python, which matters because the most common failure it diagnoses is Python
being absent.

## Run it

```bash
MARKER="skills/_shared/web_companion/doctor.sh"
DOCTOR=""
# 1. Every bin/ directory on PATH — covers --plugin-dir and marketplace installs.
old_ifs="$IFS"; IFS=:
for entry in $PATH; do
  case "$entry" in
    */bin)
      root="${entry%/bin}"
      if [ -f "$root/$MARKER" ]; then DOCTOR="$root/$MARKER"; break; fi
      ;;
  esac
done
IFS="$old_ifs"
# 2. CLAUDE_PLUGIN_ROOT when it happens to be exported (hooks get it; the Bash tool does not).
if [ -z "$DOCTOR" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "$CLAUDE_PLUGIN_ROOT/$MARKER" ]; then
  DOCTOR="$CLAUDE_PLUGIN_ROOT/$MARKER"
fi
# 3. Marketplace cache layout, last: cache/<marketplace>/<plugin>/<version>/.
#    Three levels, and matched by marker file rather than directory name — the
#    plugin directory is named for the PLUGIN (claude-annotate OR
#    claude-ide-review), so a name glob would miss half the installs.
if [ -z "$DOCTOR" ]; then
  for candidate in "$HOME"/.claude/plugins/cache/*/*/*/; do
    if [ -f "$candidate$MARKER" ]; then DOCTOR="$candidate$MARKER"; break; fi
  done
fi
[ -n "$DOCTOR" ] || { echo "claude-annotate: could not locate doctor.sh" >&2; exit 1; }
sh "$DOCTOR"
```

This scans `PATH` for directories ending in `bin/`, then checks whether the parent
contains our marker file. That covers both `--plugin-dir` installs (where Claude
Code adds `<plugin-root>/bin` to `PATH`) and marketplace installs (where the plugin's
`bin` is on `PATH`). It falls back to `CLAUDE_PLUGIN_ROOT` when the Bash tool has
access to it (only in hook contexts), and finally walks the marketplace cache layout
(`cache/<marketplace>/<plugin>/<version>/`) for a directory containing the marker.
In practice the first probe wins — Claude Code puts `<plugin-root>/bin` on `PATH` for
both install kinds — so the cache walk is the safety net for a trimmed `PATH`.
Every probe searches by marker file rather than directory name, so all three survive
clones under any directory name, and none of them assumes which of the two plugins
is installed.

## Report

Show the user the output verbatim — it is already written for a human, and
paraphrasing loses the exact commands. Then add one sentence naming the single
most important thing to fix, if anything failed.

Do **not** run any remedy yourself, with exactly one exception: the
`webcompanion` line, covered next. For every other FAIL — python3, bash,
curl, state directories, hooks — the commands it prints install software or
change permissions on the user's machine; those are theirs to run. Offer to
explain a line if they want, and stop there.

## Offering to fix webcompanion

`webcompanion` is the one line in this report naming something this plugin
does not ship — it lives in its own repository and is installed separately,
so it is also the one thing plausible for Claude to fix directly: the fix is
always a single `pipx` or `webcompanion` command, never a system package
manager or a permissions change. If the report's `webcompanion` line is
`info` (not installed) or `FAIL` (stale contract, or installed but the
service is not running):

1. **Ask, in one sentence**, whether to install/fix it now, naming which of
   the two it is. Do not run anything before the user answers.
2. **If they decline or don't answer yet**, stop — same as any other line in
   this report.
3. **If they agree**, run exactly the command doctor.sh printed under that
   line's `fix` text (`pipx install webcompanion && webcompanion
   install-service`, `pipx upgrade webcompanion`, or `webcompanion
   install-service` on its own) via Bash. If `pipx` itself is missing, say so
   and stop — installing `pipx` is a system package-manager action and stays
   out of scope here, same as the python3/bash/curl remedies above.
4. **Re-run the diagnostic** (the `Run it` block above) and report the new
   `webcompanion` line, not just "done" — the user should see the same kind
   of evidence the rest of this report gives them.

This is additive only: a machine that never uses `show-diff`'s comment
feature can ignore an `info` line about `webcompanion` same as before.

If every check passes but the user still sees a problem, the useful next
questions are which skill they invoked, and what the terminal showed.
