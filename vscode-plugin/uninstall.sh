#!/usr/bin/env bash
# desc: remove the petros-makris-vscode extension from VS Code
# example: @vscode extension-uninstall
# complete: none
# Remove the petros-makris-vscode extension from VS Code.
#
# Note: this does not clean up any markdown.styles entries the extension
# may have added to your VS Code user settings. Edit settings.json if
# you want to remove them.

set -euo pipefail

if ! command -v code >/dev/null 2>&1; then
  echo "Error: 'code' CLI not in PATH." >&2
  exit 1
fi

if code --list-extensions 2>/dev/null | grep -q '^petros-makris.petros-makris-vscode$'; then
  code --uninstall-extension petros-makris.petros-makris-vscode >/dev/null
  echo "  removed petros-makris.petros-makris-vscode"
else
  echo "  not installed; nothing to do"
fi
