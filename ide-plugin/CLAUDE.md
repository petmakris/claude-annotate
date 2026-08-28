# claude-ide-review plugin — instructions for Claude

## Deploying a change to the user's IntelliJ

The user's IntelliJ loads this plugin through a **symlink into the Gradle
sandbox**, not through an installed zip:

    ~/Library/Application Support/JetBrains/IntelliJIdea<version>/plugins/claude-ide-review
      -> ide-plugin/.intellijPlatform/sandbox/claude-ide-review/IU-<build>/plugins/claude-ide-review

**Never tell the user to install a zip from disk.** "Settings → Plugins → ⚙ →
Install Plugin from Disk" is wrong here and creates a second, real directory
that shadows the symlink — `./reload` then refuses to touch it and every later
change silently does nothing.

The command is always:

    cd ide-plugin && ./reload          # then the user restarts IntelliJ
    cd ide-plugin && ./reload --watch  # rebuild on save; user only ever restarts

Decision procedure when a change needs to reach the running IDE:

- The change is Java/Kotlin/resources in `ide-plugin/`
  - → run `./reload`
  - → then tell the user to **restart IntelliJ**. Plugin classes are not
    hot-swappable; without a restart the old ones stay loaded and the user will
    report that nothing changed.
- You only need to know the code compiles and tests pass
  - → `./gradlew test`. Do not run `./reload` — it is for deployment, not
    verification.
- The user asked for the installable artifact specifically
  - → `./gradlew buildPlugin`, zip lands in `build/distributions/`.
  - → **`buildPlugin` does NOT re-point the symlink.** It refreshes the
    sandbox, so it happens to work while the IDE build is unchanged, and
    silently loads a stale jar the moment the IDE upgrades and
    `prepareSandbox` starts writing to a new `IU-<build>` directory. Use
    `./reload` for anything the user is meant to see.

`./reload` prints which config directory it linked, e.g.

    ✓ IntelliJIdea2026.2 → IU-2026.2.1

and warns about other JetBrains config dirs still pointing into this repo —
those belong to IDE versions the user no longer runs.

## The two renderers behind the synthesis popup

`SynthesisPopup` picks one at construction (`tryCreateBrowser`), and they are
NOT interchangeable — a fix applied to the wrong one is invisible:

- `JBCefApp.isSupported()` is true → **`SynthesisBrowser`** → `SynthesisHtmlRenderer`
  - embedded Chromium. Full CSS, JS, `language-*` syntax highlighting via the
    bundled `resources/web/highlight.min.js`.
  - → this is what the user actually sees. Assume this path.
- else → **`MarkdownLinkRenderer`** into a `JEditorPane`
  - Swing HTML 3.2. No flexbox, no CSS variables, no `<h2>`, no lists, no
    tables — it regex-parses four markdown forms and nothing else.
  - → a fallback only. Do not spend design effort here.

Telling them apart from a screenshot: headings, bullets and tables render only
in the JCEF path.

`SynthesisHtmlRenderer` and `SynthesisAssets` have **no IntelliJ imports** and
are unit-tested directly. Keep it that way — colours and fonts arrive as a
`Theme`/`Tokens` record that `SynthesisBrowser` builds from
`EditorColorsScheme`, so the popup tracks the user's IDE theme.

## Verifying a UI change

Source-level assertions cannot see a rendering defect. `assertTrue(css.contains(
"overflow-wrap:anywhere"))` passes while identifiers split mid-token on screen.

For any change to `SynthesisHtmlRenderer.css()` or the theme:

1. Write the tests (they pin the contract, not the appearance) — `./gradlew test`.
2. Generate the **real** `toDocument()` output with a throwaway `Dump` class on
   `build/classes/java/main:build/resources/main:<commonmark jars>`.
3. Serve it and load it in Playwright. `file:` URLs are blocked, and a port may
   already be taken by another session — check the served bytes are yours
   before trusting the page.
4. Assert **computed styles and rects**, not source text: `getComputedStyle`
   for fonts and colours, `scrollWidth > clientWidth` for clipping,
   `getClientRects().length` for a wrapped inline element.
5. Screenshot and look at it.

Chromium gotcha that has bitten this file: its UA stylesheet declares
`pre{font-family:monospace}` **directly on the element**, and a direct
declaration beats an inherited one — so a `font-family` set on `body` is
silently ignored inside `<pre>` and must be restated on `pre code`.
