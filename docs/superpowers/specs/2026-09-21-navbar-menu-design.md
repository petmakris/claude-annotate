# Collapsing the annotate navbar into one menu

**Date:** 2026-09-21
**Status:** approved design, ready for an implementation plan

## The problem

The bar carries twelve controls. The comment above `SETTINGS`
(`skills/annotate/static/script.js:845`, the spec itself at `:861`) tells the
story of how it got there: four
preferences that each used to be their own header control were folded into one
gear, and that took the bar "down from twelve controls to nine". It is back at
twelve, and the folding stopped one level too early.

Counted left to right as it ships today: a search field 220px wide, a gear, a
review counter, a highlighter, a highlight eraser, a full-screen button, a
whole-response composer, a legend, a read-only badge, Share, Done — plus a
`Watching` pill on the left. Four separators divide them into groups whose
boundaries nobody can name. Every one of these was defensible on its own, which
is exactly how a bar reaches twelve.

Almost none of them is a thing a reader touches twice. The bar is the first
thing on the page and it is mostly storage.

## What the bar becomes

Left: emoji, title, resp id. Right: a magnifier, a menu icon carrying a status
dot, and `Done`. Everything else lives in the menu.

One conditional escape, and only one: `#highlighter-toggle` stays in the bar,
invisible unless armed. The highlighter is a **mode** — it changes what
dragging over text does — and a mode with no indicator is a bug, not a
simplification. `highlighter.js:268` already maintains `aria-pressed` on that
button, and `:289` already sets `hidden` when the browser has no Highlight API,
so a single stylesheet rule buys the whole behaviour:

```css
#highlighter-toggle:not([aria-pressed="true"]) { display: none; }
```

No JavaScript changes. Arming from the menu makes the button appear; clicking
it in the bar disarms it and it vanishes again. `#highlighter-clear` does not
get this escape — clearing is a command, not a mode, and it lives in the menu.

All four `.header-sep` spans go. There is nothing left to separate.

## Decisions taken

1. **The menu is markup plus a thin controller. The behaviour modules keep
   their elements.** This is the decision the whole plan rests on. Every other
   file that owns a header control finds it by `getElementById`; moving that
   element into the menu's DOM changes nothing those files can observe. So
   `#export-btn`, `#fullscreen-toggle`, `#composer-toggle`,
   `#highlighter-clear`, `#settings-groups`, `#palette-pop` and
   `#settings-reset` **move**, they are not reimplemented, and `export.js`,
   `fullscreen.js`, `highlighter.js` and `wireViewControls` keep working
   against them.

2. **`#menu-pop` joins the existing panel machinery rather than adding its
   own.** `initTopPanels` (`script.js:2566`) already gives every panel in its
   array Esc-to-close with focus restoration, click-outside dismissal behind a
   per-panel opt-in flag, one-panel-open-at-a-time, and correct `aria-expanded`
   bookkeeping. The menu is one more entry in that array with
   `dismissOnOutsideClick: true`. The array shrinks on net: `#settings-toggle`
   and `#resume-toggle` leave it.

3. **Panes, not a second popover.** The panel holds three panes — root,
   settings, help — swapped by a `data-pane` attribute on `#menu-pop`, with a
   back button on the two children. Opening the menu always resets to root, so
   the menu never remembers where you were last time. Settings nested inside
   the menu was the ask; a settings popover that opens *next to* a menu
   popover would be two overlapping overlays with two lit toggles.

4. **The watcher signal splits in two, and the pill is deleted.** The dot on
   the menu icon carries live / stale / unknown. The status block at the top of
   the root pane carries the sentence: what "watching" means, and how long ago
   the session was last seen. The pill said `Watching` and had room for nothing
   else.

5. **The status block absorbs `#resume-pop` entirely.** The resume command and
   its copy button currently live in their own popover behind their own header
   button, shown only when a session could be attached. It is the same subject
   as the dot — whether anything is listening — so it renders inside the status
   block when nothing is attached, and `#resume-toggle` is deleted.
   `entry.js:266-320` rewires from `#watcher-badge` to the dot and the block;
   `makeWatcherBadgeClickable` becomes unnecessary, because the command is no
   longer hidden behind a click.

6. **The read-only badge moves into the status block.** It describes what the
   page *is*, which is what that block is for. It is the only thing in the menu
   that is not a control.

7. **Review progress is deleted, not relocated.** Both halves: the `0/21` pill
   with its jump-to-next-unmarked click, and the per-block `✓` after the title
   of a block already dealt with. Annotate is not a progress tracker, and a
   counter invites completion for its own sake. A block's own mark badge still
   shows what you chose — that is per-block state, not a score.

8. **All new CSS goes in `style.css`, never `core.css`.** Annotate's
   `skills/annotate/static/core.css` is a deliberately diverged copy of
   `skills/_shared/web_companion/static/core.css`, and its own header block
   lists the three divergences and says not to re-sync. `skills/deck` holds a
   third copy. Adding menu rules to annotate's copy would widen that divergence
   for a feature only annotate has. This change therefore only **removes**
   annotate-only rules from `core.css` and adds nothing to it. No other skill's
   header moves.

9. **Search opens on click or `/`, and closes on Esc or on an outside click
   with an empty query.** An outside click while a query is live does not
   close it: the document underneath is filtered, and collapsing the field
   would hide the reason. `search.js:170` already handles Esc against the
   input.

10. **The menu gets no keyboard shortcut, and Share is now two clicks.** Every
    letter worth having is taken (`j` `k` `c` `f` `g` `/`), and the menu holds
    nothing urgent. Share's second click is the price of the bar, paid
    knowingly.

## The menu's contents

Root pane, in order:

| Row | Element | Owner today |
|---|---|---|
| Status: dot, state, last-seen, resume command, read-only note | new markup | `entry.js:266-320`, `#resume-pop` |
| Comment on the whole response — `G` | `#composer-toggle` | `initTopPanels` |
| Reading highlighter — on/off | **proxy** for `#highlighter-toggle` | `highlighter.js` |
| Clear every highlight | `#highlighter-clear` | `highlighter.js` |
| Full screen | `#fullscreen-toggle` | `fullscreen.js` |
| Settings › | pane switch | — |
| Share a copy… | `#export-btn` | `export.js` |
| Buttons & keyboard › | pane switch | — |

The highlighter row is the one proxy in the table, and it is a proxy precisely
because its element is the one that must stay in the bar. It clicks
`#highlighter-toggle` and mirrors that button's `aria-pressed` back as its own
on/off label, so `highlighter.js` remains the only owner of the state.

Settings pane: `#settings-groups`, `#set-group-highlight` and `#settings-reset`
moved verbatim, keeping `wireViewControls` (`script.js:955`) and highlighter.js's
`#palette-pop` handlers intact.

Help pane: the legend's 3-column table (`Button` / `What it tells Claude` /
`What happens to the content`) becomes a stacked list — icon and name, then the
two lines beneath — because 288px will not hold three columns. The keyboard
table stays a 2-column table; it fits.

## Two modules overwrite their button's whole contents

Both would wipe the icon out of a menu row, and both take a one-line fix that
falls back to today's behaviour when the labelled span is absent:

- `export.js:323` — `btn.textContent = "Preparing…"`, then `"Saved ✓"`,
  `"Failed"`, and back to the captured original.
- `fullscreen.js:33` — `btn.innerHTML = on ? ICON_EXIT : ICON_ENTER`.

These are the only two places where a module writes *through* an element it
owns rather than to an attribute on it, which is why they are the only two
files outside the shell that this change forces.

## Deletions

| Gone | Where |
|---|---|
| `#review-progress` button | `shell.js:55` |
| `.review-progress` rules | `style.css:393-414` |
| `initReviewProgress` | `script.js:2679` |
| `data-review-state` and the `✓` rule | `script.js:2693`, `style.css:426` |
| `#watcher-badge` and `.watcher-badge*` | `shell.js:17`, `core.css:805-823` |
| `#resume-toggle`, `#resume-pop`, `.resume-pop` | `shell.js:45-52`, `style.css:1830` |
| `#settings-toggle` and `#legend-toggle` buttons | `shell.js:25`, `shell.js:71` |
| `.header-sep` spans in annotate's bar | `shell.js`, all four occurrences |

`.export-btn` loses its bar styling and becomes a menu row; `.done-btn` is
untouched.

## Tests

`shell.js`'s markup is asserted against by roughly a dozen modules through the
one decoder in `tests/shell_source.py`, which is what makes a change of this
size tractable at all. The suites that must move with it:

- `test_smoke_shell_source.py:62` — the control inventory, which names
  `review-progress` explicitly.
- `test_smoke_review_ergonomics.py:126-133` — asserts both the pill and the
  `✓` rule exist. Both assertions invert: they become guards that the feature
  is gone, so it cannot be reintroduced by habit.
- `test_browser_review.py:178-185` — drives the counter and reads
  `data-review-state` in a real browser.
- `test_smoke_settings_panel.py` — reads `core.css` and both stylesheets to
  check every setting has a rule to land on. The settings markup moves but
  does not change, so this should pass untouched; if it does not, the move was
  not verbatim.
- `test_smoke_top_panels.py` — the panel machinery, which gains an entry.

New coverage, at the level the existing suites work at:

1. The bar holds exactly search, menu, `Done` and the hidden highlighter —
   asserted against `shell_html()`, so the inventory cannot quietly grow back.
2. `#highlighter-toggle` has a rule hiding it unless `aria-pressed="true"`.
3. Every ID the behaviour modules look up still exists somewhere in the shell.
   This is the test that protects decision 1, and it is worth writing as a
   list derived from grepping `getElementById` across `static/*.js` rather
   than as a hand-maintained constant.
4. A browser test that opens the menu, pushes the settings pane, and comes
   back — the pane switch is the only genuinely new interaction.

Per `docs`-adjacent house practice and the memory note behind it: the browser
tests are the ones that matter here, because three CSS defects in this page's
history passed every source-level test and were caught only by computed styles
and rects.

## Risks

- **The menu grows back.** This design removes nine controls from a bar that
  had already been cut once. The menu inherits the same pressure the bar had.
  Test 1 above is the only real defence, and it is deliberately an inventory
  assertion rather than a count.
- **`entry.js`'s watcher polling is the least test-covered thing being
  rewired.** It has no browser test today. Adding one is in scope.
- **The working tree is not clean.** `skills/annotate/explain.py` and
  `skills/annotate/tests/test_explain.py` carry uncommitted edits that arrived
  during the design session and belong to something else. Implementation must
  start from a committed tree, or acceptance will be measured against changes
  nobody in this plan made.
