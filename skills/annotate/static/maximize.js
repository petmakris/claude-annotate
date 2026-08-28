// annotate — Maximize: give a picture block the whole viewport.
//
// A sequence diagram is authored on a fixed grid and rendered at its real pixel
// size (see diagrams/sequence.py), so a wide one scrolls sideways inside the
// 1040px reading column. That is the right default — shrinking it to fit is the
// defect the fixed grid exists to remove — but it means a twelve-actor trace is
// read through a letterbox. This lifts one block to viewport width for as long
// as you are looking at it.
//
// Three rules shape the rest:
//
// 1. The button is ALWAYS VISIBLE, unlike the hover-actions strip. Those are
//    feedback VERBS (comment/keep/delete/compact) and hiding them keeps the
//    page calm; this is a VIEW control, and a view control you cannot see is a
//    view control nobody uses.
//
// 2. NOTHING IS MOVED IN THE DOM. The card stays exactly where it sits in
//    main.prose and is promoted with `position: fixed`. Both other designs were
//    tried and both are broken: cloning gives two live nodes carrying the same
//    `data-block-id`, which every engaged-state and card-focus selector in
//    script.js keys off; and MOVING the node into an overlay host is worse,
//    because script.js's render loop then finds the block absent from the prose
//    and paints a fresh one — measured, it took under 50ms to end up with the
//    block listed twice, and closing put the moved copy back beside it for
//    three. Promoting in place means the render loop never sees anything gone.
//
// 3. Fit-to-width is opt-in and never automatic. Automatic downscaling is
//    precisely what made wide diagrams unreadable before; offering it as a
//    button the user presses is a different thing from doing it to them.
(function () {
  "use strict";

  // Kinds where more width buys something. Prose is deliberately excluded: it
  // is set to a max measure, so a wider column only makes the lines harder to
  // track back to the left edge.
  const MAXIMIZABLE = new Set(["sequence", "flowchart", "diagram", "mockup"]);

  const ICON_MAX =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>' +
    '<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
  const ICON_MIN =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/>' +
    '<line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';

  let chrome = null;   // scrim + top bar; built once, never holds the block
  let fitBtn = null;
  let fsBtn = null;
  let titleEl = null;

  // The block ID, NOT the element. A rewrite landing while the view is open
  // replaces the node; holding the id lets reapply() find the new one and keep
  // it maximized instead of leaving a stale reference to a detached node.
  let openId = null;
  let wantFit = false;

  function cssEsc(s) {
    return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/"/g, '\\"');
  }

  function mkBtn(text, title, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "max-btn";
    if (text) b.textContent = text;
    b.title = title;
    b.addEventListener("click", onClick);
    return b;
  }

  function build() {
    if (chrome) return;
    chrome = document.createElement("div");
    chrome.className = "max-chrome";
    chrome.hidden = true;
    chrome.setAttribute("role", "dialog");
    chrome.setAttribute("aria-modal", "true");
    chrome.setAttribute("aria-label", "Maximized section");

    // Background paint only — deliberately NOT a click-to-close target. The
    // maximized card is inset by 16px, so the scrim is a hairline frame around
    // it; a close affordance that thin is one nobody can hit on purpose and
    // everybody hits by accident. The three real ways out are the × in the bar,
    // the header toggle, and Esc.
    const scrim = document.createElement("div");
    scrim.className = "max-scrim";

    const bar = document.createElement("div");
    bar.className = "max-bar";
    titleEl = document.createElement("span");
    titleEl.className = "max-title";
    const spacer = document.createElement("span");
    spacer.className = "max-spacer";
    fitBtn = mkBtn("Fit width",
                   "Scale the picture down so its full width fits the screen", toggleFit);
    fsBtn = mkBtn("Full screen",
                  "Hand the page to the browser's own full-screen mode", toggleNativeFullscreen);
    const closeBtn = mkBtn("", "Close (Esc)", () => close());
    closeBtn.classList.add("max-close");
    closeBtn.innerHTML = ICON_MIN;
    closeBtn.setAttribute("aria-label", "Close maximized view");
    bar.append(titleEl, spacer, fitBtn, fsBtn, closeBtn);

    chrome.append(scrim, bar);
    document.body.appendChild(chrome);

    document.addEventListener("fullscreenchange", syncFullscreenLabel);
    // The fitted scale is a function of the viewport, so it has to be redone
    // when the viewport changes. 1:1 needs nothing.
    window.addEventListener("resize", () => { if (wantFit) applyFit(current(), true); });
  }

  function isOpen() { return openId !== null; }

  function current() {
    if (openId === null) return null;
    return document.querySelector(
      'main.prose section.block[data-block-id="' + cssEsc(openId) + '"]');
  }

  function open(section) {
    build();
    if (isOpen()) close({ restoreFocus: false });
    openId = section.dataset.blockId;
    wantFit = false;
    // A maximized card must not also be collapsed, or the button fills the
    // screen with a folded header and nothing else.
    section.classList.remove("collapsed");
    const chev = section.querySelector(".card-chevron");
    if (chev) { chev.textContent = "▾"; chev.setAttribute("aria-label", "Collapse section"); }
    reapply();
    chrome.hidden = false;
    document.body.classList.add("has-max-overlay");
    syncFullscreenLabel();
    updateButtons();
  }

  function close(opts) {
    if (!isOpen()) return;
    const section = current();
    openId = null;
    wantFit = false;
    if (document.fullscreenElement) {
      // Best-effort: a rejected promise here must not leave the page stuck
      // half-maximized.
      document.exitFullscreen().catch(function () {});
    }
    if (section) {
      section.classList.remove("is-maximized", "is-fit");
      section.style.removeProperty("--max-fit-scale");
      section.style.removeProperty("--max-fit-h");
    }
    chrome.hidden = true;
    document.body.classList.remove("has-max-overlay");
    updateButtons();
    if (section && (!opts || opts.restoreFocus !== false)) {
      const btn = section.querySelector(".max-toggle");
      if (btn) btn.focus({ preventScroll: true });
      section.scrollIntoView({ block: "nearest" });
    }
  }

  // Put the maximized state back on whichever node currently carries the id.
  // Called on open and again from decorate(), so a rewrite that replaces the
  // block mid-view does not silently drop it back into the column.
  function reapply() {
    const section = current();
    if (!section) return;
    section.classList.add("is-maximized");
    titleEl.textContent =
      (section.querySelector(".card-title") || {}).textContent || "Section";
    applyFit(section, wantFit);
  }

  // ── Fit-to-width ────────────────────────────────────────────────────────
  // A CSS transform, not a re-render: the SVG keeps its authored pixel size, so
  // "Actual size" returns to exactly what the author laid out, and nothing
  // about the diagram's geometry ever depends on the viewport.
  function toggleFit() {
    wantFit = !wantFit;
    applyFit(current(), wantFit);
  }

  function applyFit(section, on) {
    if (!section) return;
    if (!on) {
      section.classList.remove("is-fit");
      section.style.removeProperty("--max-fit-scale");
      section.style.removeProperty("--max-fit-h");
      fitBtn.textContent = "Fit width";
      fitBtn.setAttribute("aria-pressed", "false");
      return;
    }
    const host = section.querySelector(".block-content");
    const art = host && host.querySelector("svg, iframe");
    if (!host || !art) return;
    // Measure against the CONTENT BOX the picture actually lives in, not the
    // viewport: the card's border and padding sit between the two, and sizing
    // to the viewport left the "fitted" picture 25px wider than its container,
    // so it still scrolled after the button that promised it would not.
    const scale0 = currentScale(section);
    const rect = art.getBoundingClientRect();
    const natural = rect.width / scale0;
    const naturalH = rect.height / scale0;
    const avail = host.clientWidth;
    // Only ever shrink. Blowing a small diagram up to fill the screen makes it
    // enormous and soft, and nobody pressed a button asking for that.
    const scale = natural > avail && natural > 0 ? avail / natural : 1;
    section.style.setProperty("--max-fit-scale", String(scale));
    // A transform leaves the layout box at its unscaled size, so without an
    // explicit height the card keeps the full height of the 1:1 picture and
    // shows a tall band of empty space under a scaled-down one.
    section.style.setProperty("--max-fit-h", Math.ceil(naturalH * scale) + "px");
    section.classList.add("is-fit");
    fitBtn.textContent = "Actual size";
    fitBtn.setAttribute("aria-pressed", "true");
  }

  // getBoundingClientRect reports the POST-transform size, so re-fitting an
  // already-fitted block would compound the scale. Divide it back out first.
  function currentScale(section) {
    const s = parseFloat(section.style.getPropertyValue("--max-fit-scale"));
    return section.classList.contains("is-fit") && s > 0 ? s : 1;
  }

  // Native full screen goes on the document element, not on our chrome: the
  // maximized card is a fixed-position sibling of the chrome, so making only
  // the chrome full screen would hide the very thing being maximized.
  function toggleNativeFullscreen() {
    const el = document.documentElement;
    if (document.fullscreenElement) document.exitFullscreen().catch(function () {});
    else if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
  }

  function syncFullscreenLabel() {
    if (!fsBtn) return;
    const on = !!document.fullscreenElement;
    fsBtn.textContent = on ? "Exit full screen" : "Full screen";
    fsBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (wantFit) applyFit(current(), true);   // the viewport just changed size
  }

  // ── The header button ───────────────────────────────────────────────────
  function updateButtons() {
    document.querySelectorAll(".max-toggle").forEach(function (b) {
      const sec = b.closest("section.block");
      const on = !!sec && sec.dataset.blockId === openId;
      b.innerHTML = on ? ICON_MIN : ICON_MAX;
      b.title = on ? "Restore to the page (Esc)" : "Maximize — fill the screen";
      b.setAttribute("aria-label", b.title);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function decorate() {
    build();
    document.querySelectorAll("section.block[data-kind]").forEach(function (section) {
      if (!MAXIMIZABLE.has(section.dataset.kind)) {
        // A block can change kind on rewrite; drop a button that no longer
        // applies rather than leaving a control that maximizes a paragraph.
        const stale = section.querySelector(".max-toggle");
        if (stale) stale.remove();
        return;
      }
      const head = section.querySelector(".card-head");
      if (!head || head.querySelector(".max-toggle")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "max-toggle";
      btn.innerHTML = ICON_MAX;
      btn.title = "Maximize — fill the screen";
      btn.setAttribute("aria-label", btn.title);
      btn.setAttribute("aria-pressed", "false");
      btn.addEventListener("click", function (ev) {
        // The header row toggles collapse on click; a control click must not
        // also fold the card away under the cursor.
        ev.stopPropagation();
        ev.preventDefault();
        if (section.dataset.blockId === openId) close();
        else open(section);
      });
      // Before the section/version pill, so the pill stays the rightmost thing
      // in every header and the row keeps one alignment.
      const pill = head.querySelector(".section-pill");
      if (pill) head.insertBefore(btn, pill);
      else head.appendChild(btn);
    });
    if (isOpen()) reapply();
    updateButtons();
  }

  // Esc closes. Capture phase, and registered here rather than folded into the
  // popover stack in script.js: that stack returns early when none of ITS
  // panels are open, so this handler is reached in exactly the case it should
  // be — and a popover opened on top of a maximized block still closes first.
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape" || !isOpen()) return;
    // Native full screen owns the first Esc: let the browser leave it and keep
    // the block maximized, rather than throwing the user two levels out at once.
    if (document.fullscreenElement) return;
    ev.preventDefault();
    ev.stopPropagation();
    close();
  }, true);

  // Blocks are (re)painted by script.js on load, on poll and on rewrite. There
  // is no event for it, so watch the prose the way subunits.js does.
  const mo = new MutationObserver(function () { decorate(); });
  function start() {
    const prose = document.querySelector("main.prose");
    if (prose) mo.observe(prose, { childList: true, subtree: false });
    decorate();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }

  window.AnnotateMaximize = { decorate: decorate, open: open, close: close, isOpen: isOpen };
})();
