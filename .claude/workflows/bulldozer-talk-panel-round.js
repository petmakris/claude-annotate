export const meta = {
  name: 'bulldozer-talk-panel-round',
  description: 'One trial round on the talk side panel: unsuspecting personas use the rebuilt panel with a responder session, analysts tie reports to code, three skeptics per finding, a judge, fix batches in worktrees, landing, the suite',
  phases: [{ title: 'Personas' }, { title: 'Trials' }, { title: 'Recheck' }, { title: 'Analyse' }, { title: 'Refute' }, { title: 'Judge' }, { title: 'Fix' }, { title: 'Close' }, { title: 'Land' }, { title: 'Check' }],
}

// args: { root, run, name, round, harness: '<usage text>', recheck: bool }
const ROOT = args.root
const RUN = args.run
const NAME = args.name
const R = args.round
const H = `${RUN}/harness`
const T = `${RUN}/trials/r${R}`
const PRE = `You are a job of bulldozer run ${NAME} on claude-annotate's /talk side panel, round ${R}. Read ${RUN}/brief.md first; its rules win. The run branch ${NAME} is checked out at ${ROOT} (never edit files there). The repo's rules are in CLAUDE.md. Never call Azure speech, never touch the live talk server on port 8766 or restart webcompanion or talk services, stop processes only by PID. The repo is public: nothing committed may hold home paths, machine names or company names.`

const HARNESS = `The trial harness (${H}):
${args.harness}
Every command that needs a round folder takes TRIAL_DIR=${T}.`

const PERSONA_REPORT = {
  type: 'object',
  properties: {
    persona: { type: 'string' }, turns_sent: { type: 'number' },
    worked: { type: 'array', items: { type: 'string' } },
    confused_or_annoyed: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, shot: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'major', 'minor'] } }, required: ['what', 'shot', 'severity'] } },
    could_not_find: { type: 'array', items: { type: 'string' } },
    would_change: { type: 'array', items: { type: 'string' } },
    best_shots: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, caption: { type: 'string' } }, required: ['file', 'caption'] } },
    feel: { type: 'string' }, rating_out_of_10: { type: 'number' },
  },
  required: ['persona', 'turns_sent', 'worked', 'confused_or_annoyed', 'could_not_find', 'would_change', 'best_shots', 'feel', 'rating_out_of_10'],
}
const PERSONA = { type: 'object', properties: {
  key: { type: 'string' }, start: { type: 'string', description: 'pw start options: --size WxH, --phone, --dark, --mic' },
  topics: { type: 'array', items: { type: 'string' } }, who: { type: 'string' }, goal: { type: 'string' },
  rules: { type: 'string' }, turns: { type: 'number' }, responder: { type: 'string' },
  seed: { type: 'object', properties: { n: { type: 'number' }, what: { type: 'string' }, away_hours: { type: 'number' } }, required: ['n', 'what', 'away_hours'] },
}, required: ['key', 'start', 'topics', 'who', 'goal', 'rules', 'turns', 'responder'] }

// ---------------------------------------------------------------- Personas
phase('Personas')
const cast = await agent(`${PRE}

Write 14 fresh personas for round ${R} of trials of a voice assistant page (talk's call page: a user types or speaks a question, an AI session answers aloud with the text and sometimes a board: a table, a diagram, code). Each persona is a real person with a name, an age, a reason and habits, who knows nothing about how the page is built. Use this spread, one each, keys as given:
first (first time ever, 1440x900), power (a daily user with three calls open in three tabs, 1440x900, three topics), phone (390x844 --phone, uses touch only), tv (1920x1080, the page on a TV 3 m away; judge every shot from the sofa), keyboard (keyboard only, never the mouse), screenreader (blind, learns the page only through ax(), the accessibility tree, and the keyboard), interrupter (sends a correction or a new question while an answer is still coming, changes their mind), returning (back after several hours to a conversation of 8 to 10 answers that is already there; give seed {n, what, away_hours}), greek (writes in Greek, the topic in Greek), typist (types long messages with several paragraphs, Shift+Enter, never voice), listener (mostly not looking at the screen, listens, glances every few minutes), finder (looks for something said in an earlier answer of a long conversation; give seed), mic (prefers to speak; the browser has a fake microphone, --mic), tinkerer (small dark screen 1280x720 --dark, explores every setting and control).
Topics: new ones, not used before in this run: ${R === 1 ? 'pick freely across science, history, cooking, money, travel, health, and two about this code repository (the talk server or the stage), since code topics get code boards' : `avoid these earlier topics: ${(args.usedTopics || []).join('; ')}`}. Each persona's goal is concrete and needs 5 to 8 turns. rules says how they use the browser (touch, keyboard only, ax() only, Greek, mostly not looking, long typed messages) or is empty. responder says, in a few words, who the answering session talks with.`, { label: 'cast', phase: 'Personas', schema: { type: 'object', properties: { personas: { type: 'array', items: PERSONA } }, required: ['personas'] } })
const people = cast.personas.slice(0, 14)
log(`Cast: ${people.map((p) => p.key).join(', ')}`)

// ---------------------------------------------------------------- Trials
const UP = { type: 'object', properties: { calls: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, url: { type: 'string' }, topic: { type: 'string' } }, required: ['id', 'url', 'topic'] } } }, required: ['calls'] }
const upPrompt = (p) => `${HARNESS}

Start the calls for trial "${p.key}" on the run branch and report them: run TRIAL_DIR=${T} ${H}/callctl up r${R}-${p.key} --repo ${ROOT} --pace 0.8 ${p.topics.map((t) => `--topic ${JSON.stringify(t)}`).join(' ')} and return each printed CALL line as {id, url, topic}.`

const seedPrompt = (p, call) => `${PRE}
${HARNESS}

Prepare an earlier conversation on a voice call page ("talk"), so that a user who comes back later finds it there. Read ${ROOT}/skills/talk/SKILL.md and skim skills/talk/references/boards.md for the reply format and board tags. Write ${T}/${p.key}/seed.json: a list of ${p.seed.n} objects {"q": what the user typed, "a": the session's answer in talk's reply format}. ${p.seed.what}
Mix answer lengths (some 2 sentences, some 10 to 14), include at least 4 boards and a few [[key: ...]] lines. Then make it real for a returning user: open the call in the persona's browser profile first if the harness keeps profiles (the user saw the start of it), seed it with TRIAL_DIR=${T} ${H}/callctl seed r${R}-${p.key} --call ${call.id} ${T}/${p.key}/seed.json, and, if the harness can age the visit (a profile's last-seen time, a clock offset), make the user's last visit ${p.seed.away_hours} hours ago. Fix and re-run a failed turn. Return the questions and any board: lines.`

const personaPrompt = (p, calls) => `You are role-playing a real person. Stay in character the whole time.

WHO YOU ARE
${p.who}

WHAT YOU WANT TODAY
${p.goal}

A friend set you up with a voice assistant page you can talk with (or type to) to learn about things. The assistant on the other end answers you; its answers are read aloud and shown on the page, sometimes with pictures or tables. That is all you were told. Your address${calls.length > 1 ? 'es (one per conversation you already have open)' : ''}:
${calls.map((c) => `- ${c.topic}: ${c.url}`).join('\n')}

HOW YOU USE THE BROWSER
You cannot see a screen directly, so you drive a real browser through a helper. Your browser is named "r${R}-${p.key}".
- Open it once:  TRIAL_DIR=${T} ${H}/pw start r${R}-${p.key} ${p.start} --url ${calls[0].url}
- Act:           TRIAL_DIR=${T} ${H}/pw do r${R}-${p.key} '<python>'   (Playwright sync API; \`page\` is the current tab; \`shot("label")\` saves a screenshot and prints its path, \`ax()\` returns the accessibility tree as text, \`newtab(url)\`, \`tab(i)\`, \`pages()\`, \`time\`, print().)
- Look:          after shot(...), open the printed PNG with the Read tool. Look often: before and after each thing you do.
Act like a human: find controls by what you see or by role and name (page.get_by_role, get_by_placeholder, get_by_text, keyboard.press, mouse, touchscreen.tap on a phone). ${p.rules || ''}
Do NOT read any source code or files on this computer, do not use page.evaluate to poke at the page's internals, and do not open other addresses. You are a normal user of this page.
The assistant needs time to think: after you send something, wait like a person would (time.sleep in steps of 10 to 30 seconds, looking in between). An answer can take a minute or two. If nothing comes after about 3 minutes, act as you naturally would.

HOW LONG
Send at least ${p.turns || 6} messages over roughly 25 to 40 minutes of your own time, following your goal and habits. Take at least 12 screenshots with labels that say what you were doing. Keep a running diary in ${T}/${p.key}/notes.md (what you tried, expected, what happened, how it felt, with the screenshot files).

WHEN YOU ARE DONE
Close your browser (TRIAL_DIR=${T} ${H}/pw stop r${R}-${p.key}). Then answer honestly, in your character's voice: what worked, what confused or annoyed you (each tied to a screenshot file and how bad), what you looked for and could not find, what you would change, a rating out of 10. Be concrete about the page itself, not the topic. Also save that answer as JSON in ${T}/${p.key}/report.json.`

const responderPrompt = (p, call) => `You are the AI session on the other end of a voice call page ("talk"), answering a user on the call "${call.topic}". You never see the user; you get their turns through a command line client, exactly as a real /talk session does.

Read first: ${ROOT}/skills/talk/SKILL.md (the turn loop, choosing the board, writing the answer) and skim ${ROOT}/skills/talk/references/boards.md and server.md. Follow them as a real session would: the same reply format, statuses, boards (code boards read from the repository at ${ROOT}), points and [[key: ...]] lines, and whatever the guide says about cancelled, superseded or taken-back turns.

The client (always this wrapper, never talk_client.py directly, never another port):
  TRIAL_DIR=${T} ${H}/callctl client r${R}-${p.key} -- <talk_client.py arguments, with --call=${call.id}>
for example "doorbell --call=${call.id} --wait 90", "reply <turn id> --call=${call.id} --status 'a few words'", and "reply <turn id> --call=${call.id} <<'EOF' ... EOF". Read its output: board: lines tell you a board was not shown as asked; fix it next time.

Who you are talking with: ${p.responder}.
Behave like a real working session so the page fills as in daily use: usually a status first, then real work (read the code for a code topic, else think, sometimes sleep 10 to 40 s to stand for work), then the answer. Vary answers: some short, some long (8 to 15 sentences) with a board, some with two boards. Answer in the user's language. Fold corrections in.
Loop: doorbell, answer, doorbell again. After each doorbell that returns no turn, stop if the file ${T}/${p.key}/finished-${call.id} exists. Also stop on TALK_END or after 75 minutes in all. Touch no other process, port or file outside ${T}.
Save a short log to ${T}/${p.key}/responder-${call.id}.txt and return it: turns answered, boards used, board: lines, anything odd about the client or server.`

async function runPair(p, phase) {
  const up = await agent(upPrompt(p), { label: `up:${p.key}`, phase, schema: UP, effort: 'low' })
  const calls = up.calls
  if (p.seed) await agent(seedPrompt(p, calls[0]), { label: `seed:${p.key}`, phase })
  const persona = agent(personaPrompt(p, calls), { label: `persona:${p.key}`, phase, schema: PERSONA_REPORT })
    .then(async (r) => { await agent(`Run this shell command and return its output: mkdir -p ${T}/${p.key} && ${calls.map((c) => `touch ${T}/${p.key}/finished-${c.id}`).join(' && ')} && echo ok`, { label: `finish:${p.key}`, phase, effort: 'low' }); return r })
  const responders = calls.map((c, i) => agent(responderPrompt(p, c), { label: `responder:${p.key}${calls.length > 1 ? i : ''}`, phase }))
  const [r, ...logs] = await Promise.all([persona.catch(() => null), ...responders.map((x) => x.catch(() => null))])
  await agent(`Run and return the output: TRIAL_DIR=${T} ${H}/callctl down r${R}-${p.key}; TRIAL_DIR=${T} ${H}/pw stop r${R}-${p.key} 2>/dev/null; echo down`, { label: `down:${p.key}`, phase, effort: 'low' })
  return { key: p.key, persona: p, calls, report: r, responder_logs: logs }
}

// Two batches of seven: a persona and its responders must run at the same time, and a workflow runs at most 16 agents at once.
phase('Trials')
const half = [people.slice(0, 7), people.slice(7)]
const trials = []
for (const [bi, group] of half.entries()) {
  log(`Trial batch ${bi + 1}: ${group.map((p) => p.key).join(', ')}`)
  const res = await parallel(group.map((p) => () => runPair(p, 'Trials')))
  trials.push(...res.filter(Boolean))
}

// ---------------------------------------------------------------- Recheck the study's findings (round 1 only)
let recheck = []
if (args.recheck) {
  phase('Recheck')
  const groups = args.recheckGroups
  log(`Re-checking the study's findings on the rebuilt panel in ${groups.length} groups`)
  recheck = (await parallel(groups.map((g) => () => agent(`${PRE}
${HARNESS}

Re-check these entries of ${RUN}/ledger.json on the rebuilt panel (the run branch at ${ROOT}): ${g.ids.join(', ')}. Each was found by the side panel study on the old panel; the build wave has since marked them fixed, closed or still confirmed. For each, reproduce what the study's tester did on the rebuilt panel: start your own call with the harness (key r${R}-re-${g.key}), answer turns yourself with callctl client, drive a browser with pw, shoot, look. Stop your browser and server at the end. Say for each: does it still reproduce (a user would still meet it), with the shot.`, { label: `recheck:${g.key}`, phase: 'Recheck', schema: { type: 'object', properties: { results: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, reproduces: { type: 'boolean' }, how: { type: 'string' }, shot: { type: 'string' } }, required: ['id', 'reproduces', 'how', 'shot'] } } }, required: ['results'] } })))).filter(Boolean).flatMap((x) => x.results)
}

// ---------------------------------------------------------------- Analyse and refute
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, title: { type: 'string' }, what_happened: { type: 'string' },
  shots: { type: 'array', items: { type: 'string' } }, where: { type: 'array', items: { type: 'string' }, description: 'file:line in the run branch, a few words each' },
  cause: { type: 'string' }, fix: { type: 'string' },
  scope: { type: 'string', enum: ['panel', 'panel-stage-meeting', 'stage-only', 'server', 'guide', 'harness-artifact'] },
  severity: { type: 'number', description: 'Nielsen 0-4: 1 cosmetic, 2 minor, 3 major, 4 breaks a task or loses data. A layout or look finding is 3 or 4 or nothing' },
  follows: { type: 'string', description: 'the ledger id of a fix of this run that caused it or left it half done (most entries fixed in the build wave are STEP-n, QF-n or S-...), else empty' },
  study_match: { type: 'string', description: 'the ledger id of the study finding it repeats, else empty' },
  reproduced: { type: 'string' },
}, required: ['id', 'title', 'what_happened', 'shots', 'where', 'cause', 'fix', 'scope', 'severity', 'follows', 'study_match', 'reproduced'] } } }, required: ['findings'] }
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' }, correction: { type: 'string' } }, required: ['refuted', 'reason', 'correction'] }
const CONTEXT = `${PRE}
Unsuspecting personas drove the rebuilt call page of /talk (run branch ${NAME} at ${ROOT}) through Playwright on private talk servers with a silent voice, answered by responder agents. Trial files: ${T}/<key>/ (report.json, notes.md, responder-*.txt) and the shots under ${T}/r${R}-<key>/ or as their paths say. Known harness artifacts: the voice is silent; there is no speech recognition, so the mic flow ends in "Nothing was heard"; responders are slow (1 to 9 minutes); personas read screenshots, so small text can be misread. What counts as a finding: lomem's bulldozer methods.md § "What counts as a finding" and § "Severity" (~/projects/lomem/.claude/skills/bulldozer/methods.md).`
const LENSES = ['does the code on the run branch really behave this way (read the lines)', 'does the screenshot really show it, and would a normal user meet it outside this harness', 'are the cause, the severity and follows right, and is it the page rather than the content or the responder']

phase('Analyse')
const judged = await pipeline(trials,
  (t) => agent(`${CONTEXT}
${HARNESS}

You are the analyst for persona "${t.key}". Read ${T}/${t.key}/report.json (or this copy: ${JSON.stringify(t.report).slice(0, 6000)}), notes.md and the responder logs. Turn it into findings about the page, each tied to file:line on the run branch and to the shots that show it (open them). Merge duplicates; split one complaint with two causes. When the code alone does not settle a behaviour, reproduce it with the harness (key r${R}-an-${t.key}; stop it after). Ids "r${R}-${t.key}-1", "-2", ... Set follows when the problem comes from this run's build (git -C ${ROOT} log --oneline cf001c1..${NAME} lists its commits; the ledger says which entry each fixed).`, { label: `analyst:${t.key}`, phase: 'Analyse', schema: FINDINGS }),
  (out, t) => parallel((out?.findings || []).filter((f) => f.severity >= 2).map((f) => async () => {
    const votes = await parallel(LENSES.map((lens, i) => () => agent(`${CONTEXT}

A finding from persona "${t.key}":
${JSON.stringify(f, null, 1)}

You are a skeptic. Your lens: ${lens}. Try hard to REFUTE it: open the shots, read the cited code on the run branch, run a command or the harness where it settles the claim. Refute it when it is false, a misreading, caused only by the harness, already handled in a way a normal user would find, or not about the page. Do not refute it for being minor or about the stage. If real but partly wrong, keep it and say what to correct.`, { label: `skeptic:${f.id}:${i + 1}`, phase: 'Refute', schema: VERDICT })))
    const v = votes.filter(Boolean)
    return { ...f, persona: t.key, votes: v, survives: v.filter((x) => x.refuted).length < 2 }
  })))
const all = judged.filter(Boolean).flat().filter(Boolean)
const kept = all.filter((f) => f.survives)
log(`${all.length} findings of severity 2 or more, ${kept.length} survive three skeptics`)

// ---------------------------------------------------------------- Judge
phase('Judge')
const BATCH = { type: 'object', properties: { key: { type: 'string' }, title: { type: 'string' }, files: { type: 'string' }, ids: { type: 'array', items: { type: 'string' } }, instructions: { type: 'string' } }, required: ['key', 'title', 'files', 'ids', 'instructions'] }
const judge = await agent(`${CONTEXT}

You are the judge of round ${R}. You alone write ${RUN}/ledger.json now (keep every entry; it must parse).
1. Enter each surviving finding below as an entry: id as given, round ${R}, title, where, evidence (what happened), shots, cause, fix, scope, severity, follows (null when empty), skeptics (their corrections), state confirmed. Apply the skeptics' corrections. Drop one that an entry of this run already holds (same cause): add its persona to that entry's evidence instead. A study_match on an entry that the build wave marked fixed or rejected sends that entry back to confirmed with a note; the new finding is then dropped as a duplicate of it. Severity 2 findings about looks only are dropped (methods.md).
2. Apply the re-check results below: an entry that still reproduces goes back to state confirmed with the re-check's shot and how in a note; one that does not stays as it is.
3. Count the new serious findings of this round: entries of round ${R}, state confirmed, severity 3 or 4, follows null.
4. Group every entry now confirmed (this round's and any sent back) into 3 to 5 fix batches by area of code, so no two batches change the same file as far as possible (server and TurnQueue in talk.py; the shell; the wait card; calls and return; input, keys and settings; stage). Set each entry's fix_job to "${NAME}-r${R}-<batch key>". Write precise instructions per batch.
5. Append a "Round ${R}" section to ${RUN}/experiment-log.md: personas, findings, survivors, the count against the threshold of 5 and your ruling.

Survivors:
${JSON.stringify(kept.map((f) => ({ id: f.id, persona: f.persona, title: f.title, what: f.what_happened, shots: f.shots, where: f.where, cause: f.cause, fix: f.fix, scope: f.scope, severity: f.severity, follows: f.follows, study_match: f.study_match, corrections: f.votes.map((v) => v.correction).filter(Boolean) })), null, 1)}

Re-check results:
${JSON.stringify(recheck, null, 1)}`, { label: 'judge', phase: 'Judge', effort: 'high', schema: { type: 'object', properties: { new_serious: { type: 'number' }, entered: { type: 'number' }, sent_back: { type: 'array', items: { type: 'string' } }, batches: { type: 'array', items: BATCH } }, required: ['new_serious', 'entered', 'sent_back', 'batches'] } })
log(`Judge: ${judge.entered} entered, ${judge.sent_back.length} sent back, ${judge.new_serious} new serious; ${judge.batches.length} fix batches`)

// ---------------------------------------------------------------- Fix
phase('Fix')
const RESULT = {
  type: 'object',
  properties: {
    branch: { type: 'string' }, worktree: { type: 'string' }, commits: { type: 'array', items: { type: 'string' } },
    entries: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, state: { type: 'string', enum: ['fixed', 'propose-close', 'confirmed'] }, commit: { type: 'string' },
      guard: { type: 'string' }, guard_proof: { type: 'string' }, felt: { type: 'boolean' }, notice: { type: 'string' },
      shots: { type: 'array', items: { type: 'string' } }, reason: { type: 'string' },
    }, required: ['id', 'state', 'reason'] } },
    suite: { type: 'string' }, notes: { type: 'string' },
  },
  required: ['branch', 'worktree', 'commits', 'entries', 'suite', 'notes'],
}
const fixPrompt = (b) => `${PRE}

You are fix batch ${b.key} of round ${R}: ${b.title}. Files: ${b.files}. Entries: ${b.ids.join(', ')} (read each in ${RUN}/ledger.json; never write the ledger, return your results).
Instructions:
${b.instructions}

1. Worktree: git -C ${ROOT} worktree add ${RUN}/wt-r${R}-${b.key} -b ${NAME}-r${R}-${b.key} ${NAME}. Work only there. Split independent parts across sub-agents if it helps; you own the result.
2. A change a person can see: shoot before (from ${ROOT}) and after (your worktree) at 1440 px, 390 px and dark into ${RUN}/evidence/<entry id>/ (before-1440.png, after-1440.png, before-390.png, after-390.png, after-dark.png), with tools/talk_render or a small Playwright script on the checkout's own talk server (tools/talk_render/serve.py, free port). Look at them. Load the petros-skills:house-style skill before changing UI.
3. Each bug gets a browser-free guard test with exact values, run alone twice with PYTHONDONTWRITEBYTECODE=1: failing with the fix removed, passing with it restored; paste the last lines of both into guard_proof. Layout-only fixes proved by shots get guard "none: <why>".
4. An entry that truly needs no change is propose-close with the reason (a panel of three votes); never to skip work.
5. Update CLAUDE.md, skills/talk/SKILL.md, references and demo.md (line numbers) in the same commits when the change touches what they say.
6. Full suite once at the end in your worktree (uv run -q --with-requirements requirements-test.txt python -m pytest skills fleet/tests -q); fix what you broke.
7. One-line commits on your branch, staged by path; do not merge.`
const fixed = (await parallel(judge.batches.map((b) => () => agent(fixPrompt(b), { label: `fix:${b.key}`, phase: 'Fix', schema: RESULT, effort: 'high' })))).filter(Boolean)

// ---------------------------------------------------------------- Close
phase('Close')
const proposals = fixed.flatMap((r) => r.entries.filter((e) => e.state === 'propose-close').map((e) => ({ ...e, batch: r.branch })))
const closures = await parallel(proposals.map((p) => async () => {
  const lenses = ['a user of the panel who hit this problem', `a skeptical reviewer of the code on branch ${p.batch}`, 'the run owner, who said all problems are accepted for fixing']
  const votes = await parallel(lenses.map((lens, k) => () => agent(`${PRE}

Ledger entry ${p.id} (in ${RUN}/ledger.json) is proposed for closing without a fix, because: ${p.reason}
Judge it as ${lens}. Check the claim in the code of branch ${p.batch} (git -C ${ROOT} show ${p.batch}:<path>) and the evidence. Agree only when it truly needs no change. Default to disagree when in doubt.`, { label: `close:${p.id}:${k + 1}`, phase: 'Close', schema: { type: 'object', properties: { agree: { type: 'boolean' }, reason: { type: 'string' } }, required: ['agree', 'reason'] }, effort: 'medium' })))
  return { id: p.id, reason: p.reason, votes, closed: votes.filter(Boolean).filter((v) => v.agree).length >= 2 }
}))

// ---------------------------------------------------------------- Land
phase('Land')
const landed = []
for (const r of fixed) {
  if (!r.commits.length) continue
  landed.push(await agent(`${PRE}

Land branch ${r.branch} (worktree ${r.worktree}) on ${NAME}: rebase it onto ${NAME}, resolving every conflict so both sides' work survives. Run the tests of every file the rebase touched (the full suite if a conflict touched call*.js, call.css, call.html, talk.py or a test helper), fix failures with one-line commits, then git -C ${ROOT} merge --ff-only ${r.branch}, remove the worktree, delete the branch. Return the head and old=new hash pairs.`, { label: `land:${r.branch}`, phase: 'Land', schema: { type: 'object', properties: { landed: { type: 'boolean' }, head: { type: 'string' }, remap: { type: 'string' }, notes: { type: 'string' } }, required: ['landed', 'head', 'remap', 'notes'] } }))
}

// ---------------------------------------------------------------- Check
phase('Check')
const check = await agent(`${PRE}

Round ${R}'s fixes have landed on ${NAME}. In a worktree of your own (git -C ${ROOT} worktree add ${RUN}/wt-r${R}-check -b ${NAME}-r${R}-check ${NAME}): run the full suite once and fix failures; render one answer with tools/talk_render at 1440, 390 and dark and look; fix what two batches broke together. Then git -C ${ROOT} merge --ff-only ${NAME}-r${R}-check, remove the worktree and branch. Then you alone update ${RUN}/ledger.json from the fix results below (state fixed with commit remapped by the landers' pairs, guard, guard_proof, felt, notice, shots; propose-close entries whose panel closed them become rejected with the reason and the votes, the others stay confirmed with a note; confirmed stays confirmed with its reason). The file must parse. Count states.

Fix results: ${JSON.stringify(fixed.map((f) => ({ branch: f.branch, entries: f.entries })))}
Closures: ${JSON.stringify(closures.map((c) => ({ id: c.id, closed: c.closed, reason: c.reason, votes: c.votes })))}
Landers: ${JSON.stringify(landed)}`, { label: 'check', phase: 'Check', effort: 'high', schema: { type: 'object', properties: { suite: { type: 'string' }, fixed: { type: 'string' }, head: { type: 'string' }, states: { type: 'string' } }, required: ['suite', 'fixed', 'head', 'states'] } })

return {
  round: R, new_serious: judge.new_serious, another_round: judge.new_serious >= 5 && R < 3,
  topics: people.flatMap((p) => p.topics), ratings: trials.map((t) => ({ key: t.key, rating: t.report?.rating_out_of_10, feel: t.report?.feel })),
  findings: all.length, survived: kept.length, judge, closures: closures.map((c) => ({ id: c.id, closed: c.closed })), landed, check,
}
