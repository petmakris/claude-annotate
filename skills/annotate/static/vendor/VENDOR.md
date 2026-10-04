# Vendored files

Everything the annotate page loads that this repo did not write. The page is served
from the local daemon and must not reach for a CDN, so each is committed.

## In `static/vendor/`

| File | What it is | Version / source |
|---|---|---|
| `speech-sdk.min.js` | Azure Speech SDK for the browser, unmodified `microsoft.cognitiveservices.speech.sdk.bundle-min.js` (defines `window.SpeechSDK`, loaded lazily) | `microsoft-cognitiveservices-speech-sdk` 1.51.0. Copied from `distrib/browser/` of that package, taken from lomem's `node_modules` (`.pnpm/microsoft-cognitiveservices-speech-sdk@1.51.0/`). Licence: `speech-sdk.LICENSE`. To refresh, copy the same file from a newer release of the package. |
| `editor.min.js` | The Source editor (CodeMirror) bundle, `window.AnnotateEditor` | Built from `skills/annotate/editor/` (esbuild). First line carries a sha256 of the sources; a test checks it is fresh. Licence: `editor.LICENSE`. |
| `rich.min.js` | The rich (ProseMirror) editor bundle, `window.AnnotateRich` | Built from `skills/annotate/rich/` (esbuild). Same freshness check. Licence: `rich.LICENSE`. |

## In `static/`

| File | What it is | Version / source |
|---|---|---|
| `shiki.min.js` | Syntax highlighter (Shiki with the Oniguruma engine, a fixed set of grammars and themes) | Built by `tools/shiki/` (`cd tools/shiki && npm ci && npm run build`); versions are pinned in `tools/shiki/package.json`. The first line of the bundle states the version. Also writes `code-languages.json`. |
| `markdown-it.min.js` | markdown-it, MIT | 14.1.0 (from the banner). Upstream's browser build; the original download location was not recorded. |
| `fuse.min.js` | Fuse.js fuzzy search, Apache-2.0 | 7.0.0 (from the banner). Upstream's browser build; the original download location was not recorded. |
| `fonts/` | Bricolage Grotesque, Inter, JetBrains Mono, Monaspace Radon | Licences beside each font in `fonts/`. |
