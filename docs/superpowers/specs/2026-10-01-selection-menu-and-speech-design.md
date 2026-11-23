# One selection menu, read-aloud and dictation for annotate

Date: 2026-10-01. Status: approved design, awaiting the written-spec review.

Mockups the decisions were made on:

- Selection menu: https://claude.ai/artifact/TyKa2pU5586abF9yK3Pduw
- Read-aloud options: https://claude.ai/artifact/NYVQ5LYxM8gXdARwbcta1u

## 1. What this changes, and why

Today feedback on an annotate page is per sentence. Each paragraph, bullet and
code fence carries a hover strip of buttons, and each card title carries a
second strip for the whole section. The reader can react only at those two
grains.

After this change the reader selects any text — two words, a sentence, three
paragraphs — and one menu acts on exactly that. The same menu also speaks the
selection, either as a short spoken **explanation** written by Claude or **as
written**, with each word lit as it is spoken. Dictation in comment boxes moves
from the browser's own recogniser to Azure.

Success looks like this:

- Every reaction the reader can make starts from a selection. There is no other
  control on the page for feedback.
- Pressing Explain on a selection starts speaking within about 10 seconds, and
  the reader can always see which page sentence is being explained.
- Pressing Read as written starts speaking within about 2 seconds.
- Dictation works in Chrome, Safari and Firefox, over the `.mac` domains.
- No key ever reaches the page.

## 2. Decisions

| # | Question | Decision |
|---|----------|----------|
| A | Menu shape | **A2**: icons for Comment, Delete, Compact, a divider, then a split **Explain** button whose arrow holds **Read as written**. |
| B | Per-sentence buttons | **B3**: removed. Nothing happens until the reader selects. A plain click does nothing. |
| — | Section-title buttons | Removed. Selecting the title acts on the whole section (§3.3). |
| 2 | Where the spoken script appears | **2C**: an explainer card under the passage. The script lights word by word, and the page sentence each piece explains lights yellow. |
| 3 | Word highlight | Karaoke: words ahead dimmed, the current word tinted. |
| 4 | Controls | **4B**: pause/resume, back one sentence, progress, speed (0.85×, 1×, 1.2×), and an Explain / Read as written switch. |
| 5 | Engine | **5A, adjusted**: a speech route in the webcompanion daemon. It writes scripts by running Claude headless on the user's own subscription, and hands the browser short-lived Azure tokens. The browser talks to Azure through the Speech SDK. |
| 6 | Dictation | Yes, through Azure, replacing the browser recogniser. |

### Why the engine is shaped this way

- The daemon has no dependencies, and its CI asserts that
  (`webcompanion/pyproject.toml`, `dependencies = []`). Azure's Python SDK is a
  native package, so it cannot go in the daemon.
- Azure's browser SDK is one MIT-licensed file of 378 KB (76 KB gzipped):
  `microsoft-cognitiveservices-speech-sdk@1.51.0/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js`.
  It gives word timings for synthesis and live partial results for recognition.
- Azure's token endpoint turns the key into a token that lasts 10 minutes. The
  daemon can call it with the standard library. The page only ever holds tokens.
- The script is written by `claude -p`, so no new model key or bill is needed.
  Measured on this machine on 2026-10-01: 5.0–8.0 s with Opus. `--bare` started
  in 0.7 s but accepts only an API key, which defeats the point, so it is not
  used.
- The live annotate session was considered and rejected as the writer: a request
  would wait behind whatever turn Claude is in, every explain would grow the
  session's context, and read-aloud would stop when the session ends.

## 3. Behaviour

### 3.1 The selection menu

- Selecting text inside one section opens the menu just above the selection,
  centred on it and kept inside the window.
- Buttons, in order: Comment (`c`), Delete (`d`), Compact (`x`), divider,
  Explain (`r`) with a ▾ that opens **Read as written** (`⇧r`). The icons are the
  ones the strips use today. Each has a tooltip naming its action and key.
- The keys work while the menu is open and the focus is not in a text field.
  None of them is taken today: annotate uses `j`, `k`, `c` (on a focused block),
  `f`, `/` and the round drawer's `s`.
- A selection that crosses two sections opens a one-line menu instead:
  "Select within one section".
- `Esc`, a click elsewhere, or collapsing the selection closes the menu.
- On a touch screen the menu is a bottom sheet, not a floating bar, because the
  system's own Copy / Look Up bar appears where a floating menu would. The sheet
  quotes the selection, then shows Explain aloud and Read as written as two wide
  buttons, then Comment, Delete and Compact.

### 3.2 Marks on any span

- Delete, Compact and Comment become marks on exactly the selected words, local
  until the round is submitted, as today.
- Painting: delete is struck through in red, compact has a purple underline,
  comment has a blue underline and a numbered badge. A comment's text shows as a
  chip under the paragraph the selection ends in, quoting the selection.
- Clicking a mark opens the same menu showing the mark's state ("Marked delete")
  with a Remove button first.
- A new mark that overlaps an existing one replaces it. When the selection
  overlaps a mark, the menu says so ("Replaces a delete") before any button is
  pressed.
- Comment opens the comment box from commit `e8ffc8b` (Cancel, ↩ to add, Esc to
  close), with the selection quoted at the top.

### 3.3 The whole section

- Selecting any part of a section's title — a double-click on it is enough —
  widens the scope to the whole section. The card gets a 2px accent outline and
  a light accent wash, and the menu's first item reads **Whole section**.
- The same buttons then act on the whole section. A section-scope mark shows as
  a badge after the title ("✕ delete section").
- This is how a table, picture or diagram is commented on, since those have no
  prose worth selecting.
- With a block focused by `j`/`k` and nothing selected, `c`, `d`, `x` and `r`
  act on the whole section. `c` keeps its current meaning.
- The help panel and the empty-round hint say that a double-click on a title
  selects the section, because there is no longer a visible button for it.

### 3.4 Read-aloud

- **Explain** opens the explainer card under the paragraph the selection ends
  in. It shows "Writing the explanation…" until the script arrives, then plays.
- **Read as written** opens the same card at once and speaks the selection
  verbatim. No model is involved, and Azure's own normalisation handles numbers
  and dates.
- The card shows the whole script. The current word is tinted, words ahead are
  dimmed to 38%, and the page sentence the current piece explains is lit yellow.
  In Read as written the selection itself is the script, and the page lighting
  follows the current sentence.
- Controls (4B): Pause/Resume, ⟲ back one sentence, a progress bar with
  elapsed/total, speed 0.85× / 1× / 1.2×, and the Explain / Read as written
  switch. Switching mode fetches the other script, and both are cached.
- One card plays at a time. Opening another stops the first. `Space` pauses
  while a card has focus. `Esc` and the card's × stop and close it.
- The voice comes from a new Settings row ("Read-aloud voice"). The default is
  `en-US-AvaMultilingualNeural`.

### 3.5 Dictation

- The 🎤 button stays where it is in every comment box.
- Pressing it streams the microphone to Azure. Recognised text is inserted at
  the caret. Text still being recognised shows in grey and turns solid when
  Azure finalises it.
- Azure is given a phrase list built from the page's glossary terms, so words
  like "EDR", "taxon" and "Compass" are recognised.
- The recognition language follows the browser's language. A Settings row can
  override it.

## 4. Architecture

### 4.1 Components

| Unit | Where | Does | Depends on |
|------|-------|------|------------|
| `selection.js` | annotate `static/` | Selection → menu, scope detection, keyboard, touch sheet. Emits `annotate:select` actions. | `anchors.js`, `subunits.js` round store |
| `anchors.js` | annotate `static/` | Turns a Range into `{block_id, selected_text, prefix, suffix, step_id}` and back. Paints marks and transient highlights with the CSS Custom Highlight API. | none |
| `subunits.js` | annotate `static/` | Keeps the round store, the dock and submit. Loses the unit strips, `UNIT_SELECTOR` and `decorate()`. | `anchors.js` |
| `speech.js` | annotate `static/` | Explainer card, Azure synthesis, word alignment, highlight loop, controls. | `speech-client.js`, vendored SDK |
| `speech-client.js` | annotate `static/` | Token fetch and refresh, script fetch, the in-page cache. | daemon `/api/speech/*` |
| `voice.js` | annotate `static/` | Rewritten: Azure recognition into comment boxes. | `speech-client.js`, vendored SDK |
| `vendor/speech-sdk.min.js` | annotate `static/` | Azure Speech SDK 1.51.0 browser bundle, unmodified, with its licence. | none |
| `speech` module | webcompanion `src/webcompanion/speech.py` | Token minting, script writing through `claude -p`, script cache, config. | stdlib only |

### 4.2 Why marks use the Custom Highlight API

Wrapping selected words in `<span>`s changes the DOM that the markdown renderer
owns. It also changes `textContent`, which prefix/suffix anchoring reads. The
Highlight API paints ranges without touching the DOM. Chrome and Safari
support it. Firefox support is believed current but unverified, so it is
checked first (§9).

Highlights cannot receive clicks, so `anchors.js` hit-tests: on click it takes
`document.caretPositionFromPoint` (falling back to `caretRangeFromPoint`) and
checks it against the stored ranges.

### 4.3 What reaches Claude: the round

The event shape does not change. A span mark is a `scope: "unit"` reaction:

```json
{
  "scope": "unit",
  "kind": "compact",
  "block_id": "section-1",
  "selected_text": "(transcript lines 29–34)",
  "prefix": "The 21 Aug technical session ",
  "suffix": " gave it to the non-premium",
  "step_id": "client-split"
}
```

- `prefix` and `suffix` are always sent for span marks, not only when the text
  repeats. Short spans repeat often.
- `step_id` is the nearest enclosing `data-annotate-id`, as in commit `3d90f8a`.
- A whole-section mark is a `scope: "block"` reaction, as today's header marks
  are.

`references/handling-events.md` gains the partial-span rules:

- A unit `delete` or `compact` may cover part of a sentence. Cut exactly those
  words, then repair the sentence so it is grammatical. Never delete the rest
  of the sentence to avoid the repair.
- A unit `compact` of part of a sentence folds its point into the same
  sentence where it can, before looking at neighbours.
- A `comment` is about exactly the quoted words, not the whole paragraph.

`references/pushing.md` gains one glossary rule: every abbreviation or
project term a listener might not know gets a glossary entry, because
read-aloud and dictation both use the glossary.

### 4.4 The daemon's speech routes

All three require the owner (`gate.is_owner`), like every write route, because
each one spends money or the user's subscription.

| Method | Route | Body | Returns |
|--------|-------|------|---------|
| GET | `/api/speech/status` | none | `{configured: bool, region?, claude: bool, reason?}` |
| POST | `/api/speech/token` | none | `{token, region, expires_in: 540}` |
| POST | `/api/speech/script` | `{selection, context, glossary, page_title}` | `{pieces: [{say, src}], cached: bool}` |

- **Token:** POST to `https://<region>.api.cognitive.microsoft.com/sts/v1.0/issueToken`
  with `Ocp-Apim-Subscription-Key`. Azure tokens last 10 minutes. The daemon
  reports 540 s so the page refreshes a minute early.
- **Script:** run `claude -p --model opus --tools "" --no-session-persistence
  --setting-sources "" --output-format json --json-schema <schema>`. Each
  piece's `src` must be an exact substring of `selection`. The daemon drops any
  piece whose `src` is not, keeping its `say`. Timeout: 45 s.
- **Prompt rules:**
  - Explain, don't recite.
  - Expand abbreviations that the glossary or the context defines.
  - Spell out an abbreviation nothing defines, as letters.
  - Read codes such as `06a/07a` the way a person says them.
  - Drop citations such as "transcript lines 29–34".
  - Keep each piece to one or two sentences.
  - Never invent facts the selection and context do not contain.
- **Cache:** `~/.claude/webcompanion/speech-cache/<sha256>.json`, keyed on the
  prompt version, the selection, the context and the glossary. Entries older
  than 30 days are swept with the existing retention sweep.
- **Config:** `~/.claude/webcompanion/speech.env`, mode 0600, holding
  `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` and optionally `CLAUDE_BIN`. It is
  never served and never logged. `webcompanion doctor` reports each value as
  set or missing, never its contents.
- `docs/contract.md` gains the three routes. This is the first route group that
  is not about items, threads or events; the contract says so and explains why
  speech belongs in the daemon: every skill's page can use it, the key stays in
  one place, and the page's own origin needs no CORS.

### 4.5 Data flow

**Explain**

1. `selection.js` → `speech.js`: selection text, the paragraph(s) around it as
   context, the page glossary and the page title.
2. `speech-client.js` checks its in-page cache, then POSTs `/api/speech/script`.
3. With the pieces, `speech.js` joins the `say` strings into one script, keeping
   each piece's character range.
4. The SDK synthesises the script with `speakTextAsync` and the null audio
   output, collecting `wordBoundary` events (`audioOffset`, `textOffset`,
   `wordLength`). Because the input is plain text, not SSML, `textOffset` points
   into the script string itself. (Parla used SSML and had to match by letters
   instead.)
5. The audio plays from a blob URL in an `<audio>` element. The highlight loop
   reads `audio.currentTime` every animation frame and binary-searches the
   boundaries, so pause, speed (`playbackRate`, pitch preserved) and back-one-
   sentence all stay in sync.
6. The current word's `textOffset` gives the piece, the piece's `src` gives a
   Range in the page, and that Range is painted yellow.

**Read as written:** steps 2–3 are skipped. The script is the selection text,
and its single piece's `src` is the whole selection. Sentence lighting comes
from splitting the selection at sentence ends.

**Dictation:** token → `SpeechRecognizer.fromConfig` with
`SpeechConfig.fromAuthorizationToken` → `recognizing` writes grey text,
`recognized` replaces it with solid text → a synthetic `input` event, so
draft-saving and auto-grow behave as if typed (the same contract as today's
`voice.js`).

## 5. Errors and limits

| Situation | What the reader sees |
|-----------|----------------------|
| No `speech.env`, or the key or region missing | Explain, Read and 🎤 are disabled, with a tooltip: "Read-aloud needs Azure set up — run `webcompanion doctor`". |
| `claude` not found or not logged in | Explain is disabled with that reason. Read as written and dictation still work. |
| Script times out (45 s) or fails | The card says "Couldn't write an explanation" with **Read as written instead**. |
| Token request fails | The card or 🎤 says "Azure didn't answer" with the HTTP status, and Retry. |
| Mic permission denied | 🎤 shows the browser's reason, and nothing is recorded. |
| Selection over 4,000 characters | The menu's voice buttons are disabled with "Select less than about a page". |
| Read-only viewer (not the owner) | No feedback buttons, as today. The voice buttons are shown only to the owner, because they spend the owner's money. |

## 6. What is removed

- `subunits.js`: `UNIT_SELECTOR`, `decorate()`, the unit strip, its composer and
  its chip. The round store, dock, submit and `pinComment` stay.
- `script.js`: the card-header `hover-actions` strip and `onHoverAction`.
  `openAnnotation` stays as the comment box's entry point.
- `style.css`: `.unit-strip`, `.hover-actions` and their mark styles. New mark
  styles move to highlight pseudo-elements (`::highlight(annotate-delete)` and
  so on).
- `a11y.js`: the tab-order handling for strips. The menu is a `role="toolbar"`
  that takes focus when it opens from the keyboard.
- Marks saved in the old shape (keyed by unit text and ordinal) are converted on
  load into span marks. Their text, prefix and suffix are already stored.

## 7. Testing

The rule from the earlier fixes holds: a test must fail on the code before the
change, and that failure must be seen.

- **Browser (Playwright, against the daemon, as `test_browser_review.py`):**
  - selecting words opens the menu
  - each action produces the right reaction in localStorage
  - a cross-section selection is refused
  - title selection gives a block reaction
  - an overlapping mark replaces the old one
  - clicking a mark opens its state
  - old-shape marks convert on load
  - the touch sheet appears at phone width with touch enabled
- **Read-aloud in the browser:** the Azure SDK global is replaced by a test
  double that emits scripted `wordBoundary` events and returns a short silent
  WAV. Tests assert:
  - the current word follows `audio.currentTime`
  - back-one-sentence lands on the sentence start
  - the page Range for each piece is lit
  - errors show the messages in §5
- **Dictation:** the same double emits `recognizing` / `recognized` events.
  Assert the grey-then-solid text and the synthetic `input` event.
- **Daemon (webcompanion's own suite):**
  - the routes refuse non-owners
  - token minting against a local fake STS
  - the script route against a fake `CLAUDE_BIN` that prints fixed JSON,
    including a piece whose `src` is not a substring
  - cache hit and miss
  - `speech.env` never appears in any response or log line
  - `dependencies` stays empty
- **Contract:** `handling-events.md` carries the partial-span rules, and
  `pushing.md` the glossary rule (source-string tests, as the existing round
  contract tests do).
- **One real check, by hand, before merge:** a live Explain and a live
  dictation against Azure with the user's new key.

## 8. Out of scope

- Reading a whole page aloud as one track.
- Voices or styles chosen per play (they are a Settings value).
- Translating while explaining.
- Read-aloud in deck, walkthrough and specimen pages. The daemon routes make it
  possible, and each skill would opt in later.

## 9. Risks

- **Startup time of `claude -p`.** It was 5–8 s in a quick measurement, and it
  could be slower on a cold machine. The card says what it is doing while it
  waits, and the cache makes repeats instant.
- **Daemon contract.** This is the first route group outside items, threads and
  events. It lands in the webcompanion repo with its own tests, before any
  annotate change uses it.
- **Browser SDK in Safari, and the Highlight API in Firefox.** Recognition from
  a token in Safari is expected to work, and Firefox is believed to support the
  Highlight API. Neither has been run yet. Both are the first check in the
  plan, before any code that depends on them.
- **Highlight API hit-testing.** `caretPositionFromPoint` differs slightly
  across browsers. The browser tests run in Chromium, so one manual pass in
  Safari is part of the merge check.
