# Block kind: `compare`

Code **before and after** a change, side by side, as a split diff: the page
computes the line diff itself, lines that stayed sit level on both sides,
removed lines are tinted red on the left, added lines green on the right, and
a hatched filler stands where one side has no line. Both panes are painted by
the same highlighter as every other piece of code on the page, in the reader's
code theme, with line numbers per side.

## When to use
- You are showing **how a piece of code changes**: today's version and the one
  you propose, master and a branch, the code before and after a refactor.
- Instead of two fenced blocks one under the other, which make the reader
  hold the first in their head while reading the second.

## When NOT to use
- Explaining what one version does, span by span → `explain`.
- A whole branch's or PR's diff → `/show-diff` or `/pr-diff`. This kind is a
  snippet, one function or a few, not a file; quote the part that changed.
- Prose about the change. It goes in a `markdown` block before or after this
  one: the compare block holds code only, takes no `code` anchors (its panes
  are the code), and is not editable as text.

## Block shape

    {"id": "section-N", "kind": "compare", "title": "tasksOf becomes defineTasks", "spec": {
      "before": {"label": "Today · master", "path": "advisory/src/main/java/…/EDR.java",
                 "lang": "java", "code": "…"},
      "after":  {"label": "Proposed",       "path": "advisory/src/main/java/…/EDR.java",
                 "lang": "java", "code": "…"}
    }}

- `before`, `after` — one side each. Every field in a side is a string, and all
  are optional:
  - `code` — the snippet, verbatim. One trailing newline is ignored.
  - `label` — the pane's name ("Today · master", "Proposed"); defaults to
    "Before" / "After".
  - `path` — the file, shown beside the label. The language comes from its
    extension when `lang` is absent.
  - `lang` — must be a name or alias in `static/code-languages.json`; any other
    is refused at push, since it would render uncoloured.
- A side that is absent or has empty `code` is not drawn: the other side takes
  the full width with every line marked added (a new file) or removed (deleted
  code).
- `spec.title` names the part when the block has no `title`.

## Example

    {"id": "section-2", "kind": "compare", "title": "One map of every status", "spec": {
      "before": {"label": "Today · master", "path": "workflow/EDR.java",
                 "code": "public static Entry<Status, List<Task>> tasksOf(Status status, Task... tasks) {\n    var taskList = Arrays.asList(tasks);\n    return new SimpleEntry<>(status, taskList);\n}\n"},
      "after":  {"label": "Proposed", "path": "workflow/EDR.java",
                 "code": "public static Map<Status, List<Task>> defineTasks(Function<Status, List<Task>> tasksPerStatus) {\n    return Arrays.stream(Status.values()).collect(Collectors.toMap(status -> status, tasksPerStatus));\n}\n"}
    }}

## Commenting and rewriting
The reader comments on the whole part from its heading, or selects words in
either pane. To change it, rewrite `spec` with `update_spec_block` (see
`references/handling-events.md`), the same as for `explain`.
