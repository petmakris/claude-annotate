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

    ./reload            # then restart IntelliJ
    ./reload --watch    # rebuild on every save; then you ONLY ever restart

`./reload` does two things: `prepareSandbox` (which copies the plugin jar and its
dependency jars into `.intellijPlatform/sandbox/<IU-version>/`), then points your
IDE's plugin symlink at that sandbox. It prints which one it linked:

    ✓ IntelliJIdea2026.2 → IU-2026.2.1

Both steps run every time, and the second is why. The sandbox directory is named
after the IDE **build**, so an IDE upgrade makes `prepareSandbox` write to a brand
new sandbox while the symlink still points at the old one — and the IDE then loads
a stale jar with no error anywhere, so every change you make appears to do nothing.
`./reload` re-links on each run, which is the only reliable defence.

It finds the config directory from the IDE's own `product-info.json`
(`dataDirectoryName`) rather than guessing, so it is correct on every OS:

    macOS    ~/Library/Application Support/JetBrains/<dataDirectoryName>
    Linux    ~/.config/JetBrains/<dataDirectoryName>      (or $XDG_CONFIG_HOME)
    Windows  %APPDATA%/JetBrains/<dataDirectoryName>

If it cannot find your IDE, set `IREVIEW_LOCAL_IDE_PATH` to its `Contents/`
directory. If another config directory still links into this repo, `./reload`
says so — that is a build you no longer run, and its link can be deleted.

**Confirming which jar is loaded.** The Review Annotations panel shows a build
stamp bottom-right (`b177 · 08:11:23`) — the git commit count and build time
baked into the jar. If it is older than your last `./reload`, the IDE is running
a stale plugin.

## How it talks to the Claude Code side

There is no socket handshake and no configuration. The Python side writes its URL
to `~/.claude/interactive-review/server.json` and `~/.claude/walkthrough/server.json`;
`ReviewSessionService` and `WalkthroughService` read those files and connect over SSE.
If the IDE shows nothing, check that the file exists and that the URL in it answers.

## Compatibility

`gradle.properties` holds the range (`pluginSinceBuild`, `pluginUntilBuild`).
`patchPluginXml` writes it into `plugin.xml` at build time, so editing the
`<idea-version>` tag in the source file has no effect.
