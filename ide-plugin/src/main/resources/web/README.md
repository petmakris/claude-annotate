# Bundled web assets

`highlight.min.js` — Highlight.js v11.11.1 "common" build, fetched from
cdnjs, BSD-3-Clause (the licence banner is retained at the top of the file).
Registers 36 languages including java, kotlin, python, yaml, json, xml,
bash, sql, typescript and diff.

Bundled rather than loaded from a CDN so the synthesis popup highlights code
with no network access. Read by `SynthesisAssets` and inlined into the JCEF
document by `SynthesisHtmlRenderer.toDocument`.

To upgrade: replace the file, then re-run `SynthesisAssetsTest`.
