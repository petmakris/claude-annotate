export const meta = {
  name: 'bulldozer-talk-panel-build',
  description: 'Build wave of a talk side panel run: a shared panel design and skeleton, then feature batches in worktrees, a panel of three on each proposed closure, landing one by one, the suite',
  phases: [{ title: 'Design' }, { title: 'Build' }, { title: 'Close' }, { title: 'Land' }, { title: 'Check' }],
}

// args: { root, run, name, batches: [{key, title, files, brief}], harness: bool }
const ROOT = args.root
const RUN = args.run
const NAME = args.name
const BEFORE = `${RUN}/before`
const PRE = `You are a job of bulldozer run ${NAME} on claude-annotate's /talk side panel. Read ${RUN}/brief.md first; its rules win. The run branch ${NAME} is checked out at ${ROOT} (do not edit files there; you work in your own worktree). The repo's rules are in CLAUDE.md. The ledger is ${RUN}/ledger.json (read it; never write it: you return your results and the orchestrator merges them). The study every entry comes from: ${ROOT}/docs/proposals/2026-11-25-talk-panel/details.html (every finding with file and line, every proposal with its build plan; it is large, so grep it by proposal id or finding title) and index.html (the deck with the mock-ups the build should look like; its images are in docs/proposals/2026-11-25-talk-panel/img/). Text extracts: ${RUN}/study/steps.txt, ${RUN}/study/proposals.txt, ${RUN}/study/findings-section.txt. The panel as it was before this run is checked out at ${BEFORE} (never edit it). The render harness is ${ROOT}/tools/talk_render (README.md): it starts a checkout's own talk server on a free port with a silent speech engine. Never call Azure speech, never touch the live talk server on port 8766 or restart webcompanion or talk services, stop processes only by PID. The repo is public: no home paths, machine names or company names in anything committed. Load the petros-skills:house-style skill before changing any UI; every screen follows its rules (icon and word when wide, icons when narrow, rows aligned in columns, no explaining text in lists).`

const RESULT = {
  type: 'object',
  properties: {
    branch: { type: 'string' }, worktree: { type: 'string' },
    commits: { type: 'array', items: { type: 'string' } },
    entries: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' },
      state: { type: 'string', enum: ['fixed', 'propose-close', 'confirmed'] },
      commit: { type: 'string' },
      guard: { type: 'string', description: 'the test file and test name, or "none: <why>" (a layout-only fix proved by shots)' },
      guard_proof: { type: 'string', description: 'the two pasted runs of the guard alone: failing with the fix removed, passing with it restored (last lines of each)' },
      felt: { type: 'boolean' }, notice: { type: 'string', description: 'for felt: one plain sentence of what a person notices, present tense' },
      shots: { type: 'array', items: { type: 'string' }, description: 'absolute paths of before and after shots' },
      reason: { type: 'string', description: 'for propose-close or confirmed: why, in one or two sentences' },
    }, required: ['id', 'state', 'reason'] } },
    step_shots: { type: 'string', description: 'for a batch that builds a step: the folder holding before/after shots at 1440, 390 and dark' },
    suite: { type: 'string', description: 'the full suite line: N passed, M skipped, in your worktree' },
    notes: { type: 'string' },
  },
  required: ['branch', 'worktree', 'commits', 'entries', 'suite', 'notes'],
}

// ---------------------------------------------------------------- Design
phase('Design')
log('One designer writes the shared panel layout and commits its skeleton on the run branch, so the batches build into agreed places')
const design = await agent(`${PRE}

You are the panel's designer and skeleton builder. Five feature batches will soon build in parallel on the call page's side panel, each in its own worktree. Without a shared plan they will collide in call.js, call.css and call.html. Your job is to make the shared plan and the empty places, and land those on ${NAME} before they start.

The batches (keys, what they build, the ledger entries are those with fix_job "${NAME}-build-<key>"):
${args.batches.map((b) => `- ${b.key}: ${b.title}. ${b.brief}`).join('\n')}

1. Read the study's steps (${RUN}/study/steps.txt), the proposals they draw from (revampB-1, convo-1, catchup-1, listen-1 for the Now card and earlier list; input-2, trust-1, trust-2, revampA-2, revampB-2 for the wait card; multicall-1, listen-2 for Calls; catchup-2, access-1 for return and place; input-1, access-2, devices-1 for mode switch, Keys sheet and phone; find them in details.html by their id), and look at their mock-ups in index.html/img. Read call.html, call.css and call.js fully.
2. Write ${RUN}/design.md for the builders (nobody else reads it): the panel's final DOM from top to bottom at 1440 px and at 390 px (header with the Calls button and state words; the Now card that holds the current turn, its wait card state, its full answer text with the lit word, board chips, transport and Following strip; the welcome-back card and since-you-left divider; the aligned, searchable list of earlier answers; the composer with the Type/Talk/Live switch and Your turn pill; the Keys sheet; the live region), every element's id or class, which batch owns it, which JavaScript file holds each part, the events or functions one part calls in another (names and arguments), and the server fields the page reads (existing ones by name; new ones with the batch that adds them). Keep today's behaviour rules from CLAUDE.md that the steps do not change (readerPlays, followAgain, the player claim, queued answers), and say where each sits in the new layout.
3. Split call.js so each batch owns its own file: create new classic-script files under skills/talk/static/ (for example call-calls.js, call-wait.js, call-shell.js, call-input.js; your choice), move nothing that would change behaviour, add the empty functions and DOM slots the design names (hidden or empty, so the page looks and behaves exactly as before), load them from call.html in the right order, and make skills/talk/tests/call_page.py load them too so the node tests keep running the real page. Keep the shared state where every file can reach it.
4. Run the full suite in a worktree of your own (git -C ${ROOT} worktree add ${RUN}/wt-design -b ${NAME}-design ${NAME}); render one demo answer with tools/talk_render at 1440 px and compare with the same render from ${BEFORE}: they must look the same. Commit (one line each), then land: git -C ${ROOT} merge --ff-only ${NAME}-design, remove the worktree, delete the branch.
Return the design's path, the file ownership map (file -> batch key, and the shared files every batch may touch only at the hooks you named), the landed head, and the suite line.`, {
  label: 'design', phase: 'Design', effort: 'high',
  schema: { type: 'object', properties: { design: { type: 'string' }, ownership: { type: 'string' }, head: { type: 'string' }, suite: { type: 'string' } }, required: ['design', 'ownership', 'head', 'suite'] },
})
log(`Skeleton landed at ${design.head}; ${design.suite}`)

// ---------------------------------------------------------------- Build
phase('Build')
const batchPrompt = (b, i) => `${PRE}

You are build batch ${b.key}: ${b.title}.
${b.brief}

Your ledger entries are every entry of ${RUN}/ledger.json whose fix_job is "${NAME}-build-${b.key}". Read each one in full (title, where, evidence, cause, skeptics' corrections, parts for a step). A step entry lists its parts: build every part. A study finding names a file and line in the code as it was; the code has moved since (the designer split call.js), so find the place by what it does.

The shared design: ${design.design}. Read it first; build into the places it names and keep to its file ownership:
${design.ownership}
Your own files: ${b.files}. Touch another batch's file only at a hook the design names, with the smallest change, since another batch is changing it at the same time and the landing rebases one onto the other.

How to work:
1. Make your own worktree: git -C ${ROOT} worktree add ${RUN}/wt-${b.key} -b ${NAME}-${b.key} ${NAME}. Work only there. This is a large batch: split it across sub-agents (Agent tool) where the parts are independent, each told the same rules, but you own the result and the commits.
2. Before changing a part a person can see, shoot it as it was from ${BEFORE} (tools/talk_render renders an answer playing; for a panel state the renderer does not reach, such as the wait card, the Calls popover or a returning reader, write a small Playwright script under ${RUN}/evidence/${b.key}/ that starts the checkout's talk server the way tools/talk_render/serve.py does, on a free port, and drives the page into that state). After the change shoot the same state from your worktree. Shots at 1440 px, 390 px (phone, 2x, touch) and dark go under ${RUN}/evidence/${b.key}/<entry id>/ named before-1440.png, after-1440.png, before-390.png, after-390.png, after-dark.png. Look at every shot yourself and fix what looks wrong before you call it done.${b.step ? ` For ${b.step} also make ${RUN}/evidence/steps/${b.step}/ with before and after at 1440 and 390 and after-dark of the step's main state(s): the report shows these.` : ''}
3. Each bug gets a browser-free guard test with exact values in the suite (node-run page logic through skills/talk/tests/call_page.py and skills/_shared/tests/dom_shim.mjs, or Python for the server and the drawers), proved by running it alone twice with PYTHONDONTWRITEBYTECODE=1: failing with the fix removed, passing with it restored. Paste the last lines of both runs into guard_proof. A layout-only fix proved by shots gets guard "none: <why>". A new feature gets tests of its logic.
4. A study finding you believe needs no change (for example scope harness-artifact: caused by the test, not the page; or already fixed by another of your changes, which then counts as fixed with that commit) is state propose-close with the reason; a panel of three will vote on it. Do not use propose-close to skip work: every real problem is fixed.
5. Update the docs the change touches in the same commits: CLAUDE.md, skills/talk/SKILL.md, skills/talk/references/*.md, and skills/talk/demo.md with its line numbers (see CLAUDE.md on test_demo.py).
6. Run the full suite once at the end in your worktree: uv run -q --with-requirements requirements-test.txt python -m pytest skills fleet/tests -q. Fix what you broke and rerun the failing tests only.
7. Commit on your branch, one line per commit, no body, no attribution. Stage by path. Do not merge into ${NAME}: the lander does that.
Return every entry of yours with its state.`

const BATCH_FILES = args.batches
const builtP = parallel(BATCH_FILES.map((b, i) => () => agent(batchPrompt(b, i), { label: `build:${b.key}`, phase: 'Build', schema: RESULT, effort: 'high' })))
const harness = args.harness ? agent(`${PRE}

Rebuild the trial harness the side panel study used (its scripts are in ${RUN}/study/scripts/; read talk-panel-personas-*.js: it calls ${'${H}'}/pw and ${'${H}'}/callctl). Build them in ${RUN}/harness/ as two executables:
- pw start <key> [--size WxH] [--phone] [--dark] [--mic] --url <url>; pw do <key> '<python>'; pw stop <key>. A persistent Playwright Chromium per key (a small server process holding the browser, so each 'do' acts on the same page). Inside 'do': page (current tab), shot(label) saves ${RUN}/trials/<round>/<key>/shots/NN-label.png and prints its path, ax() returns the accessibility tree as text (page.accessibility.snapshot or aria snapshot), newtab(url), tab(i), pages(), time, print. --phone means 390x844, 2x, touch, mobile; --dark sets prefers-color-scheme dark; --mic starts Chromium with a fake microphone (--use-fake-device-for-media-stream --use-fake-ui-for-media-stream). The round folder comes from the env var TRIAL_DIR.
- callctl up <key> --repo <checkout> [--pace P] --topic "T" [--topic "T2"]: starts that checkout's talk server through tools/talk_render/serve.py (silent speech engine, free port, never 8766, env cleaned of TALK_* and AZURE_*, state in ${RUN}/trials/state/<key>/), opens one call per topic with the code folder set to the checkout, prints "CALL <id> <url>  topic: <topic>" per call. callctl client <key> -- <talk_client.py args>: runs the checkout's talk_client.py against that server. callctl seed <key> --call <id> <seed.json>: for each {q, a} types q as a user turn and answers it with a, printing "turn tN: exit 0 sent ..." and board: lines. callctl down <key>: stops that key's server and its stage sessions by PID and sid.
Read tools/talk_render/render.py and serve.py for how the server, the launcher, the stage session and the page are started and ended; reuse their code.
Prove it on ${BEFORE}: up a call, start a browser on it, type a turn on the page, answer it with callctl client (doorbell then reply with a board), shoot the page, look at the shot, stop everything. Then the same on ${ROOT} (the run branch). Return the commands and what the proof showed.`, { label: 'harness', phase: 'Build', schema: { type: 'object', properties: { usage: { type: 'string' }, proof: { type: 'string' } }, required: ['usage', 'proof'] } }) : Promise.resolve(null)

const built = await builtP

// ---------------------------------------------------------------- Close
phase('Close')
const proposals = built.filter(Boolean).flatMap((r) => r.entries.filter((e) => e.state === 'propose-close').map((e) => ({ ...e, batch: r.branch })))
log(`${proposals.length} proposed closures go to a panel of three each`)
const VOTE = { type: 'object', properties: { agree: { type: 'boolean' }, reason: { type: 'string' } }, required: ['agree', 'reason'] }
const closures = await parallel(proposals.map((p) => async () => {
  const lenses = ['a user of the panel who hit this problem', 'a skeptical reviewer of the code on branch ' + p.batch, 'the run owner, who said all problems are accepted for fixing']
  const votes = await parallel(lenses.map((lens, k) => () => agent(`${PRE}

Ledger entry ${p.id} (read it in ${RUN}/ledger.json) is proposed for closing without a fix, by the batch that owned it, for this reason:
${p.reason}
Judge it as ${lens}. Check the claim yourself in the code of branch ${p.batch} (git -C ${ROOT} show ${p.batch}:<path>) and, where it helps, in the study's evidence. Agree only when the entry truly needs no change (caused by the test and not the page, or already fixed on that branch). Default to disagree when in doubt.`, { label: `close:${p.id}:${k + 1}`, phase: 'Close', schema: VOTE, effort: 'medium' })))
  const yes = votes.filter(Boolean).filter((v) => v.agree).length
  return { id: p.id, reason: p.reason, votes, closed: yes >= 2 }
}))

// ---------------------------------------------------------------- Land
phase('Land')
const landed = []
for (const r of built.filter(Boolean)) {
  if (!r.commits.length) continue
  landed.push(await agent(`${PRE}

Land branch ${r.branch} (worktree ${r.worktree}) on ${NAME}: rebase it onto ${NAME}, resolving every conflict so both sides' work survives (the other side is another batch's landed work: keep both features working; read ${design.design} for who owns what). Then run the tests of every file the rebase touched or conflicted on (the full suite if any conflict touched call.js, call.css, call.html, talk.py or a test helper), fix what fails with one-line commits, and fast-forward: git -C ${ROOT} merge --ff-only ${r.branch}. Then remove the worktree and delete the branch. Return the new head and a map from each old commit hash to its rebased hash.`, { label: `land:${r.branch}`, phase: 'Land', schema: { type: 'object', properties: { landed: { type: 'boolean' }, head: { type: 'string' }, remap: { type: 'string', description: 'old=new pairs, one per line' }, notes: { type: 'string' } }, required: ['landed', 'head', 'remap', 'notes'] } }))
}

// ---------------------------------------------------------------- Check
phase('Check')
const check = await agent(`${PRE}

Every build batch has landed on ${NAME}. In a worktree of your own at ${NAME} (git -C ${ROOT} worktree add ${RUN}/wt-check -b ${NAME}-check ${NAME}):
1. Run the full suite once. Fix any failure with one-line commits; rerun the failing tests.
2. Render two answers with tools/talk_render (one with a table, one with a sequence; answers in tools/talk_render/answers/) at 1440, 390 and dark, and use the page by hand in a Playwright script: send a turn, see the wait card, answer it with talk_client.py, open the Calls popover, search the earlier answers, switch Type/Talk/Live, open the Keys sheet. Look at every shot. Whatever is broken because two batches met (a feature lost in a rebase, two parts on top of each other, a dead control, a console error) you fix now, with a guard test where the suite can hold one.
3. Fast-forward ${NAME} to your branch (git -C ${ROOT} merge --ff-only ${NAME}-check), remove the worktree and the branch.
Return the suite line, what you fixed, the shots' folder, and what still looks wrong.`, { label: 'check', phase: 'Check', effort: 'high', schema: { type: 'object', properties: { suite: { type: 'string' }, fixed: { type: 'string' }, shots: { type: 'string' }, still_wrong: { type: 'string' }, head: { type: 'string' } }, required: ['suite', 'fixed', 'shots', 'still_wrong', 'head'] } })

return { design, built, closures, landed, check, harness: await harness }
