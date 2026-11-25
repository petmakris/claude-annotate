# The session index: the contract

This file is the one source for the session index. It fixes the row fields, the journal entry, the take call,
the chain call, the hub API, the CLI, the local files, the Python modules and which job owns which file.
`session-index.schema.json` beside it holds the same shapes as JSON Schema. The fixtures in
`fleet/tests/fixtures/session_index/` are examples of each shape, and `fleet/tests/test_session_index_contract.py`
checks every fixture against the schema.

When this file and the schema differ, the schema wins for a shape and this file wins for a rule. A builder who
finds a gap fixes this file in the same change. The words "must" and "never" are rules. Everything else explains.

Example machine names in this file are `hub`, `laptop` and `spare`. Real names come from `machines.json`.

## 1. Words

- **Session**: one Claude Code conversation, named by its session id (`sid`).
- **Hub**: the machine named `hub` in `$FLEET_HOME/machines.json`. Without a `hub` key, the machine itself. The
  hub holds the index.
- **Index**: the table `sessions` in `$FLEET_HOME/index/hub.db` on the hub. One row per sid.
- **Owner**: the one side that may work in a session now. It is a machine name from `machines.json`, or a Claude
  Voice server: `phone:prod`, or `phone:dev:<sandbox>` for a sandbox's server.
- **Epoch**: a number on each row. It is 1 when the row is made, and every take adds 1.
- **Take**: the only call that changes `owner` and `epoch`. It runs on the hub.
- **Journal**: a file on every machine that holds what its sessions did, in order, until the hub has it.
- **Writer**: who wrote a journal entry. It is the machine (`machine`) and the owner name it writes as (`as`).
- **Cache**: one file per session on every machine, holding the row as that machine last knew it.
- **Chain**: the sessions a Claude Voice topic went through. A handover at 30 % context starts a new sid; the old
  one is superseded. The chain's newest sid is its **head**. Its first sid is its **conversation**.
- **Observed facts**: what a session is doing right now (`live`, `state`, `where`, `tmux`, `pid`). They are read,
  never stored as truth.
- **Work session**: a session the work rule (section 7) says must never leave its machine with its words.

## 2. The row

A row is durable facts plus observed facts. Durable facts are stored on the hub. Observed facts are read from the
session's machine when a list is read, and carry the time they were read.

### 2.1 Durable fields

All times are Unix epoch seconds, as numbers. Registry files (section 12) hold ISO 8601 text instead; only the
registry shim converts.

| Field | Type | Written by | Meaning |
|---|---|---|---|
| `sid` | sid | first entry | The session id. Pattern `^[0-9A-Za-z][0-9A-Za-z_-]{0,127}$`. |
| `conversation` | sid | first entry, chain | The chain's first sid. Equal to `sid` for a session that continues nothing. |
| `name` | text, at most 200 | journal, rename | The name every surface shows. |
| `name_source` | enum | journal, rename | Where `name` came from (section 2.3). Empty text when there is no name. |
| `kind` | enum | journal | `chat`, `job`, `worker` or `voice`. |
| `env` | `prod` or `dev:<sandbox>` | first entry | `dev:<sandbox>` only for a row a Claude Voice sandbox server made. |
| `machine` | machine name | journal, take | The machine that holds the transcript. A phone owner's transcript is on the hub. |
| `cwd` | text or null | journal, take | The session's folder on `machine`. Null on a work row. |
| `account` | text or null | journal | The listed Claude account the session runs on. Null on a work row. |
| `owner` | owner | first entry, take | Who may work in it now. |
| `owner_since` | time | first entry, take | When `owner` last changed. |
| `epoch` | integer, 1 or more | first entry, take | Section 4. |
| `continues` | sid or null | chain | The sid this one continues. |
| `superseded_by` | sid or null | chain | The sid that continues this one. Not null means the row is not a head. |
| `first_prompt` | text or null, at most 300 | journal | The first prompt. Null on a work row. |
| `last_prompt` | text or null, at most 200 | journal, registry shim | The newest prompt. Null on a work row. |
| `last_answer` | text or null, at most 200 | journal, registry shim | The newest answer. Empty text right after a prompt. Null on a work row. |
| `topic` | `{host, id}` or null | journal, registry shim | The Claude Voice topic that holds it. `host` is `prod` or `dev:<sandbox>`. |
| `rc_name` | text or null | journal | The Remote Control name the session runs under. Null on a work row. |
| `started` | time | first entry | When the row was made. |
| `updated` | time | every applied change | When the hub last changed the row. For display only, never for order. |
| `ended` | time or null | journal, chain | When the session ended. Null while it may still run. |
| `end_reason` | text or null | journal, chain | Claude's SessionEnd reason, or `handover`, `sandbox-down`, `host-stopped`. |
| `description` | text or null, at most 2,000 | journal (`describe`) | The short description search reads. Null on a work row. |
| `work` | boolean | first entry | True for a work session. Never changes once set. |

Text is cut like the registry cuts it: runs of white space become one space, and a text longer than its limit is
cut to the limit less one character, plus `…`.

### 2.2 Observed fields

Every row in a list carries `observed`:

```json
{"live": true, "state": "idle", "where": "tmux", "tmux": "notes", "pid": 4242,
 "observed_at": 1795000000.0, "stale": false, "source": "machine"}
```

- `live`: whether a Claude process holds the session. `state`: the raw `status` of `claude agents --json` (else its
  `state`), a Claude Voice topic state, `ended`, or `unknown`. `where`: `tmux`, `window`, `bg`, `phone` or `none`.
  `tmux`: the tmux session name, or null. `pid`: the process id, or null.
- `observed_at`: when these values were read. Null when nothing was ever read.
- `source`: `machine` (read from the session's machine by the observer, section 10.3), `journal` (the newest
  observed values a journal entry carried), or `none`.
- Of the two sources, the one with the newer `observed_at` wins.
- `stale` is true when `observed_at` is more than 60 seconds old (`STALE_AFTER = 60`). One exception: values with
  source `journal` written as a `phone:*` writer are never aged. A Claude Voice server journals every change of a
  topic's state, and journals all its topics again when it starts.
- The hub may keep observed facts in its cache files (section 10.3). It never serves them as truth: `stale` says
  how old they are.
- Observed facts are never columns of `sessions`.

### 2.3 Names

`name_source` is one of these, highest rank first:

| Rank | Source | Where it comes from | Prompt-derived |
|---|---|---|---|
| 1 | `manual` | A rename through the hub (page, `fleet session rename`) | no |
| 2 | `custom` | The transcript's `custom-title` (`/rename`) | no |
| 3 | `topic` | The Claude Voice topic's name | no |
| 4 | `job` | `CLAUDE_DETACH_NAME` of a detached job | no |
| 5 | `ai` | The transcript's `ai-title` | yes |
| 6 | `agent` | The transcript's `agent-name` | no |
| 7 | `fleet` | The session's fleet member name | no |
| 8 | `registry` | A registry file's `name`, by the importer | yes |
| 9 | `prompt` | The first prompt, cut to 60 | yes |

- The hub keeps the name of the highest rank it has seen. A journal name of equal rank replaces it. A lower rank
  never does.
- A rename with an empty name clears `name` and `name_source`; the next journal name fills them again.
- A work row never holds a prompt-derived name (section 7).
- The one transcript parser is fleet's (`fleet_index_parse.session_facts`). It reads `custom-title`, `ai-title` and
  `agent-name` from the transcript's end and the first prompt from its start, as `fleet_history` does. When it
  finds no title, it names the session by the first prompt, as the registry did.

### 2.4 Kinds

- `voice`: only a Claude Voice server writes it.
- `job`: `CLAUDE_DETACH_NAME` is set and `CLAUDE_CODE_ENTRYPOINT` is not `cli`. An interactive session wins, as in
  the registry.
- Otherwise `fleet_sessions.kind_of(name, cwd, rules)` decides `worker`, `job` or `chat`, with the rules of
  `$FLEET_HOME/sessions.json`.
- A take refuses `job` and `worker` rows: they can be read, never taken.

## 3. Owners, machines and env

- A machine name must be `self` or a key of `machines.json`. The hub refuses any other.
- An owner matches `^(phone:prod|phone:dev:[a-z0-9]+|[a-z0-9][a-z0-9-]{0,62})$`, and a machine owner must be a
  machine name.
- `env` is set when the row is made and never changes. A row made by the writer `phone:dev:<sandbox>` gets
  `env = dev:<sandbox>`. Every other row gets `env = prod`.
- Lists hide `env = dev:*` rows unless the request asks for them (`env=all` or `env=dev:<sandbox>`).

## 4. Take

`owner` and `epoch` are written only by take. Take is never journaled.

### 4.1 Who calls it

env's `@claude session take SID --to OWNER` stays the only mover and keeps its steps: it reads the row, asks the
old owner to let go (`_release` for a machine, `POST /sessions/<sid>/release` for a Claude Voice server), copies
the transcript, then calls the hub's take. take runs on the hub; env already re-runs it there from other machines.

### 4.2 The call

`fleet session take SID --to OWNER --expect-epoch N [--by WHO] [--release stopped|phone|gone|none] --json`, or
`POST /api/session/take` with the same values as JSON.

Request (`take_request`):

```json
{"sid": "...", "to": "laptop", "expect_epoch": 1, "by": "laptop", "release": "stopped"}
```

- `by` is who asks: the machine where the command started, or `phone:<host>` when a Claude Voice server asks.
  env sets it to `to` when `to` is `phone:*`. Without `--by`, the CLI uses this machine's name.
- `release` says how the old owner let go. The hub stores nothing of it; it is logged.

In one SQLite `BEGIN IMMEDIATE` transaction, the hub:

1. Refuses a missing row (`no-session`).
2. Refuses a superseded row (`superseded`). The line names the head.
3. Refuses a `job` or `worker` row (`job`) and a work row (`work`).
4. Refuses when `by` or `to` is `phone:dev:<x>` and the row's `env` is not `dev:<x>`, and when `to` is
   `phone:prod` and the row's `env` is `dev:*` (`dev-refused`).
5. Answers `ok` with no change when `to` is already the owner.
6. Refuses when `expect_epoch` is not the row's `epoch` (`stale-epoch`).
7. Otherwise sets `owner = to`, `owner_since = now`, `epoch = epoch + 1`, `machine` = `to`, or the hub for a
   phone owner, and `cwd` to the mapped folder when the request carries `cwd`.

After the commit, the hub:

- backs up `hub.db` (section 11);
- runs the change callbacks (the registry shim, section 12);
- writes the new row into the caches of the old owner's machine and the new owner's machine (`_cache-put` over
  ssh, 5 s to connect, best effort). A cache that missed it learns the truth from its next journal reply.

Reply (`take_reply`), exit 0:

```json
{"ok": true, "sid": "...", "owner": "laptop", "epoch": 2, "owner_since": 1795000000.0,
 "previous_owner": "hub", "conversation": "..."}
```

Refusal, exit 2, `ok` false, and one line on stderr:

| `code` | Line |
|---|---|
| `no-session` | `session <sid> is not in the index` |
| `superseded` | `session <sid> was continued as <head>; take <head> instead` |
| `job` | `session <sid> is a <kind>: it can be read, never taken` |
| `work` | `session <sid> is a work session: it never leaves its machine` |
| `dev-refused` | `a Claude Voice sandbox takes only the sessions it made, and never gives one to phone:prod` |
| `stale-epoch` | `session <sid> moved meanwhile (epoch <now>, expected <n>); read it again` |

### 4.3 The hub is down

When the hub does not answer, take fails, exit 3, and prints exactly this one line on stderr:

    ownership cannot change while the hub is down

This is an invariant. No machine, cache or journal ever changes an owner. The reply's `code` is `hub-down`.

### 4.4 A dev owner that is gone

env's take looks a `phone:dev:<sandbox>` owner up with `lomem ports`. When the sandbox cannot be found, env treats
it as let go and calls the hub with `--release gone`. The take then runs as any other and the epoch goes up by 1.

## 5. The journal

### 5.1 The entry

```json
{"v": 1, "machine": "laptop", "seq": 41, "as": "laptop", "sid": "...", "epoch_seen": 2,
 "event": "prompt", "at": 1795000000.0,
 "fields": {"last_prompt": "fix the build", "last_answer": "",
            "observed": {"live": true, "state": "busy", "observed_at": 1795000000.0}}}
```

- `machine`: the machine that wrote the entry, a machine name.
- `seq`: the writer machine's sequence number, 1 or more. One number line per machine, shared by everything that
  journals on it.
- `as`: the owner name the entry writes as. It equals `machine`, except for a Claude Voice server: it writes as
  `phone:prod` or `phone:dev:<sandbox>`, and only from the hub machine.
- `sid`, `epoch_seen`: the session and the epoch its writer knew from its cache. 1 for a session the writer is
  starting. 0 when the writer knows nothing of the row.
- `event`: `start` (SessionStart, and a Claude Voice topic's first answer), `prompt` (UserPromptSubmit), `stop`
  (Stop), `end` (SessionEnd), `observe` (observed facts only) or `describe` (a new description).
- `at`: the writer's clock, for display only. Never used for order.
- `fields`: only the keys of `journal_fields` in the schema: `name`, `name_source`, `kind`, `cwd`, `account`,
  `first_prompt`, `last_prompt`, `last_answer`, `topic`, `rc_name`, `description`, `end_reason`, `work` and
  `observed`. `owner`, `epoch`, `owner_since`, `env`, `machine`, `continues`, `superseded_by` and `conversation`
  can never be in an entry.

### 5.2 How the hub applies entries

A batch is `{"machine": M, "entries": [...]}` (`journal_batch`). The hub applies it in one transaction, entries
in `seq` order. For each entry:

1. `seq` not above the machine's high mark → `duplicate`. The hub keeps one high mark per machine
   (`journal_high`), which dedupes on `(machine, seq)` because a machine sends its entries in order.
2. An entry that breaks the schema, names an unknown machine, or writes as `phone:*` from a machine that is not the
   hub → `invalid`.
3. A work entry (its `fields.work` is true, or its row's `work` is true) that carries a field section 7 forbids →
   `work-refused`. Nothing of it is stored.
4. No row, and `epoch_seen` is 1 or 0 → the row is made: `owner = as`, `epoch = 1`, `owner_since = started = at
   the hub's clock`, `conversation = sid`, `env` from `as` (section 3), `machine` = the entry's `machine`, `work`
   from the fields (false when absent). → `applied`.
5. A row whose `owner` is not `as` → `not-owner`.
6. A row whose `epoch` is not `epoch_seen` → `stale-epoch`.
7. Otherwise the fields are merged → `applied`. A field absent from the entry is left alone. `name` follows the
   rank rule (section 2.3). A `start`, `prompt` or `stop` clears `ended` and `end_reason`. An `end` sets `ended`
   and `end_reason` (default `other`). `kind` is set once and changed only to `voice` by a phone writer.

Each entry's outcome counts for the high mark, dropped or not. A dropped entry changes nothing and is logged to
`$FLEET_HOME/hooks.log` on the hub.

The reply (`journal_reply`):

```json
{"high_seq": 41, "results": [{"seq": 41, "outcome": "applied"}],
 "rows": {"<sid>": {"owner": "laptop", "epoch": 2, "conversation": "...", "head": "...", "work": false}}}
```

`rows` gives the truth for every sid in the batch that has a row. The writer writes it into its cache.

### 5.3 The writer's side

Files, in `$FLEET_HOME/index/` on every machine, all 0600:

- `journal.jsonl`: one entry per line, appended under `journal.lock` (an `fcntl` lock).
- `journal.state.json`: `{"next_seq": 42, "acked_seq": 41}`.

Rules:

- An entry is appended and flushed to disk before anything is sent. Writes go journal first, then hub.
- A flush sends every entry with `seq` above `acked_seq`, in order, in one batch, and sets `acked_seq` to the
  reply's `high_seq`. When the hub does not answer, the entries stay and nothing fails.
- A flush runs after every append and when a session starts. There is no timer and no poller.
- The recorder hook appends at once and flushes in a detached child, so a hook never waits for the network.
  `FLEET_INDEX_FOREGROUND=1` flushes in the same process, for tests.
- When `journal.state.json` is lost, the writer asks the hub for its high mark (`_hub high-seq`) and renumbers
  its unsent entries above it.
- When `journal.jsonl` passes 1 MB, a flush that succeeded rewrites it without the acknowledged entries.
- On the hub machine the hub is in process: a flush applies at once, with no ssh.

## 6. The recorder hook

One hook records every session: fleet's `hooks/record.sh`, on SessionStart, UserPromptSubmit, Stop and SessionEnd.

- It reads the hook input once. It runs `fleet.py hook-record` (the per-machine history, kept until phase 3) on
  SessionStart, Stop and SessionEnd, and `fleet_index_hook.py` on all four.
- `fleet_index_hook.record` works out the entry: the event, the facts of the one parser (section 2.3), `kind`
  (section 2.4), `account` (section 7), `rc_name` from `FLEET_RC_NAME`, `work` (section 7) and `observed`
  (`start`: live, `idle`; `prompt`: live, `busy`; `stop`: live, `idle`; `end`: not live, `ended`).
- It sets `work` in every entry, and masks a work session's entry before appending (section 7).
- It never fails a session: it always exits 0 and logs a problem to `hooks.log`.
- `FLEET_NO_RECORD` turns it off, as for the history.
- Detached jobs come in through it as `kind=job` with `name_source = job`.
- env's `note --hook` stays as it is until phase 3 and writes only the registry. Section 12.3 says why it writes
  no index entry.

## 7. Work sessions

A work session never leaves its machine with a prompt, a folder, a prompt-derived name or an account.

### 7.1 The rule

One function in fleet decides: `fleet_work.is_work(folder, transcript, rules)`. env imports it from fleet; fleet
never imports env.

- A transcript under a Claude config folder that is not a listed account's is work. Listed: `~/.claude`, or
  `~/.claude-<account>` for an account after the first in `accounts`.
- A folder at or under one of `profile_paths` is work.
- A folder whose nearest `.claude-launch` names a profile that only a path profile holds is work: the profile's
  `<name>.args` is in none of `own_profiles` but in `<path>/claude/profiles/` of a profile path.
- `fleet_work.account_of(config_dir, rules)` gives the listed account name, or None for an unlisted one.

The rules come from `$FLEET_HOME/work.json`:

```json
{"accounts": ["first", "second"], "profile_paths": ["/home/me/work-profile"],
 "own_profiles": "/home/me/projects/env/claude/profiles"}
```

- env writes this file on each machine: its install writes it, and so does any env command that changes the
  accounts or the path profiles.
- When the file is missing or does not parse, and `~/projects/env` exists, every session counts as work. A machine
  set up for work data fails closed.
- When the file is missing and there is no such folder, nothing is work. That is a machine without the env repo,
  such as the test world.
- A rule that raises counts the session as work.

### 7.2 Masking on the writing machine

`fleet_work.mask_fields(fields)` returns the fields with these removed: `first_prompt`, `last_prompt`,
`last_answer`, `cwd`, `account`, `description`, `rc_name`, a `name` whose `name_source` is prompt-derived
(section 2.3), and `observed.tmux`. It keeps `work: true`. The hook masks before it appends, so the journal file
never holds the words.

### 7.3 The hub's second check

`fleet_work.work_refusal(fields)` gives a reason when a work entry carries any field section 7.2 removes. The hub
refuses such an entry whole (`work-refused`) and stores none of it. The registry shim never writes a work row. The
cache file on the writing machine may hold the full row, since it never leaves; `_cache-dump` masks it before it
leaves.

A test (osidx-2-hub) starts a work session with a known prompt, folder and name, runs every write path, and
searches `hub.db`, every `journal.jsonl` and every cache dump for those bytes. It finds none.

## 8. Chains

A Claude Voice handover at 30 % context starts a new sid. It is one hub transaction.

`fleet session chain OLD NEW --by OWNER --expect-epoch N --json`, with `fields` as JSON on stdin, or
`POST /api/session/chain`. Request (`chain_request`):

```json
{"old_sid": "...", "new_sid": "...", "by": "phone:prod", "expect_epoch": 1,
 "fields": {"name": "kitchen plans", "name_source": "topic", "kind": "voice",
            "topic": {"host": "prod", "id": "kitchen-plans"}}}
```

In one transaction, the hub:

1. Refuses a missing old row, an old row whose owner is not `by`, a stale `expect_epoch`, and an old row that is
   already superseded.
2. Refuses a new sid that has a row, unless that row was made by `by` at epoch 1 and continues nothing. That
   happens when a journal entry for the new sid arrived first; the row is then linked.
3. Sets on the old row: `superseded_by = NEW`, `ended = now`, `end_reason = handover`.
4. Makes or links the new row: `continues = OLD`, `conversation` = the old row's `conversation`, `owner = by`,
   `epoch = 1`, `env`, `machine` and `cwd` from the old row, then the request's `fields`.

Reply (`chain_reply`): `{"ok": true, "old": {...}, "new": {...}}` with the two rows. A refusal is exit 2 and
`{"ok": false, "code": "...", "error": "..."}`, with the codes `no-session`, `not-owner`, `stale-epoch`,
`superseded` and `exists`.

Reading chains:

- `head_of(sid)` follows `superseded_by` to the end.
- Every list shows only heads by default (`chains=all` shows every row). A head carries `chain`: its
  conversation's sids, oldest first.
- take refuses a superseded sid (section 4.2). A picker resolves a superseded sid to its head before it takes.
- Fleet members and to-dos key by `conversation`: `members.conversation` and `todos.claimed_conversation` hold the
  conversation read from the local cache when the member joins or the to-do is claimed (the sid itself when the
  cache has no row). "Held by this session" compares conversations.
- The phone's own history of a chain stays in Claude Voice's turn log.

## 9. Dev isolation

- A row made by `phone:dev:<sandbox>` has `env = dev:<sandbox>` (section 3).
- A dev server writes only rows it owns, as every writer does. It owns only rows it made or took, and take lets it
  take only rows of its own `env` (section 4.2, step 4). It can never take or give away a `phone:prod` or machine
  row.
- Lists hide dev rows by default (section 3).
- A Claude Voice sandbox server, when it stops, journals `end` with `end_reason = host-stopped` for each of its
  rows. A later answer opens the row again (section 5.2, step 7). `lomem sandbox down` stops the server, so it ends
  that server's rows.
- `fleet session end-host phone:dev:<sandbox>` ends every row that owner holds, with `end_reason = sandbox-down`.
  It refuses `phone:prod` and machine owners.
- A take from a dev owner that is gone runs with the epoch raised (section 4.4).

## 10. Reading: one endpoint

### 10.1 `GET /api/sessions`

Served by `fleet ui` on the hub. `@claude pick`, the fleet page and the Claude Voice server's proxy read it. No
surface merges rows itself.

Query: `env` (`prod` by default, `all`, or `dev:<sandbox>`), `chains` (`heads` by default, or `all`), `kind` (a
comma list, `all` by default), `machine`, `owner`, `q` (case-blind words in `name`, `last_prompt`, `last_answer`
and `cwd`), `limit` (300 by default), `fresh=1` (wait for a new observation).

Reply (`sessions_reply`):

```json
{"v": 1, "index": "up", "hub": "hub", "as_of": 1795000000.0,
 "machines": {"hub": {"reachable": true, "as_of": 1795000000.0, "stale": false, "reason": ""}},
 "counts": {"rows": 12, "hidden_dev": 2, "superseded": 1},
 "rows": [{"...durable fields...": "", "observed": {}, "key": "hub:<sid>", "head": true, "chain": ["<sid>"]}]}
```

- One row per sid. `key` is `<machine>:<sid>`, the form `fleet sessions open` and `@claude pick` take.
- Rows are newest `updated` first. Live rows always come, whatever the limit.
- `index` is `up` from the hub. Off the hub, `fleet session list --json` gives `down` when it served its last copy
  (section 10.4). The Claude Voice server's proxy gives `down` with the rows it has when the hub does not answer,
  never a 5xx.
- The same guard as today's `/api/sessions`: loopback bind and Host, and the token as the `fleet_ui` cookie or as
  `Authorization: Bearer`.

### 10.2 The token

The hub's token never leaves a server. The Claude Voice server reads it with `fleet ui token` (prints the token and
the base address as JSON: `{"url": "http://127.0.0.1:8797", "token": "..."}`), keeps it in its process, and sends
it as `Authorization: Bearer`. The phone holds only the Claude Voice server's own token.

### 10.3 Observed facts on read

- The hub reads each machine's observed facts with `fleet sessions observe --json` over ssh (on the hub, in
  process): `{"machine": "laptop", "as_of": t, "rows": {"<sid>": {"live", "state", "where", "tmux", "pid"}}}`
  (`observe_reply`), from `claude agents --json`, the claude tmux server and `ps`. A work row's `tmux` is null.
- Stale while refresh, as fleet's `seen/` does: the last answer of each machine is kept in
  `$FLEET_HOME/index/observed/<machine>.json`, answered at once, and fetched again in the background when older
  than 3 s. `fresh=1` waits. A machine that does not answer keeps its last values, and they turn stale after 60 s.
- 5 s to connect and 8 s in all per machine, as today.

### 10.4 Off the hub

`fleet session list --json` off the hub asks the hub over ssh. When the hub answers, the reply is kept in
`$FLEET_HOME/index/last-list.json`. When it does not, the command prints that copy with `"index": "down"` and
`"reason"`, and replaces the rows this machine owns with its own cache's rows.

## 11. Hub recovery

- After every take and every chain, and before an import or a rebuild, the hub copies `hub.db` with SQLite's
  backup call to `$FLEET_BACKUP_DIR`, by default `~/.local/state/fleet/index-backups/`.
- The file name is `hub-<YYYYmmddTHHMMSSZ>-<first 8 of sid>-e<epoch>.db` (`-import-`, `-rebuild-` in place of the
  sid part for those). The 20 newest are kept, by name.
- `fleet session rebuild [--dry-run]` makes the index again from every machine's cache. It backs up the current
  `hub.db`, asks each machine for `_cache-dump` (work rows masked), keeps per sid the cache row with the highest
  epoch (on a tie, the row held by its owner's machine), and sets each machine's high mark to the `acked_seq` it
  reports. It prints a report per machine: rows, conflicts, unreachable.
- There is no nightly job. A backup happens on an event.

## 12. Phase 1: the frozen contract with Claude Voice, and the dual write

Phase 1 changes nothing for the Claude Voice server in Production. Until it ships on the index (phase 2) and phase
3 removes the old paths, these stay exactly as they are.

### 12.1 What Claude Voice calls today

| What | Shape | Read by |
|---|---|---|
| `@claude session take SID --to phone:<host>` | Exit 0: the last stdout line is `{"ok": true, "sid", "owner", "cwd", "epoch"}`. Exit 2: the first stderr line is the refusal. Up to 120 s. | `parseTake` in `apps/claudevoice/host/src/session-cmd.ts` |
| `@claude session tail SID --json --turns N` | `{"sid", "name", "machine", "turns": [{"role": "user" or "assistant", "text", "at"}]}`, oldest first. | `tailOf` in `apps/claudevoice/host/src/sessions.ts` |
| Registry files | `$VOICE_SESSIONS_DIR` or `~/.local/state/claude-sessions/<sid>.json`, one JSON object with `version, sid, name, machine, account, cwd, last_prompt, last_answer, updated, live, owner, owner_since, epoch, kind, topic` (`registry_record` in the schema). Written by rename, so a half file never shows. | `readRecord`, `Registry.all`, `sessionRows` in `sessions.ts` |
| Claude Voice patches | `Registry.patch` writes `topic`, `live`, `last_prompt`, `last_answer`, `updated` into a file that exists. | itself |
| `POST /sessions/<sid>/release` `{"to"}` | Called by env's take with `X-Voice-Token`, up to 70 s. | the server |

The files `sessions.ts` and `session-cmd.ts` are read only for this build.

### 12.2 One writer per field of a registry file

On the hub, registry files are a view of the index, written by the registry shim (`fleet_registry_shim`):

| Field | Writer on a `phone:*` row | Writer on any other row |
|---|---|---|
| `topic`, `last_prompt`, `last_answer`, `updated` | Claude Voice's patch; the shim reads it into the index | the shim |
| `live` | Claude Voice's patch | the shim: `ended` is null |
| everything else | the shim | the shim |

Rules of the shim:

- It runs after every change on the hub (take, journal, chain, rename), for the changed sids, in the same call.
- It writes a file only for a row the registry would hold: `kind` `chat` or `job`, `env` `prod`, not work, a
  non-empty name, not superseded.
- It merges into the file: it starts from the file's content and writes only fields whose index value differs
  from what it last wrote (`$FLEET_HOME/index/shim-state.json`). It never touches a field Claude Voice writes on a
  `phone:*` row.
- Registry `name`: the index `name` when its source is `manual`, `custom`, `registry` or `prompt`, else the file's
  name stays. A new file takes the first prompt, cut to 60. Times are ISO 8601 with the local offset, to the second.
  `last_prompt` and `last_answer` are cut to 200. `kind` is `chat` or `job`. `version` is 1.
- It reads a `phone:*` row's file when the file's size or change time differs from what it last wrote: before it
  writes that file, and before every list on the hub. No timer. It takes `topic`, `last_prompt`, `last_answer` and
  `updated` into the index. It never takes `owner`, `owner_since`, `epoch`, `machine` or `cwd` from a file: the
  index wins, and a file that disagrees is written again at once.
- The importer seeds `shim-state.json` with each imported file's own values, so an import writes no file.

Registry copies on the other machines keep being written by env as today, for old machines.

### 12.3 The dual write

Until phase 3, every registry write path also writes the index in the same call:

| Path | Index write |
|---|---|
| env's `take` | the hub's take (section 4); the shim writes the hub's file |
| env's `_local put` | `fleet session _cache-put` on that machine |
| env's `note --apply` on the hub (old machines) | the legacy rule below |
| env's `note --hook` | none of its own: fleet's recorder hook, which Claude Code runs on the same event |
| Claude Voice's patch | the shim reads it in (section 12.2) |

`note --hook` writes no index entry because its parser names sessions differently from fleet's, and two writers of
`name` would make the name flip. A panel ruled on this (2 to 1); `PROGRESS.md` of osidx-1-contract holds the votes.

The legacy rule (`fleet_index_store.apply_legacy_note`) for a note that reaches the hub through `note --apply`:

- No row: make one as a first entry would (section 5.2, step 4), with `owner` = the note's `machine`.
- A row whose owner is not the note's `machine`: change nothing.
- Otherwise set `last_prompt`, `last_answer` and `updated`, journal-style `observed.live`, and `name` (source
  `prompt` or `custom`) only when the row has no name.
- A legacy note has no epoch and is never replayed: env drops it when the hub is down, as today.

### 12.4 Checks of phase 1

- A contract test (osidx-4-importer) runs Claude Voice's real parsers (`readRecord`, `sessionRows`, `tailOf`,
  `parseTake`) under node on the files the shim writes and on `fleet session tail` output. It skips when node or a
  lomem checkout is missing (the pre-push hook runs with an empty `HOME`). A fixture comparison in Python runs
  always.
- Production's `GET /sessions` is captured before the import and compared after it, byte for byte
  (osenv-3-acceptance).

## 13. The CLI

All in `fleet_index_cli.py`, reached as `fleet session <verb>` (`fleet/bin/fleet` and `fleet.py` both send the
`session` verb there). JSON goes to stdout. A refusal is exit 2 with one line on stderr. The hub not answering is
exit 3.

| Verb | Does | Called by |
|---|---|---|
| `take SID --to O --expect-epoch N [--by W] [--release R] [--cwd D] --json` | Section 4. | env `take` |
| `chain OLD NEW --by O --expect-epoch N --json` (fields on stdin) | Section 8. | Claude Voice (phase 2) |
| `list --json [--env E] [--chains all] [--kind K] [--machine M] [--q Q] [--limit N] [--registry]` | The `GET /api/sessions` reply. `--registry` prints registry-shaped records instead, newest first. | env `list`, `@claude pick` |
| `show SID --json` | One row with `observed`, `head` and `chain`. | env, tests |
| `owner SID --json [--timeout S]` | `{"sid", "owner", "epoch", "head", "source": "hub" or "cache", "stale"}`. Asks the hub within `S` seconds (2 by default), writes the answer into the cache, else reads the cache. | env owner guard |
| `tail SID --json [--turns N]` | env `tail`'s shape (section 12.1), read on the row's machine. A work row is read only on its own machine. | env `tail`, Claude Voice |
| `note [--as O]` (`{"sid", "event", "fields"}` on stdin) | Appends a journal entry, masked when work, then flushes. | Claude Voice (phase 2), env |
| `flush` | Sends the unsent entries. | the hook's child |
| `rename SID NAME...` | `name_source = manual` on the hub, then `fleet history rename` on the row's machine. | the page, CLI |
| `delete SID` | Removes every row of an ended session's conversation from the index; refuses a row that has not ended. Then `fleet history delete` on the row's machine. | the page |
| `describe SID` | Writes a description on the row's machine and journals `describe`. A work row is refused. | the page |
| `ask SID QUESTION...` | `fleet history ask` on the row's machine; prints the answer. | the page |
| `end-host OWNER` | Section 9. | Claude Voice, by hand |
| `rebuild [--dry-run]` | Section 11. | by hand |
| `backup` | Section 11, by hand. | by hand |
| `import [--dry-run] [--machine M]... [--backup-dir D]` | The importer (osidx-4-importer). | osenv-3-acceptance |
| `legacy-note` (a registry note on stdin) | `apply_legacy_note` on the hub. | env `note --apply` |
| `_hub OP` (JSON on stdin) | Internal: runs a hub operation (`apply`, `take`, `chain`, `owner`, `list`, `show`, `rename`, `delete`, `end-host`, `high-seq`, `legacy-note`). | other machines over ssh |
| `_cache-put` (rows on stdin) | Internal: writes rows into this machine's cache. | take, env `_local put` |
| `_cache-dump` | Internal: this machine's cache rows, work rows masked, and `acked_seq`. | rebuild |
| `_import-dump` | Internal: this machine's registry files and `conversations`, work rows masked. | import |

Over ssh, a verb runs as `<python> <folder of machines.json's fleet path>/fleet_index_cli.py <verb>`, with
`BatchMode=yes` and `ConnectTimeout=5`, like every remote verb of fleet.

## 14. Local files

All under `$FLEET_HOME/index/` (default `~/.claude/fleet/index/`), the folder 0700 and every file 0600.

| File | Machine | Holds |
|---|---|---|
| `hub.db` | hub | The index: tables `sessions` and `journal_high (machine PRIMARY KEY, seq)`. SQLite, WAL. |
| `journal.jsonl`, `journal.state.json`, `journal.lock` | every | Section 5.3. |
| `cache/<sid>.json` | every | One `cache_row` per session (below). |
| `observed/<machine>.json` | hub | Section 10.3. |
| `last-list.json` | not the hub | Section 10.4. |
| `shim-state.json` | hub | Section 12.2. |
| `$FLEET_HOME/work.json` | every | Section 7.1. Written by env. |

A cache file (`cache_row`) is the durable row as this machine last knew it, plus `cached_at` and `source` (`hub`,
from a reply, take or rebuild; `local`, from this machine's own entry not yet acknowledged). It is written
atomically (temp file and rename). On the writing machine a work row's cache file may hold the full row. Example:

```json
{"v": 1, "sid": "...", "conversation": "...", "owner": "laptop", "epoch": 2, "owner_since": 1795000000.0,
 "name": "notes", "name_source": "custom", "kind": "chat", "env": "prod", "machine": "laptop", "work": false,
 "superseded_by": null, "cached_at": 1795000000.0, "source": "hub"}
```

- The status line reads only `.owner` of its session's cache file. It never calls the hub and keeps its refresh.
- The owner guard (UserPromptSubmit) runs `fleet session owner SID --json`: the hub when it answers within 2 s,
  else the cache. It refuses the prompt when the owner is not this machine.

## 15. Modules and signatures

New modules sit beside `fleet.py`. All are stdlib only and run on Python 3.9. Only `fleet_index_cli.py` and
`fleet_sessions_api.py` may import `fleet`, and only inside functions, so there is no import loop. Every function
that touches files takes `fleet_home` so tests pass a temp folder.

### `fleet_index_store.py` (osidx-2-hub): the hub's store

```python
SCHEMA_VERSION = 1
STALE_AFTER = 60
HUB_DOWN = "ownership cannot change while the hub is down"
NAME_RANK = ("manual", "custom", "topic", "job", "ai", "agent", "fleet", "registry", "prompt")

class Refused(Exception):            # .code (a code of section 4.2 or 8), .line (the one line)
    def __init__(self, code, line): ...

def hub_db_path(fleet_home) -> str
def backup_dir() -> str              # $FLEET_BACKUP_DIR, else ~/.local/state/fleet/index-backups
def connect(path) -> sqlite3.Connection
def on_change(fn) -> None            # fn(con, sids) after each committed change
def before_read(fn) -> None          # fn(con) before a list or show reads rows
def get_row(con, sid) -> dict | None
def head_of(con, sid) -> str
def chain_of(con, sid) -> list[str]
def list_rows(con, *, env="prod", chains="heads", kinds=None, machine=None, owner=None, q=None,
              limit=300) -> list[dict]
def take(con, sid, to, expect_epoch, by, *, hub, machines, cwd=None, release=None, now=None) -> dict
def apply_batch(con, batch, *, hub, machines, now=None) -> dict          # journal_reply
def apply_legacy_note(con, note, *, machines, now=None) -> dict | None
def chain(con, old_sid, new_sid, by, expect_epoch, fields, *, hub, now=None) -> dict
def rename(con, sid, name, *, now=None) -> dict
def delete_conversation(con, sid) -> list[str]
def end_host(con, owner, *, now=None) -> list[str]
def import_row(con, row, *, origin) -> str      # "new", "same", "updated" or "conflict-kept"; higher epoch wins
def high_seq(con, machine) -> int
def backup(con, *, label, keep=20, directory=None) -> str
def rebuild(con, dumps, *, now=None) -> dict    # dumps: {machine: {"rows": [...], "acked_seq": n}}
```

`machines` is the set of machine names (`self` plus the keys of `machines.json`).

### `fleet_index_journal.py` (osidx-2-hub): the writer's journal

```python
class HubDown(Exception): ...

def index_dir(fleet_home) -> str
def append(fleet_home, machine, sid, event, fields, *, as_owner=None, epoch_seen=None, at=None) -> dict
def pending(fleet_home) -> list[dict]
def flush(fleet_home, machine, send) -> dict | None   # send(batch) -> journal_reply, raises HubDown
def compact(fleet_home, max_bytes=1_000_000) -> None
```

`append` reads `epoch_seen` from the cache when it is not given (1 when the cache has no row and the event is
`start`, else 0).

### `fleet_index_cache.py` (osidx-2-hub): the cache files

```python
def cache_dir(fleet_home) -> str
def read(fleet_home, sid) -> dict | None
def write(fleet_home, row, *, source) -> None
def write_truth(fleet_home, rows) -> None        # the `rows` of a journal reply, take or rebuild
def all_rows(fleet_home) -> list[dict]
def dump(fleet_home) -> dict                     # {"rows": masked rows, "acked_seq": n}
```

### `fleet_work.py` (osidx-2-hub): the work rule

```python
FORBIDDEN = ("first_prompt", "last_prompt", "last_answer", "cwd", "account", "description", "rc_name")
PROMPT_NAME_SOURCES = ("ai", "registry", "prompt")

class Rules: ...                                 # accounts, profile_paths, own_profiles, home, fail_closed

def load_rules(fleet_home=None, home=None) -> Rules
def is_work(folder, transcript, rules) -> bool
def account_of(config_dir, rules) -> str | None
def mask_fields(fields) -> dict
def work_refusal(fields) -> str | None
```

### `fleet_index_parse.py` (osidx-2-hub): the one transcript parser

```python
def session_facts(transcript_path, *, event, hook) -> dict   # name, name_source, first_prompt, last_prompt, last_answer
def turns(transcript_path, n=20) -> list[dict]               # [{"role", "text", "at"}], env tail's rule
def find_transcript(sid, home=None) -> str | None
```

It uses `fleet_history`'s readers (`records`, `newest_names`, `human_prompt`).

### `fleet_index_hook.py` (osidx-2-hub): the recorder

```python
def entry_for(hook, *, environ, fleet_home, machine, rules, now=None) -> dict | None
def record(hook, *, environ=None, fleet_home=None, now=None) -> int        # always 0
def main() -> int                                                          # reads the hook JSON on stdin
```

### `fleet_index_cli.py` (osidx-2-hub): the CLI and the hub client

```python
def main(argv=None) -> int
def hub_name() -> str
def machine_names() -> set
def open_hub() -> sqlite3.Connection    # connect, and register the shim's callbacks when it can be imported
def hub_call(op, payload, *, timeout=8) -> dict    # in process on the hub, else ssh `_hub OP`; raises HubDown
def hub_rows(query) -> list[dict]       # on the hub: before_read callbacks, then list_rows
```

`main` hands `import` and `_import-dump` to `fleet_index_import`, and `list` to `fleet_sessions_api.envelope`.

### `fleet_index_http.py` (osidx-2-hub): the service routes

```python
SERVICE_POSTS = ("/api/session/take", "/api/session/journal", "/api/session/chain", "/api/session/end-host")
SERVICE_GETS = ("/api/session/owner",)

def service_refusal(bound, headers, token) -> str | None
def handle(method, path, query, body, headers, bound, token) -> tuple   # (status, dict)
```

Service routes need a loopback bind, a loopback Host (or one in `hosts` of `ui.json`), `Authorization: Bearer`
with the token (never the cookie, so no page can be tricked into them) and a JSON body for a POST. A
`POST /api/session/journal` writes as the hub machine: its entries go through the hub machine's own journal.

### `fleet_sessions_api.py` (osidx-3-surfaces): the list and the page's session writes

```python
PAGE_POSTS = ("/api/sessions/open", "/api/sessions/stop", "/api/sessions/rename", "/api/sessions/delete",
              "/api/sessions/ask", "/api/sessions/describe", "/api/sessions/search")

class IndexFeed: ...                     # stale while refresh over envelope(), as SessionsFeed did
def envelope(query, *, fresh=False) -> dict          # sessions_reply
def observe_local() -> dict                          # observe_reply of this machine
def post(path, body, feed) -> tuple                  # (status, dict)
```

### `fleet_index_import.py` and `fleet_registry_shim.py` (osidx-4-importer)

```python
# fleet_index_import.py
def backup_sources(machines, out_dir) -> dict        # {"registry_tar": path, "fleet_dbs": {machine: path}}
def dump_local(fleet_home=None) -> dict              # registry files and conversations, work rows masked
def plan(con, dumps) -> dict                         # the dry-run report: per machine rows, new, same, conflicts
def apply(con, dumps) -> dict
def main(argv) -> int                                # `fleet session import ...`

# fleet_registry_shim.py
def registry_dir() -> str                            # $CLAUDE_SESSIONS_DIR, else ~/.local/state/claude-sessions
def registry_record(row, existing=None) -> dict
def after_change(con, sids) -> None                  # store.on_change
def ingest_phone_rows(con) -> int                    # store.before_read
def seed(records) -> None                            # shim-state from imported files
```

### Wiring in existing files

- `fleet/fleet.py` (osidx-3-surfaces) sends `session` to `fleet_index_cli.main(argv[1:])` at the top of `main()`,
  routes `SERVICE_POSTS` and `SERVICE_GETS` to `fleet_index_http.handle`, routes `GET /api/sessions` and
  `PAGE_POSTS` to `fleet_sessions_api`, adds `fleet ui token` and `fleet sessions observe --json`, and drops the
  History routes.
- `fleet/bin/fleet` (osidx-2-hub) sends `session` straight to `fleet_index_cli.py`, so the hub's verbs work before
  `fleet.py` is wired.
- `fleet/hooks/hooks.json` and `fleet/hooks/record.sh` (osidx-2-hub) add the recorder (section 6).

### Pick plans

`fleet_sessions.PLAN_KINDS` (osidx-3-surfaces) drops `refuse-registry` and adds `take-then-resume`. A plan gains
`head` (the sid acted on, after a superseded sid is resolved) and `take` (`null`, or
`{"sid", "to", "expect_epoch"}`). A session owned by `phone:*`, or by another machine where it is not live, plans
`take-then-resume`: env's `pick` runs `@claude session take SID --to <machine>` and then resumes. From the phone,
Continue is Claude Voice's own `take --to phone:<host>`.

## 16. Who owns which file

Every file the build creates or edits has one owner. Jobs that run at once never edit the same file. A job may
read any file. After osidx-2-hub, osidx-3-surfaces and osidx-4-importer have landed, osidx-5-final may fix any osidx
file. osenv-3-acceptance fixes env files only after osenv-1-routes and osenv-2-docs have landed.

### claude-annotate

| File | Owner |
|---|---|
| `fleet/docs/session-index.md`, `fleet/docs/session-index.schema.json` | osidx-1-contract, then osidx-5-final |
| `fleet/tests/fixtures/session_index/**`, `fleet/tests/schema_check.py`, `fleet/tests/test_session_index_contract.py` | osidx-1-contract, then osidx-5-final |
| `fleet/fleet_index_store.py`, `fleet_index_journal.py`, `fleet_index_cache.py`, `fleet_work.py`, `fleet_index_parse.py`, `fleet_index_hook.py`, `fleet_index_cli.py`, `fleet_index_http.py` | osidx-2-hub |
| `fleet/fleet_history.py` | osidx-2-hub |
| `fleet/bin/fleet`, `fleet/hooks/hooks.json`, `fleet/hooks/record.sh` | osidx-2-hub |
| `fleet/tests/index_testkit.py` (shared helpers; others import, never edit) | osidx-2-hub |
| `fleet/tests/test_index_store.py`, `test_index_take.py`, `test_index_journal.py`, `test_index_cache.py`, `test_index_hook.py`, `test_index_work.py`, `test_index_chain.py`, `test_index_dev.py`, `test_index_rebuild.py`, `test_index_http.py`, `test_index_cli.py` | osidx-2-hub |
| `fleet/tests/test_fleet_history.py`, `test_fleet_history_format.py` | osidx-2-hub |
| `fleet/fleet.py`, `fleet/fleet_sessions.py`, `fleet/fleet_sessions_api.py` | osidx-3-surfaces |
| `fleet/ui/index.html`, `app.js`, `app.css`, `fleet/ui/fixtures/sessions.json`, `open-plans.json` | osidx-3-surfaces |
| `fleet/skills/fleet/SKILL.md`, `tools/fleet_ui_e2e.py` | osidx-3-surfaces |
| `fleet/tests/test_fleet_sessions.py`, `test_fleet_ui.py`, `test_fleet_ui_sessions.py`, `test_fleet_todo_order.py`, `test_fleet_spawn_backlog.py`, `test_fleet_statusline.py`, `test_sessions_api.py` | osidx-3-surfaces |
| `fleet/fleet_index_import.py`, `fleet/fleet_registry_shim.py` | osidx-4-importer |
| `fleet/tests/test_index_import.py`, `test_registry_shim.py`, `test_voice_parsers_contract.py` | osidx-4-importer |
| `CLAUDE.md` (the repo's: osidx-1-contract added one line pointing here), `fleet/tests/test_index_integration.py` | osidx-5-final |

Every other fleet test file stays as it is. A job that finds it must change a file it does not own writes a
public function in its own module instead, and says so in its DONE.

### env

| File | Owner |
|---|---|
| `libexec/claude/_session/_core.py`, `take`, `list`, `tail`, `note`, `_local`, `_release`, `_resume`, `_pick` | osenv-1-routes |
| `libexec/claude/_session/_index.py` (new: env's calls into `fleet session`, and the `work.json` writer) | osenv-1-routes |
| `libexec/claude/session`, `libexec/claude/pick`, `libexec/claude/launch`, `libexec/claude/on` (`FLEET_RC_NAME`) | osenv-1-routes |
| `claude/statusline.sh`, `claude/user-hooks/seamless-sessions.sh`, `claude/install` | osenv-1-routes |
| `tests/test-claude-seamless-sessions.bats`, `tests/test-claude-pick.bats` | osenv-1-routes |
| `libexec/claude/_default` (`-r` as a permanent alias of `pick`), `tests/test-claude-resume-alias.bats` | osenv-2-docs |
| `docs/seamless-sessions.md`, `docs/reference.md`, `docs/history.md`, `docs/adr/004-one-session-system.md` | osenv-2-docs |
| `CLAUDE.md`, `claude/CLAUDE.md` (the global file `~/.claude/CLAUDE.md` links to) | osenv-2-docs |

### lomem

Every file under `apps/claudevoice/` belongs to the osvoice plan: `host/` to osvoice-1-host, the app's frontend to
osvoice-2-app, and the branch's `after-ship.md` to osvoice-3-aftership. No osidx or osenv job edits lomem.

## 17. Fixtures

`fleet/tests/fixtures/session_index/` holds one folder per schema definition, each with `valid/` and `invalid/`
JSON files, and `scenarios/`. A scenario holds several documents, each named in its `parts` with its definition,
and an `expected` outcome the store's tests use:

- `scenarios/replayed-stale-entry.json`: an entry replayed at epoch 1 against a row at epoch 3. Outcome
  `stale-epoch`; the row does not change.
- `scenarios/take-chain.json`: takes `laptop` → `phone:prod` → `spare`, epochs 1, 2, 3.
- `scenarios/voice-handover-chain.json`: a chain transaction and the two rows after it.
- `scenarios/dev-take-prod.json`: a dev server's take of a prod row, refused `dev-refused`.
- `scenarios/work-masked.json`: the same work session as its local cache row (full) and as its journal entry and
  hub row (masked).

`schema_check.py` is a small JSON Schema validator for the keywords the schema uses. The contract test fails if the
schema uses any other keyword, so the schema stays checkable without a dependency.

## 18. What the build settled

The three build jobs (osidx-2-hub, osidx-3-surfaces, osidx-4-importer) landed together, and the full suite passed
on all three at once. This section adds what the build fixed that the sections above left open. It is the part env
and Claude Voice read when they call the hub.

### 18.1 The service routes

All are served by `fleet ui` on the hub (`fleet_index_http.handle`), on a loopback bind, with a loopback Host (or one
in `hosts` of `ui.json`) and `Authorization: Bearer <token>`. The token and base address come from `fleet ui token`.

| Route | Body or query | Reply |
|---|---|---|
| `POST /api/session/take` | `take_request` | `take_reply` |
| `POST /api/session/chain` | `chain_request` | `chain_reply` |
| `POST /api/session/journal` | `{"sid", "event", "fields", "as"}` | `{"ok", "seq", "result", "row"}` |
| `POST /api/session/end-host` | `{"owner"}` | `{"ok", "ended": [sid, ...]}` |
| `GET /api/session/owner?sid=<sid>` | none | `owner_reply` with `source: "hub"` |
| `GET /api/sessions` | the query of section 10.1 | `sessions_reply` |

- A journal post is appended to the hub machine's own journal and flushed at once. `as` is the hub machine's name
  (the default) or `phone:prod` / `phone:dev:<sandbox>`. `result` is that entry's outcome (section 5.2) and `row` is
  the truth the hub sends back (`journal_reply.rows[sid]`), or null.
- A POST needs `Content-Type: application/json`.

Status codes of the service routes:

| Status | When | `code` |
|---|---|---|
| 200 | done, or a take to the owner it already has | none |
| 400 | the body is not a JSON object, or a journal post is not `{sid, event, fields, as}` | `bad-request` |
| 401 | no Bearer token, or the wrong one (a cookie is never enough) | `refused` |
| 403 | not a loopback bind, or a Host not allowed | `refused` |
| 404 | no such route, or the sid is not in the index | `bad-request`, `no-session` |
| 405 | the wrong method | `bad-request` |
| 409 | every other refusal: `stale-epoch`, `superseded`, `job`, `work`, `dev-refused` | that code |
| 415 | a POST that is not JSON | `bad-request` |
| 503 | this machine is not the hub | `hub-down` |

### 18.2 The list off the hub

`fleet session list --json` and the page both go through `fleet_sessions_api.envelope`. Off the hub it runs
`fleet session list --json` on the hub through fleet's remote path, with 30 s in all (`LIST_TIMEOUT`), since the hub
reads every machine's observed facts before it answers. `fleet_index_cli.list_reply` does the same with ssh alone; it
runs only when `fleet_sessions_api` cannot be imported.

### 18.3 The importer's remote verbs

The importer runs its own module on the other machines: `<python> <folder of the fleet path>/fleet_index_import.py
_import-dump` (the registry files and `conversations`, work rows masked) and `_db-copy` (a copy of that machine's
`fleet.db`, as bytes, for the backup). `fleet session import` also takes `--json` for the report as JSON. Before it
writes, it backs up `hub.db` with the label `import` and seeds the registry shim's state from the files it read.

At the index's own epoch an import only fills empty fields (`fleet_index_store.merge_same_epoch`). It never fills a
work row's words (section 7.2). One exception: an import from the row's own machine, whose rule now says the session
is not work, clears the flag and fills the row. The writing machine decides what is work, so this undoes rows its
hook journaled while its rule failed closed, before env had written `work.json` (seen on main, 25 Nov 2026).

### 18.4 The tests that hold the whole

- `test_one_sid_reads_the_same_through_the_endpoint_the_cli_list_and_the_pick_plan` (`test_fleet_sessions.py`):
  one sid read through `GET /api/sessions`, `fleet session list --json` and the pick plan shows the same name,
  owner and state, and a phone-owned one plans `take-then-resume` with the row's epoch.
- `test_across_machines_a_journal_replayed_at_an_old_epoch_changes_nothing` (`test_index_journal.py`): real
  processes on three machines; a machine that lost its journal state resends its epoch-1 entries after two takes,
  and the hub row and the list stay exactly as they were.
