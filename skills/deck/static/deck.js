/* claude-deck client.
 *
 * The deck loads in a SAME-ORIGIN iframe, so this page can reach into its
 * document and attach targets to real elements. Three harness behaviours are
 * neutralised on the way in — zoom-to-fit, page-number injection, and the
 * floating Present/Notes chrome it appends to <body> — by undoing them in the
 * frame's DOM after load. The deck FILE is never modified.
 */
(function () {
  "use strict";

  const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
  const SCALE = 0.6094;              // 780 / 1280
  const SLIDE_W = 1280, SLIDE_H = 720;

  // One frame per slide, so there is no single shared doc to hold onto.
  const state = { model: null, base: BASE };
  window.ClaudeDeck = { state: state };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
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
    f.src = BASE + "deck#slide-" + index;
    f.addEventListener("load", () => {
      const doc = f.contentDocument;
      if (!doc) return;
      neutraliseHarness(doc);
      const slides = doc.querySelectorAll(".slide");
      slides.forEach((s, i) => { s.style.display = (i === index - 1) ? "" : "none"; });
      attachTargets(doc, index, wrap);
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
        return !(outer && block.contains(outer));
      })
      .filter(n => n.tagName.toLowerCase() === tag);
  }

  /* Turn a model element back into a live node inside the frame. Driven by
     block_ord/leaf_n from the model, never by running `path` as a selector:
     the two disagree on nesting, and a disagreement means the browser
     highlights one element while Claude edits another. */
  function resolveElement(doc, slideIndex, element) {
    const slide = doc.querySelectorAll(".slide")[slideIndex - 1];
    if (!slide || !element) return null;
    const block = slideBlocks(slide, element.block_class)[element.block_ord];
    if (!block) return null;
    if (!element.leaf_tag) return block;
    return leafNodes(block, element.leaf_tag)[element.leaf_n - 1] || null;
  }

  function isVisible(node) {
    // Speaker notes are display:none in the deck's own stylesheet; they get a
    // panel in the chrome instead of a hover target nobody can reach.
    return !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
  }

  function fire(element, node, doc, wrap) {
    document.querySelectorAll(".snoteitem.deck-selected")
            .forEach(n => n.classList.remove("deck-selected"));
    document.querySelectorAll("#deckbody iframe").forEach(f => {
      const d = f.contentDocument;
      if (d) d.querySelectorAll(".deck-selected")
              .forEach(n => n.classList.remove("deck-selected"));
    });
    node.classList.add("deck-selected");
    selectListeners.forEach(fn => fn({
      element: element,
      rect: rectToPage(node, wrap, !!doc),
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

  /* A rect measured inside a scaled iframe, expressed in parent coordinates.
     A node in the chrome (the notes column) is already in them. */
  function rectToPage(node, wrap, inFrame) {
    const r = node.getBoundingClientRect();
    if (!inFrame) return { left: r.left, top: r.top, width: r.width, height: r.height };
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
   * Render
   * ------------------------------------------------------------------ */

  function buildNotes(wrap, slide) {
    const col = el("div", "snotecol");
    col.appendChild(el("div", "hd", "Speaker notes"));
    const notes = slide.elements.filter(e => e.component === "snotes");
    if (!notes.length) {
      col.appendChild(el("div", "none", "No notes on this slide."));
    } else {
      for (const element of notes) {
        const item = el("div", "snoteitem", element.text);
        item.dataset.deckPath = element.path;
        item.dataset.deckOrd = String(element.ord || 0);
        item.addEventListener("click", () => fire(element, item, null, wrap));
        col.appendChild(item);
      }
    }
    wrap.querySelector(".slidebody").appendChild(col);
  }

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
    state.model = await fetchJSON("model");

    const head = document.getElementById("deckhead");
    head.textContent = "";
    head.appendChild(el("span", "nm", state.model.deck.split("/").pop()));
    head.appendChild(el("span", "mt", state.model.slides.length + " slides"));
    head.appendChild(el("span", "sp"));

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
    for (const slide of state.model.slides) {
      const wrap = el("div", "slidewrap");
      wrap.dataset.slide = String(slide.index);

      const label = el("div", "slidelabel");
      label.appendChild(el("span", null, "Slide " + slide.index + " · " + slide.kind));
      label.appendChild(el("span", "ln"));
      if (slide.title) label.appendChild(el("span", null, slide.title.slice(0, 48)));
      wrap.appendChild(label);
      wrap.appendChild(el("div", "slidebody"));

      body.appendChild(wrap);
      placeholder(wrap);
      buildNotes(wrap, slide);
      observer.observe(wrap);
    }
    return state.model;
  }

  window.ClaudeDeck.renderDeck = renderDeck;
  window.ClaudeDeck.mountSlide = mountSlide;

  /* ------------------------------------------------------------------ *
   * Comment popup
   * ------------------------------------------------------------------ */

  let popup = null;

  function clearSelection() {
    document.querySelectorAll(".snoteitem.deck-selected")
            .forEach(n => n.classList.remove("deck-selected"));
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
    const e = sel.element;
    popup = el("div");
    popup.id = "deckpop";

    const ph = el("div", "ph",
      "Slide " + e.slide + " · " + e.path + (e.ord ? " #" + (e.ord + 1) : "") +
      " · line " + e.line_start);
    const quote = el("div", "quote", "“" + (e.text || "(empty)").slice(0, 220) + "”");
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
    popup.style.top = top + "px";
    popup.style.left = Math.max(8, left) + "px";
    ta.focus();

    cancel.addEventListener("click", closePopup);

    async function submit() {
      const text = ta.value.trim();
      if (!text) { err.textContent = "Say what should change."; err.style.display = ""; return; }
      send.disabled = true;
      send.textContent = "Sending…";
      try {
        await window.WebCompanion.api.submit({
          slide: e.slide,
          path: e.path,
          ord: e.ord || 0,
          component: e.component,
          line_start: e.line_start,
          line_end: e.line_end,
          text: e.text,
          comment: text,
        });
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
    // ev.target is not always an Element (document, text nodes), so never
    // reach for closest() without checking.
    const t = ev.target instanceof Element ? ev.target : null;
    if (t && (popup.contains(t) || t.closest(".snoteitem"))) return;
    closePopup();
  });

  /* ------------------------------------------------------------------ *
   * Busy state and repaint
   * ------------------------------------------------------------------ */

  let lastFingerprint = null;

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

  /* Driven by core.js's own 1s poll rather than a second timer of our own. */
  async function onPoll(poll) {
    if (!poll) return;
    setBusy(poll.busy, poll.queued);
    const fp = poll.blocks && poll.blocks.deck;
    if (lastFingerprint === null) { lastFingerprint = fp; return; }
    if (fp && fp !== lastFingerprint) {
      // The file changed on disk. Re-read the model, because line numbers and
      // even the element set may have moved, then repaint every slide.
      // The fingerprint advances only on success: recording it first would
      // strand the page on stale content for good, because the retry the
      // next poll is supposed to make would see no change to react to.
      try {
        await reloadEverything();
        lastFingerprint = fp;
      } catch (e) {
        console.warn("deck reload failed, will retry on the next poll", e);
      }
    }
  }

  window.ClaudeDeck.reloadSlide = reloadSlide;
  window.ClaudeDeck.reloadEverything = reloadEverything;
  window.ClaudeDeck.onPoll = onPoll;

  document.addEventListener("DOMContentLoaded", () => {
    if (window.WebCompanion && window.WebCompanion.init) {
      window.WebCompanion.init({ onPollDelta: onPoll });
    }
    renderDeck().catch(err => {
      document.getElementById("deckbody").textContent = "Could not render deck: " + err.message;
    });
  });
})();
