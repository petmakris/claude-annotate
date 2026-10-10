/* The one control: select any words and act on exactly them.
 *
 * A selection opens a small menu above it: Comment, Delete, Compact. Select
 * any part of a section's title and the menu acts on the whole section.
 * Nothing else on the page takes feedback, and a plain click does nothing,
 * so there is one way to react and it is always the same.
 *
 * The menu never edits the page's DOM around the words. Marks are text
 * anchors kept in the round (subunits.js) and painted by AnnotateAnchors.
 * The comment chips are the only thing inserted into a block, and
 * AnnotateAnchors skips them when counting text. The comment box opens in
 * the floating comment window (comment-window.js), outside the text.
 */
(function () {
  "use strict";

  const ICON = {
    comment: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    compact: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
    remove: '<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  };
  const ACTS = [
    ["comment", "Comment", "c"],
    ["delete", "Delete — removed for good (undo until you submit)", "d"],
    ["compact", "Compact — off the page; its point folds into what stays", "x"],
  ];
  // A comment is the reader's own words, so the menu says so when a new mark
  // would take them away.
  const KIND_WORD = { delete: "a delete", compact: "a compact", comment: "your comment" };
  // A click on these is theirs, not a request for the menu. A drag that ends
  // on one is still a selection: excluded() judges where it starts and ends.
  const IGNORE = "button, a, input, textarea, select, label, .sel-menu, .comment-window, "
    + ".sel-chip, .page-header, footer, #round-dock, .code-col";
  const OWN = ".sel-menu, .comment-window, .sp-card";
  // Focus inside one of these means the keys are the panel's, not the page's.
  const PANELS = ".page-header, [role='dialog'], .menu-panel, #round-dock, .comment-window";

  // A finger has no hover and no reliable mouseup: the menu becomes a sheet
  // at the bottom of the screen, opened from selectionchange.
  const touch = window.matchMedia("(hover: none) and (pointer: coarse)");
  const WORD = { comment: "Comment", delete: "Delete", compact: "Compact" };

  let menu = null, target = null, suppressUntil = 0, lastPoint = null;
  // Where focus was when the keyboard opened the menu; it goes back there
  // when the menu closes with focus inside it.
  let returnTo = null;
  const extras = [];

  function A() { return window.AnnotateAnchors; }
  function S() { return window.AnnotateSubunits; }
  function enabled() {
    const b = document.body;
    return !!(A() && A().supported() && S())
      && !b.classList.contains("read-only") && b.dataset.highlighter !== "on";
  }
  function sectionOf(node) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    return el ? el.closest("main.prose section.block[data-block-id]") : null;
  }
  function inTitle(node) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    return !!(el && el.closest(".block-label"));
  }
  // A choice is answered with its own controls, and a picture is commented
  // whole through its title: neither body takes a selection.
  const WHOLE_ONLY = ["choice", "sequence", "diagram", "flowchart"];
  function excluded(node, section) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!el) return true;
    if (el.closest(".code-col")) return true;
    // The section's editor (edit.js): its Rich view is a .block-content too.
    if (el.closest(".ed-host, .ed-bar")) return true;
    if (section && WHOLE_ONLY.includes(section.dataset.kind) && el.closest(".block-content")) return true;
    return !(el.closest(".block-content") || el.closest(".block-label"));
  }

  function typing(a) {
    return a instanceof HTMLInputElement || a instanceof HTMLTextAreaElement
      || !!(a && a.isContentEditable);
  }
  function restoreFocus(to) {
    if (to && to !== document.body && document.contains(to)) to.focus({ preventScroll: true });
    else if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  }

  function close() {
    const had = !!(menu && menu.contains(document.activeElement));
    const back = returnTo;
    returnTo = null;
    if (menu) menu.remove();
    menu = null;
    if (had) restoreFocus(back);
    if (target && target.whole) delete target.section.dataset.selScope;
    target = null;
    A()?.setScope(null);
  }

  // A maximised card (fixed, above a scrim) or a native full-screen element
  // paints over anything appended to <body>, so the menu goes inside it.
  function layer() {
    return document.fullscreenElement
      || document.querySelector("main.prose section.block.is-maximized")
      || null;
  }

  // Coordinates are viewport ones until the end: then they are made relative
  // to whichever box holds the menu, and to its scroll.
  function place(rect) {
    const w = menu.offsetWidth, h = menu.offsetHeight;
    const host = menu.parentElement === document.body ? null : menu.parentElement;
    const box = host ? host.getBoundingClientRect()
      : { left: 0, top: 0, right: document.documentElement.clientWidth,
          bottom: document.documentElement.clientHeight };
    const lo = box.top + 8, hi = box.bottom - h - 8;
    const x = Math.min(Math.max(rect.left + rect.width / 2 - w / 2, box.left + 8), box.right - w - 8);
    const above = rect.top - h - 8, below = rect.bottom + 8;
    let y;
    if (above >= lo && above <= hi) y = above;
    else if (below >= lo && below <= hi) y = below;
    else {
      // A selection taller than the screen: neither side of it is visible,
      // so the menu goes where the mouse let go.
      const py = lastPoint ? lastPoint.y : (box.top + box.bottom) / 2;
      y = py - h - 12 >= lo ? py - h - 12 : py + 12;
      y = Math.min(Math.max(y, lo), Math.max(hi, lo));
    }
    if (host) {
      menu.style.left = `${x - box.left - host.clientLeft + host.scrollLeft}px`;
      menu.style.top = `${y - box.top - host.clientTop + host.scrollTop}px`;
    } else {
      menu.style.left = `${x + window.scrollX}px`;
      menu.style.top = `${y + window.scrollY}px`;
    }
  }

  function button(act, label, key, icon, sheet) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.act = act;
    b.innerHTML = icon + (act === "remove" ? "<span>Remove</span>"
      : sheet && WORD[act] ? `<span>${WORD[act]}</span>` : "");
    b.title = key ? `${label} (${key})` : label;
    b.setAttribute("aria-label", b.title);
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", (e) => { e.stopPropagation(); act === "remove" ? removeCurrent() : run(act); });
    return b;
  }

  function open(t, rect, opts) {
    const back = returnTo;
    close();
    returnTo = back;
    target = t;
    menu = document.createElement("div");
    const sheet = touch.matches;
    menu.className = sheet ? "sel-menu sel-sheet" : "sel-menu";
    menu.setAttribute("role", "toolbar");
    menu.setAttribute("aria-label", "Selection actions");
    if (sheet && t) {
      const q = document.createElement("div");
      q.className = "sel-quote";
      const text = t.anchor ? t.anchor.selected_text
        : (t.section.dataset.label || "").trim();
      q.textContent = text.length > 140 ? text.slice(0, 139) + "…" : text;
      menu.appendChild(q);
    }
    if (sheet) {
      // A sheet has no outside to click on iOS (a tap on blank text fires no
      // mousedown), so it carries its own way out.
      const x = document.createElement("button");
      x.type = "button";
      x.className = "sel-close";
      x.setAttribute("aria-label", "Close");
      x.innerHTML = ICON.remove;
      x.addEventListener("mousedown", (e) => e.preventDefault());
      x.addEventListener("click", (e) => { e.stopPropagation(); close(); });
      menu.appendChild(x);
    }
    if (opts.state) {
      const s = document.createElement("span");
      s.className = "sel-state";
      s.textContent = opts.state;
      menu.appendChild(s);
    }
    if (opts.removable) menu.appendChild(button("remove", "Remove this mark", "", ICON.remove, sheet));
    if (opts.state || opts.removable) {
      const sep = document.createElement("span");
      sep.className = "sel-sep";
      menu.appendChild(sep);
    }
    for (const [act, label, key] of ACTS) menu.appendChild(button(act, label, key, ICON[act], sheet));
    // Edit, Explain and Read act on one part's words, so words across a
    // heading get none of them.
    if (extras.length && t && !(t.anchor && t.anchor.spans)) {
      const sep = document.createElement("span");
      sep.className = "sel-sep";
      menu.appendChild(sep);
      for (const fn of extras) { try { fn(t, menu); } catch (_) {} }
      // A divider with nothing after it is noise: drop it if no extra added a button.
      if (menu.lastElementChild === sep) sep.remove();
    }
    // One tab stop: the arrows move between the buttons, Tab leaves.
    const buttons = [...menu.querySelectorAll("button")];
    buttons.forEach((b, i) => { b.tabIndex = i === 0 ? 0 : -1; });
    menu.addEventListener("keydown", (ev) => {
      const bs = [...menu.querySelectorAll("button")];
      const i = bs.indexOf(document.activeElement);
      if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
        if (!bs.length) return;
        ev.preventDefault(); ev.stopPropagation();
        const n = bs[(Math.max(i, 0) + (ev.key === "ArrowRight" ? 1 : bs.length - 1)) % bs.length];
        bs.forEach((b) => { b.tabIndex = b === n ? 0 : -1; });
        n.focus();
      } else if (ev.key === "Tab") {
        // Back to where the reader was, and Tab carries on from there.
        close();
      }
    });
    const host = layer();
    if (host) menu.classList.add("sel-menu-layered");
    (host || document.body).appendChild(menu);
    if (!sheet) place(rect);
    if (t && t.whole) { t.section.dataset.selScope = ""; A().setScope(t.range); }
  }

  function kindOf(id) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(id)}"]`)?.dataset.kind || "markdown";
  }

  function openForSelection(range) {
    const s1 = sectionOf(range.startContainer), s2 = sectionOf(range.endContainer);
    if (!s1 && !s2) return close();
    if (s1 && s1 === s2) {
      if (inTitle(range.startContainer) && inTitle(range.endContainer)) return openWhole(s1);
      if (excluded(range.startContainer, s1) && excluded(range.endContainer, s1)) return close();
    }
    // Within one part or across a heading: one anchor per part the words
    // touch, leaving out parts that take no selection (a picture, a question).
    const parts = window.AnnotateSpans.textOnly(A().anchorsAcross(range), kindOf, WHOLE_ONLY);
    if (!parts.length) return close();
    const anchor = window.AnnotateSpans.withSpans(parts);
    const section = sectionOf(range.startContainer) && parts[0].block_id === sectionOf(range.startContainer).dataset.blockId
      ? sectionOf(range.startContainer)
      : document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(parts[0].block_id)}"]`);
    const all = S().overlapping(anchor);
    // The very words of an existing mark are that mark, not something a new
    // one would replace: say what they are marked, and offer to take it back.
    const same = all.find((x) => sameWords(x.m, anchor));
    const over = all.filter((x) => x !== same);
    const t = { section, anchor, range: range.cloneRange(), whole: false, fromSel: true };
    if (same && !over.length) {
      return open({ ...t, key: same.key }, range.getBoundingClientRect(),
                  { state: `Marked ${same.m.kind}`, removable: true });
    }
    const state = over.length ? `Replaces ${KIND_WORD[over[0].m.kind] || "a mark"}` : "";
    open(t, range.getBoundingClientRect(), { state });
  }

  // Two marks are the same words when they cover the same parts and, in
  // each, the same stretch of its prose.
  function sameWords(a, b) {
    const pa = window.AnnotateSpans.partsOf(a), pb = window.AnnotateSpans.partsOf(b);
    if (pa.length !== pb.length) return false;
    return pa.every((p, i) => {
      const q = pb[i];
      if (p.block_id !== q.block_id) return false;
      const s = document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(p.block_id)}"]`);
      const x = s && A().locate(s, p), y = s && A().locate(s, q);
      return !!(x && y && x[0] === y[0] && x[1] === y[1]);
    });
  }

  function openWhole(section) {
    getSelection()?.removeAllRanges();
    const head = section.querySelector(".block-label");
    const range = document.createRange();
    range.selectNodeContents(section);
    const mark = S().blockMark(section.dataset.blockId);
    const state = mark ? `Part marked ${mark.kind}` : "Whole part";
    open({ section, anchor: null, range, whole: true },
         (head || section).getBoundingClientRect(), { state, removable: !!mark });
    // A double-click on the title fires two mouseups; the second must not
    // close what the first opened.
    suppressUntil = Date.now() + 400;
  }

  function openForMark(section, hit) {
    // A mark across a heading is found again by its words in this part.
    const part = window.AnnotateSpans.partsOf(hit.m).find((p) => p.block_id === section.dataset.blockId);
    const range = part && A().rangeFor(section, part);
    if (!range) return close();
    open({ section, anchor: hit.m, range, whole: false, key: hit.key },
         range.getBoundingClientRect(), { state: `Marked ${hit.m.kind}`, removable: true });
  }

  function removeCurrent() {
    if (!target) return;
    if (target.whole) {
      const m = S().blockMark(target.section.dataset.blockId);
      if (m) S().toggleBlockMark(target.section.dataset.blockId, m.kind);
    } else if (target.key) {
      S().removeMarkByKey(target.key);
    }
    close();
  }

  function run(act) {
    if (!target) return;
    const t = target;
    if (t.whole) {
      close();
      if (act === "comment") window.AnnotatePage?.openComment(t.section.dataset.blockId);
      else S().toggleBlockMark(t.section.dataset.blockId, act);
      return;
    }
    getSelection()?.removeAllRanges();
    close();
    if (act === "comment") openComposer(t.section, t.anchor, t.range);
    else S().setSpanMark(t.anchor, act);
  }

  // ── the comment box for a span ──────────────────────────────────────────
  // It opens in the one comment window (comment-window.js), which lives on
  // <body>: a rewrite of the part cannot take it away. `draft` is what the
  // box is about, kept so Save knows which words it was written on.
  let composer = null, draft = null;
  const W = () => window.AnnotateCommentWindow;
  function syncDraftLock() {
    const on = !!composer && W().owner() === "span" && W().hasWords();
    if (document.body.classList.contains("has-sel-draft") === on) return;
    document.body.classList.toggle("has-sel-draft", on);
    S()?.renderDock();
  }
  function closeComposer() {
    W().close("span");
  }
  function homeFor(anchor) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(anchor.block_id)}"]`);
  }

  // The comment already on exactly these words, if any.
  function commentOn(anchor) {
    const hit = S().overlapping(anchor).find((x) => x.m.kind === "comment" && x.m.text
      && sameWords(x.m, anchor));
    return hit ? hit.m : null;
  }

  function openComposer(section, anchor, range, initial) {
    if (W().isOpen() && W().hasWords()) { W().call(); return; }
    const box = document.createElement("div");
    box.className = "sel-body";
    const ta = document.createElement("textarea");
    const prior = commentOn(anchor);
    ta.value = initial != null ? initial : (prior ? prior.text : "");
    // Pictures pasted here ride on the mark, as a part's comment's do.
    let images = (prior && prior.images) || [];
    const strip = attachPaste(ta, images, (list) => { images = list; syncDraftLock(); });
    ta.placeholder = "Ask or push back on this…";
    ta.setAttribute("aria-label", "Comment on the selected words");
    ta.addEventListener("input", () => { if (draft) draft.text = ta.value; syncDraftLock(); });
    const row = document.createElement("div");
    row.className = "sel-row";
    row.innerHTML = '<span class="card-submit-hint"><kbd>↩</kbd> to add · '
      + '<kbd>⇧</kbd><kbd>↩</kbd> new line · paste an image to attach</span>';
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "comment-cancel"; cancel.textContent = "Cancel";
    const add = document.createElement("button");
    add.type = "button"; add.className = "card-submit-btn"; add.textContent = "Add to round";
    // The words may have been rewritten while the window was open. Still
    // there: the comment goes on them. Gone, part still there: it goes on
    // the part, quoting what it was about. Part gone too: the general box.
    const commit = () => {
      const v = ta.value.trim();
      const parts = anchor.spans || [anchor];
      closeComposer();
      if (!v) return;
      const home = homeFor(parts[0]);
      const live = parts.every((p) => { const s = homeFor(p); return s && A().rangeFor(s, p); });
      if (live) S().setSpanMark(anchor, "comment", v, images);
      else if (home) {
        const q = anchor.selected_text.length > 120 ? anchor.selected_text.slice(0, 117) + "…" : anchor.selected_text;
        S().pinComment({ block_id: parts[0].block_id, text: `On the passage that read "${q}": ${v}`, images });
      } else {
        document.dispatchEvent(new CustomEvent("annotate:orphan-comment",
          { detail: { text: v, quote: anchor.selected_text } }));
      }
      focusHome(home);
    };
    const dismiss = () => { closeComposer(); focusHome(homeFor((anchor.spans || [anchor])[0])); };
    cancel.addEventListener("click", (e) => { e.stopPropagation(); dismiss(); });
    add.addEventListener("click", (e) => { e.stopPropagation(); commit(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
    });
    row.append(cancel, add);
    box.append(ta, strip, row);
    window.AnnotateCommentWindow.open({ owner: "span", quote: anchor.selected_text, body: box,
      near: range.getBoundingClientRect(),
      home: () => homeFor((anchor.spans || [anchor])[0]),
      // A part's draft that waited while this box held words shows now.
      onClose: () => { composer = null; draft = null; syncDraftLock(); queueMicrotask(() => window.renderComments?.()); } });
    composer = box;
    draft = { anchor, text: ta.value };
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    syncDraftLock();
  }

  // ── events ──────────────────────────────────────────────────────────────
  document.addEventListener("mouseup", (ev) => {
    if (!enabled()) return;
    const on = ev.target instanceof Element ? ev.target : null;
    if (on && on.closest(OWN)) return;
    const x = ev.clientX, y = ev.clientY;
    setTimeout(() => {
      const sel = getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount) {
        lastPoint = { x, y };
        return openForSelection(sel.getRangeAt(0));
      }
      if (on && on.closest(IGNORE)) return;
      if (Date.now() < suppressUntil) return;
      const section = sectionOf(ev.target);
      if (section && inTitle(ev.target) && S().blockMark(section.dataset.blockId)) return openWhole(section);
      const hit = section && S().spanMarkAt(section, x, y);
      if (hit) return openForMark(section, hit);
      close();
    }, 0);
  });

  // The menu belongs to the selection it opened on. Once the reader selects
  // something else (keyboard, script, a drag with no mouseup here) it is
  // stale. A whole-section or mark menu has no live selection to compare.
  // A finger that lands on the sheet may collapse the selection on touchstart,
  // before its click: while one is down on the sheet, the selection is not
  // what closes it.
  let pressing = false, pressTimer = 0;
  function press(on) {
    pressing = on;
    clearTimeout(pressTimer);
    if (on) pressTimer = setTimeout(() => { pressing = false; }, 1000);
  }
  document.addEventListener("selectionchange", () => {
    if (pressing || !menu || !target || !target.fromSel) return;
    const sel = getSelection();
    const r = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
    const t = target.range;
    if (!r || r.startContainer !== t.startContainer || r.startOffset !== t.startOffset
        || r.endContainer !== t.endContainer || r.endOffset !== t.endOffset) close();
  });

  // Touch selection (long-press, drag the handles) ends in no reliable
  // mouseup, so the sheet opens once the selection has been still a moment.
  let settle = 0;
  document.addEventListener("selectionchange", () => {
    clearTimeout(settle);
    if (!touch.matches || !enabled()) return;
    settle = setTimeout(() => {
      if (!touch.matches || !enabled()) return;
      const sel = getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount) {
        const r = sel.getRangeAt(0), t = target && target.range;
        if (menu && target.fromSel && t && r.startContainer === t.startContainer
            && r.startOffset === t.startOffset && r.endContainer === t.endContainer
            && r.endOffset === t.endOffset) return;
        return openForSelection(r);
      }
      // Only a menu born of a selection goes with it; a whole-section or mark
      // sheet has already cleared the selection itself.
      if (!pressing && menu && target && target.fromSel && !menu.contains(document.activeElement)) close();
    }, 350);
  });

  // The sheet closes on a touch outside it, by pointer events: iOS fires no
  // mousedown for a tap on blank text.
  document.addEventListener("pointerdown", (ev) => {
    if (!menu || !menu.classList.contains("sel-sheet")) return;
    const inside = ev.target instanceof Element && ev.target.closest(".sel-menu");
    if (inside) return press(true);
    close();
  }, true);
  document.addEventListener("click", () => { if (pressing) setTimeout(() => press(false), 0); }, true);
  document.addEventListener("pointercancel", () => press(false), true);

  document.addEventListener("mousedown", (ev) => {
    if (menu && !(ev.target instanceof Element && ev.target.closest(".sel-menu"))) close();
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const a = document.activeElement;
    if (typing(a)) return;
    if (menu) {
      // stopImmediatePropagation: maximize.js listens on the same node in the
      // same phase, and one Esc must not close the menu and the card both.
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopImmediatePropagation(); close(); return; }
      // r is Explain, Shift+r is Read as written; both belong to speech.js's
      // buttons, and do nothing when those are missing or disabled. Shift
      // decides, not the letter's case: Caps Lock alone is still Explain.
      if (ev.key.toLowerCase() === "r") {
        ev.preventDefault(); ev.stopImmediatePropagation();
        const live = (a) => { const b = menu && menu.querySelector(`button[data-act="${a}"]`); return b && !b.disabled ? b : null; };
        if (!ev.shiftKey) { live("explain")?.click(); return; }
        // The phone sheet shows Read as written outright; the bar keeps it
        // behind the chevron.
        const read = live("read");
        if (read) { read.click(); return; }
        const more = live("voice-more");
        if (!more) return;
        more.click();
        live("read")?.click();
        return;
      }
      // e is Edit, which edit.js adds to the menu and may have disabled.
      if (ev.key === "e") {
        ev.preventDefault(); ev.stopImmediatePropagation();
        const b = menu.querySelector('button[data-act="edit"]');
        if (b && !b.disabled) b.click();
        else if (b) window.AnnotateEdit?.say?.(b.title);
        // No ✎ at all: a section that is not text, which says so.
        else if (target && target.section) window.AnnotateEdit?.sayWhy?.(target.section);
        return;
      }
      const act = { c: "comment", d: "delete", x: "compact" }[ev.key];
      if (!act) return;
      // An open menu owns these keys: they must not fall through to
      // script.js's `c`, which would open a comment behind it.
      ev.preventDefault(); ev.stopImmediatePropagation();
      if (target) run(act);
      return;
    }
    // No menu, no selection: d and x act on the block j/k chose, r
    // explains it (Shift+r reads it as written), and e opens it in the
    // editor. `c` is script.js's, and stays where it is.
    const speak = ev.key.toLowerCase() === "r";
    if (ev.key !== "d" && ev.key !== "x" && ev.key !== "e" && !speak) return;
    // e is not a selection key: with the highlighter on it still answers,
    // with the reason it cannot open (edit.js's refusal).
    const ok = ev.key === "e" ? !document.body.classList.contains("read-only") : enabled();
    if (!ok || getSelection()?.toString()) return;
    // Focus in a read-aloud card still leaves these keys to the block: the
    // card keeps only Space and Esc.
    if (a && a !== document.body && a.closest(PANELS)) return;
    const id = window.AnnotateKeyboard?.focusedId?.();
    if (!id) return;
    if (ev.key === "e") {
      if (!window.AnnotateEdit) return;
      ev.preventDefault(); ev.stopImmediatePropagation();
      window.AnnotateEdit.open(id);
      return;
    }
    if (speak) {
      const section = document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(id)}"]`);
      if (!section || !window.AnnotateSpeech?.playSection) return;
      ev.preventDefault(); ev.stopImmediatePropagation();
      window.AnnotateSpeech.playSection(section, ev.shiftKey ? "read" : "explain");
      return;
    }
    ev.preventDefault();
    S().toggleBlockMark(id, ev.key === "d" ? "delete" : "compact");
  }, true);

  // ── the keyboard's way in ───────────────────────────────────────────────
  // A selection made with Shift and the arrows (or Home, End, the page keys)
  // is done when Shift comes up: the menu opens on it with focus on its
  // first button. Only if Shift changed the selection, though: Shift+Tab out
  // of the menu, or a Shift press over a selection left from before, is not
  // a new selection.
  function sameRange(r, t) {
    return !!t && r.startContainer === t.startContainer && r.startOffset === t.startOffset
      && r.endContainer === t.endContainer && r.endOffset === t.endOffset;
  }
  function openByKeyboard(range) {
    if (!sectionOf(range.startContainer) && !sectionOf(range.endContainer)) return;
    const origin = document.activeElement;
    lastPoint = null;
    openForSelection(range);
    if (!menu) return;
    returnTo = origin;
    menu.querySelector("button[tabindex='0']")?.focus({ preventScroll: true });
  }
  let atShift = null;
  function snapshot() {
    const sel = getSelection();
    if (!sel || !sel.rangeCount) return null;
    const r = sel.getRangeAt(0);
    return { startContainer: r.startContainer, startOffset: r.startOffset,
             endContainer: r.endContainer, endOffset: r.endOffset };
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Shift" && !ev.repeat) atShift = snapshot();
  }, true);
  document.addEventListener("keyup", (ev) => {
    if (ev.key !== "Shift") return;
    const before = atShift;
    atShift = null;
    if (touch.matches || !enabled()) return;
    const a = document.activeElement;
    if (typing(a) || (menu && menu.contains(a))) return;
    if (a && a !== document.body && a.closest(PANELS)) return;
    const sel = getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const r = sel.getRangeAt(0);
    if (sameRange(r, before)) return;
    // Shift-click: the mouse already opened the menu on this selection.
    if (menu && target && target.fromSel && sameRange(r, target.range)) return;
    openByKeyboard(r);
  });
  // A rewrite replaces the section the menu points into.
  document.addEventListener("annotate:rendered", () => {
    if (target && !document.contains(target.section)) close();
  });

  window.AnnotateSelection = {
    isOpen: () => !!menu,
    close,
    registerAction(fn) { if (typeof fn === "function" && extras.indexOf(fn) < 0) extras.push(fn); },
  };
})();
