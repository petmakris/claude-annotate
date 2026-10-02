# Code anchors — UI iteration handoff

**Written:** 2026-08-21 · **Branch:** `feat/code-anchors` (28 commits ahead of `main`, nothing merged)
**For:** a fresh session continuing UI work on the code-anchor pane.

Read this first, then `docs/superpowers/specs/2026-08-20-code-anchors-design.md` if you need the
feature's reasoning. Everything below is measured, not remembered — re-measure before
trusting any number that looks stale.

---

## 1. What the feature is, in one paragraph

An annotate block may carry a `code` list of `{file, line, snippet}` anchors naming source
in the user's own repo. The server resolves each against the workspace's stored root,
reads the real file at render time, and inlines the lines into the `/raw` payload. The page
paints them as a full-bleed light slab in a second column beside the prose. A `SKILL.md`
rule instructs Claude to anchor any block that asserts something about specific code, and
`check_anchors` fails a bad citation before the URL is announced.

**It works end to end.** 1108 Python tests, 20/20 + 9/9 browser e2e, dogfooded live. The remaining
work is UI polish, not correctness.

---

## 2. How to run things

```bash
# full python suite (from the repo root)
python3 -m pytest skills -q                       # expect 1108 passed

# the browser end-to-end (manual only — NOT in CI, by repo convention)
NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/code-anchors.e2e.cjs   # expect 20/20
NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/view-controls.e2e.cjs  # expect 9/9

# the live dogfood page (8 blocks, real anchors, one deliberately stale)
./skills/annotate/ensure_server.sh
open http://localhost:3080/s/code-anchors-dogfood/
```

**The server caches Python at process start.** If you change `server.py`, `anchors.py` or
`check_anchors.py`, `pkill -f skills.annotate.server` and re-run `ensure_server.sh`, or you
will verify against stale code. CSS and JS are read from disk per request — those just need a
reload. *This bit me once; the page was served by a 40-minute-old process.*

**Measure, do not eyeball.** Playwright driving the real page and reading
`getBoundingClientRect()` / `getComputedStyle()` is how every UI claim in this branch was
settled. Two separate design errors survived review and were only caught by looking at
pixels.

---

## 3. The files you will touch

| File | What lives there |
|---|---|
| `skills/annotate/static/style.css` | `=== Code anchors ===` block, from line ~1515. Everything visual. |
| `skills/annotate/static/script.js` | `codeWideKey` · `highlightCodeLine` · `renderCodePane` · `renderCodeColumn` · `setDocumentCodeFlag` (line numbers drifted in the chrome pass — grep, do not trust them) |
| `skills/annotate/static/export.js` | `STRIP` list — controls removed from an exported file |
| `skills/annotate/tests/test_smoke_code_panes.py` | source-presence assertions on the CSS/JS |
| `skills/annotate/tests/e2e/code-anchors.e2e.cjs` | the 20 behavioural assertions |
| `skills/annotate/tests/e2e/view-controls.e2e.cjs` | the 10 assertions for the top-bar view controls |
| `skills/annotate/static/highlighter.js` | the reading highlighter, self-contained |
| `skills/annotate/tests/e2e/read-highlighter.e2e.cjs` | its 14 assertions, incl. the bugs in §7c |
| `skills/annotate/tests/test_smoke_view_controls.py` | fast guards for those, including the CSS ordering trap |

`skills/annotate/anchors.py` is the server side. You almost certainly do not need it for UI work.

---

## 4. Settled decisions — do not relitigate these

Each was decided by the repo owner after seeing it rendered. Changing one is fine; changing
one *by accident* is not.

1. **Split card, prose left / code right**, 46/54, chosen over a sticky right rail. A rail
   loses the pairing when you scroll away and loses it entirely in an export.
2. **The server reads the real file.** Blocks carry anchors, never code text. That is what
   makes a pane un-stale and an anchor cheap (~15 tokens) to write.
3. **The read-only share link serves code panes.** Deliberate. A shared page without panes
   would be the detached document the feature exists to eliminate. *Server filesystem paths
   are NOT covered by this* — see trap 4.
4. **No "no code cited" marker.** An unanchored block renders as a normal full-width card.
   Reversed after the first dogfood: the marker cost 573px of prose width and left 301px of
   dead column. Accepted consequence: **nothing catches a block that should have cited code
   and didn't.** The rule and the check both only validate anchors that were written.
5. **The pane is a reading aid.** Nothing inside is a click target except `.cp-widen` and
   `.cp-jump`. Comments come from the card header. A code line painted like a
   jump-to-source link that opens a comment box is a lie about what a click does — the
   flowchart pane learned this the hard way first.
6. **Full-bleed slab.** Zero column padding, square corners, full height. Reclaimed 51px of
   code width and removed the dead grey below a short pane.

---

## 5. The light palette — measured, not chosen by taste

Ground `#e3e7ee` · anchor row `#cbd9f2` · chrome `#d8dde7` · divider `#c3cad6`

| token | hex | on ground | on anchor row |
|---|---|---|---|
| base | `#1b1f26` | 13.33:1 AAA | 11.61:1 AAA |
| punctuation / operator | `#333a45` | 9.24:1 AAA | 8.05:1 AAA |
| number / literal / type | `#7c2d12` | 7.55:1 AAA | 6.58:1 AA |
| keyword / title | `#6b21a8` | 7.03:1 AAA | 6.12:1 AA |
| function / built-in | `#1e40af` | 7.03:1 AAA | 6.13:1 AA |
| string | `#065f46` | 6.19:1 AA | 5.40:1 AA |
| comment / meta | `#4e5665` | 5.96:1 AA | 5.19:1 AA |
| status `moved` | `#92400e` | 5.72:1 AA | — |
| status `stale`/`missing`/`refused` | `#991b1b` | 6.70:1 AA | — |

**Nothing sits below AA.** If you change a colour, recompute — the helper is four lines:

```python
def lin(c):
    c = c / 255
    return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
def lum(h):
    h = h.lstrip('#'); r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b)
def ratio(a, b):
    la, lb = lum(a), lum(b); hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
```

**Tokyo Night Day was rejected on measurement, not taste.** It is the obvious "same family
as our dark theme" choice and it fails **8 of 9 tokens**, worst at 1.85:1. The owner's brief
was explicit: good contrast, *not washed out and pale*. Do not reach for it again.

The two status colours (`#92400e`, `#991b1b`) are the only part of the palette the owner did
not personally specify — flagged to them, not yet commented on.

---

## 6. Traps — things a UI change here must not reintroduce

Every one of these actually happened on this branch.

1. **`opacity` on a light ground destroys contrast.** Context rows used `opacity: 0.5`; on
   `#e3e7ee` a comment lands at **2.17:1**, unreadable. They now de-emphasise by
   *desaturation* — one muted grey, syntax colours suppressed, 4.61:1. The override is
   `.codepane .cp-row.is-context [class^="hljs-"]` etc., deliberately (0,3,0) so it outranks
   the two-class token rules. **Do not "simplify" it back to opacity.**
2. **The split rule must carry `:not(.collapsed)`.** `section.block.card.collapsed .card-body
   { display: none }` (style.css:596) and the split rule tie at specificity (0,4,1), and the
   split rule sits *later* — so without the guard, folding a code-bearing card does nothing.
   e2e item 12 covers this.
3. **`main.prose p` beats any bare `.cp-*` paragraph rule.** (0,1,2) vs (0,1,0). This bit
   `.cp-note` — its own padding silently did nothing and it inherited the 140px right gutter
   meant for prose hover buttons — and then bit the CARD prose the same way (§7.1). The note
   itself is gone now, but the trap is not: any new `<p>` inside a pane must be scoped under
   `.codepane`, and any new rule for prose inside a card must carry `main.prose`.
4. **Server filesystem paths must not reach non-owners.** `data-repo-root` /
   `data-project-name` are gated on `_is_owner()`, and `.cp-jump` is in `export.js`'s STRIP.
   Decision 3 covers code excerpts reaching strangers; it does **not** cover
   `/Users/<name>/...`. Three separate leaks of this class were fixed here.
5. **Do not let the light theme leak.** `code-theme.css` (Tokyo Night **Dark**) still paints
   ordinary fenced code blocks elsewhere in annotate. Every light rule is scoped under
   `.codepane`. Verified: a fenced block still renders `#1a1b26`. Re-verify if you touch the
   token rules — a page-wide recolour is the failure mode.
6. **Two panes build rows the same way — a blind replace hits both.** The pflow source pane
   (`.pflow-row` / `.pflow-num`) and the code-anchor pane (`.cp-row`) both contained the
   line `row.append(num, text);` at identical indentation. Removing the code pane's line
   numbers with a global string replace silently stripped the FLOWCHART pane's gutter too;
   nothing in the code-anchor tests noticed, and `pflow.e2e.cjs` caught it. Anchor edits to
   the surrounding class name, and run the whole e2e sweep, not just the file you think you
   touched.
7. **`highlightCodeLine` needs its length cap.** `text.length > 20000` → plain text. Without
   it, an anchor into a minified file hands `hljs.highlightAuto` a 100KB line and stalls the
   render synchronously. The pane caps line *count* (40), never line *length*.

---

## 7. UI issues — what the chrome pass fixed, and what it did not

**Fixed 2026-08-21** (commit on this branch). Two complaints from the repo owner drove it:
the pane's stacked bars and line-number ruler distracted from what the code says, and the
prose column was giving up width to a gutter reserved for buttons.

*Numbers below are from the live dogfood page at 1440px, re-measured after the change.*

| Block | chrome before | chrome after | code px | overflow |
|---|---|---|---|---|
| section-2 (moved) | 101 | **35** | 157 | 0 |
| section-3 (moved) | 101 | **35** | 130 | 0 |
| section-5 (ok) | 68 | **34** | 139 | 0 |
| section-7 (stale) | 101 | **61** | 0 | 0 |

1. **The 140px prose gutter was still there, inside cards.** `main.prose p` sets
   `padding: 4px 140px 4px 6px` at specificity (0,1,2); the `.card-body p` rule written to
   release it is (0,1,1) and lost. The comment above it claimed the gutter "is gone" — it
   never was. Same trap as `.cp-note` (§6.3), on the prose side, and no source-level test
   could see it. Fixed by prefixing those rules with `main.prose`. **Card prose text went
   314px → 442px, +41%.** `pre` is deliberately excluded — see the comment at that rule.
2. **The chrome stack is one band.** `.cp-note` moved off its grey bar onto the code ground
   as an italic caption; the `moved` notice became `.cp-chip` in the header. A pane with no
   code (stale / missing / refused) still gets the full `.cp-status` sentence — its whole
   content is the reason it is empty.
3. **The pane paints no line numbers at all, and carries no caption.** Both went in stages,
   and the intermediate steps are worth knowing about because they were each rendered,
   looked at, and reversed:
   - The ruler first became anchored-row-only, with the gutter kept for indent and sized
     per pane in `ch`. Seen in place, an anchored-row-only number is *still a number to
     read*, and the header already says `file:134`. So the number, the gutter and the
     whole `--cp-gutter` mechanism are gone. `.cp-row` carries a flat 12px `padding-left`
     instead — real geometry, which is what keeps the anchor row's 3px inset bar off the
     first glyph. e2e item 15 measures that inset.
   - `.cp-note` became an italic caption on the code ground, then was removed outright. The
     `note` field went with it — out of `anchors.py`, out of `references/code-anchors.md` —
     because a reference telling Claude to author a string nothing renders is both a false
     doc and wasted tokens. **An anchor written before the removal is still accepted:**
     `anchor_problem` is a list of checks, not a reject-unknown-keys gate, so an existing
     `blocks.json` keeps validating and the string is simply ignored.
4. **Blank context rows collapse to 9px** (`.cp-row.is-blank`). With nothing in them at all
   they read as a hole in the pane at full row height.

**Still open:****Still open:**

- ~~**Horizontal overflow.**~~ **Gone.** Two things fixed it: dropping the 35px number
  gutter, and the view controls giving the reader a wider column when a line still does not
  fit. Measured on the dogfood page at 1440px: **zero panes overflow at the default width**,
  and zero at every width/layout combination. The last stubborn case was
  `anchors.py:135`'s docstring, which no gutter tuning ever reached.

- **A stale pane is still a tall box.** 85px of chrome now rather than 101, but the box
  height is set by the prose beside it (`.codepane { height: 100% }`), not by its content.
- **The dogfood doc's anchors have drifted** — several render `moved`, because the fix wave
  edited `anchors.py` underneath them. The drift machinery working correctly, and a useful
  live specimen. Do not "fix" the anchors unless you want to lose it.

## 7b. Page-wide view controls (added 2026-08-21)

Two buttons in the top bar, both pure view preferences — they change how the reader sees
the document, never what it says. Both stay live on the read-only share link for that
reason, and both ride into an export.

| control | id | body attribute | values |
|---|---|---|---|
| page width (cycles) | `#width-toggle` | `data-width` | `normal` 1040px · `wide` 1180px · `extra` 1600px |
| code-pane layout | `#codelayout-toggle` | `data-code-layout` | `split` · `wide` |

**Two things here are load-bearing and easy to break by accident.**

1. **The width rules must stay BELOW `body[data-has-code="1"]` in style.css.** Both
   selectors are specificity (0,1,1), so source order is the only thing that decides.
   Reorder them and all three settings collapse to 1180px on any document that cites code —
   measured, not guessed. Guarded twice: `test_smoke_view_controls.py` compares the indices
   in milliseconds, and `view-controls.e2e.cjs` item 3 reads the computed value.
2. **Wide mode is an override, never a rewrite.** It sets one body attribute; it does *not*
   write `data-code-wide` on each block. That is what lets leaving wide mode hand the reader
   back exactly the panes they promoted by hand, and only those. e2e item 6 round-trips it.

**Every new session opens `wide`.** This used to be derived from `data-has-code` — 1180px
with anchors, 1040px without — which made the opening measure depend on something the reader
never chose, and left a prose-only document narrower than it needed to be. One default now
(`DEFAULT_WIDTH` in script.js); only an actual click persists anything else.

**The page chrome has its own measure and never follows `--content-max`.** The top bar, stat
strip, composer band and footer actions all sit on `--chrome-max: 1600px`. The bar is not
content: narrowing the reading column used to drag the search box and every control inwards
with it. Measured before the split, the width toggle sat at **x = 980 / 1051 / 1261** for
normal / wide / extra — a 281px swing from a setting that is about prose. It now holds at one
x at every width, while the column moves underneath it. `.page-header`'s own rule lives in
core.css (shared engine, not ours to edit), so it is overridden in annotate's style.css with
a `body` prefix — (0,1,1) against core's (0,1,0) — rather than relying on the order the two
stylesheets happen to be linked in.

`.width-btn` is a **fixed** 72px, not a minimum. "NORMAL" renders 48.94px of text against
"WIDE"'s 28.47px, so at `min-width: 66px` the button grew to 66.94px on one setting only —
and since `.header-actions` is right-aligned, that 0.94px pushed every control left by 1px
whenever the width was Normal. e2e item 10 measures the toggle's x at all three.

---

## 7c. Reading highlighter (added 2026-08-21)

Drag-select prose while it is on and the stretch keeps a marker background, so the page shows
a trail of what has already been read. `#highlighter-toggle` in the top bar, with
`#highlighter-clear` beside it. Front-end only — nothing reaches the server.

Lives in its own `skills/annotate/static/highlighter.js`, loaded after `subunits.js`.

**Painted with the CSS Custom Highlight API, not with wrapper spans.** This is the choice
everything else follows from: block content is written with `innerHTML`, then walked twice
more — `subunits.js` wraps sentences, `search.js` inserts `<mark class="search-hit">` — so
wrapper elements would be shredded by one and would shred the other. Ranges painted from
outside the DOM avoid all of it, and mean an export cannot inherit one reader's progress.

**Storage:** `annotate.read:<rid>:<blockId>` → `{v, ranges:[[start,end],…]}`, offsets counted
over *prose text only*. A block's marks are dropped when its version moves, since Claude
rewrote the text they pointed at.

**Colour** is page-wide and picked from a five-swatch popover on `#highlighter-palette`
(same `initTopPanels` machinery as the legend, so Esc / click-outside / one-at-a-time come
free — its click-outside exemption is now a per-panel `dismissOnOutsideClick` flag rather
than a hardcoded check for the legend's id). Painted by
`body[data-highlight-color="…"] ::highlight(annotate-read)`; verified in a browser that
`::highlight()` does honour an ancestor selector, since it is a pseudo on the originating
element and cannot be styled inline.

Each colour measured against all three colours prose uses on it — body `#3a3d44`, bold
`#1d1d1f`, link `#1e40af`. None is below AA; worst in the set is pink on a link at 4.81:1.

| | hex | body | bold | link |
|---|---|---|---|---|
| yellow | `#fcd34d` | 7.54 | 11.67 | 6.05 |
| green | `#6ee7b7` | 7.14 | 11.04 | 5.72 |
| orange | `#fdba74` | 6.45 | 9.98 | 5.17 |
| blue | `#93c5fd` | 6.03 | 9.33 | 4.84 |
| pink | `#f9a8d4` | 6.00 | 9.28 | 4.81 |

**Two colours that had to go with it.** The pale blue `.sub-unit:hover` wash read as a second
kind of highlight in the same family as the selection — removed; the hover cue was never the
wash, it is the control strip appearing (`.sub-unit:hover .unit-strip`, still there, and the
e2e asserts both halves so removing one cannot silently remove the other). And `::selection`
goes neutral grey while the highlighter is on: the accent blue over a marker colour
composites into a hue that is in no palette — measured over yellow it lands on
`rgb(207,193,104)`, an olive-green that reads as a third highlight colour.

### Three bugs this shipped with, then didn't

Each was found by sabotaging a passing test, and each now has one that reproduces it.

1. **A control click erased what you just highlighted.** A drag deliberately leaves its text
   selected — `script.js:189` quotes the live selection into a comment — so the *next* click
   arrives with a live selection over already-highlighted words, takes the erase branch, and
   destroys the mark. `onMouseUp` now ignores mouseups on `button, a, input, textarea,
   .page-header, footer`. Deliberately not "must be inside `main.prose`": a drag released in
   the page margin is still a reading gesture.
2. **Revealing the eraser shifted the bar 26–30px.** `.header-actions` is right-aligned, so a
   `display: none` → `inline-flex` button pushes its neighbours sideways — far enough to
   slide the eraser under a pointer that had not moved since the click that revealed it. The
   next click would hit clear-all and wipe the page. The slot is now always reserved
   (`visibility` rather than `display`).
3. **The offset test proved nothing.** The obvious test — highlight, reload, check the words —
   *cannot* catch a walker that miscounts UI text, because storing and restoring use the same
   walker and the error cancels. It only shows up when the UI text differs between the two
   moments, which is what really happens: `.unit-chip` and `.unit-composer` appear inside a
   paragraph *after* a reader has highlighted things. Item 7b adds UI text ahead of a stored
   highlight and repaints. Sabotaged, it reports the highlight landing on
   `"highlights.🗑✓💬\nMarbled quartz hums…"` — the strip's emoji counted as prose.

4. **A CSS-rule check would not have proved the picker works.** `::highlight()` is painted by
   the engine — there is no element to inspect and no computed style to read — so the colour
   test screenshots the highlighted words, hands the PNG back into the page as a data URL,
   draws it on a canvas and takes the modal pixel. It measures `252,211,77` → `249,168,212`.
   Asserting the CSS rule exists would only have proved a rule was *written*, not that it won.

---

## 7d. Code pane themes (added 2026-08-21)

Four themes, picked from `#panetheme-toggle` in the top bar. `body[data-pane-theme="…"]`,
persisted per response, and it travels into an export.

**A theme is a block of variable declarations and nothing else.** Every colour the pane
paints comes from a `--cp-*` variable declared on `.codepane`; the defaults *are* Daylight.
That refactor was proved neutral before any theme was added — computed styles compared before
and after, and the rendered screenshots came out byte-identical.

**Every theme rule is scoped under `.codepane`.** `code-theme.css` paints ordinary fenced
blocks across the whole page, and Midnight is the dangerous one: it would look perfectly
correct inside the pane while recolouring every fenced block on the page. `view-controls`
item 11 samples an ordinary fenced block under **every** theme, not once.

| theme | ground | tightest pairing |
|---|---|---|
| Daylight | `#e3e7ee` | muted `#5f6773` on ground, 4.61:1 |
| Midnight | `#1a1b26` | comment `#8f99c4` on the anchor wash, 4.84:1 |
| Parchment | `#f2ead9` | comment `#6b6150` on the anchor wash, 4.52:1 |
| Contrast | `#ffffff` | comment `#4a5160` on the anchor wash, 6.40:1 |

Nothing below AA ships. Two findings from measuring:

- **A context row is never the anchor row** — the roles are exclusive — so `--cp-muted` cannot
  land on the anchor wash and is only checked against the ground. `comment` *can*: an
  anchored line may itself be a comment. That distinction is what caught Midnight.
- **Midnight is Tokyo Night Dark, seven of eight tokens unchanged.** Only `comment #565f89`
  failed, at 2.76:1 — the usual dark-theme dim convention. Lifted to `#8f99c4`, which then
  needed the anchor wash darkened from `#2c3350` to `#272d47` to clear 4.5 there too. That
  wash is still more visible against its ground (1.264:1) than Daylight's shipped one is
  against its own (1.148:1).

**A pre-existing AA failure fell out of this.** `.cp-jump` names `var(--cp-dim)` but was
painting the page accent `#0071e3`, because `main.prose a` is (0,1,2) and a bare `.cp-jump`
is (0,1,0). Measured: **3.45:1 on Daylight's chrome band** — below AA on the theme already in
production, and 3.16:1 on Midnight's. Fixed by scoping to `.codepane .cp-jump` (0,2,0). Same
trap as the one that cost the card prose 140px. The e2e compares the link against the pane's
own `--cp-dim`, so it keeps holding as themes are added.

**Whole-page theming (light/dark for the entire page) is explicitly NOT this.** It was
scoped out to its own job: the base variables live in `core.css`, the shared engine used by
two other skills, so it either changes their appearance too or needs an annotate-local
override layer.

---

## 8. Open non-UI items

- **Two doc lines are stale.** `references/code-anchors.md`'s Limits section omits the new
  1 MB file cap and 2000-char line cap; `references/pushing.md`'s step 4b still says a
  non-zero check exit means "fix `blocks.json`", which is wrong for the wrong-repo refusal
  case (you fix the *directory*). ~4 lines.
- **Python 3.9 has never been executed.** It is the declared floor and the CI matrix covers
  it (`.github/workflows/ci.yml` pins `['3.9','3.12']`), but the branch has never been
  pushed, so CI has never run it. Everything is read-verified only.
- **10 deferred minors**, each triaged by the final whole-branch review as safe to carry,
  with reasons, in `.superpowers/sdd/2026-08-20-code-anchors/progress.md`.
- **The final review's verdict was "merge."** No Critical findings; the five Important ones
  were fixed and re-reviewed.

---

## 9. Where the durable records are

| | |
|---|---|
| `docs/superpowers/specs/2026-08-20-code-anchors-design.md` | the spec, plus a dated amendment recording the decisions the owner reversed after seeing them rendered, and dogfood field notes |
| `docs/superpowers/plans/2026-08-20-code-anchors.md` | the original 11-task plan. **Left as a historical artifact** — it still describes the removed "no code cited" slot. Deliberate: rewriting it would erase the fact that the decision changed. |
| `.superpowers/sdd/2026-08-20-code-anchors/progress.md` | every ruling made during execution, every deferred minor, every fix round |
| commit messages on this branch | carry the *why* — the palette rejection, the opacity trap, the version-hash trap |

Two design-review artifacts exist for the layout and density decisions; ask the owner for the
links if the reasoning behind full-bleed or 46/54 matters.
