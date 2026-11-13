---
name: slides
description: Use when the user wants to build, extend, audit or export one of their single-file HTML presentation decks — "start a new deck for Thursday's talk", "add two slides to that deck", "does that slide overflow?", "re-export the deck and its PNGs". Decks live in one decks folder, set with `$SLIDES_DECKS_DIR` or `~/.config/slides/config.json`, and take their look from a theme the user can swap. Not for Confluence pages, artifacts or generic slide requests.
how: "Inlines the canonical 1280x720 harness from framework/ and the chosen theme as snapshots the deck owns, writes slides from the existing component vocabulary using the deck the decks folder names as its markup reference, then measures every element against its slide rect in a real browser. Exporting is a separate job that runs only when the user asks for it."
collections: [none]
argument-hint: "[create|extend|export] <deck folder, slug or date>"
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - mcp__playwright-headless__browser_navigate
  - mcp__playwright-headless__browser_evaluate
  - mcp__playwright-headless__browser_take_screenshot
  - mcp__playwright-headless__browser_close
---

> **This writes into the decks folder, which is somebody's working tree.** Nothing is
> committed. Review with `git diff` and discard with `git checkout --` if it is wrong.

Decks are hand-written HTML: one 1280×720 canvas per slide, one shared harness, one theme. The
harness has one source of truth, [`framework/`](framework/) in this skill, and every deck carries
its own **snapshot** of it, with the **theme**, pasted in by `framework/inline.py` between marker
pairs. From then on the deck owns that copy: edit the deck's copy when that one deck needs a
change, edit `framework/` when future decks should get it, re-run `inline.py` on a deck only to
adopt the current framework. Everything else stays in the deck's own `.html`, out of a fixed
vocabulary of classes.

**One deck in the folder is the reference, and `$DECKS/README.md` names it.** Where decks
disagree, that one wins. That README also holds the rules the decks obey.

## Before anything else

**Find the decks.** The decks folder is set once, by the user, and never guessed from the
current directory: `$SLIDES_DECKS_DIR`, else `$MB_DECKS_DIR` (the older name), else
`"decks_dir"` in `~/.config/slides/config.json`. `bin/decks where` resolves it. Run this
block, with the rest of any step that uses `$SLIDES` or `$DECKS`, in one Bash call — the
Bash tool keeps no variables between calls:

```bash
SLIDES="$(claude-annotate root)/skills/slides" || exit 1
DECKS="$(python3 "$SLIDES/bin/decks" where | sed 's/  (.*//')"
```

**If no decks folder is set** (`decks where` exits 3), ask the user where their decks
should live, then set it up there:

```bash
python3 "$SLIDES/bin/decks" init <folder> --use
```

That creates the folder with a `README.md`, a starter `PRESENTATION-STYLE.md`, the
`export-pdf.py` exporter and a `.gitignore`, and records the folder in
`~/.config/slides/config.json`. **If the folder is set but has no `export-pdf.py`**, say so
and offer the same `init` on it — it only adds the files that are missing.

Then:

1. `ls "$DECKS"` — the folder list is the index.
2. **Read `$DECKS/PRESENTATION-STYLE.md`.** It is the house style — how long a slide may be,
   which words are refused, what belongs on a slide at all versus what is spoken over a live
   demo. It binds every slide you write here, and it is where the standing answer to "the
   slides are too long" lives. If `$DECKS/playbooks/<slug>/` matches the deck being written,
   read that too: the style file governs length, wording and density, the playbook governs
   structure and running order. `/deck` loads the same two files — keep the two skills in step.
3. Read `$DECKS/README.md` and open the deck it names as the reference. The shared CSS/JS
   comes from `framework/` (below), so the reference deck's job is narrower than it
   used to be: it shows which **markup vocabulary** current decks use. If
   the README names no reference, ask the user which deck to copy from rather than guessing
   from date order.
4. Read [`references/components.md`](references/components.md) before writing any slide.
   It catalogues every reusable class, the markup shape each one expects, and which ones
   are shared versus deck-local.

### Then: is there a playbook for this deck?

`components.md` says how a slide is drawn, not what it should say. Playbooks live with the decks, at `$DECKS/playbooks/<meeting-slug>/`, never in this skill. Run `ls "$DECKS"/playbooks/ 2>/dev/null`; if a folder matches the meeting, read its `PLAYBOOK.md` before writing content, else ask the user what the meeting expects. [`references/playbooks.md`](references/playbooks.md) says why they stay out of the skill.

Never invent a class that a component already covers, and never write a slide as free
inline CSS when `.introb`, `.flow`, `.ctxp`, `.grail`, `.stab` or `.card` would carry it.

---

# Job 1 — Create a deck

### The folder

```
YYYY.MM.DD-slug/
├── YYYY.MM.DD-slug.html   the deck — same name as the folder, this is the master
├── YYYY.MM.DD-slug.pdf    export (gitignored, regenerated)
├── png/                   one PNG per slide (gitignored, regenerated)
├── notes.md               the talk plan
├── assets/                editable originals of anything embedded
└── demo/                  artifacts shown live
```

Hard rules from the README:

- **The deck file is named after its folder**, so it stays self-identifying when shared alone.
- **Nothing else at the top level.** Not a mockup, not a draft, not a colour study — those
  go in `assets/` or are deleted when the deck ships. Git has the history.
- **Decks embed their own content.** Every image is embedded as a `data:` URI. `assets/`
  holds the editable original; the deck holds the embedded copy. The shared CSS/JS is
  embedded the same way, as the framework snapshot (see below).
- A folder ending in **`-working-draft`** is local-only, gitignored, and never published.
  Drop the suffix when the talk ships.
- `.pdf` and `png/` are gitignored and regenerated — never hand-edit either.

### The file

Copy [`references/skeleton.html`](references/skeleton.html), then run `python3 "$SLIDES/framework/inline.py" <deck>.html` once: the skeleton's framework, theme and logo marker pairs are empty on purpose, and that command fills them with the current `framework/deck.css` and `deck.js` and the configured theme. The skeleton also has one cover and one content slide
in the reference deck's markup vocabulary. Change the `<title>`, the cover, and the slides.
Then:

- **The framework blocks belong to this deck now.** A fix this deck needs goes into its
  own copy, between the markers; a fix every future deck needs goes into `framework/`.
  New components go in a **new `<style>` block** after the `<!-- /framework:css -->` marker.
- If a slide needs something the framework doesn't have, that's a per-deck override — add
  it to that new `<style>` block, never by editing `framework/` for a one-off.
- Per-deck content is exactly: the `<title>`, the cover slide, the content slides, the
  `.floatnav` links, and any extra `<style>` blocks.

### Framework, harness, themes, notes.md

Read [`references/framework-and-themes.md`](references/framework-and-themes.md) when a deck needs a change to the shared framework, a new or swapped theme, a question about what the harness does (zoom, page numbers, present mode, progressive reveal, jump nav), or a `notes.md`. What always holds: colours and faces come from the theme's tokens, never literal values; give every jumpable slide an `id`; there are no speaker notes in a deck.

---

# Job 2 — Extend a deck

Adding slides to a deck someone already presented from.

1. **Read the whole deck first.** Which components it already uses is the constraint —
   a new slide should be recognisable as belonging to the same deck.
2. **Insert `<section class="slide">` in place.** Nothing has to be renumbered: the
   harness rewrites `.pg` and `.num` on load. If the deck has a `.home-toc` or a
   `.floatnav`, add the section link there too, and give the slide the matching `id`.
3. **Prefer an existing component.** If the new slide needs something genuinely new,
   add a new `<style>` block; do not grow the shared one.
4. **Run the layout audit** (below) on the whole deck, not only the new slides — a slide
   added between two others can push nothing, but a component copied from another deck
   often lands with the wrong `top`.
5. **Update `notes.md`** — the running order table and its timings are now wrong.

Components copied from another deck can collide with what is there (`.st` is both a `.ctxp` subtitle and the tree status pill in older decks; use `.stt` for the subtitle). `references/components.md` flags the rest.

---

# Layout discipline

**This is the step that costs time when it is skipped.** Slides are absolutely positioned
children of a fixed 720px-tall `overflow:hidden` canvas. Nothing warns you: content that
runs past the bottom is silently clipped, and content that stops 300px short just looks
wrong to everyone in the room. Neither shows up in the HTML.

So measure, in a browser, before exporting.

```bash
cd "$DECKS/<deck-folder>" && (python3 -m http.server 8777 >/dev/null 2>&1 &)
# … audit …
pkill -f "http.server 8777"
```

Then load `http://localhost:8777/<deck>.html` and run
[`references/layout-audit.js`](references/layout-audit.js) against it — paste it as the
`function` argument of a Playwright `browser_evaluate` call, or wrap it in `( … )()` in
DevTools. It sets `.deck` zoom to 1 (the harness fits the deck to the window, which
would skew every measurement), then for each slide reports:

- **`overflow`** — every descendant whose rect escapes the slide rect, and by how much on
  each side. `.num` is excluded on purpose: the gutter marker is pinned at `left:-46px`
  *outside* the canvas by design, and counting it would flag every slide in every deck.
- **`gaps`** — vertical dead bands over 60px between the slide's direct children, and
  between the lowest child and the floor.

Kill the server when you are done.

**Any overflow is a bug.** A healthy deck reports `overflow: []` on every slide. Never fix one by shrinking type below the component's own scale; split the slide. A gap is a question, not a verdict: read [`references/reading-the-audit.md`](references/reading-the-audit.md) to decide.

---

# Job 3 — Export

**Run this only when the user asks for it.** The `.html` is the master and it is what
gets presented from; a `.pdf` and a `png/` folder exist only for handing the deck to
someone as a file. Editing a deck does not oblige you to re-export it, and a stale
`.pdf` beside an edited `.html` is not a defect worth reporting — it is a file nobody
asked for yet. Export when a PDF is actually needed, and not before.

```bash
python3 "$DECKS/export-pdf.py"            # every deck
python3 "$DECKS/export-pdf.py" 2026.08    # only folders whose name contains this
```

Needs Chrome or Chromium, and poppler for the PNG step: `brew install poppler`. No network is needed: the framework and theme are inlined in each deck.

The script bakes a print stylesheet into the `.html` (regenerated, never hand-edited, always last before `</head>`), prints to PDF via headless Chrome at 1280×720 per page, and renders one PNG per page at 192dpi into `png/`. [`references/export-print-block.md`](references/export-print-block.md) says why the print block forces Helvetica and undoes the zoom; read it when a PDF looks wrong.

### Decks stay local

**This skill does not publish.** It does not post decks to Confluence, does not upload
them anywhere, and does not put them in front of an audience. A deck's whole life here
is the folder it lives in: write it, measure it in a browser, and export it to PDF when
someone asks for a PDF. If a deck needs to reach other people, that is a decision the
user makes and carries out themselves — do not offer it, do not prepare for it, and do
not treat an unpublished deck as unfinished work.

## Output

Say what changed, and list every path touched:

**Files written:**
- `<path>` (created | modified)

Then the audit result in one line per slide that had a finding, and the export line if
you ran one. If you did not run the layout audit, say so — do not imply a deck was
checked when it was not.
