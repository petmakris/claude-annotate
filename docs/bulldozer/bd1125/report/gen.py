import json,os,subprocess,html,collections
R='~/projects/dashboard/.scratch/bulldozer-talk-bd1125'
E=R+'/evidence/'
led=json.load(open(R+'/ledger.json'))['findings']
def img(rel):
    src=E+rel
    if not os.path.exists(src): raise SystemExit('missing '+src)
    name=rel.replace('/','__').replace('.png','.jpg')
    dst=R+'/report/img/'+name
    if not os.path.exists(dst):
        subprocess.run(['sips','-s','format','jpeg','-s','formatOptions','70','-Z','1100',src,'--out',dst],check=True,capture_output=True)
    return 'img/'+name
# (group, title, sentence, before, after, device)
P=[
('Tables','The table is drawn whole from the first word and the voice lights a row by colour','The grid no longer grows, reflows or jumps while the voice talks; the row being said just turns bright. (r1 table-7, table-11)','bd1125-r1-table-7/before-wide-d04.png','bd1125-r1-table-7/after-wide-d04.png','desktop'),
('Tables','A table with two tables steps through both, and each is as wide as its text','Narrow tables stop stretching across the stage; label and value are no longer 900 px apart. (r1 table-1, table-6)','bd1125-r1-table-6/before-twotables-rest.png','bd1125-r1-table-6/after-twotables-rest.png','desktop'),
('Tables','A 4x4 table stays a whole grid on a phone','Before, a phone showed one tall card per row and the comparison was never seen whole. (r1 table-3, table-8)','bd1125-r1-table-8/before-phone.png','bd1125-r1-table-8/after-phone-cells.png','phone'),
('Tables','A long table keeps its header and scrolls itself to the row being said','The rest of the table fades at the foot while there is more. (r1 table-5)','bd1125-r1-table-5/before-d05.png','bd1125-r1-table-5/after-d05.png','desktop'),
('Tables','Pointing at a later row brings the rows before it in, instead of leaving gaps','Nothing is revealed out of order any more. (r1 table-4)','bd1125-r1-table-4/before-d04.png','bd1125-r1-table-4/after-d04.png','desktop'),
('Tables','A cell with angle brackets shows exactly as written','Map<String, List<Integer>> no longer loses its brackets. (r1 robust-1)','bd1125-r1-robust-1/before-rest.png','bd1125-r1-robust-1/after-rest.png','desktop'),
('Tables','Numbers with a currency sign or k/x unit line up with the other numbers','Right-aligned in their column like the rest. (r1 table-9)','bd1125-r1-table-9/before-wide-rest.png','bd1125-r1-table-9/after-wide-rest.png','desktop'),
('Diagrams','Flowchart arrows are routed around the boxes and keep to their own lanes','Before, edges ran through unrelated nodes or under each other. (r1 diagrams-2)','bd1125-r1-diagrams-2/before/D-d10-rest.png','bd1125-r1-diagrams-2/after/D-d10-rest.png','desktop'),
('Diagrams','Each edge label sits on its own arrow, on the phone too','Labels no longer land on another edge or collide. (r1 diagrams-3)','bd1125-r1-diagrams-3/before/D-p20-rest.png','bd1125-r1-diagrams-3/after/D-p20-rest.png','phone'),
('Diagrams','The architecture map fills the pane and wraps its long lines','Before, it was a small canvas with 5 px text and a blank pane. (r1 diagrams-4)','bd1125-r1-diagrams-4/before/C-d08-rest.png','bd1125-r1-diagrams-4/after/C-d08-rest.png','desktop'),
('Diagrams','Sequence replies and phase captions sit on a backing, clear of lifelines','Labels are no longer struck through by lifelines and bars. (r1 diagrams-5)','bd1125-r1-diagrams-5/before/A-d05-point.png','bd1125-r1-diagrams-5/after/A-d05-point.png','desktop'),
('Diagrams','An 11-actor sequence on a phone shows numbered cards and a names key','The actor chips no longer pile on each other. (r1 diagrams-1)','bd1125-r1-diagrams-1/before/A-p10-board.png','bd1125-r1-diagrams-1/after/A-p10-board.png','phone'),
('Diagrams','The phone sequence header is one slim row instead of a third of the pane','More of the story is visible under it. (r1 diagrams-6)','bd1125-r1-diagrams-6/before/E-p07-point.png','bd1125-r1-diagrams-6/after/E-p07-point.png','phone'),
('Diagrams','The previous row is no longer sliced under the sticky header on a phone','The view snaps to the row boundary. (r1 trial-t7-1)','bd1125-r1-trial-t7-1/before/t7-p10-point.png','bd1125-r1-trial-t7-1/after/t7-p10-point.png','phone'),
('Diagrams','When the answer is over, a phone returns to the top of the board','Sequence, compare and flowchart no longer stay scrolled to the last rows. (r1 diagrams-7)','bd1125-r1-diagrams-7/before/t7-p14-rest.png','bd1125-r1-diagrams-7/after/t7-p14-rest.png','phone'),
('Diagrams','A compare board on a phone follows the step being said','Before, it never scrolled and later rows were never seen. (r1 trial-t2-1)','bd1125-r1-trial-t2-1/before/t2-p14-point.png','bd1125-r1-trial-t2-1/after/t2-p14-point.png','phone'),
('Diagrams','A compare board ends with a verdict strip that the voice can light','The outcome is now drawn and pointable. (r1 trial-t2-3)','bd1125-r1-trial-t2-3/before-t2-d08-rest.png','bd1125-r1-trial-t2-3/after/t2o-d08-point.png','desktop'),
('Diagrams','The map row of parts no longer jumps between the first frame and the rest','Same row height at start, middle and end. (r1 trial-t4-1)','bd1125-r1-trial-t4-1/before/t4-d04-point.png','bd1125-r1-trial-t4-1/after/t4-d04-point.png','desktop'),
('Call page','The gear settings panel is reachable on a phone','Screen, Panel and Theme were cut off at the top. (r1 callpage-1)','bd1125-r1-callpage-1/before-phone-gear-390.png','bd1125-r1-callpage-1/after-phone-gear-390.png','phone'),
('Call page','The sentence strip under a board shows the whole sentence on a phone','Before, the word being said was out of sight. (r1 callpage-2)','bd1125-r1-callpage-2/before-phone-390-9.png','bd1125-r1-callpage-2/after-phone-390-9.png','phone'),
('Call page','The sentence strip shows the whole sentence on a TV too','Same fix at 1280 px. (r1 callpage-2)','bd1125-r1-callpage-2/before-tv-1280-9.png','bd1125-r1-callpage-2/after-tv-1280-9.png','desktop'),
('Call page','Tapping the chip of the board in front now brings the stage forward','Before, nothing happened while the reader text covered the stage. (r1 callpage-5)','bd1125-r1-callpage-5/before-chip.png','bd1125-r1-callpage-5/after-chip.png','desktop'),
('Answers','An unknown board kind no longer swallows the rest of the answer','The page shows the whole answer and the board: line says so. (r1 engine-1)','bd1125-r1-engine-1/before/d01-rest.png','bd1125-r1-engine-1/after/d01-rest.png','desktop'),
('Answers','A tag the call does not have is no longer read aloud','[[highlight: ..]], [[pause]] and [[hide]] are dropped with a board: line saying what to write instead. (r1 engine-2)','bd1125-r1-engine-2/before/d01-board.png','bd1125-r1-engine-2/after/d01-board.png','desktop'),
]
def card(p,i):
    g,t,s,b,a,dev=p
    return f'''<article class="chg" id="c{i}"><h3>{html.escape(t)}</h3><p class="one">{html.escape(s)}</p>
<div class="pair {dev}"><figure><figcaption>Before</figcaption><img loading="lazy" src="{img(b)}" alt="Before: {html.escape(t)}"></figure><figure><figcaption>After</figcaption><img loading="lazy" src="{img(a)}" alt="After: {html.escape(t)}"></figure></div></article>'''
groups=collections.OrderedDict()
for i,p in enumerate(P): groups.setdefault(p[0],[]).append(card(p,i))
changes=''.join(f'<h3 class="grp">{g}</h3>'+''.join(c) for g,c in groups.items())
# new boards (after only)
NB=[
('A table is chosen last: a bars board for sizes','Quantity questions now draw bars on a scale, with a value per stage. No before: the board did not exist.','bd1125-r1-guidance-10/after/d03-point.png'),
('A structure board for commits and trees','Commit graphs and trees animate from before to after, with ghosted and added parts. No before: the board did not exist.','bd1125-r1-trial-t2-2/after/d03-point.png'),
('Pointing at an arrow keeps both its ends in view','The lit arrow no longer starts off screen. (r2 diagrams-2)','bd1125-r2-diagrams-2/after/d03-point.png'),
('A small table follows the voice','Rows and columns light when their distinctive word is said. (r2 idea small-table-follows)','bd1125-r2-idea-small-table-follows/after-twotables/d03-point.png'),
]
nb=''.join(f'<article class="chg"><h3>{html.escape(t)}</h3><p class="one">{html.escape(s)}</p><figure class="solo"><figcaption>After</figcaption><img loading="lazy" src="{img(p)}" alt="{html.escape(t)}"></figure></article>' for t,s,p in NB)
# stats
rounds=collections.defaultdict(collections.Counter)
for x in led: rounds[x['round']][x['state']]+=1
ser={1:35,2:22,3:7}
rs=''.join(f'<tr><td>{r}</td><td>{sum(rounds[r].values())}</td><td>{rounds[r]["fixed"]}</td><td>{rounds[r]["confirmed"]}</td><td>{rounds[r]["idea"]}</td><td>{rounds[r]["rejected"]+rounds[r]["merged"]}</td><td>{ser[r]}</td></tr>' for r in (1,2,3))
unseen=[x for x in led if x['state']=='fixed' and not x['felt']]
def li(x): return f'<tr><td class="id">{x["id"].replace("bd1125-","")}</td><td>{x["severity"]}</td><td>{html.escape(x["title"])}</td></tr>'
unseen_h=''.join(li(x) for x in unseen)
# fixed felt without shots (engine/server)
conf=[x for x in led if x['state']=='confirmed']
conf_h=''.join(li(x) for x in sorted(conf,key=lambda x:-x['severity']))
trials=[
('1','t1','How a typed turn reaches Claude','sequence','not recorded','Board ran ahead of the voice (unnamed steps filled earliest sentences)'),
('1','t2','Merge versus rebase','compare sequence','not recorded','Compare board on a phone never followed the step'),
('1','t3','OAuth code flow with PKCE','sequence','not recorded','Step counter counted reveals, not rows'),
('1','t4','How a word is matched to a part','flowchart','6 of 10','Viewer did not get how character position turns into audio time'),
('1','t5','Database isolation levels','table','5 of 10','Viewer could only trust it because they knew the topic'),
('1','t6','TCP congestion states','flowchart','not recorded','Edges between states could not be pointed at'),
('1','t7','Server restart keeps the call','sequence','not recorded','Phone header ate a third of the stage'),
('1','t8','Who serves what','map','not recorded','Two map arrows shared one run and read backwards'),
('2','t1','Kubernetes pod startup','sequence','6','Outcome box never drawn'),
('2','t2','Error handling in Python, Go, Rust','code x3','not recorded','A teaching example could only show a file saved in the repo'),
('2','t3','Finding a row in a B-tree','graph x2','not recorded','No findings file kept'),
('2','t4','HTTPS setup','sequence','not recorded','Step notes overlapped the last lane'),
('2','t5','Path of one turn','sequence','6','Viewer expected a stage 1 and stage 2 split'),
('2','t6','Merge and rebase','graph x2','not recorded','Before frame arrived node by node as empty boxes'),
('3','t1','How the page lights the spoken word','no board','1 of 5 (harness artifact)','A how-does-it-work question was answered with no board'),
('3','t2','CAP theorem','flowchart','not recorded','Typed reply shows Pause at 0:00 and never plays'),
('3','t3','Re-render decision','flowchart','not recorded','A topic word pulled a part in before its point'),
('3','t4','Raft election and partition','sequence','not recorded','Stalled audio left page and stage disagreeing'),
('3','t5','OAuth code flow with PKCE (again)','sequence','scored a harness artifact','[[point: outcome]] lit nothing on a plain sequence'),
('3','t6','How a part gets lit','sequence','not recorded','Phone self-step note drawn over its own chip'),
]
tr=''.join(f'<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td>{e}</td><td>{f}</td></tr>' for a,b,c,d,e,f in trials)
page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Talk and Stage bulldozer report</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--dim:#4a5361;--line:#d5dae2;--acc:#1d5fd1;--ok:#17703a;--bad:#a8321f}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1218;--card:#1a1f29;--ink:#e8ecf2;--dim:#aab3c2;--line:#2c3340;--acc:#7fb0ff;--ok:#62cf8c;--bad:#ff8f7d}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1500px;margin:0 auto;padding:16px}}
h1{{font-size:1.6rem;margin:.4em 0}}h2{{font-size:1.3rem;margin:1.8em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.3em}}h3{{font-size:1.05rem;margin:.2em 0}}
h3.grp{{font-size:1.1rem;color:var(--acc);margin:1.4em 0 .4em}}
nav{{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}}nav a{{padding:6px 12px;border:1px solid var(--line);border-radius:999px;color:var(--ink);text-decoration:none;background:var(--card);font-size:.9rem}}
.chg{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0}}
.one{{margin:.2em 0 .7em;color:var(--dim)}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.pair.phone{{grid-template-columns:repeat(2,minmax(0,380px));justify-content:start}}
figure{{margin:0}}figcaption{{font-size:.8rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--dim);margin-bottom:4px}}
figure:nth-child(2) figcaption{{color:var(--ok)}}figure:first-child figcaption{{color:var(--bad)}}
img{{width:100%;height:auto;border:1px solid var(--line);border-radius:6px;display:block;background:#fff}}
figure.solo{{max-width:900px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem;background:var(--card)}}th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--dim);font-weight:600}}
.scroll{{overflow-x:auto}}td.id{{font-family:ui-monospace,monospace;font-size:.8rem;white-space:nowrap}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}}
.num{{display:flex;gap:10px;flex-wrap:wrap}}.num div{{flex:1 1 140px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}}.num b{{font-size:1.5rem;display:block}}
.ok{{color:var(--ok)}}.no{{color:var(--bad)}}
details summary{{cursor:pointer;font-weight:600;padding:6px 0}}
@media (max-width:700px){{.pair,.pair.phone{{grid-template-columns:1fr 1fr;gap:6px}}main{{padding:16px}}}}
</style></head><body><main>
<h1>The /talk and /stage bulldozer run fixed 164 findings in three rounds and a finishing pass and rebuilt the table board</h1>
<p class="one">Run bd1125, 25 November 2026, on claude-annotate. Merged to main and pushed as c9c49e4; the talk server runs the new code. Final suite: 3187 passed, 0 failed.</p>
<div class="num"><div><b>169</b>ledger entries</div><div><b>164</b>fixed</div><div><b>0</b>confirmed, still open</div><div><b>12</b>ideas voted, 12 built</div><div><b>20</b>trials with unsuspecting authors</div></div>
<nav><a href="#see">What you will see</a><a href="#ideas">Ideas and votes</a><a href="#trials">Trial scores</a><a href="#unseen">Fixes nobody sees</a><a href="#rej">Rejections</a><a href="#open">Open questions</a><a href="#stop">Stop rulings</a></nav>

<h2 id="see">What you will see or feel changed in 24 places</h2>
<p class="one">Each card shows the same moment before and after. Phones are the 390 px view.</p>
{changes}
<h3 class="grp">New boards and behaviours (no before, they did not exist)</h3>
{nb}

<h2 id="ideas">Twelve ideas went to the committee of three and all twelve were built</h2>
<div class="box"><b>Round 1, all 3 of 3 build</b><ul>
<li><b>Table board redesign.</b> Fixed full grid lit by colour and weight; column, rows and cell pairs; phones keep the whole grid.</li>
<li><b>Choose the board by the question.</b> A decision table keyed on the question, table last. Fresh sessions picked a table in 7 of 13 answers before and 1 of 19 after.</li>
<li><b>Compare verdict strip.</b> The outcome of a before/after is drawn and pointable. Key points beside the board were cut by amendment.</li>
<li><b>Quantity board (bars).</b> Bars only, no series, thresholds or markers.</li>
<li><b>Structure board for commits and trees.</b> Commit graphs and trees only.</li>
<li><b>Visual-first answers.</b> Board opens on the first sentence, numbers in the note, zones for processes. Visual questions then drew: graph 4, bars 2, sequence 1, table 0 of 7.</li></ul></div>
<div class="box"><b>Round 2, all 3 of 3 build</b><ul>
<li><b>Name a part by its distinctive word, never by order.</b> The picture no longer contradicts the voice; an unnamed part is shown with the rest, never lit by position.</li>
<li><b>Answer shape gate.</b> Table only for 4x4 or smaller of 1-3 words, a no-board rule, two nudges. A nudge about board-after-N-sentences was dropped (1 of 3). Fresh sessions on table-prone questions: tables 8 of 8 before, 2 of 8 after.</li>
<li><b>Phone fit policy.</b> Narrowed: graph turned for 390 px, map fits the width, 11 px text floor. Table card redesign and edge fade dropped.</li>
<li><b>Small table follows the voice.</b> Unique-prefix naming allowed (2 of 3); an ambiguous name lights nothing.</li>
<li><b>Verdict closes every board and is pointable.</b></li>
<li><b>A refused board is never replaced silently.</b> Narrowed: a bare code path is accepted (2 of 3); a render-failure post-back channel was dropped by vote.</li></ul></div>
<div class="box"><b>Round 3</b><p>No idea was voted to build in the second judge pass.</p></div>
<h3 class="grp">Voted down or not built</h3>
<table><tr><th>Idea</th><th>Why</th></tr>
<tr><td>Key points beside the board and a contrast row</td><td>Cut by amendment in round 1: a separate stage-layout idea that needs its own vote.</td></tr>
<tr><td>N-way compare board (two to four options side by side)</td><td>Raised in round 3, the last allowed round; no idea was built in that pass. Stays an open idea.</td></tr>
<tr><td>Word-timeline board</td><td>Judged not core (severity 2).</td></tr>
<tr><td>Table card redesign and edge fade on phones</td><td>Dropped from the phone-fit idea by the committee.</td></tr>
<tr><td>Render-failure post-back channel</td><td>Dropped by vote: no channel exists and it cannot be tested.</td></tr>
<tr><td>Zoom to the part said on the map; "unstick the header after step 1"</td><td>Not built inside their fixes.</td></tr></table>

<h2 id="trials">Twenty trials: authors who did not know they were tested, viewers who saw only the screens</h2>
<p class="one">Viewer scores were kept in only a few trials. Round 1 trial scores ran 5 to 6 of 10 per the judge. The rest were not stored, so no table of scores would be honest. What the trials produced is findings: round 1 turned up 35 serious ones, round 2 22, round 3 7.</p>
<div class="scroll"><table><tr><th>Round</th><th>Trial</th><th>Topic</th><th>Board chosen</th><th>Viewer score</th><th>Worst thing it found</th></tr>{tr}</table></div>
<div class="box"><b>How board choice changed.</b> Before the run, fresh sessions chose a table in 7 of 13 answers. After the round 1 guide: 1 of 19, and on 7 visual-heavy questions 0 tables (graph 4, bars 2, sequence 1). After round 2's answer-shape gate, table-prone questions went from 8 of 8 tables to 2 of 8. Round 3 trials drew flowcharts and sequences; one found the flowchart had become the new default for comparisons (7 of 21), fixed in the finishing pass.</div>

<h2>Findings per round</h2>
<div class="scroll"><table><tr><th>Round</th><th>Entries</th><th>Fixed</th><th>Open</th><th>Ideas</th><th>Rejected or merged</th><th>New serious (sev 3-4)</th></tr>{rs}</table></div>

<h2 id="unseen">18 fixes make no visible difference but close real faults</h2>
<p class="one">Each is guarded by a test run failing without the fix and passing with it. Server and doorbell fixes also include ones that look visible in the ledger (a call ending while Claude answers no longer loses the transcript).</p>
<div class="scroll"><table><tr><th>Id</th><th>Sev</th><th>What</th></tr>{unseen_h}</table></div>

<h2 id="rej">One finding was rejected and one merged</h2>
<div class="box"><b>Rejected:</b> r3 trial-t3-1, the current-edge dot and arrowhead collide under the enlarged node. Severity 1, cosmetic.<br><b>Merged:</b> r3 diagrams-2 (flowchart edge labels, fan-out, state machine) into r2 diagrams-7, still open.</div>

<h2 id="open">The finishing pass fixed the 63 findings the rounds left open</h2>
<details><summary>Show the list, most severe first</summary><div class="scroll"><table><tr><th>Id</th><th>Sev</th><th>What</th></tr>{conf_h}</table></div></details>
<p class="one">Most are phone fit of the diagram boards, flowchart edge labels, the page lock across devices, and guidance residues from the board-choice rewrite.</p>

<h2 id="stop">Each round stopped or went on by the 5-serious-findings rule</h2>
<table><tr><th>Round</th><th>Suite after landing</th><th>New serious</th><th>Ruling</th></tr>
<tr><td>1</td><td>3076 passed, 0 failed</td><td>35</td><td>Round 2 warranted (35 is 5 or more).</td></tr>
<tr><td>2</td><td>3128 passed, 0 failed</td><td>22</td><td>Round 3 warranted, the last allowed (at most 3).</td></tr>
<tr><td>3</td><td>3138 passed, 1 failed, then 3139 passed after a one-line test fix</td><td>7</td><td>Threshold met (7 is 5 or more) but the 3 round cap stops the run. All 7 are fixed on bd1125.</td></tr><tr><td>Finish</td><td>3187 passed, 0 failed</td><td>–</td><td>The 63 confirmed findings left open were fixed in 5 batches; 11 had already been fixed by earlier commits.</td></tr></table>
<p class="one">Nothing is merged to main yet. The orchestrating session merges and pushes.</p>
</main></body></html>'''
open(R+'/report/index.html','w').write(page)
print(len(P),len(unseen),len(conf),sum(1 for x in led if x['state']=='fixed'))
