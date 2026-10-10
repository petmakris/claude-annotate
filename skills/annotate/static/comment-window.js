// annotate — the one comment window.
//
// Every comment opens here: words chosen in the text (selection.js) and a
// comment on a whole part or a picture's step (script-cards.js). It floats
// on the page, free of the text: moved by its title bar, resized from its
// corner, opened beside the words it is about (window-place.js). One at a
// time; an owner that would replace a window holding words calls it instead.
// It lives on <body>, so no rewrite of a part can take it away.
(function () {
  "use strict";

  const SIZE_KEY = "annotate.commentWindow.size";
  let win = null, current = null;

  function storedSize() {
    try {
      const s = JSON.parse(localStorage.getItem(SIZE_KEY) || "null");
      if (s && s.w > 0 && s.h > 0) return s;
    } catch (_) {}
    return { w: 420, h: 280 };
  }
  function saveSize(w, h) {
    try { localStorage.setItem(SIZE_KEY, JSON.stringify({ w: Math.round(w), h: Math.round(h) })); } catch (_) {}
  }
  function view() { return { w: document.documentElement.clientWidth, h: window.innerHeight }; }
  function apply(box) {
    win.style.left = box.left + "px"; win.style.top = box.top + "px";
    win.style.width = box.width + "px"; win.style.height = box.height + "px";
  }
  function box() {
    const r = win.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height };
  }

  function build() {
    win = document.createElement("div");
    win.className = "comment-window";
    win.setAttribute("role", "dialog");
    win.setAttribute("aria-label", "Comment");
    win.innerHTML =
      '<div class="comment-window-bar"><span class="comment-window-grip" aria-hidden="true"></span>'
      + '<span class="comment-window-title">Comment</span><span class="comment-window-space"></span>'
      + '<button type="button" class="comment-window-close" aria-label="Close comment">×</button></div>'
      + '<div class="comment-window-quote"></div><div class="comment-window-body"></div>'
      + '<div class="comment-window-resize" title="Drag to resize"></div>';
    document.body.appendChild(win);
    win.querySelector(".comment-window-close").addEventListener("click", () => close());

    const bar = win.querySelector(".comment-window-bar");
    bar.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button")) return;
      e.preventDefault();
      const start = box(), x = e.clientX, y = e.clientY;
      bar.setPointerCapture(e.pointerId);
      win.classList.add("is-moving");
      const move = (ev) => apply(window.AnnotateWindowPlace.clamp(
        { ...start, left: start.left + ev.clientX - x, top: start.top + ev.clientY - y }, view()));
      const up = () => {
        win.classList.remove("is-moving");
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
        bar.removeEventListener("pointercancel", up);
      };
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
      bar.addEventListener("pointercancel", up);
    });

    const grip = win.querySelector(".comment-window-resize");
    grip.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const start = box(), x = e.clientX, y = e.clientY;
      grip.setPointerCapture(e.pointerId);
      win.classList.add("is-moving");
      const move = (ev) => apply(window.AnnotateWindowPlace.clamp(
        { ...start, width: start.width + ev.clientX - x, height: start.height + ev.clientY - y }, view()));
      const up = () => {
        win.classList.remove("is-moving");
        const b = box();
        saveSize(b.width, b.height);
        grip.removeEventListener("pointermove", move);
        grip.removeEventListener("pointerup", up);
        grip.removeEventListener("pointercancel", up);
      };
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", up);
      grip.addEventListener("pointercancel", up);
    });

    // Esc closes an empty window only. Words or pictures in it are the
    // reader's, and one stray key must not throw them away: the window pulses
    // instead. The × and Cancel are the deliberate ways to discard.
    win.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      e.preventDefault(); e.stopPropagation();
      if (hasWords()) call(); else close();
    });
    window.addEventListener("resize", () => {
      if (win && !win.hidden) apply(window.AnnotateWindowPlace.clamp(box(), view()));
    });
    document.addEventListener("fullscreenchange", mount);
  }

  // A full-screen element paints only itself and what it holds, so while one
  // is up the window goes inside it, as the selection menu does (selection.js
  // layer()). Today the page only ever makes <html> full screen, which already
  // holds <body>; this keeps the window visible if an element ever is.
  function mount() {
    if (!win) return;
    const fs = document.fullscreenElement;
    const host = fs && !fs.contains(document.body) ? fs : document.body;
    if (win.parentNode !== host) host.appendChild(win);
  }

  function contentRect() {
    const c = document.querySelector("main.prose .block-content");
    const r = c ? c.getBoundingClientRect() : { left: 0, right: view().w };
    return { left: r.left, top: 0, right: r.right, bottom: view().h };
  }

  // Open for `owner`, holding `body` (the editor the caller built). A window
  // already open for another owner is closed first, its onClose told so it
  // can drop an empty draft; the caller checks hasWords() before asking.
  // `home` gives the part focus returns to when the window closes.
  function open({ owner, quote, body, near, onClose, home }) {
    if (!win) build();
    if (current && current.owner !== owner) close();
    mount();
    current = { owner, onClose, home };
    win.querySelector(".comment-window-quote").textContent = quote || "";
    win.querySelector(".comment-window-quote").hidden = !quote;
    win.querySelector(".comment-window-body").replaceChildren(body);
    win.hidden = false;
    const s = storedSize();
    const sel = near || { left: 0, top: 80, right: 0, bottom: 80 };
    apply(window.AnnotateWindowPlace.place({ sel, content: contentRect(), view: view(), size: s }));
    return win;
  }

  function close(owner) {
    if (!win || win.hidden || !current) return;
    if (owner && current.owner !== owner) return;
    const was = current;
    const hadFocus = win.contains(document.activeElement);
    current = null;
    win.hidden = true;
    win.querySelector(".comment-window-body").replaceChildren();
    try { was.onClose && was.onClose(); } catch (_) {}
    // Hiding the window drops focus to <body> (a clicked × keeps it until the
    // next style pass), and the next Tab would start from the top of the
    // page: hand it back to the part.
    const a = document.activeElement;
    if (hadFocus && (!a || a === document.body || win.contains(a)) && was.home && typeof focusHome === "function") {
      focusHome(was.home());
    }
  }

  // Typed text or a pasted picture: either is the reader's work, and both
  // openers (selection.js openComposer, script.js openAnnotation) ask this
  // before a window is replaced.
  function hasWords() {
    if (!win || win.hidden) return false;
    const ta = win.querySelector("textarea");
    return !!((ta && ta.value.trim()) || win.querySelector(".paste-thumb"));
  }

  // The answer to "why did nothing open": the open window, pulsed, with the
  // caret in it. Restarted, so a second refusal pulses too.
  function call() {
    if (!win || win.hidden) return;
    win.classList.remove("is-calling");
    void win.offsetWidth;
    win.classList.add("is-calling");
    setTimeout(() => win && win.classList.remove("is-calling"), 1200);
    win.querySelector("textarea")?.focus({ preventScroll: true });
  }

  window.AnnotateCommentWindow = {
    open, close, hasWords, call,
    isOpen: () => !!(win && !win.hidden && current),
    owner: () => (current ? current.owner : null),
    element: () => win,
  };
})();
