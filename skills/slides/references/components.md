# The slide vocabulary

Every class here is defined in the shared framework — `framework/deck.css` in this skill, which each deck carries as an inlined snapshot of the version it was created with — unless
the entry says otherwise. Reach for one of these before inventing a class. If nothing
fits, add a **new `<style>` block** in the deck itself for the new component; never edit
`framework/` for something only one deck needs — see SKILL.md for when a component has
proven itself enough to promote.

Coordinates matter, because slides are absolutely positioned on a fixed canvas:

| | Value | Why |
|---|---|---|
| Canvas | 1280 × 720 logical px | 16:9; `overflow:hidden` |
| Left / right margin | `67px` | almost every content component pins to it |
| Cover margin | `82–86px` | the cover sits inside the 18px accent `.bar` |
| Divider margin | `83–90px` | its own scale |

---

## Slide shells

### `.slide` — the canvas
```html
<section class="slide" id="sec-name"><span class="num">2</span>
  … content …
</section>
```
`id` is only needed on slides the cover TOC or the floatnav jumps to. `.num` is a
gutter marker at `left:-46px` — **outside** the canvas, so it never counts as overflow.
Its text is rewritten by the harness script, so whatever you type in it is ignored.

### `.slide.tslide` — the cover
Dark slide, one per deck, always slide 1.
```html
<section class="slide tslide"><span class="num">1</span>
  <div class="bar"></div>                    <!-- 18px accent spine, left edge -->
  <div class="wmk"><!-- theme:logo --><!-- /theme:logo --></div>  <!-- the theme's logo.svg, top right -->
  <div style="…left:86px;top:150px…">AUDIENCE · YYYY-MM-DD</div>
  <div style="…left:82px;top:200px…">Title —<br>second line</div>
  <div style="…left:86px;top:330px…">One sentence of subtitle.</div>
  <div class="home-toc" style="position:absolute;left:84px;top:404px;right:84px">
    <a href="#sec-one"><span class="n">01</span> First section</a>
  </div>
</section>
```
The cover's three text lines are **inline-styled on purpose** — they are the one place
per deck where the type scale is tuned by hand, so they have no classes. Copy the
skeleton's values and change the words.

`.home-toc` is optional; it is a wrapping row of dark pill links, one per section. Only use it when the deck has sections
worth jumping to.

### `.slide.divider` — section break
Dark slide with a giant ghost numeral or glyph bleeding off the top-right.
```html
<section class="slide divider" id="sec-questions"><span class="num">3</span>
  <div class="ghost">?</div>              <!-- 430px, var(--dark-ghost), decorative -->
  <div class="dkick">2 · THE FRAMEWORK</div>
  <div class="dname">Four categories</div>
  <div class="drule"></div>               <!-- 64x9 accent bar -->
  <div class="dtag">Usage &amp; capacity · Automation · Landscape · Controlled context</div>
</section>
```
All five children are fully positioned by the stylesheet — no inline styles needed. Many decks skip dividers and let `.kick` carry the section label instead; both are fine.

---

## Header scaffolding

Three absolutely-positioned lines, in this order, on nearly every content slide:

| Class | Position | Role |
|---|---|---|
| `.kick` | `left:67 top:50` | accent 13px tracked-out label — `01 · ONBOARDING · THE NEW FLOW` |
| `.title` | `left:67 top:84` | heading face (`--head`), bold 40px — the sentence the slide is making |
| `.lead` | `left:67 right:67`, **you set `top`** | 18px muted paragraph under the title, usually `style="top:142px"` |

`.lead` has no `top` in the stylesheet, so it collapses to `top:0` if you forget one.

`.chd` is the alternative header — a card strip with a bottom accent rule, used when the
slide is *about* a tracked item rather than about an idea. See the tree section below.

---

## Body components

### `ul.introb` — the default bullet list
The workhorse. Accent dot, big type, optional grey sub-line.
```html
<ul class="introb compact" style="top:180px">
  <li><b>The claim.</b><span class="sub">The evidence, one or two sentences.</span></li>
</ul>
```
- `top` is **required inline** — the stylesheet sets only `left`/`right`.
- `.compact` drops 23px → 21px and 28px → 20px spacing. Use it past three bullets.
- `.sub` is the grey second line; it is `display:block`, so it must be a `<span>` inside
  the `<li>`, not a sibling.
- Four bullets is the practical ceiling at `.compact` starting at `top:180px`.
- Occasionally overridden to a narrower measure: `style="top:180px;width:1000px;right:auto"`.

### `.grail` — numbered guardrail rows
A flex column of numbered rows, where the number is the point. Each row's numeral takes
its colour from its position: 1 accent, 2 settled, 3 neutral, 4 wrong — so **it only works up
to four rows**; a fifth gets no colour.
```html
<div class="grail" style="top:206px;gap:26px">
  <div class="gr">
    <div class="n">1</div>
    <div>
      <div class="tt">Nothing ships without a review</div>
      <div class="ds">What it means. <span class="faint ital">&larr; category it maps to</span></div>
    </div>
  </div>
</div>
```
The `.gr` grid is `62px | 1fr`, so the second child must be a single wrapper `<div>`
holding `.tt` and `.ds`.

### `.ctxp` — comparison panels
Two side-by-side cards for before/after or us/them. A coloured 7px cap, a name, a
subtitle, and a ticked or questioned list.
```html
<div class="ctxp" style="left:67px;top:216px;width:545px">
  <div class="top" style="background:var(--settled)"></div>
  <div class="body">
    <div class="nm">After</div>
    <div class="stt">Same setting, one screen</div>
    <ul>
      <li class="y">Good thing.<span class="sub">Why.</span></li>
      <li class="q">Open question?</li>
      <li class="n">Bad thing.</li>
    </ul>
  </div>
</div>
```
- Markers: `.y` → settled ✓, `.q` → accent ?, `.n` → wrong ✗.
- The stylesheet defaults to `top:250px;width:545px`; override both inline.
  Two panels at `left:67px` and `left:668px`, `width:545px` fill the canvas exactly.
- **Subtitle gotcha, verified against framework v1.6.0.** `deck.css` defines
  `.ctxp .st{font-size:13px;color:var(--faint);font-style:italic;margin-bottom:14px}` —
  but that only overrides those four properties. The global tree-pill rule, bare
  `.st{flex:none;font-weight:bold;padding:3px 11px;min-width:88px;text-align:center;
  white-space:nowrap}`, still applies everything it sets that `.ctxp .st` doesn't
  redeclare (a `.ctxp` subtitle using `.st` renders bold, centered and padded instead of a plain italic line). **`.stt` is
  not defined anywhere in `deck.css`** — despite this file's older advice to use it,
  that class carries no styling at all. Give a `.ctxp` subtitle its own deck-local class
  instead (e.g. `.ctxsub`), with its own rule replicating `.ctxp .st`'s four properties
  plus `font-weight:normal;text-align:left` to actually clear the pill's bleed-through.
- A `.ctxp li .sub` second line is not in the shared framework. Add them fresh in your own
  `<style>` block if a deck actually needs them.

### `.expanel` — evidence panel
A panel with a neutral left border and a tracked-out mono heading, meant to be pinned
beside other content as the supporting evidence.
```html
<div class="expanel warm" style="left:700px;top:220px;width:500px">
  <div class="eh">WHAT WE MEASURED</div>
  <ul><li><b>Claim.</b> Detail.</li></ul>
</div>
```
`.warm` swaps neutral for accent. **This is in the shared stylesheet but no current deck
uses it** — the markup above is read off the selectors, not copied from a live slide.
Position it entirely inline; the stylesheet sets no coordinates.

### `.bigq` + `ul.asks` — question slides
`.bigq` is a large heading-face italic question pinned at `top:170px`, with `<b>` rendering
upright and in the accent colour for the phrase that matters. `ul.asks` is a list whose marker is an accent `?` instead of a dot, with the same `.sub` second line as `.introb`, and needs an
inline `top`. Like `.expanel`, both are **in the stylesheet but unused in every current
deck** — treat them as available, not as an established pattern.

### `.dtake` — the takeaway line
One centred heading-face italic sentence pinned at `bottom:46px`. It is the "so what" of the
slide, not a footer.
```html
<div class="dtake">Ship the smaller change first.</div>
```

### `.card` / `.pad` — the generic container
`.card` is an absolutely-positioned panel (`var(--panel)`, soft shadow); `.card.warm`
uses the warmer `--panel2`. `.pad` adds `22px 26px` of padding, `h3.ch` is a heading-face card
heading. Everything else — coordinates, size — is yours to set inline. Use it when no
named component fits and the thing is genuinely a one-off.

Utility classes that go with it: `.mono`, `.muted`, `.faint`, `.ital`, `.ctr`.

---

## Step, table, panel, footer, tree

All in the shared framework since v1.1.0 — no per-deck copying needed for any of these.

### `.flow` — a step chain
Equal-width steps separated by arrows, across the full width.
```html
<div class="flow" style="top:296px">
  <div class="fs">
    <div class="fn">STEP 1</div>                <!-- mono, accent, tracked out -->
    <div class="ft">The user saves the form</div>
    <div class="fd">What actually happens, in two sentences.</div>
  </div>
  <div class="arw">&rarr;</div>
  <div class="fs term">…</div>                   <!-- .term = peach, the end state -->
</div>
```
`top` is required inline. Three steps and four steps both work; five is too many at this
type size.

### `.stab` — status table
A two-column table of a status value and what it means, `672px` wide so a `.rails` panel
fits beside it.
```html
<div class="stab" style="top:202px">
  <div class="sr">
    <span class="sv err">ERROR</span>
    <span class="sd">The bank would reject this today.<em>What it does anyway.</em></span>
  </div>
</div>
```
Value chips: `.ok` grey, `.info` blue, `.warn` amber, `.err` pink. The `<em>` inside
`.sd` is not italic — it is restyled as the grey second line.

**`.stab` is not a table.** It is a two-column status list. For an actual multi-column
table with a header row, use `.dtable` below.

### `.dtable` — a real data table

**Requires framework v1.6.0 or newer** — check the snapshot comment in the deck.

```html
<div class="dtable compact" style="top:158px">
  <div class="cap">MEASURED, NOT ESTIMATED <span>&mdash; both runs on 25 August</span></div>
  <table>
    <thead><tr><th style="width:360px"></th><th style="width:330px">WIKI</th><th>CODE</th></tr></thead>
    <tr><td>Time to an answer</td><td class="ok">49 seconds</td>
        <td class="no">4 min 10 s <span class="note">&mdash; 5&times;</span></td></tr>
    <tr><td>Why does it work this way</td><td class="ok">Answered</td>
        <td class="no">Not in the source<span class="sub">git history gives the order, never the reason</span></td></tr>
  </table>
</div>
```

- `top` is **required inline**; the stylesheet sets only `left`/`right`.
- **The first column is the label column and styles itself** from `td:first-child` —
  mono, 13px, muted. Put no class on it.
- **Never write `<td class="k">`.** `.k` is the alignment tree's ticket-key chip and
  carries `border:1px solid`, which paints stray vertical rules straight through the
  table; the framework zeroes `th`/`td`
  borders explicitly so nothing else leaks in either.
- Cell classes: `.ok` settled bold, `.no` wrong bold, `.hi` settled bold on a pale green
  wash (for the cell that changed). Inside a cell, `.sub` is a grey second line and
  `.note` is de-emphasised trailing text on the same line.
- Modifiers: `.compact` for denser rows (use it past six rows on a slide that also has
  a `.strip`), `.zebra` to swap the row hairlines for striping.
- The header rule is 2px accent, matching `.chd`.

### `.rails` — the side panel
A settled-coloured panel pinned to `right:67px`, `404px` wide, for the two or three
decisions that frame whatever is on the left. Same `li` + `.sub` shape as `.expanel`,
bold first line. `top` required inline. `.stab` + `.rails` at the same `top` is the
intended pairing.

**Near-duplicate of `.expanel`, not yet resolved.** Both are a bordered panel with an
eyebrow heading and a bullet list; `.rails` is settled/bold-first-line, `.expanel` is neutral-or-accent/plain. Two components doing one job is exactly the drift this framework
exists to avoid — worth consolidating once a second use case shows which shape actually
wins, not guessed at now.

### `.strip` — the footer band
A full-width `--panel2` band pinned at `bottom:36px` that carries the one fact the slide
should leave behind.
```html
<div class="strip"><b>WHERE IT STANDS</b>Prose, with <span class="mono">config.keys</span> in mono.</div>
```
The `<b>` is not bold text — it is restyled into a tracked-out accent eyebrow on its own
line. **A `.strip` changes the layout arithmetic**: the usable band for content ends
around `y=640`, not 720. See the layout discipline section of SKILL.md.

`.demo` is its own dashed-border variant of the same idea, used to mark a live-demo slot.

---

## Jump nav — `.floatnav` (framework 1.7.1)

The left-edge `☰ JUMP` tab the skeleton ships. Hidden in present mode and in print.

## Progressive reveal — `.frag` (framework 1.7.0)

Add `class="frag"` to anything that should appear on a keypress rather than with the slide.
While presenting, `→` / `Space` / `PageDown` reveals the next step before moving on, and
`←` / `PageUp` hides it again; stepping back into a slide shows it fully revealed.

- **Order:** `data-frag="1"`, `"2"`, … Elements with the same number appear together — the
  callout on a screenshot and its line in the legend. Without `data-frag`, each `.frag` is its
  own step in document order.
- **Current step:** the latest step also carries `.frag-current`, a hook for dimming earlier
  steps deck-locally. The framework does not style it.
- **Only in present mode.** The scrolling view, the `/deck` editor and the PDF export show every
  fragment, so a reader of the file or the PDF never misses one.

```html
<div class="hl frag" data-frag="1">…</div>
<ol class="leg"><li class="frag" data-frag="1">…</li></ol>
```

## The alignment tree

Renders an issue tree (an epic and its children, say) as flat rows, which is what makes it fit on a
slide.

```html
<div class="chd">
  <span class="ck">ABC-123</span>                     <!-- mono card key -->
  <span class="cn">New onboarding flow</span><!-- heading-face card name -->
  <span class="pill">In progress</span>                 <!-- green status -->
  <span class="rel">v2.4</span>                       <!-- blue release -->
  <span class="cl">Acme</span>                       <!-- client, pushed right -->
</div>

<div class="tree">
  <div class="tr epic">
    <span class="lbl">
      <span class="ind">└&nbsp;</span>                  <!-- &nbsp; per depth level -->
      <span class="k">ABC-124</span>  <!-- a theme may colour it per project: .k.<project> -->
      <span class="txt">New onboarding flow</span>
      <span class="ep">epic · 3</span>
    </span>
    <span class="cmps">
      <span class="cmp">Frontend</span>  <!-- a theme may colour it per component: .cmp.<name> -->
      <span class="cmp">Backend</span>
    </span>
    <span class="st note">3 to do</span>
  </div>
</div>
```

| Class | Role |
|---|---|
| `.chd` | card header strip at `top:118px`, accent bottom rule; pairs with `.tree` at `top:186px` |
| `.tree` | the container; `left:67 right:67 top:186` |
| `.tr` | one row — a `1fr auto auto` grid, so **each row needs exactly three children**; an empty `<span></span>` where there are no components |
| `.tr.epic` | bolds `.txt` |
| `.lbl` `.ind` `.txt` | the left cell: indent glyph, key, title. `.txt` ellipsises — long titles truncate rather than wrap |
| `.k` | the ticket-key chip; a theme can colour it per project with `.k.<project>` |
| `.ep` | `epic · N` child count |
| `.cmp` | dashed component chip; a theme can colour it per component with `.cmp.<name>` |
| `.st.done` / `.wip` / `.todo` / `.note` | the status pill. `.note` is not a pill — it is faint heading-face italic, for a roll-up like `1 in review · 1 in progress` |

Rows are `padding:7px 0` plus a hairline, so roughly 34px each. Seven rows under a `.chd`
leaves the bottom third of the slide empty — which the audit reports and which is fine,
because a tree slide has nothing pinned at the bottom.

---

## Theme components

A theme can bring components of its own — per-project `.k.<project>` chips, per-component
`.cmp.<name>` colours, a brand-specific slide shell — as rules in its `theme.css`. When the
theme directory has a `README.md`, read it before writing slides: it documents what that
theme adds on top of this file.
