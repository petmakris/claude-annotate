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
// Loaded after shiki.min.js, whose ready promise entry.js awaits before
// script.js runs, so everything below is synchronous by the time it is called.
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

  // A language name or alias ("java", "kt", "gradle") → a name Shiki answers
  // to, or null when the bundle has no grammar for it.
  function language(name) {
    const h = shiki();
    const n = String(name || "").trim().toLowerCase();
    if (!h || !n) return null;
    try {
      h.getLanguage(n);
      return n;
    } catch (e) {
      return null;
    }
  }

  function languageForFile(path) {
    const base = String(path || "").split(/[\\/]/).pop().toLowerCase();
    if (!base) return null;
    if (BY_BASENAME[base]) return language(BY_BASENAME[base]);
    const m = /\.([a-z0-9_+-]+)$/.exec(base);
    return m ? language(m[1]) : null;
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

  window.CodePaint = { rows, paint, splitRows, language, languageForFile, PANE_THEMES, FENCE_THEME };
})();
