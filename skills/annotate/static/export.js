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
    ".hover-actions",       // block control strip
    ".unit-strip",          // per-unit control strip
    ".unit-chip",           // a pinned comment's text, rendered in the prose
    ".unit-composer",       // an open per-unit comment box
    ".inline-comments",     // comment cards, mounted after each block
    ".card-diff-toggle",    // "what changed"
    ".diff-pane",           // ...and the diff it opens
    ".updating-overlay",    // the spinner on a block being rewritten
    ".card-chevron",        // folding is meaningless once nothing can fold
    ".attr-chip",           // "you asked" attribution
    ".section-pill",        // section number + version: revision history
    ".cp-widen",            // code-pane promote/narrow toggle: no JS in the export to run it
    ".cp-jump",             // jetbrains:// IDE link: an absolute author path,
                             // and dead on anyone else's machine besides
  ].join(", ");

  // Review state painted onto the document as attributes. Left in place, a
  // block someone marked "delete" reaches the reader struck through and
  // half-transparent, and a marked unit arrives with a coloured wash.
  const STATE_ATTRS = [
    "data-block-mark", "data-mark", "data-engaged-type", "data-card-focus",
    "data-visible", "data-engaged",
  ];

  // Neutralises affordances that survive as pure CSS once their JS is gone.
  const EXPORT_CSS = `
/* ── exported document ─────────────────────────────────────────────────── */
body.exported { padding-bottom: 40px; }
body.exported main.prose [data-block-id]:hover { background: none; }
body.exported section.block .card-head { cursor: default; }
body.exported .sub-unit:hover { background: none; }
body.exported .sub-unit { border-radius: 0; }
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

  // Drop repeated `url(...)` entries within one `src:` list. The Bricolage
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

    // style.css widens --content-max to 1180px via body[data-has-code="1"].
    // Each code-bearing section keeps its own data-has-code attribute
    // through the clone (it's a real DOM attribute inside main.prose), so
    // its card still splits 46/54 -- but without this flag on <body> too,
    // it splits into the NARROW 1040px column instead of the wide one.
    const hasCode = document.body.dataset.hasCode === "1"
      ? ' data-has-code="1"' : "";

    // The reader's view preferences are how the author laid the document out,
    // so they travel with it. There is no JS in an export to re-derive them
    // and no control to change them, which is exactly why they have to be
    // baked onto <body> rather than left to the default.
    const view = ["width", "codeLayout", "paneTheme"].map((k) => {
      const v = document.body.dataset[k];
      if (!v) return "";
      const attr = k === "codeLayout" ? "data-code-layout"
        : k === "paneTheme" ? "data-pane-theme"
        : "data-" + k;
      return ` ${attr}="${esc(v)}"`;
    }).join("");

    const css = await embedFonts(dedupeFontSrc(await collectCss()));
    return (
      "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n" +
      '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
      "<title>" + esc(title) + "</title>\n" +
      "<style>\n" + css + "\n" + EXPORT_CSS + "</style>\n" +
      '</head>\n<body class="exported"' + hasCode + view + '>\n' +
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
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Preparing…";
      try {
        save(await buildDocument());
        btn.textContent = "Saved ✓";
      } catch (e) {
        btn.textContent = "Failed";
        if (window.console) console.error("export failed", e);
      }
      setTimeout(() => { btn.textContent = label; btn.disabled = false; }, 1600);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
