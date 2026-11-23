# App map: a key in IntelliJ shows where the open file sits in the whole application

## Intent

In a large project (the motivating one has 59 Gradle modules and about 9,700 Java files) the user opens a file and cannot tell which part of the application it belongs to. The breadcrumb shows a path, not a picture.

The app map is a picture of the application drawn once, the way an engine drawing shows its parts and how they connect. One key in IntelliJ calls it up over the editor, like the score screen in a game: it lights up the part the open file belongs to, shows how that part connects to the rest, and shows who owns it. Letting go of the key puts it away.

It is for the user alone. The repo is public, so the tool is generic: nothing about any one project is in the code, tests or docs. A project's map lives with the user's own files.

## Goals

- From any open file, one key shows the map with the file's part lit, its arrows in and out lit, and the file's owner.
- A part can be one build module, several merged, or a slice of a big module (packages). Claude decides with the user when the map is built.
- A big part has its own detail map, one level down, with the file's sub-part lit.
- A codeowners layer colours each part by the team that owns most of its files.
- Showing the map is instant: native Java2D painting, no browser, no daemon, no network.
- The map is rebuilt by hand (`/app-map`) when the application changes. The plugin picks up a rebuilt map the next time the key is pressed, with no IDE restart.

## Non-goals

- No live analysis in the IDE. The plugin does no dependency or package scanning.
- No editing of the map in the IDE. The map is changed through `/app-map`.
- No webcompanion, no JCEF, no server.
- No class-level or method-level map.

## Anti-goals

- The map must not be a grid of every module. It is a drawing of the system with merged and split parts and arrows that carry meaning.
- The key must never get in the way of typing: no clash with an editing key.
- A file that fits nowhere must say so plainly. It is never silently lit as some other part.

## Constraints

- Generic: no project names, hosts or company names anywhere in the repo. Tests use a made-up project.
- Python 3.9+, stdlib only, for the skill's scripts (repo rule).
- The IntelliJ plugin is `ide-plugin/` (`com.petros.ireview`), Java 25, targets build 261+. It is deployed with `ide-plugin/./reload`, never a zip (see `ide-plugin/CLAUDE.md`).
- Every plugin shortcut goes in `ShortcutCatalog` (its test fails otherwise). Fonts are sized with `JBUI.Fonts.label(float)`, never `deriveFont`.
- Diagrams follow `docs/vz.md`: the title is a sentence with a verb; a dependency arrow points from the part that provides the code to the part that uses it (B → A when A uses B), and the legend says so.
- Logic classes in the plugin have no IntelliJ imports, so they unit-test with plain JUnit, like `SynthesisHtmlRenderer`.

## Approaches

| | Approach | Gain | Cost |
|---|---|---|---|
| A | Python `map_svg` draws an SVG; the plugin shows it in JCEF | one drawer, no new layout code | browser start-up on show; user rejected JCEF for speed |
| B | The plugin lays out and draws the map itself in Java | fully native | a second layout engine that drifts from `map_svg` |
| C | webcompanion serves the map as a page | opens anywhere | needs a running daemon; user rejected it |
| **D (picked)** | `map_svg` lays out once at build time; the build turns its SVG into a list of shapes with final coordinates; the plugin paints that list in Java2D | native and fast, one layout engine | a small converter from SVG to shapes |

The user picked native Java for speed and ruled out webcompanion. D keeps the drawing native while all the layout stays in `map_svg`, which the user's other tools already use.

## How it works

### Two halves

1. **The skill `/app-map`** (in the `claude-ide-review` plugin, `skills/app-map/`). Claude studies a project with the user, writes a map source file, and runs a build that checks it and writes the map file the plugin reads.
2. **The IntelliJ part** (in `ide-plugin/`). A key shows the map file's drawing over the IDE window and lights the open file's part.

### Files

All per-project files live outside every repo, in `~/.config/claude-annotate/app-map/<name>/` (`APP_MAP_HOME` moves the root, for tests):

- `source.json`: what Claude and the user write. Parts, rules, layout, details. Kept so a rebuild starts from it.
- `map.json`: what the build writes and the plugin reads. Never edited by hand.

`<name>` is a short slug Claude picks with the project (for example the repo's folder name).

### Which map belongs to which project

`source.json` has `match`: a list of git remote URLs and a list of absolute folders. The plugin finds the map for an IntelliJ project by its root folder's git `origin` URL (normalised: no scheme, no user, no `.git`, lower case), else by folder. So every checkout and worktree of the same repo finds the same map. When two maps match, the plugin uses the one whose `map.json` is newest and logs a warning.

### source.json

```json
{
  "name": "shop",
  "match": {"remotes": ["github.com/acme/shop"], "folders": []},
  "map": { "...": "a map_svg spec: title, columns, boxes, zones, arrows, legend" },
  "parts": [
    {"id": "orders", "paths": ["orders/**", "core/src/**/java/com/acme/core/orders/**"]},
    {"id": "billing", "paths": ["billing/**"]}
  ],
  "details": {
    "core": {
      "map": { "...": "a map_svg spec for inside core" },
      "parts": [{"id": "core-api", "paths": ["core/src/**/java/com/acme/core/api/**"]}]
    }
  }
}
```

- `map` is an ordinary `map_svg` spec (`docs/vz.md`). Every part id is a box id in it. A box may have no part (a label box, an outside system).
- `parts[].paths` are repo-relative patterns with CODEOWNERS semantics (below). **The last part whose pattern matches a file wins**, as in CODEOWNERS, so a narrow rule placed after a broad one carves a slice out of it.
- `details` maps a top-level part id to a map one level down, with its own `map` and `parts`. A file in that top-level part is also matched against the detail's parts. One level only.

### The path matcher

One matcher, used for parts and for CODEOWNERS, with GitHub's CODEOWNERS rules: a leading `/` anchors to the repo root; a pattern without a slash matches at any depth; a trailing `/` matches a folder and everything under it; `*` matches within one folder name; `**` matches any number of folders. There are two copies, Python (build) and Java (plugin). Both run the same cases from one JSON file, `skills/app-map/tests/match_cases.json`, so they cannot drift (the same pattern as `skills/journey/store.py` and `canvas-store.js`).

### The build: `app_map.py`

`skills/app-map/app_map.py`, stdlib only, with sub-commands:

- `facts <repo>`: prints JSON that Claude reads to design the map. Build modules and the dependencies between them (Gradle `settings.gradle(.kts)` `include` and `project(':x')` in each build file; Maven `<modules>` and dependencies on sibling artifacts; otherwise top-level folders). Source file counts per module and per top package folder. The CODEOWNERS file (found at `.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS`, first found wins, as GitHub does) as a list of rules, and its teams.
- `check <name>`: validates `source.json` and reports, without writing: files on no part (count and the 20 biggest folders), parts that match no file, box ids with no part, part ids with no box, and each part's file count. The file list is `git ls-files` in the first matching folder, so ignored files never count.
- `build <name> [--repo <folder>]`: runs `check`, then writes `map.json`. It refuses when a part id has no box. Files on no part are reported, not refused.

`map.json` holds:

- `match`, `parts` and `details` as in the source (the plugin matches at runtime, so new files land in the right part without a rebuild).
- `drawing`: for the top map and each detail map, the shapes from `map_svg.render(spec, uid, keyed=True)`, read back with `xml.etree.ElementTree`: the canvas size, then a list of shapes with absolute coordinates. Kinds: `rect` (x, y, w, h, radius, role `zone` or `box`, tone, key), `path` (points from the `M`/`L` commands, tone, dashed, arrowhead, key), `text` (x, y, anchor, role `title`, `subtitle`, `column`, `zone`, `name`, `line`, `label`, tone, key, and runs of plain and mono text from `tspan`s). Role and tone come from the SVG classes. The key is `data-key` (`box:<id>`, `zone:<i>`, `edge:<from>-><to>#<n>`).
- `owners`: for each part (top and detail), its share of files per CODEOWNERS team, computed at build time with the same matcher: `{"orders": [{"team": "@acme/orders", "files": 812}, {"team": null, "files": 40}]}`. `null` is files no rule covers.
- `built`: the time and the repo's `HEAD` commit at build time.

The converter fails the build on any SVG element or class it does not know, so a change in `map_svg` cannot silently drop shapes. A test renders a spec that uses every feature (zones, children, labels, code spans, legend, all tones, dashed arrows) and checks every shape survives.

### The skill: `/app-map`

`skills/app-map/SKILL.md` tells Claude how to make or update a map:

1. Find the map for the current repo (by `match`); a new one gets a name.
2. Run `facts`. Read the build files and the main packages enough to understand what each module does and how they work together.
3. Draft `source.json`: 12 to 25 top-level parts, merging small modules that do one job and splitting a big module along its package folders and its CODEOWNERS lines. Columns read as layers of the system (for example entry points, features, shared services, integrations). Arrows show real dependencies, provider → user, with a short label only when it adds a fact. A part with more than about 800 files, or one CODEOWNERS splits, gets a detail map.
4. Run `check` until every source file is on a part, or the rest is named as deliberate in the reply.
5. Run `build`, then `uv run tools/vz_check.py check` on each map's SVG (written beside `map.json` as `top.svg` and `<part>.svg`) until it reports 0 faults.
6. Show the user the top map's SVG and adjust it with them.

An update (`/app-map` on a repo that has a map) starts from the existing `source.json` and the new `check` report: unmapped files, new modules, parts with no files.

### The IntelliJ part

New classes in `com.petros.ireview`, logic separate from Swing:

| Class | Job | IntelliJ imports |
|---|---|---|
| `AppMapPaths` | the CODEOWNERS-style matcher | none |
| `AppMapFile` | reads `map.json` (Gson), finds the part and detail part of a repo-relative path | none |
| `AppMapStore` | finds the map for a project root (remote, then folder), caches it by `map.json` modification time | none |
| `CodeOwners` | reads the project's CODEOWNERS at show time, cached by modification time, and gives a file's owners | none |
| `AppMapCanvas` | paints a drawing into a `Graphics2D` scaled to a rectangle, with a lit part | Swing/AWT only |
| `AppMapOverlay` | the overlay component on the IDE window's layered pane | yes |
| `AppMapActions` | the key: show, hold, toggle | yes |

**The overlay.** A child of the IDE frame's `JRootPane` layered pane at `POPUP_LAYER`, filling the frame, like `WalkthroughHud` does for its pill (a component, not a `JBPopup`, so focus changes do not close it). It dims the IDE behind it and paints, top to bottom:

- a header row: the file name; its place as `Part › Sub-part`, or "Not on the map"; its owners from the live CODEOWNERS, or "No owner"; the map's build date;
- the drawing, scaled to fit the space left, never above 1.0 of its build size times the IDE scale (so text stays the size it was laid out for), centred;
- a footer row of buttons with icon and word: Back (in a detail map) and Close.

**What is lit.** The file's part box gets the accent fill and a thicker border. Arrows whose `edge:` key has that part at either end are drawn in the accent colour; all other shapes are drawn at reduced contrast. The file's zone keeps its normal look. With no file open, or a file on no part, nothing is lit and the map is drawn normally.

**Colours.** The map is always light, whatever the IDE theme (the user's choice, 23 November 2026). Text uses the IDE's UI font (Inter on the new UI) for sans roles and JetBrains Mono for mono runs, the same faces `map_svg` measured with.

**Team pills (23 November 2026, replacing the owners layer).** Each box always shows a pill for each CODEOWNERS team that owns at least a fifth of its files (at most three, biggest first), on a row of their own at the foot of the box (the build adds a blank last line to every part's box); a box where no team reaches a fifth shows a grey "No owner" pill. A pill's label comes from `teams` in `source.json` (carried into `map.json`), else the last part of the team's name in capitals. There is no Owners button and no legend. A box's tone is ignored: the lit part is the only colour on the map.

**The detail map.** Clicking a part that has a detail map, or pressing Enter while the file's part has one, shows the detail map with the file's sub-part lit. Back or Backspace returns to the top map.

**The key.** Cmd+Shift+M (the user's choice, 23 November 2026; it replaced `alt M`), on the Mac keymaps. The stock Mac keymap also binds it to "Move to another changelist", so `AppMapPromoter` puts the app map first. Pressing it shows the map. If the key is released within 300 ms, the map stays open until Escape, Cmd+Shift+M again, a click outside the drawing, or Close: this is the mode for clicking into details. If it is held longer, releasing Cmd, Shift or M closes it, like a game's score screen. The release is seen through `IdeEventQueue` key events while the overlay is open. The action is listed in `ShortcutCatalog`.

**No map for this project.** The overlay shows one line: "No app map for this project. Run /app-map in Claude Code in this repo." It never throws.

**A broken map.** A `map.json` that fails to read shows "The app map could not be read: <reason>. Run /app-map to rebuild it." and logs the cause.

## Tests

- Python, in `skills/app-map/tests/` (run by the repo suite): the matcher on `match_cases.json`; `facts` on a made-up Gradle project and a made-up Maven project in a temp folder (with `git init`); `check` reports (unmapped files, empty parts, missing boxes); the SVG converter keeps every shape of a full-feature spec and fails on an unknown element; `build` writes the expected `map.json` for the made-up project, including `owners`.
- Java, in `ide-plugin/src/test/java/com/petros/ireview/`: `AppMapPaths` on the same `match_cases.json` (read from the repo path at test time); `AppMapFile` part and detail lookup and last-match-wins; `AppMapStore` remote normalising and newest-wins; `CodeOwners` on a sample file; `AppMapCanvas` paints a sample drawing into a `BufferedImage` and the pixel at the lit box's centre has the accent colour while an unlit box's does not. `ShortcutCatalogTest` covers the new key.
- By hand once: build a map of a real project, `./reload`, restart IntelliJ, press Cmd+Shift+M on a few files, take a screenshot.

## Left to the builder

- Exact colours, as long as the targets in the house style hold (accent 3:1 against the box, dim text 4.5:1).
- How the overlay animates in, if at all (keep it under 120 ms or none).
- The icon for the actions.

## Settled after the builder check

These answer the reviewer's questions. Each is a call made without the user, by the rule that design questions are settled by the session.

1. **The key was `alt M`, now Cmd+Shift+M (see "The key").** IntelliJ runs a keymap action before the editor types a character, which is how the plugin's `alt D`, `alt B` and `alt N` already work on the Mac, so `µ` is never typed. The release is read from `KEY_RELEASED` events (`VK_M` or `VK_ALT`) through an `IdeEventQueue` dispatcher added while the overlay is open and removed when it closes. The builder checks once that the default Mac keymap has nothing on `alt M`; if it has, the plugin's binding still wins inside the editor, and the conflict is noted in `ShortcutCatalog`.
2. **The skill joins the `claude-ide-review` plugin.** Its folder is `skills/app_map/` (an importable name, like `ask_diff`), its skill name `app-map`, and it is added to that plugin's `skills` list in `.claude-plugin/marketplace.json`. The entry's description gains one sentence for `/app-map` and says it needs no daemon. The scripts import `skills._shared.visuals.map_svg` and run through the plugin's runner: `claude-annotate app_map.app_map <command> ...`. The drawing check runs as `uv run "$(claude-annotate root)/tools/vz_check.py" check <svg>`.
3. **The plugin reads the git remote itself, from files.** `AppMapStore` takes the project's base folder, walks up to the folder holding `.git`, and reads `[remote "origin"] url` from its `config`. When `.git` is a file (a worktree), it follows `gitdir:` and then that folder's `commondir` to the shared `config`. No `git` process, no git4idea. A repo-relative path is the file's path relative to that `.git` folder's parent. A project with no git folder is matched by folder only; no match shows "No app map for this project".
4. **The converter keeps every drawn element.** Shapes are `rect`, `path`, `line` (leader lines `lk` and legend arrows), `circle` (arrow badges, role `badge`) and `text` with its `tspan` runs. `defs` and `marker` are read only to learn that an arrowhead goes at the end of a path or line with `marker-end`; the shape gets `arrow: true`, and Java paints a filled triangle 7 px long in the arrow's tone, pointing along the last segment. Any other element or an unknown class fails the build. Lighting an arrow lights every shape carrying its `edge:` key: the path, its label, its badge and its leader line.
5. **Part ids are unique across the top map and every detail map**; the build refuses a duplicate. Every part id must be a box id in its own map; the build refuses otherwise. A box with no part is fine. A file on a top part that has a detail map but on none of its sub-parts is on the map: the header shows the top part only, the top map lights it, and the detail map lights nothing and says "On no sub-part".
6. **Owners have two sources on purpose.** The header shows the open file's owners from the project's CODEOWNERS read live. The owners layer shows the build's snapshot, and its legend says "Owners as of <build date>". Only GitHub's CODEOWNERS syntax is read; a GitLab `[Section]` line is skipped, and `facts` lists how many were skipped.
7. **Window and file.** The overlay goes on the window that holds the focused component when that window has a `JRootPane`, else on the project's frame (`WindowManager.getFrame`). The file is `CommonDataKeys.VIRTUAL_FILE` from the action's event, else the selected editor's file. The map shows the file as it was when opened; it does not follow later editor switches. It closes when its project closes.
8. **Dependencies in `facts`.** Gradle: `project(':x')`, `project(":x")` and `projects.x` accessors in any configuration, each edge with its configuration name and `test: true` when the configuration name starts with `test` or contains `Test` or `testFixtures`. Maven: a dependency whose group and artifact match a sibling module, with its scope, `test: true` for scope `test`. The skill tells Claude to draw non-test edges only, unless the user asks.

## Slices inside a box (23 November 2026)

The user chose to draw the web API's feature slices inside its box on the top map instead of in a detail map. A slice is a `children` box that is a part. When a slice is lit, the box holding it stays undimmed, arrows into or out of that box are lit too, and the header names it "Box › Slice". Detail maps stay supported for a part whose slices do not fit.

## Module names (23 November 2026)

Each box lists the build modules in it, as code, in place of a description. The build writes `modules` (name and folder of each build module) into `map.json`, and the header shows the open file's module: the deepest module folder that holds it. Code text on the map is drawn in the ink colour so small mono names stay readable.

## Using the whole window (23 November 2026)

The overlay's chrome is one row at the top (in the Mac title-bar strip, right of the window buttons): file name, place, module and owners on the left, the build date and the Back and Close buttons on the right. There is no footer. The drawing gets the rest less a 10 px margin, may grow to twice its built size, and sits right under the header so unused height is left at the bottom. Maps are drawn wider than tall to match the window.

## One map over two repos (23 November 2026)

The user wanted the integration layer contract, a separate repo the app depends on as a published library, on the same map. `source.json` lists extra repos (`repos`: name, remote, folders) and a part may name its `repo`. The build reads every checkout, counts and owns each part's files in its own repo with that repo's CODEOWNERS, writes `repos` and each part's `repo` into `map.json`, lists modules with their repo, and adds each repo's remote and folders to `match`. The plugin learns which repo a file is in from its checkout's origin remote and matches it only against that repo's parts and modules.

## Modes and the editor pill (23 November 2026)

The user picked these from mock-ups. The map gets modes in its header (buttons, and the keys F, B, T, U, W): this file; the branch, lighting every part with a file changed since the branch left its base (the base found as the diff keys find it), with no file counts; the open tabs, darker with more tabs; who uses the open file, its part in the accent and the parts with files that use its classes in amber; and the walkthrough, each step's part grey with its number, the current one lit, joined in order by a dotted trail, the map opening on it while a walkthrough runs. Clicking a part to jump to its code was declined. A pill at the top right of each editor shows the file's build module and its CODEOWNERS teams only, coloured as on the map; the part of the app stays on the map, and a click on the pill opens it.

