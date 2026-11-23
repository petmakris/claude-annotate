# Merging claude-ide-review and web-companion into claude-annotate

Date: 2026-08-05
Status: approved, ready for implementation planning

## Problem

The local HTTP server, SSE event bus, session registry and thread store live in
`petmakris/web-companion` and are copied into two plugin repositories as a
vendored tree under `skills/_shared/web_companion/`. `sync-vendor.sh` writes the
copy, stamps a `# GENERATED FILE — DO NOT EDIT` banner into every `.py` and
`.sh`, and records the source SHA; CI verifies the copy against a checksum
manifest.

The machinery works, and the drift it exists to prevent has happened anyway:

| Repository | Vendored SHA | State |
|---|---|---|
| claude-annotate | `7bc4988` | current (= web-companion HEAD) |
| claude-ide-review | `76af9c0` | behind |

The two copies differ in `server.py` (192 changed lines), `static/sessions.html`
(262), `static/core.js` (66) and `static/core.css` (24). claude-annotate's copy
carries three tests the other lacks: `test_index_page.py`, `test_port_binding.py`,
`test_write_gate.py`.

Every server fix costs a commit in web-companion plus a sync commit in each
consumer. One consumer has stopped paying, so the plugins now run different
servers.

## Goal

One server, one copy, edited in place. Everything else in this document exists
to serve that.

## Decisions

| Question | Decision |
|---|---|
| Repository name | Keep `claude-annotate` — preserves the URL, the marketplace entry and 14 commits of history |
| Plugins published | Two, sharing one root |
| Git history | Fresh copy, one commit. History preservation was explicitly not a goal |
| Old repositories | Archived read-only on GitHub, not deleted |
| `ide-plugin/` location | Repository root, unchanged |

## How two plugins share one root

A repository is a *marketplace*, not a plugin. `.claude-plugin/marketplace.json`
lists as many plugins as it wants, and each entry's `source` says where that
plugin's files are. Two shapes exist in the wild:

**Plugins in subdirectories.** `source: "./plugins/nord"`, each directory
self-contained with its own `plugin.json`. Claude Code resolves that directory
as if it were the whole repository. Rejected: self-contained means
`skills/_shared/` would have to exist inside each plugin directory, which is
vendoring again with a shorter path.

**Plugins sharing one root.** `source: "./"` for every entry, with an explicit
`skills` array naming the directories that entry exposes, and metadata carried
in the marketplace entry rather than a `plugin.json`. Anthropic's
`anthropic-agent-skills` marketplace ships three plugins this way.

The second shape is what makes the merge possible: the plugin boundary becomes a
*listing* concern rather than a *directory* concern, so `_shared` can sit once in
a tree that several plugins draw from.

```json
{
  "plugins": [
    { "name": "claude-annotate", "source": "./", "strict": false,
      "skills": ["./skills/annotate"] },
    { "name": "claude-ide-review", "source": "./", "strict": false,
      "skills": ["./skills/interactive_review", "./skills/walkthrough"] }
  ]
}
```

`.claude-plugin/plugin.json` is deleted — two plugins cannot share one, and the
metadata moves into the entries above.

The exact semantics of `strict: false` are read off a working marketplace rather
than off documentation. Confirm during implementation that both plugins install
and their skills appear; that is the acceptance test for this section.

## Target layout

```
claude-annotate/
  .claude-plugin/marketplace.json     two entries, both source "./"
  skills/_shared/web_companion/       one copy, no VENDOR.txt, no banners
  skills/annotate/
  skills/interactive_review/          from claude-ide-review
  skills/walkthrough/                 from claude-ide-review
  ide-plugin/                         from claude-ide-review, 676K tracked
  hooks/hooks.json
  docs/
  .github/workflows/{ci,release}.yml
```

Imports are unchanged. Both repositories already write
`skills._shared.web_companion.*` and already place the package at the same path,
so no import is rewritten anywhere.

The per-skill `ensure_server.sh` files are 8-line shims delegating to the
153-line one in `_shared`. That indirection already works and is left alone.

## Which server copy survives

claude-annotate's, being current with web-companion HEAD.

This upgrades the `interactive_review` and `walkthrough` skills across the
write-gate change: the newer server requires an `X-WebCompanion-Token` header on
every mutating request, and the IntelliJ plugin's Java clients were written
before that header existed.

They are unaffected. `_is_owner` (`skills/_shared/web_companion/server.py:508`)
returns `True` for any loopback client before it inspects the header, and the
IntelliJ plugin connects to `127.0.0.1`. No Java changes are needed.

## What is deleted

In this repository:

- `skills/_shared/VENDOR.txt`, `skills/_shared/VENDOR.sha256`
- the `# GENERATED FILE — DO NOT EDIT` banner from every `.py` and `.sh` under
  `skills/_shared/`
- the `vendor` job in `.github/workflows/ci.yml`
- `.claude-plugin/plugin.json`

In `petmakris/web-companion`: `sync-vendor.sh`, `check-vendor.sh`. The
repository is archived read-only rather than deleted, so a wrong call here stays
recoverable.

Removing the banners is the point of the exercise. After this change, editing
`skills/_shared/web_companion/server.py` in this repository is the correct and
only way to change the server.

## CI

Both repositories' `ci.yml` are byte-identical apart from ide-review's extra
`ide-plugin` job, so the merged file is a union rather than a reconciliation:

- **pytest** — `python3 -m pytest skills -q`, runs on every change
- **ide-plugin** — `./gradlew buildPlugin test`, path-filtered to `ide-plugin/**`
  so a skills-only change does not start a JetBrains build

`release.yml` moves across unchanged except:

- the trigger tag becomes `ide-plugin-v*`, leaving `v*` free for plugin releases
- the release body's `/plugin marketplace add petmakris/claude-ide-review`
  becomes `petmakris/claude-annotate`

### IntelliJ plugin version numbering

`ide-plugin/build.gradle.kts:37` sets `version = "0.1.$buildNumber"` where
`buildNumber` is `git rev-list --count HEAD`. Against ide-review's 8 commits that
yields 0.1.8; against this repository's history the next build is **0.1.15**.

The jump is forward, so IntelliJ accepts the upgrade. The consequence is that
every commit to this repository now increments the IDE plugin version even when
no Java changed. Accepted as-is — a version number that moves too often is not a
problem worth solving today.

## Testing

Measured before the merge:

| Suite | Passing |
|---|---|
| claude-annotate `skills` | 633 |
| claude-ide-review `skills` | 176 |
| claude-ide-review `interactive_review` + `walkthrough` only | 96 |

The 80-test difference is duplicate `_shared` tests, which disappear with the
second copy.

**Acceptance: `python3 -m pytest skills -q` reports 729 passing.**

The exact number matters more than a green tick — 729 is the only result that
proves no test was silently dropped while copying trees around.

Additional manual checks, neither covered by pytest:

1. Both plugins install from the merged marketplace and their skills appear.
2. `/interactive-review` against a PR still drives the IntelliJ plugin, which
   confirms the write-gate reasoning above on the real client rather than on a
   reading of the source.

## Migration

"Fresh copy" describes how the *history* arrives — the trees are copied rather
than merged with `--allow-unrelated-histories`, so neither source repository's
commits are grafted on. It does not mean the work lands as one commit. Each step
below carries its own test gate and is worth reviewing on its own, so each is its
own commit:

1. Copy `skills/interactive_review/` and `skills/walkthrough/` from
   claude-ide-review, and `ide-plugin/` with it. Confirm 729 tests pass.
2. Repoint the absorbed skills' plugin-root probe at this marketplace.
3. Rewrite `.claude-plugin/marketplace.json`; delete `.claude-plugin/plugin.json`.
4. Delete the vendoring artifacts and strip the banners.
5. Merge the CI workflows; add `release.yml` with the retagged trigger.
6. Update `README.md` to describe a repository that ships two plugins.

### The absorbed skills need repointing

Each skill resolves its own installed directory by looking its marketplace up in
`~/.claude/plugins/known_marketplaces.json`, which is keyed by **marketplace**
name:

```python
NAME, MARKER = "claude-ide-review", "skills/interactive_review/ensure_server.sh"
```

After the merge the only key is `claude-annotate`, so both absorbed skills abort
with "plugin root not found" until `NAME` is changed. This is the one functional
break the merge causes, and it is invisible until install time — so it gets a
test that derives the expected name from `marketplace.json` rather than hardcoding
it.

### The root hooks file reaches both plugins

`hooks/hooks.json` sits at the repository root and both plugins claim that root,
so installing `claude-ide-review` alone probably also registers annotate's
PostToolUse hook. `progress_publish.py` returns immediately when the session has
no pending annotate rounds and always exits 0, so the effect is a spare `python3`
spawn per tool call rather than a malfunction. Verified during implementation and
recorded; not worth pre-emptive work.

Afterwards, archive `petmakris/claude-ide-review` and `petmakris/web-companion`,
each with a README line pointing here.

## Out of scope

- Renaming the repository, the skills, or the Java package `com.petros.ireview`.
- Unifying the three skills' `server.py` files. They are separate concerns that
  share an engine, which is the arrangement that already works.
- Publishing to any marketplace beyond the existing one.
