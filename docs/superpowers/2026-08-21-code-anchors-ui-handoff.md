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

**It works end to end.** 1076 Python tests, 17/17 browser e2e, dogfooded live. The remaining
work is UI polish, not correctness.

---

## 2. How to run things

```bash
# full python suite (from the repo root)
python3 -m pytest skills -q                       # expect 1076 passed

# the browser end-to-end (manual only — NOT in CI, by repo convention)
NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/code-anchors.e2e.cjs   # expect 17/17

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
| `skills/annotate/static/script.js` | `codeWideKey` :692 · `highlightCodeLine` :697 · `renderCodePane` :716 · `renderCodeColumn` :834 · `setDocumentCodeFlag` :853 |
| `skills/annotate/static/export.js` | `STRIP` list — controls removed from an exported file |
| `skills/annotate/tests/test_smoke_code_panes.py` | source-presence assertions on the CSS/JS |
| `skills/annotate/tests/e2e/code-anchors.e2e.cjs` | the 17 behavioural assertions |

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
| gutter | `#5f6773` | 4.61:1 AA | *accent* `#1e40af` 6.13:1 |
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
3. **`main.prose p` beats `.cp-note`.** (0,1,2) vs (0,1,0). The note's own padding silently
   did nothing and it inherited a 140px right gutter meant for prose hover buttons. Fixed by
   scoping under `.codepane`. Any new `<p>` inside the pane has the same problem.
4. **Server filesystem paths must not reach non-owners.** `data-repo-root` /
   `data-project-name` are gated on `_is_owner()`, and `.cp-jump` is in `export.js`'s STRIP.
   Decision 3 covers code excerpts reaching strangers; it does **not** cover
   `/Users/<name>/...`. Three separate leaks of this class were fixed here.
5. **Do not let the light theme leak.** `code-theme.css` (Tokyo Night **Dark**) still paints
   ordinary fenced code blocks elsewhere in annotate. Every light rule is scoped under
   `.codepane`. Verified: a fenced block still renders `#1a1b26`. Re-verify if you touch the
   token rules — a page-wide recolour is the failure mode.
6. **`highlightCodeLine` needs its length cap.** `text.length > 20000` → plain text. Without
   it, an anchor into a minified file hands `hljs.highlightAuto` a 100KB line and stalls the
   render synchronously. The pane caps line *count* (40), never line *length*.

---

## 7. Known UI issues — measured, not yet fixed

Numbers from the live dogfood page at 1440px viewport, 609px code column.

| Block | rows | chrome px | code px | chrome share |
|---|---|---|---|---|
| section-3 | 6 | **101** | 131 | **44%** |
| section-2 | 9 | 101 | 189 | 35% |
| section-7 (stale) | 0 | **101** | 0 | **100%** |
| section-5 | 7 | 68 | 150 | 31% |

1. **Chrome stacks up.** `.cp-head` (35px) + `.cp-note` (27px) + `.cp-status` (~39px when a
   pane is `moved`) = **101px above the first line of code**. On a six-line pane that is more
   chrome than content. Worth considering: fold the `moved` notice into the header line, or
   make the note and status share a row.
2. **A stale pane is 101px of pure chrome and zero code** — correct behaviourally (it must
   never show wrong code) but visually it is a tall empty box.
3. **Marginal horizontal overflow.** section-2 overflows by **15px**, section-3 by **8px**.
   A small gutter reduction would remove the scrollbar entirely in both. section-4 overflows
   by 1px — effectively a rounding artifact.
4. **Blank context lines consume full rows.** Lines 132/133 in section-2 are empty and each
   costs a 19px row of the 2-line context padding.
5. **The dogfood doc's anchors have drifted** — several now render `moved: authored at line
   123, now at line 134`, because the fix wave edited `anchors.py` underneath them. This is
   the drift machinery working correctly, and it is a useful live specimen of the `moved`
   state. Do not "fix" the anchors unless you want to lose that specimen.

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
