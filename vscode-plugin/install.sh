#!/usr/bin/env bash
# desc: install the petros-makris-vscode extension into VS Code
# example: @vscode extension-install --build
# complete: words --build
# Install the petros-makris-vscode extension into VS Code.
#
# - Uninstalls the older one-trick `petros-makris-theme` if present.
# - Installs the unified extension from the committed .vsix.
# - With --build, rebuilds the .vsix first.

set -euo pipefail

# Resolve symlinks so this works when invoked via env/bin/ symlink.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
EXT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
VSIX="$EXT_DIR/petros-makris-vscode.vsix"

if [[ "${1:-}" == "--build" ]]; then
  "$EXT_DIR/build.sh"
fi

# A machine with no VS Code has nothing to install into, which is a skip rather
# than a failure — the same shape as os_require_macosx. Exiting non-zero here
# made `@bootstrap apps`, and therefore `@bootstrap all`, always fail on any
# headless or Linux box that will never have VS Code.
if ! command -v code >/dev/null 2>&1; then
  if [ "$(uname -s)" = "Darwin" ]; then
    palette="Cmd+Shift+P"
  else
    palette="Ctrl+Shift+P"
  fi
  echo "  VS Code:    skipped — 'code' CLI not in PATH."
  echo "              If VS Code is installed: $palette → 'Shell Command: Install code command in PATH'."
  exit 0
fi

if [[ ! -f "$VSIX" ]]; then
  echo "Error: vsix not found at $VSIX" >&2
  echo "  Run with --build to build it first." >&2
  exit 1
fi

# Uninstall the legacy single-purpose extension if it's installed.
# `code --list-extensions` is silent if missing, so check explicitly.
if code --list-extensions 2>/dev/null | grep -q '^petros-makris.petros-makris-theme$'; then
  code --uninstall-extension petros-makris.petros-makris-theme >/dev/null
  echo "  removed legacy petros-makris.petros-makris-theme"
fi

# Skip install when the same version is already loaded — VS Code refuses to
# reinstall while running, and there's nothing to do anyway.
PKG_VERSION=$(awk -F'"' '/"version":/ {print $4; exit}' "$EXT_DIR/package.json" 2>/dev/null || true)
INSTALLED_VERSION=$(code --list-extensions --show-versions 2>/dev/null \
  | awk -F'@' '/^petros-makris\.petros-makris-vscode@/ {print $2; exit}')
if [[ -n "$PKG_VERSION" && "$PKG_VERSION" == "$INSTALLED_VERSION" ]]; then
  echo "  already installed: petros-makris-vscode@$INSTALLED_VERSION (no-op)"
  echo "  bump version in package.json and rebuild if you've changed the extension."
  exit 0
fi

code --install-extension "$VSIX" --force >/dev/null
echo "  installed $(basename "$VSIX")"

# VS Code's own shortcuts differ per OS, so the instructions have to as well.
if [ "$(uname -s)" = "Darwin" ]; then
  theme_key="Cmd+K Cmd+T"; palette_key="Cmd+Shift+P"
else
  theme_key="Ctrl+K Ctrl+T"; palette_key="Ctrl+Shift+P"
fi

cat <<EOF

Next steps:
  Color theme:    $theme_key  →  "Petros Makris"
  Markdown theme: $palette_key  →  "Petros: Set Markdown Preview Theme"
EOF

# A running VS Code keeps executing the version each window loaded at startup. Reloading a
# window is NOT enough — the extension scan is cached for the life of the application, and
# the old version's folder is only swept on a full restart. Anything testing a fresh build
# against a running editor will silently exercise the previous one.
if pgrep -f "Visual Studio Code.app/Contents/MacOS" >/dev/null 2>&1; then
  cat <<'EOF'

  VS Code is running: QUIT AND RELAUNCH IT to load this build.
  Reloading a window is not enough — it re-runs the version already in memory.
EOF
fi
