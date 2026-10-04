# deck — handling a comment

Read this when a task-notification's first stdout line is
`WEBCOMPANION_EVENT skill=deck …`: a user commented on an element, a slide or
the whole deck. It covers reading the envelope, grounding the wording,
holding the edit to the house style, re-pushing and acking.

## Reading the comment

You wake on a `WEBCOMPANION_EVENT skill=deck sid=<sid> event_id=<id>` banner, followed by
`---payload---`, the event JSON, and `---end---`. The daemon stores exactly
`{"anchor": "...", "text": "...", "images": [...]}`, and `text` is not the comment itself but a
**JSON-encoded envelope** you must `json.loads()` before reading anything out of it. Its
`scope` says what the user commented on:

- `"element"` — one element they clicked. `anchor` is `slide:<n>:<path>:<ord>`.

```json
{"type":"deck_comment","scope":"element","deck":"/abs/path/deck.html","slide":6,
 "path":".pro > p:nth-of-type(1)","ord":0,"component":"pro",
 "line_start":404,"line_end":405,
 "text":"Every proposal has to satisfy…","comment":"Open on the constraint."}
```

- `"slide"` — the whole slide, from the *comment* button on its label. `anchor` is
  `slide:<n>`; `line_start`/`line_end` span the slide's whole `<section>`, and `title` is its
  title. Read the whole range before editing.
- `"deck"` — the whole deck, from *Comment on the deck* in the header. `anchor` is `deck`; there
  is no line range, because the request spans slides — reordering, cutting, a rule to apply to
  every slide. Read the deck's slide list (the model, or the `<section class="slide">` lines)
  before acting, and say which slides you touched.

An envelope with no `scope` comes from an older page and is an element comment.

`deck` is the absolute path to the file you edit — `push.py` stashes it onto the pushed
model specifically so this envelope can carry it back to you; the browser itself never
uses it. `ord` is the element's position among the ones on that slide sharing its path —
decks put several blocks with the same class on one slide, so the path alone is
not an address. You do not need it: `line_start`/`line_end` already point at the
right element. It is in the payload so the address is complete.

**Read the line range, do not grep the text.** `text` is decoded for display; the file holds
`&mdash;`, `&nbsp;` and `&#9492;` beside their literal characters. A grep for the decoded string
misses roughly half of them.

```bash
sed -n '404,405p' /abs/path/deck.html
```

Then edit with the Edit tool, matching the **raw** source you just read.

## Ground the words before you write them

A deck names real systems, screens and features, and its copy is only as good as the
vocabulary it uses. **When a comment asks you to rewrite anything that names a product
concept, find out what the project's own documentation calls it before you propose
wording.** A term you invent will sound official on a slide and be wrong in the room.

Look in this order, cheapest first:

1. **A connected wiki or knowledge search tool**, if this session has one — Confluence,
   a docs MCP server, a knowledge cache. This is usually the fastest route to the term a
   real user would recognise, because it is the same text the product's own users read.
2. **The repository's own docs** — `docs/`, `README`, ADRs, specs, design notes.
3. **The tracker item the slide is about**, if the deck names one. An epic or ticket
   description carries the wording the team actually settled on.

Then prefer the product's own noun over a paraphrase, and say where you got it. If nothing
confirms a term, **keep the existing wording and tell the user it is unconfirmed** — an
honest gap beats a confident invention.

Two limits on this. Grounding is **read-only**: it may open documentation and trackers,
never write to them. And it does not license a rewrite nobody asked for — it changes the
words you choose inside the edit the comment already requested.

When the comment asks for **options rather than a change**, answer in the terminal with the
candidate wordings and leave the file alone until the user picks one.

## Hold every edit to the house style

The style file you loaded at SKILL.md's step 2 is not background reading. It is the standard each edit is
measured against, and the comment that arrived is usually narrower than the rule that applies.

- **Shorter is the default direction.** A deck comes to you because it is too long far more
  often than because it is too thin. When a comment asks you to fix wording, the fix that
  removes a clause beats the fix that swaps one. Do not add a sentence to a slide unless the
  comment asked for something the slide does not already say.
- **Report the size of what you changed.** After an edit, say how the block moved — words
  before, words after. A rewrite that lands 20% longer is a regression even when the wording is
  better, and the user cannot see that from the browser until it overflows.
- **Name the rule you applied.** One clause is enough: "cut the mechanics clause, kept the
  stake". It lets the user correct the rule rather than re-litigating each slide.
- **A crowded slide usually needs a picture rather than tighter prose.** If a comment on a slide
  can only be answered by trimming prose that is already tight, say so and propose the picture
  instead of shaving words. Do not draw it until the user agrees.
- **When the comment and the style file disagree, the comment wins for that edit** — it is the
  user speaking now. Make the edit, then say in one line which rule it departs from, so they can
  decide whether the rule has changed.

**Rules that are not negotiable:**

- **Never reserialise the file.** Change only the substring you mean. A parse-and-rewrite changes
  144 of 705 lines on a real deck and destroys `git diff` as a review surface.
- **Never touch the shared harness.** In a current deck that is everything between
  `<!-- framework:css -->` and `<!-- /framework:css -->`, and between the matching
  `framework:js` markers — a snapshot of the `slides` skill's framework, refreshed only by its
  `inline.py`, never as a side effect of a comment edit. In an older deck without markers, it's
  the first `<style>` block and the `<script>` block. Either way, new CSS goes in a new
  `<style>` block before `</head>` — never inside the harness's own block. Also never hand-edit the `/* pdf-export print
  rules */` `<style>` block if one is present — it's regenerated by `export-pdf.py`.
- **Never write `.pg` or renumber `.num`.** The harness does both at runtime.
- **Do not regenerate the PDF.** A stale `.pdf` beside an edited `.html` is not a defect.

After editing, the `--watch` process from SKILL.md's step 3 re-pushes on its own: it re-copies the file
into the workspace's asset directory and re-pushes `__model__`, which is what makes the browser
reload. Check its background output shows a `pushed HH:MM:SS` line after your edit. If the
watcher is not running (it ends with the session, or it died), push once by hand — it attaches
to the same session by deck file:

```bash
claude-annotate deck.push \
  --deck "$DECK_PATH" --cwd "$PWD" --title "$DECK_NAME"
```

To confirm the deck still parses and the element you touched is still addressable, read the
model back:

```bash
claude-annotate python -c 'from skills._shared import webcompanion_client as wc; d=wc.get_items("<sid>", kind="deck")["__model__"]["body"]; print(len(d["slides"]), "slides")'
```

Report what you changed, the word count before and
after, and the house rule you applied. The page itself now checks every slide it shows and
puts badges on the slide label: **overflow** and **speaker notes** in red; **overlap**,
**off-centre**, **N words** (over the ~90-word house ceiling) and **ticket keys** in amber; a
green ✓ when clean. Hovering a badge lists the offending elements. Those checks run in the
user's browser, so you do not see them — an edit that made a block longer must still be
called out, and if the user reports a badge, fix what it names.

Finally ack the event and end the turn with no terminal output:

```bash
webcompanion ack --sid "<sid>" --event-id "<event_id>"
```
