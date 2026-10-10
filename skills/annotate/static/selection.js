/* The one control: select any words and act on exactly them.
 *
 * A selection opens a small menu above it: Comment, Delete, Compact. Select
 * any part of a section's title and the menu acts on the whole section.
 * Nothing else on the page takes feedback, and a plain click does nothing,
 * so there is one way to react and it is always the same.
 *
 * The menu never edits the page's DOM around the words. Marks are text
 * anchors kept in the round (subunits.js) and painted by AnnotateAnchors.
 * The comment box and the comment chips are the only things inserted into
 * a block, and AnnotateAnchors skips them when counting text.
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
  const IGNORE = "button, a, input, textarea, select, label, .sel-menu, .sel-composer, "
    + ".sel-chip, .page-header, footer, #round-dock, .inline-comments, .code-col";
  const OWN = ".sel-menu, .sel-composer, .sp-card";
  // Focus inside one of these means the keys are the panel's, not the page's.
  const PANELS = ".page-header, [role='dialog'], .menu-panel, #round-dock, .comment-card";

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
        : (t.section.getAttribute("aria-label") || "").trim();
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
    if (opts.refuse) {
      const m = document.createElement("span");
      m.className = "sel-state";
      m.textContent = "Select within one part";
      menu.appendChild(m);
    } else {
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
      if (extras.length && t) {
        const sep = document.createElement("span");
        sep.className = "sel-sep";
        menu.appendChild(sep);
        for (const fn of extras) { try { fn(t, menu); } catch (_) {} }
        // A divider with nothing after it is noise: drop it if no extra added a button.
        if (menu.lastElementChild === sep) sep.remove();
      }
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

  // Chrome's triple-click on a section's last paragraph ends the range at the
  // very start of the next section. Nothing of that section is selected, so
  // the end goes back to the end of the first section's content.
  function trimSpill(range) {
    const s1 = sectionOf(range.startContainer), s2 = sectionOf(range.endContainer);
    if (!s1 || !s2 || s1 === s2) return range;
    const lead = document.createRange();
    lead.setStart(s2, 0);
    lead.setEnd(range.endContainer, range.endOffset);
    const content = A().contentOf(s1);
    if (lead.toString() !== "" || !content) return range;
    const r = range.cloneRange();
    r.setEnd(content, content.childNodes.length);
    getSelection()?.removeAllRanges();
    getSelection()?.addRange(r);
    return r;
  }

  function openForSelection(range) {
    range = trimSpill(range);
    const s1 = sectionOf(range.startContainer), s2 = sectionOf(range.endContainer);
    if (!s1 && !s2) return close();
    if (s1 !== s2) return open(null, range.getBoundingClientRect(), { refuse: true });
    if (excluded(range.startContainer, s1) || excluded(range.endContainer, s1)) return close();
    if (inTitle(range.startContainer) || inTitle(range.endContainer)) return openWhole(s1);
    const anchor = A().anchorFor(s1, range);
    if (!anchor) return close();
    const all = S().overlapping(anchor);
    // The very words of an existing mark are that mark, not something a new
    // one would replace: say what they are marked, and offer to take it back.
    const same = all.find((x) => sameWords(s1, x.m, anchor));
    const over = all.filter((x) => x !== same);
    if (same && !over.length) {
      return open({ section: s1, anchor, range: range.cloneRange(), whole: false,
                    fromSel: true, key: same.key },
                  range.getBoundingClientRect(), { state: `Marked ${same.m.kind}`, removable: true });
    }
    const state = over.length ? `Replaces ${KIND_WORD[over[0].m.kind] || "a mark"}` : "";
    open({ section: s1, anchor, range: range.cloneRange(), whole: false, fromSel: true },
         range.getBoundingClientRect(), { state });
  }

  function sameWords(section, a, b) {
    const x = A().locate(section, a), y = A().locate(section, b);
    return !!(x && y && x[0] === y[0] && x[1] === y[1]);
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
    const range = A().rangeFor(section, hit.m);
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
  // `draft` is what the box is about, kept beside it so a rewrite that takes
  // the box away (it lives inside the block) can put the words back.
  let composer = null, draft = null;
  function syncDraftLock() {
    const ta = composer && document.contains(composer) && composer.querySelector("textarea");
    const on = !!(ta && ta.value.trim());
    if (document.body.classList.contains("has-sel-draft") === on) return;
    document.body.classList.toggle("has-sel-draft", on);
    // Submit sends only the round, and these words are not in it yet.
    S()?.renderDock();
  }
  function closeComposer() {
    if (composer) composer.remove();
    composer = null; draft = null;
    syncDraftLock();
  }
  // Out of the box, back to the section it was about (as a comment card does).
  function homeFocus(section) {
    const home = section && document.contains(section) ? section
      : document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(draft?.anchor.block_id || "")}"]`);
    focusHome(home);
  }
  // The comment already on exactly these words, if any.
  function commentOn(section, anchor) {
    const hit = S().overlapping(anchor).find((x) => x.m.kind === "comment" && x.m.text
      && sameWords(section, x.m, anchor));
    return hit ? hit.m.text : "";
  }

  function hostFor(range, section) {
    const content = A().contentOf(section);
    let el = range.endContainer.nodeType === 1 ? range.endContainer : range.endContainer.parentElement;
    const block = el && el.closest("li, p, pre, blockquote, table, h1, h2, h3, h4, h5, h6");
    return block && content.contains(block) ? block : content;
  }

  function openComposer(section, anchor, range, initial) {
    if (composer && !document.contains(composer)) composer = null;
    const busy = composer && composer.querySelector("textarea");
    if (busy && busy.value.trim()) {
      // Half-written words are not thrown away for a new selection: the box
      // that holds them comes back into view and says so.
      busy.focus();
      composer.scrollIntoView({ block: "nearest" });
      composer.classList.remove("sel-flash");
      void composer.offsetWidth;
      composer.classList.add("sel-flash");
      const c = composer;
      setTimeout(() => c.classList.remove("sel-flash"), 900);
      return;
    }
    closeComposer();
    const box = document.createElement("div");
    box.className = "sel-composer";
    const quote = document.createElement("div");
    quote.className = "sel-quote";
    quote.textContent = anchor.selected_text.length > 140
      ? anchor.selected_text.slice(0, 139) + "…" : anchor.selected_text;
    const ta = document.createElement("textarea");
    ta.value = initial != null ? initial : commentOn(section, anchor);
    ta.rows = 1;
    ta.placeholder = "Ask or push back on this…";
    ta.setAttribute("aria-label", "Comment on the selected words");
    const grow = () => { ta.style.height = "auto"; ta.style.height = `${ta.scrollHeight + 2}px`; };
    ta.addEventListener("input", () => { grow(); if (draft) draft.text = ta.value; syncDraftLock(); });
    const row = document.createElement("div");
    row.className = "sel-row";
    row.innerHTML = '<span class="card-submit-hint"><kbd>↩</kbd> to add · '
      + '<kbd>⇧</kbd><kbd>↩</kbd> new line · <kbd>Esc</kbd> to close</span>';
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "sel-cancel"; cancel.textContent = "Cancel";
    const add = document.createElement("button");
    add.type = "button"; add.className = "card-submit-btn"; add.textContent = "Add to round";
    const commit = () => {
      const v = ta.value.trim();
      closeComposer();
      if (v) S().setSpanMark(anchor, "comment", v);
      homeFocus(section);
    };
    const dismiss = () => { closeComposer(); homeFocus(section); };
    cancel.addEventListener("click", (e) => { e.stopPropagation(); dismiss(); });
    add.addEventListener("click", (e) => { e.stopPropagation(); commit(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
      if (e.key === "Escape") { e.preventDefault(); dismiss(); }
    });
    row.append(cancel, add);
    box.append(quote, ta, row);
    const host = hostFor(range, section);
    if (host === A().contentOf(section) || host.tagName === "LI") host.appendChild(box);
    else host.insertAdjacentElement("afterend", box);
    composer = box;
    draft = { anchor, text: ta.value };
    grow();
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    syncDraftLock();
  }

  // A rewrite took the box away with its block. Words in it are the reader's
  // and are never dropped: the box comes back on the same words if they are
  // still there, else the words go to the section's comment card, quoting
  // what they were about, and to the general box if even the section is gone.
  function rescueDraft() {
    const d = draft;
    composer = null; draft = null;
    const text = d && d.text.trim() ? d.text : "";
    if (!text) return syncDraftLock();
    const id = d.anchor.block_id;
    const section = document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(id)}"]`);
    const range = section && A().rangeFor(section, d.anchor);
    const fresh = range && A().anchorFor(section, range);
    if (fresh) {
      openComposer(section, fresh, range, d.text);
      return;
    }
    syncDraftLock();
    const quote = d.anchor.selected_text.length > 120
      ? d.anchor.selected_text.slice(0, 117) + "…" : d.anchor.selected_text;
    const moved = `On the passage that read "${quote}": ${d.text}`;
    if (section) window.AnnotatePage?.openComment(id);
    const ta = section && document.querySelector(
      `.inline-comments[data-for-block="${CSS.escape(id)}"] .comment-card textarea`);
    if (ta) {
      ta.value = ta.value.trim() ? `${ta.value.trimEnd()}\n\n${moved}` : moved;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    document.dispatchEvent(new CustomEvent("annotate:orphan-comment",
      { detail: { text: d.text, quote: d.anchor.selected_text } }));
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
      // The refusal menu has no target; its keys still must not fall through
      // to script.js's `c`, which would open a card behind it.
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
  // a new selection. One across sections opens nothing from here.
  function sameRange(r, t) {
    return !!t && r.startContainer === t.startContainer && r.startOffset === t.startOffset
      && r.endContainer === t.endContainer && r.endOffset === t.endOffset;
  }
  function openByKeyboard(range) {
    const s1 = sectionOf(range.startContainer);
    if (!s1 || s1 !== sectionOf(range.endContainer)) return;
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
  // A rewrite replaces the section the menu points into, and can take the
  // comment box with it.
  document.addEventListener("annotate:rendered", () => {
    if (target && !document.contains(target.section)) close();
    if (composer && !document.contains(composer)) rescueDraft();
  });

  window.AnnotateSelection = {
    isOpen: () => !!menu,
    close,
    registerAction(fn) { if (typeof fn === "function" && extras.indexOf(fn) < 0) extras.push(fn); },
  };
})();
