# The fleet world for ca-14

`world.py` builds an invented two-machine fleet and serves the real fleet page
from this checkout:

    uv run --with playwright python tools/promo/fixtures/fleet/world.py <scratch dir> --port <port>
    uv run python tools/promo/fixtures/fleet/world.py <scratch dir> --stop

- `laptop` is the hub and serves the page; `build-box` answers through a fake
  `ssh` that runs fleet's CLI with its own FLEET_HOME. No machine is reached.
- It prints the login URL (`/login?t=...`, a made-up token) and writes every PID
  to `<scratch>/world/pids.json`; `--stop` kills exactly those.
- Members: builder (busy), reviewer, docs-writer (busy), tester. Backlog: #2
  "Add retry to checkout" waits on #1 "Review the payment schema". Sessions: 11
  rows over both machines; "Search by meaning" for "the checkout retry work"
  gives 3 matches through a stub `claude`.
- Tools reads a synthetic home per machine (`scan_home` in tools.json), never a
  real one: 20 skills, 2 MCP servers, 3 hooks (4 on build-box), and two
  findings (a skill from several providers, a hook copy that drifted).

What the page shows today (26 November 2026): tabs `Sessions`, `Fleet`,
`For you` (with a count), `Profiles on laptop`, `Tools`. Tools has no
per-machine table: show its summary line and open a Findings row instead of
the full list, whose 21 built-in rows crowd it. At 390 px Sessions becomes
cards.
