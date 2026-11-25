export const meta = {
  name: 'bulldozer-talk-stage',
  description: 'One bulldozer round on claude-annotate /talk and /stage: finders with three skeptics, unsuspecting-viewer trials, judge, idea committee, batch fixes, landing; the report after the last round',
  phases: [
    { title: 'Set-up', detail: 'render harness on its own port, baseline suite' },
    { title: 'Find', detail: 'one finder per area, three skeptics per finding' },
    { title: 'Trials', detail: 'author answers a visual topic, harness renders, unsuspecting viewer reports, analyst turns it into findings' },
    { title: 'Judge', detail: 'merge, rank, classify ideas' },
    { title: 'Committee', detail: 'three votes per core idea' },
    { title: 'Fix', detail: 'batch jobs in their own worktrees' },
    { title: 'Land', detail: 'one landing at a time on a run' },
    { title: 'Report', detail: 'final suite and the report page' },
  ],
}

const RUN = args.run
const NAME = args.name
const START = START || 1
const MAX = MAX || START
const REUSE_ROUND = REUSE_ROUND || 0
const REUSE_TRIALS = REUSE_TRIALS || []
const HARNESS = args.harness || '~/projects/claude-annotate/tools/talk_render'
const WT = `${RUN}/wt`
const PRE = `You are a job of bulldozer run ${NAME} on claude-annotate's /talk and /stage skills. Read ${RUN}/brief.md first: it holds the owner's words and the run's rules, and they win. The run branch ${NAME} is checked out at ${WT}; the repo's own rules are in ${WT}/CLAUDE.md. What counts as a finding and the 0-4 severity scale: ~/projects/lomem/.claude/skills/bulldozer/methods.md § "What counts as a finding" and § "Severity" (ignore everything lomem-specific: sandboxes, lomem land, flows, journeys, Lungo). Never call Azure speech, never touch the live dev.talk (port 8766) or dev.webcompanion services or the user's open calls, stop processes only by PID. Scratch goes in ${RUN}.`

const FINDING = {
  type: 'object',
  properties: {
    title: { type: 'string' }, where: { type: 'string', description: 'file:line or board/screen' },
    evidence: { type: 'string', description: 'what you ran or read that shows it, with output' },
    rule: { type: 'string', description: 'the written rule or expectation it breaks' },
    why_it_matters: { type: 'string' }, fix: { type: 'string' },
    size: { type: 'string', enum: ['S', 'M', 'L'] }, severity: { type: 'integer', minimum: 0, maximum: 4 },
    kind: { type: 'string', enum: ['bug', 'robustness', 'guidance', 'idea'] }, felt: { type: 'boolean' },
  },
  required: ['title', 'where', 'evidence', 'rule', 'why_it_matters', 'fix', 'size', 'severity', 'kind', 'felt'],
}
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: FINDING } }, required: ['findings'] }
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['refuted', 'reason'] }

const RENDER = `Render an answer with the run's harness: uv run --with playwright python ${HARNESS}/render.py --repo <checkout> --answer <file> --code <folder> --out <dir> [--question "what the user asked"] [--pace 1.0] [--no-phone] [--no-dark] (details in ${HARNESS}/README.md).`
let COUNT = 0

// ---------- Areas and topics ----------
const AREAS = [
  { key: 'server', ask: 'skills/talk/talk.py as a server: calls, turns, the floor across calls, the doorbell, idle end, hand-over on restart, persistence of transcript and stage, concurrency, error paths. Run things to prove each finding.' },
  { key: 'client', ask: 'talk_client.py, live_turns.py, talk_activity.py and hooks/, talk_files.py, talk_service.py, speech.py with its engines: exit codes, races, the reply/say/end contract the SKILL.md promises, partial failures, Python 3.9 compatibility.' },
  { key: 'callpage', ask: 'the call page (skills/talk/static/call.js, call.css, call.html): playback, word highlight and tap-to-play, seek and back, live mode and interruptions, following the voice vs a picked board, the panel (sides, drag, rail), phone width, TV mode, light/dark, tab hidden, reconnect. Use the harness and the node harness (skills/talk/tests/call_page.py) to prove findings.' },
  { key: 'engine', ask: 'the answer compiler and stage engine: tag parsing in talk.py (show, point, key, verbs, forgiving tags, board: warnings), scene compilation (skills/stage/scene.py, model.py), frames and the eight rules in skills/stage/SKILL.md § "What the stage keeps true", and stage.js applying frames. Write odd but plausible answers a session would write and check what compiles and what the board: lines say.' },
  { key: 'table', ask: 'the TABLE board end to end. The owner says it is shown 9 times out of 10 and is "really badly implemented". Render many realistic tables through the harness: wide (8+ columns), long (30+ rows), long cell text, numbers, code in cells, Greek, empty cells, a markdown table without a tag, pointing at rows, cells and ranges, rows arriving with sentences, updating a table in place, phone width, dark, TV. Read how it is parsed, compiled and drawn. Report every defect, and as kind=idea what a good table board for a spoken explanation would be (what it should look like and how it should step with the voice), concretely.' },
  { key: 'diagrams', ask: 'the sequence (lanes.js, sequence.py, compare before/after), flowchart (drawn as a map) and map (map.js, map_svg.py, vz.md) boards: render realistic, large and awkward specs through the harness (10+ actors, long labels, loops, alt/par groups, back edges, 25+ nodes, phone width, dark) and look at every shot. Overlaps, clipped text, wrong lighting, arrows lit without both ends, unreadable layouts.' },
  { key: 'codeboards', ask: 'the code, change, page and screen boards and the Key points board: line pointing, old lines on a change, files outside --code, refused paths (ignored files, .git, ~/.ssh), long lines, 60-line limit, a page that refuses framing, a screen spec. Also stage.py used on its own (skills/stage/stage.py show/hide/link): every source kind in its SKILL.md table, exit codes 2 and 3, --slug rules.' },
  { key: 'guidance', ask: 'how a session is taught to explain: skills/talk/SKILL.md and demo.md (and skills/stage/SKILL.md). The owner says sessions pick the table "9 out of 10" times among many boards. Find why in the text: what nudges toward tables, what makes the other boards look costly or risky, contradictions, rules buried in walls of text, retired features still described, examples that teach the wrong habit. Measure it: give 6 fresh sub-agents (Agent tool) each a different explanatory question and only the SKILL.md, ask each to write its answer, count the boards they choose. Report guidance findings with the exact text to change, and ideas for how the guidance could make explanations better.' },
  { key: 'robust', ask: 'robustness and security of what the call serves to other machines: path traversal on code/change/page/screen boards and static files, HTML/JS injection through answer text, board titles, table cells, spec labels, Mermaid, scene HTML; the call id as a key; huge answers; malformed JSON specs; unicode. Prove each with a request or a rendered payload.' },
]

const TOPICS = [
  ['How does what I say travel from pressing Talk to your spoken answer, in this talk tool?', 'code'],
  ['Explain how git rebase differs from git merge: what happens to the commits?', 'none'],
  ['Walk me through the OAuth 2 authorization code flow with PKCE.', 'none'],
  ['How does the stage decide which part is lit while the voice speaks?', 'code'],
  ['Compare the four SQL isolation levels and the anomalies each one allows.', 'none'],
  ['Explain TCP congestion control: slow start, congestion avoidance, fast recovery, as a state machine.', 'none'],
  ['What happens to an open call when the talk server restarts?', 'code'],
  ['Which process serves what between webcompanion, the stage and the talk server?', 'code'],
  ['How does a Kubernetes pod get from kubectl apply to running containers?', 'none'],
  ['How do Python, Go and Rust handle errors differently? Show me small examples.', 'none'],
  ['Explain how a B-tree index finds a row and what a page split is.', 'none'],
  ['How does HTTPS set up a connection, from DNS to the first encrypted byte?', 'none'],
  ['How does the call page keep words highlighted in time with the audio?', 'code'],
  ['Explain the CAP theorem with three real databases as examples.', 'none'],
  ['How does React decide what to re-render after a state change?', 'none'],
  ['How does a Raft cluster elect a leader and survive a network partition?', 'none'],
]

async function verify(f, area, round) {
  const votes = await parallel([
    'Does it reproduce? Rerun or re-read the evidence yourself; a claim you cannot reproduce is refuted.',
    'Is it a real defect against a written rule or a clear user expectation, at the stated severity, and not intended behaviour documented in CLAUDE.md or a SKILL.md?',
    'Is the proposed fix right and in scope for this run (brief.md), without breaking something else? An idea is refuted if it is small extra stuff the owner said he does not want.',
  ].map((lens, i) => () => agent(`${PRE}

You are skeptic ${i + 1} of 3 on a finding of round ${round}, area ${area}. Try to REFUTE it. Your lens: ${lens} Default to refuted=true if uncertain. Change no code.

Finding:
${JSON.stringify(f, null, 2)}`, { label: `skeptic:${area}:${i + 1}`, phase: 'Find', schema: VERDICT })))
  const ok = votes.filter(Boolean).filter(v => !v.refuted).length >= 2
  return { ...f, area, round, survived: ok, skeptics: votes.filter(Boolean) }
}

const allBatches = []
const roundLog = []
let stoppedEarly = false
let round = START
while (round <= MAX) {
  const REUSE = round === REUSE_ROUND
  log(`Round ${round}: ${AREAS.length} areas and ${round === 1 ? 8 : 6} trials`)
  const changedArea = round > 1 ? [{ key: 'changed', ask: `what rounds before this one changed on ${NAME} (git -C ${WT} log main..${NAME}, git diff main...${NAME}): regressions, half-done fixes, new inconsistencies. Set follows-style notes in evidence: name the commit the problem comes from.` }] : []
  const areas = [...AREAS, ...changedArea]
  const topics = round === 1 ? TOPICS.slice(0, 8) : TOPICS.slice(8 + (round - 2) * 4, 8 + (round - 1) * 4).concat(TOPICS.slice((round - 2) * 2, (round - 2) * 2 + 2))

  const findWork = pipeline(areas,
    a => REUSE ? agent(`Read ${RUN}/findings/r${round}/${a.key}.json and return its findings exactly as written, every field, none dropped (fill a missing kind with bug and a missing felt with false). Do nothing else.`, { label: `load:${a.key}`, phase: 'Find', effort: 'low', schema: FINDINGS }) : agent(`${PRE}

You are the round ${round} find job for area "${a.key}": ${a.ask}

${RENDER}
Find real problems and prove each one: run it, render it, or quote the code. Change no tracked file in ${WT} (scratch files in ${RUN}/findings/r${round}/${a.key}/ only). Also report kind=idea for changes that would make explanations clearly better (core behaviour, not small extras). Up to 12 findings, most severe first; leave out severity 0-1 bugs. Save your findings as JSON to ${RUN}/findings/r${round}/${a.key}.json too.`, { label: `find:${a.key}`, phase: 'Find', schema: FINDINGS }),
    (r, a) => parallel((r ? r.findings : []).map(f => () => verify(f, a.key, round))),
  )
  const findWork2 = findWork

  const trialWork = REUSE ? pipeline(REUSE_TRIALS,
    t => agent(`In ${RUN}/trials/r${round}-t${t}/: return the question this answer was written for (the render's frames.json or run.log, or infer it from answer.md), the board kinds answer.md uses, the shots of render/frames.json in order ({file as an absolute path, caption, width}), the board problem lines in render/reply.txt, render/console.txt in short, and whether findings.json exists; if it exists return its findings exactly as written (fill a missing kind with bug, a missing felt with false). Do nothing else.`, { label: `load:t${t}`, phase: 'Trials', effort: 'low', schema: { type: 'object', properties: { question: { type: 'string' }, boards: { type: 'array', items: { type: 'string' } }, shots: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, caption: { type: 'string' }, width: { type: 'integer' } }, required: ['file', 'caption'] } }, board_lines: { type: 'string' }, console: { type: 'string' }, has_findings: { type: 'boolean' }, findings: { type: 'array', items: FINDING } }, required: ['question', 'boards', 'shots', 'board_lines', 'console', 'has_findings', 'findings'] } })
      .then(l => l.has_findings ? { f: { findings: l.findings }, score: null, boards: l.boards, t } : null),
    x => x ? parallel(x.f.findings.map(f => () => verify(f, `trial-t${x.t}`, round))).then(vs => ({ verified: vs, score: x.score, boards: x.boards, t: x.t })) : null,
  ) : pipeline(topics.map((t, i) => ({ q: t[0], code: t[1], n: i + 1 })),
    t => agent(`You are a Claude Code session on a spoken /talk call with the user. The talk skill is at ${WT}/skills/talk/SKILL.md: read it now, as any session would when the skill loads, and follow it. ${t.code === 'code' ? `The call's --code folder is ${WT}; read the code you need.` : 'The call is not about code in this repository; boards read from ' + WT + ' if you show any file.'}

The user just said: "${t.q}"

Write the one answer you would send with talk_client.py reply, exactly as you would send it (tags included), to the file ${RUN}/trials/r${round}-t${t.n}/answer.md. Do not send it anywhere. Then return the file path and the boards you used.`, {
      label: `author:t${t.n}`, phase: 'Trials',
      schema: { type: 'object', properties: { answer_path: { type: 'string' }, boards: { type: 'array', items: { type: 'string' } } }, required: ['answer_path', 'boards'] },
    }).then(a => ({ ...a, t })),
    a => agent(`${PRE}

Render the answer at ${a.answer_path} with the harness, --repo ${WT}, --code ${a.t.code === 'code' ? WT : WT}, --out ${RUN}/trials/r${round}-t${a.t.n}/render, --question "${a.t.q}". If the harness fails, fix the cause if it is the harness and retry; if it is talk or stage, that is a finding: describe it in notes. Return the list of shot files with their captions (from frames.json), the board: lines and console errors.`, {
      label: `render:t${a.t.n}`, phase: 'Trials',
      schema: { type: 'object', properties: { ok: { type: 'boolean' }, shots: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, caption: { type: 'string' }, width: { type: 'integer' } }, required: ['file', 'caption'] } }, board_lines: { type: 'string' }, console: { type: 'string' }, notes: { type: 'string' } }, required: ['ok', 'shots', 'board_lines', 'console', 'notes'] },
    }).then(r => ({ ...r, author: a })),
    r => agent(`You asked a voice assistant: "${r.author.t.q}". It answered out loud while a screen beside it showed pictures. Below are screenshots of that screen in the order they appeared, each with the sentence that was being spoken at that moment. Open every image file with the Read tool, in order. Do not open any other file.

${(r.shots || []).map((s, i) => `${i + 1}. ${s.file}${s.width ? ` (${s.width}px wide)` : ''} — spoken: "${s.caption}"`).join('\n')}

Then answer honestly, as the person who asked: what did you learn (explain it back in your own words); what on the screen helped; what was confusing, hard to read, cut off, overlapping, too small, in the wrong order, or did not match what was being said; what you expected to see and did not; and how well it explained it, 1 to 10.`, {
      label: `viewer:t${r.author.t.n}`, phase: 'Trials',
      schema: { type: 'object', properties: { learned: { type: 'string' }, helped: { type: 'string' }, problems: { type: 'array', items: { type: 'object', properties: { shot: { type: 'integer' }, problem: { type: 'string' } }, required: ['problem'] } }, missing: { type: 'string' }, score: { type: 'integer' } }, required: ['learned', 'helped', 'problems', 'missing', 'score'] },
    }).then(v => ({ v, r })),
    ({ v, r }) => agent(`${PRE}

You are the trial analyst for round ${round}, trial ${r.author.t.n}. A session (who did not know it was tested) answered "${r.author.t.q}" with ${r.author.answer_path}, choosing boards ${JSON.stringify(r.author.boards)}. The harness rendered it (${RUN}/trials/r${round}-t${r.author.t.n}/render; board lines: ${r.board_lines}; console: ${r.console}; notes: ${r.notes}). A viewer who only saw the shots and heard the words reported:
${JSON.stringify(v, null, 2)}

Look at the shots yourself. Trace each problem to its cause: a defect in talk/stage code (rendering, stepping, pointing, layout), a defect or gap in the guidance (skills/talk/SKILL.md, demo.md) that led the session to a poor choice (the wrong board, a table where a diagram teaches, too much at once, words and board out of step), or the session's own slip that no guidance could prevent (drop those). Also judge whether the board choice was the one that teaches best. Write findings for the first two kinds, with evidence pointing at shot files and code lines, and kind=idea for a better way the tool could have explained this. Save them to ${RUN}/trials/r${round}-t${r.author.t.n}/findings.json.`, { label: `analyst:t${r.author.t.n}`, phase: 'Trials', schema: FINDINGS })
      .then(f => ({ f, score: v.score, boards: r.author.boards, t: r.author.t.n })),
    x => parallel((x && x.f ? x.f.findings : []).map(f => () => verify(f, `trial-t${x.t}`, round)))
      .then(vs => ({ verified: vs, score: x.score, boards: x.boards, t: x.t })),
  )

  const [areaRes, trialRes] = await Promise.all([findWork2, trialWork])
  const areaFound = (areaRes || []).filter(Boolean).flat().filter(Boolean)
  const trialOut = (trialRes || []).filter(Boolean)
  const trialFound = trialOut.flatMap(t => t.verified || []).filter(Boolean)
  const survived = [...areaFound, ...trialFound].filter(f => f.survived)
  const scores = trialOut.map(t => `t${t.t}:${t.score} boards=${(t.boards || []).join('/')}`)
  log(`Round ${round}: ${survived.length} of ${areaFound.length + trialFound.length} findings survived; trials ${scores.join(', ')}`)

  // ---------- Judge ----------
  phase('Judge')
  const judged = await agent(`${PRE}

You are the round ${round} judge. These findings survived three skeptics:
${JSON.stringify(survived.map(f => ({ area: f.area, title: f.title, where: f.where, evidence: f.evidence, rule: f.rule, why_it_matters: f.why_it_matters, fix: f.fix, size: f.size, severity: f.severity, kind: f.kind, felt: f.felt })), null, 1)}

Trial scores this round: ${scores.join('; ')}.

1. Merge duplicates (the same cause found by several areas or trials is one entry with all its areas), drop what ${RUN}/ledger.json already holds from an earlier round of this run, rank by severity then reach.
2. Write every entry into ${RUN}/ledger.json (keep existing entries; ids ${NAME}-r${round}-<area>-<n>; state confirmed, or idea for kind=idea, or rejected with a reason for severity 0-1 bugs; set follows to the earlier fix's id when a finding comes from a fix of this run). The file must parse.
3. Count new serious findings: this round's confirmed entries of severity 3 or 4 with no follows.
4. Pick the ideas that are core (they change how the tool explains or make a board teach clearly better, per brief.md) for the committee: at most 6, each with a concrete proposal a builder can implement in this run.
5. Append the round's summary to ${RUN}/experiment-log.md.`, {
    label: `judge:r${round}`, phase: 'Judge',
    schema: { type: 'object', properties: {
      new_serious: { type: 'integer' },
      confirmed: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, severity: { type: 'integer' }, where: { type: 'string' }, fix: { type: 'string' } }, required: ['id', 'title', 'severity', 'where', 'fix'] } },
      core_ideas: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, proposal: { type: 'string' }, why: { type: 'string' } }, required: ['id', 'title', 'proposal', 'why'] } },
      summary: { type: 'string' },
    }, required: ['new_serious', 'confirmed', 'core_ideas', 'summary'] },
  })
  if (!judged) return { stopped: `judge r${round}`, roundLog }

  // ---------- Committee ----------
  const ideaVotes = await parallel(judged.core_ideas.map(idea => () =>
    parallel(['a teacher who explains technical topics out loud with diagrams', 'a senior front-end engineer who owns this code and its tests', 'a product designer who watches real users and hates feature creep'].map(who => () =>
      agent(`${PRE}

You sit on a committee of three as ${who}. Read the idea, look at the code and the trials in ${RUN}/trials/ it concerns, and vote: build it in this run or not. Build only if it makes the tool explain clearly better for the owner, is not small extra stuff, and can be built and tested well now.

Idea ${idea.id}: ${idea.title}
Proposal: ${idea.proposal}
Why: ${idea.why}`, { label: `vote:${idea.id}`, phase: 'Committee', schema: { type: 'object', properties: { build: { type: 'boolean' }, reason: { type: 'string' }, amend: { type: 'string', description: 'changes to the proposal you require' } }, required: ['build', 'reason'] } })))
      .then(vs => ({ idea, votes: vs.filter(Boolean), build: vs.filter(Boolean).filter(v => v.build).length >= 2 }))))
  const toBuild = ideaVotes.filter(Boolean).filter(x => x.build)
  log(`Round ${round}: ${judged.confirmed.length} confirmed, ${judged.new_serious} new serious; committee builds ${toBuild.length} of ${judged.core_ideas.length} ideas`)

  // ---------- Batch plan ----------
  const plan = await agent(`${PRE}

You are the round ${round} judge, second pass: group the work into 3 to 5 batch jobs by area of code, so batches touch disjoint files as far as possible (one owner per file). Confirmed findings:
${JSON.stringify(judged.confirmed, null, 1)}
Ideas the committee voted to build (with the votes and amendments, which the batch must honour):
${JSON.stringify(toBuild.map(x => ({ idea: x.idea, votes: x.votes })), null, 1)}
Record each confirmed entry's fix_job in ${RUN}/ledger.json and each built idea as state confirmed with its votes; ideas voted down stay idea with the votes as reason; write them to ${RUN}/ideas.md too. For each batch give precise instructions a builder can follow.`, {
    label: `batches:r${round}`, phase: 'Judge',
    schema: { type: 'object', properties: { batches: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, files: { type: 'array', items: { type: 'string' } }, ids: { type: 'array', items: { type: 'string' } }, instructions: { type: 'string' } }, required: ['id', 'title', 'files', 'ids', 'instructions'] } } }, required: ['batches'] },
  })
  if (!plan || !plan.batches.length) { roundLog.push({ round, judged, toBuild, plan: null }); break }

  // ---------- Fix ----------
  log(`Round ${round}: ${plan.batches.length} batches`)
  const fixed = await parallel(plan.batches.map((b, i) => () => agent(`${PRE}

You are fix job ${b.id} of round ${round}: ${b.title}. Your files: ${b.files.join(', ')}. Entries: ${b.ids.join(', ')} (read each in ${RUN}/ledger.json).

Instructions:
${b.instructions}

1. Make your own worktree: git -C ${WT} worktree add ${RUN}/fix-r${round}-${i + 1} -b ${NAME}-r${round}-${i + 1} ${NAME}. Work only there.
2. For each entry a person can see (felt): render the before with the harness from ${WT} and the after from your worktree, into ${RUN}/evidence/<entry id>/, and look at both.
3. Each bug gets a guard test in the suite (browser-free, the repo's rule; use the node page harnesses for page logic and stage_rule_breaks for frames). Pin exact values. Prove it: run that test alone with the fix removed (fails) and restored (passes), and paste both outputs into the ledger entry's guard notes. A layout-only fix proven by the harness shots gets guard {none: why}.
4. Update the docs the change touches in the same commits (CLAUDE.md, the SKILL.md files, demo.md; keep the demo's change-board line numbers right, test_demo.py checks them).
5. Run the full suite once at the end in your worktree; fix what you broke.
6. Commit on your branch, one line per commit, no body, no attribution. Do not merge into ${NAME}: the landing job does that.
7. Update your entries in ${RUN}/ledger.json (state fixed with commit, guard, felt, notice, felt_evidence; or back to confirmed with a reason when you could not), keeping everyone else's entries; the file must parse (other jobs write it too: re-read right before writing).`, {
    label: `fix:r${round}:${b.id}`, phase: 'Fix',
    schema: { type: 'object', properties: { branch: { type: 'string' }, worktree: { type: 'string' }, commits: { type: 'array', items: { type: 'string' } }, fixed: { type: 'array', items: { type: 'string' } }, not_fixed: { type: 'string' }, suite: { type: 'string' } }, required: ['branch', 'worktree', 'commits', 'fixed', 'not_fixed', 'suite'] },
  })))

  // ---------- Land, one at a time ----------
  const landed = []
  for (const f of fixed.filter(Boolean)) {
    if (!f.commits.length) continue
    const l = await agent(`${PRE}

You are the landing job for branch ${f.branch} (worktree ${f.worktree}). Rebase it onto ${NAME} (git -C ${f.worktree} rebase ${NAME}), resolving conflicts so both sides' fixes survive; if the rebase had conflicts, run the full suite in that worktree and fix what fails. Then fast-forward ${NAME}: git -C ${WT} merge --ff-only ${f.branch}. Then remove the worktree (git -C ${WT} worktree remove ${f.worktree}) and delete the branch. Report the new head.`, { label: `land:${f.branch}`, phase: 'Land', schema: { type: 'object', properties: { landed: { type: 'boolean' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['landed', 'head', 'notes'] } })
    landed.push(l)
  }
  const suite = await agent(`${PRE}

Run the full suite once in ${WT} (${NAME} after round ${round}'s landings). If anything fails, fix it on ${NAME} directly with one-line commits and rerun until green. In ${RUN}/ledger.json, check every fixed entry of round ${round} has felt set and a commit that is on ${NAME}. Append the round's result to ${RUN}/experiment-log.md: new serious ${judged.new_serious}, threshold 5, and the ruling.`, { label: `suite:r${round}`, phase: 'Land', schema: { type: 'object', properties: { green: { type: 'boolean' }, result: { type: 'string' } }, required: ['green', 'result'] } })
  roundLog.push({ round, new_serious: judged.new_serious, confirmed: judged.confirmed.length, ideas_built: toBuild.map(x => x.idea.title), batches: plan.batches.map(b => b.title), landed, suite, scores })
  log(`Round ${round} landed; suite ${suite ? suite.result : 'unknown'}`)
  if (judged.new_serious < 5) { stoppedEarly = true; break }
  round++
}
if (!stoppedEarly && MAX < 3) return { roundLog, next: 'round 3 warranted' }

// ---------- Report ----------
phase('Report')
const report = await agent(`${PRE}

You are the report job. Load the house-style skill (petros-skills:house-style) first. Read ${RUN}/ledger.json, ${RUN}/experiment-log.md, ${RUN}/ideas.md, ${RUN}/evidence/ and the trials. Write ${RUN}/report/index.html: one self-contained page (images copied into report/ and referenced relatively) for the owner, who reads it on a phone too:
- first, one section per change he will see or feel, with its before and after shots side by side and the one sentence of what he will notice;
- the ideas built and the committee's votes; the ideas voted down with why;
- the trial scores per round (topic, boards chosen, viewer score) and how board choice changed;
- the fixes nobody sees, the rejections, the open questions, and each round's stop ruling.
Then run: ~/projects/env/bin/@devdomains share ${RUN}/report/index.html (or find @devdomains on PATH) and return the link it prints.`, { label: 'report', phase: 'Report', schema: { type: 'object', properties: { link: { type: 'string' }, path: { type: 'string' }, headline: { type: 'string' } }, required: ['path', 'headline'] } })

return { roundLog, report }
