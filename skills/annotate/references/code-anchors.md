# Code anchors — citing real source beside a claim

Read this when you're about to write (or rewrite) a block that says
something specific about code, and need the exact field shape, limits, and
the check to run before announcing the URL.

## The rule

**A block that asserts something about specific code carries a `code`
anchor to that code.** Prose that names a file, function, branch or line —
with the code nowhere on screen — is exactly the failure this field exists
to fix: the reader has to take the claim on trust or go find the file
themselves. An anchor names a file and line; the server reads the real
source at render time and paints it in a column beside the prose.

## When NOT to anchor

A block making a recommendation, framing a question, or summarising takes
**no** anchor — it renders as ordinary full-width prose, the same as any
block in a document with no anchors at all. That is the correct, deliberate
outcome, not an omission. Anchor a claim about code; don't anchor an opinion
about one. `kind: "mockup"` blocks refuse anchors outright (see Limits) — a
sandboxed iframe has nowhere to put a pane.

## The field

Each entry in a block's `code` list, verified against `skills/annotate/anchors.py`:

```json
{"file": "src/orders/service.py", "line": 154, "end_line": 156,
 "snippet": "def validate(order):"}
```

- **`file`** (required) — repo-relative path, resolved against the
  workspace root passed to `check_anchors`/the server. An absolute path is
  refused. A path that resolves outside the root (via `..` or a symlink) is
  refused too — it never reaches the page. Anchors are not limited to
  source code — any repo file a block asserts something about is fair
  game, including `SKILL.md`, a config file, or a spec.
- **`line`** (required) — a positive integer, the line the anchor names.
- **`end_line`** (optional) — a positive integer; if given, must be `>=
  line`. Extends the anchor to a range instead of one line.
- **`snippet`** (required) — the verbatim text of `line`, at authoring
  time. Non-empty. See "Why snippet is the point" below.
There is no `note` field. One existed — a short gloss rendered as a caption
above the pane — and it was removed after being seen in place: the pane's
header line says everything the pane needs to say about itself, and the prose
beside the pane is already where a gloss belongs. An anchor written before the
removal is still accepted; the string is simply ignored. Do not author one.

### Limits

- **At most 3 anchors per block.** Past that the block is a tour of the
  codebase, not a cited claim — reach for `/walkthrough` instead.
- **40-line window.** The rendered span (`line`..`end_line`) is capped at 40
  lines; a longer span is truncated and the pane says how much was cut.
- **2 context lines** rendered dimmed on either side of the window, so an
  anchored line isn't floating with nothing around it.
- **40-line drift search.** If the line has moved, the server looks up to 40
  lines away (in either direction) for a line whose stripped text matches
  the snippet, before giving up.
- **No anchors on `mockup` blocks.**

## Why `snippet` is the point

`snippet` is what lets an anchor survive the file changing underneath it.
At render time the server doesn't trust `line` — it checks whether that
line's text (stripped) still matches `snippet`. If it does, the anchor
resolves `ok`. If a *different* nearby line matches instead, the anchor
resolves `moved` and renders at its new location. Only when no line within
the drift radius matches does it resolve `stale` — and a stale anchor shows
no code at all, just a marker naming the problem.

The comparison is **stripped**, not exact — re-indenting the line is not
drift, it's still the same line. But an anchor whose snippet doesn't match
what's really there — because you paraphrased it, or copied it from memory
instead of the file — resolves `stale` regardless of how close `line` is.
The snippet has to be the real text of that line, not a description of it.

## The check — run before announcing the URL

After writing `blocks.json`, and **before** telling the user the URL, run
this. It carries its own `python3` guard because this file is reached two
ways — mid-push (after `references/pushing.md` has already checked once)
and standalone, when a **rewrite** re-emits anchors on a comment reply with
no push in the same turn (see Rewrites below) — and the second path never
touches `pushing.md`'s guard:

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
python3 -m skills.annotate.check_anchors "<response_dir>/blocks.json" "$PWD"
```

`$PWD` here is a best guess, not authoritative: the root that actually matters is
the directory the session was **created** in, which the server stamped once and
does not refresh when you `/annotate resume` from somewhere else. If `$PWD`
disagrees with the workspace `blocks.json` itself lives under, the check refuses
outright — naming both paths — rather than silently validating against the wrong
repo.

Exit 0 means every anchor resolves. Non-zero prints one problem per line,
each naming the block id and which anchor — fix `blocks.json` and re-run
before announcing anything.

**`moved` is not a failure.** A drifted line still points at the right
code, and the pane shows it at its new location, labelled `moved: authored
at line N, now at line M`. The check only flags `stale`, `missing` (file
gone or unreadable), and `refused` (a malformed anchor, or one that resolves
outside the workspace) — those are the statuses where the reader would see
no code at all.

## Rewrites

When answering a comment on a block that carries anchors, re-emit its
`code` list along with the rewritten content — don't drop the anchors just
because the comment was about the prose. **Re-read the file if it may have
changed** since you first wrote the anchor: a snippet copied from memory
instead of from the current file is exactly how a block goes stale between
one turn and the next. **Re-run the check** (above) after rewriting, the
same as after a push — a rewrite reaches this file with no `pushing.md` in
the turn, so its own guard is the only one that will run.

## What the reader sees

- **`ok`** — the anchored lines, with 2 lines of dimmed context either side.
- **`moved`** — the same lines, now at their drifted location, with a label
  saying where they moved from.
- **`stale` / `missing` / `refused`** — a status marker naming the problem,
  and no code. Rendering whatever now happens to sit at that line number
  would be a lie the reader has no way to detect, so the pane refuses to
  guess.

A block that makes no claim about code simply carries no anchor and renders
normally — full-width prose, no second column, nothing else. Nothing on the
page marks the absence; the rule above is enforced by the push-time check,
not by a visible gap on every anchorless block.
