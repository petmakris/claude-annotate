# walkthrough — generation contract

Read this before you write `.steps.draft.json`, and again for the re-pass
before pushing: steps are frozen once pushed, so a rule broken here cannot be
fixed later.

Hard rules. A tour that breaks one of these is a defect, not a style choice.

- **5–12 steps.** Fewer than 5 means the question deserved a paragraph in
  terminal — answer it there instead and do not create a tour. More than 12 means
  the question is too broad: ask the user to narrow it. If they decline, build the
  best 12-step spine and say what you left out.
- **Every step is a real anchor.** `file` + `line` + verbatim `snippet`. Never
  anchor to a file you did not `Read` in this turn. Never guess a line number.
- **Execution order, not file order.** Follow how control and data actually flow:
  entry point → gate → dispatch → implementation → data model → seam. Grouping
  steps by package is a failure mode.
- **Each step earns its place.** The markdown says *what happens here* and *why it
  matters for the question asked* — 2–5 sentences. It is not a file summary.
- **The last step answers the question.** For "how to add X", the final steps carry
  `role: "edit-site"` and name the exact file or directory for the new code, the
  registration point, and the test that would prove it. Concretely named — never
  "somewhere in the workflow package".
- **Link references inline.** `[evaluate](src/main/java/.../RuleRegistry.java:30)`
  for code, absolute URLs for tickets. The IDE renders these clickable.
- **Titles ≤ 6 words**, plain-text noun phrases — they are rail rows and HUD text.
- **Cross-block re-pass.** After drafting all steps, re-read them together and fix
  what only shows up in aggregate: a step repeating its neighbour, a jump with a
  missing bridge, a title that no longer matches its body, an ordering that only
  made sense while you were writing it. Do this **before** writing the document —
  steps are frozen once pushed.
