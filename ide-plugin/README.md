# ide-plugin — developer notes

The IntelliJ half of [claude-ide-review](../README.md). If you just want to *use*
the tool, read the repository README — this file is about building it.

## Build

    ./gradlew buildPlugin

The installable zip lands in `build/distributions/claude-ide-review-<version>.zip`.
The version is `0.1.<commit count>`, derived in `build.gradle.kts`, so it advances
on its own and never needs bumping by hand.

Requires a JDK 25 toolchain. Gradle auto-detects one from the usual locations; if
that fails on your machine, see the note in `gradle.properties`.

## Test

    ./gradlew test

## Run a sandboxed IDE

    ./gradlew runIde

Downloads the IDE matching `platformVersion` in `gradle.properties` and launches it
with this plugin installed, leaving your real IDE untouched.

## Iterating against your real IDE

`./reload` runs `prepareSandbox`, which is what actually refreshes the plugin your
IDE loads. `./reload --watch` rebuilds on every save, so you only ever restart.

The IDE loads the sandbox through a symlink you create once:

    ~/Library/Application Support/JetBrains/IntelliJIdea<version>/plugins/claude-ide-review
      -> <this dir>/.intellijPlatform/sandbox/.../plugins/claude-ide-review

That symlink is keyed to the IDE build. After an IDE point upgrade, `prepareSandbox`
writes to a *new* sandbox directory while the symlink still points at the old one —
the IDE then silently loads a stale jar. Repoint it and restart.

## How it talks to the Claude Code side

There is no socket handshake and no configuration. The Python side writes its URL
to `~/.claude/interactive-review/server.json` and `~/.claude/walkthrough/server.json`;
`ReviewSessionService` and `WalkthroughService` read those files and connect over SSE.
If the IDE shows nothing, check that the file exists and that the URL in it answers.

## Compatibility

`gradle.properties` holds the range (`pluginSinceBuild`, `pluginUntilBuild`).
`patchPluginXml` writes it into `plugin.xml` at build time, so editing the
`<idea-version>` tag in the source file has no effect.
