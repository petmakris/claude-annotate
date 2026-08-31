# Petros Makris — VS Code Extension

Personal VS Code customizations packaged as a single sideloadable extension. Replaces the older single-trick `petros-makris-theme` and the MPE-CSS-overwrite hacks.

## What's included

- **Editor color theme** — "Petros Makris" (dark, IntelliJ Darcula derivative). Picked from the standard Color Theme dialog (`Cmd+K Cmd+T`).
- **Markdown preview theme switcher** — command **Petros: Set Markdown Preview Theme** (`Cmd+Shift+P`). Eight themes (Catppuccin / Dracula / Rose Pine / Tokyo Night × Inter / Mono).

The extension owns its slot in `markdown.styles` (entries whose path contains `petros-makris.petros-makris-vscode-`); other entries are left untouched.

## Install

```bash
@vscode extension-install
```

This uninstalls the legacy `petros-makris.petros-makris-theme` if present and installs the new unified extension from the committed `.vsix`.

If you've changed sources and want to rebuild before installing:

```bash
@vscode extension-install --build
```

## Switch markdown theme

1. `Cmd+Shift+P` → **Petros: Set Markdown Preview Theme**
2. Pick one of the 8 themes
3. Reopen any open Markdown previews to see the change

The chosen theme is remembered across VS Code restarts and across extension version bumps (the activation handler refreshes the absolute path on startup, so version-drift doesn't break the setting).

## Rebuild after editing

After editing `src/extension.js`, `package.json`, or any of the source CSS files in `../markdown-preview/`:

```bash
./build.sh                              # produces a new petros-makris-vscode.vsix
@vscode extension-install               # installs it (no --build needed; build was just run)
```

Bump the `version` in `package.json` if you want VS Code to detect it as a new version (otherwise `--force` overwrites in place).

## Uninstall

```bash
@vscode extension-uninstall
```

This does **not** clean `markdown.styles` in your user settings — edit `settings.json` if you want to remove the entry the extension added.

## File layout

```
ide-themes/vscode/
  package.json                    manifest (themes + commands)
  src/extension.js                command + activation handler
  themes/Petros-Makris-color-theme.json  the editor color theme
  build.sh                        copy CSS + run vsce package
  install.sh, uninstall.sh        targets of the libexec/vscode/extension-* symlinks
  petros-makris-vscode.vsix       committed build output
  dist/                           gitignored; build output staging
```

## IntelliJ markdown themes

This extension does not affect IntelliJ. The IntelliJ paste flow lives in `../markdown-preview/README.md` and is invoked via `@intellij mdtheme <name>`.
