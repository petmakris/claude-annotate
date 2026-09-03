#!/bin/sh
# Diagnose a claude-annotate / claude-ide-review install.
#
# POSIX sh on purpose: this script exists to report that python3 is missing,
# so it cannot be written in Python, and it must not need jq. It reports and
# prescribes; it never installs, symlinks, or edits PATH.
#
# Exit: 0 when every required check passes, 1 otherwise.

failures=0

ok()   { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
fix()  { printf '        %s\n' "$1"; }
info() { printf 'info  %s\n' "$1"; }

printf 'claude-annotate doctor\n'
printf 'claude-annotate is the marketplace that ships this plugin and claude-ide-review.\n\n'

# --- interpreter -----------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  version="$(python3 --version 2>&1 | tr -d '\n')"
  where="$(command -v python3)"
  major="$(python3 --version 2>&1 | sed -n 's/[^0-9]*\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1/p')"
  minor="$(python3 --version 2>&1 | sed -n 's/[^0-9]*\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\2/p')"
  # An unparseable version is a distinct failure from an old-but-valid one:
  # do not let it fall through and be reported as merely "older than 3.9".
  if [ -z "$major" ] || [ -z "$minor" ]; then
    fail "python3 — could not parse a version number from: $version ($where)"
    fix "Confirm this is really python3 by running: $where --version"
  elif [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; }; then
    ok "python3 — $version ($where)"
  else
    fail "python3 — $version is older than the required 3.9 ($where)"
    fix "macOS:  brew install python"
    fix "Linux:  install a newer python3 with your package manager"
  fi
else
  # --- the shim trap -------------------------------------------------------
  # python3 is not on the PATH we were handed, which is the PATH a hook sees.
  # Before prescribing an install, ask whether the user's LOGIN shell can find
  # one: a pyenv/asdf/conda shim added by .zshrc is invisible to a
  # non-interactive shell, so `python3 --version` works when they type it and
  # fails inside a hook. Telling that user to install Python is the wrong
  # remedy — they already have it. So the situation is settled FIRST, and
  # exactly one FAIL is printed for the one fault.
  #
  # Resolvable is not the same as runnable: macOS ships /usr/bin/python3 as an
  # Xcode Command Line Tools placeholder that `command -v` finds whether or not
  # its license has been accepted. Unaccepted, invoking it fails or pops a GUI
  # installer prompt — so we execute it non-interactively with all output and
  # stdin discarded, and treat a non-zero exit as "resolvable but not
  # functional" rather than something safe to symlink.
  #
  # </dev/null on BOTH calls: sourcing a login profile runs the user's own
  # .bash_profile, and one containing a bare `read` blocks forever on an
  # inherited terminal. And this runs only here, inside the failure branch —
  # a healthy machine never has its login profile sourced by the doctor.
  login_python=""
  if command -v bash >/dev/null 2>&1; then
    login_python="$(bash -lc 'command -v python3' </dev/null 2>/dev/null)"
  fi
  if [ -z "$login_python" ]; then
    fail "python3 — not found on PATH"
    fix "macOS:  xcode-select --install     (or: brew install python)"
    fix "Linux:  install python3 with your distribution's package manager"
    fix "Nothing needs pip: this plugin uses the standard library only."
  elif bash -lc 'python3 --version' </dev/null >/dev/null 2>&1; then
    fail "python3 — found by your login shell but NOT by a non-interactive shell"
    fix "Your shell finds it at: $login_python"
    fix "Hooks run under a non-interactive shell, which does not read your rc file."
    fix "Expose it to non-interactive shells, e.g. link it onto the default PATH:"
    fix "  sudo ln -s \"$login_python\" /usr/local/bin/python3"
    fix "Nothing needs installing: you already have a working python3."
  else
    fail "python3 — resolves to $login_python in your login shell, but that binary does not run"
    fix "This is often the macOS Xcode Command Line Tools placeholder before its"
    fix "license is accepted, or a broken pyenv/asdf shim. Do not symlink it —"
    fix "the target does not work. Install a real python3 instead:"
    fix "macOS:  xcode-select --install     (or: brew install python)"
    fix "Linux:  install python3 with your distribution's package manager"
  fi
fi

# --- other tools -----------------------------------------------------------
for tool in bash curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool — $(command -v "$tool")"
  else
    fail "$tool — not found on PATH"
    fix "Install $tool with your system's package manager."
  fi
done

# --- state directories -----------------------------------------------------
# annotate is deliberately absent: its sessions live under the daemon now
# (~/.claude/webcompanion/workspaces/annotate/), so a missing or unwritable
# ~/.claude/annotate says nothing about whether annotate works. dataflow was
# missing from this list for its whole life — a broken dataflow install
# reported as healthy because nothing here ever looked at it.
for skill in walkthrough interactive-review deck dataflow; do
  dir="$HOME/.claude/$skill"
  if [ ! -d "$dir" ]; then
    ok "$skill — no state yet (never run on this machine)"
  elif [ -w "$dir" ]; then
    ok "$skill — state directory writable ($dir)"
  else
    fail "$skill — state directory is not writable ($dir)"
    fix "chmod u+w \"$dir\""
  fi
done

# --- per-skill servers -----------------------------------------------------
# The four skills below still run a server of their own. annotate does not,
# and has not since it moved onto the daemon: it is checked by the
# webcompanion block further down instead. A stale ~/.claude/annotate/server.json
# may still be on disk from before that move — it is reported and offered for
# removal rather than probed, because nothing will ever answer on that port again.
if [ -f "$HOME/.claude/annotate/server.json" ]; then
  info "annotate — leftover server.json from before the daemon cutover"
  fix "Safe to delete: rm \"$HOME/.claude/annotate/server.json\" \"$HOME/.claude/annotate/server.pid\""
fi
for skill in walkthrough interactive-review deck dataflow; do
  info="$HOME/.claude/$skill/server.json"
  [ -f "$info" ] || continue
  url="$(sed -n 's/.*"url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$info" | head -n 1)"
  if [ -z "$url" ]; then
    fail "$skill — server.json has no url"
    fix "rm \"$info\" and run the skill again to restart the server."
  elif command -v curl >/dev/null 2>&1 && curl -sf --max-time 2 "$url/health" >/dev/null 2>&1; then
    ok "$skill — server healthy at $url"
  else
    ok "$skill — server not running (it starts on next use)"
  fi
done

# --- webcompanion -----------------------------------------------------------
# REQUIRED, and no longer merely optional: annotate ships no server of its own
# and cannot start a session without the daemon. show-diff also needs it for
# per-line VS Code comments, though show-diff alone degrades to a read-only
# diff. Because annotate hard-depends on it, "not installed" is a FAILURE
# here, not an informational note. Unlike every other check above,
# this is NOT shipped by this plugin -- it is a separate package
# (github.com/petmakris/webcompanion), installed via pipx, and nothing in
# `/plugin install` or `/plugin update` touches it, so it has to be installed
# once by hand. "installed but broken" (wrong contract, service down) is a
# failure for the same reason: something the user set up is not working.
#
# WC_REQUIRED_CONTRACT mirrors vscode-plugin/src/webcompanionClient.js:9 and
# skills/show-diff/show-diff.sh's own copy of the same constant. All three
# must move together when the contract version changes.
WC_REQUIRED_CONTRACT=1
if command -v webcompanion >/dev/null 2>&1; then
  where="$(command -v webcompanion)"
  version_out="$(webcompanion --version 2>&1 | tr -d '\n')"
  contract="$(printf '%s' "$version_out" | sed -n 's/.*(contract \([0-9][0-9]*\)).*/\1/p')"
  if [ -z "$contract" ]; then
    fail "webcompanion — installed but --version did not report a contract number: $version_out ($where)"
    fix "This is likely older than this plugin expects."
    fix "Upgrade it: pipx upgrade webcompanion"
  elif [ "$contract" != "$WC_REQUIRED_CONTRACT" ]; then
    fail "webcompanion — contract $contract does not match the $WC_REQUIRED_CONTRACT this plugin expects ($where)"
    fix "Upgrade it: pipx upgrade webcompanion"
  elif webcompanion status >/dev/null 2>&1; then
    ok "webcompanion — $version_out, service running ($where)"
  else
    fail "webcompanion — installed but the service is not running ($where)"
    fix "Start it: webcompanion install-service"
  fi
else
  fail "webcompanion — not installed; annotate cannot run without it"
  fix "Install it: pipx install webcompanion && webcompanion install-service"
fi

# --- hook wiring -----------------------------------------------------------
# The PostToolUse hook ships inside the plugin: hooks/hooks.json declares it,
# and it execs skills/annotate/hooks/progress_publish.py. If either half is
# missing the install is incomplete and reinstalling is the only remedy — no
# amount of PATH or permission fixing helps.
#
# Scope, stated plainly: this verifies the FILES of the copy actually running
# (resolved from this script's own path, not from PATH, so the answer is about
# the install being diagnosed). It does not verify that Claude Code has the
# plugin *enabled* — that lives in ~/.claude/plugins config, which is JSON and
# this script may not use jq or python3 to parse. A wrong answer there would be
# worse than none, so it is left to `/plugin` rather than half-implemented.
#
# Deliberately builtin-only (parameter expansion, cd/pwd, read, case): on a
# broken install PATH may hold almost nothing, and this check must not be the
# reason the doctor dies.
case "$0" in
  */*) doctor_dir="${0%/*}" ;;
  *)   doctor_dir="." ;;
esac
plugin_root="$(cd "$doctor_dir/../../.." 2>/dev/null && pwd)"
hooks_json="$plugin_root/hooks/hooks.json"
hook_script="$plugin_root/skills/annotate/hooks/progress_publish.py"
if [ -z "$plugin_root" ] || [ ! -f "$hooks_json" ]; then
  fail "hook — hooks/hooks.json is missing from the plugin at ${plugin_root:-$doctor_dir/../../..}"
  fix "The install is incomplete. Reinstall it:"
  fix "  /plugin  → uninstall, then install again from the claude-annotate marketplace"
  fix "  (or re-run your --plugin-dir install against a clean checkout)"
else
  hook_wired=0
  while IFS= read -r line; do
    case "$line" in
      *progress_publish.py*) hook_wired=1 ;;
    esac
  done < "$hooks_json"
  if [ "$hook_wired" -eq 0 ]; then
    fail "hook — hooks/hooks.json does not wire progress_publish.py"
    fix "This file has been edited or truncated. Reinstall the plugin:"
    fix "  /plugin  → uninstall, then install again from the claude-annotate marketplace"
  elif [ ! -f "$hook_script" ]; then
    fail "hook — hooks.json runs progress_publish.py, which is not installed"
    fix "Expected it at: $hook_script"
    fix "The install is incomplete. Reinstall the plugin:"
    fix "  /plugin  → uninstall, then install again from the claude-annotate marketplace"
  else
    ok "hook — PostToolUse wired in $plugin_root"
  fi
fi

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'All checks passed.\n'
  exit 0
fi
printf '%s check(s) failed. Fix the lines marked FAIL above, then run this again.\n' "$failures"
printf 'This tool only reports — it never installs or changes anything.\n'
exit 1
