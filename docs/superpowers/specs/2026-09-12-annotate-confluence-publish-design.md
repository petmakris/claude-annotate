# Publishing an annotate document to Confluence

**Date:** 2026-09-12
**Status:** approved design, ready for an implementation plan

## The problem

An annotate session produces the best explanation of a system this repo can
make — prose paired with real source, a sequence grid with a numbered key,
flowcharts split per dimension — and it is reachable at
`http://localhost:3080/...` by exactly one person on exactly one machine. The
work has the shape of documentation and the reach of a scratchpad.

The ask is not "screenshot it into Confluence". It is that the published page
stay **alive**: it must be regenerable against `master` later, by a nightly job
with no access to the author's laptop, so the documentation tracks the code
rather than rotting beside it.

Those two requirements — publish, and re-publish from scratch — are the same
problem, and the design that treats them separately builds the renderer twice.

## What already exists, and is being reused rather than reinvented

| Thing | Where | Why it matters here |
|---|---|---|
| Drift-tolerant anchors | `snippet` is identity, `line` is a hint; ±40-line search — `skills/annotate/anchors.py:239` (`_locate`) | This is *already* the mechanism that keeps a citation correct while code moves. Re-resolving against a different ref is the same algorithm with a different byte source. |
| Blocks rendered once, at push time | `skills/annotate/render.py:23` (`render_block`) | The stored item body already holds finished SVG for every picture. The publisher does not re-run the diagram layout engine. |
| The document model | `skills/annotate/blocks.py` (`BlocksDoc`, `BLOCK_KEYS`) | The publisher's input is a `BlocksDoc`, not a scrape of the live page. |
| Item storage on disk | `~/.claude/webcompanion/workspaces/annotate/<sid>/items/*.json` | A published document can be read without the daemon running. |
| "Interactive nodes are removed, never hidden" | `skills/annotate/static/export.js:10-14` | The existing Share export settled which parts of a card are the document and which are scaffolding. The Confluence renderer makes the same cut. |
| Per-block error containment | the error-pill branches in `render.py:57` and `:108` | One bad block must never take the page down. The publisher follows it: one unrenderable block becomes a visible marker, not a failed publish. |

## Decisions taken

1. **Render from the document, never from the live page.** The publisher reads
   stored items (or a `blocks.json`) and emits Confluence HTML. It does not
   drive the browser to harvest a rendered DOM. This is what makes publish and
   nightly refresh one code path, and it removes the daemon from the
   dependency list of a scheduled job.
2. **Confluence HTML format, not storage format.** Verified against
   `getContentFormatGuide(createConfluencePage)`: `<ac:structured-macro>`,
   `<ac:plain-text-body>` and `<ri:attachment>` are **not** part of this format
   and render as raw text. Everything is authored as the ADF-mapped HTML
   subset — `<pre><code class="language-java">`, `<div data-type="panel-note">`,
   `<details>`, `<figure data-type="media-single">`.
3. **Diagrams become PNG attachments.** Each stored SVG is wrapped in a
   standalone HTML document with `diagram.css` and the woff2 faces inlined, and
   screenshotted in headless Chromium at `deviceScaleFactor: 2`. Chromium
   specifically: `diagram.css` uses `color-mix()`, which `rsvg-convert` does not
   implement, so librsvg would silently produce a differently-coloured picture.
4. **The page carries its own regeneration source.** `annotate-source.json` is
   attached to the published page: the block document, every anchor, the repo
   remote, the ref and the commit it was resolved at. Confluence content
   properties are not exposed by the available MCP tools, so an attachment is
   the storage — durable, versioned, and readable back through
   `listConfluenceAttachments` + `downloadConfluenceAttachment`.
5. **Documentation is always built from `master`.** Anchors resolve against
   `origin/master`, never the working tree and never the authoring branch. A
   page describing an unmerged branch documents code its readers do not have.
6. **A stale anchor stops the publish.** It is named, with its block, and the
   author decides. It is never silently dropped and never silently published as
   if it were current.
7. **Update in place.** The first publish records the page id; every later one
   updates that page. Confluence keeps its own version history, and the URL that
   was shared stays valid.
8. **The sequence key stays native text.** `render_key()` already emits HTML,
   not SVG, so the numbered key converts to a real Confluence table for free:
   searchable, copy-pasteable, and readable on a phone. Only the grid is a
   picture.

## Rejected alternatives

- **Harvest the live DOM** (the approach `export.js` takes, and right for it):
  guarantees fidelity because there is only one renderer, but it binds every
  future refresh to a running daemon and a live session, and converting
  arbitrary rendered HTML to the ADF-mapped subset is lossier than converting
  the markdown we authored ourselves.
- **SVG attachments instead of PNG:** keeps the diagram vector and its text
  searchable. Rejected for now because Confluence Cloud sanitises SVG and its
  rendering of one with embedded fonts is not something this design can assert
  without publishing one and looking at it. Revisit once the PNG path ships.
- **No images — flowcharts as nested lists:** fully native and never rots, but
  the drawing is most of why the annotate page reads well.
- **`file.java:74` as the citation:** line numbers are the part that rots. The
  visible citation is a GitHub link pinned to the resolved commit, which is
  permanently correct, and the durable identity in the manifest is the snippet.

## Architecture

A new package, `skills/annotate/confluence/`, and one new reference,
`references/publishing.md`. Four units, each independently testable.

### `manifest.py` — what makes the page regenerable

Builds and parses `annotate-source.json`:

```json
{
  "manifest_version": 1,
  "response_id": "resp-1789003000",
  "title": "The pre-trade id chain",
  "glossary": [{"term": "proposalSyncId", "definition": "..."}],
  "repo": {"remote": "git@github.com:evooq/montblanc.git",
           "web": "https://github.com/evooq/montblanc",
           "ref": "origin/master",
           "commit": "f4a2e8eae046922b55baaf44529505aa022d9633",
           "resolved_at": "2026-09-12T11:40:00Z"},
  "blocks": [ ... the stored item bodies, verbatim ... ]
}
```

The blocks are stored verbatim, SVG included, so a refresh re-renders pictures
without re-running the layout engine and without the authoring machine.

`parse()` refuses a manifest whose `manifest_version` it does not know, rather
than guessing at a future shape.

### `resolve.py` — anchors against a git ref

`anchors.py` owns the drift search and keeps owning it. Today its `_read_lines`
reads from the filesystem; this unit gives that step an injectable source so the
same matcher can be fed by `git show <ref>:<path>`. No second copy of the drift
logic exists.

Per anchor it returns `{status, file, line, end_line, snippet, url}` where
status is `ok` / `moved` / `stale` / `ambiguous`, and `url` is the GitHub blob
link at the resolved **commit** (not the ref), `…/blob/<sha>/<path>#L<a>-L<b>`.

`ambiguous` is new and specific to this path: an anchor whose snippet matches
more than one line in the file is a citation that *could* have silently landed
on the wrong line. The real document contains one — `@Query("""` in
`CustomJpaProposalRepository.java`, which occurs five times in that file — so
this is not a hypothetical.

### `images.py` — one PNG per diagram

For each block carrying `svg`: build a standalone HTML with the SVG, the
contents of `static/diagram.css`, and the woff2 faces as base64 `@font-face`
sources; open it in headless Chromium via the globally installed `playwright`;
screenshot the `<svg>` element's bounding box at 2× scale; write
`<block-id>.png`.

The filename is derived from the block id and is therefore stable, so a
re-publish replaces an attachment rather than accumulating a second one.

A flowchart with multiple `views` publishes its default view as the block's
picture and each additional view inside a `<details>` expand, one image each,
titled by the view name.

### `body.py` — the document as Confluence HTML

Per block kind:

| Kind | Becomes |
|---|---|
| `markdown` | `<h2>` from the block title, then the markdown converted to the ADF-mapped subset: paragraphs, `<ul>`/`<ol>`, `<table>`, `<pre><code class="language-…">`, `<strong>`, `<em>`, `<code>`, links. |
| `sequence` | `<h2>`, the grid as `<figure data-type="media-single" data-width="80">`, then the numbered key as a native `<table>` (number, label, detail). |
| `flowchart` | `<h2>` from `spec.title`, the picture as a figure; extra views in `<details>`. |
| `choice` | Rendered as the decision it records, not as an open question. A choice block still unanswered at publish time is a marker, not a silent omission. |
| `mockup` | Not published. A sandboxed interactive iframe has no Confluence equivalent; the block becomes a note panel naming what is missing and linking the annotate page. |

Code anchors render beneath their block's prose: a `<pre><code>` holding the
excerpt, and a caption paragraph linking the GitHub permalink. A `moved` anchor
renders normally — it resolved. A `stale` one never reaches this stage; the
publish stopped.

Page anatomy, in order: glossary `<table>` → sections in `order` → a provenance
`<div data-type="panel-info">` footer naming the ref, the short sha, the
publication date, and the annotate session slug.

### `publish.py` — the flow

Because a media node needs an id that only exists after upload, and an upload
needs a `contentId` that only exists after the page does, publishing is three
phases and cannot be fewer:

1. **Resolve.** Read items → build manifest → resolve every anchor against
   `origin/master`. Any `stale` or `ambiguous` anchor: print block id, file,
   snippet, and stop. Nothing is written to Confluence.
2. **Create or find the page.** `state/confluence.json` in the workspace holds
   `{page_id, space_id, parent_id, last_commit, last_published}`. Absent, the
   page is created under the parent the user names once, as a **draft** — the
   first publish of a document is never live until its author has looked at it.
   `--live` skips the draft step; a later publish updates whatever status the
   page already has.
3. **Attach, then body.** Render PNGs and the manifest; upload each through
   `createConfluenceAttachment` (which returns a curl command to run locally),
   capturing the media id and collection from the response — falling back to
   `listConfluenceAttachments` if the upload response does not carry them.
   Then build the body with those ids and `updateConfluencePage`.

### Refresh — the living half

`/annotate publish --refresh <page-url|page-id>` needs no local workspace:

1. `listConfluenceAttachments` → find `annotate-source.json` →
   `downloadConfluenceAttachment` → `manifest.parse`.
2. Re-resolve every anchor against today's `origin/master` in a local checkout
   of the manifest's repo.
3. Re-render body and pictures; update the page; re-attach the manifest with the
   new commit.
4. Report: anchors that moved, anchors that went stale, and whether any block's
   prose now contradicts its own excerpt — the last being something only a human
   or a model can judge, so it is reported, never auto-edited.

A nightly job is this command on a schedule. Nothing further is built for it
now, and nothing in this design forecloses it.

## Command surface

```
/annotate publish [--space PMP] [--parent <page id or title>] [--live]
/annotate publish --refresh <page url or id>
```

`SKILL.md` gains one row pointing at `references/publishing.md`, and its
`allowed-tools` gains the Atlassian MCP tools — today it is `Bash, Read, Write`,
and none of the Confluence calls are reachable under that list.

## Error handling

- **Stale or ambiguous anchor** → publish refuses, names every one, writes
  nothing. This is the only hard stop.
- **A block that fails to render** → an error panel in its place naming the
  block id, following `render.py`'s existing per-block containment. The rest of
  the page publishes.
- **Chromium missing** → refuse before any Confluence call, with the install
  command. Never publish a page with the pictures silently absent.
- **Attachment upload fails** → the page keeps its previous body. A body
  referencing a media id that was never uploaded renders as a broken node, so
  the body update happens only after every upload has succeeded.
- **Confluence rejects the body** → report what was rejected and leave the page
  at its previous version, per the format guide's own caveat about destructive
  overwrites.

## Testing

| Unit | Test |
|---|---|
| `resolve.py` | A fixture repo with two commits: a line that moved, a line deleted, and a snippet occurring twice. Asserts `ok` / `moved` / `stale` / `ambiguous` and the permalink's sha. |
| `manifest.py` | Round-trip: build → serialise → parse → identical. An unknown `manifest_version` raises. |
| `body.py` | Golden Confluence HTML per block kind. Plus a guard that no output contains `<ac:` or `<ri:` — the format guide forbids them and they fail *silently*, by rendering as text. |
| `images.py` | Produces a PNG whose dimensions are the SVG's viewBox at 2×; skips with a clear message when Chromium is absent. |
| `publish.py` | Phase ordering with a faked Confluence client: asserts no body update is attempted before every upload reports success, and that a stale anchor produces zero writes. |

Then one real publish of `the-pre-trade-id-chain` to a **draft** page in PMP,
opened in a browser and read, before this is called done. Two defects in the
sequence-key work were visible only in a real browser; a rendering target this
design has never seen gets the same treatment.

## Known state of the first document to be published

`the-pre-trade-id-chain` (session `260912-104014-9e4021501a26eefe`, 11 blocks,
authored against the `PMP-272-…` worktree). Against `origin/master`
(`f4a2e8e`), of 10 anchors: 6 `ok`, 3 `moved` by 1–2 lines, 1 `stale`.

The stale one is **`section-8`**, "Correction — the nightly step needs no id",
anchoring `CustomJpaProposalRepository.java:74` on snippet `@Query("""`. Master
has no text-block query in that file. The method the section's claim rests on,
`findAllIdsByOrganizationIdAndStatusInAndPreTradeChecked`, is added by PMP-272
and is not merged. Per decision 6, the first publish will stop on it, and the
author decides whether to hold the section or reword it.

Space: **Portfolio Implementation (PMP)**, key `PIMP`, alias `PMP`, id
`2672492578`, homepage `2672492961`. Cloud id
`0cdfea0c-5f20-412f-bec3-236bc454b30b`.
