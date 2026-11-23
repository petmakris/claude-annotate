// annotate page code, part 5 of 9 (see script.js): comment cards.

// ── Comment cards ──────────────────────────────────────────────────────────

// Resolve a diagram step (or free-HTML data-annotate-id region) to its row node, display
// label, and 1-based ordinal — so a comment card can name the row it targets.
function stepContextFor(blockId, stepId) {
  if (!blockId || !stepId) return null;
  const section = document.querySelector(`section.block[data-block-id="${cssEsc(blockId)}"]`);
  if (!section) return null;
  let node = section.querySelector(`[data-step-id="${cssEsc(stepId)}"]`);
  let ordinal = null;
  let row = false;
  if (node) {
    ordinal = [...section.querySelectorAll("[data-step-id]")].indexOf(node) + 1;
  } else {
    node = section.querySelector(`[data-annotate-id="${cssEsc(stepId)}"]`);
    // A table row (tables.js): named ROW n, n counting the part's body rows.
    if (node && node.tagName === "TR") {
      row = true;
      ordinal = [...section.querySelectorAll("table tbody tr")].indexOf(node) + 1;
    }
  }
  if (!node) return null;
  const labelNode = node.querySelector ? node.querySelector(".arrow-label") : null;
  let label = ((labelNode ? labelNode.textContent : node.textContent) || "")
    .replace(/\s+/g, " ").trim();
  if (label.length > 48) label = label.slice(0, 47).trimEnd() + "…";
  return { node, ordinal, label, row };
}

// Add the "updating" spinner overlay + timer to a block section. Idempotent:
// a section already overlaid is left alone.
// Started on every part a submitted round names (registerRoundEvent), cleared by its ack, its new version
// or the page going idle without one (onPollDelta).
function startUpdatingOverlay(section) {
  if (!section) return;
  section.classList.add("is-updating");
  if (section.querySelector(".updating-overlay")) return;
  const overlay = document.createElement("div");
  overlay.className = "updating-overlay";
  // Not a live region. A round names many parts, and a live overlay on each
  // read its timer out every second; the round says "updating" once instead
  // (registerRoundEvent), as progress.js does for its own timer.
  const pill = document.createElement("div");
  pill.className = "updating-pill";
  const spinner = document.createElement("span");
  spinner.className = "updating-spinner";
  pill.appendChild(spinner);
  const label = document.createElement("span");
  label.className = "updating-label";
  label.textContent = "updating";
  pill.appendChild(label);
  const timer = document.createElement("span");
  timer.className = "updating-timer";
  timer.setAttribute("aria-hidden", "true");
  timer.textContent = "0:00";
  pill.appendChild(timer);
  overlay.appendChild(pill);
  section.appendChild(overlay);
  const startedAt = Date.now();
  section._updatingTimerId = setInterval(() => {
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = String(elapsed % 60).padStart(2, "0");
    timer.textContent = `${m}:${s}`;
  }, 1000);
}

// The picture strip under a comment's text box, shared by every comment
// body: a part's comment (buildCard), the selection's box (selection.js) and
// the whole-response composer (script-chrome.js). A picture comes in two
// ways: pasted, or drawn on the drawing pad (drawpad.js) from the strip's
// Draw button. Either way it is uploaded, its token goes into the text at the
// caret (`![paste-1]`, `![drawing-2]`), and `onImages` hears the whole list
// each time it changes. A drawing's tile opens the pad again on its lines.
// Returns the strip, for the caller to place under the text box. The Draw
// button goes where `placeDraw(button)` puts it, so a caller can set it in its
// own button row at no cost in height; with no `placeDraw` it heads the strip.
//
// The lines of each drawing, by its uploaded path, so a drawing reopened
// after its comment window was rebuilt can still be edited. Lost on reload:
// the picture is kept, only re-editing it is not.
const DRAWING_STROKES = new Map();

function attachPaste(ta, images, onImages, placeDraw) {
  let pastes = (images || []).map(img => ({ token: img.token, path: img.path, thumbUrl: null }));
  const used = pastes.map(p => Number(String(p.token).split("-").pop()) || 0);
  let nextIndex = Math.max(0, ...used) + 1;
  const strip = document.createElement("div");
  strip.className = "paste-strip";

  const drawBtn = document.createElement("button");
  drawBtn.type = "button";
  drawBtn.className = "paste-draw";
  drawBtn.title = "Draw a picture to attach";
  drawBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
    + 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14.5 6.5l3 3"/></svg>'
    + '<span>Draw</span>';
  drawBtn.addEventListener("click", (ev) => { ev.stopPropagation(); openPad(null); });

  function changed() {
    onImages(pastes.map(p => ({ token: p.token, path: p.path })));
  }

  // Put `![token]` into the text where the caret was, and let the owner keep
  // its text from its own input listener.
  function insertToken(token, at) {
    const insertion = `![${token}]`;
    const start = at ? at.start : ta.selectionStart;
    const end = at ? at.end : ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + insertion + ta.value.slice(end);
    const caret = start + insertion.length;
    ta.setSelectionRange(caret, caret);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function openPad(existing) {
    if (!window.DrawPad) { showPasteError("drawing is not available"); return; }
    // The pad takes focus, so remember where the caret was now.
    const at = { start: ta.selectionStart, end: ta.selectionEnd };
    window.DrawPad.open({
      title: existing ? `Edit ${existing.token}` : "New drawing",
      doneLabel: existing ? "Update drawing" : "Attach drawing",
      strokes: existing ? DRAWING_STROKES.get(existing.path) : null,
      returnFocus: ta,
      onDone: async (blob, strokes) => {
        let result;
        try {
          result = await WebCompanion.api.pasteImage(blob);
        } catch (_) {
          showPasteError("upload failed");
          return;
        }
        DRAWING_STROKES.set(result.path, strokes);
        if (existing) {
          const p = pastes.find(x => x.token === existing.token);
          if (p) { p.path = result.path; p.thumbUrl = URL.createObjectURL(blob); }
        } else {
          const token = `drawing-${nextIndex++}`;
          insertToken(token, at);
          pastes.push({ token, path: result.path, thumbUrl: URL.createObjectURL(blob) });
        }
        changed();
        render();
        ta.focus({ preventScroll: true });
      },
    });
  }

  function render() {
    const own = !drawBtn.parentNode || drawBtn.parentNode === strip;
    strip.replaceChildren(...(own ? [drawBtn] : []));
    if (pastes.length === 0 && !own) strip.dataset.empty = "1";
    else delete strip.dataset.empty;
    for (const p of pastes) {
      const tile = document.createElement("div");
      tile.className = "paste-thumb";
      tile.dataset.token = p.token;
      const img = document.createElement("img");
      img.alt = p.token;
      if (p.thumbUrl) img.src = p.thumbUrl;
      else tile.classList.add("no-thumb");
      const label = document.createElement("span");
      label.className = "paste-label";
      label.textContent = p.token;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "paste-remove";
      remove.title = "Remove";
      remove.setAttribute("aria-label", `Remove ${p.token}`);
      remove.textContent = "×";
      remove.addEventListener("click", (ev) => {
        ev.stopPropagation();
        pastes = pastes.filter(x => x.token !== p.token);
        changed();
        render();
      });
      tile.appendChild(img);
      tile.appendChild(label);
      tile.appendChild(remove);
      if (DRAWING_STROKES.has(p.path)) {
        tile.classList.add("is-drawing");
        tile.title = "Edit this drawing";
        tile.tabIndex = 0;
        tile.setAttribute("role", "button");
        tile.setAttribute("aria-label", `Edit ${p.token}`);
        tile.addEventListener("click", () => openPad(p));
        tile.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openPad(p); }
        });
      }
      strip.appendChild(tile);
    }
  }

  let errorChipTimer = null;
  function showPasteError(msg) {
    let chip = strip.querySelector(".paste-error");
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "paste-error";
      strip.appendChild(chip);
    }
    chip.textContent = msg;
    if (errorChipTimer) clearTimeout(errorChipTimer);
    errorChipTimer = setTimeout(() => { chip.remove(); errorChipTimer = null; }, 4000);
  }

  ta.addEventListener("paste", async (ev) => {
    const items = ev.clipboardData?.items;
    if (!items) return;
    let imageItem = null;
    for (const it of items) {
      if (it.kind === "file" && it.type.startsWith("image/")) { imageItem = it; break; }
    }
    if (!imageItem) return;
    ev.preventDefault();
    const blob = imageItem.getAsFile();
    if (!blob) return;
    const token = `paste-${nextIndex++}`;
    insertToken(token, null);
    try {
      const result = await WebCompanion.api.pasteImage(blob);
      pastes.push({ token, path: result.path, thumbUrl: URL.createObjectURL(blob) });
      changed();
      render();
    } catch (_) {
      showPasteError("upload failed");
    }
  });

  if (placeDraw) placeDraw(drawBtn);
  render();
  return strip;
}

function buildCard(id, a, onSubmitCb) {
  const card = document.createElement("div");
  card.className = "comment-card";
  card.dataset.id = id;
  card.dataset.type = a.type;

  // For diagram-row / data-annotate-id region comments, head the card with the step it
  // targets, and wire a focus/hover link that highlights the matching row.
  const stepCtx = a.step_id ? stepContextFor(a.block_id, a.step_id) : null;

  if (a.step_id) {
    const head = document.createElement("div");
    head.className = "card-step-head";
    const chip = document.createElement("span");
    chip.className = "card-step-chip";
    chip.textContent = stepCtx && stepCtx.ordinal
      ? `${stepCtx.row ? "ROW" : "STEP"} ${stepCtx.ordinal}` : a.step_id;
    head.appendChild(chip);
    if (stepCtx && stepCtx.label) {
      const lbl = document.createElement("span");
      lbl.className = "card-step-label";
      lbl.textContent = stepCtx.label;
      head.appendChild(lbl);
    }
    card.appendChild(head);

    // Card ↔ row link: focusing or hovering the card lights up its row.
    const row = stepCtx && stepCtx.node;
    if (row) {
      const on = () => { row.dataset.cardFocus = "1"; };
      const off = () => { delete row.dataset.cardFocus; };
      card.addEventListener("mouseenter", on);
      card.addEventListener("mouseleave", off);
      card.addEventListener("focusin", on);
      card.addEventListener("focusout", off);
    }
  }

  const wrap = document.createElement("div");
  wrap.className = "editor-wrap";

  const ta = document.createElement("textarea");
  const placeholder = PLACEHOLDER_TEXT[a.type] || PLACEHOLDER_TEXT.comment;
  ta.placeholder = placeholder;
  ta.value = a.comment || "";
  ta.addEventListener("input", () => {
    annotations[id].comment = ta.value;
    saveDrafts();
    autoGrow();
  });

  const autoGrow = () => {
    if (wrap.dataset.userSized === "1") return;
    ta.style.height = "auto";
    const cap = Math.max(160, Math.round(window.innerHeight * 0.5));
    ta.style.height = Math.min(ta.scrollHeight + 2, cap) + "px";
  };

  ta.addEventListener("focus", autoGrow);

  const handle = document.createElement("div");
  handle.className = "editor-resize";
  handle.title = "Drag to resize · double-click to reset";
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const startY = e.clientY;
    const startH = ta.offsetHeight;
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const newH = Math.max(60, startH + (ev.clientY - startY));
      ta.style.height = newH + "px";
      wrap.dataset.userSized = "1";
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    // pointercancel fires if capture is lost (e.g. the card is replaced by a
    // poll-driven update mid-drag); without this the move listener would leak
    // on a detached node, pinning the textarea/wrap closures.
    handle.addEventListener("pointercancel", up);
  });
  handle.addEventListener("dblclick", () => {
    delete wrap.dataset.userSized;
    ta.style.height = "";
    autoGrow();
  });

  wrap.appendChild(ta);
  wrap.appendChild(handle);
  card.appendChild(wrap);
  let drawButton = null;
  card.appendChild(attachPaste(ta, annotations[id].images, (images) => {
    if (!annotations[id]) return;
    if (images.length) annotations[id].images = images;
    else delete annotations[id].images;
    saveDrafts();
  }, (b) => { drawButton = b; }));
  // Auto-grow once on initial render so a card with prior content shows it all.
  queueMicrotask(autoGrow);

  // ── Add button ─────────────────────────────────────────────────────────
  const submitRow = document.createElement("div");
  submitRow.className = "card-submit-row";
  const hint = document.createElement("span");
  hint.className = "card-submit-hint";
  // The button pins into the round; nothing is sent until the round dock's
  // Submit, so the label must not promise delivery.
  hint.innerHTML = '<kbd>⌘</kbd><kbd>↩</kbd> to add';
  submitRow.appendChild(hint);
  submitRow.appendChild(drawButton);
  const submitBtn = document.createElement("button");
  submitBtn.type = "button";
  submitBtn.className = "card-submit-btn";
  submitBtn.textContent = "Add to round";
  // ⌘/Ctrl+Enter submits from the textarea.
  ta.addEventListener("keydown", (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
      ev.preventDefault();
      if (!submitBtn.disabled) submitBtn.click();
    }
  });
  submitBtn.addEventListener("click", () => {
    const text = annotations[id]?.comment || "";
    const images = annotations[id]?.images || [];
    if (!text.trim()) return;
    // Pin into the review round instead of submitting. Nothing wakes Claude
    // until the round dock's Submit — one timing model for every piece of
    // content feedback, so a click never has an invisible "this one sends
    // now" exception.
    window.AnnotateSubunits?.pinComment({
      block_id: a.block_id,
      step_id: a.step_id ?? null,
      text,
      images,
      selected_text: a.selected_text || "",
      prefix: a.prefix,
      suffix: a.suffix,
    });
    delete annotations[id];
    saveDrafts();
    document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
    // Re-render the dock in THIS tick. Its Submit button is disabled while
    // `is-editing`, but renderDock otherwise only runs on the 1s poll — so
    // without this there is a window where an editor is open and Submit is
    // still live, which drops the comment the user is mid-way through
    // writing. That window is the bug; a narrower window is not a fix.
    window.AnnotateSubunits?.renderDock();
    // Closing the window takes the focused button with it, and focus would
    // fall to <body>: the next Tab restarted from the top of the page. Hand
    // it to the part, and say what happened, since the window vanishing is
    // all a screen reader would otherwise get.
    const home = document.querySelector(
      `section.block[data-block-id="${cssEsc(a.block_id)}"]`);
    window.AnnotateCommentWindow.close("card:" + id);
    applyEngagedStyling();
    focusHome(home);
    window.AnnotateA11y?.announce("Comment added to the round");
  });
  // Cancel is the window's ×: the draft goes, and focus goes back to the
  // part (comment-window.js close()).
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "comment-cancel";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => window.AnnotateCommentWindow.close("card:" + id));
  submitRow.appendChild(cancelBtn);
  submitRow.appendChild(submitBtn);
  card.appendChild(submitRow);

  return card;
}

function renderComments() {
  // Prune orphan drafts: a block-scoped draft whose block no longer exists
  // (Claude removed it) can never render its card — and thus can never be
  // closed — so it would linger in localStorage forever. Also drop any
  // legacy block_id-null drafts from the retired general-comments UI; the
  // page-level composer no longer renders cards for them.
  //
  // isEmptyDraft was a third condition here and had to come out: it made
  // opening a comment impossible. openAnnotation creates the draft, saves
  // it, and calls this to draw its card — but a draft that has just been
  // opened has no text in it yet, so it IS empty, and this pruned it before
  // the card was ever built. Clicking the comment icon wrote the draft to
  // localStorage and deleted it again in the same tick, and the page did
  // not so much as flicker. Empty drafts are still dropped, in the two
  // places that can tell an abandoned one from a live one: openAnnotation,
  // before it opens a different target, and loadDrafts, on the way in.
  let pruned = false;
  for (const [id, a] of Object.entries(annotations)) {
    if (!a.block_id ||
        !document.querySelector(`section.block[data-block-id="${cssEsc(a.block_id)}"]`)) {
      delete annotations[id];
      pruned = true;
    }
  }
  if (pruned) saveDrafts();

  const W = window.AnnotateCommentWindow;
  const entries = Object.entries(annotations);
  if (!entries.length) {
    if (W.owner() && W.owner().startsWith("card:")) W.close();
  } else {
    const [id, a] = entries[0];
    // A window holding the reader's words for another owner (the selection's
    // box, when a response switch brings back a saved draft) is not replaced:
    // the draft waits, and the box's close calls this again to show it.
    if (W.owner() !== "card:" + id && !W.hasWords()) {
      const section = document.querySelector(`section.block[data-block-id="${cssEsc(a.block_id)}"]`);
      const step = a.step_id ? stepContextFor(a.block_id, a.step_id) : null;
      // An untitled part's label line is empty and display:none, so its box
      // is all zeros and the window would open at the top of the screen:
      // place it by the part's first line instead.
      let label = (section && section.querySelector(".block-label")) || section;
      if (label && label !== section) {
        const r = label.getBoundingClientRect();
        if (!r.width && !r.height) {
          label = section.querySelector(".block-content > :first-child") || section;
        }
      }
      window.AnnotateCommentWindow.open({
        owner: "card:" + id,
        quote: a.selected_text || (step && step.label) || (section ? section.dataset.label || "" : ""),
        body: buildCard(id, a),
        near: (step && step.node ? step.node : label).getBoundingClientRect(),
        home: () => document.querySelector(`section.block[data-block-id="${cssEsc(a.block_id)}"]`),
        // The window's × is the old card's ×: the draft goes with it.
        onClose: () => {
          if (!annotations[id]) return;
          delete annotations[id];
          saveDrafts();
          document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
          applyEngagedStyling();
          window.AnnotateSubunits?.renderDock();
        },
      });
    }
  }

  // EDITING lock: an open comment draft means one editor is active.
  document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
  // Same tick, same reason as the submit path above: the dock's disabled
  // state reads `is-editing`, so it has to be repainted the moment the
  // class moves rather than on the next poll.
  window.AnnotateSubunits?.renderDock();
}

function focusComment(id) {
  const ta = document.querySelector(".comment-window textarea");
  if (ta) ta.focus({ preventScroll: true });
}

// One editor at a time is the rule, and it stands. Refusing in SILENCE is
// what had to go: a comment icon that does nothing when clicked is
// indistinguishable from a broken one — which is exactly what it was
// mistaken for, and reported as, when renderComments was deleting these
// drafts at the moment they were created. The open comment window is the
// reason: it pulses and takes the caret (comment-window.js call()).
function revealOpenDraft() {
  window.AnnotateCommentWindow.call();
}
