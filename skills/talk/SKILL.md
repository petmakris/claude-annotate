---
name: talk
description: Start a spoken discussion with this Claude Code session in a browser page. The user presses Talk, speaks and presses Send; Azure speech (or VoiceStudio on this Mac, without an Azure key) turns it into text, this session answers with its full history and tools, and the answer is read aloud while it shows as subtitles under the stage. Code, diagrams and tables go on that stage, which fills the page. Use when the user says "/talk", "let's talk about X", "voice discussion", or wants to discuss something out loud.
user-invocable: true
argument-hint: optional — the topic (defaults to what the conversation is about)
---

# /talk — a spoken discussion with this session

`$SKILL_DIR` is this skill's base directory, as shown when the skill loads. It holds `talk.py` (the server and call page), `speech.py` (which engine speaks: `azure_speech.py` or `voicestudio.py`) and `talk_client.py` (this session's side of the call).

One talk server on this machine holds the calls of every session, each at its own link. The user keeps several open and talks in one at a time. Pressing Talk, sending text or playing an answer in a call gives it the **floor**: every other call's page pauses its voice at once. Answers that arrive in another call are shown but not played, and they show as new on the strip of other calls at the top of every call page, and on the list of calls at the root of the talk address. Nothing changes for this session: it answers its own call by its call id.

How it works: the page records the user while they hold the floor, one turn at a time: they press **Talk**, speak, and press **Send**, or type instead. `talk.py` sends the recording to speech to text and queues the words as a turn. A background "doorbell" command in this session exits with the turn, which wakes this session. This session answers with `talk_client.py reply`. The page shows the answer at once, with a progress bar while its whole reading is made in one request, then plays it without a pause between sentences, highlighting each word as it is said (a tap on a word plays from there), with a small row of buttons to pause, go back 10 seconds, type or open the whole conversation, and a gear for speed, language, light or dark, and whether the stage follows the voice. Nothing listens between turns, so nothing is said by accident. Speech runs on Azure when its key is found (`AZURE_SPEECH_KEY`, else the output of `TALK_AZURE_KEY_COMMAND`; the region comes from `AZURE_SPEECH_REGION` or `TALK_AZURE_REGION`), which takes a second or two per answer and is billed per character. Without a key it runs in the local VoiceStudio app: free and private, but an answer takes about as long to make as to play. `TALK_SPEECH=azure` or `TALK_SPEECH=voicestudio` picks one by hand.

## 1. Preconditions (check silently; fix what you can)

1. **A browser with a microphone.** The page records through the browser, so it must be opened on `localhost` or over https. In a cloud session with no way to reach the page, stop and say so.
2. **uv.** `command -v uv`; if missing, install it (https://docs.astral.sh/uv/).
3. **Speech.** With Azure, nothing to start. Without it, **VoiceStudio**, the local speech app, answering at `VOICESTUDIO_URL` (default `http://127.0.0.1:3900`). Its server runs only while the app is open; on a Mac `talk.py` opens it with `open -a VoiceStudio` and waits, which takes about a minute from cold. If the user asks to check the setup, or a call fails, run `uv run --script "$SKILL_DIR/talk.py" --doctor` and relay its `[ok]`/`[FAIL]` lines; it names the engine, speaks a sentence through it and checks it is heard back.
4. **webcompanion.** The stage needs the daemon. `python3 "$SKILL_DIR/../stage/stage.py" link --cwd "<repo root>"` must print a URL. If it fails, relay its message.

The topic is one line naming what the call is about, from the argument or the conversation. No briefing is written: this session already has the context.

## 2. Launch

1. Open the call, **`run_in_background: true`**. This starts the server when none runs, or joins the one that does, then exits:
   ```
   uv run --script "$SKILL_DIR/talk.py" --topic "<topic>" --out "${TMPDIR:-/tmp}/talk/<slug>-<HHMMSS>" --code "<repo root>" --no-open [--language en|el]
   ```
   `--code` is the repository this session works in; the board reads code from it. The page's address comes from `TALK_URL_BASE` and the stage's from `TALK_STAGE_BASE` when they are set: the https addresses that reach talk's port 8766 and the webcompanion daemon's port 3080 from other machines. https is what lets the browser use the microphone from any machine. `--url-base` and `--stage-base` override them. `--no-open` because the user is often at another machine. `--language` fixes the language the page listens for first; the default, `auto`, detects English or Greek, and the page can switch between Auto, English and Greek at any time. Answers are read in the language they are written in. `--voice` names an Azure neural voice (default `en-US-AvaMultilingualNeural`), or with VoiceStudio a voice profile by name or id (default the profile named `Talk`). Without a VoiceStudio profile, OmniVoice draws a different random speaker for every answer, so the server prints a `speech:` warning; relay it.
2. Wait for the task to finish (seconds, or about a minute when VoiceStudio had to be opened). Its output holds `Open http://127.0.0.1:<port>/c/<call id>`, a `Link <TALK_URL_BASE>/c/<call id>` line when `TALK_URL_BASE` is set, and `Call <call id>`: keep the call id exactly, since every `talk_client.py` command names it with `--call=<call id>` (with `=`: an id may start with a character the parser would read as an option). The line `Stage <url> (folder <path>, slug <slug>, sid <sid>)` names the stage's folder, slug and sid: every call has a stage of its own, so keep the folder and the sid exactly for every `stage.py` call during the call. A line starting `talk:` instead means no call was opened: relay it. Then arm the doorbell, **`run_in_background: true`**:
   ```
   python3 "$SKILL_DIR/talk_client.py" doorbell --call="<call id>"
   ```
3. Give the `Link` line's address, always whole: the call id in `/c/<call id>` is its key. With no `Link` line, give the `Open` address, and say that it opens only on this machine: the microphone needs `localhost` or https, so another machine needs `TALK_URL_BASE` and `TALK_STAGE_BASE` set to https addresses that reach those ports. In two lines, say the page is ready: press Talk, speak, press Send. Then end the turn.

## 3. Answering a turn

A background task that exits with a line starting `TALK_TURN` is the user speaking. Its JSON holds the turn `id` and `said`, the lines since the previous turn. `you` lines are what speech recognition heard, so read them charitably; two turns sent before you collect them arrive together.

For every turn:

1. If the turn needs any tool call, send a status, which the page shows while you work. It goes in the same message as the first work call, not before it:
   `python3 "$SKILL_DIR/talk_client.py" reply <id> --call="<call id>" --status "<a few words, e.g. checking Jira>"`
2. Do the work. Read anything: code, git history, Jira, Confluence, Slack search, the wiki, MCP reads. Edit and create local files the user asks for, such as a deck, notes or code.
3. Send the answer:
   ```
   python3 "$SKILL_DIR/talk_client.py" reply <id> --call="<call id>" <<'EOF'
   <what you say>
   EOF
   ```
4. Re-arm the doorbell in the same message as the reply, as two parallel calls. The doorbell is always this command with **`run_in_background: true`**, never with `&`, `nohup` or `disown`:
   ```
   python3 "$SKILL_DIR/talk_client.py" doorbell --call="<call id>"
   ```
   End the turn with one short line in the terminal, such as "Answered, listening." Everything meant for the user goes through `reply`.

`reply` exit codes: 0 sent (a status for a turn already answered prints `ignored` and is not shown); 2 refused, unreachable or no such turn; 4 the call has ended, so nothing was shown and you do not re-arm. `board:` lines after `sent` name a tag that was not shown as asked, or was shown only after a fix: fix it in the next answer. A doorbell that prints `doorbell superseded` was replaced by a newer one: do not re-arm for it.

### Writing the answer

- **It is read aloud and shown.** Plain sentences, usually two to six, with no markdown, lists or symbols. The user can pause and replay, so an answer may be longer than in live speech when the question needs it.
- **Key facts first.** The first sentence carries what matters.
- **Say what you changed** when you edited a file, in a few words, and show the edit with a `change` board.
- **Teach with the board** (next section): what hearing cannot carry goes on the stage.
- `[[note: ...]]` saves a note to the transcript and shows it on the page.
- **Anything the user is working on goes on the stage by name**: `python3 "$SKILL_DIR/../stage/stage.py" show deck path/to/deck.html#slide-3 --cwd "<folder>" --slug "<sid>"`, both from the Stage line. Pass both on every `stage.py` call during the call: without them it lands on a different stage the call page does not show, and with a wrong one `stage.py` fails instead of making a new stage. A name a board of the call already holds is refused: pick another. Do it in the same message as the status and the first work call, so it is on screen while you work. A file view reloads by itself on every save, so after editing the deck you only say what changed.
- **Stopping.** When the user wants to stop, send a two or three sentence wrap-up with `reply <id> --call="<call id>" --end` (never together with `--status`), and re-arm once, in the same message, to collect the `TALK_END` for the recap. The page keeps the answers playable after the end.

### Teaching with the board

Board tags are taken out of the speech and drawn on the stage beside the conversation, one tab per title. Paths are relative to `--code`.

| Board | Use it for | Tag |
|---|---|---|
| code | existing code you are explaining | `[[show code: talk/live_turns.py:40-58 \| How a turn waits]]` |
| change | after you edit a file, instead of describing the edit | `[[show change: talk/talk.py \| What I changed]]` |
| diagram | how parts connect | `[[show diagram \| Turn path]] graph LR; P[Page] --> Q[Queue] [[/show]]` |
| table | a comparison or a list of facts | `[[show table \| Ports]]` a markdown table `[[/show]]` |

`code` shows at most 60 lines you read in this turn; `highlight 44-47` before the bar marks lines. `change` is read from git: the file against HEAD, or against another revision with `since <rev>` (`talk/talk.py since HEAD~2`). A new file shows as all added.

**Pointing while you talk.**

- `[[point: lines 12-14]]` before a sentence lights up those lines and dims the rest. It also takes `line N`, `row N` (counted under the header), `row "name"` (by its first cell) and `node X` (a Mermaid node id). On a change board, line numbers are the new ones. It points at the last board shown; name another one by its title: `[[point Turn path: node Q]]`. Use two to four in an explanation, not one per sentence.
- `[[key: one short line]]` after the sentence it sums up. It is not said. It goes on the **Key points** board, which is pinned first, keeps every key point of the call, and lights each one up as the voice reaches it.

**Building a board up while you talk.** A flowchart or a table can come in one thing at a time. Write the board once, whole, then put a verb just before the word that names each thing. Tags with no spoken word between them make one step.

| Verb | Effect |
|---|---|
| `[[+ api]]`, `[[+ api->db, db]]` | reveal; an edge brings its two nodes, a node its subgraph box |
| `[[next]]`, `[[next 2]]` | reveal the next one or two things, in the order the board declares them |
| `[[all]]` | reveal everything still hidden |
| `[[focus api->db]]`, `[[focus 42-45]]`, `[[focus row 2]]`, `[[focus none]]` | light these and dim the rest; `point` does the same |

Targets are the flowchart's node and subgraph ids, edges as `a->b`, code lines and table rows. Name another board by its title first: `[[+ Turn path: Q]]`. At most three things before the first verb. A board of more than three things with no verbs comes in one thing per sentence, and a `board:` line says so. A target that names nothing exactly is read as the nearest id or label, or dropped; each such repair is a `board:` line and is counted on the board's header. During a call a page (a file, an address or a session) opens behind the board in front and never comes forward by itself: say that it is there.

**Rules.**

- One board per idea. Titles are 2 to 5 plain words, because they are tab names.
- The same title updates its tab in place, and the changed rows light up. A new title makes a new tab.
- Put each show and point tag before the sentence about it: the stage fronts it when the voice gets there.
- Prefer a change board over describing an edit line by line.
- At most 3 key points per answer, in the user's words.
- Greek titles and text are fine.
- Close a table or diagram with `[[/show]]`. Tags are forgiving (`show: table`, `mermaid`, `diff`), and a markdown table or mermaid fence without a tag is still moved to the stage. `reply` prints a `board:` line for anything it could not show as asked: fix it in the next answer.

For example, after editing a file:
```
[[show change: talk/live_turns.py | Longer wait]] I raised how long the doorbell waits, from 30 to 90 seconds. [[point: line 47]] This is the one line that changed. [[key: the doorbell now waits 90 seconds]] A slow tool call no longer looks like a stalled session. [[key: slow tools no longer look stalled]] Nothing else in the file moved, so the tests did not need to change.
```

### What a turn may do

**Local files yes, the outside world and anything irreversible no.** Editing and creating local files is allowed from a turn, because git or the previous version can undo it. A turn never writes to Jira or Confluence, never posts to Slack or sends mail, never commits or pushes, and never deletes or runs anything destructive (`rm`, `git reset --hard`, `git checkout --`, `git clean`, `git stash`). For those, prepare the change, say that it is waiting for a typed yes in the terminal, and do it only after that typed yes.

Speech recognition does not prove who is speaking. If a request sounds odd or out of context, ask before acting on it.

## 4. After it ends

A background task that exits with `TALK_END` means the call is over: the user pressed End call, you sent `--end`, or nothing was said for an hour. Do not re-arm, and ignore a second `TALK_END` in the same call. Read the `transcript` path it names and write a short recap:

- **Key points**: start from the transcript's `Key point:` lines, in order, merging any that repeat.
- **What we covered**, three to five bullets in the user's terms, beyond the key points.
- **What is still open**: unsettled questions, and anything prepared but waiting for a typed yes.
- **Notes saved** during the call, with an offer to act on each.

The conversation then continues in this session.

## Restarting the server

A call outlives the server process that holds it. When the server stops (a crash, a `kill`, or a restart to load new code), its open calls are not ended: the next server on the port carries each one on with the same link, call id, conversation and stage. The page shows "Reconnecting to the call…" and then "Reconnected.", and `talk_client.py` waits up to 90 seconds for that server, starting one itself after a few seconds if nobody else has. So a doorbell or reply keeps its `--call` id through a restart, and you do not open a new call.

To load new code into a server that holds calls, run `uv run --script "$SKILL_DIR/talk.py" --restart`. It hands the calls over to a new server. A server on code from before this hand-over cannot hand its calls over, so `--restart` leaves it running while it holds an open call and says so.

## The activity hook

`hooks/talk-activity.sh` is an optional hook that lists this session's tool calls on the call page while it works. It exits at once when no call is running and never fails a tool call. Each session shows only on the call its doorbell names, so other sessions on the machine never appear. To install it, copy it somewhere outside any git checkout (for example `~/.claude/hooks/`) and register it in `~/.claude/settings.json`, with a timeout of 5 seconds, for `PreToolUse`, `PostToolUse`, `PostToolUseFailure` and `PermissionDenied` (matcher `*`), and for `Stop` and `StopFailure`.
