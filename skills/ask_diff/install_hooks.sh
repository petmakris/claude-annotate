#!/bin/sh
# Installs post-commit/post-rewrite/post-checkout hooks in the target repo so
# a running ask_diff (interactive-review) session resyncs the instant the
# reviewed branch changes locally. Never overwrites an existing hook --
# appends behind a marker comment so a repo's own hooks (husky, lefthook,
# hand-written like montblanc's pre-push) keep working, and a second run is
# always a no-op. Refuses to write into a core.hooksPath outside .git, since
# that may be a repo-tracked, shared hooks directory rather than this
# machine's own untracked one.
#
# Marker text names the real entry point, `skills.ask_diff.sync` -- the old
# 2026-09-01 design's marker (`# claude-annotate: notify_change`) named a
# module this migration deletes; keeping that string would point at nothing.
# There is no separate `hooks/notify.sh` wrapper file (unlike that old
# design): with only one skill's hook to install here, `PYTHONPATH` is
# resolved once, at install time, from this script's own location, and
# baked into the hook body as a literal absolute path -- a git hook living
# under `.git/hooks/` has no fixed relationship to the plugin root it needs
# to import from, so *something* has to resolve that path from a location
# that does, and doing it here (once, at install time) needs one less moving
# part than doing it at hook-run time via an extra wrapper script.
#
# Usage: install_hooks.sh <repo-root>
set -eu

REPO_ROOT_ARG="${1:?usage: install_hooks.sh <repo-root>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MARKER="# claude-annotate: skills.ask_diff.sync"

REPO_ROOT="$(cd "$REPO_ROOT_ARG" && git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "install_hooks.sh: $REPO_ROOT_ARG is not inside a git repository" >&2
    exit 1
}

GIT_DIR="$(cd "$REPO_ROOT" && git rev-parse --git-dir)"
case "$GIT_DIR" in
    /*) : ;;
    *) GIT_DIR="$REPO_ROOT/$GIT_DIR" ;;
esac

HOOKS_DIR="$(cd "$REPO_ROOT" && git rev-parse --git-path hooks)"
case "$HOOKS_DIR" in
    /*) : ;;
    *) HOOKS_DIR="$REPO_ROOT/$HOOKS_DIR" ;;
esac

case "$HOOKS_DIR" in
    "$GIT_DIR"/*|"$GIT_DIR")
        : # inside .git -- untracked, always safe to write
        ;;
    *)
        echo "install_hooks.sh: core.hooksPath ($HOOKS_DIR) is outside .git — refusing to write a machine-specific hook into what may be a repo-tracked, shared hooks directory. Live sync will not work for this repo; install by hand if you want it, or unset core.hooksPath." >&2
        exit 0   # not fatal -- session creation must still succeed
        ;;
esac

mkdir -p "$HOOKS_DIR"

for hook in post-commit post-rewrite post-checkout; do
    hook_path="$HOOKS_DIR/$hook"
    if [ -f "$hook_path" ] && grep -qF "$MARKER" "$hook_path" 2>/dev/null; then
        continue  # already installed -- idempotent no-op
    fi
    if [ ! -f "$hook_path" ]; then
        printf '#!/bin/sh\n' > "$hook_path"
    fi
    {
        echo ""
        echo "$MARKER"
        echo "PYTHONPATH=\"$PLUGIN_ROOT\" python3 -m skills.ask_diff.sync >/dev/null 2>&1 &"
    } >> "$hook_path"
    chmod +x "$hook_path"
done
