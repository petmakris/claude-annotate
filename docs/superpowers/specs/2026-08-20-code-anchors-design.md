# Code anchors — putting the source beside the explanation

**Date:** 2026-08-20
**Status:** approved design, ready for an implementation plan

## The problem

Annotate renders explanations well, and for software questions that is the
failure. The reader gets prose *about* code with the code nowhere on screen,
so every claim has to be taken on trust or chased manually in an editor. The
explanation is detached from the thing it explains.

The gap is not that a block *cannot* carry code — fenced code blocks render
today, syntax-highlighted, and `references/pushing.md` documents them. The gap
is that `SKILL.md`'s block-kind menu never asks for code, so a response about
code arrives without any. Half of this problem is layout; the other half is an
authoring rule. **A pane with no rule beside it would sit empty on most
pushes, and a rule with no pane would be unverifiable.** Both ship together or
neither is worth building.

## What already exists, and is being reused rather than reinvented

| Thing | Where | Why it matters here |
|---|---|---|
| Workspace stores its repo root | `dirs["_cwd"] = str(cwd)` — `skills/_shared/web_companion/server.py:250` | The server can read the real file; the anchor need not carry code text. |
| Anchor shape `{file, line, snippet}` | `skills/walkthrough/steps.py:10-12` | An anchor format already shipped in this repo. Extend it; do not invent a second one. |
| Source pane paired to a picture | `.pflow` — `skills/annotate/static/style.css:1428` | Establishes the visual language for "explanation beside its source", including that the pane is a **reading aid**, not a click target. |
| Per-block error pill | `sequence` / `flowchart` / `diagram` branches — `skills/annotate/server.py:823-912` | One malformed block must never blank the page. Anchors follow the same rule. |
| Jump-to-source href | `jetbrains://idea/navigate/reference?project=…&path=…:<line>` — `references/block-kinds/flowchart.md` | The IDE link form is settled; reuse it verbatim. |
| Export snapshots the live DOM | `skills/annotate/static/export.js:1-14` | Panes survive export and share for free — **provided** the code is inlined server-side, not fetched client-side. |

## Decisions taken

1. **Layout: split card that promotes.** Prose left, code right, inside one
   card; a pane can be promoted to full card width. (Chosen over a sticky
   right rail: a rail re-attaches prose to code only while that block is on
   screen, and a shared or exported page loses the pairing entirely.)
2. **The server reads the real file.** Blocks carry anchors, not code text.
   Cheap enough in tokens that anchoring generously is affordable, and the
   pane can never be stale relative to the working tree.
3. **The read-only share link serves panes too.** One render path, no owner
   branch on reads. A shared page that dropped its panes would be the
   detached document this whole design exists to eliminate. Accepted
   consequence: whoever holds the link reads those excerpts.
4. **The rule is written *and* its violations are visible.** `SKILL.md` gains
   the anchoring rule; a block that skips it in a code document renders a
   *no code cited* slot where its pane would be. A missing citation becomes
   something the reader can point at and comment on, not something they
   silently endure.
5. **The pane is a reading aid.** Comments arrive from the card header, as
   they already do for flowcharts — and for the same reason that rule was
   adopted there: a code line painted as a jump-to-source link that opens a
   comment box instead is a lie about what a click does.

## Data model

A new optional `code` field, valid on a block of **any** kind:

```json
{"id": "section-2",
 "title": "The workspace knows its repo",
 "markdown": "When a session is created…",
 "code": [
   {"file": "skills/_shared/web_companion/server.py",
    "line": 250,
    "end_line": 253,
    "snippet": "    dirs[\"_cwd\"] = str(cwd)",
    "note": "stamped once, at create time"}
 ]}
```

| Field | Required | Meaning |
|---|---|---|
| `file` | yes | Repo-relative path, resolved against the workspace's `_cwd`. |
| `line` | yes | The emphasised line — what the prose is actually about. |
| `end_line` | no | Last line of the window shown. Defaults to `line`. |
| `snippet` | yes | Verbatim text of `line`. The drift check; see below. |
| `note` | no | One short line rendered above the pane. Not a second explanation. |

**Constraints.**

- At most **3** anchors per block — past that the block is a tour, and the
  right answer is `/walkthrough`, not a taller card. A 4th anchor is a
  **push-time check failure**, not a silent drop: an anchor quietly discarded
  is a citation the reader never learns was meant to be there.
- `end_line`, when present, must be `>= line`; otherwise a check failure.
- A window over **40 lines** renders truncated at 40 with an explicit
  `… N more lines` marker. A pane you must scroll to read has stopped being
  a glance.
- `mockup` blocks take no anchors (a sandboxed iframe has nowhere to put a
  pane). An anchor on one is a check failure.

## Resolution — new module `skills/annotate/anchors.py`

Called from `_render_block_for_raw` (`skills/annotate/server.py:801`), whose
signature gains the repo root. `serve_data` already receives `dirs`, which
carries `_cwd`, so no plumbing beyond passing it down.

**Path confinement.** Join against `_cwd`, then `realpath`, then require the
result is still under `realpath(_cwd)`. This is the entire security story: an
anchor is model-authored, and without the check a block could name
`../../.ssh/id_rsa` and the page would print it to anyone holding the share
link. Symlinks are followed *before* the containment test, never after.

**Reading.** Read `line` through `end_line`, plus exactly **2 lines before and
2 lines after**, clamped to the file's bounds and rendered dimmed — enough to
see that a line sits inside a function without turning the pane into a file
viewer. Inline the resulting text into the block payload the client already
fetches. One code path then feeds the screen, the export, and the shared link
— there is no second renderer that could disagree.

**Drift.** The file changes under an anchor; line numbers do not survive
editing. On render:

1. If the text at `line`, stripped of leading and trailing whitespace, equals
   `snippet` stripped the same way — resolved. (Indentation changes are not
   drift; the line is the same line.)
2. Else search ±40 lines for a stripped match. On several matches, take the
   one **nearest** to the original `line`; on a tie, the earlier one. Found →
   render at the found line and label the pane **moved**, showing both the
   authored and the actual number.
3. Else → render a **stale** pill naming the file, the line and the snippet
   that no longer matches.

Never silently render whatever now sits at that line number. A pane showing
confidently wrong code is worse than a pane admitting it is lost, because the
reader has no way to tell.

**Failure is a pill, never an exception.** Every failure mode — missing file,
escape attempt, unreadable bytes, drift — renders a visible marker in the
block. This matches the existing `sequence`/`flowchart`/`diagram` branches:
one malformed block must never crash `/raw` and blank the page.

## The push-time check

A render-time pill tells the *reader* an anchor is broken. It does not tell
the author, who has already ended their turn. So the skill runs an anchor
check after writing `blocks.json` and **before announcing the URL**:

- every anchor resolves, stays inside `_cwd`, and its `snippet` matches;
- failures print with block id, file and line;
- the author fixes and re-writes before the user ever sees the page.

This is the difference between a rule that is followed and a rule that is
merely stated: the check makes a violation fail where it can still be fixed.

## Versioning — a trap that must be closed

`versions.py:63` computes a block's hash from `kind` plus **either**
`markdown` **or** `spec`, and nothing else:

```python
if kind in _SPEC_KINDS:
    body = _canonical_spec(blk.get("spec") or {})
else:
    body = _normalize_markdown(blk.get("markdown") or "")
```

Left alone, editing a block's anchors would not change its hash. The version
chain would not grow, the client would never refetch, and the corrected pane
would not appear — a silent no-op that looks exactly like a bug in the pane.

**`_block_hash` must fold the canonical `code` field into the digest for every
kind**, using the same `_canonical_spec` sorted-key serialization so cosmetic
key reordering does not churn versions. A test must fail without this change.

## Layout

**Anchored block.** `.card-body` becomes a two-column grid, 46% prose / 54%
code, the code column on `--surface-soft` with a hairline divider. Multiple
anchors stack in the code column in source order.

**Promotion.** Each pane carries a `widen` control that promotes it to the
card's full width, prose moving above it. Persisted per `(sid, block_id)` in
`localStorage`, because a promotion you have to redo on every reload is worse
than not having it. Export freezes whatever state the document is in.

**Unanchored block in a code document.** Full-width prose plus a small
*no code cited* slot where the pane would be. This is the visible half of the
rule. A document with no anchors at all is not a code document and renders
exactly as annotate does today.

**Column width.** `--content-max` goes from `1040px` to `1180px` **only** when
the document carries at least one anchor. Ordinary annotate pages are
untouched — nobody's prose-only document gets wider because this feature
exists.

**Pane chrome.** A header carrying `file:line`, Tokyo Night body matching the
existing fenced-code card, line numbers, the anchor line emphasised, and a
`jetbrains://` jump link in the header. Nothing inside the pane is a click
target.

## The authoring rule

`SKILL.md`'s block-kind menu gains:

> A block that asserts something about specific code carries a `code` anchor
> to that code. Prose describing a file, function, branch or line without an
> anchor is the failure mode this field exists to fix.

The contract — field shapes, limits, drift semantics, worked examples — lives
in a new `references/code-anchors.md`, loaded only when anchors are being
written, consistent with the progressive-disclosure structure the skill
already uses for block kinds. `references/pushing.md` gains a pointer.

## Testing

| Test | Kind | Guards |
|---|---|---|
| Anchor outside `_cwd` is refused | python | The security boundary. Includes a symlink escaping the root. |
| Missing file / bad line renders a pill, `/raw` still returns 200 | python | One bad block cannot blank the page. |
| Drift: snippet moved → pane renders at the new line, marked moved | python | The reason `snippet` exists. |
| Drift: snippet gone → stale pill, never wrong code | python | The failure that must not be silent. |
| Changing only `code` bumps the block version | python | The `versions.py` trap above. Must fail before the fix. |
| Anchor cap and window truncation | python | Limits are enforced, not documented-only. |
| Split card renders; `widen` promotes and persists | e2e `.cjs` | The layout. |
| Export contains the pane's code text | e2e `.cjs` | The share/export path really is free. |

## Files

**New**
- `skills/annotate/anchors.py` — resolve, confine, read, drift
- `skills/annotate/references/code-anchors.md` — the authoring contract
- tests per the table above

**Changed**
- `skills/annotate/server.py` — `_render_block_for_raw` takes the repo root and resolves anchors
- `skills/annotate/versions.py` — `_block_hash` folds in `code`
- `skills/annotate/static/style.css` — split card, pane, promotion, conditional width
- `skills/annotate/static/script.js` — render panes, promotion toggle and persistence
- `skills/annotate/SKILL.md` — the rule in the block menu
- `skills/annotate/references/pushing.md` — pointer to the new reference

## Explicitly out of scope

- **Line-level comments.** The pane is a reading aid; comments come from the
  card header. Revisit only if commenting on a whole block proves too coarse
  in practice.
- **Anchors outside the repo.** Every anchor resolves under `_cwd` or is
  refused. No configuration option to relax this.
- **Anchors on `mockup` blocks.** Sandboxed iframe, nowhere to put a pane.
- **Fetching code from git refs or remotes.** The working tree is the truth.
- **Backfilling anchors into existing workspaces.** The field is optional;
  old documents render unchanged.
