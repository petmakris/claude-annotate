---
name: annotate-doctor
description: Check that this machine can run claude-annotate and claude-ide-review — python3 and its version, curl, state directory permissions, and server health. Invoked only when the user types `/annotate-doctor`, or when a skill's preflight has just failed and the user asks why. Never self-triggers. Reports problems and prints the command the user should run; never installs anything.
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
# 3. Marketplace cache layout, last.
if [ -z "$DOCTOR" ]; then
  for candidate in "$HOME"/.claude/plugins/cache/*/claude-annotate*/; do
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
access to it (only in hook contexts), and finally checks the marketplace cache layout.
Searching by marker file rather than directory name means it survives clones under
any directory name.

## Report

Show the user the output verbatim — it is already written for a human, and
paraphrasing loses the exact commands. Then add one sentence naming the single
most important thing to fix, if anything failed.

Do **not** run any remedy yourself. The commands it prints install software or
change permissions on the user's machine; those are theirs to run. Offer to
explain a line if they want, and stop there.

If every check passes but the user still sees a problem, the useful next
questions are which skill they invoked, and what the terminal showed.
