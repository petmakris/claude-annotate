# Can a remote MCP tool block until a user comments?

Spike run 2026-09-15 on branch `spike/mcp-blocking-tool`. Claude Code v2.1.273,
Python 3.14.7, macOS. Server is `server.py`, a stdlib streamable-HTTP MCP server.
Clients are real `claude -p` sessions with `--mcp-config` and `--strict-mcp-config`,
on `claude-haiku-4-5-20251001`.

## The question

Annotate's loop needs Claude to wake when a user clicks a block, minutes or hours
after the answer was pushed. Locally that is a background watcher process. If the
service is hosted, the wake has to come from the server, and MCP has no way for a
server to push to the model. So: can a tool call simply stay open until the
comment arrives?

## Answer

Yes. A real Claude Code session blocked on a remote MCP tool for 172 seconds,
received an externally-fired event, and reported its payload:

    EVENT {"comment": "the user clicked block 3", "at": 1789505138.7667232}

No local daemon, no watcher script, no polling. But two independent timers have
to be handled, and they are not the same timer.

## Measurements

| Call | `timeout` in `.mcp.json` | Keepalive | Outcome |
|---|---|---|---|
| `wait_json` 900s | none | none | **died at ~65s** — "The operation timed out" |
| `wait_sse` 900s | none | SSE comments, 5s | **died at 310s** — "didn't send any progress" |
| `wait_json` 300s | 1800000 | none | **returned at 300.0s**, on the boundary |
| `wait_for_event` 600s | 1800000 | SSE comments, 5s | **delivered the event at 172s** |
| `wait_progress` 600s | 1800000 | `notifications/progress`, 5s | **returned cleanly at 600.0s** |

## The two timers

**Per-request timer, about 60 seconds by default.** This is what killed the first
call. It is lifted by the per-server `timeout` field in `.mcp.json`, which a
plugin ships itself, so users configure nothing.

**Idle timer, 300 seconds.** Documented as
`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`, default five minutes for HTTP, SSE,
WebSocket and connector servers, and settable to `0` to disable. The `timeout`
field does **not** lift it. Raw SSE comment lines (`: keepalive`) do **not**
reset it — the client's own error message says the server "didn't send any
progress for that duration". The third call returned at exactly 300.0s and won
the race by a hair, which is not a margin to build on.

## Claude Code supplies a progressToken

The `tools/call` request carries one, so progress notifications are the intended
mechanism rather than a workaround:

    _meta={"claudecode/toolUseId": "toolu_01VsDSeCZ6jQZcQ1y5VpXASy", "progressToken": 2}

A server that emits `notifications/progress` against that token every few seconds
is doing what the idle timer is asking for. Measured: a call that sent one every
five seconds ran the full ten minutes and returned cleanly, with no failures in
the server log, where the SSE-comment call died at 310s and the silent call at
65s. Progress notifications reset the idle timer. SSE comments do not.

## Other facts worth keeping

- Claude Code negotiated protocol version `2025-11-25`.
- It opens a `GET /mcp` server-to-client SSE stream alongside the POST.
- It sends an undocumented `server/discover` probe before `initialize`.
- MCP tool output is capped at 25,000 tokens by default
  (`MAX_MCP_OUTPUT_TOKENS`), with a per-tool override up to 500,000 characters.
  A comment payload is far below either.
- A tool call still running after two minutes moves to a background task
  (`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`, default 120000) instead of blocking the
  session. Untested here — `claude -p` is non-interactive and may not background
  the same way. **Test this in an interactive session before designing on it**,
  because if it holds, the user keeps working while the document waits for
  comments, which is the difference between a usable product and a frozen prompt.

## What this means for the design

Hold the call open, set `timeout` in the plugin's `.mcp.json`, and emit
`notifications/progress` on a short interval for as long as the document is
waiting. Have the server return a "nothing yet, call me again" result before any
upstream proxy idle limit rather than betting on an unbounded hold, and have
Claude re-call. That keeps the loop correct even where a load balancer sits
between the client and the server, which it will in production and did not here.
