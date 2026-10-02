// Builds the vendored highlighter: skills/annotate/static/shiki.min.js.
//
// Shiki is the highlighter VS Code's grammars run in: TextMate grammars on the
// Oniguruma regex engine, which is what makes its Java look like an editor's
// and not like a guess. It is bundled once, here, into a single offline file
// — the daemon serves the page from this machine and the page must not reach
// for a CDN. Nothing in the bundle is modified: the languages and themes are
// Shiki's own, imported by name.
//
//   cd tools/shiki && npm ci && npm run build
//
// It also writes static/code-languages.json — every language name and alias
// the bundle answers to — which explain.py reads to refuse a `spec.lang` the
// page cannot colour.
import { build } from "esbuild";
import { writeFileSync, readFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const STATIC = join(here, "..", "..", "skills", "annotate", "static");

// What we put in front of a reader. Adding one is a line here and a rebuild.
export const LANGS = [
  "java", "kotlin", "groovy", "scala", "typescript", "tsx", "javascript", "jsx",
  "python", "yaml", "json", "jsonc", "sql", "shellscript", "shellsession", "xml",
  "html", "css", "scss", "handlebars", "properties", "dockerfile", "markdown",
  "diff", "go", "rust", "ini", "toml", "makefile", "c", "cpp", "csharp", "swift",
  "ruby", "php", "graphql", "proto", "hcl", "terraform", "log",
];
// File extensions no grammar claims, passed to Shiki's own `langAlias` option.
export const LANG_ALIAS = { gradle: "groovy", gvy: "groovy", props: "properties", conf: "ini", cfg: "ini" };

// One per pane theme; fences use github-dark-default too. The pane
// theme → Shiki theme table lives in code-paint.js.
export const THEMES = [
  "light-plus", "github-dark-default", "github-light-high-contrast", "github-dark-high-contrast",
];

const entry = [
  `import { createHighlighterCore } from "shiki/core";`,
  `import { createOnigurumaEngine } from "shiki/engine/oniguruma";`,
  ...LANGS.map((l, i) => `import l${i} from "@shikijs/langs/${l}";`),
  ...THEMES.map((t, i) => `import t${i} from "@shikijs/themes/${t}";`),
  `window.ShikiReady = createHighlighterCore({`,
  `  langs: [${LANGS.map((_, i) => `l${i}`).join(",")}].flat(),`,
  `  themes: [${THEMES.map((_, i) => `t${i}`).join(",")}],`,
  `  langAlias: ${JSON.stringify(LANG_ALIAS)},
  engine: createOnigurumaEngine(import("shiki/wasm")),`,
  `}).then((h) => (window.Shiki = h));`,
].join("\n");

const out = join(STATIC, "shiki.min.js");
const version = JSON.parse(readFileSync(createRequire(import.meta.url).resolve("shiki/package.json"), "utf8")).version;
await build({
  stdin: { contents: entry, resolveDir: here, loader: "js" },
  bundle: true, format: "iife", minify: true, legalComments: "none",
  outfile: out,
  banner: { js: `/* Shiki ${version} (MIT, https://shiki.style) with its Oniguruma engine, ` +
                `${LANGS.length} grammars and ${THEMES.length} themes. Built by tools/shiki/build.mjs; do not edit. */` },
});

// The language list, read back from the bundle itself rather than restated.
globalThis.window = globalThis;
new Function(readFileSync(out, "utf8"))();
const h = await window.ShikiReady;
const names = new Set();
for (const n of [...h.getLoadedLanguages(), ...Object.keys(LANG_ALIAS)]) {
  h.getLanguage(n); // throws if the bundle cannot actually colour it
  names.add(String(n).toLowerCase());
}
writeFileSync(join(STATIC, "code-languages.json"), JSON.stringify({
  _comment: "Every language name and alias static/shiki.min.js can colour, plus code-paint.js's " +
            "extension aliases. Written by tools/shiki/build.mjs; explain.py refuses a spec.lang not listed here.",
  languages: [...names].sort(),
}, null, 1) + "\n");
console.log(`shiki ${version}: ${LANGS.length} grammars, ${names.size} names, ${THEMES.length} themes -> ${out}`);
