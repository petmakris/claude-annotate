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

## The floor

- One talk server on the machine holds the calls of every session, each at its own link.
- Pressing Talk, sending text or playing an answer in a call gives it the floor: every other call's page pauses its voice at once.
- An answer that arrives in another call is shown but not played.
- It shows as new on the strip of other calls at the top of every call page, and on the list of calls at the root of the talk address.
- Nothing changes for this session: it answers its own call by its call id.

## The panel and the gear

- The panel holds the whole conversation as a chat.
- Under it sit the player (pause, back 10 seconds, a seek bar), the text field and the mic.
- Space pauses and plays. The left and right arrows move to the start of the previous or next sentence, wherever nothing is being typed.
- The panel sits on the left or the right, is as wide as it is dragged, and collapses to a rail that keeps the mic and the player.
- The gear holds speed, language, light or dark, and whether the stage follows the voice.
- With Azure the gear also picks the voice, with a short sample of each. The choice is kept in that browser.
- **Screen: TV** enlarges the panel, its words and the stage, for reading across a room.
- A board the reader picks on the stage stays in front whatever they play, until they press **Follow the voice** or the next answer starts.
- A new answer that arrives while the call's tab is hidden waits, and plays when the tab is seen again.

## Live mode

- Nothing listens between turns, so nothing is said by accident, unless the user picks **Live** under Talking in the gear.
- Then the microphone stays open, and what they say is sent after a short pause (0.8, 1.2 or 2 s).
- Speaking over an answer interrupts it by talking. "mm-hm", "yeah" and coughs let it go on.
- The gear can also limit interruptions to words that start with a cue such as "wait", "hold on", "sorry" or "listen".

## Speech engines

- Azure is used when its key is found: `AZURE_SPEECH_KEY`, else the output of `TALK_AZURE_KEY_COMMAND`.
- The region comes from `AZURE_SPEECH_REGION` or `TALK_AZURE_REGION`.
- Azure takes a second or two per answer and is billed per character.
- Without a key, the local VoiceStudio app speaks: free and private, but an answer takes about as long to make as to play.
- `TALK_SPEECH=azure` or `TALK_SPEECH=voicestudio` picks one by hand.

## The stage beside the panel

- Every answer shows on the stage in large type: each sentence appears as it is said, and the word being said is lit.
- When the voice reaches a board's tag, the board takes the stage and the sentence being said stays under it on one line.
- At rest an answer with a board shows the board.
- A board the reader picked by hand stays in front until **Follow the voice**.
- A tap on a part of a board offers Ask about this and Play from here.
