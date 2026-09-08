# Views — splitting a flowchart that answers more than one question

A flowchart gets hard to read long before it gets big. The cause is usually not
size, spacing or the layout engine: it is that one drawing is answering several
questions at once. A layered algorithm minimises crossings over the **union** of
every question's edges, so each question pays for the others', and no amount of
tuning recovers what the mixing cost.

Splitting the edges by question fixes it. Deciding which question an edge
answers is your job, and nothing in the tool can do it for you.

## Geometry forbids; meaning groups

Two edges that cross must not share a view — that is measurable, and it holds in
any domain, because a crossing knows nothing about what the graph is about.

But a machine cannot go further. Colouring the conflict graph produces a
grouping that is geometrically valid and semantically nonsense: on the graph
this procedure was built against, an automatic colouring put "opening a
proposal" and "writing results to storage" in one class and split three
unrelated concerns across another. Measured on that same graph, geometry
produced **4 constraints and left 11 of 17 edges unconstrained** — it had no
opinion about two thirds of the diagram.

So the division of labour is fixed:

| | who | why it holds in any domain |
|---|---|---|
| what **must** be separated | the checker, from a rendered layout | crossings do not know your domain |
| how to **group and name** | you, when you author the spec | you know the domain, whatever it is |
| **verify** the grouping | the checker | catches you when you are wrong |

## Measure, never predict

Every claim here comes from a rendered layout. Do not reason about what a
layered drawing will look like and act on the conclusion — predictions about
layered graphs are wrong often enough to be worthless, including confident ones
about how many crossings a change will remove. Render it and count.

The corollary: when a change does not improve the measurement, discard it even
if the reasoning behind it was good.

## The loop

```python
from skills.annotate.diagrams import views
report = views.check(spec)
print(report.summary())
```

1. **Model the graph** — nodes, edges, roles. No views yet.
2. **Check it.** `report.engine` says which layout was measured. `"fallback"`
   means ELK was unavailable, so the nodes were placed in Python and the edges
   are beziers — a real drawing, honestly counted, but not the one a machine
   with ELK ships. Install `node` before trusting the number.
   If `report.needs_views` is False, **stop**. A diagram with no
   crossings does not need views, and adding them makes it worse. Most diagrams
   land here.
3. **Read `report.conflicts`** — the edge pairs that must be separated. This is
   the constraint set, not a proposal.
4. **Propose views**: give every edge a `views` list. Name each view as a
   question a reader arrives with (below).
5. **Check again.** `report.ok` means no `violations` and no `unassigned`
   edges. A violation names the two edges and the view they wrongly share; fix
   the grouping, not the layout.
6. **Read the per-view measurements.** A view that still has crossings is
   answering more than one question — split it again.
7. **Push the block.** A flowchart whose spec declares views ships one SVG per
   view plus the union, and the page paints a control above the diagram —
   **All**, then one button per view, in declared order. The reader picks the
   question; the choice is remembered per block in their own browser. Nothing
   else in the block changes, and a spec with no views shows no control.
   (`flowchart.render_views(spec, block_id)` returns the same map directly, for
   a caller that wants the SVGs outside a block.)

## Naming a view

A view is **a question a reader arrives with**, not a category in a taxonomy.
The test: can you put a question mark on the end?

| good | bad |
|---|---|
| how an order reaches the bank | persistence layer |
| what happens when a payment fails | error handling |
| how a document becomes searchable | the indexing subsystem |
| who can see a draft | permissions |

The bad column names parts of the system; the good column names things someone
wants to know. Category names look tidier and are the reason multi-view models
go stale — nobody opens "persistence layer", so nobody notices when it is wrong.

Two to four views. More than four means the diagram is really several diagrams,
and it also makes the control a row of buttons nobody reads.

Put the views in one block with the switcher rather than one block per view.
Three sections of prose separated by three drawings reads as three topics; one
drawing the reader re-asks reads as one.

## `views` is a set

An edge may answer more than one question, and forcing it to pick makes the
spec lie:

```json
{ "from": "refresh", "to": "store", "views": ["read", "persist"] }
```

Node membership is **derived** — a node appears in a view when one of its edges
does — so nodes are never tagged and never drift out of sync with the edges.

**Every edge needs at least one view once any edge declares one.** The validator
enforces this. An untagged edge would vanish from every view while still shaping
the union, which is exactly how multi-view models rot.

`"all"` is reserved for the union, which is always rendered.

## `band` — the authored role axis

```json
{ "id": "sync", "label": "OrdersSyncService", "role": "code", "band": "orchestrator" }
```

A band is a role that peers share: entry points, orchestrators, strategies,
external calls, terminal states. Bands become ELK partitions, so their **order
holds in every view** — which is what lets a reader compare views side by side
instead of searching each one for the same node.

Use bands when the drawing has a role structure the reader already knows. Two
things to expect, both honest:

- A peer that calls a peer costs its band a second layer. That is a real fact
  about the code, and seeing it is usually the point.
- A band skipped by many edges gets long connectors through the middle. Count
  band-skipping edges before committing; if there are many, let the edges rank
  the graph and drop the bands.

Layers are derived from edges and carry whatever distortion the edge set has.
Bands do not. Never align views by layer index.

## Repeat a node, or share it

When several sources converge on one node, you can draw that node once per
source instead — the way a schematic draws many ground symbols rather than one.

**Share it when the convergence is the message; repeat it when it is a leaf
nobody compares.** "Everything ends up in one place" is often the entire answer
to a question, and duplicating the node deletes that answer to make a different
reader more comfortable.

This is a last resort, and it must be measured. On the graph this procedure was
built against it was tried, predicted to remove nearly every crossing, and
removed **none** while making the drawing 400px wider — because the crossings
were collisions between concerns, which duplicating a node cannot touch. Splitting
by question was what worked.

## When not to use views

- The union has no crossings. Stop; you are about to make it worse.
- The diagram has fewer than about eight edges. Read it as it is.
- You cannot phrase the views as questions. That means you found a taxonomy,
  not a set of readers.
