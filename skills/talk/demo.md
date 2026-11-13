<!--
The stage demo: `talk.py --demo` plays these answers in a call, one each time the user says or types
anything ("next" goes on, "again" plays the same one, "back" the one before, "start over" the first).
Each answer is written exactly as a Claude session writes one, so it goes through the same board
tags, voice and stage. Answers are separated by a line holding only `---`. Paths are relative
to the repository root.
-->
Welcome to the stage demo. The stage reads each answer with you, the word being said lit, like these words now. Every board the stage can show comes past in turn, explained the way a call explains it, so you can see each one move with the voice. [[key: say next for the next board, again to replay one, back to go back]] Say next, or type it, whenever you are ready for the next board. [[key: the stage follows the voice until you take it in hand]] If you pick a board yourself, it stays in front whatever you play, until you press Follow the voice at the top of the stage or the next answer starts.
---
[[show code: skills/talk/live_turns.py:33-53 | How a turn waits]] This is real code from talk: the turn queue. [[point: lines 33-41]] When you send something, offer puts it in the queue, and a turn sent before Claude collects the last one is merged into it. [[point: lines 43-53]] Withdraw takes a line back again, but only while no doorbell has collected it. [[key: a code board lights the lines being talked about]] Say next to see a change.
---
[[show change: skills/stage/static/scene.js since 7e355e8 | Cells and the current one]] A change board shows a file against an older version, here the last edit to the stage's scene engine. [[point: old line 18]] A table used to key only its rows. [[point: lines 18-21]] Now every table cell gets a key of its own, so a single cell can be pointed at. [[point: lines 96-99]] And this new function reads which thing is being said from the frame itself, so the page never has to guess it. [[key: a change board shows what an edit did, line by line]] Next is a sequence.
---
[[show sequence | One turn, end to end]] {"actors": [{"id": "p", "label": "Call page", "tone": "edge"}, {"id": "t", "label": "Talk server", "tone": "internal"}, {"id": "a", "label": "Azure speech", "tone": "service"}, {"id": "c", "label": "Claude session"}],
 "legend": [{"tone": "edge", "label": "the browser"}, {"tone": "internal", "label": "talk.py"}, {"tone": "service", "label": "Azure"}],
 "phases": [{"id": "h", "label": "HEAR", "start_at": "s1"}, {"id": "k", "label": "THINK", "start_at": "s4"}, {"id": "v", "label": "SPEAK", "start_at": "s7"}],
 "steps": [
  {"id": "s1", "from": "p", "to": "t", "arrow": "request", "tone": "edge", "label": "sends what you said as a WAV", "sub": "POST /api/listen"},
  {"id": "s2", "from": "t", "to": "a", "arrow": "request", "tone": "service", "label": "turns the recording into words", "sub": "speech.transcribe"},
  {"id": "s3", "from": "a", "to": "t", "arrow": "event", "tone": "service", "label": "returns the words it heard"},
  {"id": "s4", "from": "c", "to": "t", "arrow": "request", "label": "the doorbell collects the turn", "sub": "talk_client.py doorbell"},
  {"id": "s5", "from": "c", "to": "c", "arrow": "self", "label": "reads the code and writes the answer"},
  {"id": "s6", "from": "c", "to": "t", "arrow": "request", "label": "sends the answer and its boards", "sub": "talk_client.py reply"},
  {"id": "s7", "from": "t", "to": "a", "arrow": "request", "tone": "service", "label": "reads the whole answer aloud", "sub": "speech.speak"},
  {"id": "s8", "from": "t", "to": "p", "arrow": "event", "tone": "edge", "label": "the answer is ready on the next poll", "sub": "GET /api/state"}]} [[/show]]
A sequence comes in a step at a time, here the path of one turn. When you stop talking, the call page sends what you said to the talk server. The server hands the recording to Azure, which turns it into words. Azure sends back the words it heard. Your Claude session collects the turn on its doorbell. It reads the code and writes the answer. Then it sends the answer and its boards back. The server has Azure read the whole answer aloud. And the answer is ready for the page on its next poll. [[point: step s5]] The slow part is always this one: Claude reading and writing. [[key: a sequence shows the step being said large, the rest as lines]] Next is a map.
---
[[show sequence | Backtesting before and after]] {"title": "A shared module takes the Service client's place",
 "compare": {
  "before": {"label": "master", "actors": [
    {"id": "ui", "label": "Proposal report"}, {"id": "svc", "label": "Report service", "sub": "ServiceBacktestingService"},
    {"id": "cl", "label": "Service client", "role": "PMP's module"}, {"id": "rc", "label": "Service"}],
   "steps": [
    {"id": "b1", "from": "ui", "to": "svc", "arrow": "request", "label": "asks for the backtest"},
    {"id": "b2", "from": "svc", "to": "cl", "arrow": "request", "label": "asks for the backtest data", "sub": "fetch(proposal)"},
    {"id": "b3", "from": "cl", "to": "cl", "arrow": "self", "label": "builds the requests with fixed lists, always quarterly"},
    {"id": "b4", "from": "cl", "to": "rc", "arrow": "request", "label": "asks for the ex-post measures"},
    {"id": "b5", "from": "cl", "to": "rc", "arrow": "request", "label": "requests the backtest series"},
    {"id": "b6", "from": "cl", "to": "svc", "arrow": "event", "label": "returns report timeseries", "reply_to": "b2"},
    {"id": "b7", "from": "svc", "to": "ui", "arrow": "event", "label": "returns the timeseries", "reply_to": "b1"}]},
  "after": {"label": "with the PR", "actors": [
    {"id": "ui", "label": "Proposal report"}, {"id": "svc", "label": "Report service", "sub": "ServiceBacktestingService"},
    {"id": "sm", "label": "Shared backtesting module", "role": "PMP and PSIM"}, {"id": "rc", "label": "Service"}],
   "steps": [
    {"id": "b1", "from": "ui", "to": "svc", "arrow": "request", "label": "asks for the backtest"},
    {"id": "b2", "from": "svc", "to": "sm", "arrow": "request", "label": "asks for the backtest data", "sub": "fetch(proposal, QUARTERLY, measures)"},
    {"id": "b3", "from": "sm", "to": "sm", "arrow": "self", "label": "builds the requests with the lists it is given"},
    {"id": "b4", "from": "sm", "to": "rc", "arrow": "request", "label": "asks for the ex-post measures"},
    {"id": "b5", "from": "sm", "to": "rc", "arrow": "request", "label": "requests the backtest series"},
    {"id": "b6", "from": "sm", "to": "svc", "arrow": "event", "label": "returns raw values", "reply_to": "b2"},
    {"id": "c1", "from": "svc", "to": "svc", "arrow": "self", "label": "builds the report timeseries", "sub": "ReportBacktestTimeseries"},
    {"id": "b7", "from": "svc", "to": "ui", "arrow": "event", "label": "returns the timeseries", "reply_to": "b1"}]}}} [[/show]]
A before and after sequence puts the two flows side by side, row for row, so you compare their shape instead of working it out yourself. [[point: before]] On master, the proposal report asks for the backtest. The report service asks the Service client in PMP's module for the backtest data. The client builds the requests with fixed lists, always quarterly. It asks Service for the ex-post measures. Then it requests the backtest series. And it returns report timeseries. [[point: after]] With the PR, a shared backtesting module takes the client's place. The service passes quarterly and its own measures down. The module builds the requests with the lists it is given, and returns raw values. The report service builds the report timeseries itself, the one row the old flow has no step for. [[point: both]] The Service requests are the same on both sides. [[key: a before and after board sets the two flows side by side, with a gap where one has no step]] Next is a map.
---
[[show flowchart | How talk's parts connect]] {"nodes": [{"id": "page", "role": "entry", "label": "Call page", "ref": "call.html · call.js", "sub": "your microphone, the conversation, the controls"},
  {"id": "launchd", "role": "code", "label": "launchd", "ref": "dev.talk", "sub": "keeps the server running, with the speech settings"},
  {"id": "talk", "role": "code", "label": "Talk server", "ref": "talk.py", "sub": "holds every call, one server per machine"},
  {"id": "azure", "role": "call", "label": "Azure speech", "method": "speech to text · text to speech"},
  {"id": "claude", "role": "code", "label": "Claude session", "ref": "talk_client.py", "sub": "answers with its full history and tools"},
  {"id": "stage", "role": "success", "label": "Stage", "ref": "webcompanion · stage.js", "sub": "code, tables and diagrams"}],
 "edges": [{"from": "page", "to": "talk", "label": "your words · polls"}, {"from": "launchd", "to": "talk", "label": "starts it"},
  {"from": "talk", "to": "azure", "label": "text ⇄ speech"}, {"from": "talk", "to": "claude", "label": "turns"},
  {"from": "talk", "to": "stage", "label": "boards"}]} [[/show]]
A map shows how parts connect, all of it faint at first. [[+ page]] Everything starts in the call page, in your browser. [[+ talk]] It talks to one talk server on this Mac. [[+ launchd]] launchd keeps that server running. [[+ azure]] The server sends your words to Azure, and gets each answer's voice back. [[+ claude]] Your Claude session collects turns from it. [[+ stage]] And the boards go to the stage, which the webcompanion daemon serves. [[point: node talk]] The talk server is the one part everything else goes through. [[key: a map is faint at first and lights part by part]] Next is an architecture map.
---
[[show map | Where talk's parts live]] {"title": "One talk server sits between the page, Claude and the speech service",
 "columns": ["Your browser", "This Mac", "Outside talk"],
 "boxes": [{"id": "page", "col": 0, "row": 0, "name": "Call page", "lines": ["`call.js`: microphone and player"], "b": 1, "r": 1},
  {"id": "stage", "col": 0, "row": 1, "name": "Stage", "lines": ["`stage.js`: the boards"], "b": 4, "r": 4},
  {"id": "talk", "col": 1, "row": 0, "rows": 2, "tone": "red", "name": "Talk server", "lines": ["`talk.py`, one per machine", "holds every call"], "b": 2, "r": 1},
  {"id": "claude", "col": 2, "row": 0, "tone": "blue", "name": "Claude session", "lines": ["`talk_client.py`"], "b": 3, "r": 2},
  {"id": "azure", "col": 2, "row": 1, "tone": "amber", "name": "Azure speech", "lines": ["billed per character"], "b": 3, "r": 3}],
 "zones": [{"label": "one browser tab", "boxes": ["page", "stage"]}],
 "arrows": [{"from": "page", "to": "talk", "label": "turns", "b": 2}, {"from": "talk", "to": "claude", "b": 3},
  {"from": "talk", "to": "azure", "tone": "amber", "b": 3}, {"from": "talk", "to": "stage", "label": "boards", "b": 4},
  {"layer": "route", "from": "page", "to": "talk", "n": 1, "r": 1, "label": "sends your words"},
  {"layer": "route", "from": "talk", "to": "claude", "tone": "blue", "n": 2, "r": 2, "label": "the doorbell wakes Claude"},
  {"layer": "route", "from": "talk", "to": "azure", "tone": "amber", "n": 3, "r": 3, "label": "reads the answer aloud"},
  {"layer": "route", "from": "talk", "to": "stage", "n": 4, "r": 4, "label": "puts up the boards"}]} [[/show]]
An architecture map puts each part where it lives. The call page runs in your browser tab. It talks to one talk server on this Mac. The server reaches your Claude session, and Azure speech outside. The stage shows the boards. [[key: a map is built up part by part, then follows one request]] [[point: box talk]] Everything goes through this one server, so now follow one turn. The page sends your words. The doorbell wakes Claude. Azure reads the answer aloud. And the server puts up the boards. Next is a table.
---
[[show table | Two speech engines]]
| | Azure | VoiceStudio |
|---|---|---|
| Speed | a second or two per answer | about as long to make as to play |
| Cost | billed per character | free |
| Runs on | Microsoft's servers | this Mac |
| Needs | `TALK_AZURE_KEY_COMMAND` | the VoiceStudio app open |
| Picked | when a key is found | when no key is found |
[[/show]]
A table comes in a row at a time. [[next]] [[point: cell "Speed" / "Azure"]] Azure answers in a second or two. [[point: cell "Speed" / "VoiceStudio"]] VoiceStudio takes about as long to make an answer as to play it. [[next]] Azure is billed per character, and VoiceStudio is free. [[next]] Azure runs on Microsoft's servers, VoiceStudio on this Mac. [[next]] Azure needs a key command, and VoiceStudio needs its app open. [[next]] [[point: cell "Picked" / "Azure"]] And talk picks Azure whenever it finds a key. [[key: a table can light one cell, not only a row]] Next is a diagram.
---
[[show flowchart | Live mode's states]] {"nodes": [{"id": "listening", "role": "entry", "label": "Listening", "sub": "the microphone is open"},
  {"id": "hearing", "role": "code", "label": "Hearing you", "sub": "you are speaking"},
  {"id": "sending", "role": "code", "label": "Sending", "sub": "speech to text, after your pause"},
  {"id": "working", "role": "code", "label": "Working", "sub": "Claude writes the answer"},
  {"id": "speaking", "role": "success", "label": "Speaking", "sub": "the answer is read aloud"}],
 "edges": [{"from": "listening", "to": "hearing", "label": "you speak"}, {"from": "hearing", "to": "sending", "label": "you pause"},
  {"from": "sending", "to": "working", "label": "a turn went"}, {"from": "working", "to": "speaking", "label": "it is ready"},
  {"from": "sending", "to": "listening", "label": "nothing said"}, {"from": "speaking", "to": "hearing", "label": "you cut in"},
  {"from": "speaking", "to": "listening", "label": "it ends"}]} [[/show]]
A map can go round in loops too, like the states of live mode. [[+ listening]] It listens. [[+ hearing]] When you speak, it hears you. [[+ sending]] After your pause, it sends what you said. [[+ working]] If there were words, Claude works on them. [[+ speaking]] And then it speaks the answer. [[+ sending->listening, speaking->hearing, speaking->listening]] A map with more than one loop is drawn as a ring. The arrows that go back curve across its middle: nothing said, you cut in, or the answer ends. [[key: a map that loops is drawn as a ring, its ways back across the middle]] Next is a small diagram.
---
[[show flowchart | Where a turn waits]] {"nodes": [{"id": "page", "role": "entry", "label": "Call page", "sub": "what you said"},
  {"id": "talk", "role": "code", "label": "Talk server", "sub": "keeps the turn until it is collected"},
  {"id": "claude", "role": "success", "label": "Claude session", "sub": "answers it"}],
 "edges": [{"from": "page", "to": "talk", "label": "your words"}, {"from": "talk", "to": "claude", "label": "the turn"}]} [[/show]]
A diagram of three parts or fewer is not stepped, so it shows whole from the start, and this one is written with no points and no reveals. The voice still lights each part as its name is said. Your words begin in the call page. The talk server keeps each turn until it is collected. Then your Claude session collects it on its doorbell. [[key: a small diagram shows whole, and lights the part being said]] Next, something you can open.
---
[[show page: README.md | The README]] A page is a file, an address or another session, and an answer brings it forward with its voice like any other board. This is the repository's README. [[key: an answer brings a page forward as it talks about it]] Pick another board and press Play: the stage keeps the board you picked until you press Follow the voice. Next is the end.
---
That was every board: code, a change, a sequence, a map, an architecture map, a table, a map with loops, a small diagram and a page. The key points are pinned at the end of the list. Go back through them with the arrows at the top of the stage, or say start over to play the demo again. [[key: the arrows at the top go back through every board]]
