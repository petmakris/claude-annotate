# Bulldozing /talk and /stage

A bulldozer run reviews talk and the stage from every side, keeps only the findings three skeptics fail to refute, fixes them in a few batch jobs per round, and goes on while a round confirms at least 5 new serious findings (at most 3 rounds). The method is lomem's bulldozer (`~/projects/lomem/.claude/skills/bulldozer/`), without its lomem parts.

What makes it work here is the **trials**: a session that does not know it is tested answers a question that needs heavy visuals, `tools/talk_render/` renders that answer in a real browser exactly as a call shows it (silent speech, no Azure), and a viewer who sees only the screenshots and the spoken words says what it learned and what confused it. An analyst traces each problem to the code or to the guidance.

## Running one

1. Make the run folder and its branch (run name `bdMMDD`):
   ```
   RUN=~/projects/dashboard/.scratch/bulldozer-talk-<name>; mkdir -p $RUN/{findings,trials,report,evidence}
   git -C ~/projects/claude-annotate branch <name> main
   git -C ~/projects/claude-annotate worktree add $RUN/wt <name>
   echo '{"app":"claude-annotate talk+stage","run":"<name>","findings":[]}' > $RUN/ledger.json
   ```
   Copy `bd1125/brief.md` to `$RUN/brief.md` and put the owner's words of this run at its top.
2. One round per workflow invocation (a round starts about 500 agents; a workflow stops at 1000):
   `Workflow({name: "bulldozer-talk-stage", args: {run: "$RUN", name: "<name>", startRound: 1}})`, then `startRound: 2` and `3` while the round's result says another round is warranted. The last round writes the report.
3. Then the finishing pass, which fixes every entry the rounds left `confirmed`:
   `Workflow({name: "bulldozer-talk-stage-finish", args: {run: "$RUN", name: "<name>"}})`.
   bd1125 needed it for 63 entries: a judge batches only part of a round's findings.
4. Fast-forward main to the run branch, push (the pre-push hook runs the suite), `uv run --script skills/talk/talk.py --restart`, remove the worktree and the branch.

The workflows are `.claude/workflows/bulldozer-talk-stage.js` and `bulldozer-talk-stage-finish.js`.

## Runs

| Run | Date | Result |
|---|---|---|
| [bd1125](bd1125/report/index.html) | 25 Nov 2026 | 164 findings fixed in 3 rounds and a finishing pass, 12 ideas built by committee vote, the table board rebuilt; fresh sessions picked a table in 7 of 13 answers before, 1 of 19 after. `ledger.json` holds every finding with its evidence, guard and commit |
