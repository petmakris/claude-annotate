# A talk answer is a scene the voice reveals, not text beside a board

## What was wrong

One long call taught the user a topic they did not know (a report printing the wrong product name), in 25 answers.

- Answers were 100 to 690 words of prose in the panel, with a few boards attached. Long stretches had no
  picture at all.
- Thirteen of the 52 boards were whole HTML pages put up by hand, then talked about in side text. The voice could
  not step a page, so it went up at once.
- The user understood when one concrete example was built up one step at a time and checked with them.

The user marked twenty working prototypes of one answer. Good: one line at a time, words
beside the thing, tappable terms, one value followed from data to PDF, zooming in from the whole, code with real
values, side by side, picture then data, a page that grows, a "where am I" strip, stopping to ask, guess first,
say it back, tap to ask, deeper on request, a sandbox. Bad: chapters, a recap with buttons, options as cards.
Unmarked: today's full text beside one board. The user added: "bringing up a very big page all at once in the
stage is lazy work".

## What changes

| Piece | Change | Where |
|---|---|---|
| B. Scenes | A new board kind, `scene`: HTML Claude writes, made of parts marked `data-part`. The voice reveals and lights parts like rows of a table. With no verbs, each part arrives with the sentence that names it. A scene with no parts is refused. | `talk.py` Board, `stage/scene.py` parts model, `stage.js` render, `stage.css` |
| A. Words on the stage | The sentence being said shows on the stage: as a bubble under the part being said, else as a line at the stage's foot. In the panel, an answer that has boards is folded to one line with a Show text button. | `call.js`, `stage.js`, `call.css`, `stage.css` |
| Author rules | The skill tells Claude to build an explanation as a scene, one short sentence per step, starting empty; and never to put up a finished page to talk beside. `reply` prints a `board:` line for a sentence over 30 words and an answer over 220 words. A page tag stays allowed: it shows a thing that already exists (a README, a running app), and the skill keeps explanations off pages. | `talk/SKILL.md`, `talk.py` |

## How a scene is written

```
[[show scene | Ben's product name]]
<div class="cols">
  <section class="box" data-part="data" data-name="the data the server sends">…
    <div data-part="old">"K&EProductType" … "Investment Grade Bonds"</div></section>
  <section class="box" data-part="rule" data-name="the template rule">…</section>
  <section class="box" data-part="pdf" data-name="what the PDF prints">…</section>
</div>
[[/show]]
Follow one value. [[+ data]] The server sends the fund's stickers. [[point: part old]] One is the old K&E sticker. …
```

- A part is any element with `data-part="<id>"`; its key is `part:<id>`. `data-name` gives the words a sentence
  names it by; without it, its first heading or its first eight words.
- A part inside another brings its parent with it. A parent brings the parts inside it, except those a verb or
  point in the answer reveals on their own.
- Targets: `[[+ old]]`, `[[+ part old]]`, `[[point: part old]]`, `[[point Ben's product name: part old]]`.
- A script, an `on…` handler or a `javascript:` link refuses the scene in talk; the stage also sanitizes the HTML
  (DOMPurify): no scripts, forms, frames or styles; inline `style` stays.
- Building blocks, styled in talk's own tokens: `.cols`, `.box`, `.cap`, `.big`, `.mono`, `.good`, `.bad`,
  `.warn`, `.mark`, plus tables, `pre` and `code`.

## Order

1. Parts model and its compiler rules (`scene.py`), with tests.
2. The `scene` board kind in talk: parsing, cues, points, refusal, auto reveal (`talk.py`), with tests.
3. The stage renders and steps a scene (`stage.js`, `stage.css`), tested under node, checked once in Chromium.
4. Captions on the stage and the folded answer (`call.js`, `stage.js`), tested under node, checked once in Chromium.
5. Author rules and their `board:` lines (`SKILL.md`, `talk.py`), the demo's scene answer, `CLAUDE.md`.

## Out of scope

- C. Stopping to ask (check-in, guess first, say it back, deeper on request): its own design next.
- D. Asking from the stage (tap a part, tap a term): its own design after C.
- The sandbox: a scene with its own script. Scenes run no scripts until a page in its own frame is designed.
- Removing the old board kinds. Tables, code, changes, sequences and flowchart maps stay.
