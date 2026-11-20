---
name: spotlight
description: Explain a user interface part by part, as one self-contained HTML page. The real screen sits on the left with everything dimmed except the part being explained; on the right a dashed line joins it to a claim, two or three lines, and optional fact cards and examples; Previous, Next, dots and the arrow keys walk the parts. This is the first choice whenever a presentation, walkthrough, help page or guide is about what a screen, field, dialog, panel or flow shows and how to use it; /slides and /deck send UI explanations here. Triggered by /spotlight <topic or spec>, or by any request to present, walk through or explain screens.
argument-hint: "<topic, or the path to a spotlight.json>"
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
---

# /spotlight — a screen, explained one part at a time

**Reach for this first whenever the subject is a user interface.** "Make a presentation about
what changed in Jira", "walk the team through the new field", "a help page for this tab", "show
how to use the dialog": each of those is a spotlight, not a slide deck. The reader sees the real
screen, the part in focus is lit and everything else is dimmed, and the text beside it says what
that part is and what to do with it. A deck (`/slides`) is for a talk that argues something —
a proposal, numbers, a decision — where the screens, if any, are evidence rather than the subject.
When a request mixes the two, build the spotlight for the screens and leave the argument to the
deck; never squeeze screenshots into 1280×720 slides with numbered badges and a legend.

## What a reader gets

- One screen at a time, left. Everything is dimmed except the part (or parts) in focus, which
  are ringed. The screen is either a **screenshot** with boxes in its own pixels, or **live HTML**
  (a copy of the real element) whose parts are found by CSS selector.
- The explanation, right: `N / M`, the screen's chip, the claim as a heading, two or three short
  lines, then optional **facts** (a number or word in large type with one line under it) and
  **examples** (a state drawn as the page draws it, what it means, where it was seen).
- A dashed line from the part in focus to the heading.
- A thin progress bar in the top bar, Previous / Next, one dot per part (a gap between screens),
  `←` `→` `Home` `End`, and `#part-N` deep links.
- Under 900 px it stacks, the line goes, and the bar sticks to the bottom; under 560 px the dots
  go too. Light only, Inter / Space Grotesk / JetBrains Mono.

## Files

| File | Role |
|---|---|
| `template.html` | The viewer. Every spotlight uses it unchanged; a look that should change for every future spotlight changes here. |
| `build.py` | `python3 build.py <folder>/spotlight.json` writes the page with every image embedded. A spec with `crop` needs Pillow: `uv run --with pillow python build.py …`. It refuses a box that leaves its image, a step without a title, a box on an HTML screen and a focus on an image screen. |
| `check.py` | `uv run --with playwright python check.py <page>.html <review-dir>` walks every part at 1440×900 and 390×844: sideways scroll, a part that rings nothing, a ring outside its screen, a missing line on desktop, text taller than its panel. It writes `desktop-NN.png` and `phone-NN.png`, one per part: look at them, and use them where the HTML cannot go (a Confluence page). |

Run both from `$(claude-annotate root)/skills/spotlight/`.

## The spec: `spotlight.json`

```json
{
  "tag": "Team · Tool",
  "title": "What the reader is about to understand, as a sentence",
  "link": "https://… (optional: the title links here)",
  "out": "my-spotlight.html",
  "footer": "Where the screens come from, shown under each screen",
  "css": "stage.css (optional: styles for HTML screens)",
  "theme": "evooq (optional: defaults to the slides config's theme; its spotlight.css restyles the page)",
  "screens": [
    {
      "id": "create",
      "label": "Create",
      "phase": "today",
      "image": "assets/create.png",
      "crop": [300, 0, 840, 900],
      "source": "Create dialog",
      "steps": [
        {"title": "A claim, with a verb", "text": ["One or two short sentences."],
         "facts": [{"big": "5", "small": "spaces"}]},
        {"box": [999, 8, 91, 32], "title": "Press Create", "text": "The usual button."},
        {"boxes": [[58, 240, 292, 145], [58, 400, 292, 172]], "title": "Two parts at once"}
      ]
    },
    {
      "id": "panel",
      "label": "The panel",
      "html_file": "assets/panel.html",
      "steps": [
        {"focus": "[data-row=sandbox]", "title": "…", "text": "…",
         "examples": [{"draw": "<code>dev</code>", "means": "What this state means.", "seen": "TICKET-1 · 11 Nov"}]}
      ]
    }
  ]
}
```

- A screen has `image` (PNG or JPEG, relative to the spec) or `html` / `html_file` (a fragment:
  a copy of the real element, with whatever attributes make its parts easy to select).
- `box` / `boxes` are `[x, y, width, height]` in the **full** image's pixels, also when the screen
  has a `crop`. Measure them on the image; never guess. `focus` is one selector or a list.
- `crop` cuts the part of a screenshot that matters, so it is drawn larger. A full 1440×900
  capture shrunk into the left column is too small to read: crop every screenshot to the
  region its steps talk about, with enough around it to place it.
- A step with no box and no focus shows the whole screen undimmed: use it for the opening part,
  which says what the reader is looking at.
- A screen's optional `title` is the claim the whole screen makes; it shows in bold above every
  part's heading on that screen.
- `phase` (`today` green, `design` amber, optional) marks a screen as the app as it is or as a
  proposed design; a design screen's chip says Design.
- `title`, `text`, `facts`, `examples` and `source` take inline HTML (`<code>`, `<em>`, `<b>`, a
  link). The spec's author is Claude; nothing from a reader goes in unescaped.
- A spec in the older feature-walkthrough shape (`ticket`, `ticket_url`, `summary`) builds as is:
  `ticket` becomes the tag, `ticket_url` the link, and the page is named after the ticket.

## Steps

1. **Decide the screens and the parts.** One screen per place the reader looks; two to four
   parts per screen, each about one thing on it, in the order the reader would use them. The
   first part of the first screen is the opening: what this is, with facts when there are
   numbers worth keeping.
2. **Capture.** Real screens with real data, never a mock-up passed off as the app. A screen the
   user's accounts are needed for is captured in their browser, in a tab you open and close;
   never sign in for them. Save at 1440×900, viewport only.
3. **Measure the boxes** on the image (in pixels: crop the image in your head, or open it), and
   pick each screen's `crop`.
4. **Build, then check, then look** at every `desktop-NN.png`: each ring on what its part
   names, the line reaching the heading, the text legible. Fix and rebuild until the check
   reports 0 faults and the PNGs look right.
5. **Share it** the way the user's instructions say (a share link, a replaced file at its old
   link). The `.html` is the master; it renders offline except for the web fonts, which fall
   back to the system's.

## On the stage and in a call

The same spec is also a stage board, drawn with the same spotlight (`skills/_shared/static/spotlight.js`, which
this page's build pastes in and the stage keeps a copy of):

- `python3 "$(claude-annotate root)/skills/stage/stage.py" show <name> screen:<path/spotlight.json>` puts it on the
  stage, Back and Next stepping through the parts; the images stay in the spec's folder.
- In a /talk call, `[[show screen: <path/spotlight.json> | Title]]` brings it in. The voice steps it: a part comes in
  with the sentence that says its title, and `[[point: part 3]]` or `[[point: part "title"]]` lights one. So write
  titles you will say aloud. The sentence being said stays at the foot of the stage; the panel keeps the part's text.
- The parts are numbered p1, p2, ... in the spec's order, across every screen.

## Writing

The house style of whoever the spotlight is for applies (a `house-style` skill, a decks folder's
`PRESENTATION-STYLE.md`): load it first. Beyond it:

- A part's title is the claim it makes, a sentence with a verb, and fits in two lines.
- Text is two or three short sentences. What does not fit is a second part, never a smaller font.
- Say what the reader does with the part ("Tick each box when…"), not how it was built.
- Every fact on a part is checked at its source in the same session; a claim about what someone
  said quotes them.
