# An answer stops to ask, the stage takes questions, and a scene can run a script

This follows `2026-10-13-talk-answers-are-scenes-design.md`, which left three pieces out. The user marked each one
Good among the twenty prototypes ("It stops and asks if it is clear", "Guess first", "You say it back", "Short first,
deeper on request", "Tap any part to ask about it", "Hard words you can tap", "Change the case, watch the row"),
and said of the last: "if we can we must go for it".

## What changes

| Piece | Change | Where |
|---|---|---|
| C. Stops | Four tags stop the voice and wait for the reader: `[[check]]`, `[[guess: …]]`, `[[say back: …]]`, `[[deeper]]`. Its question is said, then the answer pauses on a card with buttons. | `talk.py` (cues), `call.js` (pausing, picks), `stage.js` (the card) |
| D. Asking from the stage | A tap on a scene part opens a popup: Ask about this (writes `About "<part>": ` into the text field) and Play from here. A word marked `<dfn title="meaning">` shows its meaning when tapped, in the scene and in the caption. | `stage.js`, `stage.css`, `call.js` |
| The sandbox | A scene with a `<script>` or an `on…` handler runs in a sealed frame: no network, no reach into the stage. Its parts still come in with the voice. | `model.py`, `stage.js` |

## C. Stops

| Tag | Said | Buttons | A press |
|---|---|---|---|
| `[[check]]` or `[[check: Is the matching clear?]]` | the question ("Clear so far?" when none is given) | Go on · Again, slower · Another example | Go on plays on. Again, slower plays the stretch since the last stop again at 0.8× and stops here again. Another example sends "Another example, please." as a turn. |
| `[[guess: What does it print? \| Fixed Income \| *Investment Grade Bonds \| Nothing]]` | the question | one per choice; `*` marks the right one | The pick is marked right or wrong, the right one is shown, and the answer plays on. The pick goes to Claude with the next turn (`picks`). |
| `[[say back: What does hard-coded mean here?]]` | the question | none: the text field (or Talk) takes the answer | The next turn carries `answering: <question>`, so Claude checks it. Text after this tag is reported: Claude's reply does the checking. |
| `[[deeper]]` | nothing: the short version is said before it | Go deeper · That's enough | Go deeper plays the next layer. That's enough ends the answer. |

- A stop is a cue `{at, kind: "stop", stop: {type, question, choices, right}}`, at the end of its spoken question.
- Play at a stop counts as the first button. A stop passed once in a play is not stopped at again until the reader
  plays from before it.
- A staged answer (one with a board) shows the card on the stage. Any other answer shows it in the panel, under the
  answer.

## D. Asking from the stage

- A part's popup names the part and offers **Ask about this** and **Play from here** (the frame that brought the part in).
- Ask about this pauses the voice and writes `About "<part name>": ` into the text field, focused, for the reader to
  finish. Nothing is sent until they press Send.
- `<dfn title="what it means">term</dfn>` in a scene: the term is underlined with dots. A tap shows the meaning
  without stopping the voice. The same term in the caption is tappable too.

## The sandbox

- `[[show scene | T]]` with a `<script>` or handlers is kept whole; `javascript:` links stay refused.
- The stage puts it in `<iframe sandbox="allow-scripts">` (no same origin), with a Content-Security-Policy of
  `default-src 'none'`: inline scripts and styles, the stage's own stylesheet and images from `data:` only.
- A small script the stage adds first keys each `data-part` and applies the frames the stage posts (shown, lit,
  being said), so the voice still reveals the parts. The caption is a bar for a sandboxed scene.
- Out of scope: popups, terms and taps inside a sandboxed scene (its own script owns the clicks).

## Order

1. C in talk (`[[check]]`, `[[guess]]`, `[[say back]]`, `[[deeper]]` as stop cues; `answering` and `picks` on turns), tested.
2. C on the call page and the stage, tested under node, checked once in Chromium.
3. D on the stage and the call page, tested under node, checked once in Chromium.
4. The sandbox: the parser, the sealed frame, its frames, tested, checked once in Chromium.
5. `talk/SKILL.md`, the stage `SKILL.md`, `CLAUDE.md`, the demo.
