// The one door every piece of code on the page is coloured through.
//
// The colouring itself is Shiki (static/shiki.min.js, built by
// tools/shiki/build.mjs): VS Code's TextMate grammars on the Oniguruma regex
// engine, the industry-standard way to make code in a browser look the way it
// does in an editor. Nothing here changes a grammar or a theme. This file only
// adapts Shiki's output to the page's surfaces:
//
//   rows()  — a run of lines as ONE piece of code, handed back one HTML string
//             per line, for the row-per-line panes (code anchors, explain).
//             Shiki tokenises line by line with the grammar's state carried
//             across, so a row inside a multi-line annotation or comment is
//             coloured as exactly that.
//   paint() — a whole block as one HTML string, for fenced code and pflow.
//
// Pane rows carry every pane theme's colour at once as CSS variables
// (--shiki-midnight, --shiki-daylight, …) — Shiki's own multi-theme output —
// and style.css picks one by body[data-pane-theme]. Fences are GitHub Dark,
// the default pane theme, so code looks the same wherever it sits.
//
// Everything below is synchronous, and nothing waits for Shiki. The engine
// (shiki.min.js) loads off the page's critical path, and each grammar loads
// from shiki-langs/ the first time a piece of code asks for it. Until then
// rows() and paint() answer null — "show this plain" — and note the miss.
// When the engine, or a grammar some code missed, finishes loading, a
// `codepaint:ready` event goes out on document, and the page paints again
// whatever it showed plain (script.js's repaintCode). prepare() is the other
// way round: load what a document will ask for before rendering it, so a
// rewrite lands coloured rather than plain-then-coloured.
(function () {
  "use strict";

  // Pane theme (the reader's "Code theme" setting) → the Shiki theme that
  // paints it. The four are bundled by tools/shiki/build.mjs.
  // Only themes whose every token reads at 4.5:1 (WCAG AA) on their own
  // ground made the cut, used exactly as they ship; test_browser_explain.py
  // measures it. Tokyo Night, Solarized and VS Code Dark+ were dropped for
  // failing that (comments or tag brackets below 4.5:1).
  const PANE_THEMES = {
    daylight: "light-plus",                       // VS Code Light+
    midnight: "github-dark-default",              // GitHub Dark
    contrast: "github-light-high-contrast",       // GitHub Light High Contrast
    "contrast-dark": "github-dark-high-contrast", // GitHub Dark High Contrast
  };
  const FENCE_THEME = "github-dark-default";

  // A single line this long is a minified or generated file: tokenising it
  // stalls the tab. Shown plain instead.
  const MAX_LINE = 20000;

  // File names that are the language on their own.
  const BY_BASENAME = { dockerfile: "dockerfile", makefile: "makefile" };

  function shiki() {
    return window.Shiki || null;
  }

  // ── Loading ──────────────────────────────────────────────────────────────
  // Names asked for before the engine had loaded; sorted out once it has.
  const asked = new Set();
  // Code shown plain since the last `codepaint:ready`, for want of a grammar
  // (or of the engine) that is loading or about to.
  let missed = 0;
  let misses = 0;
  let inFlight = 0;
  let engine = null;   // Promise<highlighter|null>, once shiki.min.js has run

  function attach() {
    if (engine || !window.ShikiReady) return;
    engine = window.ShikiReady.then((h) => h, (e) => {
      console.error("highlighter failed to load", e);
      return null;
    });
    engine.then((h) => {
      if (!h) return;
      const names = [...asked];
      asked.clear();
      track(Promise.all(names.map(loadGrammar)));
    });
  }
  attach();
  // shiki.min.js may run before or after this file; it says when it has.
  if (typeof document !== "undefined") document.addEventListener("shiki:loaded", attach);

  function loadGrammar(n) {
    const langs = window.ShikiLangs;
    return langs && langs.has(n) ? langs.load(n) : Promise.resolve(false);
  }

  // When every load in flight has settled and some code was shown plain
  // meanwhile, say so once.
  function track(p) {
    inFlight++;
    p.catch(() => {}).then(() => {
      inFlight--;
      if (inFlight || !missed) return;
      missed = 0;
      if (typeof document !== "undefined") document.dispatchEvent(new CustomEvent("codepaint:ready"));
    });
  }

  // `n` was asked for and cannot be coloured yet: load it if it can be.
  function want(n) {
    const h = shiki();
    if (!h) {
      asked.add(n);
      missed++;
      misses++;
      attach();
      return;
    }
    const langs = window.ShikiLangs;
    // No grammar anywhere, or one that already failed to load: plain for
    // good, and not a miss — a miss is a promise to colour it later, and
    // re-asking a dead grammar on every repaint would never settle.
    if (!langs || !langs.has(n) || dead.has(n)) return;
    missed++;
    misses++;
    track(langs.load(n).then((ok) => { if (!ok) dead.add(n); }));
  }
  const dead = new Set();

  // A language name or alias ("java", "kt", "gradle") → a name Shiki answers
  // to, or null when it cannot colour it (yet — see want()).
  function language(name) {
    const n = String(name || "").trim().toLowerCase();
    if (!n) return null;
    const h = shiki();
    if (h) {
      try {
        h.getLanguage(n);
        return n;
      } catch (e) { /* not loaded, or no such grammar */ }
    }
    want(n);
    return null;
  }

  function fileLanguage(path) {
    const base = String(path || "").split(/[\\/]/).pop().toLowerCase();
    if (!base) return null;
    if (BY_BASENAME[base]) return BY_BASENAME[base];
    const m = /\.([a-z0-9_+-]+)$/.exec(base);
    return m ? m[1] : null;
  }

  function languageForFile(path) {
    const n = fileLanguage(path);
    return n ? language(n) : null;
  }

  // Every language a document (or anything JSON-shaped) will ask for: fence
  // tags, explicit `lang`s, the extensions of anchored files, and Python for
  // a flowchart's pflow source. A superset is harmless — a name with no
  // grammar loads nothing.
  function namesIn(doc) {
    const s = JSON.stringify(doc || {});
    const out = new Set();
    for (const m of s.matchAll(/(?:```|~~~)[ \t]*([\w#+.-]+)/g)) out.add(m[1].toLowerCase());
    for (const m of s.matchAll(/"lang":"([^"\\]+)"/g)) out.add(m[1].toLowerCase());
    for (const m of s.matchAll(/"file":"([^"\\]+)"/g)) {
      const n = fileLanguage(m[1]);
      if (n) out.add(n);
    }
    if (/"source":"/.test(s)) out.add("python");
    return [...out];
  }

  // Resolves once the engine and every grammar `doc` names have loaded, or
  // failed to. Never rejects.
  function prepare(doc) {
    const names = namesIn(doc);
    attach();
    if (!engine) {
      names.forEach((n) => asked.add(n));
      return new Promise((resolve) => {
        const go = () => { document.removeEventListener("shiki:loaded", go); resolve(prepare(doc)); };
        document.addEventListener("shiki:loaded", go);
      });
    }
    return engine.then((h) => h && Promise.all(names.map(loadGrammar))).then(() => undefined, () => undefined);
  }

  function escape(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function styleOf(obj) {
    return Object.entries(obj).map(([k, v]) => `${k}:${v}`).join(";");
  }

  // Shiki's font-style bit field → CSS.
  function fontCss(fs) {
    const out = [];
    if (fs & 1) out.push("font-style:italic");
    if (fs & 2) out.push("font-weight:700");
    if (fs & 4) out.push("text-decoration:underline");
    return out;
  }

  function tokenise(code, lang, opts) {
    const h = shiki();
    if (!h || !lang) return null;
    if (code.split("\n").some((l) => l.length > MAX_LINE)) return null;
    try {
      return h.codeToTokens(code, Object.assign({ lang }, opts)).tokens;
    } catch (e) {
      return null;
    }
  }

  // `wrap(token, html)` lets pflow mark its own tags; everything else passes null.
  function rowHtml(line, style, wrap) {
    return line.map((t) => {
      const text = escape(t.content);
      const inner = wrap ? wrap(t, text) : text;
      return `<span class="sk" style="${style(t)}">${inner}</span>`;
    }).join("");
  }

  // Lines of one piece of code → one HTML string per line, every pane theme's
  // colour carried as a CSS variable. null means "show these lines plain":
  // no grammar for the language, or a runaway line.
  function rows(lines, opts) {
    const o = opts || {};
    const lang = language(o.lang) || languageForFile(o.file);
    const tokens = tokenise(lines.join("\n"), lang, { themes: PANE_THEMES, defaultColor: false });
    if (!tokens || tokens.length !== lines.length) return null;
    return tokens.map((line) => rowHtml(line, (t) => styleOf(t.htmlStyle || {}), null));
  }

  // A whole block in the fence theme → HTML (lines joined by "\n"), or null.
  function paint(text, opts) {
    const o = opts || {};
    const lang = language(o.lang) || languageForFile(o.file);
    const tokens = tokenise(String(text == null ? "" : text), lang, { theme: FENCE_THEME });
    if (!tokens) return null;
    return tokens.map((line) => rowHtml(
      line, (t) => [`color:${t.color}`, ...fontCss(t.fontStyle || 0)].join(";"), o.wrap || null,
    )).join("\n");
  }

  // Cut HTML whose spans may straddle newlines into one balanced string per
  // line. paint()'s own output never straddles, but the pflow pane still cuts
  // what it is handed.
  function splitRows(html) {
    const out = [];
    const open = [];
    for (const raw of String(html).split("\n")) {
      const prefix = open.join("");
      const tags = raw.match(/<span[^>]*>|<\/span>/g) || [];
      for (const tag of tags) {
        if (tag === "</span>") open.pop();
        else open.push(tag);
      }
      out.push(prefix + raw + "</span>".repeat(open.length));
    }
    return out;
  }

  window.CodePaint = {
    rows, paint, splitRows, language, languageForFile, prepare, PANE_THEMES, FENCE_THEME,
    // How many times code has been shown plain for want of a grammar that
    // loads; a renderer compares it before and after to know it missed.
    misses: () => misses,
    // Whether code on the page is still waiting to be coloured: something
    // missed and its `codepaint:ready` (and so the repaint) has not run yet.
    // A page that has rendered and says false shows its code as it will stay.
    pending: () => missed > 0 || inFlight > 0,
  };
})();
