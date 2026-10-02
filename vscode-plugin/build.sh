#!/usr/bin/env bash
# Build the Petros Makris VS Code extension into a single .vsix file.
#
# - Copies the markdown preview CSS files from ../markdown-preview/ into
#   dist/markdown-themes/ so they ship inside the .vsix.
# - Runs vsce via npx (no global install required).
# - Output overwrites petros-makris-vscode.vsix in place; that file is
#   committed so a fresh machine can install without Node.

set -euo pipefail

cd "$(cd "$(dirname "$0")" && pwd)"

# markdown-preview/ is a cross-IDE resource (IntelliJ's switch-intellij.sh
# reads it too) and stays in the env repo even though this extension moved
# out of it — hence the fixed path rather than a relative one.
CSS_SRC_DIR="$HOME/projects/env/apps/ide-themes/markdown-preview"
if [[ ! -d "$CSS_SRC_DIR" ]]; then
  echo "markdown-preview theme source not found at $CSS_SRC_DIR (is env checked out there?)" >&2
  exit 1
fi
DIST_CSS_DIR="dist/markdown-themes"

rm -rf dist
mkdir -p "$DIST_CSS_DIR"

# Copy only the theme CSS files (not intellij-active.css symlink, not READMEs).
THEMES=(
  dracula-mono
  rosepine-mono
  neon-mono
  slate-light
  slate-dark
)
for t in "${THEMES[@]}"; do
  cp "$CSS_SRC_DIR/$t.css" "$DIST_CSS_DIR/$t.css"
done

# Seed the slot that contributes.markdown.previewStyles points at.
# Empty is fine — extension activation overwrites it from persisted state.
: > "$DIST_CSS_DIR/active.css"

npx --yes @vscode/vsce package --out ./petros-makris-vscode.vsix --skip-license

echo
echo "Built: $(pwd)/petros-makris-vscode.vsix"
