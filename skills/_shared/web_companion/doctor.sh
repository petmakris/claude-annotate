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

printf 'claude-annotate doctor\n\n'

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
  fail "python3 — not found on PATH"
  fix "macOS:  xcode-select --install     (or: brew install python)"
  fix "Linux:  install python3 with your distribution's package manager"
  fix "Nothing needs pip: this plugin uses the standard library only."
fi

# --- the shim trap ---------------------------------------------------------
# Hooks run under a non-interactive shell. A pyenv/asdf/conda shim added by
# .zshrc is invisible there, so `python3 --version` can work when the user
# types it and fail inside a hook. No README can resolve that; detect it.
#
# Resolvable is not the same as runnable: macOS ships /usr/bin/python3 as an
# Xcode Command Line Tools placeholder that `command -v` finds whether or not
# its license has been accepted. Unaccepted, invoking it fails or pops a GUI
# installer prompt — so we execute it non-interactively with all output and
# stdin discarded, and treat a non-zero exit as "resolvable but not
# functional" rather than something safe to symlink.
login_python="$(bash -lc 'command -v python3' 2>/dev/null)"
if [ -n "$login_python" ] && ! command -v python3 >/dev/null 2>&1; then
  if bash -lc 'python3 --version' </dev/null >/dev/null 2>&1; then
    fail "python3 — found by your login shell but NOT by a non-interactive shell"
    fix "Your shell finds it at: $login_python"
    fix "Hooks run under a non-interactive shell, which does not read your rc file."
    fix "Expose it to non-interactive shells, e.g. link it onto the default PATH:"
    fix "  sudo ln -s \"$login_python\" /usr/local/bin/python3"
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
for skill in annotate walkthrough interactive-review; do
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

# --- server ----------------------------------------------------------------
for skill in annotate walkthrough interactive-review; do
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

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'All checks passed.\n'
  exit 0
fi
printf '%s check(s) failed. Fix the lines marked FAIL above, then run this again.\n' "$failures"
printf 'This tool only reports — it never installs or changes anything.\n'
exit 1
