# Tracing the code for a dataflow

Moved out of SKILL.md. Read it when tracing a seed: it holds the four steps in full, with the cases for mappers and slices and a good and a bad `model` claim.

### 1. Find both ends

From the seed, walk **up** until you hit an HTTP entry point, and **down**
until you hit a real table. Do not stop at a repository interface: a
repository is not an answer to "where does it go", the table is. Open the
migration that creates the table or column and read it.

### 2. Name every mapping, including the ones with no file

Between any two adjacent nodes, the value either keeps its shape or changes
it. Where it changes, there is a mapper — and **the mapper often has no class
of its own**:

- an explicit converter, mapper or `…ConversionService` → a `mapper` node with
  `implicit: false`, anchored at the class
- Jackson serializing an aggregate into a blob column → a `mapper` node with
  `implicit: true`, anchored at the line that configures the `ObjectMapper`
- an ORM flattening an embedded value into columns → a `mapper` node with
  `implicit: true`, anchored at the annotation
- an ORM mapping an entity to its table → same treatment

**Never omit an implicit mapping.** A reader who cannot find the second mapper
concludes the code is missing something. Naming it, and saying it has no file,
is the single most useful thing this diagram does.

### 3. Decide how many slices there are

A slice is one path from an entry point to storage. Ask whether the seed
appears in more than one:

- **One slice** — one entry point, one path down. Most features.
- **Two or more** — e.g. one path that *configures* something and another that
  *uses* it, each with its own controller, its own storage, and different
  persistence mechanics. Give each its own slice, and mark the method where
  they meet with `join: true` on the edges in both directions.

Do not invent a second slice to look thorough. Two slices is a claim: that
they are independent except at named points.

### 4. Write the model

`model` is 2–5 claims a reader could be wrong about — the things you had to
read the code to learn. Each states what **is**, not what to do. If a claim is
also visible in a node, keep it in both: the model is the summary, the node is
the evidence.

Good: "The two slices are linked only by a string. Nothing enforces it — no
foreign key, no validation on read."
Bad: "This feature has a controller, a service and a repository."
