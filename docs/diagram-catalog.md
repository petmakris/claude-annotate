# Diagram catalog

Every place your projects make a diagram, what draws it, where it shows, and whether it moves to the shared diagram library (sequence and map, in claude-annotate `skills/_shared/visuals/`). Scanned 2026-10-15.

| Project | Producer | Kind | Tech | Shows in | Count | Plan |
|---|---|---|---|---|---|---|
| ai-building-blocks | Overview diagram per block (`diagrams/*.svg`) | architecture map | hand-written SVG, story.css classes | story page, `/slides/`, slide PNGs | 17 | library: map |
| ai-building-blocks | Walkthrough per story page (`tools/story_page.py` `diagram()`) | sequence | SVG generated in Python from the store | story page, lit as you scroll | 17 | library: sequence (option A), plus route reveal (option C) |
| ai-building-blocks | Flows on the reference pages (`tools/build.py` `sequence()`) | sequence | Mermaid 11.4.1 from a CDN | reference pages | ~210 | library: sequence |
| ai-building-blocks | Lifecycles on the reference pages (`tools/build.py` `state_diagram()`) | state | Mermaid 11.4.1 | reference pages | ~113 | stays: state diagrams are not one of the two types |
| ai-building-blocks | Request path on the home page (`tools/build.py`) | flowchart | Mermaid | home page | 1 | stays: flowchart |
| ai-building-blocks | Diagram checker and slide export (`tools/diagrams.py`) | tool | Playwright Chromium | fault list, light and dark PNGs | 1 | library: becomes its checker |
| claude-annotate | `/annotate` sequence block (`_shared/visuals/sequence.py`) | sequence | SVG generated in Python on push | annotate page; PNG to Confluence | per answer | library: sequence |
| claude-annotate | `/annotate` flowchart block (`_shared/visuals/flowchart.py`) | flowchart | SVG in Python, ELK layout through node | annotate page; PNG to Confluence | per answer | stays: flowchart |
| claude-annotate | `/stage` and `/talk` lanes (`stage/static/lanes.js`) | sequence | DOM and SVG in the browser, revealed by frames | stage page, talk call page | per board | library: sequence |
| claude-annotate | `/stage` and `/talk` map (`stage/static/map.js`) | flowchart as cards | DOM cards and SVG edges, revealed by frames | stage page, talk call page | per board | library: map, for architecture boards |
| claude-annotate | `/stage` Mermaid board (`stage.js` `drawDiagram`) | any Mermaid | Mermaid 11.17.2, vendored | stage page | per board | stays for now: talk already turns Mermaid graphs into maps |
| claude-annotate | `/stage` and `/talk` scenes (`stage/static/scene.js`) | hand-written HTML parts | DOMPurify or a sealed iframe, revealed by frames | stage page | per answer | stays: the reveal engine the library plugs into |
| claude-annotate | `/dataflow` board and field canvas (`dataflow/fields/engine/`) | field mapping | own DOM engine, network-simplex layout | annotate page, standalone HTML | per answer | stays: a third kind |
| claude-annotate | `/slides` and `/deck` (`.flow` chain, inline `svg.diag`, `frag` reveal) | any | hand-written HTML, CSS and SVG | deck HTML, PDF | per deck | library: map and sequence as deck parts, one PNG per step |
| dashboard | Mermaid in task notes (`lib/mermaid.ts`, `MermaidBlock.tsx`) | any Mermaid | Mermaid 12.0.0, themed from app tokens | dashboard web app | per note | stays for now |
| dashboard | Presentation decks (`presentations/*/*.html`) | sequence, architecture, metro map | hand-typed inline SVG, 1280 canvas | browser deck, PDF, PNG, Confluence | ~15-20 in 13 decks | library: new decks use map and sequence |
| dashboard | AI Friday 06.06 Mermaid files (`assets/diagrams/*.mmd`) | flowchart | `mmdc` to PNG and SVG | files for PowerPoint | 2 | stays: one-off |
| wp-skills | Information-flow map (`scripts/docscheck/flowmap.py`) | flowchart | Mermaid in mkdocs, `mmdc` SVG with a hash stamp | docs site, SVG for decks | 3 | stays: Mermaid on purpose, so a PR diff shows the change |
| wp-skills | `wp trace` (`wp/src/wp/trace/web/engine.js`) | field mapping | JS card-and-wire engine, forked from annotate's dataflow | standalone HTML, api.mac, PNG shots | per trace | stays: a third kind |
| wp-skills | wp-atlas architecture map (`topology.py`, `answerview.py`) | architecture map | SVG from Python at fixed coordinates (ADR 0018) | Atlas report page | 1 per report | stays: its colours are honesty grades (ADR 0018) |
| wp-skills | Knowledge-architecture figures (`docs/adr/assets/knowledge-architecture/`) | architecture | hand-written SVG, IBM Plex | ADR page, standalone SVG | 3 | library: candidate to redraw as maps |
| wp-skills | Rules: P-148 paired sequence diagrams, blueprint policy (no diagrams) | rules | markdown | Claude instructions | 2 | library: P-148 maps onto the sequence type |
| wp-architecture | LikeC4 model and views | architecture, 2 sequence views | LikeC4 1.59.4 | local site on port 5190 | ~32 views | stays for now; you judged it "too much" |
| lomem | Mermaid in docs and ADRs | 4 sequence, 4 ER, 2 flowchart | Mermaid on GitHub | markdown on GitHub | 10 | sequence ones: library; ER and flowchart stay |
| lomem | Database diagram (`tools/db-diagram/`) | ER | React Flow viewer from the Prisma schema | offline HTML | 1 | stays: ER |
| lomem | Parrot decks (`docs/presentations/parrot-*.html`) | architecture, journey | HTML and CSS boxes, almost no SVG | browser deck | 3 | library: new decks use map and sequence |
| ~/.claude skills | code-archaeology, mentee-task-pack (synced from claude.ai) | architecture | instructions to hand-write inline SVG | self-contained HTML | rules | library: point them at the library |
| env | Global rules (`claude/CLAUDE.md`): rendered HTML, contrast targets, Inter, arrow direction | rules | markdown | every session | rules | library: gains the rule to draw through the library |
| env | Toolkit installs graphviz, d2 with TALA, structurizr-cli | tools | installed, unused | none | 0 uses | stays: unused |

Not scanned: the blog, which exists only in machine backups. Duplicates in worktrees and checkouts are counted once.
