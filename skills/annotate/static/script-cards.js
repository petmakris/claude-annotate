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
  if (node) {
    ordinal = [...section.querySelectorAll("[data-step-id]")].indexOf(node) + 1;
  } else {
    node = section.querySelector(`[data-annotate-id="${cssEsc(stepId)}"]`);
  }
  if (!node) return null;
  const labelNode = node.querySelector ? node.querySelector(".arrow-label") : null;
  let label = ((labelNode ? labelNode.textContent : node.textContent) || "")
    .replace(/\s+/g, " ").trim();
  if (label.length > 48) label = label.slice(0, 47).trimEnd() + "…";
  return { node, ordinal, label };
}

// Add the "updating" spinner overlay + timer to a block section. Idempotent:
// a section already overlaid is left alone. Its last caller was the choice
// block's own Submit, which is gone now that answers ride the round.
function startUpdatingOverlay(section) {
  if (!section) return;
  section.classList.add("is-updating");
  if (section.querySelector(".updating-overlay")) return;
  const overlay = document.createElement("div");
  overlay.className = "updating-overlay";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
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

function buildCard(id, a, onSubmitCb) {
  const card = document.createElement("div");
  card.className = "comment-card";
  card.dataset.id = id;
  card.dataset.type = a.type;

  // For diagram-row / data-annotate-id region comments, head the card with the step it
  // targets, and wire a focus/hover link that highlights the matching row.
  const stepCtx = a.step_id ? stepContextFor(a.block_id, a.step_id) : null;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "card-close";
  closeBtn.dataset.type = a.type;
  closeBtn.title = "Remove";
  closeBtn.setAttribute("aria-label", "Remove annotation");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", () => {
    delete annotations[id];
    saveDrafts();
    renderComments();
    applyEngagedStyling();
  });
  card.appendChild(closeBtn);

  if (a.step_id) {
    const head = document.createElement("div");
    head.className = "card-step-head";
    const chip = document.createElement("span");
    chip.className = "card-step-chip";
    chip.textContent = stepCtx && stepCtx.ordinal ? `STEP ${stepCtx.ordinal}` : a.step_id;
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

  if (a.selected_text) {
    const quote = document.createElement("div");
    quote.className = "quote";
    quote.dataset.type = a.type;
    quote.textContent = a.selected_text;
    card.appendChild(quote);
  }

  const wrap = document.createElement("div");
  wrap.className = "editor-wrap";

  const ta = document.createElement("textarea");
  const pasteState = {
    pastes: (annotations[id].images || []).map(img => ({
      token: img.token,
      path: img.path,
      thumbUrl: null,
    })),
    nextIndex: ((annotations[id].images || []).length) + 1,
  };

  const pasteStrip = document.createElement("div");
  pasteStrip.className = "paste-strip";
  if (pasteState.pastes.length === 0) pasteStrip.dataset.empty = "1";

  function renderStrip() {
    pasteStrip.replaceChildren();
    if (pasteState.pastes.length === 0) {
      pasteStrip.dataset.empty = "1";
      return;
    }
    delete pasteStrip.dataset.empty;
    for (const p of pasteState.pastes) {
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
      remove.textContent = "×";
      remove.addEventListener("click", (ev) => {
        ev.stopPropagation();
        pasteState.pastes = pasteState.pastes.filter(x => x.token !== p.token);
        persistImages();
        renderStrip();
      });
      tile.appendChild(img);
      tile.appendChild(label);
      tile.appendChild(remove);
      pasteStrip.appendChild(tile);
    }
  }

  function persistImages() {
    if (pasteState.pastes.length === 0) {
      delete annotations[id].images;
    } else {
      annotations[id].images = pasteState.pastes.map(p => ({ token: p.token, path: p.path }));
    }
    saveDrafts();
  }

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
  card.appendChild(pasteStrip);
  renderStrip();
  // Auto-grow once on initial render so a card with prior content shows it all.
  queueMicrotask(autoGrow);

  // ── Add button ─────────────────────────────────────────────────────────
  const submitRow = document.createElement("div");
  submitRow.className = "card-submit-row";
  const hint = document.createElement("span");
  hint.className = "card-submit-hint";
  // The button pins into the round; nothing is sent until the round dock's
  // Submit, so the label must not promise delivery.
  hint.innerHTML = '<kbd>⌘</kbd><kbd>↩</kbd> to add · paste an image to attach';
  submitRow.appendChild(hint);
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
    // Removing the card took the focused button with it, and focus fell to
    // <body>: the next Tab restarted from the top of the page. Hand it to
    // the section's fold button, and say what happened, since the card
    // vanishing is all a screen reader would otherwise get.
    const home = document.querySelector(
      `section.block[data-block-id="${cssEsc(a.block_id)}"]`);
    card.remove();
    applyEngagedStyling();
    home?.querySelector(".card-chevron")?.focus();
    window.AnnotateA11y?.announce("Comment added to the round");
  });
  submitRow.appendChild(submitBtn);
  card.appendChild(submitRow);

  // ── Image paste ────────────────────────────────────────────────────────
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
    const token = `paste-${pasteState.nextIndex++}`;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const insertion = `![${token}]`;
    ta.value = ta.value.slice(0, start) + insertion + ta.value.slice(end);
    const caret = start + insertion.length;
    ta.setSelectionRange(caret, caret);
    annotations[id].comment = ta.value;
    saveDrafts();
    try {
      const result = await WebCompanion.api.pasteImage(blob);
      pasteState.pastes.push({ token, path: result.path, thumbUrl: URL.createObjectURL(blob) });
      persistImages();
      renderStrip();
    } catch (_) {
      showPasteError("upload failed");
    }
  });

  let errorChipTimer = null;
  function showPasteError(msg) {
    let chip = pasteStrip.querySelector(".paste-error");
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "paste-error";
      pasteStrip.appendChild(chip);
    }
    chip.textContent = msg;
    if (errorChipTimer) clearTimeout(errorChipTimer);
    errorChipTimer = setTimeout(() => { chip.remove(); errorChipTimer = null; }, 4000);
  }

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

  document.querySelectorAll(".inline-comments").forEach(el => el.remove());

  const byBlock = {};
  for (const [id, a] of Object.entries(annotations)) {
    (byBlock[a.block_id] ||= []).push([id, a]);
  }

  for (const [blockId, items] of Object.entries(byBlock)) {
    // Insert after the <section.block> that wraps the block.
    const section = document.querySelector(`section.block[data-block-id="${cssEsc(blockId)}"]`);
    if (!section) continue;
    const wrap = document.createElement("div");
    wrap.className = "inline-comments";
    wrap.dataset.forBlock = blockId;
    for (const [id, a] of items) wrap.appendChild(buildCard(id, a));
    section.insertAdjacentElement("afterend", wrap);
  }

  // EDITING lock: any open comment card means one editor is active.
  document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
  // Same tick, same reason as the submit path above: the dock's disabled
  // state reads `is-editing`, so it has to be repainted the moment the
  // class moves rather than on the next poll.
  window.AnnotateSubunits?.renderDock();
}

function focusComment(id) {
  const card = document.querySelector(`.comment-card[data-id="${id}"]`);
  if (!card) return;
  const ta = card.querySelector("textarea");
  if (ta) ta.focus({ preventScroll: true });
}

// One editor at a time is the rule, and it stands. Refusing in SILENCE is
// what had to go: a comment icon that does nothing when clicked is
// indistinguishable from a broken one — which is exactly what it was
// mistaken for, and reported as, when renderComments was deleting these
// drafts at the moment they were created. The open card is usually the
// reason, and it is usually somewhere off screen.
function revealOpenDraft() {
  const openId = Object.keys(annotations)[0];
  if (!openId) return;
  const card = document.querySelector(`.comment-card[data-id="${cssEsc(openId)}"]`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  // Restarted rather than merely added: a second refusal while the class is
  // still on the element would re-add a class it already has and animate
  // nothing, so the one signal the user gets would fire only the first time.
  card.classList.remove("is-calling");
  void card.offsetWidth;
  card.classList.add("is-calling");
  setTimeout(() => card.classList.remove("is-calling"), 1200);
  const ta = card.querySelector("textarea");
  if (ta) ta.focus({ preventScroll: true });
}
