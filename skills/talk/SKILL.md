---
name: talk
description: Start a spoken discussion with this Claude Code session in a browser page. The user presses Talk, speaks, presses Done, checks the words and presses Send; Azure speech (or VoiceStudio on this Mac, without an Azure key) turns it into text, this session answers with its full history and tools, and the answer is read aloud while it shows in a side panel beside the stage. Code, diagrams and tables go on that stage, which keeps the page's full height. Use when the user says "/talk", "let's talk about X", "voice discussion", or wants to discuss something out loud.
user-invocable: true
argument-hint: optional — the topic (defaults to what the conversation is about)
---

# /talk — a spoken discussion with this session

`$SKILL_DIR` is this skill's base directory, as shown when the skill loads.
It holds `talk.py` (the server and call page), `speech.py` (which engine speaks), and `talk_client.py` (this session's side of the call).

How it works, in short:

- The user speaks into a browser page, checks the words and presses **Send**, which queues them as a turn.
- A background "doorbell" command in this session exits with the turn, which wakes this session.
- This session answers with `talk_client.py reply`.
- The page reads the answer aloud, lights each word as it is said, and puts boards (code, diagrams, tables) on a stage beside the conversation.
- Nothing reaches this session before Send.
- One talk server on the machine holds the calls of every session, each at its own link. This session answers its own call by its call id.

What the page looks like, its gear, its floor rules and live mode: `references/call-page.md`.

## 1. Preconditions (check silently; fix what you can)

1. **A browser with a microphone.** The page records through the browser, so it must be opened on `localhost` or over https. In a cloud session with no way to reach the page, stop and say so.
2. **uv.** `command -v uv`; if missing, install it (https://docs.astral.sh/uv/).
3. **Speech.** With Azure, nothing to start. Without it, **VoiceStudio**, the local speech app, answering at `VOICESTUDIO_URL` (default `http://127.0.0.1:3900`).
   - Its server runs only while the app is open. On a Mac `talk.py` opens it with `open -a VoiceStudio` and waits, which takes about a minute from cold.
   - If the user asks to check the setup, or a call fails, run `uv run --script "$SKILL_DIR/talk.py" --doctor` and relay its `[ok]` and `[FAIL]` lines.
4. **webcompanion.** The stage needs the daemon. `python3 "$SKILL_DIR/../stage/stage.py" link --cwd "<repo root>"` must print a URL. If it fails, relay its message.

The topic is one line naming what the call is about, from the argument or the conversation. No briefing is written: this session already has the context.

## 2. Launch

1. Open the call, **`run_in_background: true`**. This starts the server when none runs, or joins the one that does, then exits:
   ```
   uv run --script "$SKILL_DIR/talk.py" --topic "<topic>" --out "${TMPDIR:-/tmp}/talk/<slug>-<HHMMSS>" --code "<repo root>" --no-open [--language en|el]
   ```
   - `--code` is the repository this session works in. The board reads code from it.
   - The page's address comes from `TALK_URL_BASE`, and the stage's from `TALK_STAGE_BASE`, when they are set. They are the https addresses that reach talk's port 8766 and the webcompanion daemon's port 3080 from other machines. https is what lets the browser use the microphone from any machine. `--url-base` and `--stage-base` override them.
   - `--no-open` because the user is often at another machine.
   - `--language` fixes the language the page listens for first. The default, `auto`, detects English or Greek. Answers are read in the language they are written in.
   - `--voice` names an Azure neural voice (default `en-US-AvaMultilingualNeural`), or with VoiceStudio a voice profile by name or id (default the profile named `Talk`). Without a VoiceStudio profile, OmniVoice draws a different random speaker for every answer, so the server prints a `speech:` warning; relay it.
2. Wait for the task to finish (seconds, or about a minute when VoiceStudio had to be opened). Read its output:
   - `Open http://127.0.0.1:<port>/c/<call id>`, and a `Link <TALK_URL_BASE>/c/<call id>` line when `TALK_URL_BASE` is set.
   - `Call <call id>`: keep it exactly, since every `talk_client.py` command names it with `--call=<call id>` (with `=`: an id may start with a character the parser would read as an option).
   - `Stage <url> (folder <path>, slug <slug>, sid <sid>)`: every call has a stage of its own, so keep the folder and the sid exactly for every `stage.py` call during the call.
   - A line starting `talk:` instead means no call was opened: relay it.
3. Arm the doorbell, **`run_in_background: true`**:
   ```
   python3 "$SKILL_DIR/talk_client.py" doorbell --call="<call id>"
   ```
4. Give the `Link` line's address, always whole: the call id in `/c/<call id>` is its key.
   - With no `Link` line, give the `Open` address, and say that it opens only on this machine. The microphone needs `localhost` or https, so another machine needs `TALK_URL_BASE` and `TALK_STAGE_BASE` set to https addresses that reach those ports.
   - In two lines, say the page is ready: press Talk, speak, press Done, check the words, press Send. Then end the turn.

## 3. Answering a turn

A background task that exits with a line starting `TALK_TURN` is the user speaking.

- Its JSON holds the turn `id` and `said`, the lines since the previous turn.
- `you` lines are what speech recognition heard, so read them charitably. Two turns sent before you collect them arrive together.
- A `you` line with `interrupted` is the user cutting into answer `answer` in live mode. `heard` is its last words before they spoke, and `rest_unheard` says the rest was never played.
  - Answer what they asked, as a person who was interrupted would.
  - If something they did not hear still matters, say it briefly, never the whole rest again.
- A `you` line with `while_working: true` was said while you were still working on their previous turn. Treat it as an addition to that question (a correction, an afterthought, "and also...") and fold it into the one answer.
- In live mode some words never reach you: spoken commands ("go on", "pause", "repeat that", "go back", "never mind", "stop listening") are acted on by the page.
  - "never mind" or the Undo button take back a turn you have not collected yet.
  - If you see a plain "never mind", you already had the turn: drop what you were doing with it and say so in a few words.
- A sentence that stops mid-thought ("so what about the... um") is held a few seconds for its end, so a turn can arrive a moment after the user stopped talking.
- A `you` line that starts `About "<part>": ` was asked from that part of a board on the stage: answer about that part.

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

`reply` exit codes:

- 0: sent. A status for a turn already answered prints `ignored` and is not shown.
- 2: refused, unreachable or no such turn.
- 4: the call has ended, so nothing was shown and you do not re-arm. When it names a transcript, write the recap from it as for `TALK_END`.
- `board:` lines after `sent` name a tag that was not shown as asked, or was shown only after a fix. Fix it in the next answer.
- A doorbell that prints `doorbell superseded` was replaced by a newer one: do not re-arm for it.

**An answer with no turn.**

- A turn takes one reply. When that reply went wrong (a board not shown, a wrong board), or the user asks in the terminal for something on the call, send another answer with `python3 "$SKILL_DIR/talk_client.py" say --call="<call id>"`.
- The answer goes on stdin in the same tag language as a reply. It is shown and read aloud like a reply and prints the same `sent` and `board:` lines. It exits 4 when the call is over.
- Never tell the user to speak or type on the call so that you can answer: say it.

### Choose the board by the question

First ask whether the turn has anything for the eye. Then pick the board from what the listener must see, before you write a word. A table is the last resort.

| The question is about | Board | Why not a table |
|---|---|---|
| what happens in order between actors (a request, a login, a release, a wait) | sequence | a table of steps loses who talks to whom |
| what changed: how it was and how it is now, or A versus B as a flow | sequence with compare (`compare`) | a table of two columns loses the order |
| the parts of a system, where one request goes, what must never call what | map | a table lists parts and hides how they connect |
| a decision, branches, a state machine | flowchart | a table hides the arrows |
| how much, how long, how many: sizes, costs, waits, a quantity through a pipeline | bars | a table lists numbers and hides their size |
| what happens to commits or to a tree: a rebase, a merge, a split, a delete | graph | a table cannot show a shape changing |
| code, or an edit you made | code, change | never describe it in a table |
| which of several options to choose, or how three things differ | the verdict first, then one concrete case through each option as a sequence with compare, or bars when one measure decides | a table of options is read aloud cell by cell and teaches nothing the voice did not |
| the state of the user's work: PRs, tickets, risks, a week | what blocks what as a flowchart, how much as bars, then only the one or two items to act on | a table of every item is the list they already have |
| a rule that is broken in code | a map with a solid red arrow labelled `breaks the rule` on the call that happens | a dashed arrow labelled `never` says it does not happen |
| a fixed tree or hierarchy that does not change (an index, a folder tree, a class tree) | graph, with no `lane` on any node | nothing to move, so no steps and no before and after |
| a yes or no, one number, a repeat, a recap, a thanks, a go-ahead | no board: two or three plain sentences | nothing for the eye, and a board would only decorate |
| several things judged on the same short measures, and the verdict does not depend on a story | table, last: at most 4 rows and 4 columns, each cell 1 to 3 words | the one case a table is for |

Before a table, ask: could the viewer say what each column measures, and would the voice add something the cells do not say?

- If the rows are steps, parts, states, days or events, the board is a sequence, a map, a flowchart or bars, never a table. Days, events and findings go in a list or a sequence.
- If you cannot name what every column measures, it is not a table.
- A table is at most 4 rows by 4 columns, each cell 1 to 3 words. A fifth row is a sentence.
- Speak the verdict, never the cells: the voice says what the rows mean, the table holds the values.
- No real shape means no diagram. A diagram with nothing in it that moves, branches or compares is decoration: say it in a sentence.

### Writing the answer

- **The stage reads your words aloud with you.** Each sentence appears as it is said and the word being said is lit, so the words on the stage are always the words being spoken. When the voice reaches a board's tag, the board takes the stage for the rest of the answer, and the sentence being said stays under it on one line.
- **A question about structure or flow is answered with the board.**
  - At most one plain claim sentence first, then the board's tag, then walk through it with points. The board opens on the first sentence, not after a lead-in.
  - Show the whole board first, then zoom into the part that matters.
  - Any other answer says its plain part first, then puts up what hearing cannot carry.
- **A turn with nothing for the eye has no board.** A yes or no, one number, a repeat of what you said, a recap, a thanks and a go-ahead are answered in two or three plain sentences. Never put the number, the file or the test result on a code board or a table to look thorough.
- **Short.** One idea per sentence, under 20 words. `reply` prints a `board:` line for a sentence over 30 words or an answer over 220. Plain sentences, with no markdown, lists or symbols. Never read identifiers or values aloud one by one: put them on the stage and say what they mean.
- **Labels are words you will say.** A part lights when a sentence says its label, so write labels as spoken words (`the new server`), never symbols or primes (`X'`, `->`, `v2'`). Put the symbol in `sub`.
- **Say the parts in the order you list them**, one sentence for each, so a part comes in when its sentence is said and not before.
- **A step an actor does to itself** (it reads, it decides, it waits) is `"arrow": "self"` with the same actor in `from` and `to`. A call between two actors is a `request`.
- **Every number you say goes on the board**, in a step's `note` or `sub`, or a box's `lines`. Never leave a spoken number out of the picture.
- **Draw a process as a zone with its name and port**, around the boxes it serves. A named part gets its own box.
- **Draw a wait as a request with a reply.** A long poll is a `request` plus an `event` with `reply_to`, which holds a bar open between them. Never draw a wait as a push from the server.
- **Draw a relation you speak about.** A relation that must never happen is a dashed red arrow labelled `never`.
- **Close with the verdict.** End a before and after board with an `outcome` (tone `amber` for a threat or cost) that states what the reader should keep.
- **One step at a time.** Explain three to six steps, then end the answer and let the user ask for more. A user who asks for another example gets the same thing another way (another example, a picture, smaller steps), never the same words again.
- **Start where the user is.** Never assume they have seen the thing. Carry one concrete example through the whole explanation, with real or made-up values, and say which.
- **Key facts first.** The first sentence carries what matters.
- **Say what you changed** when you edited a file, in a few words, and show the edit with a `change` board.
- `[[note: ...]]` saves a note to the transcript and shows it on the page.
- **A file the user is working on and asked to see goes on the stage by name**, never one you only read for your own answer: `python3 "$SKILL_DIR/../stage/stage.py" show deck path/to/deck.html#slide-3 --cwd "<folder>" --slug "<sid>"`.
  - Pass `--cwd` and `--slug` on every `stage.py` call during the call (the folder and sid of the Stage line). Without them it lands on a different stage the call page does not show, and with a wrong one `stage.py` fails.
  - A name a board of the call already holds is refused: pick another.
  - Do it in the same message as the status and the first work call, so it is on screen while you work. A file view reloads by itself on every save.
- **Stopping.** When the user wants to stop, send a two or three sentence wrap-up with `reply <id> --call="<call id>" --end` (never together with `--status`), and re-arm once, in the same message, to collect the `TALK_END` for the recap.
  - When they ask in the terminal instead, with no turn left to answer, send the wrap-up with `python3 "$SKILL_DIR/talk_client.py" end --call="<call id>"` (the wrap-up on stdin, as for a reply) and re-arm the same way. It exits 4 when the call was already over.
  - The page keeps the answers playable after the end.

### Teaching with the board

To see every board move with the voice without a session answering, `uv run --script "$SKILL_DIR/talk.py" --demo` plays `demo.md`: one answer per thing the user says (next, again, back, start over), written exactly as you write yours.

Board tags are taken out of the speech and drawn on the stage beside the conversation, one board per title, with the latest in front and the rest one click back.

| Board | Use it for | Tag |
|---|---|---|
| sequence | who talks to whom, in time: a request's path, a release, a wait. Say "two stages" or "phases" and give it `phases` | `[[show sequence \| Turn path]]` a JSON spec `[[/show]]` |
| sequence with compare | how a flow was before a change and how it is after it, side by side, row for row | `[[show sequence \| Report path]]` a spec with `compare` `[[/show]]` |
| map | an architecture: the parts of a system in columns and zones, where each caller comes in, and one request followed across it | `[[show map \| Where pay lives]]` a map spec `[[/show]]` |
| flowchart | a decision or process that branches, joins or ends in outcomes, or a state machine (loops are fine) | `[[show flowchart \| Floor rule]]` a JSON spec `[[/show]]` |
| bars | how much, how long or how many, one bar a thing on one scale, linear or log | `[[show bars \| Cache costs]]` a bars spec `[[/show]]` |
| graph | a commit graph or a tree, and what a change does to it, before and after | `[[show graph \| Rebase]]` a graph spec `[[/show]]` |
| code | existing code you are explaining; the line range is optional | `[[show code: talk/live_turns.py:40-58 \| How a turn waits]]` |
| change | after you edit a file, instead of describing the edit | `[[show change: talk/talk.py \| What I changed]]` |
| table | two to four short measures of three or more things (at most 4 by 4 cells of 1 to 3 words), with nothing connecting them, and you say the verdict, never the cells. Last resort | `[[show table \| Ports]]` a markdown table `[[/show]]` |
| page | a page you made or a link: a file in `--code`, an address, or `session:<kind>/<slug>` | `[[show page: docs/walkthrough.html \| Report data walkthrough]]` |
| screen | a user interface explained part by part, from a spotlight spec in `--code` | `[[show screen: docs/spotlight.json \| Filing a request]]` |

Every field of every board, how each one draws, and the rules for Mermaid, paths and pages: `references/boards.md`.

A spec is the inner object only, never annotate's `{"id", "kind", "spec"}` wrapper. A spec the tool refuses is not shown, and a `board:` line quotes why. A call draws no Mermaid: write the JSON spec.

**A map**, a zoned architecture with one request followed across it and a relation that must never happen:

```
[[show map | Where a request goes]] {"title": "The page never reaches the stage's storage",
 "columns": ["Browser", "Talk server", "Webcompanion"],
 "boxes": [{"id": "page", "col": 0, "row": 0, "name": "Call page", "lines": ["`call.js`"], "b": 1, "r": 1},
  {"id": "talk", "col": 1, "row": 0, "tone": "red", "name": "Talk server", "lines": ["`talk.py`"], "b": 2, "r": 2},
  {"id": "store", "col": 2, "row": 0, "name": "Stage storage", "lines": ["boards live here"], "b": 3, "r": 3}],
 "zones": [{"label": "talk, port 8766", "boxes": ["talk"]}, {"label": "webcompanion, port 3080", "boxes": ["store"]}],
 "arrows": [{"from": "page", "to": "talk", "b": 2}, {"from": "talk", "to": "store", "b": 3},
  {"from": "page", "to": "store", "tone": "red", "dash": true, "label": "never", "b": 3},
  {"layer": "route", "from": "page", "to": "talk", "n": 1, "r": 1, "label": "sends your words"},
  {"layer": "route", "from": "talk", "to": "store", "n": 2, "r": 2, "label": "puts up the boards"}]} [[/show]]
The call page sends your words to the talk server, on port 8766. The talk server puts up the boards in the stage storage, which webcompanion keeps on port 3080. [[point: box talk]] Everything goes through the talk server, and the page never reaches the stage storage itself.
```

**A sequence with a wait**: a request that stays open until its reply, and a number on the board:

```
[[show sequence | The doorbell waits]] {"actors": [{"id": "d", "label": "Doorbell", "sub": "talk_client.py"}, {"id": "s", "label": "Talk server", "sub": "talk.py"}, {"id": "p", "label": "Call page"}],
 "steps": [{"id": "a1", "from": "d", "to": "s", "arrow": "request", "label": "asks for the next turn", "sub": "GET /api/turn"},
  {"id": "a2", "from": "p", "to": "s", "arrow": "request", "label": "sends what you said"},
  {"id": "a3", "from": "s", "to": "d", "arrow": "event", "label": "answers the open request", "reply_to": "a1", "note": "25 s a try"}]} [[/show]]
```

**A sequence in two phases**: when you say stage or phase aloud, give the spec `phases`, each starting at the step that opens it, so the board draws the split you promised:

```
[[show sequence | Login in two stages]] {"actors": [{"id": "u", "label": "Browser"}, {"id": "a", "label": "Auth server"}, {"id": "g", "label": "Google"}],
 "phases": [{"id": "p1", "label": "Stage one: prove who you are", "start_at": "s1"}, {"id": "p2", "label": "Stage two: get a session", "start_at": "s3"}],
 "steps": [{"id": "s1", "from": "u", "to": "g", "arrow": "request", "label": "asks Google to sign you in"},
  {"id": "s2", "from": "g", "to": "u", "arrow": "event", "label": "sends back a one-time code", "reply_to": "s1"},
  {"id": "s3", "from": "u", "to": "a", "arrow": "request", "label": "hands the code to the server"},
  {"id": "s4", "from": "a", "to": "u", "arrow": "event", "label": "opens your session", "reply_to": "s3"}]} [[/show]]
In stage one, the browser asks Google to sign you in. Google sends back a one-time code. In stage two, the browser hands the code to the server. The server opens your session.
```

**A sequence with compare**: before and after, closed with the verdict on the board and in speech. An `outcome` sits beside `compare`, and `[[point: outcome]]` lights it:

```
[[show sequence | Report path]] {"compare": {
 "before": {"label": "master", "actors": [{"id": "svc", "label": "Report service"}, {"id": "cl", "label": "Service client"}, {"id": "rc", "label": "Service"}],
  "steps": [{"id": "a1", "from": "svc", "to": "cl", "arrow": "request", "label": "asks for its data"},
            {"id": "a2", "from": "cl", "to": "rc", "arrow": "request", "label": "sends requests with fixed lists"}]},
 "after": {"label": "with the PR", "actors": [{"id": "svc", "label": "Report service"}, {"id": "sm", "label": "Shared module", "tone": "amber"}, {"id": "rc", "label": "Service"}],
  "steps": [{"id": "a1", "from": "svc", "to": "sm", "arrow": "request", "label": "asks for its data"},
            {"id": "a2", "from": "sm", "to": "rc", "arrow": "request", "label": "sends requests with the lists it is given"}]}},
 "outcome": {"tone": "amber", "title": "One module, two reports", "lines": ["a change there reaches both"]}} [[/show]]
[[point: before]] Before, the service asks the client for its data. [[point: after]] Now the shared module takes its place. [[point: outcome]] The cost is that one change reaches both reports. [[key: two teams now share one module, so a change there reaches both reports]]
```

**Bars**: how big, on a scale you can see. One unit for the board, `scale` `log` when the values span powers of ten, and a bar's `note` for a number you say:

```
[[show bars | Cache costs]] {"title": "A miss costs a hundred times a hit", "unit": "ns", "scale": "log",
 "bars": [{"id": "l1", "label": "L1 cache", "value": 1, "note": "about four cycles"},
  {"id": "l2", "label": "L2 cache", "value": 4}, {"id": "ram", "label": "Main memory", "value": 100, "tone": "red"}]} [[/show]]
The L1 cache answers in about one nanosecond. [[point: bar l2]] The L2 cache takes four. [[point: bar ram]] Main memory takes a hundred, and that is the miss.
```

**A graph**: commits or a tree, before and after. A node is `new` (after only), `ghost` (still there, faint, after) or `struck` (removed, after): mark every node the change replaces or removes, or it stays in the after as current. Its `lane` is the row it sits in:

```
[[show graph | Rebase]] {"title": "A rebase copies your commits onto the new tip",
 "nodes": [{"id": "a", "label": "base commit", "lane": "main"}, {"id": "c", "label": "new tip", "lane": "main"},
  {"id": "d", "label": "old work", "lane": "feature", "state": "ghost"}, {"id": "d2", "label": "copied work", "lane": "after rebase", "state": "new"}],
 "edges": [{"from": "a", "to": "c"}, {"from": "a", "to": "d"}, {"from": "c", "to": "d2"}]} [[/show]]
[[point: before]] Before, your work hangs off the base commit. [[point: after]] Now the copied work hangs off the new tip. [[point: node d]] The old work is still there, but nothing reaches it.
```

For a flowchart:

```
[[show flowchart | Floor rule]] {"nodes": [{"id": "a", "role": "entry", "label": "Turn arrives"},
 {"id": "b", "role": "decision", "label": "Floor free?"}, {"id": "c", "role": "success", "label": "Played"}],
 "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"}]} [[/show]]
```

**A table** is a markdown table. Escape a pipe in a cell with `\|`. Rows arrive with the sentences that name them, and the row being said is lit.

**Pointing while you talk.**

- `[[point: lines 12-14]]` before a sentence lights up those lines and dims the rest.
- Code: `line N`, `lines A-B`. On a change board, line numbers are the new ones and a range takes any line removed inside it; `old line N` (or `old lines A-B`) points at a removed line, by its number before the change.
- Table: `row N`, `rows A-B`, `rows 2,5`, `row "name"` (by its first cell), `column "header"`, `cell "row" / "column"` (by its row's first cell and its column's header, or by numbers: `cell 2 / 3`).
- Diagrams, by kind: a flowchart takes `node X` and `edge a->b` (or `edge "label"`); a graph takes `node X`; a sequence takes `step S` (a step id) and `outcome`; a map takes only `box X`, `zone N` (the first zone is 0) and `route N`, and refuses `edge a->b` with a `board:` line, so point at the box the arrow ends in or at its `route N`. On a before and after sequence or a graph: `before`, `after`, `both`. `[[point: outcome]]` is how a sequence or compare board points at its verdict.
- Bars: `bar X` (a bar id) or `rows A-B`. A name that is nearly an id is read as it, with a `board:` line; one that is not names the ids.
- A lit step or node is drawn as the one being said.
- It points at the last board shown. Name another one by its title: `[[point Turn path: node Q]]`.
- Use two to four in an explanation, not one per sentence.
- `[[key: one short line]]` after the sentence it sums up. It is not said. It goes on the **Key points** board, which is pinned first, keeps every key point of the call, and lights each one up as the voice reaches it.

**Building a board up while you talk.** A sequence, a flowchart, a map or a table can come in one thing at a time. With no verbs, each thing comes in with the first sentence that names it, so label each part with the words you will say.

To control it, write the board once, whole, then put a verb just before the word that names each thing. Tags with no spoken word between them make one step.

| Verb | Effect |
|---|---|
| `[[+ api]]`, `[[+ api->db, db]]` | reveal. An edge brings its two nodes, a node its subgraph box, a step its two actors. An edge also comes in by itself once both its nodes are shown |
| `[[next]]`, `[[next 2]]` | reveal the next one or two things, in the order the board declares them |
| `[[all]]` | reveal everything still hidden |
| `[[focus api->db]]`, `[[focus 42-45]]`, `[[focus rows 2-3]]`, `[[focus none]]` | light these and dim the rest. `point` does the same. The next reveal with no point of its own turns the light off |

- Targets are node and subgraph ids, a flowchart's edges as `a->b` (a map's targets are its boxes, zones and routes, never `a->b`), sequence step and actor ids, a map's `box X`, `zone N` (from 0) and `route N`, a bars board's `bar X`, code lines and table rows, or their labels. Name another board by its title first: `[[+ Turn path: Q]]`.
- At most three things before the first verb.
- A board of more than three things with no verbs comes in with the sentences that name each thing, and a `board:` line says so.
- A target that names nothing exactly is read as the nearest id or label, or dropped. Each such repair is a `board:` line and is counted on the board's header.
- A board none of whose reveals names anything shows whole from the start.

**Rules.**

- One board per idea. Titles are 2 to 5 plain words, because they are the boards' names in the stage's header and list.
- The same title updates its board in place, and the changed rows light up. A new title makes a new board.
- Each answer keeps the steps it said a board with, so a replay of an earlier answer unfolds the board as that answer did.
- Put each show and point tag before the sentence about it: the stage fronts it when the voice gets there.
- Prefer a change board over describing an edit line by line.
- At most 3 key points per answer, in the user's words. A title over 5 words, or more than 3 key points, gets a `board:` line asking you to cut it.
- Greek titles and text are fine.
- Close a table or diagram with `[[/show]]`. Tags are forgiving (`show: table`, `mermaid`, `diff`), and a markdown table or mermaid fence without a tag is still moved to the stage, and a `[[point]]` after it lights its rows; a table's separator row needs one `---` per header cell, or `reply` rewrites it and says so. `reply` prints a `board:` line for anything it could not show as asked: fix it in the next answer.
- The scene tag and the four stop tags are retired: never write them.

For example, after editing a file:
```
[[show change: talk/live_turns.py | Longer wait]] I raised how long the doorbell waits, from 30 to 90 seconds. [[point: line 47]] This is the one line that changed. [[key: the doorbell now waits 90 seconds]] A slow tool call no longer looks like a stalled session. [[key: slow tools no longer look stalled]] Nothing else in the file moved, so the tests did not need to change.
```

### What a turn may do

**A spoken turn counts like a typed message.** A turn may do anything a message typed in the terminal could, and a spoken yes is a yes. The user's own rules apply exactly as they do in the terminal: before anything destructive or outward-facing (`rm`, `git reset --hard`, a commit, a push, a post), show the state and the exact commands in an answer, and run them once the user says go on the call.

Speech recognition does not prove who is speaking. If a request sounds odd or out of context, ask before acting on it.

## 4. After it ends

A background task that exits with `TALK_END` means the call is over: the user pressed End call, you sent `--end`, or for an hour nothing was said and no doorbell waited. Do not re-arm, and ignore a second `TALK_END` in the same call. Read the `transcript` path it names and write a short recap:

- **Key points**: start from the transcript's `Key point:` lines, in order, merging any that repeat.
- **What we covered**, three to five bullets in the user's terms, beyond the key points.
- **What is still open**: unsettled questions, and anything prepared but still waiting for the user's go.
- **Notes saved** during the call, with an offer to act on each.

The conversation then continues in this session.

## The server and the hook

A call stays open while its doorbell is armed, outlives a server restart, and closing the page never ends it. Always re-arm the doorbell after an answer.

Restarting the server, the launchd service and the activity hook: `references/server.md`.
