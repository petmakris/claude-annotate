# Publishing a document to Confluence

Read this when the user types `/annotate publish` (or
`/annotate publish --refresh <page>`). It turns the session the conversation
is attached to into a Confluence page, and updates that same page on every
later publish.

## What this is not

It is not the Share export (`static/export.js`), which produces a standalone
HTML file from the live page. This builds a native Confluence page: the prose
is Confluence prose, the diagrams are attachments, and the citations link
GitHub at a pinned commit.

## The rule that shapes the procedure

**Documentation is built from `origin/master`.** A page describing an unmerged
branch documents code its readers do not have. If a citation does not resolve
on master, the publish stops and the user decides — it is never quietly
dropped, and never published as though it were current.

## The helper command

Every command below is `claude-annotate <command>`, a script in the plugin's
`bin/` that Claude Code puts on PATH. It runs from any directory and needs
nothing exported first; if the shell cannot find it, suggest
`/annotate-doctor`.

## Resolve the site and the space

Every Confluence call below needs a `cloudId`, and creating a page needs a
`spaceId`. Both are per-organisation, so this plugin ships neither — resolve
them once per publish and substitute them wherever `<cloudId>` and
`<spaceId>` appear:

- `getAccessibleAtlassianResources()` lists the Atlassian sites this user can
  reach. Each entry's `id` **is** the `cloudId`. One entry is the ordinary
  case; if there are several, ask the user which site the page belongs on.
- `getConfluenceSpaces(cloudId: <cloudId>)` lists that site's spaces. Ask the
  user which space (by name or key), take its `id`, and that is `<spaceId>`.

A document that has been published before needs neither question:
`<workspace>/confluence.json` already records its `space_id` and `page_id`.

## Step 1 — build the bundle

```bash
claude-annotate confluence.prepare \
  --items "<workspace>/items" \
  --repo "<a checkout of the repo the session was authored against>" \
  --out "<bundle dir>" \
  --slug "<session slug>"
```

Exit 0 means `report.json`'s `proceed` field is true and the bundle is
complete. **Exit 2 means stop** — `proceed` is false. Read
`<bundle dir>/report.json` and tell the user exactly what refused — a publish
stops when **any** of these four are non-empty:

- `blocking` — citations that do not resolve on master. Each names the block,
  the file, the snippet, and why (`stale`, `missing`, `ambiguous`, `refused`).
- `unconvertible` — a block that cannot be rendered as approved: markdown
  using raw HTML, a markdown image, a setext heading, or a diagram block with
  no stored drawing to attach.
- `unsupported_views` — a flowchart carrying more than the union view. Only
  the union is published today, so a block with extra views refuses rather
  than dropping them silently.
- `missing_blocks` — a block id named in the session's `order` with no file on
  disk for it. The stored document has drifted from what the author actually
  approved, so this is refused the same as a bad citation, not skipped.

Do not work around any of the four. The user's options are to reword the
block, drop it, or wait for the merge; all of them are theirs to choose.

A refused run leaves no publishable bundle behind, including from an earlier
successful run into the same `--out`: `prepare` clears the directory before it
writes. If `body.template.html` is absent, that is the refusal, not a
half-written bundle.

## Step 2 — find or create the page

Read `<workspace>/confluence.json`. If it has a `page_id`, this document has
been published before: skip to step 3.

Otherwise ask the user which page to nest under, once, then:

```
createConfluencePage(cloudId: <cloudId>,
                     spaceId: <spaceId>, title: <report.title>,
                     parentId: <the page they named>, status: "draft",
                     contentFormat: "html", body: "<p>Publishing…</p>")
```

Created as a **draft**: the first publish of a document is never live until its
author has read it. Record the result:

```bash
claude-annotate confluence.state --workspace "<workspace>" \
  page_id="<page id>" space_id="<spaceId>" parent_id="<parent page id>"
```

## Step 3 — upload the attachments

For every file in `<bundle dir>/images/` and for `annotate-source.json`:

```
executeWrite(name: "createConfluenceAttachment",
            cloudId: <cloudId>,
            inputs: {contentId: <page id>,
                     localFilePath: "<bundle dir>/images/section-4.png"})
```

It returns a curl command. Run it with Bash, and keep the media id and
collection from its response. If the response does not carry them, read them
back with:

```
executeRead(name: "listConfluenceAttachments",
           cloudId: <cloudId>,
           inputs: {contentId: <page id>})
```

`annotate-source.json` is not decoration: it is what lets this page be rebuilt
against a later master by someone who has never seen this machine.

## Step 4 — write the body

```bash
claude-annotate confluence.finalize \
  --bundle "<bundle dir>" \
  --media '{"section-4.png": {"id": "<media id>", "collection": "<collection>"}}'
```

It **exits 2 and writes no `body.html`** if any picture is missing an id,
naming the block ids it could not fill. A media node pointing at nothing
renders as a broken tile with no error anywhere, so on exit 2 stop: go back
to step 3, upload what is missing, and run finalize again. Never publish the
template. Then:

```
updateConfluencePage(cloudId: <cloudId>,
                     pageId: <page id>, title: <report.title>,
                     contentFormat: "html", body: <contents of bundle/body.html>)
```

Record the commit that was published:

```bash
claude-annotate confluence.state --workspace "<workspace>" \
  last_commit="<report.repo.commit>"
```

Give the user the page URL and say it is a draft, if it is.

## Refreshing a published page

`/annotate publish --refresh <page url or id>` rebuilds a page against today's
master. It needs no annotate workspace — only a checkout of the repo the
manifest names.

1. `executeRead(name: "listConfluenceAttachments", cloudId, inputs: {contentId})`
   → find `annotate-source.json` →
   `executeRead(name: "downloadConfluenceAttachment", cloudId, inputs: {...})`
   → run the curl it returns.
2. Build the bundle from that file directly. There is no items directory to
   reconstruct: the manifest already carries the title, the slug, the
   response id, the glossary, and the blocks in order.

   ```bash
   claude-annotate confluence.prepare \
     --manifest "<the downloaded annotate-source.json>" \
     --repo "<a checkout of the repo the manifest's repo.remote names>" \
     --out "<bundle dir>"
   ```

   No `--slug`: the manifest carries it. Exit 0 / exit 2 and the four refusal
   lists mean exactly what they mean in step 1, and a refusal here stops the
   refresh with the published page untouched.
3. Continue from step 3. The page already exists, so nothing is created.
4. Report what changed: anchors that moved, anchors that went stale, and any
   block whose prose no longer matches the source beneath it. The last one is
   a judgement, not a diff — say what you saw and let the user decide. Never
   edit the prose to fit the code.
