# Resuming a workspace

Read this when the user invokes `/annotate resume` (with or without a slug
argument), or when you're about to push a fresh response and want to check
whether this project already has a live workspace worth reusing instead of
forking a new one (the "auto-offer" below).

This is a **separate, later invocation** from the pushing pipeline — it doesn't
create content. It records an existing session in this conversation's marker,
rebuilds the working `blocks.json` from what the page holds, and re-arms a
watcher. After that, the next push attaches to it like any second push in a
conversation that never left (`references/pushing.md`, `--slug <slug>`).

Every command here is `claude-annotate <command>` (see `references/pushing.md`
§ "The helper command"). None of them needs a variable from an earlier Bash
call: write the values each one prints into the next one literally.

## `/annotate resume <slug>`

1. **Look it up:**

   ```bash
   claude-annotate session lookup --slug <slug>
   ```

   It prints `{"index": <daemon's list page>, "sessions": [rows]}`. Each row is
   `{sid, slug, kind, cwd, title, state, watcher_seen_at, url}` — `state` is
   `"live"`, `"finished"` or `"cancelled"`, and `cwd` is the full path of the
   repo the session was created in.

2. **Not found (`sessions` is empty), or found with `state` other than
   `"live"`** — tell the user plainly and stop. Do not create anything. A
   `"finished"`/`"cancelled"` row is a workspace the user already clicked
   Done/cancelled on — attaching to it would reopen the same directory but the
   page still renders "This annotation round is closed", so treat it the same
   as not-found rather than attaching:

   > *"`<slug>` isn't a live workspace. Run `/annotate resume` with no argument
   > to list this project's live workspaces, or open `<index>` in the browser."*

3. **Found** — there is nothing to POST. The session already exists (that's
   what step 1 just confirmed), and the daemon has no "attach" concept:
   `POST /api/sessions` always mints a brand-new session.

4. **Record it, rebuild the working copy, and re-arm a watcher** on the found
   `sid`:

   - **The marker**, so the next push and every event turn can find it:
     ```bash
     claude-annotate session set --sid <sid> --slug <slug> --cwd "<row cwd>" --title "<row title>"
     ```
   - **The working `blocks.json`**, rebuilt from the page. Without it the next
     "edit and re-push" would start from nothing and replace the page:
     ```bash
     claude-annotate pull --sid <sid> --out <scratchpad>/blocks.json
     ```
     It also points the marker's `blocks` path at the file it wrote.
   - **The watcher**: follow "Arming the watcher" in `references/pushing.md`
     — `webcompanion watch --kind annotate --sid <sid>` via the `Monitor`
     tool, exactly as a fresh push does it.

5. **Announce** the URL: *"Resumed `<title>` → `http://localhost:<port>/s/<slug>/`.
   Comments will attach to this workspace from here."* (The port is the one in
   `index`.)

## `/annotate resume` (no argument)

1. ```bash
   claude-annotate session lookup --cwd "$PWD"
   ```
   The match is an **exact path** against each row's `cwd` (the daemon does no
   basename resolution).
2. Keep rows where `state == "live"`. A `"finished"`/`"cancelled"` row is one
   the user already clicked Done/cancelled on — resuming one would just show
   "This annotation round is closed", so leave it out.
3. **None match** — say so and point at the alternatives:

   > *"No live annotate workspaces for this project. Open `<index>` to browse
   > every project, or just push — a new workspace will be created."*

4. **One or more match** — present a short list (slug, title) and ask which to
   resume, e.g.:

   > *"Live workspaces for this project: `fixing-the-flaky-test`,
   > `auth-refactor-plan`. Which one, or start a new one? You can also browse
   > all of them at `<index>`."*

   Once the user names one, follow `/annotate resume <slug>` above.

Because the match is on the exact `cwd`, not a directory basename, two
projects that happen to share a basename (e.g. `backend` in two different
repos) never collide here — each row's `cwd` is unambiguous.

## Auto-offer: don't silently fork a new workspace

Before creating a fresh workspace for what looks like the first push of a
conversation (`claude-annotate session show` prints `[]`), run the same
`--cwd` lookup as the no-argument case above. If it finds any
`state == "live"` row, don't create — offer the choice instead:

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
