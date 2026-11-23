// Builds the vendored highlighter: skills/annotate/static/shiki.min.js and
// the grammars beside it in skills/annotate/static/shiki-langs/.
//
// Shiki is the highlighter VS Code's grammars run in: TextMate grammars on the
// Oniguruma regex engine, which is what makes its Java look like an editor's
// and not like a guess. It is bundled here into offline files — the daemon
// serves the page from this machine and the page must not reach for a CDN.
// Nothing in the bundle is modified: the languages and themes are Shiki's own,
// imported by name.
//
//   cd tools/shiki && npm ci && npm run build
//
// Two outputs, because a page needs the engine and the themes at once but only
// the grammars its code is written in:
//
//   shiki.min.js   — the engine (Oniguruma, as WebAssembly), the four themes,
//                    and an index of every language name to the file that
//                    colours it. Loads off the page's critical path: code is
//                    shown plain first and coloured when this is ready.
//   shiki-langs/   — one ES module per grammar, imported the first time the
//                    page meets that language. A grammar that embeds others
//                    (html embeds javascript and css) shares them through
//                    chunk-*.js rather than carrying its own copies.
//
// All 40 grammars used to be inlined into shiki.min.js: 3.2 MB the page
// parsed before it showed any code, though a document rarely holds more than
// three languages.
//
// The first line of shiki.min.js is a hash of this file and its package pins;
// skills/annotate/tests/test_shiki_bundle_fresh.py recomputes it, so a change
// here without a rebuild fails there.
//
// It also writes static/code-languages.json — every language name and alias
// the bundle answers to — which explain.py reads to refuse a `spec.lang` the
// page cannot colour.
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const STATIC = join(here, "..", "..", "skills", "annotate", "static");
const LANG_DIR = "shiki-langs";
const require = createRequire(import.meta.url);

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

// The hash the freshness test recomputes: this file, then the package pins.
function sourceHash() {
  const h = createHash("sha256");
  for (const f of ["build.mjs", "package.json", "package-lock.json"]) h.update(readFileSync(join(here, f)));
  return h.digest("hex");
}

// Every grammar module a listed language needs, its embedded languages
// included (ruby embeds lua, cpp embeds glsl, ...), each colourable on its
// own exactly as it was when it rode inside its host. name → module id, from
// each module's own grammar (the last entry of its default export).
async function grammarIndex() {
  const modules = new Set();
  const index = {};
  const queue = [...LANGS];
  while (queue.length) {
    const id = queue.shift();
    if (modules.has(id)) continue;
    modules.add(id);
    const grammars = (await import(`@shikijs/langs/${id}`)).default;
    const main = grammars[grammars.length - 1];
    for (const n of [main.name, ...(main.aliases || [])]) {
      const key = String(n).toLowerCase();
      if (!(key in index)) index[key] = id;
    }
    for (const g of grammars) {
      if (modules.has(g.name)) continue;
      try { require.resolve(`@shikijs/langs/${g.name}`); queue.push(g.name); }
      catch (_) { /* a grammar with no module of its own stays inside its host */ }
    }
  }
  for (const [alias, target] of Object.entries(LANG_ALIAS)) index[alias] = index[target];
  return { modules: [...modules].sort(), index };
}

const { modules, index } = await grammarIndex();
const version = JSON.parse(readFileSync(require.resolve("shiki/package.json"), "utf8")).version;
const hash = sourceHash();

// ── the grammars, one module each ────────────────────────────────────────
const langOut = join(STATIC, LANG_DIR);
if (existsSync(langOut)) rmSync(langOut, { recursive: true });
await build({
  entryPoints: modules.map((id) => ({ in: `lang:${id}`, out: id })),
  plugins: [{
    name: "lang-entries",
    setup(b) {
      b.onResolve({ filter: /^lang:/ }, (a) => ({ path: a.path.slice(5), namespace: "lang" }));
      b.onLoad({ filter: /.*/, namespace: "lang" }, (a) => ({
        contents: `export { default } from "@shikijs/langs/${a.path}";`, resolveDir: here, loader: "js",
      }));
    },
  }],
  bundle: true, format: "esm", splitting: true, minify: true, legalComments: "none",
  outdir: langOut, chunkNames: "chunk-[hash]",
  banner: { js: `/* Shiki ${version} grammar (MIT). Built by tools/shiki/build.mjs; do not edit. */` },
});

// ── the engine, the themes and the index ──────────────────────────────────
const entry = [
  `import { createHighlighterCore } from "shiki/core";`,
  `import { createOnigurumaEngine } from "shiki/engine/oniguruma";`,
  ...THEMES.map((t, i) => `import t${i} from "@shikijs/themes/${t}";`),
  `const INDEX = ${JSON.stringify(index)};`,
  // Where the grammars are: beside this file. A test (no document) says so itself.
  `const HERE = (typeof document !== "undefined" && document.currentScript && document.currentScript.src) || "";`,
  `const loading = new Map();`,
  `window.ShikiReady = createHighlighterCore({`,
  `  langs: [],`,
  `  themes: [${THEMES.map((_, i) => `t${i}`).join(",")}],`,
  `  langAlias: ${JSON.stringify(LANG_ALIAS)},`,
  `  engine: createOnigurumaEngine(import("shiki/wasm")),`,
  `}).then((h) => (window.Shiki = h));`,
  // name → Promise<boolean>: the grammar that colours `name` is loaded (true),
  // or there is none, or it failed to load (false — retried on the next ask).
  `window.ShikiLangs = {`,
  `  has: (name) => Object.prototype.hasOwnProperty.call(INDEX, name),`,
  `  load(name) {`,
  `    const id = INDEX[name];`,
  `    if (!id) return Promise.resolve(false);`,
  `    if (!loading.has(id)) {`,
  `      const base = window.ShikiBase || new URL("${LANG_DIR}/", HERE).href;`,
  `      const load = window.ShikiImport || ((url) => import(url));`,
  `      loading.set(id, Promise.all([window.ShikiReady, load(base + id + ".js")])`,
  `        .then(([h, m]) => h.loadLanguage(...m.default))`,
  `        .then(() => true, (e) => { loading.delete(id); console.error("grammar " + id + " failed to load", e); return false; }));`,
  `    }`,
  `    return loading.get(id);`,
  `  },`,
  `};`,
  `if (typeof document !== "undefined") document.dispatchEvent(new Event("shiki:loaded"));`,
].join("\n");

const out = join(STATIC, "shiki.min.js");
await build({
  stdin: { contents: entry, resolveDir: here, loader: "js" },
  bundle: true, format: "iife", minify: true, legalComments: "none",
  outfile: out,
  logOverride: { "unsupported-dynamic-import": "silent" },
  banner: { js: `/* annotate-shiki ${hash} */\n` +
                `/* Shiki ${version} (MIT, https://shiki.style) with its Oniguruma engine and ` +
                `${THEMES.length} themes; ${modules.length} grammars load from ${LANG_DIR}/ on demand. ` +
                `Built by tools/shiki/build.mjs; do not edit. */` },
});

// ── the language list, read back from the built files ────────────────────
globalThis.window = globalThis;
globalThis.ShikiBase = new URL(`${LANG_DIR}/`, `file://${STATIC}/`).href;
new Function(readFileSync(out, "utf8"))();
const h = await window.ShikiReady;
const results = await Promise.all(Object.keys(index).map((n) => window.ShikiLangs.load(n)));
if (results.some((ok) => !ok)) throw new Error("a grammar failed to load from the built files");
const names = new Set();
for (const n of [...h.getLoadedLanguages(), ...Object.keys(LANG_ALIAS)]) {
  h.getLanguage(n); // throws if the bundle cannot actually colour it
  names.add(String(n).toLowerCase());
}
for (const n of names) {
  if (!window.ShikiLangs.has(n)) throw new Error(`${n} is colourable but the index cannot load it`);
}
writeFileSync(join(STATIC, "code-languages.json"), JSON.stringify({
  _comment: "Every language name and alias static/shiki.min.js can colour, plus code-paint.js's " +
            "extension aliases. Written by tools/shiki/build.mjs; explain.py refuses a spec.lang not listed here.",
  languages: [...names].sort(),
}, null, 1) + "\n");
console.log(`shiki ${version}: ${modules.length} grammar modules, ${names.size} names, ${THEMES.length} themes -> ${out}`);
