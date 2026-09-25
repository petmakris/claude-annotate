/* claude-deck client.
 *
 * The deck loads in a SAME-ORIGIN iframe, so this page can reach into its
 * document and attach targets to real elements. Three harness behaviours are
 * neutralised on the way in — zoom-to-fit, page-number injection, and any
 * floating chrome it appends to <body> — by undoing them in the
 * frame's DOM after load. The deck FILE is never modified.
 */
(function () {
  "use strict";

  const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
  const SLIDE_W = 1280, SLIDE_H = 720;
  // The slide frame used to be a fixed 780px regardless of screen size, which
  // left most of a wide monitor empty. SCALE is now derived from the actual
  // viewport on load and on resize, so the frame grows to fill the space
  // available, capped at native resolution (SCALE 1) so it never upscales
  // past its own crispness.
  const MIN_FRAME_W = 480, MAX_FRAME_W = 1280, APP_PAD = 64;
  // Slide view keeps two thin bars — the header above, the slide strip below —
  // and gives everything between them to the slide, with this much air around it.
  const SINGLE_PAD = 8;
  let SCALE = 0.6094;

  function computeScale() {
    let availW = document.documentElement.clientWidth - APP_PAD;
    if (state.view === "slide") {
      availW = document.documentElement.clientWidth - 2 * SINGLE_PAD;
      const head = document.getElementById("deckhead");
      const strip = document.getElementById("deckstrip");
      const availH = window.innerHeight - (head ? head.offsetHeight : 32) -
                     (strip ? strip.offsetHeight : 40) - 2 * SINGLE_PAD;
      availW = Math.min(availW, availH * SLIDE_W / SLIDE_H);
    }
    const frameW = Math.max(MIN_FRAME_W, Math.min(MAX_FRAME_W, availW));
    SCALE = frameW / SLIDE_W;
    const app = document.getElementById("app");
    if (app) app.style.setProperty("--frame-w", Math.round(frameW) + "px");
    return frameW;
  }

  /* Resize the already-mounted frames in place rather than remounting them —
     remounting would reload every deck iframe on every resize tick. */
  function relayoutFrames() {
    computeScale();
    document.querySelectorAll(".slideframe").forEach(holder => {
      holder.style.width = Math.round(SLIDE_W * SCALE) + "px";
      holder.style.height = Math.round(SLIDE_H * SCALE) + "px";
      const f = holder.querySelector("iframe");
      if (f) f.style.transform = "scale(" + SCALE + ")";
    });
  }

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(relayoutFrames, 120);
  });

  // One frame per slide, so there is no single shared doc to hold onto.
  // `view` is the reader's own preference, so it lives in localStorage; the
  // slide they are on lives in the page's hash, so a reload keeps their place.
  function storedView() {
    try { return localStorage.getItem("claude-deck-view") === "slide" ? "slide" : "scroll"; }
    catch (_) { return "scroll"; }
  }
  const hashSlide = Number((location.hash.match(/^#slide-(\d+)$/) || [])[1]) || 1;
  const state = { model: null, modelVersion: null, base: BASE,
                  view: storedView(), current: hashSlide };
  window.ClaudeDeck = { state: state };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  const ICONS = {
    rows: '<rect x="3" y="3" width="18" height="7" rx="1"/><rect x="3" y="14" width="18" height="7" rx="1"/>',
    single: '<rect x="3" y="5" width="18" height="14" rx="1.5"/>',
    left: '<polyline points="15 18 9 12 15 6"/>',
    right: '<polyline points="9 18 15 12 9 6"/>',
    comment: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>' +
              '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    play: '<polygon points="6 4 20 12 6 20 6 4"/>',
  };
  /* A button or link carrying a stroke icon, with an optional short label. */
  function iconEl(tag, cls, icon, label, title) {
    const n = el(tag, cls);
    n.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      ICONS[icon] + "</svg>";
    if (label) n.appendChild(el("span", null, label));
    if (title) { n.title = title; n.setAttribute("aria-label", title); }
    return n;
  }

  async function fetchJSON(path) {
    const r = await fetch(BASE + path, { cache: "no-store" });
    if (!r.ok) throw new Error(path + " -> " + r.status);
    return r.json();
  }

  /* With the frame sandboxed the deck's own script never runs, so the three
     things it does — zoom-to-fit, page-number injection, floating chrome —
     never happen. This still undoes them, because a deck may carry an inline
     zoom or a hand-written .pg in the file itself, and because the frame is
     the only place it is safe to touch anything at all. The FILE is never
     modified. */
  function neutraliseHarness(doc) {
    const deck = doc.querySelector(".deck");
    if (deck) deck.style.zoom = "";
    doc.querySelectorAll(".slide .pg").forEach(n => n.remove());
    doc.querySelectorAll(".slide .num").forEach(n => { n.dataset.deckIgnore = "1"; });
    const style = doc.createElement("style");
    let css =
      ".deck{zoom:1 !important;gap:0 !important;display:block !important}" +
      ".slide{margin:0 !important;box-shadow:none !important}" +
      "body{padding:0 !important;margin:0 !important;background:#fff !important}";
    // Only hide the deck's siblings when there IS a .deck wrapper. Some decks
    // put their slides straight in <body>; hiding everything that is not
    // .deck would then hide the slides themselves and render every frame
    // blank while the model still reported content.
    if (deck && deck.parentElement === doc.body) {
      css += "body > *:not(.deck){display:none !important}";
    } else {
      css += "body > *:not(.slide):not(style):not(script){display:none !important}";
    }
    style.textContent = css;
    doc.head.appendChild(style);
  }

  /* Each slide is shown by loading the whole deck document into its own frame
     and hiding every other slide. Cheaper and far more faithful than trying
     to re-render markup we do not own. */
  function mountSlide(wrap, index) {
    const holder = el("div", "slideframe");
    holder.style.width = Math.round(SLIDE_W * SCALE) + "px";
    holder.style.height = Math.round(SLIDE_H * SCALE) + "px";

    const f = document.createElement("iframe");
    // The deck is a file the user owns, and it carries its own <script>. Same
    // origin without this attribute would let that script read the write
    // token out of sessionStorage and call the owner-only APIs. allow-scripts
    // is deliberately absent: this page already undoes everything the deck's
    // harness does, so nothing of value is lost by never running it.
    f.setAttribute("sandbox", "allow-same-origin");
    f.width = SLIDE_W;
    f.height = SLIDE_H;
    f.style.width = SLIDE_W + "px";
    f.style.height = SLIDE_H + "px";
    f.style.transform = "scale(" + SCALE + ")";
    f.style.transformOrigin = "0 0";
    f.src = BASE + "assets/content.html?v=" + state.modelVersion + "#slide-" + index;
    f.addEventListener("load", () => {
      const doc = f.contentDocument;
      if (!doc) return;
      neutraliseHarness(doc);
      slideSections(doc).forEach((s, i) => {
        s.style.display = (i === index - 1) ? "" : "none";
      });
      attachTargets(doc, index, wrap);
      doc.addEventListener("keydown", onNavKey);
      try { renderChecks(wrap, doc, index); }
      catch (ex) { console.warn("deck checks failed on slide " + index, ex); }
      wrap.dispatchEvent(new CustomEvent("deck:slide-ready", { detail: { doc, index } }));
    });
    holder.appendChild(f);
    const body = wrap.querySelector(".slidebody");
    const pending = body.querySelector(".slideframe-pending");
    if (pending) body.replaceChild(holder, pending);
    else body.insertBefore(holder, body.firstChild);
    return f;
  }

  /* ------------------------------------------------------------------ *
   * Targets
   * ------------------------------------------------------------------ */

  const FRAME_CSS = `
    [data-deck-target]{outline:1px dashed transparent;outline-offset:2px;cursor:pointer;
      transition:outline-color .1s,background-color .1s}
    [data-deck-target]:hover{outline-color:#9BC9F5;background-color:rgba(0,113,227,.06)}
    [data-deck-target].deck-selected{outline:1.5px solid #0071E3;
      background-color:rgba(0,113,227,.07)}
    [data-deck-target].deck-has{outline:1.5px solid #E9C79A;
      background-color:rgba(184,92,46,.06)}
    [data-deck-target].deck-working{outline:1.5px solid #B85C2E;
      background-color:rgba(184,92,46,.09)}
  `;

  const selectListeners = [];
  window.ClaudeDeck.onSelect = fn => selectListeners.push(fn);

  /* The slide's direct children whose FIRST class is `cls` — exactly what the
     model addresses. querySelectorAll would also return nested matches and a
     block whose class is second in the list, and then every index after the
     stray one would point at the wrong element. */
  /* Top-level slides only. The model does not treat a section.slide nested
     inside another as a slide, so counting them here would put every later
     slide one out — frame N would render the nested section and slide N's
     targets would resolve against the wrong document node. */
  function slideSections(doc) {
    return [...doc.querySelectorAll(".slide")].filter(
      n => !(n.parentElement && n.parentElement.closest(".slide")));
  }

  function slideBlocks(slide, cls) {
    return [...slide.children].filter(
      n => n.classList && n.classList[0] === cls);
  }

  /* The <p>/<li> the model counts inside a block: outermost only. A <p>
     nested in an <li> is not a target, so it must not consume an index
     either — CSS nth-of-type would count it and shift everything after. */
  function leafNodes(block, tag) {
    return [...block.querySelectorAll("p, li")]
      .filter(n => {
        const outer = n.parentElement && n.parentElement.closest("p, li");
        // `block.contains(block)` is true, so a block that is itself a <p> or
        // an <li> would otherwise filter out every leaf inside it.
        return !(outer && outer !== block && block.contains(outer));
      })
      .filter(n => n.tagName.toLowerCase() === tag);
  }

  /* Turn a model element back into a live node inside the frame. Driven by
     block_ord/leaf_n from the model, never by running `path` as a selector:
     the two disagree on nesting, and a disagreement means the browser
     highlights one element while Claude edits another. */
  function resolveElement(doc, slideIndex, element) {
    const slide = slideSections(doc)[slideIndex - 1];
    if (!slide || !element) return null;
    const block = slideBlocks(slide, element.block_class)[element.block_ord];
    if (!block) return null;
    if (!element.leaf_tag) return block;
    return leafNodes(block, element.leaf_tag)[element.leaf_n - 1] || null;
  }

  function isVisible(node) {
    return !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
  }

  function fire(element, node, doc, wrap) {
    document.querySelectorAll("#deckbody iframe").forEach(f => {
      const d = f.contentDocument;
      if (d) d.querySelectorAll(".deck-selected")
              .forEach(n => n.classList.remove("deck-selected"));
    });
    node.classList.add("deck-selected");
    selectListeners.forEach(fn => fn({
      element: element,
      rect: rectToPage(node, wrap),
      node: node,
      doc: doc,
    }));
  }

  function attachTargets(doc, slideIndex, wrap) {
    const style = doc.createElement("style");
    style.textContent = FRAME_CSS;
    doc.head.appendChild(style);

    const slide = state.model.slides[slideIndex - 1];
    if (!slide) return;

    for (const element of slide.elements) {
      const node = resolveElement(doc, slideIndex, element);
      if (!node) continue;
      if (node.dataset.deckIgnore === "1") continue;
      if (!isVisible(node)) continue;
      // Two model elements must never share one node; if they did, the second
      // listener would answer for a click on the first.
      if (node.dataset.deckTarget !== undefined) continue;
      node.dataset.deckTarget = element.path;
      node.dataset.deckOrd = String(element.ord || 0);
      node.addEventListener("click", ev => {
        ev.preventDefault();
        ev.stopPropagation();
        fire(element, node, doc, wrap);
      });
    }
  }

  /* A rect measured inside a scaled iframe, expressed in parent coordinates. */
  function rectToPage(node, wrap) {
    const r = node.getBoundingClientRect();
    const holder = wrap.querySelector(".slideframe").getBoundingClientRect();
    return {
      left: holder.left + r.left * SCALE,
      top: holder.top + r.top * SCALE,
      width: r.width * SCALE,
      height: r.height * SCALE,
    };
  }

  window.ClaudeDeck.resolveElement = resolveElement;
  window.ClaudeDeck.attachTargets = attachTargets;

  /* ------------------------------------------------------------------ *
   * Checks: layout, house style, reveal steps
   * ------------------------------------------------------------------ */

  // The same three measurements as the slides skill's layout-audit.js, run on
  // the one slide this frame shows. The frame is 1280x720 and unscaled inside
  // (the scale is a transform on the iframe), so rects are in slide pixels.
  const OVERFLOW_TOLERANCE = 1, OVERLAP_TOLERANCE = 2, DEAD_BAND = 60, OFF_CENTRE = 40;
  // House-style ceilings (PRESENTATION-STYLE.md): ~90 words on a slide.
  const WORD_BUDGET = 90;
  const TICKET_KEY = /\b[A-Z][A-Z0-9]{1,9}-\d+\b/g;
  const OURS = "deck-stepbadge";

  function skipForAudit(n) {
    return n.classList.contains("num") || n.classList.contains("pg") ||
           n.classList.contains("ghost") || n.classList.contains(OURS);
  }
  function nameOf(n) {
    return (n.className && n.className.baseVal !== undefined ? n.className.baseVal : n.className ||
            n.tagName).toString().trim().split(/\s+/)[0] || n.tagName.toLowerCase();
  }

  function auditSlide(slide, win) {
    const s = slide.getBoundingClientRect();
    const overflow = [], collisions = [], offCentre = [];
    const boxes = [];
    slide.querySelectorAll("*").forEach(n => {
      if (skipForAudit(n) || n.closest("." + OURS)) return;
      const r = n.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const worst = Math.max(s.left - r.left, r.right - s.right, s.top - r.top, r.bottom - s.bottom);
      if (worst > OVERFLOW_TOLERANCE) overflow.push(nameOf(n) + " by " + Math.round(worst) + "px");
      if (win.getComputedStyle(n).position === "absolute") boxes.push({ n, r });
    });
    for (let a = 0; a < boxes.length; a++) {
      for (let b = a + 1; b < boxes.length; b++) {
        const A = boxes[a], B = boxes[b];
        if (A.n.contains(B.n) || B.n.contains(A.n)) continue;
        const x = Math.min(A.r.right, B.r.right) - Math.max(A.r.left, B.r.left);
        const y = Math.min(A.r.bottom, B.r.bottom) - Math.max(A.r.top, B.r.top);
        if (x > OVERLAP_TOLERANCE && y > OVERLAP_TOLERANCE) {
          collisions.push(nameOf(A.n) + " × " + nameOf(B.n));
        }
      }
    }
    // A block with dead space both above and below it should sit in the middle
    // of that band; the skill's target is within about 10px, flagged past 40.
    const blocks = [...slide.children].filter(n => !skipForAudit(n)).map(n => {
      const r = n.getBoundingClientRect();
      return { n, top: r.top - s.top, bottom: r.bottom - s.top, h: r.height };
    }).filter(b => b.h > 0).sort((a, b) => a.top - b.top);
    let lowest = null;
    const gaps = [];
    for (const b of blocks) {
      if (lowest) gaps.push({ above: b.top - lowest.bottom, block: b });
      if (!lowest || b.bottom > lowest.bottom) lowest = b;
    }
    for (let k = 0; k + 1 < gaps.length; k++) {
      const above = gaps[k].above, below = gaps[k + 1].above;
      if (above > DEAD_BAND && below > DEAD_BAND && Math.abs(above - below) > OFF_CENTRE) {
        offCentre.push(nameOf(gaps[k].block.n) + ": " + Math.round(above) + "px above, " +
                       Math.round(below) + "px below");
      }
    }
    return { overflow, collisions, offCentre };
  }

  function lintSlide(slide) {
    const text = slide.innerText || "";
    const words = (text.match(/\S+/g) || []).length;
    const keys = [...new Set(text.match(TICKET_KEY) || [])];
    const notes = !!slide.querySelector(".snotes");
    return { words, keys, notes };
  }

  /* Reveal steps exactly as the framework groups them: data-frag="n" first,
     elements sharing a number together, bare .frag after in document order. */
  function fragSteps(slide) {
    const frags = [...slide.querySelectorAll(".frag")];
    const key = (f, k) => f.dataset.frag !== undefined ? parseFloat(f.dataset.frag) : 1e6 + k;
    const keys = [...new Set(frags.map(key))].sort((a, b) => a - b);
    return frags.map((f, k) => ({ node: f, step: keys.indexOf(key(f, k)) + 1 }));
  }

  function markSteps(doc, slide, steps) {
    if (!steps.length) return;
    const s = slide.getBoundingClientRect();
    for (const { node, step } of steps) {
      const r = node.getBoundingClientRect();
      const b = doc.createElement("div");
      b.className = OURS;
      b.textContent = step;
      b.style.left = Math.max(0, r.right - s.left - 10) + "px";
      b.style.top = Math.max(0, r.top - s.top - 10) + "px";
      slide.appendChild(b);
    }
    const css = doc.createElement("style");
    css.textContent =
      "." + OURS + "{position:absolute;z-index:50;min-width:20px;height:20px;padding:0 5px;" +
      "border-radius:10px;background:#6A4FB3;color:#fff;font:bold 12px/20px sans-serif;" +
      "text-align:center;pointer-events:none;box-shadow:0 0 0 2px #fff}" +
      ".deck-step-hidden{visibility:hidden !important}";
    doc.head.appendChild(css);
  }

  function showStep(slide, steps, upTo) {
    for (const { node, step } of steps) {
      node.classList.toggle("deck-step-hidden", upTo !== null && step > upTo);
    }
  }

  function badge(cls, text, detail) {
    const b = el("span", "badge " + cls, text);
    if (detail && detail.length) b.title = detail.join("\n");
    return b;
  }

  function renderChecks(wrap, doc, index) {
    const slide = slideSections(doc)[index - 1];
    const label = wrap._label || wrap.querySelector(".slidelabel");
    const box = label && label.querySelector(".checks");
    if (!slide || !box) return;
    const steps = fragSteps(slide);
    const layout = auditSlide(slide, doc.defaultView);
    const lint = lintSlide(slide);
    markSteps(doc, slide, steps);
    box.textContent = "";
    if (layout.overflow.length) box.appendChild(badge("bad", "overflow " + layout.overflow.length, layout.overflow));
    if (layout.collisions.length) box.appendChild(badge("warn", "overlap " + layout.collisions.length, layout.collisions));
    if (layout.offCentre.length) box.appendChild(badge("warn", "off-centre", layout.offCentre));
    if (lint.notes) box.appendChild(badge("bad", "speaker notes", ["Speaker notes are not supported; delete the .snotes block."]));
    if (lint.words > WORD_BUDGET) box.appendChild(badge("warn", lint.words + " words", ["House-style ceiling is about " + WORD_BUDGET + " words a slide."]));
    if (lint.keys.length) box.appendChild(badge("warn", "ticket keys", lint.keys));
    if (!box.childNodes.length) box.appendChild(badge("ok", "✓", ["No layout or house-style problem found."]));
    const level = box.querySelector(".badge.bad") ? "bad" : box.querySelector(".badge.warn") ? "warn" : "ok";
    const dot = document.querySelector('#deckstrip [data-rail-slide="' + index + '"] .dot');
    if (dot) { dot.className = "dot " + level; dot.title = [...box.querySelectorAll(".badge")].map(b => b.textContent).join(", "); }

    const scrub = label.querySelector(".steps");
    if (scrub && steps.length) {
      const total = Math.max(...steps.map(s => s.step));
      scrub.textContent = "";
      scrub.appendChild(el("span", "lb", "reveal"));
      const buttons = [];
      const pick = (upTo, btn) => {
        showStep(slide, steps, upTo);
        buttons.forEach(x => x.classList.toggle("on", x === btn));
      };
      for (let n = 0; n <= total; n++) {
        const btn = el("button", null, String(n));
        btn.title = n === 0 ? "Before any reveal" : "After step " + n;
        btn.addEventListener("click", () => pick(n, btn));
        buttons.push(btn);
        scrub.appendChild(btn);
      }
      const all = el("button", "on", "all");
      all.title = "Every step shown, as in the file";
      all.addEventListener("click", () => pick(null, all));
      buttons.push(all);
      scrub.appendChild(all);
    }
  }

  /* ------------------------------------------------------------------ *
   * Render
   * ------------------------------------------------------------------ */

  /* A frame holds a whole copy of the deck document, and a deck with embedded
     images runs to tens of megabytes. Mounting all of them at once meant 25
     copies in memory before the reader had scrolled past slide two, so a slide
     keeps a same-size placeholder until it comes near the viewport. */
  function placeholder(wrap) {
    const holder = el("div", "slideframe slideframe-pending");
    holder.style.width = Math.round(SLIDE_W * SCALE) + "px";
    holder.style.height = Math.round(SLIDE_H * SCALE) + "px";
    const body = wrap.querySelector(".slidebody");
    body.insertBefore(holder, body.firstChild);
  }

  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const wrap = entry.target;
      observer.unobserve(wrap);
      mountSlide(wrap, Number(wrap.dataset.slide));
    }
  }, { rootMargin: "1200px 0px" });

  /* Mount one slide now, whether or not it is on screen. */
  function mountNow(index) {
    const wrap = document.querySelector('.slidewrap[data-slide="' + index + '"]');
    if (!wrap) return null;
    if (wrap.querySelector("iframe")) return wrap.querySelector("iframe");
    observer.unobserve(wrap);
    return mountSlide(wrap, index);
  }
  window.ClaudeDeck.mountNow = mountNow;

  async function renderDeck() {
    const item = await fetchJSON("items/__model__");
    state.model = item.body;
    state.modelVersion = item.version;

    const head = document.getElementById("deckhead");
    head.textContent = "";
    // state.model.deck (the deck's absolute path) is only ever useful to
    // Claude reading a later comment event, never to this page — the shell's
    // own <title> already carries the deck's name (set server-side from the
    // session's title, push.py's `deck.stem`), so the header reads it from
    // there instead of the model.
    head.appendChild(el("span", "nm", document.title || "Deck"));
    head.appendChild(el("span", "mt", state.model.slides.length + " slides"));
    head.appendChild(el("span", "ct"));
    head.appendChild(el("span", "sp"));
    const toggle = el("span", "viewtoggle");
    for (const [v, icon, title] of [["scroll", "rows", "Scroll: every slide, one under another"],
                                     ["slide", "single", "Slide: one at a time (← →)"]]) {
      const b = iconEl("button", v === state.view ? "on" : null, icon, null, title);
      b.dataset.view = v;
      b.addEventListener("click", () => setView(v));
      toggle.appendChild(b);
    }
    head.appendChild(toggle);
    const deckComment = iconEl("button", "hdbtn", "comment", "Deck", "Comment on the whole deck");
    deckComment.addEventListener("click", ev => {
      ev.stopPropagation();
      openPopup({ scope: "deck", rect: deckComment.getBoundingClientRect(), node: null });
    });
    head.appendChild(deckComment);
    // The deck itself, scripts running, in a new tab — present.html frames it
    // with an opaque origin so the deck's script never runs as this page.
    const link = iconEl("a", "hdbtn present", "external", "Present", "Open the presentation in a new tab");
    link.href = BASE + "assets/present.html?v=" + state.modelVersion +
                "&title=" + encodeURIComponent(document.title || "Deck");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    head.appendChild(link);

    const body = document.getElementById("deckbody");
    observer.disconnect();
    body.textContent = "";
    if (!state.model.slides.length) {
      // Pointing /deck at a demo panel or a diagram page is an easy mistake;
      // an empty page would look like a rendering failure.
      const empty = el("div", "deckempty");
      empty.appendChild(el("div", "hd", "No slides in this file"));
      empty.appendChild(el("div", null,
        "claude-deck addresses <section class=\"slide\"> elements, and this " +
        "file has none. Point it at a deck rather than a standalone page."));
      body.appendChild(empty);
      return state.model;
    }
    // Slide view's bottom strip: a chip per slide, then the current slide's
    // own controls, which goTo() moves in from that slide's label.
    const old = document.getElementById("deckstrip");
    if (old) old.remove();
    const strip = el("nav", null);
    strip.id = "deckstrip";
    const prev = iconEl("button", "sbtn", "left", null, "Previous slide (←)");
    prev.addEventListener("click", () => goTo(state.current - 1));
    const chips = el("span", "chips");
    for (const slide of state.model.slides) {
      const chip = el("button", "chip");
      chip.dataset.railSlide = String(slide.index);
      chip.title = slide.index + " · " + (slide.title || slide.kind);
      chip.appendChild(el("span", "dot"));
      chip.appendChild(el("span", null, String(slide.index)));
      chip.addEventListener("click", () => goTo(slide.index));
      chips.appendChild(chip);
    }
    const next = iconEl("button", "sbtn", "right", null, "Next slide (→)");
    next.addEventListener("click", () => goTo(state.current + 1));
    strip.append(prev, chips, next, el("span", "sp"), el("span", "here"));
    document.getElementById("app").appendChild(strip);
    for (const slide of state.model.slides) {
      const wrap = el("div", "slidewrap");
      wrap.dataset.slide = String(slide.index);

      const label = el("div", "slidelabel");
      wrap._label = label;
      label.appendChild(el("span", "nm", "Slide " + slide.index + " · " + slide.kind));
      label.appendChild(el("span", "checks"));
      label.appendChild(el("span", "ln"));
      if (slide.title) label.appendChild(el("span", "tt", slide.title.slice(0, 48)));
      label.appendChild(el("span", "steps"));
      const talk = iconEl("button", "lbtn", "comment", "slide", "Comment on the whole slide");
      talk.addEventListener("click", ev => {
        ev.stopPropagation();
        openPopup({ scope: "slide", slide: slide, rect: talk.getBoundingClientRect(), node: null });
      });
      label.appendChild(talk);
      // Present mode from this slide, in the same sandboxed page as the
      // header link; a deck on framework 2.1+ reads #present-N on load.
      const play = iconEl("a", "lbtn", "play", null, "Present from this slide");
      play.href = BASE + "assets/present.html?v=" + state.modelVersion +
                  "&title=" + encodeURIComponent(document.title || "Deck") +
                  "#present-" + slide.index;
      play.target = "_blank";
      play.rel = "noopener noreferrer";
      label.appendChild(play);
      wrap.appendChild(label);
      wrap.appendChild(el("div", "slidebody"));

      body.appendChild(wrap);
      placeholder(wrap);
      observer.observe(wrap);
    }
    applyView();
    return state.model;
  }

  /* ------------------------------------------------------------------ *
   * Views: every slide in a scrolling column, or one slide at a time
   * ------------------------------------------------------------------ */

  function slideCount() { return state.model ? state.model.slides.length : 0; }

  function applyView() {
    const single = state.view === "slide";
    const body = document.getElementById("deckbody");
    body.classList.toggle("single", single);
    document.getElementById("app").classList.toggle("single", single);
    document.querySelectorAll("#deckhead .viewtoggle button")
      .forEach(b => b.classList.toggle("on", b.dataset.view === state.view));
    if (!single) {
      // Every label home again, above its own slide.
      document.querySelectorAll(".slidewrap").forEach(w => {
        if (w._label && w._label.parentNode !== w) w.insertBefore(w._label, w.firstChild);
      });
    }
    relayoutFrames();
    if (single) goTo(state.current, true);
  }

  function setView(v) {
    if (v === state.view) return;
    closePopup();
    // Carry the reader's place across: the slide nearest the middle of the
    // window becomes the one shown, and back again.
    if (v === "slide") state.current = nearestWrap();
    state.view = v;
    try { localStorage.setItem("claude-deck-view", v); } catch (_) {}
    applyView();
    if (v === "scroll") {
      const wrap = document.querySelector('.slidewrap[data-slide="' + state.current + '"]');
      if (wrap) wrap.scrollIntoView({ block: "center" });
    }
  }

  function nearestWrap() {
    const mid = window.innerHeight / 2;
    let best = state.current, bestD = Infinity;
    document.querySelectorAll(".slidewrap").forEach(w => {
      const r = w.getBoundingClientRect();
      const d = Math.abs(r.top + r.height / 2 - mid);
      if (r.height && d < bestD) { bestD = d; best = Number(w.dataset.slide); }
    });
    return best;
  }

  function goTo(n, quiet) {
    const total = slideCount();
    if (!total) return;
    const target = Math.max(1, Math.min(total, n));
    if (target !== state.current || quiet) closePopup();
    state.current = target;
    document.querySelectorAll(".slidewrap")
      .forEach(w => w.classList.toggle("cur", Number(w.dataset.slide) === target));
    document.querySelectorAll("#deckstrip .chip")
      .forEach(c => c.classList.toggle("on", Number(c.dataset.railSlide) === target));
    const slide = state.model.slides[target - 1];
    const ct = document.querySelector("#deckhead .ct");
    if (ct) ct.textContent = target + "/" + total + " · " + (slide.title || slide.kind);
    history.replaceState(null, "", "#slide-" + target);
    if (state.view === "slide") {
      const here = document.querySelector("#deckstrip .here");
      const wrap = document.querySelector('.slidewrap[data-slide="' + target + '"]');
      if (here && wrap && wrap._label) {
        [...here.children].forEach(l => {
          const home = l !== wrap._label && document.querySelector(
            '.slidewrap[data-slide="' + (l.dataset.forSlide || "") + '"]');
          if (home) home.insertBefore(l, home.firstChild);
        });
        wrap._label.dataset.forSlide = String(target);
        here.appendChild(wrap._label);
      }
      mountNow(target);
      const chip = document.querySelector('#deckstrip .chip[data-rail-slide="' + target + '"]');
      if (chip) chip.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function onNavKey(ev) {
    if (state.view !== "slide" || popup) return;
    const t = ev.target;
    if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) return;
    const step = { ArrowRight: 1, ArrowDown: 1, PageDown: 1, " ": 1,
                   ArrowLeft: -1, ArrowUp: -1, PageUp: -1 }[ev.key];
    if (step) { ev.preventDefault(); goTo(state.current + step); }
    else if (ev.key === "Home") { ev.preventDefault(); goTo(1); }
    else if (ev.key === "End") { ev.preventDefault(); goTo(slideCount()); }
  }
  document.addEventListener("keydown", onNavKey);
  window.ClaudeDeck.goTo = goTo;
  window.ClaudeDeck.setView = setView;

  window.ClaudeDeck.renderDeck = renderDeck;
  window.ClaudeDeck.mountSlide = mountSlide;

  /* ------------------------------------------------------------------ *
   * Comment popup
   * ------------------------------------------------------------------ */

  let popup = null;

  function clearSelection() {
    document.querySelectorAll("#deckbody iframe").forEach(f => {
      const d = f.contentDocument;   // same-origin, so this is reachable
      if (d) d.querySelectorAll(".deck-selected")
              .forEach(n => n.classList.remove("deck-selected"));
    });
  }

  function closePopup() {
    if (popup) { popup.remove(); popup = null; }
    clearSelection();
  }

  function openPopup(sel) {
    if (popup) { popup.remove(); popup = null; }
    const scope = sel.scope || "element";
    const e = sel.element;
    popup = el("div");
    popup.id = "deckpop";

    const ph = el("div", "ph",
      scope === "deck" ? "The whole deck · " + state.model.slides.length + " slides" :
      scope === "slide" ? "Slide " + sel.slide.index + " · the whole slide · lines " +
                          sel.slide.line_start + "–" + sel.slide.line_end :
      "Slide " + e.slide + " · " + e.path + (e.ord ? " #" + (e.ord + 1) : "") +
      " · line " + e.line_start);
    const quote = el("div", "quote",
      scope === "deck" ? "Anything that spans slides: order, cuts, a rule for every slide." :
      scope === "slide" ? "“" + (sel.slide.title || "Slide " + sel.slide.index).slice(0, 220) + "”" :
      "“" + (e.text || "(empty)").slice(0, 220) + "”");
    const body = el("div", "body");
    const ta = el("textarea");
    ta.placeholder = (!window.WebCompanion || window.WebCompanion.writable)
      ? "What should change?"
      : "This is a read-only link — comments cannot be sent from it.";
    const row = el("div", "row");
    const hint = el("span", "ph", "⌘↵ send");
    hint.style.border = "none";
    hint.style.padding = "0";
    const sp = el("span", "sp");
    const cancel = el("button", null, "Cancel");
    const writable = !window.WebCompanion || window.WebCompanion.writable;
    const send = el("button", "send",
      writable ? "Send to Claude" : "Read-only link");
    send.disabled = !writable;
    if (!writable) send.title = "This link does not carry write access.";
    const err = el("div", "err");
    err.style.display = "none";

    row.append(hint, sp, cancel, send);
    body.append(ta, row, err);
    popup.append(ph, quote, body);
    document.body.appendChild(popup);

    // place under the element, clamped to the viewport
    const top = window.scrollY + sel.rect.top + sel.rect.height + 8;
    const left = Math.min(
      window.scrollX + sel.rect.left,
      window.scrollX + document.documentElement.clientWidth - 356);
    // A button in the bottom strip has no room under it: open above instead.
    const above = window.scrollY + sel.rect.top - popup.offsetHeight - 8;
    const fitsBelow = sel.rect.top + sel.rect.height + 8 + popup.offsetHeight <= window.innerHeight;
    popup.style.top = (fitsBelow ? top : Math.max(window.scrollY + 8, above)) + "px";
    popup.style.left = Math.max(8, left) + "px";
    ta.focus();

    cancel.addEventListener("click", closePopup);

    async function submit() {
      const text = ta.value.trim();
      if (!text) { err.textContent = "Say what should change."; err.style.display = ""; return; }
      send.disabled = true;
      send.textContent = "Sending…";
      // The daemon's /api/submit stores exactly {anchor, text, images} and
      // drops every other key, so the structured payload travels JSON-encoded
      // inside `text` — the same bridge annotate/static/compat.js's own
      // submit() uses for its multi-field feedback. The anchor still keys the
      // comment to the element clicked, independent of what's inside `text`.
      //
      // `deck` (the file's absolute path) rides along here because push.py
      // puts it on __model__ specifically so this envelope can carry it back
      // out — the browser itself never reads state.model.deck for anything.
      let anchor, envelope;
      if (scope === "deck") {
        anchor = "deck";
        envelope = { type: "deck_comment", scope: "deck", deck: state.model.deck,
                     slides: state.model.slides.length, comment: text };
      } else if (scope === "slide") {
        const sl = sel.slide;
        anchor = "slide:" + sl.index;
        envelope = { type: "deck_comment", scope: "slide", deck: state.model.deck,
                     slide: sl.index, title: sl.title, line_start: sl.line_start,
                     line_end: sl.line_end, comment: text };
      } else {
        anchor = "slide:" + e.slide + ":" + e.path + ":" + (e.ord || 0);
        envelope = {
          type: "deck_comment", scope: "element", deck: state.model.deck, slide: e.slide,
          path: e.path, ord: e.ord || 0, component: e.component, line_start: e.line_start,
          line_end: e.line_end, text: e.text, comment: text,
        };
      }
      try {
        await window.WebCompanion.api.submit({ anchor, text: JSON.stringify(envelope) });
        setBusyLocal(true);
        if (sel.node) sel.node.classList.add("deck-working");
        closePopup();
      } catch (ex) {
        err.textContent = String(ex.message || ex);
        err.style.display = "";
        send.disabled = false;
        send.textContent = "Send to Claude";
      }
    }

    send.addEventListener("click", submit);
    ta.addEventListener("keydown", ev => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") { ev.preventDefault(); submit(); }
      if (ev.key === "Escape") closePopup();
    });
  }

  window.ClaudeDeck.openPopup = openPopup;
  window.ClaudeDeck.closePopup = closePopup;
  window.ClaudeDeck.onSelect(openPopup);

  document.addEventListener("mousedown", ev => {
    if (!popup) return;
    if (ev.target instanceof Node && popup.contains(ev.target)) return;
    closePopup();
  });

  /* ------------------------------------------------------------------ *
   * Busy state and repaint
   * ------------------------------------------------------------------ */

  function flash(index) {
    const wrap = document.querySelector('.slidewrap[data-slide="' + index + '"]');
    if (!wrap) return;
    wrap.classList.add("fresh");
    setTimeout(() => wrap.classList.remove("fresh"), 2500);
  }

  function reloadSlide(index) {
    const wrap = document.querySelector('.slidewrap[data-slide="' + index + '"]');
    if (!wrap) return;
    const holder = wrap.querySelector(".slideframe");
    if (holder) holder.remove();
    placeholder(wrap);
    mountSlide(wrap, index);
    flash(index);
  }

  function signature(model) {
    return model.slides.map(
      s => JSON.stringify(s.elements.map(e => [e.path, e.ord, e.text])));
  }

  async function reloadEverything() {
    const before = state.model ? signature(state.model) : [];
    // renderDeck empties #deckbody, which collapses the document height and
    // clamps the scroll to the top. Reading a deck and being thrown back to
    // slide 1 on every edit is the whole page's worth of annoyance.
    const y = window.scrollY;
    closePopup();
    await renderDeck();
    window.scrollTo(0, y);
    const after = signature(state.model);
    after.forEach((sig, i) => { if (before[i] !== sig) flash(i + 1); });
  }

  function setBusy(on, queued) {
    let banner = document.getElementById("deckbusy");
    if (!on) { if (banner) banner.remove(); return; }
    if (!banner) {
      banner = el("div");
      banner.id = "deckbusy";
      banner.appendChild(el("span", "dot"));
      banner.appendChild(el("span", "tx"));
      document.getElementById("deckhead").after(banner);
    }
    banner.querySelector(".tx").textContent =
      "Claude is editing the deck… " + (queued > 1 ? "(" + queued + " queued)" : "");
  }

  // The daemon reports no busy/queued concept at all — /poll and the SSE
  // frames only ever say WHICH anchor changed, never whether Claude is still
  // working on one. Reconstructed the same way annotate/static/compat.js
  // already had to for its own submit lock: optimistic-lock on submit,
  // unlock only once an actual item-changed delta for __model__ arrives.
  // Erring towards "locked a little too long" (a busy banner that outlives
  // an ack that changed nothing) is the safe direction — the alternative,
  // a page that looks idle while Claude is mid-edit, invites a second
  // conflicting comment.
  let busyLocal = false;
  function setBusyLocal(v) {
    busyLocal = !!v;
    setBusy(busyLocal, 0);
  }

  function connect() {
    window.WebCompanion.init({
      onDelta(ev) {
        if (ev.kind === "item" && ev.anchor === "__model__" && !ev.initial) {
          setBusyLocal(false);
          reloadEverything().catch(e =>
            console.warn("deck reload failed, will retry on the next change", e));
        }
      },
    });
  }

  window.ClaudeDeck.reloadSlide = reloadSlide;
  window.ClaudeDeck.reloadEverything = reloadEverything;

  function boot() {
    computeScale();
    renderDeck().then(() => {
      if (window.WebCompanion && window.WebCompanion.init) {
        connect();
      }
    }).catch(err => {
      document.getElementById("deckbody").textContent = "Could not render deck: " + err.message;
    });
  }

  // entry.js loads this file from a <script> element it creates itself,
  // inside a promise chain (core.css, then deck.css, then this file) kicked
  // off from a `type="module"` <script>. A module script's own top-level
  // code runs before DOMContentLoaded fires, but the browser does not wait
  // for THIS file's async loadStylesheet/loadScript chain to settle before
  // firing it — so DOMContentLoaded has already happened by the time this
  // script itself starts running, and a plain `document.addEventListener
  // ("DOMContentLoaded", boot)` would never call `boot` at all. Checking
  // `readyState` first is the same guard annotate's own late-loaded scripts
  // (highlighter.js, search.js, export.js) already use for the identical
  // reason.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
