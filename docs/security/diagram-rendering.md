# Rendering diagrams without handing the page to an author

**Date:** 2026-09-07
**Status:** Record of a decision. D2 was tried for `kind: "diagram"` and reverted.

## Why this document exists

On 2026-09-07 the `kind: "diagram"` renderer was moved from Mermaid to D2, for
layout reasons that were real and measured. Seven adversarial review rounds
each found a way for author-controlled markup to reach the page. The renderer
was reverted.

The value of that day is not in the diff, which is gone. It is in knowing
which approaches were tried, why each failed, and what the failures had in
common — so that the next person who wants better diagrams does not spend the
day rediscovering it.

## The setting, which is what makes this hard

A rendered diagram is not a picture in a sandbox. It goes to three places:

1. **Into the live page**, via `content.innerHTML` in `static/script.js`. The
   page also holds the user's document, other people's comments, and the
   page's own stylesheets.
2. **Into the daemon**, stored opaquely and served to every later reader.
3. **Into a standalone file**, via the Share button in `static/export.js`,
   which serialises the live DOM and inlines every stylesheet. That file is
   re-parsed by a fresh parser in a recipient's browser — so markup that is
   inert via `innerHTML` can execute there. A `<script>` element demonstrated
   exactly this.

The page has **no Content-Security-Policy**. There is nothing behind the
sanitizer.

## What Mermaid does, and why it was safe

`diagrams/mermaid.py` runs `mmdc` with `htmlLabels: false`, `securityLevel:
"strict"`, and strips `%%{init: …}%%` directives from the source so it cannot
re-enable either. The result contains no author HTML at all — labels are SVG
`<text>`. Its layout is poor past a dozen nodes, and its labels live in
`<foreignObject>` when HTML labels are on, which is why they are off.

**Formatted text inside a diagram box has never been a capability of this
tool.** Any proposal that frames losing it as a cost is mistaken.

## What D2 does differently

Everything D2 emits is pure SVG except one construct: a **block string**
(`|md| … |`, `|markdown| … |`, or an untagged `| … |`) renders its content as
Markdown, and CommonMark passes raw HTML through, into a `<foreignObject>`.

Empirically — across every shape, both layout engines, both themes, `--sketch`
and `--force-appendix` — **no other D2 construct emits a `foreignObject`.**
`|latex|`, `|tex|`, `shape: text`, `shape: code`, `shape: class`,
`shape: sql_table`, `icon:`, `tooltip:`, `link:`, `near:`, grids and sequence
diagrams were all checked and are clean.

So the entire attack surface was one feature we did not need.

## The seven rounds

Each fix was sound against what the previous round found. Each was broken by
the next.

| # | Guard | How it broke |
|---|---|---|
| 1 | Strip `<script>` from the SVG | Only `script` was copied from `sanitizeFreeHtml`'s tag denylist. `<iframe srcdoc>` gives same-origin, zero-click script execution; `<base href>` repoints the whole document. |
| 2 | Add the tag denylist, strip `on*` and `javascript:` | Deleting a span splices its neighbours: `<img src=q on src="javascript:z"error=alert(1)>` re-forms a live `onerror` *after* the handler rule ran. `/` is a legal attribute separator and the rules anchored on `\s+`. Chrome decodes `&#106;avascript:` before stripping control characters. |
| 3 | Replace the regexes with an `html.parser` allowlist | `style` was exempt so D2's own stylesheet survives — but an author `<style>` inside a `|md|` block is not scoped to the diagram. A `background-image` beacon fired; `body::before {position:fixed}` covered the viewport. |
| 4 | Drop `style` attributes and off-document URLs inside `foreignObject` | The rule named `src` and `href`. `srcset`, `poster` and `background` also fetch on render, and all three did. |
| 5 | Invert to an attribute allowlist inside `foreignObject` | The `foreignObject` depth counter is state, and `HTMLParser.parse_pi` ends a processing instruction at the first `>` while D2's XML checker ends it at `?>`. `<?x > </foreignObject> ?>` is one PI to D2 and a live end tag to Python: depth hits zero and the allowlist switches off. |
| 6 | Sanitize in the browser, walking the DOM Chrome actually built | Correct as far as it went — 57 payloads round-tripped through serialize-and-reparse with no mutation XSS. But the allowlist applied only *inside* `foreignObject`, on the assumption that everything outside is D2's own output. `</div></foreignObject>` puts the rest of the author's HTML outside it. |
| 7 | Refuse block strings in the source; strip `foreignObject` entirely | The source check has to predict D2's lexer. `_string_end` treats any quote as a string opener; D2 opens a string only at a value/key boundary. `a'b: |md '` passes the check, and D2 renders the block. |

## The pattern

Every guard rested on **predicting how some other parser behaves** —
Chrome's tokenizer, D2's XML well-formedness check, Python's `HTMLParser`,
D2's own lexer. Each prediction was right about the cases it was written for
and wrong somewhere else.

Two corollaries worth keeping:

- **A rule that reads document position is unsound across serialization.** Two
  MathML payloads were shown to relocate nodes when a sanitized tree is
  serialised and re-parsed — which the export path does on every share.
- **The sanitizer being sound "because the other component normalises its
  input" is not soundness.** Rounds 2, 5 and 7 were each saved for a while by
  D2 rejecting malformed input, and each time the rejection turned out to have
  an edge.

## If you want better diagrams later

Ranked by how much they actually change the problem.

1. **A sandboxed iframe.** This codebase already has the primitive:
   `kind: "mockup"` renders in a sandboxed iframe with the sanitizer lifted, precisely
   because arbitrary HTML is expected there. A diagram kind could do the same,
   and then author HTML would be a non-issue. Costs: iframe sizing, theme
   propagation, and deciding what the export does.
2. **A Content-Security-Policy on the page.** Would have stopped the beacons
   and the `@import` in rounds 3 through 7 outright, and is worth having
   regardless of what renders diagrams.
3. **D2 with block strings never authored and `foreignObject` stripped.** This
   is round 7. It failed on the source check, but the check is only needed
   because refusing is done by reading the source. If D2 ever gains a flag to
   disable markdown blocks, this becomes a one-line configuration rather than a
   parser prediction, and is then a good option.
4. **A vetted sanitizer library.** Not stdlib, which this plugin is, and it
   would still be sanitizing rather than isolating.

What is *not* on this list: another hand-written sanitizer. Seven attempts is
enough evidence.

## What was kept from the attempt

- **The ELK layout work** for `kind: "flowchart"`, which is unrelated to any of
  the above and shipped.
- **`flowchart.py`'s `_safe_href`.** A review found that a flowchart node's
  `href` reached the page unchecked, and flowchart SVG is deliberately injected
  without sanitization because it is generated from a validated spec. It now
  allows `http:`, `https:`, `mailto:`, `#fragment` and `jetbrains:` — the last
  two being the cross-block anchor and the jump-to-source link — and drops
  everything else.
- **`node` as a documented requirement**, in the README and in
  `/annotate-doctor`, since the ELK layout driver needs it.


**Update 2026-09-08:** `kind: "diagram"` was removed altogether, with `mermaid.py` and the
`mmdc` dependency. `flowchart` covers branching shapes; static structure goes to prose or a table.
