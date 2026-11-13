# Framework changes, the harness, themes and notes.md

Moved out of SKILL.md. Read it when a deck needs a change to the shared framework, when borrowing a component from another deck, when making or swapping a theme, when asked what the harness does for a deck, or when writing `notes.md`.

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

## Borrowing components: the `.st` collision

`.st` is both a `.ctxp` subtitle and the tree status pill in older decks. Put both in one deck and the subtitle inherits the pill's `font-weight`, `padding`, `min-width` and `text-align`, because `.ctxp .st` only overrides the properties it names. That is why the reference deck renamed the subtitle to `.stt`: use `.stt` in any deck that carries both.
