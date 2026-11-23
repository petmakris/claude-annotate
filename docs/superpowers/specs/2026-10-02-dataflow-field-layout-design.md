# Dataflow field layout: the engine derives columns, order and heights from the wires

Date: 2026-10-02. Status: written spec, adversarially reviewed; the review notes at the end list what the review changed and what it left open.

This spec replaces part of `2026-10-02-dataflow-field-canvas-design.md`: decision B (§2), the layout engine (§4), the `slot` and `gaps` knobs (§5) and the measures table (§6). The page, camera, tracing, ports, tones and the checked-render step of that spec stay.

Both judges chose the reader ("docked provenance") design, so this spec builds on it and merges the judges' grafts. A merged prototype settled the points where the grafts conflict. Every number below comes from that prototype, from the shipped engine, or from an exact ILP over all column orders; numbers the review added come from its runs of the same prototype. The prototype (`rv.js`, `ns.js`, `measures.js` and its fixtures) and the review's scripts stay outside the repo as evidence; they are not part of the change.

The merge settled three conflicts:
- **Dock weight and lane clearance.** Judge 2 grafted a ×4 weight on a source's wire and a 13 px lane clearance under cards. Judge 1 showed that the ×4 weight bends copy chains toward side sources. This spec keeps the 13 px clearance and adds a copy weight: a 1:1 copy weighs four plain wires and a source's first hop weighs 7/4 of its kind. `ctxorg` lands exactly level with `tenantId`, and no single source bends a copy block of two wires or more.
- **Port slide.** Judge 1 grafted the optimisation design's slide; judge 2 found arrowheads 5 px from row borders. The slide stays with a 5 px cap, which keeps every port at least 8 px inside its row band (checked on 943 fuzzed specs).
- **Chain and path moves.** Judge 1 grafted the layered design's exact chain and path moves under a work budget; judge 2 saw no gain from them on realistic specs. In the merged prototype they cut crossings by 3.4% on generated specs, reach the ILP optimum on every fixture and keep the reader design's order independence on judge 2's suite, so they stay, joined by a new move that frees a follow card's end row.

The merged design against the three prototypes, on judge 1's 300 generated provenance specs, with one set of measures:

| Design | Crossings | 1:1 copies straight | Source wires level | Gaps inside cards |
|---|---|---|---|---|
| layered | 4739 | 34.6% | 34.4% | 0 |
| optimisation | 4742 | 72.4% | 37.2% | 310 px |
| reader | 4850 | 46.7% | 32.1% | 0 |
| this spec | 4677 | 74.4% | 39.5% | 0 |
| this spec, canonical numbering (review) | 4686 | 74.3% | 39.4% | 0 |

On judge 2's edit-stability suite (44 specs), reversing the card order changes no layout (the layered design changes 5), and adding a context card moves the other cards 12.7 px on average (reader: 16.3). That held on this suite only. On the four fuzz corpora, reversing the card order changed the layout of 49 of 273 one-flow specs, and reversing the edge order changed 39. Stage 0's canonical numbering, added in review, makes both changes impossible for one-flow specs (R8); with it, adding a context card moves the other cards 12.9 px.

## 1. The current layout puts a source far from what it feeds and on the wrong side of it

A reader of a field diagram picks a field on the right and follows its wire back to its origin, or picks an origin and follows it forward. On a private wire spec, called spec W below (it stays out of this public repo, and its card and field ids appear here only as neutral stand-ins), the current engine breaks this in two ways:
- **A source lands in the wrong column.** A card's column is its `slot`, or its spec index when it has none (`engine.js:30`, `:37-49`). The context card `ctxorg` feeds only `remote.tenantId` in column 8, but it was written with `"slot": 1`. Its wire runs 3472 px across seven columns, and crossings rise from 28 to 37 wire pairs.
- **A source lands on the wrong side of the row it feeds.** Moved by hand to column 7, `ctxorg` stacks under `file`, because cards keep spec order inside a column and the least-squares fit keeps that order (`:127-148`). `ctxorg.org` (y 345) feeds `remote.tenantId`, remote's top row (y 190), so the wire climbs 155 px across the three wires `file` sends into `remote.data`. Column 6 repeats the defect: `ctxfmt` sits under `dto` (y 278) while it feeds `file`'s top rows (y 156 and 187).

The user's sketch (image 13) states the target. A consumer card has rows. Source A feeds the top row and sits just left of and above the consumer, level with that row or descending into it. Source B feeds the bottom row and sits left of and below it. A chain of intermediate cards flows in from the left. Sources live next to what they feed.

No tuning of the current engine reaches that shape, for five structural reasons:
- Columns are read from the spec. Nothing computes them, so nothing puts a source next to its consumer.
- Card order inside a column is spec order, and the fit keeps it, so card B can never move above card A.
- Nothing counts or reduces crossings. A long wire may pass only above or below a whole column, a row's height follows one side per sweep, and compaction fights the wires, so copies bend and cards open gaps (`remote` 58 px, `sea` 38 px).
- `--check` fails only on `behind_card` and `label_overlaps`, so both failures exit 0. Its crossing count costs O(E²·S²): 0.9–2.1 s at 60 cards and 300 edges.
- `SKILL.md` asks the LLM author to fix crossings by choosing slots and card order, which are graph-drawing decisions.

## 2. The diagram is read from a field back to its origin, and nine rules follow from that

Each rule is a guarantee of the engine. It names the test that pins it (§8) and, where it can be measured, the `--check` target that fails when it breaks (§6).

- **R1. A wire spans as few columns as the stages allow.** Columns minimise Σ (wires between two cards) × (their column distance), with every wire running right. A source, a card that nothing feeds and that feeds something, sits exactly one column left of the nearest card it feeds. A card with as many wires in as out sits next to what it feeds. Target `source_slack = 0`; brute-force optimality on small graphs.
- **R2. A column is ordered by crossings first, then by the rows its items feed.** No two neighbours in a column (same flow and lane band) can swap to remove a crossing, and neither can two neighbouring wired rows of a follow card. When crossings tie, items stack in the order of the rows they feed. Target `improvable_swaps = 0`; the sketch fixture's middle column reads A, the intermediate card, the long wire, B; crossings equal the ILP optimum on every fixture.
- **R3. A copy is a straight line.** A 1:1 copy (its row sends one wire, its target row receives one) keeps both rows the same height and weighs four plain wires, so it is drawn straight unless the stacking forbids it. Tests: every copy in `example-order` is straight, and so are the sketch fixture's `mid → C` copies, `entry.user` and `entry.raw` (§5.1 bends the docks of A, B and `opts` by construction); on spec W all five `remote → http` copies are.
- **R4. A source sits as level with the row it feeds as its column allows.** When another item holds that height, the source sits on its row's side of that item: above an item that feeds lower rows, below one that feeds higher rows, as A and B do in the sketch. Target `loose_sources = 0`; `example-context` docks level; in the sketch fixture A's box ends above the consumer's and B's starts below it.
- **R5. A long wire runs as an express lane.** It runs flat across every column it skips, at the place the column order gives it, which may lie between two cards. It never passes behind a card. Its lane-to-lane hops are the heaviest pull in stage 6 (8000), so it bends between two skipped columns only when the column orders leave it no common height. This happens once on spec W: `sp.draft → sea.supplier` runs above `req` in column 1 and under the three `req` lanes in column 2, and drops 68 px between them. Target `behind_card = 0`; the corridor spec; flat samples over each skipped column.
- **R6. Wires that share a row keep their order.** Each gets its own port, ordered by the wire's other end, and every port stays at least 8 px inside its row band, so a reader tracing back can tell which row a wire enters. Tests: distinct ordered ports; the 8 px margin.
- **R7. A card is one rigid record.** Its rows touch, in declared order unless the card says `rows: "follow"`; then wired rows follow their wires and rows without wires trail. Tests: no gap and no overlap between consecutive rows; real order holds.
- **R8. Spec order and `slot` place nothing.** The same cards and wires, in any order and with any slots, draw the same picture. Every tie and every processing order uses the canonical numbering of stage 0 (cards by id, edges by their two ends), never the position in `cards[]` or `edges[]`. Spec order decides exactly three things: separate flows stack in the spec order of their first cards, a card without wires joins the column of its spec neighbour, and a spec without edges lays its cards out left to right. Test: identical `__layout`, with wires and labels matched by their two ends, when slots are removed, zeroed or scrambled, when the card order is reversed and when the edge order is reversed, on every one-flow fixture.
- **R9. The same spec always draws the same picture.** Nothing measures the DOM, every sort has an explicit last key, and the ordering budget counts work units. Test: determinism.

## 3. The spec format shrinks: `slot` and `gaps` stop placing anything

The author writes cards, fields and edges, plus `rows: "follow"` where field order means nothing. Nothing in the spec places a card.

- **`slot` becomes a legacy key that the engine never reads.**
  - `render.py` still refuses a slot that is not a whole number, `"slot": null` included, so the live test `test_malformed_cards_are_refused_with_a_clear_error` keeps passing and no spec changes validity.
  - It no longer compares slots with edge direction, so the "must run left to right" error goes.
  - When any card carries `slot` or the spec carries `gaps`, `main()` prints one line to stderr: `note: "slot" and "gaps" are no longer read; columns and gap widths come from the wires`.
  - `render()` validates first, then drops `slot` from every card and `gaps` from the spec before it embeds the spec in the page. A spec with legacy keys therefore gives the same page, byte for byte, as the same spec without them.
  - Spec W draws the identical picture with `ctxorg` at slot 1, at slot 7, or with no slots at all.
- **`gaps` becomes a legacy key with the same note.** It was keyed by slot value, which no longer names a column. Gaps size themselves from labels and climbs, and stage 9 widens a gap that a label needs.
- **The order of `cards[]` and `edges[]` places nothing**, beyond the three things R8 names. Ties go to the canonical numbering of stage 0, so an author or an LLM that rewrites the spec in another order gets the same picture.
  - A card without wires goes into the column of the nearest card with wires listed before it (else after it), below everything else in that column. Several such cards in one column keep spec order.
  - Separate flows stack in the spec order of their first cards.
  - A spec with no wires at all gets one column per card, in spec order, top-aligned.
- **`rows: "follow"` keeps its syntax and sharpens its meaning.** Wired rows are ordered against the columns on both sides (fewest crossings; ties follow the rows they feed), and rows without wires trail in declared order. Today rows follow their sources only, and rows without wires keep their place; `SKILL.md` documents the change.
- **`lane: "above" | "below"` keeps its syntax and becomes rare.** The wire's lane items go above (below) every card and free lane item of their own flow in each column they cross. Free lanes already run between cards, so `SKILL.md` documents `lane` for a deliberate side channel only.
- **No new hints are added.**
- **Validation** lives in `render.validate`; the engine re-checks and throws, so `--check` exits 3 when a page skipped `render.py`.
  - Kept: no cards; duplicate card id; duplicate field id; slot not a whole number; a card without fields; unknown `rows`; unknown card or field (`KeyError`); unknown `lane`.
  - New: `edge dto.id → dto.total stays inside card 'dto'; a field cannot feed its own card`.
  - New: `edge a.x → b.y appears twice`.
  - New: `cards feed each other in a loop: entity → dto → json → entity; draw the later stage of one of them as its own card`. A three-colour DFS starts from each card in spec order and visits successors in id order, so the loop it reports is deterministic.
- **Compatibility.** Every spec that validated before still validates, except one that repeats an edge (it was drawn twice over itself). The old rule `slot[to] > slot[from]` already excluded loops and edges inside one card. Every drawing changes (§9).
- **`SKILL.md`, "Field mode", changes to match:**
  - The spec-format block drops `slot` and `gaps`. "Every edge runs left to right…" becomes "Cards never feed each other in a loop, and a field never feeds its own card. If a value comes back, draw the object twice, before and after."
  - Step 4 names the five targets. A nonzero `behind_card`, `source_slack`, `improvable_swaps` or `loose_sources` is an engine regression: hand the file over, say so, and leave the spec alone. A nonzero `label_overlaps` is the one target the author fixes, with a shorter label or note (step 5).
  - Step 5's fix list becomes: `rows: "follow"` on argument lists and wire parameters; a shorter label or note where one still collides; splitting the figure; `lane` for a deliberate side channel. "Card order within a slot, and which slot a card sits in" and `gaps` go.
  - The "Nothing is hand-placed" bullets become R1–R9, one line each.
  - The failure table swaps the left-to-right error for the loop, inside-one-card and duplicate-edge errors.
- **The examples drop `slot`,** so the specs LLM authors copy show the smaller format. The tests re-inject slots to cover compatibility.

## 4. The algorithm runs in twelve pure stages, numbered 0 to 11

The layout moves into a new `fields/layout.js` as pure stage functions (spec in, geometry out), with the solver in `fields/ns.js`. `render.py` inlines both ahead of `engine.js`, so the page stays one offline file. Drawing, camera, trace and chrome keep reading `cards[].x/y/w/h/fields/rowY/rowH` and `routes[].d/samples/texts`.

### 4.0 Every stage shares one set of constants, integer weights and one solver

Sizes: C cards, R rows, E edges, D lane items, H = E + D hops, K columns, n_k items in column k, d wires at an item.

| Constant | Value | Use |
|---|---|---|
| `HEADER_H`, `ROW_H`, `PORT` | 46, 26, 10 | card header, row, port spacing (as today) |
| `CLEAR` card→card, card→lane, lane→card, lane→lane | 40, 13, 42, 16 | gap between vertical neighbours; 42 = 24 + an 18 px stage label |
| `MIN_GAP`, `STEEP`, `STEEP_CAP`, `PER_WIRE`, `MARGIN` | 120, 1, 480, 8, 20 | gap width and left margin (as today) |
| `LABEL_ADV`, `LABEL_H` | 5.1, 11 | text width per character, text height |
| `SLIDE` | 5 | largest port slide, px |
| `SWEEPS`, `PATIENCE`, `ROUNDS`, `REFINE_PASSES`, `LABEL_ROUNDS` | 12, 3, 2, 4, 4 | loop bounds |
| `SWEEP_BUDGET`, `ORDER_BUDGET` | 800 000, 1 500 000 | stage 4 work units |
| `PIVOT_CAP`, `SEARCH` | 40n + 200, 30 | solver |

Card widths keep today's advance-width formula. Every length that reaches a solver is an integer (row halves are 13 + 5k, clearances and offsets are whole), and every weight is an integer (stage 2), so both solves run in exact integer arithmetic and every y is an integer.

**The solver `networkSimplex(n, edges, init)`** minimises Σ weight(e)·(y[head] − y[tail]) subject to y[head] − y[tail] ≥ minlen(e) on an acyclic, connected graph (Gansner, Koutsofios, North and Vo 1993; Graphviz `ns.c`). Stages 1 and 6 use it. Port the prototype's `ns.js` (186 lines; it matched scipy's HiGHS on 600 random problems):

```
merge parallel edges: weights add, the larger minlen wins
1 feasible ranks: Kahn order; y[v] = max(init[v] ?? 0, max over in-edges of y[tail] + minlen)   // throws on a cycle
2 tight tree: grow from node 0 over edges with slack 0 (slack = y[head] − y[tail] − minlen);
  while it does not span: take the least-slack edge with exactly one end in the tree (ties: lowest index),
  shift every tree node by +slack if that edge's tail is in the tree, else by −slack; grow again
3 numbering: one DFS from node 0 gives low/lim (postorder), each node's parent edge, and post[lim] = node
4 cut values, children before parents: cut(e) = Σ weights of edges from e's tail side to its head side
  − Σ weights from its head side to its tail side (per node from its children, as dagre's calcCutValue)
5 pivot while some tree edge has a negative cut value:
    leaving e  = the most negative cut among the next SEARCH negative tree edges, scanning the tree-edge list cyclically
    S          = the end of e with the smaller lim, i.e. the subtree e cuts off
    entering f = the least-slack non-tree edge from e's head side to its tail side, found by scanning the incident
                 edges of the smaller of S and its complement; stop early at slack 0
    shift S by slack(f) so f becomes tight; add ±cut(e) along the tree paths from both ends of f up to their
    lowest common ancestor (Graphviz treeupdate); cut(f) = −cut(e); swap e and f; renumber below that ancestor only
6 stop when no cut value is negative (the optimality certificate) or after PIVOT_CAP pivots (capped; ranks stay feasible)
7 shift so the smallest rank is 0
```

A pivot costs O(tree path + subtree + incident edges of the smaller side). Every scan runs in a fixed order and every tie goes to the lowest index, so the solver is deterministic. `__layoutTiming` records pivots and `capped` per solve.

### Stage 0 validates the spec and builds the model — O(C log C + R + E log E)

```
card = { id, specIndex, canon, width (today's formula), follow: rows === "follow", rows in declared order }
row  = { card, field, declaredIndex, in: [], out: [] }      // hops arriving and leaving, filled by stage 2
edge = { specIndex, canon, from: row, to: row, lane, label, note, tone }
throw on every refusal of §3
canon(card) = rank of its id; canon(edge) = rank of its (from, to) pair; both in UTF-16 code-unit order   // R8
```

Every later stage numbers, sorts and iterates cards and edges by `canon`: solver node numbers, item keys, port ties, the refinement's move order and the label order. `specIndex` is read only where R8 lets spec order decide: the order of flows and the place of cards without wires (stage 1, and their key in stage 2), and the columns of a spec without edges. Published arrays (`wires`, `labels`, and a lane's edge index in `columns`) keep spec order, so `draw()` and tracing keep their indices.

### Stage 1 computes the columns (R1) — under 1 ms

```
w(a, b) = number of field edges from a row of card a to a row of card b
in(c)   = Σ_a w(a, c);  out(c) = Σ_b w(c, b)
flows   = weakly connected components of the cards that have an edge, numbered by their first card in spec order

for each flow F:
  col = networkSimplex(F's cards in canon order, { a → b : minlen 1, weight w(a, b) })   // least Σ w·span, every wire runs right
  for c in F by col descending, ties by canon descending:
    if out(c) > 0 and in(c) = out(c):
      col[c] = min over cards b fed by c of (col[b] − 1)                  // cost-neutral: sit next to what it feeds
  // the solver normalises, so every flow starts at column 0

if the spec has no edge: col[c] = specIndex(c) for every card
else for every card c without an edge:
  col[c]  = col of the nearest card with an edge listed before c in the spec, else after c
  flow(c) = number of flows                                               // below every flow in its column
renumber the column values in use to 0 … K−1
```

A source has the objective coefficient −out(c) and is bounded on the right only by the cards it feeds. If it sat further left than min(col of those cards) − 1, moving it right alone would lower the cost, which contradicts optimality, so `source_slack` is 0 whenever the solve is not capped. A card that feeds nothing sits next to its nearest producer by the mirror argument. Cost: O(pivots·(C + E′)) with E′ ≤ E distinct card pairs.

### Stage 2 turns long wires into lanes and weighs every hop — O(E + D)

```
for each edge e in canon order (i = canon(e)) from row a in column ca to row b in column cb:
  chain = [a, lane(e, ca+1), …, lane(e, cb−1), b]           // one lane item per skipped column
  each consecutive pair of the chain is a hop; a hop knows its edge, its gap (the column of its left end), its two ports
card item: flow = flow(card), cls = 1, key = canon(card), or specIndex for a card without wires (its own group)
lane item: flow = flow(card of a), cls = 0 if e.lane = "above", 2 if "below", else 1, key = C + i
group(item) = (flow, cls)                                    // an item never leaves its group's run in a column

base(h) = 1 row→row | 2 row↔lane | 8 lane→lane               // dot's Ω; the ordering stage uses base only
ω(h)    = 1000·base(h) × (4 if copy(h)) × (7/4 if dock(h))    // the height stage uses ω, always an integer
copy(h) = h runs row→row, its left row has exactly one outgoing wire and its right row exactly one incoming wire
dock(h) = h is the first hop of its wire and the wire's source card has no incoming wire
```

| Hop | ω |
|---|---|
| plain row→row | 1000 |
| copy | 4000 |
| first hop out of a source, row→row | 1750 |
| first hop out of a source that is also a copy | 7000 |
| row↔lane | 2000 |
| first hop out of a source into a lane | 3500 |
| lane→lane | 8000 |
| separation tie-break (stage 6) | 1 |

A copy outweighs any single plain wire or plain source hop on its rows. A source hop outweighs a plain wire. A 1:1 source hop (7000) also outweighs a single copy, and stays lighter than a block of two copies between the same two cards (8000), so one source never bends such a block. It can bend a lone copy: in a chain of single copies with a 1:1 source docked on the last card's neighbouring row, the last copy gives way (the review's pass-through test bent `M3.x → W.x` by 102 px). Keeping the dock factor out of the ordering keeps order independence (judge 2 measured one reversal case lost with it in).

### Stage 3 fixes row heights and card shapes — O(R + H·passes)

```
h(r) = 26 + 10·max(0, max(|in(r)|, |out(r)|) − 1)             // a port per wire, as today; a row without wires is 26
repeat until nothing changes:                                  // a copy keeps both rows the same height
  for each copy hop a → b: h(a) = h(b) = max(h(a), h(b))
shape(card): off(r0) = 0; off(ri) = off(ri−1) + (h(ri−1) + h(ri))/2
             top = h(r0)/2 + HEADER_H; bot = off(last) + h(last)/2; span = off(last)
shape(lane): off = top = bot = span = 0
sep(u, v) = bot(u) + CLEAR(u, v) + top(v)       // least distance between the anchors of consecutive items
anchor    = a card's first-row centre, or a lane's y
```

The 13 px card→lane clearance lets a lane run one row pitch under a card, so a source stacked above a lane can sit level with the row next to the one the lane enters (`ctxorg` in §5.2).

### Stage 4 orders every column (R2, R5) under a work budget

**4.1 Estimates and exact counts.**

```
stack(k): anchor(first) = 0; anchor(next) = anchor(prev) + sep(prev, next);
          shift column k so its extent [anchor(first) − top(first), anchor(last) + bot(last)] is centred on 0;
          y(port) = anchor(item) + off(port)
rank(k):  number the ports of column k from 0, top to bottom
bary(it, s)    = Σ_{p ∈ it} Σ_{h ∈ hops(p, s)} base(h)·(y(far end of h) − off(p)) / Σ base(h) + span(it)/2
rowBary(p, s)  = Σ_{h ∈ hops(p, s)} base(h)·y(far end of h) / Σ base(h)
                 // both null without hops on side s; bary is where the item's centre would sit if each port met its wire level
crossings(g)   = number of hop pairs in gap g whose left ranks and right ranks are strictly inverted
                 // Fenwick tree, O(H_g log H_g); hops sharing a port never count, because stage 5 orders ports by far end
total()        = Σ_g crossings(g)
pair(u, v)     = (c, r) for u directly above v, over both sides:
                 c = #{(h at u, g at v): rank(far end of h) > rank(far end of g)}   // their crossings now
                 r = #{… < …}                                                     // their crossings after a swap
                 one merge of each item's sorted far-end ranks per side, O(d_u + d_v)
climb()        = Σ_h base(h)·|y(a) − y(b)| on the estimate
```

Swapping two neighbours changes only the crossings between their own hops, which is why `pair` is exact.

**4.2 Sweeps, sifting and transposition** (the reader design, with a budget):

```
reorder(k, s):              // s = R: against what the items feed; s = L: against what feeds them; s̄ = the other side
  for each follow card in k: wired rows by (rowBary(p, s) ?? rowBary(p, s̄)), ties by declared index;
                             rows without wires after them, in declared order; shape
  want(it) = bary(it, s) ?? bary(it, s̄) ?? anchor(it) + span(it)/2
  stable sort column k by (group, want, key); stack(k); rank(k)

sift(k):                    // each item tries every slot of its group run, the others kept in order
  for each u of column k, in the order they stand when sift starts:
    cost(slot) = Σ_{v above the slot} pair(v, u).c + Σ_{v below} pair(u, v).c       // prefix sums over the slots
    move u to the first cheapest slot if it is strictly cheaper than u's own

transpose(rounds):          // adjacent swaps; at equal crossings the rows each item feeds decide
  for each round, at most `rounds`:
    freeze want(it) = bary(it, R) ?? bary(it, L) ?? centre;  want(p) = rowBary(p, R) ?? rowBary(p, L) ?? y(p)
    repeat until a full pass swaps nothing:
      for k = 0 … K−1:
        each adjacent u above v with group(u) = group(v): (c, r) = pair(u, v); swap if r < c, or r = c and want(u) > want(v)
        each adjacent pair of wired rows p above q of a follow card: the same test on their own hops
        stack(k); rank(k)
    stop after a round that swapped nothing

search():
  follow cards: wired rows first, then rows without wires, each in declared order
  sort every column by (group, key); shape; stack; rank
  transpose(ROUNDS)                                  // the first kept order is converged too
  best = snapshot; (bx, bc) = (total(), climb()); stale = 0      // snapshot = column orders + follow-card row orders
  for sweep = 0 … SWEEPS−1 while stale < PATIENCE and work < SWEEP_BUDGET:
    if sweep is even: for k = K−2 … 0: reorder(k, R)              // provenance first
    else:             for k = 1 … K−1: reorder(k, L)
    for every k: sift(k)
    transpose(ROUNDS)
    x = total(); stale = (x < bx) ? 0 : stale + 1
    if (x, climb()) < (bx, bc) lexicographically: best = snapshot; (bx, bc) = (x, climb())
  restore best
```

**4.3 Exact refinement moves.** Each move re-places one object across several columns at once, everything else fixed, and is kept only when `total()` strictly drops.

```
movePath(P = P_0 … P_{n−1}, one item per consecutive column k0 … k0+n−1):
  if a P_t is a lane with cls ≠ 1: return false                 // a pinned lane stays in its band
  remember the current slots; remove P from its columns
  // slot s of column k = before the s-th remaining item (s = their count: at the bottom);
  // P_t lies above remaining item v exactly when s ≤ v
  range_t = the slots inside P_t's group run
  for each gap g = k0−1 … k0+n−1 that exists:
    i runs over the slots of P's item left of g (one index 0 if P has none there); j likewise right of g
    D = zero grid; for each hop x of g with an end on P and each other hop z of g (pairs with both on P counted once):
      left relation "x above z":
        both ends fixed, or both on the same P item: a constant from their ranks (a shared port: skip the pair)
        x's end on P, z's on remaining item v: true for i ≤ v;  z's end on P, x's on item v: true for i > v
      right relation: the same on the right column with j
      add 1 over every (i, j) where the two relations differ                 // ≤ 4 rectangles, 2-D difference array
    prefix-sum D; if P has items on both sides of g: pair_t(i, j) = D(i, j) with t the left item
                  else add D as a unary term to the one side that has an item
  best_0(s) = unary_0(s);  best_t(s) = unary_t(s) + min_{s′} (best_{t−1}(s′) + pair_{t−1}(s′, s))     // s, s′ in range
  backtrack; insert P at the optimum if it is strictly below the remembered slots' cost, else at the remembered slots
  stack and rank the touched columns

chainMove(e)        = movePath(the lane items of e)
freeEndChainMove(e) = for each end row of e that sits in a follow card:
                        for each slot of that row among its card's wired rows:
                          put the row there; chainMove(e); count crossings in the card's two gaps and in e's gaps
                        keep the strictly best row slot with its lane slots, else restore
heavyPath(it)       = from it, step to the item in the next column that receives most of the current item's hops
                      (ties: the one met first, ports top to bottom) while that item lies in the very next column and is
                      not on the path yet; then the same leftwards

refine():
  for pass = 1 … REFINE_PASSES:
    for each edge with lanes, in canon order: chainMove(e)                 // each move starts only if work < ORDER_BUDGET
    for each edge with lanes and an end row in a follow card, in canon order: freeEndChainMove(e)
    paths = [its source card, its lanes, its target card] for each edge with lanes, in canon order,
            then heavyPath(card) for each card, column by column, top to bottom    // listed once, before any path move
    for each path of two items or more, in that order: movePath(path)
    if nothing improved: stop
    for every k: sift(k);  transpose(ROUNDS)
```

The DP is exact for the move it makes. In the prototype, on 162 chain moves its optimum equalled a brute-force search over every slot combination, and on 592 path moves its predicted change equalled the recounted total. The free-end move is what takes spec W with `args` set to `follow` from 12 crossings (where the reader design stops) to the optimum of 10: the `args.documents` row must reach the bottom of `args` together with its lane, and neither move alone gains.

**4.4 A closing pass makes `improvable_swaps` zero.** It freezes the wants once and repeats `transpose`'s swap test (items and follow rows) until a full pass swaps nothing. It is never budgeted. Each swap strictly lowers (total crossings, inversions of the frozen wants) in lexicographic order, so it terminates; on the 60-card stress specs it ran at most 5 passes and 18 swaps (83 swaps on `big8` with canonical numbering, and 3871 on the review's 4130-lane chain).

**Work units.** `pair(u, v)` costs d_u + d_v + 1; `crossings(g)` costs the hops in g; `movePath` costs its grid cells plus 4 per pair tested. One counter runs from the start of stage 4, and both budgets cap it, so the refinement gets what the sweeps left of `ORDER_BUDGET`. `SWEEP_BUDGET` is checked before each sweep and `ORDER_BUDGET` before each refinement move, so one sweep or one move may overshoot by its own cost (one sweep of the `big8` stress spec costs about 0.5 million units). The sift and transposition after a refinement pass and the closing pass are not budgeted. On the 943 fuzzed specs (up to 23 cards) neither budget was reached, and budgeted and unbudgeted runs gave the same crossings; the largest used 1.22 million units (20 cards, 77 edges). The budget binds on the 60-card stress specs only. Counting operations keeps the result identical on every machine.

**Cost.** Sweeps: O(SWEEPS·(Σ n_k log n_k + H log H + Σ n_k²·d + passes·Σ n_k·d)), capped by `SWEEP_BUDGET`. Refinement: capped by `ORDER_BUDGET`. Closing pass: O(passes·Σ d²).

### Stage 5 assigns ports in the order of the far ends (R6) — O(H log H)

```
for each port p and each side s:
  hops(p, s) sorted by (rank of the far end, canon of the edge)
  the i-th of n gets the offset (i − (n−1)/2)·PORT on a row and 0 on a lane     // pa at a hop's left end, pb at its right
```

### Stage 6 solves the heights exactly (R3, R4, R5, R7)

The objective is the weighted L1 climb of every hop, port to port, under the stacking constraints. L1 draws a wire straight or clearly bent, where least squares bends every wire a little.

```
nodes: anchor(it) for every item (one per card: cards are rigid), aux(h) for every hop, one root
edges (tail → head means y_head − y_tail ≥ minlen, costing weight·(y_head − y_tail)):
  root → anchor(first item of column k)          minlen 0                     weight 0     for every column
  anchor(u) → anchor(v)                          minlen sep(u, v)             weight 1     for each u directly above v
  aux(h) → anchor(item of a)                     minlen −(off(a) + pa(h))     weight ω(h)  for each hop h from port a
  aux(h) → anchor(item of b)                     minlen −(off(b) + pb(h))     weight ω(h)    to port b
  // at the optimum aux(h) = min(Ya, Yb), so the pair costs ω(h)·|Ya − Yb| + a constant (Gansner 1993 §4.2)
start: anchors at the stage-4 estimate, rounded; aux(h) = min(Ya, Yb); root = min over first anchors   // already feasible
Y = networkSimplex(…)

port slide, one pass in column order and one in reverse:
  for each row p and side s with n ≥ 1 hops (order of stage 5):
    nominal_i = (i − (n−1)/2)·PORT;  want_i = y(far port of hop i) − (Y(p) + nominal_i)
    lo, hi = the lower and upper medians of want
    t = the current shift if lo ≤ t ≤ hi, else the nearer of lo and hi; clamp to ±SLIDE; round
    offset_i = nominal_i + t                         // order and spacing kept, so crossings cannot change
re-solve with the new offsets, warm-started: anchors at their solved y, aux(h) at the new min(Ya, Yb)

card.y = Y(first row) − h(first)/2 − HEADER_H;  card.h = Y(last row) + h(last)/2 − card.y
shift everything so min(card.y − 30, lane.y − 20) = 0
```

The root edges keep the graph connected at no cost: a spec without wires, or a column of cards without wires, no longer leaves the solver with separate pieces. Never connect it with large negative minlens: the layered prototype's −10⁶ edges did bind and drew a wireless spec 2 000 000 px tall.

The graph has N = items + H + 1 nodes and about 2H + items edges. Measured: 18 pivots plus 7 for the re-solve on spec W (93 nodes: the prototype has no root, which this spec adds for specs without wires); 358–419 plus 64–81 on three 60-card stress specs (1206–1506 nodes); never capped. The re-solve ends the stage, so no source can lower its own climb by moving alone (`loose_sources = 0`), and the slide raised straight copies from 67.4% to 74.2% and level sources from 32.8% to 39.5% on the generated specs.

### Stage 7 sizes columns and gaps — O(K + H)

```
colW[k] = max(130, widest card in column k)            // every card in k is drawn at colW[k], as today
need[g] = max over labels and notes of wires whose first hop is in gap g of (len·LABEL_ADV + 46); stage 9 may raise it
gapW[g] = max(MIN_GAP, need[g], min(STEEP_CAP, max |port y difference| in g · STEEP + hops in g · PER_WIRE))
colX[0] = MARGIN; colX[k+1] = colX[k] + colW[k] + gapW[k]
```

### Stage 8 draws one cubic per hop and one straight run per lane — O(H)

- A hop in gap g is a cubic from (colX[g] + colW[g], y_a + pa) to (colX[g+1], y_b + pb), with control points at 0.55 and 0.35 of the gap, flat at both ends (as today).
- A lane in column k is a straight run at its y across the column. It may now lie between two cards.
- Samples stay at 25 per cubic and 12 per run.
- All hops in one gap share x(t) and differ only in their end heights, so two hops cross exactly once when their end orders are inverted and never otherwise. That is why `crossings` can be counted from ranks.

### Stage 9 places labels and widens a gap until they fit

```
width(t) = len(t)·LABEL_ADV + 4; height LABEL_H; the box sits 9 px above the anchor point
candidates, in order:
  beside the start, above and below:      (x1 + 10, y1 − 6), (x1 + 10, y1 + 13), anchored at the start
  beside the arrowhead (one-hop wires):   (x2 − 12, y2 − 6), (x2 − 12, y2 + 13), anchored at the end
  each lane run at least width + 16 long: its middle, above and below, centred
  the first hop at t = 0.5, 0.3, 0.7, and the last hop at t = 0.5 for wires with lanes: the curve point, above and below, centred
score = (overlap area with card boxes, each grown 2 px sideways and 24 px on top for its stage label, and with texts already placed,
         samples of other wires inside the box, found through a 40 px grid)
take the first candidate with the least score, compared lexicographically; a text left with area > 0 overlaps

fixpoint, at most LABEL_ROUNDS rounds:
  for each gap g that holds the first hop of an overlapping text's wire:
    want    = w1 + w2 + 46       // the two widest texts whose wires start in g; w2 = 0 when there is one
    need[g] = want > gapW[g] ? want : gapW[g] + 40
  redo stages 7–9
```

A round costs O(texts × candidates × (cards + texts + nearby samples)). One advance width now serves sizing and placing (today 4.9 places and 5.1 sizes). Of 864 fuzzed specs, 2 left a text overlapping without the new candidates and the fixpoint; with them, none does. The fixpoint needed one round, on one spec.

### Stage 10 measures the layout — O(H log H + samples + Σ d_u·d_v over neighbours)

§6 defines the measures. `behind_card` tests each sample only against the cards of the column whose x-range holds it, and `crossings` reuses the rank count, so the report no longer dominates the time. `improvable_swaps` is counted hop pair by hop pair (O(d_u·d_v) per neighbour pair), not through stage 4's merge, so a fault in `pair()` shows up as a nonzero target instead of agreeing with itself.

### Stage 11 publishes the layout

- `window.__layout` keeps `cards[id].{x, y, w, h, rows}`, `wires[].{from, to, start, end, samples}` and `labels`, and adds:
  - `cards[id].col` and `cards[id].order` (index in its column, 0 at the top);
  - `cards[id].rowOrder`, the field ids top to bottom. `rows` is an object, and a JavaScript object lists integer-like keys such as `"0"` and `"1"` in numeric order, so its key order is not the row order;
  - `columns: [{ x, w, items }]`, with each item `{ "card": id }` or `{ "lane": edgeIndex }` (the edge's index in the spec), top to bottom;
  - `wires[].hops: [[x1, y1, x2, y2], …]`, port to port.
- `window.__layoutReport` holds the measures of §6, and nothing time-based, so the determinism test keeps comparing it byte for byte.
- `window.__layoutTiming` holds milliseconds per stage, `total`, `work`, `sweeps`, `refinePasses`, `closeSwaps`, `labelRounds`, and `{ pivots, capped }` per solve.
- `window.__measure(layout)` recomputes the report from a published layout, deriving ranks from `columns` and `rowOrder`, so a test can feed it a mutated copy.
- `window.__fieldEngine = { networkSimplex, computeLayout }` serves the solver tests.

### The layout stays under 100 ms at 60 cards and 300 edges while lane items stay under about 900

Cold headless Chromium on an Apple-silicon Mac, median of 5 fresh browsers, total layout time from `__layoutTiming`:

| Spec | Cards / edges / lanes | Time |
|---|---|---|
| spec W | 12 / 45 / 18 | 7 ms |
| stress A (r60-8) | 60 / 300 / 423 | 75 ms |
| stress (r60-20) | 60 / 300 / 498 | 68 ms |
| stress (big8) | 60 / 300 / 573 | 63 ms |
| stress B (L-perf6) | 60 / 300 / 662 | 79 ms: order 42, heights 22, labels 9, report 3 |

The shipped engine takes 939–2119 ms at 60 cards and 300 edges, nearly all of it in the report.

Time follows the lane items D, not the card or edge count. The four stress specs carry 423–662 lane items. The review generated 60-card, 300-edge chains whose wires skip more columns and timed them cold in Node 24 on the same Mac (median of 3 fresh processes; Chromium runs V8 too):

| Lane items | Total | Stage 4 | Stage 6 | Closing swaps | Pivots (solve + re-solve) |
|---|---|---|---|---|---|
| 1129 | 122 ms | 64 ms | 39 ms | 38 | 1399 + 394 |
| 1234 | 126 ms | 66 ms | 40 ms | 28 | 1412 + 394 |
| 2337 | 218 ms | 103 ms | 89 ms | 674 | 2330 + 797 |
| 4130 | 370 ms | 119 ms | 209 ms | 3871 | 3501 + 1383 |

The work budget caps only the sweeps and the refinement. The closing pass and both solves are uncapped, and the solve's pivots grow with N = items + H + 1. The 100 ms bound therefore holds up to about 900 lane items. Real specs sit far below that: spec W has 18 lane items for 45 edges, and the stress specs average 1.4–2.2 per edge. A 60-card spec whose average wire skips four columns does not meet the bound. The review notes list this as open.

## 5. The sketch and spec W come out the way the user drew them

### 5.1 The sketch fixture docks A above and B below its consumer

`example-sketch.json` (made up, to be added) lists its cards consumer first and B before A, the order behind complaint 2, with no slots:
- `C` "POST /things": rows `tenant`, `mode`, `owner`, `file`, `ts` (label "timestamp")
- `B` "not an argument": row `now` ("clock.now()")
- `entry` "handle(…)": rows `body`, `user`, `raw` ("rawUpload")
- `mid` "ThingCommand": rows `mode`, `owner`
- `opts` "ThingOptions": row `mode`
- `A` "not an argument": row `tenant` ("tenantContext.id()")

Edges: `opts.mode → mid.mode`, `entry.user → mid.owner`, `entry.raw → C.file` (label "untouched"), `mid.mode → C.mode`, `mid.owner → C.owner`, `A.tenant → C.tenant`, `B.now → C.ts`.

**Stage 1.** A and B feed only C (in 0, out 1), so they sit at col(C) − 1. `mid` has two wires in and two out, so the tie rule puts it next to C. `opts` feeds only `mid`. `entry` feeds `mid` and C and docks before the nearer one. Columns: {opts, entry} 0, {A, mid, B} 1, C 2. One lane, `entry.raw → C.file`, crosses column 1.

**Stage 4.** The first sweep runs right to left and orders column 1 by what each item feeds in C (tenant 0 … timestamp 4): A, mid, the lane, B. Column 0 follows: `opts` (feeds `mid.mode`) above `entry`. Crossings 0, the ILP optimum. A under `mid` would cross `mid`'s two wires, so no swap is possible.

**Stage 6** (y in px, top = 0):
- `mid.mode` 201 and `mid.owner` 227 equal `C.mode` and `C.owner`: both copies are straight.
- `entry.raw` 253, its lane 253 and `C.file` 253 form one straight line. The lane runs 13 px under `mid` (box 142–240).
- `entry.user` 227 feeds `mid.owner` 227 straight.
- A (box 30–102) ends above C (box 116–292), so it sits above and left of the consumer. Its wire descends from port 94 to 170 into `tenant`. It cannot be level, because `mid` and its header occupy that height, and the sketch draws A the same way.
- B (box 295–367) starts below C, so it sits below and left of the consumer. Its wire climbs from 349 to 284 into `timestamp`.

Report: the five targets 0, crossings 0, `max_dock_climb` 102 (`opts`), `copy_bend` 0, 5 of 8 hops straight, extent 652 × 367. Reversing the card order or adding any slots draws the identical layout.

The shipped engine, given the natural slots (opts and entry 0; A, mid, B 1; C 2), keeps spec order in column 1: B, mid, A. A (y 371) climbs 214 px into the top row, B (y 121) descends 140 px into the bottom row, 10 wire pairs cross, and 3 neighbouring card pairs could swap to remove crossings.

### 5.2 Spec W puts `ctxorg` in column 7, level with `tenantId`

The spec stays out of this public repo; this section uses only neutral stand-ins for its card and field ids. It has 12 cards, 45 edges and 63 hops.

**Stage 1** gives these columns, whatever the slots say:

| Column | Cards | Why |
|---|---|---|
| 0 | sp | nothing feeds it; it feeds req |
| 1 | req | fed by sp |
| 2 | out | two wires in, two out: the tie rule puts it next to sea |
| 3 | sea | |
| 4 | args | |
| 5 | rep | |
| 6 | dto, ctxfmt | ctxfmt feeds only file (7) |
| 7 | file, ctxorg | ctxorg feeds only remote (8) |
| 8 | remote | |
| 9 | http | |

The total span is 63 columns over 45 edges, the minimum. Ten wires skip columns and become 18 lane items: three from `sp` to `sea` (columns 1–2), the three `req → sea` wires (column 2), `args.preview → remote.preview` and `args.documents → remote.parts` (5–7), `args.draftName → file.filename` (5–6) and `dto.action → remote.action` (7).

**Stage 4** orders the problem columns, top to bottom (`~a → b` is a lane):
- Column 7: **ctxorg**, `~args.preview → remote.preview`, `~dto.action → remote.action`, **file**, `~args.documents → remote.parts`.
- Column 6: `~args.preview`, **ctxfmt**, **dto**, `~args.draftName → file.filename`, `~args.documents`.
- Column 5: `~args.preview`, rep, `~args.draftName`, `~args.documents`.
- Column 2: `~sp.draft → sea.draft`, the three `req → sea` lanes, `~sp.draft → sea.supplier`, out, `~sp.ctx → sea.supplier`.
- Column 1: `~sp.draft → sea.draft`, `~sp.draft → sea.supplier`, req, `~sp.ctx → sea.supplier`.

`ctxorg` feeds `tenantId`, rank 0 of column 8, so the first sweep puts it on top. Under the preview lane it would cross that lane's hop; under `file` it would cross `file`'s three wires into `data`. `ctxfmt` feeds `filename` and `contentType`, which sit above `bytes`, the row `dto` feeds: above `dto` it crosses 2 wires (the action lane's climb), below it 6. Both complaint-2 defects are gone. Crossings: 19, the ILP optimum, reached by the sweeps; the refinement finds nothing to improve.

**Stage 6** (y in px):
- `ctxorg.org` 89 and `remote.tenantId` 89 are exactly level. The preview lane runs at 115, level with `remote.preview` and 13 px under `ctxorg`'s box; the action lane runs at 141, level with `remote.action`.
- `remote` rows: tenantId 89, preview 115, action 141, data 177 (46 px tall, three inputs), parts 213. `http` has the same rows, so all five copies are straight; harmonisation gave `http.data` the same 46 px.
- `ctxfmt` (box 157–239) plays the sketch's A: its wires descend from ports 221 and 231 into `filename` (268) and `contentType` (299).
- `dto` (box 279–423) plays B: its three wires climb into `bytes` (ports 335, 345, 355).
- `file` box 183–363, rows name 242, filename 273, contentType 304, bytes 340.

Report: the five targets 0; crossings 19 (19 wire pairs by the old definition, against 28 shipped); `max_dock_climb` 92 (`sp.draft` into its lane; `ctxorg` 0); `copy_bend` 16 (`rep → dto`); 26 of 63 hops straight; `travel` 2641 px; extent 4929 × 589 against 4849 × 437 shipped. With `ctxorg` at slot 1, with every slot removed, or with the card or the edge order reversed, the layout is identical. With `rows: "follow"` on `args`, crossings drop to 10, the ILP optimum, with `args.documents` moved to the bottom of `args` and its lane below `rep`, `dto` and `file`.

### 5.3 The shipped examples keep their crossing counts and lose their gaps

- `example-bypass`: form and ctx in column 0, cmd 1, env 2, req 3; 6 crossings, the ILP optimum and the shipped count. `env` (follow) reads body, tenant, attachment, then `contentType`, which has no wire. The `lane: "below"` locale wire runs under every card it passes. `audit`, which has no wires and is listed after `req`, sits at the bottom of column 3 (today it floats at the top right). No card opens a gap (shipped: cmd, env and req did).
- `example-order`: 0 crossings; every `entity → dto → json` copy is straight; no gaps.

## 6. Five targets make `--check` fail on both halves of the tenantId regression

**Targets** (`check.py` exits 1 unless each is 0). Four are 0 by construction, so a failure there is an engine regression. `label_overlaps` comes from a greedy placement with a bounded fixpoint: it is 0 on every fixture and on the 864 fuzzed specs, and the review could not break it with fans of ten labelled wires, but nothing guarantees it, so a miss there is the author's to fix. Below, a *source* is a card that nothing feeds and that feeds at least one card; a card without wires is not a source.
- **`behind_card`**: wire samples strictly inside a card that is not one of the wire's end cards, testing each sample against the cards of the column whose x-range holds it. Lanes are sampled across their column, so a lane inside a card counts.
- **`label_overlaps`**: texts whose final box overlaps a card box (with its stage-label band) or another text, after the stage-9 fixpoint.
- **`source_slack`** (complaint 1): Σ over sources of (smallest column among the cards they feed − own column − 1). Zero by stage 1's optimality. `ctxorg` at slot 1 scores 6 on the shipped engine. Without the source rule, a card without wires would add min(∅) = ∞, which `JSON.stringify` publishes as `null`.
- **`improvable_swaps`** (complaint 2): the number of neighbouring pairs in one column with the same group, plus neighbouring wired rows of a follow card, whose swap strictly removes crossings (`pair(u, v)` with r < c). Zero by the closing pass. The shipped spec W layout has 2 such card pairs: `file`/`ctxorg` (3 crossings → 0) and `dto`/`ctxfmt` (8 → 0).
- **`loose_sources`** (R4): the number of sources that could move 1 px up or down without breaking a separation in their column and would thereby lower Σ ω(h)·|Δy| over their own hops. Zero by stage 6's optimality; nonzero after a capped or broken solve.

**Reported** for judgment:
- **`crossings`**: crossing points, Σ over gaps of rank inversions. Exact (stage 8) and O(H log H); the old measure counted wire pairs by sampled intersection in O(E²·S²).
- **`dock_inversions`**: complaint 2 measured by geometry instead of crossings, kept from the reader design. It counts neighbouring pairs in one column (same group) where one of the two is a source and the upper item's highest far port on the right lies more than 0.5 px below the lower item's lowest one. It adds the same test on the left side for pairs where one of the two feeds nothing.
- **`max_dock_climb`**: the largest |Δy| on a first hop leaving a source (structural bends such as the sketch's A show here).
- **`copy_bend`**: the largest |Δy| inside an order-preserving block of two or more copies between the same two cards.
- **`straight`** and **`hops`**: hops with |Δy| < 0.5, out of all hops.
- **`travel`**: Σ over hops of |port Δy| in px, the straightness term of stage 6.
- **`max_steepness`**: the largest |port Δy| / gap width (today it uses item centres).
- **`detour`**: as today, the worst multi-column wire's length minus its chord.
- **`width`** and **`height`**: the drawing's extent, so aspect regressions show: card boxes with their 30 px stage band, and wire samples with 10 px around them, the box the camera's `bounds()` fits.

**Plumbing.** `check.py`: `MEASURES = (behind_card, label_overlaps, source_slack, improvable_swaps, loose_sources, crossings, dock_inversions, max_dock_climb, copy_bend, straight, hops, travel, max_steepness, detour, width, height)`; `TARGETS` = the first five; `passed()` keeps its rule that every target equals 0. `render.py --check` prints every measure, as today.

**Proof that the targets catch the regression.** Computed at card level from the shipped engine's `__layout` (the judges' `measure_old.js` approach): spec W with `ctxorg` at slot 1 scores `source_slack` 6; spec W as committed has 2 improvable card swaps; the sketch fixture with natural slots has 3. Each would have exited 1. The merged engine scores 0 on all five targets on every fixture and on 943 fuzzed specs from four generators.

## 7. Drawing, tracing and the canvas stay; the layout, report and validation are replaced

**Stays as is:**
- `engine.js` drawing (`draw()`, `:330-365`, with wires drawn before cards), tones, markers, `muted` and `strong` fields, the label halo.
- Tracing (`:367-396`): hover and click lineage, one way from the field.
- Camera, fit, fit-to-selection, keyboard, wheel and pinch, minimap and zoom controls (`:398-527`), and `window.__fit`.
- Chrome: title chip, About panel, legend (`:529-543`).
- The offline single-file page and `canvas.html`.
- Per-row ports sorted by the far end, row growth per wire, the gap-width formula, curve shape and sampling.
- `check.py`'s screenshot flow and exit codes 0–3.

**Replaced:**
- `engine.js` constants (`:13-20`), `slot` and the slot table (`:30`, `:37-39`), `layout()` (`:42-261`) and `report()` (`:263-322`) move into `fields/layout.js` (about 800 lines) and `fields/ns.js` (about 190). `engine.js` calls the layout, copies the geometry into its cards and routes, and publishes stage 11.
- `draw()` loses its `rowgap` branch (`:354-356`), dead with rigid cards, and draws fields in the published row order.
- `render.validate` (`:35-64`) is rewritten per §3; `render()` drops `slot` and `gaps` from the spec it embeds and inlines `ns.js`, `layout.js` and `engine.js`; `main()` prints the legacy note.
- `check.py` `MEASURES` and `TARGETS` (`:22-23`).
- `SKILL.md`, "Field mode", per §3; `example-order.json` and `example-bypass.json` drop `slot`; `example-sketch.json` and `example-context.json` are added.
- The canvas design spec gets a line under §2, §4, §5 and §6 pointing here.

## 8. The tests pin each reading rule, both regressions and the time budget

All fixtures are made up, because the repo is public. Each new browser test is first run against the shipped engine and must fail.

**New fixtures:**
- `example-sketch.json`: §5.1.
- `example-context.json`, the tenantId shape: `upload(…)` → `UploadCommand` → `StoredDocument` → `ArchiveClient.store(…)` → `PUT /{tenant}/documents`. A one-row context card `ctxTenant` is listed first and feeds only the client's first parameter. The file carries no `slot`, like every example an author copies (§3); the tests add `"slot": 0` to it, the tenantId mistake; a second context card `ctxFormat` feeds the document's name and contentType; `cmd.notify → client.notify` skips the document's column. Prototype result: `ctxTenant` in column 2, first, its port level with `client.tenant` (89); the notify lane 13 px under it; 6 crossings, the ILP optimum.
- Three stress specs, `stress-60x300-423.json` and `stress-60x300-662.json` (synthetic `cN.fN` names, generated by the prototypes' seeded generators), and `stress-60x300-1234.json`, the review's chain of 60 cards whose wires skip four columns on average (§4, lane items).
- Inline specs in the tests: the corridor (S feeds T and U in one column and `S.mid` reaches D past them); two cards wired crosswise; a loop; an edge inside one card; a repeated edge; a spec without edges; two flows with a `lane: "below"` in the first; a card without wires in a spec with wires; a follow card with rows that have no wire; a follow card whose field ids are `"0"` to `"3"`.

**`test_fields.py`** (no browser):
- Kept: complete document; no external references (now three inlined scripts); unknown field; unknown lane; unknown rows mode; card without fields; `test_malformed_cards_are_refused_with_a_clear_error` unchanged, `"slot": null` included.
- `test_backward_edge_is_refused` becomes `test_card_loop_is_refused`: `json.total → entity.id` raises `ValueError` naming `entity → dto → json → entity`.
- `test_same_column_edge_is_refused` becomes `test_edge_inside_one_card_is_refused` (`dto.id → dto.total`).
- New: `test_repeated_edge_is_refused`; `test_legacy_slot_and_gaps_draw_with_a_note` (`main()` prints the note on stderr, and `render()` gives the same page as without them); `test_card_order_needs_no_topological_sort` (a spec listing its consumer first, without slots, renders; today it raises "must run left to right").

**`test_fields_browser.py`.** Helpers `_col(L, id)` and `_items(L, k)` read `cards[id].col` and `columns[k].items`; `_slot` goes.
- `test_targets_hold`: the five targets are 0 on the four example fixtures and on every inline spec that validates.
- `test_sources_sit_one_column_before_their_consumer`: for each source (§6), `col = min(col of the cards it feeds) − 1`.
- `test_slot_and_card_order_place_nothing`: on every one-flow fixture and inline spec, slots removed, all 0 or scrambled, the card order reversed and the edge order reversed each give a `__layout` equal to the original, with `wires` and `labels` matched by their two ends instead of their index. On the two-flow inline spec, reversing the card order puts the other flow on top.
- `test_context_card_docks_level_on_top` (`example-context`): `ctxTenant` is item 0 of column `col(client) − 1`, and its wire's start y equals its end y.
- `test_sketch_keeps_its_shape` (`example-sketch`): columns {opts, entry} 0, {A, mid, B} 1, C 2; column 1 items are A, mid, the `entry.raw` lane, B; crossings 0; A's box bottom < C's top, B's box top > C's bottom; both `mid → C` copies and the `entry.raw → C.file` wire are straight.
- `test_long_wire_takes_the_corridor` (corridor spec): the lane's y lies strictly between T's bottom and U's top, and the wire's samples are flat over that column.
- `test_crossings_are_exact`: `report.crossings` equals the per-gap rank inversions recomputed from `wires[].hops`. For every pair of hops in one gap, the height difference along their 25 shared samples changes sign exactly once when their end ranks are inverted and never otherwise, with zero samples skipped. A segment-intersection test is not used: on the crosswise spec the two hops meet exactly at the middle sample, and the strict test of today's report misses that crossing (the review measured 0 found against 1 real, and 0 against 3 with three crosswise wires).
- `test_crossings_reach_the_optimum`: example-order 0, example-bypass 6, example-sketch 0, example-context 6, constants computed once by the offline ILP oracle (scipy `milp` over pairwise order variables with transitivity, from the layered prototype).
- `test_copies_are_straight`: every copy in example-order, and the `mid → C` copies, `entry.user` and `entry.raw` in example-sketch, have |Δy| < 0.5; `copy_bend` 0 on example-order.
- `test_ports_stay_inside_their_rows`: every wire end lies at least 8 px inside its row band (extends `test_arrowheads_land_on_their_rows`).
- `test_rows_touch`: on every fixture, consecutive rows of a card neither gap nor overlap.
- `test_follow_rows` (`example-bypass`): `env` reads body, tenant, attachment, contentType. On the inline follow card with ids `"0"` to `"3"`, `rowOrder` lists the ids in the order their row centres descend the page.
- `test_cards_without_wires`: `audit` is the last item of the last column; the spec without edges draws one column per card, top-aligned.
- `test_lane_stays_in_its_flow`: the first flow's `below` lane sits under that flow's cards and above the second flow's items in each column it crosses.
- `test_measures_catch_the_tenant_context_regressions`: `__measure` on mutated copies of example-context's layout: `ctxTenant` moved to column 0 gives `source_slack` 2; `ctxTenant` swapped under the notify lane gives `improvable_swaps` ≥ 1; `ctxTenant` moved 30 px up gives `loose_sources` 1.
- Kept and adapted: no wire behind a card; arrowheads on their rows; distinct ordered ports; real order without follow; `test_lane_override_goes_below` via `_col`; no NaN; the gap holds the longest label; a long note widens its gap; a note is drawn and placed; trace tests; dotted field ids; shot mode; determinism (same page bytes, same `__layout` and `__layoutReport`); the check tests, with `test_check_writes_png_and_reports` listing every measure and `test_check_exits_1_when_a_target_is_missed` parametrised over the five targets.

**Solver tests** (through `window.__fieldEngine`):
- `test_network_simplex_matches_exhaustive_search`: 200 seeded problems (≤ 5 nodes, minlen −3…3, weight 0…5) reach the optimum found by exhaustive search over a bounded integer grid.
- `test_cut_values_stay_consistent`: a debug flag recomputes every cut value after each pivot and asserts it equals the incremental one, on the fixtures and a generated 40-card spec.
- `test_solves_are_certified`: `capped` is false for every solve on the fixtures and on 20 seeded random specs.
- `test_layering_is_optimal`: on 40 seeded random acyclic specs of up to 6 cards, Σ w·span from `__layout` equals the brute-force minimum.

**Property and budget tests:**
- `test_fuzz_invariants` (marked slow): 200 seeded specs of 2–25 cards with follow cards, lanes, labels, notes, two flows and cards without wires. No page error; five targets 0; ports at least 8 px inside rows; rows touch; real order holds; a second load gives the same layout. The prototype passed the equivalent on 943 specs.
- `test_layout_budget` (marked perf): the two generated stress specs, each in a fresh Chromium; `__layoutTiming.total` < 100 ms, median of 3.
- `test_layout_scales_with_lanes` (marked perf): `stress-60x300-1234.json` stays under 200 ms, median of 3 (126 ms measured), so the open lane-count item cannot get worse unseen.

**`test_skill_doc.py`:** the field-mode section names the five targets and keeps `--check`, `"lane"`, `"rows": "follow"` and "three rounds"; its spec-format block contains neither `slot` nor `gaps`.

**Local acceptance** (spec W stays out of the repo): render with `--check` and compare with §5.2: 19 crossings; `ctxorg` first in column 7, level with `tenantId`; `ctxfmt` above `dto`; five straight `remote → http` copies; identical output at slot 1; 10 crossings with `args` set to `follow`.

## 9. Two decisions are made here, and eight risks need watching

The user asked for a ground-up design and asked not to be consulted on choices like these, so the spec makes both decisions on the evidence instead of handing them back.

**Decided: cards become rigid, which reverses decision B.** The canvas spec records "spaced" rows, chosen by the user: a row sits at the height of what feeds it and a card may show gaps. This spec draws each card as one rigid record (R7). The evidence:
- The shipped engine's gaps (`remote` 58 px, `sea` 38 px) came from compaction losing to wires.
- The reader prototype's gap-cost experiment opened a 106 px hole in `remote` and broke the `remote → http` copy at a cost of 2.5 wires per px of gap. At 4.5 or more, no gap opened in its tests.
- The user's sketch (image 13) draws rigid cards: its rows touch, and the sources move to meet them.

If spaced rows are ever wanted back, stage 6 splits each card into one node per row, joined by edges of weight γ per px of gap. A γ high enough to keep copies whole draws rigid cards in practice; the threshold has to be measured again under this spec's copy weight.

**Decided: this document names the private spec only as spec W, with neutral stand-ins for its short card and field ids, and nothing else from it.** The sections above use them wherever a number comes from that spec; the mapping to the real ids stays with the private file, so the local acceptance check (§8) can still be read against it. They carry no class, method or file names, no values and no code, and the spec file itself stays out of the repo.

**Risks:**
- **Three constants were tuned by measurement and checked on few renders.** The 13 px lane clearance under a card (24 px leaves `ctxorg` 11 px off level), the 5 px port slide, and the copy and dock weights (×4 and ×7/4, picked from a sweep of ×1.5 to ×6 on 300 generated specs and the fixtures). A different corpus may move the best values; the tests pin behaviours (R3–R6) and leave the constants free.
- **The budget is calibrated on one machine.** 800 000 and 1 500 000 units keep the worst 60-card spec at 79 ms cold on an Apple-silicon Mac. A slower runner may pass 100 ms, so the perf test is marked and the two budgets are the knobs to retune with it.
- **Crossing minimisation stays heuristic.** `improvable_swaps = 0` certifies single swaps only. Every fixture reaches the ILP optimum, but a future spec can stop in a worse local optimum. Crossings outrank bends, so a forced order can draw a long climb: on spec W `args.preview` climbs 264 px over `reportData`'s four wires into the topmost lane. `rows: "follow"` on that argument list, which the skill already asks for, cuts the spec's crossings from 19 to 10.
- **Drawings get taller.** Spec W grows from 437 to 589 px at about the same width, because lanes run between cards and cards no longer squeeze rows. Width follows the chain length, so a ten-stage chain still fits the window only at small zoom.
- **Every existing diagram changes.** Authors lose `slot` as a placement tool, stale `lane` overrides from the old fix list are still obeyed and may cost crossings, cards without wires move under their spec predecessor, and follow cards move rows without wires to the bottom.
- **The solver is the subtlest code.** A sign slip in an incremental cut value gives a feasible, suboptimal layout and no error. Port the prototype's `ns.js` first, add the smaller-side search for the entering edge only behind the cut-value test, keep the exhaustive-search test, and treat a nonzero `source_slack` or `loose_sources` as the alarm.
- **Time follows the lane items, and nothing caps the solves.** At 60 cards and 300 edges, wires that skip four columns on average make 1234 lane items and take 126 ms; 4130 lane items take 370 ms (§4). The work budget covers stage 4's sweeps and moves only. `test_layout_scales_with_lanes` pins today's cost, and the review notes list the fixes worth trying.
- **A source with consumers in several columns still has one place.** It docks one column before its nearest consumer, and its other wires become lanes. In the review's test, a context card feeding the top rows of cards in three consecutive columns sat above the first of them and sent two lanes over the cards in between, crossing nothing. That is correct under R1, but a reader tracing the farthest row back follows a long lane. Drawing such a value once per consumer column is not part of this spec.

## Review notes

An adversarial review on 2026-10-02 hand-simulated the spec on the sketch, re-ran the prototype on spec W, the fixtures and the four fuzz corpora, and built specs to break it. It tested each fix on a patched copy of the prototype. The scripts and specs sit beside the prototype: `rvc.js` is the prototype with stage 0's canonical numbering, and `perm2.js`, `corpus300.js`, `stab2.js`, `fuzzc.js`, `cross.js`, `patho2.js`, `labels2.js` and `layer2.js` produced the numbers below.

**What the review changed:**
- **Stage 3 drew a row without wires 16 px tall.** `26 + 10·(max(in, out) − 1)` is 16 when both are 0. The prototype clamps with `max(0, …)`, and the formula now does too.
- **R8 did not hold.** Item keys, solver numbers, port ties, and the order of refinement moves and labels all used spec or edge indices, and the heuristics start from spec order.
  - On the four fuzz corpora, reversing the card order changed 49 of 273 one-flow specs, and reversing the edge order changed 39. Judge 2's 44-spec suite happened to show none. Two flows also swap places.
  - The fix: stage 0 numbers cards by id and edges by their two ends, and every tie and processing order uses those numbers. Spec order decides only the flow stacking, the place of cards without wires, and the columns of a spec without edges. R8, §3 and the R8 test say so.
  - With the patched prototype, no one-flow spec changed under card reversal, edge reversal or edge shuffles, and every fixture's layout stayed identical. The 300-spec corpus moved from 4677 to 4686 crossings, from 74.4% to 74.3% straight copies, and from 39.5% to 39.4% level sources. On all 943 fuzzed specs the five targets stayed 0, ports stayed at least 8 px inside their rows, and a second run gave the same layout.
- **R5 promised that a long wire bends only at its ends.** §5.2's own layout bends `sp.draft → sea.supplier` 68 px between columns 1 and 2. R5 now states what the weights guarantee and names that case.
- **`source_slack` was undefined for a card without wires.** "Cards that nothing feeds" includes such cards, and min(∅) = ∞ publishes as `null`. That fails `test_no_nan_in_layout` on `example-bypass`, whose `audit` has no wires. §6 now defines a source as a card that nothing feeds and that feeds something, and every source measure and the R1 test use that definition.
- **§6 called all five targets 0 by construction.** Label placement is greedy with a bounded fixpoint, and the new SKILL.md fix list already tells the author to shorten a colliding label. §6 and step 4 now give `label_overlaps` to the author and treat the other four as engine regressions, `behind_card` included.
- **`dock_inversions` was listed but never defined.** It is now defined as the prototype computes it.
- **`test_legacy_slot_and_gaps_draw_with_a_note` could not pass**, because `render()` embeds the spec JSON, slots and all. `render()` now drops `slot` and `gaps` after validating, so the two pages are byte-identical.
- **`test_crossings_are_exact` would fail on the crosswise spec.** Its two hops meet exactly at the middle sample, where the strict segment test of today's report finds nothing: 0 found against 1 real crossing, and 0 against 3 with three crosswise wires. The test now counts sign changes of the height difference.
- **Row order was published only as the key order of `rows`.** JavaScript lists integer-like keys such as `"0"` and `"1"` in numeric order, so a follow card with such ids would give `__measure` and the tests the wrong order. Stage 11 now publishes `rowOrder`.
- **Two tests named sets that hold invalid inputs.** `test_targets_hold` ran on every inline spec, including the loop, the edge inside one card and the repeated edge, which validation refuses. `test_sources_sit_one_column_before_their_consumer` included cards without wires. Both now name their sets exactly.
- **The time bound was stated without its condition.** It holds while lane items stay under about 900. At 60 cards and 300 edges, the review measured 122–370 ms for 1129–4130 lane items (§4). The heading, a table, a risk and `test_layout_scales_with_lanes` now say so.
- **§9 handed two decisions back to the user**, who asked not to be consulted on such choices. Rigid cards and the naming of the private spec are now decided, with their reasons.
- **Smaller corrections:**
  - The copy-weight paragraph claimed one source never bends a copy chain. A 1:1 source can bend a lone copy; only a block of two or more copies between the same two cards holds.
  - Stage 4 has one work counter, and a sweep can overshoot its budget like a move.
  - The heavy-path list is taken once per pass, before any path move.
  - The free-end move counts crossings in the card's two gaps and in the wire's gaps.
  - Stage 6's measured node count is the prototype's, which has no root.
  - The report counts `improvable_swaps` without stage 4's merge, so a fault in `pair()` cannot certify itself.
  - `width` and `height` are now defined.
  - `example-context.json` carried `"slot": 0`, although §3 says the examples authors copy drop `slot`. The tests now add it.
  - Two `engine.js` line ranges moved by 2 after a concurrent edit to the wheel handler.

**What the review checked and left as written:**
- **The sketch.**
  - Stage 1 by hand: the columns {opts, entry}, {A, mid, B} and {C} are the only optimum. Moving `mid` left drags `entry` and `opts` with it and costs 3 more.
  - Stage 4 by hand, from the canonical start A, B, mid, lane: the first transposition moves B under `mid` and the lane, giving A, mid, lane, B with 0 crossings, and column 0 becomes opts, entry.
  - The prototype reproduces every stage-6 number of §5.1.
- **Spec W.** The prototype reproduces §5.2 exactly: 19 crossings, `ctxorg` first in column 7 at 89, level with `tenantId`, `ctxfmt` above `dto`, the five straight copies, 10 crossings with `args` set to `follow`, and the same layout at slot 1 and with the cards reversed.
- **Specs built to break it.** All five targets were 0 on each one that validates.
  - One source feeding the top rows of cards in three consecutive columns: it sits above and left of the first of them, two lanes run over the cards in between, and nothing crosses. This is the new risk in §9.
  - A pass-through `E.id → W.id` beside a side source in each of the three columns it skips: the lane runs on top, and each source docks above and left of its consumer. One crossing remains, forced by the declared row order.
  - A diamond with a long branch, a short branch and a skip: 0 crossings. The long branch's middle card stacks above the short branch's, and its two copies bend 76 px, because two cards in one column cannot both sit level with adjacent rows.
  - A balanced block, one card with one wire in and two out feeding a card with two in and one out: stage 1 gave the same columns from forward, reversed and shuffled numberings, here and on 820 random card graphs with 6 orders each.
  - A loop: the three-colour DFS as written reports `entity → dto → json → entity`, and `B → C → B` for a loop entered from outside it.
- **The measures against the regression.**
  - A source has no wires on its left, so a neighbour above it that feeds a lower row always gives c > r. `improvable_swaps` therefore catches every wrong-side stacking of `ctxorg`.
  - `source_slack` scores 6 at slot 1, and `loose_sources` catches a source left above its row.
- **Determinism.** Integer solves, explicit last keys and work units hold. The 8 px port margin is a bound, not a measurement: 13 + 5(n − 1) − 5(n − 1) − 5 = 8.
- **The label fixpoint.** The spec widens a gap to `gapW + 40`, where the prototype used `need + 40`. The prototype's version stalls when the climb term sets the gap, so the spec's version stays. Fans of up to ten labelled and noted wires left no overlap.

**Left open:**
- **The time bound for lane-heavy specs.** Beyond about 900 lane items the layout passes 100 ms. Stage 4 takes most of it at first, and stage 6's two solves take over as D grows (209 of the 370 ms at 4130 lane items). Three fixes are worth a prototype run before any goes in:
  - one lane item for all the wires that leave one row toward one card, which cuts D itself;
  - a warmer start for stage 6, whose pivots grow with D;
  - fewer refinement candidates per pass on large specs.
- **A value used in several columns is drawn once.** Drawing it beside each consumer column would shorten the reader's trace, but it changes tracing and the spec format.
- **Stage 1's ties are left to the solver.** A group of cards can sometimes move together at no cost even though no single card in it has as many wires in as out. Such a group stays where network simplex leaves it, which was order-independent on every test above. Weighting each wire by C² + 1 and adding a weight-1 edge from every card to an extra rightmost node would make the push to the right exact. That variant moved columns on 59 of 1645 random graphs at equal total span, and it was not adopted without a pass over the fixtures.
