# Annotate as a cloud service

Design notes written alongside the MCP blocking-call spike on branch
`spike/mcp-blocking-tool`. Measurements are in `FINDINGS.md`.

## What the product is

Claude Code answers in a terminal, where the user cannot point at anything. The
only ways to disagree are to accept the whole answer or to retype the objection
as prose. Annotate makes the answer a document whose blocks are addressable: the
user clicks the one paragraph that is wrong, says why, and Claude replaces that
block.

Everything above already works locally and is free. The cloud version sells three
things the local one cannot give:

1. **A URL other people can open.** A migration plan reviewed by three engineers,
   each commenting on different blocks, with Claude revising in place.
2. **Persistence.** The document outlives the session, the terminal and the
   laptop. A comment left on Thursday reaches Claude on Friday.
3. **No install.** No `python3`, no port, no daemon, no IntelliJ plugin.

The positioning is not "nicer output". It is "review what Claude wrote the way
you review a pull request".

## Why the margins are unusual

The inference runs on the user's own Claude Code subscription. The service hosts
a page and a comment store, and never calls a model. Cost of goods is cents per
user per month, against a per-seat price. Almost no AI product has this shape,
because almost every AI product pays for the tokens it generates.

The corollary is that usage-based pricing is the wrong instinct here. There is no
per-round cost to recover, so price per seat and let rounds be unlimited.

## The shape: a free plugin plus a paid remote MCP server

Neither half can be the product alone.

A plugin is the only thing Claude Code installs from a marketplace, and there is
no paid marketplace — the community and official marketplaces are free, and
approved plugins are pinned to a commit in a public catalog. So the plugin cannot
carry the billing.

A remote MCP server cannot carry the trigger. A server only answers calls; it
cannot make Claude do anything, and it does not know what the user typed.

So the plugin carries the trigger and is free and thin. The server carries
rendering, hosting, state, identity and billing, and sits behind OAuth. Claude
Code supports remote HTTP MCP with OAuth 2.0 directly: `claude mcp add
--transport http`, then `/mcp` or `claude mcp login <name>` to authenticate. A
plugin can ship the server config in `.mcp.json` at its root, so install is one
`/plugin install` followed by one login.

| Piece | Where it lives | Paid |
|---|---|---|
| `/annotate` command and routing rules | plugin, on the user's machine | no |
| block composition instructions | server, served after auth | yes |
| page render, hosting, the URL | server | yes |
| comment store, round history | server | yes |
| the wake | server holds a call open | yes |
| file reads, edits, code anchors | Claude Code, locally | n/a |

## Where the instructions live is a business decision

The block-kind system is most of what makes annotate good: sequence diagrams,
flowcharts with ELK layout and views, choice blocks, mockups, the verbosity
contracts, the anchoring rules. That is a large body of prompt engineering, and
today it sits in a public repository where anyone can copy it in an afternoon.

Moving it behind authentication is the single highest-leverage change. MCP tool
descriptions and MCP prompts are both delivered after the OAuth handshake, so the
server can hand Claude the composition contract only once the seat is paid for.
What remains in the public plugin is the trigger and the routing table, which is
not worth copying on its own.

## What stays on the user's machine

Less is lost than it first appears. The server holds the document; Claude Code
still holds the filesystem. So code anchors, file edits and deck editing all keep
working, because the cloud page reports which block was clicked and Claude does
the local reading and writing itself.

Two things genuinely do not survive:

- **Jump-to-source from the browser.** A hosted page cannot open `file://`. It
  needs either a tiny local helper or a "Claude, open this" round trip.
- **The IntelliJ half.** `walkthrough` and `ask_diff` drive the IDE plugin over
  localhost. Those stay local, and that is fine — they are the more defensible
  half precisely because they need a machine.

## Tiers

Assumed, not researched. Numbers are a starting point for a pricing test, not a
conclusion.

| Tier | Price | What it adds |
|---|---|---|
| Free | 0 | the existing local plugin: solo, localhost, ephemeral |
| Pro | ~$15/user/month | cloud pages, shareable URLs, persistence, round history |
| Team | ~$30/user/month | org workspace, SSO, audit export, Confluence and Jira publishing |
| Enterprise | quoted | self-hosted server image, no document leaves the network |

The free tier is deliberately solo and ephemeral rather than crippled. It is the
funnel, and the plugin is already published on a marketplace, which is
distribution most products at this stage do not have.

Enterprise self-hosting is not a concession, it is a tier. Source code and
architecture plans on a third-party server is the first objection any regulated
buyer raises, and having an answer priced above Team turns the objection into
revenue.

## Risks, worst first

1. **Anthropic ships this.** Published artifacts already take comments that reach
   Claude, and watch for republishes. That covers the solo read-and-comment case,
   which is exactly the free tier. The defence is depth in the directions
   Anthropic is unlikely to go: IDE integration, diff review, code anchors,
   Confluence and Jira publishing, team review workflow.
2. **The instructions are public today.** Addressed above, and it should be
   addressed before any launch rather than after.
3. **Cannibalisation by the free local version.** Acceptable only if free stays
   solo and ephemeral by design, and that line is held.
4. **Claude Code version churn.** The plugin surface, the MCP protocol version
   and the timeout defaults all move. The spike already saw protocol
   `2025-11-25` negotiated. This needs a compatibility test suite run against
   each Claude Code release, not a one-time integration.
5. **Support cost of OAuth.** Every user hits a login flow before the product
   works. This is the most common place a paid developer tool loses a trial.

## What to build first

Not the block-kind zoo — it exists, it works, and it is not what anyone would pay
for. The smallest slice that tests willingness to pay is:

1. Push a document to the server, get back a URL.
2. Open the URL, click a block, leave a comment.
3. Claude wakes, revises that block, the page updates.
4. A second person opens the same URL and does the same.

Step 3 is the one that was unproven, which is why the spike exists.
