# Fleet: Claude Code sessions you join, that talk to each other

Status: implemented, 13 November 2026 (the fleet plugin, `fleet/`; this document is the design it was built from).

## Why

Work runs in several Claude Code sessions at once, and they touch each other's context. One session
installs apps on a phone while another changes which apps a development build installs. Today they
are connected by hand. You rename one session, go to the other, and ask it to message the renamed
one through Claude Code's `SendMessage`.

The fleet makes that connection a first-class thing:

- **A manager runs the day.** It starts sessions, gives each work, and collects what they report.
- **Any session can ask any other.** It can ask one session, or broadcast to all of them.
- **You can step into any session and steer it yourself.** Being in the fleet never locks you out.

## Decisions already made

- **Opt-in.** Only a session that runs `/fleet join` is in the fleet. Nothing registers on its own.
- **No stored summaries.** The fleet keeps no description of what a session is doing. "Who works on
  X" is a live broadcast question, which the sessions answer themselves, so it is never stale.
- **A separate plugin.** It is a third plugin in this marketplace, installed on its own. It has its
  own skills and does not import from talk, stage or annotate.
- **The fleet page owns session history (decided 13 November 2026).** A list of past sessions that an older
  tool kept moves here: the folder tree of every past conversation, rename, delete, ask, search by meaning,
  and the resume command. The older tool keeps no session code.
- **History and membership are two lists.** History records every session, through a hook, as the older
  tool did. Membership holds only the sessions you join. Search by meaning stores a short
  description per past session. That is history, not a summary of live work, so "who works on X" stays
  a live broadcast.
- **The live members view shows identity only.** That means each session's id, name, machine and folder,
  whether it is alive, and the command that respawns it.

## What it must do

| # | Case | Served by |
|---|---|---|
| 1 | "Which session works on X?" | `ask *`, with answers collected back to the asker |
| 2 | "Sessions on related work: organise yourselves" | `ask *`, then the asker proposes a rearrangement and `tell`s each session |
| 3 | A session records a to-do, and another session picks it up | the backlog: `todo add`, then `todo claim` or `todo spawn` |
| 4 | A manager starts sessions and drives them | `spawn` and `tell`, with `ask` for status |
| 5 | A session you open yourself joins and picks up work | `/fleet join`, then `todo claim` |
| 6 | See every session and respawn a dead one | the fleet page |

## Parts

```
 session ──/fleet join──▶  registry  ◀── fleet page (read-only, copy respawn command)
    ▲                         │
    │ wake                    ▼
 delivery  ◀── messages (tell / ask / answer / broadcast)
    ▲
 backlog (to-dos, claimed by one session)
```

### Registry

One row per joined session:

- **Identity.** `session_id`, `name` (unique among live sessions) and `host`.
- **Location.** `cwd`, plus `branch` at join.
- **Liveness.** `pid` and `proc_start`, taken from Claude Code's `~/.claude/sessions/<pid>.json`.
- **Delivery.** `socket`, from `CLAUDE_CODE_MESSAGING_SOCKET`.
- **Respawn.** `respawn`, which is `cd <cwd> && claude --resume <session_id> -n <name>`, or the
  `claude --bg …` line the session was spawned with.
- **Lifecycle.** `joined_at`, `left_at`.

A session is alive when its pid runs with the same `proc_start`. Nothing heartbeats.

A plugin `SessionEnd` hook marks a joined session left. It exits at once for a session that never joined.

### Messages

One table, with these fields:

- **Routing.** `id`, `thread`, `from`, `to` (a name, or `*`).
- **Content.** `kind` and `body`.
- **Timing.** `created_at`, `delivered_at`, `answered_at`.

The `kind` is one of:

- `tell`: an instruction. No answer is expected beyond an acknowledgement.
- `ask`: a question. Each recipient answers once into the thread.
- `answer`: the reply to an `ask`, written into the thread.

A broadcast writes one row per live member except the sender, all in one thread. The asker can wait on a
thread (`fleet wait <thread>`) and is woken when every recipient has answered or the timeout passes.

### Delivery

A message is stored first, then delivered.

Delivery wakes the target with one short line: "Fleet message 12 from manager: … Answer with
`/fleet answer 12 …`." The body stays in the store. A long message never travels in the wake line.

The wake is a post to the target's inbox socket (proved 13 November 2026, see "Spike results").
This needs no model on the sending side and no polling. It works for interactive, `claude -p` and `claude --bg`
sessions. An idle target starts a turn in 2 to 5 seconds. A busy one reads the message between tool calls.
Each member also binds its own reply socket under `/tmp/cc-socks/` and names it as the sender, so the
target can answer. The doorbell from July's mesh is kept only for a session that refuses inbound messages.

A message to a dead session waits. The page shows it as waiting, next to the respawn command.

A session that receives a `tell` from another fleet member acts on it as if you had typed it. Only you
join sessions, so a fleet member speaks for you (decided 13 November 2026).

### Backlog

To-dos with these fields:

- **Content.** `id`, `title`, `ref` (a file or link, such as a parked README) and `notes`.
- **Tracking.** `created_by`, `claimed_by`, `state` (open, claimed, done) and timestamps.

There are four commands:

- `todo add`: any member adds a to-do.
- `todo claim`: atomic. Only one session holds a to-do.
- `todo done`: closes a to-do.
- `todo spawn <id> [--on host]`: starts a new session, joins it, and claims the to-do for it.

### Spawn

`fleet spawn <name> <cwd> "<prompt>"` starts a background session whose prompt begins with
`/fleet join <name>`. It uses `claude --bg` on this machine, or the host's job runner on another
machine, so the session joins before it does anything else. `claude attach <name>` steps into it.

### Across machines

Each machine keeps its own store at `~/.claude/fleet/fleet.db` (SQLite, WAL). A command that names a
member on another machine runs `ssh <host> fleet …` there. The machine list is a config file. `ls` and
broadcast fan out over the same list. There is no central server to keep alive.

### The page

`fleet ui` serves one read-only page. It shows:

- **Members.** Name, id, host, folder, alive or dead, and a copy button for the respawn command.
- **To-dos.** Open, claimed and done.
- **Threads.** The last threads, with their answers.

The page has no write actions.

### Session history

This is a view of an older tool, rebuilt as a plugin part that imports nothing from it.

- **The record.** A plugin `SessionStart`/`Stop`/`SessionEnd` hook writes one row per conversation to
  the fleet store: id, folder, names, start and end, and transcript path. Names follow the rule that
  the newest name wins.
- **The page.** A History view beside Members: the folder tree, each row with rename, delete, ask (a
  question answered from that transcript), and copy resume command.
- **Search by meaning.** Each finished session gets a short description, made by one headless call, and
  the search runs over those descriptions.
- **Privacy.** The store, transcripts and descriptions stay under `~/.claude/fleet/` and are never
  committed. The repo is public. Only the code lives in it.
- **Migration.** Existing rows of an older store's `conversations` table are copied in once
  (`fleet history import`).
- **Removal from the older tool.** That happens in a separate change in its own repository, after the
  history view works here.

### Launch profiles

Added 14 November 2026: the older tool's profile view moves here too, so the fleet holds everything about sessions.

- **What it edits.** Which tools new sessions get in each folder: the nearest `.claude-launch` names a profile, whose
  `.args` and `.json` files switch plugin folders, MCP servers and marketplace plugins.
- **The page.** A Profiles view beside History: the folder tree, each folder's profile and where it comes from with a
  select to change it, and one profile's switches with Revert and Save and push.
- **The CLI.** `fleet profile ls|show|set`.
- **Privacy.** Every path and name of the user's own setup is in `profiles.json` under the fleet's folder, never in
  the repository.

## Control and the user's inbox

Added 13 November 2026, on top of the slices above.

- **Manager control**, across machines like `ask`. `fleet stop <name>` stops a background member with `claude stop <id>`
  (the member is the entry of `claude agents --json` whose `sessionId` is its session id). An interactive member is never
  killed: it gets a `tell` asking it to wrap up and leave. `fleet respawn <name>` starts a dead or left member again with
  `claude --bg --resume <session id> -n <name> --settings ...` in its recorded folder, and refuses a live one.
  `fleet attach <name>` prints `claude attach <id>`, wrapped in `ssh -t <host>` for another machine; for an interactive
  member it says the session lives in a terminal and prints its resume command.
- **Redelivery.** When a member joins (the `join` verb and the SessionStart hook), every ask or tell to that name that is
  unanswered and either never delivered or delivered to a session that is no longer alive is posted to the new session,
  and its `recipient_session` moves there. A respawned member therefore finds what was waiting for it.
- **`petros` is the user**: a reserved name nobody can join, with no session and an inbox. A session outside the fleet
  sends as him with `--as petros` (or `FLEET_AS=petros`), which is how a voice or phone assistant acts for the user. A
  member always speaks as itself. A message to `petros` is stored, never posted; `fleet inbox` lists it (every machine),
  `fleet answer <id> "..." --as petros` answers it to the asking session, `fleet dismiss <id> --as petros` clears it (an
  ask is answered "dismissed", so its asker stops waiting). An item on another machine is addressed `12@machine`.
- **`fleet notify "<text>"`**: a member tells the user something. It is stored in his inbox; the skill also has the
  session call its PushNotification tool, which reaches the phone when Remote Control is on.
- **The page** gains writes under the same protection as the History API: add a to-do, tell or ask a member as the user,
  answer or dismiss an inbox item, stop or respawn a member, copy an attach command. A "For you" view and a header badge
  show the inbox. History shows a member's fleet name when the session has no other name.

## Commands

The CLI is `fleet`. The skills wrap it as `/fleet <verb>`.

| Verb | Does |
|---|---|
| `join [name]` | Register this session. The default name is the session's name or folder. |
| `leave` | Leave the fleet. |
| `ls` | Members on every machine. |
| `tell <name\|*> "…"` | Instruct one member, or all members. |
| `ask <name\|*> "…"` | Ask, and return a thread id. |
| `answer <msg> "…"` | Answer a question. |
| `wait <thread>` | Wait for the answers, without polling. |
| `todo add\|ls\|claim\|done\|spawn` | The backlog. |
| `spawn <name> <cwd> "…"` | Start and join a new session. |
| `ui` | Serve the page. |

## Spike results (13 November 2026)

1. **The socket's line format works from a script.**
   - The script connects to `messagingSocketPath` from `~/.claude/sessions/<pid>.json`.
   - It may first send `{"type":"auth","token":…}`, using the `peerToken` from the sibling
     `<pid>.<hash>.key`. On macOS this line was optional.
   - It then sends one JSON line: `{"msgV":1,"msg_id":…,"type":"user","message":{"role":"user","content":…},"priority":"next","from":"uds:<reply socket>"}`.
     The content is wrapped in a `cross-session-message` element carrying `from`, `from-name` and `from-mode`.
   - Without a `from`, the receiver cannot reply.
   - The sender's name and mode are self-asserted. The receiver also shows the verified peer pid.
2. **Headless sessions have sockets.** A `claude -p` run and a `claude --bg` session both register in
   `~/.claude/sessions` and bind a socket. A `-p` run acted on a message mid-run, about 2 seconds after it
   arrived. `--bg` refuses an untrusted folder.
3. **Bypass sessions hold messages by default.**
   - A session that skips permissions holds a message unless the sender claims `from-mode="bypass"`, or the
     receiver sets `crossSessionInbound: "accept"`.
   - The user settings on the Mac already set `accept`.
   - `fleet spawn` passes `--settings '{"crossSessionInbound":"accept"}'` anyway, so it works on any machine.
4. **Trust.** Any local process can post to a session's socket and claim any name. The fleet adds nothing to
   that exposure. It only acts on lines whose `from` is a registered member's reply socket.

## Out of scope

- Stored summaries of what a session is doing.
- File or folder locks.
- Cloud sessions and Remote Control.
- Any integration with other tools that keep their own session lists.
