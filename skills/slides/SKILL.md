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
harness (CSS + JS — the slide canvas, cover/divider layouts, present mode, progressive
reveal) has one source of truth, [`framework/`](framework/) in this skill (`deck.css`,
`deck.js`, `VERSION`), and every deck carries its own **snapshot** of it: at creation, `framework/inline.py` pastes both files into the deck between `<!-- framework:css -->` and `<!-- framework:js -->` marker pairs, with a comment recording the version and date. The same command inlines the **theme** — colours, faces, logo — between `<!-- theme:css -->` markers; see Themes below. From
then on the deck owns that copy. Edit the deck's copy when that one deck needs a change;
edit `framework/` when future decks should get it; re-run `inline.py` on a deck only when
you deliberately want it to adopt the current framework. Everything else — images, per-deck styling, deck
content — stays written directly into the deck's own `.html`, out of a fixed vocabulary
of classes.



**One deck in the folder is the reference, and `$DECKS/README.md` names it.** Where decks
disagree, that one wins. The name lives with the decks rather than in this skill, because
every decks folder has its own history and its own reference. That README also holds the
rules the decks obey — read it if the user asks anything about folders or naming.

## Before anything else

**Find the decks.** The decks folder is set once, by the user, and never guessed from the
current directory: `$SLIDES_DECKS_DIR`, else `$MB_DECKS_DIR` (the older name), else
`"decks_dir"` in `~/.config/slides/config.json`. `bin/decks where` resolves it. Run this
block, with the rest of any step that uses `$SLIDES` or `$DECKS`, in one Bash call — the
Bash tool keeps no variables between calls:

```bash
if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
claude-annotate: python3 was not found on PATH.
claude-annotate is the marketplace that ships this plugin and claude-ide-review.

This plugin needs Python 3.9 or newer (standard library only — nothing to
pip install).

  macOS:  xcode-select --install     # or: brew install python
  Linux:  install python3 with your distribution's package manager

Run /annotate-doctor for a full check of this machine.
EOF
  exit 1
fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c '
import json, os, sys
NAME, MARKER = "claude-annotate", "skills/slides/framework/inline.py"
ok = lambda r: bool(r) and os.path.isfile(os.path.join(r, MARKER))
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if os.path.basename(entry) == "bin" and ok(os.path.dirname(entry)):
        print(os.path.dirname(entry)); sys.exit()
try:
    root = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))[NAME]["installLocation"]
except Exception:
    root = None
if ok(root):
    print(root); sys.exit()
sys.exit(f"could not locate the {NAME} plugin root")
')}"
[ -n "$PLUGIN_ROOT" ] || { echo "claude-annotate: plugin root not found" >&2; exit 1; }
SLIDES="$PLUGIN_ROOT/skills/slides"
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

`components.md` says how a slide is drawn. It does not say what a slide should **say** —
that belongs to the meeting the deck is for, and it differs per meeting.

**Playbooks live with the decks, not in this skill.** A playbook carries one meeting's
audience, slot length and section order — none of which transfers to a different room —
so it belongs beside the decks it governs, at `$DECKS/playbooks/<meeting-slug>/`. Keeping
them out of the skill also keeps the skill about *how a slide is drawn*, which is the only
thing that is true for every deck. Look for one next to the decks:

```bash
ls "$DECKS"/playbooks/ 2>/dev/null || echo "no playbooks in this decks folder"
```

If a folder there matches the meeting this deck is for, read its `PLAYBOOK.md` before
writing any content, and follow whatever else it points at. If there is none, ask the
user what the meeting expects, and offer to write a playbook into
`$DECKS/playbooks/<meeting-slug>/` if it is a meeting that recurs.

Never fold a playbook into this skill. A
playbook names real people and a real audience; the skill is generic and gets read in
full on every invocation. Keep the boundary.

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

### Changing the shared framework itself

**The goal is that a deck's own `<style>` block stays small or empty** — content and
per-deck styling only, everything reusable already in the framework. So the default
when a slide needs a new visual pattern is to build it deck-local first, prove it on a
real slide, then promote it — don't design speculatively generic components in
`framework/` before anything uses them. A component is ready to promote once it has
actually rendered a real slide (not just been written) and nothing about it is specific
to that one deck's content. Two decks independently reinventing the same shape is a
stronger signal than one deck defining it — but don't wait for two if it's obviously
generic (a step chain, a status table) rather than obviously deck-specific.

The source is [`framework/`](framework/) in this skill:

1. Edit `framework/deck.css` / `deck.js` and bump `framework/VERSION` (semver: breaking
   change to a class a deck already uses = major, additive = minor/patch). Commit with the
   rest of the repo.
2. Existing decks are unaffected — each keeps the snapshot it was created with, labelled
   in its `framework:css snapshot vX.Y.Z` comment. Move a deck to the current framework only when you want it to: `python3 "$SLIDES/framework/inline.py" <deck>.html`
   replaces the framework and theme blocks, then re-run the layout audit — a framework change can shift an
   already-written slide.
3. Update [`references/components.md`](references/components.md) — move the entry out of
   whatever "deck-local" section it was in, into the shared vocabulary proper. Move the
   deck's own copy of the promoted rules out of its `<style>` block once its framework
   snapshot has been refreshed and renders identically.

### What the harness gives you for free

| | |
|---|---|
| Zoom to fit | `.deck` gets an inline `zoom` clamped to 0.5–1.5 so the whole slide fits the window; recomputed on resize |
| Page numbers | `.pg` (`3 / 11`) is injected into every slide; the `.num` gutter marker is renumbered too — **so whatever you type in `.num` is ignored** (the reference deck still reads `1 2 3 4 4 5 6 7 10 11`) |
| Present mode | `F` or the `▶ Present` button — fullscreen, one slide scaled to the viewport. `←` `→` `Space` `PageUp/Down` `Home` `End` move, `Esc` exits. Opening the file at `#present` or `#present-4` starts in present mode at that slide (window-filling; `F` then goes fullscreen) — `/deck`'s ▶ buttons use this |
| Progressive reveal | `.frag` elements appear one step per `→`/`Space` in present mode; `data-frag="n"` groups them. See `references/components.md` |
| Jump nav | the `☰ JUMP` rail on the left edge, expanding on hover; hand-written, one `<a href="#sec-…">` per section |

So: give every jumpable slide an `id`. There are no speaker notes — the harness does not
support them, by the house style's rule. What the presenter says lives in `notes.md` or
in their head, never in the deck.

### Themes

The framework is structure only; every colour and face it uses comes from a **theme**,
inlined into the deck at creation as its own snapshot. The skill ships one, `default`
(`themes/default/theme.css`). A theme is a directory holding:

- `theme.css` — required. The tokens below, plus any rules that restyle a component or
  add the theme's own (`.k.<project>`, `.cmp.<name>`, a brand shell).
- `logo.svg` — optional. Drawn top right on the cover through the `theme:logo` markers.
- `README.md` — optional. The theme's own components and rules. **Read it before writing
  slides** when the deck's theme has one.

Which theme a new deck gets, first match wins: `inline.py --theme <name|path>`,
`$SLIDES_THEME`, `"theme"` in `~/.config/slides/config.json`, else `default`. A name is
looked up in `~/.config/slides/themes/<name>/` before the shipped themes.
`python3 "$SLIDES/framework/inline.py" --which-theme` says which one applies and why.

**To make a theme for the user:** copy `themes/default/` to
`~/.config/slides/themes/<name>/`, change the token values, add their `logo.svg`, and set
`"theme": "<name>"` in `~/.config/slides/config.json`. An existing deck keeps its snapshot;
to move it to the new look, re-run `inline.py --theme <name>` on it and re-run the audit.

Use the tokens, never literal colours, in slides and per-deck styles:

```css
--ink --mute --faint                  /* text, strongest to weakest */
--paper --panel --panel2 --rule       /* slide, card, warm card, hairline */
--accent                              /* carries the eye: kickers, bullets, rules, the cover spine */
--settled --neutral --wrong --positive/* agreed or done · evidence · rejected · good */
--dark --on-dark --on-dark-mute       /* cover, dividers, jump rail */
--head --body --mono                  /* titles and asides · everything else · keys and config */
```

`--accent` is the only accent. Do not add a fifth semantic colour; a theme that needs one
defines it in its own `theme.css` and documents it in its README. The older palette names
(`--orange`, `--olive`, `--slate`, `--berry`, `--green`) are kept in the default theme as
aliases, so markup copied from an older deck still resolves.

### notes.md

The talk plan, not a transcript. Follow the reference deck's shape:

```markdown
# <Audience> — <date>

**<Day date, time, room.>** Organiser, who is invited, slot length.

## The frame
What this deck is and what last time was. Two or three sentences. What is deliberately
excluded, and where it belongs instead.

## Running order
| # | Slide | Time |
Then: the total, what to drop if it runs long, and what must never be dropped.

## Open before <day>
Decisions and questions still outstanding, each with who owns the answer.

## Things worth saying out loud
Facts that belong in the room but not on a slide.

## Not in this deck
True, useful, and deliberately absent — with the reason.
```

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

### Watch for collisions when borrowing

Components copied from another deck can collide with what is already there. The known
one: `.st` is both a `.ctxp` subtitle and the tree status pill in older decks. Put both in one deck and the subtitle inherits the pill's `font-weight`,
`padding`, `min-width` and `text-align`, because `.ctxp .st` only overrides the
properties it names. That is why the reference deck renamed the subtitle to `.stt` —
use `.stt` in any deck that carries both. `references/components.md` flags the rest.

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

### Reading the result

**Any overflow is a bug.** A healthy deck reports `overflow: []` on every slide — the
reference deck does.

**A gap is a question, not a verdict.** Two cases:

- *Bottom gap on a top-anchored slide* — an `.introb` or `.tree` slide with nothing pinned
  at the bottom. Fine. The reference deck's tree slides run 269–383px of floor gap.
- *A block sandwiched between the header and a bottom-pinned `.strip`* — **not fine if the
  two gaps differ much.** Centre the content in the band instead of leaving the slack at
  one end. Set the block's `top` so the space above it and below it match.

That is what the reference deck does, and it is what the audit should show:

| Slide | Above the block | Below it |
|---|---|---|
| 4 · before/after `.ctxp` pair | 86px | 82px |
| 7 · `.flow` chain | 133px | 126px |
| 10 · `.flow` chain | 102px | 94px |
| 11 · `.stab` + `.rails` | 72px | 67px |

Within about 10px is the target. A `.strip` at `bottom:36px` ends the usable band around
`y=640`, so a block of height `h` sitting under a header that ends at `y=hdr` wants
`top ≈ hdr + (640 − hdr − h) / 2`.

Two shortcuts that are not shortcuts: never fix an overflow by shrinking type below the
component's own scale. Split the slide.

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

The script does three things per deck, and each has a reason worth knowing:

1. **Bakes a print stylesheet into the `.html`**, replacing any previous copy rather than
   stacking one — it matches on the `/* pdf-export print rules */` marker and substitutes.
   So the block is regenerated, never hand-edited, and it always ends up last before
   `</head>`. If you find it in the middle of the head, styles were appended after the
   last export; that is normal and the next export moves it back.
2. **Prints to PDF via headless Chrome**, one slide per page at 1280×720.
3. **Renders one PNG per page at 192dpi** (2560×1440, exactly 2×) into `png/`, renumbered
   to a fixed width so a plain sort is presentation order.

### What the print block does, and why

```css
:root{--body:Helvetica,Arial,sans-serif!important}
body>*:not(.deck){display:none!important}
.deck{display:block!important;gap:0!important;zoom:1!important}
```

- **Helvetica is forced** because the on-screen `--body` stack ends in a generic
  `sans-serif` that macOS resolves to San Francisco, and Chrome cannot embed SF as a real
  font — it writes each glyph as an unhinted Type 3 procedure that most PDF viewers
  render badly. Helvetica embeds as TrueType. Georgia (`--head`) and Menlo (`--mono`)
  already do, so they are left alone. (The comment in `export-pdf.py` says the stack ends
  in `system-ui`; the decks now end in `sans-serif`, which resolves the same way.)
- **`body>*:not(.deck)` is hidden** because the harness script appends the present button
  to `<body>`. Only `.deck` is content.
- **`.deck` zoom is undone** because the script sets an inline zoom to fit the browser
  window, and that zoom would otherwise scale the printed page.

A consequence worth remembering: `Cmd+P` in the browser gives the same PDF, because the
rules are baked into the file rather than passed on the command line.

The `.html` never leaves the repo. `.pptx` is retired.

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
