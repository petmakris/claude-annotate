// annotate — Share: one click turns the document you are reading into a single
// standalone HTML file you can send to someone who cannot reach this machine.
//
// Everything happens in the browser, because everything needed is already on
// screen. The server renders sequence/flowchart/diagram blocks to inline SVG
// and markdown-it renders the prose here, so the live DOM IS the finished
// document — there is no second renderer to write and no way for the file to
// disagree with what the author was looking at when they pressed the button.
//
// The one rule that shapes the rest: interactive nodes are REMOVED, never
// hidden. `body.read-only` hides comment cards with CSS, so an export built on
// that mode would look right and still carry the full text of every private
// note inside a file handed to other people. Deleting the nodes is the only
// version of this that is safe to send.
(function () {
  // Comments, controls, and review scaffolding. See the note above on why
  // these are deleted rather than styled away.
  const STRIP = [
    ".cq-bar",              // a choice queue's navigation: a view, not content
    ".max-toggle",          // maximize: a view control with no JS in the export to run it
    ".max-overlay",         // ...and its overlay, if the export ran while one was open
    ".sel-menu",            // the selection menu, if one was open
    ".sel-composer",        // an open span comment box
    ".sel-chip",            // a span comment's text, rendered in the prose
    ".sp-card",             // a read-aloud card, if one was playing
    ".ed-bar",              // a section open in the editor: its bar...
    ".ed-host",             // ...and the editor, whose text is not yet saved
    ".ed-toast",            // an editing notice
    ".inline-comments",     // comment cards, mounted after each block
    ".card-diff-toggle",    // "what changed"
    ".diff-pane",           // ...and the diff it opens
    ".updating-overlay",    // the spinner on a block being rewritten
    ".card-chevron",        // folding is meaningless once nothing can fold
    ".attr-chip",           // "you asked" attribution
    ".section-pill",        // section number + version: revision history
    ".cp-jump",             // jetbrains:// IDE link: an absolute author path,
                             // and dead on anyone else's machine besides
    ".flow-flavours",       // flowchart layout-flavour buttons: no JS in the export to run them
    // The explain kind's walk. Its controls are dead without JS, and a file
    // frozen on step 2 would carry one note out of five with the rest painted
    // out — so the controls go and `data-walk` goes with them (see
    // STATE_ATTRS), which restores the pane with every label showing. The
    // static pane is always in the DOM; nothing here has to rebuild it.
    ".ex-bar",              // step controls
    ".ex-tray",             // the current note, restated by the ladder below it
    ".ex-at",               // the numbered pins, and the buttons inside them
  ].join(", ");

  // Review state painted onto the document as attributes. Left in place, a
  // block someone marked "delete" reaches the reader struck through and
  // half-transparent.
  const STATE_ATTRS = [
    "data-block-mark", "data-engaged-type", "data-card-focus",
    "data-visible", "data-engaged",
    // A whole section chosen in the selection menu: an accent outline.
    "data-sel-scope",
    // A section open in the editor hides its rendered text by this attribute.
    "data-editing",
    // The "your words" badge on a section the reader edited: review state,
    // not part of the document.
    "data-mine",
    // Every rule the walk uses to suppress a label or dim a row is scoped to
    // this attribute, so dropping it is the whole of undoing the walk.
    "data-walk",
  ];

  // Neutralises affordances that survive as pure CSS once their JS is gone.
  const EXPORT_CSS = `
/* ── exported document ─────────────────────────────────────────────────── */
body.exported { padding-bottom: 40px; }
body.exported main.prose [data-block-id]:hover { background: none; }
body.exported section.block .card-head { cursor: default; }
body.exported .export-header {
  max-width: var(--content-max); margin: 0 auto; padding: 26px 24px 0;
}
body.exported .export-title {
  font-size: 24px; font-weight: 700; letter-spacing: -0.022em;
  color: var(--text-strong); margin: 0;
}
body.exported .export-meta {
  font-size: 12px; color: var(--text-dim); margin-top: 6px;
}
body.exported .export-foot {
  max-width: var(--content-max); margin: 30px auto 0; padding: 0 24px;
  font-size: 11.5px; color: var(--text-dim);
  border-top: 1px solid var(--border); padding-top: 12px;
}
`;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function slug() {
    const m = (location.pathname || "").match(/\/s\/([^/]+)/);
    return (m && decodeURIComponent(m[1])) || "annotate";
  }

  // Every stylesheet the page actually loaded, read off the DOM rather than
  // hardcoded — a stylesheet added to the page shell later comes along without
  // anyone remembering to update this list.
  async function collectCss() {
    const links = Array.from(document.querySelectorAll('link[rel="stylesheet"]'));
    const parts = await Promise.all(links.map((l) =>
      fetch(l.href).then((r) => (r.ok ? r.text() : "")).catch(() => "")));
    return parts.join("\n");
  }

  // btoa() needs a binary string, and String.fromCharCode(...bytes) blows the
  // argument limit on a 400KB font — hence the chunking.
  async function fetchBase64(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      const bytes = new Uint8Array(await res.arrayBuffer());
      let bin = "";
      const CHUNK = 0x8000;
      for (let i = 0; i < bytes.length; i += CHUNK) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
      }
      return btoa(bin);
    } catch (_) {
      return null;
    }
  }

  // Drop repeated `url(...)` entries within one `src:` list. The Inter
  // face names the same file twice — once as `woff2-variations`, once as plain
  // `woff2` — which is a sensible fallback while it is a 12-byte path and a
  // 544KB mistake once it is a base64 payload.
  //
  // Runs BEFORE embedding, deliberately: at this point a url() holds a short
  // path with no commas in it, so splitting the list on commas is safe. After
  // embedding, every url() contains a data: URI whose base64 follows a comma,
  // and the same split would tear the payloads apart.
  function dedupeFontSrc(css) {
    return css.replace(/src\s*:\s*([^;]+);/g, (whole, list) => {
      const seen = new Set();
      const kept = list.split(",").map((s) => s.trim()).filter(Boolean)
        .filter((entry) => {
          const m = entry.match(/url\(\s*['"]?([^'")]+)['"]?\s*\)/);
          if (!m) return true;
          if (seen.has(m[1])) return false;
          seen.add(m[1]);
          return true;
        });
      return kept.length ? "src: " + kept.join(", ") + ";" : whole;
    });
  }

  // Inline every font the CSS references. Without this the file falls back to
  // system fonts the moment it is opened anywhere but here — which is the only
  // place it is ever going to be opened.
  // Which families this document actually renders in. An export carries its
  // fonts as base64 inside the file, so every @font-face that survives here is
  // weight every reader downloads — including readers of a document nobody
  // restyled. The prose is always Inter; the code font is the reader's
  // choice, so only that one of the code families is kept.
  // Keep in step with the body[data-code-font] rules in style.css and with
  // script.js's SETTINGS spec; "system" maps to null because a system stack
  // has no file to embed.
  const PROSE_FAMILY = "Inter";
  const CODE_FAMILIES = { monaspace: "Monaspace Radon", jetbrains: "JetBrains Mono",
                          system: null };

  // Diagram text is pinned to Monaspace Radon in visuals.css and does NOT
  // follow the reader's code font, because the SVG around it was measured for
  // that typeface: skills/_shared/visuals/text_metrics.py sizes every box,
  // lane and label from an advance width of 0.62em, which is Monaspace's.
  // JetBrains Mono is 0.6em, so a diagram rendered in it sits wrong inside
  // geometry computed for the other one.
  //
  // Which makes this the one family the reader's choice cannot speak for. It
  // stopped being the default code font, so the rule below would have dropped
  // its @font-face from every export — and a shared file's diagrams would
  // have fallen back to a system mono, inside boxes drawn for Monaspace. The
  // page looked perfect; only the exported copy was wrong.
  const DIAGRAM_SELECTOR = ".annotate-seq, .annotate-flow";

  function stripUnusedFontFaces(css) {
    const d = document.body.dataset;
    const used = new Set(
      [PROSE_FAMILY,
       CODE_FAMILIES[d.codeFont || "jetbrains"],
       document.querySelector(DIAGRAM_SELECTOR) ? "Monaspace Radon" : null,
      ].filter(Boolean));
    // Quotes optional: collectCss fetches the stylesheet's SOURCE, where these
    // are quoted today, but a one-word family is legal unquoted and a stricter
    // pattern would simply fail to match it — keeping the block, embedding the
    // font, and looking like it worked.
    return css.replace(/@font-face\s*\{[^}]*\}/g, (block) => {
      const m = /font-family:\s*['"]?([^'";]+?)['"]?\s*;/.exec(block);
      return m && !used.has(m[1].trim()) ? "" : block;
    });
  }

  async function embedFonts(css) {
    const urls = new Set();
    const re = /url\(\s*['"]?([^'")]+\.woff2)['"]?\s*\)/g;
    let m;
    while ((m = re.exec(css))) urls.add(m[1]);
    for (const url of urls) {
      const b64 = await fetchBase64(url);
      if (!b64) continue;
      css = css.split(url).join("data:font/woff2;base64," + b64);
    }
    return css;
  }

  function buildProse() {
    const src = document.querySelector("main.prose");
    if (!src) return "";
    const clone = src.cloneNode(true);

    clone.querySelectorAll(STRIP).forEach((n) => n.remove());

    // A search leaves <mark> wrappers behind AND hides every non-matching
    // section. Exporting mid-search must not quietly ship a document with
    // blocks missing, so both are undone rather than carried over.
    clone.querySelectorAll("mark.search-hit").forEach((m) => {
      m.replaceWith(document.createTextNode(m.textContent || ""));
    });
    clone.querySelectorAll(".search-hidden").forEach((n) => {
      n.classList.remove("search-hidden");
    });
    // A collapsed queue hides all but one question; the export carries them all.
    clone.querySelectorAll(".cq-hidden").forEach((n) => n.classList.remove("cq-hidden"));

    // The author's fold state is theirs, not the reader's — and with the
    // chevrons gone a folded block could never be opened again.
    clone.querySelectorAll("section.block.collapsed").forEach((s) => {
      s.classList.remove("collapsed");
    });

    clone.querySelectorAll("*").forEach((el) => {
      STATE_ATTRS.forEach((a) => el.removeAttribute(a));
    });

    // Cross-block links inside a flowchart are href="#<block-id>", which the
    // live page resolves in JS via [data-block-id]. No JS travels with the
    // file, so give each section a real id and let the browser do it.
    clone.querySelectorAll("section.block[data-block-id]").forEach((s) => {
      s.id = s.getAttribute("data-block-id");
    });

    return clone.outerHTML;
  }

  function buildHeader(title, responseId) {
    return (
      '<div class="export-header">' +
      '<h1 class="export-title">' + esc(title) + "</h1>" +
      '<div class="export-meta">' + esc(responseId) + "</div>" +
      "</div>"
    );
  }

  function buildFooter() {
    const when = new Date().toISOString().slice(0, 10);
    return '<div class="export-foot">Read-only export · ' + esc(when) + "</div>";
  }

  async function buildDocument() {
    const titleEl = document.querySelector(".header-text");
    const respEl = document.querySelector(".header-respid");
    const title = (titleEl && titleEl.textContent.trim()) || document.title || "annotate";
    const respId = (respEl && respEl.textContent.trim()) || "";

    // The reader's view preferences are how the author laid the document out,
    // so they travel with it. There is no JS in an export to re-derive them
    // and no control to change them, which is exactly why they have to be
    // baked onto <body> rather than left to the default.
    const view = ["pageTheme", "width", "paneTheme",
                  "codeFont", "textSize"].map((k) => {
      const v = document.body.dataset[k];
      if (!v) return "";
      // dataset keys are camelCase and attributes are kebab: paneTheme is
      // data-pane-theme. This was a ternary naming the two exceptions by
      // hand, which silently emitted a camelCase `data-codeFont` once a third
      // key was added — an attribute no rule matches, so the export would
      // have quietly ignored the reader's font.
      const attr = "data-" + k.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
      return ` ${attr}="${esc(v)}"`;
    }).join("");

    const css = await embedFonts(stripUnusedFontFaces(dedupeFontSrc(await collectCss())));
    return (
      "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n" +
      '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
      "<title>" + esc(title) + "</title>\n" +
      "<style>\n" + css + "\n" + EXPORT_CSS + "</style>\n" +
      '</head>\n<body class="exported"' + view + '>\n' +
      buildHeader(title, respId) +
      buildProse() +
      buildFooter() +
      "\n</body>\n</html>\n"
    );
  }

  function save(html) {
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = slug() + ".html";
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Long enough for the download to have been handed off; revoking straight
    // away cancels it in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  function wire() {
    const btn = document.getElementById("export-btn");
    if (!btn) return;
    // As a bar button this element's whole content was the word "Share", so
    // writing its textContent was the same as writing its label. As a menu tile
    // it is an icon AND a label, and textContent would eat the icon. The slot
    // is optional so a caller that never adds one keeps today's behaviour.
    const label = btn.querySelector("[data-label]") || btn;
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      const original = label.textContent;
      btn.disabled = true;
      label.textContent = "Preparing…";
      try {
        save(await buildDocument());
        label.textContent = "Saved ✓";
      } catch (e) {
        label.textContent = "Failed";
        if (window.console) console.error("export failed", e);
      }
      setTimeout(() => { label.textContent = original; btn.disabled = false; }, 1600);
    });
  }

  window.AnnotateExport = Object.assign(window.AnnotateExport || {}, { buildProse });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
