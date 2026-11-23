# Fleet plugin: implementation plan

Spec: `docs/superpowers/specs/2026-11-13-fleet-plugin-design.md`. Read it first; this plan only adds the
how. Everything ships on one branch, `fleet`, and lands once at the end.

## Ground rules for every slice

- **Public repo.** claude-annotate is public. No private names, hosts, companies, tickets or data in code,
  tests, docs or commit messages. Machine names come from the user's config file, never from the code.
- **Isolated plugin.** All code lives under `fleet/` at the repo root:
  - `fleet/.claude-plugin/plugin.json`
  - `fleet/fleet.py`, a stdlib-only CLI that runs on Python 3.9+
  - `fleet/hooks/hooks.json` and `fleet/hooks/*.sh`
  - `fleet/skills/fleet/SKILL.md`
  - `fleet/ui/`
  - `fleet/tests/`

  The marketplace gets a third entry, `fleet`, with `source: "./fleet"`. It must not share
  `hooks/hooks.json` with the other two plugins, and it imports nothing from `skills/`.
- **Store.** `$FLEET_HOME` (default `~/.claude/fleet/`) holds `fleet.db` (SQLite in WAL mode, with
  `busy_timeout`), `machines.json` and `ui.json`. Every test sets `FLEET_HOME` to a temp dir.
- **Never touch live sessions.** No test or manual check posts into, stops or attaches to a session the
  slice did not start itself. Scratch sessions run in scratch dirs and are stopped by exact id or pid.
  Never use `pkill`.
- **Tests.** `fleet/tests/` uses pytest. The repo's test command and `.githooks/pre-push` must run them
  too (update `CLAUDE.md` with the new command). A test that guards a fix shows two runs: failing with
  the fix removed, passing with it restored.
- **Commits.** One line, no body, no trailers.

## Slice 1: core messaging

- **Identity.** A session finds itself from `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_SOCKET`
  and the matching `~/.claude/sessions/<pid>.json`, which gives `pid`, `procStart` and `name`.
  Liveness means the pid is alive and `procStart` matches.
- **`fleet join [name]` and `fleet leave`.** Registry rows as in the spec. Names are unique among live
  members, and `join` refuses a taken name with the holder. It records the respawn command. It warns
  when `crossSessionInbound` is not `accept` in the session's effective settings.
- **`fleet ls [--json]`.** Lists members with alive or dead status.
- **`fleet tell|ask <name|*> "…"`, `fleet answer <msg-id> "…"`, `fleet wait <thread> [--timeout]`,
  `fleet thread <id>`.** Each stores the message, then posts the wake line to the target's socket (the
  Spike 1 format in the spec).
  - `from` is the sender's own session socket, and `from-name` is its fleet name.
  - The wake line names the message id and says how to answer: `/fleet answer <id> …` for an ask,
    `/fleet ack <id>` for a tell.
  - `answer` stores the answer, then wakes the asker.
  - `wait` blocks with no polling of the model. It is meant to run as a background Bash task, and exits
    when every recipient has answered or the timeout passes.
- **Auto-join.** A plugin `SessionStart` hook joins the session when `FLEET_JOIN_NAME` is set, so spawned
  sessions and job runners join without a prompt. A `SessionEnd` hook marks the member left. Both
  exit at once otherwise.
- **The skill.** `/fleet <verb>` wraps the CLI. The skill text tells the model:
  - a `tell` from a member counts as if the user typed it;
  - an `ask` gets one `fleet answer`;
  - a broadcast "who works on X" is answered from the session's own context.
- **Tests.** Store and CLI against a fake sessions dir and fake socket listeners, covering the wire
  format, broadcast fan-out, wait or timeout, name clashes and liveness. One manual end-to-end run with
  two scratch `claude --bg` sessions, with the evidence pasted.

## Slice 2: spawn and backlog

- **`fleet spawn <name> <cwd> "<prompt>"`.** Runs `claude --bg -n <name> --settings
  '{"crossSessionInbound":"accept"}'` with `FLEET_JOIN_NAME=<name>` in the environment. It refuses an
  untrusted folder with the fix. It prints the id.
- **`fleet todo add "<title>" [--ref <path|url>] [--notes …]`**, plus `todo ls`, `todo claim <id>`
  (atomic), `todo done <id>` and `todo spawn <id> [--name] [--cwd]`.
- **Tests.** Backlog states, claim races between two processes, and the spawn command line (the
  `claude` binary is stubbed with `FLEET_CLAUDE_BIN`).

## Slice 3: across machines

- **The machine list.** `machines.json` maps a machine name to `{"ssh": "<host>", "fleet": "<path to
  fleet.py there>"}`.
- **Remote commands.** A target `name@machine`, or a member found on another machine by `ls`, runs
  `ssh <host> python3 <fleet.py> <verb> …` there. `ls` and `*` fan out over every machine, with short
  timeouts. An unreachable machine is reported, never fatal.
- **`spawn --on <machine>`.**
- **Tests.** A fake `ssh` on `PATH` that runs the local CLI with a different `FLEET_HOME`.

## Slice 4: the fleet page

- **`fleet ui [--port]`.** A stdlib HTTP server, with one read-only page and JSON endpoints.
- **Members.** All machines, with name, id, machine, folder, alive or dead, and copy respawn.
- **Backlog.** To-dos and their state.
- **Threads.** Recent threads with answers.
- **Look.** Light and dark themes. Phone width works.
- **Service.** It runs as a service. Its install script lives outside this repo, in the user's
  environment repo, and the plan's final step adds it.
- **Tests.** The endpoints' JSON. Page logic is tested only where it is pure.

## Slice 5: session history

- **Recording.** A plugin hook (`SessionStart`, `Stop`, `SessionEnd`) records every session into a
  `conversations` table. Fields: id, folder, names (the newest name wins), started, last seen, ended,
  transcript path, and description.
- **Import.** `fleet history import <sqlite path>` reads an older store's `conversations` table
  read-only, and copies its rows once (it is idempotent).
- **Commands.** `fleet history ls|show|rename|delete|ask|search`:
  - `ask` answers a question from one transcript with one headless call.
  - `search` matches by meaning over descriptions.
  - `describe` fills missing descriptions in batches. It is rate-limited and on demand, with no call
    per session at start.
- **The page.** A History view: the folder tree, each row with rename, delete, ask and copy resume.
  Search by meaning is in this view too.
- **Privacy.** Transcripts and descriptions never leave `FLEET_HOME` and are never committed.

## Slice 6: outside this repo (personal repos, done after slices 1 to 5 land)

- **The page as a service.** A login item or service unit runs `fleet ui` and restarts it when it dies.
- **Machines.** Install the plugin and write `machines.json` on both machines.
- **Job runner.** A job runner that starts detached sessions exports `FLEET_JOIN_NAME=job:<NAME>` when the
  fleet plugin is installed.
- **Import.** Import an older store's conversations into the fleet store (`fleet history import`).
- **Clean-up.** Once fleet history records, the older tool's own recording is removed in its own repository.
