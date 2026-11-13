// annotate page code, part 6 of 9 (see script.js): the page around the
// blocks — Done, the general composer, the top-bar panels, the toolbar, the
// keyboard review and the fold chords.

// ── Done button ────────────────────────────────────────────────────────────

// Done, and its way back. Finishing a session was a one-way door in the
// page: the daemon has had POST /s/<sid>/api/unfinish all along and the CLI
// exposes it as `webcompanion unfinish`, but nothing in the document did —
// so a Done pressed a moment too early meant dropping to a terminal to
// recover a session you were looking at.
//
// Deliberately NOT a confirm on the way back. Finishing tells Claude to
// resume and so asks first; reopening only puts the controls back, and the
// round that was already submitted stays submitted either way.
const doneBtn = document.getElementById("done-btn");
if (doneBtn) {
  doneBtn.addEventListener("click", async () => {
    if (document.body.classList.contains("session-finished")) {
      doneBtn.disabled = true;
      const r = await fetch("api/unfinish", { method: "POST" }).catch(() => null);
      if (r && r.ok) window.location.reload();
      else doneBtn.disabled = false;
      return;
    }
    if (!window.confirm("Mark this annotation round as done? Claude will resume.")) return;
    doneBtn.disabled = true;
    const ok = await WebCompanion.api.finish();
    if (ok) {
      window.location.reload();
    } else {
      doneBtn.disabled = false;
    }
  });
}

// The button is server-rendered as "Done"; only the page knows the session
// has since ended, so the label follows the state rather than the markup.
(function trackFinishedState() {
  const btn = document.getElementById("done-btn");
  if (!btn) return;
  const sync = () => {
    const finished = document.body.classList.contains("session-finished");
    btn.textContent = finished ? "Reopen" : "Done";
    btn.title = finished
      ? "This round is closed. Reopen it to mark or comment on more parts."
      : "Mark this round as done — Claude resumes";
    btn.disabled = false;
  };
  new MutationObserver(sync).observe(document.body,
    { attributes: true, attributeFilter: ["class"] });
  sync();
})();

// ── General composer (page-level, non-block comment) ────────────────────────
// A persistent textarea that sends a block_id-null comment straight to Claude
// Code. Unlike block comments it leaves no inline card; status is reported in
// the composer's own status line and resolved when Claude acks the event.
(function initGeneralComposer() {
  const input = document.getElementById("general-input");
  const sendBtn = document.getElementById("general-send");
  const statusEl = document.getElementById("general-status");
  if (!input || !sendBtn) return;

  // Per session, not per response: an unsent general comment is a turn in
  // the conversation, and a new response arriving must not lose it.
  const KEY = `annotate.general.${location.pathname}`;
  try { input.value = localStorage.getItem(KEY) || ""; } catch {}

  const sync = () => {
    sendBtn.disabled = input.value.trim() === "";
    try {
      if (input.value) {
        localStorage.setItem(KEY, input.value);
        window.AnnotateStorage.touch(KEY);
      } else localStorage.removeItem(KEY);
    } catch {}
  };
  sync();

  function send() {
    const text = input.value.trim();
    if (!text) return;
    sendBtn.disabled = true;
    // Read before sending: the page locks itself the moment the daemon has
    // this comment, so asking afterwards always answered "busy", and every
    // comment was reported as queued behind some other update.
    const queued = document.body.classList.contains("is-busy");
    const payload = { block_id: null, step_id: null, type: "comment", text, selected_text: "", images: [] };
    WebCompanion.api.submit(payload).then((res) => {
      const eventId = res && res.event_id;
      if (eventId) pendingEvents.set(String(eventId), { general: true });
      input.value = "";
      try { localStorage.removeItem(KEY); } catch {}
      sync();
      // The server queues events, so a send while Claude is mid-update is
      // safe — but say so, instead of implying an immediate response.
      if (statusEl) {
        statusEl.textContent = queued
          ? "queued — Claude will get to it after the current update…"
          : "sent — Claude is responding…";
      }
    }).catch(() => {
      sendBtn.disabled = false;
      if (statusEl) statusEl.textContent = "send failed — try again";
    });
  }

  input.addEventListener("input", sync);
  // A pending comment whose whole block Claude removed has no block left to
  // go to in a round. It comes here rather than vanishing (subunits.js
  // pruneMarks), quoting what it was about, one press away from sending.
  document.addEventListener("annotate:orphan-comment", (ev) => {
    const { text, quote } = ev.detail || {};
    if (!text) return;
    const quoted = quote ? quote.split("\n").map(l => "> " + l).join("\n") + "\n\n" : "";
    input.value = (input.value.trim() ? input.value.trimEnd() + "\n\n" : "") + quoted + text;
    sync();
    if (statusEl) {
      statusEl.textContent =
        "A part you commented on was removed; your comment moved here.";
    }
  });
  // Same chord as the comment cards: Enter is a newline, ⌘/Ctrl+Enter sends.
  // Plain-Enter-to-send once cost a user a multi-line answer mid-compose.
  input.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); send(); }
  });
  sendBtn.addEventListener("click", send);
})();

// ── Top-bar panels ───────────────────────────────────────────────────────
// Two one-shot controls used to hold permanent space above the first word: a
// full-width "comment on the whole response" trigger row, and a centred
// legend pill. Both now hang off icon buttons in the page header.
//
// They open differently, on purpose, because they are used differently. The
// composer is somewhere you WRITE, so it opens as a band of the bar with the
// full column width; pushing the document down for as long as you are typing
// is fine. The legend is something you GLANCE at, so it opens as a popover
// over the document — nudging every sentence down to answer "what does the
// trash button do?" would be absurd. Same shell here, different geometry in
// the stylesheet; see .general-composer and .legend-pop in style.css.
// Runs at parse time, alongside initTopPanels below: the controls are
// server-rendered, so they exist before any block does, and painting the
// stored preference now avoids a flash of the default measure.
wireViewControls();

(function initTopPanels() {
  // Each panel is (toggle button, panel element, what to focus on open).
  const panels = [
    { btn: document.getElementById("composer-toggle"),
      el: document.getElementById("general-composer"),
      focus: () => document.getElementById("general-input") },
    // The two popovers: the status pill's (what Watching means, and the
    // resume command when nothing watches) and the toolbar's Keys.
    { btn: document.getElementById("status-toggle"),
      el: document.getElementById("status-pop"),
      focus: () => null, dismissOnOutsideClick: true },
    { btn: document.getElementById("keys-toggle"),
      el: document.getElementById("keys-pop"),
      focus: () => null, dismissOnOutsideClick: true },
  ].filter((p) => p.btn && p.el);
  if (!panels.length) return;

  const isOpen = (p) => !p.el.hidden;

  function close(p, { restoreFocus = false } = {}) {
    if (!isOpen(p)) return;
    // Move focus off the panel BEFORE hiding it: blurring a display:none
    // element drops focus to <body>, and the Esc-to-close path is meant to
    // hand the keyboard back to the button you opened it with.
    const inside = p.el.contains(document.activeElement);
    p.el.hidden = true;
    p.btn.setAttribute("aria-expanded", "false");
    if (restoreFocus || inside) p.btn.focus();
  }

  function open(p) {
    // One at a time. Two panels open at once would stack a popover on top of
    // a band and leave two toggles lit with no way to tell which owns what.
    panels.forEach((other) => { if (other !== p) close(other); });
    if (isOpen(p)) return;
    p.el.hidden = false;
    p.btn.setAttribute("aria-expanded", "true");
    p.focus()?.focus();
  }

  const toggle = (p) => (isOpen(p) ? close(p, { restoreFocus: true }) : open(p));

  panels.forEach((p) => {
    p.btn.addEventListener("click", (e) => { e.preventDefault(); toggle(p); });
  });

  // Esc closes whichever panel is open, and takes precedence over the page's
  // other two Esc handlers (search.js clears the query, subunits.js closes a
  // per-unit composer). Capture phase + stopPropagation is what buys that
  // precedence, and it is a deliberate ordering, not just defensiveness: an
  // open panel is the most recent thing the user opened, so it is what they
  // mean by "close this". Both other handlers are already conditional on
  // focus being in their own field, and neither can be reached without a
  // panel ALSO being open, so nothing is stranded — the early return below
  // leaves their Esc untouched whenever no panel is open, which is the
  // overwhelmingly common case.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open_ = panels.find(isOpen);
    if (!open_) return;
    e.preventDefault();
    e.stopPropagation();
    close(open_, { restoreFocus: true });
  }, true);

  // Click-outside, for the popovers only. The composer is deliberately
  // exempt: it can hold half-written text, and losing that to a stray click
  // on the document would be the worst bug in this file. That exemption is
  // now carried by a per-panel flag rather than by naming the legend, so a
  // new popover opts in instead of being silently left out.
  document.addEventListener("click", (e) => {
    panels.forEach((p) => {
      if (!p.dismissOnOutsideClick) return;
      if (!isOpen(p)) return;
      if (p.el.contains(e.target) || p.btn.contains(e.target)) return;
      close(p);
    });
  });

  // The `/` shortcut in search.js reaches the search field with
  // input.focus() and no click, so the click-outside handler above never
  // fires for it. Left alone, an open panel would only be masked by the
  // takeover's CSS (.header-actions > *:not(.header-search)) — still open
  // underneath — and would resurface the moment the field gives up the
  // takeover. `focusin` bubbles (plain `focus` does not), so one
  // document-level listener catches focus landing on the field however it
  // got there.
  document.addEventListener("focusin", (e) => {
    if (e.target.id !== "block-search") return;
    panels.forEach((p) => { if (isOpen(p)) close(p); });
  });

  // The `g` shortcut, unchanged in behaviour: it opens the composer from
  // anywhere you are not already typing.
  const composer = panels[0];
  document.addEventListener("keydown", (e) => {
    if (e.key !== "g" && e.key !== "G") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const active = document.activeElement;
    const typing = active instanceof HTMLInputElement ||
      active instanceof HTMLTextAreaElement ||
      (active && active.isContentEditable);
    if (typing) return;
    if (!composer || isOpen(composer)) return;
    e.preventDefault();
    open(composer);
  });
})();

// ── The highlighter's toolbar button ─────────────────────────────────────
// A proxy, because the real element stays in the header: the highlighter is
// a MODE, and its header button is the indicator that dragging over text now
// marks it, even with the toolbar hidden. This button clicks that one and
// mirrors it, which keeps highlighter.js the single owner of the state.
(function initHighlighterToolbarButton() {
  const row = document.getElementById("toolbar-highlighter");
  const btn = document.getElementById("highlighter-toggle");
  if (!row || !btn) return;
  row.addEventListener("click", (e) => { e.preventDefault(); btn.click(); });
  // It says "on" with colour alone (the stylesheet reads aria-pressed).
  function sync() {
    const on = btn.getAttribute("aria-pressed") === "true";
    row.setAttribute("aria-pressed", on ? "true" : "false");
    // highlighter.js hides the toggle when the browser has no Highlight
    // API. A button for a feature that cannot run is worse than none.
    row.hidden = btn.hidden;
  }
  new MutationObserver(sync).observe(
    btn, { attributes: true, attributeFilter: ["aria-pressed", "hidden"] });
  sync();
})();


// ── The settings drawer ──────────────────────────────────────────────────
// Every setting at once, opened from the toolbar's All settings. It is not one
// of initTopPanels' panels: those close each other, and the drawer must stay
// open while a popover or the composer is used. Its own Esc runs only when no panel took the key first.
(function initSettingsDrawer() {
  const drawer = document.getElementById("settings-drawer");
  const tile = document.getElementById("settings-open");
  if (!drawer || !tile) return;
  const scrim = document.getElementById("settings-scrim");
  const closeBtn = document.getElementById("settings-close");

  const isOpen = () => !drawer.hidden;
  function open() {
    drawer.hidden = false;
    if (scrim) scrim.hidden = false;
    document.body.classList.add("settings-open");
    tile.setAttribute("aria-expanded", "true");
    // The theme previews are painted when the drawer opens, not when it is
    // built: the code painter may not have been ready at parse time.
    repaintThemePreviews();
    closeBtn?.focus();
  }
  function close() {
    if (!isOpen()) return;
    const inside = drawer.contains(document.activeElement);
    drawer.hidden = true;
    if (scrim) scrim.hidden = true;
    document.body.classList.remove("settings-open", "width-dragging");
    tile.setAttribute("aria-expanded", "false");
    if (inside) tile.focus();
  }
  tile.addEventListener("click", (e) => { e.preventDefault(); isOpen() ? close() : open(); });
  closeBtn?.addEventListener("click", close);
  scrim?.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || !isOpen()) return;
    e.preventDefault();
    close();
  });

  // The highlighter's switch is a proxy for the header's toggle, like the
  // toolbar's button, so highlighter.js stays the one owner of "is it on".
  const sw = document.getElementById("settings-highlighter");
  const hlBtn = document.getElementById("highlighter-toggle");
  if (sw && hlBtn) {
    sw.addEventListener("click", () => hlBtn.click());
    const sync = () => {
      sw.setAttribute("aria-checked", hlBtn.getAttribute("aria-pressed") === "true" ? "true" : "false");
    };
    new MutationObserver(sync).observe(hlBtn, { attributes: true, attributeFilter: ["aria-pressed"] });
    sync();
  }
})();

// ── The toolbar ──────────────────────────────────────────────────────────
// The second bar holds every command and the three settings read most often.
// The header's toolbar button shows or hides it, and the choice is the
// reader's, kept for every annotate document. It shows until hidden.
(function initToolbar() {
  const bar = document.getElementById("toolbar");
  const btn = document.getElementById("toolbar-toggle");
  if (!bar || !btn) return;
  const KEY = "annotate.view:toolbar";
  const shown = () => {
    try { return localStorage.getItem(KEY) !== "hidden"; } catch (_) { return true; }
  };
  function paint() {
    const on = shown();
    document.body.dataset.toolbar = on ? "shown" : "hidden";
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "Hide the toolbar" : "Show the toolbar";
  }
  btn.addEventListener("click", () => {
    try { localStorage.setItem(KEY, shown() ? "hidden" : "shown"); } catch (_) {}
    paint();
  });
  paint();
})();

// ── Keyboard review (j / k / c / f) ──────────────────────────────────────
// Everything that decides anything in this page started with the mouse: the
// controls live in a strip that only exists while the pointer is over a
// 26px band, so working down a twelve-block plan meant twelve hover-and-aim
// cycles. The page already spoke some keyboard — `/` searches, `g` opens the
// composer, ⌘K⌘J folds — so what was missing was the middle of the
// vocabulary: move to the next block, and act on the one you are looking at.
//
// The cursor is one attribute, data-kb-focus on the section. Everything else
// follows from it in CSS, including revealing that block's control strip —
// which is how a keyboard user reaches controls that are otherwise painted
// in only by :hover.
(function initKeyboardReview() {
  let focusId = null;

  // Blocks in document order, minus anything a search has hidden: k and j
  // should walk what is on screen, not what the DOM still holds.
  function blocks() {
    return [...document.querySelectorAll("section.block[data-block-id]")]
      .filter((b) => b.offsetParent !== null);
  }

  function paint() {
    document.querySelectorAll("[data-kb-focus]").forEach((b) => {
      delete b.dataset.kbFocus;
    });
    if (!focusId) return null;
    const el = document.querySelector(
      `section.block[data-block-id="${cssEsc(focusId)}"]`);
    if (!el) { focusId = null; return null; }
    el.dataset.kbFocus = "1";
    return el;
  }

  function move(delta) {
    const list = blocks();
    if (!list.length) return;
    let i = list.findIndex((b) => b.dataset.blockId === focusId);
    // No cursor yet: j starts at the top of what you can see rather than at
    // the top of the document, because the first j after scrolling should
    // not throw you back to block one.
    if (i === -1) {
      const firstVisible = list.findIndex(
        (b) => b.getBoundingClientRect().bottom > 0);
      i = firstVisible === -1 ? 0 : firstVisible;
    } else {
      i = Math.min(list.length - 1, Math.max(0, i + delta));
    }
    focusId = list[i].dataset.blockId;
    const el = paint();
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function focused() {
    return focusId
      ? document.querySelector(`section.block[data-block-id="${cssEsc(focusId)}"]`)
      : null;
  }

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const active = document.activeElement;
    const typing = active instanceof HTMLInputElement ||
      active instanceof HTMLTextAreaElement ||
      (active && active.isContentEditable);
    if (typing) return;

    if (e.key === "j" || e.key === "k") {
      e.preventDefault();
      const delta = e.key === "j" ? 1 : -1;
      // Inside a collapsed choice queue, J/K walk its questions first; past
      // either end they fall through to the ordinary block walk.
      const next = focusId && window.AnnotateChoiceQueue?.stepFrom(focusId, delta);
      if (next) {
        focusId = next;
        const el = paint();
        if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      move(delta);
      return;
    }
    if (e.key === "c") {
      const el = focused();
      if (!el) return;
      e.preventDefault();
      // Same entry point the selection menu's Comment uses, so the two paths
      // cannot drift: step scoping, selection capture, the one-editor
      // rule and its refusal all behave identically.
      openAnnotation(el, "comment", {});
      return;
    }
    if (e.key === "f") {
      const el = focused();
      if (!el) return;
      const owner = window.AnnotateFolds.ownerOf(foldList(), el.dataset.blockId);
      if (!owner) return;
      e.preventDefault();
      const section = document.querySelector(`section.block[data-block-id="${cssEsc(owner)}"]`);
      setFolded(owner, !section.classList.contains("collapsed"));
      // On an untitled part the fold just hid the cursor's own part, so the
      // cursor moves to the heading that folded it, or j/k would start from
      // a part the reader cannot see.
      if (owner !== focusId) { focusId = owner; paint(); }
      return;
    }
    if (e.key === "Escape" && focusId) {
      // Last in the chain on purpose: the panel machinery binds Escape in
      // the capture phase and stops the event when a panel is open, so this
      // only ever runs when Escape had nothing else to close.
      focusId = null;
      paint();
    }
  });

  // A block Claude rewrites is replaced, not mutated, so the cursor has to
  // be repainted onto the new element or it silently disappears mid-round.
  window.AnnotateKeyboard = {
    repaint: paint,
    focusedId: () => focusId,
    // Used by the progress pill's "jump to the next untouched block": the
    // cursor and the jump must be the same cursor, or the page would have
    // two ideas of where you are.
    focusBlock: (id) => { focusId = id; paint(); },
  };
})();

// ── Fold-all / unfold-all chords (⌘K ⌘0 / ⌘K ⌘J) ─────────────────────────
// The user's VS Code fold bindings, verbatim. ⌘K arms a two-step chord —
// intercepted so the browser's address-bar focus never fires — and the
// second key acts on every titled part through the same localStorage
// keys the fold button uses, so a fold-all survives reload and a single
// fold click afterwards still toggles one part.
(function () {
  let armed = null; // timeout id while waiting for the second chord key
  const pill = document.createElement("div");
  pill.className = "chord-pill";
  pill.textContent = "⌘K …";
  pill.hidden = true;
  document.body.appendChild(pill);

  function disarm() {
    if (armed !== null) { clearTimeout(armed); armed = null; }
    pill.hidden = true;
  }

  function foldAll(collapsed) {
    document.querySelectorAll("main.prose section.block .block-heading").forEach((h) => {
      const section = h.closest("section.block");
      try {
        localStorage.setItem(collapseKey(section.dataset.blockId), collapsed ? "1" : "0");
      } catch (_) {}
    });
    applyFolds();
  }

  document.addEventListener("keydown", (e) => {
    const active = document.activeElement;
    const typing = active instanceof HTMLInputElement ||
      active instanceof HTMLTextAreaElement ||
      (active && active.isContentEditable);
    if (typing) { disarm(); return; }
    if (armed === null) {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey &&
          (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        pill.hidden = false;
        armed = setTimeout(disarm, 2000);
      }
      return;
    }
    // While armed, the modifier keys themselves (releasing/re-pressing ⌘
    // between the two strokes) neither resolve nor cancel the chord.
    if (e.key === "Meta" || e.key === "Control" || e.key === "Shift" || e.key === "Alt") return;
    if ((e.metaKey || e.ctrlKey) && e.key === "0") {
      e.preventDefault();
      foldAll(true);
    } else if ((e.metaKey || e.ctrlKey) && (e.key === "j" || e.key === "J")) {
      e.preventDefault();
      foldAll(false);
    }
    disarm();
  });

  document.getElementById("fold-all")?.addEventListener("click", (e) => {
    foldAll(e.currentTarget.dataset.next !== "unfold");
  });
})();
