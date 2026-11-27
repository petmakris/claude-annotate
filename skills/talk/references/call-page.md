# The call page: what the user sees and does

Read this to explain the page to the user or to debug it. Nothing here is needed to answer a turn.

## How a turn travels

- The page records the user while they hold the floor, one turn at a time.
- They press **Talk**, speak and press **Done**, or type instead.
- `talk.py` sends the recording to speech to text, and the words land in the text field, added to anything already typed.
- The user checks or changes the words and presses **Send**, which queues them as a turn. Nothing reaches this session before Send.
- A background "doorbell" command in this session exits with the turn, which wakes this session.
- This session answers with `talk_client.py reply`.
- The page shows the answer at once in its side panel; the play button turns while the whole reading is made in one request.
- Then it plays the answer without a pause between sentences, lighting each word as it is said.
- A tap on a word plays from there, and the panel keeps that word in view until the user scrolls away.

### Claude thinking

- From Send until the answer lands, the end of the conversation shows three dots, the step in a few words and a clock: **Sent** (no doorbell has collected it), what Claude reports it is doing (else **Claude is working**), **Taking longer than usual** (90 seconds on), **Not picked up** and **Claude has gone quiet** (amber).
- The clock counts from the question's own time, so a reload keeps it.
- One way out sits on that line: **Cancel** puts the words back in the field; when nothing moves it is **Send again**, which sends the question once more and replaces the first.
- Words typed meanwhile and sent are added to the question in flight.
- An answer to a question the user has since replaced is kept in the conversation, dimmed, with "Replaced by your correction" and **Play**; it is never read aloud by itself.
- An answer that arrives while another plays starts when that one ends.

## The floor

- One talk server on the machine holds the calls of every session, each at its own link.
- Pressing Talk, sending text or playing an answer in a call gives it the floor: every other call's page pauses its voice at once.
- An answer that arrives in another call is shown but not played.
- When another call takes the voice, this call pauses and the line above the field says which call took it. Play takes it back.
- Nothing changes for this session: it answers its own call by its call id.

## Other calls

- Every call is said in one set of words, on the Calls popover and on the list of calls at the root of the talk address: **Stalled**, **New answer** (or "N new answers"), **Answering**, **Talking now**, **Waiting for you**, **Ended**. A glyph and a colour go with each word, never the colour alone.
- The Calls button shows in the panel's title only while another call needs the user (a stalled one or one with answers not heard), with how many. The popover lists this call first, then the others by need; **Next waiting** opens the one that needs the user most, **All calls** opens the list at the root.
- The tab's title and icon say what the call is doing, state word first: `Playing · topic`, `Answering · topic`, `Stalled · topic`, `Ended · topic`, `(2) New · topic`, plain `Talk · topic` otherwise.
- One polite live region (`#announcer`) says what happens while nobody watches the panel: Claude starts working, a call stalls or ends, an answer arrives, a board changes while the voice is silent, another call has a new answer. Each sentence is said once, never while the user is typing.

## The panel

The panel holds four things and nothing else. Every part must earn its place; anything that is a setting lives in Settings.

- **The title**: the call's topic, the Calls button when another call needs the user, and the gear.
- **The conversation**: one list, oldest first, like a chat. Each question is a bubble on the right; each answer is plain text under it. The answer being said lights the word being said, the words before it in full ink. A tap on any word of any answer plays from there; selecting text does not. The list keeps the word being said in view until the user scrolls away; then a small round arrow brings it back. Long questions fold at six lines with Show all.
- **The player**: one round play button, the position and the time (the time left while playing, else the length). It acts on the answer that plays, else the newest. Space plays and pauses; the left and right arrows move a sentence.
- **The field**: "Message", with the mic inside it. Once words are typed, Send takes the mic's place. While recording, the field gives way to the level and the time, with Cancel and Done. One quiet line above it says the one thing worth saying now: what happened to a send, why a recording gave no words, why the voice or the open microphone is not on, that the call ended.

What is typed and not sent is kept per call in the tab's session storage (`talk.draft.<call>`). A typed command ("slower", "repeat that") is never sent to Claude. The field takes the focus on load on a screen wider than 700 px.

## Settings

The gear opens one sheet over the panel, grouped like a phone's settings:

- **Voice**: the voice (with Azure, each with a sample), the speed, the language.
- **Listening**: play new answers by themselves, the stage follows the voice, keep the microphone open (Live), and in Live how speech interrupts the voice and the pause before sending.
- **Display**: Light, Dark or Auto; the panel on the left or the right; text size Desk or TV (`?screen=tv` in the address does the same).
- **Keyboard shortcuts** (also `?`), **Stage demo**, and **End call** at the bottom.

The panel is as wide as it is dragged. Keys: Space, ← →, Alt+S next speed, Alt+M the field, Alt+P the player, Alt+V follow the voice again, Alt+T Talk or Done, ? the keys, Esc closes a sheet. Two skip links, the first stops of the page, go to the field and the player; a third reads the board in front as text.

## Live mode

- Nothing listens between turns, so nothing is said by accident, unless the user turns on **Keep the microphone open** in Settings.
- Then the microphone stays open, and what they say is sent after a short pause (0.8, 1.2 or 2 s).
- Speaking over an answer interrupts it by talking. "mm-hm", "yeah" and coughs let it go on.
- **Interrupt the voice** in Settings can limit interruptions to words that start with a cue such as "wait", "hold on", "sorry" or "listen"; **Send after a pause of** sets the pause.
- The mic button mutes and unmutes. A microphone that delivers only silence for ten seconds shows **No sound heard**.
- "slower", "faster" and "say that again slower" are spoken commands for the voice speed, acted on by the page.

## Speech engines

- Azure is used when its key is found: `AZURE_SPEECH_KEY`, else the output of `TALK_AZURE_KEY_COMMAND`.
- The region comes from `AZURE_SPEECH_REGION` or `TALK_AZURE_REGION`.
- Azure takes a second or two per answer and is billed per character.
- Without a key, the local VoiceStudio app speaks: free and private, but an answer takes about as long to make as to play.
- `TALK_SPEECH=azure` or `TALK_SPEECH=voicestudio` picks one by hand.

## The stage beside the panel

- An answer with no board of its own is read on the stage in large type when the stage has no board in front; with a board in front the board stays and the sentence being said goes on the strip under it. The panel holds the full text either way.
- When the voice reaches a board's tag, the board takes the stage and the sentence being said stays under it on one line.
- At rest an answer with a board shows the board, and one with none leaves the board that was in front.
- A board the reader picked by hand stays in front until **Back to the voice**, which returns to the board the voice showed last (Key points, which no cue fronts, never keeps the stage). While it stays, the strip under it names its answer ("Answer 2:") and dims when that answer did not put the board up.
- The stage's own words (its toolbar, board counter, Copy, step control, Key points) follow the page's language, English or Greek.
- A tap on a part of a board offers Ask about this and Play from here.
