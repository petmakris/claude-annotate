#!/usr/bin/env node
/*
 * Behavioural tests for static/code-paint.js — the one door every piece of
 * code on the page is coloured through — running the page's own vendored
 * Shiki bundle exactly as the page does.
 *
 * Uncoloured or wrongly coloured code reached the reader more than once, and
 * every browser test that could have seen it skips in CI (no playwright
 * there). This suite needs only node, so it runs on every push. It asserts
 * what a reader checks, not how the highlighter works inside: every string
 * literal is the same colour wherever it sits, a comment's second line is
 * still a comment, an annotation is not comment-coloured, and each language
 * we write resolves to a real grammar.
 *
 * Run:  node skills/annotate/tests/code_paint.test.cjs
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { pathToFileURL } = require("url");

const STATIC = path.join(__dirname, "..", "static");

// The page stylesheet: style.css and its parts, in the order entry.js links them.
function pageCss() {
  const entry = fs.readFileSync(path.join(STATIC, "entry.js"), "utf8");
  const list = /const CSS = \[([\s\S]*?)\];/.exec(entry)[1];
  return [...list.matchAll(/"([^"]+)"/g)].map((m) => m[1])
    .filter((f) => f === "style.css" || f.startsWith("style-"))
    .map((f) => fs.readFileSync(path.join(STATIC, f), "utf8")).join("\n");
}

// The page's files, run as the page runs them: the engine, then the door.
// Grammars are ES modules the bundle imports on demand; a vm context cannot
// import, so the bundle is handed node's own import and told where they are.
async function load() {
  const ctx = { console, URL, TextDecoder, TextEncoder, WebAssembly, setTimeout, clearTimeout,
                queueMicrotask, atob, btoa, Uint8Array, Promise };
  ctx.window = ctx;
  ctx.self = ctx;
  ctx.globalThis = ctx;
  ctx.ShikiBase = pathToFileURL(path.join(STATIC, "shiki-langs") + path.sep).href;
  ctx.ShikiImport = (url) => import(url);
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(STATIC, "shiki.min.js"), "utf8"), ctx, { filename: "shiki.min.js" });
  await ctx.ShikiReady;
  vm.runInContext(fs.readFileSync(path.join(STATIC, "code-paint.js"), "utf8"), ctx, { filename: "code-paint.js" });
  return ctx;
}

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg); }

const unescape = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
// One row's HTML → [{text, style}] per token span.
function spans(row) {
  return [...row.matchAll(/<span class="sk" style="([^"]*)">([\s\S]*?)<\/span>/g)]
    .map((m) => ({ style: m[1], text: unescape(m[2].replace(/<[^>]+>/g, "")) }));
}
// The colour a pane theme gives a token.
function ink(tok, theme) {
  const m = new RegExp("--shiki-" + theme + ":([^;]+)").exec(tok.style);
  return m ? m[1].toLowerCase() : null;
}
// Colours of every non-blank token overlapping the given substring of a row.
function inksOf(row, needle, theme) {
  let pos = 0;
  const line = spans(row).map((t) => { const s = { ...t, from: pos }; pos += t.text.length; return s; });
  const full = line.map((t) => t.text).join("");
  const at = full.indexOf(needle);
  ok(at >= 0, `${JSON.stringify(needle)} not in ${JSON.stringify(full)}`);
  const out = new Set();
  for (const t of line) {
    if (t.from < at + needle.length && t.from + t.text.length > at && t.text.trim()) out.add(ink(t, theme));
  }
  return [...out];
}

const CORPUS = [
  { lang: "java", code:
`@IncludeWhen("proposal.report.consolidated-allocations-enabled")
@Schema(title = "Aggregated Allocations", description = "Same as the normal "
    + "allocations, aggregated.",
    extensions = @Extension(name = "config", properties = @ExtensionProperty(name = "yml",
        value = "consolidated-allocations-enabled=true")))
Collection<Allocation> aggregatedAllocations,
/* gated out of the base spec
   until the flag is on */
public static final int LIMIT = 42;` },
  { lang: "kotlin", code: `// a price\nfun price(q: Int): String = "p=" + q` },
  { lang: "gradle", code: `dependencies {\n    implementation 'com.acme:wp-domain-model:1.0'\n}` },
  { lang: "typescript", code: `// load\nexport async function load(id: string) { return get("/c/" + id); }` },
  { lang: "tsx", code: `const A = () => <div className="x">{n}</div>;` },
  { lang: "python", code: `# fetch\ndef load(sid: str) -> dict:\n    return get(f"/s/{sid}")` },
  { lang: "yaml", code: `# reporting\nproposal:\n  enabled: "true"` },
  { lang: "sql", code: `SELECT id FROM portfolio WHERE name = 'x';` },
  { lang: "bash", code: `# build\necho "done" && cd /tmp` },
  { lang: "json", code: `{"a": "b", "n": 1}` },
  { lang: "xml", code: `<dependency scope="test"><id>x</id></dependency>` },
  { lang: "handlebars", code: `<div>{{#if proposal}}{{proposal.name}}{{/if}}</div>` },
  { lang: "properties", code: `proposal.report.enabled=true` },
  { lang: "dockerfile", code: `FROM eclipse-temurin:21\nRUN ./gradlew build` },
];

(async () => {
  const ctx = await load();
  const P = ctx.CodePaint;
  const THEMES = Object.keys(P.PANE_THEMES);

  // Before anything else asks for it: a grammar that has not loaded yet is
  // shown plain, counted as a miss, and coloured once it has.
  {
    const before = P.misses();
    const first = P.rows(["fn main() {}"], { lang: "rust" });
    test("a grammar not loaded yet is shown plain, and the miss is counted", () => {
      ok(first === null, "rust was coloured before its grammar loaded");
      ok(P.misses() === before + 1, `misses ${before} -> ${P.misses()}`);
    });
    test("code waiting on a grammar is pending", () => ok(P.pending(), "pending() is false mid-load"));
    await ctx.ShikiLangs.load("rust");
    await new Promise((r) => setTimeout(r, 0));
    test("nothing is pending once the grammar has loaded", () => ok(!P.pending(), "pending() still true"));
    test("the same code is coloured once its grammar has loaded", () => {
      const rows = P.rows(["fn main() {}"], { lang: "rust" });
      ok(rows && spans(rows[0]).length > 1, "rust still plain after its grammar loaded");
    });
    test("a language with no grammar anywhere is not a miss", () => {
      const m = P.misses();
      ok(P.rows(["x"], { lang: "cobol-ish" }) === null && P.misses() === m, "an unknown language counted as a miss");
    });
  }

  // prepare() loads what a document names: fence tags, langs, anchored files.
  await P.prepare({ blocks: [
    { markdown: "```go\nfunc f() {}\n```" },
    { code: [{ file: "src/Main.kt", line: 1 }] },
    { spec: { lang: "swift" } },
  ] });
  test("prepare() loads the grammars a document names", () => {
    for (const n of ["go", "kotlin", "swift"]) ok(ctx.Shiki.getLoadedLanguages().includes(n), `${n} not loaded`);
  });

  // Everything the suite below colours, loaded the way the page loads it.
  const listedNames = JSON.parse(fs.readFileSync(path.join(STATIC, "code-languages.json"), "utf8")).languages;
  const loads = await Promise.all(listedNames.map((n) => ctx.ShikiLangs.load(n)));
  test("every listed language has a grammar file that loads", () => {
    const failed = listedNames.filter((_, i) => !loads[i]);
    ok(!failed.length, "failed to load: " + failed.join(", "));
  });

  test("every pane theme and the fence theme are bundled", () => {
    const loaded = ctx.Shiki.getLoadedThemes();
    for (const t of [...Object.values(P.PANE_THEMES), P.FENCE_THEME])
      ok(loaded.includes(t), `${t} is not in shiki.min.js (loaded: ${loaded})`);
  });

  for (const c of CORPUS) {
    test(`${c.lang}: has a grammar`, () => ok(P.language(c.lang), `no grammar for ${c.lang}`));
    test(`${c.lang}: rows() gives one balanced row per line that reads back as the input`, () => {
      const lines = c.code.split("\n");
      const rows = P.rows(lines, { lang: c.lang });
      ok(rows && rows.length === lines.length, "row count differs");
      rows.forEach((r, i) => {
        ok(spans(r).map((t) => t.text).join("") === lines[i], `row ${i + 1}: ${r}`);
        ok((r.match(/<span/g) || []).length === (r.match(/<\/span>/g) || []).length, `row ${i + 1} unbalanced`);
      });
    });
    test(`${c.lang}: coloured in more than one ink in every pane theme`, () => {
      const rows = P.rows(c.code.split("\n"), { lang: c.lang });
      for (const th of THEMES) {
        const inks = new Set(rows.flatMap((r) => spans(r).map((t) => ink(t, th))));
        ok(!inks.has(null), `${th}: a token has no colour`);
        ok(inks.size > 1, `${th}: one colour for everything — not highlighted`);
      }
    });
  }

  const JAVA = CORPUS[0].code.split("\n");
  const JROWS = P.rows(JAVA, { lang: "java" });

  test("java: every string literal is the same colour wherever it sits", () => {
    for (const th of THEMES) {
      const inks = new Set();
      JAVA.slice(0, 5).forEach((line, i) => {
        // The text between the quotes: a theme may colour the quote marks
        // themselves as punctuation (Tokyo Night does), which is its choice.
        for (const lit of line.match(/"[^"]+"/g) || []) inksOf(JROWS[i], lit.slice(1, -1), th).forEach((x) => inks.add(x));
      });
      ok(inks.size === 1, `${th}: string literals come out in ${[...inks]}`);
      const ident = inksOf(JROWS[5], "aggregatedAllocations", th);
      ok(!ident.some((x) => inks.has(x)), `${th}: an identifier is string-coloured`);
    }
  });

  test("java: a block comment's second line is still the comment's colour", () => {
    for (const th of THEMES) {
      const first = inksOf(JROWS[6], "gated out of the base spec", th);
      const second = inksOf(JROWS[7], "until the flag is on", th);
      ok(first.length === 1 && JSON.stringify(first) === JSON.stringify(second), `${th}: ${first} vs ${second}`);
      ok(!inksOf(JROWS[8], "LIMIT", th).includes(first[0]), `${th}: the code after the comment is comment-coloured`);
    }
  });

  test("java: an annotation is not comment-coloured", () => {
    for (const th of THEMES) {
      const comment = inksOf(JROWS[6], "gated out", th)[0];
      ok(!inksOf(JROWS[0], "IncludeWhen", th).includes(comment), `${th}: @IncludeWhen is in comment ink`);
    }
  });

  test("fences are one Tokyo Night block with a colour on every token", () => {
    const html = P.paint(CORPUS[0].code, { lang: "java" });
    ok(html && html.split("\n").length === JAVA.length, "fence row count");
    ok(!/style=""/.test(html) && /color:#/i.test(html), html.slice(0, 200));
  });

  test("a language resolves from the file path a code anchor has", () => {
    const cases = { "a/b/ProposalData.java": "java", "domain-models/build.gradle": "gradle",
      "x/content.handlebars": "handlebars", "x/y.hbs": "hbs", "app.yml": "yml",
      "application.properties": "properties", "ops/Dockerfile": "dockerfile",
      "src/Main.kt": "kt", "web/app.tsx": "tsx", "Makefile": "makefile" };
    for (const [f, want] of Object.entries(cases))
      ok(P.languageForFile(f) === want, `${f} → ${P.languageForFile(f)}, want ${want}`);
  });

  test("a language with no grammar is shown plain, never guessed", () => {
    ok(P.rows(["x = 1"], { lang: "cobol-ish" }) === null, "rows guessed");
    ok(P.paint("x = 1", { lang: "cobol-ish" }) === null, "paint guessed");
    ok(P.paint("x = 1", {}) === null, "an untagged block was guessed");
  });

  test("a runaway minified line is left plain rather than hanging the tab", () => {
    ok(P.paint("var a=1;".repeat(4000), { lang: "javascript" }) === null, "was highlighted");
  });

  test("code-languages.json lists exactly the names the bundle colours", () => {
    const listed = JSON.parse(fs.readFileSync(path.join(STATIC, "code-languages.json"), "utf8")).languages;
    for (const n of listed) ok(P.language(n), `listed but not colourable: ${n}`);
    for (const n of ctx.Shiki.getLoadedLanguages())
      ok(listed.includes(String(n).toLowerCase()), `colourable but not listed: ${n} — rebuild tools/shiki`);
  });

  test("the page stylesheet paints each pane theme from its own Shiki variable", () => {
    const css = pageCss();
    for (const th of THEMES)
      ok(new RegExp("color:\\s*var\\(--shiki-" + th + "\\)").test(css), `no rule reads --shiki-${th}`);
  });

  // The accessibility floor, in CI: every token of every corpus snippet, in
  // every pane theme, at 4.5:1 on that theme's ground AND on its anchor /
  // current-row wash — both read from style.css, so a new theme or a new
  // wash is measured the day it lands.
  test("every token reads at 4.5:1 on its theme's ground and wash (WCAG AA)", () => {
    const css = pageCss();
    const block = (sel) => {
      const i = css.indexOf(sel);
      ok(i >= 0, "no block " + sel);
      return css.slice(i, css.indexOf("\n}", i));
    };
    const v = (blk, name) => { const m = new RegExp("--" + name + ":\\s*(#[0-9a-fA-F]{6})").exec(blk); return m && m[1]; };
    const base = block(".codepane {\n  --cp-ground:");
    const lum = (hex) => { const c = hex.slice(1).match(/../g).map((x) => parseInt(x, 16) / 255)
      .map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
    const cr = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const bad = [];
    for (const th of THEMES) {
      const blk = th === "daylight" ? base : block(`body[data-pane-theme="${th}"] .codepane {`);
      const grounds = [v(blk, "cp-ground") || v(base, "cp-ground"), v(blk, "cp-anchor-bg") || v(base, "cp-anchor-bg")];
      for (const c of CORPUS) for (const r of P.rows(c.code.split("\n"), { lang: c.lang }))
        for (const t of spans(r)) {
          if (!t.text.trim()) continue;
          const i = ink(t, th).slice(0, 7);
          for (const g of grounds) if (cr(i, g) < 4.5)
            bad.push(`${th} ${c.lang} ${JSON.stringify(t.text)} ${i} on ${g}: ${cr(i, g).toFixed(2)}`);
        }
    }
    ok(!bad.length, [...new Set(bad)].slice(0, 12).join("\n         "));
  });

  process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
