# Board details: map, sequence, compare, flowchart, screen, code

The core guide (`SKILL.md`) says which board to pick and shows one example each. This file holds every field and every rule of how a board draws. The full spec fields are in `$SKILL_DIR/../annotate/references/block-kinds/sequence.md` and `flowchart.md`, and the map spec is in `$SKILL_DIR/../../docs/vz.md`.

## Paths and files

- A relative path is read inside `--code`.
- A `code` or `change` board also takes an absolute or `~` path to a file in any git work tree, such as another checkout or a branch cloned into the scratchpad.
- Its change is read in that file's own repository, and the board names it `<repo folder>/<path>`.
- A file git ignores, a path through `.git` and a hidden folder of the home folder (`~/.ssh`, `~/.config`) are refused, since the stage is served to other machines.
- A `page` file still has to be inside `--code`.
- `code` shows at most 60 lines you read in this turn. `highlight 44-47` before the bar marks lines.
- `change` is read from git: the file against HEAD, or against another revision with `since <rev>` (`talk/talk.py since HEAD~2`). A new file shows as all added.

## Map

- An architecture map is the map spec of `docs/vz.md`: `columns`, `boxes` on a grid, `zones`, `arrows`, each part's build step `b` and route step `r`, and `"layer": "route"` arrows with a badge `n`.
- Give it a title that states the claim.
- Draw each process as a zone with its name and port, around the boxes it serves. A named part gets its own box, never only a column header.
- A forbidden relation is an arrow with `"tone": "red", "dash": true` and the label `never`. Draw only relations you speak about.
- With no verbs, each box or zone arrives with the first sentence that names it (its `name`, a zone's `label`).
- Parts no sentence names fill the sentences that name nothing, in build order (`b`). A box inside another rides in with it unless its own `b` is later.
- When the answer follows a request, the route's arrows arrive a step at a time, each with the sentences that name it (its arrow's `label`, or the step's caption title in `captions.route`).
- The box a route step arrives at is said with it, and the parts the request has not reached yet are faint.
- An answer that never names a route step leaves the route alone.
- Verbs: `[[next]]`, `[[all]]`, `[[+ box ask]]`, `[[+ zone 0]]` (a zone by its place in `zones`, from 0), `[[+ route 2]]` and `[[+ ask->svc]]` (a structure arrow by its two boxes).
- Points: `[[point: box ask]]`, `[[point: zone 0]]`, `[[point: route 2]]`.
- The reader can tap any part shown for Ask about this and Play from here.

## Sequence

- A sequence is drawn as lanes: whole from the start, the steps not said yet faint, the step being said on an accent band.
- Each actor is a box over its lifeline in its `tone`: `blue` the AI or model path, `red` the central mechanism, `green` a rule that holds, `amber` a cost or a warning. An actor with no tone is plain, since a colour carries a meaning.
- Under its name go its `role` (what it is) and its `sub` (its file or service, such as `talk.py`).
- A call carries its `label` and its `sub` in a chip on its arrow. A reply's words sit bare over its dashed arrow.
- `checks` on a step (`[{"label": "scopes", "ok": true}, {"label": "already paid", "ok": false}]`) are tick and cross badges under its arrow.
- A phase is a band behind its steps. `n` numbers the walkthrough (several arrows may share one).
- An `outcome` (`{"tone", "title", "lines"}`) is a box that closes the diagram once the last step is shown.
- `reply_to` on an `event` names the `request` it answers, and it must go back the way the call came. The call then holds a bar open on its receiver until the reply, with calls made inside it nesting their bars. This is how a wait is drawn.
- `groups` puts boxes round runs of steps: `{"id", "kind": "alt" | "par", "branches": [conditions]}` or `{"id", "kind": "loop" | "opt", "label": condition}`. A step joins one with `"group"` (and `"branch": 0, 1, ...` in an `alt` or `par`; a branch written `else` or `otherwise` reads as else).
- `ref` on a step (`talk/talk.py:2213`, relative to `--code`) gives its popup the source lines round that line.
- A box's steps follow one another and stay inside one phase.
- The reader can click any step for its popup (the call, those source lines, the step it answers, and Play from here), click an actor's card to follow it, and fold a box or a phase.
- A step's `arrow` is `request`, `event` (dashed), `self` or `band` (a sentence laid across actors).
- `sub` is a monospace line under the label, for a version or a path. `note` is a short right-hand value such as a date.
- Write every `label` as a short phrase that reads on its own, 3 to 8 words, with the sender as its implied subject ("turns the recording into words").
- On a phone a sequence of five actors or more draws each actor as its number, with the names once in a key above the lifelines and the actors of the step being said named under the numbers, so name an actor in a few words and do not count on its `role` or `sub` being shown there. Once the answer is over the board returns to its top.
- Each actor's chip is as wide as the space between two columns and wraps its `label`. On a phone a board of many actors puts every other chip on a second line, so keep actor labels to two or three words.
- With no verbs, each step comes in with the first sentence that names it (more than half the words of its `label`, or its id), each arrow arriving with its second end.
- A sentence that names nothing, such as an introduction, brings nothing. A `[[point ...]]` brings in what it lights.
- Parts no sentence names fill the sentences that name nothing, in order, and a `board:` line counts them.

## Before and after (a sequence with compare)

- Write one sequence whose spec holds `compare` instead of `actors` and `steps`: `{"title": "...", "legend": [...], "compare": {"before": {"label": "master", "actors": [...], "steps": [...]}, "after": {"label": "with the PR", "actors": [...], "steps": [...]}}}`.
- Each side is a sequence of its own, with the same fields and checks, so every step is a real call. Its `label` names it over its diagram. `title` and `legend` sit beside `compare`.
- `phases`, `groups` and `captions` are not supported with it. An `outcome` (`{"tone", "title", "lines"}`) is one verdict drawn once across both sides under the last row, faint until the last step is shown, lit by `[[point: outcome]]`, by the sentence that says the last step and at rest. Close a before/after answer by pointing at it (`amber` for a warning).
- The stage draws the two flows side by side, the before on the left and the after on the right, lined up row by row.
- A step in both flows sits level with itself. A side with no step in a row shows a hatched gap.
- A gutter marks each row: `=` the same, `~` changed, `+` new, `-` removed, an up-down arrow for moved.
- The stage pairs steps by id, else by the same `label` and `arrow`. Give a step the same id on both sides when it is the same step.
- A pair is the same row when only a replaced actor tells them apart, changed when its words differ too (the words that changed are bold, red on the left and green on the right), and moved when it runs between other actors that are on both sides or stands out of order.
- An actor on one side only is red and "removed" on the left or green and "new" on the right.
- `[[point: before]]` or `[[point: after]]` dims the other side. On a phone, where one side shows at a time, it switches the side. `[[point: both]]` brings both back.
- `[[point: step b2]]` lights that row on both sides. The before row of a moved step is `step was~b2`.
- Tell the before story first and the after story second: a sentence that names the words a step had before brings its row too.
- A malformed `compare` (a side missing, a side with fewer than two actors, a step naming an unknown actor) is not shown, and a `board:` line quotes why. `[[point: before]]` on a board with no `compare` is a `board:` line too.
- The demo's "Backtesting before and after" has a whole answer.

## Flowchart

- A flowchart node's `role` is `entry`, `code`, `call`, `decision`, `success` or `error`.
- An edge may set `"line": "dashed"` and `"heads": "both"` or `"none"`.
- On the stage a flowchart is a map: the whole of it shows from the start as faint dashed ghosts, and each part lights up as you reach it.
- The part being said is drawn large with its `ref` or `method` and its `sub` under its label.
- Give every node a short `label` (2 to 4 words), its file or call in `ref` or `method`, and one line on what it does in `sub`.
- A map reads left to right, or top to bottom on a narrow board. A long name wraps inside its card.
- Loops still read in one direction: every way back runs under the map, or up a lane on the right when it reads top to bottom. An arrow from a part to itself is a small loop over that part.
- With no verbs, each node comes in with the first sentence that names it, as on a sequence.

## Mermaid

- A call draws no Mermaid. A Mermaid graph or state diagram you write is turned into a map, and any other kind is not shown. Write the JSON spec.
- On the map a Mermaid subgraph has no box: each of its parts says under its label which subgraph it is in.
- An arrow to or from the subgraph joins the parts at its ends, and a verb or a point can name the subgraph to bring or light all its parts.
- A Mermaid link keeps its look: a dotted one is dashed, `<-->` has a head at both ends, `---` none, and `~~~` is no arrow. A `<<choice>>` state is a decision.

## Screen

- A screen board is a spotlight spec (`$SKILL_DIR/../spotlight/SKILL.md`): its screenshots or HTML screens, each with its parts, made before the call (capturing screens takes minutes).
- One screen shows at a time, dimmed except the part being said, which is ringed and joined by a dashed line to its count, title and text beside it.
- Each part comes in with the sentence that says its title (more than half of its words), so say the titles.
- `[[point: part 3]]` (the parts are numbered in the spec's order) or `[[point: part "Press Create"]]` lights one.
- It is the way to show a site that refuses to be framed (Jira, Confluence, GitHub): its screenshots, never the page.

## Page

- A page is shown whole, all at once, so it is for a thing that already exists (a README, a running app, a document the user asked to see), never for an explanation you built.
- It goes in the answer with `[[show page: ... | title]]`, before the sentence about it. The voice brings it forward there and on every replay.
- A page put up with `stage.py show` during a call opens behind the board in front and the voice can never bring it forward. The tag takes over a copy of the same page already put up by hand.
- A page has nothing to point at.
- Never show a page from a site that refuses to be framed (Jira, Confluence, GitHub, sign-in pages): it draws as an empty board. Give the link in the answer instead (`skills/stage/SKILL.md`).

## Retired: scenes and stops

- The scene tag and the four stop tags (check, guess, say back, deeper) are retired: never write them.
- The stage reads your text, so a page of cards beside it splits the user's attention, and a card of buttons in the middle of an answer breaks it.
