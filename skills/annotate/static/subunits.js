// annotate skill — the review round: every piece of content feedback on the
// page, batched into one submission.
//
// THREE CONTROLS, one vocabulary, at every scope. Each answers two questions:
// does the content survive, and if so what should Claude do to it?
//
//   delete   content is REMOVED from blocks.json, references re-threaded,
//            and treated as out of scope from then on. The only control that
//            takes an idea out of scope. Reversible locally until Submit.
//   comment  content survives and is REWRITTEN to fold in a response.
//            Claude weighs every comment on its merits, conceding or
//            defending, so there is no separate "I disagree" flag.
//   compact  content is REMOVED from the page but stays IN SCOPE — the idea
//            still binds the plan, and its contribution is absorbed into the
//            surviving prose of a neighbouring unit. Destructive to the
//            words, not to the plan: lossy (nothing is stored off-page, so
//            detail no surviving sentence can carry is gone for good) and
//            irreversible once Submit sends the round.
//
// TWO SCOPES: a span (any words the reader selected, carried as selected_text
// plus prefix/suffix) and a block (the whole section, chosen by selecting its
// title). Both are set from the selection menu in selection.js.
//   A span inside an authored data-annotate-id region also carries that id
//   as step_id, so Claude finds it after a rewrite of its words. A step mark
//   (step_id, no words) names a diagram or flowchart node.
//
// ONE TIMING MODEL. Every mark is LOCAL — localStorage, nothing wakes Claude
// — until the round dock's Submit sends ONE {type:"round", reactions:[...]}
// event. Claude applies the whole round in a single pass and acks once.
// Choice picks ride the same round as `kind: "choice"` reactions: a page that
// asks three questions is answered with one Submit, not three round trips.
// (The general comment box is a conversation turn, not feedback on content,
// so it still sends immediately.)
//
// A span mark goes on the wire as its words plus up to 32 characters either
// side, always, so Claude finds the right occurrence even when the words
// repeat.
(function () {
  // `let`, not `const`: a second response pushed into the same session
  // changes the response id under an open page (see resetForResponse).
  let RID = document.body.dataset.responseId || "";
  let KEY = `annotate.round.${RID}`;
  // The id of the round this page submitted and has not seen answered. Kept
  // per SESSION rather than per response, and in storage rather than only in
  // memory: a reload, or a second tab, must know a round is already out, or
  // it offers to send the same marks again.
  const PENDING_KEY = `annotate.round.pending.${location.pathname}`;

  // marks: { [key]: {scope, block_id, kind, selected_text?, prefix?, suffix?,
  //                  step_id?, text?, images?, spans?} }, keyed by spanKey, blockMarkKey,
  // stepMarkKey, choiceMarkKey or orphanMarkKey below.
  let marks = loadMarks();
  // event_id of the in-flight submitted round, if any. Also doubles as a
  // synchronous in-flight guard: set to the "inflight" sentinel the moment
  // submit is dispatched (before the promise resolves) so a fast double
  // click can't fire two rounds.
  let pendingRound = loadPending();
  // Set when the watcher behind our in-flight round has gone dark. The
  // event stays queued on disk and a fresh watcher re-emits it, so
  // `pendingRound` is deliberately NOT cleared here — clearing it would
  // re-arm Submit and let the user fire the same round a second time. This
  // flag only changes what the button says while that lock holds.
  let sessionDead = false;
  // Set for a few seconds after a failed submit so the dock can surface it
  // instead of silently reverting to "Submit round (n)" with no signal.
  let roundError = false;
  let roundErrorTimer = null;
  // block_ids from the most recently SUBMITTED round. Captured synchronously
  // at submit time (see submitRound) because clearRound() wipes `marks` on
  // ack — this is the only moment "what did the user actually ask for"
  // exists.
  //
  // Deliberately NOT cleared in clearRound(): that runs on the ack, and the
  // change bar reads this AFTER the ack. script.js clears it instead, at the
  // one point the bar has finished consuming it (the busy false edge, right
  // after computeChangeSet) — via clearSubmittedBlockIds below. Left uncleared
  // it outlived its round and mis-attributed the next general comment's
  // rewrites as "you asked".
  let lastSubmittedBlockIds = [];

  // Mirrors script.js's WATCHER_DEAD_AFTER_S: if the watcher hasn't reported
  // in this long, no ack is ever coming for an in-flight round either.
  const WATCHER_DEAD_AFTER_S = 15;

  function loadMarks() {
    let stored;
    try { stored = JSON.parse(localStorage.getItem(KEY) || "{}"); }
    catch { return {}; }
    // A "keep" saved before that control was removed has no button left to
    // undo it, so it is dropped rather than sent.
    for (const [k, m] of Object.entries(stored)) {
      if (m && m.kind === "keep") delete stored[k];
    }
    // Marks made by the old per-sentence strip were keyed by the sentence's
    // text and its position among same-text sentences. Their words are all a
    // span mark needs; the position is dropped, and an empty prefix/suffix
    // lets `locate` take the first match, which is what ordinal 0 meant.
    let converted = false;
    for (const [k, m] of Object.entries(stored)) {
      if (!m || m.scope !== "unit" || !m.selected_text || k.includes("::__")) continue;
      delete stored[k];
      const { ordinal, ...rest } = m;
      const conv = { ...rest, prefix: m.prefix || "", suffix: m.suffix || "" };
      stored[`${conv.block_id}::__span__::${conv.prefix}␟${conv.selected_text}␟${conv.suffix}`] = conv;
      converted = true;
    }
    // Written back at once, so the store holds one shape: another tab, or
    // the next load, never sees the old keys beside the new ones.
    if (converted) {
      try {
        localStorage.setItem(KEY, JSON.stringify(stored));
        window.AnnotateStorage?.touch(KEY);
      } catch {}
    }
    return stored;
  }
  // An empty round is removed rather than stored as "{}", so a finished
  // document leaves nothing behind; a non-empty one is stamped for the sweep
  // in script.js that retires rounds nobody has opened in weeks.
  function saveMarks() {
    try {
      if (Object.keys(marks).length) {
        localStorage.setItem(KEY, JSON.stringify(marks));
        window.AnnotateStorage?.touch(KEY);
      } else localStorage.removeItem(KEY);
    } catch {}
  }
  function loadPending() {
    try { return localStorage.getItem(PENDING_KEY) || null; } catch { return null; }
  }
  function savePending() {
    try {
      // The "inflight" sentinel covers only the POST itself and never leaves
      // this tab: a reload mid-POST cannot know whether the daemon got it.
      if (pendingRound && pendingRound !== "inflight") {
        localStorage.setItem(PENDING_KEY, pendingRound);
      } else localStorage.removeItem(PENDING_KEY);
    } catch {}
  }

  // Block-scope marks have no text to key on, and a block can carry at most
  // one — marking a block "compact" replaces a pending "delete" rather than
  // stacking.
  function blockMarkKey(blockId) {
    return `${blockId}::__block__`;
  }
  // A span mark is keyed by the words AND their surroundings, so the same
  // words twice in one block are two marks. U+241F cannot occur in prose a
  // reader selected, which keeps the three parts unambiguous. A mark across a
  // heading joins the keys of its parts (spans.js); one part keeps its key.
  const SP = () => window.AnnotateSpans;
  function spanKey(a) {
    return SP().markKey(SP().partsOf(a));
  }
  function isSpan(m) {
    return m && m.scope === "unit" && !!m.selected_text && m.kind !== "choice";
  }
  function sectionFor(blockId) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(blockId)}"]`);
  }
  // Where one part's words are in its part's prose, as [start, end].
  function locatePart(p) {
    const s = sectionFor(p.block_id);
    return s && window.AnnotateAnchors ? window.AnnotateAnchors.locate(s, p) : null;
  }
  function spanOf(m) { return locatePart(SP().partsOf(m)[0]); }

  // Marks that share words with the anchor in any part both cover.
  function overlapping(anchor) {
    const want = SP().partsOf(anchor).map((p) => ({ p, span: locatePart(p) })).filter((x) => x.span);
    if (!want.length) return [];
    return Object.entries(marks)
      .filter(([, m]) => isSpan(m) && SP().partsOf(m).some((q) => {
        const qs = locatePart(q);
        return qs && want.some((w) => w.p.block_id === q.block_id && qs[0] < w.span[1] && w.span[0] < qs[1]);
      }))
      .map(([key, m]) => ({ key, m }));
  }

  // `images` are pictures pasted into the comment window (attachPaste), sent
  // with the round as a part's comment's are.
  function setSpanMark(anchor, kind, text, images) {
    const key = spanKey(anchor);
    const existing = marks[key];
    if (existing && existing.kind === kind && !text) {
      delete marks[key];                                // undo
    } else {
      for (const { key: k } of overlapping(anchor)) delete marks[k];
      const m = { scope: "unit", block_id: anchor.block_id, kind,
                  selected_text: anchor.selected_text,
                  prefix: anchor.prefix || "", suffix: anchor.suffix || "" };
      if (anchor.step_id) m.step_id = anchor.step_id;
      if (anchor.spans) m.spans = anchor.spans.map((p) => ({ block_id: p.block_id, selected_text: p.selected_text, prefix: p.prefix || "", suffix: p.suffix || "" }));
      if (text) m.text = text;
      if (images && images.length) m.images = images;
      marks[key] = m;
    }
    saveMarks();
    paintSpans();
    renderDock();
  }

  function paintSpans() {
    if (!window.AnnotateAnchors) return;
    const items = [];
    for (const m of Object.values(marks)) {
      if (!isSpan(m)) continue;
      for (const p of SP().partsOf(m)) {
        const section = sectionFor(p.block_id);
        if (section) items.push({ section, anchor: p, kind: m.kind });
      }
    }
    window.AnnotateAnchors.paint(items);
    // A comment's words are shown where it was made: one chip under the
    // paragraph (or list item) the commented words end in, in the last part
    // they cover.
    document.querySelectorAll(".sel-chip").forEach((c) => c.remove());
    for (const [key, m] of Object.entries(marks)) {
      if (!isSpan(m) || m.kind !== "comment" || !m.text) continue;
      const last = SP().partsOf(m).slice(-1)[0];
      const section = sectionFor(last.block_id);
      const r = section && window.AnnotateAnchors.rangeFor(section, last);
      if (!r) continue;
      const content = window.AnnotateAnchors.contentOf(section);
      const end = r.endContainer.nodeType === 1 ? r.endContainer : r.endContainer.parentElement;
      const host = (end && end.closest("li, p, pre, blockquote, table")) || content;
      const chip = document.createElement("span");
      chip.className = "sel-chip";
      chip.dataset.key = key;
      const said = document.createElement("span");
      said.textContent = `💬 ${m.text}`;
      // The chip is the comment's only place on the page, so it is also
      // where the comment is taken back.
      const x = document.createElement("button");
      x.type = "button";
      x.className = "sel-chip-x";
      x.textContent = "×";
      x.title = "Remove comment";
      x.setAttribute("aria-label", "Remove comment");
      x.addEventListener("click", (ev) => { ev.stopPropagation(); removeMark(chip.dataset.key); });
      chip.append(said, x);
      if (host === content || host.tagName === "LI") host.appendChild(chip);
      else host.insertAdjacentElement("afterend", chip);
    }
  }

  function spanMarkAt(section, x, y) {
    const root = window.AnnotateAnchors?.contentOf(section);
    if (!root) return null;
    const off = window.AnnotateAnchors.offsetAt(root, x, y);
    if (off === null) return null;
    for (const [key, m] of Object.entries(marks)) {
      if (!isSpan(m)) continue;
      for (const p of SP().partsOf(m)) {
        if (p.block_id !== section.dataset.blockId) continue;
        const sp = locatePart(p);
        if (sp && sp[0] <= off && off < sp[1]) return { key, m };
      }
    }
    return null;
  }

  // Step-scope marks (diagram/flowchart nodes, authored data-annotate-id
  // regions) anchor by id, not by text position.
  function stepMarkKey(blockId, stepId) {
    return `${blockId}::__step__::${stepId}`;
  }
  // A choice answer has its own key, not the block key: answering a question
  // and marking its card (delete, compact...) are separate decisions, and sharing
  // the key would let one silently overwrite the other.
  function choiceMarkKey(blockId) {
    return `${blockId}::__choice__`;
  }
  // A unit comment whose paragraph was rewritten out from under it. Keyed by
  // the old text, so two orphaned comments in one block stay two.
  function orphanMarkKey(m) {
    return `${m.block_id}::__moved__::${m.selected_text}::${m.prefix || ""}`;
  }
  function orphaned(m) {
    const quote = m.selected_text.length > 120
      ? m.selected_text.slice(0, 117) + "…" : m.selected_text;
    const o = { scope: "block", block_id: m.block_id, kind: "comment",
                text: `On the passage that read "${quote}": ${m.text}`,
                moved_from: m.selected_text };
    if (m.images && m.images.length) o.images = m.images;
    return o;
  }

  // ── Boot tracking (guards pruneMarks against a partially-built document) ──
  //
  // loadAndRenderBlocks() (and reconcile()'s insert-new-block path) build
  // sections in a synchronous per-block loop, each section built detached and
  // appended after. Mid-loop, `document` holds only the blocks already
  // appended; pruning against that half-built snapshot would take the marks
  // on every later block for orphans and delete them.
  //
  // So pruning waits for `booted`, which flips on a timer armed by the first
  // "annotate:rendered" — the event both render paths dispatch only after
  // their whole loop. When the blocks rendered before this file loaded (the
  // usual case: the fetch does not wait for it), that event has already gone
  // by, and the sections on the page are the finished document, so the timer
  // is armed at load instead (see the bottom of this file). Once booted, the
  // dock is rendered again, which is what prunes: nothing else would until
  // the next mark or poll.
  let booted = false;
  let bootTimerArmed = false;
  function armBootTimer() {
    if (bootTimerArmed) return;
    bootTimerArmed = true;
    setTimeout(() => { booted = true; renderDock(); }, 0);
  }

  // Drop local marks whose block (or, best-effort, whose specific unit)
  // no longer exists. Reachable whenever Claude removes a block (or a
  // unit's text changes) out from under a pending local mark — e.g. the
  // user marks a list item, then the whole section goes in a rewrite.
  // Block-gone is the critical half: an orphaned block_id 422s the ENTIRE
  // round on submit (server.py's _handle_round rejects on the first unknown
  // block_id), which without this pruning would wedge Submit forever with
  // no user-visible recovery short of a devtools localStorage clear. Unit-gone (text no longer resolves within
  // an otherwise-live block) is best-effort cleanup on top of that.
  function pruneMarks() {
    if (!booted) return;                      // see boot-tracking note above
    const liveSections = document.querySelectorAll("main.prose section.block");
    if (!liveSections.length) return;          // belt-and-suspenders
    const liveBlockIds = new Set();
    liveSections.forEach((s) => {
      const id = s.dataset.blockId;
      if (!id) return;
      liveBlockIds.add(id);
    });
    let pruned = false;
    for (const [key, m] of Object.entries(marks)) {
      // An edit mark on a section that is gone goes with it, in silence: its
      // words were the section's text, and they went with the section.
      if (SP().blockIdsOf(m).some((id) => !liveBlockIds.has(id))) {
        // Same rule as a rewritten paragraph below: words the reader wrote are
        // never dropped in silence. With the whole block gone there is nowhere
        // in the round to put them, so script.js moves them to the general box.
        if (m.text && m.kind !== "choice") {
          document.dispatchEvent(new CustomEvent("annotate:orphan-comment",
            { detail: { text: m.text, quote: m.selected_text || "" } }));
        }
        delete marks[key];
        pruned = true;
        continue;
      }
      // Block- and step-scope marks have no text anchor to re-resolve: a live
      // block_id is the whole liveness test for them. (A step_id that vanished
      // from a re-rendered diagram is left alone deliberately — the server
      // only rejects unknown block_ids, and Claude treats an unresolvable
      // step as a per-reaction no-op.)
      if (m.scope && m.scope !== "unit") continue;
      if (!isSpan(m) && m.step_id) continue;
      if (isSpan(m) && !SP().partsOf(m).every(locatePart)) {
        // The words it pointed at were rewritten. A bare delete/compact has
        // nothing left to act on and goes. A comment is words the reader
        // wrote, so it is never dropped in silence: it moves to the whole
        // section, quoting the text it was about.
        if (m.text) marks[orphanMarkKey(m)] = orphaned(m);
        delete marks[key];
        pruned = true;
      }
    }
    if (pruned) saveMarks();
  }

  // The three controls' glyphs, for the dock's summary and rows. The menu in
  // selection.js names the same three acts.
  //
  // There is no "keep". It promised Claude would not rewrite a sentence, but
  // Claude rewrites only what a round asks about, so it changed nothing.
  // Compact's glyph is the eye-off icon the private fold used to carry. The
  // gesture the user learned — "take this off my screen" — is unchanged; what
  // changed is that it now reaches Claude and slims the document instead of
  // collapsing a stub locally. Kept as SVG rather than an emoji because there
  // is no emoji that reads as "hide" without also reading as "delete".
  const COMPACT_ICON =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>' +
    '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>' +
    '<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/>' +
    '<line x1="1" y1="1" x2="23" y2="23"/></svg>';

  const CONTROL_SPECS = [
    ["delete",  "🗑", "Delete — removed for good (undo until you submit)"],
    ["comment", "💬", "Comment — fold a response into this"],
    ["compact", COMPACT_ICON,
     "Compact — take this off the page; its point is folded into what stays"],
  ];

  // ── Round dock / review drawer ───────────────────────────────────────────
  // Open/closed is remembered for the session so the drawer does not
  // re-collapse under the user every time a mark changes.
  let drawerOpen = false;

  function markRows() {
    // Stable order: document order by block, then by where the mark's words
    // start in it, so the manifest reads like the page rather than like a hash map.
    const order = [...document.querySelectorAll("section.block[data-block-id]")]
      .map(s => s.dataset.blockId);
    const rows = Object.entries(marks).map(([key, m]) => ({ key, m, at: spanOf(m)?.[0] ?? -1 }));
    return rows.sort((a, b) => {
      const ai = order.indexOf(a.m.block_id), bi = order.indexOf(b.m.block_id);
      if (ai !== bi) return ai - bi;
      return a.at - b.at;
    }).map(({ key, m }) => ({ key, m }));
  }

  function blockTitleFor(blockId) {
    const s = document.querySelector(
      `section.block[data-block-id="${CSS.escape(blockId)}"]`);
    return s?.getAttribute("aria-label") || blockId;
  }

  function jumpToMark(m) {
    // A queued question off screen is display:none and cannot be scrolled to.
    window.AnnotateChoiceQueue?.show(m.block_id);
    const s = document.querySelector(
      `section.block[data-block-id="${CSS.escape(m.block_id)}"]`);
    if (!s) return;
    if (isSpan(m) && window.AnnotateAnchors) {
      const range = window.AnnotateAnchors.rangeFor(s, SP().partsOf(m)[0]);
      if (range) {
        const rect = range.getBoundingClientRect();
        window.scrollBy({ top: rect.top + rect.height / 2 - window.innerHeight / 2,
                          behavior: "smooth" });
        window.AnnotateAnchors.setScope(range);
        setTimeout(() => window.AnnotateAnchors.setScope(null), 1200);
        return;
      }
    }
    s.scrollIntoView({ behavior: "smooth", block: "center" });
    s.classList.add("rd-flash");
    setTimeout(() => s.classList.remove("rd-flash"), 1200);
  }

  function removeMark(key) {
    // Capture before deleting: repaintBlocks() only visits marks that still
    // exist, so a removed block-scope mark would never have its card
    // repainted and would stay visually marked. Same reason toggleBlockMark
    // calls paintBlock directly rather than relying on the sweep.
    const gone = marks[key];
    delete marks[key];
    saveMarks();
    if (gone && gone.scope === "block" && gone.block_id) paintBlock(gone.block_id);
    if (gone && gone.kind === "choice") syncChoices();
    repaintBlocks();
    paintSpans();
    renderDock();
  }

  // Not one of the three controls, so the menu has no button for it; it needs
  // a glyph only for the dock's summary and rows.
  const CHOICE_GLYPH = "☑";

  // The reader's own edit in the editor (edit.js). One per section: a second
  // save before Submit merges into it, keeping the text before the first
  // and the text after the last, so Claude reads the whole change at once.
  const EDIT_GLYPH = "✎";
  function editMarkKey(blockId) {
    return `${blockId}::__edit__`;
  }
  function addEdit(blockId, before, after) {
    if (!blockId || typeof before !== "string" || typeof after !== "string") return;
    const key = editMarkKey(blockId);
    const first = marks[key] ? marks[key].before : before;
    // Edited back to where it started: there is nothing to tell Claude.
    if (first === after) delete marks[key];
    else marks[key] = { scope: "block", block_id: blockId, kind: "edit", before: first, after };
    saveMarks();
    renderDock();
  }

  // The dock row's words: each change as struck and added text, with the
  // unchanged text between changes cut to an ellipsis.
  function editDiffInto(el, m) {
    const D = window.AnnotateEditDiff;
    if (!D) { el.textContent = "edited"; return; }
    const groups = [];
    let g = null;
    for (const op of D.wordDiff(m.before || "", m.after || "")) {
      if (op.op === "eq" && op.text.trim()) { g = null; continue; }
      if (!g) { g = { del: "", ins: "" }; groups.push(g); }
      if (op.op !== "ins") g.del += op.text;
      if (op.op !== "del") g.ins += op.text;
    }
    // The words as the page shows them, without markdown's markers; a change
    // that only re-formatted words says so instead of striking and re-adding
    // the same words.
    const words = (t) => (window.AnnotateEdit?.plain ? window.AnnotateEdit.plain(t) : t)
      .replace(/\s+/g, " ").trim();
    let n = 0;
    for (const x of groups) {
      const del = words(x.del), ins = words(x.ins);
      if (!del && !ins) continue;
      if (n++) el.append(" … ");
      if (del === ins) { el.append(`${del} (formatting)`); continue; }
      if (del) { const d = document.createElement("del"); d.textContent = del; el.append(d); }
      if (del && ins) el.append(" ");
      if (ins) { const i = document.createElement("ins"); i.textContent = ins; el.append(i); }
    }
    if (!n) el.textContent = "formatting only";
  }

  function glyphFor(kind) {
    if (kind === "edit") return EDIT_GLYPH;
    if (kind === "choice") return CHOICE_GLYPH;
    const spec = CONTROL_SPECS.find(([k]) => k === kind);
    return spec ? spec[1] : "";
  }

  function renderDock() {
    pruneMarks();
    let dock = document.getElementById("round-dock");
    const rows = markRows();
    const count = rows.length;
    // Keep the dock alive while a round is in flight even if the user
    // unmarks everything after Submit but before busy/consumed_events
    // propagate back — otherwise it flashes away and reappears.
    if (!count && !pendingRound) {
      if (dock) dock.remove();
      return;
    }
    if (!dock) {
      dock = document.createElement("div");
      dock.id = "round-dock";
      dock.dataset.open = drawerOpen ? "true" : "false";

      const head = document.createElement("div");
      head.className = "rd-head";
      // Ignores clicks that land on the Submit button: that button's own
      // handler stops propagation before it can bubble up to this toggle.
      head.addEventListener("click", () => {
        drawerOpen = !drawerOpen;
        dock.dataset.open = drawerOpen ? "true" : "false";
        caret.setAttribute("aria-expanded", String(drawerOpen));
      });
      // A button, so the drawer opens from the keyboard: the header used to
      // be a clickable div with no role and no tab stop, and the rows it
      // hides were unreachable any other way. Its click bubbles to the
      // header's handler above, which is the one toggle.
      const caret = document.createElement("button");
      caret.type = "button";
      caret.className = "rd-caret rd-toggle";
      caret.innerHTML = '<span aria-hidden="true">▾</span>';
      caret.setAttribute("aria-label", "What is in this round");
      caret.setAttribute("aria-controls", "round-dock-list");
      caret.setAttribute("aria-expanded", String(drawerOpen));
      const summary = document.createElement("div");
      summary.className = "rd-summary";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = "round-submit";
      btn.addEventListener("click", (ev) => { ev.stopPropagation(); submitRound(); });
      head.append(caret, summary, btn);

      const list = document.createElement("div");
      list.className = "rd-list";
      list.id = "round-dock-list";

      dock.append(head, list);
      document.body.appendChild(dock);
    }
    dock.dataset.open = drawerOpen ? "true" : "false";
    dock.querySelector(".rd-toggle")?.setAttribute("aria-expanded", String(drawerOpen));

    // Per-kind counts, in CONTROL_SPECS order, so the summary reads like the
    // controls the user actually clicked.
    const summary = dock.querySelector(".rd-summary");
    summary.innerHTML = "";
    const counts = {};
    for (const { m } of rows) counts[m.kind] = (counts[m.kind] || 0) + 1;
    for (const [kind, glyph] of [["edit", EDIT_GLYPH], ["choice", CHOICE_GLYPH], ...CONTROL_SPECS]) {
      if (!counts[kind]) continue;
      const span = document.createElement("span");
      span.innerHTML = `<span aria-hidden="true">${glyph}</span> <b>${counts[kind]}</b>`
        + `<span class="sr-only"> ${kind}</span>`;
      summary.appendChild(span);
    }

    // Rows are rebuilt wholesale each render — cheap at this scale, and it
    // keeps the manifest from ever drifting out of document order.
    const list = dock.querySelector(".rd-list");
    list.innerHTML = "";
    for (const { key, m } of rows) {
      const row = document.createElement("div");
      row.className = "rd-row";
      row.addEventListener("click", () => jumpToMark(m));

      const k = document.createElement("span");
      k.className = "rd-k";
      k.dataset.kind = m.kind;
      k.innerHTML = glyphFor(m.kind);
      k.setAttribute("aria-hidden", "true");

      const body = document.createElement("div");
      body.className = "rd-body";
      // The row's jump, made reachable: Enter or Space does what a click on
      // the row does. On the body rather than the row, because the row also
      // holds the remove button and a button inside a button is not one.
      body.tabIndex = 0;
      body.setAttribute("role", "button");
      body.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        ev.preventDefault();
        jumpToMark(m);
      });
      const where = document.createElement("div");
      where.className = "rd-where";
      where.textContent = blockTitleFor(m.block_id);
      const text = document.createElement("div");
      text.className = "rd-text";
      // `.rd-where` above already carries blockTitleFor(), so falling back to
      // it here printed "§3 · The retry path" twice on every block-scope row.
      // What the second line has to add is the SCOPE — a block-scope delete
      // and a unit-scope delete on the section's first sentence are different
      // decisions, and echoing the block's first line of text (the other
      // candidate) would render those two rows identically. A step mark names
      // its node instead: it is neither the whole block nor a text span.
      if (m.kind === "edit") editDiffInto(text, m);
      else text.textContent = m.kind === "choice"
        ? (m.labels && m.labels.length ? m.labels.join(", ") : "your own answer")
        : m.selected_text
          || (m.step_id ? `step: ${m.step_id}` : "whole part");
      body.append(where, text);
      if (m.text) {
        const said = document.createElement("div");
        said.className = "rd-said";
        said.textContent = m.text;
        body.appendChild(said);
      }

      row.append(k, body);
      // An edit is already saved: removing its row would only keep it from
      // Claude while the text stays edited. It has no ×; editing the section
      // back is how it is undone (addEdit drops a mark that returns to where
      // it started).
      if (m.kind !== "edit") {
        const x = document.createElement("button");
        x.type = "button";
        x.className = "rd-x";
        x.textContent = "×";
        x.title = "Remove this mark";
        x.setAttribute("aria-label", `Remove ${m.kind} mark`);
        x.addEventListener("click", (ev) => { ev.stopPropagation(); removeMark(key); });
        row.appendChild(x);
      }
      list.appendChild(row);
    }
    const foot = document.createElement("div");
    foot.className = "rd-foot";
    const edits = rows.filter(({ m }) => m.kind === "edit").length;
    const others = rows.length - edits;
    foot.textContent = "Click any row to jump to it. "
      + (edits ? "Your edits are already saved; submitting tells Claude." : "")
      + (edits && others ? " Every other mark is undoable until you submit."
        : others ? "Nothing has reached Claude yet — every mark is undoable until you submit." : "");
    list.appendChild(foot);

    const btn = dock.querySelector("#round-submit");
    if (sessionDead) {
      btn.textContent = "Session gone — see the banner";
      btn.title = "";
    } else if (pendingRound) {
      btn.textContent = "Applying round…";
      btn.title = "";
    } else if (roundError) {
      btn.textContent = "Submit failed — retry";
      btn.title = "The last submit didn't go through. Click to try again.";
    } else {
      btn.textContent = `Submit round (${count})`;
      btn.title = "";
    }
    if (document.body.classList.contains("is-busy") && !pendingRound) {
      btn.textContent = count
        ? `${count} queued for next round`
        : "Claude is working…";
      btn.title = "Keep marking — this submits once Claude finishes.";
    }
    // `is-editing` matters as much as the other two: drafts live in
    // script.js's store and round marks live here, and submitRound only
    // reads the latter — so submitting with an editor open silently drops
    // the comment the user believes they just left.
    // `has-sel-draft` is the same lock for selection.js's span comment box,
    // whose words are not in the round until "Add to round".
    const selDraft = document.body.classList.contains("has-sel-draft");
    // `has-edit-draft`: edit.js's editor holds words not saved yet, so the
    // round's `edit` mark does not have them either.
    const editDraft = document.body.classList.contains("has-edit-draft");
    btn.disabled = !!pendingRound
      || document.body.classList.contains("is-busy")
      || document.body.classList.contains("is-editing") || selDraft || editDraft;
    if (!pendingRound && document.body.classList.contains("is-editing")) {
      // The LABEL, not just the title: the button is disabled a line below,
      // and browsers suppress mouse events on a disabled button, so its
      // tooltip can never be shown. A title-only version left the dock dead
      // with no explanation anywhere on screen.
      btn.textContent = "Finish or discard the open comment";
      btn.title = "Finish or discard the open comment first.";
    } else if (!pendingRound && selDraft) {
      btn.textContent = "Finish or discard the open comment";
      btn.title = "Finish or discard the open comment first.";
    } else if (!pendingRound && editDraft) {
      btn.textContent = "Save or discard your edit";
      btn.title = "Save or discard your edit first.";
    }
  }

  function submitRound() {
    pruneMarks();                              // never submit an orphaned block_id
    if (pendingRound) return;                  // synchronous double-click guard
    const reactions = Object.values(marks).map((m) => {
      const r = { scope: m.scope || "unit", kind: m.kind, block_id: m.block_id,
                  selected_text: m.selected_text || "",
                  text: (m.text || "").trim(), images: m.images || [] };
      if (m.step_id) r.step_id = m.step_id;
      if (m.kind === "choice") r.selected_options = m.selected_options || [];
      // The full markdown both sides of the reader's edit: Claude diffs them.
      if (m.kind === "edit") { r.before = m.before || ""; r.after = m.after || ""; }
      if (m.prefix !== undefined) r.prefix = m.prefix;
      if (m.suffix !== undefined) r.suffix = m.suffix;
      if (m.spans && m.spans.length > 1) r.spans = m.spans;
      return r;
    });
    if (!reactions.length) return;
    // Set the sentinel BEFORE the async call and repaint immediately so the
    // button disables synchronously — closes the window where a fast
    // double-click (or a click racing the first busy poll) fires two rounds.
    pendingRound = "inflight";
    roundError = false;
    if (roundErrorTimer) { clearTimeout(roundErrorTimer); roundErrorTimer = null; }
    renderDock();
    // Captured HERE, not read back later: clearRound() wipes `marks` on ack,
    // so this is the only moment that information exists. Task 4's
    // attribution split depends on it.
    // A reaction across a heading puts every part it covers in that list.
    lastSubmittedBlockIds = [...new Set(reactions.flatMap((r) => r.spans ? r.spans.map((s) => s.block_id) : [r.block_id]))];
    WebCompanion.api.submit({ type: "round", reactions }).then((res) => {
      pendingRound = res && res.event_id ? String(res.event_id) : null;
      savePending();
      window.AnnotatePage?.registerRoundEvent(pendingRound, lastSubmittedBlockIds);
      renderDock();
    }).catch(() => {
      // Surface the failure instead of silently reverting — a bare .catch
      // that only cleared pendingRound would look like Submit no-oped.
      pendingRound = null;
      roundError = true;
      renderDock();
      roundErrorTimer = setTimeout(() => {
        roundError = false;
        roundErrorTimer = null;
        renderDock();
      }, 5000);
    });
  }

  function clearRound() {
    marks = {};
    pendingRound = null;
    sessionDead = false;
    saveMarks();
    savePending();
    document.querySelectorAll("section.block[data-block-mark]").forEach(s => {
      delete s.dataset.blockMark;
    });
    syncChoices();
    paintSpans();
    renderDock();
  }

  // Choice blocks paint their own answer (renderChoice in script.js hangs the
  // painter on the section). Call it when an answer changes from outside the
  // block, or the cards stay lit for an answer that is no longer in the round.
  function syncChoices() {
    document.querySelectorAll("section.block").forEach(s => s.syncChoice?.());
    document.dispatchEvent(new CustomEvent("annotate:choice-changed"));
  }

  // ── Block scope ───────────────────────────────────────────────────────────
  //
  // Driven by the selection menu on a section's title. A block carries at most one
  // mark, so re-marking replaces rather than stacks, and clicking the same
  // control twice is the undo. Painting is a data attribute on the section —
  // CSS greys and strikes a pending delete, so "removed for good" still reads
  // as reversible right up until Submit.

  function paintBlock(blockId) {
    const section = document.querySelector(
      `section.block[data-block-id="${CSS.escape(blockId)}"]`);
    if (!section) return;
    const m = marks[blockMarkKey(blockId)];
    if (m) section.dataset.blockMark = m.kind;
    else delete section.dataset.blockMark;
  }

  function toggleBlockMark(blockId, kind) {
    if (!blockId) return;
    const key = blockMarkKey(blockId);
    const existing = marks[key];
    if (existing && existing.kind === kind) delete marks[key];
    else marks[key] = { scope: "block", block_id: blockId, kind };
    saveMarks();
    paintBlock(blockId);
    renderDock();
  }

  // Pin a comment that the rich editor in script.js composed. `step_id` is
  // set for diagram/flowchart nodes and authored data-annotate-id regions;
  // absent means the comment is about the whole block.
  function pinComment({ block_id, step_id, text, images,
                        selected_text, prefix, suffix }) {
    if (!block_id || !text) return;
    if (!step_id && selected_text) {
      for (const { key: k } of overlapping({ block_id, selected_text, prefix, suffix })) delete marks[k];
    }
    const key = step_id ? stepMarkKey(block_id, step_id)
      : (selected_text ? spanKey({ block_id, selected_text, prefix, suffix })
                       : blockMarkKey(block_id));
    const m = { scope: (step_id || selected_text) ? "unit" : "block", block_id, kind: "comment", text };
    if (step_id) m.step_id = step_id;
    if (images && images.length) m.images = images;
    if (selected_text) m.selected_text = selected_text;
    if (prefix !== undefined) m.prefix = prefix;
    if (suffix !== undefined) m.suffix = suffix;
    marks[key] = m;
    saveMarks();
    paintSpans();
    if (!step_id) paintBlock(block_id);
    renderDock();
  }

  function blockMark(blockId) {
    return marks[blockMarkKey(blockId)] || null;
  }

  // A choice block's answer: the picked option ids plus an optional note. An
  // empty pick with an empty note is no answer, so the mark goes away.
  // `labels` is for the dock only and never goes on the wire.
  function setChoice(blockId, selected_options, labels, text) {
    if (!blockId) return;
    const key = choiceMarkKey(blockId);
    if (!selected_options.length && !(text || "").trim()) delete marks[key];
    else marks[key] = { scope: "block", block_id: blockId, kind: "choice",
                        selected_options, labels, text };
    saveMarks();
    renderDock();
    document.dispatchEvent(new CustomEvent("annotate:choice-changed"));
  }

  function choiceMark(blockId) {
    return marks[choiceMarkKey(blockId)] || null;
  }

  // Re-apply block painting after a re-render replaced the section element.
  function repaintBlocks() {
    for (const m of Object.values(marks)) {
      if (m.scope === "block") paintBlock(m.block_id);
    }
  }

  // Poll integration: disable the dock while busy; clear marks when our
  // round's event id shows up acked in consumed_events (dismissed units
  // disappear via the normal reconcile pass — version bump / block rewrite).
  function onPoll(data) {
    // compat.js holds every unanswered event id, for this tab and any other
    // on the same page. A round it no longer holds was answered — whether the
    // ack reached this tab, another tab, or arrived while no tab was open.
    if (pendingRound && pendingRound !== "inflight" &&
        !window.WebCompanion?.isHeld?.(pendingRound)) {
      clearRound();
      return;
    }
    // Mirrors script.js's watcher_age_s > WATCHER_DEAD_AFTER_S handling: the
    // watcher behind our in-flight round has gone dark. The event is still
    // queued on disk and a fresh watcher will re-emit it, so clearing
    // pendingRound here would re-arm Submit and let the user fire the same
    // round twice — the dock stays locked (the consumed_events branch above
    // is what eventually clears it, once a fresh watcher actually acks).
    sessionDead = !!(pendingRound && typeof data.watcher_age_s === "number" &&
        data.watcher_age_s > WATCHER_DEAD_AFTER_S);
    renderDock();
  }

  // Repaint everything this module owns from the stored round. Used when the
  // store changed under the page: another tab, or a new response.
  function repaintAll() {
    document.querySelectorAll("section.block[data-block-mark]").forEach((sec) => {
      if (!marks[blockMarkKey(sec.dataset.blockId)]) delete sec.dataset.blockMark;
    });
    repaintBlocks();
    syncChoices();
    paintSpans();
    renderDock();
  }

  // Another tab on this page marked, unmarked, submitted or saw the round
  // answered. Without this the other tab kept its own copy and wrote it
  // back on its next click, resurrecting marks that had already gone out.
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) {
      marks = loadMarks();
      repaintAll();
    } else if (e.key === PENDING_KEY) {
      if (pendingRound !== "inflight") pendingRound = loadPending();
      renderDock();
    }
  });

  // A second response pushed into the same session reuses the section ids,
  // so marks made on the first would land on different content. They were
  // about a document that is gone: drop them, and move to the new key.
  function resetForResponse(rid) {
    try { localStorage.removeItem(KEY); } catch {}
    RID = rid || "";
    KEY = `annotate.round.${RID}`;
    marks = loadMarks();
    window.AnnotateSelection?.close();
    repaintAll();
  }

  window.AnnotateSubunits = {
    onPoll,
    // Span and block marks, driven by the selection menu in selection.js.
    setSpanMark, overlapping, spanMarkAt, removeMarkByKey: removeMark, paintSpans,
    toggleBlockMark, pinComment, blockMark, repaintBlocks, renderDock,
    // The reader's edits, driven by edit.js.
    addEdit,
    // Choice answers, driven by renderChoice in script.js.
    setChoice, choiceMark,
    resetForResponse,
    submittedBlockIds: () => lastSubmittedBlockIds.slice(),
    // Called by script.js once the change bar has derived its attribution —
    // see the note on lastSubmittedBlockIds for why the ack is too early.
    clearSubmittedBlockIds: () => { lastSubmittedBlockIds = []; },
  };
  // entry.js loads this file after script.js, and the blocks are fetched
  // without waiting for it, so on most loads they have already rendered, and
  // their "annotate:rendered" has gone by. Paint whatever is there now. A
  // section on the page means a render loop has finished (it never yields
  // mid-loop), so pruning is safe to arm; otherwise the first render arms it.
  if (document.querySelector("main.prose section.block")) armBootTimer();
  repaintAll();
  // Every render path ends with this event (loadAndRenderBlocks, reconcile).
  // Ranges are rebuilt from text each time, so a rewrite, a glossary pass or
  // a search never leaves a mark painted on stale nodes.
  document.addEventListener("annotate:rendered", () => {
    armBootTimer();
    paintSpans();
    renderDock();
  });
})();
