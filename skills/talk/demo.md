<!--
The stage demo: `talk.py --demo` plays these answers in a call, one each time the user says or types
anything ("next" goes on, "again" plays the same one, "back" the one before, "start over" the first).
Each answer is written exactly as a Claude session writes one, so it goes through the same board
tags, scenes, voice and stage. Answers are separated by a line holding only `---`. A first line
`page: <path> | <title>` puts that file on the stage, behind the boards, as a page opens in a call.
Paths are relative to the repository root.
-->
Welcome to the stage demo. Every board the stage can show comes past in turn, explained the way a call explains it, so you can see each one move with the voice. [[key: say next for the next board, again to replay one, back to go back]] Say next, or type it, whenever you are ready for the next board. [[key: the stage follows the voice until you take it in hand]] If you pick a board yourself, the stage stops following the voice until you press Play or the next answer starts.
---
[[show code: skills/talk/live_turns.py:33-53 | How a turn waits]] This is real code from talk: the turn queue. [[point: lines 33-41]] When you send something, offer puts it in the queue, and a turn sent before Claude collects the last one is merged into it. [[point: lines 43-53]] Withdraw takes a line back again, but only while no doorbell has collected it. [[key: a code board lights the lines being talked about]] Say next to see a change.
---
[[show change: skills/stage/static/scene.js since 7e355e8 | Cells and the current one]] A change board shows a file against an older version, here the last edit to the stage's scene engine. [[point: old line 18]] A table used to key only its rows. [[point: lines 18-21]] Now every table cell gets a key of its own, so a single cell can be pointed at. [[point: lines 99-102]] And this new function reads which thing is being said from the frame itself, so the page never has to guess it. [[key: a change board shows what an edit did, line by line]] Next is a sequence.
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
[[show flowchart | How talk's parts connect]] {"nodes": [{"id": "page", "role": "entry", "label": "Call page", "ref": "call.html · call.js", "sub": "your microphone, the subtitles, the controls"},
  {"id": "launchd", "role": "code", "label": "launchd", "ref": "dev.talk", "sub": "keeps the server running, with the speech settings"},
  {"id": "talk", "role": "code", "label": "Talk server", "ref": "talk.py", "sub": "holds every call, one server per machine"},
  {"id": "azure", "role": "call", "label": "Azure speech", "method": "speech to text · text to speech"},
  {"id": "claude", "role": "code", "label": "Claude session", "ref": "talk_client.py", "sub": "answers with its full history and tools"},
  {"id": "stage", "role": "success", "label": "Stage", "ref": "webcompanion · stage.js", "sub": "code, tables and diagrams"}],
 "edges": [{"from": "page", "to": "talk", "label": "your words · polls"}, {"from": "launchd", "to": "talk", "label": "starts it"},
  {"from": "talk", "to": "azure", "label": "text ⇄ speech"}, {"from": "talk", "to": "claude", "label": "turns"},
  {"from": "talk", "to": "stage", "label": "boards"}]} [[/show]]
A map shows how parts connect, all of it faint at first. [[+ page]] Everything starts in the call page, in your browser. [[+ talk]] It talks to one talk server on this Mac. [[+ launchd]] launchd keeps that server running. [[+ azure]] The server sends your words to Azure, and gets each answer's voice back. [[+ claude]] Your Claude session collects turns from it. [[+ stage]] And the boards go to the stage, which the webcompanion daemon serves. [[point: node talk]] The talk server is the one part everything else goes through. [[key: a map is faint at first and lights part by part]] Next is a table.
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
A map can go round in loops too, like the states of live mode. [[+ listening]] It listens. [[+ hearing]] When you speak, it hears you. [[+ sending]] After your pause, it sends what you said. [[+ working]] If there were words, Claude works on them. [[+ speaking]] And then it speaks the answer. [[+ sending->listening, speaking->hearing, speaking->listening]] A map with more than one loop is drawn as a ring, and the arrows that go back curve across its middle: nothing said, you cut in, or the answer ends. [[key: a map that loops is drawn as a ring, its ways back across the middle]] Next is a page.
---
page: README.md | The README
A page is a file, an address or another session, and in a call it opens behind the boards. The repository's README is on the stage now: pick it from the list of boards, under the counter at the top, to read it. [[key: a page opens behind the boards; pick it from the list]] Next is the end.
---
That was every board: code, a change, a sequence, a map, a table, a map with loops, a page, and the key points pinned at the end of the list. Go back through them with the arrows at the top of the stage, or say start over to play the demo again. [[key: the arrows at the top go back through every board]]
