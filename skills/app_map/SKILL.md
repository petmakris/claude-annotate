---
name: app-map
description: Build or update a map of the application, a picture of its parts and how they connect, that the IntelliJ key Cmd+Shift+M shows over the editor with the open file's part lit, so the user can see where a file belongs. Use when the user says /app-map, asks for a map of the application, wants to know where a file belongs in the whole system, or wants the IntelliJ app map made or refreshed. Needs no daemon.
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
---

# /app-map: a map of the application for the IntelliJ key

In a large project a file's path does not say which part of the application it belongs to. This skill draws
the application once, the way an engine drawing shows its parts, and the IntelliJ plugin shows that drawing
on Cmd+Shift+M with the open file's part lit, its arrows lit and its owners named. You study the project with the
user, write `source.json`, and a build checks it and writes the `map.json` the plugin reads. Nothing runs
live: no daemon, no browser.

The map is for the user alone and the repo is public: nothing about a project goes into this repo, only into the
user's own files below.

## Files

All in `~/.config/claude-annotate/app-map/<name>/` (`APP_MAP_HOME` moves the root), `<name>` a short slug such as
the repo's folder name:

- `source.json`: what you and the user write. Kept, so a rebuild starts from it.
- `map.json`, `top.svg`, `<part>.svg`: what the build writes. Never edit them by hand.

## Commands

    claude-annotate app_map.app_map facts <repo>
    claude-annotate app_map.app_map check <name> [--repo DIR]
    claude-annotate app_map.app_map build <name> [--repo DIR]

`check` and `build` find the repo by `--repo`, else the first existing folder in `match.folders`. Both print a
JSON report: `check` writes nothing; `build` runs `check`, refuses (exit 1, nothing written) on any error, else
writes the files. Files are counted from `git ls-files`, so untracked and ignored files never count.

## source.json

    {
      "name": "shop",
      "match": {"remotes": ["github.com/acme/shop"], "folders": ["/abs/path/to/checkout"]},
      "map": { ...a map_svg spec: title, columns, boxes, zones, arrows, legend... },
      "parts": [
        {"id": "orders", "paths": ["/orders/", "/core/src/**/java/com/acme/core/orders/**"]},
        {"id": "billing", "paths": ["/billing/"]}
      ],
      "details": {
        "core": {
          "map": { ...a map_svg spec for the inside of core... },
          "parts": [{"id": "core-api", "paths": ["/core/src/**/java/com/acme/core/api/**"]}]
        }
      }
    }

- `match`: git remotes written as `host/owner/repo` (no scheme, no user, no `.git`, lower case) and absolute
  folders. The plugin finds the map by the project's `origin`, else by folder, so every checkout and worktree of
  one repo shares a map.
- `map` is an ordinary `map_svg` spec (`docs/vz.md`). **Every part id is a box id in its own map.** A box with no
  part (a label, an outside system) is fine.
- `paths` use GitHub CODEOWNERS patterns (`skills/app_map/paths.py`): a leading `/` anchors at the repo root, no
  slash matches at any depth, a trailing `/` is a folder and everything under it, `*` stays inside one folder
  name, `**` crosses folders. **The last part with a matching pattern wins**, so a narrow part placed after a
  broad one carves a slice out of it.
- `teams` (optional) maps a CODEOWNERS team to the short label on its pill.
- `repos` (optional) lists other repos the map spans, each `{"name", "remote", "folders"}` (for example a contract
  or library repo the app uses). A part with `"repo": "<name>"` has paths relative to that repo; parts without one
  belong to the map's own repo. The build reads every checkout (files, modules, CODEOWNERS each from its own repo)
  and adds each repo's remote and folders to `match`, so a file opened in either repo finds this map. The plugin
  matches a file only against the parts of its own repo, so the same folder name in two repos never mixes up.
  Arrows between repos come from reading the code: a dependency on another repo's published library (its group and
  artifact) is the edge.
- `details` maps a top-level part id to a map one level down. A file on that part is matched against the
  detail's parts too. One level only. **Part ids are unique across the top map and every detail.**

## Design rules for a good map

- **12 to 25 parts** at the top. Merge small modules that do one job into one part; split a big module along its
  package folders and its CODEOWNERS lines. It is a drawing of the system, never a grid of every module.
- **Columns are layers** of the system (for example entry points, features, shared services, integrations).
- **Wider than tall**, about 1.6 to 1 or wider, since the IDE window is: the plugin scales the map to fill the
  window's width. A layer with many parts takes two columns (the second one's label empty) rather than a long one;
  then check that no arrow crosses a box (`vz_check` reports it).
- **Clean lines.** When arrows from a far column bundle or cross, route them by hand with `points` (every corner,
  start and end, in the drawing's own coordinates, read from the boxes in `top.svg` after a build): give each its own
  lane and turn, ordered so none crosses another. A box with no arrows (such as the app's assembly) is a small box
  in a free cell, never a tall column. Redo the `points` after any change that moves boxes.
- **The title is the claim**: a sentence with a verb. Every word carries a fact: a real name, a number.
- **Arrows are dependencies, provider to user**: B points to A when A uses B. The legend says so, as a note such as
  "an arrow points from the part that provides code to the part that uses it". Draw non-test edges only (the
  `test: false` ones of `facts`), unless the user asks. A short label only when it adds a fact.
- **Slices inside a box first.** A big part that CODEOWNERS or its package folders split is best drawn as a box
  with its slices as `children`, each slice a part, on the top map: the plugin lights the slice at a glance, lights
  the arrows into the box around it, and names it "Box › Slice" in its header. The box itself then needs no part.
- **A detail map** only when the slices do not fit inside the box (more than about 10). Same rules inside.
- **No tone on a box.** In the IDE the lit part is the only colour on the map, so a coloured box reads as "your
  file is here". The plugin paints every box plain whatever its tone.
- **Team pills.** Each box shows a pill for each CODEOWNERS team that owns at least a fifth of its files (at most
  three), else a grey "No owner" pill. `teams` in `source.json` gives each team its short label, for example
  `{"@org/payments-team": "PAY"}`; ask the user for the labels the team uses. A team without one shows the last
  part of its name in capitals. The build gives each part's box a blank last row, where the pills go.
- **A box holds its name and the build modules in it**, as code: one code span per line, commas inside it, about
  34 characters a line (`` `rules, rules-repository` ``). A box that is not a whole module (a slice) holds its name
  only. No file counts, class lists or numbers the user did not ask for. The plugin's header shows the open file's
  module from `map.json`'s `modules`, which the build fills from `facts`.

## Make a map

1. Find the map for this repo: a folder under `~/.config/claude-annotate/app-map/` whose `source.json` matches
   by remote or folder. A new map gets a name.
2. Run `facts <repo>`. It lists build modules (Gradle, Maven, else top-level folders), the edges between them
   with their configuration, file counts and source folders per module, and the CODEOWNERS rules and teams (a
   GitLab `[Section]` line is skipped and counted in `skipped_sections`). Read the build files and the main
   packages enough to know what each module does and how they work together.
3. Draft `source.json` by the rules above and show the user the parts and columns in words before building.
4. Run `check <name>` until every file is on a part, or the rest is named as deliberate in your reply. Read the
   report: `unmapped` (count and the 20 biggest folders), `empty_parts`, `parts_without_box`,
   `boxes_without_part`, `duplicate_part_ids`, `map_errors`.
5. Run `build <name>`, then check each drawing until it reports 0 faults:

       uv run "$(claude-annotate root)/tools/vz_check.py" check ~/.config/claude-annotate/app-map/<name>/top.svg

   and the same for each `<part>.svg`.
6. Show the user `top.svg` and adjust it with them. A change goes into `source.json`, then `check`, `build`.

## Update

`/app-map` on a repo that already has a map starts from its `source.json`, not from scratch: run `check` and
read what moved: unmapped files (new modules or packages), parts with no files left, new edges in `facts`. Fix
`source.json`, build again. The plugin picks up the rebuilt `map.json` the next time the key is pressed, with no
IDE restart. The map shows the owners as of the build; the header of the overlay reads CODEOWNERS live.
