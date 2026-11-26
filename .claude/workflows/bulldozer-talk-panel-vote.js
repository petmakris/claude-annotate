export const meta = {
  name: 'bulldozer-talk-panel-vote',
  description: 'Final vote of a talk side panel run: fresh personas do the same tasks on the panel before the run and the rebuilt one, and say which they prefer and why',
  phases: [{ title: 'Cast' }, { title: 'Compare' }, { title: 'Tally' }],
}

// args: { root, run, name, before, harness }
const ROOT = args.root
const RUN = args.run
const BEFORE = args.before
const H = `${RUN}/harness`
const T = `${RUN}/trials/vote`
const HARNESS = `The trial harness (${H}):\n${args.harness}\nEvery command takes TRIAL_DIR=${T}.`
const BALLOT = { type: 'object', properties: {
  key: { type: 'string' }, prefer: { type: 'string', enum: ['A', 'B', 'same'] }, strength: { type: 'number', description: '1 slight to 5 strong' },
  why: { type: 'string' }, a_best: { type: 'string' }, a_worst: { type: 'string' }, b_best: { type: 'string' }, b_worst: { type: 'string' },
  shots: { type: 'array', items: { type: 'string' } },
}, required: ['key', 'prefer', 'strength', 'why', 'a_best', 'a_worst', 'b_best', 'b_worst', 'shots'] }

phase('Cast')
const cast = await agent(`Write 10 personas for a comparison of two versions of a voice assistant page (a user types or speaks, an AI answers aloud with text and sometimes a table or diagram). Spread: first-time user, daily power user, phone (390x844, touch), keyboard only, screen reader (ax() only), someone who interrupts and corrects, someone back after hours who needs to catch up, someone who types long messages, someone who mostly listens, someone who looks for an earlier answer. Each: key, start (pw options: --size 1440x900, or --phone, --dark), who (name, age, habits), task (one concrete topic and 4 to 5 questions to ask, the same on both versions), rules (how they use the browser, or empty). Topics new and varied.`, { label: 'cast', phase: 'Cast', schema: { type: 'object', properties: { personas: { type: 'array', items: { type: 'object', properties: { key: { type: 'string' }, start: { type: 'string' }, who: { type: 'string' }, task: { type: 'string' }, topic: { type: 'string' }, rules: { type: 'string' } }, required: ['key', 'start', 'who', 'task', 'topic', 'rules'] } } }, required: ['personas'] } })

const UP = { type: 'object', properties: { id: { type: 'string' }, url: { type: 'string' } }, required: ['id', 'url'] }
const up = (key, repo, topic) => agent(`${HARNESS}\nRun TRIAL_DIR=${T} ${H}/callctl up ${key} --repo ${repo} --pace 0.8 --topic ${JSON.stringify(topic)} and return the CALL line's id and url.`, { label: `up:${key}`, phase: 'Compare', schema: UP, effort: 'low' })
const responder = (key, repo, call, topic) => agent(`You are the AI session on the other end of a voice call page ("talk"), answering a user on the call "${topic}". Read ${repo}/skills/talk/SKILL.md (the turn loop, choosing the board, writing the answer) and skim its references/boards.md, and answer as a real session would, through TRIAL_DIR=${T} ${H}/callctl client ${key} -- <talk_client.py arguments with --call=${call.id}> (doorbell --wait 90, reply <turn> --status, reply <turn> <<'EOF' ... EOF). A status first, some work, then the answer; vary lengths; use boards where they teach. Loop until the file ${T}/${key}/finished exists (check after each empty doorbell), TALK_END, or 60 minutes. Return a short log.`, { label: `responder:${key}`, phase: 'Compare' })

// a persona with its two responders is three agents; five pairs at a time stay under the 16-agent cap
phase('Compare')
const people = cast.personas.slice(0, 10)
const ballots = []
for (const group of [people.slice(0, 5), people.slice(5)]) {
  const res = await parallel(group.map((p, i) => async () => {
    const aIsOld = (people.indexOf(p) % 2) === 0
    const [ca, cb] = await Promise.all([up(`v-${p.key}-a`, aIsOld ? BEFORE : ROOT, p.topic), up(`v-${p.key}-b`, aIsOld ? ROOT : BEFORE, p.topic)])
    const ra = responder(`v-${p.key}-a`, aIsOld ? BEFORE : ROOT, ca, p.topic)
    const rb = responder(`v-${p.key}-b`, aIsOld ? ROOT : BEFORE, cb, p.topic)
    const ballot = await agent(`You are role-playing a real person. Stay in character.

WHO YOU ARE
${p.who}

A friend set you up with a voice assistant page you can talk with or type to. There are two versions of it, A and B, and you are asked to try both on the same task and say which you would rather use. Nothing else was told to you.
Version A: ${ca.url}
Version B: ${cb.url}
TASK (the same on both): ${p.task}

You drive a real browser through a helper: TRIAL_DIR=${T} ${H}/pw start v-${p.key} ${p.start} --url <address>, then TRIAL_DIR=${T} ${H}/pw do v-${p.key} '<python>' (page is the current tab; shot("label") saves and prints a PNG path; open it with the Read tool to see the screen; ax() gives the accessibility tree; newtab(url), tab(i)). ${p.rules || ''} Do not read source code or files, do not use page.evaluate, open no other address. After sending, wait like a person (sleep 10 to 30 s, looking in between); an answer takes a minute or two.
Do the whole task on A first, then on B (or B first if you prefer; say which). Take at least 8 shots on each. Then stop the browser (pw stop v-${p.key}) and say which version you prefer (A, B or same), how strongly (1 to 5), why, and the best and worst thing of each, with shot paths.`, { label: `voter:${p.key}`, phase: 'Compare', schema: BALLOT })
    await agent(`Run and return the output: mkdir -p ${T}/v-${p.key}-a ${T}/v-${p.key}-b && touch ${T}/v-${p.key}-a/finished ${T}/v-${p.key}-b/finished && echo ok`, { label: `finish:${p.key}`, phase: 'Compare', effort: 'low' })
    await Promise.all([ra.catch(() => null), rb.catch(() => null)])
    await agent(`Run and return the output: TRIAL_DIR=${T} ${H}/callctl down v-${p.key}-a; TRIAL_DIR=${T} ${H}/callctl down v-${p.key}-b; echo down`, { label: `down:${p.key}`, phase: 'Compare', effort: 'low' })
    if (!ballot) return null
    const map = (x) => x === 'same' ? 'same' : ((x === 'A') === aIsOld ? 'old' : 'new')
    return { ...ballot, a_is_old: aIsOld, prefers: map(ballot.prefer) }
  }))
  ballots.push(...res.filter(Boolean))
}

phase('Tally')
const tally = { new: ballots.filter((b) => b.prefers === 'new').length, old: ballots.filter((b) => b.prefers === 'old').length, same: ballots.filter((b) => b.prefers === 'same').length }
log(`Votes: new ${tally.new}, old ${tally.old}, same ${tally.same}`)
const summary = await agent(`Ten people compared two versions of a voice assistant page's side panel: "old" (before a rebuild) and "new" (after). Their ballots, unblinded: ${JSON.stringify(ballots)}. Write a plain summary for the owner: the tally, the reasons that came up more than once for each side, and the worst things people still found in the new one, with the shot paths that show them. Short sentences.`, { label: 'summary', phase: 'Tally' })
return { tally, ballots, summary }
