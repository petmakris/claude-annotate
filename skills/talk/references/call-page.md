# The call page: what the user sees and does

Read this to explain the page to the user or to debug it. Nothing here is needed to answer a turn.

## How a turn travels

- The page records the user while they hold the floor, one turn at a time.
- They press **Talk**, speak and press **Done**, or type instead.
- `talk.py` sends the recording to speech to text, and the words land in the text field, added to anything already typed.
- The user checks or changes the words and presses **Send**, which queues them as a turn. Nothing reaches this session before Send.
- A background "doorbell" command in this session exits with the turn, which wakes this session.
- This session answers with `talk_client.py reply`.
- The page shows the answer at once in its side panel, with a progress bar while the whole reading is made in one request.
- Then it plays the answer without a pause between sentences, lighting each word as it is said.
- A tap on a word plays from there, and the panel keeps that word in view until the user scrolls away.

### The wait card

- From Send until the answer lands, the top of the panel holds a wait card instead of the answer. It says where the question stands: **Sent** (no doorbell has collected it), **Claude is working** (the session has it), **Taking longer than usual** (90 seconds on), **Not picked up** (the server says nothing collected it, after 20 seconds with no tool call) and **Claude has gone quiet** (the session collected it and stopped, after 180 seconds).
- Its clock counts from the first time the question was sent, so a reload keeps it and a question sent again keeps the time it has waited; each question in flight is its own row ("Question 2 of 2") so none is hidden behind another; the stepper shows Sent, Picked up, Working and Answer; the step the session reports (its tool calls) and the finished ones are rows with their seconds.
- Each state has its way out. **Take back** (not collected) withdraws every question the card shows and **Cancel** (collected) the turn, and both put the words back in the box in order, with a note that says how many came back; **Send again** sends the questions once more, as one, and replaces them, and the card keeps a line that says when and how many ("Sent again 1:12 ago, 2 questions as one."); **Copy question** copies it. The amber states say the question is saved. None of it asks the user to go to a terminal.
- A draft typed meanwhile is kept, with a note, and **Replace question** sends it as a correction of the question in flight; plain Send adds to it instead.
- A correction replaces the question: what no doorbell had collected is taken back, and what the session had is marked replaced. That session's answer is kept in the list with its tag, never read aloud and never queued; the reader hears it only by asking. An answer that lands after the user added to its question is kept the same way, even when the session had already collected the addition as a turn of its own, and the answer covering the addition is the one that plays.
- An answer that arrives while another plays waits in a row, "Next: answer N", with **Skip**, which only drops it from the queue: the answer stays in the list, unplayed.

## The floor

- One talk server on the machine holds the calls of every session, each at its own link.
- Pressing Talk, sending text or playing an answer in a call gives it the floor: every other call's page pauses its voice at once.
- An answer that arrives in another call is shown but not played.
- When another call takes the voice, this call pauses and the state strip says "Paused: <call> took the voice" with Resume here. No toast covers the board; only the collapsed rail, which has no strip, uses the toast.
- Nothing changes for this session: it answers its own call by its call id.

## Other calls and coming back

- Every call is said in one set of words, on the Calls popover and on the list of calls at the root of the talk address: **Stalled**, **New answer** (or "N new answers"), **Answering**, **Talking now**, **Waiting for you**, **Ended**. A glyph and a colour go with each word, never the colour alone.
- The Calls button in the panel's header shows how many other calls need the user (a stalled one or one with answers not heard), amber when one is stalled. The popover lists this call first ("Here"), then the others by need, each with its age. **Next waiting** opens the call that needs the user most (the one waiting longest among equals); it is hidden while none does. **All calls** opens the list at the root.
- The tab's title and icon say what the call is doing, state word first: `Playing · topic`, `Answering · topic`, `Stalled · topic`, `Ended · topic`, `(2) New · topic` for answers that came while the tab was out of sight, plain `Talk · topic` otherwise. It runs from the poll, so a tab in the background keeps it current.
- The state strip under the header says the call's state in words (playing which answer and whether the board follows or is pinned, paused, answering with a clock counted from the question, not picked up, queued, on another screen, ended) with a switch for playing new answers by themselves. It is not a live region.
- After the tab was out of sight for five minutes (or the page was reopened after that), with answers that came meanwhile and were not played, the welcome-back card says how long the user was away and what came, with **Play the N new** (the answers play one after another; the first is the user's play, the rest start by themselves, and an answer that arrives meanwhile waits until they are played) and **Read them** (scrolls to them, plays nothing). A shorter absence (30 seconds) only puts the "Since you left, N not heard" divider before the first of them in the list of earlier answers.
- One polite live region (`#announcer`) says what happens while nobody watches the panel: Claude starts working or changes what it works on, a call stalls or ends, an answer arrives, a board changes while the voice is silent, another call has a new answer. Each sentence is said once, a burst as one, at least a second and a half apart, never while the user is typing. Other parts say something through `announce(text)`.
- The panel's first tab stop is "Jump to the latest answer"; the stage's reader is hidden from screen readers (the panel holds the same text).

## The panel and the gear

- The panel's top is the **Now card**, the current turn: the answer in the player (else the newest) with its number, the state in words (Playing, Paused, New, Ready, Played, Preparing the voice, Not read aloud), the question asked, the full text with the word being said lit (a tap on a word plays from there), the answer's boards as named chips (the Key points chip says how many points are new), and the player: previous and next sentence, play or pause, a labelled seek bar, the time and the speed (one tap to the next speed). Space, the arrows, Back and the card name one answer; when the board in front belongs to another answer, Play says "Play answer N".
- The card ends with the **Following strip**: Following (the stage goes where the voice goes) or Pinned (a board picked by hand stays in front), the board named, and one button, Pin board or Follow. A pinned stage also says which answer the voice is on. A chip tap, a tab, a step by hand and the gear's switch all show on it.
- Under the card, **Earlier** lists every other answer as one aligned row: number (filled when the answer is new), question and its first sentence, boards with their count, time and Play. A tap on a row opens it in place (full text, chips, Play from the start, Copy); Expand all opens every row; the boards cell fronts the answer's board. Play on a row starts that answer and puts the stage back on the voice. Search (under the list's head, and the header's magnifier) finds an answer by its question, its words or its boards, ignoring case and accents, and marks the match.
- Progress notes (`reply --status`) are not rows of the conversation: the foot says what Claude is doing now. An answer a correction replaced is tagged "Replaced by your correction".
- Under the conversation sit the text field and the mic.
- How the user talks and steers: the foot's Type, Talk and Live switch with a Your turn pill, a true mute in Live, the speed chip in the player (and Alt+S), Back as one sentence, the Keys sheet (`?`), layers that take and give back the focus, TV at one scale (`--tv`) and 44 px targets on a phone (`call-input.js`, `call-live.js`).
- Space pauses and plays. The left and right arrows move to the start of the previous or next sentence, wherever nothing is being typed.
- The panel sits on the left or the right, is as wide as it is dragged, and collapses to a rail that keeps the mic and the player.
- The gear holds speed, language, light or dark, and whether the stage follows the voice.
- With Azure the gear also picks the voice, with a short sample of each. The choice is kept in that browser.
- **Screen: TV** enlarges the panel, its words and the stage, for reading across a room.
- A board the reader picks on the stage stays in front whatever they play, until they press **Follow the voice** or the next answer starts.
- A new answer that arrives while the call's tab is hidden waits, and plays when the tab is seen again.

### Keys and input mode

- The switch under the player says how the next words get in: **Type** (the mic is put away and the cursor is in the field), **Talk** (press the mic, check the words, send) and **Live** (the microphone stays open). It is locked while a recording runs.
- The pill beside it says whose turn it is: Your turn, Typing, Recording, Claude is working, Claude is speaking, and in Live Listening, Hearing you, Muted or No sound heard.
- The voice speed is a chip in the player (and in the gear). Back is one sentence.
- Space plays and pauses; the left and right arrows go a sentence back or forward; **?** opens the list of every key (also the Keys button under the field and the row in the gear). The other shortcuts are Alt chords by physical key: S next speed, M the message field, P the player, V follow the voice again, T Talk or Done.
- Two skip links, the first stops of the page, go to the message field and to the player. A settings or keys layer takes the focus when it opens, keeps Tab inside it and gives the focus back to its button on Escape.
- The page's own words are English whatever language the user speaks: **Speech language** is only what the page listens for and what is read aloud.
- Full screen on a display 1700 px wide or more that has not chosen a size is TV size until full screen ends. `?screen=tv` or `?screen=desk` in the address chooses it and is kept. The gear's **Screen** row does the same.

## Live mode

- Nothing listens between turns, so nothing is said by accident, unless the user picks **Live** on the switch under the player.
- Then the microphone stays open, and what they say is sent after a short pause (0.8, 1.2 or 2 s).
- Speaking over an answer interrupts it by talking. "mm-hm", "yeah" and coughs let it go on.
- The pill **Interrupt** on the switch can limit interruptions to words that start with a cue such as "wait", "hold on", "sorry" or "listen"; **Send after** sets the pause.
- The mic button mutes and unmutes. A microphone that delivers only silence for ten seconds shows **No sound heard**.
- "slower", "faster" and "say that again slower" are spoken commands for the voice speed, acted on by the page.

## Speech engines

- Azure is used when its key is found: `AZURE_SPEECH_KEY`, else the output of `TALK_AZURE_KEY_COMMAND`.
- The region comes from `AZURE_SPEECH_REGION` or `TALK_AZURE_REGION`.
- Azure takes a second or two per answer and is billed per character.
- Without a key, the local VoiceStudio app speaks: free and private, but an answer takes about as long to make as to play.
- `TALK_SPEECH=azure` or `TALK_SPEECH=voicestudio` picks one by hand.

## The stage beside the panel

- An answer with no board of its own is read on the stage in large type, under the label of its answer, when the stage has no board in front; with a board in front the board stays and the sentence being said goes on the strip under it. The panel's Now card holds the full text either way.
- When the voice reaches a board's tag, the board takes the stage and the sentence being said stays under it on one line.
- At rest an answer with a board shows the board, and one with none leaves the board that was in front.
- A board the reader picked by hand stays in front until **Follow the voice**.
- A tap on a part of a board offers Ask about this and Play from here.
