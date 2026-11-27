# Shot list

Every clip in the README is an animated WebP in `docs/img/`, recorded by a
script in `tools/promo/clips/` from made-up projects, on its own webcompanion
daemon under a scratch HOME. This file is the spec for each one: what it shows,
how it is staged, what is scripted and what is real, and the command that
records it again. When a UI change touches a clip's page, run that clip's
command again.

## Rules for every clip

- Animated WebP, 800 px wide (the hero 880), 10 to 12 fps steps. Size caps:
  P0 600 KB, P1 450 KB, P2 300 KB; all of `docs/img/` stays under 6 MB.
  Every binary in git history is permanent, so re-records land in one commit.
- Record at device scale 2 and scale down. Light theme.
- Made-up data only: invented projects (acme-billing, shop-app), people and
  ids. Never a real client, person, ticket key, host, session path or token.
- The privacy gate runs before anything is committed:
  `uv run tools/promo/scan.py <clip script> <fixtures> docs/img/<id>.webp`
  (word list, OCR of every frame, metadata).
- Look at the clips together: `uv run tools/promo/sheet.py` builds a contact
  sheet from the final files, captioned with each clip's hook below.
- The kit and its notes are in `tools/promo/README.md`.

## ca-01: comment on one part, and only that part rewrites (hero) (file: hero.webp)

status: recorded
priority: P0
file: docs/img/hero.webp (880 px, for the hero slot that hero.webp holds today)
hook: Comment on one part of Claude's answer and only that part rewrites, while the rest of the page holds still.
duration: about 8 s

### Beats

1. A four-part plan for acme-billing. "The backfill" says 2 million rows.
2. The reader selects "2 million rows", presses `c` and types: 40M rows, not 2M - run this as an online job.
3. Add to round, then Submit round (1).
4. "The backfill" greys with `updating`, the dock reads `Applying round…`, and the `Claude is working` pill shows.
5. "The backfill" is replaced in place. The bar reads `1 part changed — 1 you asked for`, and the part gets the chips `you asked` and `what changed`.

### Staging

Own webcompanion daemon on a scratch HOME (port 19120), the invented acme-billing repo, fixtures in `tools/promo/fixtures/ca-01/`. Viewport 1040x760 at scale 2, scrolled so the page header is out of frame. Near-lossless encoding.

Differences from the plan, as the page works today: the comment opens from selected words and `c`, and there is no version chip.

### Scripted and real

Scripted: the Claude side. The clip script runs the commands a session runs (watch, progress, push with a rewrite written beforehand, progress --done, ack). The waiting times are shorter than a real session's.
Real: everything the page shows and does.

### Re-record

    uv run tools/promo/clips/ca-01-hero.py

## ca-02: pick an option, change your mind, submit the round

status: recorded
priority: P0
file: docs/img/ca-02.webp (800 px)
hook: A fork in the plan is asked as cards with a suggested answer, and your pick travels with the round.
duration: about 11 s

### Beats

1. A decision card, "Where should the 40M-row backfill run?", with Claude's suggestion and two other ways. "The backfill" below waits on it.
2. See other ways (2), then Pick this one instead on "Inline in the release pipeline".
3. The card shows `Your pick:` and `Not sent yet. It goes to Claude when you press Submit round.`
4. Change my mind, then Go with Claude's suggestion.
5. Submit round (1).
6. The card reads `Answered`, and "The backfill" is rewritten. The bar reads `2 parts changed — 1 you asked for, 1 by the coherence sweep`.

### Staging

Own daemon (port 19120), acme-billing, fixtures in `tools/promo/fixtures/ca-02/`. Viewport 960x820 at scale 2. Near-lossless encoding.

Differences from the plan: the "short note" beat is left out. On today's page a comment on a decision replaces the pick (the round then holds only the note and the question stays open), so a pick and a note cannot be sent together from the card. There is no version chip.

### Scripted and real

Scripted: the Claude side of the round, including the rewritten parts. The waiting times are shorter than a real session's.
Real: everything the page shows and does, including the round it sends (`Choose a: Online job after the release`).

### Re-record

    uv run tools/promo/clips/ca-02-decisions.py

### README note

Replaces comment-flow.webp and block-choice.png. The README paragraph on choice cards needs to describe decisions.

## ca-03: every block kind, one page

status: recorded
priority: P1
file: docs/img/ca-03.webp (800 px), and the still docs/img/block-sequence.png shot again
hook: Answers are not just prose: facts, explain, compare, map, sequence, flowchart, decisions, jobs and tables.
duration: about 12.5 s

### Beats

1. Facts strip and an explain part; the reader steps to the second note.
2. A before and after compare, and a map; Follow the request, then two steps.
3. A sequence diagram.
4. A flowchart.
5. A decision card.
6. A jobs list with done, running, todo and blocked.
7. A table; the reader hovers two rows and opens a comment on one (chip `ROW 2`).

Sequence and flowchart parts are commented whole from their heading, so no caption may say that an arrow or a node takes a comment.

### Staging

Restaged: `skills/annotate/docs/gallery.html` (the plan's source) is a static design page that no longer matches the page and cites work code. The clip pushes a made-up acme-billing page (`tools/promo/fixtures/ca-03/v1.blocks.json`) to its own daemon (port 19120). Viewport 960x640 at scale 2. The cuts between kinds are instant scrolls. Near-lossless encoding.

The still block-sequence.png is the same renderer's output for `fixtures/ca-03/sequence-still.blocks.json`. The old still showed a version chip, a "Local server" actor and "one event per comment".

### Scripted and real

Scripted: nothing but the one push of the page.
Real: every part as the page draws it, and every click.

### Re-record

    uv run tools/promo/clips/ca-03-blocks.py
    uv run tools/promo/clips/ca-03-sequence-still.py

## ca-04: a mockup whose toggles really toggle

status: recorded
priority: P2
file: docs/img/ca-04.webp (800 px)
hook: The toggles work inside the page, and a comment can land on a single settings row.
duration: about 10.5 s

### Beats

1. A "Notification preferences" card inside the page.
2. The reader turns Email digest off, turns Push on, and picks Hourly.
3. A click on the label "Push on new order" opens a comment with the chip `push`: No pushes at night, please.
4. Add to round, Submit round (1).
5. The mockup is rewritten: the Push row gains "Silent from 22:00 to 07:00". The bar reads `1 part changed — 1 you asked for`.

The rewrite loads the mockup afresh, so the toggles are back at their starting positions. The round carries the comment and its row, not the toggle positions.

### Staging

Own daemon (port 19120), fixtures in `tools/promo/fixtures/ca-04/`. Only the row labels carry `data-annotate-id`, as `references/block-kinds/mockup.md` asks: in the shared fixture the whole row is tagged, so flipping its toggle would also open a comment. Viewport 960x600 at scale 2. Near-lossless encoding.

### Scripted and real

Scripted: the Claude side of the round. The waiting times are shorter than a real session's.
Real: the toggles inside the sandboxed iframe, the region comment, and the round (`step_id: push`, checked by the script).

### Re-record

    uv run tools/promo/clips/ca-04-mockup.py

### README note

Replaces block-mockup.png.

## ca-05: Talk to the page, the word and the picture arrive together

- **File:** `docs/img/ca-05.webp` (800 px wide, about 11 s, P0)
- **Hook:** the answer is read aloud, the word being said lights up, and the board lights the step, the side or the lines exactly when they are spoken.
- **Re-record:** `uv run tools/promo/clips/ca-05-talk.py` (its own webcompanion daemon on port 19140 under a scratch HOME, talk server on 19150; 1 to 2 minutes). `--keep-render` re-encodes the last render only.

### Beats, as recorded

1. 0-3 s: a sequence board, "One timed-out charge"; each sentence lights its step (sends the cart, wraps the charge in a retry, charges once, times out, waits and tries again, charges again with the same key, shows the order as paid). The caption bar under the stage shows the sentence with the word being said lit. A pill says the call reads it aloud and the loop is silent.
2. 3-6 s: the next board, "Before and after the retry": main on the left, the branch on the right, rows lined up (`~ = +`), "No step here" where main has no retry, then the green outcome, "One timeout no longer loses the order".
3. 6-9 s: a code board of `api/retry.py` lights lines 8-10, then 11-12, then 13-16.
4. 9-11 s: the Key points board, fronted on the stage, with the three key points of the answer.

### Staging

- `tools/talk_render/render.py` plays the answer on a real call page: the repo's own talk server with its silent stand-in voice (`fake_speech.py`), no microphone, no Azure, never port 8766. The clip imports it and adds three things in its own script: a shot at the first word and a middle word of each sentence (so the lit word moves), the Key points board fronted after the answer ends, and device scale 2 for crisp text.
- The answer is `tools/promo/fixtures/ca-05/answer.txt`, invented for the invented shop-app (`tools/promo/fixtures/shop-app`, branch `checkout-retry`). talk accepted it with no `board:` line.
- Each shot is cropped to the stage and its caption bar (the call panel beside it is too small to read at 800 px). Delays follow the voice's own timings, squeezed to about 10 s.

### Scripted versus real

- Scripted: the answer text (what a Claude session would say), and the question typed on the call.
- Real: the call page, the stage, every board, the step and line lighting, the caption with the lit word and the Key points board are drawn by the repo's own code from that answer. Only the audio is silent; an animated WebP has no sound, and the pill says so.

## ca-06: Stage, one page of boards that fills as you work

- **File:** `docs/img/ca-06.webp` (800 px wide, about 9.5 s, P0)
- **Hook:** each `stage show` adds a board to the same page in seconds; save a file and its board reloads, with a dot that says it changed.
- **Re-record:** `uv run tools/promo/clips/ca-06-stage.py` (its own webcompanion daemon on port 19141 under a scratch HOME, the page on 19152).

### Beats, as recorded

1. 0-1.5 s: `stage link` prints the stage's address; the stage opens empty ("The stage is empty").
2. 1.5-3 s: `stage show login "code:web/login.ts:1-8 highlight 2-6"`: a code board with lines 2-6 lit.
3. 3-4.5 s: `stage show deck slides/deck.html`: the deck file as a board, "Board 2 of 2".
4. 4.5-6 s: `stage show ports table:-` and `stage show checkout sequence:-`: a table, then the lanes of a sequence, "Board 4 of 4".
5. 6-7 s: `sed -i s/Monday/Thursday/ slides/deck.html` saves the deck while the sequence is in front; a dot appears beside "Board 4 of 4".
6. 7-9.5 s: the cursor presses ‹ twice; the deck is back in front, reloaded: "Ships to all stores on Thursday".

The catalog's five boards became four (code, deck, table, sequence) to keep the loop under 10 s.

### Staging

- An invented shop-app repo (`tools/promo/fixtures/shop-app`) with the deck, table and sequence of `tools/promo/fixtures/ca-06/` copied in.
- A small page on its own port holds the real stage page in a frame and an xterm.js terminal under it.
- `stage` on the PATH is a two-line wrapper that runs the skill's own `skills/stage/stage.py`, so the typed line is the command that ran.

### Scripted versus real

- Scripted: the typing of each command line (typed into the terminal at a steady pace), and the cursor's two clicks.
- Real: each command runs in a pty when its line is typed, and the terminal shows what it printed (the stage's address), with one swap from `fixtures/ca-06/rekey.txt`: the loopback number is written as `localhost` (port and session id stay as printed). The stage page, its boards, the reload after the save and the dot are the stage's own behaviour.

## ca-07: Spotlight: a product tour with zero tooling

- **id:** ca-07 · **file:** `docs/img/ca-07.webp` · **priority:** P0 · **status:** recorded
- **Hook:** the screen with everything dimmed except the part in focus, a claim beside it, walked part by part.
- **Duration:** about 8.4 s, 800x500, 12 fps steps, near-lossless 40.

#### Beats

1. 0 to 1.2 s: the opening part, the whole screen undimmed, two fact cards (1,284 orders today, 37 payments failed).
2. 1.2 to 3.4 s: the cursor clicks Next; the Failed payments card is ringed, everything else dims, a dashed line runs to the heading.
3. 3.4 to 4.8 s: Right arrow; the ring and line move to Retry failed payments, the progress bar grows.
4. 4.8 to 6.4 s: Right arrow; the Status column is ringed, the progress bar is full.
5. 6.4 to 8.4 s: the same page in a 560 px window: it stacks, the screen on top, the text under it, the line gone.

#### Staging

- `fixtures/ca-07/draw_screen.py` draws an invented shop-app Orders screen with Pillow (1440x900 at 2x). The shop, the customers, the order numbers and the amounts are made up.
- `fixtures/ca-07/spotlight.json` is a normal spotlight spec: one screen cropped to the page area (the spike found the full 1440x900 screen too small), four parts, boxes measured in the image's 2x pixels.
- The page is built by the real `skills/spotlight/build.py`, served by `python -m http.server` on its own port, and recorded at 1040x650, device scale 2. The narrow beat sets the window to 560 px; those frames are centred on a grey backdrop so every frame keeps the same size.

#### Re-record

    uv run tools/promo/clips/ca-07-spotlight.py --port 19162
    uv run tools/promo/scan.py tools/promo/clips/ca-07-spotlight.py tools/promo/fixtures/ca-07 docs/img/ca-07.webp

#### Real versus scripted

- Real: the spotlight page, its build, the dimming, rings, dashed line, progress bar, Next button, arrow keys and the stacked narrow layout.
- Invented: the screen being explained is a drawing of a made-up admin page, and the page says so under the screen ("An invented shop-app admin screen, drawn for this demo"). The cursor is the recorder's drawn cursor.

## ca-08: Canvas: 20 screens at once, then only what changed

- **id:** ca-08 · **file:** `docs/img/ca-08.webp` · **priority:** P0 · **status:** recorded, downgraded (no before/now beat)
- **Hook:** every screen of a shop, desktop and phone, on one canvas; Fit all shows all 20, Changed only keeps the three boards that changed.
- **Duration:** about 9.6 s, 800x500, 12 fps steps, near-lossless 20.

#### Beats

1. 0 to 1.2 s: the first group (Sign in), desktop and phone shots side by side.
2. 1.2 to 2.4 s: the wheel pans down to Browse.
3. 2.4 to 4 s: the pointer moves over the Home phone shot; Ctrl + wheel zooms in round it to 204 %.
4. 4 to 6 s: Fit all: all ten boards, 20 shots, in four groups; Cart, Payment and Order placed are outlined (changed, changed, new).
5. 6 to 9.6 s: Changed only (its button shows 3): only those three boards stay, laid out and fitted.

The catalog's before/now beat is dropped: the viewer does not show a shot's `previous` image today (the foundation job's spike), though `skills/canvas/SKILL.md` says it does.

#### Staging

- `fixtures/ca-08/draw_screens.py` draws ten screens of an invented web shop, Northwind Goods, with Pillow: each a 1600x1000 desktop shot and a 390x844 phone shot at 2x. Products, prices, the address and the card number (a public test number) are made up.
- `fixtures/ca-08/canvas.json` is a normal canvas manifest: four groups, ten boards, `changes.since`, two boards `changed` and one `new`. No `session` and no `comments`, so the build never talks to a webcompanion daemon.
- Built by the real `tools/canvas.py check` and `build` into the scratch folder (never `~/Outbox`), with `CLAUDE_ANNOTATE_UPDATED=1` so the build does not first update the checkout. Served by `python -m http.server` on its own port, recorded at 1200x750, device scale 2.

#### Re-record

    uv run tools/promo/clips/ca-08-canvas.py --port 19163
    uv run tools/promo/scan.py tools/promo/clips/ca-08-canvas.py tools/promo/fixtures/ca-08 docs/img/ca-08.webp

#### Real versus scripted

- Real: the canvas page, its build and thumbnails, wheel pan, Ctrl + wheel zoom, Fit all, the change outlines and Changed only.
- Invented: the screens are drawings of a made-up shop, and the change marks are set in the manifest (the project compares; the canvas only shows). The cursor is the recorder's drawn cursor.

## ca-09: Deck, click a bullet, one line changes in the file

- **id:** ca-09
- **file:** `docs/img/ca-09.webp` (800x500, 11.1 s, 46 frames, about 265 KB, lossless)
- **priority:** P1
- **hook:** Click one bullet, say "shorter", and the slide and the file both change on that one line.

### Beats (as recorded)

1. 0-1.5 s: the deck page in Slide view on slide 4 of an invented six-slide deck (checkout retry for shop-app).
2. 1.5-4 s: the cursor clicks the first, long bullet. The comment popup opens with the slide, the element path and the line. "shorter" is typed.
3. 4-5 s: Send to Claude. The banner says "Claude is editing the deck…" and the bullet is marked as being worked on.
4. 5-7 s: the bullet is rewritten in the file on disk. The page repaints the slide with the short bullet and a green frame.
5. 7-11 s: a terminal inset types `git diff -U0` and shows exactly one line removed and one added.

### Staging

- `tools/promo/fixtures/ca-09/checkout-retry.html` is `skills/deck/demo/sample-deck.html` with every text rewritten (same framework, six slides).
- The clip copies it into a scratch git repo (one commit by Dana Example), starts its own webcompanion daemon (scratch HOME, port 19142), and runs the real `claude-annotate deck.push --deck ... --watch`.
- The terminal inset is a real `git diff -U0` in that repo, captured in a pty by `termcast.capture` and replayed in xterm.js (served on port 19154). No rekeying was needed: the diff prints only relative paths.
- At the end the watcher is stopped by PID, the session is forgotten and the daemon stopped by PID.

### Re-record

    uv run tools/promo/clips/ca-09-deck.py

### Scripted versus real

- **Scripted:** the edit itself. The clip writes the same one-line change Claude makes when it handles this comment (`skills/deck/references/handling-comments.md`: read the line range, edit those lines). The typed command line in the inset is typed by the replay page.
- **Real:** the deck page, the click-to-line popup, the send, the busy banner, the `--watch` re-push and the repaint, and the `git diff` output.

## ca-10: slides: the audit names the overflow

- **id:** ca-10 · **file:** `docs/img/ca-10.webp` · **priority:** P1 (cap 450 KB)
- **status:** recorded
- **hook:** A slide's last point runs off the bottom; the layout audit names the element and its overshoot; the slide is split and the audit re-measures clean.
- **duration:** about 11 s, 800 px wide, 12 fps.

### Beats

1. 0-1 s: slide 2 of an invented deck ("Why checkout calls fail today") in the deck's scrolling view; its last point stops at the slide's edge.
2. 1-4.5 s: a terminal inset drops in; `python3 audit.py 2026.12.03-retries.html` prints each slide's `overflow`: slide 2 lists `introb`, `LI` and `sub` with `"bottom": 46`. A red dashed box then marks the list's own box from the slide's bottom edge to its bottom edge, labelled with the 46 px the audit printed.
3. 4.5-7 s: the deck now holds the fixed version (slide 2 split in two); the audit runs again and every slide prints `"overflow": []`.
4. 7-11 s: F enters present mode on slide 2; the right arrow steps to slide 3 ("What it costs us") and slide 4 ("Three changes, one release").

### Staging

- `HOME` and `SLIDES_DECKS_DIR` point into the scratch folder; `decks init --use` is never run, so no user config is written. Only the shipped `default` theme is used (`inline.py --theme default`).
- The deck is `tools/promo/fixtures/ca-10/deck-v1.html`, a copy of `skills/slides/references/skeleton.html` with invented text (shop-api, checkout retries). `framework/inline.py` pastes in the framework and the theme.
- `tools/promo/fixtures/ca-10/audit.py` loads the deck in headless Chromium at 1280x720 and evaluates `skills/slides/references/layout-audit.js` exactly as it is in the skill, then prints the `overflow` field of its report, one slide per line (the `gaps` and `collisions` fields are not printed).
- The deck and both audit runs are served by one `http.server` on 127.0.0.1:19164, stopped by its PID when the clip ends.
- The recording is a stage page holding the deck in one iframe and the terminal replay in another; the clip drives the deck's own keys (F, right arrow).

### Re-record

    uv run tools/promo/clips/ca-10-slides.py --port 19164
    uv run tools/promo/scan.py tools/promo/clips/ca-10-slides.py tools/promo/fixtures/ca-10 docs/SHOTLIST.md docs/img/ca-10.webp

### Real versus scripted

- **Real:** both audit runs. They are captured once in a pty (`termcast.capture`) and replayed in xterm.js (dark theme); the output, numbers and exit codes (1, then 0) are as the runs printed them. The 46 px label is read from the first run's output. The deck pages, the scrolling view, present mode and its keys are the skill's real harness.
- **Scripted:** the fix. `deck-v2.html` is a prepared edit that splits slide 2 in two, as the skill's rule says ("never fix one by shrinking type; split the slide"). The command line is typed by the replay at a steady pace. The wait while Chromium starts (about a second) is cut. The red dashed box is drawn by the clip over the stage page, from the list's box the page itself measures; it is not part of the slides skill.

## ca-11: Specimen, a Java object with real values and one explicit null

- **id:** ca-11
- **file:** `docs/img/ca-11.webp` (800x533, 11.3 s, 68 frames, about 370 KB, lossless)
- **priority:** P1
- **hook:** A bare class becomes a tree of real-looking values, the nullable field is plainly `null`, and one click sends a question about it to the session.

### Beats (as recorded)

1. 0-1 s: an invented `Order` as a tree: customer, two order lines, total, payment and discountCode, each value tagged `chosen` or `captured` with its source line.
2. 1-2.5 s: the cursor shows the `captured` tag on `payment`, then the red `null` badge on `discountCode` (`?` means `@Nullable`).
3. 2.5-6 s: a click on that row's ✻ opens the comment box; "why is this null for guests?" is typed and sent with Comment.
4. 6-11 s: a terminal inset titled "Claude session" shows the session's watcher receiving the question, with its anchor `com.acme.shop.Order#discountCode`.

The planned beat "the answer lands on that field's row" was dropped: the specimen page draws no replies on its rows (`specimen.js` renders items only; a reply goes to the field's thread in the session). Showing one would fake the page.

### Staging

- `tools/promo/fixtures/ca-11/src/` is an invented shop in Java (Lombok `@Data`; `discountCode` and `Customer.accountId` are `@Nullable`). The clip copies it into a scratch git repo and runs the real `claude-annotate specimen.extract_types Order`.
- `shop-specimen.json` is the populated instance (a guest order, so `accountId` and `discountCode` are null). `leaves.json` is an invented capture for the one leaf type, `com.acme.payments.PaymentMethod`, so `payment` is tagged `captured`.
- The real `specimen.push` puts it on the clip's own webcompanion daemon (scratch HOME, port 19143). The page is scrolled past its header, which names the scratch folder and the capture.
- The inset replays a real `webcompanion watch --kind specimen --sid order-specimen` run, captured in a pty after the question was sent (served on port 19155). The run is stopped by `timeout` after it printed the event; the replay types the command without `timeout`.
- At the end the session is forgotten and the daemon stopped by PID.

### Re-record

    uv run tools/promo/clips/ca-11-specimen.py

### Scripted versus real

- **Scripted:** the values in `shop-specimen.json` and `leaves.json` (a session writes the first by hand; the second stands in for a project's capture and is labelled invented). The typed command line in the inset.
- **Real:** the shapes read from the Java source, the page, the null badge and tags, the ✻ composer, the sent question, and the watcher's output.

## ca-12: dataflow: hover a field, light its whole route

- **id:** ca-12 · **file:** `docs/img/ca-12.webp` · **priority:** P0 (cap 600 KB)
- **status:** recorded
- **hook:** Hover one field and its route lights across three records while everything else dims.
- **duration:** about 10.5 s, 800 px wide, 12 fps.

### Beats

1. 0-2.5 s: the field view of `Order` → `OrderDto` → `order.json` at rest: a rename (`id` → `orderId`), a fan-out (`customer` → `customerId`, `customerName`) and three amounts summing into `totalCents`.
2. 2.5-5 s: the cursor hovers `totalCents`: `subtotalCents`, `taxCents`, `shippingCents` and `total_cents` light with their arrows, the rest dims.
3. 5-7 s: hover `internalNotes`, a faded field nothing carries forward: only it lights.
4. 7-10.5 s: off the fields, `+` twice zooms in (the minimap's frame shrinks to 277 %), then F fits the drawing again.

### Staging

- The spec is the skill's own public example, `skills/dataflow/fields/example-order.json` (generic names: Order, OrderDto, totalCents). No fixture of its own.
- The clip runs `python -m skills.dataflow.fields.render <spec> --check <out.html>` from the checkout, which writes the standalone page and fails on a bad layout report, then serves the page with `http.server` on 127.0.0.1:19165 (stopped by its PID) and records it at 1100x690, device scale 2.
- No daemon: the field view is one offline HTML file. The class view needs a live session and stays a README line.

### Re-record

    uv run tools/promo/clips/ca-12-dataflow.py --port 19165
    uv run tools/promo/scan.py tools/promo/clips/ca-12-dataflow.py docs/SHOTLIST.md docs/img/ca-12.webp

### Real versus scripted

- **Real:** everything on screen. The highlight, the dimming, the zoom and the fit are the page's own response to real mouse moves and key presses.
- **Scripted:** only the cursor's path, drawn by the kit's cursor overlay because a headless browser draws none.

## ca-13: App map: a you-are-here map of the whole application

- **id:** ca-13 · **file:** `docs/img/ca-13.webp` · **priority:** P1 · **status:** recorded, beats changed (no file counts)
- **Hook:** one drawing of the whole application, with the open file's part lit, its arrows lit and the team that owns each part.
- **Duration:** about 7.8 s, 800x704, 12 fps steps, near-lossless 40.

#### Beats

1. 0 to 1.7 s: the map of an invented 13-module shop: three layers, Checkout drawn with two slices, a team pill in every box.
2. 1.7 to 3.8 s: a file of the Retry slice is open: Retry is lit, Checkout around it is framed, its three arrows turn blue, everything else dims. The header reads `RetryService.java  Checkout › Retry  Module checkout  @acme/checkout`.
3. 3.8 to 4.9 s: another file: Orders is lit, with its arrows to Admin console, Shipping and Notifications.
4. 4.9 to 7.8 s: a click on Orders opens its detail map; Returns is lit, the header reads `Orders › Returns`, a Back button appears.

The planned "file counts per part" beat is dropped: the plugin shows no number of files in any mode (`AppMapLights`, and the skill's design rules).

#### Staging

- `fixtures/ca-13/make_repo.py` builds an invented Gradle repo `shop` (13 modules, Gradle `project(...)` dependencies, a CODEOWNERS file with four invented teams, one commit by Dana Example at a fixed date). `skills/app_map/tests/sample_map.json` is too small for the clip (three boxes), so it is not used.
- `fixtures/ca-13/source.json` is the map's `source.json`: the top map with Checkout's slices, and a detail map for Orders.
- The clip runs the real `claude-annotate app_map.app_map check` and `build` with `APP_MAP_HOME` in the scratch folder; `--check` also runs `tools/vz_check.py` on both drawings (0 faults on 26 November 2026). Two root files (settings.gradle, CODEOWNERS) are deliberately on no part.
- The page holds the built `top.svg` and `orders.svg` with `vz.css` inline and the fonts copied beside it, served by `python -m http.server` on its own port, recorded at 1000x880, device scale 2.

#### Re-record

    uv run tools/promo/clips/ca-13-app-map.py --port 19166 --check
    uv run tools/promo/scan.py tools/promo/clips/ca-13-app-map.py tools/promo/fixtures/ca-13 docs/SHOTLIST.md docs/img/ca-13.webp

#### Real versus scripted

- Real: the repo facts, `check`, `build`, the layout and routing of both drawings, the part ids, the owners and team labels in `map.json`.
- Scripted: the lighting. The app map is shown by the IntelliJ plugin (Cmd+Shift+M), which has no browser page, so the clip's page is a stand-in that paints the plugin's file mode the way `AppMapCanvas.paint` does (the lit part in the accent, a slice's holder framed and its arrows lit, the rest dimmed, pills from `map.json` owners at a fifth of the files or more, each map fitted at most twice its size) and the overlay's header row. Which file is "open" is chosen by the script. A caption in every frame says so: "Browser stand-in for the IntelliJ overlay (Cmd+Shift+M): the map is the real build, the lighting is drawn by the clip". The cursor is the recorder's drawn cursor.

## ca-14: Fleet: every session on every machine, one page

- **id:** ca-14 · **file:** `docs/img/ca-14.webp` · **priority:** P1 · **status:** recorded, beats changed (Tools: summary and one finding)
- **Hook:** every session across two machines, a search by meaning, the members and a backlog with a dependency, the tools each machine has, and the phone layout.
- **Duration:** about 12.2 s, 800x524, 12 fps steps, lossy q70.

#### Beats

1. 0 to 1.1 s: Sessions: 11 rows over `laptop` and `build-box`, four live members on top.
2. 1.1 to 3.3 s: "the checkout retry work" is typed and Search by meaning pressed: the table narrows to 3 matches.
3. 3.3 to 6.2 s: the Fleet tab: four members alive, busy or idle and free; scrolled down, the backlog shows #2 "Add retry to checkout" that waits on #1.
4. 6.2 to 9.0 s: the Tools tab: 20 skills, 6 agents, 2 MCP servers and 4 hooks, a line per machine; the finding "Same name from several providers" opens to `skill commit-helper comes from 2 providers`.
5. 9.0 to 12.2 s: the same page at 390 px: Sessions as a list of cards.

The plan's per-machine Tools table does not exist (Tools has a summary line per machine), so the clip shows that line and one Findings row, as the foundation spike said.

#### Staging

- `fixtures/fleet/world.py` (from the foundation batch) builds the invented two-machine world in the scratch folder: its own FLEET_HOME and synthetic home per machine, a stub `claude`, a fake `ssh`, made-up members, to-dos, sessions, skills, MCP servers and hooks. `laptop` serves the real page from this checkout (`fleet ui`) on the clip's port; the clip logs in with the world's made-up token, records at 1100x720, device scale 2, and stops every PID the world started with `world.py --stop`.
- The phone beat sets the viewport to 390x720; that frame is centred on a ground a shade off the page's own, so every frame keeps one size and the lossy encoder leaves no ghost of the frame before.

#### Re-record

    uv run tools/promo/clips/ca-14-fleet.py --port 19160
    uv run tools/promo/scan.py tools/promo/clips/ca-14-fleet.py docs/SHOTLIST.md docs/img/ca-14.webp

#### Real versus scripted

- Real: the fleet page, its five tabs, the session list across the two machines (the second through the fake ssh), members' states, the backlog order, the Tools scan of each synthetic home and its findings, the 390 px layout.
- Scripted: the answer to Search by meaning comes from the world's stub `claude`, which matches the words against the invented sessions; no model runs. The search text is typed by the recorder. The cursor is the recorder's drawn cursor.

## ca-15: journey: pin comments on screens, send one batch

- **id:** ca-15 · `docs/img/ca-15.webp` · P2 · status: recorded (downgraded: no session inset)
- **hook:** Pin comments on app screenshots, press Send, and one batch waits for the session you attach.
- **beats (as recorded, about 10.5 s, 800x391):**
  - 0-1 s: a journey canvas of the invented Corner Shop checkout: Cart, Delivery, Payment; "No session attached".
  - 1-7 s: Comment mode on; three pins on three boards, each typed and posted ("Show the delivery fee here", "Make the slot a list", "Say the total on Pay"); the Send button counts 1, 2, 3.
  - 7-8 s: Send: the pill turns "Waiting for a session · sent just now" and the status says "Kept 3 comments: they wait for a session".
  - 8-10.5 s: the pill opens its card: "3 comments sent just now wait here", with `/journey shop-checkout-dana` to copy.
- **staging:** an own webcompanion daemon (scratch HOME, port 19144). The screens are an invented HTML page (`tools/promo/fixtures/ca-15/screens.html`, made-up shop, person and address) shot at 960x600. `tools/canvas.py build` makes the canvas with a `journey` session; `skills/journey/journey.py register shop --name checkout-dana` records it, with `JOURNEY_APPS` at `tools/promo/fixtures/ca-15/apps.json`. After the recording `journey.py batches shop-checkout-dana` must return the one batch of 3 comments, or the clip fails. Then `webcompanion forget`. Nothing goes to Lungo; no file under the real journey config is read or written.
- **re-record:** `uv run tools/promo/clips/ca-15-journey.py` (options `--port 19144 --http 19156`)
- **real vs scripted:** everything on the page is real: pins, posts, Send and the waiting card come from the canvas's own code on a real session, and the batch is read back through `journey.py`. Scripted: only the recorder's pointer and the typed words. Dropped (kit ruling): the "attached session receives the batch" inset, because attaching needs a Claude session and the follow-up is a Lungo plan, which would be a faked side effect.

## ca-16: draw: sketch on a tablet, the session answers

- **id:** ca-16 · `docs/img/ca-16.webp` · P2 · status: recorded
- **hook:** Sketch a screen on a tablet, tap Update, and the session answers about your drawing.
- **beats (as recorded, about 10 s, 800x556, tablet viewport 1180x820):**
  - 0-1 s: the empty pad: "Draw with the pen. Update sends the drawing to Claude."
  - 1-7 s: hand-like strokes draw a sign-in wireframe (frame, logo, title, two fields, a button); the pad goes full screen after the first line.
  - 7-8 s: Update; the pad says Sent.
  - 8-10 s: a terminal inset shows the line `draw.py watch` printed for that Update, then a reply typed out, marked "reply scripted".
- **staging:** an own webcompanion daemon (scratch HOME, port 19145); `skills/draw/draw.py claim --session <made-up id>` takes the pad on that daemon only, and `draw.py watch` waits as /draw does. The strokes are cubic curves through set points with a small seeded wobble (seed 16). The Update event is acked and the session forgotten at the end.
- **re-record:** `uv run tools/promo/clips/ca-16-draw.py` (option `--port 19145`)
- **real vs scripted:** real: the pad, its full-screen switch, Update, and the `WEBCOMPANION_EVENT skill=draw ...` line the watch printed (its random sid and event id are swapped for `d1` and `e1`, names only; the raw line is kept in the scratch folder). Scripted: the reply in the inset (no model runs; the inset's title bar says "reply scripted"), the inset window itself (an overlay drawn on the recording, standing for the terminal; the pad never shows replies), and the pointer path.

## ca-17: show-diff, every changed file of a branch in one scroll

- **File:** `docs/img/ca-17.webp`, 800x500, about 12 s, cap 450 KB (P1).
- **Hook:** one command opens every changed file of a branch as a single scrollable diff, and a question on a line is answered under it.

### Beats

1. A terminal runs `show-diff.sh shop-app main checkout-retry` and prints what it opened.
2. VS Code shows the four changed files in one scroll, with the file list in the sidebar. Two scrolls pass `payments.py` and reach `retry.py`.
3. A click beside line 11 of `retry.py` opens a comment box. The question is typed and **Ask Claude** is pressed.
4. Claude's answer appears in the same box.

### Staging

Linux only. VS Code runs under Xvfb with a throwaway profile whose only
extension is this repo's `vscode-plugin/` (its `src`, `themes` and
`package.json`, copied into the scratch extensions folder). It is driven
through its remote debugging port, so only the VS Code window is captured.
The repo is `fixtures/shop-app` (invented, author Dana Example), checked out
on `main`. A webcompanion daemon of the clip's own listens on 19180, VS Code
debugs on 19181 and the terminal replay is served on 19182
(`CA17_DAEMON_PORT`, `CA17_DEBUG_PORT`, `CA17_TERM_PORT` change them). All of
it lives in `/tmp/promo-ca17`, with its own HOME, and is removed at the end.

Needs `code`, `Xvfb`, `webcompanion`, `img2webp` and Playwright's Chromium.

### Re-record

    uv run tools/promo/clips/ca-17-show-diff.py

A port that was just used stays busy for about a minute, and the script then
refuses to start.

### Real and scripted

**Real:** the run of `skills/show-diff/show-diff.sh`, its output and exit code;
the extension's diff, file list and comment box; the question reaching the
daemon (the script checks its anchor and text); the extension picking up the
reply.

**Scripted:**

- Claude's answer is the fixed text in `fixtures/ca-17/answer.md`, posted with
  `webcompanion reply`, the command a Claude session uses. No model runs.
- The question (`fixtures/ca-17/question.txt`) is typed by the recorder.
- The replay types the command line, and types the short form of the script's
  path. The wait while VS Code opens the diff (about 16 s) is cut.
- `show-diff.sh` calls macOS `open` and `code`. On Linux two small wrappers on
  its PATH send both to the throwaway profile.
- The recorder answers VS Code's one-time "allow this extension to open this
  URI" question before the recorded view.
- The drawn cursor, and VS Code settings for the shot: dark theme, inline diff,
  word wrap, no minimap.

The line `window <title unreadable ...>` is what the script really prints
where it cannot read window titles.

### Known limits seen while recording (extension 1.8.3)

The clip shows these as they are; the answer text is written so that the
second one does not show.

- When the reply arrives, the box shows only Claude's message. The question
  leaves it, because the daemon's thread holds only replies.
- A reply is shown as plain text: Markdown marks such as `**` stay visible.

## ca-18: IntelliJ: walkthrough, ask-diff, the diff keys and the app map

- **File:** `docs/img/ca-18.webp`, 800x533, about 20 s, 21 frames, cap 300 KB (P2).
- **Hook:** Claude's answers live in the IntelliJ editor: a walkthrough step and a PR diff line each take a question and show the answer in place, and the plugin's keys diff a file and map it.

### Beats

1. `/walkthrough`: step 1 of five sits under `pay` in `FlowService.java`. ⌥N moves to step 2.
2. ⌥A opens the question box on step 2. The question is typed and OK pressed; "waiting for Claude" shows, then the answer under the step.
3. `/ask-diff 42`: ⌥B opens the file against the base branch. The pointer clicks the ask icon on line 18, the question is typed and Ask pressed, and the answer appears in the popup.
4. ⌥D on `RetryPolicy.java` shows its last commit; pressed again, one change further back.
5. ⌘⇧M shows the app map over the editor, with the Retry part of Checkout lit.

### Staging

macOS or Linux; the committed clip was recorded on Linux. Everything lives in
`/tmp/promo-ca18`, with its own HOME, and is removed at the end:

- the invented shop repo from `fixtures/ca-18/make_repo.py` (author Dana
  Example, remote `acme/shop`, branch `checkout-retry`);
- a clone of this repo at its committed `main`, which the plugin is built from;
- a webcompanion daemon of the clip's own on 19190 (`CA18_DAEMON_PORT`);
- a second IntelliJ IDEA (2026.3) with its own config, system and plugin
  folders, so no IntelliJ a person uses is touched. Its plugins are this
  repo's, `tools/promo/ide-driver` and, on Linux, JetBrains' "macOS Keymap".

`ide-driver` is a test-only plugin. Over HTTP on 127.0.0.1:19191
(`CA18_DRIVER_PORT`) it runs actions by id, posts clicks into the IDE's own
event queue, fills the question boxes and reports the IDE's state.

On Linux the IDE runs on an Xvfb display of its own (`CA18_DISPLAY`, default
`:77`) at scale 2, and a frame is that display cut to the IDE window. Two
things only a window manager would do are done by the script: it parks the
display's pointer on empty toolbar so the IDE has keyboard focus, and it gives
the focus back to the editor after a dialog closes. On macOS each frame is
the IDE window and its popups captured window by window, and the IDE stays a
background app.

Needs IntelliJ IDEA (`CA18_IDE`: the `.app` on macOS, the unpacked folder on
Linux), JDK 25 for the two Gradle builds, `webcompanion` and `img2webp`; on
Linux also `Xvfb`, ImageMagick's `import` and `xdotool`.

### Re-record

    CA18_IDE=<IntelliJ IDEA folder> uv run tools/promo/clips/ca-18-intellij.py

Commit plugin changes first: the plugin is built from a clone of the
committed `main`.

### Real and scripted

**Real:** the plugin, built from this repo; its walkthrough cards, step bar,
ask box and answer; the ask-diff session made by `ask_diff.push`, its gutter
icon, popup and thread; the questions reaching the daemon (the script waits
for each event); the base-branch diff and the Smart Diff walk, which are git's
own; the app map built by `app_map build` from `fixtures/ca-13/source.json`.

**Scripted:**

- Both answers are fixed text in the script, posted the way a Claude session
  posts them, then acknowledged. No model runs.
- `gh` is a stand-in (`fixtures/ca-18/bin/gh`) that answers `pr view` with an
  invented PR #42 of `acme/shop`. Its `pr diff` fails, so `ask_diff` falls back
  to the local `git diff main...checkout-retry`.
- The keys are drawn as badges and run as the actions they are bound to, so no
  key is pressed. Each key is checked against the active keymap before
  recording; on Linux that keymap is "Mac OS X 10.5+", where `plugin.xml`
  binds them.
- The questions grow word by word through the driver, and the clicks and the
  hover are posted by the driver. The pointer is drawn on the frame.
- The walkthrough is dismissed after its scene, as a person would, so the app
  map opens on "This file" and not on the walkthrough's steps.

**Left out:** `/pr-diff` needs a GitHub sign-in in IntelliJ and a real PR, so
it is not in the clip.

### Found while recording

Pressing ⌥D a second time inside the diff tab it opened did nothing: the diff
tab's file is IntelliJ's diff placeholder, not a file on disk. Fixed in
`b94ee0f`: a press inside the plugin's own diff tab means the file that tab
shows.
