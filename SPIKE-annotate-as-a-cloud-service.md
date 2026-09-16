# Spike: annotate as a hosted cloud service

Status: the spike is finished and its central question is answered. One item is
untested and is named below. Nothing here has been built into the product.

- Branch: `spike/mcp-blocking-tool`
- Commit: `11d6898` — "Spike a remote MCP server that blocks until a comment arrives"
- Code and raw logs: `spikes/mcp_blocking/`
- Run on: 2026-09-15, macOS, Claude Code v2.1.273, Python 3.14.7
- Written up: 2026-09-16

This document is self-contained. It repeats what is in
`spikes/mcp_blocking/FINDINGS.md` and `spikes/mcp_blocking/PRODUCT.md` so that
picking this up later needs no other reading.

---

# Part 1 — The question

## What annotate does today

Claude Code answers in a terminal, where the reader cannot point at anything. The
only ways to disagree are to accept the whole answer or to retype the objection
as prose. `/annotate` turns the answer into a web page whose blocks are
addressable: the user clicks the one paragraph that is wrong, says why, and
Claude replaces that block in place, without re-rendering the rest.

Today that runs entirely on the user's machine:

- A local HTTP server, `skills/_shared/web_companion/`, shared by `annotate`,
  `deck`, `dataflow`, `walkthrough` and `ask_diff`.
- A browser page served from localhost.
- A background watcher (`watcher.sh`) that blocks until a comment arrives and
  then emits a `WEBCOMPANION_EVENT` line, which reaches Claude as a task
  notification and re-invokes the skill.
- Requirements the user must satisfy: `python3` 3.9+, `bash`, `curl`, `node` for
  ELK layout, and for the IDE half a separately installed IntelliJ plugin.

## Why a hosted version was considered

To sell it. A cloud version offers three things the local one cannot:

1. A URL other people can open, so several reviewers comment on the same
   document and Claude revises in place.
2. Persistence beyond the session, the terminal and the laptop.
3. No install at all.

## The question the spike had to answer

An MCP server cannot push to the model. It only answers calls. So if the server
is remote, where does the wake come from when a user clicks a block minutes or
hours after the document was pushed?

The proposed answer was: **the tool call simply stays open until the comment
arrives.** That had to be measured, because it lives or dies on Claude Code's
timeouts.

---

# Part 2 — The answer

Yes, it works.

A real Claude Code session called a remote MCP tool, the call blocked for **172
seconds** waiting on an event fired from outside, and the session received the
payload and reported it:

    EVENT {"comment": "the user clicked block 3", "at": 1789505138.7667232}

No local daemon, no watcher script, no polling.

But two independent timers sit in the path, they are not the same timer, and they
need different fixes.

---

# Part 3 — Verified platform facts

## Measured in this spike

All five runs used real `claude -p` sessions against a stdlib streamable-HTTP MCP
server on loopback, model `claude-haiku-4-5-20251001`, with `--mcp-config` and
`--strict-mcp-config`.

| Call | `timeout` in config | Keepalive | Outcome |
|---|---|---|---|
| `wait_json` 900s | none | none | **died at ~65s** |
| `wait_sse` 900s | none | SSE comment lines, 5s | **died at 310s** |
| `wait_json` 300s | 1800000 | none | **returned at 300.0s** |
| `wait_for_event` 600s | 1800000 | SSE comment lines, 5s | **event delivered at 172.4s** |
| `wait_progress` 600s | 1800000 | `notifications/progress`, 5s | **returned cleanly at 600.0s** |

Exact client-side messages, which are the useful evidence:

- `wait_json` with no `timeout` field: *"The operation timed out. The tool was
  called with seconds=900, but the system's timeout limit was exceeded before the
  900-second wait could complete."*
- `wait_sse`: *"the MCP server "spike" tool "wait_sse" timed out after 300
  seconds of no response. The harness aborted because the server didn't send any
  progress for that duration, and a 900-second wait exceeds the default idle
  timeout. To make this work, the MCP server would need a longer timeout
  configured (either per-server in MCP settings or globally via
  `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`)."*
- `wait_json` with `timeout`: *"Tool returned: `wait_json returned after 300.0s`"*
- `wait_progress`: *"The tool returned: `wait_progress returned after 600.0s`"*

Server-side confirmation of the `wait_sse` death:
`354.56  wait_sse: CLIENT GONE after 310.2s ([Errno 32] Broken pipe)`.

**Caveat on `wait_for_event`.** It survived 172 seconds, which is under the
300-second idle limit, so it proves the event-delivery mechanism and proves
nothing about long holds. `wait_progress` is the run that proves the long hold.

## Claude Code supplies a progressToken

The `tools/call` request carries one, so progress notifications are the intended
mechanism rather than a workaround:

    _meta={"claudecode/toolUseId": "toolu_01VsDSeCZ6jQZcQ1y5VpXASy", "progressToken": 2}

## Protocol details observed on the wire

- Claude Code negotiated MCP protocol version `2025-11-25`.
- It opens a `GET /mcp` server-to-client SSE stream alongside the POST.
- It sends an undocumented `server/discover` probe *before* `initialize`, with
  id `server-discover-probe-1`.
- A minimal server needs `initialize`, `notifications/initialized` (a
  notification, answer `202` with no body), `tools/list`, `tools/call`, and
  tolerance of `GET /mcp` and `DELETE /mcp`.

## From the documentation

Source: https://code.claude.com/docs/en/mcp and
https://code.claude.com/docs/en/plugins (fetched 2026-09-15).

| Setting | Default | What it governs |
|---|---|---|
| per-server `timeout` in `.mcp.json` | unset | tool execution, in ms, overrides `MCP_TOOL_TIMEOUT` for that server |
| `MCP_TOOL_TIMEOUT` | ~28 hours | per-server tool execution wall clock |
| `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` | 5 min HTTP/SSE/WS, 30 min stdio | idle window before abort; `0` disables |
| `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` | 2 min | when a running call moves to a background task |
| `MCP_TIMEOUT` | not stated | server startup |
| `MAX_MCP_OUTPUT_TOKENS` | warn 10k, cap 25k | tool result size; per-tool override `_meta["anthropic/maxResultSizeChars"]` up to 500k chars |

Also confirmed in the docs:

- **Remote HTTP MCP with OAuth 2.0 is first-class.** `claude mcp add --transport
  http <name> <url>`, then `/mcp` in-session or `claude mcp login <name>`.
  Pre-configured credentials via `--client-id` / `--client-secret`, and custom
  schemes via `headersHelper`.
- **Plugins bundle MCP config** in `.mcp.json` at the plugin root or inline in
  `plugin.json`. Plugin MCP tools are named
  `mcp__plugin_<plugin>_<server>__<tool>`.
- **Plugins can ship background monitors** in `monitors/monitors.json`; each
  stdout line becomes a Claude notification. This is a second, independent wake
  path worth remembering.
- **There is no paid marketplace.** `claude-plugins-official` is curated by
  Anthropic; `claude-community` takes submissions after review and pins them to a
  commit SHA in a public catalog. Billing therefore has to ride on the OAuth
  identity, not on distribution.

---

# Part 4 — The two timers

**Per-request timer, about 60 seconds by default.** This killed the first call at
~65s. It is lifted by the per-server `timeout` field in `.mcp.json`. A plugin
ships its own `.mcp.json`, so you set this yourself and users configure nothing.

**Idle timer, 300 seconds.** Documented as `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`.
The `timeout` field does **not** lift it. Raw SSE comment lines (`: keepalive`)
do **not** reset it — the client's own error says the server "didn't send any
progress". It **is** reset by `notifications/progress` sent against the supplied
`progressToken`, proven by a clean 600-second hold.

The third run returned at exactly 300.0s and won that race by a hair. Do not read
it as a passing design; it is a coin flip against the idle limit.

---

# Part 5 — The design that follows

1. Ship `"timeout": 1800000` in the plugin's `.mcp.json`. Lifts the per-request
   timer with no user configuration.
2. Emit `notifications/progress` against the request's `progressToken` every few
   seconds for as long as the document is waiting. Not SSE comments.
3. Do not bet on an unbounded hold. Return a "nothing yet, call again" result
   before any upstream proxy idle limit and have Claude re-call. This spike ran
   on loopback with no load balancer in the path; production will have one, and
   it will have its own opinions about idle connections.
4. Keep tool results small. The comment payload is far below the 25k-token cap,
   but the document itself must never be returned through a tool result.

---

# Part 6 — The open question

**Untested: does a long tool call move to a background task at two minutes, in an
interactive session?**

The documentation says it does: *"An MCP tool call in the main conversation that
is still running after two minutes moves to a background task instead of blocking
the session."* Every measurement here used `claude -p`, which is non-interactive
and has no reason to implement that behaviour, so the spike says nothing about
it.

This matters more than anything else in this document. If it holds, the user
keeps working while the document waits for comments. If it does not, every push
freezes the prompt until somebody clicks something, and the shape is unusable.

## How to test it

    cd spikes/mcp_blocking
    python3 server.py 8899          # leave running in its own terminal
    claude mcp add --transport http spike http://127.0.0.1:8899/mcp
    # then, in an interactive claude session:
    #   ask it to call wait_progress with seconds=600
    #   watch whether the prompt returns to you before the call finishes
    #   if it does, type something else and confirm the session still works
    #   confirm the result arrives as a notification when the 600s elapse

Then remove it: `claude mcp remove spike`.

---

# Part 7 — Product analysis

## What the product is

Not "nicer output". The framing that holds up is **review what Claude wrote the
way you review a pull request**. The paid version sells the shareable URL, the
persistence and the zero install, not the rendering.

## The margins are unusual

The inference runs on the user's own Claude Code subscription. The service hosts
a page and a comment store and never calls a model. Cost of goods is cents per
user per month against a per-seat price.

The corollary: usage-based pricing is the wrong instinct. There is no per-round
cost to recover. Price per seat and let rounds be unlimited.

## The shape: a free plugin plus a paid remote MCP server

Neither half works alone. A plugin cannot carry billing, because there is no paid
marketplace. A remote server cannot carry the trigger, because it only answers
calls and does not know what the user typed.

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
contracts, the anchoring rules. That is a large body of prompt engineering
sitting in a public repository, copyable in an afternoon.

MCP tool descriptions and MCP prompts are delivered after the OAuth handshake. So
the server can hand Claude the composition contract only once the seat is paid
for. What stays public is the trigger and the routing table, which is not worth
copying alone.

**This is the highest-leverage change available, and it belongs before launch.**

## What stays on the user's machine

Less is lost than it first appears. The server holds the document; Claude Code
still holds the filesystem. Code anchors, file edits and deck editing all keep
working, because the page reports which block was clicked and Claude does the
local reading and writing itself.

Two things genuinely do not survive:

- **Jump-to-source from the browser.** A hosted page cannot open `file://`. It
  needs a small local helper or a "Claude, open this" round trip.
- **The IntelliJ half.** `walkthrough` and `ask_diff` drive the IDE plugin over
  localhost. They stay local, and that is fine — they are the more defensible
  half precisely because they need a machine.

## Tiers

Assumed, not researched. A starting point for a pricing test, not a conclusion.

| Tier | Price | What it adds |
|---|---|---|
| Free | 0 | the existing local plugin: solo, localhost, ephemeral |
| Pro | ~$15/user/month | cloud pages, shareable URLs, persistence, round history |
| Team | ~$30/user/month | org workspace, SSO, audit export, Confluence and Jira publishing |
| Enterprise | quoted | self-hosted image, no document leaves the network |

Free stays solo and ephemeral by design rather than crippled. It is the funnel,
and the plugin is already published on a marketplace, which is distribution most
products at this stage do not have.

Enterprise self-hosting is a tier, not a concession. Source code and architecture
plans on a third-party server is the first objection a regulated buyer raises.
Pricing the answer above Team turns that objection into revenue.

## Risks, worst first

1. **Anthropic ships this.** Published artifacts already take comments that reach
   Claude and watch for republishes. That covers the solo read-and-comment case,
   which is exactly the free tier. Defence: depth where Anthropic is unlikely to
   go — IDE integration, diff review, code anchors, Confluence and Jira
   publishing, team review workflow.
2. **The instructions are public today.** Addressed above.
3. **Cannibalisation by the free local version.** Acceptable only if free stays
   solo and ephemeral, and that line holds.
4. **Claude Code version churn.** The plugin surface, the MCP protocol version
   and the timeout defaults all move; this spike already saw `2025-11-25`
   negotiated and undocumented probes on the wire. This needs a compatibility
   suite run against each Claude Code release, not a one-time integration.
5. **OAuth support cost.** Every user hits a login flow before the product works.
   That is the most common place a paid developer tool loses a trial.

## What to build first

Not the block-kind zoo. It exists, it works, and it is not what anyone would pay
for. The smallest slice that tests willingness to pay:

1. Push a document to the server, get back a URL.
2. Open the URL, click a block, leave a comment.
3. Claude wakes, revises that block, the page updates.
4. A second person opens the same URL and does the same.

Step 3 was the unproven one. It is now proven, subject to Part 6.

---

# Part 8 — Reproducing the spike

    cd spikes/mcp_blocking
    python3 server.py 8899 > server.log 2>&1 &

    # tools: wait_json, wait_sse, wait_progress, wait_for_event
    # configs: mcp.json (no timeout), mcp_timeout.json and mcp2.json (30 min)

    claude -p "Call the spike wait_progress tool with seconds=600. Report exactly what it returned." \
      --mcp-config mcp2.json --strict-mcp-config \
      --model claude-haiku-4-5-20251001 --dangerously-skip-permissions

    # fire an external event at a blocked wait_for_event call:
    curl -s -X POST http://127.0.0.1:8899/fire

Raw evidence kept in the commit: `server.log`, `server2.log`, and one
`out_*.txt` per client run.
