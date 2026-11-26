export const meta = {
  name: 'bulldozer-talk-panel-finish',
  description: 'Fix the confirmed entries a talk side panel run left open, in batches, land them on the run branch, run the suite',
  phases: [{ title: 'Plan' }, { title: 'Fix' }, { title: 'Land' }],
}
const RUN = args.run
const NAME = args.name
const WT = args.root
const PRE = `You are a job of bulldozer run ${NAME} on claude-annotate's /talk side panel. Read ${RUN}/brief.md first; its rules win. The run branch ${NAME} is checked out at ${WT}; the repo's rules are in ${WT}/CLAUDE.md. The render harness is tools/talk_render in the checkout (README.md). Load the petros-skills:house-style skill before changing UI. Never call Azure speech, never touch dev.talk (8766) or dev.webcompanion, stop processes only by PID.`

phase('Plan')
const plan = await agent(`${PRE}

The rounds ended with entries in ${RUN}/ledger.json still in state confirmed (their reason or note may say what is half done). Every one of them is to be fixed now. Re-check each against current ${NAME} first: one already fixed by a later commit becomes fixed with that commit; one no longer true becomes rejected with why. Group the rest into 4 to 6 batch jobs by area of code, disjoint files as far as possible, with precise instructions. Record fix_job on each entry. The file must parse.`, {
  label: 'plan', phase: 'Plan',
  schema: { type: 'object', properties: { closed: { type: 'string' }, batches: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, files: { type: 'array', items: { type: 'string' } }, ids: { type: 'array', items: { type: 'string' } }, instructions: { type: 'string' } }, required: ['id', 'title', 'files', 'ids', 'instructions'] } } }, required: ['closed', 'batches'] },
})
log(`${plan.batches.length} batches; ${plan.closed}`)

const fixed = await parallel(plan.batches.map((b, i) => () => agent(`${PRE}

You are fix job ${b.id}: ${b.title}. Your files: ${b.files.join(', ')}. Entries: ${b.ids.join(', ')} (read each in ${RUN}/ledger.json).

Instructions:
${b.instructions}

1. Make your own worktree: git -C ${WT} worktree add ${RUN}/fix-f-${i + 1} -b ${NAME}-f-${i + 1} ${NAME}. Work only there.
2. A change a person can see: render before (from ${WT}) and after (from your worktree) with the harness into ${RUN}/evidence/<entry id>/ and look at both.
3. Each bug gets a browser-free guard test with exact values, proven by running it alone with the fix removed (fails) and restored (passes); paste both into the entry's guard notes. A layout-only fix proven by harness shots gets guard {none: why}.
4. Update the docs the change touches in the same commits (CLAUDE.md, SKILL.md files, demo.md and its line numbers).
5. Run the full suite once at the end in your worktree; fix what you broke.
6. Commit on your branch, one line per commit, no body, no attribution. Do not merge into ${NAME}.
7. Update your entries in ${RUN}/ledger.json (fixed with commit, guard, felt, notice, felt_evidence; or confirmed with a reason when you truly could not), re-reading it right before writing; it must parse.`, {
  label: `fix:${b.id}`, phase: 'Fix',
  schema: { type: 'object', properties: { branch: { type: 'string' }, worktree: { type: 'string' }, commits: { type: 'array', items: { type: 'string' } }, fixed: { type: 'array', items: { type: 'string' } }, not_fixed: { type: 'string' }, suite: { type: 'string' } }, required: ['branch', 'worktree', 'commits', 'fixed', 'not_fixed', 'suite'] },
})))

const landed = []
for (const f of fixed.filter(Boolean)) {
  if (!f.commits.length) continue
  landed.push(await agent(`${PRE}

Land branch ${f.branch} (worktree ${f.worktree}): rebase it onto ${NAME}, resolving conflicts so both sides' fixes survive; if there were conflicts run the full suite there and fix what fails. Then git -C ${WT} merge --ff-only ${f.branch}, remove the worktree, delete the branch, and remap the ledger's commit hashes of its entries to the rebased commits.`, { label: `land:${f.branch}`, phase: 'Land', schema: { type: 'object', properties: { landed: { type: 'boolean' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['landed', 'head', 'notes'] } }))
}
const suite = await agent(`${PRE}

Run the full suite once in ${WT}. Fix any failure on ${NAME} with one-line commits and rerun until green. Then count ${RUN}/ledger.json states and list every entry still confirmed with its reason. Append a "Finish" section to ${RUN}/experiment-log.md. `, { label: 'suite', phase: 'Land', schema: { type: 'object', properties: { green: { type: 'boolean' }, result: { type: 'string' }, states: { type: 'string' }, still_open: { type: 'string' } }, required: ['green', 'result', 'states', 'still_open'] } })
return { plan: plan.closed, batches: plan.batches.map(b => b.title), fixed: fixed.filter(Boolean).map(f => ({ fixed: f.fixed, not_fixed: f.not_fixed })), landed, suite }