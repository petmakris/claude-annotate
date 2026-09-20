# Resuming a workspace

Read this when the user invokes `/annotate resume` (with or without a slug
argument), or when you're about to push a fresh response and want to check
whether this project already has a live workspace worth reusing instead of
forking a new one (the "auto-offer" below).

This is a **separate, later invocation** from the pushing pipeline — it doesn't
create content, it points the conversation's local workspace marker at an
existing session (see "Set the marker and re-arm a watcher" below), then
re-arms a watcher on it. Once the marker is set, the *next* push in this
conversation attaches to it automatically — no different from a second push
in a conversation that never left, per `references/pushing.md`.

Every step below needs the daemon's own config. `/annotate resume` reaches
this file **directly** from SKILL.md's router — it never passes through
`references/pushing.md`, so it never confirms the daemon itself. That makes
the block below this skill's first `python3` call on a resume, and it carries
its own guard for the same reason `references/pushing.md` does. This reads
`~/.claude/webcompanion/config.json` — the same file `push.py` reads — never
a per-skill `server.json`; the daemon is a separately-installed process
(`github.com/petmakris/webcompanion`), not something this plugin starts:

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.
claude-annotate is the marketplace that ships this plugin and claude-ide-review.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
SERVER_URL=$(python3 -c 'import json,os; c=json.load(open(os.path.expanduser("~/.claude/webcompanion/config.json"))); print("http://127.0.0.1:%d" % c["port"])')
```

## `/annotate resume <slug>`

1. **Look it up:**

   ```bash
   curl -sf "$SERVER_URL/api/sessions?scope=all"
   ```

   Find the row whose `"slug"` field matches the argument. Each row is
   `{sid, slug, kind, cwd, title, state, watcher_seen_at, url}` — `state` is
   `"live"`, `"finished"` or `"cancelled"`; there is no `"status"` field and no
   `"done"` value, and no `"project"` field (`cwd` is the full path).

2. **Not found, or found with `state` other than `"live"`** — tell the user
   plainly and stop. Do not create anything. A `"finished"`/`"cancelled"` row
   is a workspace the user already clicked Done/cancelled on — attaching to it
   would reopen the same directory but the page still renders "This annotation
   round is closed", so treat it the same as not-found rather than attaching:

   > *"`<slug>` isn't a live workspace. Run `/annotate resume` with no argument
   > to list this project's live workspaces, or open the browser at
   > `<SERVER_URL>/`."*

3. **Found** — there is nothing to POST. The session already exists (that's
   what step 1 just confirmed), and the daemon has no "attach" concept:
   `POST /api/sessions` always mints a brand-new session, so calling it here
   would create a stray duplicate next to the one you meant to resume, not
   reattach to it. The row from step 1 already has everything needed —
   `sid`, `slug`, `cwd`, `url` — for the marker step below.

4. **Set the conversation's workspace marker and re-arm a watcher** on the
   found `sid`. Two separate things, not one:

   - **The watcher**: follow "Arming the watcher" in `references/pushing.md`
     — `webcompanion watch --kind annotate --sid "<sid>"` via the `Monitor`
     tool, exactly as a fresh push does it.
   - **The marker**: write (or overwrite) `~/.claude/annotate/pending-${CLAUDE_CODE_SESSION_ID}.json`
     with `[{"workspace": {"sid": "<sid>", "slug": "<slug>"}}]` — this is what
     makes the *next* push in this conversation attach to this session instead
     of creating a new one. `references/pushing.md` reads this same file to
     decide whether a conversation already has a workspace; nothing else
     writes it.

5. **Announce** the slug URL: *"Resumed `<title>` → `<url>`. Comments will
   attach to this workspace from here."*

Subsequent pushes in this conversation now follow the ordinary "every push
after the first" path in `references/pushing.md` § "Push the document" (pass
`--slug`) — no special-casing needed after this point.

## `/annotate resume` (no argument)

`?cwd=<path>&kind=annotate` is an **exact-path** match against the row's own
`cwd` (the daemon does no basename resolution) and returns the same full row
shape as `?scope=all` — `push.py`'s own attach-resolution uses this exact
query, so there is nothing legacy or partial about it:

1. ```bash
   curl -sf "$SERVER_URL/api/sessions?cwd=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$PWD")&kind=annotate"
   ```
2. Keep rows where `state == "live"`. A `"finished"`/`"cancelled"` row is one
   the user already clicked Done/cancelled on — resuming one would just show
   "This annotation round is closed", so leave it out.
3. **None match** — say so and point at the alternatives:

   > *"No live annotate workspaces for this project. Open the browser at
   > `<SERVER_URL>/` to browse every project, or just push — a new workspace
   > will be created."*

4. **One or more match** — present a short list (slug, title) and ask which to
   resume, e.g.:

   > *"Live workspaces for this project: `fixing-the-flaky-test`,
   > `auth-refactor-plan`. Which one, or start a new one? You can also browse
   > all of them at `<SERVER_URL>/`."*

   Once the user names one, follow `/annotate resume <slug>` above.

Because the match is on the exact `cwd`, not a directory basename, two
projects that happen to share a basename (e.g. `backend` in two different
repos) never collide here — each row's `cwd` is unambiguous.

## Auto-offer: don't silently fork a new workspace

Before creating a fresh workspace for what looks like the first push of a
conversation (the `$WORKSPACE` marker in `references/pushing.md` is empty),
run the same `?cwd=`-filtered lookup as the no-argument case above. If it
finds any `state == "live"` row, don't create — offer the choice instead:

> *"This project already has a live annotate workspace: `<title>` (`<slug>`).
> Resume it, or start a new one?"*

- **Resume** → follow `/annotate resume <slug>` above.
- **New** → proceed with `references/pushing.md` § "Push the document" as
  normal (the first push of a conversation, so omit `--slug`); the two
  workspaces coexist (different slugs).

## Never crash on a bad slug

If `<slug>` doesn't resolve, or the server is unreachable, degrade to a plain
message and stop — same "check `webcompanion status` and retry" pattern as
`references/handling-events.md` § Edge cases for a transient failure. Never
let a resume attempt fall through into creating (or attaching to) the wrong
workspace silently.

## Where a workspace lives

`~/.claude/webcompanion/workspaces/annotate/<sid>/`, alongside the registry
that indexes it — **never** inside the directory it was created from. That is the point: a
workspace created from a throwaway git worktree used to be written into that
worktree, so removing the worktree destroyed the annotations, and the next
server start pruned the registry row too — a resume then answered 404 with
nothing left to say a workspace had ever existed.

Consequences worth knowing when resuming:

- The workspace's path no longer names its project, so `workspace.json` at the
  top of the tree records it: `{"sid", "skill", "cwd"}`. That `cwd` is the repo
  root code anchors resolve against, and `check_anchors` reads it.
- `_cwd` in the registry still means the project root, unchanged by the move.
  A workspace resumed from a different directory still belongs to the repo it
  was created in.
- Workspaces written under the old per-project layout are moved into this home
  automatically on the next server start, keeping their `sid` and `slug` — a
  resume by slug works across the move with nothing to do by hand.
- The `workspace_root` field in `~/.claude/webcompanion/config.json` relocates
  the base (the skill name is appended, so every migrated skill shares one
  volume) — not an environment variable; the daemon reads no environment
  variables at all. A relative value is ignored in favour of the default
  rather than resolved against the daemon's own cwd.
