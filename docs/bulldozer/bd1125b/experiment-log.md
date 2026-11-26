# Experiment log, run bd1125b (talk side panel)

## Round 1

Personas (14, unsuspecting, Playwright on private talk servers with a silent voice, answered by responder agents): first, power, phone, tv, keyboard, screenreader, interrupter, returning, greek, typist, listener, finder, mic, tinkerer. A re-check wave (about 20 groups) drove the study's 118 fixed entries again.

Findings: 53 survivors of three skeptics each. Judge's ruling:
- 30 entered as new round-1 entries (state confirmed). 6 of them merge 6 further survivors of the same cause (r1-greek-2 takes r1-phone-5 and r1-listener-4; r1-typist-3 takes r1-tv-7; r1-listener-3 takes r1-returning-5 and r1-finder-6; r1-finder-1 takes r1-returning-3).
- 15 dropped as duplicates of an entry of this run, their personas added to that entry: r1-first-1, r1-keyboard-2 and r1-screenreader-1 to S-listener-1; r1-first-2 to S-listener-6; r1-first-3 and r1-finder-2 to S-tinkerer-6; r1-first-4, r1-returning-4, r1-listener-2 and r1-typist-2 to S-finder-2; r1-greek-1 to S-greek-2; r1-tinkerer-1 to QF-10; r1-tv-1 to S-tv-1; r1-mic-3 to S-tv-7; r1-keyboard-3 to QF-2.
- 2 dropped by severity: r1-typist-5 (compose box stops at 120 px: severity 2 and only a look; the box scrolls), r1-tinkerer-3 (follow is per visit by design: severity 1, wording only).
- Skeptics' corrections applied to every entry: for example r1-phone-4 (the stage popup has no X; close it on frame, board change and answer start), r1-finder-4 (a table has no tap handler at all), r1-tv-6 and r1-phone-3 (no scene advice: scenes are retired; 'pinned first' means first in the list), r1-listener-1 and r1-power-3 (merging queued questions is deliberate; the defect is missing feedback).

Re-check results applied: 6 entries still reproduce and go back to confirmed (S-tv-7, S-phone-7, S-tinkerer-7, S-tv-1, S-interrupter-1, QF-2); 6 more go back because a round-1 finding carried them as its study_match (S-listener-1, S-listener-6, S-tinkerer-6, S-finder-2, S-greek-2, QF-10). Total sent back: 12. The other 106 stay fixed. Note: S-listener-1 and S-listener-6 did not reproduce in the re-check wave's own case, but three personas met the same cause in the trials, so the judge reopened them.

New serious findings (round 1, confirmed, severity 3 or 4, follows null): 6: r1-phone-1, r1-phone-2, r1-phone-3, r1-mic-1, r1-tv-2, r1-screenreader-2. Threshold: another round only while at least 5. 6 >= 5, so round 2 runs (at most 3 rounds). Close call: without r1-tv-2 (a look at severity 3) it is 5, still at the threshold. 15 new entries have a non-null follows (the build left them half done or caused them: mostly STEP-3, STEP-2 and STEP-5), 8 of them severity 3, so they do not count.

Ruling on the fix batches (5, by area of code, one owner per file): wait (call-wait.js, call-wait.css, talk.py, live_turns.py, talk_client.py), shell (call-shell.js, call-shell.css, call-player.js), input (call.html, call.js, call.css, call-input.js, call-return.js, call-calls.js, call-live.js, new call-i18n.js), stage (skills/stage/static/*, call-stage.js), guide (SKILL.md, references, CLAUDE.md, demo). Shared entries have one owner and name the other batches' parts (S-phone-7, S-tinkerer-6). The i18n entry S-greek-2 touches every file: its owner lands last in the round and rebases to route the literals of call-wait.js and call-shell.js.

## Round 2

Personas (14, unsuspecting, Playwright on private talk servers with a silent voice, answered by responder agents; the first round's list again): first, power, phone, tv, keyboard, screenreader, interrupter, returning, greek, typist, listener, finder, mic, tinkerer. No re-check wave this round (the list was empty).

Findings: 51 survivors of three skeptics each. Judge's ruling:
- 33 entered as new round-2 entries (state confirmed), skeptics' corrections applied (wrong where-lines fixed, causes narrowed, several fixes redirected to the real file). 12 further survivors are merged into them (same cause): r2-tv-3 into r2-tinkerer-1 (the Autoplay tip wider than the panel); r2-tv-2 into r2-tv-1 (TV legibility of lanes); r2-mic-1 and r2-tinkerer-3 into r2-listener-1 (the visible .m-reading list, three personas); r2-finder-1 and r2-finder-2 into r2-returning-1 (the boards icon); r2-listener-4 into r2-returning-2 (the cramped Earlier list); r2-greek-4, r2-typist-2 and r2-listener-3 into r2-returning-3 (the Now card's text window); r2-mic-3 into r2-listener-2 (the 'still shows' line); r2-greek-3 into r2-first-2 (the Autoplay chip taking the strip's room).
- 2 sent back by a study_match, new finding dropped as a duplicate: S-screenreader-5 (r2-power-1: the Autoplay switch's accessible name does not start with its visible word, no announce) and S-first-1 (r2-tinkerer-5: Play names answer 5 inside the answer-6 card).
- 4 dropped: r2-first-5 (empty-stage tiles: severity 1, decorative and redundant with the sentence beside them), r2-power-3 ('Board 2 of 2': the count is accurate and the arrow reaches Key points, a wording surprise at severity 2 that is a look; its study_match S-first-7 is about what the Key points chip means, a different cause, so S-first-7 is not reopened), r2-tv-5 (small panel texts at TV size: severity 2 and looks only; the speed chip and Expand all are already scaled), r2-typist-5 (the composer stops at 120 px: the same ruling as r1-typist-5, severity 2, a look, the box scrolls).
- Two study_match values were not applied as sent-back: r2-power-2 (S-power-4 is the popup's dots; this is a dead span in the strip, a different cause, entered as new with follows null) and r2-power-3 (above).
- Merged entries take the highest severity of their parts, except where the skeptics lowered it: r2-returning-1 is 2 (the board is one tap away), r2-typist-3 is 2 (a workaround exists; the gap is the guide), r2-finder-3 is 2.
- Entries the build caused or left half done carry follows (checked in git log against the build commits from e317a74 on): the Now card, Following strip and list (STEP-3: r2-returning-2, -3, r2-first-3, r2-tinkerer-4), the phone panel and stage split (b13d000 set --ph 52% and cut the stage from 62% to 48%: r2-phone-1, r2-phone-4 follow STEP-5), the state strip and wait card (r2-first-2, r2-tinkerer-1, r2-interrupter-2, -3, -4), the flowchart reading list added without a style (8b60e42: r2-listener-1, r2-screenreader-1 follow r1-screenreader-2), the page language (r2-greek-1, r2-greek-2 follow S-greek-2: the r1 i18n covers the panel after an answer, not the first exchange or the stage frame), the Copy icon (r2-typist-1 follows r1-typist-3). The ones with no follows predate the build: r2-first-1 (a refused board), r2-tinkerer-2 (the player claim, e398050), r2-tv-1 (lanes styles, a6491c6).

New serious findings (round 2, confirmed, severity 3 or 4, follows null): 3: r2-first-1, r2-tinkerer-2, r2-tv-1. Threshold: another round only while at least 5. 3 < 5, so the run stops after this round's fixes. Close call, stated plainly: 14 more entries of severity 3 carry a follows (build-caused or half done); if the two the build caused by the phone split (r2-phone-1) and the Key points hand pick (r2-first-3) were counted as new, the number would be 5. They are counted by the rule as written (follows set), so no round 3.

Ruling on the fix batches (5, by area of code, one owner per file; every batch adds its English and Greek words next to the related keys in call-i18n.js and rebases at landing, since the landings run one after another):
- server (talk.py, live_turns.py, talk_client.py, call-player.js, call-boot.js, SKILL.md, references, demo, the repo CLAUDE.md): r2-first-1, r2-tinkerer-2, r2-typist-3, r2-typist-1 (guide half).
- wait-calls (call-wait.js, call-wait.css, call-return.js, call-calls.js, call-calls.css): S-screenreader-5, r2-interrupter-2, -3, -4, r2-mic-2, r2-first-2, r2-tinkerer-1, r2-power-2, r2-screenreader-2.
- shell (call-shell.js, call-shell.css): S-first-1, r2-returning-1, -2, -3, r2-finder-3, r2-first-6, r2-tinkerer-4, r2-listener-2, r2-typist-4, r2-screenreader-4, and the Copy word of r2-typist-1.
- input (call-input.js, call.js, call.css, call.html, call-live.js, call-input.css, call-i18n.js structure): r2-greek-1, r2-first-4, r2-keyboard-1, r2-phone-4.
- stage (skills/stage/static/*, skills/stage tests, skills/_shared/visuals, call-stage.js): r2-listener-1, r2-screenreader-1, -3, r2-tv-1, r2-phone-1, r2-first-3, r2-finder-4, r2-greek-2.
Cross-batch rules written into the batches: r2-phone-1 and r2-phone-4 both must leave --ph alone (stage trims stage chrome, input trims panel chrome); r2-mic-2 and the Autoplay announce use globals and DOM listeners so call-input.js and call.html stay with the input batch; the stage batch reads uiLang and does not edit call-i18n.js.

## Finish

Full suite on bd1125b (uv run ... pytest skills fleet/tests -q): 3518 passed in 74.57s, first run, no failure, no fix commit needed.
Ledger (181 entries): fixed 181, confirmed 0. Nothing still confirmed.

## Finish (second pass)

Full suite on bd1125b (uv run ... pytest skills fleet/tests -q): 3528 passed in 68.29s, first run, no failure, no fix commit needed.
Ledger (186 entries): fixed 186, confirmed 0. Nothing still confirmed.

## Finish (third pass)

Full suite on bd1125b (uv run ... pytest skills fleet/tests -q): 3730 passed in 73.48s, first run, no failure, no fix commit needed.
Ledger (193 entries): fixed 192, confirmed 1.
Still confirmed: bd1125b-vote-12 (from the final vote summary, not yet checked by skeptics; the voters' shots are under .scratch/run/trials/vote/): after a correction the session drew a narrower board (a rent-only bar chart) instead of redoing the table, because the guide did not say so. Commit b818a18 changed the guide for this, but the ledger entry was not verified or moved to fixed.
