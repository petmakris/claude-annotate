# Bulldozer run bd1125b: the talk side panel, built from the side panel study

## The owner's words (25 Nov 2026, verbatim)

> All problems accepted for fixing. Start a huge new bulldozer run targeted For those problems,

He said this after reading the side panel study (`docs/proposals/2026-11-25-talk-panel/`): fix all of its 99 confirmed findings, build its quick fixes and its five recommended steps.

## Scope of this run (replaces bd1125's scope below)

- The talk call page's side panel (`skills/talk/static/call.js`, `call.css`, `call.html`), the server parts it needs (`skills/talk/talk.py`, `live_turns.py`, `talk_client.py`), the guide that describes it (`skills/talk/SKILL.md`, `references/call-page.md`, the repo's `CLAUDE.md`), and the stage defects the panel's testers hit (`skills/stage/`, `skills/_shared/`).
- Run folder: `.scratch/run/` of the worktree `claude-annotate-bd1125b`, run branch `bd1125b` checked out there. Fix jobs work in their own worktrees branched from `bd1125b`.
- The ledger starts with the study's findings (`S-<study id>`), its quick fixes (`QF-n`) and its five steps (`STEP-n`), all `confirmed`.
- The trials: unsuspecting personas drive the rebuilt panel on this branch's own talk server (silent engine) through Playwright while a responder agent answers as a /talk session.

---

The bd1125 brief follows; its method, rules and stop threshold apply, its scope does not.

# Bulldozer run bd1125: claude-annotate's /talk and /stage

## The owner's words (25 Nov 2026, verbatim)

> I want you to run the bulldozer against /talk and the skill stage
>
> This is something that I use a lot, and I want it to be heavily debugged and fixed from multiple perspectives. And I'm also eager not only for bug fixing and making its code robust, but also some ideas of how it could be better without getting stupid small additional stuff. I'm asking for core fixes, behavioral ideas, how it can explain things better. For example, it has so many tools right now available for presenting information, and 9 out of 10 it shows up the table component, which is currently really badly implemented. So you know what you can do? I want you to use workflows, the bulldozer, and as many tools as you want. I have all the quota needed. Don't spare tokens, and try to find topics that they require nice and heavy visual explanations, and make unsuspected agents To be presented with this information, and see what goes wrong. This is very important. This is a significantly important tool, and I want it to be improved by any possible direction

## What this run is

The method of lomem's bulldozer (`~/projects/lomem/.claude/skills/bulldozer/`: `methods.md` § "What counts as a finding", § "Severity", § "The stop rule"; `rules.md`), applied to a repo that is not lomem. Nothing lomem-specific applies: no sandbox, no `lomem land`, no Lungo plan, no flows, no journeys.

- **Repo:** `~/projects/claude-annotate` (Petros' personal tooling: change, reinstall, merge and push without asking). Read its `CLAUDE.md` first; it wins over this brief on how the repo works.
- **Scope:** `skills/talk/`, `skills/stage/`, and what they draw with in `skills/_shared/` (visuals, static) and the annotate block-kind specs they use. The fleet plugin and other skills are out of scope.
- **Run branch:** `bd1125`, checked out at `wt/` in this folder. Fix jobs work in their own worktrees branched from `bd1125` and land on `bd1125` only. Nothing reaches `main` until the run ends; the orchestrating session merges and pushes.
- **Run folder:** this folder. `ledger.json` (shape: the bulldozer's SKILL.md § "The run's ledger", minus Lungo fields), `findings/r<N>/<area>.json`, `trials/`, `evidence/`, `ideas.md`, `experiment-log.md`, `decisions-made-alone.md`, `report/`.

## How this run differs from a lomem run (the owner's words win)

1. **Redesign is in scope where the owner asked for it.** The table board is "really badly implemented": rework it properly (rendering, reveal, pointing, wide and long tables, phones, TV). The answer guidance that makes sessions pick a table "9 out of 10" times is in scope: the skill's text (`skills/talk/SKILL.md`, `demo.md`) may be rewritten so a session picks the board that teaches best.
2. **Ideas are wanted, but not small stuff.** "Core fixes, behavioral ideas, how it can explain things better ... without getting stupid small additional stuff." An idea is a change to how a session explains (what it puts on the stage, in what order, how the voice and the board work together) or a change to a board that makes it teach better. A cosmetic toggle, a new setting nobody asked for, or a small extra is not an idea worth building. Ideas the judge rates core go to a committee of three; a majority builds it this run.
3. **Unsuspecting agents.** Topics that need heavy visual explanation are answered by an author agent that only knows it is a Claude session on a /talk call (it reads `skills/talk/SKILL.md` as any session would, and is not told it is being tested). The answer is rendered in a real browser through the run's harness. A viewer agent who only sees the screenshots and the spoken words (not the source, not the spec, not that this is a test) says what it learned and what confused it. What went wrong becomes findings.
4. **No money.** Never call Azure speech: it is billed per character. The harness uses a free path (a silent or local engine), and never the live `dev.talk` server on port 8766 or the user's open calls.
5. **Live services are the user's.** Never restart, stop or reconfigure `dev.talk` or `dev.webcompanion` during the run; the harness runs its own talk server from the run's code on its own port. Stop processes by PID only.
6. **Tests.** The suite: `uv run -q --with-requirements requirements-test.txt python -m pytest skills fleet/tests -q` in the job's checkout. A guard test counts with two runs of that test alone: failing with the fix removed, passing with it restored (paste both into the finding's notes). The suite stays browser-free (the repo's rule); browser checks are the harness's, outside the suite.
7. **Commits:** one line each, no body, no trailers, no attribution.

## Stop threshold

The bulldozer's: another round only while the last round confirmed at least 5 new serious findings (severity 3 or 4, no `follows`). At most 3 rounds.
