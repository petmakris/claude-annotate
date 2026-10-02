# Specimen Page Format

The specimen web page draws one populated instance of a Java type, then the types that
instance never reached. This document describes what each token, row and block means.

## Header

The header names the class, the commit and the worktree the shapes were read from,
then two lines about provenance:

- the **note**, fixed text: shapes read from source and checkable, identifiers
  captured from the deployment named below, numbers illustrative
- the **capture line**, `Captured identifiers: <deployment> · <timestamp>`, read from
  `leaves.json`'s own `deployment` and `captured` fields and carried into the document
  by `lib/document.py::build_items`. Without it the note would claim a real deployment
  without saying which one or when.

Underneath sit the view switch, **tree** and **table**, and in the tree view also
**expand all** and **collapse all**. The tree opens fully by default: a specimen is
written small on purpose, and collapsing by default would hide the null the reader came
for.

## Two Views

The same document, laid out two ways. The switch writes the view into the URL, so
`…/s/<sid>/#table` opens the table and a bare URL opens the tree.

- **tree** — structure. What holds what, how deep it goes, what a node contains.
- **table** — comparison. One row per instance, columns aligned, so the same field of
  three list items can be read next to each other. In the tree those three are pages
  apart once each item is open, which is the one thing the tree cannot do.

`#table/all` opens the table with every composite column expanded, so a link can point
at a particular layout and not only at a view.

Both views carry the same anchors, so switching never moves a comment thread.

## The Instance Tree

The `instance` written in `specimen.json` is drawn node by node, under the heading
`instance`.

- A **field whose value is an object** becomes a node. Its own fields are drawn
  underneath it, indented, behind a disclosure triangle. This is the difference from
  the table this page used to be: a `MarketValue` is the two numbers it holds, not a
  dash and a filename to go and look up.
- A **field whose value is a list** becomes a node whose value reads `N items`. Each
  item is a node of its own, labelled `[0]`, `[1]`, and expands into that element
  type's fields.
- Anything else is a plain row.

A row is a line, not a row of columns: `name: value`, the way a debugger's variables
panel reads. Columns are what made an earlier version of this page read as a table with
indentation rather than as something to explore.

- The **disclosure slot** comes first, and is kept even on a row that cannot be opened,
  so a leaf's name starts where the name of the node above it starts.
- The **name** carries its own colour, so the eye lands on names when scanning down and
  on values when reading across.
- A **`?`** immediately after the name means `@Nullable`. `@NonNull` shows nothing, and
  the third state, `unmarked`, shows `·`. All three spell themselves out on hover. One
  character rather than the word `@Nullable` repeated down the page: the fact is one
  bit, and spelling it out on every second row is what a reader ends up looking past.
- The **value** follows the colon.
- The **declaration detail** — declared type, provenance tag, source file and line, and
  the editor button — is grouped at the end of the line and held at low opacity until
  the line is under the cursor. It is reference material and must not compete with the
  value.

Indentation is drawn as a rail, not implied by whitespace, and the rail lights up with
the node it belongs to.

### Closed nodes say what they hold

Every object node renders a **preview**, `{amount: 1250000.00, currency: CHF}`, which
CSS shows only while the node is closed — an open node is already showing the real
thing. It summarises the keys the **instance** carries, not the ones the type declares:
a preview is about what is in there, and a field nobody filled is not. At most three
keys, then `…`. A null inside survives the summary as the word `null`, because that is
the row the reader came for.

### Rows are per instance; anchors are not

Each occurrence of a type in the tree draws its own rows. Three `Contributor` items draw
three `proposedRiskContribution` rows, each showing what that item holds. So a null on
the first of three is visible on the first of three, and a category id repeated across
sibling lists is visibly the same id in all of them.

All three of those rows carry the **same** anchor, `<fqn>#<field>`, and therefore the
same comment thread. The anchor holds no list position, which is what lets a thread
survive a re-push after the code moves. A question asked from one row is a question
about the field, and the answer may have been prompted by any of them.

### Shape comes from the type, not from the specimen

An object node lists every field its **type declares**, read from `types.json` — not
only the keys `specimen.json` happened to fill. A field the populator never reached is
drawn with its declared type and an unset dash, rather than being invisible.

## Type Names Are Copyable

Every type name on the page — the root in the header, a block's heading, a node's type in
the tree, a record block's caption, a declared type on any row or column header — is a
**pill**. Clicking it copies the fully qualified name to the clipboard and flashes green,
so the next step, opening the class in an IDE, is a paste rather than retyping a package.

What is copied is the qualified name with the nested-class `$` written as a dot:
`…AnalyticsResult.MarketValue`. `$` is what the JVM and the extractor call it and
what a class search finds nothing for.

Where the page cannot qualify a name it copies the name it has. `BigDecimal` is not in
the type graph, so the pill copies `BigDecimal` — half a name is still what the reader
would type, and inventing a package for it would be worse. A simple name is only resolved
to a fully qualified one when exactly one type on the page answers to it; a large codebase can have
five called `Category`.

A pill stops the click reaching the row, so copying a name never also expands a node or
opens a comment composer.

## Value Tokens

Four display tokens appear in the value position, and they are four different facts:

- **`specimen-null`** — a red badge reading `null`. The field's value is genuinely
  absent. Making this visible is the point of the page, and its row is tinted.
- **`specimen-unset`** — a dash `–`. No value was supplied for this field. It reads as
  "nobody looked", never as "the value is null".
- **`specimen-count`** — italic and grey: `3 items` for a list, the element's simple
  type name for an object. What the node is worth is the rows underneath it.
- Anything else is the value itself, in the monospace face.

## The Editor Button

Every row ends with `⌘`, which opens that field's declaration in the editor: the
declaring type's `source` from `types.json`, at the field's own `line`. A list item's
head opens its element type's declaration.

The page cannot open a file itself — `file://` is refused from an `http` origin — so it
POSTs to the daemon's `/api/open`, which runs the opener. That endpoint accepts only an
absolute path already inside a session's workspace, which is exactly what `types.json`
records. A failure turns the button red and prints the server's own reason to the
console; it never guesses.

A row whose declaring type has no source in this worktree has no button, because there
is no file to open.

## Type Blocks

Below the tree, every type the tree never reached gets a block of its own, in the four
kinds `lib/typegraph.py::classify` emits. All four are printed, never dropped. A
silently missing type is how the page would become confidently wrong. A type the tree
**did** reach is not repeated here — drawn twice it would read as two things rather
than one thing seen from two places.

### Data Blocks (kind: "data")
A readable class — a record, an enum, or a class annotated `@Value`, `@Data` or
`@Entity` — that nothing in the instance holds. Badged `data — not reached by this
instance`. Its fields keep their anchors and their shapes; their values come from the
row bodies `build_items` computed, which for an unreached type is usually nothing.

### Behaviour Blocks (kind: "behaviour")
A class whose source WAS read but which is not a data holder: a service, a repository
wrapper, a holder of collaborators. `classify` returns this for anything that is not a
record, an enum, or annotated as data. The entry class of a service page is normally
this one, and its instance is thin by nature — which is why this block exists at all
rather than leaving the root of such a page blank.

Tinted (`specimen-behaviour`) under the badge `behaviour — holds collaborators, not
data`. Its rows normally show an unset dash, and that is correct: a collaborator is not
data and `specimen.json` has nothing to put there.

### Leaf Blocks (kind: "leaf")
A type with no source file in this worktree — `lib/typegraph.py::build` could not
resolve any path for it at all. Dashed border, and shows:
- A `leaf — no source in this worktree` badge
- The reason, always in the fixed form `no source in worktree; <package> is not
  checked out here`. The package is computed by dropping every trailing capitalised
  segment, so a leaf reached through a dotted nested import
  (`...classification.domain.Category.CategoryId`) names `...classification.domain` and not
  `...classification.domain.Category`, which is a type and not a package. This explains why the
  *extractor* has nothing to read, not whether `leaves.json` has captured data for it.
  Those are separate facts; a leaf can have real captured instances (`Category`) or none
  (`Currency`) — check `missing_leaves()` for that, not this block.
- The list of accessors the checkout actually calls on this type, so the reason is
  specific. `equals`, `hashCode`, `toString` and setters are excluded: every Java
  object answers those, so they name no field of the absent type and
  `coverage_gaps()` would report gaps no capture could ever close.

A nested type that IS in the worktree is not a leaf. Java writes a nested import with
a dot and `SourceIndex` keys it with a `$`; `lib/imports.py::resolve` rewrites the dot
form before giving up, so `AnalyticsResult.CategoryAllocation` resolves to the
declaration it already read rather than producing a leaf that denies its own package
is checked out.

### Unhandled Blocks (kind: "unhandled")
`lib/typegraph.py::build` produces this kind for two cases where a type is named
but nothing usable was read for it:
- The source file was found, but no declaration in that file matches the simple
  name being looked for. The reason is the fixed string `no type declaration
  matching the file name`.
- A dotted nested type written directly in source, not through an import
  (`Classification.ClassificationId` on a field, with only `Classification` imported), that
  resolves through none of `lib/imports.py::resolve`'s cases — not an import,
  not the compilation unit, not the package, not a wildcard. One node is kept
  per distinct unresolved name; it is not expanded further, since nothing here
  says what file it would even be in.

`lib/emit.py::provenance_errors` refuses a payload whose `unhandled` or `leaf` entry
has no reason, so a badge on the page is never left standing over an empty paragraph.

## The Table View

One table per type the instance holds, **one row per instance of that type**, one column
per field the type declares. Three `Contributor` items are three lines under each other,
which is the comparison the tree cannot make: once each item is expanded there, its
fields are a screen away from its siblings'.

Grouping is by type rather than by nesting, so objects of one type reached at different
depths still land in the same table. Each block is captioned with the type's simple name
and how many instances of it the specimen holds.

- The **row label** is the path of that instance — `[1]`, or
  `charts[0].riskContributions[1]`. Without it a row cannot say which instance it is.
  The root object's own row is labelled `instance`.
- A **column header** names the field, marks it `?` when `@Nullable`, and prints its
  declared type underneath.

It is a real `<table>`, so the browser sizes the columns to their content, and the block
scrolls sideways when a type is wider than the card.

**Values align right, every one of them.** A column of numbers has to line up on its last
digit to be comparable at all, and a column where some cells are right and others left —
a spanning null against the value beside it — reads as a cell overflowing into its
neighbour rather than as two different values. The row label is an identifier and stays
left. A group header is a label over a *range* of columns rather than a value, so it
centres over the span it names.

**Every column draws its own faint line.** Without them a cell that spans a group is
indistinguishable from a cell whose text has overflowed. With them the spanning cell is
obvious precisely because the line that would have been inside it is the one that is
missing.

### Nested columns

A field whose value is an object is a column that **opens**, the same gesture the tree
uses, and what it opens into can open again. `CategoryAllocation.current` is an
`Allocation`, whose `marketValue` is a `MarketValue`: three levels, and every value at
every level ends up in a real column that can be read straight down the page. That is
the only reason to be in the table rather than the tree.

- The header is therefore a **tree drawn with `colspan` and `rowspan`**, one row per open
  level. A composite that is open spans its leaf columns; a leaf beside it reaches down
  with `rowspan` to sit on the bottom row.
- Each level takes its own tint and a left edge, because two groups side by side with no
  line between them read as one wide group.
- Closed is the default, so the table starts as narrow as the type is wide.
  **open all columns** / **close all columns** in the header move every group at once,
  and the first of those is what `#table/all` means.
- A leaf header carries `data-col-index`, its left-to-right position. Header cells are
  emitted level by level, so a leaf on row 3 follows a leaf on row 1 in the DOM while
  standing to its left on the page; the page states the visual order rather than leaving
  it to be inferred.

**A null object spans every column its group owns.** A run of empty cells would read as a
run of empty *fields*; one cell across the group says the object itself is absent. A
field the instance never reached is different again, and gets an unset dash in each of
its leaf columns rather than a spanning null.

**Which type a column opens into** comes from the instance where it can: a record holding
an object at that path names its class exactly. Where no record does — every instance
null, or the field never reached — the declared name is all that is left, and it is
trusted only when exactly one type on the page answers to it. A simple name does not
identify a class; a large codebase can have five called `Category`. The column still opens in that case,
showing unset dashes under the right field names, because the shape is what this page is
for.

## Anchors and Comments

Every field row, in either view and in the blocks below, is an anchor element with
`data-wc-anchor` set to `<fqn>#<field>` — the fully qualified name of the class that
**declares** the field, then the field name. Example: `com.example.User#email`.

The encoding has no position information, so a comment thread survives a re-push after
the code moves: if the field is still there under the same name, the comment stays with
it. The cost of that choice is that the thread belongs to the field rather than to one
item of a list, and the page shows the same thread on every row of that field.

### Asking is deliberate, and in the table it is per column

The runtime opens a composer on any click that reaches the page root. On a tree a click
means "open this", not "write about this", so **the row swallows its own clicks** — it
expands when there is something to expand — and only the `✻` control is let through to
reach the root. The anchor stays on the row rather than on the control, so the composer
still opens underneath the row instead of inside its meta group, where it would tear the
line apart.

The disclosure triangle and the `⌘` button stop propagation for the same reason:
opening a node or jumping to a file must not also open a composer.

In the table view the `(type, field)` pair **is** the column, so the anchor and the `✻`
live in the column header — one thread per column, not one per cell. A thread per cell
would need a per-instance anchor, which the next push invalidates.

A nested column is anchored to the type that **declares** it, not to the record it is
nested inside: `current.marketValue.amount` carries `…$MarketValue#amount`. Anchoring it
to the enclosing record would put the thread on a field that type has not got. A group
header is a field too, so it carries its own anchor — `…$Allocation#marketValue` — and
can be commented on like any other.

The composer is taken out of flow inside a table block (`position: absolute`). The
runtime inserts it as the anchor element's next sibling, and the anchor there is a
`<th>`; left in flow it would become a stray cell and tear the header row apart.
