// annotate skill — the review round: every piece of content feedback on the
// page, batched into one submission.
//
// FOUR CONTROLS, one vocabulary, at every scope. Each answers two questions:
// does the content survive, and if so what should Claude do to it?
//
//   delete   content is REMOVED from blocks.json, references re-threaded,
//            and treated as out of scope from then on. The only control that
//            takes an idea out of scope. Reversible locally until Submit.
//   keep     content survives UNTOUCHED — an explicit "do not rewrite this",
//            which is what protects a line while its neighbours change.
//   comment  content survives and is REWRITTEN to fold in a response. An
//            optional `disagree` flag turns it into a push-back, which tells
//            Claude to concede or defend rather than assume agreement.
//   compact  content is REMOVED from the page but stays IN SCOPE — the idea
//            still binds the plan, and its contribution is absorbed into the
//            surviving prose of a neighbouring unit. Destructive to the
//            words, not to the plan: lossy (nothing is stored off-page, so
//            detail no surviving sentence can carry is gone for good) and
//            irreversible once Submit sends the round.
//
// TWO SCOPES, distinguished by where you hover, not by which icon you get:
//   scope "block"  — the card header. Applies to the whole block.
//   scope "unit"   — a paragraph/bullet/row/fence inside the card body.
//                    Carries selected_text (+ prefix/suffix when ambiguous).
//   A unit-scope mark may also carry step_id for diagram/flowchart nodes and
//   authored data-annotate-id sub-units, which anchor by id rather than text.
//
// ONE TIMING MODEL. Every mark is LOCAL — localStorage, nothing wakes Claude
// — until the round dock's Submit sends ONE {type:"round", reactions:[...]}
// event. Claude applies the whole round in a single pass and acks once.
// (Choice picks and the general comment box are NOT feedback on content —
// they are an answer and a conversation turn — so they still submit
// immediately.)
//
// Unit identity on the wire is the existing span format: the unit's
// plain text as selected_text, plus prefix/suffix disambiguation (picked
// via each unit's local occurrence ordinal) when that text occurs more
// than once in the block. The ordinal itself never goes on the wire —
// prefix/suffix is the wire-level disambiguator; ordinal is purely an
// internal bookkeeping detail for telling same-text units apart in the
// local marks store.
(function () {
  const RID = document.body.dataset.responseId || "";
  const KEY = `annotate.round.${RID}`;

  // marks: { [markKey]: {block_id, kind, selected_text, ordinal, prefix?, suffix?, text?} }
  // markKey = `${block_id}::${text}::${ordinal}` — ordinal is the unit's
  // 0-based position among same-text sub-units in its block, so two
  // identical-text units (e.g. two "Done" list items) get distinct keys
  // and a re-render (reconcile/version bump) re-applies surviving marks
  // to the matching occurrence instead of colliding on one shared key.
  let marks = loadMarks();
  // event_id of the in-flight submitted round, if any. Also doubles as a
  // synchronous in-flight guard: set to the "inflight" sentinel the moment
  // submit is dispatched (before the promise resolves) so a fast double
  // click can't fire two rounds.
  let pendingRound = null;
  // Set for a few seconds after a failed submit so the dock can surface it
  // instead of silently reverting to "Submit round (n)" with no signal.
  let roundError = false;
  let roundErrorTimer = null;
  // block_ids from the most recently SUBMITTED round. Captured synchronously
  // at submit time (see submitRound) because clearRound() wipes `marks` on
  // ack — this is the only moment "what did the user actually ask for"
  // exists. Deliberately NOT cleared in clearRound(); Task 4's change-bar
  // attribution reads it after the ack.
  let lastSubmittedBlockIds = [];

  // Mirrors script.js's WATCHER_DEAD_AFTER_S: if the watcher hasn't reported
  // in this long, no ack is ever coming for an in-flight round either.
  const WATCHER_DEAD_AFTER_S = 15;

  function loadMarks() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
    catch { return {}; }
  }
  function saveMarks() {
    try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch {}
  }

  function unitText(el) {
    return (el.textContent || "").replace(/\s+/g, " ").trim();
  }
  function markKey(blockId, text, ordinal) {
    return `${blockId}::${text}::${ordinal}`;
  }
  // Block-scope marks have no text to key on, and a block can carry at most
  // one — marking a block "keep" replaces a pending "delete" rather than
  // stacking. The sentinel can't collide with a unit key: unit keys always
  // carry a numeric ordinal in the third segment.
  function blockMarkKey(blockId) {
    return `${blockId}::__block__`;
  }
  // Step-scope marks (diagram/flowchart nodes, authored data-annotate-id
  // sub-units) anchor by id, not by text position.
  function stepMarkKey(blockId, stepId) {
    return `${blockId}::__step__::${stepId}`;
  }

  // 0-based position of `el` among its block's sub-units that share the
  // same normalized text. Recomputed on demand from the live DOM rather
  // than cached, so it stays correct across reorders/re-decoration.
  //
  // `root` is the decorated `.block-content` subtree, threaded down from
  // decorate() (captured in the click-handler closure, not re-derived via
  // el.closest() at call time). During createBlockSection's first decorate
  // pass `content` is still DETACHED — appendChild into `section`/`body`
  // happens after decorate() runs — so el.closest("section.block") would
  // return null there and silently collapse every ordinal to 0. Querying
  // `root` directly works whether it's attached to the document or not,
  // since querySelectorAll is scoped to the subtree, not the document.
  function unitOrdinal(root, el, text) {
    if (!root) return 0;
    const same = Array.from(root.querySelectorAll(".sub-unit"))
      .filter((u) => unitText(stripClone(u)) === text);
    const idx = same.indexOf(el);
    return idx === -1 ? same.length : idx;
  }

  function occurrences(haystack, needle) {
    if (!needle) return 0;
    let n = 0, i = 0;
    while ((i = haystack.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
    return n;
  }

  // Index of the (0-based) nth occurrence of `needle` in `haystack`, or -1.
  function nthIndexOf(haystack, needle, n) {
    let idx = -1;
    for (let i = 0; i <= n; i++) {
      idx = haystack.indexOf(needle, idx + 1);
      if (idx === -1) return -1;
    }
    return idx;
  }

  // ── Boot tracking (guards pruneMarks against a partially-built document) ──
  //
  // loadAndRenderBlocks() (and reconcile()'s insert-new-block path) build
  // sections in a fully synchronous per-block loop: createBlockSection(blk)
  // — which calls decorate(), which calls renderDock() at its end — runs
  // BEFORE the caller appends that section to the document. So mid-loop,
  // `document` only contains whichever earlier blocks have already been
  // appended; later blocks in the same batch are legitimately still
  // "missing" even though they're about to land. Pruning against that
  // half-built snapshot would wrongly treat those still-pending blocks'
  // marks as orphaned and delete them.
  //
  // Fix: arm a setTimeout(0) the first time decorate() runs. Because the
  // whole per-block loop (all blocks, one synchronous call stack) never
  // awaits mid-loop, a timer queued during it can only fire on a LATER
  // macrotask — i.e. strictly after that entire loop (and everything after
  // it in the same synchronous turn) has finished unwinding. `booted` can
  // therefore never flip true while a per-block loop is still in progress,
  // regardless of how many blocks it contains or how far through it we are.
  let booted = false;
  let bootTimerArmed = false;
  function armBootTimer() {
    if (bootTimerArmed) return;
    bootTimerArmed = true;
    setTimeout(() => { booted = true; }, 0);
  }

  // Drop local marks whose block (or, best-effort, whose specific unit)
  // no longer exists. Reachable whenever Claude removes a block (or a
  // unit's text changes) out from under a pending local mark — e.g. the
  // user marks a list item, then dismisses the whole section via the
  // block-header path. Block-gone is the critical half: an orphaned
  // block_id 422s the ENTIRE round on submit (server.py's _handle_round
  // rejects on the first unknown block_id), which without this pruning
  // would wedge Submit forever with no user-visible recovery short of a
  // devtools localStorage clear. Unit-gone (text no longer resolves within
  // an otherwise-live block) is best-effort cleanup on top of that.
  function pruneMarks() {
    if (!booted) return;                      // see boot-tracking note above
    const liveSections = document.querySelectorAll("main.prose section.block");
    if (!liveSections.length) return;          // belt-and-suspenders
    const liveBlockIds = new Set();
    const contentByBlock = new Map();
    liveSections.forEach((s) => {
      const id = s.dataset.blockId;
      if (!id) return;
      liveBlockIds.add(id);
      const c = s.querySelector(".block-content");
      if (c) contentByBlock.set(id, c);
    });
    let pruned = false;
    for (const [key, m] of Object.entries(marks)) {
      if (!liveBlockIds.has(m.block_id)) {
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
      if (m.step_id) continue;
      const content = contentByBlock.get(m.block_id);
      if (content && typeof m.ordinal === "number") {
        const same = Array.from(content.querySelectorAll(".sub-unit"))
          .filter((u) => unitText(stripClone(u)) === m.selected_text);
        if (m.ordinal >= same.length) {
          delete marks[key];
          pruned = true;
        }
      }
    }
    if (pruned) saveMarks();
  }

  // The four controls, in one place so the card header and the sub-unit
  // strip can never drift apart. Same order, same meaning, same glyphs at
  // both scopes — position is what tells the user the scope, not the icon.
  // Tooltips name the consequence, not the gesture: "delete" has to read as
  // destructive-but-undoable, and "keep" has to read as a protection rather
  // than applause, or we are back to the vocabulary that confused everyone.
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
    ["keep",    "✓", "Keep — don't rewrite this"],
    ["comment", "💬", "Comment — fold a response into this"],
    ["compact", COMPACT_ICON,
     "Compact — take this off the page; its point is folded into what stays"],
  ];
  const CONTROLS = { unit: CONTROL_SPECS, block: CONTROL_SPECS };

  // The four sub-unit types (spec decision: all four, one DOM walk).
  // Top-level only: a nested list belongs to its parent bullet's unit.
  const UNIT_SELECTOR = [
    ":scope > ul > li",
    ":scope > ol > li",
    ":scope > p",
    ":scope > pre",
    ":scope > table tbody tr",
    // markdown-it wraps tables bare (no wrapper div); some blocks nest the
    // table under a div via free HTML. The descendant combinator here
    // matches the table at any depth under that div, not just one level.
    ":scope > div table tbody tr",
  ].join(", ");

  function decorate(content, section) {
    armBootTimer();
    const blockId = section && section.dataset ? section.dataset.blockId : null;
    if (!blockId || !content) return;
    let units;
    try { units = content.querySelectorAll(UNIT_SELECTOR); }
    catch { return; }
    units.forEach((el) => {
      // Authored sub-units keep their existing immediate-comment path.
      if (el.closest("[data-annotate-id]")) return;
      if (el.classList.contains("sub-unit")) {
        applyMarkState(content, el, blockId);
        return;
      }
      const text = unitText(el);
      if (!text) return;
      el.classList.add("sub-unit");
      const strip = document.createElement("span");
      strip.className = "unit-strip";
      for (const [kind, glyph, title] of CONTROLS.unit) {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.kind = kind;
        // innerHTML, not textContent: three of the four glyphs are emoji but
        // compact's is an inline SVG. Every glyph here is a module constant —
        // nothing user-supplied reaches this line.
        b.innerHTML = glyph;
        b.title = title;
        // Capture `content` (the decorated root) in this closure rather than
        // re-deriving it via el.closest() at click time — one consistent
        // mechanism for both the detached-DOM initial pass and any later
        // (already-attached) re-decoration.
        b.addEventListener("click", (ev) => {
          ev.stopPropagation();
          ev.preventDefault();
          if (document.body.classList.contains("is-busy")) return;
          if (kind === "comment") openComposer(content, el, blockId);
          else toggleMark(content, el, blockId, kind);
        });
        strip.appendChild(b);
      }
      el.appendChild(strip);
      applyMarkState(content, el, blockId);
    });
    // A re-render replaces the section element, dropping the data attribute a
    // pending block mark painted onto it — restore it here, where we already
    // know the DOM has just been rebuilt.
    paintBlock(blockId);
    renderDock();
  }

  function toggleMark(root, el, blockId, kind) {
    const text = unitText(stripClone(el));
    const ordinal = unitOrdinal(root, el, text);
    const key = markKey(blockId, text, ordinal);
    const existing = marks[key];
    if (existing && existing.kind === kind) {
      delete marks[key];                      // undo
    } else {
      marks[key] = buildMark(root, el, blockId, kind, ordinal,
        existing && existing.kind === "comment" ? existing.text : "");
    }
    saveMarks();
    applyMarkState(root, el, blockId);
    renderDock();
  }

  // textContent of the unit minus our own UI (strip, chip, composer).
  function stripClone(el) {
    const c = el.cloneNode(true);
    c.querySelectorAll(".unit-strip, .unit-chip, .unit-composer")
      .forEach(n => n.remove());
    return c;
  }

  // `root` is the decorated `.block-content` subtree (see unitOrdinal for
  // why it's threaded down rather than re-derived via el.closest()).
  // blockText comes from that same subtree — the rendered markdown content
  // only, excluding card-title/header chrome — which is also strictly
  // better prefix/suffix context: it matches what the markdown source
  // actually contains.
  function buildMark(root, el, blockId, kind, ordinal, text) {
    const selected = unitText(stripClone(el));
    // `ordinal` is stored for internal bookkeeping only — never copied onto
    // the wire payload (see submitRound's explicit field list).
    const mark = { scope: "unit", block_id: blockId, kind,
                   selected_text: selected, ordinal };
    if (text) mark.text = text;
    if (root) {
      const blockText = unitText(stripClone(root));
      if (occurrences(blockText, selected) > 1) {
        const idx = nthIndexOf(blockText, selected, ordinal);
        if (idx !== -1) {
          mark.prefix = blockText.slice(Math.max(0, idx - 20), idx);
          mark.suffix = blockText.slice(idx + selected.length,
                                        idx + selected.length + 20);
        }
      }
    }
    return mark;
  }

  function applyMarkState(root, el, blockId) {
    const text = unitText(stripClone(el));
    const ordinal = unitOrdinal(root, el, text);
    const m = marks[markKey(blockId, text, ordinal)];
    if (m) el.dataset.mark = m.kind;
    else delete el.dataset.mark;
    let chip = el.querySelector(".unit-chip");
    if (m && m.kind === "comment" && m.text) {
      // Rebuild the chip each pass: label + a × that unpins the comment.
      if (chip) chip.remove();
      chip = document.createElement("span");
      chip.className = "unit-chip";
      const label = document.createElement("span");
      label.className = "unit-chip-text";
      label.textContent = (m.disagree ? "👎 " : "💬 ") + m.text;
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "unit-chip-remove";
      rm.textContent = "×";
      rm.title = "Remove this comment";
      rm.setAttribute("aria-label", "Remove comment");
      rm.addEventListener("click", (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        delete marks[markKey(blockId, text, ordinal)];
        saveMarks();
        applyMarkState(root, el, blockId);
        renderDock();
      });
      chip.append(label, rm);
      el.appendChild(chip);
    } else if (chip) chip.remove();
  }

  // ── Inline per-unit composer (local pin, not a submit) ────────────────────
  let openComposerEl = null;

  function openComposer(root, el, blockId) {
    closeComposer();
    const text = unitText(stripClone(el));
    const ordinal = unitOrdinal(root, el, text);
    const existing = marks[markKey(blockId, text, ordinal)];
    const wrap = document.createElement("span");
    wrap.className = "unit-composer";
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Ask or push back on this item…";
    input.value = (existing && existing.kind === "comment" && existing.text) || "";
    // Disagreement is a flag on a comment, not a fourth control: under the
    // hood both keep the content and both make Claude rewrite it. The only
    // difference is the instruction — a disagree tells Claude to concede or
    // defend rather than quietly fold the note in as agreement.
    const stanceId = `unit-disagree-${Math.random().toString(36).slice(2, 9)}`;
    const stance = document.createElement("label");
    stance.className = "unit-composer-stance";
    stance.htmlFor = stanceId;
    const stanceBox = document.createElement("input");
    stanceBox.type = "checkbox";
    stanceBox.id = stanceId;
    stanceBox.checked = !!(existing && existing.disagree);
    stance.append(stanceBox, document.createTextNode(" I disagree"));
    const pin = document.createElement("button");
    pin.type = "button";
    pin.textContent = "Pin";
    const commit = () => {
      const v = input.value.trim();
      const key = markKey(blockId, text, ordinal);
      if (v) {
        const m = buildMark(root, el, blockId, "comment", ordinal, v);
        if (stanceBox.checked) m.disagree = true;
        marks[key] = m;
      } else delete marks[key];
      saveMarks();
      closeComposer();
      applyMarkState(root, el, blockId);
      renderDock();
    };
    pin.addEventListener("click", commit);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); commit(); }
      if (ev.key === "Escape") { ev.preventDefault(); closeComposer(); }
    });
    wrap.append(input, stance, pin);
    el.appendChild(wrap);
    openComposerEl = wrap;
    input.focus();
  }

  function closeComposer() {
    if (openComposerEl) { openComposerEl.remove(); openComposerEl = null; }
  }

  // ── Round dock ─────────────────────────────────────────────────────────────
  function renderDock() {
    pruneMarks();
    let dock = document.getElementById("round-dock");
    const count = Object.keys(marks).length;
    // Keep the dock alive while a round is in flight even if the user
    // unmarks everything after Submit but before busy/consumed_events
    // propagate back — otherwise it flashes away and reappears.
    if (!count && !pendingRound) { if (dock) dock.remove(); return; }
    if (!dock) {
      dock = document.createElement("div");
      dock.id = "round-dock";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = "round-submit";
      btn.addEventListener("click", submitRound);
      dock.appendChild(btn);
      document.body.appendChild(dock);
    }
    const btn = dock.querySelector("#round-submit");
    if (pendingRound) {
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
    btn.disabled = !!pendingRound || document.body.classList.contains("is-busy");
  }

  function submitRound() {
    pruneMarks();                              // never submit an orphaned block_id
    if (pendingRound) return;                  // synchronous double-click guard
    const reactions = Object.values(marks).map((m) => {
      const r = { scope: m.scope || "unit", kind: m.kind, block_id: m.block_id,
                  selected_text: m.selected_text || "",
                  text: m.text || "", images: m.images || [] };
      if (m.step_id) r.step_id = m.step_id;
      if (m.disagree) r.disagree = true;
      if (m.prefix !== undefined) r.prefix = m.prefix;
      if (m.suffix !== undefined) r.suffix = m.suffix;
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
    lastSubmittedBlockIds = [...new Set(reactions.map(r => r.block_id))];
    WebCompanion.api.submit({ type: "round", reactions }).then((res) => {
      pendingRound = res && res.event_id ? String(res.event_id) : null;
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
    saveMarks();
    document.querySelectorAll(".sub-unit[data-mark]").forEach(el => {
      delete el.dataset.mark;
      el.querySelector(".unit-chip")?.remove();
    });
    document.querySelectorAll("section.block[data-block-mark]").forEach(s => {
      delete s.dataset.blockMark;
    });
    renderDock();
  }

  // ── Block scope ───────────────────────────────────────────────────────────
  //
  // Driven by the card header strip in script.js. A block carries at most one
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
  // set for diagram/flowchart nodes and authored data-annotate-id sub-units;
  // absent means the comment is about the whole block.
  function pinComment({ block_id, step_id, text, disagree, images,
                        selected_text, prefix, suffix }) {
    if (!block_id || !text) return;
    const key = step_id ? stepMarkKey(block_id, step_id) : blockMarkKey(block_id);
    const m = { scope: step_id ? "unit" : "block", block_id, kind: "comment", text };
    if (step_id) m.step_id = step_id;
    if (disagree) m.disagree = true;
    if (images && images.length) m.images = images;
    if (selected_text) m.selected_text = selected_text;
    if (prefix !== undefined) m.prefix = prefix;
    if (suffix !== undefined) m.suffix = suffix;
    marks[key] = m;
    saveMarks();
    if (!step_id) paintBlock(block_id);
    renderDock();
  }

  function blockMark(blockId) {
    return marks[blockMarkKey(blockId)] || null;
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
    if (pendingRound && Array.isArray(data.consumed_events) &&
        data.consumed_events.map(String).includes(pendingRound)) {
      clearRound();
      return;
    }
    // Mirrors script.js's watcher_age_s > WATCHER_DEAD_AFTER_S handling: a
    // dead watcher means no ack is ever coming for our in-flight round
    // either, so don't leave the dock wedged on "Applying round…" forever.
    // Marks stay put — they're still valid local state the user can retry.
    if (pendingRound && typeof data.watcher_age_s === "number" &&
        data.watcher_age_s > WATCHER_DEAD_AFTER_S) {
      pendingRound = null;
      renderDock();
      return;
    }
    renderDock();
  }

  window.AnnotateSubunits = {
    decorate, onPoll,
    // Block/step scope, driven by the card header strip in script.js.
    toggleBlockMark, pinComment, blockMark, repaintBlocks, renderDock,
    CONTROLS,
    submittedBlockIds: () => lastSubmittedBlockIds.slice(),
  };
})();
