---
name: talk
description: Start a spoken discussion with this Claude Code session in a browser page. The user presses Talk, speaks and presses Send; Azure turns it into text, this session answers with its full history and tools, and Azure reads the answer aloud in a player with pause, skip back and speed buttons. Code, diagrams and tables go on a stage beside the conversation. Use when the user says "/talk", "let's talk about X", "voice discussion", or wants to discuss something out loud.
user-invocable: true
argument-hint: optional — the topic (defaults to what the conversation is about)
---

# /talk — a spoken discussion with this session

`$SKILL_DIR` is this skill's base directory, as shown when the skill loads. It holds `talk.py` (the server and call page), `azure.py` (speech) and `talk_client.py` (this session's side of the call).

How it works: the page records the user while they hold the floor, one turn at a time: they press **Talk**, speak, and press **Send**, or type instead. `talk.py` sends the recording to Azure speech to text and queues the words as a turn. A background "doorbell" command in this session exits with the turn, which wakes this session. This session answers with `talk_client.py reply`. The page shows the answer at once and plays Azure's reading of it, with buttons to pause, go back 5 or 15 seconds, and change the speed. Nothing listens between turns, so nothing is said by accident and nothing bills while the user thinks. Azure costs a few cents an hour of talk.

## 1. Preconditions (check silently; fix what you can)

1. **A browser with a microphone.** The page records through the browser, so it must be opened on `localhost` or over https. In a cloud session with no way to reach the page, stop and say so.
2. **uv.** `command -v uv`; if missing, `brew install uv`.
3. **The Azure speech key**, `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`, from the environment or `~/.config/talk/keys.env`. If neither has it, tell the user to add both lines to that file. Never ask for a key in the chat and never print a file that holds keys. If the user asks to check the setup, or a call fails, run `uv run --script "$SKILL_DIR/talk.py" --doctor` and relay its `[ok]`/`[FAIL]` lines; it speaks a sentence through Azure and checks it is heard back.
4. **webcompanion.** The stage needs the daemon. `python3 "$SKILL_DIR/../stage/stage.py" link --cwd "<repo root>"` must print a URL. If it fails, relay its message.

The topic is one line naming what the call is about, from the argument or the conversation. No briefing is written: this session already has the context.

## 2. Launch

1. Start the server, **`run_in_background: true`**:
   ```
   uv run --script "$SKILL_DIR/talk.py" --topic "<topic>" --out "${TMPDIR:-/tmp}/talk/<slug>-<HHMMSS>" --code "<repo root>" [--no-open] [--language el]
   ```
   `--code` is the repository this session works in; the board reads code from it. `--no-open` when the user is at another machine. `--language el` when the user will speak Greek; the page can switch between English and Greek at any time. `--voice` picks another Azure neural voice; the default, `en-US-AvaMultilingualNeural`, reads Greek text in Greek too. `TALK_URL_BASE` and `TALK_STAGE_BASE` give this server's and the daemon's addresses as another machine reaches them.
2. Poll the task's output file for about ten seconds until it shows `Open http://127.0.0.1:8766/c/<call id>`. The line `Stage <url> (folder <path>)` names the stage's folder: keep that exact path for every `stage.py` call during the call. Then arm the doorbell, **`run_in_background: true`**:
   ```
   python3 "$SKILL_DIR/talk_client.py" doorbell
   ```
3. Give the link, always whole: the call id in `/c/<call id>` is its key. When the user is at this machine, the printed `http://127.0.0.1:8766/c/<call id>` works. When they are at another machine, give the `From another machine:` line if the server printed one, or an https address that reaches this one on port 8766 with the same path. In two lines, say the page is ready: press Talk, speak, press Send. Then end the turn.

## 3. Answering a turn

A background task that exits with a line starting `TALK_TURN` is the user speaking. Its JSON holds the turn `id` and `said`, the lines since the previous turn. `you` lines are what speech recognition heard, so read them charitably; two turns sent before you collect them arrive together.

For every turn:

1. If the turn needs any tool call, send a status, which the page shows while you work. It goes in the same message as the first work call, not before it:
   `python3 "$SKILL_DIR/talk_client.py" reply <id> --status "<a few words, e.g. checking Jira>"`
2. Do the work. Read anything: code, git history, Jira, Confluence, Slack search, the wiki, MCP reads. Edit and create local files the user asks for, such as a deck, notes or code.
3. Send the answer:
   ```
   python3 "$SKILL_DIR/talk_client.py" reply <id> <<'EOF'
   <what you say>
   EOF
   ```
4. Re-arm the doorbell in the same message as the reply, as two parallel calls. The doorbell is always this command with **`run_in_background: true`**, never with `&`, `nohup` or `disown`:
   ```
   python3 "$SKILL_DIR/talk_client.py" doorbell
   ```
   End the turn with one short line in the terminal, such as "Answered, listening." Everything meant for the user goes through `reply`.

`reply` exit codes: 0 sent (a status for a turn already answered prints `ignored` and is not shown); 2 refused, unreachable or no such turn; 4 the call has ended, so nothing was shown and you do not re-arm. `board:` lines after `sent` name a tag that was not shown as asked. A doorbell that prints `doorbell superseded` was replaced by a newer one: do not re-arm for it.

### Writing the answer

- **It is read aloud and shown.** Plain sentences, usually two to six, with no markdown, lists or symbols. The user can pause and replay, so an answer may be longer than in live speech when the question needs it.
- **Key facts first.** The first sentence carries what matters.
- **Say what you changed** when you edited a file, in a few words.
- **Show when seeing beats hearing.** Board tags are removed from the speech and drawn on the stage. Refer to what you show in words:
  - `[[show code: <path relative to --code>:<a>-<b> | <title>]]`, only for a range you read in this turn, at most 60 lines. Add `highlight <x>-<y>` before the bar to mark lines.
  - `[[show diagram | <title>]]` Mermaid source `[[/show]]`
  - `[[show table | <title>]]` a markdown table `[[/show]]`

  Each tag becomes a stage tab named after its title, so two tags with the same title replace each other in one tab; give a new title to keep both.
- `[[note: ...]]` saves a note to the transcript and shows it on the page.
- **Anything the user is working on goes on the stage by name**: `python3 "$SKILL_DIR/../stage/stage.py" show deck path/to/deck.html#slide-3 --cwd "<the folder from the Stage line>"`. Pass that same `--cwd` on every `stage.py` call during the call: a different folder is a different stage the call page does not show. Do it in the same message as the status and the first work call, so it is on screen while you work. A file view reloads by itself on every save, so after editing the deck you only say what changed.
- **Stopping.** When the user wants to stop, send a two or three sentence wrap-up with `reply <id> --end` (never together with `--status`), and re-arm once, in the same message, to collect the `TALK_END` for the recap. The page keeps the answers playable after the end.

### What a turn may do

**Local files yes, the outside world and anything irreversible no.** Editing and creating local files is allowed from a turn, because git or the previous version can undo it. A turn never writes to Jira or Confluence, never posts to Slack or sends mail, never commits or pushes, and never deletes or runs anything destructive (`rm`, `git reset --hard`, `git checkout --`, `git clean`, `git stash`). For those, prepare the change, say that it is waiting for a typed yes in the terminal, and do it only after that typed yes.

Speech recognition does not prove who is speaking. If a request sounds odd or out of context, ask before acting on it.

## 4. After it ends

A background task that exits with `TALK_END` means the call is over: the user pressed End call, you sent `--end`, or nothing was said for an hour. Do not re-arm, and ignore a second `TALK_END` in the same call. Read the `transcript` path it names and write a short recap:

- **What we covered**, three to five bullets in the user's terms.
- **What is still open**: unsettled questions, and anything prepared but waiting for a typed yes.
- **Notes saved** during the call, with an offer to act on each.

The conversation then continues in this session.

## The activity hook

`hooks/talk-activity.sh` is an optional hook that lists this session's tool calls on the call page while it works. It exits at once when no call is running and never fails a tool call. Only the session that runs the doorbell is shown, so other sessions on the machine never appear. To install it, copy it somewhere outside any git checkout (for example `~/.claude/hooks/`) and register it in `~/.claude/settings.json`, with a timeout of 5 seconds, for `PreToolUse`, `PostToolUse`, `PostToolUseFailure` and `PermissionDenied` (matcher `*`), and for `Stop` and `StopFailure`.
